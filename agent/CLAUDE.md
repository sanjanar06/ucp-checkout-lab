# agent/: the shoppers

| File | What it is |
| --- | --- |
| `ucp_client.py` | Sends UCP requests to one store; records every request and reply in `transcript` (the trial's timeline). A dropped connection gives status `None` and an `error` (the AI sees "no reply from the store") |
| `buyer.py` | The pretend human. `Buyer.ask()` answers from the scenario's `buyer_approves` and writes the question into the timeline. Says no when the question mentions a scenario's unwanted word and the store's latest checkout has one too. `Buyer.pay()` is the wallet: attaches the saved card (`WALLET_CARD`) and, with the approval check on, refuses unapproved totals |
| `scripted_shopper.py` | Non-AI shopper with fixed steps (re-reads the checkout before asking). `--bug` makes it misbehave on purpose so we can prove the grader catches it |
| `ai_shopper.py` | AI shopper: `BRIEFING` (the system prompt), seven `TOOLS`, and the agent loop. A cart across stores adds a `store` field to each store tool (`tools_for`); with one store the tools and task message are unchanged |
| `llm.py` | Calls a model (Ollama, OpenRouter, Gemini); retries busy replies; raises `ProviderUnavailable` |

Rules:
- The AI only *asks* for tools; our code runs them. It never holds card details.
- Every "complete" goes through `Buyer.pay()` (the wallet attaches the card).
  By default it does **not** block unapproved purchases: we measure what the
  AI does on its own. With `--approval-check` (Stage 8) the wallet pays only a
  total the buyer said yes to, for that checkout, as the store last reported
  it; otherwise it records `wallet_refused` and tells the shopper to ask
  again. It's on the buyer's side, so the stores stay Google's code.
- The briefing is the user's text. Any change bumps `BRIEFING_VERSION` with a
  dated note, because results from different briefings aren't comparable. No
  warning about trick text (Stage 5 tests whether the AI resists on its own).
- The trial ends when the AI replies without a tool request; that reply is
  its final message to the buyer (recorded in the timeline). No nudges: a model that stops early has stopped.
- Keep the agent basic: it's the thing being tested. Tune only on `dev` scenarios.
