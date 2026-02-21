import os
import sys
import json
import uuid
import random
import time
from datetime import datetime, timezone
from pathlib import Path
from generate_requests import load_prompts, build_payload, call_llm, save_request, fill_placeholders, _load_key_from_dotenv, PROMPTS_PATH, SAMPLE_DIR, REPLACEMENTS


def run_batch_generation(num_iterations=100, verbose=True):
    """Generate multiple sample requests with randomized fillers."""
    
    print(f"Starting batch generation of {num_iterations} requests...", flush=True)
    sys.stdout.flush()
    
    if not os.path.exists(PROMPTS_PATH):
        print(f"Prompts file not found at {PROMPTS_PATH}", flush=True)
        return
    
    prompts = load_prompts(PROMPTS_PATH)
    keys = list(prompts.keys())
    
    api_key = os.getenv("NVAPI_KEY") or os.getenv("NVIDIA_API_KEY")
    if not api_key:
        current = Path(__file__).resolve().parent
        for p in [current] + list(current.parents):
            env_path = p / ".env"
            api_key = _load_key_from_dotenv(env_path)
            if api_key:
                break
    
    if not api_key:
        print("Please set NVAPI_KEY or NVIDIA_API_KEY environment variable, or add it to a .env file", flush=True)
        return
    
    print(f"Found {len(keys)} prompt templates", flush=True)
    
    saved_paths = []
    failed_count = 0
    
    for i in range(num_iterations):
        try:
            chosen_key = random.choice(keys)
            template = prompts[chosen_key]
            
            filled_prompt, used_replacements = fill_placeholders(template)
            
            payload = build_payload(filled_prompt)
            
            print(f"[{i+1}/{num_iterations}] Calling API (template: {chosen_key[:30]}...)...", flush=True)
            sys.stdout.flush()
            
            response = call_llm(payload, api_key)
            
            request_record = {
                "id": uuid.uuid4().hex,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "template_key": chosen_key,
                "template": template,
                "filled_prompt": filled_prompt,
                "placeholders": used_replacements,
                "request_payload": payload,
                "response": response,
                "children": []
            }
            
            saved_path = save_request(request_record)
            saved_paths.append(saved_path)
            
            if verbose:
                print(f"[{i+1}/{num_iterations}] ✓ Saved: {os.path.basename(saved_path)}", flush=True)
                sys.stdout.flush()
        
        except Exception as e:
            failed_count += 1
            print(f"[{i+1}/{num_iterations}] ✗ Error: {str(e)[:100]}", flush=True)
    
    print(f"\n✓ Batch generation complete!", flush=True)
    print(f"  Successfully saved: {len(saved_paths)} requests", flush=True)
    if failed_count > 0:
        print(f"  Failed: {failed_count} requests", flush=True)


if __name__ == "__main__":
    num_runs = 100
    if len(sys.argv) > 1:
        try:
            num_runs = int(sys.argv[1])
        except ValueError:
            print(f"Invalid argument. Usage: python batch_generate_requests.py [number]")
            sys.exit(1)
    
    run_batch_generation(num_runs)
