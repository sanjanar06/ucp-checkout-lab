"""Talks to one UCP store over HTTP and records every exchange.

If the connection drops with no reply, the status is None and the
recorded response says so: the shopper has to find out what happened.

The scripted shopper uses it now; the AI shopper will use it in Stage 4.
Every request and reply is appended to `transcript`, which the harness saves
as the trial's trace.
"""

import http.client
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
        error = None
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                status, raw = resp.status, resp.read()
        except urllib.error.HTTPError as e:
            status, raw = e.code, e.read()
        except (urllib.error.URLError, http.client.HTTPException, ConnectionError,
                TimeoutError) as e:
            # No reply at all: the store may or may not have acted on it.
            status, raw = None, None
            error = f"no reply from the store ({type(getattr(e, 'reason', e)).__name__})"
        reply = json.loads(raw) if raw else None
        response = {"status": status, "body": reply}
        if error:
            response["error"] = error
        self.transcript.append(
            {
                "step": step,
                "request": {"method": method, "path": path, "headers": headers, "body": body},
                "response": response,
                "latency_s": round(time.monotonic() - start, 3),
            }
        )
        return status, reply

    def discover(self):
        return self._send("discover", "GET", "/.well-known/ucp")

    def create_checkout(self, body):
        return self._send("create_checkout", "POST", "/checkout-sessions", body)

    def get_checkout(self, checkout_id):
        return self._send("get_checkout", "GET", f"/checkout-sessions/{checkout_id}")

    def update_checkout(self, checkout_id, body, step="update_checkout"):
        return self._send(step, "PUT", f"/checkout-sessions/{checkout_id}", body)

    def complete_checkout(self, checkout_id, body, idempotency_key=None):
        return self._send(
            "complete_checkout", "POST", f"/checkout-sessions/{checkout_id}/complete",
            body, idempotency_key,
        )

    def cancel_checkout(self, checkout_id):
        return self._send("cancel_checkout", "POST", f"/checkout-sessions/{checkout_id}/cancel")
