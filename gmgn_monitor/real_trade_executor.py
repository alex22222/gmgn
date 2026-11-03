from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .config_manager import ConfigManager
from .copy_risk import CopyRiskProfile, load_copy_risk
from .gmgn_api_client import GmgnApiClient, GmgnSigner
from .live_guard import live_buy_block_reason, load_automation_gate
from .order_manager import Order, OrderManager
from .portfolio_tracker import PortfolioTracker
from .risk_manager import RiskCheckResult, RiskManager, RiskLimits
from .trade_signal import TradeExecution, TradeSignal


__all__ = [
    "RealTradeExecutor",
    "ExecutionResult",
    "HUMAN_CONFIRMATION_REQUIRED",
]


HUMAN_CONFIRMATION_REQUIRED = (
    "⚠️  HUMAN CONFIRMATION REQUIRED\n"
    "This is REAL-MONEY mode. The following trade will be submitted on-chain.\n"
    "Please review carefully before confirming.\n"
)


@dataclass(frozen=True)
class ExecutionResult:
    """Result of a single real-money trade execution."""

    success: bool
    trade_execution: TradeExecution | None
    order_id: str | None
    tx_hash: str | None
    error_message: str | None
    gas_cost_sol: float
    actual_slippage_percent: float
    confirmation_time_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "trade_execution": self.trade_execution.to_dict() if self.trade_execution else None,
            "order_id": self.order_id,
            "tx_hash": self.tx_hash,
            "error_message": self.error_message,
            "gas_cost_sol": self.gas_cost_sol,
            "actual_slippage_percent": self.actual_slippage_percent,
            "confirmation_time_ms": self.confirmation_time_ms,
        }


