from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from .order_manager import OrderManager
from .portfolio_tracker import PortfolioTracker
from .risk_manager import RiskManager

__all__ = [
    "AlertLevel",
    "Alert",
    "Monitor",
]

logger = logging.getLogger(__name__)


class AlertLevel(Enum):
    """Severity levels for monitoring alerts."""

    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    EMERGENCY = "emergency"

    def __str__(self) -> str:
        return self.value


@dataclass
class Alert:
    """A single monitoring alert."""

    timestamp: str
    level: AlertLevel
    source: str
    message: str
    metrics: dict[str, Any] = field(default_factory=dict)
    action_required: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "level": self.level.value,
            "source": self.source,
            "message": self.message,
            "metrics": self.metrics,
            "action_required": self.action_required,
        }


class Monitor:
    """Monitoring and alerting system for the GMGN Phase 2 pipeline.

    Checks signal pipeline health, risk limits, execution health, and loop
    status.  Alerts are sent via a configurable webhook or written to a daily
    JSONL log file.

    Args:
        webhook_url: Optional HTTP(S) endpoint for POST-ing JSON alerts.
        log_dir: Directory for daily JSONL alert logs (default ``logs/monitor``).
    """

    def __init__(
        self,
        webhook_url: str | None = None,
        log_dir: str = "logs/monitor",
    ) -> None:
        self.webhook_url = webhook_url
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self._alerts: list[Alert] = []

    # ------------------------------------------------------------------
    # Checks
    # ------------------------------------------------------------------

    def check_signal_pipeline(self, metrics: dict[str, Any]) -> list[Alert]:
        """Check signal pipeline health and generate alerts.

        Expected *metrics* keys:

        - ``signals_in`` (int) — total signals received
        - ``signals_out`` (int) — signals that passed the pipeline
        - ``latency_ms`` (float) — end-to-end pipeline latency

        Returns:
            List of :class:`Alert` objects.
        """
        alerts: list[Alert] = []
        signals_in = int(metrics.get("signals_in", 0))
        signals_out = int(metrics.get("signals_out", 0))
        latency_ms = float(metrics.get("latency_ms", 0.0))
        ts = datetime.now(timezone.utc).isoformat()

        # Drop rate
        if signals_in > 0:
            drop_rate = (signals_in - signals_out) / signals_in
            if drop_rate > 0.50:
                alerts.append(
                    Alert(
                        timestamp=ts,
                        level=AlertLevel.CRITICAL,
                        source="signal_pipeline",
                        message=f"Signal drop rate {drop_rate:.1%} exceeds 50%",
                        metrics={"signals_in": signals_in, "signals_out": signals_out, "drop_rate": round(drop_rate, 4)},
                        action_required=True,
                    )
                )
            elif drop_rate > 0.20:
                alerts.append(
                    Alert(
                        timestamp=ts,
                        level=AlertLevel.WARNING,
                        source="signal_pipeline",
                        message=f"Signal drop rate {drop_rate:.1%} exceeds 20%",
                        metrics={"signals_in": signals_in, "signals_out": signals_out, "drop_rate": round(drop_rate, 4)},
                        action_required=False,
                    )
                )

        # Latency
        if latency_ms > 10000:
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.CRITICAL,
                    source="signal_pipeline",
                    message=f"Pipeline latency {latency_ms:.0f} ms exceeds 10,000 ms",
                    metrics={"latency_ms": round(latency_ms, 2)},
                    action_required=True,
                )
            )
        elif latency_ms > 5000:
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.WARNING,
                    source="signal_pipeline",
                    message=f"Pipeline latency {latency_ms:.0f} ms exceeds 5,000 ms",
                    metrics={"latency_ms": round(latency_ms, 2)},
                    action_required=False,
                )
            )

        # No signals at all
        if signals_in == 0:
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.WARNING,
                    source="signal_pipeline",
                    message="Zero signals received in the last cycle",
                    metrics={"signals_in": 0, "signals_out": 0},
                    action_required=False,
                )
            )

        return alerts

    def check_risk_limits(
        self,
        portfolio: PortfolioTracker,
        risk_manager: RiskManager,
    ) -> list[Alert]:
        """Check if risk limits are breached and generate alerts.

        Returns:
            List of :class:`Alert` objects.
        """
        alerts: list[Alert] = []
        ts = datetime.now(timezone.utc).isoformat()
        snapshot = portfolio.get_snapshot()

        # Daily loss
        if snapshot.daily_pnl_percent < -risk_manager.risk_limits.daily_loss_limit_percent:
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.CRITICAL,
                    source="risk_limits",
                    message=f"Daily loss {snapshot.daily_pnl_percent:.2f}% exceeds limit of {risk_manager.risk_limits.daily_loss_limit_percent}%",
                    metrics={
                        "daily_pnl_percent": round(snapshot.daily_pnl_percent, 4),
                        "daily_loss_limit": risk_manager.risk_limits.daily_loss_limit_percent,
                    },
                    action_required=True,
                )
            )

        # Circuit breaker
        if risk_manager.is_circuit_breaker_active():
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.CRITICAL,
                    source="risk_limits",
                    message=f"Circuit breaker active: {risk_manager.circuit_breaker.reason}",
                    metrics={
                        "circuit_breaker_triggered": True,
                        "reason": risk_manager.circuit_breaker.reason,
                        "consecutive_failed_trades": risk_manager.circuit_breaker.consecutive_failed_trades,
                    },
                    action_required=True,
                )
            )

        # Kill switch
        if risk_manager.is_kill_switch_active():
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.EMERGENCY,
                    source="risk_limits",
                    message="Kill switch is ACTIVE — all trading halted",
                    metrics={"kill_switch": True},
                    action_required=True,
                )
            )

        # Max drawdown
        if snapshot.max_drawdown_percent > 15.0:
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.CRITICAL,
                    source="risk_limits",
                    message=f"Max drawdown {snapshot.max_drawdown_percent:.2f}% exceeds 15%",
                    metrics={"max_drawdown_percent": round(snapshot.max_drawdown_percent, 4)},
                    action_required=True,
                )
            )
        elif snapshot.max_drawdown_percent > 10.0:
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.WARNING,
                    source="risk_limits",
                    message=f"Max drawdown {snapshot.max_drawdown_percent:.2f}% exceeds 10%",
                    metrics={"max_drawdown_percent": round(snapshot.max_drawdown_percent, 4)},
                    action_required=False,
                )
            )

        return alerts

    def check_execution_health(self, order_manager: OrderManager) -> list[Alert]:
        """Check order execution health and generate alerts.

        Returns:
            List of :class:`Alert` objects.
        """
        alerts: list[Alert] = []
        ts = datetime.now(timezone.utc).isoformat()
        stats = order_manager.get_stats()

        total = stats.total_orders
        if total == 0:
            return alerts

        success_rate = stats.success_rate
        failed = stats.failed
        retry_avg = stats.avg_execution_time_ms

        # Success rate
        if success_rate < 0.80:
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.CRITICAL,
                    source="execution_health",
                    message=f"Order success rate {success_rate:.1%} below 80%",
                    metrics={
                        "success_rate": round(success_rate, 4),
                        "total_orders": total,
                        "failed_orders": failed,
                    },
                    action_required=True,
                )
            )
        elif success_rate < 0.95:
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.WARNING,
                    source="execution_health",
                    message=f"Order success rate {success_rate:.1%} below 95%",
                    metrics={
                        "success_rate": round(success_rate, 4),
                        "total_orders": total,
                        "failed_orders": failed,
                    },
                    action_required=False,
                )
            )

        # Failed orders
        if failed >= 5:
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.CRITICAL,
                    source="execution_health",
                    message=f"{failed} failed orders accumulated",
                    metrics={"failed_orders": failed, "total_orders": total},
                    action_required=True,
                )
            )

        # Avg execution time
        if retry_avg > 30000:
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.CRITICAL,
                    source="execution_health",
                    message=f"Average execution time {retry_avg:.0f} ms exceeds 30,000 ms",
                    metrics={"avg_execution_time_ms": round(retry_avg, 2)},
                    action_required=True,
                )
            )
        elif retry_avg > 10000:
            alerts.append(
                Alert(
                    timestamp=ts,
                    level=AlertLevel.WARNING,
                    source="execution_health",
                    message=f"Average execution time {retry_avg:.0f} ms exceeds 10,000 ms",
                    metrics={"avg_execution_time_ms": round(retry_avg, 2)},
                    action_required=False,
                )
            )

        return alerts

    def check_loop_status(self, loop_results: dict[str, Any]) -> list[Alert]:
        """Check Phase 2 loop results and generate alerts for critical loops.

        *loop_results* is a flat mapping of loop name → result dict with keys
        ``status`` (``"ok"`` | ``"warning"`` | ``"critical"``) and
        ``score`` (float 0-100).

        Returns:
            List of :class:`Alert` objects.
        """
        alerts: list[Alert] = []
        ts = datetime.now(timezone.utc).isoformat()

        for loop_name, result in loop_results.items():
            if not isinstance(result, dict):
                continue
            status = str(result.get("status", "")).lower()
            score = float(result.get("score", 100.0))
            issues = result.get("issues", [])

            if status == "critical":
                alerts.append(
                    Alert(
                        timestamp=ts,
                        level=AlertLevel.CRITICAL,
                        source=f"loop:{loop_name}",
                        message=f"Loop '{loop_name}' is critical (score={score:.0f})",
                        metrics={
                            "loop_name": loop_name,
                            "score": round(score, 2),
                            "issues": issues,
                        },
                        action_required=True,
                    )
                )
            elif status == "warning":
                alerts.append(
                    Alert(
                        timestamp=ts,
                        level=AlertLevel.WARNING,
                        source=f"loop:{loop_name}",
                        message=f"Loop '{loop_name}' is warning (score={score:.0f})",
                        metrics={
                            "loop_name": loop_name,
                            "score": round(score, 2),
                            "issues": issues,
                        },
                        action_required=False,
                    )
                )

        return alerts

    # ------------------------------------------------------------------
    # Alert delivery
    # ------------------------------------------------------------------

    def send_alert(self, alert: Alert) -> None:
        """Send an alert to the webhook (if configured) or log to a daily
        JSONL file.

        Args:
            alert: The alert to dispatch.
        """
        self._alerts.append(alert)
        payload = self.format_alert_for_webhook(alert)

        if self.webhook_url:
            try:
                data = json.dumps(payload).encode("utf-8")
                req = urllib.request.Request(
                    self.webhook_url,
                    data=data,
                    headers={
                        "Content-Type": "application/json",
                        "User-Agent": "gmgn-monitor/0.1",
                    },
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=10) as response:
                    _ = response.read()
            except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
                logger.warning("Webhook delivery failed: %s", exc)
                # Fallback to file logging
                self._log_to_file(alert)
        else:
            self._log_to_file(alert)

    def _log_to_file(self, alert: Alert) -> None:
        """Append an alert to the daily JSONL log."""
        today = date.today().isoformat()
        log_path = self.log_dir / f"alerts_{today}.jsonl"
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(alert.to_dict(), ensure_ascii=False) + "\n")

    def format_alert_for_webhook(self, alert: Alert) -> dict[str, Any]:
        """Format an alert as a JSON payload suitable for HTTP POST to a
        generic webhook (Feishu, DingTalk, Slack, etc.).

        Returns:
            A dict with ``timestamp``, ``level``, ``source``, ``message``,
            ``metrics``, and ``action_required``.
        """
        return alert.to_dict()

    # ------------------------------------------------------------------
    # Daily report
    # ------------------------------------------------------------------

    def get_daily_report(self) -> dict[str, Any]:
        """Aggregate all alerts for today into a summary report.

        Returns:
            Dict with ``date``, ``total_alerts``, ``counts_by_level``,
            ``top_issues``, and ``action_required_count``.
        """
        today = date.today().isoformat()
        today_alerts = [a for a in self._alerts if a.timestamp.startswith(today)]

        counts = {level.value: 0 for level in AlertLevel}
        for a in today_alerts:
            counts[a.level.value] += 1

        # If no in-memory alerts for today, try loading from file
        if not today_alerts:
            log_path = self.log_dir / f"alerts_{today}.jsonl"
            if log_path.exists():
                with open(log_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            entry = json.loads(line)
                            level = entry.get("level", "info")
                            if level in counts:
                                counts[level] += 1
                        except json.JSONDecodeError:
                            continue

        top_issues = [
            a.message for a in today_alerts if a.level in (AlertLevel.WARNING, AlertLevel.CRITICAL, AlertLevel.EMERGENCY)
        ][:10]

        action_required = sum(
            1 for a in today_alerts if a.action_required
        )

        return {
            "date": today,
            "total_alerts": len(today_alerts),
            "counts_by_level": counts,
            "top_issues": top_issues,
            "action_required_count": action_required,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
