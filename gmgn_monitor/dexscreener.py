from __future__ import annotations

import argparse
import json
import ssl
import sys
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from urllib.error import URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from .file_io import atomic_write_jsonl
from .serialization import load_json


DEXSCREENER_SEARCH_URL = 'https://api.dexscreener.com/latest/dex/search'
DEXSCREENER_TOKEN_PROFILES_URL = 'https://api.dexscreener.com/token-profiles/latest/v1'
DEXSCREENER_TOKENS_URL = 'https://api.dexscreener.com/tokens/v1/{chain_id}/{token_addresses}'
USER_AGENT = 'gmgn-monitor/0.1 read-only'


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


class DexScreenerLatestProfilesSource:
    def __init__(self, limit: int = 20):
        self.limit = _validate_limit(limit)

    def load(self):
        profiles = _profiles_from_payload(fetch_token_profiles_payload(), self.limit)
        pairs_by_token = _fetch_pairs_by_profile_token(profiles)
        for profile in profiles:
            chain_id = _string_value(profile.get('chainId'), 'unknown')
            token_address = _string_value(profile.get('tokenAddress'), 'unknown')
            pair = pairs_by_token.get((chain_id, token_address))
            if pair:
                yield map_pair_to_candidate(pair, source='dexscreener:token-profiles')
            else:
                yield map_profile_to_candidate(profile)


def fetch_search_payload(query: str) -> dict:
    url = f'{DEXSCREENER_SEARCH_URL}?{urlencode({"q": query})}'
    return _fetch_json_url(url, label='DEX Screener response')


def fetch_token_profiles_payload() -> list:
    return _fetch_json_url(DEXSCREENER_TOKEN_PROFILES_URL, label='DEX Screener token profiles response')


def fetch_tokens_payload(chain_id: str, token_addresses: list[str]) -> list:
    url = DEXSCREENER_TOKENS_URL.format(
        chain_id=quote(chain_id, safe=''),
        token_addresses=quote(','.join(token_addresses), safe=','),
    )
    return _fetch_json_url(url, label='DEX Screener tokens response')


def _fetch_json_url(url: str, label: str):
    context = _tls_context()
    kwargs = {'timeout': 15}
    if context is not None:
        kwargs['context'] = context
    request = Request(url, headers={'User-Agent': USER_AGENT})
    with urlopen(request, **kwargs) as response:
        try:
            return json.loads(response.read().decode('utf-8'))
        except UnicodeDecodeError as exc:
            raise ValueError(f'invalid {label} UTF-8: {exc.reason}') from exc
        except json.JSONDecodeError as exc:
            raise ValueError(f'invalid {label} JSON at line {exc.lineno}: {exc.msg}') from exc


def _tls_context():
    default_cafile = ssl.get_default_verify_paths().cafile
    if default_cafile and Path(default_cafile).exists():
        return None
    try:
        import certifi
    except ImportError:
        return None
    return ssl.create_default_context(cafile=certifi.where())


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


def _profiles_from_payload(payload: list, limit: int) -> list[dict]:
    if not isinstance(payload, list):
        raise ValueError('DEX Screener token profiles payload must be a list')
    profiles = []
    for index, profile in enumerate(payload[:limit], start=1):
        if not isinstance(profile, dict):
            raise ValueError(f'DEX Screener token profile {index} must be an object')
        profiles.append(profile)
    return profiles


def _fetch_pairs_by_profile_token(profiles: list[dict]) -> dict[tuple[str, str], dict]:
    requested_by_chain: dict[str, list[str]] = {}
    for profile in profiles:
        chain_id = _string_value(profile.get('chainId'), '')
        token_address = _string_value(profile.get('tokenAddress'), '')
        if not chain_id or not token_address:
            continue
        requested_by_chain.setdefault(chain_id, [])
        if token_address not in requested_by_chain[chain_id]:
            requested_by_chain[chain_id].append(token_address)

    pairs_by_token = {}
    for chain_id, token_addresses in requested_by_chain.items():
        for chunk in _chunks(token_addresses, 30):
            payload = fetch_tokens_payload(chain_id, chunk)
            for pair in _token_pairs_from_payload(payload):
                token_address = _pair_token_address(pair)
                if token_address and (chain_id, token_address) not in pairs_by_token:
                    pairs_by_token[(chain_id, token_address)] = pair
    return pairs_by_token


def _chunks(values: list[str], size: int):
    for index in range(0, len(values), size):
        yield values[index:index + size]


def _token_pairs_from_payload(payload: list) -> list[dict]:
    if not isinstance(payload, list):
        raise ValueError('DEX Screener tokens payload must be a list')
    pairs = []
    for index, pair in enumerate(payload, start=1):
        if not isinstance(pair, dict):
            raise ValueError(f'DEX Screener token pair {index} must be an object')
        pairs.append(pair)
    return pairs


def _pair_token_address(pair: dict) -> str:
    base_token = _object_value(pair.get('baseToken'))
    return _string_value(base_token.get('address'), '')


def map_profile_to_candidate(profile: dict) -> dict:
    return {
        'chain': _string_value(profile.get('chainId'), 'unknown'),
        'token_address': _string_value(profile.get('tokenAddress'), 'unknown'),
        'symbol': 'UNKNOWN',
        'detected_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'source': 'dexscreener:token-profiles',
        'liquidity': 0.0,
        'market_cap': 0.0,
        'volume_1m': 0.0,
        'volume_5m': 0.0,
        'tx_count_1m': 0.0,
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


def map_pair_to_candidate(pair: dict, source: str = 'dexscreener:search') -> dict:
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
        'detected_at': datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z'),
        'source': source,
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
    parser.add_argument('--latest-profiles', action='store_true', help='Fetch latest DEX Screener token profiles, then enrich market fields from token pairs.')
    args = parser.parse_args()

    try:
        if args.payload:
            source = DexScreenerPayloadSource(args.payload, args.limit)
        elif args.latest_profiles:
            source = DexScreenerLatestProfilesSource(args.limit)
        else:
            source = DexScreenerSearchSource(args.query, args.limit)
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
