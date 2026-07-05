from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4

from .backtest_engine import (
    BuyMode,
    CloseReason,
    CostModel,
    PaperTrade,
    SLLevel,
    StrategyConfig,
    TPLevel,
    TradeLifecycle,
    TradeStatus,
)


class StrategyType(Enum):
    """Named strategies from the spec."""

    FIXED_BUY = "fixed_buy"
    MAX_BUY = "max_buy"
    FIXED_RATIO = "fixed_ratio"
    SMART_MONEY_COPY = "smart_money_copy"
    SIGNAL_FOLLOW = "signal_follow"
    TRAILING_STOP = "trailing_stop"


@dataclass(frozen=True)
class FixedBuyStrategy:
    """Fixed Buy strategy: fixed 0.5–1 SOL per entry.

    TP: +100% sell 50%, +300% sell remaining 50%.
    SL: -65% sell 100%.
    """

    fixed_sol_amount: float = 0.5
    sol_price_usd: float = 150.0

    def to_config(self) -> StrategyConfig:
        return StrategyConfig(
            buy_mode=BuyMode.FIXED_BUY,
            fixed_sol_amount=self.fixed_sol_amount,
            sol_price_usd=self.sol_price_usd,
            tp_levels=(
                TPLevel(level=1, trigger_percent=100.0, sell_percent=50.0),
                TPLevel(level=2, trigger_percent=300.0, sell_percent=50.0),
            ),
            sl_level=SLLevel(trigger_percent=-65.0),
        )

    @classmethod
    def from_config(cls, config: StrategyConfig) -> "FixedBuyStrategy":
        return cls(
            fixed_sol_amount=config.fixed_sol_amount,
            sol_price_usd=config.sol_price_usd,
        )

    def create_trade(
        self,
        wallet_address: str,
        token_address: str,
        token_symbol: str,
        entry_price: float,
        entry_at: str,
        source_amount_usd: float = 0.0,
        backtest_batch_id: str = "",
    ) -> PaperTrade:
        """Create a paper trade with fixed SOL amount."""
        config = self.to_config()
        amount_sol = config.fixed_sol_amount
        amount_usd = amount_sol * config.sol_price_usd
        return PaperTrade(
            trade_id=str(uuid4()),
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol=token_symbol,
            follow_mode=BuyMode.FIXED_BUY,
            entry_price=entry_price,
            entry_amount_usd=amount_usd,
            entry_amount_sol=amount_sol,
            entry_at=entry_at,
            tp_levels=config.tp_levels,
            sl_level=config.sl_level,
            backtest_batch_id=backtest_batch_id,
            created_at=datetime.now().isoformat(),
        )


@dataclass(frozen=True)
class MaxBuyStrategy:
    """Max Buy strategy: set a cap; if the source wallet exceeds it, use the cap.

    TP: 2X sell 50%, 5X sell 30%, remaining 20% hold.
    SL: -40% sell 100%.
    """

    max_usd: float = 1000.0
    sol_price_usd: float = 150.0

    def to_config(self) -> StrategyConfig:
        return StrategyConfig(
            buy_mode=BuyMode.MAX_BUY,
            fixed_sol_amount=self.max_usd / self.sol_price_usd,
            sol_price_usd=self.sol_price_usd,
            tp_levels=(
                TPLevel(level=1, trigger_percent=100.0, sell_percent=50.0),
                TPLevel(level=2, trigger_percent=400.0, sell_percent=30.0),
                TPLevel(level=3, trigger_percent=500.0, sell_percent=20.0),
            ),
            sl_level=SLLevel(trigger_percent=-40.0),
        )

    @classmethod
    def from_config(cls, config: StrategyConfig) -> "MaxBuyStrategy":
        return cls(
            max_usd=config.fixed_sol_amount * config.sol_price_usd,
            sol_price_usd=config.sol_price_usd,
        )

    def create_trade(
        self,
        wallet_address: str,
        token_address: str,
        token_symbol: str,
        entry_price: float,
        entry_at: str,
        source_amount_usd: float = 0.0,
        backtest_batch_id: str = "",
    ) -> PaperTrade:
        """Create a paper trade capped at max_usd."""
        config = self.to_config()
        amount_usd = min(source_amount_usd, config.fixed_sol_amount * config.sol_price_usd) if source_amount_usd > 0 else config.fixed_sol_amount * config.sol_price_usd
        amount_sol = amount_usd / config.sol_price_usd
        return PaperTrade(
            trade_id=str(uuid4()),
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol=token_symbol,
            follow_mode=BuyMode.MAX_BUY,
            entry_price=entry_price,
            entry_amount_usd=amount_usd,
            entry_amount_sol=amount_sol,
            entry_at=entry_at,
            tp_levels=config.tp_levels,
            sl_level=config.sl_level,
            backtest_batch_id=backtest_batch_id,
            created_at=datetime.now().isoformat(),
        )


