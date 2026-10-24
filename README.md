# UCP Checkout Test Lab

A reliability benchmark: can AI agents take a saved multi-store cart through
Universal Commerce Protocol (UCP) checkout correctly and safely when stores,
the network and data misbehave? See [PLAN.md](PLAN.md).

Spec pinned to **UCP 2026-04-08** — see [versions.lock.toml](versions.lock.toml).

## Layout

| Folder | Stage | Contents |
| --- | --- | --- |
| `stores/` | 2, 6 | Fake UCP stores (from Google's Python sample) |
| `faults/` | 5, 6 | Store fault switch and network fault layer |
| `agent/` | 4 | The simple agent under test |
| `scenarios/dev`, `scenarios/heldout` | 3, 5, 6 | Scenario files; held-out set is never tuned on |
| `grader/` | 3, 7 | Code-based grader and mutation tests |
| `harness/` | 3, 7 | Runs scenarios × trials × models |
| `runs/` | all | Run logs (git-ignored) |
| `report/` | 9 | Write-up and charts |

## Stage 1 check

```bash
cp .env.example .env          # add your free keys
python3 scripts/smoke_test.py ollama
python3 scripts/smoke_test.py openrouter
python3 scripts/smoke_test.py gemini
```

## Related work

ACWorld (arXiv 2608.02441), spck-conformance, τ-bench (arXiv 2406.12045).
