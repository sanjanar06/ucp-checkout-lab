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
    docker compose run --rm lab --agent ai --trials 3 --temperature default
    docker compose run --rm lab --resume <run_id>     # finish a run another day
    docker compose run --rm lab --agent ai --approval-check   # wallet pays only approved totals

Repeated trials go scenario by scenario within a trial (all of trial 1, then
trial 2, ...), so a run cut short by a daily quota still covers every
scenario once. After several provider errors in a row the run stops; resume
it later: it skips trials already graded and retries the ERRORs.

Outputs go to $LAB_DATA_DIR/runs/<run_id>/: one <scenario>.json trace each
(<scenario>.t<n>.json with --trials > 1) and results.jsonl with one summary
line per trial (on resume, a trial's last line counts).
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
                  instruction.get("buyer_says_no_if_mentions", ()), args.approval_check)
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


# Stop a run after this many provider errors in a row: the quota is probably
# used up for the day, and every further trial would just wait and fail.
MAX_ERRORS_IN_A_ROW = 3


def _temperature(value):
    return None if value == "default" else float(value)


def _duplicate_order(checks):
    """Did any store end up with more orders than expected (paid twice)?"""
    return any(c["check"].split(":")[-1] == "orders" and not c["ok"]
               and isinstance(c["actual"], int) and c["actual"] > c["expected"]
               for c in checks)


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
    p.add_argument("--temperature", type=_temperature, default=0.0,
                   help='a number, or "default" for the model\'s own')
    p.add_argument("--trials", type=int, default=1, help="run each scenario this many times")
    p.add_argument("--max-cost", type=float, default=3.0,
                   help="stop the run once its model calls cost this many US dollars")
    p.add_argument("--approval-check", action="store_true",
                   help="the buyer's wallet pays only a checkout total the buyer approved")
    p.add_argument("--resume", metavar="RUN_ID",
                   help="finish an earlier run with its own settings")
    args = p.parse_args()
    done, spent = set(), 0.0
    if args.resume:
        out_dir = DATA_DIR / "runs" / args.resume
        meta = json.loads((out_dir / "run.json").read_text())
        for key in ("agent", "bug", "provider", "model", "scenarios", "only", "trials"):
            setattr(args, key, meta.get(key))
        args.approval_check = meta.get("approval_check", False)
        args.temperature = (meta.get("settings") or {}).get("temperature", 0.0)
        for line in (out_dir / "results.jsonl").read_text().splitlines():
            r = json.loads(line)
            spent += r.get("cost_usd") or 0.0
            key = (r["scenario_id"], r.get("trial", 1))
            if r["verdict"] == "ERROR":
                done.discard(key)
            else:
                done.add(key)
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

    if args.resume:
        run_id = args.resume
        meta.setdefault("resumed_at", []).append(datetime.now(timezone.utc).isoformat())
    else:
        started = datetime.now(timezone.utc)
        label = args.model.replace("/", "_").replace(":", "_") if args.agent == "ai" else "scripted"
        run_id = (started.strftime("%Y%m%dT%H%M%SZ") + "_" + label
                  + ("_bug-" + args.bug if args.bug else "")
                  + ("_approval-check" if args.approval_check else ""))
        out_dir = DATA_DIR / "runs" / run_id
        out_dir.mkdir(parents=True)
        spec = tomllib.loads((ROOT / "versions.lock.toml").read_text())["spec"]["ucp_version"]
        meta = {"run_id": run_id, "agent": args.agent, "bug": args.bug, "ucp_version": spec,
                "started_at": started.isoformat(), "scenarios": args.scenarios,
                "only": args.only, "trials": args.trials,
                "approval_check": args.approval_check}
        if args.agent == "ai":
            meta.update(provider=args.provider, model=args.model,
                        briefing_version=ai_shopper.BRIEFING_VERSION,
                        settings={"temperature": args.temperature,
                                  "max_model_calls": ai_shopper.MAX_MODEL_CALLS})
    (out_dir / "run.json").write_text(json.dumps(meta, indent=2))
    # The trace and summary carry the run's settings, not resume bookkeeping.
    meta = {k: v for k, v in meta.items() if k != "resumed_at"}

    who = f"{args.provider} {args.model}" if args.agent == "ai" else "scripted"
    print(f"Run {run_id}  (agent: {who}{', bug: ' + args.bug if args.bug else ''}"
          f"{', approval check on' if args.approval_check else ''})"
          f"{'  resuming: ' + str(len(done)) + ' trials already graded' if args.resume else ''}\n")
    counts = {"PASS": 0, "FAIL": 0, "UNSAFE": 0, "ERROR": 0}
    trials = args.trials or 1
    errors_in_a_row, stopped = 0, False
    todo = [(t, path) for t in range(1, trials + 1) for path in paths
            if (path.stem, t) not in done]
    with open(out_dir / "results.jsonl", "a" if args.resume else "w") as results:
        for trial, path in todo:
            scenario, result = run_scenario(path, args)
            counts[result["verdict"]] += 1
            trace = {**meta, "trial": trial, "scenario": scenario, **result}
            name = scenario["id"] + (f".t{trial}" if trials > 1 else "")
            (out_dir / f"{name}.json").write_text(json.dumps(trace, indent=2))
            summary = {**meta, "scenario_id": scenario["id"], "trial": trial,
                       "category": scenario["category"],
                       "kind": scenario["kind"], "verdict": result["verdict"],
                       "latency_s": result["latency_s"], "error": result["error"],
                       "failed_checks": [c["check"] for c in result["checks"] if not c["ok"]],
                       "duplicate_order": _duplicate_order(result["checks"]),
                       "wallet_refusals": sum(e["step"] == "wallet_refused"
                                              for e in result["transcript"]),
                       **result["stats"]}
            results.write(json.dumps(summary) + "\n")
            results.flush()

            st = result["stats"]
            extra = f"  ({st['model_calls']} model calls, {result['latency_s']:.0f}s)" if st else ""
            label = f"{scenario['id']}" + (f"  trial {trial}" if trials > 1 else "")
            print(f"  {result['verdict']:<6}  {label}{extra}", flush=True)
            if result["error"]:
                print(f"          provider error: {result['error'][:150]}")
            for c in result["checks"]:
                if not c["ok"]:
                    print(f"          {c['check']}: expected {c['expected']}, got {c['actual']}")
            spent += (st.get("cost_usd") or 0.0) if st else 0.0
            if spent >= args.max_cost:
                stopped = True
                print(f"\nSpent ${spent:.2f}, the cap is ${args.max_cost:.2f}: stopping. "
                      f"Resume with a higher --max-cost if that's intended.")
                break
            errors_in_a_row = errors_in_a_row + 1 if result["verdict"] == "ERROR" else 0
            if errors_in_a_row >= MAX_ERRORS_IN_A_ROW:
                stopped = True
                print(f"\n{MAX_ERRORS_IN_A_ROW} provider errors in a row: stopping. "
                      f"Resume later: docker compose run --rm lab --resume {run_id}")
                break

    if spent:
        print(f"\nmodel cost so far: ${spent:.4f}")
    graded = sum(counts.values()) - counts["ERROR"]
    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['UNSAFE']} unsafe, "
          f"{counts['ERROR']} provider errors  ->  {out_dir.relative_to(DATA_DIR)}")
    if graded:
        print(f"pass rate: {counts['PASS']}/{graded}")
    sys.exit(0 if not stopped and counts["PASS"] == len(todo) else 1)


if __name__ == "__main__":
    main()
