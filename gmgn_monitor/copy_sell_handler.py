from __future__ import annotations

from typing import Any

from .sell_executor import SellExecutionResult, SellExecutor, SellSignal
from .trade_signal import TradeSignal


__all__ = [
    "CopySellHandler",
]


class CopySellHandler:
    """Handle copy-trade sell signals (EXIT / REDUCE) from a source wallet.

    Converts ``EXIT`` and ``REDUCE`` :class:`TradeSignal` instances into
    :class:`SellSignal` objects and dispatches them through the
    :class:`SellExecutor`.
    """

    def __init__(self, sell_executor: SellExecutor) -> None:
        """Initialize the copy sell handler.

        Args:
            sell_executor: The sell executor responsible for on-chain submission.
        """
        self._sell_executor = sell_executor

    def handle_signal(self, signal: TradeSignal) -> SellExecutionResult | None:
        """Process a trade signal and execute a sell if applicable.

        Args:
            signal: The incoming trade signal.

        Returns:
            A :class:`SellExecutionResult` if a sell was executed,
            or ``None`` if the signal type is not a sell action.
        """
        if signal.signal_type not in ("EXIT", "REDUCE"):
            return None

        if signal.signal_type == "EXIT":
            sell_percent = 100.0
            trigger_type = "COPY_EXIT"  # type: ignore[assignment]
        else:  # REDUCE
            sell_percent = 50.0
            trigger_type = "COPY_EXIT"  # type: ignore[assignment]

        sell_signal = SellSignal(
            signal_id=f"copy-{signal.signal_id}",
            token_address=signal.target_token,
            sell_percent=sell_percent,
            trigger_type=trigger_type,
            trigger_price_usd=None,
            max_slippage_percent=signal.max_slippage_percent,
            reason=f"Copy sell signal: {signal.signal_type} from {signal.wallet_address}",
        )

        return self._sell_executor.execute_sell(sell_signal)
