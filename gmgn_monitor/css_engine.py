"""Comprehensive Signal Score (CSS) decision engine.

The :class:`CSSEngine` evaluates incoming trade signals across five dimensions
(wallet quality, token risk, market condition, account state, time momentum) and
produces a normalised CSS score (0–100) together with a PASS / WATCH / REJECT
decision.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from .trade_signal import TradeSignal


__all__ = [
    "CSSWeights",
    "AccountState",
    "TokenRiskScore",
    "MarketCondition",
    "TimeMomentum",
    "CSSDecision",
    "CSSResult",
    "CSSEngine",
]


@dataclass(frozen=True)
class CSSWeights:
    """Weight configuration for the Comprehensive Signal Score (CSS).

    All fields are expressed as decimals (e.g. 0.25 = 25%).
    They must sum to 1.0 (within a small tolerance).
    """

    wallet: float = 0.25
    token_risk: float = 0.20
    market_condition: float = 0.15
    account_state: float = 0.20
    time_momentum: float = 0.20

    def __post_init__(self) -> None:
        total = (
            self.wallet
            + self.token_risk
            + self.market_condition
            + self.account_state
            + self.time_momentum
        )
        if not (0.99 <= total <= 1.01):
            raise ValueError(f"CSS weights must sum to 1.0, got {total:.4f}")

    @classmethod
    def default_weights(cls) -> CSSWeights:
        """Return the factory-default weight configuration."""
        return cls(0.25, 0.20, 0.15, 0.20, 0.20)


@dataclass(frozen=True)
class AccountState:
    """Snapshot of the trading account's current condition.

    *can_trade* is computed automatically: it becomes ``False`` when the daily
    loss limit is exceeded **or** when the maximum number of open positions is
    reached.
    """

    balance_sol: float
    open_positions_count: int
    daily_pnl_sol: float
    daily_loss_limit_sol: float
    max_positions: int
    can_trade: bool = field(init=False)

    def __post_init__(self) -> None:
        loss_exceeded = self.daily_pnl_sol < -self.daily_loss_limit_sol
        positions_maxed = self.open_positions_count >= self.max_positions
        object.__setattr__(self, "can_trade", not (loss_exceeded or positions_maxed))


@dataclass(frozen=True)
class TokenRiskScore:
    """Token-level risk assessment."""

    liquidity_score: float  # 0-100
    contract_safe: bool
    market_cap_usd: float
    holder_count: int


@dataclass(frozen=True)
class MarketCondition:
    """Overall market environment snapshot."""

    btc_trend_24h: float  # percent, e.g. +5.0 or -3.5
    overall_sentiment: float  # 0-100
    fear_greed_index: float  # 0-100


@dataclass(frozen=True)
class TimeMomentum:
    """Temporal and on-chain momentum indicators."""

    signal_age_seconds: float
    chain_activity_score: float  # 0-100
    volume_surge_1h: float  # percent, e.g. +150.0


class CSSDecision(Enum):
    """Final execution decision produced by the CSS engine."""

    PASS = "pass"
    WATCH = "watch"
    REJECT = "reject"


@dataclass(frozen=True)
class CSSResult:
    """Full evaluation result including the raw sub-scores and metadata."""

    decision: CSSDecision
    css_score: float
    wallet_score: float
    token_risk_score: float
    market_condition_score: float
    account_state_score: float
    time_momentum_score: float
    can_trade: bool
    details: dict[str, Any] = field(default_factory=dict)

    @property
    def is_pass(self) -> bool:
        """True when the decision is PASS."""
        return self.decision == CSSDecision.PASS

    @property
    def is_watch(self) -> bool:
        """True when the decision is WATCH."""
        return self.decision == CSSDecision.WATCH

    @property
    def is_reject(self) -> bool:
        """True when the decision is REJECT."""
        return self.decision == CSSDecision.REJECT


class CSSEngine:
    """Comprehensive Signal Score (CSS) decision engine.

    Computes a weighted composite score from five normalised sub-scores and
    maps it to a PASS / WATCH / REJECT decision based on the thresholds
    defined in the project SPEC.

    Usage::

        engine = CSSEngine()
        result = engine.evaluate(
            signal=trade_signal,
            wallet_score=85.0,
            token_risk=token_risk_score,
            market=market_condition,
            account=account_state,
            momentum=time_momentum,
        )
        if result.is_pass:
            execute_trade(signal)
    """

    def __init__(
        self,
        weights: CSSWeights | None = None,
        *,
        pass_score: float = 70.0,
        watch_score: float = 50.0,
    ) -> None:
        """Initialise the engine with optional custom weights and decision lines.

        The monitor pipeline keeps the factory lines: PASS at 70, WATCH at 50.
        Copy execution passes its own lines from ``config/copy_risk.json``.

        Args:
            weights: Optional weight overrides. Defaults to ``CSSWeights.default_weights()``.
            pass_score: Minimum CSS that can become an order when the account can trade.
            watch_score: Minimum CSS that stays observable without an order.
        """
        if not 0.0 <= float(watch_score) <= float(pass_score) <= 100.0:
            raise ValueError("CSS watch_score must be between 0 and pass_score, and pass_score at most 100")
        self.weights = weights or CSSWeights.default_weights()
        self.pass_score = float(pass_score)
        self.watch_score = float(watch_score)

    @classmethod
    def default_weights(cls) -> CSSWeights:
        """Return the factory-default weight configuration."""
        return CSSWeights.default_weights()

    def evaluate(
        self,
        signal: TradeSignal,
        wallet_score: float,
        token_risk: TokenRiskScore,
        market: MarketCondition,
        account: AccountState,
        momentum: TimeMomentum,
    ) -> CSSResult:
        """Evaluate a single trade signal and return the CSS decision.

        Each sub-score is normalised to the 0–100 range before being fed into
        the weighted composite formula.

        Args:
            signal: The incoming trade signal to evaluate.
            wallet_score: Wallet quality score (0-100) from the scoring engine.
            token_risk: Token risk assessment.
            market: Current market environment.
            account: Current trading account state.
            momentum: Temporal momentum indicators.

        Returns:
            A :class:`CSSResult` containing the decision, raw score, and all
            normalised sub-scores for auditing.
        """
        # Normalise each sub-score to 0-100
        token_risk_score = self._normalize_token_risk(token_risk)
        market_score = self._normalize_market_condition(market)
        account_score = self._normalize_account_state(account)
        momentum_score = self._normalize_time_momentum(momentum)

        # Clamp wallet score to valid range
        wallet_score = max(0.0, min(100.0, wallet_score))

        css = (
            wallet_score * self.weights.wallet
            + token_risk_score * self.weights.token_risk
            + market_score * self.weights.market_condition
            + account_score * self.weights.account_state
            + momentum_score * self.weights.time_momentum
        )

        if css >= self.pass_score and account.can_trade:
            decision = CSSDecision.PASS
        elif css >= self.watch_score and account.can_trade:
            decision = CSSDecision.WATCH
        else:
            decision = CSSDecision.REJECT

        return CSSResult(
            decision=decision,
            css_score=round(css, 2),
            wallet_score=round(wallet_score, 2),
            token_risk_score=round(token_risk_score, 2),
            market_condition_score=round(market_score, 2),
            account_state_score=round(account_score, 2),
            time_momentum_score=round(momentum_score, 2),
            can_trade=account.can_trade,
            details={
                "signal_id": signal.signal_id,
                "wallet_address": signal.wallet_address,
                "target_token": signal.target_token,
                "signal_type": signal.signal_type,
                "pass_score": self.pass_score,
                "watch_score": self.watch_score,
            },
        )

    # ------------------------------------------------------------------
    # Normalisation helpers
    # ------------------------------------------------------------------

    def _normalize_token_risk(self, tr: TokenRiskScore) -> float:
        """Map a :class:`TokenRiskScore` to a 0-100 score.

        Composition:
        - liquidity_score (30%)
        - contract_safe (30%)
        - market_cap_usd (20%)
        - holder_count (20%)
        """
        liquidity = max(0.0, min(100.0, tr.liquidity_score))
        contract = 100.0 if tr.contract_safe else 0.0

        # Market cap: log-scale from $10k → 10, $1M → 50, $100M → 100
        if tr.market_cap_usd <= 0:
            mcap_score = 0.0
        else:
            mcap_score = min(
                100.0, max(0.0, 10.0 + 30.0 * math.log10(tr.market_cap_usd / 10_000.0))
            )

        # Holder count: log-scale from 100 → 20, 1k → 50, 10k → 80, 100k → 100
        if tr.holder_count <= 0:
            holder_score = 0.0
        else:
            holder_score = min(
                100.0, max(0.0, 20.0 + 30.0 * math.log10(tr.holder_count / 100.0))
            )

        return liquidity * 0.3 + contract * 0.3 + mcap_score * 0.2 + holder_score * 0.2

    def _normalize_market_condition(self, mc: MarketCondition) -> float:
        """Map a :class:`MarketCondition` to a 0-100 score.

        Composition:
        - btc_trend_24h (40%): -20% → 0, 0% → 50, +20% → 100
        - overall_sentiment (30%)
        - fear_greed_index (30%)
        """
        btc_score = min(100.0, max(0.0, 50.0 + mc.btc_trend_24h * 2.5))
        sentiment = max(0.0, min(100.0, mc.overall_sentiment))
        fear_greed = max(0.0, min(100.0, mc.fear_greed_index))
        return btc_score * 0.4 + sentiment * 0.3 + fear_greed * 0.3

    def _normalize_account_state(self, acc: AccountState) -> float:
        """Map an :class:`AccountState` to a 0-100 score.

        Composition:
        - balance_sol (30%): 0 → 0, 5+ → 100
        - position capacity (30%): full → 0, empty → 100
        - daily PnL vs limit (40%): at loss limit → 0, break-even → 50, +limit → 100
        """
        balance_score = min(100.0, max(0.0, acc.balance_sol * 20.0))

        if acc.max_positions <= 0:
            pos_score = 0.0
        else:
            available = acc.max_positions - acc.open_positions_count
            pos_score = min(100.0, max(0.0, (available / acc.max_positions) * 100.0))

        limit = acc.daily_loss_limit_sol if acc.daily_loss_limit_sol > 0 else 1.0
        pnl_score = min(100.0, max(0.0, 50.0 + (acc.daily_pnl_sol / limit) * 50.0))

        return balance_score * 0.3 + pos_score * 0.3 + pnl_score * 0.4

    def _normalize_time_momentum(self, tm: TimeMomentum) -> float:
        """Map a :class:`TimeMomentum` to a 0-100 score.

        Composition:
        - signal freshness (40%): 0s → 100, 300s → 0
        - chain_activity_score (30%)
        - volume_surge_1h (30%): 0% → 50, +50% → 100
        """
        if tm.signal_age_seconds <= 0:
            freshness = 100.0
        elif tm.signal_age_seconds >= 300.0:
            freshness = 0.0
        else:
            freshness = max(0.0, 100.0 - (tm.signal_age_seconds / 300.0) * 100.0)

        activity = max(0.0, min(100.0, tm.chain_activity_score))
        volume_score = min(100.0, max(0.0, 50.0 + tm.volume_surge_1h))

        return freshness * 0.4 + activity * 0.3 + volume_score * 0.3
