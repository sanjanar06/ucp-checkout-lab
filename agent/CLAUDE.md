# agent/: the shoppers

| File | What it is |
| --- | --- |
| `ucp_client.py` | Sends UCP requests to one store; records every request and reply in `transcript` (the trial's timeline) |
| `buyer.py` | The pretend human. `Buyer.ask()` answers from the scenario's `buyer_approves` and writes the question into the timeline. Also the saved card (`WALLET_CARD`) |
| `scripted_shopper.py` | Non-AI shopper with fixed steps. `--bug` makes it misbehave on purpose so we can prove the grader catches it |
| `ai_shopper.py` | AI shopper: `BRIEFING` (the system prompt), seven `TOOLS`, and the agent loop |
| `llm.py` | Calls a model (Ollama, OpenRouter, Gemini); retries busy replies; raises `ProviderUnavailable` |

Rules:
- The AI only *asks* for tools; our code runs them. It never holds card details.
- `complete_checkout` deliberately does **not** block unapproved purchases: we
  measure what the AI does on its own. Code guardrails come in Stage 8.
- The briefing is the user's text. Any change bumps `BRIEFING_VERSION` with a
  dated note, because results from different briefings aren't comparable. No
  warning about trick text (Stage 5 tests whether the AI resists on its own).
- If the AI replies without a tool request, the loop sends up to `MAX_NUDGES`
  neutral nudges (`NUDGE`, clearly not from the buyer) before ending (D22).
  Each trial records how many it needed.
- Keep the agent basic: it's the thing being tested. Tune only on `dev` scenarios.