@dataclass(frozen=True)
class FixedRatioStrategy:
    """Fixed Ratio strategy: mirror the source wallet's position at 10–20%.

    Trailing TP: close 10% on 10% pullback from peak.
    Trailing SL: close 15% on 15% pullback from peak.
    """

    ratio: float = 0.1
    sol_price_usd: float = 150.0

    def to_config(self) -> StrategyConfig:
        return StrategyConfig(
            buy_mode=BuyMode.FIXED_RATIO,
            fixed_ratio=self.ratio,
            sol_price_usd=self.sol_price_usd,
            tp_levels=(
                TPLevel(level=1, trigger_percent=50.0, sell_percent=30.0),
                TPLevel(level=2, trigger_percent=100.0, sell_percent=30.0),
                TPLevel(level=3, trigger_percent=200.0, sell_percent=40.0),
            ),
            sl_level=SLLevel(trigger_percent=-30.0),
        )

    @classmethod
    def from_config(cls, config: StrategyConfig) -> "FixedRatioStrategy":
        return cls(
            ratio=config.fixed_ratio,
            sol_price_usd=config.sol_price_usd,
        )

    def create_trade(
        self,
        wallet_address: str,
        token_address: str,
        token_symbol: str,
        entry_price: float,
        entry_at: str,
        source_amount_usd: float = 0.0,
        backtest_batch_id: str = "",
    ) -> PaperTrade:
        """Create a paper trade proportional to the source wallet's entry."""
        config = self.to_config()
        amount_usd = source_amount_usd * config.fixed_ratio if source_amount_usd > 0 else 100.0
        amount_sol = amount_usd / config.sol_price_usd
        return PaperTrade(
            trade_id=str(uuid4()),
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol=token_symbol,
            follow_mode=BuyMode.FIXED_RATIO,
            entry_price=entry_price,
            entry_amount_usd=amount_usd,
            entry_amount_sol=amount_sol,
            entry_at=entry_at,
            tp_levels=config.tp_levels,
            sl_level=config.sl_level,
            backtest_batch_id=backtest_batch_id,
            created_at=datetime.now().isoformat(),
        )


@dataclass(frozen=True)
class BuySignal:
    """A structured buy signal extracted from wallet activity data.
    
    Represents a single wallet buying a specific token at a specific time and price,
    with a confidence score derived from the wallet's historical performance.
    """
    wallet_address: str
    token_address: str
    timestamp: str
    price_usd: float
    amount_sol: float
    confidence: float  # 0-1, based on wallet score

    def __post_init__(self) -> None:
        if not (0.0 <= self.confidence <= 1.0):
            object.__setattr__(
                self, "confidence", max(0.0, min(1.0, self.confidence))
            )


