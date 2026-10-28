# stores/: the fake UCP stores

- `ucp_store/` is Google's sample store (`samples@e7c9c12`, Apache-2.0),
  copied unchanged in its first commit. Every change since is a normal commit
  marked "Lab fix" or "Lab addition", so `git log -p stores/ucp_store` shows
  exactly what differs from Google. Our own files are listed in its `NOTICE.md`.
- `supervisor.py` (ours) keeps a seeded `template/` copy of the databases and
  resets `live/` from it in about a second. Store on :8182, reset on :8183.
- `seed/<store>/` holds each store's catalog as CSVs. Prices are in cents.
- The store is the authority on its own prices: scenarios follow its pricing
  rules (e.g. percentage discounts include shipping).
- Any change to store behaviour must keep Google's conformance suite passing
  (`docker compose run --rm conformance`) and be recorded in `docs/findings.md`.
- **Misbehave switch** (Stage 5, D29): the harness POSTs a scenario's
  `[misbehave]` note to `:8183/misbehave`; the supervisor checks it and saves
  `live/misbehave.json` (a reset wipes it). `misbehave.py` fires the trick once
  on its checkout event (`checkout_created`, `first_ready`) and records
  `fired_at`. Known tricks: `price_change`.
- Reads re-price from the catalog, and `complete` refuses a changed total with
  `409 PRICE_CHANGED` (D30).
