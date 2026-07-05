from __future__ import annotations

from dataclasses import dataclass
from math import isfinite
from typing import Any

from .time_utils import is_iso_timestamp


# ---------------------------------------------------------------------------
# Wallet (raw record from GMGN data fetch)
# ---------------------------------------------------------------------------

WALLET_REQUIRED_FIELDS = (
    "wallet_address",
    "chain",
    "first_seen_at",
    "last_active_at",
    "source",
    "fetched_at",
)

WALLET_STRING_FIELDS = (
    "wallet_address",
    "chain",
    "first_seen_at",
    "last_active_at",
    "source",
    "fetched_at",
)

WALLET_NUMERIC_FIELDS = (
    "total_trades_7d",
    "total_trades_30d",
    "winning_trades_30d",
    "win_rate_30d",
    "avg_investment_usd",
    "avg_profit_usd",
    "total_profit_usd",
    "avg_holding_duration_hours",
    "stablecoin_balance_usd",
    "portfolio_balance_usd",
)

WALLET_COUNT_FIELDS = (
    "total_trades_7d",
    "total_trades_30d",
    "winning_trades_30d",
)

WALLET_PERCENT_FIELDS = ("win_rate_30d",)

VALID_CHAINS = {"solana", "base", "bsc"}


@dataclass(frozen=True)
class Wallet:
    """Raw wallet record from GMGN data fetch.

    Stores all fields in a flat *data* dict so downstream code can access
    arbitrary fields without schema changes.  Validation is performed on
    construction via :meth:`from_dict`.
    """

    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Wallet:
        errors = _validate_wallet_data(data)
        if errors:
            raise ValueError("; ".join(errors))
        return cls(data)

    def get(self, field: str) -> Any:
        return self.data[field]


def _validate_wallet_data(data: dict[str, Any]) -> list[str]:
    """Return a list of validation errors for a raw wallet dict."""
    errors: list[str] = []

    for field in WALLET_REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"missing field: {field}")

    for field in WALLET_STRING_FIELDS:
        if field in data and not isinstance(data[field], str):
            errors.append(f"{field} must be string")
        elif field in data and not data[field].strip():
            errors.append(f"{field} must be non-empty")

    for field in ("first_seen_at", "last_active_at", "fetched_at"):
        if isinstance(data.get(field), str) and data[field].strip() and not is_iso_timestamp(data[field]):
            errors.append(f"{field} must be ISO timestamp")

    if "chain" in data and data["chain"] not in VALID_CHAINS:
        errors.append(f"chain must be one of {sorted(VALID_CHAINS)}")

    for field in WALLET_NUMERIC_FIELDS:
        if field in data and (isinstance(data[field], bool) or not isinstance(data[field], (int, float))):
            errors.append(f"{field} must be numeric")
        elif field in data and not isfinite(data[field]):
            errors.append(f"{field} must be finite")
        elif field in data and data[field] < 0:
            errors.append(f"{field} must be non-negative")

    for field in WALLET_PERCENT_FIELDS:
        if field in data and isinstance(data[field], (int, float)) and not isinstance(data[field], bool) and data[field] > 100:
            errors.append(f"{field} must be at most 100")

    for field in WALLET_COUNT_FIELDS:
        if field in data and isinstance(data[field], (int, float)) and not isinstance(data[field], bool) and isfinite(data[field]) and not float(data[field]).is_integer():
            errors.append(f"{field} must be an integer")

    # Cross-field checks
    if "winning_trades_30d" in data and "total_trades_30d" in data:
        if data["winning_trades_30d"] > data["total_trades_30d"]:
            errors.append("winning_trades_30d must not exceed total_trades_30d")

    if "last_active_at" in data and "first_seen_at" in data:
        if isinstance(data["last_active_at"], str) and isinstance(data["first_seen_at"], str):
            if data["last_active_at"] < data["first_seen_at"]:
                errors.append("last_active_at must be >= first_seen_at")

    return errors


# ---------------------------------------------------------------------------
# WalletTrade (individual trade record)
# ---------------------------------------------------------------------------

TRADE_REQUIRED_FIELDS = (
    "tx_hash",
    "wallet_address",
    "chain",
    "timestamp",
    "token_address",
    "token_symbol",
    "direction",
    "amount_token",
    "amount_sol",
    "price_usd",
    "dex",
    "program_id",
)

TRADE_STRING_FIELDS = (
    "tx_hash",
    "wallet_address",
    "chain",
    "timestamp",
    "token_address",
    "token_symbol",
    "direction",
    "dex",
    "program_id",
)

TRADE_NUMERIC_FIELDS = (
    "amount_token",
    "amount_sol",
    "price_usd",
    "slippage_percent",
    "fee_sol",
    "priority_fee_sol",
)

VALID_DIRECTIONS = {"buy", "sell"}
VALID_MEV_MODES = {"off", "reduced", "secure"}


@dataclass(frozen=True)
class WalletTrade:
    """Individual trade record for a wallet.

    Stores all fields in a flat *data* dict.  Validation is performed on
    construction via :meth:`from_dict`.
    """

    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WalletTrade:
        errors = _validate_trade_data(data)
        if errors:
            raise ValueError("; ".join(errors))
        return cls(data)

    def get(self, field: str) -> Any:
        return self.data[field]


