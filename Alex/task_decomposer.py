import os
import re
import json
import glob
import uuid
import time
from pathlib import Path
from datetime import datetime, timezone
from openai import OpenAI

from complexity_evaluator import (
    evaluate_sample_requests,
    evaluate_complexity,
    extract_response_content,
    SAMPLE_DIR,
    CLEANED_DIR,
    LOGS_DIR,
    EVAL_GEN
)
from task_id_manager import create_subtask_id


MODEL = "qwen/qwen3-235b-a22b"

API_RATE_LIMIT_SECONDS = 5  # Limit API calls to 1 per 5 seconds
_last_api_call_time = 0

TASK_DECOMPOSITION_PROMPT_TEMPLATE = """You are a task decomposition engine designed to break down complex tasks into actionable subtasks.

Given a complex task, your goal is to:
1. Identify the key sequential steps needed to complete the task
2. Break down each major step into atomic, executable subtasks
3. Consider dependencies between subtasks
4. Ensure subtasks are specific and actionable

Respond ONLY with a valid JSON object (no markdown, no extra text) with the following structure:
{{
  "subtasks": [
    {{
      "id": "<unique_id>",
      "title": "<concise subtask title>",
      "description": "<detailed description of what this subtask entails>",
      "dependencies": [<list of other subtask ids this depends on, empty list if none>],
      "estimated_complexity": <0-100 complexity score estimate>
    }},
    ...
  ]
}}

Task to decompose:
{INPUT_TASK}"""


def _load_key_from_dotenv(path: Path):
    """Load API key from .env file."""
    if not path.exists():
        return None
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip('"').strip("'")
        if k in ("NVAPI_KEY", "NVIDIA_API_KEY"):
            return v
    return None


def _get_api_key():
    """Get NVIDIA API key from environment or .env file."""
    api_key = os.getenv("NVAPI_KEY") or os.getenv("NVIDIA_API_KEY")
    if not api_key:
        current = Path(__file__).resolve().parent
        for p in [current] + list(current.parents):
            env_path = p / ".env"
            api_key = _load_key_from_dotenv(env_path)
            if api_key:
                break
    return api_key


def _get_client():
    """Create and return OpenAI client configured for NVIDIA API."""
    api_key = _get_api_key()
    if not api_key:
        raise ValueError("Please set NVAPI_KEY or NVIDIA_API_KEY environment variable, or add it to a .env file")
    
    return OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key
    )


def decompose_task(task_description: str, client: OpenAI = None) -> dict:
    """
    Decompose a complex task into subtasks using LLM.
    
    Args:
        task_description: The task to decompose
        client: Optional OpenAI client
    
    Returns:
        dict with 'subtasks' list and 'raw_response' for debugging
    """
    global _last_api_call_time
    
    if client is None:
        client = _get_client()
    
    # Rate limiting: ensure at least API_RATE_LIMIT_SECONDS between calls
    elapsed = time.time() - _last_api_call_time
    if elapsed < API_RATE_LIMIT_SECONDS:
        time.sleep(API_RATE_LIMIT_SECONDS - elapsed)
    
    full_prompt = TASK_DECOMPOSITION_PROMPT_TEMPLATE.replace("{INPUT_TASK}", task_description)
    
    try:
        _last_api_call_time = time.time()
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": full_prompt}],
            temperature=0.3,
            top_p=0.9,
            max_tokens=2000,
            stream=False,
        )
        
        raw_response = completion.choices[0].message.content if completion.choices else ""
        
        # Parse JSON response
        subtasks = _parse_decomposition_response(raw_response)
        
        return {
            "subtasks": subtasks,
            "raw_response": raw_response,
            "error": None
        }
        
    except Exception as e:
        return {
            "subtasks": [],
            "raw_response": None,
            "error": str(e)
        }


