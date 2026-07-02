# GMGN Monitor Schema

This document defines the Phase 1 monitor-only data contract.

## Candidate Input Record

Candidate inputs are raw opportunities from fixtures or read-only source adapters. Each record is one JSON object.

Required string fields:

- `chain`: chain identifier, for example `solana`, `base`, or `bsc`.
- `token_address`: token contract or mint address.
- `symbol`: token symbol.
- `detected_at`: ISO-like detection timestamp.
- `source`: source identifier, for example `fixture:new_token` or `dexscreener:search`.

Required numeric fields:

- `liquidity`: liquidity value in the source adapter's normalized unit.
- `market_cap`: market cap or FDV when market cap is unavailable.
- `volume_1m`: 1-minute volume, or `0.0` when unavailable.
- `volume_5m`: 5-minute volume.
- `tx_count_1m`: 1-minute transaction count, or nearest conservative proxy.
- `holder_count`: holder count, or `0` when unavailable.
- `top10_holder_percent`: top 10 holder concentration.
- `dev_holding_percent`: developer or related wallet holding concentration.
- `insider_or_rat_percent`: insider, rat wallet, or suspicious cluster concentration.
- `bundle_buy_percent`: bundled buy or suspicious launch buy concentration.

Required boolean safety fields:

- `mint_renounced`
- `freeze_renounced`
- `lp_burned_or_locked`
- `honeypot_risk`
- `blacklist_risk`
- `tax_risk`

## Scored Output Record

Replay writes all candidate input fields plus:

- `score`: integer score from the current scoring rules.
- `decision`: one of `reject`, `watch`, or `alert`.
- `reasons`: ordered list of reasons for the score or hard rejection.
- `outcome`: empty review object for later manual outcome tracking.

## Outcome Object

Outcome fields are for review only. They must not influence Phase 1 scoring.

- `reviewed`: boolean review status.
- `reviewed_at`: review timestamp or `null`.
- `price_change_5m_percent`: later 5-minute price change or `null`.
- `price_change_30m_percent`: later 30-minute price change or `null`.
- `price_change_24h_percent`: later 24-hour price change or `null`.
- `max_drawdown_percent`: observed drawdown or `null`.
- `notes`: human review notes.

Outcome review JSONL records must include a non-empty `token_address`, and each token may appear at most once per review file. If present, `reviewed` must be boolean, `reviewed_at` must be an ISO timestamp or `null`, price/drawdown fields must be finite numbers or `null`, and `notes` must be a string.

## Unsafe Defaults

If a source adapter cannot provide a safety field, it must map the field to the conservative unsafe value:

- Concentration fields should default to `100.0`.
- Authority checks should default to `false`.
- Risk flags should default to `true`.

This is intentional. Unknown safety is treated as unsafe so incomplete live data cannot produce `alert` decisions before a safety-enrichment source is added.

## Validation Rules

Validation happens before scoring:

- Missing required fields fail replay.
- Wrong primitive types fail replay.
- Required string fields must be non-empty after trimming whitespace.
- `detected_at` must be an ISO timestamp; `Z` UTC suffixes are accepted.
- Numeric fields must be JSON numbers; JSON booleans are not accepted as numbers.
- Numeric fields must be finite; `NaN` and infinity are rejected.
- Numeric fields must be non-negative.
- Count fields such as `tx_count_1m` and `holder_count` must be whole-number values.
- Percentage fields must be between `0` and `100`, inclusive.
- Malformed JSONL fails replay before alerts are generated.
- Each non-empty JSONL line must be a JSON object.

## Thresholds

Thresholds live in `config/thresholds.json`.

- `default` applies to every chain.
- `chains` overrides default values by chain.
- Unknown threshold fields fail fast.
- Threshold config sections must be JSON objects.
- Threshold values must be finite, non-negative numbers.
- Percentage threshold values must be at most `100`.
- `alert_score` must be greater than or equal to `watch_score`.
