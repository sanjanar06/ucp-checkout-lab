"""Lab addition (not Google's code): runs the store and resets it on request.

Every trial must start from the same store state. Restarting the container
for each trial is slow, so this small supervisor keeps a seeded copy of the
databases (the template) and, on POST /reset, stops the store, copies the
template over the live databases and starts the store again.

  /data/stores/<STORE_NAME>/template/   seeded once from /seed/<STORE_NAME>
  /data/stores/<STORE_NAME>/live/       what the running store reads and writes

Admin port 8183 (POST /reset, GET /health); the store itself is on 8182.
"""

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


class Admin(BaseHTTPRequestHandler):
    def do_POST(self):
        if self.path != "/reset":
            self.send_error(404)
            return
        start = time.monotonic()
        reset()
        self.send_response(200)
        self.end_headers()
        self.wfile.write(f"reset in {time.monotonic() - start:.2f}s\n".encode())

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