@dataclass(frozen=True)
class SmartMoneyCopyStrategy:
    """Smart Money Copy strategy: Follow a specific wallet's buy signals.
    
    When the target wallet buys a token, we copy the buy at the same price
    (with configurable delay/slippage). Uses TP/SL from the wallet's historical
    performance to estimate optimal levels.
    """
    target_wallet_address: str
    copy_ratio: float = 0.1  # Copy 10% of the target wallet's buy amount
    max_position_sol: float = 1.0  # Max 1 SOL per position
    tp_levels: tuple[TPLevel, ...] = (
        TPLevel(level=1, trigger_percent=100.0, sell_percent=50.0),
        TPLevel(level=2, trigger_percent=300.0, sell_percent=50.0),
    )
    sl_level: SLLevel = field(default_factory=lambda: SLLevel(trigger_percent=-65.0))
    entry_delay_hours: int = 0  # Delay before copying (0 = immediate)
    sol_price_usd: float = 150.0

    def to_config(self) -> StrategyConfig:
        return StrategyConfig(
            buy_mode=BuyMode.FIXED_RATIO,
            fixed_sol_amount=min(self.max_position_sol, 0.5),
            fixed_ratio=self.copy_ratio,
            sol_price_usd=self.sol_price_usd,
            tp_levels=self.tp_levels,
            sl_level=self.sl_level,
        )

    @classmethod
    def from_config(cls, config: StrategyConfig, target_wallet_address: str) -> "SmartMoneyCopyStrategy":
        return cls(
            target_wallet_address=target_wallet_address,
            copy_ratio=config.fixed_ratio,
            max_position_sol=config.fixed_sol_amount,
            sol_price_usd=config.sol_price_usd,
            tp_levels=config.tp_levels,
            sl_level=config.sl_level,
        )

    def generate_signals(self, wallet_activity: list[dict]) -> list[BuySignal]:
        """Generate buy signals from wallet activity data.
        
        wallet_activity is a list of activity entries, each with keys:
        token_address, action, price, amount, timestamp.
        Only entries where action == 'buy' are converted to signals.
        """
        signals: list[BuySignal] = []
        for entry in wallet_activity:
            if not isinstance(entry, dict):
                continue
            action = entry.get("action", "").lower()
            if action not in ("buy", "purchase", "swap_in"):
                continue
            try:
                amount_sol = float(entry.get("amount", 0.0))
                if amount_sol <= 0:
                    continue
                copied_amount = min(amount_sol * self.copy_ratio, self.max_position_sol)
                signal = BuySignal(
                    wallet_address=self.target_wallet_address,
                    token_address=entry.get("token_address", ""),
                    timestamp=entry.get("timestamp", ""),
                    price_usd=float(entry.get("price", 0.0)),
                    amount_sol=copied_amount,
                    confidence=float(entry.get("confidence", 0.7)),
                )
                signals.append(signal)
            except (ValueError, TypeError):
                continue
        return signals

    def create_trade_from_signal(
        self,
        signal: BuySignal,
        backtest_batch_id: str = "",
    ) -> PaperTrade:
        """Create a PaperTrade from a BuySignal."""
        config = self.to_config()
        amount_sol = min(signal.amount_sol, self.max_position_sol)
        amount_usd = amount_sol * config.sol_price_usd
        return PaperTrade(
            trade_id=str(uuid4()),
            wallet_address=signal.wallet_address,
            token_address=signal.token_address,
            token_symbol="UNKNOWN",
            follow_mode=BuyMode.FIXED_RATIO,
            entry_price=signal.price_usd,
            entry_amount_usd=amount_usd,
            entry_amount_sol=amount_sol,
            entry_at=signal.timestamp,
            tp_levels=config.tp_levels,
            sl_level=config.sl_level,
            backtest_batch_id=backtest_batch_id,
            created_at=datetime.now().isoformat(),
        )


