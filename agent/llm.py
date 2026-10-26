"""Calls an AI model through an OpenAI-style chat API (all three providers speak it).

Free tiers often answer "too busy" (HTTP 429) or have brief outages (5xx).
Those are the provider's problem, not the AI's, so chat() waits and retries
them, and records how long it waited. If they never clear, it raises
ProviderUnavailable and the harness marks the trial ERROR (not a failure).
"""

import json
import os
import random
import time
import urllib.error
import urllib.request

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

RETRY_STATUSES = {429, 500, 502, 503, 504}


class ProviderUnavailable(Exception):
    """The provider kept refusing (rate limits, outages). Not the AI's fault."""


def chat(provider, model, messages, tools, temperature=0.0, max_retries=6):
    """One model call. Returns (reply_json, meta) where meta has latency and waits."""
    cfg = PROVIDERS[provider]
    headers = {"Content-Type": "application/json"}
    if cfg["key_env"]:
        key = os.environ.get(cfg["key_env"])
        if not key:
            raise SystemExit(f"Set {cfg['key_env']} in .env (see .env.example)")
        headers["Authorization"] = f"Bearer {key}"
    body = {"model": model, "temperature": temperature, "messages": messages, "tools": tools}
    if provider == "openrouter":
        body["usage"] = {"include": True}
    data = json.dumps(body).encode()

    waited, retries = 0.0, 0
    while True:
        req = urllib.request.Request(cfg["url"], data, headers)
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:
                reply = json.load(resp)
            if reply.get("choices"):
                return reply, {"latency_s": round(time.monotonic() - start, 3),
                               "retries": retries, "waited_s": round(waited, 1)}
            # Some providers (OpenRouter) report upstream trouble as HTTP 200
            # with an "error" and no answer. Treat it like a busy reply.
            last_error = f"200 without an answer: {json.dumps(reply)[:500]}"
        except urllib.error.HTTPError as e:
            detail = e.read().decode()[:500]
            if e.code not in RETRY_STATUSES:
                raise RuntimeError(f"{provider} HTTP {e.code}: {detail}") from e
            last_error = f"HTTP {e.code}: {detail}"
        except (urllib.error.URLError, TimeoutError) as e:
            last_error = f"connection: {e}"
        if retries >= max_retries:
            raise ProviderUnavailable(f"{provider} gave up after {retries} retries: {last_error}")
        # Back off: 2, 4, 8, 16, 32, 60 s, plus a little randomness (jitter).
        pause = min(60, 2 ** (retries + 1)) + random.uniform(0, 1)
        time.sleep(pause)
        waited += pause
        retries += 1