def _parse_decomposition_response(response_text: str) -> list:
    """
    Parse LLM response to extract subtasks JSON.
    
    Args:
        response_text: Raw LLM response
    
    Returns:
        list of subtask dicts, or empty list if parsing fails
    """
    if not response_text:
        return []
    
    # Try to extract JSON from the response
    # First try direct parsing
    try:
        data = json.loads(response_text)
        if isinstance(data, dict) and "subtasks" in data:
            return data["subtasks"]
    except json.JSONDecodeError:
        pass
    
    # Try to extract JSON from markdown code blocks
    try:
        json_match = re.search(r"```(?:json)?\s*(\{[\s\S]*?\})\s*```", response_text, re.DOTALL)
        if json_match:
            data = json.loads(json_match.group(1))
            if isinstance(data, dict) and "subtasks" in data:
                return data["subtasks"]
    except (json.JSONDecodeError, AttributeError):
        pass
    
    # Try to find any JSON object in the text (greedy search for closing brace)
    try:
        start = response_text.find('{')
        if start != -1:
            # Search for closing brace more carefully
            brace_count = 0
            end = -1
            for i in range(start, len(response_text)):
                if response_text[i] == '{':
                    brace_count += 1
                elif response_text[i] == '}':
                    brace_count -= 1
                    if brace_count == 0:
                        end = i + 1
                        break
            
            if end > start:
                json_str = response_text[start:end]
                data = json.loads(json_str)
                if isinstance(data, dict) and "subtasks" in data:
                    return data["subtasks"]
    except (json.JSONDecodeError, ValueError):
        pass
    
    return []


def update_request_with_subtasks(request_file_path, subtasks, decomposition_result, logs_dir=LOGS_DIR):
    """
    Update request file with decomposed subtasks.
    Supports hierarchical/nested subtasks for recursive decomposition.
    Saves full log to logs folder and cleaned version to cleaned_requests.
    Assigns hierarchical task IDs to all subtasks.
    
    Args:
        request_file_path: Path to the request JSON in cleaned_requests
        subtasks: List of subtask dicts from decomposition
        decomposition_result: Full decomposition result for metadata
        logs_dir: Directory to save full decomposition logs
    
    Returns:
        bool: True if successful
    """
    try:
        with open(request_file_path, "r", encoding="utf-8") as f:
            request_data = json.load(f)
        
        # Get parent task ID for hierarchical ID creation
        parent_task_id = request_data.get("task_id", "")
        
        # Build subtask records with minimal structure and hierarchical IDs
        processed_subtasks = []
        for index, subtask in enumerate(subtasks):
            # Create hierarchical task ID for this subtask
            subtask_id = create_subtask_id(parent_task_id, index)
            
            subtask_record = {
                "task_id": subtask_id,
                "input": subtask.get("description", ""),
                "complexity_score": subtask.get("estimated_complexity"),
                "eval_gen": EVAL_GEN,
                "subtasks": []
            }
            processed_subtasks.append(subtask_record)
        
        # Save full decomposition log
        os.makedirs(logs_dir, exist_ok=True)
        log_filename = f"decomp_log_{os.path.basename(request_file_path)}"
        log_path = os.path.join(logs_dir, log_filename)
        
        full_log = {
            "parent_task_id": parent_task_id,
            "request_file": request_file_path,
            "decomposed_at": datetime.now(timezone.utc).isoformat() + "Z",
            "subtask_count": len(processed_subtasks),
            "subtask_ids": [s.get("task_id") for s in processed_subtasks],
            "subtasks": subtasks,
            "raw_response": decomposition_result.get("raw_response"),
            "error": decomposition_result.get("error")
        }
        
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(full_log, f, ensure_ascii=False, indent=2)
        
        # Update cleaned request
        request_data["subtasks"] = processed_subtasks
        
        # Write back to cleaned_requests
        with open(request_file_path, "w", encoding="utf-8") as f:
            json.dump(request_data, f, ensure_ascii=False, indent=2)
        
        return True
    except Exception as e:
        print(f"Error updating {request_file_path} with subtasks: {e}")
        return False


