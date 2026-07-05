from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from gmgn_monitor.loop_engine import (
    BacktestCalibrationLoop,
    DataQualityLoop,
    ExecutionQualityLoop,
    LoopCheckResult,
    LoopConfig,
    LoopEngine,
    LoopName,
    ScoreValidationLoop,
    SystemHealthLoop,
    load_loop_config,
)
from gmgn_monitor.loop_logging import LoopLogger


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def default_config() -> LoopConfig:
    return LoopConfig()


@pytest.fixture
def temp_log_dir():
    with tempfile.TemporaryDirectory() as tmp:
        yield Path(tmp)


@pytest.fixture
def logger(temp_log_dir: Path):
    return LoopLogger("test", log_dir=temp_log_dir)


# ---------------------------------------------------------------------------
# Loop 1 — Data Quality
# ---------------------------------------------------------------------------


class TestDataQualityLoop:
    def test_healthy_when_all_metrics_good(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = DataQualityLoop(default_config, logger=logger)
        metrics = {
            "consecutive_fetch_failures": 0,
            "missing_field_rate": 0.01,
            "max_price_deviation": 0.05,
            "data_completeness": 0.99,
        }
        result = loop.check(metrics)

        assert result.status == "healthy"
        assert not result.triggered
        assert result.acceptance_met
        assert result.trigger_reasons == []

    def test_triggered_on_consecutive_failures(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = DataQualityLoop(default_config, logger=logger)
        metrics = {
            "consecutive_fetch_failures": 5,
            "missing_field_rate": 0.01,
            "max_price_deviation": 0.05,
            "data_completeness": 0.99,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "consecutive failures 5 >= 3" in result.trigger_reasons
        assert "paused_data_ingestion" in result.actions_taken

    def test_triggered_on_missing_field_rate(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = DataQualityLoop(default_config, logger=logger)
        metrics = {
            "consecutive_fetch_failures": 0,
            "missing_field_rate": 0.10,
            "max_price_deviation": 0.05,
            "data_completeness": 0.99,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "missing field rate" in result.trigger_reasons[0]

    def test_triggered_on_price_deviation(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = DataQualityLoop(default_config, logger=logger)
        metrics = {
            "consecutive_fetch_failures": 0,
            "missing_field_rate": 0.01,
            "max_price_deviation": 0.50,
            "data_completeness": 0.99,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "price deviation" in result.trigger_reasons[0]

    def test_triggered_on_low_completeness(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = DataQualityLoop(default_config, logger=logger)
        metrics = {
            "consecutive_fetch_failures": 0,
            "missing_field_rate": 0.01,
            "max_price_deviation": 0.05,
            "data_completeness": 0.90,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "completeness" in result.trigger_reasons[0]

    def test_acceptance_passes_when_completeness_recovered(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = DataQualityLoop(default_config, logger=logger)
        metrics = {
            "consecutive_fetch_failures": 5,
            "missing_field_rate": 0.01,
            "max_price_deviation": 0.05,
            "data_completeness": 0.96,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert result.acceptance_met
        assert result.status == "accepted"

    def test_acceptance_fails_when_completeness_still_low(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = DataQualityLoop(default_config, logger=logger)
        metrics = {
            "consecutive_fetch_failures": 5,
            "missing_field_rate": 0.01,
            "max_price_deviation": 0.05,
            "data_completeness": 0.90,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert not result.acceptance_met
        assert result.status == "failed"

    def test_switches_to_backup_when_available(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = DataQualityLoop(default_config, logger=logger)
        metrics = {
            "consecutive_fetch_failures": 5,
            "missing_field_rate": 0.01,
            "max_price_deviation": 0.05,
            "data_completeness": 0.96,
            "backup_source_available": True,
        }
        result = loop.check(metrics)

        assert "switched_to_backup_source" in result.actions_taken

    def test_returns_paused_when_loop_paused(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = DataQualityLoop(default_config, logger=logger)
        loop.pause()
        result = loop.check({})

        assert result.status == "paused"
        assert not result.triggered


# ---------------------------------------------------------------------------
# Loop 2 — Score Validation
# ---------------------------------------------------------------------------


class TestScoreValidationLoop:
    def test_healthy_when_correlation_strong(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ScoreValidationLoop(default_config, logger=logger)
        metrics = {
            "score_return_correlation": 0.70,
            "top20_score_change_rate": 0.05,
            "manual_consistency": 0.85,
        }
        result = loop.check(metrics)

        assert result.status == "healthy"
        assert not result.triggered

    def test_triggered_on_low_correlation(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ScoreValidationLoop(default_config, logger=logger)
        metrics = {
            "score_return_correlation": 0.45,
            "top20_score_change_rate": 0.05,
            "manual_consistency": 0.85,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "correlation 0.45 < 0.6" in result.trigger_reasons
        assert "triggered_weight_grid_search" in result.actions_taken

    def test_triggered_on_high_top20_change(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ScoreValidationLoop(default_config, logger=logger)
        metrics = {
            "score_return_correlation": 0.70,
            "top20_score_change_rate": 0.25,
            "manual_consistency": 0.85,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "Top 20 change" in result.trigger_reasons[0]

    def test_triggered_on_low_manual_consistency(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ScoreValidationLoop(default_config, logger=logger)
        metrics = {
            "score_return_correlation": 0.70,
            "top20_score_change_rate": 0.05,
            "manual_consistency": 0.60,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "manual consistency" in result.trigger_reasons[0]

    def test_acceptance_passes_when_metrics_recovered(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ScoreValidationLoop(default_config, logger=logger)
        metrics = {
            "score_return_correlation": 0.65,
            "top20_score_change_rate": 0.10,
            "manual_consistency": 0.80,
        }
        result = loop.check(metrics)

        assert not result.triggered
        assert result.acceptance_met
        assert result.status == "healthy"

    def test_acceptance_fails_when_metrics_still_bad(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ScoreValidationLoop(default_config, logger=logger)
        metrics = {
            "score_return_correlation": 0.30,
            "top20_score_change_rate": 0.20,
            "manual_consistency": 0.50,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert not result.acceptance_met
        assert result.status == "failed"


# ---------------------------------------------------------------------------
# Loop 3 — Backtest Calibration
# ---------------------------------------------------------------------------


class TestBacktestCalibrationLoop:
    def test_healthy_when_deviation_low(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = BacktestCalibrationLoop(default_config, logger=logger)
        metrics = {
            "simulated_vs_actual_7d_deviation": 0.05,
            "slippage_estimate_deviation": 0.10,
        }
        result = loop.check(metrics)

        assert result.status == "healthy"
        assert not result.triggered

    def test_triggered_on_high_7d_deviation(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = BacktestCalibrationLoop(default_config, logger=logger)
        metrics = {
            "simulated_vs_actual_7d_deviation": 0.35,
            "slippage_estimate_deviation": 0.10,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "7-day deviation" in result.trigger_reasons[0]
        assert "adjusted_slippage_parameters" in result.actions_taken

    def test_triggered_on_high_slippage_deviation(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = BacktestCalibrationLoop(default_config, logger=logger)
        metrics = {
            "simulated_vs_actual_7d_deviation": 0.05,
            "slippage_estimate_deviation": 0.50,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "slippage deviation" in result.trigger_reasons[0]

    def test_acceptance_passes_when_deviation_acceptable(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = BacktestCalibrationLoop(default_config, logger=logger)
        metrics = {
            "simulated_vs_actual_7d_deviation": 0.10,
            "slippage_estimate_deviation": 0.10,
        }
        result = loop.check(metrics)

        assert not result.triggered
        assert result.acceptance_met
        assert result.status == "healthy"

    def test_acceptance_fails_when_deviation_too_high(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = BacktestCalibrationLoop(default_config, logger=logger)
        metrics = {
            "simulated_vs_actual_7d_deviation": 0.50,
            "slippage_estimate_deviation": 0.10,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert not result.acceptance_met
        assert result.status == "failed"


# ---------------------------------------------------------------------------
# Loop 4 — Execution Quality
# ---------------------------------------------------------------------------


class TestExecutionQualityLoop:
    def test_healthy_when_all_good(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ExecutionQualityLoop(default_config, logger=logger)
        metrics = {
            "order_success_rate": 0.99,
            "condition_order_trigger_rate": 1.0,
            "mev_loss_rate": 0.0,
        }
        result = loop.check(metrics)

        assert result.status == "healthy"
        assert not result.triggered

    def test_triggered_on_low_success_rate(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ExecutionQualityLoop(default_config, logger=logger)
        metrics = {
            "order_success_rate": 0.90,
            "condition_order_trigger_rate": 1.0,
            "mev_loss_rate": 0.0,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "order success rate" in result.trigger_reasons[0]
        assert "switched_rpc_endpoint" in result.actions_taken

    def test_triggered_on_low_trigger_rate(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ExecutionQualityLoop(default_config, logger=logger)
        metrics = {
            "order_success_rate": 0.99,
            "condition_order_trigger_rate": 0.95,
            "mev_loss_rate": 0.0,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "condition order trigger rate" in result.trigger_reasons[0]

    def test_triggered_on_high_mev_loss(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ExecutionQualityLoop(default_config, logger=logger)
        metrics = {
            "order_success_rate": 0.99,
            "condition_order_trigger_rate": 1.0,
            "mev_loss_rate": 0.05,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "MEV loss" in result.trigger_reasons[0]

    def test_acceptance_passes_when_metrics_recovered(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ExecutionQualityLoop(default_config, logger=logger)
        metrics = {
            "order_success_rate": 0.96,
            "condition_order_trigger_rate": 0.99,
            "mev_loss_rate": 0.0,
        }
        result = loop.check(metrics)

        assert not result.triggered
        assert result.acceptance_met
        assert result.status == "healthy"

    def test_acceptance_fails_when_metrics_still_bad(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = ExecutionQualityLoop(default_config, logger=logger)
        metrics = {
            "order_success_rate": 0.90,
            "condition_order_trigger_rate": 0.95,
            "mev_loss_rate": 0.05,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert not result.acceptance_met
        assert result.status == "failed"


# ---------------------------------------------------------------------------
# Loop 5 — System Health
# ---------------------------------------------------------------------------


class TestSystemHealthLoop:
    def test_healthy_when_all_good(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = SystemHealthLoop(default_config, logger=logger)
        metrics = {
            "service_available": True,
            "memory_usage_percent": 0.50,
            "disk_usage_percent": 0.60,
            "wallet_balance": 100.0,
            "wallet_balance_threshold": 10.0,
            "recovery_time_seconds": 30,
            "alert_time_seconds": 15,
        }
        result = loop.check(metrics)

        assert result.status == "healthy"
        assert not result.triggered

    def test_triggered_on_service_unavailable(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = SystemHealthLoop(default_config, logger=logger)
        metrics = {
            "service_available": False,
            "memory_usage_percent": 0.50,
            "disk_usage_percent": 0.60,
            "wallet_balance": 100.0,
            "wallet_balance_threshold": 10.0,
            "recovery_time_seconds": 30,
            "alert_time_seconds": 15,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "service unavailable" in result.trigger_reasons
        assert "restarted_service" in result.actions_taken

    def test_triggered_on_high_memory(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = SystemHealthLoop(default_config, logger=logger)
        metrics = {
            "service_available": True,
            "memory_usage_percent": 0.95,
            "disk_usage_percent": 0.60,
            "wallet_balance": 100.0,
            "wallet_balance_threshold": 10.0,
            "recovery_time_seconds": 30,
            "alert_time_seconds": 15,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "memory usage" in result.trigger_reasons[0]
        assert "cleaned_cache" in result.actions_taken

    def test_triggered_on_high_disk(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = SystemHealthLoop(default_config, logger=logger)
        metrics = {
            "service_available": True,
            "memory_usage_percent": 0.50,
            "disk_usage_percent": 0.95,
            "wallet_balance": 100.0,
            "wallet_balance_threshold": 10.0,
            "recovery_time_seconds": 30,
            "alert_time_seconds": 15,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "disk usage" in result.trigger_reasons[0]
        assert "cleaned_logs" in result.actions_taken

    def test_triggered_on_low_balance(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = SystemHealthLoop(default_config, logger=logger)
        metrics = {
            "service_available": True,
            "memory_usage_percent": 0.50,
            "disk_usage_percent": 0.60,
            "wallet_balance": 5.0,
            "wallet_balance_threshold": 10.0,
            "recovery_time_seconds": 30,
            "alert_time_seconds": 15,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert "wallet balance" in result.trigger_reasons[0]
        assert "paused_trading" in result.actions_taken
        assert "sent_alert" in result.actions_taken

    def test_acceptance_passes_when_recovery_fast(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = SystemHealthLoop(default_config, logger=logger)
        metrics = {
            "service_available": False,
            "memory_usage_percent": 0.50,
            "disk_usage_percent": 0.60,
            "wallet_balance": 100.0,
            "wallet_balance_threshold": 10.0,
            "recovery_time_seconds": 60,
            "alert_time_seconds": 30,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert result.acceptance_met
        assert result.status == "accepted"

    def test_acceptance_fails_when_recovery_slow(self, default_config: LoopConfig, logger: LoopLogger) -> None:
        loop = SystemHealthLoop(default_config, logger=logger)
        metrics = {
            "service_available": False,
            "memory_usage_percent": 0.50,
            "disk_usage_percent": 0.60,
            "wallet_balance": 100.0,
            "wallet_balance_threshold": 10.0,
            "recovery_time_seconds": 300,
            "alert_time_seconds": 120,
        }
        result = loop.check(metrics)

        assert result.triggered
        assert not result.acceptance_met
        assert result.status == "failed"


# ---------------------------------------------------------------------------
# LoopEngine orchestrator
# ---------------------------------------------------------------------------


class TestLoopEngine:
    def test_run_all_returns_five_results(self, default_config: LoopConfig, temp_log_dir: Path) -> None:
        engine = LoopEngine(config=default_config, logger=LoopLogger("engine", log_dir=temp_log_dir))
        metrics = {
            "data_quality": {
                "consecutive_fetch_failures": 0,
                "missing_field_rate": 0.01,
                "max_price_deviation": 0.05,
                "data_completeness": 0.99,
            },
            "score_validation": {
                "score_return_correlation": 0.70,
                "top20_score_change_rate": 0.05,
                "manual_consistency": 0.85,
            },
            "backtest_calibration": {
                "simulated_vs_actual_7d_deviation": 0.05,
                "slippage_estimate_deviation": 0.10,
            },
            "execution_quality": {
                "order_success_rate": 0.99,
                "condition_order_trigger_rate": 1.0,
                "mev_loss_rate": 0.0,
            },
            "system_health": {
                "service_available": True,
                "memory_usage_percent": 0.50,
                "disk_usage_percent": 0.60,
                "wallet_balance": 100.0,
                "wallet_balance_threshold": 10.0,
                "recovery_time_seconds": 30,
                "alert_time_seconds": 15,
            },
        }
        results = engine.run_all(metrics)

        assert len(results) == 5
        assert all(r.status == "healthy" for r in results)
        assert not engine.is_kill_switch_active()

    def test_data_quality_trigger_pauses_other_loops(self, default_config: LoopConfig, temp_log_dir: Path) -> None:
        engine = LoopEngine(config=default_config, logger=LoopLogger("engine", log_dir=temp_log_dir))
        metrics = {
            "data_quality": {
                "consecutive_fetch_failures": 5,
                "missing_field_rate": 0.01,
                "max_price_deviation": 0.05,
                "data_completeness": 0.96,
            },
            "score_validation": {
                "score_return_correlation": 0.70,
                "top20_score_change_rate": 0.05,
                "manual_consistency": 0.85,
            },
            "backtest_calibration": {
                "simulated_vs_actual_7d_deviation": 0.05,
                "slippage_estimate_deviation": 0.10,
            },
            "execution_quality": {
                "order_success_rate": 0.99,
                "condition_order_trigger_rate": 1.0,
                "mev_loss_rate": 0.0,
            },
            "system_health": {
                "service_available": True,
                "memory_usage_percent": 0.50,
                "disk_usage_percent": 0.60,
                "wallet_balance": 100.0,
                "wallet_balance_threshold": 10.0,
                "recovery_time_seconds": 30,
                "alert_time_seconds": 15,
            },
        }
        engine.run_all(metrics)

        assert engine.get_loop(LoopName.SCORE_VALIDATION).is_paused()
        assert engine.get_loop(LoopName.BACKTEST_CALIBRATION).is_paused()
        assert engine.get_loop(LoopName.EXECUTION_QUALITY).is_paused()
        assert not engine.get_loop(LoopName.SYSTEM_HEALTH).is_paused()

    def test_score_validation_trigger_pauses_execution_quality(self, default_config: LoopConfig, temp_log_dir: Path) -> None:
        engine = LoopEngine(config=default_config, logger=LoopLogger("engine", log_dir=temp_log_dir))
        metrics = {
            "data_quality": {"data_completeness": 0.99, "consecutive_fetch_failures": 0, "missing_field_rate": 0.01, "max_price_deviation": 0.05},
            "score_validation": {"score_return_correlation": 0.45, "top20_score_change_rate": 0.05, "manual_consistency": 0.85},
            "backtest_calibration": {"simulated_vs_actual_7d_deviation": 0.05, "slippage_estimate_deviation": 0.10},
            "execution_quality": {"order_success_rate": 0.99, "condition_order_trigger_rate": 1.0, "mev_loss_rate": 0.0},
            "system_health": {
                "service_available": True, "memory_usage_percent": 0.50, "disk_usage_percent": 0.60,
                "wallet_balance": 100.0, "wallet_balance_threshold": 10.0,
                "recovery_time_seconds": 30, "alert_time_seconds": 15,
            },
        }
        engine.run_all(metrics)

        assert engine.get_loop(LoopName.EXECUTION_QUALITY).is_paused()
        assert not engine.get_loop(LoopName.BACKTEST_CALIBRATION).is_paused()

    def test_backtest_calibration_trigger_pauses_execution_quality(self, default_config: LoopConfig, temp_log_dir: Path) -> None:
        engine = LoopEngine(config=default_config, logger=LoopLogger("engine", log_dir=temp_log_dir))
        metrics = {
            "data_quality": {"data_completeness": 0.99, "consecutive_fetch_failures": 0, "missing_field_rate": 0.01, "max_price_deviation": 0.05},
            "score_validation": {"score_return_correlation": 0.70, "top20_score_change_rate": 0.05, "manual_consistency": 0.85},
            "backtest_calibration": {"simulated_vs_actual_7d_deviation": 0.35, "slippage_estimate_deviation": 0.10},
            "execution_quality": {"order_success_rate": 0.99, "condition_order_trigger_rate": 1.0, "mev_loss_rate": 0.0},
            "system_health": {
                "service_available": True, "memory_usage_percent": 0.50, "disk_usage_percent": 0.60,
                "wallet_balance": 100.0, "wallet_balance_threshold": 10.0,
                "recovery_time_seconds": 30, "alert_time_seconds": 15,
            },
        }
        engine.run_all(metrics)

        assert engine.get_loop(LoopName.EXECUTION_QUALITY).is_paused()
        assert not engine.get_loop(LoopName.SCORE_VALIDATION).is_paused()

    def test_system_health_trigger_activates_kill_switch(self, default_config: LoopConfig, temp_log_dir: Path) -> None:
        engine = LoopEngine(config=default_config, logger=LoopLogger("engine", log_dir=temp_log_dir))
        metrics = {
            "data_quality": {"data_completeness": 0.99, "consecutive_fetch_failures": 0, "missing_field_rate": 0.01, "max_price_deviation": 0.05},
            "score_validation": {"score_return_correlation": 0.70, "top20_score_change_rate": 0.05, "manual_consistency": 0.85},
            "backtest_calibration": {"simulated_vs_actual_7d_deviation": 0.05, "slippage_estimate_deviation": 0.10},
            "execution_quality": {"order_success_rate": 0.99, "condition_order_trigger_rate": 1.0, "mev_loss_rate": 0.0},
            "system_health": {
                "service_available": False, "memory_usage_percent": 0.50, "disk_usage_percent": 0.60,
                "wallet_balance": 100.0, "wallet_balance_threshold": 10.0,
                "recovery_time_seconds": 30, "alert_time_seconds": 15,
            },
        }
        engine.run_all(metrics)

        assert engine.is_kill_switch_active()
        assert engine.get_loop(LoopName.DATA_QUALITY).is_paused()
        assert engine.get_loop(LoopName.SCORE_VALIDATION).is_paused()
        assert engine.get_loop(LoopName.BACKTEST_CALIBRATION).is_paused()
        assert engine.get_loop(LoopName.EXECUTION_QUALITY).is_paused()
        assert not engine.get_loop(LoopName.SYSTEM_HEALTH).is_paused()

    def test_reset_kill_switch_resumes_all(self, default_config: LoopConfig, temp_log_dir: Path) -> None:
        engine = LoopEngine(config=default_config, logger=LoopLogger("engine", log_dir=temp_log_dir))
        metrics = {
            "data_quality": {"data_completeness": 0.99, "consecutive_fetch_failures": 0, "missing_field_rate": 0.01, "max_price_deviation": 0.05},
            "score_validation": {"score_return_correlation": 0.70, "top20_score_change_rate": 0.05, "manual_consistency": 0.85},
            "backtest_calibration": {"simulated_vs_actual_7d_deviation": 0.05, "slippage_estimate_deviation": 0.10},
            "execution_quality": {"order_success_rate": 0.99, "condition_order_trigger_rate": 1.0, "mev_loss_rate": 0.0},
            "system_health": {
                "service_available": False, "memory_usage_percent": 0.50, "disk_usage_percent": 0.60,
                "wallet_balance": 100.0, "wallet_balance_threshold": 10.0,
                "recovery_time_seconds": 30, "alert_time_seconds": 15,
            },
        }
        engine.run_all(metrics)
        assert engine.is_kill_switch_active()

        engine.reset_kill_switch()
        assert not engine.is_kill_switch_active()
        for name in LoopName:
            assert not engine.get_loop(name).is_paused()

    def test_run_loop_with_missing_metrics(self, default_config: LoopConfig, temp_log_dir: Path) -> None:
        engine = LoopEngine(config=default_config, logger=LoopLogger("engine", log_dir=temp_log_dir))
        result = engine.run_loop(LoopName.DATA_QUALITY, {})

        assert isinstance(result, LoopCheckResult)
        assert result.status == "healthy"
        assert not result.triggered

    def test_global_pause_affects_non_health_loops(self, default_config: LoopConfig, temp_log_dir: Path) -> None:
        engine = LoopEngine(config=default_config, logger=LoopLogger("engine", log_dir=temp_log_dir))
        # Manually engage global pause to simulate kill-switch
        engine._global_paused = True
        result = engine.run_loop(LoopName.DATA_QUALITY, {})
        assert result.status == "paused"

        health_result = engine.run_loop(LoopName.SYSTEM_HEALTH, {})
        assert health_result.status == "healthy"


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


class TestLoadLoopConfig:
    def test_loads_valid_config(self, temp_log_dir: Path) -> None:
        path = temp_log_dir / "loop_config.json"
        path.write_text('{"data_quality_max_consecutive_failures": 10, "score_validation_min_correlation": 0.55}')
        config = load_loop_config(path)

        assert config.data_quality_max_consecutive_failures == 10
        assert config.score_validation_min_correlation == 0.55
        assert config.data_quality_min_completeness == 0.95  # default

    def test_rejects_non_object(self, temp_log_dir: Path) -> None:
        path = temp_log_dir / "loop_config.json"
        path.write_text("[]")
        with pytest.raises(ValueError, match="loop config must be an object"):
            load_loop_config(path)

    def test_rejects_unknown_fields(self, temp_log_dir: Path) -> None:
        path = temp_log_dir / "loop_config.json"
        path.write_text('{"unknown_field": 42}')
        with pytest.raises(ValueError, match="unknown loop config fields"):
            load_loop_config(path)

    def test_rejects_invalid_json(self, temp_log_dir: Path) -> None:
        path = temp_log_dir / "loop_config.json"
        path.write_text("not json")
        with pytest.raises(ValueError):
            load_loop_config(path)
