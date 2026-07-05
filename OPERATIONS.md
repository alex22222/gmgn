# GMGN Monitor Operations

This project implements Phases 1–5 of the GMGN sweep-chain intelligence system spec. Trading automation remains blocked by the Phase 5 automation gate.

The system reads local candidate fixtures, validates required fields, applies conservative risk checks, writes scored JSONL events, and generates human-review outputs. It does not send Telegram messages, place orders, sign transactions, or read private keys.

## Safety Boundary

Allowed in Phase 1:

- Read local fixture data.
- Validate candidate records.
- Score candidates as `reject`, `watch`, or `alert`.
- Write JSONL event logs.
- Generate markdown summaries.
- Generate Telegram-ready dry-run text files.

Not allowed in Phase 1:

- Auto-buy.
- Auto-sell.
- Wallet signing.
- Private-key storage.
- Telegram network sending.
- Trading API calls.
- Copy-trade execution.

## Run Tests

```bash
python3 -m unittest discover -s tests
```

## Run Local Dashboard

```bash
python3 -m gmgn_monitor.dashboard
```

The dashboard binds to `127.0.0.1` and starts at port `8765`, automatically selecting the next available port if the preferred port is occupied. It exposes only fixed local actions for status, verification, pipeline generation, replay, dry-run alert text, and human-confirmed trade-plan generation. It does not accept arbitrary shell commands and does not execute trades.

## Run Full Local Verification

```bash
python3 -m gmgn_monitor.verify
```

```bash
python3 -m gmgn_monitor.verify --json
```

```bash
python3 -m gmgn_monitor.verify --report data/verification_report.json
```

```bash
python3 -m gmgn_monitor.verify --report data/verification_report.json --history data/verification_history.jsonl
```

This command regenerates the local dry-run pipeline outputs, checks `config/verification_expectations.json`, runs the doctor checks, runs the unit tests, and runs the safety scan. It uses `data/verification.lock` to fail fast when another verification run is already active. With `--json`, lock conflicts also return a machine-readable failure object. The optional report file records the same verification status and step details as JSON, plus hashes of the threshold, risk, automation-gate, venue, expectation configuration files, generated pipeline artifacts, and a compact operational summary. Report loading rejects malformed JSON and non-object reports with explicit diagnostics. Doctor checks require those report fingerprint objects to exist and to cover the current generated config/artifact files. Report writes use temporary files followed by atomic replace. The optional history file appends each report as one JSONL record and flushes the append to disk.

Summarize local verification history:

```bash
python3 -m gmgn_monitor.history --input data/verification_history.jsonl
```

```bash
python3 -m gmgn_monitor.history --input data/verification_history.jsonl --json
```

```bash
python3 -m gmgn_monitor.history --input data/verification_history.jsonl --limit 5
```

```bash
python3 -m gmgn_monitor.history --input data/verification_history.jsonl --limit 5 --fail-on-any-failure
```

```bash
python3 -m gmgn_monitor.history --input data/verification_history.jsonl --limit 5 --fail-on-any-failure --require-complete-steps
```

```bash
python3 -m gmgn_monitor.history --input data/verification_history.jsonl --limit 5 --fail-on-any-failure --require-complete-steps --require-valid-timestamps
```

The history summary reports record count, failure count, incomplete step record count, status-step mismatch count, invalid timestamp count, future timestamp count, out-of-order timestamp count, consecutive failure count, last successful verification time, status counts, per-step failure counts, latest step statuses, and the latest operational summary. History JSONL loading rejects malformed JSON and non-object records with line-number diagnostics. Use `--limit` to summarize only the most recent records without modifying the history file. Use `--fail-on-any-failure` for monitoring windows where any failed record should make the command exit non-zero. Use `--require-complete-steps` when every selected history record must contain the complete ok verification step set and a status that matches its step results. Use `--require-valid-timestamps` when every selected history record must have a valid, non-future `generated_at` timestamp and non-decreasing timeline order.

## Run Health Check

Read local status without regenerating outputs or running tests:

```bash
python3 -m gmgn_monitor.status
```

```bash
python3 -m gmgn_monitor.status --json
```

```bash
python3 -m gmgn_monitor.status --max-report-age-minutes 1440
```

```bash
python3 -m gmgn_monitor.status --max-report-age-minutes 1440 --history-limit 5 --fail-on-any-history-failure
```

```bash
python3 -m gmgn_monitor.status --max-report-age-minutes 1440 --history-limit 5 --fail-on-any-history-failure --require-history-complete-steps --require-history-valid-timestamps --require-report --require-history-current --fail-on-future-report --fail-on-stale-lock --fail-on-stale-temp-artifacts
```

```bash
python3 -m gmgn_monitor.doctor
```

```bash
python3 -m gmgn_monitor.doctor --json
```

