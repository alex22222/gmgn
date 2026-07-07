from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config_manager import ConfigManager
from .file_io import atomic_write_text
from .gmgn_data_mapper import map_token_top_traders_to_wallet_addresses, map_wallet_stats_to_features
from .real_wallet_fetcher import RealWalletFetcher
from .wallet_filter import filter_wallet
from .wallet_scorer import score_wallet


_BATCH_SIZE = 100
_DEFAULT_SCORE_BATCH_SIZE = 10


def discover_leaders(
    root: Path,
    *,
    target: int,
    chain: str = 'sol',
    api_key: str | None = None,
    fetcher: Any | None = None,
) -> dict[str, object]:
    root = root.resolve()
    current = _read_json_list(root / 'data' / 'candidate_wallets_smartmoney.json')
    current_by_address = _dedupe_candidates(current)
    needed = max(0, target - len(current_by_address))
    if needed == 0:
        result = _action_result('discover', True, f'候选池已达到目标：{len(current_by_address)}/{target}')
        result.update({'before': len(current_by_address), 'after': len(current_by_address), 'added': 0})
        _write_action_result(root, result)
        return result

    fetcher = fetcher or _build_fetcher(chain=chain, api_key=api_key)
    now = datetime.now(timezone.utc).isoformat()
    added = _merge_wallet_candidates(
        current_by_address,
        fetcher.fetch_smartmoney_wallets(limit=target),
        chain=chain,
        source='gmgn_smartmoney',
        discovered_at=now,
    )
    tracked_added = 0
    if len(current_by_address) < target:
        tracked_added = _discover_from_tracked_trades(
            current_by_address,
            fetcher,
            chain=chain,
            target=target,
            discovered_at=now,
        )
        added += tracked_added
    market_signal_added = 0
    if len(current_by_address) < target:
        market_signal_added = _discover_from_market_signals(
            current_by_address,
            fetcher,
            chain=chain,
            target=target,
            discovered_at=now,
        )
        added += market_signal_added
    secondary_added = 0
    if len(current_by_address) < target:
        secondary_added = _discover_from_token_top_traders(
            current_by_address,
            fetcher,
            chain=chain,
            target=target,
            discovered_at=now,
        )
        added += secondary_added

    merged = list(current_by_address.values())
    _write_json_list(root / 'data' / 'candidate_wallets_smartmoney.json', merged)
    result = _action_result('discover', True, f'扫链扩池完成：新增 {added} 个，当前 {len(merged)}/{target}')
    result.update({
        'before': len(current),
        'after': len(merged),
        'added': added,
        'market_signal_added': market_signal_added,
        'tracked_added': tracked_added,
        'secondary_added': secondary_added,
        'target': target,
    })
    _write_action_result(root, result)
    return result


