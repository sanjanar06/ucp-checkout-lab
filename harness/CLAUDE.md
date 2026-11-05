# harness/: runs the lab

`run.py`, run as `docker compose run --rm lab [options]`. For each scenario:
reset the store (`POST :8183/reset`), run the shopper, grade, then write
`../lab-data/runs/<run_id>/<scenario>.json` (full trace) and a line in
`results.jsonl`. `run.json` records model, provider, briefing version and
settings.

- `STORES` maps a store name to its shop name, URL and reset port; add new
  stores there. A scenario uses one store (`[start] store`) or several
  (`[start] stores`); all its clients share one timeline, each event naming
  its store.
  Shoppers reach stores through the network proxy by shop name
  (`http://flower-shop:8182`). Before each scenario the harness resets the
  network, arms the scenario's `[network]` fault if any, and saves the
  network's log in the trace (`network`).
- Options: `--agent scripted|ai`, `--provider`, `--model`, `--only`, `--bug`,
  `--trials N` (trial-major order: all of trial 1 first), `--temperature
  default` (leave it to the model), `--max-cost` (stop once the run's model
  calls cost this much; default $3), `--resume RUN_ID` (reuse the run's
  settings, skip graded trials, retry ERRORs).
- The run stops after 3 provider errors in a row (daily quota used up): resume
  it later. Each summary line records `trial` and `duplicate_order`.
- `scripts/report.py` turns runs into pass@1, pass^k (95% bootstrap ranges
  over scenarios), UNSAFE, duplicates, cost and latency.
- Exit code is 0 only if every scenario passed.