The status command is read-only and can enforce a maximum verification report age when `--max-report-age-minutes` is set. It can also inspect a recent history window with `--history-limit`, fail if any selected record failed with `--fail-on-any-history-failure`, fail if any selected history record lacks the complete ok verification step set or has a status that contradicts its step results with `--require-history-complete-steps`, fail if any selected history record has an invalid, future, or out-of-order `generated_at` timestamp with `--require-history-valid-timestamps`, require an ok verification report with a valid, non-future timestamp and complete ok verification step set with `--require-report`, require the current report status, steps, operational summary, and config/artifact fingerprints to match the latest history record with `--require-history-current`, fail on a future-dated verification report with `--fail-on-future-report`, fail on a stale `data/verification.lock` with `--fail-on-stale-lock`, and fail on stale atomic-write temp files under `data/` with `--fail-on-stale-temp-artifacts`. The doctor command checks required docs/configs, verification expectation config shape, fixture schema validity, complete generated pipeline outputs, generated JSONL/JSON parseability, generated event schema sanity, optional verification report/history parseability, verification report timestamp/step/status/operational-summary/fingerprint freshness, verification report consistency with the latest history record when both artifacts exist, verification history status/step/timestamp/operational-summary integrity, stale verification lock state, stale temp artifact state, required output content, and safety keywords in code/config/fixture directories. The generated automation gate must remain `Status: blocked`.

## Run Full Local Dry-Run Pipeline

This command runs replay, summary generation, Telegram dry-run text, optional outcome review, trade-plan generation, and automation gate evaluation. It writes generated artifacts through temporary files followed by atomic replace, reducing partial-read windows for concurrent health checks. It does not send messages or execute trades.

```bash
python3 -m gmgn_monitor.pipeline \
  --input fixtures/candidates.jsonl \
  --reviews fixtures/outcome_reviews.jsonl \
  --output-dir data/pipeline
```

## Replay Fixture Candidates

```bash
python3 -m gmgn_monitor.replay \
  --input fixtures/candidates.jsonl \
  --output data/candidate_events.jsonl \
  --config config/thresholds.json
```

Expected fixture summary:

```text
summary: alert=1 watch=1 reject=2
```

## Replay Chain Threshold Fixtures

```bash
python3 -m gmgn_monitor.replay \
  --input fixtures/chain_threshold_candidates.jsonl \
  --output data/chain_threshold_events.jsonl \
  --config config/thresholds.json
```

Expected fixture summary:

```text
summary: alert=2 watch=0 reject=0
```

## Generate Phase 2 Large Sample

```bash
python3 -m gmgn_monitor.sample_data \
  --count 200 \
  --output fixtures/large_sample_candidates.jsonl
```

Replay it:

```bash
python3 -m gmgn_monitor.replay \
  --input fixtures/large_sample_candidates.jsonl \
  --output data/large_sample_events.jsonl \
  --config config/thresholds.json \
  --summary-only
```

## Generate Daily Summary

```bash
python3 -m gmgn_monitor.report \
  --input data/candidate_events.jsonl \
  --output data/daily_summary.md
```

Output:

- `data/daily_summary.md`

The summary includes decision counts, chain counts, source counts, outcome review status, and top alert/watch candidates.

Generate a weekly summary from any accumulated event file:

```bash
python3 -m gmgn_monitor.report \
  --input data/large_sample_events.jsonl \
  --output data/weekly_summary.md \
  --title "GMGN Monitor Weekly Summary"
```

## Generate Telegram Dry-Run Messages

```bash
python3 -m gmgn_monitor.telegram_dry_run \
  --input data/candidate_events.jsonl \
  --output data/telegram_dry_run.txt
```

Output:

- `data/telegram_dry_run.txt`

This file is text only. It is meant for review and manual copy/paste. The command does not send messages and does not read Telegram tokens.

## Optional Read-Only DEX Screener Fetch

DEX Screener provides public read-only API endpoints documented at `https://docs.dexscreener.com/api/reference`. The adapter supports search results and the latest token profiles feed. It maps unknown safety fields to unsafe defaults, so fetched candidates should be expected to reject until another safety-enrichment source is added.

Fetch the latest token profiles from the live read-only API, enrich available market fields from token pairs, and store candidate JSONL:

```bash
python3 -m gmgn_monitor.dexscreener \
  --latest-profiles \
  --limit 10 \
  --output data/dexscreener_latest_profiles_candidates.jsonl
```

Then replay the latest-profile candidates:

```bash
python3 -m gmgn_monitor.replay \
  --input data/dexscreener_latest_profiles_candidates.jsonl \
  --output data/dexscreener_latest_profiles_events.jsonl \
  --config config/thresholds.json
```

Generate a review summary:

```bash
python3 -m gmgn_monitor.report \
  --input data/dexscreener_latest_profiles_events.jsonl \
  --output data/dexscreener_latest_profiles_summary.md \
  --title "DEX Screener Latest Profiles Summary"
```

Market search remains available:

```bash
python3 -m gmgn_monitor.dexscreener \
  --query "SOL" \
  --limit 5 \
  --output data/dexscreener_candidates.jsonl
```

Then replay the fetched candidates:

```bash
python3 -m gmgn_monitor.replay \
  --input data/dexscreener_candidates.jsonl \
  --output data/dexscreener_events.jsonl \
  --config config/thresholds.json
```

