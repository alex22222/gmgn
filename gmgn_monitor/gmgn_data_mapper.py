from __future__ import annotations

from typing import Any


__all__ = [
    "map_wallet_stats_to_features",
    "map_smartmoney_list_to_wallet_addresses",
    "map_token_top_traders_to_wallet_addresses",
]

SOL_PRICE_USD = 150.0


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely coerce *value* to ``float``.  Booleans and non-numeric values fall
    back to *default*."""
    if isinstance(value, bool):
        return default
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return default
    return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely coerce *value* to ``int``."""
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(float(value))
        except ValueError:
            return default
    return default


def map_wallet_stats_to_features(wallet_stats: dict[str, Any]) -> dict[str, Any]:
    """Convert a single wallet's GMGN flat statistics into the nested feature
    dictionary expected by :func:`~gmgn_monitor.wallet_scorer.score_wallet`.

    Missing or malformed fields are replaced with sensible defaults so that
    downstream scoring never crashes.

    Args:
        wallet_stats: A dict containing one wallet's GMGN fields such as
            ``total_profit``, ``win_rate``, ``trades_7d``, etc.

    Returns:
        A nested feature dict with keys ``profit_metrics``,
        ``risk_metrics``, ``frequency_metrics``, ``portfolio_metrics``,
        ``behavior_flags``, ``behavioral_metrics``, ``capital_metrics``,
        ``token_preference``, plus top-level ``wallet_address``,
        ``chain``, ``first_seen_at`` and ``total_transactions``.
    """
    if not isinstance(wallet_stats, dict):
        raise TypeError("wallet_stats must be a dict")

    # ------------------------------------------------------------------
    # Raw GMGN fields (with safe defaults)
    # ------------------------------------------------------------------
    total_profit = _safe_float(wallet_stats.get("total_profit"))
    if total_profit == 0:
        total_profit = _safe_float(wallet_stats.get("realized_profit"))
    pnl_stat = wallet_stats.get("pnl_stat")
    if not isinstance(pnl_stat, dict):
        pnl_stat = {}
    win_rate = _safe_float(wallet_stats.get("win_rate"))
    if win_rate == 0:
        raw_winrate = _safe_float(pnl_stat.get("winrate"))
        win_rate = raw_winrate * 100.0 if 0 < raw_winrate <= 1 else raw_winrate
    total_trades = _safe_int(wallet_stats.get("total_trades"))
    if total_trades == 0:
        total_trades = _safe_int(wallet_stats.get("buy")) + _safe_int(wallet_stats.get("sell"))
    # A missing period count falls back to the payload's total. An explicit 0
    # stays 0 so a quiet 7d window is not replaced by the 30d book.
    trades_7d = total_trades if "trades_7d" not in wallet_stats or wallet_stats.get("trades_7d") is None else _safe_int(wallet_stats.get("trades_7d"))
    trades_30d = total_trades if "trades_30d" not in wallet_stats or wallet_stats.get("trades_30d") is None else _safe_int(wallet_stats.get("trades_30d"))
    avg_holding_time = _safe_float(wallet_stats.get("avg_holding_time"))
    if avg_holding_time == 0:
        avg_holding_time = _safe_float(pnl_stat.get("avg_holding_period")) / 3600.0
    pnl_30d = _safe_float(wallet_stats.get("pnl_30d"))
    if pnl_30d == 0:
        pnl_30d = total_profit
    max_drawdown = _safe_float(wallet_stats.get("max_drawdown"))
    portfolio_value = _safe_float(wallet_stats.get("portfolio_value"))
    balance_usd = _safe_float(wallet_stats.get("balance_usd"))

    wallet_address = str(wallet_stats.get("wallet_address", ""))
    chain = str(wallet_stats.get("chain", "solana"))
    first_seen_at = str(wallet_stats.get("first_seen_at", "2025-01-01T00:00:00Z"))
    days_since_last_trade = _safe_float(wallet_stats.get("days_since_last_trade"))

    mev_attacker = bool(wallet_stats.get("mev_attacker", False))
    dev_wallet = bool(wallet_stats.get("dev_wallet", False))
    sniper_detected = bool(wallet_stats.get("sniper_detected", False))

    # Boolean flags (default False)
    mev_attacker = bool(wallet_stats.get("mev_attacker", False))
    dev_wallet = bool(wallet_stats.get("dev_wallet", False))
    sniper_detected = bool(wallet_stats.get("sniper_detected", False))

    # ------------------------------------------------------------------
    # Derived metrics
    # ------------------------------------------------------------------
    total_pnl_sol = total_profit / SOL_PRICE_USD
    avg_profit_per_trade_sol = (
        total_pnl_sol / total_trades if total_trades > 0 else 0.0
    )
    profit_factor = max(1.0, win_rate / 30.0) if win_rate > 0 else 1.0
    profit_loss_ratio = profit_factor

    avg_daily_trades = trades_30d / 30.0 if trades_30d > 0 else 0.0

    stablecoin_ratio = (
        (balance_usd / portfolio_value * 100.0) if portfolio_value > 0 else 0.0
    )

    avg_position_sol = _safe_float(wallet_stats.get("avg_position_sol"))
    if avg_position_sol == 0 and portfolio_value > 0:
        avg_position_sol = round(portfolio_value / SOL_PRICE_USD / 10.0, 4)
    if avg_position_sol == 0:
        avg_position_sol = 2.0

    max_position_sol = _safe_float(wallet_stats.get("max_position_sol"))
    if max_position_sol == 0 and portfolio_value > 0:
        max_position_sol = round(portfolio_value / SOL_PRICE_USD, 4)
    if max_position_sol == 0:
        max_position_sol = 10.0

    median_position_sol = _safe_float(wallet_stats.get("median_position_sol"))
    if median_position_sol == 0:
        median_position_sol = avg_position_sol

    total_volume_sol = _safe_float(wallet_stats.get("total_volume_sol"))
    if total_volume_sol == 0:
        total_volume_sol = round(total_trades * 2.0, 4)

    profit_sol_30d = pnl_30d / SOL_PRICE_USD
    profit_usd_30d = pnl_30d

    total_transactions = total_trades or trades_30d or trades_7d

    return {
        "wallet_address": wallet_address,
        "chain": chain,
        "first_seen_at": first_seen_at,
        "total_transactions": total_transactions,
        "trades_7d": trades_7d,
        "trades_30d": trades_30d,
        "win_rate_percent": round(win_rate, 2),
        "total_profit_usd": round(total_profit, 2),
        "avg_holding_hours": round(avg_holding_time, 2),
        "total_trades": total_trades,
        "single_token_concentration_percent": 0.0,
        "self_transfer_ratio_percent": 0.0,
        "inactive_days": 0,
        "is_mev_attacker": mev_attacker,
        "is_dev_associated": dev_wallet,
        "trade_intervals_seconds": None,
        "fees_sol_list": None,
        "trade_hours_of_day": None,
        "volatility_30d": 0.0,
        "turbo_slippage_usage_percent": 0.0,
        "wallet_age_days": 0,
        "diversification_index": 0.5,
        "mev_usage_percent": 0.0,
        "pump_fun_interaction_percent": 0.0,
        "large_gambler_ratio_percent": 0.0,
        "stop_loss_trigger_rate_percent": 0.0,
        "profit_metrics": {
            "total_pnl_sol": round(total_pnl_sol, 4),
            "total_pnl_usd": round(total_profit, 2),
            "win_rate_percent": round(win_rate, 2),
            "avg_profit_per_trade_sol": round(avg_profit_per_trade_sol, 4),
            "profit_factor": profit_factor,
            "profit_loss_ratio": profit_loss_ratio,
            "max_consecutive_losses": 0,
            "profit_sol_30d": round(profit_sol_30d, 4),
            "profit_usd_30d": round(profit_usd_30d, 2),
            "max_consecutive_wins": 0,
        },
        "risk_metrics": {
            "max_drawdown_percent": round(max_drawdown, 2),
            "avg_drawdown_percent": round(max_drawdown * 0.5, 2),
            "sharpe_ratio": 0.0,
            "sortino_ratio": 0.0,
            "volatility_7d": 0.0,
            "var_95": 0.0,
        },
        "frequency_metrics": {
            "trades_7d": trades_7d,
            "trades_30d": trades_30d,
            "avg_daily_trades": avg_daily_trades,
            "avg_holding_hours": round(avg_holding_time, 2),
            "median_holding_hours": round(avg_holding_time, 2),
            "max_holding_hours": round(avg_holding_time * 2.0, 2) if avg_holding_time > 0 else 0.0,
            "min_holding_hours": 0.0,
            "days_since_last_trade": round(days_since_last_trade, 2),
        },
        "portfolio_metrics": {
            "stablecoin_ratio_percent": stablecoin_ratio,
            "diversification_index": 0.5,
            "concentration_risk": 0.5,
        },
        "behavior_flags": {
            "mev_attacker": mev_attacker,
            "dev_wallet": dev_wallet,
            "known_scammer": False,
            "bot_pattern": False,
        },
        "behavioral_metrics": {
            "sniper_detected": sniper_detected,
            "bot_pattern_score": 0.0,
            "mev_usage_percent": 0.0,
            "turboslippage_usage_percent": 0.0,
            "new_token_buy_percent": 0.0,
            "stablecoin_holding_percent": stablecoin_ratio,
            "diversification_index": 0.5,
        },
        "capital_metrics": {
            "avg_position_sol": avg_position_sol,
            "max_position_sol": max_position_sol,
            "median_position_sol": median_position_sol,
            "total_volume_sol": total_volume_sol,
            "profit_sol_30d": round(profit_sol_30d, 4),
            "profit_usd_30d": round(profit_usd_30d, 2),
        },
        "token_preference": {
            "favorite_token_categories": [],
            "pump_fun_interaction_percent": 0.0,
            "graduated_token_rate": 0.0,
            "early_entry_rate": 0.0,
        },
    }


