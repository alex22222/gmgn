# GMGN Execution Layer Evaluation

This report is evaluation-only. It does not integrate with wallets, signing, or trading APIs.

## Ranked Venues

| Rank | Venue | Role | Fee % | Latency | Custody Risk | Measurement |
|---:|---|---|---:|---|---|---|
| 1 | Axiom | execution_terminal | 0.95 | sub_second_claimed | external_execution_surface | needs_live_measurement |
| 2 | GMGN | data_and_execution | 1.0 | seconds | external_execution_surface | needs_live_measurement |
| 3 | Trojan | execution_bot | 1.0 | sub_two_second_claimed | bot_wallet_surface | needs_live_measurement |
| 4 | DirectRouting | custom_execution | 0.0 | unknown_until_built | self_custody_engineering_risk | not_implemented |

## Notes

- Axiom: Candidate execution venue; requires measured fill quality and failure-rate tracking.
- GMGN: Useful as data discovery layer; execution cost and latency should be measured before use.
- Trojan: Candidate execution venue; requires custody and wallet-separation review.
- DirectRouting: Not available yet; would require a separate security review before any signing code.

## Phase 4 Gate

No venue should be selected for real execution until fill quality, failed transaction rate, slippage, fee cost, and custody risk are measured with non-trading or paper workflows. Not-implemented venues must remain below measured or measurement-ready venues regardless of nominal fee.
