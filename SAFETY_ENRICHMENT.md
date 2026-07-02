# Safety Enrichment Plan

Phase 1 can score fixtures and saved read-only source payloads, but live market-data sources are not enough to produce alertable candidates.

DEX Screener search provides useful market fields such as token address, liquidity, FDV, 5-minute volume, and transaction counts. It does not provide enough contract and holder safety data for this system's alert threshold.

## Required Safety Inputs

The system must not produce live `alert` decisions unless these fields are supplied by a trusted safety-enrichment source:

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

## Source Categories

Acceptable source categories:

- Contract scanners that expose read-only risk flags.
- Holder distribution APIs.
- LP lock/burn verification APIs.
- Internal fixture records captured from manual GMGN review.
- Browser-derived read-only snapshots, if the data is stable and manually verified.

Not acceptable as safety enrichment:

- KOL posts.
- Trending lists.
- Market cap alone.
- Liquidity alone.
- Volume or transaction count alone.
- Any source requiring wallet signing.
- Any source requiring private keys.

## Enrichment Interface

A future enrichment component should accept a candidate dictionary and return a new candidate dictionary with safety fields filled or preserved.

Rules:

- It must not mutate the original candidate in place.
- It must not place trades.
- It must not read private keys.
- It must not reduce conservative safety defaults unless the source provides explicit evidence.
- It must record the enrichment source in a future `enrichment_sources` field.

## Fallback Behavior

If enrichment fails or is incomplete:

- Keep unknown concentration fields at `100.0`.
- Keep authority checks as `false`.
- Keep risk flags as `true`.
- Candidate remains `reject`.

## Phase 2 Gate

Before live candidates may become `alert`, the project needs:

- At least one implemented safety-enrichment adapter.
- Tests proving incomplete safety data remains rejected.
- Tests proving enriched safe data can become `watch` or `alert`.
- Documentation of the enrichment source and its limitations.
- At least 200 candidate records reviewed with outcome fields.

