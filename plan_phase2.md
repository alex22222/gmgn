# Phase 2 Execution Plan

Current state: 40% win rate (No-Go). Need to reach 80%.

## Stage 1 — Signal Quality Optimization
- Create `gmgn_monitor/signal_quality_optimizer.py` (SignalQualityOptimizer class)
- Modify `scripts/run_phase2_dryrun_iteration.py` (200 wallets, real Birdeye data, CSS grid search)
- Run script, verify report, check Go/No-Go

## Stage 2 — Real Data Activation
- Run `scripts/run_live_dryrun.py` with GMGN API key
- Create `gmgn_monitor/live_data_analyzer.py` (LiveDataAnalyzer class)
- Write `data/live_data_analysis.json`

## Stage 3 — Loop Engine Phase 2
- Create `gmgn_monitor/loop_engine_phase2.py` (5 new loops + Phase2LoopEngine)
- Verify import

## Stage 4 — Advance Exposure
- Create `scripts/advance_exposure.py` (CLI: advance, retreat, status, report)
- Update `gmgn_monitor/exposure_state.json` to `simulate`
- Run `status` command

Skill loading: none required — custom orchestration.
