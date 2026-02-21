import os
import re
import json
import uuid
import sys
from datetime import datetime
from pathlib import Path
from openai import OpenAI


MODEL = "qwen/qwen3-235b-a22b"
PROMPT = (
    "Output EXACTLY one line only:\n"
    "domain: <one random domain that benefits from AI automation, 1-5 words>\n"
    "Do not explain. Example:\n"
    "domain: predictive maintenance"
)

BASE_DIR = os.path.dirname(__file__)
DOMAINS_PATH = os.path.join(BASE_DIR, "sample_domains.json")


def ensure_domains_file(path):
    if not os.path.exists(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump([], f, ensure_ascii=False, indent=2)


def call_llm(prompt_text: str, client: OpenAI):
    try:
        completion = client.chat.completions.create(
            model=MODEL,
            messages=[{"role": "user", "content": prompt_text}],
            temperature=0.7,
            top_p=0.95,
            max_tokens=100,
            stream=False,
        )
        return completion
    except Exception as e:
        print(f"[ERROR] LLM call failed: {e}")
        return {"error": str(e)}


def extract_domain(text: str):
    if not text:
        return None
    # remove markdown/code fences
    text = re.sub(r"```[\s\S]*?```", "", text)
    
    # Try multiple patterns to find domain
    # Pattern 1: "domain: xxx" at line start
    m = re.search(r"(?m)^\s*domain:\s*(.+)$", text, flags=re.IGNORECASE)
    # Pattern 2: "domain: xxx" anywhere in text (with limited chars)
    if not m:
        m = re.search(r"domain:\s*([A-Za-z0-9 &\-,'()\.\w]+?)(?:\.|,|;|$)", text, flags=re.IGNORECASE)
    # Pattern 3: Look for lines that mention "domain:" and extract what comes after
    if not m:
        m = re.search(r"domain:\s*(.+?)[\n\.]", text, flags=re.IGNORECASE | re.DOTALL)
    
    if not m:
        return None
    
    val = m.group(1).strip()
    # remove wrapping quotes and trailing punctuation
    val = val.strip('"').strip("'").strip()
    val = val.rstrip('.,;: ')
    # keep only first line and collapse whitespace
    lines = val.splitlines()
    if lines:
        val = lines[0].strip()
    val = re.sub(r"\s+", " ", val)
    
    # validate 1-5 words (allow hyphens and ampersands)
    words = [w for w in re.findall(r"[A-Za-z0-9&\-']+", val)]
    if 1 <= len(words) <= 5:
        result = " ".join(words)
        print(f"[DEBUG] Extracted domain: {result}")
        return result
    return None


def get_domain_with_retries(client: OpenAI, attempts=3):
    for attempt in range(attempts):
        resp = call_llm(PROMPT, client)
        text = parse_response_json(resp)
        if not text:
            print(f"[DEBUG attempt {attempt+1}] Empty response: {repr(resp)}")
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
        content = f.read().strip()
        data = json.loads(content) if content else []
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


def parse_response_json(resp):
    # Handle OpenAI response object or error dict
    text = None
    if hasattr(resp, "error"):
        return ""
    if isinstance(resp, dict) and "error" in resp:
        return ""
    # OpenAI response object: choices[0].message.content or reasoning_content
    if hasattr(resp, "choices") and resp.choices:
        choice = resp.choices[0]
        if hasattr(choice, "message"):
            # Try content first, then reasoning_content as fallback
            content = getattr(choice.message, "content", None)
            reasoning = getattr(choice.message, "reasoning_content", None)
            if content:
                print(f"[DEBUG] Using content field: {content[:80] if content else 'None'}")
                text = content
            elif reasoning:
                print(f"[DEBUG] Using reasoning_content field: {reasoning[:80] if reasoning else 'None'}")
                text = reasoning
            else:
                print(f"[DEBUG] Neither content nor reasoning_content found")
    return text or ""


def _load_key_from_dotenv(path: Path):
    if not path.exists():
        return None
    for raw in path.read_text(encoding="utf-8").splitlines():
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


def main():
    # count via arg or default 1
    count = 1
    if len(sys.argv) > 1:
        try:
            count = int(sys.argv[1])
            if count < 1:
                raise ValueError
        except Exception:
            print("Usage: python generate_domains.py [count]")
            return

    # prefer explicit NVAPI_KEY, fall back to NVIDIA_API_KEY from .env
    api_key = os.environ.get("NVAPI_KEY") or os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        # try root .env (parent directories)
        current = Path(BASE_DIR).resolve()
        for p in [current] + list(current.parents):
            env_path = p / ".env"
            api_key = _load_key_from_dotenv(env_path)
            if api_key:
                break

    if not api_key:
        raise SystemExit("Please set NVAPI_KEY or NVIDIA_API_KEY environment variable, or add it to a .env file")

    # Initialize OpenAI client with NVIDIA endpoint
    client = OpenAI(
        base_url="https://integrate.api.nvidia.com/v1",
        api_key=api_key,
    )

    ensure_domains_file(DOMAINS_PATH)

    for i in range(count):
        domain, text, resp = get_domain_with_retries(client, attempts=3)
        record = append_domain_record(domain, text)
        print(f"[{i+1}/{count}] Added domain: {domain} (id={record['id']})")


if __name__ == "__main__":
    main()
