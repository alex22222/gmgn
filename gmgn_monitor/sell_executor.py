from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import shutil
import subprocess
from time import perf_counter
from typing import Any, Literal
from uuid import uuid4

from .gmgn_api_client import GmgnApiClient, GmgnApiError
from .order_manager import OrderManager
from .portfolio_tracker import PortfolioTracker
from .risk_manager import RiskManager

__all__ = [
    "SellSignal",
    "SellExecutionResult",
    "SellExecution",
    "SellExecutor",
]

SOL_TOKEN_ADDRESS = "So11111111111111111111111111111111111111112"
DEFAULT_MAX_SLIPPAGE_PERCENT = 5.0
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
_CHAIN_OUTPUT_TOKENS = {
    "sol": SOL_TOKEN_ADDRESS,
    "bsc": "0x0000000000000000000000000000000000000000",
    "base": "0x0000000000000000000000000000000000000000",
    "eth": "0x0000000000000000000000000000000000000000",
}


@dataclass(frozen=True)
class SellSignal:
    """Structured sell signal derived from TP/SL triggers or manual/copy commands."""

    signal_id: str
    token_address: str
    sell_percent: float                         # 100=全卖，50=卖一半
    trigger_type: Literal["TP", "SL", "COPY_EXIT", "MANUAL"]
    trigger_price_usd: float | None = None
    max_slippage_percent: float = 0.0
    reason: str = ""

    def __post_init__(self) -> None:
        if not (0.0 < self.sell_percent <= 100.0):
            object.__setattr__(self, "sell_percent", max(0.0, min(100.0, self.sell_percent)))
        if not (0.0 <= self.max_slippage_percent <= 100.0):
            object.__setattr__(self, "max_slippage_percent", max(0.0, min(100.0, self.max_slippage_percent)))

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal_id": self.signal_id,
            "token_address": self.token_address,
            "sell_percent": self.sell_percent,
            "trigger_type": self.trigger_type,
            "trigger_price_usd": self.trigger_price_usd,
            "max_slippage_percent": self.max_slippage_percent,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class SellExecutionResult:
    """Outcome of a single sell execution attempt."""

    success: bool
    sell_execution: dict[str, Any] | None
    order_id: str | None
    tx_hash: str | None
    error_message: str | None
    gas_cost_sol: float
    actual_slippage_percent: float
    confirmation_time_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "sell_execution": self.sell_execution,
            "order_id": self.order_id,
            "tx_hash": self.tx_hash,
            "error_message": self.error_message,
            "gas_cost_sol": self.gas_cost_sol,
            "actual_slippage_percent": self.actual_slippage_percent,
            "confirmation_time_ms": self.confirmation_time_ms,
        }


@dataclass(frozen=True)
class SellExecution:
    """Record of a single sell execution attempt and its outcome."""

    execution_id: str
    signal_id: str
    status: Literal["PENDING", "SUBMITTED", "CONFIRMED", "FAILED", "CANCELLED"]
    tx_hash: str | None = None
    actual_amount_sol: float = 0.0
    actual_slippage_percent: float = 0.0
    gas_cost_sol: float = 0.0
    received_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    submitted_at: datetime | None = None
    confirmed_at: datetime | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.actual_amount_sol < 0:
            object.__setattr__(self, "actual_amount_sol", 0.0)
        if self.actual_slippage_percent < 0:
            object.__setattr__(self, "actual_slippage_percent", 0.0)
        if self.gas_cost_sol < 0:
            object.__setattr__(self, "gas_cost_sol", 0.0)

    def duration_ms(self) -> float | None:
        """Return total execution duration from received to confirmed (in ms)."""
        if self.received_at is None or self.confirmed_at is None:
            return None
        return (self.confirmed_at - self.received_at).total_seconds() * 1000.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "execution_id": self.execution_id,
            "signal_id": self.signal_id,
            "status": self.status,
            "tx_hash": self.tx_hash,
            "actual_amount_sol": self.actual_amount_sol,
            "actual_slippage_percent": self.actual_slippage_percent,
            "gas_cost_sol": self.gas_cost_sol,
            "received_at": self.received_at.isoformat(),
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "confirmed_at": self.confirmed_at.isoformat() if self.confirmed_at else None,
            "error_message": self.error_message,
        }


