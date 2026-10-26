"""Runs scenarios end to end and prints pass/fail for each.

For every scenario file:
  1. reset the store (if [start] reset = true)
  2. let the shopper do the task (scripted, or an AI model)
  3. grade the store's database against [expected]
  4. save the full trace, and a summary line

Usage (from the repo root):
    docker compose run --rm lab                       # all dev scenarios
    docker compose run --rm lab --only 002            # scenarios whose id contains 002
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
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from agent import ai_shopper, llm, scripted_shopper
from agent.buyer import Buyer
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


def run_scenario(path, args):
    scenario = tomllib.loads(path.read_text())
    store = scenario["start"]["store"]
    instruction = scenario["instruction"]
    if scenario["start"].get("reset"):
        reset_store(store)

    client = UcpClient(STORES[store]["url"])
    buyer = Buyer(instruction["buyer_approves"], client.transcript)
    start = time.monotonic()
    stats, error = {}, None
    try:
        if args.agent == "scripted":
            shopper_log = scripted_shopper.run(client, instruction["details"], buyer, bug=args.bug)
        else:
            shopper_log, stats = ai_shopper.run(
                client, buyer, instruction["text"], instruction["details"]["items"],
                args.provider, args.model, args.temperature)
    except llm.ProviderUnavailable as e:
        # The provider never answered: not the AI's failure, so don't grade it.
        shopper_log, error = [], str(e)
    elapsed = time.monotonic() - start

    if error:
        verdict, checks = "ERROR", []
    else:
        verdict, checks = grade(scenario["expected"], store_db(store), client.transcript)
    return scenario, {
        "verdict": verdict,
        "error": error,
        "checks": checks,
        "shopper_log": shopper_log,
        "stats": stats,
        "transcript": client.transcript,
        "latency_s": round(elapsed, 3),
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--scenarios", default="scenarios/dev")
    p.add_argument("--only", help="run only scenarios whose id contains this text")
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
        paths = [x for x in paths if args.only in x.stem]
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
            extra = (f"  ({st['model_calls']} model calls, {result['latency_s']:.0f}s)"
                     if st else "")
            print(f"  {result['verdict']:<6}  {scenario['id']}{extra}", flush=True)
            if result["error"]:
                print(f"          provider error: {result['error'][:150]}")
            for c in result["checks"]:
                if not c["ok"]:
                    print(f"          {c['check']}: expected {c['expected']}, got {c['actual']}")

    graded = len(paths) - counts["ERROR"]
    rate = f"pass rate {counts['PASS']}/{graded}" if graded else "nothing graded"
    print(f"\n{counts['PASS']} passed, {counts['FAIL']} failed, {counts['UNSAFE']} unsafe, "
          f"{counts['ERROR']} provider errors  ->  {rate}  ->  {out_dir.relative_to(DATA_DIR)}")
    sys.exit(0 if counts["PASS"] == len(paths) else 1)


if __name__ == "__main__":
    main()
