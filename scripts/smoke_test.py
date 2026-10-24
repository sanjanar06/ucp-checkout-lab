"""Stage 1 check: one test call to a free model, including a tool call.

Usage:
    python scripts/smoke_test.py ollama
    python scripts/smoke_test.py openrouter
    python scripts/smoke_test.py gemini
    python scripts/smoke_test.py openrouter --model google/gemma-4-31b-it:free

Every call is appended to runs/smoke.jsonl (model, provider, date, settings,
latency, tokens, cost). Standard library only.
"""

import argparse
import json
import os
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

PROVIDERS = {
    "ollama": {
        "url": "http://localhost:11434/v1/chat/completions",
        "key_env": None,
        "default_model": "qwen3:8b",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "default_model": "google/gemma-4-31b-it:free",
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key_env": "GEMINI_API_KEY",
        "default_model": "gemini-2.5-flash",
    },
}

# A stand-in for the real UCP actions the agent will get in Stage 4.
TOOL = {
    "type": "function",
    "function": {
        "name": "get_checkout",
        "description": "Fetch a UCP checkout session by id.",
        "parameters": {
            "type": "object",
            "properties": {"checkout_id": {"type": "string"}},
            "required": ["checkout_id"],
        },
    },
}


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def main():
    p = argparse.ArgumentParser()
    p.add_argument("provider", choices=PROVIDERS)
    p.add_argument("--model")
    p.add_argument("--temperature", type=float, default=0.0)
    args = p.parse_args()

    load_env()
    cfg = PROVIDERS[args.provider]
    model = args.model or cfg["default_model"]
    headers = {"Content-Type": "application/json"}
    if cfg["key_env"]:
        key = os.environ.get(cfg["key_env"])
        if not key:
            raise SystemExit(f"Set {cfg['key_env']} in .env (see .env.example)")
        headers["Authorization"] = f"Bearer {key}"

    body = {
        "model": model,
        "temperature": args.temperature,
        "messages": [
            {"role": "user", "content": "Look up checkout session chk_123 using your tool."}
        ],
        "tools": [TOOL],
    }
    if args.provider == "openrouter":
        body["usage"] = {"include": True}

    req = urllib.request.Request(cfg["url"], json.dumps(body).encode(), headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
        error = None
    except urllib.error.HTTPError as e:
        data, error = {}, f"HTTP {e.code}: {e.read().decode()[:300]}"
    except urllib.error.URLError as e:
        data, error = {}, f"Connection failed: {e.reason}"
    latency = time.monotonic() - start

    msg = (data.get("choices") or [{}])[0].get("message", {})
    calls = msg.get("tool_calls") or []
    tool_ok = any(
        c["function"]["name"] == "get_checkout"
        and "chk_123" in c["function"].get("arguments", "")
        for c in calls
    )
    usage = data.get("usage", {})
    spec = tomllib.loads((ROOT / "versions.lock.toml").read_text())["spec"]["ucp_version"]

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "kind": "smoke_test",
        "provider": args.provider,
        "model": model,
        "served_model": data.get("model"),
        "settings": {"temperature": args.temperature},
        "ucp_version": spec,
        "latency_s": round(latency, 3),
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "cost_usd": usage.get("cost", 0.0),
        "tool_call_ok": tool_ok,
        "error": error,
    }
    (ROOT / "runs").mkdir(exist_ok=True)
    with open(ROOT / "runs" / "smoke.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")

    print(json.dumps(record, indent=2))
    if error:
        raise SystemExit(1)
    print("\nPASS: model made the tool call" if tool_ok else "\nFAIL: no correct tool call")
    raise SystemExit(0 if tool_ok else 1)


if __name__ == "__main__":
    main()
