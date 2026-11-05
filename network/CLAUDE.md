# network/: the network between shoppers and stores

`proxy.py` (service `network`) sits between every shopper and every store.
Shoppers use shop names (`http://flower-shop:8182`); the Host header picks
the store container. It passes traffic through unchanged unless a scenario's
`[network]` table arms a fault.

- Faults fire on a checkout event (`on`: `discover`, `create`, `get`,
  `update`, `complete`, `cancel`), once, never on a request count.
- `lost_reply`: the store gets the request and acts on it; the reply never
  reaches the shopper (the connection closes with no answer).
- `duplicate`: the request reaches the store twice (same idempotency key);
  the shopper gets the second reply. A store check, not an AI test.
  `on = "all"` doubles every request.
- `other_buyer` (needs `details`: items, buyer, ship_to, shipping_option):
  just before the shopper's request reaches the store, another buyer (the
  honest scripted shopper) places a real order there. Pair it with the
  store trick `set_stock` to make it the last unit.
- Admin port 8191: `POST /reset`, `POST /fault`, `GET /log`. A malformed fault
  is rejected (400) and the harness stops the run.
- The stores stay Google's code. Network faults belong here, not in the store.
- Adding a store: add its shop name to `ROUTES` and to the `network` service's
  aliases in `compose.yaml`.
