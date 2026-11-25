"""Turns finished runs into the Stage 7 numbers.

Usage (from the repo root):
    docker compose run --rm --entrypoint python lab scripts/report.py RUN_ID [RUN_ID ...]

Each run is one model on one scenario set (dev or held-out), usually with
3 trials per scenario. For each run it reports:

  pass@1     share of trials that passed, averaged per scenario
  pass^k     share of scenarios that passed in all k trials (how dependable)
  unsafe     share of trials judged UNSAFE
  duplicate orders  trials where some store took more orders than expected
  wallet refusals  trials where the buyer's wallet refused to pay an
             unapproved total (only with the approval check on, Stage 8)
  failures by category, cost per passed trial, latency p50/p95

The 95% ranges come from a bootstrap over scenarios: scenarios are re-drawn
with replacement 2,000 times and the middle 95% of the results is shown. They
say how much the number could move with a different set of scenarios like
these, not how much the model could improve.

ERROR trials (the provider never answered) are left out and counted. If a
trial was rerun on resume, its last result counts. The report is printed and
saved to $LAB_DATA_DIR/reports/.
"""

import json
import os
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

DATA_DIR = Path(os.environ.get("LAB_DATA_DIR", Path(__file__).resolve().parents[2] / "lab-data"))
BOOTSTRAP = 2000


def load(run_id):
    run_dir = DATA_DIR / "runs" / run_id
    meta = json.loads((run_dir / "run.json").read_text())
    last = {}
    for line in (run_dir / "results.jsonl").read_text().splitlines():
        r = json.loads(line)
        last[(r["scenario_id"], r.get("trial", 1))] = r
    return meta, list(last.values())


def bootstrap(per_scenario, stat):
    """95% range of stat() over scenarios re-drawn with replacement."""
    if not per_scenario:
        return None, None
    rng = random.Random(0)   # fixed seed: the same runs give the same report
    values = sorted(stat([rng.choice(per_scenario) for _ in per_scenario])
                    for _ in range(BOOTSTRAP))
    return values[int(0.025 * BOOTSTRAP)], values[int(0.975 * BOOTSTRAP) - 1]


def pct(x):
    return "–" if x is None else f"{100 * x:.0f}%"


def with_range(value, lo, hi):
    return f"{pct(value)} ({pct(lo)}–{pct(hi)})"


def percentile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def summarize(meta, rows):
    k = meta.get("trials") or 1
    graded = [r for r in rows if r["verdict"] != "ERROR"]
    by_scenario = defaultdict(list)
    for r in graded:
        by_scenario[r["scenario_id"]].append(r)
    scenarios = list(by_scenario.values())
    full = [s for s in scenarios if len(s) == k]   # pass^k needs all k trials

    def pass1(sample):
        return statistics.mean(sum(r["verdict"] == "PASS" for r in s) / len(s) for s in sample)

    def passk(sample):
        return statistics.mean(all(r["verdict"] == "PASS" for r in s) for s in sample)

    def unsafe(sample):
        return statistics.mean(sum(r["verdict"] == "UNSAFE" for r in s) / len(s) for s in sample)

    passes = sum(r["verdict"] == "PASS" for r in graded)
    cost = sum(r.get("cost_usd") or 0.0 for r in rows)
    latencies = [r["latency_s"] for r in graded]
    categories = defaultdict(lambda: {"PASS": 0, "FAIL": 0, "UNSAFE": 0})
    for r in graded:
        categories[r["category"]][r["verdict"]] += 1
    return {
        "run": meta["run_id"],
        "model": (meta.get("model") or meta["agent"] + (f" bug {meta['bug']}" if meta.get("bug") else ""))
        + (" + approval check" if meta.get("approval_check") else ""),
        "set": Path(meta.get("scenarios") or "scenarios/dev").name, "k": k,
        "scenarios": len(scenarios), "trials": len(graded),
        "errors": len(rows) - len(graded),
        "pass1": (pass1(scenarios) if scenarios else None, *bootstrap(scenarios, pass1)),
        "passk": (passk(full) if full else None, *bootstrap(full, passk), len(full)),
        "unsafe": (unsafe(scenarios) if scenarios else None, *bootstrap(scenarios, unsafe)),
        "unsafe_trials": sum(r["verdict"] == "UNSAFE" for r in graded),
        "duplicates": sum(bool(r.get("duplicate_order")) for r in graded),
        "wallet_refusals": sum(bool(r.get("wallet_refusals")) for r in graded),
        "cost": cost, "cost_per_pass": cost / passes if passes else None,
        "p50": percentile(latencies, 0.5), "p95": percentile(latencies, 0.95),
        "calls": statistics.mean(r["model_calls"] for r in graded if "model_calls" in r)
        if any("model_calls" in r for r in graded) else None,
        "categories": dict(categories),
        "unsafe_list": sorted({r["scenario_id"] for r in graded if r["verdict"] == "UNSAFE"}),
    }


def render(summaries):
    out = [f"# Lab report, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", ""]
    out += ["| Model | Set | Scenarios × trials | pass@1 (95% range) | pass^k (95% range) "
            "| UNSAFE trials | Duplicate orders | Wallet refusals | Errors | Cost | Cost per pass "
            "| Latency p50 / p95 |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |"]
    for s in summaries:
        p1, pk = s["pass1"], s["passk"]
        cpp = f"${s['cost_per_pass']:.3f}" if s["cost_per_pass"] is not None else "–"
        lat = f"{s['p50']:.0f}s / {s['p95']:.0f}s" if s["p50"] is not None else "–"
        out.append(
            f"| {s['model']} | {s['set']} | {s['scenarios']} × {s['k']} "
            f"| {with_range(*p1)} | {with_range(*pk[:3])} (n={pk[3]}) "
            f"| {s['unsafe_trials']} ({with_range(*s['unsafe'])}) | {s['duplicates']} "
            f"| {s['wallet_refusals']} "
            f"| {s['errors']} | ${s['cost']:.2f} | {cpp} | {lat} |")
    out += ["", "## By category (trials: pass / fail / unsafe)", ""]
    cats = sorted({c for s in summaries for c in s["categories"]})
    out += ["| Category | " + " | ".join(f"{s['model']} ({s['set']})" for s in summaries) + " |",
            "| --- |" + " --- |" * len(summaries)]
    for c in cats:
        cells = []
        for s in summaries:
            v = s["categories"].get(c)
            cells.append(f"{v['PASS']} / {v['FAIL']} / {v['UNSAFE']}" if v else "–")
        out.append(f"| {c} | " + " | ".join(cells) + " |")
    out += ["", "## Scenarios with an UNSAFE trial", ""]
    for s in summaries:
        out.append(f"- {s['model']} ({s['set']}): {', '.join(s['unsafe_list']) or 'none'}")
    out += ["", "Runs: " + ", ".join(f"`{s['run']}`" for s in summaries)]
    return "\n".join(out) + "\n"


def main():
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    summaries = [summarize(*load(run_id)) for run_id in sys.argv[1:]]
    text = render(summaries)
    print(text)
    reports = DATA_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.md"
    path.write_text(text)
    print(f"saved to {path.relative_to(DATA_DIR)}")


if __name__ == "__main__":
    main()
