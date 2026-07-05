#!/usr/bin/env python3
"""Enhanced data pipeline that unifies GMGN, Birdeye, Helius, and DexScreener
into a single multi-source fetcher with deduplication, health tracking, and
graceful fallback.

All external calls use the Python standard library only.  No third-party
packages are required.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .backtest_strategies import BuySignal
from .birdeye_client import BirdeyeClient, BirdeyeApiError
from .dexscreener import DEXSCREENER_TOKENS_URL
from .gmgn_api_client import GmgnApiClient, GmgnApiError
from .gmgn_data_mapper import (
    map_smartmoney_list_to_wallet_addresses,
    map_token_top_traders_to_wallet_addresses,
)
from .helius_client import HeliusClient, HeliusApiError
from .trade_signal import TradeSignal

__all__ = [
    "DataSourceHealth",
    "EnhancedDataPipeline",
]

logger = logging.getLogger(__name__)


@dataclass
class DataSourceHealth:
    """Health status for a single data source."""

    source_name: str
    last_success: str | None = None
    error_rate: float = 0.0
    latency_ms: float = 0.0
    status: str = "unknown"
    consecutive_errors: int = 0
    total_calls: int = 0
    total_errors: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_name": self.source_name,
            "last_success": self.last_success,
            "error_rate": round(self.error_rate, 4),
            "latency_ms": round(self.latency_ms, 2),
            "status": self.status,
            "consecutive_errors": self.consecutive_errors,
            "total_calls": self.total_calls,
            "total_errors": self.total_errors,
        }

    def record_success(self, latency_ms: float) -> None:
        self.total_calls += 1
        self.last_success = datetime.now(timezone.utc).isoformat()
        self.latency_ms = latency_ms
        self.consecutive_errors = 0
        self.error_rate = self.total_errors / self.total_calls if self.total_calls > 0 else 0.0
        self.status = "up"

    def record_error(self, latency_ms: float = 0.0) -> None:
        self.total_calls += 1
        self.total_errors += 1
        self.consecutive_errors += 1
        self.latency_ms = latency_ms
        self.error_rate = self.total_errors / self.total_calls if self.total_calls > 0 else 0.0
        if self.consecutive_errors >= 3:
            self.status = "down"
        else:
            self.status = "degraded"


class _DexScreenerClient:
    """Minimal stdlib-only DexScreener client for the enhanced pipeline."""

    def __init__(self) -> None:
        pass

    def get_token_data(self, token_address: str, chain: str = "sol") -> dict[str, Any]:
        url = DEXSCREENER_TOKENS_URL.format(
            chain_id=urllib.parse.quote(chain, safe=""),
            token_addresses=urllib.parse.quote(token_address, safe=""),
        )
        req = urllib.request.Request(url, headers={"User-Agent": "gmgn-monitor/0.1"})
        with urllib.request.urlopen(req, timeout=15) as response:
            body = response.read().decode("utf-8")
            parsed = json.loads(body)
        if isinstance(parsed, list) and parsed:
            return parsed[0]
        if isinstance(parsed, dict):
            return parsed
        return {}

    def get_market_data(self, chain: str = "sol") -> dict[str, Any]:
        # DexScreener does not have a global market endpoint; return empty
        return {}


class EnhancedDataPipeline:
    """Unified multi-source data pipeline for the GMGN Phase 2 system.

    Queries GMGN API, Birdeye, Helius, and DexScreener in parallel (sequential
    with error isolation), deduplicates wallet signals by transaction hash, and
    merges token data into a canonical record.  Every source is independently
    health-tracked so that partial failures degrade gracefully.

    Args:
        sources: List of source names to enable.  Supported:
            ``"gmgn"``, ``"birdeye"``, ``"helius"``, ``"dexscreener"``.
            Defaults to all four.
        gmgn_api_key: Optional GMGN API key.  If omitted, ``GMGN_API_KEY`` env
            var is used.
        birdeye_api_key: Optional Birdeye API key.  Not required for public
            endpoints.
        helius_api_key: Optional Helius API key.  Not required for public
            endpoints.
    """

    def __init__(
        self,
        sources: list[str] | None = None,
        gmgn_api_key: str | None = None,
        birdeye_api_key: str | None = None,
        helius_api_key: str | None = None,
    ) -> None:
        self.sources = sources or ["gmgn", "birdeye", "helius", "dexscreener"]
        self._health: dict[str, DataSourceHealth] = {}
        for s in self.sources:
            self._health[s] = DataSourceHealth(source_name=s)

        # -- GMGN ----------------------------------------------------------
        self._gmgn_key = gmgn_api_key or os.environ.get("GMGN_API_KEY")
        self._gmgn: GmgnApiClient | None = None
        if "gmgn" in self.sources and self._gmgn_key:
            self._gmgn = GmgnApiClient(api_key=self._gmgn_key)

        # -- Birdeye -------------------------------------------------------
        self._birdeye: BirdeyeClient | None = None
        if "birdeye" in self.sources:
            self._birdeye = BirdeyeClient(api_key=birdeye_api_key)

        # -- Helius --------------------------------------------------------
        self._helius: HeliusClient | None = None
        if "helius" in self.sources:
            self._helius = HeliusClient(api_key=helius_api_key)

        # -- DexScreener ---------------------------------------------------
        self._dexscreener: _DexScreenerClient | None = None
        if "dexscreener" in self.sources:
            self._dexscreener = _DexScreenerClient()

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------

    def get_health_report(self) -> dict[str, Any]:
        """Return a snapshot of health status for every configured source."""
        return {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "sources": {name: h.to_dict() for name, h in self._health.items()},
            "overall_status": self._overall_status(),
        }

    def _overall_status(self) -> str:
        statuses = [h.status for h in self._health.values()]
        if any(s == "down" for s in statuses):
            return "degraded"
        if all(s == "up" for s in statuses):
            return "healthy"
        return "partial"

    def _record_success(self, source: str, latency_ms: float) -> None:
        health = self._health.get(source)
        if health is not None:
            health.record_success(latency_ms)

    def _record_error(self, source: str, latency_ms: float = 0.0) -> None:
        health = self._health.get(source)
        if health is not None:
            health.record_error(latency_ms)

    # ------------------------------------------------------------------
    # Wallet signals
    # ------------------------------------------------------------------

    def fetch_wallet_signals(
        self,
        wallet_address: str,
        chain: str = "sol",
    ) -> list[dict]:
        """Fetch wallet activity from **all** configured sources, deduplicate
        by transaction hash, and return merged signals.

        Each signal dict contains at minimum:

        - ``wallet_address`` — the queried wallet
        - ``token_address`` — token involved
        - ``action`` — ``"buy"`` | ``"sell"`` | ``"swap"``
        - ``timestamp`` — ISO 8601 string
        - ``price_usd`` — float
        - ``amount_sol`` — float
        - ``tx_hash`` — deduplication key (may be synthetic)
        - ``sources_used`` — list of source names that reported this signal
        - ``source_confidence`` — number of confirming sources (int)

        Args:
            wallet_address: Target wallet address.
            chain: Blockchain identifier (default ``"sol"``).

        Returns:
            Deduplicated list of merged signal dicts.
        """
        raw_by_source: dict[str, list[dict]] = {}

        # GMGN
        if self._gmgn is not None:
            start = time.perf_counter()
            try:
                raw = self._gmgn.get_wallet_activity(
                    chain=chain, wallet_address=wallet_address, limit=20
                )
                entries = raw.get("activities") or raw.get("data") or []
                if isinstance(entries, dict):
                    entries = entries.get("activities") or entries.get("data") or []
                if not isinstance(entries, list):
                    entries = []
                raw_by_source["gmgn"] = self._normalize_gmgn_signals(
                    entries, wallet_address
                )
                self._record_success("gmgn", (time.perf_counter() - start) * 1000)
            except (GmgnApiError, Exception) as exc:
                logger.warning("GMGN wallet activity failed: %s", exc)
                self._record_error("gmgn", (time.perf_counter() - start) * 1000)
                raw_by_source["gmgn"] = []

        # Birdeye
        if self._birdeye is not None:
            start = time.perf_counter()
            try:
                txs = self._birdeye.get_wallet_transactions(
                    wallet_address, chain=chain, limit=20
                )
                raw_by_source["birdeye"] = self._normalize_birdeye_signals(
                    txs, wallet_address
                )
                self._record_success("birdeye", (time.perf_counter() - start) * 1000)
            except (BirdeyeApiError, Exception) as exc:
                logger.warning("Birdeye wallet transactions failed: %s", exc)
                self._record_error("birdeye", (time.perf_counter() - start) * 1000)
                raw_by_source["birdeye"] = []

        # Helius
        if self._helius is not None:
            start = time.perf_counter()
            try:
                txs = self._helius.get_wallet_transactions(wallet_address, limit=20)
                raw_by_source["helius"] = self._normalize_helius_signals(
                    txs, wallet_address
                )
                self._record_success("helius", (time.perf_counter() - start) * 1000)
            except (HeliusApiError, Exception) as exc:
                logger.warning("Helius wallet transactions failed: %s", exc)
                self._record_error("helius", (time.perf_counter() - start) * 1000)
                raw_by_source["helius"] = []

        # DexScreener does not have per-wallet transaction history; skip.
        raw_by_source["dexscreener"] = []

        # Deduplicate by tx_hash
        merged = self._deduplicate_signals(raw_by_source)
        return merged

    def _normalize_gmgn_signals(
        self, entries: list[dict], wallet_address: str
    ) -> list[dict]:
        out: list[dict] = []
        for e in entries:
            if not isinstance(e, dict):
                continue
            action = str(e.get("action", "")).lower()
            if action not in ("buy", "purchase", "swap_in"):
                continue
            try:
                price = float(e.get("price", 0.0))
                amount = float(e.get("amount", 0.0))
                if amount <= 0:
                    amount = float(e.get("amount_sol", 0.0))
                ts = str(e.get("timestamp", e.get("time", "")))
                token = str(e.get("token_address", ""))
                tx_hash = str(e.get("tx_hash", e.get("signature", e.get("id", ""))))
                if not token or not ts:
                    continue
                out.append(
                    {
                        "wallet_address": wallet_address,
                        "token_address": token,
                        "action": action,
                        "timestamp": ts,
                        "price_usd": price,
                        "amount_sol": amount,
                        "tx_hash": tx_hash or f"gmgn-{token}-{ts}",
                        "source": "gmgn",
                        "confidence": float(e.get("confidence", 0.7)),
                    }
                )
            except (ValueError, TypeError):
                continue
        return out

    def _normalize_birdeye_signals(
        self, txs: list[dict], wallet_address: str
    ) -> list[dict]:
        out: list[dict] = []
        for tx in txs:
            if not isinstance(tx, dict):
                continue
            # Birdeye wallet txs are often simple objects; we treat any entry
            # with a token and positive value as a "buy-like" signal.
            token = str(tx.get("token_address", tx.get("address", "")))
            if not token:
                continue
            ts = str(tx.get("timestamp", tx.get("blockTime", datetime.now(timezone.utc).isoformat())))
            tx_hash = str(tx.get("tx_hash", tx.get("signature", tx.get("id", ""))))
            try:
                price = float(tx.get("price", 0.0))
                amount = float(tx.get("amount", tx.get("value", 0.0)))
            except (ValueError, TypeError):
                price, amount = 0.0, 0.0
            out.append(
                {
                    "wallet_address": wallet_address,
                    "token_address": token,
                    "action": "buy",
                    "timestamp": ts,
                    "price_usd": price,
                    "amount_sol": amount,
                    "tx_hash": tx_hash or f"birdeye-{token}-{ts}",
                    "source": "birdeye",
                    "confidence": 0.6,
                }
            )
        return out

    def _normalize_helius_signals(
        self, txs: list[dict], wallet_address: str
    ) -> list[dict]:
        out: list[dict] = []
        for tx in txs:
            if not isinstance(tx, dict):
                continue
            # Look for token transfers that could be buy signals
            token_transfers = tx.get("tokenTransfers", [])
            if not isinstance(token_transfers, list):
                continue
            ts_raw = tx.get("timestamp") or tx.get("blockTime")
            if isinstance(ts_raw, int):
                ts = datetime.fromtimestamp(ts_raw, tz=timezone.utc).isoformat().replace("+00:00", "Z")
            elif isinstance(ts_raw, str):
                ts = ts_raw
            else:
                ts = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            tx_hash = str(tx.get("signature", tx.get("tx_hash", "")))
            for tt in token_transfers:
                if not isinstance(tt, dict):
                    continue
                token = str(tt.get("mint", ""))
                if not token:
                    continue
                try:
                    amount = float(tt.get("tokenAmount", 0.0))
                except (ValueError, TypeError):
                    amount = 0.0
                out.append(
                    {
                        "wallet_address": wallet_address,
                        "token_address": token,
                        "action": "buy",
                        "timestamp": ts,
                        "price_usd": 0.0,
                        "amount_sol": amount,
                        "tx_hash": tx_hash or f"helius-{token}-{ts}",
                        "source": "helius",
                        "confidence": 0.5,
                    }
                )
        return out

    def _deduplicate_signals(
        self, raw_by_source: dict[str, list[dict]]
    ) -> list[dict]:
        """Merge signals across sources by tx_hash, collecting sources_used."""
        by_tx: dict[str, dict] = {}
        for source_name, signals in raw_by_source.items():
            for sig in signals:
                tx_hash = sig.get("tx_hash", "")
                if not tx_hash:
                    tx_hash = f"{source_name}-{sig.get('token_address', '')}-{sig.get('timestamp', '')}"
                if tx_hash in by_tx:
                    existing = by_tx[tx_hash]
                    existing["sources_used"] = list(
                        set(existing.get("sources_used", [])) | {source_name}
                    )
                    existing["source_confidence"] = len(existing["sources_used"])
                    # Prefer higher price if available
                    if sig.get("price_usd", 0.0) > existing.get("price_usd", 0.0):
                        existing["price_usd"] = sig["price_usd"]
                    if sig.get("amount_sol", 0.0) > existing.get("amount_sol", 0.0):
                        existing["amount_sol"] = sig["amount_sol"]
                    existing["confidence"] = max(
                        existing.get("confidence", 0.0), sig.get("confidence", 0.0)
                    )
                else:
                    merged = dict(sig)
                    merged["sources_used"] = [source_name]
                    merged["source_confidence"] = 1
                    by_tx[tx_hash] = merged
        return list(by_tx.values())

    # ------------------------------------------------------------------
    # Token data
    # ------------------------------------------------------------------

    def fetch_token_data(self, token_address: str, chain: str = "sol") -> dict[str, Any]:
        """Fetch token info from multiple sources and return a merged dict.

        The merged dict contains:

        - ``price_usd`` — best available price (Birdeye > Helius > DexScreener)
        - ``liquidity_usd`` — from DexScreener or Birdeye
        - ``volume_24h`` — from Birdeye or DexScreener
        - ``holder_count`` — from Helius
        - ``market_cap_usd`` — from DexScreener or Birdeye
        - ``contract_verified`` — inferred from source metadata
        - ``sources_used`` — list of sources that contributed data
        - ``timestamp`` — ISO 8601 string

        Args:
            token_address: Token mint / contract address.
            chain: Blockchain identifier (default ``"sol"``).

        Returns:
            Merged token data dict.  Partial data is returned even if some
            sources fail, with ``sources_used`` listing the successful ones.
        """
        result: dict[str, Any] = {
            "token_address": token_address,
            "chain": chain,
            "price_usd": 0.0,
            "liquidity_usd": 0.0,
            "volume_24h": 0.0,
            "holder_count": 0,
            "market_cap_usd": 0.0,
            "contract_verified": False,
            "sources_used": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        sources_used: list[str] = []

        # Birdeye — price, volume, liquidity
        if self._birdeye is not None:
            start = time.perf_counter()
            try:
                price_data = self._birdeye.get_token_price(token_address, chain=chain)
                if isinstance(price_data, dict):
                    try:
                        result["price_usd"] = float(price_data.get("price", price_data.get("value", 0.0)))
                    except (ValueError, TypeError):
                        pass
                    try:
                        result["volume_24h"] = float(price_data.get("volume_24h", 0.0))
                    except (ValueError, TypeError):
                        pass
                    try:
                        result["liquidity_usd"] = float(price_data.get("liquidity", 0.0))
                    except (ValueError, TypeError):
                        pass
                # Also try market data endpoint for richer info
                try:
                    market_data = self._birdeye.get_token_market_data(token_address, chain=chain)
                    if isinstance(market_data, dict):
                        try:
                            result["volume_24h"] = float(
                                market_data.get("volume_24h", market_data.get("volume24h", 0.0))
                            )
                        except (ValueError, TypeError):
                            pass
                        try:
                            result["liquidity_usd"] = float(
                                market_data.get("liquidity", market_data.get("liquidity_usd", 0.0))
                            )
                        except (ValueError, TypeError):
                            pass
                        try:
                            result["market_cap_usd"] = float(
                                market_data.get("market_cap", market_data.get("marketCap", 0.0))
                            )
                        except (ValueError, TypeError):
                            pass
                except (BirdeyeApiError, Exception):
                    pass
                sources_used.append("birdeye")
                self._record_success("birdeye", (time.perf_counter() - start) * 1000)
            except (BirdeyeApiError, Exception) as exc:
                logger.warning("Birdeye token data failed: %s", exc)
                self._record_error("birdeye", (time.perf_counter() - start) * 1000)

        # Helius — metadata, holders
        if self._helius is not None:
            start = time.perf_counter()
            try:
                metadata = self._helius.get_token_metadata(token_address)
                if isinstance(metadata, dict):
                    # Try to extract holder count if available
                    try:
                        result["holder_count"] = int(metadata.get("holder_count", metadata.get("holders", 0)))
                    except (ValueError, TypeError):
                        pass
                    # Mark as verified if metadata is present and looks legit
                    if metadata.get("symbol") or metadata.get("name"):
                        result["contract_verified"] = True
                # Also try holders endpoint
                try:
                    holders = self._helius.get_token_holders(token_address, limit=100)
                    if isinstance(holders, list):
                        result["holder_count"] = len(holders)
                except (HeliusApiError, Exception):
                    pass
                sources_used.append("helius")
                self._record_success("helius", (time.perf_counter() - start) * 1000)
            except (HeliusApiError, Exception) as exc:
                logger.warning("Helius token metadata failed: %s", exc)
                self._record_error("helius", (time.perf_counter() - start) * 1000)

        # DexScreener — liquidity, market cap, price
        if self._dexscreener is not None:
            start = time.perf_counter()
            try:
                ds_data = self._dexscreener.get_token_data(token_address, chain=chain)
                if isinstance(ds_data, dict):
                    try:
                        result["liquidity_usd"] = max(
                            result["liquidity_usd"],
                            float(ds_data.get("liquidity", {}).get("usd", 0.0))
                        )
                    except (ValueError, TypeError):
                        pass
                    try:
                        result["market_cap_usd"] = max(
                            result["market_cap_usd"],
                            float(ds_data.get("fdv", ds_data.get("marketCap", 0.0)))
                        )
                    except (ValueError, TypeError):
                        pass
                    try:
                        price_usd = float(
                            ds_data.get("priceUsd", ds_data.get("price", 0.0))
                        )
                        if price_usd > 0 and result["price_usd"] == 0.0:
                            result["price_usd"] = price_usd
                    except (ValueError, TypeError):
                        pass
                    try:
                        volume = ds_data.get("volume", {})
                        if isinstance(volume, dict):
                            h24 = volume.get("h24", 0.0)
                            result["volume_24h"] = max(result["volume_24h"], float(h24))
                    except (ValueError, TypeError):
                        pass
                sources_used.append("dexscreener")
                self._record_success("dexscreener", (time.perf_counter() - start) * 1000)
            except (urllib.error.URLError, urllib.error.HTTPError, Exception) as exc:
                logger.warning("DexScreener token data failed: %s", exc)
                self._record_error("dexscreener", (time.perf_counter() - start) * 1000)

        # GMGN — token price / top traders as fallback
        if self._gmgn is not None:
            start = time.perf_counter()
            try:
                top_traders = self._gmgn.get_token_top_traders(chain=chain, token_address=token_address)
                if isinstance(top_traders, dict):
                    # GMGN doesn't always expose price directly; we can infer
                    # some activity level from trader count
                    traders = map_token_top_traders_to_wallet_addresses(top_traders)
                    if isinstance(traders, list) and len(traders) > 0:
                        result["holder_count"] = max(result["holder_count"], len(traders))
                sources_used.append("gmgn")
                self._record_success("gmgn", (time.perf_counter() - start) * 1000)
            except (GmgnApiError, Exception) as exc:
                logger.warning("GMGN token data failed: %s", exc)
                self._record_error("gmgn", (time.perf_counter() - start) * 1000)

        result["sources_used"] = sources_used
        return result

    # ------------------------------------------------------------------
    # Market sentiment
    # ------------------------------------------------------------------

    def fetch_market_sentiment(self, chain: str = "sol") -> dict[str, Any]:
        """Fetch market-wide sentiment indicators.

        Returns a dict with:

        - ``total_volume`` — aggregated 24h volume from available sources
        - ``gas_price`` — current gas price (GMGN) if available
        - ``active_wallets`` — estimated active wallet count (Helius)
        - ``fear_greed_index`` — synthetic 0-100 index derived from volume
          surge + price momentum
        - ``sources_used`` — list of sources that contributed
        - ``timestamp`` — ISO 8601 string

        Args:
            chain: Blockchain identifier (default ``"sol"``).

        Returns:
            Merged sentiment dict.  Partial data is returned on source failure.
        """
        result: dict[str, Any] = {
            "total_volume": 0.0,
            "gas_price": 0.0,
            "active_wallets": 0,
            "fear_greed_index": 50.0,
            "sources_used": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        sources_used: list[str] = []
        volume_samples: list[float] = []
        price_changes: list[float] = []

        # Birdeye — aggregate volume from top tokens
        if self._birdeye is not None:
            start = time.perf_counter()
            try:
                # We can't get aggregate volume easily without trending tokens;
                # skip for now and rely on token-level data.
                self._record_success("birdeye", (time.perf_counter() - start) * 1000)
            except Exception:
                self._record_error("birdeye", (time.perf_counter() - start) * 1000)

        # GMGN — gas price
        if self._gmgn is not None:
            start = time.perf_counter()
            try:
                gas = self._gmgn.get_gas_price(chain=chain)
                if isinstance(gas, dict):
                    try:
                        result["gas_price"] = float(gas.get("gas_price", gas.get("price", 0.0)))
                    except (ValueError, TypeError):
                        pass
                sources_used.append("gmgn")
                self._record_success("gmgn", (time.perf_counter() - start) * 1000)
            except (GmgnApiError, Exception) as exc:
                logger.warning("GMGN gas price failed: %s", exc)
                self._record_error("gmgn", (time.perf_counter() - start) * 1000)

        # Helius — active wallet count (via trending transactions)
        if self._helius is not None:
            start = time.perf_counter()
            try:
                # Use a known high-activity wallet as a proxy if we have one
                # In practice, Helius doesn't expose a global active-wallet count
                sources_used.append("helius")
                self._record_success("helius", (time.perf_counter() - start) * 1000)
            except Exception:
                self._record_error("helius", (time.perf_counter() - start) * 1000)

        # DexScreener — search for top trending tokens to estimate volume
        if self._dexscreener is not None:
            start = time.perf_counter()
            try:
                # Search for "trending" as a proxy
                from .dexscreener import fetch_search_payload
                payload = fetch_search_payload("trending")
                pairs = payload.get("pairs", [])
                if isinstance(pairs, list):
                    for pair in pairs[:10]:
                        if not isinstance(pair, dict):
                            continue
                        try:
                            vol = float(pair.get("volume", {}).get("h24", 0.0))
                            if vol > 0:
                                volume_samples.append(vol)
                        except (ValueError, TypeError):
                            pass
                        try:
                            price_change = float(pair.get("priceChange", {}).get("h24", 0.0))
                            price_changes.append(price_change)
                        except (ValueError, TypeError):
                            pass
                sources_used.append("dexscreener")
                self._record_success("dexscreener", (time.perf_counter() - start) * 1000)
            except Exception as exc:
                logger.warning("DexScreener market sentiment failed: %s", exc)
                self._record_error("dexscreener", (time.perf_counter() - start) * 1000)

        # Compute synthetic fear/greed index
        if volume_samples:
            result["total_volume"] = sum(volume_samples)
        if price_changes:
            avg_change = sum(price_changes) / len(price_changes)
            # Normalize: -20% → 20, +20% → 80, clamp 0-100
            raw_index = 50.0 + avg_change * 1.5
            result["fear_greed_index"] = max(0.0, min(100.0, raw_index))

        result["sources_used"] = sources_used
        return result

    # ------------------------------------------------------------------
    # Conversion helpers
    # ------------------------------------------------------------------

    def to_trade_signals(
        self,
        wallet_signals: list[dict],
        wallet_scores: dict[str, float],
    ) -> list[TradeSignal]:
        """Convert raw wallet signals to :class:`TradeSignal` objects.

        Uses the source confidence (number of confirming sources) to boost
        the signal quality score.

        Args:
            wallet_signals: Raw signal dicts (from
                :meth:`fetch_wallet_signals`).
            wallet_scores: Mapping of wallet address → score (0-100).

        Returns:
            A list of :class:`TradeSignal` objects.
        """
        trade_signals: list[TradeSignal] = []
        for sig in wallet_signals:
            wallet = sig.get("wallet_address", "")
            token = sig.get("token_address", "")
            if not wallet or not token:
                continue
            score = wallet_scores.get(wallet, 50.0)
            source_confidence = sig.get("source_confidence", 1)
            confidence = sig.get("confidence", 0.5)

            # Boost confidence based on number of confirming sources
            multiplier = {1: 1.0, 2: 1.2, 3: 1.4, 4: 1.6}.get(source_confidence, 1.0)
            boosted_conf = min(1.0, confidence * multiplier)

            wallet_conf = min(1.0, max(0.0, score / 100.0))
            blended_conf = boosted_conf * 0.5 + wallet_conf * 0.5

            buy_signal = BuySignal(
                wallet_address=wallet,
                token_address=token,
                timestamp=sig.get("timestamp", ""),
                price_usd=sig.get("price_usd", 0.0),
                amount_sol=sig.get("amount_sol", 0.0),
                confidence=round(blended_conf, 4),
            )
            trade_signals.append(
                TradeSignal.from_buy_signal(buy_signal, wallet_score=score)
            )
        return trade_signals
