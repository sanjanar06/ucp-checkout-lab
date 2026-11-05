"""The network between the shoppers and the stores, which can fail on cue.

Every shopper request goes through here. Normally it passes requests and
replies through unchanged. A scenario's [network] table arms one fault,
which fires on a checkout event (the first request of a given kind), never
on a request count. An optional `shop` limits it to one store's traffic:

  lost_reply   the store gets the request and acts on it, but its reply never
               reaches the shopper: the connection closes with no answer
               (e.g. "complete" went through, but the shopper can't tell)
  duplicate    the request reaches the store twice (same headers, so the
               same idempotency key) and the shopper gets the second reply.
               A lab check of the store, not an AI test: a correct store
               answers both the same way. `on = "all"` doubles every request
  other_buyer  just before the shopper's request reaches the store, another
               buyer places a real order there (e.g. takes the last unit).
               The other buyer is the honest scripted shopper, using the
               fault's `details` (items, buyer, ship_to, shipping_option)

The stores stay Google's code: the network fails, the store doesn't lie.
Shoppers reach each store by its shop name (e.g. http://flower-shop:8182);
the Host header picks which store to forward to.

Admin port (8191), used by the harness before each scenario:
  POST /reset   disarm any fault and clear the log
  POST /fault   arm one fault: {"kind": "lost_reply", "on": "complete"}
  GET  /log     what the network did this scenario (saved with the trace)
"""

import http.client
import json
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from agent import scripted_shopper
from agent.buyer import Buyer
from agent.ucp_client import UcpClient

# Shop name the shopper uses -> the store container behind it.
ROUTES = {
    "flower-shop": ("store-flower", 8182),
    "bakery": ("store-bakery", 8182),
    "gift-shop": ("store-gifts", 8182),
}

# Each fault and the keys it needs besides kind and on.
FAULTS = {"lost_reply": set(), "duplicate": set(), "other_buyer": {"details"}}

# Which checkout event a request is, from its method and path.
ACTIONS = {
    "discover": ("GET", r"/\.well-known/ucp"),
    "create": ("POST", r"/checkout-sessions"),
    "get": ("GET", r"/checkout-sessions/[^/]+"),
    "update": ("PUT", r"/checkout-sessions/[^/]+"),
    "complete": ("POST", r"/checkout-sessions/[^/]+/complete"),
    "cancel": ("POST", r"/checkout-sessions/[^/]+/cancel"),
}

# Hop-by-hop headers belong to one connection, not the message.
SKIP_HEADERS = {"host", "connection", "keep-alive", "transfer-encoding", "content-length"}

state = {"fault": None, "log": []}
lock = threading.Lock()


def action_of(method, path):
    path = path.split("?")[0]
    return next((name for name, (m, pattern) in ACTIONS.items()
                 if m == method and re.fullmatch(pattern, path)), None)


def take_fault(action, shop):
    """The armed fault, if this request is its event. It fires only once."""
    with lock:
        fault = state["fault"]
        if not fault or fault.get("shop", shop) != shop:
            return None
        if fault["on"] == "all":
            return fault
        if not fault.get("fired") and fault["on"] == action:
            fault["fired"] = True
            return fault
    return None


def note(entry):
    with lock:
        state["log"].append(entry)


class Traffic(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _forward(self):
        shop = (self.headers.get("Host") or "").split(":")[0]
        if shop not in ROUTES:
            self.send_error(502, f"no store called {shop!r}")
            return
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        headers = {k: v for k, v in self.headers.items() if k.lower() not in SKIP_HEADERS}
        action = action_of(self.command, self.path)
        fault = take_fault(action, shop)
        if fault and fault["kind"] == "other_buyer":
            self._other_buyer(shop, fault["details"], action)
        status, reply_headers, reply = self._send_to_store(shop, body, headers)
        if fault and fault["kind"] == "duplicate":
            first = status
            status, reply_headers, reply = self._send_to_store(shop, body, headers)
            note({"fault": "duplicate", "action": action, "path": self.path,
                  "store_statuses": [first, status]})
        if fault and fault["kind"] == "lost_reply":
            # The store already acted; the shopper just never hears back.
            note({"fault": "lost_reply", "action": action, "path": self.path,
                  "store_status": status})
            self.close_connection = True
            return
        self.send_response(status)
        for k, v in reply_headers:
            if k.lower() not in SKIP_HEADERS:
                self.send_header(k, v)
        self.send_header("Content-Length", str(len(reply)))
        self.end_headers()
        self.wfile.write(reply)

    def _other_buyer(self, shop, details, action):
        """Someone else checks out at this store first, for real."""
        host, port = ROUTES[shop]
        client = UcpClient(f"http://{host}:{port}")
        log = scripted_shopper.run(client, details, Buyer(True, client.transcript))
        orders = [e["response"]["body"].get("order", {}).get("id") for e in client.transcript
                  if e["step"] == "complete_checkout" and (e["response"]["status"] or 999) < 400]
        note({"fault": "other_buyer", "action": action, "buyer": details["buyer"]["email"],
              "orders": orders, "log": log})

    def _send_to_store(self, shop, body, headers):
        conn = http.client.HTTPConnection(*ROUTES[shop], timeout=60)
        try:
            conn.request(self.command, self.path, body or None, headers)
            resp = conn.getresponse()
            return resp.status, resp.getheaders(), resp.read()
        finally:
            conn.close()

    do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _forward

    def log_message(self, *args):
        pass


class Admin(BaseHTTPRequestHandler):
    def _reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._reply(200, {"ok": True})
        elif self.path == "/log":
            with lock:
                self._reply(200, {"fault": state["fault"], "log": state["log"]})
        else:
            self._reply(404, {"error": "unknown path"})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        if self.path == "/reset":
            with lock:
                state["fault"], state["log"] = None, []
            self._reply(200, {"ok": True})
        elif self.path == "/fault":
            try:
                fault = json.loads(body)
            except json.JSONDecodeError:
                return self._reply(400, {"error": "body must be JSON"})
            # A mistyped [network] table must stop the run, not test nothing.
            if fault.get("kind") not in FAULTS:
                return self._reply(400, {"error": f"kind must be one of {sorted(FAULTS)}"})
            keys = {"kind", "on"} | FAULTS[fault["kind"]]
            if set(fault) - {"shop"} != keys:
                return self._reply(400, {"error": f"{fault['kind']} has exactly: {sorted(keys)}"
                                                  " (plus optional shop)"})
            if fault.get("shop", "flower-shop") not in ROUTES:
                return self._reply(400, {"error": f"shop must be one of {sorted(ROUTES)}"})
            if fault["on"] not in ACTIONS and fault["on"] != "all":
                return self._reply(400, {"error": f"on must be one of {sorted(ACTIONS) + ['all']}"})
            with lock:
                state["fault"], state["log"] = fault, []
            self._reply(200, {"ok": True})
        else:
            self._reply(404, {"error": "unknown path"})

    def log_message(self, *args):
        pass


def main():
    servers = [ThreadingHTTPServer(("0.0.0.0", 8182), Traffic),
               ThreadingHTTPServer(("0.0.0.0", 8191), Admin)]
    for s in servers[1:]:
        threading.Thread(target=s.serve_forever, daemon=True).start()
    print("network: traffic on :8182, admin on :8191", flush=True)
    servers[0].serve_forever()


if __name__ == "__main__":
    main()
