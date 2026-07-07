from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .gmgn_api_client import GmgnApiClient
from .gmgn_data_mapper import map_wallet_stats_to_features
from .realistic_mock import RealisticMockGenerator


__all__ = ["RealWalletFetcher"]


# Maximum number of wallets per stats API call.
_WALLET_STATS_BATCH_SIZE = 100


class RealWalletFetcher:
    """Fetch real wallet data from the GMGN OpenAPI.

    When no API key is provided and ``mock_fallback`` is enabled, the fetcher
    transparently returns synthetic mock data.  When ``use_realistic_mock`` is
    ``True``, the fallback uses :class:`~gmgn_monitor.realistic_mock.RealisticMockGenerator`
    instead of the legacy static mock generator.
    """

    def __init__(
        self,
        api_key: str | None = None,
        chain: str = "sol",
        mock_fallback: bool = True,
        use_realistic_mock: bool = False,
    ) -> None:
        self._api_key = api_key or os.environ.get("GMGN_API_KEY")
        self._chain = chain
        self._mock_fallback = mock_fallback
        self._use_realistic_mock = use_realistic_mock
        self._client: GmgnApiClient | None = None
        self._mock_generator: RealisticMockGenerator | None = None

        if self._api_key:
            self._client = GmgnApiClient(api_key=self._api_key)
        elif self._mock_fallback and self._use_realistic_mock:
            self._mock_generator = RealisticMockGenerator()

    def _is_mock(self) -> bool:
        """Return ``True`` when the fetcher is operating in mock fallback mode."""
        return self._client is None and self._mock_fallback

    def _is_realistic_mock(self) -> bool:
        """Return ``True`` when using the realistic mock generator."""
        return self._is_mock() and self._use_realistic_mock and self._mock_generator is not None

    # ------------------------------------------------------------------
    # Fetch methods
    # ------------------------------------------------------------------

    def fetch_smartmoney_wallets(self, limit: int = 200) -> list[dict[str, Any]]:
        """Fetch Smart Money wallet addresses from GMGN.

        Returns a list of wallet dicts (each containing at least
        ``wallet_address``).  In mock fallback mode the returned list is
        synthetic.
        """
        if self._client is None:
            if not self._mock_fallback:
                raise RuntimeError("No API key configured and mock_fallback is disabled")
            return self._mock_wallet_list(count=limit)

        data = self._client.get_smartmoney(chain=self._chain, limit=limit)
        return self._extract_wallet_list(data)

    def fetch_wallet_stats(
        self,
        wallet_addresses: list[str],
        period: str = "7d",
    ) -> dict[str, Any]:
        """Fetch trading stats for multiple wallets.

        Returns the raw GMGN API ``data`` payload (typically a mapping of
        ``wallet_address -> stats``).
        """
        if self._client is None:
            if not self._mock_fallback:
                raise RuntimeError("No API key configured and mock_fallback is disabled")
            return self._mock_wallet_stats(addresses=wallet_addresses)

        data = self._client.get_wallet_stats(
            chain=self._chain,
            wallet_addresses=wallet_addresses,
            period=period,
        )
        return self._unwrap_data(data)

    def fetch_wallet_activity(
        self,
        wallet_address: str,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Fetch recent activity for a single wallet."""
        if self._client is None:
            if not self._mock_fallback:
                raise RuntimeError("No API key configured and mock_fallback is disabled")
            return self._mock_wallet_activity(wallet_address, limit=limit)

        data = self._client.get_wallet_activity(
            chain=self._chain,
            wallet_address=wallet_address,
            limit=limit,
        )
        return self._unwrap_data(data)

    def fetch_trending_tokens(self, interval: str = "24h", limit: int = 20) -> list[dict[str, Any]]:
        """Fetch trending token records used as secondary leader-discovery seeds."""
        if self._client is None:
            if not self._mock_fallback:
                raise RuntimeError("No API key configured and mock_fallback is disabled")
            return []

        data = self._client.get_trending_swaps(
            chain=self._chain,
            interval=interval,
            limit=limit,
        )
        data = self._unwrap_data(data)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("list", "tokens", "rank"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    def fetch_token_top_traders(
        self,
        token_address: str,
        limit: int = 50,
        tag: str | None = None,
        order_by: str | None = None,
        direction: str | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch top traders for a token as secondary leader candidates."""
        if self._client is None:
            if not self._mock_fallback:
                raise RuntimeError("No API key configured and mock_fallback is disabled")
            return []

        extra: dict[str, Any] = {'limit': limit}
        if tag:
            extra['tag'] = tag
        if order_by:
            extra['order_by'] = order_by
        if direction:
            extra['direction'] = direction
        data = self._client.get_token_top_traders(
            chain=self._chain,
            token_address=token_address,
            **extra,
        )
        data = self._unwrap_data(data)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            for key in ("list", "traders", "wallets"):
                value = data.get(key)
                if isinstance(value, list):
                    return [item for item in value if isinstance(item, dict)]
        return []

    def fetch_smartmoney_trades(self, limit: int = 200, side: str = "buy") -> list[dict[str, Any]]:
        """Fetch real-time Smart Money trades used as leader-discovery candidates."""
        if self._client is None:
            if not self._mock_fallback:
                raise RuntimeError("No API key configured and mock_fallback is disabled")
            return []

        data = self._client.get_smartmoney(chain=self._chain, limit=limit, side=side)
        return self._filter_trades_by_side(self._extract_trade_list(self._unwrap_data(data)), side)

    def fetch_kol_trades(self, limit: int = 100, side: str = "buy") -> list[dict[str, Any]]:
        """Fetch real-time KOL trades used as leader-discovery candidates."""
        if self._client is None:
            if not self._mock_fallback:
                raise RuntimeError("No API key configured and mock_fallback is disabled")
            return []

        data = self._client.get_kol(chain=self._chain, limit=limit, side=side)
        return self._filter_trades_by_side(self._extract_trade_list(self._unwrap_data(data)), side)

    def fetch_market_signal_wallets(self, signal_type: int = 12, limit: int = 50) -> list[dict[str, Any]]:
        """Fetch wallets from GMGN token signals, focused on Smart Degen buys."""
        if self._client is None:
            if not self._mock_fallback:
                raise RuntimeError("No API key configured and mock_fallback is disabled")
            return []

        data = self._client.get_token_signals(
            chain=self._chain,
            groups=[{"signal_type": [int(signal_type)]}],
        )
        return self._extract_market_signal_wallets(self._unwrap_data(data), limit=limit)

    # ------------------------------------------------------------------
    # Scoring helpers
    # ------------------------------------------------------------------

    def build_scored_features(
        self,
        wallet_stats: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Build nested features dicts for all wallets contained in *wallet_stats*.

        *wallet_stats* is expected to be a mapping of
        ``wallet_address -> flat_stats_dict`` (the shape returned by the
        GMGN ``wallet_stats`` endpoint).
        """
        if not isinstance(wallet_stats, dict):
            return []

        # Unwrap GMGN response wrapper if present
        wallet_stats = self._unwrap_data(wallet_stats)
        if not isinstance(wallet_stats, dict):
            return []

        features_list: list[dict[str, Any]] = []
        for address, stats in wallet_stats.items():
            if not isinstance(stats, dict):
                continue
            # Ensure the wallet address is present in the stats dict
            if "wallet_address" not in stats:
                stats = {**stats, "wallet_address": address}
            features = map_wallet_stats_to_features(stats)
            if features:
                features_list.append(features)
        return features_list

    def run_fetch(
        self,
        batch_size: int = 200,
        output_path: str | None = None,
    ) -> list[dict[str, Any]]:
        """End-to-end fetch pipeline: Smart Money → Stats → Features.

        Args:
            batch_size: Number of wallets to fetch (passed to smartmoney).
            output_path: If provided, write the resulting feature list as
                JSONL to this path.

        Returns:
            A list of nested feature dicts, one per wallet.
        """
        # 1. Discover wallet addresses
        smartmoney_wallets = self.fetch_smartmoney_wallets(limit=batch_size)
        addresses = [
            str(w.get("wallet_address", ""))
            for w in smartmoney_wallets
            if isinstance(w, dict) and w.get("wallet_address")
        ]
        if not addresses:
            addresses = [f"MockWallet{i:04d}111111111111111111111111111111111111" for i in range(batch_size)]

        # 2. Fetch wallet stats in batches
        all_stats: dict[str, Any] = {}
        for i in range(0, len(addresses), _WALLET_STATS_BATCH_SIZE):
            batch = addresses[i : i + _WALLET_STATS_BATCH_SIZE]
            batch_stats = self.fetch_wallet_stats(batch)
            if isinstance(batch_stats, dict):
                all_stats.update(batch_stats)

        # 3. Map to features
        features = self.build_scored_features(all_stats)

        # 4. Optionally write JSONL
        if output_path is not None:
            path = Path(output_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("w", encoding="utf-8") as fh:
                for feat in features:
                    fh.write(json.dumps(feat, ensure_ascii=False) + "\n")

        return features

    # ------------------------------------------------------------------
    # Static helpers for unwrapping GMGN response envelopes
    # ------------------------------------------------------------------

    @staticmethod
    def _unwrap_data(data: Any) -> Any:
        """Unwrap a GMGN response envelope ``{code, data, message}`` if present."""
        if isinstance(data, dict) and "code" in data and "data" in data:
            return data["data"]
        return data

    @staticmethod
    def _extract_wallet_list(data: Any) -> list[dict[str, Any]]:
        """Extract a list of wallet dicts from various GMGN response shapes."""
        if isinstance(data, list):
            return [w for w in data if isinstance(w, dict)]
        if not isinstance(data, dict):
            return []
        # Direct list under "data"
        if isinstance(data.get("data"), list):
            return [w for w in data["data"] if isinstance(w, dict)]
        # Nested dict under "data" with "list" or "wallets"
        nested = data.get("data")
        if isinstance(nested, dict):
            if isinstance(nested.get("list"), list):
                return [w for w in nested["list"] if isinstance(w, dict)]
            if isinstance(nested.get("wallets"), list):
                return [w for w in nested["wallets"] if isinstance(w, dict)]
        return []

    @staticmethod
    def _extract_trade_list(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
        if isinstance(data, dict):
            value = data.get("list")
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    @staticmethod
    def _filter_trades_by_side(trades: list[dict[str, Any]], side: str) -> list[dict[str, Any]]:
        side = str(side or "").lower()
        if not side:
            return trades
        return [trade for trade in trades if str(trade.get("side") or "").lower() == side]

    @staticmethod
    def _extract_market_signal_wallets(data: Any, limit: int = 50) -> list[dict[str, Any]]:
        if isinstance(data, dict):
            for key in ("list", "signals", "data"):
                value = data.get(key)
                if isinstance(value, list):
                    data = value
                    break
        if not isinstance(data, list):
            return []

        records: list[dict[str, Any]] = []
        for signal in data:
            if not isinstance(signal, dict):
                continue
            snapshot = signal.get("data")
            if not isinstance(snapshot, dict):
                snapshot = {}
            wallets = snapshot.get("smart_degen_wallets")
            if not isinstance(wallets, list):
                continue
            token_address = str(signal.get("token_address") or snapshot.get("address") or "").strip()
            for wallet in wallets:
                if len(records) >= limit:
                    return records
                if not isinstance(wallet, dict):
                    continue
                address = str(wallet.get("address") or wallet.get("wallet_address") or "").strip()
                if not address:
                    continue
                records.append({
                    "wallet_address": address,
                    "token_address": token_address,
                    "token_symbol": snapshot.get("symbol"),
                    "signal_type": signal.get("signal_type"),
                    "trigger_at": signal.get("trigger_at"),
                    "trigger_mc": signal.get("trigger_mc"),
                    "market_cap": signal.get("market_cap"),
                    "signal_times": signal.get("signal_times"),
                    "signal_count": snapshot.get("count") or snapshot.get("smart_degen_count"),
                    "total_amount": snapshot.get("total_amount"),
                    "buy_timestamp": wallet.get("buy_timestamp"),
                    "buy_amount": wallet.get("buy_amount"),
                    "tags": ["smart_degen", f"market_signal_{signal.get('signal_type') or 'unknown'}"],
                })
        return records

    # ------------------------------------------------------------------
    # Mock helpers
    # ------------------------------------------------------------------

    def _mock_wallet_list(self, count: int) -> list[dict[str, Any]]:
        return [
            {
                "wallet_address": f"MockWallet{i:04d}111111111111111111111111111111111111",
                "chain": self._chain,
                "rank": i + 1,
            }
            for i in range(count)
        ]

    def _mock_wallet_stats(self, addresses: list[str]) -> dict[str, Any]:
        return {
            addr: self._mock_single_stats(addr, i)
            for i, addr in enumerate(addresses)
        }

    def _mock_single_stats(self, wallet_address: str, index: int) -> dict[str, Any]:
        """Generate a single mock stats record compatible with the mapper."""
        if self._is_realistic_mock() and self._mock_generator is not None:
            return self._mock_generator.generate_wallet_stats(
                wallet_address=wallet_address, chain=self._chain
            )
        return {
            "wallet_address": wallet_address,
            "chain": self._chain,
            "total_profit": 52000.0 + index * 1000,
            "realized_profit": 45000.0 + index * 800,
            "unrealized_profit": 7000.0 + index * 200,
            "win_rate": 68.5,
            "total_trades": 280 + index,
            "trades_7d": 72,
            "trades_30d": 280,
            "avg_holding_time": 36.5,
            "pnl_7d": 0.05,
            "pnl_30d": 0.18,
            "max_drawdown": 42.0,
            "portfolio_value": 15000.0 + index * 500,
            "balance_usd": 2500.0,
            "first_seen_at": "2025-01-15T08:30:00Z",
            "last_active_at": "2025-07-03T12:00:00Z",
        }

    def _mock_wallet_activity(self, wallet_address: str, limit: int) -> dict[str, Any]:
        return {
            "wallet_address": wallet_address,
            "activities": [
                {
                    "tx_hash": f"mock_tx_{wallet_address}_{i:04d}",
                    "token_address": f"MockToken{i:04d}1111111111111111111111111111111111111",
                    "token_symbol": f"MOCK{i}",
                    "direction": "buy" if i % 2 == 0 else "sell",
                    "amount_usd": 500.0 + i * 10,
                    "timestamp": "2025-07-01T14:23:00Z",
                }
                for i in range(limit)
            ],
        }
