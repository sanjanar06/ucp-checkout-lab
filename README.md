# UCP Checkout Test Lab

A reliability benchmark: can AI agents take a saved multi-store cart through
Universal Commerce Protocol (UCP) checkout correctly and safely when stores,
the network and data misbehave? See [PLAN.md](PLAN.md).

Spec pinned to **UCP 2026-04-08** — see [versions.lock.toml](versions.lock.toml).

## How to run

Everything runs in Docker. Outputs (run logs, store databases, results) go to
`../lab-data/`, outside the repo.

```bash
cp .env.example .env                        # add your free keys
docker compose run --rm smoke openrouter    # or: gemini, ollama
```

### The fake store (Stage 2)

`stores/ucp_store/` is Google's sample UCP store, copied unchanged at a pinned
commit (see its `NOTICE.md`). `stores/seed/<store>/` holds each store's catalog.

```bash
docker compose up -d store-flower           # store on http://localhost:8182
curl localhost:8182/.well-known/ucp         # its UCP info card
docker compose run --rm conformance         # Google's official UCP tests
RESET=1 docker compose up -d --force-recreate store-flower   # fresh databases
```

The store's records (`products.db`, `transactions.db`) are in
`../lab-data/stores/flower_shop/`; test reports in `../lab-data/conformance/`.

Ollama runs natively on the Mac (Docker can't use the Apple GPU); containers
reach it at `host.docker.internal:11434`.

## Related work

ACWorld (arXiv 2608.02441), spck-conformance, τ-bench (arXiv 2406.12045).