@dataclass(frozen=True)
class SignalFollowStrategy:
    """Signal Follow strategy: Follow multiple smart wallets' consensus signals.
    
    Buys when >= N smart wallets buy the same token within a time window.
    """
    min_wallet_count: int = 3  # Minimum number of wallets buying
    time_window_hours: int = 6  # Time window for consensus
    buy_amount_sol: float = 0.5
    tp_levels: tuple[TPLevel, ...] = (
        TPLevel(level=1, trigger_percent=100.0, sell_percent=50.0),
        TPLevel(level=2, trigger_percent=300.0, sell_percent=50.0),
    )
    sl_level: SLLevel = field(default_factory=lambda: SLLevel(trigger_percent=-65.0))
    sol_price_usd: float = 150.0

    def to_config(self) -> StrategyConfig:
        return StrategyConfig(
            buy_mode=BuyMode.FIXED_BUY,
            fixed_sol_amount=self.buy_amount_sol,
            sol_price_usd=self.sol_price_usd,
            tp_levels=self.tp_levels,
            sl_level=self.sl_level,
        )

    @classmethod
    def from_config(cls, config: StrategyConfig) -> "SignalFollowStrategy":
        return cls(
            buy_amount_sol=config.fixed_sol_amount,
            sol_price_usd=config.sol_price_usd,
            tp_levels=config.tp_levels,
            sl_level=config.sl_level,
        )

    def generate_consensus_signals(
        self,
        wallet_activities: list[list[dict]],
    ) -> list[BuySignal]:
        """Generate consensus signals from multiple wallet activities.
        
        wallet_activities: list of activity lists, one per wallet.
        Each activity entry: {token_address, action, price, amount, timestamp, wallet_address, confidence}
        """
        all_signals: list[BuySignal] = []
        for activity_list in wallet_activities:
            for entry in activity_list:
                if not isinstance(entry, dict):
                    continue
                action = entry.get("action", "").lower()
                if action not in ("buy", "purchase", "swap_in"):
                    continue
                try:
                    signal = BuySignal(
                        wallet_address=entry.get("wallet_address", ""),
                        token_address=entry.get("token_address", ""),
                        timestamp=entry.get("timestamp", ""),
                        price_usd=float(entry.get("price", 0.0)),
                        amount_sol=float(entry.get("amount", 0.0)),
                        confidence=float(entry.get("confidence", 0.7)),
                    )
                    all_signals.append(signal)
                except (ValueError, TypeError):
                    continue

        # Group by token and time window
        consensus_signals: list[BuySignal] = []
        from datetime import datetime, timedelta
        from collections import defaultdict

        token_signals: dict[str, list[BuySignal]] = defaultdict(list)
        for sig in all_signals:
            token_signals[sig.token_address].append(sig)

        for token, signals in token_signals.items():
            if len(signals) < self.min_wallet_count:
                continue
            # Sort by timestamp
            signals.sort(key=lambda s: s.timestamp)
            # Find clusters within time_window_hours
            for i, anchor in enumerate(signals):
                window_signals = [anchor]
                try:
                    anchor_dt = datetime.fromisoformat(anchor.timestamp.replace("Z", "+00:00"))
                except ValueError:
                    continue
                for j in range(i + 1, len(signals)):
                    try:
                        other_dt = datetime.fromisoformat(signals[j].timestamp.replace("Z", "+00:00"))
                        if (other_dt - anchor_dt) <= timedelta(hours=self.time_window_hours):
                            window_signals.append(signals[j])
                    except ValueError:
                        continue
                if len(window_signals) >= self.min_wallet_count:
                    # Use average price and max confidence
                    avg_price = sum(s.price_usd for s in window_signals) / len(window_signals)
                    max_conf = max(s.confidence for s in window_signals)
                    consensus_signals.append(
                        BuySignal(
                            wallet_address="consensus",
                            token_address=token,
                            timestamp=anchor.timestamp,
                            price_usd=avg_price,
                            amount_sol=self.buy_amount_sol,
                            confidence=max_conf,
                        )
                    )
                    break  # One consensus signal per token cluster

        return consensus_signals

    def create_trade_from_signal(
        self,
        signal: BuySignal,
        backtest_batch_id: str = "",
    ) -> PaperTrade:
        """Create a PaperTrade from a consensus BuySignal."""
        config = self.to_config()
        amount_usd = self.buy_amount_sol * config.sol_price_usd
        return PaperTrade(
            trade_id=str(uuid4()),
            wallet_address=signal.wallet_address,
            token_address=signal.token_address,
            token_symbol="UNKNOWN",
            follow_mode=BuyMode.FIXED_BUY,
            entry_price=signal.price_usd,
            entry_amount_usd=amount_usd,
            entry_amount_sol=self.buy_amount_sol,
            entry_at=signal.timestamp,
            tp_levels=config.tp_levels,
            sl_level=config.sl_level,
            backtest_batch_id=backtest_batch_id,
            created_at=datetime.now().isoformat(),
        )