def score_leaders(
    root: Path,
    *,
    min_score: float,
    min_win_rate_percent: float,
    min_total_trades: int,
    lookback_windows: list[str],
    score_batch_size: int = _DEFAULT_SCORE_BATCH_SIZE,
    score_concurrency: int = 4,
    chain: str = 'sol',
    api_key: str | None = None,
    fetcher: Any | None = None,
) -> dict[str, object]:
    root = root.resolve()
    candidates = _read_json_list(root / 'data' / 'candidate_wallets_smartmoney.json')
    candidate_records = _prioritised_candidates(candidates)
    addresses = [str(item.get('wallet_address') or item.get('address') or '').strip() for item in candidate_records]
    if not addresses:
        result = _action_result('score', False, '没有候选钱包，请先执行扫链扩池。')
        _write_action_result(root, result)
        return result
    previous_whitelist = _read_json_list(root / 'data' / 'whitelist_wallets.json')
    previous_watchlist = _read_json_list(root / 'data' / 'watchlist_wallets.json')
    previous_blacklist = _read_json_list(root / 'data' / 'blacklist_wallets.json')
    previously_scored = {
        str(item.get('wallet_address') or item.get('address') or '').lower()
        for item in previous_whitelist + previous_watchlist + previous_blacklist
        if isinstance(item, dict) and (item.get('wallet_address') or item.get('address'))
    }
    pending_addresses = [address for address in addresses if address.lower() not in previously_scored]
    selected_addresses = pending_addresses[:max(1, int(score_batch_size))]
    if not selected_addresses:
        selected_addresses = addresses[:max(1, int(score_batch_size))]

    fetcher = fetcher or _build_fetcher(chain=chain, api_key=api_key)
    windows = lookback_windows or ['7d', '14d', '30d']

    whitelist: list[dict[str, Any]] = [item for item in previous_whitelist if isinstance(item, dict)]
    watchlist: list[dict[str, Any]] = [item for item in previous_watchlist if isinstance(item, dict)]
    blacklist: list[dict[str, Any]] = [item for item in previous_blacklist if isinstance(item, dict)]
    candidate_by_address = {
        str(item.get('wallet_address') or item.get('address')).lower(): item
        for item in candidate_records
        if isinstance(item, dict) and (item.get('wallet_address') or item.get('address'))
    }

    scored_records = _score_selected_wallets(
        fetcher,
        selected_addresses,
        windows,
        candidate_by_address,
        chain=chain,
        min_score=min_score,
        min_win_rate_percent=min_win_rate_percent,
        min_total_trades=min_total_trades,
        score_concurrency=max(1, int(score_concurrency)),
    )

    for address, best_record in scored_records:
        if not best_record:
            _replace_record(blacklist, _reject_record(address, 'GMGN stats unavailable'))
            continue
        if _is_high_quality(best_record, min_score, min_win_rate_percent, min_total_trades):
            _remove_record(watchlist, address)
            _remove_record(blacklist, address)
            _replace_record(whitelist, best_record)
        elif best_record['filter_decision'] == 'watch' or best_record['decision'] in {'watch', 'copy'}:
            _remove_record(whitelist, address)
            _remove_record(blacklist, address)
            _replace_record(watchlist, best_record)
        else:
            _remove_record(whitelist, address)
            _remove_record(watchlist, address)
            _replace_record(blacklist, best_record)

    whitelist.sort(key=lambda item: float(item.get('total_score') or 0), reverse=True)
    watchlist.sort(key=lambda item: float(item.get('total_score') or 0), reverse=True)
    blacklist.sort(key=lambda item: float(item.get('total_score') or 0), reverse=True)
    high_quality_count = sum(
        1 for item in whitelist + watchlist
        if _is_high_quality(item, min_score, min_win_rate_percent, min_total_trades)
    )
    _write_json_list(root / 'data' / 'whitelist_wallets.json', whitelist)
    _write_json_list(root / 'data' / 'watchlist_wallets.json', watchlist)
    _write_json_list(root / 'data' / 'blacklist_wallets.json', blacklist)
    result = _action_result(
        'score',
        True,
        f'评分筛选完成：高质量 {high_quality_count}，观察 {len(watchlist)}，淘汰 {len(blacklist)}。',
    )
    result.update({
        'candidate_count': len(addresses),
        'scored_this_run': len(selected_addresses),
        'remaining_unscored': max(0, len(pending_addresses) - len(selected_addresses)),
        'high_quality_count': high_quality_count,
        'watchlist_count': len(watchlist),
        'blacklist_count': len(blacklist),
        'lookback_windows': windows,
        'score_concurrency': max(1, int(score_concurrency)),
    })
    _write_action_result(root, result)
    return result


