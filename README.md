# UCP Checkout Test Lab

A reliability benchmark: can AI agents take a saved multi-store cart through
Universal Commerce Protocol (UCP) checkout correctly and safely when stores,
the network and data misbehave? See [PLAN.md](PLAN.md).

Spec pinned to **UCP 2026-04-08** — see [versions.lock.toml](versions.lock.toml).

## Run commands

Everything runs in Docker (open Docker Desktop first), from this folder. Outputs (run logs, store
databases, test reports) go to `../lab-data/`, outside the repo.

**First time only**

```bash
cp .env.example .env        # then paste your free API keys into .env
```

**Check an AI model answers (Stage 1)**

```bash
docker compose run --rm smoke gemini        # or: openrouter, ollama
```

**The fake store (Stage 2)**

| What | Command |
| --- | --- |
| Start the store | `docker compose up -d store-flower` |
| See its UCP info card | `curl localhost:8182/.well-known/ucp` |
| Watch what it receives | `docker compose logs -f store-flower` |
| Run Google's official UCP tests | `docker compose run --rm conformance` |
| Print its orders and checkouts | `docker compose exec store-flower uv run --no-sync dump_transactions.py --transactions_db_path=/data/stores/flower_shop/transactions.db` |
| Start over with a fresh store | `RESET=1 docker compose up -d --force-recreate store-flower` |
| Stop everything | `docker compose down` |

**Where things end up**

| Output | Location |
| --- | --- |
| Smoke test logs and traces | `../lab-data/runs/` |
| Store databases | `../lab-data/stores/flower_shop/` |
| Official test reports | `../lab-data/conformance/` |

`stores/ucp_store/` is Google's sample store, copied unchanged at a pinned
commit (see its `NOTICE.md`); `stores/seed/<store>/` holds each store's catalog.
Ollama runs natively on the Mac (Docker can't use the Apple GPU); containers
reach it at `host.docker.internal:11434`.

## Related work

ACWorld (arXiv 2608.02441), spck-conformance, τ-bench (arXiv 2406.12045).
