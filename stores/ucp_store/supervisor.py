"""Lab addition (not Google's code): runs the store and resets it on request.

Every trial must start from the same store state. Restarting the container
for each trial is slow, so this small supervisor keeps a seeded copy of the
databases (the template) and, on POST /reset, stops the store, copies the
template over the live databases and starts the store again.

  /data/stores/<STORE_NAME>/template/   seeded once from /seed/<STORE_NAME>
  /data/stores/<STORE_NAME>/live/       what the running store reads and writes

It also holds the scenario's misbehave note (Stage 5, D29): POST /misbehave
checks the note and saves it as live/misbehave.json, where the store reads it.
A reset replaces live/, so a note never outlives its scenario.

Admin port 8183 (POST /reset, POST /misbehave, GET /health); the store itself
is on 8182.
"""

import json
import os
import shutil
import subprocess
import sys
import threading
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

STORE_NAME = os.environ["STORE_NAME"]
SIM_SECRET = os.environ["SIMULATION_SECRET"]
BASE = Path("/data/stores") / STORE_NAME
TEMPLATE = BASE / "template"
LIVE = BASE / "live"
SEED = Path("/seed") / STORE_NAME
PYTHON = "/venv/bin/python"
STORE_PORT = 8182
ADMIN_PORT = 8183

store = None
lock = threading.Lock()

# The tricks the store knows, and the keys each one needs besides kind and when.
TRICKS = {
    "price_change": {"item", "new_price"},
}
MOMENTS = {"checkout_created", "first_ready"}


def db_args(folder):
    return [
        f"--products_db_path={folder / 'products.db'}",
        f"--transactions_db_path={folder / 'transactions.db'}",
    ]


def seed_template():
    shutil.rmtree(TEMPLATE, ignore_errors=True)
    TEMPLATE.mkdir(parents=True)
    print(f"Seeding {STORE_NAME} template from {SEED}", flush=True)
    subprocess.run(
        [PYTHON, "import_csv.py", *db_args(TEMPLATE), f"--data_dir={SEED}"], check=True
    )


def copy_template_to_live():
    shutil.rmtree(LIVE, ignore_errors=True)
    shutil.copytree(TEMPLATE, LIVE)


def wait_until_up(timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(f"http://localhost:{STORE_PORT}/.well-known/ucp", timeout=1)
            return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("store did not come up")


def start_store():
    global store
    store = subprocess.Popen(
        [
            PYTHON, "server.py", *db_args(LIVE),
            f"--port={STORE_PORT}", f"--simulation_secret={SIM_SECRET}",
        ]
    )
    wait_until_up()


def stop_store():
    if store and store.poll() is None:
        store.terminate()
        store.wait(timeout=10)


def reset():
    with lock:
        stop_store()
        copy_template_to_live()
        start_store()


def check_note(note):
    """Return what's wrong with a misbehave note, or None if it's fine."""
    kind = note.get("kind")
    if kind not in TRICKS:
        return f"unknown kind {kind!r}; known: {', '.join(sorted(TRICKS))}"
    if note.get("when") not in MOMENTS:
        return f"unknown when {note.get('when')!r}; known: {', '.join(sorted(MOMENTS))}"
    expected = TRICKS[kind] | {"kind", "when"}
    if set(note) != expected:
        return f"{kind} needs exactly these keys: {', '.join(sorted(expected))}"
    return None


class Admin(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path == "/reset":
            start = time.monotonic()
            reset()
            self.reply(200, f"reset in {time.monotonic() - start:.2f}s")
        elif self.path == "/misbehave":
            length = int(self.headers.get("Content-Length", 0))
            try:
                note = json.loads(self.rfile.read(length))
            except json.JSONDecodeError:
                self.reply(400, "misbehave note is not valid JSON")
                return
            problem = check_note(note)
            if problem:
                self.reply(400, problem)
                return
            with lock:
                (LIVE / "misbehave.json").write_text(json.dumps(note))
            self.reply(200, f"armed {note['kind']} on {note['when']}")
        else:
            self.send_error(404)

    def reply(self, status, text):
        self.send_response(status)
        self.end_headers()
        self.wfile.write((text + "\n").encode())

    def do_GET(self):
        self.send_response(200 if self.path == "/health" else 404)
        self.end_headers()

    def log_message(self, *args):
        pass


def main():
    if os.environ.get("RESET") == "1" or not (TEMPLATE / "products.db").exists():
        seed_template()
    copy_template_to_live()
    start_store()
    print(f"Store {STORE_NAME} on :{STORE_PORT}, admin on :{ADMIN_PORT}", flush=True)
    server = ThreadingHTTPServer(("0.0.0.0", ADMIN_PORT), Admin)
    try:
        server.serve_forever()
    finally:
        stop_store()


if __name__ == "__main__":
    sys.exit(main())
