# Status

Last updated: 2026-10-28.

| Stage | Status |
| --- | --- |
| 1. Set up | ✅ Repo, spec pinned, free models answer |
| 2. One fake store | ✅ Passes Google's conformance (76 passed, 1 skipped); manual checkout works |
| 3. Test lab without AI | ✅ 10 scenarios, grader proven with deliberate bugs |
| 4. First AI run | ✅ Nemotron 5/7 graded, 0 unsafe; failures read (F1–F3). Full rerun with briefing v2 still open |
| 5. Store problems | Next |
| 6. Network and multi-store problems | — |
| 7. Trustworthy numbers | — |
| 8. Compare models, safety rules | — |
| 9. Write up and share | — |

## Open items

- Rerun all 10 scenarios with briefing v2 and nudges (D22): **qwen3:8b**
  (local), then **Nemotron** and **Gemini** when free capacity allows.
  Gemini's run on 2026-10-26 was all ERROR (free tier overloaded).
- Tighten scenario 008 so doing nothing can't pass it.
- Stage 5 design so far: price change early and late; saved cart shows the
  saved price; Option 2 applies only when the AI pauses a checkout to ask
  about a problem; approval message must show the new total in any format.
- Watch upstream issue
  [samples#262](https://github.com/Universal-Commerce-Protocol/samples/issues/262) (F1).
- Check the discount-includes-shipping observation against the UCP discount
  spec before reporting it.

## Results so far

| Date | Run | Model | Briefing | Result |
| --- | --- | --- | --- | --- |
| 2026-10-26 | `20261026T152907Z` | nvidia/nemotron-3.5-super-vl:free | v1 | 5 pass, 2 fail, 0 unsafe, 3 error (daily limit) |
| 2026-10-26 | `20261026T164116Z` | gemini-3.8-flash | v2 | 10 error (provider overloaded) |
| 2026-10-26 | `20261026T220754Z` | qwen3:8b (Ollama) | v2 | 2 pass, 7 fail, 0 unsafe, 1 error (local timeout) |