class RealTradeExecutor:
    """Execute real on-chain trades via the GMGN API.

    This executor submits actual signed transactions to the Solana blockchain
    through the GMGN swap endpoint. Tiny auto-confirm still refuses the swap
    unless the automation gate is open and the order is inside the copy caps.

    Usage::

        executor = RealTradeExecutor(
            wallet_address="YourSolanaWalletAddress",
            chain="sol",
            auto_confirm=False,  # always ask for human confirmation
        )
        result = executor.execute_trade(signal)
    """

    # Solana token address (wrapped SOL)
    SOL_TOKEN_ADDRESS = "So11111111111111111111111111111111111111112"

    def __init__(
        self,
        wallet_address: str | None = None,
        chain: str = "sol",
        auto_confirm: bool = False,
        api_key: str | None = None,
        private_key_pem: str | None = None,
        risk_limits: RiskLimits | None = None,
        copy_risk: CopyRiskProfile | None = None,
        gate_config: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the real trade executor.

        Args:
            wallet_address: The Solana wallet address to trade from.
                Must be provided explicitly; no default is used.
            chain: Blockchain identifier (default ``"sol"``).
            auto_confirm: If ``True``, skip the stdin prompt. The gate and
                copy caps are still enforced.
            api_key: GMGN API key.  If ``None``, loaded from config.
            private_key_pem: Ed25519 private key PEM.  If ``None``, loaded
                from config.
            risk_limits: Risk management limits.  If ``None``, uses defaults.
            copy_risk: Absolute SOL and slippage caps. Defaults to the copy sheet.
            gate_config: When set, tests pin the gate. Production re-reads the
                gate file on every order so the kill switch applies immediately.
        """
        self._chain = chain
        self._wallet_address = wallet_address
        self._auto_confirm = auto_confirm
        self._copy_risk = copy_risk or load_copy_risk()
        self._gate_override = gate_config
        self._risk_limits = risk_limits or RiskLimits(
            daily_loss_limit_percent=5.0,
            max_single_position_percent=20.0,
            max_total_positions=3,
            default_stop_loss_percent=65.0,
        )

        # Load credentials from config if not provided
        cm = ConfigManager()
        self._api_key = api_key or cm.gmgn_api_key
        self._private_key_pem = private_key_pem or cm.gmgn_private_key

        if not self._api_key:
            raise RuntimeError(
                "GMGN API key is required for real-money trading. "
                "Set GMGN_API_KEY environment variable or configure ~/.config/gmgn/config.json"
            )
        if not self._private_key_pem:
            raise RuntimeError(
                "GMGN private key is required for real-money trading. "
                "Set GMGN_PRIVATE_KEY environment variable or ensure ~/.config/gmgn/keypair.pem exists"
            )

        # Initialize clients
        self._client = GmgnApiClient(
            api_key=self._api_key,
            private_key_pem=self._private_key_pem,
        )
        self._order_manager = OrderManager()
        self._risk_manager = RiskManager(self._risk_limits)
        self._portfolio = PortfolioTracker(initial_balance_sol=10.0)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_trade(self, signal: TradeSignal) -> ExecutionResult:
        """Execute a single real-money trade.

        Steps:
        1. Refuse unless the automation gate is open and the order is inside
           the copy caps
        2. Human confirmation (unless tiny auto-confirm is armed)
        3. Risk check
        4. Build swap parameters
        5. Submit via GMGN API (signed auth)
        6. Record execution result

        Args:
            signal: The trade signal to execute.

        Returns:
            An :class:`ExecutionResult` with success/failure details.
        """
        start_time = time.perf_counter()

        blocked = self._live_buy_block_reason(signal)
        if blocked:
            return ExecutionResult(
                success=False,
                trade_execution=None,
                order_id=None,
                tx_hash=None,
                error_message=blocked,
                gas_cost_sol=0.0,
                actual_slippage_percent=0.0,
                confirmation_time_ms=0.0,
            )

        # Human confirmation. Auto-confirm does not skip the gate above.
        if not self._auto_confirm:
            if not self._confirm_trade(signal):
                return ExecutionResult(
                    success=False,
                    trade_execution=None,
                    order_id=None,
                    tx_hash=None,
                    error_message="User cancelled the trade",
                    gas_cost_sol=0.0,
                    actual_slippage_percent=0.0,
                    confirmation_time_ms=0.0,
                )

        # 2. Risk check
        portfolio_snapshot = self._portfolio.get_snapshot()
        risk_result = self._risk_manager.check_trade(
            signal=signal,
            current_portfolio_value=portfolio_snapshot.total_value_sol,
            open_positions=[p.to_dict() for p in self._portfolio.list_positions()],
        )
        if risk_result != RiskCheckResult.ALLOW:
            return ExecutionResult(
                success=False,
                trade_execution=None,
                order_id=None,
                tx_hash=None,
                error_message=f"Risk check failed: {risk_result.name}",
                gas_cost_sol=0.0,
                actual_slippage_percent=0.0,
                confirmation_time_ms=0.0,
            )

        # 3. Create order record
        order = self._order_manager.create_order(signal)
        order_id = order.order_id

        # 4. Build swap parameters
        amount_lamports = int(signal.recommended_amount_sol * 1_000_000_000)  # SOL to lamports
        slippage_bps = int(signal.max_slippage_percent * 100)  # percent to basis points

        swap_params = {
            "chain": self._chain,
            "from_address": self._wallet_address or "",
            "input_token": self.SOL_TOKEN_ADDRESS,
            "output_token": signal.target_token,
            "input_amount": str(amount_lamports),
            "slippage": signal.max_slippage_percent,
            "auto_slippage": False,
        }

        # 5. Submit trade
        self._order_manager.submit_order(order_id)
        try:
            api_result = self._client.swap(swap_params)
            tx_hash = api_result.get("tx_hash") or api_result.get("order_id")
        except Exception as e:
            self._order_manager.fail_order(order_id, str(e))
            return ExecutionResult(
                success=False,
                trade_execution=None,
                order_id=order_id,
                tx_hash=None,
                error_message=str(e),
                gas_cost_sol=0.0,
                actual_slippage_percent=0.0,
                confirmation_time_ms=(time.perf_counter() - start_time) * 1000,
            )

        # 6. Confirm order
        # Estimate actual values (real values come from on-chain receipt)
        gas_cost = 0.01  # Estimated SOL gas cost
        slippage = signal.max_slippage_percent * 0.5  # Conservative estimate
        actual_amount = signal.recommended_amount_sol * (1.0 - slippage / 100.0)

        self._order_manager.confirm_order(
            order_id,
            actual_amount=actual_amount,
            actual_slippage=slippage,
            gas_cost=gas_cost,
        )

        # 7. Update portfolio
        self._portfolio.open_position(
            token_address=signal.target_token,
            entry_price_sol=actual_amount,
            quantity=1.0,  # Simplified: 1 unit per trade
        )

        # 8. Build TradeExecution
        trade_exec = TradeExecution(
            execution_id=order_id,
            signal_id=signal.signal_id,
            status="CONFIRMED",
            tx_hash=tx_hash,
            actual_amount_sol=actual_amount,
            actual_slippage_percent=slippage,
            gas_cost_sol=gas_cost,
            dry_run=False,  # <-- REAL MONEY
        )

        confirmation_time = (time.perf_counter() - start_time) * 1000

        return ExecutionResult(
            success=True,
            trade_execution=trade_exec,
            order_id=order_id,
            tx_hash=tx_hash,
            error_message=None,
            gas_cost_sol=gas_cost,
            actual_slippage_percent=slippage,
            confirmation_time_ms=confirmation_time,
        )

    def get_portfolio(self) -> PortfolioTracker:
        """Return the internal portfolio tracker."""
        return self._portfolio

    def get_order_manager(self) -> OrderManager:
        """Return the internal order manager."""
        return self._order_manager

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _current_gate(self) -> dict[str, Any]:
        override = getattr(self, "_gate_override", None)
        if isinstance(override, dict):
            return override
        return load_automation_gate()

    def _live_buy_block_reason(self, signal: TradeSignal) -> str | None:
        profile = getattr(self, "_copy_risk", None)
        if profile is None:
            return "live buy guard is not configured"
        snapshot = self._portfolio.get_snapshot()
        return live_buy_block_reason(
            amount_sol=signal.recommended_amount_sol,
            daily_pnl_sol=snapshot.daily_pnl_sol,
            slippage_percent=signal.max_slippage_percent,
            profile=profile,
            gate_config=self._current_gate(),
        )

    def _confirm_trade(self, signal: TradeSignal) -> bool:
        """Ask for human confirmation before submitting a real trade.

        Returns ``True`` if the user confirms, ``False`` otherwise.
        """
        print("\n" + "=" * 60)
        print(HUMAN_CONFIRMATION_REQUIRED)
        print("=" * 60)
        print(f"  Token:        {signal.target_token}")
        print(f"  Amount:       {signal.recommended_amount_sol:.6f} SOL")
        print(f"  Slippage:     {signal.max_slippage_percent:.1f}%")
        print(f"  Priority Fee: {signal.priority_fee_sol:.4f} SOL")
        print(f"  MEV Protect:  {signal.mev_protection}")
        print(f"  TP Levels:    {[f'{tp.trigger_percent:.0f}%' for tp in signal.tp_orders]}")
        print(f"  SL Level:     {signal.sl_order.trigger_percent if signal.sl_order else 'N/A'}%")
        print(f"  Wallet:       {self._wallet_address or 'NOT SET'}")
        print("=" * 60)

        try:
            response = input("\nSubmit this REAL-MONEY trade? [Y/N]: ").strip().upper()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return False

        return response == "Y" or response == "YES"
