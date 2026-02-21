import os
import re
import json
import uuid
import random
import requests
from datetime import datetime


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


def build_payload(prompt_text):
    return {
        "model": "moonshotai/kimi-k2.5",
        "messages": [{"role": "user", "content": prompt_text}],
        "max_tokens": 16384,
        "temperature": 1.00,
        "top_p": 1.00,
        "stream": False,
        "chat_template_kwargs": {"thinking": True},
    }


def call_llm(payload, api_key, invoke_url="https://integrate.api.nvidia.com/v1/chat/completions"):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json"
    }
    resp = requests.post(invoke_url, headers=headers, json=payload, timeout=120)
    try:
        return resp.json()
    except Exception:
        return {"text": resp.text}


def save_request(request_obj, folder=SAMPLE_DIR):
    os.makedirs(folder, exist_ok=True)
    fname = f"{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}_{uuid.uuid4().hex}.json"
    path = os.path.join(folder, fname)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(request_obj, f, ensure_ascii=False, indent=2)
    return path


def main():
    if not os.path.exists(PROMPTS_PATH):
        print(f"Prompts file not found at {PROMPTS_PATH}")
        return

    prompts = load_prompts(PROMPTS_PATH)
    keys = list(prompts.keys())
    # equal-weight random selection for now
    chosen_key = random.choice(keys)
    template = prompts[chosen_key]

    filled_prompt, used_replacements = fill_placeholders(template)

    payload = build_payload(filled_prompt)

    api_key = os.environ.get("NVAPI_KEY")
    if not api_key:
        print("Environment variable NVAPI_KEY not set. Set it to your NVIDIA API key and rerun.")
        return

    response = call_llm(payload, api_key)

    request_record = {
        "id": uuid.uuid4().hex,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "template_key": chosen_key,
        "template": template,
        "filled_prompt": filled_prompt,
        "placeholders": used_replacements,
        "request_payload": payload,
        "response": response,
        "children": []  # allows nested/tree-style requests
    }

    saved_path = save_request(request_record)
    print(f"Saved request to {saved_path}")


if __name__ == "__main__":
    main()