The DEX Screener adapter is read-only. It does not use API keys, wallets, or trading endpoints.

If local Python certificate verification fails, do not disable TLS verification. Use the checked-in sample payload tests until the local certificate store is fixed.

Offline adapter check from the checked-in sample payload:

```bash
python3 -m gmgn_monitor.dexscreener \
  --query "SOL" \
  --payload fixtures/dexscreener_search_sample.json \
  --limit 1 \
  --output data/dexscreener_candidates.jsonl
```

## Generated Files

- `data/candidate_events.jsonl`: scored events from `fixtures/candidates.jsonl`.
- `data/chain_threshold_events.jsonl`: scored chain-threshold fixture events.
- `data/daily_summary.md`: markdown review summary.
- `data/telegram_dry_run.txt`: Telegram-ready dry-run messages.
- `data/dexscreener_candidates.jsonl`: optional read-only DEX Screener candidate fixtures.
- `data/dexscreener_events.jsonl`: optional scored DEX Screener candidate events.
- `data/dexscreener_latest_profiles_candidates.jsonl`: live latest token profiles converted into conservative candidate fixtures.
- `data/dexscreener_latest_profiles_events.jsonl`: scored latest-profile candidate events.
- `data/dexscreener_latest_profiles_summary.md`: review summary for latest-profile candidate events.

## Add Fixture Records

Add one JSON object per line to a `.jsonl` fixture file.

See `SCHEMA.md` for the full input, scored output, and outcome schemas.

See `SAFETY_ENRICHMENT.md` before adding any live source that could produce alertable candidates.

Required fields:

- `chain`
- `token_address`
- `symbol`
- `detected_at`
- `source`
- `liquidity`
- `market_cap`
- `volume_1m`
- `volume_5m`
- `tx_count_1m`
- `holder_count`
- `top10_holder_percent`
- `dev_holding_percent`
- `insider_or_rat_percent`
- `bundle_buy_percent`
- `mint_renounced`
- `freeze_renounced`
- `lp_burned_or_locked`
- `honeypot_risk`
- `blacklist_risk`
- `tax_risk`

Schema failures stop replay before alerts are generated.

## Configure Thresholds

Edit `config/thresholds.json`.

- `default` applies to all chains.
- `chains` overrides default values for a specific chain.
- Unknown threshold fields fail fast during config loading.
- Threshold config sections must be JSON objects, values must be finite and non-negative, percentage thresholds cannot exceed `100`, and `alert_score` must be greater than or equal to `watch_score`.

Keep thresholds conservative until at least 200 candidates have been recorded and reviewed.

## Review Outcomes

Replay adds an empty `outcome` object to each scored event. These fields are for later manual review and do not affect scoring:

- `reviewed`
- `reviewed_at`
- `price_change_5m_percent`
- `price_change_30m_percent`
- `price_change_24h_percent`
- `max_drawdown_percent`
- `notes`

Do not use outcome fields as scoring inputs in Phase 1.

Apply outcome reviews from a separate JSONL file:

```bash
python3 -m gmgn_monitor.outcomes \
  --events data/candidate_events.jsonl \
  --reviews fixtures/outcome_reviews.jsonl \
  --output data/reviewed_candidate_events.jsonl
```

Then regenerate a summary from reviewed events:

```bash
python3 -m gmgn_monitor.report \
  --input data/reviewed_candidate_events.jsonl \
  --output data/reviewed_daily_summary.md
```

Generate score and outcome analysis:

```bash
python3 -m gmgn_monitor.analysis \
  --input data/reviewed_candidate_events.jsonl \
  --output data/outcome_analysis.md
```

## Generate Human-Confirmed Trade Plans

Trade plans are dry-run planning artifacts only. They do not execute trades.
The risk config must contain positive `daily_loss_limit_percent` and `max_single_position_percent` values, a negative `default_stop_loss_percent`, and non-empty `take_profit_steps` whose positive `sell_percent` values sum to `100`.

```bash
python3 -m gmgn_monitor.trade_plan \
  --input data/candidate_events.jsonl \
  --risk-config config/risk_limits.json \
  --daily-loss-percent 0 \
  --output data/trade_plans.json
```

If the daily loss limit is reached, proposal generation is blocked:

```bash
python3 -m gmgn_monitor.trade_plan \
  --input data/candidate_events.jsonl \
  --risk-config config/risk_limits.json \
  --daily-loss-percent 5 \
  --output data/trade_plans_blocked.json
```

## Generate Execution Layer Evaluation

Execution evaluation is dry-run analysis only. It does not connect to venues or execute trades.

```bash
python3 -m gmgn_monitor.execution_eval \
  --input config/execution_venues.json \
  --output data/execution_evaluation.md
```

## Evaluate Phase 5 Automation Gate

The automation gate does not enable trading. It checks whether limited automation may even be considered.

```bash
python3 -m gmgn_monitor.automation_gate \
  --config config/automation_gate.json \
  --output data/automation_gate.md
```
