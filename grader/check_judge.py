"""Tests the AI judge against hand-labelled messages before we trust it.

Run: docker compose run --rm --entrypoint python lab -m grader.check_judge

Prints each message the judge got wrong, then how often it agreed with our
labels. Lies it missed matter most: those would let an unsafe trial pass.
"""

import tomllib
from pathlib import Path

from grader import judge

EXAMPLES = Path(__file__).with_name("judge_examples.toml")


def main():
    examples = tomllib.loads(EXAMPLES.read_text())["example"]
    agree, missed_lies, false_alarms, cost = 0, 0, 0, 0.0
    print(f"Judge {judge.MODEL}, threshold {judge.THRESHOLD}, {len(examples)} examples\n")
    for ex in examples:
        p_yes, details = judge.claims_success(ex["message"])
        cost += details.get("cost_usd") or 0.0
        said = p_yes >= judge.THRESHOLD
        if said == ex["claims_success"]:
            agree += 1
            mark = "ok   "
        elif ex["claims_success"]:
            missed_lies += 1
            mark = "MISS "   # a success claim the judge didn't see
        else:
            false_alarms += 1
            mark = "FALSE"   # an honest message the judge flagged
        print(f"  {mark} p(yes)={p_yes:.2f}  {ex['message'][:80]}")
    print(f"\nagreed {agree}/{len(examples)}; missed success claims {missed_lies};"
          f" false alarms {false_alarms}; served by {details.get('model')}; cost ${cost:.6f}")


if __name__ == "__main__":
    main()
