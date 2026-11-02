from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from gmgn_monitor.leader_pool import screen_qualified_leaders


def _healthy(address: str, *, trades_7d: int = 40, trades_30d: int = 160, win_rate: float = 72) -> dict[str, object]:
    return {
        'wallet_address': address,
        'total_profit': 60000,
        'win_rate': win_rate,
        'buy': trades_30d // 2,
        'sell': trades_30d - trades_30d // 2,
        'trades_7d': trades_7d,
        'trades_30d': trades_30d,
        'avg_holding_time': 30,
        'pnl_30d': 20000,
        'max_drawdown': 18,
    }


class FakeStatsFetcher:
    def __init__(self, stats_by_period: dict[str, dict[str, dict[str, object]]], profits=None):
        self.stats_by_period = stats_by_period
        self.profits = profits
        self.calls: list[tuple[str, str]] = []

    def fetch_wallet_stats(self, addresses, period='7d'):
        address = addresses[0]
        self.calls.append((address, period))
        stats = self.stats_by_period.get(period, {}).get(address)
        if stats is None:
            return {}
        return {address: stats}

    def fetch_wallet_profits(self, addresses, period='7d'):
        if self.profits is None:
            raise AssertionError('profits were not expected')
        return {
            address: self.profits[period][address]
            for address in addresses
            if address in self.profits.get(period, {})
        }


class LeaderScreenTest(unittest.TestCase):
    def test_qualified_leader_becomes_enabled_follow(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'trade_mode': 'paper',
                'wallets': [{
                    'wallet_address': 'LeaderA',
                    'label': 'alpha',
                    'enabled': False,
                    'mode': 'observe',
                    'total_score': 10,
                    'grade': 'E',
                    'risk_limits': {'max_single_trade_sol': 0.01},
                }],
            }), encoding='utf-8')
            (root / 'data/watchlist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'total_score': 10},
            ]), encoding='utf-8')
            fetcher = FakeStatsFetcher({
                '7d': {'LeaderA': {**_healthy('LeaderA'), 'buy': 20, 'sell': 20}},
                '30d': {'LeaderA': _healthy('LeaderA')},
            })

            result = screen_qualified_leaders(root, fetcher=fetcher, pause_seconds=0)

            saved = json.loads((root / 'config/wallet_whitelist.json').read_text(encoding='utf-8'))
            report = json.loads((root / 'data/qualified_leaders.json').read_text(encoding='utf-8'))
            watchlist = json.loads((root / 'data/watchlist_wallets.json').read_text(encoding='utf-8'))
            wallet = saved['wallets'][0]

        self.assertTrue(result['ok'])
        self.assertEqual(result['follow_count'], 1)
        self.assertEqual(saved['trade_mode'], 'paper')
        self.assertEqual(wallet['label'], 'alpha')
        self.assertEqual(wallet['mode'], 'follow')
        self.assertTrue(wallet['enabled'])
        self.assertGreaterEqual(float(wallet['total_score']), 65)
        self.assertEqual(wallet['stats_snapshot']['trades_7d'], 40)
        self.assertEqual(wallet['risk_limits']['max_single_trade_sol'], 0.01)
        self.assertEqual(report['qualified_count'], 1)
        self.assertEqual(watchlist, [])
        self.assertEqual(fetcher.calls, [('LeaderA', '7d'), ('LeaderA', '30d')])

    def test_quiet_and_low_win_rate_leaders_stay_off_the_follow_list(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'trade_mode': 'paper',
                'wallets': [
                    {'wallet_address': 'Quiet', 'label': 'quiet', 'enabled': True, 'mode': 'follow', 'total_score': 80},
                    {'wallet_address': 'CoinFlip', 'label': 'flip', 'enabled': True, 'mode': 'follow', 'total_score': 80},
                ],
            }), encoding='utf-8')
            fetcher = FakeStatsFetcher({
                '7d': {
                    'Quiet': {**_healthy('Quiet', trades_7d=2), 'buy': 1, 'sell': 1},
                    'CoinFlip': {**_healthy('CoinFlip', win_rate=55), 'buy': 20, 'sell': 20},
                },
                '30d': {
                    'Quiet': _healthy('Quiet', trades_7d=2),
                    'CoinFlip': _healthy('CoinFlip', win_rate=55),
                },
            })

            result = screen_qualified_leaders(root, fetcher=fetcher)

            saved = json.loads((root / 'config/wallet_whitelist.json').read_text(encoding='utf-8'))
            report = json.loads((root / 'data/qualified_leaders.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['qualified_count'], 0)
        self.assertEqual(saved['wallets'][0]['enabled'], False)
        self.assertEqual(saved['wallets'][0]['mode'], 'observe')
        self.assertEqual(saved['wallets'][1]['enabled'], False)
        self.assertEqual({row['wallet_address'] for row in report['wallets'] if row['qualified']}, set())

    def test_missing_stats_do_not_rewrite_the_follow_list(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            original = {
                'trade_mode': 'paper',
                'wallets': [{
                    'wallet_address': 'LeaderA',
                    'enabled': False,
                    'mode': 'follow',
                    'total_score': 62.49,
                }],
            }
            (root / 'config/wallet_whitelist.json').write_text(json.dumps(original), encoding='utf-8')

            result = screen_qualified_leaders(root, fetcher=FakeStatsFetcher({}))
            saved = json.loads((root / 'config/wallet_whitelist.json').read_text(encoding='utf-8'))

        self.assertFalse(result['ok'])
        self.assertEqual(saved['wallets'][0]['total_score'], 62.49)
        self.assertEqual(saved['wallets'][0]['mode'], 'follow')

    def test_profit_prefilter_skips_inactive_candidates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'trade_mode': 'paper',
                'wallets': [],
            }), encoding='utf-8')
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'wallet_address': 'Dead', 'source': 'gmgn_smartmoney'},
                {'wallet_address': 'Live', 'source': 'gmgn_track_smartmoney'},
            ]), encoding='utf-8')
            fetcher = FakeStatsFetcher(
                {
                    '7d': {'Live': {**_healthy('Live'), 'buy': 20, 'sell': 20}},
                    '30d': {'Live': _healthy('Live')},
                },
                profits={
                    '7d': {
                        'Dead': {'wallet_address': 'Dead', 'buy': 0, 'sell': 0, 'realized_profit': '0'},
                        'Live': {'wallet_address': 'Live', 'buy': 20, 'sell': 20, 'realized_profit': '1000'},
                    },
                    '30d': {
                        'Dead': {'wallet_address': 'Dead', 'buy': 1, 'sell': 1, 'realized_profit': '10'},
                        'Live': {'wallet_address': 'Live', 'buy': 80, 'sell': 80, 'realized_profit': '60000'},
                    },
                },
            )

            result = screen_qualified_leaders(root, fetcher=fetcher, stats_limit=5)
            saved = json.loads((root / 'config/wallet_whitelist.json').read_text(encoding='utf-8'))

        self.assertEqual(result['qualified_count'], 1)
        self.assertEqual([call[0] for call in fetcher.calls], ['Live', 'Live'])
        self.assertEqual(saved['wallets'][0]['wallet_address'], 'Live')
        self.assertEqual(saved['wallets'][0]['label'], 'qualified_1')
        self.assertTrue(saved['wallets'][0]['enabled'])
        self.assertEqual(saved['trade_mode'], 'paper')


if __name__ == '__main__':
    unittest.main()
