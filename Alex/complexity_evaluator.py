import os
import re
import json
import glob
import time
from pathlib import Path
from openai import OpenAI

from task_id_manager import generate_base_id


MODEL = "qwen/qwen3-235b-a22b"

BASE_DIR = os.path.dirname(__file__)
SAMPLE_DIR = os.path.join(BASE_DIR, "sample_requests")
CLEANED_DIR = os.path.join(BASE_DIR, "cleaned_requests")
LOGS_DIR = os.path.join(BASE_DIR, "logs")
EVAL_ENGINE_PATH = os.path.join(BASE_DIR, "evaluation_engine.json")

EVAL_GEN = 1  # Increment this when evaluation criteria changes
API_RATE_LIMIT_SECONDS = 5  # Limit API calls to 1 per 5 seconds
_last_api_call_time = 0


def _load_evaluation_engine(path: str, eval_gen: int) -> str:
    """
    Load the evaluation prompt template from evaluation_engine.json.
    
    Args:
        path: Path to evaluation_engine.json
        eval_gen: The evaluation generation number to load
    
    Returns:
        str: The prompt template for the given generation
    
    Raises:
        FileNotFoundError: If evaluation_engine.json is not found
        KeyError: If the evaluation generation is not found
    """
    if not os.path.exists(path):
        raise FileNotFoundError(f"evaluation_engine.json not found at {path}")
    
    with open(path, "r", encoding="utf-8") as f:
        engine_data = json.load(f)
    
    eval_key = str(eval_gen)
    if eval_key not in engine_data.get("evaluations", {}):
        raise KeyError(f"Evaluation generation {eval_gen} not found in evaluation_engine.json")
    
    return engine_data["evaluations"][eval_key]["prompt_template"]


# Load the complexity prompt template from evaluation_engine.json
try:
    COMPLEXITY_PROMPT_TEMPLATE = _load_evaluation_engine(EVAL_ENGINE_PATH, EVAL_GEN)
except (FileNotFoundError, KeyError) as e:
    print(f"Warning: Could not load evaluation engine: {e}")
    print("Using fallback prompt template")
    COMPLEXITY_PROMPT_TEMPLATE = """EVALUATION CRITERIA (Generation {EVAL_GEN}):
You are a task complexity evaluation engine.

First, internally define a **0–100 Task Execution Complexity Scale** for how difficult a prompt would be to execute via code, automation, or agentic workflows, where complexity reflects required planning depth, number of steps, branching logic, tool integrations, state management, uncertainty handling, data dependencies, and failure recovery requirements.

The scale must follow these anchors:

* **0–10**: Single-step, no external tools, no state.
* **11–30**: Few sequential steps, minimal logic, limited data handling.
* **31–50**: Multi-step workflow with light branching and basic tool use.
* **51–70**: Coordinated multi-system execution with moderate decision logic and validation.
* **71–90**: Complex orchestration, dynamic decision-making, multiple integrations, error handling, and state tracking.
* **91–100**: High-autonomy, adaptive, multi-phase execution requiring long-horizon planning, uncertainty resolution, and recovery mechanisms.

Then, given the following input prompt, assign a **complexity score from 0–100** strictly based on execution requirements (not topic difficulty).

Evaluation requirements:

* Consider number of discrete executable steps.
* Consider branching/conditional logic.
* Consider required integrations or external systems.
* Consider persistence of state across steps.
* Consider need for validation or error handling.
* Ignore writing difficulty or domain knowledge difficulty unless it impacts execution structure.

Output strictly in the following format:

Complexity Score: <integer 0–100>
Justification: <concise 3–6 sentence explanation referencing the scale>

Prompt to evaluate:
{INPUT_PROMPT}"""


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


