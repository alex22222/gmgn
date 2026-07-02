from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from math import isfinite
from pathlib import Path
from urllib.error import URLError
from urllib.parse import urlencode
from urllib.request import urlopen

from .file_io import atomic_write_jsonl
from .serialization import load_json


DEXSCREENER_SEARCH_URL = 'https://api.dexscreener.com/latest/dex/search'


class DexScreenerSearchSource:
    def __init__(self, query: str, limit: int = 20):
        self.query = _validate_query(query)
        self.limit = _validate_limit(limit)

    def load(self):
        payload = fetch_search_payload(self.query)
        for pair in _pairs_from_payload(payload, self.limit):
            yield map_pair_to_candidate(pair)


class DexScreenerPayloadSource:
    def __init__(self, path: Path, limit: int = 20):
        self.path = path
        self.limit = _validate_limit(limit)

    def load(self):
        payload = load_json(self.path, label='DEX Screener')
        for pair in _pairs_from_payload(payload, self.limit):
            yield map_pair_to_candidate(pair)


def fetch_search_payload(query: str) -> dict:
    url = f'{DEXSCREENER_SEARCH_URL}?{urlencode({"q": query})}'
    with urlopen(url, timeout=15) as response:
        try:
            return json.loads(response.read().decode('utf-8'))
        except UnicodeDecodeError as exc:
            raise ValueError(f'invalid DEX Screener response UTF-8: {exc.reason}') from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f'invalid DEX Screener response JSON at line {exc.lineno}: {exc.msg}') from exc


def _validate_limit(limit: int) -> int:
    if isinstance(limit, bool) or not isinstance(limit, int):
        raise ValueError('DEX Screener limit must be an integer')
    if limit <= 0:
        raise ValueError('DEX Screener limit must be greater than 0')
    return limit


def _validate_query(query: str) -> str:
    if not isinstance(query, str) or not query.strip():
        raise ValueError('DEX Screener query must be a non-empty string')
    return query.strip()


def _pairs_from_payload(payload: dict, limit: int) -> list[dict]:
    if not isinstance(payload, dict):
        raise ValueError('DEX Screener payload must be an object')
    pairs = payload.get('pairs', [])
    if not isinstance(pairs, list):
        raise ValueError('DEX Screener pairs must be a list')
    for index, pair in enumerate(pairs[:limit], start=1):
        if not isinstance(pair, dict):
            raise ValueError(f'DEX Screener pair {index} must be an object')
    return pairs[:limit]


def map_pair_to_candidate(pair: dict) -> dict:
    base_token = _object_value(pair.get('baseToken'))
    chain = _string_value(pair.get('chainId'), 'unknown')
    token_address = _string_value(base_token.get('address'), _string_value(pair.get('pairAddress'), 'unknown'))
    symbol = _string_value(base_token.get('symbol'), 'UNKNOWN')
    liquidity = _nested_number(pair, ('liquidity', 'usd'))
    volume_5m = _nested_number(pair, ('volume', 'm5'))
    tx_count_5m = _tx_count(pair)

    return {
        'chain': chain,
        'token_address': token_address,
        'symbol': symbol,
        'detected_at': datetime.now(UTC).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'source': 'dexscreener:search',
        'liquidity': liquidity,
        'market_cap': _number(pair.get('fdv')),
        'volume_1m': 0.0,
        'volume_5m': volume_5m,
        'tx_count_1m': tx_count_5m,
        'holder_count': 0,
        'top10_holder_percent': 100.0,
        'dev_holding_percent': 100.0,
        'insider_or_rat_percent': 100.0,
        'bundle_buy_percent': 100.0,
        'mint_renounced': False,
        'freeze_renounced': False,
        'lp_burned_or_locked': False,
        'honeypot_risk': True,
        'blacklist_risk': True,
        'tax_risk': True,
    }


def write_jsonl(records, output_path: Path) -> None:
    atomic_write_jsonl(list(records), output_path)


def _tx_count(pair: dict) -> float:
    txns = _object_value(pair.get('txns'))
    m5 = _object_value(txns.get('m5'))
    return _count_number(m5.get('buys')) + _count_number(m5.get('sells'))


def _nested_number(data: dict, path: tuple[str, str]) -> float:
    current = data
    for key in path:
        current = _object_value(current).get(key)
    return _number(current)


def _object_value(value) -> dict:
    if isinstance(value, dict):
        return value
    return {}


def _string_value(value, fallback: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return fallback


def _number(value) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)) and isfinite(value) and value >= 0:
        return float(value)
    return 0.0


def _count_number(value) -> float:
    number = _number(value)
    if not number.is_integer():
        return 0.0
    return number


def main() -> int:
    parser = argparse.ArgumentParser(description='Fetch DEX Screener search results as monitor-only candidate fixtures.')
    parser.add_argument('--query')
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--output', type=Path, default=Path('data/dexscreener_candidates.jsonl'))
    parser.add_argument('--payload', type=Path, help='Use a saved DEX Screener JSON payload instead of live network fetch.')
    args = parser.parse_args()

    try:
        source = DexScreenerPayloadSource(args.payload, args.limit) if args.payload else DexScreenerSearchSource(args.query, args.limit)
        records = list(source.load())
    except URLError as exc:
        print(f'failed to fetch DEX Screener data: {exc}', file=sys.stderr)
        return 2
    except ValueError as exc:
        print(f'invalid DEX Screener data: {exc}', file=sys.stderr)
        return 2
    except OSError as exc:
        print(f'failed to read DEX Screener data: {exc}', file=sys.stderr)
        return 2
    try:
        write_jsonl(records, args.output)
    except OSError as exc:
        print(f'failed to write DEX Screener data: {exc}', file=sys.stderr)
        return 2
    print(f'wrote {len(records)} read-only candidates to {args.output}')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