def map_smartmoney_list_to_wallet_addresses(
    smartmoney_data: dict[str, Any],
) -> list[str]:
    """Extract wallet addresses from the smartmoney API response.

    The GMGN smartmoney endpoint typically returns a list of wallet objects
    under ``data`` or directly as a list.  This function is tolerant of
    both shapes and silently skips malformed entries.

    Args:
        smartmoney_data: Raw API response (usually the ``data`` field) or
            a full response dict.

    Returns:
        A list of wallet address strings.
    """
    if not isinstance(smartmoney_data, dict):
        return []

    # The response may already be the ``data`` payload, or it may be a
    # response wrapper.  Try to unwrap a ``data`` or ``wallets`` key.
    candidates = smartmoney_data
    if isinstance(smartmoney_data.get("data"), list):
        candidates = {"data": smartmoney_data["data"]}
    elif isinstance(smartmoney_data.get("wallets"), list):
        candidates = {"data": smartmoney_data["wallets"]}
    elif isinstance(smartmoney_data.get("data"), dict):
        data_dict = smartmoney_data["data"]
        if isinstance(data_dict.get("list"), list):
            candidates = {"data": data_dict["list"]}
        elif isinstance(data_dict.get("wallets"), list):
            candidates = {"data": data_dict["wallets"]}

    wallets = candidates.get("data", [])
    if not isinstance(wallets, list):
        return []

    addresses: list[str] = []
    for item in wallets:
        if isinstance(item, str):
            addresses.append(item)
        elif isinstance(item, dict):
            addr = item.get("wallet_address") or item.get("address")
            if isinstance(addr, str) and addr:
                addresses.append(addr)

    return addresses


