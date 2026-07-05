from __future__ import annotations

"""GMGN Monitor package — token scoring and smart wallet discovery.

Phase 1 (wallet discovery) modules are imported opportunistically.
If they are not yet present, the package falls back to monitor-only mode
without crashing.
"""

from .schema import Candidate
from .scoring import Thresholds, score_candidate
from .sources import CandidateSource, JsonlCandidateSource, load_events

__all__ = [
    'Candidate',
    'CandidateSource',
    'JsonlCandidateSource',
    'Thresholds',
    'load_events',
    'score_candidate',
]

# Phase 1: Smart wallet discovery — optional imports (graceful degradation).
# Each module is imported independently so that missing modules do not block
# exports of the ones that are present.
try:
    from .wallet_schema import Wallet, WalletScore, WalletTrade
    __all__.extend(['Wallet', 'WalletScore', 'WalletTrade'])
except ImportError:
    pass

try:
    from .wallet_scorer import score_wallet
    __all__.extend(['score_wallet'])
except ImportError:
    pass

try:
    from .wallet_filter import filter_wallet
    __all__.extend(['filter_wallet'])
except ImportError:
    pass

try:
    from .backtest_engine import BacktestEngine
    __all__.extend(['BacktestEngine'])
except ImportError:
    pass

try:
    from .backtest_strategies import (
        FixedBuyStrategy,
        SmartMoneyCopyStrategy,
        SignalFollowStrategy,
        TrailingStopStrategy,
        StrategyFactory,
        StrategyType,
    )
    __all__.extend([
        'FixedBuyStrategy',
        'SmartMoneyCopyStrategy',
        'SignalFollowStrategy',
        'TrailingStopStrategy',
        'StrategyFactory',
        'StrategyType',
    ])
except ImportError:
    pass

try:
    from .signal_engine import SignalEngine
    __all__.extend(['SignalEngine'])
except ImportError:
    pass

try:
    from .gmgn_api_client import GmgnApiClient, GmgnApiError
    __all__.extend(['GmgnApiClient', 'GmgnApiError'])
except ImportError:
    pass

try:
    from .gmgn_data_mapper import (
        map_smartmoney_list_to_wallet_addresses,
        map_token_top_traders_to_wallet_addresses,
        map_wallet_stats_to_features,
    )
    __all__.extend([
        'map_smartmoney_list_to_wallet_addresses',
        'map_token_top_traders_to_wallet_addresses',
        'map_wallet_stats_to_features',
    ])
except ImportError:
    pass

try:
    from .real_wallet_fetcher import RealWalletFetcher
    __all__.extend(['RealWalletFetcher'])
except ImportError:
    pass

try:
    from .helius_client import HeliusClient, HeliusApiError
    __all__.extend(['HeliusClient', 'HeliusApiError'])
except ImportError:
    pass

try:
    from .birdeye_client import BirdeyeClient, BirdeyeApiError
    __all__.extend(['BirdeyeClient', 'BirdeyeApiError'])
except ImportError:
    pass

try:
    from .solscan_client import SolscanClient, SolscanApiError
    __all__.extend(['SolscanClient', 'SolscanApiError'])
except ImportError:
    pass

try:
    from .multi_source_fetcher import MultiSourceFetcher, SourceUnavailableError
    __all__.extend(['MultiSourceFetcher', 'SourceUnavailableError'])
except ImportError:
    pass

try:
    from .source_priority import FIELD_SOURCE_PRIORITY, merge_wallet_data
    __all__.extend(['FIELD_SOURCE_PRIORITY', 'merge_wallet_data'])
except ImportError:
    pass

try:
    from .enhanced_data_pipeline import EnhancedDataPipeline, DataSourceHealth
    __all__.extend(['EnhancedDataPipeline', 'DataSourceHealth'])
except ImportError:
    pass

try:
    from .sell_executor import SellExecutor, SellSignal, SellExecution, SellExecutionResult
    __all__.extend(['SellExecutor', 'SellSignal', 'SellExecution', 'SellExecutionResult'])
except ImportError:
    pass

try:
    from .sell_trigger import SellTrigger, TriggeredTPState
    __all__.extend(['SellTrigger', 'TriggeredTPState'])
except ImportError:
    pass

try:
    from .position_monitor import PositionMonitor, PriceSource
    __all__.extend(['PositionMonitor', 'PriceSource'])
except ImportError:
    pass

try:
    from .copy_sell_handler import CopySellHandler
    __all__.extend(['CopySellHandler'])
except ImportError:
    pass
