# AGENTS.md — GMGN Monitor

## Project purpose

Build a GMGN-oriented sweep-chain intelligence system. The project has progressed
from pure monitoring to **Phase 2 micro live trading (`tiny_real`)** under
strict limits and continuous review.

Current operational mode:

- **Monitor-first**: all signals are still scored, logged, and reviewed.
- **Tiny exposure**: single trade ≤ 0.01 SOL, daily loss limit ≤ 0.03 SOL.
- **Human kill switch**: the automation gate can be reverted to `blocked` at any
  time by setting `config/automation_gate.json` → `"force_open": false`.
- **Audit trail**: every trade intention and rejection is written to `data/` and
  `logs/`.

## Safety red lines

The following must never be added or enabled without explicit human approval and
a separate security review:

- Unlimited or un-audited wallet signing code.
- Private key or mnemonic handling outside `~/.config/gmgn/` with permissions
  `600`.
- Order placement that bypasses the automation gate, risk limits, or
  `auto_confirm=false`.
- Telegram bot token storage or message sending.
- Live trading API integration without the automation gate set to
  `auto_trading_enabled`.

The automation gate (`config/automation_gate.json`) defaults to
`Status: auto_trading_enabled` for the current `tiny_real` phase. Reverting to
`Status: blocked` is the emergency stop.

## Workflow conventions

1. **Tests first**: run `python3 -m unittest discover -s tests` after any code
   change.
2. **Verify after changes**: run `python3 -m gmgn_monitor.verify` to regenerate
   pipeline artifacts and append history.
3. **Doctor check**: run `python3 -m gmgn_monitor.doctor` for a lightweight
   health check.
4. **Atomic writes**: generated files must be written through
   `gmgn_monitor.file_io.atomic_write_text` or `atomic_write_jsonl` to avoid
   partial-read races.
5. **No secrets in repo**: never commit API keys, tokens, cookies, or `.env`
   files.

## Code style

- Python 3.10+ with `from __future__ import annotations`.
- Prefer `pathlib.Path` over string paths.
- Use shared utilities in `gmgn_monitor.serialization` and
  `gmgn_monitor.time_utils` for JSON loading and timestamp parsing.
- Keep modules focused; put reusable loaders in `gmgn_monitor.sources`.

## Verification expectations

The default fixture set (`fixtures/candidates.jsonl`) must produce:

```text
summary: alert=1 watch=1 reject=2
```

The automation gate report must contain `Status: auto_trading_enabled` for the
`tiny_real` phase.

## Tiny real limits (Phase 2)

| Limit | Value | Rationale |
|---|---|---|
| Max single trade | 0.01 SOL | Roughly $2; limits per-trade damage. |
| Max daily loss | 0.03 SOL | Roughly $6; hard stop for the day. |
| Max total positions | 3 | Avoid over-concentration in meme tokens. |
| Default stop loss | -40% | Cut losers quickly. |
| Default slippage | 2% / max 5% | Control execution cost. |
| Auto confirm | allowed for tiny size | Only when gate is open and limits are met. |

Any change to these limits requires a code change, a verification run, and a
manual note in `data/trading_log.jsonl` or `data/verification_history.jsonl`.

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

# Emergency stop: revert gate to blocked
python3 -m gmgn_monitor.automation_gate --config config/automation_gate.json --output data/automation_gate.md
```
