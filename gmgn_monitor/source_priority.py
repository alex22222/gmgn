from __future__ import annotations

from typing import Any


__all__ = [
    "FIELD_SOURCE_PRIORITY",
    "merge_wallet_data",
]


# Field-level source priority for merging multi-source wallet data.
# Higher-priority sources appear earlier in each list.
FIELD_SOURCE_PRIORITY = {
    "total_profit": ["gmgn", "birdeye"],
    "win_rate": ["gmgn"],
    "trades_7d": ["gmgn"],
    "trades_30d": ["gmgn"],
    "portfolio_value": ["helius", "solscan"],
    "token_price": ["birdeye", "helius"],
    "transactions": ["solscan", "helius"],
    "token_metadata": ["helius", "birdeye"],
    "account_info": ["solscan", "helius"],
    "token_holders": ["helius"],
}


def _extract_field(data: dict[str, Any], field: str) -> Any:
    """Extract *field* from a source response dict, handling nested wrappers.

    Returns ``None`` if the field is absent or the value is ``None``.
    """
    if not isinstance(data, dict):
        return None

    # Direct key
    if field in data and data[field] is not None:
        return data[field]

    # Nested under "data"
    nested = data.get("data")
    if isinstance(nested, dict) and field in nested and nested[field] is not None:
        return nested[field]

    # Special-case mappings for known nested structures
    if field == "portfolio_value":
        portfolio = data.get("portfolio")
        if isinstance(portfolio, dict):
            return portfolio.get("total_value")
        balances = data.get("balances")
        if isinstance(balances, list):
            return sum(
                b.get("value", 0) or 0
                for b in balances
                if isinstance(b, dict)
            )

    if field == "token_price":
        price = data.get("price")
        if price is not None:
            return price
        value = data.get("value")
        if value is not None:
            return value

    if field == "transactions":
        txs = data.get("transactions")
        if isinstance(txs, list):
            return txs
        tx_list = data.get("txs")
        if isinstance(tx_list, list):
            return tx_list

    return None


def merge_wallet_data(sources_data: dict[str, dict]) -> dict[str, Any]:
    """Merge wallet data from multiple sources into a single canonical record.

    For each field in :pydata:`FIELD_SOURCE_PRIORITY`, the value from the
    highest-priority source that provides a non-``None`` value is chosen.
    Sources not listed in the priority map are ignored for that field.

    Args:
        sources_data: Mapping of source name → raw response dict.
            Example::

                {
                    "gmgn": {"total_profit": 5000, "win_rate": 0.75},
                    "helius": {"portfolio_value": 12000},
                }

    Returns:
        A merged dict with the best available data per field.
    """
    merged: dict[str, Any] = {}

    for field, priority in FIELD_SOURCE_PRIORITY.items():
        for source in priority:
            source_data = sources_data.get(source)
            if not isinstance(source_data, dict):
                continue
            value = _extract_field(source_data, field)
            if value is not None:
                merged[field] = value
                break

    return merged
