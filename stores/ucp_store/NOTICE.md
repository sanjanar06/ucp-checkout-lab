# Origin

Copied from Google's UCP sample merchant server, Apache License 2.0 (see `LICENSE`):

- Repo: https://github.com/Universal-Commerce-Protocol/samples
- Path: `rest/python/server`
- Commit: `e7c9c124864108cbb35e5102beeac9cbef80a154`

Files we added (not Google's): `Dockerfile`, `entrypoint.sh`, `supervisor.py`,
`misbehave.py`, `uv.lock`, `.dockerignore`, this `NOTICE.md`.

Google's own `*_test.py` files were left out; this store is tested with Google's
conformance suite instead. Every change we make is a normal commit on top of the
untouched import, so `git log -p stores/ucp_store` shows exactly what we changed.
