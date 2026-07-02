# GMGN Sweep-Chain Intelligence System Spec

## Final Goal

Build a GMGN-oriented sweep-chain intelligence system that discovers, filters, scores, alerts, and reviews meme-token opportunities before any trading automation is considered.

The system must be built in phases. The first production goal is not auto-buying. The first goal is to create a reliable monitoring and evidence pipeline that can answer whether the signals have positive expected value after fees, priority fees, slippage, and failed exits.

## Operating Principle

Do not build a profit-seeking auto-trader first. Build an intelligence system first.

The system should make trading slower and more selective at the beginning:

- Record every candidate signal.
- Explain why it was selected.
- Track what happened after the alert.
- Reject unsafe tokens before any human decision.
- Keep trade execution manual until signal quality is proven.

## Loop Engineering Plan

Goal: reach a verified monitoring-only Phase 1 where new token and wallet signals can be collected, scored with explicit rules, written to durable storage, and sent as alerts without placing trades.

Trigger: one-shot Codex iterations, later convertible to a scheduled runner or daemon.

Isolation: single repository for now. No parallel agents should edit the same files until an application skeleton exists.

Memory: `LOOP_STATE.md`.

Maker/checker split:

- Maker: implementation iteration creates or modifies the smallest scoped artifact.
- Checker: each iteration must verify by command output, schema validation, sample data replay, tests, or a documented manual review checklist.

Stop condition for Phase 1:

- The system can ingest at least one configured source or replay fixture.
- Each candidate produces a structured record.
- Each record includes risk flags, score inputs, and alert decision.
- Alerts are dry-run or monitor-only.
- No private keys, wallet signing, or order placement code exists.

## Phased Build Plan

### Phase 1: Monitor Only, No Trading

Purpose: discover and record candidate tokens or wallets without placing trades.

Scope:

- New token monitoring.
- Smart wallet or KOL wallet monitoring.
- Token safety metadata collection.
- Candidate scoring.
- Telegram or console alerting.
- Durable event log for later analysis.

Out of scope:

- Auto-buy.
- Auto-sell.
- Private key storage.
- Wallet signing.
- Copy-trade execution.
- Any strategy that requires live capital.

Required data fields for each candidate:

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
- `score`
- `decision`
- `reasons`

Initial decision values:

- `reject`: unsafe, incomplete, or below threshold.
- `watch`: interesting but missing confirmation.
- `alert`: passes monitor-only threshold.

Phase 1 acceptance criteria:

- A fixture or live source can create candidate records.
- Candidate records are stored as JSONL or SQLite rows.
- Risk checks can reject unsafe records before alerting.
- Alert output includes score, decision, and top reasons.
- A replay command can recompute decisions from stored data.
- The repository contains no trading execution or private-key code.

### Phase 2: Scoring System

Purpose: convert raw monitoring signals into a more selective ranking system.

Scope:

- Weighted scoring rules.
- Configurable thresholds.
- Score explanations.
- False-positive review workflow.
- Daily and weekly summary reports.

Acceptance criteria:

- At least 200 recorded candidates can be replayed.
- Score distribution and later price outcomes can be compared.
- Rules can be adjusted without rewriting code.

### Phase 3: Human-Confirmed Semi-Automation

Purpose: reduce manual error without giving the system authority to buy automatically.

Scope:

- Human confirmation before any trade.
- Pre-filled trade plan.
- Stop-loss and take-profit plan generation.
- Daily loss limit tracking.
- Manual execution checklist.

Acceptance criteria:

- Every proposed trade has a written reason, invalidation rule, and exit plan.
- The system blocks proposals when daily risk limits are exceeded.

### Phase 4: Execution Layer Evaluation

Purpose: decide whether execution should use GMGN, Axiom, Trojan, direct routing, or another path.

Scope:

- Fee comparison.
- Latency comparison.
- Slippage and failed transaction tracking.
- Custody and private-key risk review.

Acceptance criteria:

- Execution choice is based on measured cost and reliability, not marketing claims.
- No production signing key is introduced without a separate security review.

### Phase 5: Limited Automation Only If Proven

Purpose: introduce constrained automation only after signal quality and risk controls are proven.

Scope:

- Tiny-size testing only.
- Hard daily loss limits.
- Kill switch.
- Mandatory logs.
- No martingale, DCA into failing meme tokens, or unlimited retry loops.

Acceptance criteria:

- Backtest and paper/live shadow results show positive expectancy after all costs.
- Manual review confirms the automation cannot exceed defined risk limits.

## Initial Risk Rules

Reject a candidate if any of these are true:

- Honeypot risk is present.
- Blacklist risk is present.
- Mint or freeze authority is not renounced when the chain requires that check.
- Top 10 holder concentration exceeds the configured threshold.
- Developer or related wallets hold more than the configured threshold.
- LP is not burned, locked, or otherwise explainably safe.
- Required fields are missing.

Default thresholds for Phase 1 should be conservative:

- Top 10 holders: reject above 30%.
- Insider or rat wallets: reject above 20%.
- Dev holding: reject above 5% unless explicitly classified as safe.
- Minimum liquidity: require configuration per chain.
- Minimum transaction activity: require configuration per chain.

## Data Source Strategy

Preferred order:

1. Official or documented APIs where available.
2. Read-only public endpoints.
3. Replay fixtures captured manually.
4. Browser scraping only if the data is not otherwise available and the route is stable.

The first implementation should work with fixtures even if live API access is unavailable. This prevents the project from being blocked by API keys or rate limits.

## Security Constraints

- Do not store private keys in this repository.
- Do not add wallet signing in Phase 1 or Phase 2.
- Do not commit API keys, Telegram bot tokens, or cookies.
- Keep `.env` files out of version control if an application skeleton is added.
- Any future execution component must be isolated from monitoring and scoring.

## Verification Strategy

Every iteration must include at least one verification step:

- Markdown spec review for planning-only changes.
- JSON schema validation for candidate records.
- Unit tests for scoring rules.
- Fixture replay for ingestion and alert decisions.
- Dry-run alert output review.
- Diff review to confirm no trading code was introduced before approved phases.

## Phase 1 First Step Completed

This spec defines the monitor-only system boundary, phase sequence, acceptance criteria, initial risk rules, and loop state location. The next implementation step is to create the Phase 1 application skeleton with fixture-based ingestion, structured candidate records, and a dry-run alert path.
