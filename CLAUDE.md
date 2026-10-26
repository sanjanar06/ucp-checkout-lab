# UCP Checkout Test Lab

A reliability benchmark: can AI agents take a saved cart through Universal
Commerce Protocol (UCP) checkout correctly and safely when stores, the network
and data misbehave? The question, scope and metrics are in [PLAN.md](PLAN.md).

## Where knowledge lives

This file is the map. Read the rest only when the task needs it.

| File | Holds |
| --- | --- |
| [docs/status.md](docs/status.md) | Which stage we're on, what's open, what's next |
| [docs/decisions.md](docs/decisions.md) | Every design decision, dated, with the reason |
| [docs/findings.md](docs/findings.md) | What the runs revealed (store bugs, AI behaviour) |
| [README.md](README.md) | Every run command and where outputs go |
| [versions.lock.toml](versions.lock.toml) | Pinned spec, SDK and Google repo commits |
| `<folder>/CLAUDE.md` | How that part works and its rules |

## Layout

| Folder | Part |
| --- | --- |
| `stores/` | Fake UCP stores (Google's sample, copied) and their seed catalogs |
| `scenarios/` | One TOML file per test: start, instruction, expected end |
| `agent/` | Shoppers (scripted and AI), the UCP client, the pretend buyer |
| `grader/` | The referee: judges the store's database and the trial timeline |
| `harness/` | Runs scenarios: reset store, shopper, grader, save trace |
| `tests/` | Google's conformance suite, built at the pinned commit |
| `scripts/` | One-off checks (model smoke test) |
| `docs/` | Status, decisions, findings |

## Ground rules

- **Everything runs in Docker** (`docker compose ...`). Exception: Ollama runs
  natively on the Mac; containers reach it at `host.docker.internal:11434`.
- **No outputs in the repo.** Run logs, traces, store databases and reports go
  to `../lab-data/`. No placeholder folders or `.gitkeep` files.
- **Git:** a new branch for each feature or stage. Never commit or push without
  the user's explicit go-ahead, and ask again for each one.
- **One UCP spec version** (2026-04-08) for the whole project.
- **Grade from the store's records and our own timeline,** never from what
  the agent says it did.
- **$10 maximum** paid AI spend; build and debug on free and local models.
- **Log every run:** model, provider, date, settings, briefing version, cost, time.
- **One lab run at a time:** runs share the store and reset it.
- **Each stage works before the next starts.**
- When a design decision is made, add it to `docs/decisions.md`. When a run
  reveals something, add it to `docs/findings.md`. When a stage or open item
  changes, update `docs/status.md`.
