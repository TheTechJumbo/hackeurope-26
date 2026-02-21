import os
import re
import json
import uuid
import requests
import sys
from datetime import datetime
from pathlib import Path


INVOKE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
MODEL = "moonshotai/kimi-k2.5"
PROMPT = (
    "Generate one randomly selected professional, commercial, scientific, industrial, or societal domain "
    "that could plausibly benefit from workflow automation or AI agents, maximizing diversity and avoiding "
    "overly broad categories (e.g., avoid “business” or “technology”); output exactly in the format `domain: X` "
    "where X is 1–5 specific words, and provide no additional text."
)

BASE_DIR = os.path.dirname(__file__)
DOMAINS_PATH = os.path.join(BASE_DIR, "sample_domains.json")


def ensure_domains_file(path):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)


def build_payload(prompt_text: str):
    return {
        "model": MODEL,
        "messages": [{"role": "user", "content": prompt_text}],
        "max_tokens": 256,
        "temperature": 1.0,
        "top_p": 1.0,
        "stream": False,
    }


def call_llm(payload, api_key):
    headers = {"Authorization": f"Bearer {api_key}", "Accept": "application/json"}
    resp = requests.post(INVOKE_URL, headers=headers, json=payload, timeout=120)
    try:
        return resp.json()
    except Exception:
        return {"raw_text": resp.text}


def extract_domain(text: str):
    if not text:
        return None
    # remove markdown/code fences
    text = re.sub(r"```[\s\S]*?```", "", text)
    # find a line that starts with 'domain:' (case-insensitive)
    m = re.search(r"(?m)^\s*domain:\s*(.+)$", text, flags=re.IGNORECASE)
    if not m:
        # fallback: look anywhere for 'domain:' then the following words
        m = re.search(r"domain:\s*([A-Za-z0-9 &\-,'()\.]+)", text, flags=re.IGNORECASE)
    if not m:
        return None
    val = m.group(1).strip()
    # remove wrapping quotes and trailing punctuation
    val = val.strip('"').strip("'")
    val = val.rstrip('.,;:')
    # keep only first line and collapse whitespace
    val = val.splitlines()[0].strip()
    val = re.sub(r"\s+", " ", val)
    # validate 1-5 words (allow hyphens and ampersands)
    words = [w for w in re.findall(r"[A-Za-z0-9&\-']+", val)]
    if 1 <= len(words) <= 5:
        return " ".join(words)
    return None


def get_domain_with_retries(build_payload_fn, api_key, attempts=3):
    for attempt in range(attempts):
        payload = build_payload_fn(PROMPT)
        resp = call_llm(payload, api_key)
        text = parse_response_json(resp)
        domain = extract_domain(text)
        if domain:
            return domain, text, resp
    # final fallback: try to construct a short candidate from full text
    text = parse_response_json(resp)
    tokens = re.findall(r"[A-Za-z0-9&\-']+", text)
    candidate = " ".join(tokens[:5]) if tokens else "unknown"
    return candidate, text, resp


def append_domain_record(domain: str, raw_response, path=DOMAINS_PATH):
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    record = {
        "id": uuid.uuid4().hex,
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "domain": domain,
        "raw_response": raw_response,
    }
    data.append(record)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return record


def parse_response_json(resp_json):
    # Typical shapes: {'choices':[{'message':{'content':'...'}}]} or {'choices':[{'text':'...'}]}
    text = None
    if isinstance(resp_json, dict):
        if "choices" in resp_json and isinstance(resp_json["choices"], list) and resp_json["choices"]:
            c = resp_json["choices"][0]
            if isinstance(c, dict):
                if "message" in c and isinstance(c["message"], dict) and "content" in c["message"]:
                    text = c["message"]["content"]
                elif "text" in c:
                    text = c["text"]
        # fallback locations
        if not text:
            for k in ("text", "content", "raw_text"):
                if k in resp_json and isinstance(resp_json[k], str):
                    text = resp_json[k]
                    break
    elif isinstance(resp_json, str):
        text = resp_json
    return text or ""


def main():
    # load .env if present to pick up NVIDIA_API_KEY
    def load_dotenv_file(path: str):
        p = Path(path)
        if not p.exists():
            return
        with p.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k not in os.environ:
                    os.environ[k] = v

    load_dotenv_file(os.path.join(BASE_DIR, ".env"))

    # count via arg or default 1
    count = 1
    if len(sys.argv) > 1:
        try:
            count = int(sys.argv[1])
            if count < 1:
                raise ValueError
        except Exception:
            print("Usage: python sample_kimik2.5_generate_domains.py [count]")
            return

    # prefer explicit NVAPI_KEY, fall back to NVIDIA_API_KEY from .env
    api_key = os.environ.get("NVAPI_KEY") or os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        print("Set NVAPI_KEY or NVIDIA_API_KEY environment variable (or add to .env) and retry.")
        return

    ensure_domains_file(DOMAINS_PATH)

    for i in range(count):
        payload = build_payload(PROMPT)
        resp = call_llm(payload, api_key)
        text = parse_response_json(resp)
        domain = extract_domain(text)
        if not domain:
            # if parsing failed, try to extract first plausible phrase (1-5 words) from full text
            tokens = re.findall(r"[A-Za-z0-9 &\-]+", text)
            candidate = tokens[0] if tokens else "unknown"
            candidate = " ".join(candidate.split()[:5])
            domain = candidate or "unknown"

        record = append_domain_record(domain, text)
        print(f"[{i+1}/{count}] Added domain: {domain} (id={record['id']})")


if __name__ == "__main__":
    main()
