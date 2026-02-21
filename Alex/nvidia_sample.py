
import os
import json
import requests
import argparse
from pathlib import Path

invoke_url = "https://integrate.api.nvidia.com/v1/chat/completions"

# CLI + env control for streaming: CLI overrides env
parser = argparse.ArgumentParser(description="Call NVIDIA chat completions (streaming or non-streaming)")
parser.add_argument("--stream", action="store_true", help="Enable streaming mode")
args = parser.parse_args()

# env var STREAM=1 enables streaming (unless CLI overrides with --stream)
env_stream = os.getenv("STREAM")
stream_enabled = args.stream or (env_stream and env_stream != "0")


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
    # try root .env (parent directories)
    current = Path(__file__).resolve().parent
    for p in [current] + list(current.parents):
        env_path = p / ".env"
        api_key = _load_key_from_dotenv(env_path)
        if api_key:
            break

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
        if line:
            print(line.decode("utf-8"))
else:
    # non-streaming: return full JSON response and pretty-print
    try:
        data = response.json()
    except Exception:
        print(response.text)
    else:
        print(json.dumps(data, indent=2, ensure_ascii=False))