def map_token_top_traders_to_wallet_addresses(
    top_traders_data: dict[str, Any],
) -> list[str]:
    """Extract wallet addresses from the token_top_traders API response.

    Args:
        top_traders_data: Raw API response (usually the ``data`` field) or
            a full response dict.

    Returns:
        A list of wallet address strings.
    """
    if not isinstance(top_traders_data, dict):
        return []

    # Unwrap if the caller passed the full response wrapper
    candidates = top_traders_data
    if isinstance(top_traders_data.get("data"), list):
        candidates = {"data": top_traders_data["data"]}
    elif isinstance(top_traders_data.get("traders"), list):
        candidates = {"data": top_traders_data["traders"]}
    elif isinstance(top_traders_data.get("data"), dict):
        data_dict = top_traders_data["data"]
        if isinstance(data_dict.get("list"), list):
            candidates = {"data": data_dict["list"]}
        elif isinstance(data_dict.get("traders"), list):
            candidates = {"data": data_dict["traders"]}

    traders = candidates.get("data", [])
    if not isinstance(traders, list):
        return []

    addresses: list[str] = []
    for item in traders:
        if isinstance(item, str):
            addresses.append(item)
        elif isinstance(item, dict):
            addr = item.get("wallet_address") or item.get("address") or item.get("maker") or item.get("wallet") or item.get("account_address")
            if isinstance(addr, str) and addr:
                addresses.append(addr)

    return addresses
