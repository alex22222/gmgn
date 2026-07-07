import json
import os
import socket
import subprocess
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.dashboard import (
    ACTIONS,
    ACTION_LOCK,
    DashboardHandler,
    INDEX_HTML,
    _execute_sell,
    _get_portfolio_data,
    _read_leader_pool_state,
    _read_automation_gate_state,
    _read_copy_trading_config,
    _run_auto_stop_loss_once,
    _run_whitelist_score_refresh_once,
    _start_whitelist_score_monitor,
    _liquidate_leader_positions,
    _promote_single_leader_to_copy_whitelist,
    _recycle_scored_leader_to_candidates,
    _set_automation_gate_enabled,
    _set_leader_enabled,
    _run_leader_pool_action,
    _update_leader_pool_config,
    _update_token_exit_config,
    _update_leader_trading_params,
    build_action_command,
    build_dashboard_payload,
    find_available_port,
    main,
    make_handler,
    run_action,
)
from gmgn_monitor.leader_pool import backtest_leaders, discover_leaders, promote_leaders, score_leaders
import gmgn_monitor.leader_pool as leader_pool_module


class FakeLeaderFetcher:
    def __init__(self, wallets=None, stats_by_period=None, trending_tokens=None, token_traders=None, smartmoney_trades=None, kol_trades=None, market_signal_wallets=None):
        self.wallets = wallets or []
        self.stats_by_period = stats_by_period or {}
        self.trending_tokens = trending_tokens or []
        self.token_traders = token_traders or {}
        self.smartmoney_trades = smartmoney_trades or []
        self.kol_trades = kol_trades or []
        self.market_signal_wallets = market_signal_wallets or []
        self.wallet_stats_calls = []

    def fetch_smartmoney_wallets(self, limit=100):
        return self.wallets[:limit]

    def fetch_wallet_stats(self, addresses, period='7d'):
        self.wallet_stats_calls.append((tuple(addresses), period))
        period_stats = self.stats_by_period.get(period, {})
        return {
            address: period_stats[address]
            for address in addresses
            if address in period_stats
        }

    def fetch_trending_tokens(self, interval='24h', limit=20):
        return self.trending_tokens[:limit]

    def fetch_token_top_traders(self, token_address, limit=50, tag=None, order_by=None, direction=None):
        tagged_key = (token_address, tag, order_by, direction)
        if tag:
            return self.token_traders.get(tagged_key, [])[:limit]
        return self.token_traders.get(token_address, [])[:limit]

    def fetch_smartmoney_trades(self, limit=200, side='buy'):
        return self.smartmoney_trades[:limit]

    def fetch_kol_trades(self, limit=100, side='buy'):
        return self.kol_trades[:limit]

    def fetch_market_signal_wallets(self, signal_type=12, limit=50):
        return self.market_signal_wallets[:limit]