def evaluate_complexity(task_prompt: str, client: OpenAI = None) -> dict:
    """
    Evaluate the execution complexity of a given task prompt.
    
    Args:
        task_prompt: The task/prompt to evaluate for complexity.
        client: Optional OpenAI client. If not provided, one will be created.
    
    Returns:
        dict with keys:
            - score: int (0-100 complexity score)
            - justification: str (explanation of the score)
            - raw_response: str (full LLM response)
            - eval_gen: int (evaluation generation/criteria version)
    """
    global _last_api_call_time
    
    if client is None:
        client = _get_client()
    
    # Rate limiting: ensure at least API_RATE_LIMIT_SECONDS between calls
    elapsed = time.time() - _last_api_call_time
    if elapsed < API_RATE_LIMIT_SECONDS:
        time.sleep(API_RATE_LIMIT_SECONDS - elapsed)
    
    full_prompt = COMPLEXITY_PROMPT_TEMPLATE.replace("{INPUT_PROMPT}", task_prompt).replace("{EVAL_GEN}", str(EVAL_GEN))
    
    try:
        _last_api_call_time = time.time()
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": full_prompt}],
            temperature=0.3,  # Lower temperature for more consistent scoring
            top_p=0.9,
            max_tokens=500,
            stream=False,
        )
        
        raw_response = completion.choices[0].message.content if completion.choices else ""
        
        # Parse the response
        result = _parse_complexity_response(raw_response)
        result["raw_response"] = raw_response
        result["eval_gen"] = EVAL_GEN
        return result
        
    except Exception as e:
        return {
            "score": None,
            "justification": None,
            "raw_response": None,
            "eval_gen": EVAL_GEN,
            "error": str(e)
        }


def _parse_complexity_response(response_text: str) -> dict:
    """
    Parse the LLM response to extract complexity score and justification.
    
    Args:
        response_text: Raw LLM response text.
    
    Returns:
        dict with 'score' (int or None) and 'justification' (str or None)
    """
    if not response_text:
        return {"score": None, "justification": None}
    
    # Remove markdown code fences if present
    text = re.sub(r"```[\s\S]*?```", "", response_text)
    
    # Extract complexity score
    score = None
    score_match = re.search(r"Complexity\s*Score:\s*(\d+)", text, re.IGNORECASE)
    if score_match:
        score = int(score_match.group(1))
        # Clamp to valid range
        score = max(0, min(100, score))
    
    # Extract justification
    justification = None
    justification_match = re.search(r"Justification:\s*(.+)", text, re.IGNORECASE | re.DOTALL)
    if justification_match:
        justification = justification_match.group(1).strip()
        # Clean up: take until end or next section marker
        justification = re.split(r"\n\s*\n|\n[A-Z]", justification)[0].strip()
    
    return {"score": score, "justification": justification}


def get_complexity_score(task_prompt: str, client: OpenAI = None) -> int:
    """
    Simple wrapper that returns just the complexity score.
    
    Args:
        task_prompt: The task/prompt to evaluate.
        client: Optional OpenAI client.
    
    Returns:
        int: Complexity score (0-100), or -1 if evaluation failed.
    """
    result = evaluate_complexity(task_prompt, client)
    return result.get("score") if result.get("score") is not None else -1


def extract_response_content(response_obj):
    """
    Extract the actual content/output from an LLM response object.
    Handles OpenAI-like response format.
    
    Args:
        response_obj: Response dict from LLM
    
    Returns:
        str: The extracted content, or empty string if not found
    """
    if not response_obj or not isinstance(response_obj, dict):
        return ""
    
    # Standard OpenAI-like response format
    if "choices" in response_obj and isinstance(response_obj["choices"], list):
        if len(response_obj["choices"]) > 0:
            choice = response_obj["choices"][0]
            if "message" in choice and isinstance(choice["message"], dict):
                return choice["message"].get("content", "")
    
    return ""


def update_request_with_complexity(request_file_path, complexity_result, output_dir=CLEANED_DIR, logs_dir=LOGS_DIR):
    """
    Update the request JSON file with complexity evaluation data.
    Saves cleaned version to cleaned_requests folder and full log to logs folder.
    Maintains hierarchical structure for future recursive task breakdown.
    Assigns a unique hierarchical ID to the request.
    
    Args:
        request_file_path: Path to the request JSON file in sample_requests
        complexity_result: Dict with 'score', 'justification', and 'raw_response'
        output_dir: Directory to save cleaned request to
        logs_dir: Directory to save full request logs to
    """
    try:
        with open(request_file_path, "r", encoding="utf-8") as f:
            request_data = json.load(f)
        
        # Extract input (the actual task/prompt)
        input_text = request_data.get("response", {}).get("choices", [{}])[0].get("message", {}).get("content", "")
        if not input_text:
            input_text = request_data.get("filled_prompt", "")
        
        # Generate unique task ID for this root request
        task_id = generate_base_id()
        
        # Save full request log
        os.makedirs(logs_dir, exist_ok=True)
        log_filename = f"log_{os.path.basename(request_file_path)}"
        log_path = os.path.join(logs_dir, log_filename)
        
        full_log = {
            "task_id": task_id,
            "request_id": request_data.get("id"),
            "timestamp": request_data.get("timestamp"),
            "original_request": request_data,
            "complexity_evaluation": {
                "score": complexity_result.get("score"),
                "justification": complexity_result.get("justification"),
                "raw_response": complexity_result.get("raw_response"),
                "eval_gen": complexity_result.get("eval_gen"),
                "error": complexity_result.get("error")
            }
        }
        
        with open(log_path, "w", encoding="utf-8") as f:
            json.dump(full_log, f, ensure_ascii=False, indent=2)
        
        # Create cleaned request (minimal structure)
        cleaned_request = {
            "task_id": task_id,
            "input": input_text,
            "complexity_score": complexity_result.get("score"),
            "eval_gen": complexity_result.get("eval_gen", 1),
            "subtasks": []
        }
        
        # Write to cleaned_requests folder
        os.makedirs(output_dir, exist_ok=True)
        output_path = os.path.join(output_dir, os.path.basename(request_file_path))
        
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_request, f, ensure_ascii=False, indent=2)
        
        return True, task_id
    except Exception as e:
        print(f"Error updating {request_file_path}: {e}")
        return False, None


