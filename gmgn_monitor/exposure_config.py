from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

__all__ = [
    "ExposureLevel",
    "ExposureConfig",
    "ProgressiveExposureManager",
]


class ExposureLevel(Enum):
    """Four-stage safety ladder for progressive real-money exposure."""

    OBSERVE = "observe"
    SIMULATE = "simulate"
    MINI_REAL = "mini_real"
    FULL_SCALE = "full_scale"


@dataclass(frozen=True)
class ExposureConfig:
    """Risk parameters for a single exposure level."""

    level: ExposureLevel
    max_position_sol: float
    max_daily_loss_percent: float
    max_positions: int
    stop_loss_percent: float
    take_profit_levels: list[tuple[float, float]]
    mev_protection: str
    slippage_tolerance: float
    requires_approval: bool
    go_nogo_criteria: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        return {
            "level": self.level.value,
            "max_position_sol": self.max_position_sol,
            "max_daily_loss_percent": self.max_daily_loss_percent,
            "max_positions": self.max_positions,
            "stop_loss_percent": self.stop_loss_percent,
            "take_profit_levels": self.take_profit_levels,
            "mev_protection": self.mev_protection,
            "slippage_tolerance": self.slippage_tolerance,
            "requires_approval": self.requires_approval,
            "go_nogo_criteria": self.go_nogo_criteria,
        }


class ProgressiveExposureManager:
    """Manages the 4-stage safety ladder for progressive real-money exposure.

    Each stage has stricter Go/No-Go criteria before advancing to the next.
    The manager can also retreat to a safer level in emergency situations.

    Usage::

        mgr = ProgressiveExposureManager(current_level=ExposureLevel.OBSERVE)
        config = mgr.get_config()
        if mgr.can_advance(metrics={"win_rate": 0.45, "max_drawdown": 0.15}):
            mgr.advance()
    """

    def __init__(self, current_level: ExposureLevel = ExposureLevel.OBSERVE) -> None:
        self._current_level = current_level
        self._level_configs = self._build_configs()
        self._consecutive_days = 0

    def _build_configs(self) -> dict[ExposureLevel, ExposureConfig]:
        """Return the canonical configuration for each exposure level."""
        return {
            ExposureLevel.OBSERVE: ExposureConfig(
                level=ExposureLevel.OBSERVE,
                max_position_sol=0.0,
                max_daily_loss_percent=5.0,
                max_positions=0,
                stop_loss_percent=-65.0,
                take_profit_levels=[(100.0, 50.0), (300.0, 50.0)],
                mev_protection="SECURE",
                slippage_tolerance=0.0,
                requires_approval=False,
                go_nogo_criteria={},
            ),
            ExposureLevel.SIMULATE: ExposureConfig(
                level=ExposureLevel.SIMULATE,
                max_position_sol=0.0,
                max_daily_loss_percent=5.0,
                max_positions=5,
                stop_loss_percent=-65.0,
                take_profit_levels=[(100.0, 50.0), (300.0, 50.0)],
                mev_protection="SECURE",
                slippage_tolerance=50.0,
                requires_approval=False,
                go_nogo_criteria={},
            ),
            ExposureLevel.MINI_REAL: ExposureConfig(
                level=ExposureLevel.MINI_REAL,
                max_position_sol=0.005,
                max_daily_loss_percent=5.0,
                max_positions=3,
                stop_loss_percent=-65.0,
                take_profit_levels=[(100.0, 50.0), (300.0, 50.0)],
                mev_protection="SECURE",
                slippage_tolerance=30.0,
                requires_approval=True,
                go_nogo_criteria={
                    "consecutive_days": 7.0,
                    "win_rate": 0.40,
                    "max_drawdown": 0.20,
                },
            ),
            ExposureLevel.FULL_SCALE: ExposureConfig(
                level=ExposureLevel.FULL_SCALE,
                max_position_sol=5.0,
                max_daily_loss_percent=10.0,
                max_positions=10,
                stop_loss_percent=-65.0,
                take_profit_levels=[(100.0, 50.0), (300.0, 50.0)],
                mev_protection="SECURE",
                slippage_tolerance=30.0,
                requires_approval=True,
                go_nogo_criteria={
                    "consecutive_days": 14.0,
                    "win_rate": 0.50,
                    "sharpe_ratio": 0.5,
                    "max_drawdown": 0.15,
                    "daily_loss": 0.05,
                },
            ),
        }

    def get_config(self) -> ExposureConfig:
        """Return the configuration for the current exposure level."""
        return self._level_configs[self._current_level]

    def can_advance(self, metrics: dict[str, Any]) -> bool:
        """Check if current metrics meet the Go criteria for advancing.

        Returns ``True`` only if *all* criteria for the current level are met.
        """
        config = self.get_config()
        criteria = config.go_nogo_criteria
        if not criteria:
            # OBSERVE -> SIMULATE has no criteria; just flip the switch
            return True

        for key, threshold in criteria.items():
            actual = metrics.get(key)
            if actual is None:
                return False

            if key == "consecutive_days":
                if actual < threshold:
                    return False
            elif key in ("win_rate", "sharpe_ratio"):
                if actual < threshold:
                    return False
            elif key in ("max_drawdown", "daily_loss"):
                if actual > threshold:
                    return False
            else:
                if actual < threshold:
                    return False
        return True

    def advance(self) -> bool:
        """Move to the next exposure level if possible.

        Returns ``True`` if the level was advanced, ``False`` if already at
        the highest level.
        """
        levels = list(ExposureLevel)
        idx = levels.index(self._current_level)
        if idx < len(levels) - 1:
            self._current_level = levels[idx + 1]
            return True
        return False

    def retreat(self, reason: str) -> None:
        """Move back one level (emergency de-risking).

        Args:
            reason: Human-readable reason for the retreat (logged but not
                stored in this minimal implementation).
        """
        levels = list(ExposureLevel)
        idx = levels.index(self._current_level)
        if idx > 0:
            self._current_level = levels[idx - 1]

    def get_current_level(self) -> ExposureLevel:
        """Return the current exposure level."""
        return self._current_level

    def to_dict(self) -> dict[str, Any]:
        """Serialize the manager state to a plain dict."""
        config = self.get_config()
        return {
            "current_level": self._current_level.value,
            "consecutive_days": self._consecutive_days,
            "config": config.to_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ProgressiveExposureManager":
        """Deserialize a :class:`ProgressiveExposureManager` from a dict."""
        level = ExposureLevel(d.get("current_level", "observe"))
        mgr = cls(current_level=level)
        mgr._consecutive_days = d.get("consecutive_days", 0)
        return mgr