class DashboardTest(unittest.TestCase):
    def test_action_commands_are_whitelisted_python_modules(self):
        command = build_action_command('status')

        self.assertEqual(command[1:3], ['-m', 'gmgn_monitor.status'])
        self.assertIn('status', ACTIONS)

        with self.assertRaises(ValueError):
            build_action_command('rm -rf')

    def test_find_available_port_skips_used_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as used:
            used.bind(('127.0.0.1', 0))
            used.listen()
            occupied_port = used.getsockname()[1]

            port = find_available_port('127.0.0.1', occupied_port, occupied_port + 2)

        self.assertNotEqual(port, occupied_port)

    def test_dashboard_main_reports_start_failure_without_traceback(self):
        stderr = StringIO()
        with patch.object(sys, 'argv', ['dashboard']), \
                patch('sys.stderr', stderr), \
                patch('gmgn_monitor.dashboard.serve', side_effect=OSError('no available port')):
            code = main()

        self.assertEqual(code, 2)
        self.assertIn('failed to start GMGN dashboard: no available port', stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())

    def test_dashboard_payload_includes_status_actions_and_outputs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'fixtures/candidates.jsonl').write_text('{"symbol":"A"}\n{"symbol":"B"}\n', encoding='utf-8')
            (root / 'data/pipeline/daily_summary.md').write_text('# Summary\n', encoding='utf-8')

            payload = build_dashboard_payload(root)

        self.assertIn('status', payload)
        self.assertIn('actions', payload)
        self.assertEqual(payload['actions'][0]['label'], '刷新状态')
        self.assertEqual(payload['data_sources'][0]['name'], '本地 JSONL 候选数据')
        self.assertEqual(payload['data_sources'][0]['health'], '可用，2 条记录')
        self.assertEqual(payload['signals_summary']['total'], 0)
        self.assertIn('portfolio', payload)
        self.assertIn('leader_pool', payload)
        self.assertIn('audit_report', payload)
        self.assertEqual(payload['audit_report']['total'], 0)
        self.assertFalse(payload['portfolio']['ok'])
        self.assertIn('未接入真实钱包数据', payload['portfolio']['notice'])
        self.assertEqual(payload['user_flow'][0]['action'], '刷新状态')
        self.assertEqual(payload['outputs']['daily_summary']['content'], '# Summary\n')

    def test_dashboard_portfolio_reads_local_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir(parents=True)
            (root / 'config').mkdir()
            (root / 'config/risk_limits.json').write_text('{"max_total_positions":3}', encoding='utf-8')
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [{
                    'wallet_address': 'Leader111111111111111111111111111111111111',
                    'label': 'alpha',
                    'enabled': True,
                }],
            }), encoding='utf-8')
            (root / 'data/portfolio_snapshot.json').write_text(json.dumps({
                'timestamp': '2026-07-04T00:00:00+00:00',
                'total_value_sol': 10.2,
                'available_sol': 9.7,
                'daily_pnl_sol': 0.1,
                'max_drawdown_percent': 1.5,
                'positions': [{
                    'token_address': 'Token111111111111111111111111111111111111',
                    'symbol': 'TOK',
                    'source_wallet': 'Leader111111111111111111111111111111111111',
                    'entry_price_sol': 0.01,
                    'current_price_sol': 0.02,
                    'quantity': 10,
                }],
            }), encoding='utf-8')

            portfolio = _get_portfolio_data(root)

        self.assertTrue(portfolio['ok'])
        self.assertEqual(portfolio['summary']['open_positions'], 1)
        self.assertEqual(portfolio['summary']['max_positions'], 3)
        self.assertEqual(portfolio['positions'][0]['symbol'], 'TOK')
        self.assertEqual(portfolio['positions'][0]['copy_source_wallet'], 'Leader111111111111111111111111111111111111')
        self.assertEqual(portfolio['positions'][0]['copy_source_label'], 'alpha')
        self.assertTrue(portfolio['positions'][0]['copy_source_enabled'])
        self.assertFalse(portfolio['positions'][0]['copy_source_inferred'])
        self.assertEqual(portfolio['positions'][0]['value_sol'], 0.2)

    def test_dashboard_portfolio_does_not_fallback_to_dryrun_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir(parents=True)
            (root / 'config').mkdir()
            (root / 'data/live_dryrun_results.json').write_text(json.dumps({
                'simulation_result': {
                    'portfolio_snapshot': {
                        'total_value_sol': 10,
                        'available_sol': 10,
                        'positions': [],
                    },
                },
            }), encoding='utf-8')

            with patch.dict(os.environ, {}, clear=True):
                portfolio = _get_portfolio_data(root)

        self.assertFalse(portfolio['ok'])
        self.assertEqual(portfolio['source'], 'not_configured')
        self.assertEqual(portfolio['summary']['total_value_sol'], 0.0)
        self.assertIn('不再读取 dry-run 模拟快照', portfolio['notice'])

    def test_dashboard_portfolio_infers_copy_source_from_whitelist_holdings(self):
        leader_holdings = {
            'list': [{
                'token': {'address': 'Token111111111111111111111111111111111111', 'symbol': 'TOK'},
                'balance': 100,
                'usd_value': 2.0,
            }],
        }
        leader_completed = subprocess.CompletedProcess(
            args=['gmgn-cli'],
            returncode=0,
            stdout=json.dumps(leader_holdings),
            stderr='',
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir(parents=True)
            (root / 'config').mkdir()
            (root / 'config/risk_limits.json').write_text('{"max_total_positions":3}', encoding='utf-8')
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [{
                    'wallet_address': 'Leader111111111111111111111111111111111111',
                    'label': 'alpha',
                    'enabled': True,
                }],
            }), encoding='utf-8')
            (root / 'data/portfolio_snapshot.json').write_text(json.dumps({
                'positions': [{
                    'token_address': 'Token111111111111111111111111111111111111',
                    'symbol': 'TOK',
                    'entry_price_sol': 0.01,
                    'current_price_sol': 0.02,
                    'quantity': 10,
                }],
            }), encoding='utf-8')

            with patch.dict(os.environ, {}, clear=True), \
                    patch('gmgn_monitor.dashboard.shutil.which', return_value='/usr/local/bin/gmgn-cli'), \
                    patch('gmgn_monitor.dashboard.subprocess.run', return_value=leader_completed):
                portfolio = _get_portfolio_data(root)

        self.assertEqual(portfolio['positions'][0]['copy_source_wallet'], 'Leader111111111111111111111111111111111111')
        self.assertEqual(portfolio['positions'][0]['copy_source_label'], 'alpha')
        self.assertTrue(portfolio['positions'][0]['copy_source_inferred'])

    def test_dashboard_portfolio_infers_copy_source_from_successful_auto_buy_audit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir(parents=True)
            (root / 'config').mkdir()
            (root / 'config/risk_limits.json').write_text('{"max_total_positions":3}', encoding='utf-8')
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [],
            }), encoding='utf-8')
            (root / 'data/portfolio_snapshot.json').write_text(json.dumps({
                'positions': [{
                    'token_address': 'Token111111111111111111111111111111111111',
                    'symbol': 'TOK',
                    'entry_price_sol': 0.01,
                    'current_price_sol': 0.02,
                    'quantity': 10,
                }],
            }), encoding='utf-8')
            (root / 'data/audit_events.jsonl').write_text(json.dumps({
                'action': 'auto_buy',
                'success': True,
                'object_id': 'Token111111111111111111111111111111111111',
                'details': {
                    'signal': {
                        'target_token': 'Token111111111111111111111111111111111111',
                        'wallet_address': 'RemovedLeader111',
                    },
                },
            }) + '\n', encoding='utf-8')

            portfolio = _get_portfolio_data(root)

        self.assertEqual(portfolio['positions'][0]['copy_source_wallet'], 'RemovedLeader111')
        self.assertEqual(portfolio['positions'][0]['copy_source_label'], '')
        self.assertFalse(portfolio['positions'][0]['copy_source_inferred'])

    def test_dashboard_portfolio_reads_gmgn_cli_holdings_when_wallet_configured(self):
        holdings_payload = {
            'holdings': [{
                'token': {'address': 'Token111111111111111111111111111111111111', 'symbol': 'TOK', 'price': 0.25},
                'balance': 4,
                'usd_value': 1.0,
                'avg_cost': 0.1,
                'unrealized_profit': 0.6,
                'profit_change': 1.5,
                'last_active_timestamp': 1783210000,
            }],
        }
        info_payload = {
            'wallets': [{
                'chain': 'sol',
                'address': 'Wallet111111111111111111111111111111111111',
                'balances': [
                    {'symbol': 'SOL', 'balance': '0.1234'},
                ],
            }],
        }
        holdings_completed = subprocess.CompletedProcess(
            args=['gmgn-cli'],
            returncode=0,
            stdout=json.dumps(holdings_payload),
            stderr='',
        )
        info_completed = subprocess.CompletedProcess(
            args=['gmgn-cli'],
            returncode=0,
            stdout=json.dumps(info_payload),
            stderr='',
        )

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            with patch.dict(os.environ, {'GMGN_WALLET_ADDRESS': 'Wallet111111111111111111111111111111111111'}, clear=True), \
                    patch('gmgn_monitor.dashboard.shutil.which', return_value='/usr/local/bin/gmgn-cli'), \
                    patch('gmgn_monitor.dashboard.subprocess.run', side_effect=[holdings_completed, info_completed]) as run:
                portfolio = _get_portfolio_data(root)

        self.assertTrue(portfolio['ok'])
        self.assertEqual(portfolio['source'], 'gmgn-cli portfolio holdings')
        self.assertEqual(portfolio['notice'], '')
        self.assertEqual(portfolio['value_unit'], 'USD')
        self.assertEqual(portfolio['available_unit'], 'SOL')
        self.assertTrue(portfolio['has_available_balance'])
        self.assertFalse(portfolio['has_max_drawdown'])
        self.assertEqual(portfolio['summary']['total_value_sol'], 1.0)
        self.assertEqual(portfolio['summary']['available_sol'], 0.1234)
        self.assertEqual(portfolio['positions'][0]['symbol'], 'TOK')
        self.assertEqual(portfolio['positions'][0]['copy_source_wallet'], '')
        self.assertEqual(portfolio['positions'][0]['copy_source_label'], '')
        self.assertFalse(portfolio['positions'][0]['copy_source_inferred'])
        self.assertTrue(portfolio['positions'][0]['has_entry_price'])
        self.assertTrue(portfolio['positions'][0]['has_current_price'])
        self.assertEqual(portfolio['positions'][0]['entry_price_sol'], 0.1)
        self.assertEqual(portfolio['positions'][0]['current_price_sol'], 0.25)
        self.assertAlmostEqual(portfolio['positions'][0]['unrealized_pnl_percent'], 150.0)
        self.assertIn('--wallet', run.call_args_list[0].args[0])

    def test_leader_toggle_updates_wallet_whitelist(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'trade_mode': 'real',
                'exposure_level': 'tiny_real',
                'wallets': [
                    {
                        'wallet_address': 'Leader111',
                        'label': 'alpha',
                        'enabled': True,
                        'total_score': 80,
                    },
                    {
                        'wallet_address': 'Leader222',
                        'label': 'beta',
                        'enabled': False,
                        'total_score': 20,
                    },
                ],
            }), encoding='utf-8')

            result = _set_leader_enabled(root, 'Leader111', False)
            config = _read_copy_trading_config(root)

        self.assertTrue(result['ok'])
        self.assertFalse(config['wallets'][0]['enabled'])
        self.assertFalse(config['wallets'][1]['enabled'])
        self.assertEqual(config['wallets'][0]['copy_weight'], 0.0)
        self.assertEqual(config['wallets'][1]['copy_weight'], 0.0)
        self.assertEqual(config['enabled_wallet_count'], 0)
        self.assertEqual(config['wallet_count'], 2)
        self.assertEqual(config['exposure_level_label'], '微型真实')

    def test_leader_toggle_off_liquidates_positions_copied_from_leader(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [{
                    'wallet_address': 'Leader111',
                    'label': 'alpha',
                    'enabled': True,
                    'mode': 'follow',
                    'total_score': 80,
                }],
            }), encoding='utf-8')
            (root / 'data/portfolio_snapshot.json').write_text(json.dumps({
                'positions': [
                    {
                        'token_address': 'Token111',
                        'symbol': 'TOK',
                        'source_wallet': 'Leader111',
                        'quantity': 10,
                        'value_sol': 1.0,
                    },
                    {
                        'token_address': 'Token222',
                        'symbol': 'KEEP',
                        'source_wallet': 'Leader222',
                        'quantity': 5,
                        'value_sol': 0.5,
                    },
                ],
            }), encoding='utf-8')

            with patch('gmgn_monitor.dashboard._execute_sell', return_value={
                'success': True,
                'tx_hash': 'tx-1',
                'order_id': 'order-1',
                'error_message': '',
            }) as sell:
                result = _set_leader_enabled(root, 'Leader111', False)
            audits = [
                json.loads(line)
                for line in (root / 'data/audit_events.jsonl').read_text(encoding='utf-8').splitlines()
            ]

        self.assertTrue(result['ok'])
        self.assertTrue(result['liquidation']['triggered'])
        self.assertEqual(result['liquidation']['matched_positions'], 1)
        sell.assert_called_once()
        payload = sell.call_args.args[1]
        self.assertEqual(payload['token_address'], 'Token111')
        self.assertEqual(payload['trigger_type'], 'LEADER_REMOVED')
        self.assertEqual(payload['leader_wallet_address'], 'Leader111')
        self.assertEqual(audits[-1]['action'], 'leader_removed_liquidation')
        self.assertEqual(audits[-1]['details']['matched_positions'], 1)

    def test_copy_trading_config_refreshes_whitelist_score_report_and_flags_low_scores(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'trade_mode': 'real',
                'exposure_level': 'tiny_real',
                'wallets': [
                    {
                        'wallet_address': 'LeaderHigh',
                        'label': 'alpha',
                        'total_score': 76.0,
                        'grade': 'B',
                        'enabled': True,
                    },
                    {
                        'wallet_address': 'LeaderLow',
                        'label': 'beta',
                        'total_score': 53.4,
                        'grade': 'D',
                        'enabled': True,
                    },
                ],
            }), encoding='utf-8')

            config = _read_copy_trading_config(root)
            report = json.loads((root / 'data/whitelist_score_report.json').read_text(encoding='utf-8'))

        self.assertEqual(config['score_report']['interval_hours'], 3)
        self.assertEqual(config['score_report']['low_score_count'], 1)
        self.assertEqual(config['wallets'][0]['score_status'], 'ok')
        self.assertEqual(config['wallets'][1]['score_status'], 'low')
        self.assertIn('评分偏低', config['wallets'][1]['score_warning'])
        self.assertEqual(report['interval_seconds'], 10800)
        self.assertEqual(report['low_score_count'], 1)

    def test_whitelist_score_refresh_once_writes_report_without_page_access(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [
                    {'wallet_address': 'LeaderHigh', 'total_score': 76.0, 'grade': 'B'},
                    {'wallet_address': 'LeaderLow', 'total_score': 53.4, 'grade': 'D'},
                ],
            }), encoding='utf-8')

            result = _run_whitelist_score_refresh_once(root)
            report = json.loads((root / 'data/whitelist_score_report.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['wallet_count'], 2)
        self.assertEqual(result['low_score_count'], 1)
        self.assertEqual(report['interval_seconds'], 10800)

    def test_whitelist_score_monitor_runs_in_background_and_logs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [
                    {'wallet_address': 'LeaderHigh', 'total_score': 76.0, 'grade': 'B'},
                ],
            }), encoding='utf-8')
            stop_event = threading.Event()

            with patch('gmgn_monitor.dashboard._WHITELIST_SCORE_INTERVAL_SECONDS', 0.01):
                thread = _start_whitelist_score_monitor(root, stop_event)
                log_path = root / 'data/trading_log.jsonl'
                for _ in range(100):
                    if log_path.exists() and 'whitelist_score_refresh' in log_path.read_text(encoding='utf-8'):
                        break
                    threading.Event().wait(0.01)
                stop_event.set()
                thread.join(timeout=1)

            log_content = log_path.read_text(encoding='utf-8')

        self.assertIn('whitelist_score_refresh', log_content)
        self.assertFalse(thread.is_alive())

    def test_copy_trading_config_auto_weights_active_leaders_and_zeroes_paused(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            config_path = root / 'config/wallet_whitelist.json'
            config_path.write_text(json.dumps({
                'wallets': [
                    {
                        'wallet_address': 'LeaderA',
                        'label': 'alpha',
                        'enabled': True,
                        'mode': 'follow',
                        'total_score': 80,
                        'copy_weight': 0.1,
                    },
                    {
                        'wallet_address': 'LeaderB',
                        'label': 'beta',
                        'enabled': True,
                        'mode': 'observe',
                        'total_score': 20,
                        'copy_weight': 0.1,
                    },
                    {
                        'wallet_address': 'LeaderPaused',
                        'label': 'paused',
                        'enabled': True,
                        'mode': 'paused',
                        'total_score': 100,
                        'copy_weight': 0.8,
                    },
                ],
            }), encoding='utf-8')

            config = _read_copy_trading_config(root)
            saved = json.loads(config_path.read_text(encoding='utf-8'))

        self.assertAlmostEqual(config['wallets'][0]['copy_weight'], 0.8)
        self.assertAlmostEqual(config['wallets'][1]['copy_weight'], 0.2)
        self.assertEqual(config['wallets'][2]['copy_weight'], 0.0)
        self.assertEqual(saved['wallets'][0]['copy_weight_percent'], '80.0%')
        self.assertEqual(saved['wallets'][1]['copy_weight_percent'], '20.0%')
        self.assertEqual(saved['wallets'][2]['copy_weight_percent'], '0.0%')
        self.assertEqual(saved['weight_calculation']['method'], 'active_score_normalized')

    def test_leader_pool_state_tracks_targets_quality_and_whitelist_progress(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'logs/loop').mkdir(parents=True)
            (root / 'config/leader_pool.json').write_text(json.dumps({
                'discovery_target': 5,
                'high_quality_target': 2,
                'whitelist_target': 2,
                'backtest_target': 3,
                'min_score': 65,
                'min_win_rate_percent': 60,
                'min_total_trades': 50,
                'score_batch_size': 50,
                'lookback_windows': ['7d', '14d', '30d'],
            }), encoding='utf-8')
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA', 'source': 'gmgn_token_top_traders'},
                {'address': 'LeaderB', 'source': 'gmgn_token_top_traders'},
                {'address': 'LeaderC', 'source': 'gmgn_market_signal_12'},
                {'address': 'LeaderA', 'source': 'gmgn_token_top_traders'},
            ]), encoding='utf-8')
            (root / 'data/whitelist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'source': 'gmgn_token_top_traders', 'total_score': 70, 'grade': 'B', 'decision': 'copy', 'stats': {'winrate': 65, 'total_trades': 100}},
                {'wallet_address': 'LeaderLow', 'source': 'gmgn_token_top_traders', 'total_score': 55, 'grade': 'D', 'decision': 'observe', 'stats': {'winrate': 80, 'total_trades': 100}},
            ]), encoding='utf-8')
            (root / 'data/watchlist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderB', 'source': 'gmgn_token_top_traders', 'total_score': 68, 'grade': 'C', 'decision': 'watch', 'stats': {'winrate': 61, 'total_trades': 80}},
            ]), encoding='utf-8')
            (root / 'data/blacklist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderRejected', 'source': 'gmgn_market_signal_12', 'total_score': 20, 'grade': 'F'},
            ]), encoding='utf-8')
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [{'wallet_address': 'LeaderA'}],
            }), encoding='utf-8')
            (root / 'data/leader_backtest_results.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA'},
                {'wallet_address': 'LeaderB'},
            ]), encoding='utf-8')

            state = _read_leader_pool_state(root)

        self.assertEqual(state['counts']['discovered'], 3)
        self.assertEqual(state['counts']['high_quality'], 2)
        self.assertEqual(state['counts']['whitelisted'], 1)
        self.assertEqual(state['stages'][0]['current'], 3)
        self.assertEqual(state['stages'][1]['target'], 2)
        self.assertEqual(state['stages'][3]['current'], 2)
        self.assertEqual(state['top_leaders'][0]['wallet_address'], 'LeaderA')
        self.assertEqual([stage['key'] for stage in state['funnel']], [
            'candidates',
            'rejected',
            'watch',
            'scored_whitelist',
            'copy_whitelist',
        ])
        self.assertEqual(state['funnel_lists']['candidates'][0]['wallet_address'], 'LeaderA')
        self.assertEqual(state['funnel'][1]['label'], '淘汰剩余名单')
        self.assertIn('遗留的剩余候选', state['funnel'][1]['note'])
        self.assertEqual(state['funnel_lists']['rejected'][0]['wallet_address'], 'LeaderC')
        self.assertNotIn('LeaderRejected', {item['wallet_address'] for item in state['funnel_lists']['rejected']})
        self.assertEqual(state['funnel_lists']['watch'][0]['wallet_address'], 'LeaderB')
        self.assertEqual(state['funnel_lists']['scored_whitelist'][0]['wallet_address'], 'LeaderA')
        self.assertEqual(state['funnel_lists']['copy_whitelist'][0]['wallet_address'], 'LeaderA')
        self.assertTrue(state['funnel_lists']['scored_whitelist'][0]['in_copy_whitelist'])
        self.assertEqual(state['copy_whitelist_limit'], 10)
        self.assertEqual(state['backtest']['count'], 2)
        source_quality = {item['source']: item for item in state['source_quality']}
        self.assertEqual(source_quality['gmgn_token_top_traders']['candidates'], 2)
        self.assertEqual(source_quality['gmgn_token_top_traders']['scored'], 3)
        self.assertEqual(source_quality['gmgn_token_top_traders']['high_quality'], 2)
        self.assertEqual(source_quality['gmgn_token_top_traders']['near_quality'], 1)
        self.assertEqual(source_quality['gmgn_market_signal_12']['rejected'], 1)
        self.assertEqual(
            {item['wallet_address'] for item in state['backtest']['leaders']},
            {'LeaderA', 'LeaderB'},
        )
        self.assertEqual(state['next_action']['action'], 'discover')
        self.assertIn('gmgn_api_key_configured', state['prerequisites'])

    def test_update_leader_pool_config_saves_targets_and_thresholds(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            result = _update_leader_pool_config(root, {
                'discovery_target': 500,
                'high_quality_target': 40,
                'whitelist_target': 10,
                'backtest_target': 10,
                'min_score': 70,
                'min_win_rate_percent': 62,
                'min_total_trades': 80,
                'score_batch_size': 25,
                'score_concurrency': 6,
                'lookback_windows': '7d,14d,30d',
            })
            saved = json.loads((root / 'config/leader_pool.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(saved['discovery_target'], 500)
        self.assertEqual(saved['high_quality_target'], 40)
        self.assertEqual(saved['whitelist_target'], 10)
        self.assertEqual(saved['score_batch_size'], 25)
        self.assertEqual(saved['score_concurrency'], 6)
        self.assertEqual(saved['lookback_windows'], ['7d', '14d', '30d'])

    def test_discover_leaders_merges_smartmoney_candidates(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir()
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
            ]), encoding='utf-8')
            fetcher = FakeLeaderFetcher(wallets=[
                {'wallet_address': 'LeaderA'},
                {'wallet_address': 'LeaderB', 'rank': 1},
                {'wallet_address': 'LeaderC', 'rank': 2},
            ])

            result = discover_leaders(root, target=3, fetcher=fetcher)
            saved = json.loads((root / 'data/candidate_wallets_smartmoney.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['added'], 2)
        self.assertEqual(len(saved), 3)
        self.assertEqual(saved[1]['source'], 'gmgn_smartmoney')

    def test_discover_leaders_falls_back_to_token_top_traders(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir()
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
            ]), encoding='utf-8')
            fetcher = FakeLeaderFetcher(
                wallets=[{'wallet_address': 'LeaderA'}],
                trending_tokens=[{'token_address': 'Token111'}],
                token_traders={'Token111': [{'wallet_address': 'LeaderB'}, {'wallet_address': 'LeaderC'}]},
            )

            result = discover_leaders(root, target=3, fetcher=fetcher)
            saved = json.loads((root / 'data/candidate_wallets_smartmoney.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['secondary_added'], 2)
        self.assertEqual(len(saved), 3)
        self.assertEqual(saved[-1]['source'], 'gmgn_token_top_traders')

    def test_discover_leaders_uses_token_smart_degen_traders_before_plain_top_traders(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir()
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
            ]), encoding='utf-8')
            fetcher = FakeLeaderFetcher(
                wallets=[{'wallet_address': 'LeaderA'}],
                trending_tokens=[{'token_address': 'Token111'}],
                token_traders={
                    ('Token111', 'smart_degen', 'profit', 'desc'): [{'wallet_address': 'SmartProfit'}],
                    'Token111': [{'wallet_address': 'PlainTrader'}],
                },
            )

            result = discover_leaders(root, target=3, fetcher=fetcher)
            saved = json.loads((root / 'data/candidate_wallets_smartmoney.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['secondary_added'], 2)
        self.assertEqual(saved[1]['wallet_address'], 'SmartProfit')
        self.assertEqual(saved[1]['source'], 'gmgn_token_smart_degen_traders')
        self.assertEqual(saved[1]['tags'], ['smart_degen', 'token_profit'])
        self.assertEqual(saved[2]['source'], 'gmgn_token_top_traders')

    def test_discover_leaders_uses_tracked_smartmoney_before_token_top_traders(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir()
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
            ]), encoding='utf-8')
            fetcher = FakeLeaderFetcher(
                wallets=[{'wallet_address': 'LeaderA'}],
                smartmoney_trades=[{
                    'maker': 'TrackedSmart',
                    'amount_usd': 1200,
                    'base_address': 'Token111',
                    'side': 'buy',
                    'timestamp': 1783222847,
                    'base_token': {'symbol': 'PUNK'},
                    'maker_info': {'tags': ['smart_degen', 'gmgn']},
                }],
                trending_tokens=[{'token_address': 'Token222'}],
                token_traders={'Token222': [{'wallet_address': 'TokenTrader'}]},
            )

            result = discover_leaders(root, target=3, fetcher=fetcher)
            saved = json.loads((root / 'data/candidate_wallets_smartmoney.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['tracked_added'], 1)
        self.assertEqual(result['secondary_added'], 1)
        self.assertEqual(saved[1]['wallet_address'], 'TrackedSmart')
        self.assertEqual(saved[1]['source'], 'gmgn_track_smartmoney')
        self.assertEqual(saved[1]['tags'], ['smart_degen', 'gmgn'])
        self.assertEqual(saved[1]['token_symbol'], 'PUNK')

    def test_discover_leaders_uses_market_signal_wallets_before_token_top_traders(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir()
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
            ]), encoding='utf-8')
            fetcher = FakeLeaderFetcher(
                wallets=[{'wallet_address': 'LeaderA'}],
                market_signal_wallets=[{
                    'wallet_address': 'SignalSmart',
                    'token_address': 'Token111',
                    'token_symbol': 'PUNK',
                    'signal_type': 12,
                    'signal_times': 3,
                    'signal_count': 2,
                    'buy_amount': 79.5,
                    'buy_timestamp': 1783229266,
                    'tags': ['smart_degen', 'market_signal_12'],
                }],
                smartmoney_trades=[{
                    'maker': 'TrackedSmart',
                    'amount_usd': 1200,
                    'base_address': 'Token222',
                    'side': 'buy',
                    'timestamp': 1783222847,
                    'base_token': {'symbol': 'TRACK'},
                    'maker_info': {'tags': ['smart_degen']},
                }],
                trending_tokens=[{'token_address': 'Token333'}],
                token_traders={'Token333': [{'wallet_address': 'TokenTrader'}]},
            )

            result = discover_leaders(root, target=4, fetcher=fetcher)
            saved = json.loads((root / 'data/candidate_wallets_smartmoney.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['market_signal_added'], 1)
        self.assertEqual(result['tracked_added'], 1)
        self.assertEqual(result['secondary_added'], 1)
        self.assertEqual(saved[1]['wallet_address'], 'TrackedSmart')
        self.assertEqual(saved[2]['wallet_address'], 'SignalSmart')
        self.assertEqual(saved[2]['source'], 'gmgn_market_signal_12')
        self.assertEqual(saved[2]['token_address'], 'Token111')
        self.assertEqual(saved[2]['token_symbol'], 'PUNK')
        self.assertEqual(saved[2]['signal_times'], 3)
        self.assertEqual(saved[2]['tags'], ['smart_degen', 'market_signal_12'])
        self.assertEqual(saved[3]['source'], 'gmgn_token_top_traders')

    def test_score_leaders_uses_best_lookback_window_and_writes_lists(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir()
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
                {'address': 'LeaderB'},
            ]), encoding='utf-8')
            fetcher = FakeLeaderFetcher(stats_by_period={
                '7d': {
                    'LeaderA': {
                        'wallet_address': 'LeaderA',
                        'total_profit': 30000,
                        'win_rate': 55,
                        'total_trades': 120,
                        'trades_7d': 40,
                        'trades_30d': 120,
                        'avg_holding_time': 24,
                        'pnl_30d': 12000,
                        'max_drawdown': 20,
                    },
                },
                '14d': {
                    'LeaderA': {
                        'wallet_address': 'LeaderA',
                        'total_profit': 60000,
                        'win_rate': 72,
                        'total_trades': 160,
                        'trades_7d': 50,
                        'trades_30d': 160,
                        'avg_holding_time': 30,
                        'pnl_30d': 20000,
                        'max_drawdown': 18,
                    },
                    'LeaderB': {
                        'wallet_address': 'LeaderB',
                        'total_profit': -100,
                        'win_rate': 20,
                        'total_trades': 30,
                        'trades_7d': 5,
                        'trades_30d': 30,
                        'avg_holding_time': 2,
                        'pnl_30d': -100,
                        'max_drawdown': 70,
                    },
                },
            })

            result = score_leaders(
                root,
                min_score=60,
                min_win_rate_percent=60,
                min_total_trades=50,
                lookback_windows=['7d', '14d'],
                score_batch_size=2,
                fetcher=fetcher,
            )
            whitelist = json.loads((root / 'data/whitelist_wallets.json').read_text(encoding='utf-8'))
            blacklist = json.loads((root / 'data/blacklist_wallets.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['high_quality_count'], 1)
        self.assertEqual(whitelist[0]['wallet_address'], 'LeaderA')
        self.assertEqual(whitelist[0]['stats']['period'], '14d')
        self.assertEqual(blacklist[0]['wallet_address'], 'LeaderB')

    def test_score_leaders_stops_window_fetching_after_high_quality_hit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir()
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
                {'address': 'LeaderB'},
            ]), encoding='utf-8')
            fetcher = FakeLeaderFetcher(stats_by_period={
                '7d': {
                    'LeaderA': {
                        'wallet_address': 'LeaderA',
                        'total_profit': 60000,
                        'win_rate': 72,
                        'total_trades': 160,
                        'trades_7d': 50,
                        'trades_30d': 160,
                        'avg_holding_time': 30,
                        'pnl_30d': 20000,
                        'max_drawdown': 18,
                    },
                    'LeaderB': {
                        'wallet_address': 'LeaderB',
                        'total_profit': -100,
                        'win_rate': 20,
                        'total_trades': 30,
                        'trades_7d': 5,
                        'trades_30d': 30,
                        'avg_holding_time': 2,
                        'pnl_30d': -100,
                        'max_drawdown': 70,
                    },
                },
                '14d': {
                    'LeaderA': {
                        'wallet_address': 'LeaderA',
                        'total_profit': 90000,
                        'win_rate': 80,
                        'total_trades': 220,
                    },
                    'LeaderB': {
                        'wallet_address': 'LeaderB',
                        'total_profit': -200,
                        'win_rate': 25,
                        'total_trades': 40,
                    },
                },
            })

            result = score_leaders(
                root,
                min_score=60,
                min_win_rate_percent=60,
                min_total_trades=50,
                lookback_windows=['7d', '14d'],
                score_batch_size=2,
                fetcher=fetcher,
            )
            whitelist = json.loads((root / 'data/whitelist_wallets.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(whitelist[0]['wallet_address'], 'LeaderA')
        self.assertEqual(whitelist[0]['stats']['period'], '7d')
        self.assertNotIn((('LeaderA',), '14d'), fetcher.wallet_stats_calls)

    def test_score_leaders_prioritizes_smartmoney_candidates_before_token_traders(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir()
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'TokenTraderLow', 'source': 'gmgn_token_top_traders', 'rank': 1},
                {
                    'address': 'SmartLeader',
                    'source': 'gmgn_smartmoney',
                    'tags': ['smart_degen'],
                    'volume_usd': 1000,
                    'trades': 20,
                },
            ]), encoding='utf-8')
            fetcher = FakeLeaderFetcher(stats_by_period={
                '7d': {
                    'SmartLeader': {
                        'wallet_address': 'SmartLeader',
                        'total_profit': 60000,
                        'win_rate': 72,
                        'total_trades': 160,
                        'trades_7d': 50,
                        'trades_30d': 160,
                        'avg_holding_time': 30,
                        'pnl_30d': 20000,
                        'max_drawdown': 18,
                    },
                },
            })

            result = score_leaders(
                root,
                min_score=60,
                min_win_rate_percent=60,
                min_total_trades=50,
                lookback_windows=['7d'],
                score_batch_size=1,
                fetcher=fetcher,
            )
            whitelist = json.loads((root / 'data/whitelist_wallets.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['scored_this_run'], 1)
        self.assertEqual(whitelist[0]['wallet_address'], 'SmartLeader')
        self.assertEqual(fetcher.wallet_stats_calls, [(('SmartLeader',), '7d')])

    def test_score_leaders_scores_incremental_batch_and_preserves_previous_records(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir()
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
                {'address': 'LeaderB'},
            ]), encoding='utf-8')
            (root / 'data/whitelist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'total_score': 75, 'grade': 'B', 'stats': {'winrate': 70, 'total_trades': 100}},
            ]), encoding='utf-8')
            fetcher = FakeLeaderFetcher(stats_by_period={
                '7d': {
                    'LeaderB': {
                        'wallet_address': 'LeaderB',
                        'total_profit': 60000,
                        'win_rate': 72,
                        'total_trades': 160,
                        'trades_7d': 50,
                        'trades_30d': 160,
                        'avg_holding_time': 30,
                        'pnl_30d': 20000,
                        'max_drawdown': 18,
                    },
                },
            })

            result = score_leaders(
                root,
                min_score=60,
                min_win_rate_percent=60,
                min_total_trades=50,
                lookback_windows=['7d'],
                score_batch_size=1,
                fetcher=fetcher,
            )
            whitelist = json.loads((root / 'data/whitelist_wallets.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['scored_this_run'], 1)
        self.assertEqual({wallet['wallet_address'] for wallet in whitelist}, {'LeaderA', 'LeaderB'})

    def test_run_leader_pool_action_records_missing_api_key(self):
        class EmptyConfig:
            gmgn_api_key = None

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()

            with patch.dict(os.environ, {'GMGN_API_KEY': ''}), \
                    patch.object(leader_pool_module, 'ConfigManager', return_value=EmptyConfig()):
                result = _run_leader_pool_action(root, {'action': 'discover'})
            last_action = json.loads((root / 'data/leader_pool_last_action.json').read_text(encoding='utf-8'))

        self.assertFalse(result['ok'])
        self.assertIn('GMGN_API_KEY', result['message'])
        self.assertEqual(last_action['action'], 'discover')

    def test_leader_pool_uses_config_manager_api_key_fallback(self):
        class FakeConfig:
            gmgn_api_key = 'file-key'

        with patch.dict(os.environ, {'GMGN_API_KEY': ''}), \
                patch.object(leader_pool_module, 'ConfigManager', return_value=FakeConfig()):
            fetcher = leader_pool_module._build_fetcher(chain='sol', api_key=None)

        self.assertIsNotNone(fetcher)

    def test_leader_pool_loop_once_records_blocker_for_missing_api_key(self):
        class EmptyConfig:
            gmgn_api_key = None

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/leader_pool.json').write_text(json.dumps({
                'discovery_target': 2,
                'high_quality_target': 1,
                'whitelist_target': 1,
                'backtest_target': 1,
            }), encoding='utf-8')
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
            ]), encoding='utf-8')

            with patch.dict(os.environ, {'GMGN_API_KEY': ''}), \
                    patch('gmgn_monitor.dashboard.ConfigManager', return_value=EmptyConfig()):
                result = _run_leader_pool_action(root, {'action': 'loop_once'})
            loop_state = json.loads((root / 'data/leader_pool_loop_state.json').read_text(encoding='utf-8'))

        self.assertFalse(result['ok'])
        self.assertEqual(result['selected_action'], 'discover')
        self.assertIn('GMGN_API_KEY', result['message'])
        self.assertEqual(loop_state['selected_action'], 'discover')

    def test_leader_pool_next_action_uses_config_manager_api_key_status(self):
        class FakeConfig:
            gmgn_api_key = 'file-key'

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/leader_pool.json').write_text(json.dumps({
                'discovery_target': 2,
                'high_quality_target': 1,
                'whitelist_target': 1,
                'backtest_target': 1,
            }), encoding='utf-8')
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
            ]), encoding='utf-8')

            with patch.dict(os.environ, {'GMGN_API_KEY': ''}), \
                    patch('gmgn_monitor.dashboard.ConfigManager', return_value=FakeConfig()):
                state = _read_leader_pool_state(root)

        self.assertTrue(state['prerequisites']['gmgn_api_key_configured'])
        self.assertFalse(state['next_action']['blocked'])

    def test_leader_pool_expands_candidates_when_scored_pool_quality_is_insufficient(self):
        class FakeConfig:
            gmgn_api_key = 'file-key'

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/leader_pool.json').write_text(json.dumps({
                'discovery_target': 2,
                'high_quality_target': 1,
                'whitelist_target': 1,
                'backtest_target': 1,
            }), encoding='utf-8')
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
                {'address': 'LeaderB'},
            ]), encoding='utf-8')
            (root / 'data/blacklist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'total_score': 10, 'stats': {'winrate': 20, 'total_trades': 10}},
                {'wallet_address': 'LeaderB', 'total_score': 12, 'stats': {'winrate': 25, 'total_trades': 12}},
            ]), encoding='utf-8')

            with patch.dict(os.environ, {'GMGN_API_KEY': ''}), \
                    patch('gmgn_monitor.dashboard.ConfigManager', return_value=FakeConfig()):
                state = _read_leader_pool_state(root)

        self.assertEqual(state['counts']['scored'], 2)
        self.assertEqual(state['next_action']['action'], 'discover')
        self.assertGreater(state['next_action']['target'], 2)
        self.assertEqual(state['quality_summary']['high_quality_hit_rate_percent'], 0.0)
        self.assertIn('继续扩池', state['next_action']['reason'])

    def test_leader_pool_expands_candidates_when_projected_quality_is_insufficient(self):
        class FakeConfig:
            gmgn_api_key = 'file-key'

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/leader_pool.json').write_text(json.dumps({
                'discovery_target': 500,
                'high_quality_target': 40,
                'whitelist_target': 10,
                'backtest_target': 10,
                'min_score': 65,
                'min_win_rate_percent': 60,
                'min_total_trades': 50,
            }), encoding='utf-8')
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': f'Leader{i}'}
                for i in range(500)
            ]), encoding='utf-8')
            (root / 'data/whitelist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'Leader0', 'total_score': 70, 'stats': {'winrate': 70, 'total_trades': 100}},
            ]), encoding='utf-8')
            (root / 'data/blacklist_wallets.json').write_text(json.dumps([
                {'wallet_address': f'Leader{i}', 'total_score': 10, 'stats': {'winrate': 20, 'total_trades': 10}}
                for i in range(1, 100)
            ]), encoding='utf-8')

            with patch.dict(os.environ, {'GMGN_API_KEY': ''}), \
                    patch('gmgn_monitor.dashboard.ConfigManager', return_value=FakeConfig()):
                state = _read_leader_pool_state(root)

        self.assertEqual(state['counts']['scored'], 100)
        self.assertEqual(state['next_action']['action'], 'discover')
        self.assertEqual(state['next_action']['target'], 1000)
        self.assertIn('命中率预计不足', state['next_action']['reason'])

    def test_leader_pool_scores_when_expansion_has_no_new_wallets(self):
        class FakeConfig:
            gmgn_api_key = 'file-key'

        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/leader_pool.json').write_text(json.dumps({
                'discovery_target': 500,
                'high_quality_target': 40,
                'whitelist_target': 10,
                'backtest_target': 10,
                'min_score': 65,
                'min_win_rate_percent': 60,
                'min_total_trades': 50,
            }), encoding='utf-8')
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': f'Leader{i}'}
                for i in range(500)
            ]), encoding='utf-8')
            (root / 'data/whitelist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'Leader0', 'total_score': 70, 'stats': {'winrate': 70, 'total_trades': 100}},
            ]), encoding='utf-8')
            (root / 'data/blacklist_wallets.json').write_text(json.dumps([
                {'wallet_address': f'Leader{i}', 'total_score': 10, 'stats': {'winrate': 20, 'total_trades': 10}}
                for i in range(1, 100)
            ]), encoding='utf-8')
            (root / 'data/leader_pool_last_action.json').write_text(json.dumps({
                'action': 'loop_once',
                'ok': True,
                'selected_action': 'discover',
                'result': {
                    'action': 'discover',
                    'ok': True,
                    'added': 0,
                },
            }), encoding='utf-8')

            with patch.dict(os.environ, {'GMGN_API_KEY': ''}), \
                    patch('gmgn_monitor.dashboard.ConfigManager', return_value=FakeConfig()):
                state = _read_leader_pool_state(root)

        self.assertEqual(state['next_action']['action'], 'score')
        self.assertIn('扩池无新增', state['next_action']['reason'])

    def test_promote_leaders_adds_high_quality_wallets_as_paused_observe(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [{'wallet_address': 'ExistingLeader', 'total_score': 80, 'enabled': True}],
            }), encoding='utf-8')
            (root / 'data/whitelist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'total_score': 75, 'grade': 'B', 'stats': {'winrate': 70, 'total_trades': 100, 'realized_profit': 1200}},
                {'wallet_address': 'LeaderLow', 'total_score': 50, 'grade': 'D', 'stats': {'winrate': 90, 'total_trades': 100}},
            ]), encoding='utf-8')

            result = promote_leaders(root, target=3, min_score=65, min_win_rate_percent=60, min_total_trades=50)
            saved = json.loads((root / 'config/wallet_whitelist.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['added'], 1)
        self.assertEqual(len(saved['wallets']), 2)
        promoted = saved['wallets'][1]
        self.assertEqual(promoted['wallet_address'], 'LeaderA')
        self.assertEqual(promoted['mode'], 'observe')
        self.assertFalse(promoted['enabled'])
        self.assertEqual(promoted['copy_weight'], 0.0)
        self.assertIn('weight_calculation', saved)

    def test_promote_single_leader_to_copy_whitelist_enforces_limit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [
                    {'wallet_address': f'Existing{i}', 'total_score': 80, 'enabled': True}
                    for i in range(10)
                ],
            }), encoding='utf-8')
            (root / 'data/whitelist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'total_score': 75, 'grade': 'B', 'stats': {'winrate': 70, 'total_trades': 100}},
            ]), encoding='utf-8')

            result = _promote_single_leader_to_copy_whitelist(root, {'wallet_address': 'LeaderA'})

        self.assertFalse(result['ok'])
        self.assertIn('最多 10 个', result['error'])

    def test_promote_single_leader_to_copy_whitelist_adds_scored_leader(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [{'wallet_address': 'ExistingLeader', 'total_score': 80, 'enabled': True}],
            }), encoding='utf-8')
            (root / 'data/whitelist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'total_score': 75, 'grade': 'B', 'stats': {'winrate': 70, 'total_trades': 100, 'realized_profit': 1200}},
            ]), encoding='utf-8')

            result = _promote_single_leader_to_copy_whitelist(root, {'wallet_address': 'LeaderA'})
            saved = json.loads((root / 'config/wallet_whitelist.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(len(saved['wallets']), 2)
        promoted = saved['wallets'][1]
        self.assertEqual(promoted['wallet_address'], 'LeaderA')
        self.assertEqual(promoted['mode'], 'observe')
        self.assertFalse(promoted['enabled'])
        self.assertEqual(promoted['copy_weight'], 0.0)

    def test_recycle_scored_leader_to_candidates_removes_whitelist_records(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'data/whitelist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'total_score': 75, 'grade': 'B', 'tags': ['gmgn']},
                {'wallet_address': 'LeaderB', 'total_score': 70, 'grade': 'B'},
            ]), encoding='utf-8')
            (root / 'data/candidate_wallets_smartmoney.json').write_text('[]', encoding='utf-8')
            (root / 'data/leader_backtest_results.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'backtest_score': 50},
            ]), encoding='utf-8')
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [{'wallet_address': 'LeaderA', 'total_score': 75, 'enabled': True}],
            }), encoding='utf-8')

            result = _recycle_scored_leader_to_candidates(root, {'wallet_address': 'LeaderA'})
            scored = json.loads((root / 'data/whitelist_wallets.json').read_text(encoding='utf-8'))
            candidates = json.loads((root / 'data/candidate_wallets_smartmoney.json').read_text(encoding='utf-8'))
            backtest = json.loads((root / 'data/leader_backtest_results.json').read_text(encoding='utf-8'))
            config = json.loads((root / 'config/wallet_whitelist.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual([item['wallet_address'] for item in scored], ['LeaderB'])
        self.assertEqual(candidates[0]['wallet_address'], 'LeaderA')
        self.assertEqual(backtest, [])
        self.assertEqual(config['wallets'], [])

    def test_backtest_leaders_includes_scored_and_configured_whitelist(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'data/whitelist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'total_score': 75, 'grade': 'B', 'stats': {'winrate': 70, 'total_trades': 100, 'realized_profit': 1200}},
            ]), encoding='utf-8')
            (root / 'data/blacklist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderRejected', 'total_score': 60, 'grade': 'C', 'stats': {'winrate': 75, 'total_trades': 1400, 'realized_profit': 900}},
            ]), encoding='utf-8')
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [
                    {'wallet_address': 'LeaderConfigured', 'total_score': 80, 'grade': 'A', 'stats_snapshot': {'winrate': 68, 'total_trades': 90, 'realized_profit': 900}},
                ],
            }), encoding='utf-8')

            result = backtest_leaders(root, target=10, min_score=65, min_win_rate_percent=60, min_total_trades=50)
            saved = json.loads((root / 'data/leader_backtest_results.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['backtested'], 3)
        self.assertEqual(result['passed'], 2)
        self.assertEqual({item['wallet_address'] for item in saved}, {'LeaderA', 'LeaderConfigured', 'LeaderRejected'})
        self.assertTrue(all('backtest_score' in item for item in saved))

    def test_run_leader_pool_action_promotes_and_backtests(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/leader_pool.json').write_text(json.dumps({
                'whitelist_target': 2,
                'backtest_target': 2,
                'min_score': 65,
                'min_win_rate_percent': 60,
                'min_total_trades': 50,
            }), encoding='utf-8')
            (root / 'data/whitelist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'total_score': 75, 'grade': 'B', 'stats': {'winrate': 70, 'total_trades': 100}},
            ]), encoding='utf-8')

            promote = _run_leader_pool_action(root, {'action': 'promote'})
            backtest = _run_leader_pool_action(root, {'action': 'backtest'})

        self.assertTrue(promote['ok'])
        self.assertTrue(backtest['ok'])
        self.assertEqual(backtest['backtested'], 1)

    def test_leader_pool_loop_once_promotes_when_quality_target_met(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/leader_pool.json').write_text(json.dumps({
                'discovery_target': 1,
                'high_quality_target': 1,
                'whitelist_target': 1,
                'backtest_target': 1,
                'min_score': 65,
                'min_win_rate_percent': 60,
                'min_total_trades': 50,
            }), encoding='utf-8')
            (root / 'data/candidate_wallets_smartmoney.json').write_text(json.dumps([
                {'address': 'LeaderA'},
            ]), encoding='utf-8')
            (root / 'data/whitelist_wallets.json').write_text(json.dumps([
                {'wallet_address': 'LeaderA', 'total_score': 75, 'grade': 'B', 'stats': {'winrate': 70, 'total_trades': 100}},
            ]), encoding='utf-8')

            result = _run_leader_pool_action(root, {'action': 'loop_once'})
            saved = json.loads((root / 'config/wallet_whitelist.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(result['selected_action'], 'promote')
        self.assertEqual(saved['wallets'][0]['wallet_address'], 'LeaderA')

    def test_update_leader_trading_params_saves_tiny_real_limits(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            config_path = root / 'config/wallet_whitelist.json'
            config_path.write_text(json.dumps({
                'wallets': [{
                    'wallet_address': 'Leader111',
                    'label': 'alpha',
                    'mode': 'follow',
                    'total_score': 80,
                    'copy_weight': 0.25,
                    'risk_limits': {
                        'max_single_trade_sol': 0.01,
                        'max_daily_loss_sol': 0.03,
                        'max_daily_trades': 3,
                        'slippage_percent': 2.0,
                        'stop_loss_percent': -40.0,
                    },
                }],
            }), encoding='utf-8')

            result = _update_leader_trading_params(root, {
                'wallet_address': 'Leader111',
                'mode': 'observe',
                'copy_weight': 0.5,
                'max_single_trade_sol': 0.005,
                'max_daily_loss_sol': 0.02,
                'max_daily_trades': 2,
                'slippage_percent': 3.0,
                'stop_loss_percent': -35.0,
            })
            saved = json.loads(config_path.read_text(encoding='utf-8'))

        wallet = saved['wallets'][0]
        self.assertTrue(result['ok'])
        self.assertEqual(wallet['mode'], 'observe')
        self.assertEqual(wallet['copy_weight'], 1.0)
        self.assertEqual(wallet['copy_weight_percent'], '100.0%')
        self.assertEqual(wallet['risk_limits']['max_single_trade_sol'], 0.005)
        self.assertEqual(wallet['risk_limits']['max_daily_loss_sol'], 0.02)
        self.assertEqual(wallet['risk_limits']['max_daily_trades'], 2)
        self.assertEqual(wallet['risk_limits']['slippage_percent'], 3.0)
        self.assertEqual(wallet['risk_limits']['stop_loss_percent'], -35.0)
        self.assertTrue(result['liquidation']['triggered'])
        self.assertEqual(result['liquidation']['matched_positions'], 0)

    def test_update_leader_trading_params_liquidates_when_follow_mode_removed(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [{
                    'wallet_address': 'Leader111',
                    'label': 'alpha',
                    'enabled': True,
                    'mode': 'follow',
                    'total_score': 80,
                    'risk_limits': {
                        'max_single_trade_sol': 0.01,
                        'max_daily_loss_sol': 0.03,
                        'max_daily_trades': 3,
                        'slippage_percent': 2.0,
                        'stop_loss_percent': -40.0,
                    },
                }],
            }), encoding='utf-8')
            (root / 'data/portfolio_snapshot.json').write_text(json.dumps({
                'positions': [{
                    'token_address': 'Token111',
                    'symbol': 'TOK',
                    'source_wallet': 'Leader111',
                    'quantity': 10,
                    'value_sol': 1.0,
                }],
            }), encoding='utf-8')

            with patch('gmgn_monitor.dashboard._execute_sell', return_value={
                'success': False,
                'tx_hash': '',
                'order_id': '',
                'error_message': 'gate closed',
            }) as sell:
                result = _update_leader_trading_params(root, {
                    'wallet_address': 'Leader111',
                    'mode': 'observe',
                    'copy_weight': 0.5,
                    'max_single_trade_sol': 0.005,
                    'max_daily_loss_sol': 0.02,
                    'max_daily_trades': 2,
                    'slippage_percent': 3.0,
                    'stop_loss_percent': -35.0,
                })

        self.assertTrue(result['ok'])
        self.assertTrue(result['liquidation']['triggered'])
        self.assertEqual(result['liquidation']['matched_positions'], 1)
        self.assertFalse(result['liquidation']['results'][0]['success'])
        sell.assert_called_once()
        self.assertEqual(sell.call_args.args[1]['trigger_type'], 'LEADER_REMOVED')

    def test_update_leader_trading_params_rejects_over_limit_trade_size(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [{'wallet_address': 'Leader111'}],
            }), encoding='utf-8')

            with self.assertRaises(ValueError):
                _update_leader_trading_params(root, {
                    'wallet_address': 'Leader111',
                    'mode': 'follow',
                    'copy_weight': 0.5,
                    'max_single_trade_sol': 0.02,
                    'max_daily_loss_sol': 0.02,
                    'max_daily_trades': 2,
                    'slippage_percent': 3.0,
                    'stop_loss_percent': -35.0,
                })

    def test_update_token_exit_config_saves_signal_cache_and_resets_triggered_levels(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data').mkdir()
            (root / 'data/triggered_tp.json').write_text(json.dumps({
                'Token111': {'token_address': 'Token111', 'triggered_levels': [1]},
            }), encoding='utf-8')

            result = _update_token_exit_config(root, {
                'token_address': 'Token111',
                'stop_loss_percent': -35.0,
                'max_slippage_percent': 2.5,
                'tp1_trigger_percent': 80.0,
                'tp1_sell_percent': 40.0,
                'tp2_trigger_percent': 200.0,
                'tp2_sell_percent': 60.0,
            })
            cache = json.loads((root / 'data/signal_cache.json').read_text(encoding='utf-8'))
            triggered = json.loads((root / 'data/triggered_tp.json').read_text(encoding='utf-8'))

        self.assertTrue(result['ok'])
        self.assertEqual(cache['Token111']['sl_order']['trigger_percent'], -35.0)
        self.assertEqual(cache['Token111']['max_slippage_percent'], 2.5)
        self.assertEqual(cache['Token111']['tp_orders'][0]['trigger_percent'], 80.0)
        self.assertEqual(cache['Token111']['tp_orders'][0]['sell_percent'], 40.0)
        self.assertEqual(cache['Token111']['tp_orders'][1]['sell_percent'], 60.0)
        self.assertNotIn('Token111', triggered)

    def test_update_token_exit_config_requires_take_profit_sells_sum_to_100(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)

            with self.assertRaises(ValueError):
                _update_token_exit_config(root, {
                    'token_address': 'Token111',
                    'stop_loss_percent': -35.0,
                    'max_slippage_percent': 2.5,
                    'tp1_trigger_percent': 80.0,
                    'tp1_sell_percent': 40.0,
                    'tp2_trigger_percent': 200.0,
                    'tp2_sell_percent': 40.0,
                })

    def test_automation_gate_toggle_updates_config_and_reports(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'config/automation_gate.json').write_text(json.dumps({
                'force_open': True,
                'positive_expectancy_after_costs': True,
                'reviewed_candidate_count': 200,
                'minimum_reviewed_candidate_count': 200,
                'paper_or_shadow_results_available': True,
                'kill_switch_configured': True,
                'mandatory_logs_configured': True,
                'hard_daily_loss_limit_configured': True,
                'security_review_completed': True,
                'allows_martingale': False,
                'allows_dca_into_losers': False,
                'allows_unlimited_retries': False,
            }), encoding='utf-8')

            disabled = _set_automation_gate_enabled(root, False)
            disabled_config = json.loads((root / 'config/automation_gate.json').read_text(encoding='utf-8'))
            disabled_report = (root / 'data/pipeline/automation_gate.md').read_text(encoding='utf-8')
            enabled = _set_automation_gate_enabled(root, True)
            enabled_config = json.loads((root / 'config/automation_gate.json').read_text(encoding='utf-8'))
            enabled_report = (root / 'data/pipeline/automation_gate.md').read_text(encoding='utf-8')
            state = _read_automation_gate_state(root)

        self.assertTrue(disabled['ok'])
        self.assertFalse(disabled_config['force_open'])
        self.assertIn('Status: eligible_for_tiny_size_testing', disabled_report)
        self.assertTrue(enabled['ok'])
        self.assertTrue(enabled_config['force_open'])
        self.assertIn('Status: auto_trading_enabled', enabled_report)
        self.assertEqual(state['status_label'], '自动交易已启用')

    def test_dashboard_source_health_reports_invalid_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'fixtures/candidates.jsonl').write_text('{"symbol":"A"}\nnot json\n', encoding='utf-8')

            payload = build_dashboard_payload(root)

        self.assertIn('格式错误，第 2 行', payload['data_sources'][0]['health'])

    def test_dashboard_source_health_reports_non_object_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'fixtures/candidates.jsonl').write_text('[]\n', encoding='utf-8')

            payload = build_dashboard_payload(root)

        self.assertEqual(payload['data_sources'][0]['health'], '格式错误，第 1 行不是对象')

    def test_dashboard_source_health_reports_invalid_utf8_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'fixtures/candidates.jsonl').write_bytes(b'\xff')

            payload = build_dashboard_payload(root)

        self.assertEqual(payload['data_sources'][0]['health'], '格式错误，不是有效 UTF-8')

    def test_dashboard_source_health_reports_jsonl_read_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures/candidates.jsonl').mkdir(parents=True)

            payload = build_dashboard_payload(root)

        self.assertIn('读取失败', payload['data_sources'][0]['health'])

    def test_dashboard_dexscreener_health_reports_payload_pairs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'data').mkdir(parents=True)
            (root / 'fixtures/dexscreener_search_sample.json').write_text('{"pairs":[{}]}', encoding='utf-8')
            (root / 'data/dexscreener_candidates.jsonl').write_text('{"symbol":"DEX"}\n', encoding='utf-8')
            (root / 'data/dexscreener_events.jsonl').write_text('{"symbol":"DEX"}\n', encoding='utf-8')
            (root / 'data/dexscreener_latest_profiles_candidates.jsonl').write_text('{"symbol":"LIVE"}\n', encoding='utf-8')
            (root / 'data/dexscreener_latest_profiles_events.jsonl').write_text('{"symbol":"LIVE"}\n', encoding='utf-8')

            payload = build_dashboard_payload(root)

        health = payload['data_sources'][2]['health']
        self.assertEqual(payload['data_sources'][2]['name'], 'DEX Screener 真实只读源')
        self.assertEqual(payload['data_sources'][2]['status'], '已接入')
        self.assertIn('dexscreener_search_sample.json: 可用，1 个 pairs', health)
        self.assertIn('dexscreener_candidates.jsonl: 可用，1 条记录', health)
        self.assertIn('dexscreener_latest_profiles_candidates.jsonl: 可用，1 条记录', health)

    def test_homepage_highlights_operational_overview(self):
        self.assertNotIn('只读扫链情报台', INDEX_HTML)
        self.assertNotIn('信号态势', INDEX_HTML)
        self.assertNotIn('href="#signals"', INDEX_HTML)
        self.assertNotIn('id="signalOverview"', INDEX_HTML)
        self.assertNotIn('操作命令', INDEX_HTML)
        self.assertNotIn('用户执行流程', INDEX_HTML)
        self.assertNotIn('href="#actions-section"', INDEX_HTML)
        self.assertNotIn('id="userFlow"', INDEX_HTML)
        self.assertNotIn('报告年龄', INDEX_HTML)
        self.assertNotIn('reportAge', INDEX_HTML)
        self.assertNotIn('candidateCountCard', INDEX_HTML)
        self.assertNotIn('toggleCandidateDetails', INDEX_HTML)
        self.assertNotIn('candidateDetails', INDEX_HTML)
        self.assertNotIn('candidateBreakdown', INDEX_HTML)
        self.assertNotIn('signalTotalCard', INDEX_HTML)
        self.assertNotIn('toggleSignalDetails', INDEX_HTML)
        self.assertNotIn('signalDetails', INDEX_HTML)
        self.assertNotIn('signalBreakdown', INDEX_HTML)
        self.assertNotIn('class="header-status"', INDEX_HTML)
        self.assertNotIn('id="statusBadge"', INDEX_HTML)
        self.assertNotIn('系统状态', INDEX_HTML)
        self.assertNotIn('diagnosticHeadline', INDEX_HTML)
        self.assertIn('class="header-gate"', INDEX_HTML)
        self.assertNotIn('<span>自动化安全门</span>', INDEX_HTML)
        self.assertIn('class="gmgn-avatar"', INDEX_HTML)
        self.assertIn('rel="icon"', INDEX_HTML)
        self.assertIn('leader-status-stack', INDEX_HTML)
        self.assertIn('renderLeaderPoolStatusCards', INDEX_HTML)
        self.assertNotIn('<div class="metric"><span>系统状态</span><strong id="statusBadge"', INDEX_HTML)
        self.assertNotIn('class="metric gate-card"', INDEX_HTML)
        self.assertIn('持仓管理', INDEX_HTML)
        self.assertIn('>持仓</a>', INDEX_HTML)
        self.assertIn('白名单', INDEX_HTML)
        self.assertIn('Leader', INDEX_HTML)
        self.assertIn('页面菜单', INDEX_HTML)
        self.assertNotIn('id="walletCount"', INDEX_HTML)
        self.assertNotIn('<div class="metric"><span>Leader</span>', INDEX_HTML)
        self.assertIn('href="/#portfolio"', INDEX_HTML)
        self.assertNotIn('href="/#whitelist"', INDEX_HTML)
        self.assertIn('href="/leader-pool"', INDEX_HTML)
        self.assertIn('Leader 池', INDEX_HTML)
        self.assertIn('Leader 池目标', INDEX_HTML)
        self.assertIn('Leader 筛选', INDEX_HTML)
        self.assertIn('href="/copy-config"', INDEX_HTML)
        self.assertIn('href="/token-exit-config"', INDEX_HTML)
        self.assertIn('href="/sources"', INDEX_HTML)
        self.assertIn('href="/reports"', INDEX_HTML)
        self.assertIn('data-page="copy-config"', INDEX_HTML)
        self.assertIn('data-page="leader-pool"', INDEX_HTML)
        self.assertIn('leaderPoolTargetPanel', INDEX_HTML)
        self.assertIn('leaderPoolFilterPanel', INDEX_HTML)
        self.assertIn('id="leaderPoolFilterTab" class="active"', INDEX_HTML)
        self.assertIn('id="leaderPoolTargetPanel" data-leader-tab="target" hidden', INDEX_HTML)
        self.assertIn("return document.documentElement.dataset.leaderPoolTab || 'filter';", INDEX_HTML)
        self.assertIn("switchLeaderPoolTab('target')", INDEX_HTML)
        self.assertIn("switchLeaderPoolTab('filter')", INDEX_HTML)
        self.assertIn('leaderPoolStages', INDEX_HTML)
        self.assertIn('leaderSourceQuality', INDEX_HTML)
        self.assertIn('来源质量诊断', INDEX_HTML)
        self.assertIn('renderLeaderSourceQuality', INDEX_HTML)
        self.assertIn('leaderPoolConfigForm', INDEX_HTML)
        self.assertIn('saveLeaderPoolConfig', INDEX_HTML)
        self.assertIn('/api/leader-pool/config', INDEX_HTML)
        self.assertIn('/api/leader-pool/actions', INDEX_HTML)
        self.assertIn('/api/leader-pool/promote-one', INDEX_HTML)
        self.assertIn('/api/leader-pool/recycle-scored', INDEX_HTML)
        self.assertIn("runLeaderPoolAction('loop_once'", INDEX_HTML)
        self.assertIn("runLeaderPoolAction('discover'", INDEX_HTML)
        self.assertIn("runLeaderPoolAction('score'", INDEX_HTML)
        self.assertNotIn("runLeaderPoolAction('promote'", INDEX_HTML)
        self.assertIn("runLeaderPoolAction('backtest'", INDEX_HTML)
        self.assertIn('leaderFunnel', INDEX_HTML)
        self.assertIn('leaderFunnelLeaders', INDEX_HTML)
        self.assertIn('leaderFunnelPagination', INDEX_HTML)
        self.assertIn('leaderFunnelPageSize', INDEX_HTML)
        self.assertIn('renderLeaderFunnelPagination', INDEX_HTML)
        self.assertIn('changeLeaderFunnelPage', INDEX_HTML)
        self.assertIn('leaderBacktestLeaders', INDEX_HTML)
        self.assertIn('promoteLeaderToCopyWhitelist', INDEX_HTML)
        self.assertIn('recycleScoredLeader', INDEX_HTML)
        self.assertIn('淘汰回候选', INDEX_HTML)
        self.assertIn('已在跟单白名单', INDEX_HTML)
        self.assertIn('回测分', INDEX_HTML)
        self.assertIn('leaderPoolActionStatus', INDEX_HTML)
        self.assertIn('leaderPoolLoopStatus', INDEX_HTML)
        self.assertIn('高质量候选目标', INDEX_HTML)
        self.assertIn('最低胜率 %', INDEX_HTML)
        self.assertIn('单次评分数量', INDEX_HTML)
        self.assertIn('copyConfigRows', INDEX_HTML)
        self.assertIn('copy-config-table', INDEX_HTML)
        self.assertIn('renderCopyConfig', INDEX_HTML)
        self.assertIn('saveLeaderConfig', INDEX_HTML)
        self.assertIn('/api/leaders/config', INDEX_HTML)
        self.assertIn('<option value="follow">跟随买卖</option>', INDEX_HTML)
        self.assertIn('<option value="observe">仅观察</option>', INDEX_HTML)
        self.assertIn('<option value="paused">暂停跟单</option>', INDEX_HTML)
        self.assertIn('is-paused', INDEX_HTML)
        self.assertIn('已暂停：不参与自动权重分配', INDEX_HTML)
        self.assertIn('启用：权重按评分自动计算', INDEX_HTML)
        self.assertIn('name="copy_weight"', INDEX_HTML)
        self.assertIn('disabled', INDEX_HTML)
        self.assertIn('data-page="token-exit-config"', INDEX_HTML)
        self.assertIn('tokenExitGrid', INDEX_HTML)
        self.assertIn('renderTokenExitConfig', INDEX_HTML)
        self.assertIn('saveTokenExitConfig', INDEX_HTML)
        self.assertIn('/api/tokens/exit-config', INDEX_HTML)
        self.assertIn('name="tp1_sell_percent" type="number" min="0.0001" max="100" step="any"', INDEX_HTML)
        self.assertIn('name="tp2_sell_percent" type="number" min="0.0001" max="100" step="any"', INDEX_HTML)
        self.assertIn('name="tp1_trigger_percent" type="number" min="0.0001" max="10000" step="any"', INDEX_HTML)
        self.assertIn('name="tp2_trigger_percent" type="number" min="0.0001" max="10000" step="any"', INDEX_HTML)
        self.assertNotIn('whitelistSummary', INDEX_HTML)
        self.assertNotIn('白名单级别配置', INDEX_HTML)
        self.assertNotIn('执行前仍受安全门和限额约束', INDEX_HTML)
        self.assertIn('whitelistScoreNotice', INDEX_HTML)
        self.assertIn('score-low', INDEX_HTML)
        self.assertIn('score_warning', INDEX_HTML)
        self.assertIn('每 3 小时刷新', INDEX_HTML)
        self.assertIn('whitelistWallets', INDEX_HTML)
        self.assertIn('/api/leaders/toggle', INDEX_HTML)
        self.assertIn('/api/automation-gate/toggle', INDEX_HTML)
        self.assertIn('gate-switch', INDEX_HTML)
        self.assertIn('toggleAutomationGate', INDEX_HTML)
        self.assertIn('portfolioActionNotice', INDEX_HTML)
        self.assertIn('跟单来源', INDEX_HTML)
        self.assertIn('formatCopySource', INDEX_HTML)
        self.assertNotIn('GMGN 只读 holdings', INDEX_HTML)
        self.assertNotIn('dashboard 不执行买卖', INDEX_HTML)
        self.assertNotIn('人工处理前请核对链上钱包和人工计划', INDEX_HTML)
        self.assertNotIn('本页不会从钱包发起交易', INDEX_HTML)
        self.assertIn('requestSellPosition', INDEX_HTML)
        self.assertIn('/api/sell', INDEX_HTML)
        self.assertIn('async function loadPortfolio(options = {})', INDEX_HTML)
        self.assertIn('await loadPortfolio({ renderPositions: true });', INDEX_HTML)
        self.assertIn('let portfolioRefreshPromise = null;', INDEX_HTML)
        self.assertIn('let portfolioNeedsPositionRender = false;', INDEX_HTML)
        self.assertIn('if (portfolioRefreshPromise) {', INDEX_HTML)
        self.assertIn('return portfolioRefreshPromise;', INDEX_HTML)
        self.assertIn('if (!response.ok) {', INDEX_HTML)
        self.assertIn('if (portfolioNeedsPositionRender) {', INDEX_HTML)
        self.assertIn('卖出', INDEX_HTML)
        self.assertIn('formatPriceWithUnit', INDEX_HTML)
        self.assertIn('formatPrice', INDEX_HTML)
        self.assertIn('刷新中', INDEX_HTML)
        self.assertIn('自动交易已启用', INDEX_HTML)
        self.assertIn('微型真实', INDEX_HTML)
        self.assertIn('formatTimestamp', INDEX_HTML)
        self.assertNotIn('id="headline"', INDEX_HTML)
        self.assertNotIn('报告时间', INDEX_HTML)
        self.assertNotIn('原始时间', INDEX_HTML)
        self.assertNotIn('formatUtcTimestamp', INDEX_HTML)
        self.assertIn('document.documentElement.dataset.page', INDEX_HTML)
        self.assertIn('html[data-page="leader-pool"] [data-page]:not([data-page="leader-pool"])', INDEX_HTML)
        self.assertIn('data-page="sources"', INDEX_HTML)
        self.assertIn('data-page="reports"', INDEX_HTML)
        self.assertIn('applyPageMode', INDEX_HTML)
        self.assertIn('startPortfolioAutoRefresh', INDEX_HTML)
        self.assertIn('loadPortfolio({ renderPositions: false })', INDEX_HTML)
        self.assertIn('loadPortfolio({ renderPositions: true })', INDEX_HTML)
        self.assertIn('}, 10000);', INDEX_HTML)
        self.assertIn('window.setInterval(refreshPositions, 30000)', INDEX_HTML)

    def test_dashboard_dexscreener_health_reports_invalid_payload_pairs(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'fixtures/dexscreener_search_sample.json').write_text('{"pairs":{}}', encoding='utf-8')

            payload = build_dashboard_payload(root)

        self.assertIn('dexscreener_search_sample.json: 格式错误，pairs 不是列表', payload['data_sources'][2]['health'])

    def test_dashboard_dexscreener_health_reports_invalid_utf8_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures').mkdir(parents=True)
            (root / 'data').mkdir(parents=True)
            (root / 'fixtures/dexscreener_search_sample.json').write_text('{"pairs":[]}', encoding='utf-8')
            (root / 'data/dexscreener_candidates.jsonl').write_bytes(b'\xff')

            payload = build_dashboard_payload(root)

        self.assertIn('dexscreener_candidates.jsonl: 格式错误，不是有效 UTF-8', payload['data_sources'][2]['health'])

    def test_dashboard_dexscreener_health_reports_payload_read_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'fixtures/dexscreener_search_sample.json').mkdir(parents=True)

            payload = build_dashboard_payload(root)

        self.assertIn('dexscreener_search_sample.json: 读取失败', payload['data_sources'][2]['health'])

    def test_dashboard_planned_doc_health_reports_non_file(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'SAFETY_ENRICHMENT.md').mkdir()

            payload = build_dashboard_payload(root)

        self.assertEqual(payload['data_sources'][4]['health'], '读取失败：不是文件')

    def test_dashboard_output_invalid_utf8_reports_read_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/daily_summary.md').write_bytes(b'\xff')

            payload = build_dashboard_payload(root)

        self.assertEqual(payload['outputs']['daily_summary']['content'], '')
        self.assertEqual(payload['outputs']['daily_summary']['read_error'], '输出文件不是有效 UTF-8')

    def test_dashboard_output_read_error_reports_read_error(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data/pipeline/daily_summary.md').mkdir(parents=True)

            payload = build_dashboard_payload(root)

        self.assertEqual(payload['outputs']['daily_summary']['content'], '')
        self.assertIn('输出文件读取失败', payload['outputs']['daily_summary']['read_error'])

    def test_dashboard_action_timeout_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch('gmgn_monitor.dashboard.subprocess.run') as run:
                run.side_effect = subprocess.TimeoutExpired(['python3'], timeout=1)

                result = run_action(root, 'status', timeout_seconds=1)

        self.assertFalse(result['ok'])
        self.assertEqual(result['returncode'], None)
        self.assertIn('超时', result['stderr'])
        self.assertIn('dashboard', result)

    def test_dashboard_action_decode_error_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch('gmgn_monitor.dashboard.subprocess.run') as run:
                run.side_effect = UnicodeDecodeError('utf-8', b'\xff', 0, 1, 'invalid start byte')

                result = run_action(root, 'status')

        self.assertFalse(result['ok'])
        self.assertEqual(result['returncode'], None)
        self.assertIn('命令输出不是有效文本', result['stderr'])
        self.assertIn('dashboard', result)

    def test_dashboard_action_start_error_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            with patch('gmgn_monitor.dashboard.subprocess.run') as run:
                run.side_effect = OSError('cannot start')

                result = run_action(root, 'status')

        self.assertFalse(result['ok'])
        self.assertEqual(result['returncode'], None)
        self.assertIn('命令启动失败', result['stderr'])
        self.assertIn('cannot start', result['stderr'])
        self.assertIn('dashboard', result)

    def test_dashboard_action_rejects_concurrent_run(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            ACTION_LOCK.acquire()
            try:
                result = run_action(root, 'status')
            finally:
                ACTION_LOCK.release()

        self.assertFalse(result['ok'])
        self.assertEqual(result['returncode'], None)
        self.assertIn('已有命令正在运行', result['stderr'])
        self.assertIn('dashboard', result)

    def test_handler_serves_index_and_payload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'data/pipeline').mkdir(parents=True)
            (root / 'data/pipeline/automation_gate.md').write_text('Status: auto_trading_enabled\n', encoding='utf-8')
            handler = make_handler(root)
            server = DashboardHandler.create_server('127.0.0.1', 0, handler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/', timeout=5) as response:
                    html = response.read().decode('utf-8')
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/sources', timeout=5) as response:
                    sources_html = response.read().decode('utf-8')
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/leader-pool', timeout=5) as response:
                    leader_pool_html = response.read().decode('utf-8')
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/reports', timeout=5) as response:
                    reports_html = response.read().decode('utf-8')
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/status', timeout=5) as response:
                    payload = json.loads(response.read().decode('utf-8'))
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/portfolio', timeout=5) as response:
                    portfolio = json.loads(response.read().decode('utf-8'))
            finally:
                server.shutdown()
                server.server_close()

        self.assertIn('GMGN 扫链监控', html)
        self.assertIn('data-page="home"', html)
        self.assertNotIn('本地只读控制台', html)
        self.assertNotIn('操作命令', html)
        self.assertNotIn('用户执行流程', html)
        self.assertIn('data-page="leader-pool"', leader_pool_html)
        self.assertIn('Leader 池目标', leader_pool_html)
        self.assertIn('Leader 筛选', leader_pool_html)
        self.assertNotIn('candidateCountCard', leader_pool_html)
        self.assertNotIn('signalTotalCard', leader_pool_html)
        self.assertIn('data-page="sources"', sources_html)
        self.assertIn('数据源状态', sources_html)
        self.assertIn('data-page="reports"', reports_html)
        self.assertIn('审计事件报告', reports_html)
        self.assertNotIn('输出结果', reports_html)
        self.assertNotIn('aria-label="输出文件"', reports_html)
        self.assertNotIn('提醒文本', reports_html)
        self.assertNotIn('自动化安全门</button>', reports_html)
        self.assertNotIn('候选事件', reports_html)
        self.assertNotIn('每日摘要', reports_html)
        self.assertNotIn('结果复盘分析', reports_html)
        self.assertNotIn('流水线提醒文本', reports_html)
        self.assertNotIn('流水线人工计划', reports_html)
        self.assertIn('数据源状态', html)
        self.assertIn('运行状态', html)
        self.assertIn('summaryWarning', html)
        self.assertIn('验证报告 JSON 格式错误', html)
        self.assertIn('验证报告读取失败：', html)
        self.assertIn('读取失败：', html)
        self.assertEqual(payload['outputs']['automation_gate']['content'], 'Status: auto_trading_enabled\n')
        self.assertFalse(portfolio['ok'])
        self.assertEqual(portfolio['summary']['open_positions'], 0)
        self.assertEqual(payload['data_sources'][2]['alertable'], '默认不可以')
        self.assertIn('dexscreener_search_sample.json', payload['data_sources'][2]['health'])
        self.assertEqual(payload['user_flow'][-1]['action'], '人工计划 / 自动化安全门')

    def test_execute_sell_requires_dashboard_confirmation(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            result = _execute_sell(Path(tmp_dir), {
                'token_address': 'Token111',
                'symbol': 'TOK',
            })
            audit = json.loads((Path(tmp_dir) / 'data/audit_events.jsonl').read_text(encoding='utf-8').splitlines()[-1])

        self.assertFalse(result['success'])
        self.assertIn('需要用户在 dashboard 明确确认', result['error_message'])
        self.assertEqual(audit['category'], 'manual_trade')
        self.assertEqual(audit['action'], 'dashboard_manual_sell')
        self.assertFalse(audit['success'])

    def test_execute_sell_submits_gmgn_cli_swap_after_safety_checks(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/automation_gate.json').write_text(json.dumps({
                'force_open': True,
                'positive_expectancy_after_costs': True,
                'reviewed_candidate_count': 200,
                'minimum_reviewed_candidate_count': 200,
                'paper_or_shadow_results_available': True,
                'kill_switch_configured': True,
                'mandatory_logs_configured': True,
                'hard_daily_loss_limit_configured': True,
                'security_review_completed': True,
                'allows_martingale': False,
                'allows_dca_into_losers': False,
                'allows_unlimited_retries': False,
            }), encoding='utf-8')
            (root / 'config/wallet.json').write_text(json.dumps({
                'gmgn_wallet_address': 'Wallet111',
            }), encoding='utf-8')
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'global_settings': {'chain': 'sol'},
            }), encoding='utf-8')
            (root / 'data/signal_cache.json').write_text(json.dumps({
                'Token111': {'max_slippage_percent': 2.5},
            }), encoding='utf-8')
            portfolio = {
                'ok': True,
                'positions': [{
                    'token_address': 'Token111',
                    'symbol': 'TOK',
                    'quantity': 10,
                }],
            }
            config_check = subprocess.CompletedProcess(
                args=['gmgn-cli', 'config', '--check'],
                returncode=0,
                stdout='',
                stderr='',
            )
            swap_result = subprocess.CompletedProcess(
                args=['gmgn-cli', 'swap'],
                returncode=0,
                stdout=json.dumps({'order_id': 'order-1', 'tx_hash': 'tx-1'}),
                stderr='',
            )

            with patch('gmgn_monitor.dashboard.shutil.which', return_value='/usr/local/bin/gmgn-cli'), \
                    patch('gmgn_monitor.dashboard._get_portfolio_data', return_value=portfolio), \
                    patch('gmgn_monitor.dashboard.subprocess.run', side_effect=[config_check, swap_result]) as run:
                result = _execute_sell(root, {
                    'token_address': 'Token111',
                    'symbol': 'TOK',
                    'sell_percent': 100,
                    'confirmed': True,
                })
            audit = json.loads((root / 'data/trading_log.jsonl').read_text(encoding='utf-8').splitlines()[-1])
            unified_audit = json.loads((root / 'data/audit_events.jsonl').read_text(encoding='utf-8').splitlines()[-1])

        self.assertTrue(result['success'])
        self.assertEqual(result['order_id'], 'order-1')
        self.assertEqual(result['tx_hash'], 'tx-1')
        command = run.call_args_list[1].args[0]
        self.assertEqual(command[:2], ['gmgn-cli', 'swap'])
        self.assertIn('--percent', command)
        self.assertIn('100', command)
        self.assertIn('--slippage', command)
        self.assertIn('3', command)
        self.assertIn('--anti-mev', command)
        self.assertEqual(audit['event'], 'dashboard_manual_sell')
        self.assertEqual(unified_audit['category'], 'manual_trade')
        self.assertEqual(unified_audit['action'], 'dashboard_manual_sell')
        self.assertTrue(unified_audit['success'])

    def test_auto_stop_loss_sells_real_holding_when_threshold_is_breached(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'config/automation_gate.json').write_text(json.dumps({
                'force_open': True,
                'positive_expectancy_after_costs': True,
                'reviewed_candidate_count': 200,
                'minimum_reviewed_candidate_count': 200,
                'paper_or_shadow_results_available': True,
                'kill_switch_configured': True,
                'mandatory_logs_configured': True,
                'hard_daily_loss_limit_configured': True,
                'security_review_completed': True,
                'allows_martingale': False,
                'allows_dca_into_losers': False,
                'allows_unlimited_retries': False,
            }), encoding='utf-8')
            (root / 'config/wallet.json').write_text(json.dumps({
                'gmgn_wallet_address': 'Wallet111',
            }), encoding='utf-8')
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'global_settings': {'chain': 'sol'},
            }), encoding='utf-8')
            (root / 'data/signal_cache.json').write_text(json.dumps({
                'TokenSL': {
                    'tp_orders': [],
                    'sl_order': {'trigger_percent': -40.0, 'sell_percent': 100.0},
                    'max_slippage_percent': 2.0,
                },
            }), encoding='utf-8')
            portfolio = {
                'ok': True,
                'positions': [{
                    'token_address': 'TokenSL',
                    'symbol': 'LOSS',
                    'quantity': 100,
                    'value_sol': 0.01,
                    'unrealized_pnl_percent': -47.2,
                }],
            }
            config_check = subprocess.CompletedProcess(
                args=['gmgn-cli', 'config', '--check'],
                returncode=0,
                stdout='',
                stderr='',
            )
            swap_result = subprocess.CompletedProcess(
                args=['gmgn-cli', 'swap'],
                returncode=0,
                stdout=json.dumps({'order_id': 'sl-order', 'tx_hash': 'sl-tx'}),
                stderr='',
            )

            with patch('gmgn_monitor.dashboard.shutil.which', return_value='/usr/local/bin/gmgn-cli'), \
                    patch('gmgn_monitor.dashboard._get_portfolio_data', return_value=portfolio), \
                    patch('gmgn_monitor.dashboard.subprocess.run', side_effect=[config_check, swap_result]) as run:
                result = _run_auto_stop_loss_once(root)

            state = json.loads((root / 'data/auto_stop_loss_state.json').read_text(encoding='utf-8'))
            audit = json.loads((root / 'data/trading_log.jsonl').read_text(encoding='utf-8').splitlines()[-1])
            unified_audit = json.loads((root / 'data/audit_events.jsonl').read_text(encoding='utf-8').splitlines()[-1])

        self.assertEqual(result['triggered'], 1)
        self.assertTrue(state['TokenSL']['success'])
        self.assertEqual(state['TokenSL']['order_id'], 'sl-order')
        command = run.call_args_list[1].args[0]
        self.assertEqual(command[:2], ['gmgn-cli', 'swap'])
        self.assertIn('--input-token', command)
        self.assertIn('TokenSL', command)
        self.assertIn('--percent', command)
        self.assertIn('100', command)
        self.assertEqual(audit['event'], 'auto_stop_loss_sell')
        self.assertEqual(audit['trigger_type'], 'AUTO_STOP_LOSS')
        self.assertIn('-47.20%', audit['reason'])
        self.assertEqual(unified_audit['category'], 'auto_trade')
        self.assertEqual(unified_audit['action'], 'auto_stop_loss_sell')
        self.assertTrue(unified_audit['success'])

    def test_handler_copy_config_page_and_leader_config_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'config/wallet_whitelist.json').write_text(json.dumps({
                'wallets': [{
                    'wallet_address': 'Leader111',
                    'label': 'alpha',
                    'mode': 'follow',
                    'total_score': 80,
                    'copy_weight': 0.25,
                    'risk_limits': {
                        'max_single_trade_sol': 0.01,
                        'max_daily_loss_sol': 0.03,
                        'max_daily_trades': 3,
                        'slippage_percent': 2.0,
                        'stop_loss_percent': -40.0,
                    },
                }],
            }), encoding='utf-8')
            handler = make_handler(root)
            server = DashboardHandler.create_server('127.0.0.1', 0, handler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/copy-config', timeout=5) as response:
                    html = response.read().decode('utf-8')
                request = urllib.request.Request(
                    f'http://127.0.0.1:{port}/api/leaders/config',
                    data=json.dumps({
                        'wallet_address': 'Leader111',
                        'mode': 'observe',
                        'copy_weight': 0.4,
                        'max_single_trade_sol': 0.005,
                        'max_daily_loss_sol': 0.02,
                        'max_daily_trades': 2,
                        'slippage_percent': 3.0,
                        'stop_loss_percent': -30.0,
                    }).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode('utf-8'))
            finally:
                server.shutdown()
                server.server_close()

        self.assertIn('跟单配置', html)
        self.assertTrue(payload['ok'])
        wallet = payload['dashboard']['copy_trading_config']['wallets'][0]
        self.assertEqual(wallet['mode'], 'observe')
        self.assertEqual(wallet['copy_weight'], 1.0)
        self.assertEqual(wallet['copy_weight_percent'], '100.0%')
        self.assertEqual(wallet['risk_limits']['max_single_trade_sol'], 0.005)

    def test_handler_token_exit_config_page_and_endpoint(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            (root / 'config').mkdir()
            (root / 'data').mkdir()
            (root / 'data/portfolio_snapshot.json').write_text(json.dumps({
                'positions': [{
                    'token_address': 'Token111',
                    'symbol': 'TOK',
                    'quantity': 10,
                    'entry_price_sol': 0.01,
                    'current_price_sol': 0.02,
                }],
            }), encoding='utf-8')
            handler = make_handler(root)
            server = DashboardHandler.create_server('127.0.0.1', 0, handler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with urllib.request.urlopen(f'http://127.0.0.1:{port}/token-exit-config', timeout=5) as response:
                    html = response.read().decode('utf-8')
                request = urllib.request.Request(
                    f'http://127.0.0.1:{port}/api/tokens/exit-config',
                    data=json.dumps({
                        'token_address': 'Token111',
                        'stop_loss_percent': -30.0,
                        'max_slippage_percent': 2.0,
                        'tp1_trigger_percent': 80.0,
                        'tp1_sell_percent': 40.0,
                        'tp2_trigger_percent': 200.0,
                        'tp2_sell_percent': 60.0,
                    }).encode('utf-8'),
                    headers={'Content-Type': 'application/json'},
                    method='POST',
                )
                with urllib.request.urlopen(request, timeout=5) as response:
                    payload = json.loads(response.read().decode('utf-8'))
            finally:
                server.shutdown()
                server.server_close()

        self.assertIn('代币止损止盈配置', html)
        self.assertTrue(payload['ok'])
        token = payload['dashboard']['token_exit_config']['tokens'][0]
        self.assertEqual(token['token_address'], 'Token111')
        self.assertEqual(token['sl_order']['trigger_percent'], -30.0)
        self.assertEqual(token['tp_orders'][0]['sell_percent'], 40.0)

    def test_handler_unknown_action_returns_structured_failure(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            root = Path(tmp_dir)
            handler = make_handler(root)
            server = DashboardHandler.create_server('127.0.0.1', 0, handler)
            port = server.server_address[1]
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            request = urllib.request.Request(
                f'http://127.0.0.1:{port}/api/actions/not_allowed',
                method='POST',
            )
            try:
                with self.assertRaises(urllib.error.HTTPError) as context:
                    urllib.request.urlopen(request, timeout=5)
                error = context.exception
                try:
                    body = error.read().decode('utf-8')
                finally:
                    error.close()
            finally:
                server.shutdown()
                server.server_close()

        payload = json.loads(body)
        self.assertEqual(context.exception.code, 400)
        self.assertFalse(payload['ok'])
        self.assertEqual(payload['command'], '')
        self.assertEqual(payload['returncode'], None)
        self.assertEqual(payload['stdout'], '')
        self.assertIn('unknown dashboard action', payload['stderr'])
        self.assertIn('dashboard', payload)


if __name__ == '__main__':
    unittest.main()