@dataclass(frozen=True)
class TrailingStopStrategy:
    """Trailing Stop strategy: Buy fixed amount, sell with trailing stop.
    
    Tracks highest price after entry, sells when price drops X% from peak.
    """
    fixed_sol_amount: float = 0.5
    trailing_stop_percent: float = 25.0  # Sell when price drops 25% from peak
    min_profit_percent: float = 50.0  # Minimum profit before trailing stop activates
    tp_levels: tuple[TPLevel, ...] = (
        TPLevel(level=1, trigger_percent=100.0, sell_percent=50.0),
    )
    sl_level: SLLevel = field(default_factory=lambda: SLLevel(trigger_percent=-65.0))
    sol_price_usd: float = 150.0

    def to_config(self) -> StrategyConfig:
        return StrategyConfig(
            buy_mode=BuyMode.FIXED_BUY,
            fixed_sol_amount=self.fixed_sol_amount,
            sol_price_usd=self.sol_price_usd,
            tp_levels=self.tp_levels,
            sl_level=self.sl_level,
            max_holding_days=30,  # Longer hold for trailing stop
        )

    @classmethod
    def from_config(cls, config: StrategyConfig) -> "TrailingStopStrategy":
        return cls(
            fixed_sol_amount=config.fixed_sol_amount,
            sol_price_usd=config.sol_price_usd,
            tp_levels=config.tp_levels,
            sl_level=config.sl_level,
        )

    def create_trade(
        self,
        wallet_address: str,
        token_address: str,
        token_symbol: str,
        entry_price: float,
        entry_at: str,
        source_amount_usd: float = 0.0,
        backtest_batch_id: str = "",
    ) -> PaperTrade:
        """Create a paper trade with trailing stop configuration."""
        config = self.to_config()
        amount_sol = config.fixed_sol_amount
        amount_usd = amount_sol * config.sol_price_usd
        return PaperTrade(
            trade_id=str(uuid4()),
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol=token_symbol,
            follow_mode=BuyMode.FIXED_BUY,
            entry_price=entry_price,
            entry_amount_usd=amount_usd,
            entry_amount_sol=amount_sol,
            entry_at=entry_at,
            tp_levels=config.tp_levels,
            sl_level=config.sl_level,
            backtest_batch_id=backtest_batch_id,
            created_at=datetime.now().isoformat(),
        )

    def should_exit(
        self,
        entry_price: float,
        highest_price: float,
        current_price: float,
    ) -> bool:
        """Determine if the trailing stop should trigger.
        
        Returns True if price has dropped trailing_stop_percent from the highest price
        AND min_profit_percent has been reached.
        """
        if entry_price <= 0:
            return False
        profit_percent = (highest_price - entry_price) / entry_price * 100.0
        if profit_percent < self.min_profit_percent:
            # Not enough profit yet, fall back to regular SL
            return (current_price - entry_price) / entry_price * 100.0 <= self.sl_level.trigger_percent
        if highest_price <= 0:
            return False
        drop_percent = (highest_price - current_price) / highest_price * 100.0
        return drop_percent >= self.trailing_stop_percent