def promote_leaders(
    root: Path,
    *,
    target: int,
    min_score: float,
    min_win_rate_percent: float,
    min_total_trades: int,
) -> dict[str, object]:
    root = root.resolve()
    config_path = root / 'config' / 'wallet_whitelist.json'
    config = _read_json_object(config_path)
    wallets = config.get('wallets', [])
    if not isinstance(wallets, list):
        wallets = []
    existing = {
        str(wallet.get('wallet_address') or '').lower()
        for wallet in wallets
        if isinstance(wallet, dict) and wallet.get('wallet_address')
    }
    candidates = [
        wallet for wallet in _read_json_list(root / 'data' / 'whitelist_wallets.json')
        if isinstance(wallet, dict)
        and _is_high_quality(wallet, min_score, min_win_rate_percent, min_total_trades)
    ]
    candidates.sort(key=lambda item: float(item.get('total_score') or 0), reverse=True)
    added = 0
    for candidate in candidates:
        if len(wallets) >= target:
            break
        address = str(candidate.get('wallet_address') or candidate.get('address') or '').strip()
        if not address or address.lower() in existing:
            continue
        wallets.append(_promoted_wallet(candidate, len(wallets) + 1))
        existing.add(address.lower())
        added += 1

    config['wallets'] = wallets
    config.setdefault('version', '1.0')
    config.setdefault('description', 'GMGN leader whitelist')
    config['updated_at'] = datetime.now(timezone.utc).isoformat()
    _recalculate_copy_weights(config)
    atomic_write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', config_path)
    result = _action_result('promote', True, f'白名单升级完成：新增 {added} 个，当前 {len(wallets)}/{target}。')
    result.update({'added': added, 'after': len(wallets), 'target': target})
    _write_action_result(root, result)
    return result


def backtest_leaders(
    root: Path,
    *,
    target: int,
    min_score: float,
    min_win_rate_percent: float,
    min_total_trades: int,
) -> dict[str, object]:
    root = root.resolve()
    whitelist_config = _read_json_object(root / 'config' / 'wallet_whitelist.json')
    configured_wallets = whitelist_config.get('wallets', [])
    if not isinstance(configured_wallets, list):
        configured_wallets = []
    candidates = _dedupe_scored_records(
        _read_json_list(root / 'data' / 'whitelist_wallets.json')
        + _read_json_list(root / 'data' / 'watchlist_wallets.json')
        + _read_json_list(root / 'data' / 'blacklist_wallets.json')
        + configured_wallets
    )
    selected = sorted(
        candidates.values(),
        key=lambda item: (float(item.get('total_score') or 0), _stats_number(item, 'winrate')),
        reverse=True,
    )[:target]
    results = [
        _score_backtest_record(wallet, min_score, min_win_rate_percent, min_total_trades)
        for wallet in selected
    ]
    _write_json_list(root / 'data' / 'leader_backtest_results.json', results)
    passed = sum(1 for item in results if item.get('passed'))
    result = _action_result('backtest', True, f'评分回测完成：{passed}/{len(results)} 通过。')
    result.update({'backtested': len(results), 'passed': passed, 'target': target})
    _write_action_result(root, result)
    return result


def _build_fetcher(*, chain: str, api_key: str | None) -> RealWalletFetcher:
    resolved_api_key = _resolve_gmgn_api_key(api_key)
    if not resolved_api_key:
        raise RuntimeError('GMGN_API_KEY 未配置，无法执行真实扫链。')
    return RealWalletFetcher(api_key=resolved_api_key, chain=chain, mock_fallback=False)


def _resolve_gmgn_api_key(api_key: str | None = None) -> str | None:
    if api_key:
        return api_key
    env_key = os.environ.get('GMGN_API_KEY')
    if env_key:
        return env_key
    try:
        return ConfigManager().gmgn_api_key
    except Exception:
        return None