def process_sample_requests(complexity_threshold=50, sample_dir=SAMPLE_DIR, output_dir=CLEANED_DIR):
    """
    Process all sample requests:
    1. Evaluate complexity (if not already done)
    2. For tasks above threshold, decompose into subtasks
    3. Saves all results to cleaned_requests folder
    
    Args:
        complexity_threshold: Complexity score above which to decompose (0-100)
        sample_dir: Path to sample_requests directory
        output_dir: Path to cleaned_requests directory (for output)
    
    Returns:
        dict with statistics about processing
    """
    if not os.path.exists(sample_dir):
        print(f"Sample directory not found: {sample_dir}")
        return {}
    
    # Step 1: Evaluate all requests for complexity
    print(f"Step 1: Evaluating complexity for all requests...\n")
    eval_results = evaluate_sample_requests(sample_dir, output_dir)
    
    print(f"\n{'='*60}")
    print(f"Step 2: Decomposing tasks with complexity > {complexity_threshold}...\n")
    
    json_files = glob.glob(os.path.join(output_dir, "*.json"))
    if not json_files:
        print(f"No evaluated requests found in {output_dir}")
        return {}
    
    decomposition_count = 0
    skipped_count = 0
    error_count = 0
    
    client = _get_client()
    
    for request_file in sorted(json_files):
        try:
            with open(request_file, "r", encoding="utf-8") as f:
                request_data = json.load(f)
            
            # Check if already decomposed
            if "decomposition" in request_data:
                print(f"Skipping {os.path.basename(request_file)} (already decomposed)")
                skipped_count += 1
                continue
            
            # Check complexity score (from new cleaned structure)
            complexity_score = request_data.get("complexity_score")
            
            if complexity_score is None:
                print(f"Skipping {os.path.basename(request_file)} (no complexity score)")
                skipped_count += 1
                continue
            
            if complexity_score <= complexity_threshold:
                print(f"Skipping {os.path.basename(request_file)} (complexity {complexity_score} <= {complexity_threshold})")
                skipped_count += 1
                continue
            
            # Decompose the task (from cleaned request structure)
            task_text = request_data.get("input", "")
            
            if not task_text:
                print(f"  [ERROR] No input text to decompose")
                error_count += 1
                continue
            
            print(f"Decomposing {os.path.basename(request_file)} (complexity: {complexity_score})...")
            decomposition_result = decompose_task(task_text, client)
            
            if decomposition_result.get("error"):
                print(f"  [ERROR] {decomposition_result['error']}")
                error_count += 1
                continue
            
            subtasks = decomposition_result.get("subtasks", [])
            if not subtasks:
                print(f"  [WARN] No subtasks generated from decomposition")
                error_count += 1
                continue
            
            # Update request file (in cleaned_requests)
            try:
                if update_request_with_subtasks(request_file, subtasks, decomposition_result, LOGS_DIR):
                    print(f"  [OK] Decomposed into {len(subtasks)} subtasks")
                    decomposition_count += 1
                else:
                    print(f"  [ERROR] Failed to update request file")
                    error_count += 1
            except Exception as e:
                print(f"  [ERROR] {str(e)}")
                error_count += 1
        
        except Exception as e:
            print(f"Error processing {os.path.basename(request_file)}: {e}")
            error_count += 1
    
    print(f"\n{'='*60}")
    print(f"Results:")
    print(f"  Evaluated: {len(eval_results)}")
    print(f"  Decomposed: {decomposition_count}")
    print(f"  Skipped: {skipped_count}")
    print(f"  Errors: {error_count}")
    print(f"  Output directory: {output_dir}")
    print(f"{'='*60}")
    
    return {
        "evaluated": len(eval_results),
        "decomposed": decomposition_count,
        "skipped": skipped_count,
        "errors": error_count
    }


# CLI usage
if __name__ == "__main__":
    import sys
    
    threshold = 50
    
    if len(sys.argv) > 1:
        try:
            threshold = int(sys.argv[1])
        except ValueError:
            print(f"Invalid threshold: {sys.argv[1]}")
            print("Usage: python task_decomposer.py [complexity_threshold (0-100)]")
            print(f"\nDefault threshold: {threshold}")
            sys.exit(1)
    
    print(f"Task Decomposition Pipeline")
    print(f"Complexity threshold: {threshold}\n")
    
    process_sample_requests(complexity_threshold=threshold)
