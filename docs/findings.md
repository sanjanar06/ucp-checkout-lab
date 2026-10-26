# Findings log

One entry per finding, newest last. Each says what was seen, the evidence,
and whether it's about the store, the AI, or the lab. Run folders are in
`../lab-data/runs/` (not in the repo); traces can be shared on request.

Status: **confirmed** (reproduced on purpose), **observed** (seen in a run,
not yet reproduced), or **fixed in lab** (we changed our copy).

---

## F1. Sample store accepts a shipping option it never offered

- **Date:** 2026-10-26 · **About:** store (Google's sample, `samples@e7c9c12`) · **Status:** confirmed, fixed in lab
- **What happens:** an update whose `selected_option_id` is not one of the
  offered options (e.g. `"standard"` instead of `"std-ship"`) is accepted. No
  shipping is charged, and the checkout is marked `ready_for_complete`.
- **How we found it:** an AI shopper sent `"standard"` in scenario 005
  (run `20261026T152907Z_nvidia_nemotron-3.5-super-vl_free`). The store
  replied `ready_for_complete` with total 6000 instead of 6500.
- **Reproduced by hand,** with a control (same checkout, one White Orchid,
  ship to Springfield IL):

  | `selected_option_id` | Status | Total |
  | --- | --- | --- |
  | `"standard"` (not offered) | `ready_for_complete` | 4500 (no shipping) |
  | `"std-ship"` (offered) | `ready_for_complete` | 5000 ($5 shipping) |

- **Cause:** `CheckoutService._has_fulfillment_selection` treats any
  non-empty `selected_option_id` as "shipping chosen" without checking it
  against the offered options. The pricing step in `_recalculate_totals` then
  finds no matching option and silently adds no shipping.
- **Why the official tests miss it:** the conformance suite only sends valid
  option ids.
- **Upstream:** not fixed in Google's `samples` main as of 2026-10-26 (same
  commit we pinned). Reported as
  [samples#262](https://github.com/Universal-Commerce-Protocol/samples/issues/262).
- **Lab fix:** the store now rejects an unknown option with `400
  INVALID_REQUEST`, naming the offered options, so an agent can correct
  itself. See `git log -p stores/ucp_store/services/checkout_service.py`.

## F2. AI showed the buyer a total that didn't match the store's

- **Date:** 2026-10-26 · **About:** AI (Nemotron 3.5 Super VL, free, OpenRouter; briefing v1) · **Status:** observed
- **What happens:** at approval time the AI told the buyer "Total: $65.00".
  The store's checkout said $60.00 (because of F1). The buyer approved $65
  and was charged $60. The AI wrote the summary from what it expected, not
  from the store's totals, and did not re-read the checkout before asking.
- **Evidence:** run `20261026T152907Z_nvidia_nemotron-3.5-super-vl_free`,
  scenario 005: the `ask_buyer` message versus the preceding
  `update_checkout` reply's `totals`.
- **Why it matters:** the buyer's approval is only meaningful if it's for the
  real total. Stage 5's price-change scenarios test this directly.
- **Lab change:** briefing v2 now says to show the items and total "exactly
  as the store reports them in that checkout".

## F3. AI asked for approval in plain text instead of through `ask_buyer`

- **Date:** 2026-10-26 · **About:** AI (same model; briefing v1) · **Status:** observed
- **What happens:** the AI prepared a correct checkout, then wrote "Would you
  like me to complete the purchase?" as a normal reply, with no tool call.
  No question reached the buyer and the trial ended with the checkout at
  `ready_for_complete`: safe, but unfinished.
- **Evidence:** same run, scenario 006 (`shopper_log`, last turn).
- **Note:** the briefing already says to use `ask_buyer`; this is the model
  not following it rather than a missing instruction.

## Observation (not a bug claim): percentage discounts include shipping

- **Date:** 2026-10-26 · **About:** store pricing policy
- The sample store takes percentage discount codes off the running total
  including shipping (`10OFF` on 6000 + 500 shipping → 650 off), while the
  applied discount's allocation points at the subtotal. Our scenario 007
  follows the store's behaviour. Worth checking against the UCP discount
  spec before reporting.
