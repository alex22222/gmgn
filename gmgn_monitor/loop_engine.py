from __future__ import annotations

"""Loop Engineering — five self-healing feedback loops.

Each loop follows the same lifecycle: **check** → **trigger** → **auto-fix**
→ **acceptance**.  The :class:`LoopEngine` orchestrator enforces
inter-loop dependency rules and a global kill-switch.

Safety boundary
---------------
All auto-fix actions are simulated (configuration adjustments, alerts,
pauses).  No private keys, signatures, or on-chain transaction submission
are ever introduced.

Inter-loop dependencies
-----------------------
* DataQuality triggered → pause ScoreValidation, BacktestCalibration, ExecutionQuality
* ScoreValidation triggered → pause ExecutionQuality, resume BacktestCalibration
* BacktestCalibration triggered → pause ExecutionQuality, resume ScoreValidation
* ExecutionQuality triggered → risk circuit breaker notification
* SystemHealth triggered → global kill-switch (pause everything except itself)
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .loop_logging import LoopLogger, get_loop_logger
from .serialization import load_json


class LoopName(Enum):
    """Canonical names for the five feedback loops."""

    DATA_QUALITY = "data_quality"
    SCORE_VALIDATION = "score_validation"
    BACKTEST_CALIBRATION = "backtest_calibration"
    EXECUTION_QUALITY = "execution_quality"
    SYSTEM_HEALTH = "system_health"


@dataclass(frozen=True)
class LoopCheckResult:
    """Immutable snapshot of a single loop check iteration."""

    loop_name: str
    status: str
    triggered: bool
    metrics: dict[str, Any]
    trigger_reasons: list[str]
    actions_taken: list[str]
    acceptance_met: bool
    timestamp: str
    error: str | None = None


@dataclass(frozen=True)
class LoopConfig:
    """Configurable thresholds for all five loops.

    Inherits the ``default`` + ``chains`` pattern from
    :class:`config.ThresholdConfig` but keeps the structure flat because
    loop thresholds are global (not chain-specific).
    """

    # --- Loop 1: Data Quality ---
    data_quality_max_consecutive_failures: int = 3
    data_quality_max_missing_rate: float = 0.05
    data_quality_max_price_deviation: float = 0.20
    data_quality_min_completeness: float = 0.95

    # --- Loop 2: Score Validation ---
    score_validation_min_correlation: float = 0.60
    score_validation_max_top20_change: float = 0.15
    score_validation_min_manual_consistency: float = 0.75
    score_validation_max_weight_adjust: float = 0.05

    # --- Loop 3: Backtest Calibration ---
    backtest_max_7d_deviation: float = 0.20
    backtest_max_slippage_deviation: float = 0.30
    backtest_max_adjust_percent: float = 0.05
    backtest_acceptance_deviation: float = 0.15

    # --- Loop 4: Execution Quality ---
    execution_min_order_success_rate: float = 0.95
    execution_min_trigger_rate: float = 0.99
    execution_max_mev_loss: float = 0.01

    # --- Loop 5: System Health ---
    health_max_memory_percent: float = 0.80
    health_max_disk_percent: float = 0.90
    health_max_recovery_seconds: int = 120
    health_max_alert_seconds: int = 60


# ---------------------------------------------------------------------------
# Base class
# ---------------------------------------------------------------------------

class BaseLoop:
    """Abstract base for a single feedback loop."""

    def __init__(self, name: LoopName, config: LoopConfig, logger: LoopLogger | None = None) -> None:
        self.name = name
        self.config = config
        self.logger = logger or get_loop_logger(name.value)
        self._paused = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def is_paused(self) -> bool:
        """Return ``True`` when the loop is administratively paused."""
        return self._paused

    def pause(self) -> None:
        """Pause the loop.  Checks return ``status='paused'``."""
        self._paused = True
        self.logger.log("warning", f"Loop {self.name.value} paused")

    def resume(self) -> None:
        """Resume the loop."""
        self._paused = False
        self.logger.log("info", f"Loop {self.name.value} resumed")

    def check(self, metrics: dict[str, Any]) -> LoopCheckResult:
        """Run one check iteration against *metrics*.

        Concrete subclasses override :meth:`_check_impl`.
        """
        if self._paused:
            return LoopCheckResult(
                loop_name=self.name.value,
                status="paused",
                triggered=False,
                metrics=metrics,
                trigger_reasons=[],
                actions_taken=[],
                acceptance_met=True,
                timestamp=self._now(),
            )
        return self._check_impl(metrics)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _now(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _check_impl(self, metrics: dict[str, Any]) -> LoopCheckResult:
        raise NotImplementedError

    def _auto_fix(self, issues: list[str], metrics: dict[str, Any]) -> list[str]:
        raise NotImplementedError

    def _verify_acceptance(self, metrics: dict[str, Any], actions: list[str]) -> bool:
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Loop 1 — Data Quality
# ---------------------------------------------------------------------------

class DataQualityLoop(BaseLoop):
    """Loop 1: data quality (1-minute frequency).

    Checks completeness, missing-field rate, price anomalies, and
    consecutive fetch failures.  Auto-fix pauses ingestion and retries
    with exponential back-off.
    """

    def __init__(self, config: LoopConfig, logger: LoopLogger | None = None) -> None:
        super().__init__(LoopName.DATA_QUALITY, config, logger)

    def _check_impl(self, metrics: dict[str, Any]) -> LoopCheckResult:
        trigger_reasons: list[str] = []

        consecutive = metrics.get("consecutive_fetch_failures", 0)
        if consecutive >= self.config.data_quality_max_consecutive_failures:
            trigger_reasons.append(
                f"consecutive failures {consecutive} >= "
                f"{self.config.data_quality_max_consecutive_failures}"
            )

        missing_rate = metrics.get("missing_field_rate", 0.0)
        if missing_rate > self.config.data_quality_max_missing_rate:
            trigger_reasons.append(
                f"missing field rate {missing_rate:.2%} > "
                f"{self.config.data_quality_max_missing_rate:.2%}"
            )

        price_deviation = metrics.get("max_price_deviation", 0.0)
        if price_deviation > self.config.data_quality_max_price_deviation:
            trigger_reasons.append(
                f"price deviation {price_deviation:.2%} > "
                f"{self.config.data_quality_max_price_deviation:.2%}"
            )

        completeness = metrics.get("data_completeness", 1.0)
        if completeness < self.config.data_quality_min_completeness:
            trigger_reasons.append(
                f"completeness {completeness:.2%} < "
                f"{self.config.data_quality_min_completeness:.2%}"
            )

        triggered = bool(trigger_reasons)
        if triggered:
            self.logger.log(
                "warning",
                f"Triggered: {'; '.join(trigger_reasons)}",
                extra={"metrics": metrics},
            )
            actions_taken = self._auto_fix(trigger_reasons, metrics)
            acceptance = self._verify_acceptance(metrics, actions_taken)
            status = "accepted" if acceptance else "failed"
            if not acceptance:
                self.logger.log("error", "Acceptance failed after auto-fix")
        else:
            status = "healthy"
            actions_taken = []
            acceptance = True

        return LoopCheckResult(
            loop_name=self.name.value,
            status=status,
            triggered=triggered,
            metrics=metrics,
            trigger_reasons=trigger_reasons,
            actions_taken=actions_taken,
            acceptance_met=acceptance,
            timestamp=self._now(),
        )

    def _auto_fix(self, issues: list[str], metrics: dict[str, Any]) -> list[str]:
        actions: list[str] = ["paused_data_ingestion"]
        actions.append("triggered_exponential_backoff_retry")
        if metrics.get("backup_source_available", False):
            actions.append("switched_to_backup_source")
        actions.append("flagged_data_for_review")
        return actions

    def _verify_acceptance(self, metrics: dict[str, Any], actions: list[str]) -> bool:
        completeness = metrics.get("data_completeness", 0.0)
        return completeness >= self.config.data_quality_min_completeness


# ---------------------------------------------------------------------------
# Loop 2 — Score Validation
# ---------------------------------------------------------------------------

class ScoreValidationLoop(BaseLoop):
    """Loop 2: scoring validation (daily).

    Validates that wallet scores correlate with actual returns.
    Triggers weight grid-search when the Pearson coefficient drops
    below the threshold.
    """

    def __init__(self, config: LoopConfig, logger: LoopLogger | None = None) -> None:
        super().__init__(LoopName.SCORE_VALIDATION, config, logger)

    def _check_impl(self, metrics: dict[str, Any]) -> LoopCheckResult:
        trigger_reasons: list[str] = []

        correlation = metrics.get("score_return_correlation", 1.0)
        if correlation < self.config.score_validation_min_correlation:
            trigger_reasons.append(
                f"correlation {correlation:.2f} < "
                f"{self.config.score_validation_min_correlation}"
            )

        top20_change = metrics.get("top20_score_change_rate", 0.0)
        if top20_change > self.config.score_validation_max_top20_change:
            trigger_reasons.append(
                f"Top 20 change {top20_change:.2%} > "
                f"{self.config.score_validation_max_top20_change:.2%}"
            )

        manual = metrics.get("manual_consistency", 1.0)
        if manual < self.config.score_validation_min_manual_consistency:
            trigger_reasons.append(
                f"manual consistency {manual:.2%} < "
                f"{self.config.score_validation_min_manual_consistency:.2%}"
            )

        triggered = bool(trigger_reasons)
        if triggered:
            self.logger.log(
                "warning",
                f"Triggered: {'; '.join(trigger_reasons)}",
                extra={"metrics": metrics},
            )
            actions_taken = self._auto_fix(trigger_reasons, metrics)
            acceptance = self._verify_acceptance(metrics, actions_taken)
            status = "accepted" if acceptance else "failed"
            if not acceptance:
                self.logger.log("error", "Acceptance failed after auto-fix")
        else:
            status = "healthy"
            actions_taken = []
            acceptance = True

        return LoopCheckResult(
            loop_name=self.name.value,
            status=status,
            triggered=triggered,
            metrics=metrics,
            trigger_reasons=trigger_reasons,
            actions_taken=actions_taken,
            acceptance_met=acceptance,
            timestamp=self._now(),
        )

    def _auto_fix(self, issues: list[str], metrics: dict[str, Any]) -> list[str]:
        return [
            "triggered_weight_grid_search",
            "adjusted_weights_within_5_percent",
            "recomputed_scores",
            "verified_correlation",
        ]

    def _verify_acceptance(self, metrics: dict[str, Any], actions: list[str]) -> bool:
        correlation = metrics.get("score_return_correlation", 0.0)
        manual = metrics.get("manual_consistency", 0.0)
        return (
            correlation >= self.config.score_validation_min_correlation
            and manual >= self.config.score_validation_min_manual_consistency
        )


# ---------------------------------------------------------------------------
# Loop 3 — Backtest Calibration
# ---------------------------------------------------------------------------

class BacktestCalibrationLoop(BaseLoop):
    """Loop 3: backtest calibration (daily / per trade).

    Compares simulated returns with tracked reality.  Adjusts the
    slippage / cost model when deviation exceeds the threshold.
    """

    def __init__(self, config: LoopConfig, logger: LoopLogger | None = None) -> None:
        super().__init__(LoopName.BACKTEST_CALIBRATION, config, logger)

    def _check_impl(self, metrics: dict[str, Any]) -> LoopCheckResult:
        trigger_reasons: list[str] = []

        deviation_7d = metrics.get("simulated_vs_actual_7d_deviation", 0.0)
        if deviation_7d > self.config.backtest_max_7d_deviation:
            trigger_reasons.append(
                f"7-day deviation {deviation_7d:.2%} > "
                f"{self.config.backtest_max_7d_deviation:.2%}"
            )

        slippage_dev = metrics.get("slippage_estimate_deviation", 0.0)
        if slippage_dev > self.config.backtest_max_slippage_deviation:
            trigger_reasons.append(
                f"slippage deviation {slippage_dev:.2%} > "
                f"{self.config.backtest_max_slippage_deviation:.2%}"
            )

        triggered = bool(trigger_reasons)
        if triggered:
            self.logger.log(
                "warning",
                f"Triggered: {'; '.join(trigger_reasons)}",
                extra={"metrics": metrics},
            )
            actions_taken = self._auto_fix(trigger_reasons, metrics)
            acceptance = self._verify_acceptance(metrics, actions_taken)
            status = "accepted" if acceptance else "failed"
            if not acceptance:
                self.logger.log("error", "Acceptance failed after auto-fix")
        else:
            status = "healthy"
            actions_taken = []
            acceptance = True

        return LoopCheckResult(
            loop_name=self.name.value,
            status=status,
            triggered=triggered,
            metrics=metrics,
            trigger_reasons=trigger_reasons,
            actions_taken=actions_taken,
            acceptance_met=acceptance,
            timestamp=self._now(),
        )

    def _auto_fix(self, issues: list[str], metrics: dict[str, Any]) -> list[str]:
        return [
            "adjusted_slippage_parameters",
            "reran_backtest",
            "verified_deviation",
        ]

    def _verify_acceptance(self, metrics: dict[str, Any], actions: list[str]) -> bool:
        deviation = metrics.get("simulated_vs_actual_7d_deviation", 1.0)
        return deviation <= self.config.backtest_acceptance_deviation


# ---------------------------------------------------------------------------
# Loop 4 — Execution Quality
# ---------------------------------------------------------------------------

class ExecutionQualityLoop(BaseLoop):
    """Loop 4: execution quality (per trade).

    Monitors order success rate, TP/SL trigger rate, and MEV loss.
    All checks are simulated; no real trading infrastructure is ever
    invoked.
    """

    def __init__(self, config: LoopConfig, logger: LoopLogger | None = None) -> None:
        super().__init__(LoopName.EXECUTION_QUALITY, config, logger)

    def _check_impl(self, metrics: dict[str, Any]) -> LoopCheckResult:
        trigger_reasons: list[str] = []

        success_rate = metrics.get("order_success_rate", 1.0)
        if success_rate < self.config.execution_min_order_success_rate:
            trigger_reasons.append(
                f"order success rate {success_rate:.2%} < "
                f"{self.config.execution_min_order_success_rate:.2%}"
            )

        trigger_rate = metrics.get("condition_order_trigger_rate", 1.0)
        if trigger_rate < self.config.execution_min_trigger_rate:
            trigger_reasons.append(
                f"condition order trigger rate {trigger_rate:.2%} < "
                f"{self.config.execution_min_trigger_rate:.2%}"
            )

        mev_loss = metrics.get("mev_loss_rate", 0.0)
        if mev_loss > self.config.execution_max_mev_loss:
            trigger_reasons.append(
                f"MEV loss {mev_loss:.2%} > "
                f"{self.config.execution_max_mev_loss:.2%}"
            )

        triggered = bool(trigger_reasons)
        if triggered:
            self.logger.log(
                "warning",
                f"Triggered: {'; '.join(trigger_reasons)}",
                extra={"metrics": metrics},
            )
            actions_taken = self._auto_fix(trigger_reasons, metrics)
            acceptance = self._verify_acceptance(metrics, actions_taken)
            status = "accepted" if acceptance else "failed"
            if not acceptance:
                self.logger.log("error", "Acceptance failed after auto-fix")
        else:
            status = "healthy"
            actions_taken = []
            acceptance = True

        return LoopCheckResult(
            loop_name=self.name.value,
            status=status,
            triggered=triggered,
            metrics=metrics,
            trigger_reasons=trigger_reasons,
            actions_taken=actions_taken,
            acceptance_met=acceptance,
            timestamp=self._now(),
        )

    def _auto_fix(self, issues: list[str], metrics: dict[str, Any]) -> list[str]:
        return [
            "switched_rpc_endpoint",
            "adjusted_slippage_mode",
            "switched_mev_protection_level",
        ]

    def _verify_acceptance(self, metrics: dict[str, Any], actions: list[str]) -> bool:
        success = metrics.get("order_success_rate", 0.0)
        trigger = metrics.get("condition_order_trigger_rate", 0.0)
        return (
            success >= self.config.execution_min_order_success_rate
            and trigger >= self.config.execution_min_trigger_rate
        )


# ---------------------------------------------------------------------------
# Loop 5 — System Health
# ---------------------------------------------------------------------------

class SystemHealthLoop(BaseLoop):
    """Loop 5: system health (every 5 minutes).

    Monitors service availability, resource usage, and wallet balance.
    Triggers a global kill-switch when critical thresholds are breached.
    """

    def __init__(self, config: LoopConfig, logger: LoopLogger | None = None) -> None:
        super().__init__(LoopName.SYSTEM_HEALTH, config, logger)

    def _check_impl(self, metrics: dict[str, Any]) -> LoopCheckResult:
        trigger_reasons: list[str] = []

        if not metrics.get("service_available", True):
            trigger_reasons.append("service unavailable")

        memory = metrics.get("memory_usage_percent", 0.0)
        if memory > self.config.health_max_memory_percent:
            trigger_reasons.append(
                f"memory usage {memory:.2%} > "
                f"{self.config.health_max_memory_percent:.2%}"
            )

        disk = metrics.get("disk_usage_percent", 0.0)
        if disk > self.config.health_max_disk_percent:
            trigger_reasons.append(
                f"disk usage {disk:.2%} > "
                f"{self.config.health_max_disk_percent:.2%}"
            )

        balance = metrics.get("wallet_balance", float("inf"))
        threshold = metrics.get("wallet_balance_threshold", 0.0)
        if balance < threshold:
            trigger_reasons.append(
                f"wallet balance {balance} < threshold {threshold}"
            )

        triggered = bool(trigger_reasons)
        if triggered:
            self.logger.log(
                "warning",
                f"Triggered: {'; '.join(trigger_reasons)}",
                extra={"metrics": metrics},
            )
            actions_taken = self._auto_fix(trigger_reasons, metrics)
            acceptance = self._verify_acceptance(metrics, actions_taken)
            status = "accepted" if acceptance else "failed"
            if not acceptance:
                self.logger.log("error", "Acceptance failed after auto-fix")
        else:
            status = "healthy"
            actions_taken = []
            acceptance = True

        return LoopCheckResult(
            loop_name=self.name.value,
            status=status,
            triggered=triggered,
            metrics=metrics,
            trigger_reasons=trigger_reasons,
            actions_taken=actions_taken,
            acceptance_met=acceptance,
            timestamp=self._now(),
        )

    def _auto_fix(self, issues: list[str], metrics: dict[str, Any]) -> list[str]:
        actions: list[str] = []
        if any("service unavailable" in issue for issue in issues):
            actions.append("restarted_service")
        if any("memory" in issue for issue in issues):
            actions.append("cleaned_cache")
        if any("disk" in issue for issue in issues):
            actions.append("cleaned_logs")
        if any("wallet balance" in issue for issue in issues):
            actions.append("paused_trading")
            actions.append("sent_alert")
        return actions

    def _verify_acceptance(self, metrics: dict[str, Any], actions: list[str]) -> bool:
        recovery = metrics.get("recovery_time_seconds", 999)
        alert = metrics.get("alert_time_seconds", 999)
        return (
            recovery <= self.config.health_max_recovery_seconds
            and alert <= self.config.health_max_alert_seconds
        )


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class LoopEngine:
    """Orchestrates all five feedback loops with inter-loop dependency
    management and a global kill-switch.

    Usage::

        engine = LoopEngine()
        results = engine.run_all({
            "data_quality": {"data_completeness": 0.94},
            "score_validation": {"score_return_correlation": 0.65},
            ...
        })
    """

    def __init__(self, config: LoopConfig | None = None, logger: LoopLogger | None = None) -> None:
        self.config = config or LoopConfig()
        self.logger = logger or get_loop_logger("loop_engine")
        self._loops: dict[LoopName, BaseLoop] = {
            LoopName.DATA_QUALITY: DataQualityLoop(self.config),
            LoopName.SCORE_VALIDATION: ScoreValidationLoop(self.config),
            LoopName.BACKTEST_CALIBRATION: BacktestCalibrationLoop(self.config),
            LoopName.EXECUTION_QUALITY: ExecutionQualityLoop(self.config),
            LoopName.SYSTEM_HEALTH: SystemHealthLoop(self.config),
        }
        self._global_paused = False
        self._kill_switch = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def run_all(self, metrics: dict[str, dict[str, Any]]) -> list[LoopCheckResult]:
        """Run every loop and apply dependency rules.

        *metrics* is a mapping from :attr:`LoopName.value` to a dict of
        check metrics for that loop.
        """
        results: list[LoopCheckResult] = []
        for name in LoopName:
            loop_metrics = metrics.get(name.value, {})
            result = self.run_loop(name, loop_metrics)
            results.append(result)
        self._apply_dependencies(results)
        return results

    def run_loop(self, name: LoopName, metrics: dict[str, Any]) -> LoopCheckResult:
        """Run a single loop by name."""
        if self._global_paused and name != LoopName.SYSTEM_HEALTH:
            self._loops[name].pause()
        return self._loops[name].check(metrics)

    def get_loop(self, name: LoopName) -> BaseLoop:
        """Return the loop instance for *name*."""
        return self._loops[name]

    def is_kill_switch_active(self) -> bool:
        """Return ``True`` when the global kill-switch is engaged."""
        return self._kill_switch

    def reset_kill_switch(self) -> None:
        """Disengage the kill-switch and resume all loops."""
        self._kill_switch = False
        self._global_paused = False
        for loop in self._loops.values():
            loop.resume()
        self.logger.log("info", "Kill switch reset, all loops resumed")

    # ------------------------------------------------------------------
    # Dependency rules
    # ------------------------------------------------------------------

    def _apply_dependencies(self, results: list[LoopCheckResult]) -> None:
        """Enforce inter-loop dependency rules.

        Rules (from SPEC §2.3):

        1. DataQuality triggered → pause ScoreValidation, BacktestCalibration,
           ExecutionQuality.  Keep SystemHealth running.
        2. ScoreValidation triggered → pause ExecutionQuality,
           resume BacktestCalibration (to rerun backtest).
        3. BacktestCalibration triggered → pause ExecutionQuality,
           resume ScoreValidation (to trigger weight self-optimisation).
        4. ExecutionQuality triggered → notify risk circuit breaker.
        5. SystemHealth triggered → global kill-switch (pause everything
           except SystemHealth).
        """
        triggered = {r.loop_name for r in results if r.triggered}

        # Rule 1
        if LoopName.DATA_QUALITY.value in triggered:
            self._loops[LoopName.SCORE_VALIDATION].pause()
            self._loops[LoopName.BACKTEST_CALIBRATION].pause()
            self._loops[LoopName.EXECUTION_QUALITY].pause()
            self.logger.log(
                "warning",
                "DataQuality triggered: paused ScoreValidation, BacktestCalibration, ExecutionQuality",
            )

        # Rule 2
        if LoopName.SCORE_VALIDATION.value in triggered:
            self._loops[LoopName.EXECUTION_QUALITY].pause()
            self._loops[LoopName.BACKTEST_CALIBRATION].resume()
            self.logger.log(
                "warning",
                "ScoreValidation triggered: paused ExecutionQuality, resumed BacktestCalibration",
            )

        # Rule 3
        if LoopName.BACKTEST_CALIBRATION.value in triggered:
            self._loops[LoopName.EXECUTION_QUALITY].pause()
            self._loops[LoopName.SCORE_VALIDATION].resume()
            self.logger.log(
                "warning",
                "BacktestCalibration triggered: paused ExecutionQuality, resumed ScoreValidation",
            )

        # Rule 4
        if LoopName.EXECUTION_QUALITY.value in triggered:
            self.logger.log(
                "warning",
                "ExecutionQuality triggered: risk circuit breaker notified",
            )

        # Rule 5 — global kill-switch
        if LoopName.SYSTEM_HEALTH.value in triggered:
            self._kill_switch = True
            self._global_paused = True
            for loop_name in LoopName:
                if loop_name != LoopName.SYSTEM_HEALTH:
                    self._loops[loop_name].pause()
            self.logger.log("critical", "SystemHealth triggered: GLOBAL KILL SWITCH ACTIVATED")


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------

def load_loop_config(path: Path) -> LoopConfig:
    """Load a :class:`LoopConfig` from a JSON file.

    The file must contain a JSON object whose keys are field names of
    :class:`LoopConfig`.  Unknown fields raise ``ValueError`` to match
    the strict validation used by :func:`config.load_threshold_config`.
    """
    raw = load_json(path, label="loop config")
    if not isinstance(raw, dict):
        raise ValueError("loop config must be an object")

    allowed = {f for f in LoopConfig.__dataclass_fields__}
    unknown = sorted(set(raw) - allowed)
    if unknown:
        raise ValueError(f'unknown loop config fields: {", ".join(unknown)}')

    return LoopConfig(**raw)
