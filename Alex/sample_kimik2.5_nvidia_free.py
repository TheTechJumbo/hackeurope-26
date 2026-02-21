
import os
import json
import requests
import argparse

invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"

# CLI + env control for streaming: CLI overrides env
parser = argparse.ArgumentParser(description="Call NVIDIA chat completions (streaming or non-streaming)")
parser.add_argument("--no-stream", action="store_true", help="Disable streaming and return full JSON response")
args = parser.parse_args()

# env var NO_STREAM=1 also disables streaming (unless CLI overrides)
env_no_stream = os.getenv("NO_STREAM")
stream_enabled = not (args.no_stream or (env_no_stream and env_no_stream != "0"))


from pathlib import Path


# prefer explicit env var names, then try loading .env in repo
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


api_key = os.getenv("NVAPI_KEY") or os.getenv("NVIDIA_API_KEY")
if not api_key:
    # try .env next to this script (or workspace root)
    script_env = Path(__file__).resolve().parent / ".env"
    api_key = _load_key_from_dotenv(script_env)

if not api_key:
    raise SystemExit("Please set NVAPI_KEY or NVIDIA_API_KEY environment variable, or add it to a .env file")

headers = {
    "Authorization": f"Bearer {api_key}",
    "Accept": "text/event-stream" if stream_enabled else "application/json",
}

payload = {
    "model": "moonshotai/kimi-k2.5",
    "messages": [{"role": "user", "content": ""}],
    "max_tokens": 16384,
    "temperature": 1.00,
    "top_p": 1.00,
    "stream": stream_enabled,
    "chat_template_kwargs": {"thinking": True},
}


# enable streaming at the requests level so iter_lines yields as it arrives
response = requests.post(invoke_url, headers=headers, json=payload, stream=stream_enabled)

if stream_enabled:
    for line in response.iter_lines(decode_unicode=False):
        if not line:
            continue
        s = line.decode("utf-8")
        # server-sent events include lines like: "data: {...}"
        if s.startswith("data: "):
            data = s[len("data: "):].strip()
            if data == "[DONE]":
                break
            try:
                obj = json.loads(data)
            except Exception:
                print(data)
                continue

            # choose likely fields containing assistant text
            choices = obj.get("choices", [])
            if choices:
                delta = choices[0].get("delta", {})
                content = delta.get("content") or delta.get("reasoning") or delta.get("reasoning_content")
                if content:
                    print(content, end="", flush=True)
                else:
                    # fallback: pretty-print the chunk
                    print(json.dumps(obj, ensure_ascii=False))
            else:
                print(json.dumps(obj, ensure_ascii=False))
else:
    # non-streaming: return full JSON response and pretty-print
    try:
        data = response.json()
    except Exception:
        print(response.text)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))