class StrategyFactory:
    """Factory for creating strategy objects and trades from config or type name."""

    _STRATEGIES: dict[str, type] = {
        StrategyType.FIXED_BUY.value: FixedBuyStrategy,
        StrategyType.MAX_BUY.value: MaxBuyStrategy,
        StrategyType.FIXED_RATIO.value: FixedRatioStrategy,
        StrategyType.SMART_MONEY_COPY.value: SmartMoneyCopyStrategy,
        StrategyType.SIGNAL_FOLLOW.value: SignalFollowStrategy,
        StrategyType.TRAILING_STOP.value: TrailingStopStrategy,
    }

    @classmethod
    def get_strategy(cls, strategy_type: str | StrategyType) -> type:
        """Return the strategy class for the given type name."""
        key = strategy_type.value if isinstance(strategy_type, StrategyType) else strategy_type
        strategy_class = cls._STRATEGIES.get(key)
        if strategy_class is None:
            raise ValueError(f"unknown strategy type: {key}")
        return strategy_class

    @classmethod
    def create_trade(
        cls,
        strategy_type: str | StrategyType,
        wallet_address: str,
        token_address: str,
        token_symbol: str,
        entry_price: float,
        entry_at: str,
        source_amount_usd: float = 0.0,
        backtest_batch_id: str = "",
    ) -> PaperTrade:
        """Create a PaperTrade using the specified strategy."""
        strategy_class = cls.get_strategy(strategy_type)
        return strategy_class().create_trade(
            wallet_address=wallet_address,
            token_address=token_address,
            token_symbol=token_symbol,
            entry_price=entry_price,
            entry_at=entry_at,
            source_amount_usd=source_amount_usd,
            backtest_batch_id=backtest_batch_id,
        )

    @classmethod
    def create_config(cls, strategy_type: str | StrategyType, **kwargs: Any) -> StrategyConfig:
        """Create a StrategyConfig for the given type with optional overrides."""
        strategy_class = cls.get_strategy(strategy_type)
        instance = strategy_class(**kwargs)
        return instance.to_config()


def run_single_trade_simulation(
    strategy_type: str,
    price_series: list[dict[str, Any]],
    wallet_address: str,
    token_address: str,
    token_symbol: str = "UNKNOWN",
    source_amount_usd: float = 0.0,
    cost_model: CostModel | None = None,
) -> PaperTrade:
    """High-level helper: simulate one trade through a price series.

    *strategy_type* is one of ``fixed_buy``, ``max_buy``, ``fixed_ratio``.
    *price_series* is a list of ``{"timestamp": "...", "price": float}`` sorted
    chronologically.

    Returns the fully-finalized ``PaperTrade``.
    """
    if not price_series:
        raise ValueError("price_series must not be empty")

    entry_point = price_series[0]
    exit_point = price_series[-1]

    trade = StrategyFactory.create_trade(
        strategy_type=strategy_type,
        wallet_address=wallet_address,
        token_address=token_address,
        token_symbol=token_symbol,
        entry_price=entry_point["price"],
        entry_at=entry_point["timestamp"],
        source_amount_usd=source_amount_usd,
        backtest_batch_id="single-sim",
    )

    lifecycle = TradeLifecycle(trade)

    for point in price_series:
        lifecycle.update_price(point["price"], point["timestamp"])
        if lifecycle.status != TradeStatus.OPEN:
            break

    # Force-close if still open
    if lifecycle.status == TradeStatus.OPEN:
        lifecycle._execute_expiry(exit_point["price"], exit_point["timestamp"])  # type: ignore[misc]

    if cost_model is None:
        # Default conservative cost model
        cost_model = CostModel()

    return lifecycle.finalize(cost_model)
