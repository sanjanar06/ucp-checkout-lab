"""Talks to one UCP store over HTTP and records every exchange.

The scripted shopper uses it now; the AI shopper will use it in Stage 4.
Every request and reply is appended to `transcript`, which the harness saves
as the trial's trace.
"""

import json
import time
import urllib.error
import urllib.request
import uuid


class UcpClient:
    def __init__(self, base_url):
        self.base_url = base_url.rstrip("/")
        self.transcript = []

    def _send(self, step, method, path, body=None, idempotency_key=None):
        headers = {
            "UCP-Agent": 'profile="https://agent.example/profile"',
            "Request-Signature": "test",
            "Idempotency-Key": idempotency_key or str(uuid.uuid4()),
            "Request-Id": str(uuid.uuid4()),
            "Content-Type": "application/json",
        }
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(self.base_url + path, data, headers, method=method)
        start = time.monotonic()
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        reply = json.loads(raw) if raw else None
        self.transcript.append(
            {
                "step": step,
                "request": {"method": method, "path": path, "headers": headers, "body": body},
                "response": {"status": status, "body": reply},
                "latency_s": round(time.monotonic() - start, 3),
            }
        )
        return status, reply

    def discover(self):
        return self._send("discover", "GET", "/.well-known/ucp")

    def create_checkout(self, body):
        return self._send("create_checkout", "POST", "/checkout-sessions", body)

    def update_checkout(self, checkout_id, body, step="update_checkout"):
        return self._send(step, "PUT", f"/checkout-sessions/{checkout_id}", body)

    def complete_checkout(self, checkout_id, body, idempotency_key=None):
        return self._send(
            "complete_checkout", "POST", f"/checkout-sessions/{checkout_id}/complete",
            body, idempotency_key,
        )

    def cancel_checkout(self, checkout_id):
        return self._send("cancel_checkout", "POST", f"/checkout-sessions/{checkout_id}/cancel")
