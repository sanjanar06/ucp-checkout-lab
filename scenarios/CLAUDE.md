# scenarios/: one test per file

- `dev/` — scenarios we may look at and tune on. `heldout/` (from Stage 5)
  — never tuned on, never published.
- Format (TOML): `id`, `category`, `kind` (`regression` must always pass;
  `capability` is hard on purpose), `[start]` (store, reset),
  `[instruction]` (`text` for the AI, `buyer_approves`, `[instruction.details]`
  for the scripted shopper), `[expected]` (the grader's checks).
- Expect only what must be true, never random values like order ids. Count
  orders so double orders are caught.
- Work out expected totals by hand from the seed CSVs, then confirm with the
  scripted shopper. If they disagree, find out why before changing either.
- Buyer declines → expected `orders = 0` and `checkout_status = "canceled"`.