class SellExecutor:
    """Handles the on-chain execution of sell orders via GMGN swap API."""

    def __init__(
        self,
        wallet_address: str,
        chain: str,
        api_key: str,
        private_key_pem: str,
        risk_manager: RiskManager,
        order_manager: OrderManager,
        portfolio_tracker: PortfolioTracker,
        auto_confirm: bool = True,
    ) -> None:
        self._wallet_address = wallet_address
        self._chain = chain
        self._risk_manager = risk_manager
        self._order_manager = order_manager
        self._portfolio_tracker = portfolio_tracker
        self._auto_confirm = auto_confirm
        self._client = GmgnApiClient(api_key=api_key, private_key_pem=private_key_pem)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def execute_sell(self, sell_signal: SellSignal) -> SellExecutionResult:
        """Execute a sell from a :class:`SellSignal`.

        Pipeline:
        a) Confirm trade (or auto-skip if ``auto_confirm=True``).
        b) Check kill-switch / circuit-breaker.
        c) Query on-chain token balance.
        d) Compute sell amount.
        e) Build swap parameters.
        f) Submit swap via GMGN API.
        g) Update OrderManager.
        h) Update PortfolioTracker.
        i) Return :class:`SellExecutionResult`.
        """
        received_at = datetime.now(timezone.utc)
        execution_id = str(uuid4())

        # -- a) Confirmation ------------------------------------------------
        token_balance = self.get_token_balance(sell_signal.token_address)
        sell_amount = token_balance * sell_signal.sell_percent / 100.0
        confirmed = self._confirm_sell(sell_signal, sell_amount, token_balance)
        if not confirmed:
            execution = SellExecution(
                execution_id=execution_id,
                signal_id=sell_signal.signal_id,
                status="CANCELLED",
                error_message="User cancelled sell confirmation",
                received_at=received_at,
            )
            return SellExecutionResult(
                success=False,
                sell_execution=execution.to_dict(),
                order_id=None,
                tx_hash=None,
                error_message="User cancelled sell confirmation",
                gas_cost_sol=0.0,
                actual_slippage_percent=0.0,
                confirmation_time_ms=0.0,
            )

        # -- b) Risk checks -------------------------------------------------
        if self._risk_manager.is_kill_switch_active():
            return self._build_failure_result(
                execution_id, sell_signal, received_at, "Kill switch is active"
            )
        if self._risk_manager.is_circuit_breaker_active():
            return self._build_failure_result(
                execution_id, sell_signal, received_at, "Circuit breaker is active"
            )

        if token_balance <= 0.0:
            return self._build_failure_result(
                execution_id, sell_signal, received_at, "Zero token balance"
            )
        if sell_amount <= 0.0:
            return self._build_failure_result(
                execution_id, sell_signal, received_at, "Calculated sell amount is zero"
            )

        # -- c-f) Build params & submit swap --------------------------------
        submit_start = perf_counter()
        tx_hash: str | None = None
        swap_result: dict[str, Any] = {}
        try:
            swap_result = self._submit_swap(sell_signal, sell_amount)
            tx_hash = (
                swap_result.get("tx_hash")
                or swap_result.get("hash")
                or swap_result.get("transaction_hash")
                or swap_result.get("signature")
            )
        except GmgnApiError as e:
            return self._build_failure_result(
                execution_id,
                sell_signal,
                received_at,
                f"GMGN swap failed: {e.message}",
            )
        except Exception as e:
            return self._build_failure_result(
                execution_id,
                sell_signal,
                received_at,
                f"Unexpected swap error: {e}",
            )

        submitted_at = datetime.now(timezone.utc)

        # -- g) Update OrderManager ----------------------------------------
        order = self._order_manager.create_sell_order(
            token_address=sell_signal.token_address,
            amount_sol=sell_amount,
            signal_id=sell_signal.signal_id,
        )
        self._order_manager.submit_order(order.order_id, tx_hash=tx_hash)

        actual_slippage = self._extract_slippage(swap_result)
        gas_cost = self._extract_gas_cost(swap_result)
        actual_amount = sell_amount * (1.0 - actual_slippage / 100.0)

        self._order_manager.confirm_order(
            order.order_id,
            actual_amount=actual_amount,
            actual_slippage=actual_slippage,
            gas_cost=gas_cost,
        )

        confirmed_at = datetime.now(timezone.utc)

        # -- h) Update PortfolioTracker -------------------------------------
        position = self._portfolio_tracker.get_position(sell_signal.token_address)
        if position is not None:
            current_price = position.current_price_sol
            if sell_signal.sell_percent >= 99.9:
                self._portfolio_tracker.close_position(
                    sell_signal.token_address, exit_price_sol=current_price
                )
            else:
                self._portfolio_tracker.reduce_position(
                    sell_signal.token_address,
                    quantity=sell_amount,
                    current_price_sol=current_price,
                )

        # -- i) Build result -----------------------------------------------
        execution = SellExecution(
            execution_id=execution_id,
            signal_id=sell_signal.signal_id,
            status="CONFIRMED",
            tx_hash=tx_hash,
            actual_amount_sol=actual_amount,
            actual_slippage_percent=actual_slippage,
            gas_cost_sol=gas_cost,
            received_at=received_at,
            submitted_at=submitted_at,
            confirmed_at=confirmed_at,
        )
        confirmation_time_ms = (perf_counter() - submit_start) * 1000.0

        return SellExecutionResult(
            success=True,
            sell_execution=execution.to_dict(),
            order_id=order.order_id,
            tx_hash=tx_hash,
            error_message=None,
            gas_cost_sol=gas_cost,
            actual_slippage_percent=actual_slippage,
            confirmation_time_ms=round(confirmation_time_ms, 2),
        )

    def get_token_balance(self, token_address: str) -> float:
        """Return the on-chain token balance for *token_address* (in token units)."""
        try:
            holdings = self._client.get_wallet_holdings(
                self._chain, self._wallet_address
            )
        except Exception:
            return 0.0

        items = self._extract_holding_items(holdings)
        wanted = token_address.lower()
        for item in items:
            addr = self._extract_holding_token_address(item)
            if addr and addr.lower() == wanted:
                balance = (
                    item.get("balance")
                    or item.get("amount")
                    or item.get("uiAmount")
                    or item.get("ui_amount")
                    or item.get("amount_raw")
                )
                if balance is not None:
                    try:
                        return float(balance)
                    except (TypeError, ValueError):
                        continue
        return 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _submit_swap(self, sell_signal: SellSignal, sell_amount: float) -> dict[str, Any]:
        if shutil.which("gmgn-cli"):
            return self._submit_swap_with_cli(sell_signal)

        swap_params = {
            "chain": self._chain,
            "from_address": self._wallet_address,
            "input_token": sell_signal.token_address,
            "output_token": _CHAIN_OUTPUT_TOKENS.get(self._chain, SOL_TOKEN_ADDRESS),
            "input_amount": sell_amount,
            "slippage": self._sell_slippage_percent(sell_signal),
            "auto_slippage": False,
        }
        return self._client.swap(swap_params)

    def _submit_swap_with_cli(self, sell_signal: SellSignal) -> dict[str, Any]:
        config_check = subprocess.run(
            ["gmgn-cli", "config", "--check"],
            cwd=_PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if config_check.returncode != 0:
            message = (config_check.stderr or config_check.stdout or "gmgn-cli config --check failed").strip()
            raise RuntimeError(f"gmgn-cli config --check failed: {message}")

        chain = self._chain.lower().strip() or "sol"
        output_token = _CHAIN_OUTPUT_TOKENS.get(chain)
        if not output_token:
            raise RuntimeError(f"Unsupported chain: {self._chain}")

        command = [
            "gmgn-cli",
            "swap",
            "--chain", chain,
            "--from", self._wallet_address,
            "--input-token", sell_signal.token_address,
            "--output-token", output_token,
            "--percent", self._format_cli_number(sell_signal.sell_percent),
            "--slippage", str(int(min(100, max(0, math.ceil(self._sell_slippage_percent(sell_signal)))))),
            "--raw",
        ]
        if chain != "base":
            command.append("--anti-mev")

        try:
            result = subprocess.run(
                command,
                cwd=_PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=180,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("gmgn-cli swap timed out") from exc

        if result.returncode != 0:
            message = (result.stderr or result.stdout or f"gmgn-cli swap exited {result.returncode}").strip()
            raise RuntimeError(f"gmgn-cli swap failed: {message}")

        return self._parse_cli_json(result.stdout)

    @staticmethod
    def _sell_slippage_percent(sell_signal: SellSignal) -> float:
        slippage = sell_signal.max_slippage_percent or DEFAULT_MAX_SLIPPAGE_PERCENT
        return min(100.0, max(0.0, slippage))

    @staticmethod
    def _format_cli_number(value: float) -> str:
        if value == int(value):
            return str(int(value))
        return f"{value:.6f}".rstrip("0").rstrip(".")

    @staticmethod
    def _parse_cli_json(output: str) -> dict[str, Any]:
        text = output.strip()
        if not text:
            raise RuntimeError("gmgn-cli swap returned empty output")
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            for index, char in enumerate(text):
                if char in "[{":
                    try:
                        payload = json.loads(text[index:])
                        break
                    except json.JSONDecodeError:
                        continue
            else:
                raise RuntimeError("gmgn-cli swap returned non-JSON output")
        if not isinstance(payload, dict):
            raise RuntimeError("gmgn-cli swap returned a non-object payload")
        return payload

    @staticmethod
    def _extract_holding_items(holdings: Any) -> list[dict[str, Any]]:
        if isinstance(holdings, list):
            return [item for item in holdings if isinstance(item, dict)]
        if not isinstance(holdings, dict):
            return []

        for key in ("holdings", "items", "list"):
            value = holdings.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]

        data = holdings.get("data")
        if isinstance(data, (dict, list)):
            return SellExecutor._extract_holding_items(data)
        return []

    @staticmethod
    def _extract_holding_token_address(item: dict[str, Any]) -> str | None:
        for key in ("token_address", "address", "mint"):
            value = item.get(key)
            if isinstance(value, str) and value:
                return value

        token = item.get("token")
        if isinstance(token, str) and token:
            return token
        if isinstance(token, dict):
            for key in ("token_address", "address", "mint"):
                value = token.get(key)
                if isinstance(value, str) and value:
                    return value
        return None

    def _confirm_sell(
        self, sell_signal: SellSignal, sell_amount: float, token_balance: float
    ) -> bool:
        """Print sell details and prompt for confirmation.

        Returns ``True`` immediately when ``auto_confirm=True``.
        """
        if self._auto_confirm:
            return True
        print("\n" + "=" * 50)
        print("[Sell Confirmation Required]")
        print(f"  Token Address : {sell_signal.token_address}")
        print(f"  Trigger Type  : {sell_signal.trigger_type}")
        print(f"  Sell Percent  : {sell_signal.sell_percent}%")
        print(f"  Token Balance : {token_balance}")
        print(f"  Sell Amount   : {sell_amount}")
        if sell_signal.trigger_price_usd is not None:
            print(f"  Trigger Price : ${sell_signal.trigger_price_usd:.6f}")
        print(f"  Reason        : {sell_signal.reason}")
        print("=" * 50)
        try:
            response = input("Confirm sell? [Y/N]: ").strip().lower()
        except (EOFError, OSError):
            return False
        return response == "y"

    def _build_failure_result(
        self,
        execution_id: str,
        sell_signal: SellSignal,
        received_at: datetime,
        error_message: str,
    ) -> SellExecutionResult:
        """Build a failed :class:`SellExecutionResult` with a :class:`SellExecution` record."""
        execution = SellExecution(
            execution_id=execution_id,
            signal_id=sell_signal.signal_id,
            status="FAILED",
            error_message=error_message,
            received_at=received_at,
        )
        return SellExecutionResult(
            success=False,
            sell_execution=execution.to_dict(),
            order_id=None,
            tx_hash=None,
            error_message=error_message,
            gas_cost_sol=0.0,
            actual_slippage_percent=0.0,
            confirmation_time_ms=0.0,
        )

    @staticmethod
    def _extract_slippage(swap_result: dict[str, Any]) -> float:
        """Try to extract slippage percent from swap response, fallback to 0.3."""
        for key in ("slippage", "actual_slippage", "slippage_percent"):
            val = swap_result.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
        return 0.3

    @staticmethod
    def _extract_gas_cost(swap_result: dict[str, Any]) -> float:
        """Try to extract gas cost (SOL) from swap response, fallback to 0.02."""
        for key in ("gas_cost", "gas_cost_sol", "fee", "fee_sol"):
            val = swap_result.get(key)
            if val is not None:
                try:
                    return float(val)
                except (TypeError, ValueError):
                    continue
        return 0.02
