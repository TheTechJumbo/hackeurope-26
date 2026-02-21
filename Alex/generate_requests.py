import os
import re
import json
import uuid
import random
import sys
from datetime import datetime, timezone
from pathlib import Path
from openai import OpenAI


BASE_DIR = os.path.dirname(__file__)
PROMPTS_PATH = os.path.join(BASE_DIR, "meta_prompts.json")
SAMPLE_DIR = os.path.join(BASE_DIR, "sample_requests")


def load_prompts(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


REPLACEMENTS = {
    "industry": ["healthcare", "fintech", "e-commerce", "manufacturing", "education"],
    "broad_topic": ["climate adaptation", "AI fairness", "market entry", "quantum algorithms", "supply-chain resilience"],
    "technical_domain": ["backend microservices", "ML pipeline", "mobile app", "infrastructure as code", "edge computing"],
    "business_type": ["SaaS startup", "retail chain", "managed hosting provider", "telecom operator"],
    "regulated_domain": ["pharmaceutical clinical trials", "financial audits", "aircraft maintenance", "health data privacy"],
    "physical_system": ["warehouse conveyor network", "wind-turbine farm", "autonomous delivery fleet", "HVAC building system"]
}


def _load_key_from_dotenv(path: Path):
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


def fill_placeholders(template):
    fields = re.findall(r"\{([^}]+)\}", template)
    chosen = {}
    for f in fields:
        if f not in chosen:
            pool = REPLACEMENTS.get(f, [f])
            chosen[f] = random.choice(pool)
    result = template
    for k, v in chosen.items():
        result = result.replace("{" + k + "}", v)
    return result, chosen


def call_llm(prompt_text, api_key):
    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key
    )
    
    try:
        completion = client.chat.completions.create(
            model="deepseek-ai/deepseek-v3.2",
            messages=[{"role": "user", "content": prompt_text}],
            temperature=1,
            top_p=0.95,
            max_tokens=8192,
            extra_body={"chat_template_kwargs": {"thinking": True}},
            stream=False,
            timeout=300
        )
        return completion.model_dump()
    except Exception as e:
        return {"error": str(e)}


def save_request(request_obj, folder=SAMPLE_DIR):
    os.makedirs(folder, exist_ok=True)
    fname = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex}.json"
    path = os.path.join(folder, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(request_obj, f, ensure_ascii=False, indent=2)
    return path


def main(num_iterations=1):
    if not os.path.exists(PROMPTS_PATH):
        print(f"Prompts file not found at {PROMPTS_PATH}")
        return

    prompts = load_prompts(PROMPTS_PATH)
    keys = list(prompts.keys())

    api_key = os.getenv("NVAPI_KEY") or os.getenv("NVIDIA_API_KEY")
    if not api_key:
        # try root .env (parent directories)
        current = Path(__file__).resolve().parent
        for p in [current] + list(current.parents):
            env_path = p / ".env"
            api_key = _load_key_from_dotenv(env_path)
            if api_key:
                break

    if not api_key:
        print("Please set NVAPI_KEY or NVIDIA_API_KEY environment variable, or add it to a .env file")
        return

    saved_count = 0
    failed_count = 0

    for i in range(num_iterations):
        try:
            # equal-weight random selection for now
            chosen_key = random.choice(keys)
            template = prompts[chosen_key]

            filled_prompt, used_replacements = fill_placeholders(template)

            print(f"[{i+1}/{num_iterations}] Calling DeepSeek API...", end=" ", flush=True)

            response = call_llm(filled_prompt, api_key)

            request_record = {
                "id": uuid.uuid4().hex,
                "timestamp": datetime.now(timezone.utc).isoformat() + "Z",
                "template_key": chosen_key,
                "template": template,
                "filled_prompt": filled_prompt,
                "placeholders": used_replacements,
                "response": response,
                "children": []  # allows nested/tree-style requests
            }

            saved_path = save_request(request_record)
            saved_count += 1
            print(f"Saved: {os.path.basename(saved_path)}")

        except Exception as e:
            failed_count += 1
            print(f"Error: {str(e)[:100]}")

    if num_iterations > 1:
        print(f"\nBatch complete: {saved_count} saved, {failed_count} failed")


if __name__ == "__main__":
    num_iterations = 10
    if len(sys.argv) > 1:
        try:
            num_iterations = int(sys.argv[1])
        except ValueError:
            print(f"Invalid argument. Usage: python generate_requests.py [number]")
            sys.exit(1)
    
    main(num_iterations)
