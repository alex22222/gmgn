from __future__ import annotations

from dataclasses import dataclass, fields
from math import isclose, isfinite
from pathlib import Path
from typing import Any

from .serialization import load_json
from .wallet_scorer import WalletScoringWeights


# ---------------------------------------------------------------------------
# Copy-trading configuration (Phase 2)
# ---------------------------------------------------------------------------

@dataclass
class CopyTradingWalletConfig:
    """单个白名单钱包的跟单配置。"""
    wallet_address: str
    label: str
    tags: list[str]
    total_score: float
    grade: str
    copy_weight: float
    mode: str
    enabled: bool
    risk_limits: dict[str, Any]
    stats_snapshot: dict[str, Any]
    notes: str


@dataclass
class CopyTradingConfig:
    """白名单跟单全局配置。"""
    version: str
    exposure_level: str
    trade_mode: str
    wallets: list[CopyTradingWalletConfig]
    global_settings: dict[str, Any]
    weight_calculation: dict[str, Any]


@dataclass
class SignalSource:
    """单个信号源配置。"""
    wallet_address: str
    source_type: str
    priority: int
    label: str
    tags: list[str]
    total_score: float
    enabled: bool
    signal_types: list[str]
    copy_weight: float
    risk_tier: str
    max_single_trade_sol: float
    slippage_percent: float
    notes: str


@dataclass
class SignalSourcesConfig:
    """信号源全局配置。"""
    version: str
    signal_sources: list[SignalSource]
    signal_processing: dict[str, Any]
    risk_gates: dict[str, Any]


def load_copy_trading_config(path: Path) -> CopyTradingConfig:
    """Load copy-trading whitelist config from JSON.

    Args:
        path: Path to ``wallet_whitelist.json``.

    Returns:
        A :class:`CopyTradingConfig` instance.

    Raises:
        ValueError: On malformed JSON or missing required fields.
    """
    raw = load_json(path, label='copy trading config')
    if not isinstance(raw, dict):
        raise ValueError('copy trading config must be an object')

    wallets_raw = raw.get('wallets', [])
    if not isinstance(wallets_raw, list):
        raise ValueError('wallets must be a list')

    wallets = []
    for w in wallets_raw:
        if not isinstance(w, dict):
            raise ValueError('each wallet entry must be an object')
        wallets.append(CopyTradingWalletConfig(
            wallet_address=w.get('wallet_address', ''),
            label=w.get('label', ''),
            tags=w.get('tags', []),
            total_score=float(w.get('total_score', 0)),
            grade=w.get('grade', ''),
            copy_weight=float(w.get('copy_weight', 0)),
            mode=w.get('mode', 'follow'),
            enabled=bool(w.get('enabled', True)),
            risk_limits=w.get('risk_limits', {}),
            stats_snapshot=w.get('stats_snapshot', {}),
            notes=w.get('notes', ''),
        ))

    return CopyTradingConfig(
        version=raw.get('version', '1.0'),
        exposure_level=raw.get('exposure_level', 'mini_real'),
        trade_mode=raw.get('trade_mode', 'dryrun'),
        wallets=wallets,
        global_settings=raw.get('global_settings', {}),
        weight_calculation=raw.get('weight_calculation', {}),
    )


def load_signal_sources_config(path: Path) -> SignalSourcesConfig:
    """Load signal-sources config from JSON.

    Args:
        path: Path to ``signal_sources.json``.

    Returns:
        A :class:`SignalSourcesConfig` instance.

    Raises:
        ValueError: On malformed JSON or missing required fields.
    """
    raw = load_json(path, label='signal sources config')
    if not isinstance(raw, dict):
        raise ValueError('signal sources config must be an object')

    sources_raw = raw.get('signal_sources', [])
    if not isinstance(sources_raw, list):
        raise ValueError('signal_sources must be a list')

    sources = []
    for s in sources_raw:
        if not isinstance(s, dict):
            raise ValueError('each signal source entry must be an object')
        sources.append(SignalSource(
            wallet_address=s.get('wallet_address', ''),
            source_type=s.get('source_type', ''),
            priority=int(s.get('priority', 0)),
            label=s.get('label', ''),
            tags=s.get('tags', []),
            total_score=float(s.get('total_score', 0)),
            enabled=bool(s.get('enabled', True)),
            signal_types=s.get('signal_types', ['buy']),
            copy_weight=float(s.get('copy_weight', 0)),
            risk_tier=s.get('risk_tier', 'mini_real'),
            max_single_trade_sol=float(s.get('max_single_trade_sol', 0.005)),
            slippage_percent=float(s.get('slippage_percent', 2.0)),
            notes=s.get('notes', ''),
        ))

    return SignalSourcesConfig(
        version=raw.get('version', '1.0'),
        signal_sources=sources,
        signal_processing=raw.get('signal_processing', {}),
        risk_gates=raw.get('risk_gates', {}),
    )