def _prioritised_candidates(candidates: list[object]) -> list[dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for item in candidates:
        if not isinstance(item, dict):
            continue
        address = str(item.get('wallet_address') or item.get('address') or '').strip()
        if not address:
            continue
        candidate = {**item, 'wallet_address': address, 'address': address}
        key = address.lower()
        current = deduped.get(key)
        if current is None or _candidate_priority_key(candidate) > _candidate_priority_key(current):
            deduped[key] = candidate
    return sorted(deduped.values(), key=_candidate_priority_key, reverse=True)


def _candidate_priority_key(candidate: dict[str, Any]) -> tuple[float, float, float, float, float, float, float]:
    source = str(candidate.get('source') or '')
    source_score = {
        'gmgn_track_smartmoney': 5.0,
        'gmgn_smartmoney': 4.0,
        'gmgn_track_kol': 3.0,
        'gmgn_token_smart_degen_traders': 2.0,
        'gmgn_market_signal_12': 1.5,
        'gmgn_token_top_traders': 1.0,
    }.get(source, 0.0)
    tags = candidate.get('tags')
    if not isinstance(tags, list):
        tags = []
    tag_score = sum(
        1.0 for tag in tags
        if str(tag) in {'smart_degen', 'app_smart_money', 'top_followed', 'gmgn'}
    )
    return (
        source_score,
        tag_score,
        _safe_float(candidate.get('signal_times')),
        _safe_float(candidate.get('signal_count')),
        _safe_float(candidate.get('volume_usd')),
        _safe_float(candidate.get('amount_usd')) or _safe_float(candidate.get('buy_amount')),
        -_safe_float(candidate.get('rank'), default=999999.0),
    )


def _safe_float(value: object, *, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _fetch_stats_batches(fetcher: Any, addresses: list[str], *, period: str) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for start in range(0, len(addresses), _BATCH_SIZE):
        batch = addresses[start:start + _BATCH_SIZE]
        try:
            data = fetcher.fetch_wallet_stats(batch, period=period)
            if isinstance(data, dict):
                stats.update(_normalise_wallet_stats(batch, data))
        except Exception:
            for address in batch:
                try:
                    data = fetcher.fetch_wallet_stats([address], period=period)
                except Exception:
                    continue
                if isinstance(data, dict):
                    stats.update(_normalise_wallet_stats([address], data))
    return stats


def _score_selected_wallets(
    fetcher: Any,
    selected_addresses: list[str],
    windows: list[str],
    candidate_by_address: dict[str, dict[str, Any]],
    *,
    chain: str,
    min_score: float,
    min_win_rate_percent: float,
    min_total_trades: int,
    score_concurrency: int,
) -> list[tuple[str, dict[str, Any] | None]]:
    if score_concurrency <= 1 or len(selected_addresses) <= 1:
        return [
            (
                address,
                _score_one_wallet(
                    fetcher,
                    address,
                    windows,
                    candidate_by_address,
                    chain=chain,
                    min_score=min_score,
                    min_win_rate_percent=min_win_rate_percent,
                    min_total_trades=min_total_trades,
                ),
            )
            for address in selected_addresses
        ]

    results: dict[str, dict[str, Any] | None] = {}
    with ThreadPoolExecutor(max_workers=min(score_concurrency, len(selected_addresses))) as executor:
        futures = {
            executor.submit(
                _score_one_wallet,
                fetcher,
                address,
                windows,
                candidate_by_address,
                chain=chain,
                min_score=min_score,
                min_win_rate_percent=min_win_rate_percent,
                min_total_trades=min_total_trades,
            ): address
            for address in selected_addresses
        }
        for future in as_completed(futures):
            address = futures[future]
            try:
                results[address] = future.result()
            except Exception:
                results[address] = None
    return [(address, results.get(address)) for address in selected_addresses]


def _score_one_wallet(
    fetcher: Any,
    address: str,
    windows: list[str],
    candidate_by_address: dict[str, dict[str, Any]],
    *,
    chain: str,
    min_score: float,
    min_win_rate_percent: float,
    min_total_trades: int,
) -> dict[str, Any] | None:
    return _score_wallet_across_windows(
        fetcher,
        address,
        windows,
        {},
        chain=chain,
        source_candidate=candidate_by_address.get(address.lower(), {}),
        min_score=min_score,
        min_win_rate_percent=min_win_rate_percent,
        min_total_trades=min_total_trades,
    )


def _score_wallet_across_windows(
    fetcher: Any,
    address: str,
    windows: list[str],
    stats_by_window: dict[str, dict[str, Any]],
    *,
    chain: str,
    source_candidate: dict[str, Any],
    min_score: float,
    min_win_rate_percent: float,
    min_total_trades: int,
) -> dict[str, Any] | None:
    best_record: dict[str, Any] | None = None
    best_key = (-1.0, -1.0)
    for window in windows:
        window_stats = stats_by_window.setdefault(window, {})
        if address not in window_stats:
            window_stats.update(_fetch_stats_batches(fetcher, [address], period=window))
        raw_stats = window_stats.get(address)
        if not isinstance(raw_stats, dict):
            continue
        record = _scored_record(
            address,
            window,
            raw_stats,
            windows,
            stats_by_window,
            chain=chain,
            source_candidate=source_candidate,
        )
        key = _record_quality_key(record)
        if key > best_key:
            best_record = record
            best_key = key
        if _is_high_quality(record, min_score, min_win_rate_percent, min_total_trades):
            return record
    return best_record


def _scored_record(
    address: str,
    window: str,
    raw_stats: dict[str, Any],
    windows: list[str],
    stats_by_window: dict[str, dict[str, Any]],
    *,
    chain: str,
    source_candidate: dict[str, Any],
) -> dict[str, Any]:
    stats = dict(raw_stats)
    stats.setdefault('wallet_address', address)
    stats.setdefault('chain', chain)
    features = map_wallet_stats_to_features(stats)
    score_result = score_wallet(features)
    filter_result = filter_wallet(features)
    return {
        'wallet_address': address,
        'address': address,
        'chain': chain,
        'source': source_candidate.get('source') or 'gmgn_smartmoney',
        'total_score': score_result['total_score'],
        'grade': score_result['grade'],
        'decision': score_result['decision'],
        'score_reasons': score_result['reasons'],
        'filter_decision': filter_result['decision'],
        'filter_score': filter_result['score'],
        'filter_reasons': filter_result['reasons'],
        'hard_rejected': filter_result['hard_rejected'],
        'robot_score': filter_result['robot_score'],
        'stats': _compact_stats(features, window),
        'window_stats': _compact_window_stats(address, windows, stats_by_window),
        'dimension_scores': score_result['dimension_scores'],
        'scored_at': datetime.now(timezone.utc).isoformat(),
    }


def _record_quality_key(record: dict[str, Any]) -> tuple[float, float]:
    stats = record.get('stats')
    if not isinstance(stats, dict):
        return (-1.0, -1.0)
    return (
        float(stats.get('winrate') or 0),
        float(stats.get('total_trades') or 0),
    )


def _normalise_wallet_stats(addresses: list[str], data: dict[str, Any]) -> dict[str, Any]:
    if len(addresses) == 1 and addresses[0] not in data:
        return {addresses[0]: data}
    return data


def _best_window_stats(
    address: str,
    windows: list[str],
    stats_by_window: dict[str, dict[str, Any]],
) -> tuple[str, dict[str, Any]] | None:
    best: tuple[str, dict[str, Any]] | None = None
    best_key = (-1.0, -1.0)
    for window in windows:
        stats = stats_by_window.get(window, {}).get(address)
        if not isinstance(stats, dict):
            continue
        features = map_wallet_stats_to_features({**stats, 'wallet_address': address})
        key = (
            float(features.get('win_rate_percent') or 0),
            float(features.get('total_trades') or features.get('total_transactions') or 0),
        )
        if key > best_key:
            best = (window, stats)
            best_key = key
    return best


def _compact_stats(features: dict[str, Any], window: str) -> dict[str, object]:
    return {
        'period': window,
        'realized_profit': features.get('total_profit_usd'),
        'winrate': features.get('win_rate_percent'),
        'total_trades': features.get('total_trades') or features.get('total_transactions'),
        'trades_7d': features.get('trades_7d'),
        'trades_30d': features.get('trades_30d'),
        'avg_holding_hours': features.get('avg_holding_hours'),
    }


def _compact_window_stats(
    address: str,
    windows: list[str],
    stats_by_window: dict[str, dict[str, Any]],
) -> dict[str, dict[str, object]]:
    compact: dict[str, dict[str, object]] = {}
    for window in windows:
        stats = stats_by_window.get(window, {}).get(address)
        if not isinstance(stats, dict):
            continue
        features = map_wallet_stats_to_features({**stats, 'wallet_address': address})
        compact[window] = _compact_stats(features, window)
    return compact


def _is_high_quality(
    record: dict[str, Any],
    min_score: float,
    min_win_rate_percent: float,
    min_total_trades: int,
) -> bool:
    stats = record.get('stats')
    if not isinstance(stats, dict):
        return False
    return (
        float(record.get('total_score') or 0) >= min_score
        and float(stats.get('winrate') or 0) >= min_win_rate_percent
        and int(float(stats.get('total_trades') or 0)) >= min_total_trades
    )


def _reject_record(address: str, reason: str) -> dict[str, Any]:
    return {
        'wallet_address': address,
        'address': address,
        'total_score': 0.0,
        'grade': 'E',
        'decision': 'reject',
        'score_reasons': [reason],
        'stats': {},
        'dimension_scores': {},
    }


def _replace_record(records: list[dict[str, Any]], record: dict[str, Any]) -> None:
    address = str(record.get('wallet_address') or record.get('address') or '').lower()
    if not address:
        return
    _remove_record(records, address)
    records.append(record)


def _remove_record(records: list[dict[str, Any]], address: str) -> None:
    key = address.lower()
    records[:] = [
        record for record in records
        if str(record.get('wallet_address') or record.get('address') or '').lower() != key
    ]


def _merge_wallet_candidates(
    current_by_address: dict[str, dict[str, Any]],
    wallets: list[dict[str, Any]],
    *,
    chain: str,
    source: str,
    discovered_at: str,
) -> int:
    added = 0
    for index, wallet in enumerate(wallets):
        if not isinstance(wallet, dict):
            continue
        address = str(wallet.get('wallet_address') or wallet.get('address') or wallet.get('wallet') or '').strip()
        if not address:
            continue
        key = address.lower()
        if key in current_by_address:
            continue
        current_by_address[key] = {
            'address': address,
            'wallet_address': address,
            'chain': chain,
            'source': source,
            'rank': wallet.get('rank', index + 1),
            'discovered_at': discovered_at,
        }
        for field in (
            'tags',
            'amount_usd',
            'base_address',
            'token_address',
            'token_symbol',
            'side',
            'trade_timestamp',
            'signal_type',
            'trigger_at',
            'trigger_mc',
            'market_cap',
            'signal_times',
            'signal_count',
            'total_amount',
            'buy_timestamp',
            'buy_amount',
        ):
            if field in wallet:
                current_by_address[key][field] = wallet[field]
        added += 1
    return added


def _discover_from_market_signals(
    current_by_address: dict[str, dict[str, Any]],
    fetcher: Any,
    *,
    chain: str,
    target: int,
    discovered_at: str,
) -> int:
    if not hasattr(fetcher, 'fetch_market_signal_wallets'):
        return 0
    try:
        wallets = fetcher.fetch_market_signal_wallets(signal_type=12, limit=max(50, target - len(current_by_address)))
    except Exception:
        return 0
    return _merge_wallet_candidates(
        current_by_address,
        wallets,
        chain=chain,
        source='gmgn_market_signal_12',
        discovered_at=discovered_at,
    )


def _discover_from_tracked_trades(
    current_by_address: dict[str, dict[str, Any]],
    fetcher: Any,
    *,
    chain: str,
    target: int,
    discovered_at: str,
) -> int:
    added = 0
    sources = [
        ('gmgn_track_smartmoney', 'fetch_smartmoney_trades', 200),
        ('gmgn_track_kol', 'fetch_kol_trades', 100),
    ]
    for source, method_name, limit in sources:
        if len(current_by_address) >= target:
            break
        if not hasattr(fetcher, method_name):
            continue
        try:
            trades = getattr(fetcher, method_name)(limit=limit, side='buy')
        except Exception:
            continue
        wallet_records = _wallet_records_from_trades(trades)
        added += _merge_wallet_candidates(
            current_by_address,
            wallet_records,
            chain=chain,
            source=source,
            discovered_at=discovered_at,
        )
    return added


def _wallet_records_from_trades(trades: list[dict[str, Any]]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for index, trade in enumerate(trades):
        if not isinstance(trade, dict):
            continue
        address = str(trade.get('maker') or '').strip()
        if not address:
            continue
        maker_info = trade.get('maker_info')
        if not isinstance(maker_info, dict):
            maker_info = {}
        base_token = trade.get('base_token')
        if not isinstance(base_token, dict):
            base_token = {}
        records.append({
            'wallet_address': address,
            'rank': index + 1,
            'tags': maker_info.get('tags') if isinstance(maker_info.get('tags'), list) else [],
            'amount_usd': trade.get('amount_usd'),
            'base_address': trade.get('base_address'),
            'token_symbol': base_token.get('symbol'),
            'side': trade.get('side'),
            'trade_timestamp': trade.get('timestamp'),
        })
    return records


def _discover_from_token_top_traders(
    current_by_address: dict[str, dict[str, Any]],
    fetcher: Any,
    *,
    chain: str,
    target: int,
    discovered_at: str,
) -> int:
    if not hasattr(fetcher, 'fetch_trending_tokens') or not hasattr(fetcher, 'fetch_token_top_traders'):
        return 0
    added = 0
    tokens = fetcher.fetch_trending_tokens(interval='24h', limit=20)
    for token in tokens:
        if len(current_by_address) >= target:
            break
        token_address = _token_address(token)
        if not token_address:
            continue
        try:
            smart_traders = fetcher.fetch_token_top_traders(
                token_address,
                limit=50,
                tag='smart_degen',
                order_by='profit',
                direction='desc',
            )
        except TypeError:
            smart_traders = []
        if smart_traders:
            smart_addresses = map_token_top_traders_to_wallet_addresses({'data': smart_traders})
            smart_wallet_records = [
                {
                    'wallet_address': address,
                    'token_address': token_address,
                    'rank': index + 1,
                    'tags': ['smart_degen', 'token_profit'],
                }
                for index, address in enumerate(smart_addresses)
            ]
            added += _merge_wallet_candidates(
                current_by_address,
                smart_wallet_records,
                chain=chain,
                source='gmgn_token_smart_degen_traders',
                discovered_at=discovered_at,
            )
        if len(current_by_address) >= target:
            break
        traders = fetcher.fetch_token_top_traders(token_address, limit=50)
        addresses = map_token_top_traders_to_wallet_addresses({'data': traders})
        wallet_records = [
            {'wallet_address': address, 'token_address': token_address, 'rank': index + 1}
            for index, address in enumerate(addresses)
        ]
        added += _merge_wallet_candidates(
            current_by_address,
            wallet_records,
            chain=chain,
            source='gmgn_token_top_traders',
            discovered_at=discovered_at,
        )
    return added


def _token_address(token: dict[str, Any]) -> str:
    for key in ('token_address', 'address', 'base_token_address', 'base_address', 'mint'):
        value = token.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    base_token = token.get('base_token')
    if isinstance(base_token, dict):
        for key in ('address', 'token_address', 'mint'):
            value = base_token.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ''


def _promoted_wallet(candidate: dict[str, Any], index: int) -> dict[str, Any]:
    address = str(candidate.get('wallet_address') or candidate.get('address') or '')
    stats = candidate.get('stats')
    if not isinstance(stats, dict):
        stats = {}
    return {
        'wallet_address': address,
        'label': f'leader_pool_{index}',
        'tags': candidate.get('tags') if isinstance(candidate.get('tags'), list) else ['leader_pool'],
        'total_score': candidate.get('total_score', 0),
        'grade': candidate.get('grade', ''),
        'copy_weight': 0.0,
        'copy_weight_percent': '0.0%',
        'mode': 'observe',
        'enabled': False,
        'risk_limits': {
            'max_single_trade_sol': 0.01,
            'max_daily_loss_sol': 0.03,
            'max_daily_trades': 3,
            'slippage_percent': 2.0,
            'stop_loss_percent': -40.0,
            'take_profit_steps': [
                {'price_change_percent': 100.0, 'sell_percent': 50.0},
                {'price_change_percent': 300.0, 'sell_percent': 50.0},
            ],
        },
        'stats_snapshot': {
            'total_trades': stats.get('total_trades'),
            'realized_profit': stats.get('realized_profit'),
            'winrate': stats.get('winrate'),
            'avg_holding_hours': stats.get('avg_holding_hours'),
            'period': stats.get('period'),
        },
        'dimension_scores': candidate.get('dimension_scores') if isinstance(candidate.get('dimension_scores'), dict) else {},
        'notes': 'Leader 池自动晋级；默认 observe 且暂停，需人工在跟单配置启用。',
    }


def _recalculate_copy_weights(config: dict[str, Any]) -> None:
    wallets = config.get('wallets', [])
    if not isinstance(wallets, list):
        return
    active = [
        wallet for wallet in wallets
        if isinstance(wallet, dict)
        and wallet.get('enabled') is not False
        and str(wallet.get('mode') or 'follow') != 'paused'
    ]
    score_sum = sum(max(0.0, float(wallet.get('total_score') or 0)) for wallet in active)
    for wallet in wallets:
        if not isinstance(wallet, dict):
            continue
        if wallet in active and score_sum > 0:
            weight = round(max(0.0, float(wallet.get('total_score') or 0)) / score_sum, 6)
        else:
            weight = 0.0
        wallet['copy_weight'] = weight
        wallet['copy_weight_percent'] = f'{weight * 100:.1f}%'
    config['weight_calculation'] = {
        'method': 'active_score_normalized',
        'description': '仅对启用且未 paused 的 leader 按 total_score 归一化；暂停 leader 权重为 0',
        'total_score_sum': round(score_sum, 2),
        'formula': 'active_wallet_weight = wallet_score / active_score_sum',
    }


def _dedupe_scored_records(records: list[object]) -> dict[str, dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        address = str(record.get('wallet_address') or record.get('address') or '').strip()
        if not address:
            continue
        existing = deduped.get(address.lower())
        if existing is None or float(record.get('total_score') or 0) >= float(existing.get('total_score') or 0):
            deduped[address.lower()] = {**record, 'wallet_address': address}
    return deduped


def _score_backtest_record(
    wallet: dict[str, Any],
    min_score: float,
    min_win_rate_percent: float,
    min_total_trades: int,
) -> dict[str, Any]:
    score = float(wallet.get('total_score') or 0)
    winrate = _stats_number(wallet, 'winrate')
    trades = int(_stats_number(wallet, 'total_trades'))
    realized_profit = _stats_number(wallet, 'realized_profit')
    sample_score = min(100.0, trades / max(1, min_total_trades) * 50.0)
    threshold_score = min(100.0, score / max(1.0, min_score) * 40.0)
    winrate_score = min(100.0, winrate / max(1.0, min_win_rate_percent) * 60.0)
    backtest_score = round((sample_score * 0.25) + (threshold_score * 0.35) + (winrate_score * 0.40), 2)
    return {
        'wallet_address': wallet.get('wallet_address') or '',
        'total_score': score,
        'grade': wallet.get('grade') or '',
        'winrate': winrate,
        'total_trades': trades,
        'realized_profit': realized_profit,
        'backtest_score': backtest_score,
        'passed': score >= min_score and winrate >= min_win_rate_percent and trades >= min_total_trades,
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'method': 'score_window_threshold_replay',
        'reason': f'评分 {score:.2f} / 胜率 {winrate:.2f}% / 样本 {trades}',
    }


def _stats_number(wallet: dict[str, Any], key: str) -> float:
    stats = wallet.get('stats')
    if not isinstance(stats, dict):
        stats = wallet.get('stats_snapshot')
    if not isinstance(stats, dict):
        stats = {}
    value = stats.get(key)
    if value is None and key == 'realized_profit':
        value = wallet.get('realized_profit')
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _dedupe_candidates(records: list[object]) -> dict[str, dict[str, Any]]:
    deduped: dict[str, dict[str, Any]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        address = str(record.get('wallet_address') or record.get('address') or '').strip()
        if not address:
            continue
        deduped[address.lower()] = {**record, 'address': address, 'wallet_address': address}
    return deduped


def _read_json_list(path: Path) -> list[object]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return []
    return data if isinstance(data, list) else []


def _read_json_object(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_json_list(path: Path, records: list[dict[str, Any]]) -> None:
    atomic_write_text(json.dumps(records, ensure_ascii=False, indent=2) + '\n', path)


def _action_result(action: str, ok: bool, message: str) -> dict[str, object]:
    return {
        'action': action,
        'ok': ok,
        'message': message,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }


def _write_action_result(root: Path, result: dict[str, object]) -> None:
    atomic_write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + '\n',
        root / 'data' / 'leader_pool_last_action.json',
    )
