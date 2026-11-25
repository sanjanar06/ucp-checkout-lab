"""Are the differences between two setups real, or could they be chance?

Usage (from the repo root):
    docker compose run --rm --entrypoint python lab scripts/compare.py \
        NAME=RUN_ID[,RUN_ID...] NAME=RUN_ID[,RUN_ID...] ... [--pairs A:B,C:D]

Each NAME is one setup (a model, or a model with the approval check on); its
runs are pooled, so give the dev and held-out runs together. Without --pairs,
every pair of setups is compared.

The comparison is paired by scenario: both setups ran the same scenarios, and
some scenarios are much harder than others, so each scenario's score under A
is set against its own score under B (the share of its trials that passed, or
that were UNSAFE). For each pair it reports:

  difference   mean over scenarios of (A minus B), in percentage points
  95% range    bootstrap over scenarios (re-drawn with replacement 10,000 times)
  p            paired permutation test: how often randomly swapping A and B
               within scenarios gives a difference at least this large
               (10,000 swaps). Small p: unlikely to be chance
  Holm p       p corrected for making several comparisons at once (Holm's
               method, within each measure). Use this one: with many pairs,
               some plain p values come out small by luck

A difference counts as significant when its Holm p is below 0.05. Not
significant doesn't mean the setups are equal, only that these scenarios
can't tell them apart. ERROR trials are left out; a trial rerun on resume
counts once, its last result. The output is printed and saved to
$LAB_DATA_DIR/reports/.
"""

import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime, timezone
from itertools import combinations

from report import DATA_DIR, load

DRAWS = 10_000
MEASURES = {"pass@1": "PASS", "UNSAFE": "UNSAFE"}


def setup_scores(run_ids):
    """{scenario: [verdict, ...]} pooled over the given runs."""
    verdicts = defaultdict(list)
    for run_id in run_ids:
        _, rows = load(run_id)
        for r in rows:
            if r["verdict"] != "ERROR":
                verdicts[r["scenario_id"]].append(r["verdict"])
    return verdicts


def share(verdicts, verdict):
    return sum(v == verdict for v in verdicts) / len(verdicts)


def compare(a, b, verdict):
    scenarios = sorted(set(a) & set(b))
    diffs = [share(a[s], verdict) - share(b[s], verdict) for s in scenarios]
    observed = statistics.mean(diffs)
    rng = random.Random(0)   # fixed seed: the same runs give the same answer
    boots = sorted(statistics.mean(rng.choice(diffs) for _ in diffs) for _ in range(DRAWS))
    lo, hi = boots[int(0.025 * DRAWS)], boots[int(0.975 * DRAWS) - 1]
    as_large = sum(abs(statistics.mean(d if rng.random() < 0.5 else -d for d in diffs))
                   >= abs(observed) - 1e-12 for _ in range(DRAWS))
    p = (as_large + 1) / (DRAWS + 1)
    differing = sum(d != 0 for d in diffs)
    return {"n": len(scenarios), "diff": observed, "lo": lo, "hi": hi, "p": p,
            "differing": differing}


def holm(ps):
    """Holm-adjusted p values, in the input order."""
    order = sorted(range(len(ps)), key=lambda i: ps[i])
    adjusted, running = [0.0] * len(ps), 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (len(ps) - rank) * ps[i]))
        adjusted[i] = running
    return adjusted


def pp(x):
    return f"{100 * x:+.0f}"


def main():
    args = sys.argv[1:]
    pairs = None
    if "--pairs" in args:
        i = args.index("--pairs")
        pairs = [tuple(p.split(":")) for p in args[i + 1].split(",")]
        args = args[:i] + args[i + 2:]
    if len(args) < 2 or any("=" not in a for a in args):
        sys.exit(__doc__)
    setups = {}
    for arg in args:
        name, runs = arg.split("=", 1)
        setups[name] = setup_scores(runs.split(","))
    pairs = pairs or list(combinations(setups, 2))

    out = [f"# Paired comparison, {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC", ""]
    for measure, verdict in MEASURES.items():
        results = [compare(setups[a], setups[b], verdict) for a, b in pairs]
        for r, adj in zip(results, holm([r["p"] for r in results])):
            r["holm"] = adj
        out += [f"## {measure} (A minus B, percentage points)", "",
                "| A | B | Scenarios | Scenarios that differ | Difference (95% range) | p | Holm p | Significant |",
                "| --- | --- | --- | --- | --- | --- | --- | --- |"]
        for (a, b), r in zip(pairs, results):
            out.append(f"| {a} | {b} | {r['n']} | {r['differing']} "
                       f"| {pp(r['diff'])} ({pp(r['lo'])} to {pp(r['hi'])}) "
                       f"| {r['p']:.3f} | {r['holm']:.3f} | {'yes' if r['holm'] < 0.05 else 'no'} |")
        out.append("")
    out.append("Setups: " + "; ".join(f"{name} ({len(v)} scenarios)" for name, v in setups.items()))
    for arg in args:
        out.append(f"- `{arg}`")
    text = "\n".join(out) + "\n"
    print(text)
    reports = DATA_DIR / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    path = reports / f"{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}_compare.md"
    path.write_text(text)
    print(f"saved to {path.relative_to(DATA_DIR)}")


if __name__ == "__main__":
    main()