# ---------------------------------------------------------------------------
# Wallet scoring configuration (existing)
# ---------------------------------------------------------------------------

class WalletScoringConfig:
    """Per-chain wallet scoring configuration, mirroring the existing
    :class:`ThresholdConfig` pattern.

    Supports a ``default`` weight set plus optional ``chains`` overrides.
    Unknown chains fall back to the default.
    """

    def __init__(
        self,
        default: WalletScoringWeights | None = None,
        chains: dict[str, WalletScoringWeights] | None = None,
    ):
        self.default = default or WalletScoringWeights()
        self.chains = chains or {}

    def for_chain(self, chain: str) -> WalletScoringWeights:
        """Return the scoring weights for *chain*, falling back to the default."""
        return self.chains.get(chain.lower(), self.default)


def load_wallet_scoring_config(path: Path) -> WalletScoringConfig:
    """Load a wallet-scoring config from a JSON file.

    The JSON must be an object with an optional ``default`` key and an optional
    ``chains`` key.  ``default`` provides the baseline weights; each entry in
    ``chains`` overrides specific fields for that chain.  Unknown fields are
    rejected.  Dimension weights must sum to approximately 1.0.

    Args:
        path: Path to the JSON configuration file.

    Returns:
        A :class:`WalletScoringConfig` instance.

    Raises:
        ValueError: On malformed JSON, missing required structure, unknown
            fields, invalid numeric values, or weights that do not sum to 1.0.
    """
    raw = load_json(path, label='wallet scoring config')
    if not isinstance(raw, dict):
        raise ValueError('wallet scoring config must be an object')

    default_values = raw.get('default', {})
    if not isinstance(default_values, dict):
        raise ValueError('default wallet scoring weights must be an object')

    chain_values = raw.get('chains', {})
    if not isinstance(chain_values, dict):
        raise ValueError('chains wallet scoring weights must be an object')

    default = _weights_from_dict(default_values, WalletScoringWeights(), 'default')
    chains = {
        chain.lower(): _weights_from_dict(values, default, chain.lower())
        for chain, values in chain_values.items()
    }

    _validate_weights_sum(default)
    for chain, weights in chains.items():
        _validate_weights_sum(weights)

    return WalletScoringConfig(default=default, chains=chains)


def _weights_from_dict(
    values: dict[str, Any],
    base: WalletScoringWeights,
    label: str,
) -> WalletScoringWeights:
    """Merge a dict of weight overrides into a base :class:`WalletScoringWeights`."""
    if not isinstance(values, dict):
        raise ValueError(f'{label} wallet scoring weights must be an object')

    allowed = {field.name for field in fields(WalletScoringWeights)}
    unknown = sorted(set(values) - allowed)
    if unknown:
        raise ValueError(f'unknown wallet scoring weight fields: {", ".join(unknown)}')

    merged = {field.name: getattr(base, field.name) for field in fields(WalletScoringWeights)}
    merged.update(values)
    _validate_weight_values(merged)
    return WalletScoringWeights(**merged)


def _validate_weight_values(values: dict[str, Any]) -> None:
    """Validate numeric constraints for each weight field."""
    weight_fields = {
        'profitability',
        'win_rate',
        'risk_control',
        'consistency',
        'activity',
        'stability',
    }
    threshold_fields = {
        'copy_threshold',
        'watch_threshold',
        'observe_threshold',
        'max_robot_score',
        'min_win_rate_hard',
        'min_avg_holding_hours',
        'min_total_pnl',
        'bot_pattern_penalty_threshold',
        'win_rate_penalty_threshold',
    }
    integer_fields = {
        'min_trades_for_scoring',
        'max_trades_7d',
        'min_total_trades_for_pnl_check',
    }

    for name, value in values.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f'{name} must be numeric')
        if not isfinite(value):
            raise ValueError(f'{name} must be finite')

        if name in weight_fields:
            if value < 0 or value > 1:
                raise ValueError(f'{name} weight must be between 0 and 1')
        elif name in threshold_fields:
            if value < 0 or value > 100:
                raise ValueError(f'{name} must be between 0 and 100')
        elif name in integer_fields:
            if not float(value).is_integer():
                raise ValueError(f'{name} must be an integer')
            if value < 0:
                raise ValueError(f'{name} must be non-negative')
        else:
            # Catch-all for any future numeric fields
            if value < 0:
                raise ValueError(f'{name} must be non-negative')


def _validate_weights_sum(weights: WalletScoringWeights) -> None:
    """Ensure the six dimension weights sum to approximately 1.0."""
    weight_fields = ('profitability', 'win_rate', 'risk_control', 'consistency', 'activity', 'stability')
    total = sum(getattr(weights, f) for f in weight_fields)
    if not isclose(total, 1.0, abs_tol=0.01):
        raise ValueError(f'dimension weights must sum to 1.0 (got {total})')
