# GMGN Monitor

A monitor-first intelligence system for discovering, filtering, scoring, and reviewing meme-token opportunities before any trading automation is considered.

This repository implements the phased build plan described in `gmgn_system_spec.md`:

- **Phase 1**: Monitor only, no trading.
- **Phase 2**: Scoring system with configurable thresholds.
- **Phase 3**: Human-confirmed semi-automation (trade plans, daily loss limits).
- **Phase 4**: Execution layer evaluation (dry-run venue comparison).
- **Phase 5**: Automation gate — intentionally blocked until evidence exists.

## Quick start

Run the test suite:

```bash
python3 -m unittest discover -s tests
```

Run the full local verification chain:

```bash
python3 -m gmgn_monitor.verify
```

Run the health check without regenerating outputs:

```bash
python3 -m gmgn_monitor.doctor
```

Launch the local dashboard:

```bash
python3 -m gmgn_monitor.dashboard
```

## Project layout

- `gmgn_monitor/` — Python package.
- `config/` — JSON configuration files (thresholds, risk limits, automation gate, etc.).
- `fixtures/` — Sample candidate data in JSONL format.
- `data/` — Generated outputs (JSONL events, markdown reports, dry-run artifacts).
- `tests/` — Unit tests.
- `gmgn_system_spec.md` — System specification and phased build plan.
- `OPERATIONS.md` — Operational commands and usage guide.
- `SCHEMA.md` — Data schema for candidates, scored events, and outcomes.

## Safety boundary

This project deliberately contains no wallet signing code, no private-key handling, no order placement, and no auto-buy/auto-sell logic. The automation gate is blocked by default.

See `GOAL_AUDIT.md` and `SAFETY_ENRICHMENT.md` for details.
