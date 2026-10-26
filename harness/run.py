"""Runs scenarios end to end and prints pass/fail for each.

For every scenario file:
  1. reset the store (if [start] reset = true)
  2. let the shopper do the task (scripted for now; the AI from Stage 4)
  3. grade the store's database against [expected]
  4. save the full trace, and a summary line

Usage (from the repo root):
    docker compose run --rm lab                       # all dev scenarios
    docker compose run --rm lab --only 002            # scenarios whose id contains 002
    docker compose run --rm lab --bug ignore_decline  # break the shopper on purpose

Outputs go to $LAB_DATA_DIR/runs/<run_id>/: one <scenario>.json trace each
and results.jsonl with one summary line per scenario.
"""

import argparse
import json
import os
import sys
import time
import tomllib
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from agent import scripted_shopper
from agent.ucp_client import UcpClient
from grader.grade import grade

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("LAB_DATA_DIR", ROOT.parent / "lab-data"))

# Where each store answers, where its admin (reset) port is, and its live database.
STORES = {
    "flower_shop": {
        "url": os.environ.get("FLOWER_URL", "http://store-flower:8182"),
        "admin": os.environ.get("FLOWER_ADMIN_URL", "http://store-flower:8183"),
    },
}


def store_db(store):
    return DATA_DIR / "stores" / store / "live" / "transactions.db"


def reset_store(store):
    req = urllib.request.Request(STORES[store]["admin"] + "/reset", method="POST")
    urllib.request.urlopen(req, timeout=60).read()


def run_scenario(path, bug):
    scenario = tomllib.loads(path.read_text())
    store = scenario["start"]["store"]
    instruction = scenario["instruction"]
    if scenario["start"].get("reset"):
        reset_store(store)

    client = UcpClient(STORES[store]["url"])
    start = time.monotonic()
    shopper_log = scripted_shopper.run(
        client, instruction["details"], instruction["buyer_approves"], bug=bug
    )
    elapsed = time.monotonic() - start
    verdict, checks = grade(scenario["expected"], store_db(store))
    return scenario, {
        "verdict": verdict,
        "checks": checks,
        "shopper_log": shopper_log,
        "transcript": client.transcript,
        "latency_s": round(elapsed, 3),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scenarios", default="scenarios/dev")
    p.add_argument("--only", help="run only scenarios whose id contains this text")
    p.add_argument("--bug", choices=scripted_shopper.BUGS, help="break the shopper on purpose")
    args = p.parse_args()

    paths = sorted((ROOT / args.scenarios).glob("*.toml"))
    if args.only:
        paths = [x for x in paths if args.only in x.stem]
    if not paths:
        sys.exit("no scenarios found")

    started = datetime.now(timezone.utc)
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + ("_bug-" + args.bug if args.bug else "")
    out_dir = DATA_DIR / "runs" / run_id
    out_dir.mkdir(parents=True)
    spec = tomllib.loads((ROOT / "versions.lock.toml").read_text())["spec"]["ucp_version"]
    meta = {"run_id": run_id, "agent": "scripted", "bug": args.bug, "ucp_version": spec,
            "started_at": started.isoformat()}

    print(f"Run {run_id}  (agent: scripted{', bug: ' + args.bug if args.bug else ''})\n")
    counts = {"PASS": 0, "FAIL": 0, "UNSAFE": 0}
    with open(out_dir / "results.jsonl", "w") as results:
        for path in paths:
            scenario, result = run_scenario(path, args.bug)
            counts[result["verdict"]] += 1
            trace = {**meta, "scenario": scenario, **result}
            (out_dir / f"{scenario['id']}.json").write_text(json.dumps(trace, indent=2))
            summary = {**meta, "scenario_id": scenario["id"], "category": scenario["category"],
                       "kind": scenario["kind"], "verdict": result["verdict"],
                       "latency_s": result["latency_s"],
                       "failed_checks": [c["check"] for c in result["checks"] if not c["ok"]]}
            results.write(json.dumps(summary) + "\n")

            print(f"  {result['verdict']:<6}  {scenario['id']}")
            for c in result["checks"]:
                if not c["ok"]:
                    print(f"          {c['check']}: expected {c['expected']}, got {c['actual']}")

    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['UNSAFE']} unsafe"
          f"  ->  {out_dir.relative_to(DATA_DIR)}")
    sys.exit(0 if counts["PASS"] == len(paths) else 1)


if __name__ == "__main__":
    main()