def evaluate_sample_requests(sample_dir=SAMPLE_DIR, output_dir=CLEANED_DIR, client=None):
    """
    Evaluate all sample request files in the sample_requests directory.
    Reads the response content, evaluates complexity, and writes results to cleaned_requests folder.
    
    Args:
        sample_dir: Path to the sample_requests directory
        output_dir: Path to save cleaned requests with complexity evaluation
        client: Optional OpenAI client
    
    Returns:
        list: Tuples of (file_path, success, complexity_score)
    """
    if not os.path.exists(sample_dir):
        print(f"Sample directory not found: {sample_dir}")
        return []
    
    json_files = glob.glob(os.path.join(sample_dir, "*.json"))
    if not json_files:
        print(f"No JSON files found in {sample_dir}")
        return []
    
    results = []
    
    for request_file in sorted(json_files):
        try:
            with open(request_file, "r", encoding="utf-8") as f:
                request_data = json.load(f)
            
            # Check if already processed in cleaned folder
            cleaned_file = os.path.join(output_dir, os.path.basename(request_file))
            if os.path.exists(cleaned_file):
                print(f"Skipping {os.path.basename(request_file)} (already evaluated)")
                results.append((request_file, False, None, "already_evaluated"))
                continue
            
            # Extract the response content to evaluate
            response_obj = request_data.get("response", {})
            response_content = extract_response_content(response_obj)
            
            if not response_content:
                print(f"Skipping {os.path.basename(request_file)} (no response content)")
                results.append((request_file, False, None, "no_response_content"))
                continue
            
            # Evaluate complexity
            print(f"Evaluating {os.path.basename(request_file)}...")
            complexity_result = evaluate_complexity(response_content, client)
            
            # Update the request file with results (saves to cleaned_requests and logs)
            success, task_id = update_request_with_complexity(request_file, complexity_result, output_dir, LOGS_DIR)
            if success:
                score = complexity_result.get("score")
                print(f"  [OK] Complexity Score: {score}, Task ID: {task_id}")
                results.append((request_file, True, score, task_id))
            else:
                results.append((request_file, False, None, None))
        
        except Exception as e:
            print(f"Error processing {os.path.basename(request_file)}: {e}")
            results.append((request_file, False, None, str(e)))
    
    return results


# CLI usage
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Usage: python complexity_evaluator.py [<task_prompt> | --batch]")
        print("\nExamples:")
        print("  python complexity_evaluator.py 'Send an email to the user'")
        print("  python complexity_evaluator.py --batch    # Evaluate all sample requests")
        sys.exit(1)
    
    if sys.argv[1] == "--batch":
        print(f"Evaluating all sample requests in {SAMPLE_DIR}...\n")
        results = evaluate_sample_requests()
        
        success_count = sum(1 for _, success, _, _ in results if success)
        total_count = len(results)
        
        print(f"\n{'='*60}")
        print(f"Results: {success_count}/{total_count} requests evaluated successfully")
        print(f"{'='*60}")
        
        if success_count > 0:
            scores = [score for _, success, score, _ in results if success and score is not None]
            if scores:
                avg_score = sum(scores) / len(scores)
                print(f"Average complexity score: {avg_score:.1f}")
    else:
        task = " ".join(sys.argv[1:])
        print(f"Evaluating complexity for: {task}\n")
        
        result = evaluate_complexity(task)
        
        if result.get("error"):
            print(f"Error: {result['error']}")
            sys.exit(1)
        
        print(f"Complexity Score: {result['score']}")
        print(f"Justification: {result['justification']}")
