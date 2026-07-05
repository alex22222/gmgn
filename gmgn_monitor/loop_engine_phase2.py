"""Loop Engineering — Phase 2 feedback loops.

Extends the Phase 1 :class:`~gmgn_monitor.loop_engine.LoopEngine` with five
additional self-healing loops targeted at signal quality, execution quality,
risk compliance, portfolio sync, and system health.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from gmgn_monitor.loop_engine import LoopEngine


__all__ = [
    "LoopResult",
    "SignalQualityLoop",
    "ExecutionQualityLoop",
    "RiskComplianceLoop",
    "PortfolioSyncLoop",
    "SystemHealthLoop",
    "Phase2LoopEngine",
]


@dataclass(frozen=True)
class LoopResult:
    """Result of a single loop check."""

    name: str
    status: str  # "ok" | "warning" | "critical"
    score: float  # 0-100
    issues: list[str] = field(default_factory=list)
    actions: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "score": self.score,
            "issues": self.issues,
            "actions": self.actions,
            "timestamp": self.timestamp,
        }


# ---------------------------------------------------------------------------
# Phase 2 loops
# ---------------------------------------------------------------------------

class SignalQualityLoop:
    """Phase 2 Loop 1 — Signal Quality.

    Monitors signal accuracy (win rate), false-positive rate, and
    false-negative rate.  If accuracy < 80 %, the action is to tighten
    *min_wallet_score* and increase *min_confidence*.
    """

    name = "signal_quality"

    def check(self, metrics: dict[str, Any]) -> LoopResult:
        accuracy = metrics.get("signal_accuracy", 1.0)
        fp_rate = metrics.get("false_positive_rate", 0.0)
        fn_rate = metrics.get("false_negative_rate", 0.0)

        issues: list[str] = []
        actions: list[str] = []
        score = 100.0

        if accuracy < 0.80:
            issues.append(f"signal accuracy {accuracy:.2%} < 80%")
            actions.append("tighten min_wallet_score")
            actions.append("increase min_confidence")
            score -= 30.0

        if fp_rate > 0.20:
            issues.append(f"false-positive rate {fp_rate:.2%} > 20%")
            actions.append("reduce signal spam threshold")
            score -= 20.0

        if fn_rate > 0.20:
            issues.append(f"false-negative rate {fn_rate:.2%} > 20%")
            actions.append("relax overly aggressive filters")
            score -= 20.0

        status = "ok" if score >= 80 else "warning" if score >= 50 else "critical"
        return LoopResult(
            name=self.name,
            status=status,
            score=max(0.0, score),
            issues=issues,
            actions=actions,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name}


class ExecutionQualityLoop:
    """Phase 2 Loop 2 — Execution Quality.

    Monitors order success rate, average execution time, and retry rate.
    If success rate < 95 %, the action is to increase retry logic and
    adjust timeout parameters.
    """

    name = "phase2_execution_quality"

    def check(self, metrics: dict[str, Any]) -> LoopResult:
        success_rate = metrics.get("order_success_rate", 1.0)
        avg_time = metrics.get("avg_execution_time_ms", 0.0)
        retry_rate = metrics.get("retry_rate", 0.0)

        issues: list[str] = []
        actions: list[str] = []
        score = 100.0

        if success_rate < 0.95:
            issues.append(f"order success rate {success_rate:.2%} < 95%")
            actions.append("increase retry logic")
            actions.append("adjust timeout parameters")
            score -= 30.0

        if avg_time > 5000.0:
            issues.append(f"avg execution time {avg_time:.0f} ms > 5000 ms")
            actions.append("switch to faster RPC endpoint")
            score -= 15.0

        if retry_rate > 0.10:
            issues.append(f"retry rate {retry_rate:.2%} > 10%")
            actions.append("review RPC reliability")
            score -= 15.0

        status = "ok" if score >= 80 else "warning" if score >= 50 else "critical"
        return LoopResult(
            name=self.name,
            status=status,
            score=max(0.0, score),
            issues=issues,
            actions=actions,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name}


class RiskComplianceLoop:
    """Phase 2 Loop 3 — Risk Compliance.

    Monitors daily loss, max drawdown, and circuit-breaker triggers.
    If daily loss > 5 %, the action is to tighten
    *max_single_position_percent* and reduce *max_total_positions*.
    """

    name = "risk_compliance"

    def check(self, metrics: dict[str, Any]) -> LoopResult:
        daily_loss = metrics.get("daily_loss", 0.0)
        max_dd = metrics.get("max_drawdown", 0.0)
        cb_count = metrics.get("circuit_breaker_count", 0)

        issues: list[str] = []
        actions: list[str] = []
        score = 100.0

        if daily_loss > 0.05:
            issues.append(f"daily loss {daily_loss:.2%} > 5%")
            actions.append("tighten max_single_position_percent")
            actions.append("reduce max_total_positions")
            score -= 30.0

        if max_dd > 0.15:
            issues.append(f"max drawdown {max_dd:.2%} > 15%")
            actions.append("review stop-loss parameters")
            score -= 20.0

        if cb_count > 0:
            issues.append(f"circuit breaker triggered {cb_count} time(s)")
            actions.append("pause new positions for 1 hour")
            score -= 25.0

        status = "ok" if score >= 80 else "warning" if score >= 50 else "critical"
        return LoopResult(
            name=self.name,
            status=status,
            score=max(0.0, score),
            issues=issues,
            actions=actions,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name}


class PortfolioSyncLoop:
    """Phase 2 Loop 4 — Portfolio Sync.

    Monitors portfolio value, unrealized PnL, realized PnL, and position
    count.  If portfolio value diverges from chain by > 0.1 %, the action
    is to trigger a re-sync and alert.
    """

    name = "portfolio_sync"

    def check(self, metrics: dict[str, Any]) -> LoopResult:
        divergence = metrics.get("portfolio_value_divergence", 0.0)
        unrealized = metrics.get("unrealized_pnl", 0.0)
        realized = metrics.get("realized_pnl", 0.0)
        pos_count = metrics.get("position_count", 0)

        issues: list[str] = []
        actions: list[str] = []
        score = 100.0

        if divergence > 0.001:
            issues.append(f"portfolio divergence {divergence:.4%} > 0.1%")
            actions.append("trigger re-sync with chain")
            actions.append("send alert to operator")
            score -= 30.0

        if unrealized < -1.0:
            issues.append(f"unrealized PnL {unrealized:.4f} SOL is deeply negative")
            actions.append("review open positions for forced exit")
            score -= 15.0

        if pos_count > 10:
            issues.append(f"position count {pos_count} > 10")
            actions.append("review concentration risk")
            score -= 10.0

        status = "ok" if score >= 80 else "warning" if score >= 50 else "critical"
        return LoopResult(
            name=self.name,
            status=status,
            score=max(0.0, score),
            issues=issues,
            actions=actions,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name}


class SystemHealthLoop:
    """Phase 2 Loop 5 — System Health.

    Monitors API latency, error rate, memory usage, and uptime.  If error
    rate > 1 %, the action is to alert and restart data pipelines.
    """

    name = "phase2_system_health"

    def check(self, metrics: dict[str, Any]) -> LoopResult:
        latency = metrics.get("api_latency_ms", 0.0)
        error_rate = metrics.get("error_rate", 0.0)
        memory = metrics.get("memory_usage", 0.0)
        uptime = metrics.get("uptime", 0.0)

        issues: list[str] = []
        actions: list[str] = []
        score = 100.0

        if error_rate > 0.01:
            issues.append(f"error rate {error_rate:.2%} > 1%")
            actions.append("alert operator")
            actions.append("restart data pipelines")
            score -= 30.0

        if latency > 3000.0:
            issues.append(f"API latency {latency:.0f} ms > 3000 ms")
            actions.append("switch to backup API endpoint")
            score -= 20.0

        if memory > 0.85:
            issues.append(f"memory usage {memory:.2%} > 85%")
            actions.append("clear caches")
            score -= 15.0

        if uptime < 300.0:
            issues.append(f"uptime {uptime:.0f} s < 300 s (recent restart)")
            actions.append("investigate crash cause")
            score -= 10.0

        status = "ok" if score >= 80 else "warning" if score >= 50 else "critical"
        return LoopResult(
            name=self.name,
            status=status,
            score=max(0.0, score),
            issues=issues,
            actions=actions,
        )

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name}


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

class Phase2LoopEngine:
    """Orchestrates all 10 feedback loops (5 Phase 1 + 5 Phase 2).

    Usage::

        engine = Phase2LoopEngine()
        results = engine.run_all({
            "data_quality": {"data_completeness": 0.94},
            "score_validation": {"score_return_correlation": 0.65},
            "backtest_calibration": {"simulated_vs_actual_7d_deviation": 0.12},
            "execution_quality": {"order_success_rate": 0.98},
            "system_health": {"service_available": True},
            "signal_quality": {"signal_accuracy": 0.75},
            "risk_compliance": {"daily_loss": 0.03},
            "portfolio_sync": {"portfolio_value_divergence": 0.0005},
        })
    """

    def __init__(self) -> None:
        self._phase1 = LoopEngine()
        self._phase2: dict[str, Any] = {
            "signal_quality": SignalQualityLoop(),
            "phase2_execution_quality": ExecutionQualityLoop(),
            "risk_compliance": RiskComplianceLoop(),
            "portfolio_sync": PortfolioSyncLoop(),
            "phase2_system_health": SystemHealthLoop(),
        }

    def run_all(self, metrics: dict[str, dict[str, Any]]) -> dict[str, LoopResult]:
        """Run every loop and return a flat mapping of results.

        *metrics* is a mapping from loop name to a dict of check metrics.
        """
        results: dict[str, LoopResult] = {}

        # Phase 1 loops
        phase1_results = self._phase1.run_all(metrics)
        for r in phase1_results:
            status_map = {
                "healthy": "ok",
                "accepted": "warning",
                "failed": "critical",
                "paused": "warning",
            }
            mapped_status = status_map.get(r.status, r.status)
            score = 100.0 if mapped_status == "ok" else 50.0 if mapped_status == "warning" else 0.0
            results[r.loop_name] = LoopResult(
                name=r.loop_name,
                status=mapped_status,
                score=score,
                issues=r.trigger_reasons,
                actions=r.actions_taken,
                timestamp=r.timestamp,
            )

        # Phase 2 loops
        for name, loop in self._phase2.items():
            loop_metrics = metrics.get(name, {})
            result = loop.check(loop_metrics)
            results[name] = result

        return results

    def get_phase2_results(self, results: dict[str, LoopResult] | None = None) -> dict[str, LoopResult]:
        """Return only the Phase 2 loop results.

        If *results* is provided, filters it; otherwise returns an empty dict.
        """
        if results is None:
            return {}
        return {k: v for k, v in results.items() if k in self._phase2}

    def to_report(self, results: dict[str, LoopResult] | None = None) -> dict[str, Any]:
        """Return a structured report with all loop statuses."""
        if results is None:
            results = {}
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "loops": {name: r.to_dict() for name, r in results.items()},
            "phase1_loops": list(self._phase1._loops.keys()),
            "phase2_loops": list(self._phase2.keys()),
            "total_loops": len(self._phase1._loops) + len(self._phase2),
            "summary": {
                "ok": sum(1 for r in results.values() if r.status == "ok"),
                "warning": sum(1 for r in results.values() if r.status == "warning"),
                "critical": sum(1 for r in results.values() if r.status == "critical"),
            },
        }
