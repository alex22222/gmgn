from __future__ import annotations

import os
from typing import Any

from .dry_run_executor import DryRunExecutor
from .real_trade_executor import RealTradeExecutor


__all__ = [
    "ExecutionSwitch",
    "get_executor",
    "TRADE_MODE_DRYRUN",
    "TRADE_MODE_REAL",
]


TRADE_MODE_DRYRUN = "dryrun"
TRADE_MODE_REAL = "real"

_DEFAULT_ENV_KEY = "GMGN_TRADE_MODE"
_DEFAULT_CONFIG_KEY = "trade_mode"


class ExecutionSwitch:
    """Switch between dry-run and real-money execution modes.

    Resolution order (highest precedence first):
    1. Environment variable ``GMGN_TRADE_MODE`` (``dryrun`` / ``real``)
    2. ``gmgn_monitor/exposure_state.json`` → ``trade_mode`` field
    3. Default: ``dryrun`` (safety first)

    Usage::

        switch = ExecutionSwitch()
        if switch.is_real:
            print("⚠️  REAL MONEY MODE — every trade submits on-chain!")
        else:
            print("ℹ️  Dry-run mode — no real transactions")
    """

    def __init__(self, mode: str | None = None) -> None:
        self._mode = self._resolve_mode(mode)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def mode(self) -> str:
        """Return the current execution mode (``dryrun`` or ``real``)."""
        return self._mode

    @property
    def is_dryrun(self) -> bool:
        """Return ``True`` if running in dry-run mode."""
        return self._mode == TRADE_MODE_DRYRUN

    @property
    def is_real(self) -> bool:
        """Return ``True`` if running in real-money mode."""
        return self._mode == TRADE_MODE_REAL

    # ------------------------------------------------------------------
    # Mutable helpers
    # ------------------------------------------------------------------

    def set_dryrun(self) -> None:
        """Switch to dry-run mode."""
        self._mode = TRADE_MODE_DRYRUN

    def set_real(self) -> None:
        """Switch to real-money mode."""
        self._mode = TRADE_MODE_REAL

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dict."""
        return {"mode": self._mode}

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve_mode(explicit: str | None) -> str:
        if explicit is not None:
            return _validate_mode(explicit)

        # 1. Environment variable
        env = os.environ.get(_DEFAULT_ENV_KEY, "").strip().lower()
        if env in (TRADE_MODE_DRYRUN, TRADE_MODE_REAL):
            return env

        # 2. Config file
        try:
            import json
            from pathlib import Path
            cfg_path = Path(__file__).parent / "exposure_state.json"
            if cfg_path.exists():
                with open(cfg_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                mode = data.get(_DEFAULT_CONFIG_KEY, TRADE_MODE_DRYRUN)
                return _validate_mode(mode)
        except Exception:
            pass

        # 3. Safety default
        return TRADE_MODE_DRYRUN


# ------------------------------------------------------------------
# Factory
# ------------------------------------------------------------------

def get_executor(
    switch: ExecutionSwitch | None = None,
    **kwargs: Any,
) -> DryRunExecutor | RealTradeExecutor:
    """Return the appropriate executor based on the current mode.

    Args:
        switch: An :class:`ExecutionSwitch` instance.  If ``None``, one is
            created from the default resolution chain.
        **kwargs: Forwarded to the executor constructor.

    Returns:
        A :class:`DryRunExecutor` or :class:`RealTradeExecutor`.
    """
    if switch is None:
        switch = ExecutionSwitch()

    if switch.is_real:
        return RealTradeExecutor(**kwargs)
    return DryRunExecutor(**kwargs)


# ------------------------------------------------------------------
# Internal helpers
# ------------------------------------------------------------------


def _validate_mode(mode: str) -> str:
    mode = str(mode).strip().lower()
    if mode not in (TRADE_MODE_DRYRUN, TRADE_MODE_REAL):
        raise ValueError(
            f"Invalid trade mode: {mode!r}. "
            f"Expected one of: {TRADE_MODE_DRYRUN!r}, {TRADE_MODE_REAL!r}."
        )
    return mode
