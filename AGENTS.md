# AGENTS.md — GMGN Monitor

## Project purpose

Build a GMGN-oriented sweep-chain intelligence system. The current goal is **monitoring and evidence collection**, not automated trading.

## Safety red lines

The following must never be added without explicit human approval and a separate security review:

- Wallet signing code.
- Private key or mnemonic handling.
- Order placement or auto-buy/auto-sell logic.
- Telegram bot token storage or message sending.
- Live trading API integration.

The automation gate (`config/automation_gate.json`) must remain `Status: blocked` by default.

## Workflow conventions

1. **Tests first**: run `python3 -m unittest discover -s tests` after any code change.
2. **Verify after changes**: run `python3 -m gmgn_monitor.verify` to regenerate pipeline artifacts and append history.
3. **Doctor check**: run `python3 -m gmgn_monitor.doctor` for a lightweight health check.
4. **Atomic writes**: generated files must be written through `gmgn_monitor.file_io.atomic_write_text` or `atomic_write_jsonl` to avoid partial-read races.
5. **No secrets in repo**: never commit API keys, tokens, cookies, or `.env` files.

## Code style

- Python 3.10+ with `from __future__ import annotations`.
- Prefer `pathlib.Path` over string paths.
- Use shared utilities in `gmgn_monitor.serialization` and `gmgn_monitor.time_utils` for JSON loading and timestamp parsing.
- Keep modules focused; put reusable loaders in `gmgn_monitor.sources`.

## Verification expectations

The default fixture set (`fixtures/candidates.jsonl`) must produce:

```text
summary: alert=1 watch=1 reject=2
```

The automation gate report must contain `Status: blocked`.

## Useful commands

```bash
# Run all tests
python3 -m unittest discover -s tests

# Full verification chain
python3 -m gmgn_monitor.verify --report data/verification_report.json --history data/verification_history.jsonl

# Health check
python3 -m gmgn_monitor.doctor

# Replay fixture candidates
python3 -m gmgn_monitor.replay --input fixtures/candidates.jsonl --output data/candidate_events.jsonl --config config/thresholds.json
```
