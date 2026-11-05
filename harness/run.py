"""Runs scenarios end to end and prints pass/fail for each.

For every scenario file:
  1. reset the store (if [start] reset = true)
  2. let the shopper do the task (scripted, or an AI model)
  3. grade the store's database against [expected]
  4. save the full trace, and a summary line

Usage (from the repo root):
    docker compose run --rm lab                       # all dev scenarios
    docker compose run --rm lab --only 002            # scenarios whose id contains 002
    docker compose run --rm lab --only 008,011        # ...or any of several
    docker compose run --rm lab --bug ignore_decline  # break the shopper on purpose
    docker compose run --rm lab --agent ai --provider gemini   # an AI shopper
    docker compose run --rm lab --agent ai --provider openrouter --model <id>

Outputs go to $LAB_DATA_DIR/runs/<run_id>/: one <scenario>.json trace each
and results.jsonl with one summary line per scenario.
"""

import argparse
import json
import os
import sys
import time
import tomllib
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from agent import ai_shopper, llm, scripted_shopper
from agent.buyer import Buyer
from agent.ucp_client import UcpClient
from grader.grade import grade
from grader.judge import JudgeUnavailable

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("LAB_DATA_DIR", ROOT.parent / "lab-data"))

# Where each store answers (through the network), where its admin (reset)
# port is, and its live database.
STORES = {
    "flower_shop": {
        "shop": "flower-shop",
        "url": os.environ.get("FLOWER_URL", "http://flower-shop:8182"),
        "admin": os.environ.get("FLOWER_ADMIN_URL", "http://store-flower:8183"),
    },
    "bakery": {"shop": "bakery", "url": "http://bakery:8182",
               "admin": "http://store-bakery:8183"},
    "gift_shop": {"shop": "gift-shop", "url": "http://gift-shop:8182",
                  "admin": "http://store-gifts:8183"},
}


NETWORK_ADMIN = os.environ.get("NETWORK_ADMIN_URL", "http://network:8191")


def store_db(store):
    return DATA_DIR / "stores" / store / "live" / "transactions.db"


def reset_store(store):
    req = urllib.request.Request(STORES[store]["admin"] + "/reset", method="POST")
    urllib.request.urlopen(req, timeout=60).read()


def misbehave_store(store, note):
    """Hand the store this scenario's one trick (its [misbehave] table)."""
    req = urllib.request.Request(
        STORES[store]["admin"] + "/misbehave", method="POST",
        data=json.dumps(note).encode(), headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=10).read()
    except urllib.error.HTTPError as e:
        # A mistyped [misbehave] block: stop now rather than run the wrong test.
        sys.exit(f"store rejected the [misbehave] note: {e.read().decode().strip()}")


def _network(path, note=None):
    req = urllib.request.Request(
        NETWORK_ADMIN + path, method="POST" if path != "/log" else "GET",
        data=json.dumps(note).encode() if note else None,
        headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=10))
    except urllib.error.HTTPError as e:
        # A mistyped [network] table: stop now rather than run the wrong test.
        sys.exit(f"network rejected the [network] note: {e.read().decode().strip()}")