def _validate_trade_data(data: dict[str, Any]) -> list[str]:
    """Return a list of validation errors for a trade dict."""
    errors: list[str] = []

    for field in TRADE_REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"missing field: {field}")

    for field in TRADE_STRING_FIELDS:
        if field in data and not isinstance(data[field], str):
            errors.append(f"{field} must be string")
        elif field in data and not data[field].strip():
            errors.append(f"{field} must be non-empty")

    if isinstance(data.get("timestamp"), str) and data["timestamp"].strip() and not is_iso_timestamp(data["timestamp"]):
        errors.append("timestamp must be ISO timestamp")

    for field in TRADE_NUMERIC_FIELDS:
        if field in data and (isinstance(data[field], bool) or not isinstance(data[field], (int, float))):
            errors.append(f"{field} must be numeric")
        elif field in data and not isfinite(data[field]):
            errors.append(f"{field} must be finite")
        elif field in data and data[field] < 0:
            errors.append(f"{field} must be non-negative")

    if "direction" in data and data["direction"] not in VALID_DIRECTIONS:
        errors.append(f"direction must be one of {sorted(VALID_DIRECTIONS)}")

    if "slippage_percent" in data and isinstance(data["slippage_percent"], (int, float)) and not isinstance(data["slippage_percent"], bool) and data["slippage_percent"] > 100:
        errors.append("slippage_percent must be at most 100")

    if "is_mev_protected" in data and not isinstance(data["is_mev_protected"], bool):
        errors.append("is_mev_protected must be boolean")

    if "mev_protection_mode" in data and data["mev_protection_mode"] not in VALID_MEV_MODES:
        errors.append(f"mev_protection_mode must be one of {sorted(VALID_MEV_MODES)}")

    return errors


# ---------------------------------------------------------------------------
# WalletScore (scoring engine output)
# ---------------------------------------------------------------------------

SCORE_REQUIRED_FIELDS = (
    "wallet_address",
    "chain",
    "score",
    "tier",
    "decision",
)

SCORE_DIMENSION_FIELDS = (
    "profitability",
    "win_rate",
    "risk_control",
    "consistency",
    "activity",
    "stability",
)

VALID_TIERS = {"S", "A", "B", "C", "D"}
VALID_DECISIONS = {"follow", "watch", "reject"}


@dataclass(frozen=True)
class WalletScore:
    """Scored wallet output from the six-dimensional scoring engine.

    Stores all fields in a flat *data* dict.  Convenience properties expose
    the most commonly accessed fields.
    """

    data: dict[str, Any]

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WalletScore:
        errors = _validate_score_data(data)
        if errors:
            raise ValueError("; ".join(errors))
        return cls(data)

    def get(self, field: str) -> Any:
        return self.data[field]

    @property
    def total_score(self) -> float:
        return float(self.data.get("score", 0))

    @property
    def tier(self) -> str:
        return str(self.data.get("tier", "D"))

    @property
    def decision(self) -> str:
        return str(self.data.get("decision", "reject"))

    @property
    def robot_score(self) -> float:
        return float(self.data.get("robot_score", 0))

    def dimension_score(self, name: str) -> float | None:
        """Return a dimension score, looking in *metrics* first then top level."""
        metrics = self.data.get("metrics")
        if isinstance(metrics, dict) and name in metrics:
            val = metrics[name]
            return float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else None
        if name in self.data:
            val = self.data[name]
            return float(val) if isinstance(val, (int, float)) and not isinstance(val, bool) else None
        return None


def _validate_score_data(data: dict[str, Any]) -> list[str]:
    """Return a list of validation errors for a scored wallet dict."""
    errors: list[str] = []

    for field in SCORE_REQUIRED_FIELDS:
        if field not in data:
            errors.append(f"missing field: {field}")

    if "wallet_address" in data and (not isinstance(data["wallet_address"], str) or not data["wallet_address"].strip()):
        errors.append("wallet_address must be non-empty string")

    if "chain" in data and data["chain"] not in VALID_CHAINS:
        errors.append(f"chain must be one of {sorted(VALID_CHAINS)}")

    if "score" in data and (isinstance(data["score"], bool) or not isinstance(data["score"], (int, float))):
        errors.append("score must be numeric")
    elif "score" in data and not isfinite(data["score"]):
        errors.append("score must be finite")
    elif "score" in data and (data["score"] < 0 or data["score"] > 100):
        errors.append("score must be between 0 and 100")

    if "tier" in data and data["tier"] not in VALID_TIERS:
        errors.append(f"tier must be one of {sorted(VALID_TIERS)}")

    if "decision" in data and data["decision"] not in VALID_DECISIONS:
        errors.append(f"decision must be one of {sorted(VALID_DECISIONS)}")

    if "reasons" in data:
        if not isinstance(data["reasons"], list):
            errors.append("reasons must be a list")
        else:
            for i, r in enumerate(data["reasons"]):
                if not isinstance(r, str):
                    errors.append(f"reasons[{i}] must be string")

    if "metrics" in data and not isinstance(data["metrics"], dict):
        errors.append("metrics must be a dict")

    # Validate individual dimension scores if present at top level
    for field in SCORE_DIMENSION_FIELDS:
        if field in data and (isinstance(data[field], bool) or not isinstance(data[field], (int, float))):
            errors.append(f"{field} must be numeric")
        elif field in data and not isfinite(data[field]):
            errors.append(f"{field} must be finite")
        elif field in data and (data[field] < 0 or data[field] > 100):
            errors.append(f"{field} must be between 0 and 100")

    # Validate robot_score if present
    if "robot_score" in data:
        if isinstance(data["robot_score"], bool) or not isinstance(data["robot_score"], (int, float)):
            errors.append("robot_score must be numeric")
        elif not isfinite(data["robot_score"]):
            errors.append("robot_score must be finite")
        elif data["robot_score"] < 0 or data["robot_score"] > 100:
            errors.append("robot_score must be between 0 and 100")

    return errors
