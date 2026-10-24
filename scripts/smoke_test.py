"""Stage 1 check: one test call to a free model, including a tool call.

Usage (from the repo root):
    docker compose run --rm smoke ollama
    docker compose run --rm smoke openrouter
    docker compose run --rm smoke gemini
    docker compose run --rm smoke openrouter --model google/gemma-4-31b-it:free

Each call writes two things under $LAB_DATA_DIR/runs/, outside the repo:
  - a summary line in smoke.jsonl (model, provider, date, settings, latency,
    tokens, cost, pass/fail)
  - the full trace in traces/<run_id>.json (the exact request, with the API key
    redacted, and the complete reply or error)
Standard library only.
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
DATA_DIR = Path(os.environ.get("LAB_DATA_DIR", ROOT.parent / "lab-data"))
OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")

PROVIDERS = {
    "ollama": {
        "url": f"{OLLAMA_BASE_URL}/v1/chat/completions",
        "key_env": None,
        "default_model": "qwen3:8b",
    },
    "openrouter": {
        "url": "https://openrouter.ai/api/v1/chat/completions",
        "key_env": "OPENROUTER_API_KEY",
        "default_model": "nvidia/nemotron-3.5-super-vl:free",
    },
    "gemini": {
        "url": "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        "key_env": "GEMINI_API_KEY",
        "default_model": "gemini-3.8-flash",
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
EXPECTED_ID = "chk_123"


def load_env():
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())


def tool_call_ok(calls):
    """True if any call is get_checkout with checkout_id exactly EXPECTED_ID."""
    for c in calls:
        fn = c.get("function", {})
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except json.JSONDecodeError:
            continue
        if (
            fn.get("name") == "get_checkout"
            and isinstance(args, dict)
            and args.get("checkout_id") == EXPECTED_ID
        ):
            return True
    return False


def parse_body(raw):
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return raw


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
            {"role": "user", "content": f"Look up checkout session {EXPECTED_ID} using your tool."}
        ],
        "tools": [TOOL],
    }
    if args.provider == "openrouter":
        body["usage"] = {"include": True}

    started_at = datetime.now(timezone.utc)
    run_id = f"{started_at.strftime('%Y%m%dT%H%M%S%fZ')}_{args.provider}"

    req = urllib.request.Request(cfg["url"], json.dumps(body).encode(), headers)
    start = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            data = json.load(resp)
        response = {"status": resp.status, "body": data}
        error = None
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        data = {}
        response = {"status": e.code, "body": parse_body(raw)}
        error = f"HTTP {e.code}: {raw[:300]}"
    except urllib.error.URLError as e:
        data = {}
        response = {"status": None, "body": None}
        error = f"Connection failed: {e.reason}"
    latency = time.monotonic() - start

    msg = (data.get("choices") or [{}])[0].get("message", {})
    tool_ok = tool_call_ok(msg.get("tool_calls") or [])
    usage = data.get("usage", {})
    spec = tomllib.loads((ROOT / "versions.lock.toml").read_text())["spec"]["ucp_version"]

    traces_dir = DATA_DIR / "runs" / "traces"
    traces_dir.mkdir(parents=True, exist_ok=True)
    trace_path = traces_dir / f"{run_id}.json"
    trace = {
        "run_id": run_id,
        "timestamp": started_at.isoformat(),
        "latency_s": round(latency, 3),
        "request": {
            "url": cfg["url"],
            "headers": {
                k: ("<redacted>" if k == "Authorization" else v) for k, v in headers.items()
            },
            "body": body,
        },
        "response": response,
        "error": error,
    }
    trace_path.write_text(json.dumps(trace, indent=2))

    record = {
        "run_id": run_id,
        "timestamp": started_at.isoformat(),
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
        "trace_file": str(trace_path.relative_to(DATA_DIR)),
    }
    with open(DATA_DIR / "runs" / "smoke.jsonl", "a") as f:
        f.write(json.dumps(record) + "\n")

    print(json.dumps(record, indent=2))
    if error:
        raise SystemExit(1)
    print("\nPASS: model made the tool call" if tool_ok else "\nFAIL: no correct tool call")
    raise SystemExit(0 if tool_ok else 1)


if __name__ == "__main__":
    main()