def run_scenario(path, args):
    scenario = tomllib.loads(path.read_text())
    # One store ([start] store) or a cart across several ([start] stores).
    stores = scenario["start"].get("stores") or [scenario["start"]["store"]]
    instruction = scenario["instruction"]
    if scenario["start"].get("reset"):
        for store in stores:
            reset_store(store)
    if "misbehave" in scenario:
        note = dict(scenario["misbehave"])
        misbehave_store(note.pop("store", stores[0]), note)
    # Always start with a healthy network, so no fault leaks between scenarios.
    _network("/reset")
    if "network" in scenario:
        _network("/fault", scenario["network"])

    timeline = []
    clients = {s: UcpClient(STORES[s]["url"], timeline, s) for s in stores}
    buyer = Buyer(instruction["buyer_approves"], timeline,
                  instruction.get("buyer_says_no_if_mentions", ()))
    details = instruction["details"]
    start = time.monotonic()
    stats, error = {}, None
    try:
        if args.agent == "scripted" and len(stores) > 1:
            shopper_log = scripted_shopper.run_multi(clients, details, buyer, bug=args.bug)
        elif args.agent == "scripted":
            shopper_log = scripted_shopper.run(clients[stores[0]], details, buyer, bug=args.bug)
        else:
            # The AI knows stores by their shop names, as in their addresses.
            items = [{**i, "store": STORES[i["store"]]["shop"]} if "store" in i else i
                     for i in details["items"]]
            shopper_log, stats = ai_shopper.run(
                {STORES[s]["shop"]: c for s, c in clients.items()}, buyer,
                instruction["text"], items, args.provider, args.model, args.temperature)
    except llm.ProviderUnavailable as e:
        # The provider never answered: not the AI's failure, so don't grade it.
        shopper_log, error = [], str(e)
    elapsed = time.monotonic() - start
    network_log = _network("/log")

    if error:
        verdict, checks = "ERROR", []
    else:
        try:
            verdict, checks = grade(scenario["expected"],
                                    {s: store_db(s) for s in stores}, timeline)
        except JudgeUnavailable as e:
            # The judge never answered: we can't grade, so ERROR, not FAIL.
            verdict, checks, error = "ERROR", [], str(e)
    return scenario, {
        "verdict": verdict,
        "error": error,
        "checks": checks,
        "shopper_log": shopper_log,
        "stats": stats,
        "transcript": timeline,
        "network": network_log,
        "latency_s": round(elapsed, 3),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scenarios", default="scenarios/dev")
    p.add_argument("--only", help="run only scenarios whose id contains this text "
                   "(comma-separated: any of them)")
    p.add_argument("--agent", choices=("scripted", "ai"), default="scripted")
    p.add_argument("--bug", choices=scripted_shopper.BUGS,
                   help="break the scripted shopper on purpose")
    p.add_argument("--provider", choices=llm.PROVIDERS, default="gemini")
    p.add_argument("--model", help="model id (default: the provider's default)")
    p.add_argument("--temperature", type=float, default=0.0)
    args = p.parse_args()
    if args.agent == "ai":
        if args.bug:
            sys.exit("--bug only applies to the scripted shopper")
        args.model = args.model or llm.PROVIDERS[args.provider]["default_model"]

    paths = sorted((ROOT / args.scenarios).glob("*.toml"))
    if args.only:
        wanted = args.only.split(",")
        paths = [x for x in paths if any(w in x.stem for w in wanted)]
    if not paths:
        sys.exit("no scenarios found")

    started = datetime.now(timezone.utc)
    label = args.model.replace("/", "_").replace(":", "_") if args.agent == "ai" else "scripted"
    run_id = started.strftime("%Y%m%dT%H%M%SZ") + "_" + label + ("_bug-" + args.bug if args.bug else "")
    out_dir = DATA_DIR / "runs" / run_id
    out_dir.mkdir(parents=True)
    spec = tomllib.loads((ROOT / "versions.lock.toml").read_text())["spec"]["ucp_version"]
    meta = {"run_id": run_id, "agent": args.agent, "bug": args.bug, "ucp_version": spec,
            "started_at": started.isoformat()}
    if args.agent == "ai":
        meta.update(provider=args.provider, model=args.model,
                    briefing_version=ai_shopper.BRIEFING_VERSION,
                    settings={"temperature": args.temperature,
                              "max_model_calls": ai_shopper.MAX_MODEL_CALLS})
    (out_dir / "run.json").write_text(json.dumps(meta, indent=2))

    who = f"{args.provider} {args.model}" if args.agent == "ai" else "scripted"
    print(f"Run {run_id}  (agent: {who}{', bug: ' + args.bug if args.bug else ''})\n")
    counts = {"PASS": 0, "FAIL": 0, "UNSAFE": 0, "ERROR": 0}
    with open(out_dir / "results.jsonl", "w") as results:
        for path in paths:
            scenario, result = run_scenario(path, args)
            counts[result["verdict"]] += 1
            trace = {**meta, "scenario": scenario, **result}
            (out_dir / f"{scenario['id']}.json").write_text(json.dumps(trace, indent=2))
            summary = {**meta, "scenario_id": scenario["id"], "category": scenario["category"],
                       "kind": scenario["kind"], "verdict": result["verdict"],
                       "latency_s": result["latency_s"], "error": result["error"],
                       "failed_checks": [c["check"] for c in result["checks"] if not c["ok"]],
                       **result["stats"]}
            results.write(json.dumps(summary) + "\n")

            st = result["stats"]
            extra = f"  ({st['model_calls']} model calls, {result['latency_s']:.0f}s)" if st else ""
            print(f"  {result['verdict']:<6}  {scenario['id']}{extra}", flush=True)
            if result["error"]:
                print(f"          provider error: {result['error'][:150]}")
            for c in result["checks"]:
                if not c["ok"]:
                    print(f"          {c['check']}: expected {c['expected']}, got {c['actual']}")

    graded = len(paths) - counts["ERROR"]
    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['UNSAFE']} unsafe, "
          f"{counts['ERROR']} provider errors  ->  {out_dir.relative_to(DATA_DIR)}")
    if graded:
        print(f"pass rate: {counts['PASS']}/{graded}")
    sys.exit(0 if counts["PASS"] == len(paths) else 1)


if __name__ == "__main__":
    main()
