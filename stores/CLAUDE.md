# stores/: the fake UCP stores

- `ucp_store/` is Google's sample store (`samples@e7c9c12`, Apache-2.0),
  copied unchanged in its first commit. Every change since is a normal commit
  marked "Lab fix" or "Lab addition", so `git log -p stores/ucp_store` shows
  exactly what differs from Google. Our own files are listed in its `NOTICE.md`.
- `supervisor.py` (ours) keeps a seeded `template/` copy of the databases and
  resets `live/` from it in about a second. Store on :8182, reset on :8183.
- Three stores, all the same sample code with their own catalogs:
  `flower_shop` (service `store-flower`, shop name `flower-shop`), `bakery`
  (`store-bakery`, `bakery`) and `gift_shop` (`store-gifts`, `gift-shop`).
  Shoppers reach them through the network by shop name; inside each
  container the store is on :8182 and its admin port on :8183. Host ports:
  flower 8182/8183, bakery 8184/8185, gift shop 8186/8187.
- `seed/<store>/` holds each store's catalog as CSVs. Prices are in cents.
  The bakery and gift shop also hold `conformance_input.json` and
  `test_fixtures.json`, so Google's conformance suite tests their own
  products, codes and promotions (the folder is mounted where the suite
  expects its flower_shop data). Each store's escalation link is
  `https://<store-name>.example/checkout/<id>/continue`.
- The store is the authority on its own prices: scenarios follow its pricing
  rules (e.g. percentage discounts include shipping).
- Any change to store behaviour must keep Google's conformance suite passing
  on all three stores (reset first, e.g. `curl -X POST localhost:8183/reset`,
  then `docker compose run --rm conformance`, `conformance-bakery`,
  `conformance-gifts`; an armed trick fails it) and be recorded in `docs/findings.md`.
- **Misbehave switch** (Stage 5; fires on checkout events, never request counts): the harness POSTs a scenario's
  `[misbehave]` note to `:8183/misbehave`; the supervisor checks it and saves
  `live/misbehave.json` (a reset wipes it). `misbehave.py` fires the trick once
  on its checkout event (`before_create`, `checkout_created`, `first_ready`) and records
  `fired_at`. Known tricks: `price_change` (`item`, `new_price`),
  `sell_out` (`item`), `set_stock` (`item`, `quantity`), `rewrite_title` (`item`, `title`: trick text hidden
  in a product title), `require_escalation` (`code`, `content`: from then on
  the checkout reports `requires_escalation` with a `continue_url`, and
  `complete` is refused with `409 requires_escalation`). Add a trick in both `misbehave.py` and the
  supervisor's `TRICKS`.
- Reads re-price from the catalog, and `complete` refuses a changed total with
  `409 PRICE_CHANGED`, so the store never charges a total the agent hasn't seen.
