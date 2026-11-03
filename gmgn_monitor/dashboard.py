from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
import os
import shutil
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .audit_log import append_audit_event, build_audit_report
from .automation_gate import build_gate_report, evaluate_gate
from .config_manager import ConfigManager
from .file_io import atomic_write_text, durable_append_text
from .copy_risk import load_copy_risk
from .leader_pool import backtest_leaders, discover_leaders, promote_leaders, score_leaders
from .status import build_status

# Tiny real safety limits enforced by the dashboard (SOL)
_MAX_SINGLE_TRADE_SOL = 0.01
_MAX_DAILY_LOSS_SOL = 0.03
_MAX_COPY_WHITELIST_LEADERS = 10
_WHITELIST_SCORE_INTERVAL_SECONDS = 3 * 60 * 60
_LOW_WALLET_SCORE_THRESHOLD = 60.0
_AUTO_STOP_LOSS_INTERVAL_SECONDS = 30
_AUTO_STOP_LOSS_RETRY_SECONDS = 60
_CHAIN_OUTPUT_TOKENS = {
    'sol': 'So11111111111111111111111111111111111111112',
    'bsc': '0x0000000000000000000000000000000000000000',
    'base': '0x0000000000000000000000000000000000000000',
    'eth': '0x0000000000000000000000000000000000000000',
}


ACTION_LOCK = threading.Lock()


ACTIONS: dict[str, dict[str, object]] = {
    'status': {
        'label': '刷新状态',
        'module': 'gmgn_monitor.status',
        'args': [
            '--max-report-age-minutes', '1440',
            '--history-limit', '5',
            '--require-report',
            '--require-history-current',
            '--fail-on-future-report',
            '--fail-on-stale-lock',
            '--fail-on-stale-temp-artifacts',
        ],
    },
    'verify': {
        'label': '运行完整验证',
        'module': 'gmgn_monitor.verify',
        'args': ['--report', 'data/verification_report.json', '--history', 'data/verification_history.jsonl'],
    },
    'pipeline': {
        'label': '生成流水线结果',
        'module': 'gmgn_monitor.pipeline',
        'args': [
            '--input', 'fixtures/candidates.jsonl',
            '--reviews', 'fixtures/outcome_reviews.jsonl',
            '--threshold-config', 'config/thresholds.json',
            '--risk-config', 'config/risk_limits.json',
            '--automation-config', 'config/automation_gate.json',
            '--output-dir', 'data/pipeline',
        ],
    },
    'replay': {
        'label': '重放候选数据',
        'module': 'gmgn_monitor.replay',
        'args': ['--input', 'fixtures/candidates.jsonl', '--output', 'data/candidate_events.jsonl', '--config', 'config/thresholds.json'],
    },
    'telegram_dry_run': {
        'label': '生成提醒文本',
        'module': 'gmgn_monitor.telegram_dry_run',
        'args': ['--input', 'data/candidate_events.jsonl', '--output', 'data/telegram_dry_run.txt'],
    },
    'trade_plan': {
        'label': '生成人工计划',
        'module': 'gmgn_monitor.trade_plan',
        'args': [
            '--input', 'data/candidate_events.jsonl',
            '--risk-config', 'config/risk_limits.json',
            '--daily-loss-percent', '0',
            '--output', 'data/trade_plans.json',
        ],
    },
}


OUTPUTS = {
    'daily_summary': ('每日摘要', Path('data/pipeline/daily_summary.md')),
    'pipeline_alert_text': ('流水线提醒文本', Path('data/pipeline/telegram_dry_run.txt')),
    'pipeline_trade_plans': ('流水线人工计划', Path('data/pipeline/trade_plans.json')),
    'automation_gate': ('自动化安全门', Path('data/pipeline/automation_gate.md')),
    'outcome_analysis': ('结果复盘分析', Path('data/pipeline/outcome_analysis.md')),
    'candidate_events': ('候选事件', Path('data/candidate_events.jsonl')),
    'alert_text': ('提醒文本', Path('data/telegram_dry_run.txt')),
    'trade_plans': ('人工计划', Path('data/trade_plans.json')),
    'verification_report': ('验证报告', Path('data/verification_report.json')),
}


USER_FLOW = [
    {
        'title': '1. 检查系统健康',
        'body': '先点击刷新状态。只有状态为 ok、验证报告和历史一致、没有过期锁或临时文件时，才继续后续判断。',
        'action': '刷新状态',
    },
    {
        'title': '2. 运行完整验证',
        'body': '修改候选数据、配置、复盘记录或代码后，点击运行完整验证。它会重建报告、追加历史、运行测试并检查安全边界。',
        'action': '运行完整验证',
    },
    {
        'title': '3. 生成 dry-run 流水线',
        'body': '点击生成流水线结果，重建候选事件、提醒文本、已复盘事件、摘要、结果分析、人工计划和自动化安全门报告。',
        'action': '生成流水线结果',
    },
    {
        'title': '4. 人工查看结果',
        'body': '查看每日摘要、候选事件、提醒文本、结果复盘和人工计划。alert/watch 只是人工判断证据，不是执行指令。',
        'action': '结果标签页',
    },
    {
        'title': '5. 保持人工执行',
        'body': '人工计划必须保持 needs_human_confirmation。除非证据、熔断、限额和安全审查全部完成，自动化安全门应保持 blocked。',
        'action': '人工计划 / 自动化安全门',
    },
]


DATA_SOURCES = [
    {
        'name': '本地 JSONL 候选数据',
        'status': '已启用',
        'path': 'fixtures/candidates.jsonl',
        'kind': 'jsonl',
        'alertable': '可以',
        'notes': '当前主流程数据源；字段完整时可进入 reject/watch/alert 决策。',
    },
    {
        'name': '链阈值与大样本 fixture',
        'status': '已启用',
        'path': 'fixtures/chain_threshold_candidates.jsonl / fixtures/large_sample_candidates.jsonl',
        'paths': ['fixtures/chain_threshold_candidates.jsonl', 'fixtures/large_sample_candidates.jsonl'],
        'kind': 'jsonl_group',
        'alertable': '可以',
        'notes': '用于阈值校验、样本回放、分布和复盘分析。',
    },
    {
        'name': 'DEX Screener 真实只读源',
        'status': '已接入',
        'path': 'gmgn_monitor/dexscreener.py',
        'paths': [
            'fixtures/dexscreener_search_sample.json',
            'data/dexscreener_candidates.jsonl',
            'data/dexscreener_events.jsonl',
            'data/dexscreener_latest_profiles_candidates.jsonl',
            'data/dexscreener_latest_profiles_events.jsonl',
        ],
        'kind': 'dexscreener',
        'alertable': '默认不可以',
        'notes': '可发现 liquidity、FDV、volume、tx count；缺少 holder/dev/LP/honeypot 等安全字段，未知安全会保守 reject。',
    },
    {
        'name': 'GMGN 人工审查导出',
        'status': '待接入',
        'path': '未来 JSONL fixture',
        'kind': 'planned',
        'alertable': '字段完整后可以',
        'notes': '推荐下一步数据源：由人工在 GMGN/链上工具审查后导出完整安全字段。',
    },
    {
        'name': '安全增强 API',
        'status': '待接入',
        'path': 'SAFETY_ENRICHMENT.md',
        'kind': 'planned_doc',
        'alertable': '验证后可以',
        'notes': '用于补 holder concentration、dev holding、insider/bundle、mint/freeze、LP、honeypot、blacklist、tax 等安全字段。',
    },
]


class DashboardHandler(BaseHTTPRequestHandler):
    root: Path = Path('.')

    @staticmethod
    def create_server(host: str, port: int, handler: type[BaseHTTPRequestHandler]) -> ThreadingHTTPServer:
        return ThreadingHTTPServer((host, port), handler)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path in ('/', '/leader-pool', '/sources', '/reports', '/copy-config', '/token-exit-config'):
            self._send_text(INDEX_HTML, 'text/html; charset=utf-8')
            return
        if path == '/api/status':
            self._send_json(build_dashboard_payload(self.root))
            return
        if path == '/api/trading/config':
            self._send_json(_read_trading_config(self.root))
            return
        if path == '/api/portfolio':
            self._send_json(_get_portfolio_data(self.root))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == '/api/trading/config':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                config = json.loads(body) if body else {}
                _save_trading_config(self.root, config)
                self._send_json({'ok': True, 'message': '配置已保存'})
            except Exception as exc:
                self._send_json({'ok': False, 'error': str(exc)}, status=400)
            return
        if path == '/api/trading/execute':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                payload = json.loads(body) if body else {}
                result = _execute_trade(self.root, payload)
                self._send_json(result)
            except Exception as exc:
                self._send_json({
                    'success': False,
                    'tx_hash': '',
                    'order_id': '',
                    'gas_cost_sol': 0.0,
                    'error_message': str(exc),
                    'confirmation_time_ms': 0,
                }, status=500)
            return
        if path == '/api/sell':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                payload = json.loads(body) if body else {}
                result = _execute_sell(self.root, payload)
                self._send_json(result)
            except Exception as exc:
                self._send_json({
                    'success': False, 'tx_hash': '', 'error_message': str(exc),
                }, status=500)
            return
        if path == '/api/leaders/toggle':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                payload = json.loads(body) if body else {}
                result = _set_leader_enabled(
                    self.root,
                    str(payload.get('wallet_address') or ''),
                    bool(payload.get('enabled')),
                )
                self._send_json({**result, 'dashboard': build_dashboard_payload(self.root)})
            except Exception as exc:
                self._send_json({'ok': False, 'error': str(exc)}, status=400)
            return
        if path == '/api/leaders/config':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                payload = json.loads(body) if body else {}
                result = _update_leader_trading_params(self.root, payload)
                self._send_json({**result, 'dashboard': build_dashboard_payload(self.root)})
            except Exception as exc:
                self._send_json({'ok': False, 'error': str(exc)}, status=400)
            return
        if path == '/api/tokens/exit-config':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                payload = json.loads(body) if body else {}
                result = _update_token_exit_config(self.root, payload)
                self._send_json({**result, 'dashboard': build_dashboard_payload(self.root)})
            except Exception as exc:
                self._send_json({'ok': False, 'error': str(exc)}, status=400)
            return
        if path == '/api/automation-gate/toggle':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                payload = json.loads(body) if body else {}
                result = _set_automation_gate_enabled(self.root, bool(payload.get('enabled')))
                self._send_json({**result, 'dashboard': build_dashboard_payload(self.root)})
            except Exception as exc:
                self._send_json({'ok': False, 'error': str(exc)}, status=400)
            return
        if path == '/api/leader-pool/config':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                payload = json.loads(body) if body else {}
                result = _update_leader_pool_config(self.root, payload)
                self._send_json({**result, 'dashboard': build_dashboard_payload(self.root)})
            except Exception as exc:
                self._send_json({'ok': False, 'error': str(exc)}, status=400)
            return
        if path == '/api/leader-pool/actions':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                payload = json.loads(body) if body else {}
                result = _run_leader_pool_action(self.root, payload)
                status = 200 if result.get('ok') else 400
                self._send_json({**result, 'dashboard': build_dashboard_payload(self.root)}, status=status)
            except Exception as exc:
                self._send_json({'ok': False, 'error': str(exc), 'dashboard': build_dashboard_payload(self.root)}, status=400)
            return
        if path == '/api/leader-pool/promote-one':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                payload = json.loads(body) if body else {}
                result = _promote_single_leader_to_copy_whitelist(self.root, payload)
                status = 200 if result.get('ok') else 400
                self._send_json({**result, 'dashboard': build_dashboard_payload(self.root)}, status=status)
            except Exception as exc:
                self._send_json({'ok': False, 'error': str(exc), 'dashboard': build_dashboard_payload(self.root)}, status=400)
            return
        if path == '/api/leader-pool/recycle-scored':
            try:
                length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(length).decode('utf-8')
                payload = json.loads(body) if body else {}
                result = _recycle_scored_leader_to_candidates(self.root, payload)
                status = 200 if result.get('ok') else 400
                self._send_json({**result, 'dashboard': build_dashboard_payload(self.root)}, status=status)
            except Exception as exc:
                self._send_json({'ok': False, 'error': str(exc), 'dashboard': build_dashboard_payload(self.root)}, status=400)
            return
        if not path.startswith('/api/actions/'):
            self.send_error(404)
            return
        action = path.rsplit('/', 1)[-1]
        try:
            payload = run_action(self.root, action)
        except ValueError as exc:
            self._send_json({
                'command': '',
                'ok': False,
                'returncode': None,
                'stderr': str(exc),
                'stdout': '',
                'dashboard': build_dashboard_payload(self.root),
            }, status=400)
            return
        self._send_json(payload, status=200 if payload['ok'] else 500)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send_json(self, payload: dict[str, object], status: int = 200) -> None:
        body = json.dumps(payload, sort_keys=True).encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(body)))
            self.send_header('Cache-Control', 'no-store, max-age=0')
            self.end_headers()
            self.wfile.write(body)
        except BrokenPipeError:
            return

    def _send_text(self, body: str, content_type: str, status: int = 200) -> None:
        data = body.encode('utf-8')
        try:
            self.send_response(status)
            self.send_header('Content-Type', content_type)
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-store, max-age=0')
            self.end_headers()
            self.wfile.write(data)
        except BrokenPipeError:
            return


def make_handler(root: Path) -> type[DashboardHandler]:
    root = root.resolve()

    class BoundDashboardHandler(DashboardHandler):
        pass

    BoundDashboardHandler.root = root
    return BoundDashboardHandler


def _read_trading_config(root: Path) -> dict[str, object]:
    """Read trading configuration for the trading page."""
    root = root.resolve()
    config_path = root / 'config' / 'wallet_whitelist.json'
    if not config_path.exists():
        return {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    if not isinstance(data, dict):
        return {}
    global_settings = data.get('global_settings', {})
    return {
        'trade_mode': data.get('trade_mode', 'dryrun'),
        'exposure_level': data.get('exposure_level', 'observe'),
        'global': {
            'max_total_daily_trades': global_settings.get('max_total_daily_trades', 3),
            'max_total_daily_loss_sol': global_settings.get('max_total_daily_loss_sol', _MAX_DAILY_LOSS_SOL),
            'default_slippage_percent': global_settings.get('default_slippage_percent', 2.0),
            'chain': global_settings.get('chain', 'sol'),
            'execution_venue': global_settings.get('execution_venue', 'GMGN'),
            'rebalance_frequency': global_settings.get('rebalance_frequency', 'daily'),
            'audit_log_enabled': global_settings.get('audit_log_enabled', True),
            'feishu_alert_enabled': global_settings.get('feishu_alert_enabled', True),
            'auto_confirm': global_settings.get('auto_confirm', False),
            'max_single_trade_sol': _MAX_SINGLE_TRADE_SOL,
        },
    }


def _save_trading_config(root: Path, config: dict) -> None:
    """Save trading configuration to wallet whitelist config."""
    root = root.resolve()
    config_path = root / 'config' / 'wallet_whitelist.json'
    data = {}
    if config_path.exists():
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            data = {}
    if not isinstance(data, dict):
        data = {}
    # Update top-level fields
    if 'trade_mode' in config:
        data['trade_mode'] = config['trade_mode']
    if 'exposure_level' in config:
        data['exposure_level'] = config['exposure_level']
    # Update global settings
    g = config.get('global', {})
    global_settings = data.get('global_settings', {})
    for key in ['max_total_daily_trades', 'max_total_daily_loss_sol', 'default_slippage_percent', 'chain', 'execution_venue', 'rebalance_frequency', 'audit_log_enabled', 'feishu_alert_enabled', 'auto_confirm']:
        if key in g:
            global_settings[key] = g[key]
    data['global_settings'] = global_settings
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    append_audit_event(
        root,
        category='manual_config',
        action='trading_config_update',
        success=True,
        source='dashboard',
        actor='user',
        object_type='config',
        object_id='config/wallet_whitelist.json',
        message='交易全局配置已保存',
        details={'payload': config},
    )


def _set_leader_enabled(root: Path, wallet_address: str, enabled: bool) -> dict[str, object]:
    if not wallet_address.strip():
        raise ValueError('wallet_address is required')
    config_path = root.resolve() / 'config' / 'wallet_whitelist.json'
    data = _read_json_object(config_path)
    wallets = data.get('wallets', [])
    if not isinstance(wallets, list):
        raise ValueError('wallet_whitelist.json wallets must be a list')
    matched = False
    was_enabled = False
    for wallet in wallets:
        if not isinstance(wallet, dict):
            continue
        if wallet.get('wallet_address') == wallet_address:
            was_enabled = bool(wallet.get('enabled', True))
            wallet['enabled'] = enabled
            matched = True
            break
    if not matched:
        raise ValueError('leader wallet not found')
    _recalculate_copy_weights(data)
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    atomic_write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', config_path)
    append_audit_event(
        root,
        category='manual_config',
        action='leader_toggle',
        success=True,
        source='dashboard',
        actor='user',
        object_type='leader',
        object_id=wallet_address,
        message='Leader 已启动' if enabled else 'Leader 已暂停',
        details={'enabled': enabled},
    )
    liquidation = {'triggered': False, 'matched_positions': 0, 'results': []}
    if was_enabled and not enabled:
        liquidation = _liquidate_leader_positions(
            root,
            wallet_address,
            'Leader 已从跟单白名单停用，自动平仓该 Leader 跟单持仓',
        )
    return {'ok': True, 'wallet_address': wallet_address, 'enabled': enabled, 'liquidation': liquidation}


def _update_leader_trading_params(root: Path, payload: dict[str, object]) -> dict[str, object]:
    wallet_address = str(payload.get('wallet_address') or '').strip()
    if not wallet_address:
        raise ValueError('wallet_address is required')
    root = root.resolve()
    config_path = root / 'config' / 'wallet_whitelist.json'
    data = _read_json_object(config_path)
    wallets = data.get('wallets', [])
    if not isinstance(wallets, list):
        raise ValueError('wallet_whitelist.json wallets must be a list')
    matched_wallet: dict[str, object] | None = None
    for wallet in wallets:
        if isinstance(wallet, dict) and wallet.get('wallet_address') == wallet_address:
            matched_wallet = wallet
            break
    if matched_wallet is None:
        raise ValueError('leader wallet not found')

    previous_following = _leader_is_following(matched_wallet)
    mode = str(payload.get('mode') or matched_wallet.get('mode') or 'follow').strip()
    if mode not in {'follow', 'observe', 'paused'}:
        raise ValueError('mode must be follow, observe, or paused')
    risk_limits = matched_wallet.get('risk_limits')
    if not isinstance(risk_limits, dict):
        risk_limits = {}
    updated_limits = dict(risk_limits)
    updated_limits['max_single_trade_sol'] = _bounded_number(
        payload.get('max_single_trade_sol'), 0.0, _MAX_SINGLE_TRADE_SOL, 'max_single_trade_sol'
    )
    updated_limits['max_daily_loss_sol'] = _bounded_number(
        payload.get('max_daily_loss_sol'), 0.0, _MAX_DAILY_LOSS_SOL, 'max_daily_loss_sol'
    )
    updated_limits['max_daily_trades'] = int(_bounded_number(
        payload.get('max_daily_trades'), 0.0, 20.0, 'max_daily_trades'
    ))
    updated_limits['slippage_percent'] = _bounded_number(
        payload.get('slippage_percent'), 0.0, 5.0, 'slippage_percent'
    )
    updated_limits['stop_loss_percent'] = _bounded_number(
        payload.get('stop_loss_percent'), -99.0, 0.0, 'stop_loss_percent'
    )

    matched_wallet['mode'] = mode
    matched_wallet['risk_limits'] = updated_limits
    _recalculate_copy_weights(data)
    data['updated_at'] = datetime.now(timezone.utc).isoformat()
    atomic_write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', config_path)
    append_audit_event(
        root,
        category='manual_config',
        action='leader_config_update',
        success=True,
        source='dashboard',
        actor='user',
        object_type='leader',
        object_id=wallet_address,
        message='Leader 跟单参数已保存',
        details={'mode': mode, 'risk_limits': updated_limits},
    )
    liquidation = {'triggered': False, 'matched_positions': 0, 'results': []}
    if previous_following and not _leader_is_following(matched_wallet):
        liquidation = _liquidate_leader_positions(
            root,
            wallet_address,
            f'Leader 模式从跟随买卖改为 {mode}，自动平仓该 Leader 跟单持仓',
        )
    return {'ok': True, 'wallet_address': wallet_address, 'liquidation': liquidation}


def _recalculate_copy_weights(config: dict[str, object]) -> bool:
    wallets = config.get('wallets', [])
    if not isinstance(wallets, list):
        return False
    active_wallets = [
        wallet for wallet in wallets
        if isinstance(wallet, dict) and _leader_is_active(wallet)
    ]
    score_sum = sum(max(0.0, _number(wallet.get('total_score'))) for wallet in active_wallets)
    changed = False
    for wallet in wallets:
        if not isinstance(wallet, dict):
            continue
        old_weight = wallet.get('copy_weight')
        old_percent = wallet.get('copy_weight_percent')
        if _leader_is_active(wallet) and score_sum > 0:
            weight = round(max(0.0, _number(wallet.get('total_score'))) / score_sum, 6)
        else:
            weight = 0.0
        percent = f'{weight * 100:.1f}%'
        if old_weight != weight or old_percent != percent:
            wallet['copy_weight'] = weight
            wallet['copy_weight_percent'] = percent
            changed = True
    weight_calculation = config.get('weight_calculation')
    if not isinstance(weight_calculation, dict):
        weight_calculation = {}
    new_total = round(score_sum, 2)
    if weight_calculation.get('total_score_sum') != new_total:
        weight_calculation['total_score_sum'] = new_total
        changed = True
    for key, value in {
        'method': 'active_score_normalized',
        'description': '仅对启用且未 paused 的 leader 按 total_score 归一化；暂停 leader 权重为 0',
        'formula': 'active_wallet_weight = wallet_score / active_score_sum',
    }.items():
        if weight_calculation.get(key) != value:
            weight_calculation[key] = value
            changed = True
    config['weight_calculation'] = weight_calculation
    return changed


def _leader_is_active(wallet: dict[str, object]) -> bool:
    return bool(wallet.get('enabled', True)) and str(wallet.get('mode') or 'follow') != 'paused'


def _leader_is_following(wallet: dict[str, object]) -> bool:
    return bool(wallet.get('enabled', True)) and str(wallet.get('mode') or 'follow') == 'follow'


def _liquidate_leader_positions(root: Path, wallet_address: str, reason: str) -> dict[str, object]:
    root = root.resolve()
    target = wallet_address.lower().strip()
    if not target:
        return {'triggered': False, 'matched_positions': 0, 'results': []}
    portfolio = _get_portfolio_data(root)
    positions = portfolio.get('positions', [])
    if not isinstance(positions, list):
        positions = []
    matched_positions = [
        position for position in positions
        if isinstance(position, dict)
        and str(position.get('copy_source_wallet') or '').lower().strip() == target
    ]
    results: list[dict[str, object]] = []
    for position in matched_positions:
        token_address = str(position.get('token_address') or '').strip()
        if not token_address:
            continue
        symbol = str(position.get('symbol') or 'unknown')
        result = _execute_sell(root, {
            'token_address': token_address,
            'symbol': symbol,
            'quantity': position.get('quantity') or 0,
            'value': position.get('value_sol') or 0,
            'sell_percent': 100,
            'confirmed': True,
            'trigger_type': 'LEADER_REMOVED',
            'leader_wallet_address': wallet_address,
            'reason': reason,
        })
        results.append({
            'token_address': token_address,
            'symbol': symbol,
            'success': bool(result.get('success')),
            'tx_hash': result.get('tx_hash') or '',
            'order_id': result.get('order_id') or '',
            'error_message': result.get('error_message') or '',
        })
    append_audit_event(
        root,
        category='auto_trade',
        action='leader_removed_liquidation',
        success=all(bool(result.get('success')) for result in results) if results else True,
        source='dashboard',
        actor='system',
        object_type='leader',
        object_id=wallet_address,
        message=f'Leader 移出跟单后自动平仓：匹配 {len(matched_positions)} 个持仓',
        details={
            'reason': reason,
            'matched_positions': len(matched_positions),
            'results': results,
        },
    )
    return {
        'triggered': True,
        'leader_wallet_address': wallet_address,
        'matched_positions': len(matched_positions),
        'results': results,
    }


def _bounded_number(value: object, minimum: float, maximum: float, name: str) -> float:
    number = _optional_number(value)
    if number is None:
        raise ValueError(f'{name} is required')
    if number < minimum or number > maximum:
        raise ValueError(f'{name} must be between {minimum} and {maximum}')
    return float(number)


def _read_automation_gate_state(root: Path) -> dict[str, object]:
    config = _read_json_object(root.resolve() / 'config' / 'automation_gate.json')
    result = evaluate_gate(config)
    status = str(result.get('status') or 'unknown')
    return {
        'force_open': bool(config.get('force_open')),
        'status': status,
        'status_label': _status_label(status),
        'enabled': status == 'auto_trading_enabled',
        'blockers': result.get('blockers') or [],
    }


def _set_automation_gate_enabled(root: Path, enabled: bool) -> dict[str, object]:
    root = root.resolve()
    config_path = root / 'config' / 'automation_gate.json'
    config = _read_json_object(config_path)
    if not config:
        raise ValueError('automation_gate.json is missing or invalid')
    config['force_open'] = enabled
    atomic_write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', config_path)
    report = build_gate_report(config)
    atomic_write_text(report, root / 'data' / 'automation_gate.md')
    atomic_write_text(report, root / 'data' / 'pipeline' / 'automation_gate.md')
    append_audit_event(
        root,
        category='manual_config',
        action='automation_gate_toggle',
        success=True,
        source='dashboard',
        actor='user',
        object_type='automation_gate',
        object_id='config/automation_gate.json',
        message='自动交易开关已启用' if enabled else '自动交易开关已关闭',
        details={'enabled': enabled},
    )
    return {'ok': True, 'automation_gate': _read_automation_gate_state(root)}


def _execute_trade(root: Path, payload: dict) -> dict:
    response = {
        'success': False,
        'tx_hash': '',
        'order_id': '',
        'gas_cost_sol': 0.0,
        'error_message': '首页仅启用监控、验证和人工计划；交易执行未在 dashboard 开放。',
        'confirmation_time_ms': 0,
    }
    append_audit_event(
        root,
        category='manual_trade',
        action='dashboard_manual_buy',
        success=False,
        source='dashboard',
        actor='user',
        object_type='token',
        object_id=str(payload.get('token_address') or payload.get('target_token') or ''),
        message=str(response['error_message']),
        details={'payload': payload, 'response': response},
    )
    return response


def _get_portfolio_data(root: Path) -> dict:
    root = root.resolve()
    risk_limits = _read_json_object(root / 'config/risk_limits.json')
    snapshot, source, notice = _read_live_portfolio_snapshot(root)
    if snapshot is None:
        local_snapshot, local_source = _read_portfolio_snapshot(root)
        if local_snapshot:
            snapshot = local_snapshot
            source = local_source
            notice = '本地真实持仓快照'
        elif not notice:
            notice = (
                '未接入真实钱包数据：请设置 GMGN_WALLET_ADDRESS，并确保 gmgn-cli 已配置可读取 holdings。'
                'Portfolio 不再读取 dry-run 模拟快照。'
            )
    if not snapshot:
        return _empty_portfolio_response(root, risk_limits, source, notice)
    leader_lookup = _read_leader_lookup(root)
    positions = _normalize_positions(snapshot.get('positions', []))
    if any(not position.get('copy_source_wallet') for position in positions):
        audited_sources = _infer_copy_sources_from_audit(root, positions)
        for position in positions:
            if not position.get('copy_source_wallet'):
                source_wallet = audited_sources.get(str(position.get('token_address') or '').lower())
                if source_wallet:
                    position['copy_source_wallet'] = source_wallet
        inferred_sources = _infer_copy_sources_from_whitelist(root, positions, leader_lookup)
        for position in positions:
            if not position.get('copy_source_wallet'):
                source_wallet = inferred_sources.get(str(position.get('token_address') or '').lower())
                if source_wallet:
                    position['copy_source_wallet'] = source_wallet
                    position['copy_source_inferred'] = True
    positions = [
        _with_copy_source(position, leader_lookup)
        for position in positions
    ]
    max_positions = risk_limits.get('max_total_positions', 3)
    return {
        'ok': True,
        'source': source,
        'wallet_address': snapshot.get('wallet_address') or _configured_wallet_address(root) or '',
        'timestamp': snapshot.get('timestamp'),
        'value_unit': snapshot.get('value_unit') or 'SOL',
        'price_unit': snapshot.get('price_unit') or snapshot.get('value_unit') or 'SOL',
        'available_unit': snapshot.get('available_unit') or snapshot.get('value_unit') or 'SOL',
        'has_available_balance': snapshot.get('available_sol') is not None,
        'has_max_drawdown': snapshot.get('max_drawdown_percent') is not None,
        'summary': {
            'total_value_sol': _number(snapshot.get('total_value_sol')),
            'available_sol': _number(snapshot.get('available_sol')),
            'daily_pnl_sol': _number(snapshot.get('daily_pnl_sol')),
            'daily_pnl_percent': _number(snapshot.get('daily_pnl_percent')),
            'total_return_percent': _number(snapshot.get('total_return_percent')),
            'max_drawdown_percent': _number(snapshot.get('max_drawdown_percent')),
            'open_positions': len(positions),
            'max_positions': max_positions,
        },
        'positions': positions,
        'notice': notice,
    }


def _execute_sell(root: Path, payload: dict) -> dict:
    root = root.resolve()
    started_at = datetime.now(timezone.utc)
    token_address = str(payload.get('token_address') or '').strip()
    symbol = str(payload.get('symbol') or 'unknown').strip() or 'unknown'
    sell_percent = _optional_number(payload.get('sell_percent'))
    if sell_percent is None:
        sell_percent = 100.0

    def fail(message: str) -> dict[str, object]:
        response = _sell_failure(message)
        _append_sell_audit(root, token_address, symbol, sell_percent, False, response, [], started_at, payload)
        return response

    if not token_address:
        return fail('缺少代币地址。')
    if payload.get('confirmed') is not True:
        return fail('真实卖出需要用户在 dashboard 明确确认。')
    if sell_percent <= 0.0 or sell_percent > 100.0:
        return fail('sell_percent must be between 0 and 100')

    gate = _read_automation_gate_state(root)
    if not gate.get('enabled'):
        return fail(f"自动化安全门未开启：{gate.get('status_label') or gate.get('status') or 'unknown'}")
    if not shutil.which('gmgn-cli'):
        return fail('gmgn-cli 未安装，无法提交真实卖出。')
    wallet_address = _configured_wallet_address(root)
    if not wallet_address:
        return fail('缺少 GMGN_WALLET_ADDRESS 或 config/wallet.json 钱包地址。')

    portfolio = _get_portfolio_data(root)
    matched_position = _find_portfolio_position(portfolio, token_address)
    if matched_position is None:
        return fail(f'当前真实持仓中未找到 {symbol}，已拒绝卖出。')
    quantity = _number(matched_position.get('quantity'))
    if quantity <= 0.0:
        return fail(f'{symbol} 当前持仓数量为 0，已拒绝卖出。')

    config_check = subprocess.run(
        ['gmgn-cli', 'config', '--check'],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if config_check.returncode != 0:
        message = (config_check.stderr or config_check.stdout or 'gmgn-cli config --check failed').strip()
        return fail(f'gmgn-cli 配置检查失败：{message}')

    chain = _configured_chain(root)
    output_token = _CHAIN_OUTPUT_TOKENS.get(chain)
    if not output_token:
        return fail(f'不支持的链：{chain}')
    slippage = _sell_slippage_percent(root, token_address)
    command = [
        'gmgn-cli',
        'swap',
        '--chain', chain,
        '--from', wallet_address,
        '--input-token', token_address,
        '--output-token', output_token,
        '--percent', _format_cli_number(sell_percent),
        '--slippage', str(int(min(100, max(0, math.ceil(slippage))))),
        '--raw',
    ]
    if chain != 'base':
        command.append('--anti-mev')

    try:
        result = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=180,
        )
    except subprocess.TimeoutExpired:
        response = _sell_failure('gmgn-cli swap 超时；请在 GMGN 或链上浏览器核对是否已提交。')
        _append_sell_audit(root, token_address, symbol, sell_percent, False, response, command, started_at, payload)
        return response

    if result.returncode != 0:
        message = (result.stderr or result.stdout or f'gmgn-cli swap exited {result.returncode}').strip()
        response = _sell_failure(f'gmgn-cli swap 失败：{message}')
        _append_sell_audit(root, token_address, symbol, sell_percent, False, response, command, started_at, payload)
        return response

    try:
        swap_payload = _parse_gmgn_cli_json(result.stdout)
    except ValueError as exc:
        response = _sell_failure(str(exc))
        _append_sell_audit(root, token_address, symbol, sell_percent, False, response, command, started_at, payload)
        return response

    response = {
        'success': True,
        'tx_hash': _first_string(swap_payload, ('tx_hash', 'hash', 'transaction_hash', 'signature')),
        'order_id': _first_string(swap_payload, ('order_id', 'id')),
        'gas_cost_sol': _number(swap_payload.get('gas_cost_sol') or swap_payload.get('gas_cost') or swap_payload.get('fee_sol')),
        'actual_slippage_percent': _number(swap_payload.get('actual_slippage_percent') or swap_payload.get('slippage')),
        'confirmation_time_ms': 0.0,
        'error_message': '',
        'message': f'{symbol} 真实卖出命令已由 gmgn-cli 提交。',
        'raw': swap_payload,
    }
    _append_sell_audit(root, token_address, symbol, sell_percent, True, response, command, started_at, payload)
    return response


def _run_auto_stop_loss_once(root: Path) -> dict[str, object]:
    root = root.resolve()
    portfolio = _get_portfolio_data(root)
    positions = portfolio.get('positions', [])
    if not isinstance(positions, list) or not positions:
        return {'ok': True, 'checked': 0, 'triggered': 0, 'results': []}
    exit_config = _read_token_exit_config(root, portfolio)
    token_config = {
        str(item.get('token_address') or '').lower(): item
        for item in exit_config.get('tokens', [])
        if isinstance(item, dict)
    }
    state_path = root / 'data/auto_stop_loss_state.json'
    state = _read_json_object(state_path)
    now = datetime.now(timezone.utc)
    results: list[dict[str, object]] = []
    for position in positions:
        if not isinstance(position, dict):
            continue
        token_address = str(position.get('token_address') or '')
        if not token_address:
            continue
        token_key = token_address.lower()
        existing = state.get(token_address)
        if isinstance(existing, dict) and existing.get('success') is True:
            continue
        if isinstance(existing, dict):
            last_attempt = _parse_iso_datetime(str(existing.get('last_attempt_at') or ''))
            if last_attempt and (now - last_attempt).total_seconds() < _AUTO_STOP_LOSS_RETRY_SECONDS:
                continue
        config = token_config.get(token_key, {})
        sl_order = config.get('sl_order') if isinstance(config, dict) else None
        if not isinstance(sl_order, dict):
            continue
        sl_trigger = _optional_number(sl_order.get('trigger_percent'))
        sell_percent = _optional_number(sl_order.get('sell_percent'))
        if sl_trigger is None:
            continue
        if sell_percent is None:
            sell_percent = 100.0
        pnl_percent = _position_pnl_percent(position)
        if pnl_percent is None or pnl_percent > sl_trigger:
            continue
        symbol = str(position.get('symbol') or 'unknown')
        result = _execute_sell(root, {
            'token_address': token_address,
            'symbol': symbol,
            'quantity': position.get('quantity') or 0,
            'value': position.get('value_sol') or 0,
            'sell_percent': sell_percent,
            'confirmed': True,
            'trigger_type': 'AUTO_STOP_LOSS',
            'reason': f'Auto stop-loss: pnl {pnl_percent:.2f}% <= {sl_trigger:.2f}%',
        })
        record = {
            'token_address': token_address,
            'symbol': symbol,
            'pnl_percent': pnl_percent,
            'stop_loss_percent': sl_trigger,
            'sell_percent': sell_percent,
            'last_attempt_at': now.isoformat(),
            'success': bool(result.get('success')),
            'tx_hash': result.get('tx_hash') or '',
            'order_id': result.get('order_id') or '',
            'error_message': result.get('error_message') or '',
            'attempts': int(existing.get('attempts') or 0) + 1 if isinstance(existing, dict) else 1,
        }
        state[token_address] = record
        results.append(record)
    if results:
        atomic_write_text(json.dumps(state, ensure_ascii=False, indent=2) + '\n', state_path)
    return {'ok': True, 'checked': len(positions), 'triggered': len(results), 'results': results}


def _position_pnl_percent(position: dict[str, object]) -> float | None:
    explicit = _optional_number(position.get('unrealized_pnl_percent'))
    if explicit is not None:
        return explicit
    entry = _optional_number(position.get('entry_price_sol'))
    current = _optional_number(position.get('current_price_sol'))
    if entry is None or current is None or entry <= 0:
        return None
    return (current - entry) / entry * 100.0


def _start_auto_stop_loss_monitor(root: Path, stop_event: threading.Event) -> threading.Thread:
    def run() -> None:
        while not stop_event.is_set():
            try:
                result = _run_auto_stop_loss_once(root)
                if result.get('triggered'):
                    durable_append_text(
                        json.dumps({
                            'event': 'auto_stop_loss_scan',
                            'timestamp': datetime.now(timezone.utc).isoformat(),
                            'checked': result.get('checked'),
                            'triggered': result.get('triggered'),
                            'results': result.get('results'),
                        }, ensure_ascii=False, sort_keys=True) + '\n',
                        root.resolve() / 'data/trading_log.jsonl',
                    )
            except Exception as exc:
                durable_append_text(
                    json.dumps({
                        'event': 'auto_stop_loss_error',
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'error': str(exc),
                    }, ensure_ascii=False, sort_keys=True) + '\n',
                    root.resolve() / 'data/trading_log.jsonl',
                )
            stop_event.wait(_AUTO_STOP_LOSS_INTERVAL_SECONDS)

    thread = threading.Thread(target=run, name='gmgn-auto-stop-loss', daemon=True)
    thread.start()
    return thread


def _sell_failure(message: str) -> dict[str, object]:
    return {
        'success': False,
        'tx_hash': '',
        'order_id': '',
        'gas_cost_sol': 0.0,
        'actual_slippage_percent': 0.0,
        'confirmation_time_ms': 0.0,
        'error_message': message,
    }


def _find_portfolio_position(portfolio: dict[str, object], token_address: str) -> dict[str, object] | None:
    positions = portfolio.get('positions', [])
    if not isinstance(positions, list):
        return None
    target = token_address.lower()
    for position in positions:
        if not isinstance(position, dict):
            continue
        if str(position.get('token_address') or '').lower() == target:
            return position
    return None


def _configured_chain(root: Path) -> str:
    config = _read_json_object(root / 'config/wallet_whitelist.json')
    global_settings = config.get('global_settings')
    chain = ''
    if isinstance(global_settings, dict):
        chain = str(global_settings.get('chain') or '')
    if not chain:
        chain = str(config.get('chain') or '')
    chain = chain.lower().strip() or 'sol'
    return chain if chain in _CHAIN_OUTPUT_TOKENS else 'sol'


def _sell_slippage_percent(root: Path, token_address: str) -> float:
    cache = _read_json_object(root / 'data/signal_cache.json')
    config = cache.get(token_address)
    slippage = None
    if isinstance(config, dict):
        slippage = _optional_number(config.get('max_slippage_percent'))
    if slippage is None:
        slippage = 5.0
    return min(100.0, max(0.0, slippage))


def _format_cli_number(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f'{value:.6f}'.rstrip('0').rstrip('.')


def _parse_gmgn_cli_json(output: str) -> dict[str, object]:
    text = output.strip()
    if not text:
        raise ValueError('gmgn-cli swap 没有返回结果。')
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        for index, char in enumerate(text):
            if char in '[{':
                try:
                    payload = json.loads(text[index:])
                    break
                except json.JSONDecodeError:
                    continue
        else:
            raise ValueError('gmgn-cli swap 返回的不是有效 JSON。')
    if isinstance(payload, dict):
        return payload
    raise ValueError('gmgn-cli swap 返回结构不是对象。')


def _first_string(payload: dict[str, object], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = payload.get(key)
        if value:
            return str(value)
    return ''


def _short_address(value: str) -> str:
    if len(value) <= 12:
        return value
    return f'{value[:6]}...{value[-4:]}'


def _append_sell_audit(
    root: Path,
    token_address: str,
    symbol: str,
    sell_percent: float,
    success: bool,
    response: dict[str, object],
    command: list[str],
    started_at: datetime,
    request_payload: dict | None = None,
) -> None:
    request_payload = request_payload or {}
    trigger_type = str(request_payload.get('trigger_type') or '').strip()
    if trigger_type == 'AUTO_STOP_LOSS':
        event = 'auto_stop_loss_sell'
    elif trigger_type == 'LEADER_REMOVED':
        event = 'leader_removed_liquidation_sell'
    else:
        event = 'dashboard_manual_sell'
    safe_command = [
        part if index == 0 or command[index - 1] not in {'--from'} else _short_address(part)
        for index, part in enumerate(command)
    ]
    record = {
        'event': event,
        'started_at': started_at.isoformat(),
        'completed_at': datetime.now(timezone.utc).isoformat(),
        'token_address': token_address,
        'symbol': symbol,
        'sell_percent': sell_percent,
        'success': success,
        'tx_hash': response.get('tx_hash') or '',
        'order_id': response.get('order_id') or '',
        'error_message': response.get('error_message') or '',
        'command': safe_command,
    }
    if trigger_type:
        record['trigger_type'] = trigger_type
    reason = str(request_payload.get('reason') or '').strip()
    if reason:
        record['reason'] = reason
    durable_append_text(json.dumps(record, ensure_ascii=False, sort_keys=True) + '\n', root / 'data/trading_log.jsonl')
    append_audit_event(
        root,
        category='auto_trade' if event in {'auto_stop_loss_sell', 'leader_removed_liquidation_sell'} else 'manual_trade',
        action=event,
        success=success,
        source='dashboard',
        actor='system' if event in {'auto_stop_loss_sell', 'leader_removed_liquidation_sell'} else 'user',
        object_type='token',
        object_id=token_address,
        message=reason or str(response.get('message') or response.get('error_message') or event),
        details=record,
    )


def _read_token_exit_config(root: Path, portfolio: dict[str, object]) -> dict[str, object]:
    root = root.resolve()
    cache = _read_json_object(root / 'data/signal_cache.json')
    positions = portfolio.get('positions', [])
    if not isinstance(positions, list):
        positions = []
    return {
        'source': 'data/signal_cache.json',
        'tokens': [
            _token_exit_payload(position, cache)
            for position in positions
            if isinstance(position, dict) and position.get('token_address')
        ],
    }


def _token_exit_payload(position: dict[str, object], cache: dict[str, object]) -> dict[str, object]:
    token_address = str(position.get('token_address') or '')
    config = cache.get(token_address)
    if not isinstance(config, dict):
        config = {}
    tp_orders = config.get('tp_orders')
    if not isinstance(tp_orders, list) or not tp_orders:
        tp_orders = [
            {'level': 1, 'trigger_percent': 100.0, 'sell_percent': 50.0},
            {'level': 2, 'trigger_percent': 300.0, 'sell_percent': 50.0},
        ]
    sl_order = config.get('sl_order')
    if not isinstance(sl_order, dict):
        sl_order = {'trigger_percent': -40.0, 'sell_percent': 100.0}
    slippage = _optional_number(config.get('max_slippage_percent') if config else None)
    return {
        'token_address': token_address,
        'symbol': position.get('symbol') or 'unknown',
        'quantity': position.get('quantity'),
        'value': position.get('value_sol'),
        'tp_orders': tp_orders[:2],
        'sl_order': sl_order,
        'max_slippage_percent': 2.0 if slippage is None else slippage,
        'configured': token_address in cache,
    }


def _update_token_exit_config(root: Path, payload: dict[str, object]) -> dict[str, object]:
    root = root.resolve()
    token_address = str(payload.get('token_address') or '').strip()
    if not token_address:
        raise ValueError('token_address is required')
    tp1 = _bounded_number(payload.get('tp1_trigger_percent'), 0.0001, 10000.0, 'tp1_trigger_percent')
    tp1_sell = _bounded_number(payload.get('tp1_sell_percent'), 0.0001, 100.0, 'tp1_sell_percent')
    tp2 = _bounded_number(payload.get('tp2_trigger_percent'), tp1, 10000.0, 'tp2_trigger_percent')
    tp2_sell = _bounded_number(payload.get('tp2_sell_percent'), 0.0001, 100.0, 'tp2_sell_percent')
    if abs((tp1_sell + tp2_sell) - 100.0) > 0.000001:
        raise ValueError('take-profit sell percents must sum to 100')
    stop_loss = _bounded_number(payload.get('stop_loss_percent'), -99.0, -0.0001, 'stop_loss_percent')
    slippage = _bounded_number(payload.get('max_slippage_percent'), 0.0, 5.0, 'max_slippage_percent')

    cache_path = root / 'data/signal_cache.json'
    cache = _read_json_object(cache_path)
    cache[token_address] = {
        'tp_orders': [
            {'level': 1, 'trigger_percent': tp1, 'sell_percent': tp1_sell},
            {'level': 2, 'trigger_percent': tp2, 'sell_percent': tp2_sell},
        ],
        'sl_order': {'trigger_percent': stop_loss, 'sell_percent': 100.0},
        'max_slippage_percent': slippage,
    }
    atomic_write_text(json.dumps(cache, ensure_ascii=False, indent=2) + '\n', cache_path)
    _reset_triggered_tp_for_token(root, token_address)
    append_audit_event(
        root,
        category='manual_config',
        action='token_exit_config_update',
        success=True,
        source='dashboard',
        actor='user',
        object_type='token',
        object_id=token_address,
        message='代币止损止盈配置已保存',
        details={'config': cache[token_address]},
    )
    return {'ok': True, 'token_address': token_address}


def _reset_triggered_tp_for_token(root: Path, token_address: str) -> None:
    path = root / 'data/triggered_tp.json'
    data = _read_json_object(path)
    if token_address not in data:
        return
    data.pop(token_address, None)
    atomic_write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', path)


def _empty_portfolio_response(root: Path, risk_limits: dict[str, object], source: str, notice: str) -> dict:
    return {
        'ok': False,
        'source': source,
        'wallet_address': _configured_wallet_address(root) or '',
        'timestamp': None,
        'value_unit': 'USD',
        'price_unit': 'USD',
        'summary': {
            'total_value_sol': 0.0,
            'available_sol': 0.0,
            'daily_pnl_sol': 0.0,
            'daily_pnl_percent': 0.0,
            'total_return_percent': 0.0,
            'max_drawdown_percent': 0.0,
            'open_positions': 0,
            'max_positions': risk_limits.get('max_total_positions', 3),
        },
        'positions': [],
        'notice': notice,
    }


def _read_live_portfolio_snapshot(root: Path) -> tuple[dict[str, object] | None, str, str]:
    wallet_address = _configured_wallet_address(root)
    if not wallet_address:
        return None, 'not_configured', (
            '未接入真实钱包数据：缺少 GMGN_WALLET_ADDRESS。Portfolio 不再读取 dry-run 模拟快照。'
        )
    if not shutil.which('gmgn-cli'):
        return None, 'gmgn-cli missing', '未接入真实钱包数据：gmgn-cli 未安装，无法读取真实 holdings。'
    try:
        return _fetch_gmgn_cli_portfolio(root, wallet_address), 'gmgn-cli portfolio holdings', ''
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return None, 'gmgn-cli portfolio holdings failed', f'真实钱包读取失败：{exc}'


def _configured_wallet_address(root: Path) -> str:
    for key in ('GMGN_WALLET_ADDRESS', 'WALLET_ADDRESS'):
        value = os.environ.get(key)
        if value:
            return value.strip()
    local_config = _read_json_object(root / 'config/wallet.json')
    for key in ('gmgn_wallet_address', 'wallet_address'):
        value = local_config.get(key)
        if value:
            return str(value).strip()
    if root.resolve() == Path.cwd().resolve():
        try:
            value = ConfigManager().gmgn_wallet_address
        except (OSError, json.JSONDecodeError):
            value = None
        if value:
            return str(value).strip()
    return ''


def _fetch_gmgn_cli_portfolio(root: Path, wallet_address: str) -> dict[str, object]:
    holdings = _fetch_gmgn_cli_holdings(root, wallet_address, limit=50, timeout=25)
    positions = [_normalize_gmgn_holding(item) for item in holdings]
    available_balance = _fetch_gmgn_cli_native_balance(root, wallet_address)
    total_value_usd = sum(_number(position.get('value_sol')) for position in positions)
    total_unrealized_usd = sum(_number(position.get('unrealized_pnl_sol')) for position in positions)
    return {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'wallet_address': wallet_address,
        'total_value_sol': total_value_usd,
        'available_sol': available_balance,
        'daily_pnl_sol': total_unrealized_usd,
        'daily_pnl_percent': 0.0,
        'total_return_percent': 0.0,
        'positions': positions,
        'value_unit': 'USD',
        'price_unit': 'USD',
        'available_unit': 'SOL',
    }


def _fetch_gmgn_cli_native_balance(root: Path, wallet_address: str) -> float | None:
    command = ['gmgn-cli', 'portfolio', 'info', '--raw']
    result = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=25,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        payload = _parse_json_output(result.stdout)
    except ValueError:
        return None
    if not isinstance(payload, dict):
        return None
    wallets = payload.get('wallets')
    if not isinstance(wallets, list):
        return None
    for wallet in wallets:
        if not isinstance(wallet, dict):
            continue
        if wallet.get('chain') != 'sol' or wallet.get('address') != wallet_address:
            continue
        balances = wallet.get('balances')
        if not isinstance(balances, list):
            return None
        for balance in balances:
            if not isinstance(balance, dict):
                continue
            if balance.get('symbol') == 'SOL':
                return _optional_number(balance.get('balance'))
    return None


def _parse_json_output(output: str) -> object:
    text = output.strip()
    if not text:
        raise ValueError('gmgn-cli 没有返回 holdings 数据')
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        for index, char in enumerate(text):
            if char in '[{':
                try:
                    return json.loads(text[index:])
                except json.JSONDecodeError:
                    break
    raise ValueError('gmgn-cli 返回的 holdings 不是有效 JSON')


def _extract_holdings(payload: object) -> list[dict[str, object]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ('holdings', 'items', 'list'):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    data = payload.get('data')
    if isinstance(data, dict):
        return _extract_holdings(data)
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return []


def _normalize_gmgn_holding(item: dict[str, object]) -> dict[str, object]:
    token = item.get('token')
    token_data = token if isinstance(token, dict) else {}
    profit_change = _number(item.get('profit_change') or item.get('total_profit_pnl') or item.get('unrealized_profit_pnl'))
    timestamp = item.get('last_active_timestamp') or item.get('last_active_time')
    quantity = _number(item.get('balance') or item.get('amount') or item.get('ui_amount'))
    entry_price = _number(item.get('avg_cost') or item.get('cost_price'))
    if entry_price == 0.0 and quantity:
        entry_price = _number(item.get('accu_cost') or item.get('cost')) / quantity
    current_price = _optional_number(token_data.get('price') or item.get('price') or item.get('price_usd'))
    return {
        'token_address': str(token_data.get('address') or token_data.get('token_address') or item.get('token_address') or item.get('address') or ''),
        'symbol': str(token_data.get('symbol') or item.get('symbol') or 'unknown'),
        'copy_source_wallet': _position_source_wallet(item),
        'entry_price_sol': entry_price,
        'current_price_sol': current_price,
        'has_entry_price': entry_price > 0,
        'has_current_price': current_price is not None,
        'quantity': quantity,
        'value_sol': _number(item.get('usd_value') or item.get('value_usd')),
        'unrealized_pnl_sol': _number(item.get('unrealized_profit')),
        'unrealized_pnl_percent': profit_change * 100.0,
        'entry_time': '',
        'last_updated': _format_unix_timestamp(timestamp),
    }


def _format_unix_timestamp(value: object) -> str:
    number = _number(value)
    if not number:
        return ''
    return datetime.fromtimestamp(number, timezone.utc).isoformat()


def _read_portfolio_snapshot(root: Path) -> tuple[dict[str, object] | None, str]:
    direct_path = root / 'data/portfolio_snapshot.json'
    if direct_path.exists():
        payload = _read_json_object(direct_path)
        if payload:
            return payload, 'data/portfolio_snapshot.json'

    return None, 'none'


def _normalize_positions(raw_positions: object) -> list[dict[str, object]]:
    if not isinstance(raw_positions, list):
        return []
    positions: list[dict[str, object]] = []
    for item in raw_positions:
        if not isinstance(item, dict):
            continue
        token_address = str(item.get('token_address') or item.get('address') or '')
        symbol = str(item.get('symbol') or item.get('token_symbol') or token_address[:8] or 'unknown')
        entry_price = _number(item.get('entry_price_sol'))
        current_price = _optional_number(item.get('current_price_sol'))
        quantity = _number(item.get('quantity'))
        value_sol = _number(item.get('value_sol'))
        if value_sol == 0.0 and current_price is not None:
            value_sol = current_price * quantity
        unrealized = _number(item.get('unrealized_pnl_sol'))
        pnl_percent = _number(item.get('unrealized_pnl_percent'))
        cost = entry_price * quantity
        if pnl_percent == 0.0 and cost:
            pnl_percent = unrealized / cost * 100.0
        positions.append({
            'token_address': token_address,
            'symbol': symbol,
            'copy_source_wallet': _position_source_wallet(item),
            'entry_price_sol': entry_price,
            'current_price_sol': current_price,
            'has_entry_price': item.get('has_entry_price') if isinstance(item.get('has_entry_price'), bool) else entry_price > 0,
            'has_current_price': item.get('has_current_price') if isinstance(item.get('has_current_price'), bool) else current_price is not None,
            'quantity': quantity,
            'value_sol': value_sol,
            'unrealized_pnl_sol': unrealized,
            'unrealized_pnl_percent': pnl_percent,
            'entry_time': item.get('entry_time'),
            'last_updated': item.get('last_updated'),
        })
    return positions


def _position_source_wallet(item: dict[str, object]) -> str:
    for key in (
        'copy_source_wallet',
        'copy_source_wallet_address',
        'leader_wallet',
        'leader_wallet_address',
        'source_wallet',
        'source_wallet_address',
        'signal_wallet',
        'signal_wallet_address',
        'copied_from',
        'copied_from_wallet',
    ):
        value = item.get(key)
        if value:
            return str(value).strip()
    copy_source = item.get('copy_source')
    if isinstance(copy_source, dict):
        for key in ('wallet_address', 'address', 'wallet'):
            value = copy_source.get(key)
            if value:
                return str(value).strip()
    return ''


def _read_leader_lookup(root: Path) -> dict[str, dict[str, object]]:
    config = _read_json_object(root / 'config/wallet_whitelist.json')
    wallets = config.get('wallets', [])
    if not isinstance(wallets, list):
        return {}
    lookup: dict[str, dict[str, object]] = {}
    for wallet in wallets:
        if not isinstance(wallet, dict):
            continue
        address = str(wallet.get('wallet_address') or '').strip()
        if not address:
            continue
        lookup[address.lower()] = {
            'wallet_address': address,
            'label': str(wallet.get('label') or ''),
            'enabled': bool(wallet.get('enabled', True)),
        }
    return lookup


def _infer_copy_sources_from_audit(
    root: Path,
    positions: list[dict[str, object]],
) -> dict[str, str]:
    tokens = {
        str(position.get('token_address') or '').lower()
        for position in positions
        if position.get('token_address')
    }
    if not tokens:
        return {}
    audit_path = root / 'data/audit_events.jsonl'
    if not audit_path.exists():
        return {}
    inferred: dict[str, str] = {}
    try:
        lines = audit_path.read_text(encoding='utf-8').splitlines()
    except OSError:
        return {}
    for line in reversed(lines[-5000:]):
        if len(inferred) >= len(tokens):
            break
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get('action') != 'auto_buy' or event.get('success') is not True:
            continue
        details = event.get('details')
        if not isinstance(details, dict):
            continue
        signal = details.get('signal')
        if not isinstance(signal, dict):
            continue
        token = str(signal.get('target_token') or event.get('object_id') or '').lower()
        wallet = str(signal.get('wallet_address') or '').strip()
        if token in tokens and wallet and token not in inferred:
            inferred[token] = wallet
    return inferred


def _infer_copy_sources_from_whitelist(
    root: Path,
    positions: list[dict[str, object]],
    leader_lookup: dict[str, dict[str, object]],
) -> dict[str, str]:
    tokens = {
        str(position.get('token_address') or '').lower()
        for position in positions
        if position.get('token_address')
    }
    if not tokens or not shutil.which('gmgn-cli'):
        return {}
    inferred: dict[str, str] = {}
    for leader in list(leader_lookup.values())[:20]:
        wallet_address = str(leader.get('wallet_address') or '').strip()
        if not wallet_address:
            continue
        try:
            holdings = _fetch_gmgn_cli_holdings(root, wallet_address, limit=100, timeout=12)
        except (OSError, subprocess.SubprocessError, ValueError):
            continue
        for item in holdings:
            token = _holding_token_address(item).lower()
            if token in tokens and token not in inferred:
                inferred[token] = wallet_address
    return inferred


def _fetch_gmgn_cli_holdings(root: Path, wallet_address: str, limit: int, timeout: int) -> list[dict[str, object]]:
    command = [
        'gmgn-cli',
        'portfolio',
        'holdings',
        '--chain',
        'sol',
        '--wallet',
        wallet_address,
        '--limit',
        str(limit),
        '--order-by',
        'usd_value',
        '--direction',
        'desc',
        '--raw',
    ]
    result = subprocess.run(
        command,
        cwd=root,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        message = (result.stderr or result.stdout or f'gmgn-cli exited {result.returncode}').strip()
        raise ValueError(message)
    return _extract_holdings(_parse_json_output(result.stdout))


def _holding_token_address(item: dict[str, object]) -> str:
    token = item.get('token')
    token_data = token if isinstance(token, dict) else {}
    return str(
        token_data.get('address')
        or token_data.get('token_address')
        or item.get('token_address')
        or item.get('address')
        or ''
    )


def _with_copy_source(position: dict[str, object], leader_lookup: dict[str, dict[str, object]]) -> dict[str, object]:
    source_wallet = str(position.get('copy_source_wallet') or '').strip()
    if not source_wallet:
        return {
            **position,
            'copy_source_wallet': '',
            'copy_source_label': '',
            'copy_source_enabled': None,
            'copy_source_inferred': False,
        }
    leader = leader_lookup.get(source_wallet.lower(), {})
    return {
        **position,
        'copy_source_wallet': str(leader.get('wallet_address') or source_wallet),
        'copy_source_label': str(leader.get('label') or ''),
        'copy_source_enabled': leader.get('enabled') if leader else None,
        'copy_source_inferred': bool(position.get('copy_source_inferred')),
    }


def _number(value: object) -> float:
    if isinstance(value, bool):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value)
        except ValueError:
            return 0.0
    return 0.0


def _optional_number(value: object) -> float | None:
    if value is None or value == '':
        return None
    return _number(value)


def build_dashboard_payload(root: Path) -> dict[str, object]:
    root = root.resolve()
    status = build_status(
        root=root,
        max_report_age_minutes=1440,
        history_limit=5,
        require_report=True,
        require_history_current=True,
        fail_on_future_report=True,
        fail_on_stale_lock=True,
        fail_on_stale_temp_artifacts=True,
    )
    portfolio = _get_portfolio_data(root)
    return {
        'actions': [
            {
                'id': action_id,
                'label': str(config['label']),
                'command': ' '.join(build_action_command(action_id)),
            }
            for action_id, config in ACTIONS.items()
        ],
        'outputs': _read_outputs(root),
        'audit_report': build_audit_report(root),
        'data_sources': build_data_sources(root),
        'signals_summary': _read_signals_summary(root),
        'leader_pool': _read_leader_pool_state(root),
        'system_config': _read_system_config(root),
        'copy_trading_config': _read_copy_trading_config(root),
        'portfolio': portfolio,
        'token_exit_config': _read_token_exit_config(root, portfolio),
        'automation_gate': _read_automation_gate_state(root),
        'status_diagnostics': _build_status_diagnostics(status),
        'status': status,
        'user_flow': USER_FLOW,
    }


def build_action_command(action: str) -> list[str]:
    if action not in ACTIONS:
        raise ValueError(f'unknown dashboard action: {action}')
    config = ACTIONS[action]
    return [sys.executable, '-m', str(config['module']), *list(config['args'])]


def run_action(root: Path, action: str, timeout_seconds: int = 180) -> dict[str, object]:
    command = build_action_command(action)
    if not ACTION_LOCK.acquire(blocking=False):
        return {
            'command': ' '.join(command),
            'ok': False,
            'returncode': None,
            'stderr': '已有命令正在运行，请稍后再试',
            'stdout': '',
            'dashboard': build_dashboard_payload(root),
        }
    try:
        try:
            completed = subprocess.run(
                command,
                cwd=root.resolve(),
                capture_output=True,
                text=True,
                check=False,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired:
            return {
                'command': ' '.join(command),
                'ok': False,
                'returncode': None,
                'stderr': f'命令超时，超过 {timeout_seconds} 秒未完成',
                'stdout': '',
                'dashboard': build_dashboard_payload(root),
            }
        except UnicodeDecodeError as exc:
            return {
                'command': ' '.join(command),
                'ok': False,
                'returncode': None,
                'stderr': f'命令输出不是有效文本：{exc.reason}',
                'stdout': '',
                'dashboard': build_dashboard_payload(root),
            }
        except OSError as exc:
            return {
                'command': ' '.join(command),
                'ok': False,
                'returncode': None,
                'stderr': f'命令启动失败：{exc}',
                'stdout': '',
                'dashboard': build_dashboard_payload(root),
            }
        payload = build_dashboard_payload(root)
        return {
            'command': ' '.join(command),
            'ok': completed.returncode == 0,
            'returncode': completed.returncode,
            'stderr': completed.stderr,
            'stdout': completed.stdout,
            'dashboard': payload,
        }
    finally:
        ACTION_LOCK.release()


def find_available_port(host: str, preferred_port: int, max_port: int = 8999) -> int:
    for port in range(preferred_port, max_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((host, port))
            except OSError:
                continue
            return port
    raise OSError(f'no available port from {preferred_port} to {max_port}')


def serve(
    root: Path = Path('.'),
    host: str = '127.0.0.1',
    port: int = 8765,
    server_factory: Callable[[str, int, type[BaseHTTPRequestHandler]], ThreadingHTTPServer] | None = None,
) -> None:
    selected_port = find_available_port(host, port)
    handler = make_handler(root)
    factory = server_factory or DashboardHandler.create_server
    server = factory(host, selected_port, handler)
    stop_auto_stop_loss = threading.Event()
    stop_whitelist_score = threading.Event()
    auto_stop_loss_thread = _start_auto_stop_loss_monitor(root.resolve(), stop_auto_stop_loss)
    whitelist_score_thread = _start_whitelist_score_monitor(root.resolve(), stop_whitelist_score)
    print(f'GMGN dashboard: http://{host}:{selected_port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('GMGN dashboard stopped')
    finally:
        stop_auto_stop_loss.set()
        stop_whitelist_score.set()
        auto_stop_loss_thread.join(timeout=2)
        whitelist_score_thread.join(timeout=2)
        server.server_close()


def _read_outputs(root: Path) -> dict[str, dict[str, object]]:
    outputs: dict[str, dict[str, object]] = {}
    for output_id, (label, relative_path) in OUTPUTS.items():
        path = root / relative_path
        content = ''
        exists = path.exists()
        read_error = ''
        if exists:
            try:
                content = path.read_text(encoding='utf-8')
            except UnicodeDecodeError:
                read_error = '输出文件不是有效 UTF-8'
            except OSError as exc:
                read_error = f'输出文件读取失败：{exc}'
        outputs[output_id] = {
            'content': content,
            'exists': exists,
            'label': label,
            'path': str(relative_path),
            'read_error': read_error,
        }
    return outputs


def _read_signals_summary(root: Path) -> dict[str, object]:
    summary = {
        'total': 0,
        'by_decision': {},
        'by_source': {},
    }
    for relative_path in (
        Path('data/candidate_events.jsonl'),
        Path('data/dexscreener_latest_profiles_events.jsonl'),
    ):
        path = root / relative_path
        if not path.exists():
            continue
        try:
            lines = path.read_text(encoding='utf-8').splitlines()
        except (UnicodeDecodeError, OSError):
            continue
        for line in lines:
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(record, dict):
                continue
            summary['total'] += 1
            decision = str(record.get('decision') or 'unknown')
            source = str(record.get('source') or record.get('source_id') or 'unknown')
            summary['by_decision'][decision] = summary['by_decision'].get(decision, 0) + 1
            summary['by_source'][source] = summary['by_source'].get(source, 0) + 1
    return summary


def _read_system_config(root: Path) -> dict[str, object]:
    wallet_config = _read_json_object(root / 'config/wallet_whitelist.json')
    env_trade_mode = os.environ.get('GMGN_TRADE_MODE')
    config_trade_mode = wallet_config.get('trade_mode')
    trade_mode = env_trade_mode or config_trade_mode or 'dryrun'
    trade_mode_source = 'GMGN_TRADE_MODE' if env_trade_mode else 'config/wallet_whitelist.json' if config_trade_mode else 'default'
    return {
        'trade_mode': trade_mode,
        'trade_mode_source': trade_mode_source,
        'trade_mode_label': _trade_mode_label(str(trade_mode)),
        'trade_mode_note': _trade_mode_note(str(trade_mode), trade_mode_source),
        'exposure_level': wallet_config.get('exposure_level') or 'monitor',
        'exposure_level_label': _exposure_level_label(str(wallet_config.get('exposure_level') or 'monitor')),
        'max_position_sol': _first_wallet_limit(wallet_config, 'max_single_trade_sol'),
        'max_daily_loss_sol': _first_wallet_limit(wallet_config, 'max_daily_loss_sol'),
        'max_daily_trades': _first_wallet_limit(wallet_config, 'max_daily_trades'),
    }


def _read_copy_trading_config(root: Path) -> dict[str, object]:
    root = root.resolve()
    config_path = root / 'config/wallet_whitelist.json'
    config = _read_json_object(config_path)
    wallets = config.get('wallets', [])
    if not isinstance(wallets, list):
        wallets = []
    if _recalculate_copy_weights(config):
        config['updated_at'] = datetime.now(timezone.utc).isoformat()
        atomic_write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', config_path)
        wallets = config.get('wallets', [])
        if not isinstance(wallets, list):
            wallets = []
    score_report = _read_or_refresh_whitelist_score_report(root, wallets)
    score_by_wallet = {
        str(item.get('wallet_address') or '').lower(): item
        for item in score_report.get('wallets', [])
        if isinstance(item, dict)
    }
    enabled_wallets = [
        wallet for wallet in wallets
        if isinstance(wallet, dict) and wallet.get('enabled', True)
    ]
    return {
        'trade_mode': config.get('trade_mode') or 'dryrun',
        'trade_mode_label': _trade_mode_label(str(config.get('trade_mode') or 'dryrun')),
        'exposure_level': config.get('exposure_level') or 'monitor',
        'exposure_level_label': _exposure_level_label(str(config.get('exposure_level') or 'monitor')),
        'wallet_count': len(wallets),
        'enabled_wallet_count': len(enabled_wallets),
        'score_report': {
            'generated_at': score_report.get('generated_at') or '',
            'next_run_at': score_report.get('next_run_at') or '',
            'interval_hours': 3,
            'low_score_count': score_report.get('low_score_count') or 0,
            'low_score_threshold': _LOW_WALLET_SCORE_THRESHOLD,
        },
        'risk_gates': load_copy_risk(root / 'config/copy_risk.json').to_dict(),
        'wallets': [
            _copy_trading_wallet_payload(wallet, score_by_wallet)
            for wallet in wallets[:20]
            if isinstance(wallet, dict)
        ],
    }


def _copy_trading_wallet_payload(
    wallet: dict[str, object],
    score_by_wallet: dict[str, dict[str, object]],
) -> dict[str, object]:
    score_record = score_by_wallet.get(str(wallet.get('wallet_address') or '').lower(), {})
    return {
        'label': wallet.get('label') or '',
        'wallet_address': wallet.get('wallet_address') or '',
        'mode': wallet.get('mode') or '',
        'grade': score_record.get('grade') or wallet.get('grade') or '',
        'total_score': score_record.get('total_score', wallet.get('total_score')),
        'score_status': score_record.get('score_status') or 'unknown',
        'score_warning': score_record.get('warning') or '',
        'copy_weight_percent': wallet.get('copy_weight_percent') or '',
        'copy_weight': wallet.get('copy_weight'),
        'risk_limits': wallet.get('risk_limits') if isinstance(wallet.get('risk_limits'), dict) else {},
        'enabled': bool(wallet.get('enabled', True)),
    }


def _read_or_refresh_whitelist_score_report(
    root: Path,
    wallets: list[object],
    *,
    force: bool = False,
) -> dict[str, object]:
    report_path = root / 'data' / 'whitelist_score_report.json'
    current = _read_json_object(report_path)
    now = datetime.now(timezone.utc)
    generated_at = _parse_iso_datetime(str(current.get('generated_at') or ''))
    if not force and generated_at and (now - generated_at).total_seconds() < _WHITELIST_SCORE_INTERVAL_SECONDS:
        return current
    records = [
        _score_whitelist_wallet(wallet)
        for wallet in wallets
        if isinstance(wallet, dict)
    ]
    low_count = sum(1 for record in records if record.get('score_status') == 'low')
    report = {
        'generated_at': now.isoformat(),
        'next_run_at': datetime.fromtimestamp(now.timestamp() + _WHITELIST_SCORE_INTERVAL_SECONDS, timezone.utc).isoformat(),
        'interval_seconds': _WHITELIST_SCORE_INTERVAL_SECONDS,
        'low_score_threshold': _LOW_WALLET_SCORE_THRESHOLD,
        'wallet_count': len(records),
        'low_score_count': low_count,
        'wallets': records,
    }
    atomic_write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', report_path)
    return report


def _run_whitelist_score_refresh_once(root: Path) -> dict[str, object]:
    config = _read_json_object(root / 'config' / 'wallet_whitelist.json')
    wallets = config.get('wallets') if isinstance(config.get('wallets'), list) else []
    report = _read_or_refresh_whitelist_score_report(root, wallets)
    return {
        'ok': True,
        'generated_at': report.get('generated_at') or '',
        'next_run_at': report.get('next_run_at') or '',
        'wallet_count': report.get('wallet_count') or 0,
        'low_score_count': report.get('low_score_count') or 0,
    }


def _start_whitelist_score_monitor(root: Path, stop_event: threading.Event) -> threading.Thread:
    def run() -> None:
        while not stop_event.is_set():
            try:
                result = _run_whitelist_score_refresh_once(root)
                durable_append_text(
                    json.dumps({
                        'event': 'whitelist_score_refresh',
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'result': result,
                    }, ensure_ascii=False, sort_keys=True) + '\n',
                    root.resolve() / 'data/trading_log.jsonl',
                )
            except Exception as exc:
                durable_append_text(
                    json.dumps({
                        'event': 'whitelist_score_refresh_error',
                        'timestamp': datetime.now(timezone.utc).isoformat(),
                        'error': str(exc),
                    }, ensure_ascii=False, sort_keys=True) + '\n',
                    root.resolve() / 'data/trading_log.jsonl',
                )
            stop_event.wait(_WHITELIST_SCORE_INTERVAL_SECONDS)

    thread = threading.Thread(target=run, name='gmgn-whitelist-score', daemon=True)
    thread.start()
    return thread


def _score_whitelist_wallet(wallet: dict[str, object]) -> dict[str, object]:
    score = round(_number(wallet.get('total_score')), 2)
    grade = _grade_from_score(score)
    low = score < _LOW_WALLET_SCORE_THRESHOLD or grade in {'D', 'E'}
    return {
        'wallet_address': str(wallet.get('wallet_address') or ''),
        'label': str(wallet.get('label') or ''),
        'total_score': score,
        'grade': grade,
        'score_status': 'low' if low else 'ok',
        'warning': f'评分偏低：{score:.2f} / {grade}，建议暂停或人工复核。' if low else '',
    }


def _grade_from_score(score: float) -> str:
    if score >= 80:
        return 'A'
    if score >= 70:
        return 'B'
    if score >= 60:
        return 'C'
    if score >= 40:
        return 'D'
    return 'E'


def _parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _build_status_diagnostics(status: dict[str, object]) -> dict[str, object]:
    failed_steps: list[str] = []
    for step in status.get('report_steps', []) or []:
        if isinstance(step, dict) and step.get('status') != 'ok':
            failed_steps.append(str(step.get('name') or 'unknown'))
    history = status.get('history', {})
    last_step_statuses = history.get('last_step_statuses', {}) if isinstance(history, dict) else {}
    if not failed_steps and isinstance(last_step_statuses, dict):
        failed_steps = [
            name for name, step_status in last_step_statuses.items()
            if step_status != 'ok'
        ]
    reasons = list(status.get('doctor_failures', []) or [])
    if not reasons and failed_steps:
        reasons.append('verification report contains failed steps')
    return {
        'failed_steps': failed_steps,
        'reasons': reasons,
        'report_status': status.get('report_status'),
        'report_steps_complete': status.get('report_steps_complete'),
        'report_matches_latest_history': status.get('report_matches_latest_history'),
    }


def _read_json_object(path: Path) -> dict[str, object]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _read_json_list(path: Path) -> list[object]:
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding='utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError, OSError):
        return []
    return payload if isinstance(payload, list) else []


def _default_leader_pool_config() -> dict[str, object]:
    return {
        'discovery_target': 500,
        'high_quality_target': 40,
        'whitelist_target': 10,
        'backtest_target': 10,
        'min_score': 65.0,
        'min_win_rate_percent': 60.0,
        'min_total_trades': 50,
        'score_batch_size': 10,
        'score_concurrency': 4,
        'lookback_windows': ['7d', '14d', '30d'],
    }


def _read_leader_pool_config(root: Path) -> dict[str, object]:
    config = _default_leader_pool_config()
    stored = _read_json_object(root / 'config/leader_pool.json')
    for key in config:
        if key in stored:
            config[key] = stored[key]
    windows = config.get('lookback_windows')
    if not isinstance(windows, list) or not windows:
        config['lookback_windows'] = ['7d', '14d', '30d']
    else:
        config['lookback_windows'] = [str(item) for item in windows if str(item).strip()]
    return config


def _update_leader_pool_config(root: Path, payload: dict[str, object]) -> dict[str, object]:
    root = root.resolve()
    config = {
        'discovery_target': int(_bounded_number(payload.get('discovery_target'), 1, 100000, 'discovery_target')),
        'high_quality_target': int(_bounded_number(payload.get('high_quality_target'), 1, 10000, 'high_quality_target')),
        'whitelist_target': int(_bounded_number(payload.get('whitelist_target'), 1, 10000, 'whitelist_target')),
        'backtest_target': int(_bounded_number(payload.get('backtest_target'), 1, 10000, 'backtest_target')),
        'min_score': _bounded_number(payload.get('min_score'), 0, 100, 'min_score'),
        'min_win_rate_percent': _bounded_number(payload.get('min_win_rate_percent'), 0, 100, 'min_win_rate_percent'),
        'min_total_trades': int(_bounded_number(payload.get('min_total_trades'), 1, 1000000, 'min_total_trades')),
        'score_batch_size': int(_bounded_number(payload.get('score_batch_size'), 1, 1000, 'score_batch_size')),
        'score_concurrency': int(_bounded_number(payload.get('score_concurrency'), 1, 20, 'score_concurrency')),
        'lookback_windows': _parse_leader_pool_windows(payload.get('lookback_windows')),
    }
    atomic_write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', root / 'config/leader_pool.json')
    append_audit_event(
        root,
        category='manual_config',
        action='leader_pool_config_update',
        success=True,
        source='dashboard',
        actor='user',
        object_type='config',
        object_id='config/leader_pool.json',
        message='Leader 池目标和筛选参数已保存',
        details={'config': config},
    )
    return {'ok': True, 'leader_pool': _read_leader_pool_state(root)}


def _promote_single_leader_to_copy_whitelist(root: Path, payload: dict[str, object]) -> dict[str, object]:
    wallet_address = str(payload.get('wallet_address') or '').strip()
    if not wallet_address:
        raise ValueError('wallet_address is required')
    root = root.resolve()
    config_path = root / 'config/wallet_whitelist.json'
    config = _read_json_object(config_path)
    wallets = config.get('wallets', [])
    if not isinstance(wallets, list):
        raise ValueError('wallet_whitelist.json wallets must be a list')
    existing = {
        str(wallet.get('wallet_address') or '').lower()
        for wallet in wallets
        if isinstance(wallet, dict) and wallet.get('wallet_address')
    }
    if wallet_address.lower() in existing:
        return {'ok': True, 'message': '该 Leader 已在跟单白名单中。', 'wallet_address': wallet_address}
    if len(wallets) >= _MAX_COPY_WHITELIST_LEADERS:
        return {
            'ok': False,
            'error': f'跟单白名单最多 {_MAX_COPY_WHITELIST_LEADERS} 个，当前已满，无法加入。',
            'wallet_address': wallet_address,
            'limit': _MAX_COPY_WHITELIST_LEADERS,
            'current': len(wallets),
        }
    candidates = _dedupe_wallet_records(_read_json_list(root / 'data/whitelist_wallets.json'))
    candidate = next(
        (wallet for wallet in candidates if str(wallet.get('wallet_address') or '').lower() == wallet_address.lower()),
        None,
    )
    if candidate is None:
        raise ValueError('该 Leader 不在评分白名单中，无法人工加入跟单白名单。')
    wallets.append(_copy_whitelist_wallet_from_scored_leader(candidate, len(wallets) + 1))
    config['wallets'] = wallets
    config.setdefault('version', '1.0')
    config.setdefault('description', 'GMGN leader whitelist')
    config['updated_at'] = datetime.now(timezone.utc).isoformat()
    _recalculate_copy_weights(config)
    atomic_write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', config_path)
    append_audit_event(
        root,
        category='manual_config',
        action='leader_promote_to_copy_whitelist',
        success=True,
        source='dashboard',
        actor='user',
        object_type='leader',
        object_id=wallet_address,
        message='评分白名单 Leader 已人工加入跟单白名单',
        details={'current': len(wallets), 'limit': _MAX_COPY_WHITELIST_LEADERS},
    )
    return {
        'ok': True,
        'message': f'已加入跟单白名单：{_short_address(wallet_address)}，当前 {len(wallets)}/{_MAX_COPY_WHITELIST_LEADERS}。',
        'wallet_address': wallet_address,
        'current': len(wallets),
        'limit': _MAX_COPY_WHITELIST_LEADERS,
    }


def _recycle_scored_leader_to_candidates(root: Path, payload: dict[str, object]) -> dict[str, object]:
    wallet_address = str(payload.get('wallet_address') or '').strip()
    if not wallet_address:
        raise ValueError('wallet_address is required')
    root = root.resolve()
    scored_path = root / 'data/whitelist_wallets.json'
    candidate_path = root / 'data/candidate_wallets_smartmoney.json'
    backtest_path = root / 'data/leader_backtest_results.json'
    config_path = root / 'config/wallet_whitelist.json'

    scored_records = _read_json_list(scored_path)
    recycled: dict[str, object] | None = None
    remaining_scored: list[object] = []
    for record in scored_records:
        if isinstance(record, dict) and str(record.get('wallet_address') or record.get('address') or '').lower() == wallet_address.lower():
            recycled = {**record, 'wallet_address': wallet_address}
            continue
        remaining_scored.append(record)
    if recycled is None:
        raise ValueError('该 Leader 不在评分白名单中。')

    candidate_records = _read_json_list(candidate_path)
    candidate_addresses = {
        str(record.get('wallet_address') or record.get('address') or '').lower()
        for record in candidate_records
        if isinstance(record, dict)
    }
    if wallet_address.lower() not in candidate_addresses:
        candidate_records.append({
            'wallet_address': wallet_address,
            'address': wallet_address,
            'tags': recycled.get('tags') if isinstance(recycled.get('tags'), list) else ['leader_pool_recycled'],
            'source': recycled.get('source') or 'leader_pool_recycled',
            'recycled_at': datetime.now(timezone.utc).isoformat(),
        })

    config = _read_json_object(config_path)
    wallets = config.get('wallets', [])
    if isinstance(wallets, list):
        config['wallets'] = [
            wallet for wallet in wallets
            if not (
                isinstance(wallet, dict)
                and str(wallet.get('wallet_address') or '').lower() == wallet_address.lower()
            )
        ]
        _recalculate_copy_weights(config)
        config['updated_at'] = datetime.now(timezone.utc).isoformat()
        atomic_write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', config_path)

    backtest_records = [
        record for record in _read_json_list(backtest_path)
        if not (
            isinstance(record, dict)
            and str(record.get('wallet_address') or '').lower() == wallet_address.lower()
        )
    ]
    atomic_write_text(json.dumps(remaining_scored, ensure_ascii=False, indent=2) + '\n', scored_path)
    atomic_write_text(json.dumps(candidate_records, ensure_ascii=False, indent=2) + '\n', candidate_path)
    atomic_write_text(json.dumps(backtest_records, ensure_ascii=False, indent=2) + '\n', backtest_path)
    append_audit_event(
        root,
        category='manual_config',
        action='leader_recycle_to_candidates',
        success=True,
        source='dashboard',
        actor='user',
        object_type='leader',
        object_id=wallet_address,
        message='评分白名单 Leader 已退回扫链候选',
        details={'removed_from_copy_whitelist': isinstance(wallets, list)},
    )
    return {
        'ok': True,
        'message': f'已将 {_short_address(wallet_address)} 从评分白名单退回扫链候选。',
        'wallet_address': wallet_address,
    }


def _copy_whitelist_wallet_from_scored_leader(candidate: dict[str, object], index: int) -> dict[str, object]:
    address = str(candidate.get('wallet_address') or candidate.get('address') or '').strip()
    stats = candidate.get('stats')
    if not isinstance(stats, dict):
        stats = {}
    return {
        'wallet_address': address,
        'label': f'leader_pool_manual_{index}',
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
        'notes': '评分白名单人工加入；默认 observe 且暂停，需在跟单配置中启用。',
    }


def _run_leader_pool_action(root: Path, payload: dict[str, object]) -> dict[str, object]:
    root = root.resolve()
    action = str(payload.get('action') or '').strip()
    config = _read_leader_pool_config(root)
    try:
        if action == 'loop_once':
            result = _run_leader_pool_loop_once(root, config, payload)
        if action == 'discover':
            result = discover_leaders(
                root,
                target=int(payload.get('target') or config['discovery_target']),
                chain=str(payload.get('chain') or 'sol'),
            )
        elif action == 'score':
            result = score_leaders(
                root,
                min_score=_number(config.get('min_score')),
                min_win_rate_percent=_number(config.get('min_win_rate_percent')),
                min_total_trades=int(config.get('min_total_trades') or 1),
                lookback_windows=[str(item) for item in config.get('lookback_windows', [])],
                score_batch_size=int(config.get('score_batch_size') or 10),
                score_concurrency=int(config.get('score_concurrency') or 1),
                chain=str(payload.get('chain') or 'sol'),
            )
        elif action == 'promote':
            result = promote_leaders(
                root,
                target=int(config['whitelist_target']),
                min_score=_number(config.get('min_score')),
                min_win_rate_percent=_number(config.get('min_win_rate_percent')),
                min_total_trades=int(config.get('min_total_trades') or 1),
            )
        elif action == 'backtest':
            result = backtest_leaders(
                root,
                target=int(config['backtest_target']),
                min_score=_number(config.get('min_score')),
                min_win_rate_percent=_number(config.get('min_win_rate_percent')),
                min_total_trades=int(config.get('min_total_trades') or 1),
            )
        elif action != 'loop_once':
            raise ValueError('unsupported leader pool action')
        append_audit_event(
            root,
            category='manual_config',
            action=f'leader_pool_{action}',
            success=bool(result.get('ok', True)) if isinstance(result, dict) else True,
            source='dashboard',
            actor='user',
            object_type='leader_pool',
            object_id=action,
            message=str(result.get('message') or _leader_pool_action_label(action)) if isinstance(result, dict) else action,
            details={'payload': payload, 'result': result},
        )
        return result
    except Exception as exc:
        result = {'action': action, 'ok': False, 'message': str(exc)}
        atomic_write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', root / 'data/leader_pool_last_action.json')
        append_audit_event(
            root,
            category='manual_config',
            action=f'leader_pool_{action or "unknown"}',
            success=False,
            source='dashboard',
            actor='user',
            object_type='leader_pool',
            object_id=action,
            message=str(exc),
            details={'payload': payload, 'result': result},
        )
        return result


def _run_leader_pool_loop_once(root: Path, config: dict[str, object], payload: dict[str, object]) -> dict[str, object]:
    state = _read_leader_pool_state(root)
    next_action = state.get('next_action')
    if not isinstance(next_action, dict):
        raise ValueError('leader pool next action unavailable')
    selected = str(next_action.get('action') or '')
    if selected == 'complete':
        result = {'action': 'loop_once', 'ok': True, 'message': 'Leader 池目标已全部完成。', 'selected_action': 'complete'}
        _write_leader_pool_loop_state(root, result)
        return result
    if next_action.get('blocked'):
        result = {
            'action': 'loop_once',
            'ok': False,
            'message': str(next_action.get('reason') or 'Leader 池下一步被阻塞。'),
            'selected_action': selected,
        }
        _write_leader_pool_loop_state(root, result)
        return result
    target = next_action.get('target')
    action_payload = {**payload, 'action': selected}
    if target is not None:
        action_payload['target'] = target
    result = _run_leader_pool_action(root, action_payload)
    loop_result = {
        'action': 'loop_once',
        'ok': bool(result.get('ok')),
        'message': f"推进下一步：{_leader_pool_action_label(selected)}；{result.get('message') or ''}",
        'selected_action': selected,
        'result': result,
    }
    _write_leader_pool_loop_state(root, loop_result)
    return loop_result


def _parse_leader_pool_windows(value: object) -> list[str]:
    if isinstance(value, list):
        windows = [str(item).strip() for item in value]
    else:
        windows = [item.strip() for item in str(value or '').split(',')]
    windows = [item for item in windows if item]
    return windows or ['7d', '14d', '30d']


def _write_leader_pool_loop_state(root: Path, result: dict[str, object]) -> None:
    payload = {
        **result,
        'generated_at': datetime.now(timezone.utc).isoformat(),
    }
    atomic_write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
        root / 'data' / 'leader_pool_loop_state.json',
    )
    atomic_write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + '\n',
        root / 'data' / 'leader_pool_last_action.json',
    )


def _read_leader_pool_state(root: Path) -> dict[str, object]:
    root = root.resolve()
    config = _read_leader_pool_config(root)
    discovered = _dedupe_wallet_records(_read_json_list(root / 'data/candidate_wallets_smartmoney.json'))
    whitelist_records = _read_json_list(root / 'data/whitelist_wallets.json')
    watchlist_records = _read_json_list(root / 'data/watchlist_wallets.json')
    blacklist_records = _read_json_list(root / 'data/blacklist_wallets.json')
    scored = _dedupe_wallet_records(whitelist_records + watchlist_records + blacklist_records)
    scored_positive = _dedupe_wallet_records(whitelist_records + watchlist_records)
    whitelist_config = _read_json_object(root / 'config/wallet_whitelist.json')
    whitelist_wallets = whitelist_config.get('wallets', [])
    if not isinstance(whitelist_wallets, list):
        whitelist_wallets = []
    configured_records = _dedupe_wallet_records(whitelist_wallets)
    configured_addresses = {
        str(wallet.get('wallet_address') or '').lower()
        for wallet in configured_records
        if wallet.get('wallet_address')
    }
    classified_addresses = {
        str(wallet.get('wallet_address') or wallet.get('address') or '').lower()
        for wallet in whitelist_records + watchlist_records + blacklist_records + configured_records
        if isinstance(wallet, dict) and (wallet.get('wallet_address') or wallet.get('address'))
    }
    remaining_candidates = [
        wallet for wallet in discovered
        if str(wallet.get('wallet_address') or wallet.get('address') or '').lower() not in classified_addresses
    ]
    high_quality = [
        wallet for wallet in scored_positive
        if _leader_meets_quality(wallet, config)
    ]
    high_quality.sort(key=lambda item: _number(item.get('total_score')), reverse=True)
    backtest_records = _dedupe_wallet_records(_read_json_list(root / 'data/leader_backtest_results.json'))
    backtest_count = len(backtest_records)
    backtest_events = _count_jsonl_lines(root / 'logs/loop/backtest_calibration.log')
    stages = [
        _leader_pool_stage('扫链引入', len(discovered), int(config['discovery_target']), '目标让更多 leader 钱包进入候选池'),
        _leader_pool_stage('高质量候选', len(high_quality), int(config['high_quality_target']), '按分数、胜率和交易样本筛选'),
        _leader_pool_stage('升级白名单', len(whitelist_wallets), int(config['whitelist_target']), '进入 config/wallet_whitelist.json 的跟单 leader'),
        _leader_pool_stage('评分回测', min(backtest_count, int(config['backtest_target'])), int(config['backtest_target']), '统计 data/leader_backtest_results；校准日志仅作参考'),
    ]
    counts = {
        'discovered': len(discovered),
        'scored': len(scored),
        'high_quality': len(high_quality),
        'whitelisted': len(whitelist_wallets),
        'backtested': backtest_count,
        'backtest_calibration_events': backtest_events,
    }
    last_action = _read_json_object(root / 'data/leader_pool_last_action.json')
    return {
        'config': config,
        'stages': stages,
        'counts': counts,
        'quality_summary': _leader_pool_quality_summary(counts, config),
        'source_quality': _leader_pool_source_quality(discovered, whitelist_records, watchlist_records, blacklist_records, config),
        'next_action': _leader_pool_next_action(counts, config, last_action),
        'copy_whitelist_limit': _MAX_COPY_WHITELIST_LEADERS,
        'prerequisites': {
            'gmgn_api_key_configured': _gmgn_api_key_configured(),
        },
        'loop_state': _read_json_object(root / 'data/leader_pool_loop_state.json'),
        'last_action': last_action,
        'top_leaders': [_leader_pool_wallet_payload(wallet) for wallet in high_quality[:10]],
        'funnel': [
            _leader_pool_funnel_stage('candidates', '扫链候选', len(discovered), '进入候选池，等待评分筛选'),
            _leader_pool_funnel_stage('rejected', '淘汰剩余名单', len(remaining_candidates), '遗留的剩余候选，尚未进入观察、评分白名单或跟单白名单'),
            _leader_pool_funnel_stage('watch', '观察', len(watchlist_records), '暂不跟单，继续观察'),
            _leader_pool_funnel_stage('scored_whitelist', '评分白名单', len(whitelist_records), '评分通过，可人工加入跟单白名单'),
            _leader_pool_funnel_stage('copy_whitelist', '跟单白名单', len(configured_records), f'最多 {_MAX_COPY_WHITELIST_LEADERS} 个，进入实际跟单配置'),
        ],
        'funnel_lists': {
            'candidates': [_leader_pool_wallet_payload(wallet, configured_addresses) for wallet in discovered],
            'rejected': [_leader_pool_wallet_payload(wallet, configured_addresses) for wallet in remaining_candidates],
            'watch': [_leader_pool_wallet_payload(wallet, configured_addresses) for wallet in watchlist_records],
            'scored_whitelist': [_leader_pool_wallet_payload(wallet, configured_addresses) for wallet in whitelist_records],
            'copy_whitelist': [_leader_pool_wallet_payload(wallet, configured_addresses) for wallet in configured_records],
        },
        'backtest': {
            'label': '评分回测',
            'path': 'data/leader_backtest_results.json',
            'count': backtest_count,
            'calibration_events': backtest_events,
            'leaders': [_leader_pool_wallet_payload(wallet, configured_addresses) for wallet in backtest_records],
        },
        'sources': [
            {'label': '扫链候选', 'path': 'data/candidate_wallets_smartmoney.json', 'count': len(discovered)},
            {'label': '评分白名单', 'path': 'data/whitelist_wallets.json', 'count': len(_read_json_list(root / 'data/whitelist_wallets.json'))},
            {'label': '观察名单', 'path': 'data/watchlist_wallets.json', 'count': len(_read_json_list(root / 'data/watchlist_wallets.json'))},
            {'label': '淘汰名单', 'path': 'data/blacklist_wallets.json', 'count': len(blacklist_records)},
            {'label': '跟单白名单', 'path': 'config/wallet_whitelist.json', 'count': len(whitelist_wallets)},
            {'label': '评分回测', 'path': 'data/leader_backtest_results.json', 'count': backtest_count},
        ],
    }


def _leader_pool_next_action(
    counts: dict[str, object],
    config: dict[str, object],
    last_action: dict[str, object] | None = None,
) -> dict[str, object]:
    discovered = int(counts.get('discovered') or 0)
    scored = int(counts.get('scored') or 0)
    high_quality = int(counts.get('high_quality') or 0)
    whitelisted = int(counts.get('whitelisted') or 0)
    backtested = int(counts.get('backtested') or 0)
    discovery_target = int(config.get('discovery_target') or 0)
    high_quality_target = int(config.get('high_quality_target') or 0)
    last_discover_added = None
    if isinstance(last_action, dict):
        discover_action = last_action
        nested_result = last_action.get('result')
        if last_action.get('action') == 'loop_once' and isinstance(nested_result, dict):
            discover_action = nested_result
        if discover_action.get('action') == 'discover':
            last_discover_added = int(discover_action.get('added') or 0)
    if discovered < discovery_target:
        if last_discover_added == 0 and scored < discovered:
            return _leader_pool_action_status(
                'score',
                '扩池暂未新增钱包，先评分当前未评分候选，避免空转。',
                needs_api_key=True,
            )
        return _leader_pool_action_status('discover', '继续扫链扩池，把更多 leader 钱包加入候选池。', needs_api_key=True)
    if high_quality < high_quality_target:
        if scored >= min(discovered, 100):
            hit_rate = high_quality / scored if scored else 0.0
            projected = discovered * hit_rate if hit_rate > 0 else 0.0
            if projected < high_quality_target:
                if last_discover_added == 0 and scored < discovered:
                    return _leader_pool_action_status(
                        'score',
                        '高质量命中率偏低，但本轮扩池无新增；先评分现有未评分候选。',
                        needs_api_key=True,
                    )
                expanded_target = discovered + max(100, discovery_target)
                status = _leader_pool_action_status(
                    'discover',
                    '当前候选命中率预计不足以达到高质量目标，优先继续扩池寻找更强 leader。',
                    needs_api_key=True,
                )
                status['target'] = expanded_target
                return status
        if discovered > 0 and scored >= discovered:
            expanded_target = discovered + max(100, discovery_target)
            status = _leader_pool_action_status(
                'discover',
                '当前候选已全部评分但高质量不足，继续扩池寻找更多 leader 钱包。',
                needs_api_key=True,
            )
            status['target'] = expanded_target
            return status
        return _leader_pool_action_status('score', '继续按 7d/14d/30d 窗口评分，筛出高质量 leader。', needs_api_key=True)
    if whitelisted < int(config.get('whitelist_target') or 0):
        return _leader_pool_action_status('promote', '把高质量 leader 晋级到跟单白名单，默认 observe 且暂停。')
    if backtested < int(config.get('backtest_target') or 0):
        return _leader_pool_action_status('backtest', '对 leader 池和白名单做评分回测。')
    return {
        'action': 'complete',
        'label': '目标完成',
        'reason': 'Leader 池四阶段目标均已达到。',
        'blocked': False,
        'needs_api_key': False,
    }


def _leader_pool_quality_summary(counts: dict[str, object], config: dict[str, object]) -> dict[str, object]:
    discovered = int(counts.get('discovered') or 0)
    scored = int(counts.get('scored') or 0)
    high_quality = int(counts.get('high_quality') or 0)
    target = int(config.get('high_quality_target') or 0)
    hit_rate = high_quality / scored if scored else 0.0
    projected = discovered * hit_rate if scored else 0.0
    estimated_required = math.ceil(target / hit_rate) if hit_rate > 0 and target > 0 else None
    recommendation = ''
    if scored and target and high_quality < target and projected < target:
        recommendation = '当前候选质量命中率不足，完成本池评分后需要继续扩池。'
    return {
        'scoring_coverage_percent': round(scored / discovered * 100, 2) if discovered else 0.0,
        'high_quality_hit_rate_percent': round(hit_rate * 100, 2),
        'projected_high_quality_at_current_pool': round(projected, 2),
        'estimated_candidates_needed': estimated_required,
        'recommendation': recommendation,
    }


def _leader_pool_source_quality(
    discovered: list[dict[str, object]],
    whitelist_records: list[object],
    watchlist_records: list[object],
    blacklist_records: list[object],
    config: dict[str, object],
) -> list[dict[str, object]]:
    candidate_counts: dict[str, int] = {}
    for wallet in discovered:
        if not isinstance(wallet, dict):
            continue
        source = _leader_source_label(wallet.get('source'))
        candidate_counts[source] = candidate_counts.get(source, 0) + 1

    buckets: dict[str, dict[str, object]] = {}
    for source, count in candidate_counts.items():
        buckets[source] = {
            'source': source,
            'candidates': count,
            'scored': 0,
            'high_quality': 0,
            'near_quality': 0,
            'watch': 0,
            'rejected': 0,
        }

    for bucket_name, records in (
        ('whitelist', whitelist_records),
        ('watch', watchlist_records),
        ('rejected', blacklist_records),
    ):
        for wallet in records:
            if not isinstance(wallet, dict):
                continue
            source = _leader_source_label(wallet.get('source'))
            entry = buckets.setdefault(source, {
                'source': source,
                'candidates': candidate_counts.get(source, 0),
                'scored': 0,
                'high_quality': 0,
                'near_quality': 0,
                'watch': 0,
                'rejected': 0,
            })
            entry['scored'] = int(entry.get('scored') or 0) + 1
            if bucket_name == 'watch':
                entry['watch'] = int(entry.get('watch') or 0) + 1
            if bucket_name == 'rejected':
                entry['rejected'] = int(entry.get('rejected') or 0) + 1
            if _leader_meets_quality(wallet, config):
                entry['high_quality'] = int(entry.get('high_quality') or 0) + 1
            elif _leader_near_quality(wallet, config):
                entry['near_quality'] = int(entry.get('near_quality') or 0) + 1

    rows: list[dict[str, object]] = []
    for entry in buckets.values():
        scored = int(entry.get('scored') or 0)
        high_quality = int(entry.get('high_quality') or 0)
        near_quality = int(entry.get('near_quality') or 0)
        candidates = int(entry.get('candidates') or 0)
        hit_rate = high_quality / scored if scored else 0.0
        near_rate = (high_quality + near_quality) / scored if scored else 0.0
        recommendation = '继续评分'
        if scored >= 20 and high_quality == 0 and near_quality == 0:
            recommendation = '降权或兜底'
        elif scored >= 20 and near_quality > high_quality:
            recommendation = '保留观察'
        rows.append({
            **entry,
            'coverage_percent': round(min(100.0, scored / candidates * 100), 2) if candidates else 0.0,
            'hit_rate_percent': round(hit_rate * 100, 2),
            'near_rate_percent': round(near_rate * 100, 2),
            'recommendation': recommendation,
        })
    return sorted(
        rows,
        key=lambda item: (
            float(item.get('hit_rate_percent') or 0),
            float(item.get('near_rate_percent') or 0),
            int(item.get('scored') or 0),
            int(item.get('candidates') or 0),
        ),
        reverse=True,
    )


def _leader_source_label(source: object) -> str:
    value = str(source or '').strip()
    return value or 'unknown'


def _leader_near_quality(wallet: dict[str, object], config: dict[str, object]) -> bool:
    stats = wallet.get('stats')
    if not isinstance(stats, dict):
        stats = {}
    min_score = _number(config.get('min_score'))
    min_win_rate = _number(config.get('min_win_rate_percent'))
    min_trades = _number(config.get('min_total_trades'))
    return (
        _number(wallet.get('total_score')) >= max(0.0, min_score - 10.0)
        and _number(stats.get('winrate')) >= max(0.0, min_win_rate - 5.0)
        and _number(stats.get('total_trades')) >= min_trades
    )


def _leader_pool_action_status(action: str, reason: str, needs_api_key: bool = False) -> dict[str, object]:
    blocked = needs_api_key and not _gmgn_api_key_configured()
    return {
        'action': action,
        'label': _leader_pool_action_label(action),
        'reason': 'GMGN_API_KEY 未配置，无法执行真实扫链或评分。' if blocked else reason,
        'blocked': blocked,
        'needs_api_key': needs_api_key,
    }


def _leader_pool_action_label(action: str) -> str:
    return {
        'discover': '扫链扩池',
        'score': '评分筛选',
        'promote': '升级白名单',
        'backtest': '评分回测',
        'loop_once': '推进下一步',
    }.get(action, action)


def _gmgn_api_key_configured() -> bool:
    if os.environ.get('GMGN_API_KEY'):
        return True
    try:
        return bool(ConfigManager().gmgn_api_key)
    except Exception:
        return False


def _dedupe_wallet_records(records: list[object]) -> list[dict[str, object]]:
    deduped: dict[str, dict[str, object]] = {}
    for record in records:
        if not isinstance(record, dict):
            continue
        address = str(record.get('wallet_address') or record.get('address') or '').strip()
        if not address:
            continue
        deduped[address.lower()] = {**record, 'wallet_address': address}
    return list(deduped.values())


def _leader_meets_quality(wallet: dict[str, object], config: dict[str, object]) -> bool:
    stats = wallet.get('stats')
    if not isinstance(stats, dict):
        stats = {}
    return (
        _number(wallet.get('total_score')) >= _number(config.get('min_score'))
        and _number(stats.get('winrate')) >= _number(config.get('min_win_rate_percent'))
        and _number(stats.get('total_trades')) >= _number(config.get('min_total_trades'))
    )


def _leader_pool_stage(label: str, current: int, target: int, note: str) -> dict[str, object]:
    progress = 0.0 if target <= 0 else min(100.0, current / target * 100.0)
    return {
        'label': label,
        'current': current,
        'target': target,
        'progress_percent': round(progress, 1),
        'remaining': max(0, target - current),
        'note': note,
    }


def _leader_pool_funnel_stage(key: str, label: str, count: int, note: str) -> dict[str, object]:
    return {
        'key': key,
        'label': label,
        'count': count,
        'note': note,
    }


def _leader_pool_wallet_payload(
    wallet: dict[str, object],
    configured_addresses: set[str] | None = None,
) -> dict[str, object]:
    configured_addresses = configured_addresses or set()
    stats = wallet.get('stats')
    if not isinstance(stats, dict):
        stats = wallet.get('stats_snapshot')
    if not isinstance(stats, dict):
        stats = {}
    wallet_address = str(wallet.get('wallet_address') or '')
    return {
        'wallet_address': wallet_address,
        'total_score': wallet.get('total_score'),
        'grade': wallet.get('grade') or '',
        'decision': wallet.get('decision') or '',
        'winrate': stats.get('winrate') if stats.get('winrate') is not None else wallet.get('winrate'),
        'total_trades': stats.get('total_trades') if stats.get('total_trades') is not None else wallet.get('total_trades'),
        'realized_profit': stats.get('realized_profit') if stats.get('realized_profit') is not None else wallet.get('realized_profit'),
        'avg_holding_hours': stats.get('avg_holding_hours'),
        'backtest_score': wallet.get('backtest_score'),
        'passed': wallet.get('passed'),
        'reason': wallet.get('reason') or '',
        'in_copy_whitelist': wallet_address.lower() in configured_addresses if wallet_address else False,
        'tags': wallet.get('tags') if isinstance(wallet.get('tags'), list) else [],
    }


def _count_jsonl_lines(path: Path) -> int:
    if not path.exists():
        return 0
    try:
        return sum(1 for line in path.read_text(encoding='utf-8').splitlines() if line.strip())
    except (UnicodeDecodeError, OSError):
        return 0


def _read_leader_backtest_count(root: Path) -> int:
    json_path = root / 'data/leader_backtest_results.json'
    jsonl_path = root / 'data/leader_backtest_results.jsonl'
    records = _read_json_list(json_path)
    if records:
        return len(_dedupe_wallet_records(records))
    return _count_jsonl_lines(jsonl_path)


def _first_wallet_limit(config: dict[str, object], key: str) -> object:
    wallets = config.get('wallets', [])
    if not isinstance(wallets, list) or not wallets:
        return None
    wallet = wallets[0]
    if not isinstance(wallet, dict):
        return None
    limits = wallet.get('risk_limits', {})
    if not isinstance(limits, dict):
        return None
    return limits.get(key)


def _trade_mode_label(mode: str) -> str:
    labels = {
        'paper': 'Paper（真实信号，模拟成交）',
        'dryrun': 'Dry Run（安全模拟）',
        'dry_run': 'Dry Run（安全模拟）',
        'real': 'Real（小额真实配置）',
    }
    return labels.get(mode, mode or '未知')


def _status_label(status: str) -> str:
    labels = {
        'ok': '通过',
        'blocked': '已阻断',
        'fail': '失败',
        'eligible_for_tiny_size_testing': '可小额测试',
        'auto_trading_enabled': '自动交易已启用',
        'unknown': '未知',
    }
    return labels.get(status, status or '未知')


def _exposure_level_label(level: str) -> str:
    labels = {
        'tiny_real': '微型真实',
        'monitor': '监控',
        'observe': '观察',
        'dryrun': '模拟',
        'dry_run': '模拟',
    }
    return labels.get(level, level or '未知')


def _trade_mode_note(mode: str, source: str) -> str:
    if mode == 'paper':
        return f'来自 {source}；读取真实 leader 成交，只做模拟跟单，不会提交链上交易。'
    if mode in ('dryrun', 'dry_run'):
        return f'来自 {source}；只生成计划和报告，不会真实下单。'
    if mode == 'real':
        return (
            f'来自 {source}；真实跟单只提交 30 分钟内的信号。'
            '自动化闸门打开且单笔不超过额度时，才允许小额自动确认。'
        )
    return f'来自 {source}；请检查配置值是否符合预期。'


def build_data_sources(root: Path) -> list[dict[str, object]]:
    return [
        {**source, 'health': _source_health(root, source)}
        for source in DATA_SOURCES
    ]


def _source_health(root: Path, source: dict[str, object]) -> str:
    kind = source.get('kind')
    if kind == 'jsonl':
        path = root / str(source['path'])
        return _jsonl_health(path)
    if kind == 'jsonl_group':
        details = [
            f'{Path(path).name}: {_jsonl_health(root / str(path))}'
            for path in source.get('paths', [])
        ]
        return '；'.join(details)
    if kind == 'dexscreener':
        details = [
            f'{Path(path).name}: {_dexscreener_health(root / str(path))}'
            for path in source.get('paths', [])
        ]
        return '；'.join(details)
    if kind == 'planned_doc':
        return _file_health(root / str(source['path']))
    return '待接入'


def _jsonl_health(path: Path) -> str:
    if not path.exists():
        return '缺失'
    try:
        lines = path.read_text(encoding='utf-8').splitlines()
    except UnicodeDecodeError:
        return '格式错误，不是有效 UTF-8'
    except OSError as exc:
        return f'读取失败：{exc}'
    count = 0
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            record = json.loads(stripped)
        except json.JSONDecodeError:
            return f'格式错误，第 {line_number} 行不是有效 JSON'
        if not isinstance(record, dict):
            return f'格式错误，第 {line_number} 行不是对象'
        count += 1
    return f'可用，{count} 条记录'


def _dexscreener_health(path: Path) -> str:
    if path.suffix == '.jsonl':
        return _jsonl_health(path)
    if path.suffix == '.json':
        return _dexscreener_payload_health(path)
    return _file_health(path)


def _dexscreener_payload_health(path: Path) -> str:
    if not path.exists():
        return '缺失'
    try:
        if path.stat().st_size == 0:
            return '空文件'
        payload = json.loads(path.read_text(encoding='utf-8'))
    except UnicodeDecodeError:
        return '格式错误，不是有效 UTF-8'
    except json.JSONDecodeError:
        return '格式错误，不是有效 JSON'
    except OSError as exc:
        return f'读取失败：{exc}'
    if not isinstance(payload, dict):
        return '格式错误，不是对象'
    pairs = payload.get('pairs', [])
    if not isinstance(pairs, list):
        return '格式错误，pairs 不是列表'
    for index, pair in enumerate(pairs, start=1):
        if not isinstance(pair, dict):
            return f'格式错误，第 {index} 个 pair 不是对象'
    return f'可用，{len(pairs)} 个 pairs'


def _file_health(path: Path) -> str:
    if not path.exists():
        return '缺失'
    if not path.is_file():
        return '读取失败：不是文件'
    try:
        if path.stat().st_size == 0:
            return '空文件'
    except OSError as exc:
        return f'读取失败：{exc}'
    return '可用'


def main() -> int:
    parser = argparse.ArgumentParser(description='Run the local GMGN monitor dashboard.')
    parser.add_argument('--root', type=Path, default=Path('.'))
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    try:
        serve(args.root, args.host, args.port)
    except OSError as exc:
        print(f'failed to start GMGN dashboard: {exc}', file=sys.stderr)
        return 2
    return 0


INDEX_HTML = r'''<!doctype html>
<html lang="zh-CN" data-theme="dark">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GMGN 扫链监控</title>
  <meta name="color-scheme" content="dark">
  <link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'%3E%3Crect width='64' height='64' rx='18' fill='%23f5c14f'/%3E%3Ctext x='32' y='43' text-anchor='middle' font-family='sans-serif' font-size='34' font-weight='700' fill='%23171108'%3EG%3C/text%3E%3C/svg%3E">
  <script>
    (() => {
      const path = window.location.pathname;
      document.documentElement.dataset.page = path === '/sources'
        ? 'sources'
        : path === '/reports'
          ? 'reports'
          : path === '/leader-pool'
            ? 'leader-pool'
            : path === '/copy-config'
              ? 'copy-config'
              : path === '/token-exit-config'
                ? 'token-exit-config'
                : 'home';
    })();
  </script>
  <style>
    :root {
      color-scheme: dark;
      --bg: #07090d;
      --surface: #11151c;
      --surface-2: #171d26;
      --surface-3: #1c2430;
      --line: #29313d;
      --line-soft: rgba(255, 255, 255, .08);
      --ink: #f5f7fa;
      --muted: #8f9baa;
      --faint: #5f6b7a;
      --brand: #f5c14f;
      --brand-strong: #f8d27a;
      --brand-ink: #171108;
      --brand-soft: rgba(245, 193, 79, .12);
      --accent: var(--brand);
      --accent-2: var(--muted);
      --good: #51d6a3;
      --bad: #ff6c78;
      --warn: #f0a04b;
      --blue: #78a9ff;
      --purple: var(--blue);
      --soft: var(--brand-soft);
      --green-soft: rgba(81, 214, 163, .12);
      --red-soft: rgba(255, 108, 120, .12);
      --blue-soft: rgba(120, 169, 255, .12);
      --shadow: 0 18px 48px rgba(0, 0, 0, .24);
      --panel: var(--surface);
      --panel-strong: var(--surface-2);
      --glow: none;
      --radius: 14px;
      --radius-sm: 9px;
      --font: Inter, ui-sans-serif, -apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      --font-num: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    * { box-sizing: border-box; }
    html[data-page="home"] [data-page]:not([data-page="home"]),
    html[data-page="leader-pool"] [data-page]:not([data-page="leader-pool"]),
    html[data-page="copy-config"] [data-page]:not([data-page="copy-config"]),
    html[data-page="token-exit-config"] [data-page]:not([data-page="token-exit-config"]),
    html[data-page="sources"] [data-page]:not([data-page="sources"]),
    html[data-page="reports"] [data-page]:not([data-page="reports"]) {
      display: none !important;
    }
    html { -webkit-text-size-adjust: 100%; }
    body {
      margin: 0;
      min-height: 100vh;
      color: var(--ink);
      font: 14px/1.5 var(--font);
      background:
        radial-gradient(circle at 15% -8%, rgba(245, 193, 79, .10), transparent 31rem),
        radial-gradient(circle at 95% 26%, rgba(120, 169, 255, .06), transparent 34rem),
        linear-gradient(rgba(255, 255, 255, .012) 1px, transparent 1px),
        linear-gradient(90deg, rgba(255, 255, 255, .012) 1px, transparent 1px),
        var(--bg);
      background-size: auto, auto, 32px 32px, 32px 32px, auto;
      background-attachment: fixed;
    }
    header {
      position: sticky;
      top: 0;
      z-index: 20;
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      gap: 8px 20px;
      max-width: 1440px;
      min-height: 58px;
      margin: 10px auto 0;
      padding: 8px 12px;
      border: 1px solid var(--line-soft);
      border-radius: 16px;
      background: rgba(14, 18, 24, .88);
      box-shadow: 0 12px 38px rgba(0, 0, 0, .22);
      -webkit-backdrop-filter: blur(18px);
      backdrop-filter: blur(18px);
    }
    .brand {
      display: flex;
      align-items: center;
      gap: 10px;
      min-width: max-content;
      color: var(--ink);
      font-weight: 750;
    }
    .brand-mark {
      display: grid;
      place-items: center;
      width: 34px;
      height: 34px;
      border-radius: 11px;
      background: var(--brand);
      color: var(--brand-ink);
      font-size: 16px;
      font-weight: 900;
      box-shadow: 0 0 24px rgba(245, 193, 79, .18);
    }
    h1 {
      margin: 0;
      color: var(--ink);
      font-size: 15px;
      font-weight: 750;
      letter-spacing: 0;
    }
    .top-nav {
      display: flex;
      flex: 1;
      flex-wrap: wrap;
      align-items: center;
      gap: 4px;
      min-width: 0;
    }
    .top-nav a {
      padding: 8px 12px;
      border-radius: var(--radius-sm);
      color: var(--muted);
      font-size: 13px;
      font-weight: 650;
      text-decoration: none;
      white-space: nowrap;
      transition: color .15s, background-color .15s;
    }
    .top-nav a:hover {
      color: var(--ink);
      background: rgba(255, 255, 255, .05);
    }
    html[data-page="home"] .top-nav a[href="/#portfolio"],
    html[data-page="leader-pool"] .top-nav a[href="/leader-pool"],
    html[data-page="copy-config"] .top-nav a[href="/copy-config"],
    html[data-page="token-exit-config"] .top-nav a[href="/token-exit-config"],
    html[data-page="sources"] .top-nav a[href="/sources"],
    html[data-page="reports"] .top-nav a[href="/reports"] {
      color: var(--brand);
      background: var(--brand-soft);
    }
    .header-meta {
      display: flex;
      align-items: center;
      margin-left: auto;
      color: var(--muted);
      font-size: 12px;
    }
    .header-gate {
      display: flex;
      align-items: center;
      justify-content: flex-end;
    }
    main {
      max-width: 1440px;
      margin: 0 auto;
      padding: 18px 16px 32px;
    }
    .hero, .metric, .section, .output, .panel, .info-tile, .leader-status-card, .leader-config-card, .workflow-step {
      background: var(--surface);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      box-shadow: 0 1px 2px rgba(0, 0, 0, .18);
    }
    .hero {
      margin-bottom: 16px;
      padding: 18px;
    }
    .hero h2, .section h2, .panel h2, .output h2 {
      margin: 0 0 12px;
      color: var(--ink);
      font-size: 16px;
      font-weight: 750;
    }
    .section > h2::after, .panel > h2::after {
      content: "";
      display: block;
      height: 1px;
      margin-top: 10px;
      background: linear-gradient(90deg, var(--line), transparent);
    }
    .hero p { margin: 0; max-width: 860px; color: var(--muted); }
    .hero-grid, .signal-grid, .status-grid, .portfolio-summary, .leader-status-stack, .config-grid {
      display: grid;
      gap: 10px;
    }
    .hero-grid, .signal-grid { grid-template-columns: repeat(3, minmax(0, 1fr)); margin-top: 14px; }
    .status-grid { grid-template-columns: repeat(5, minmax(150px, 1fr)); margin-bottom: 16px; }
    .portfolio-summary { grid-template-columns: repeat(4, minmax(0, 1fr)); margin-bottom: 12px; }
    .leader-status-stack { grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 12px 0; }
    .config-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
    .info-tile, .metric, .leader-status-card, .leader-config-card {
      min-height: 86px;
      padding: 14px;
    }
    .info-tile { background: var(--surface-2); }
    .info-tile span, .metric span, .leader-status-card strong {
      display: block;
      margin-bottom: 6px;
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
    }
    .info-tile strong, .metric strong, .leader-funnel strong {
      display: block;
      color: var(--ink);
      font-family: var(--font-num);
      font-size: 20px;
      font-weight: 700;
      font-variant-numeric: tabular-nums;
      line-height: 1.15;
      overflow-wrap: anywhere;
    }
    .info-tile small, .metric-action small {
      display: block;
      margin-top: 6px;
      color: var(--faint);
      font-size: 12px;
    }
    .leader-status-card span {
      display: block;
      color: var(--ink);
      font-size: 13px;
      line-height: 1.45;
    }
    .leader-status-card.warn {
      border-color: rgba(240, 160, 75, .45);
      background: rgba(240, 160, 75, .08);
    }
    .metric { position: relative; overflow: hidden; }
    .metric-action {
      width: 100%;
      color: inherit;
      font: inherit;
      text-align: left;
      cursor: pointer;
    }
    .metric-action:hover, .metric-action.active {
      border-color: var(--brand);
      box-shadow: 0 0 0 1px var(--brand-soft);
    }
    .section, .panel { margin-bottom: 16px; padding: 16px; }
    .output { overflow: hidden; }
    .output h2 {
      margin: 0;
      padding: 12px 14px;
      border-bottom: 1px solid var(--line);
    }
    .portfolio-head, .leader-list-head, .action-row {
      display: flex;
      flex-wrap: wrap;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
    }
    .portfolio-head { align-items: flex-start; margin-bottom: 12px; }
    .portfolio-head h2 { margin-bottom: 4px; }
    .leader-list-head { margin-top: 16px; }
    .leader-list-head h3 { margin: 0; font-size: 14px; }
    .signal-details[hidden], [data-leader-tab][hidden], .page-hidden { display: none !important; }
    .signal-details { margin-top: -4px; }
    .notice {
      margin: 0 0 12px;
      color: var(--bad);
      font-size: 13px;
    }
    .notice.score-notice { color: var(--muted); }
    .diagnostics {
      display: none;
      margin: 0 0 16px;
      padding: 12px 14px;
      border: 1px solid rgba(240, 160, 75, .35);
      border-radius: var(--radius-sm);
      background: rgba(240, 160, 75, .1);
      color: #f8d7a2;
    }
    .diagnostics.visible, .log.visible { display: block; }
    .diagnostics strong { display: block; margin-bottom: 5px; }
    .badge, .status-pill {
      display: inline-flex;
      align-items: center;
      padding: 6px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      line-height: 1;
    }
    .ok { background: var(--green-soft); color: var(--good); }
    .blocked { background: rgba(240, 160, 75, .12); color: var(--warn); }
    .fail { background: var(--red-soft); color: var(--bad); }
    .status-pill { margin-top: 8px; border: 1px solid var(--line); color: var(--muted); }
    .status-pill.paused { border-color: rgba(240, 160, 75, .45); color: var(--warn); }
    .workflow { display: grid; grid-template-columns: repeat(5, minmax(0, 1fr)); gap: 10px; }
    .workflow-step { min-height: 150px; padding: 14px; }
    .workflow-step strong { display: block; margin-bottom: 8px; font-size: 13px; }
    .workflow-step p { margin: 0 0 10px; color: var(--muted); font-size: 12px; }
    .workflow-step span { display: block; color: var(--brand); font-size: 12px; font-weight: 700; overflow-wrap: anywhere; }
    .portfolio-table-wrap, .table-wrap { overflow-x: auto; }
    table { width: 100%; border-collapse: collapse; }
    th, td {
      padding: 10px 8px;
      border-top: 1px solid var(--line-soft);
      color: var(--ink);
      font-size: 13px;
      text-align: left;
      vertical-align: top;
    }
    th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 650;
      background: transparent;
    }
    tbody tr:hover td { background: rgba(255, 255, 255, .03); }
    .source-table tr.score-low td, .copy-config-table tr.score-low td, tr.score-low td {
      background: var(--red-soft);
      border-top-color: rgba(255, 108, 120, .28);
    }
    code, pre, .source-table code {
      font-family: var(--font-num);
      overflow-wrap: anywhere;
    }
    .source-table code { font-size: 12px; line-height: 1.4; }
    .score-warning { display: block; margin-top: 4px; color: var(--bad); font-size: 12px; }
    .leader-config-card h3 { margin: 0 0 4px; font-size: 14px; }
    .leader-config-card.score-low { border-color: rgba(255, 108, 120, .45); }
    .leader-config-card.is-paused, .copy-config-table tr.is-paused td { opacity: .56; filter: grayscale(.7); }
    .copy-config-table td { vertical-align: middle; }
    .copy-config-table .leader-cell strong { display: block; margin-bottom: 3px; color: var(--ink); font-size: 13px; }
    .copy-config-table .leader-cell small { display: block; max-width: 220px; color: var(--muted); font-size: 11px; overflow-wrap: anywhere; }
    .config-form {
      display: grid;
      grid-template-columns: repeat(2, minmax(0, 1fr));
      gap: 10px;
      margin-top: 12px;
    }
    .config-form label {
      display: grid;
      gap: 6px;
      color: var(--muted);
      font-size: 12px;
    }
    .config-form input, .config-form select, .copy-config-table input, .copy-config-table select {
      width: 100%;
      min-height: 40px;
      padding: 8px 10px;
      border: 1px solid var(--line);
      border-radius: 10px;
      color: var(--ink);
      background: var(--bg);
      font: inherit;
    }
    .copy-config-table select, .config-form select { min-width: 108px; }
    .config-form select option, .copy-config-table select option { color: var(--ink); background: var(--surface); }
    .config-form input:focus-visible, .config-form select:focus-visible,
    .copy-config-table input:focus-visible, .copy-config-table select:focus-visible {
      outline: 2px solid var(--brand);
      outline-offset: 1px;
      border-color: transparent;
    }
    .config-form button { grid-column: 1 / -1; }
    input[disabled], select[disabled] { color: var(--muted); }
    button {
      appearance: none;
      min-height: 38px;
      padding: 8px 14px;
      border: 0;
      border-radius: 10px;
      background: var(--brand);
      color: var(--brand-ink);
      font: inherit;
      font-weight: 750;
      cursor: pointer;
    }
    button:hover:not(:disabled) { background: var(--brand-strong); }
    button:focus-visible, .top-nav a:focus-visible {
      outline: 2px solid var(--brand);
      outline-offset: 2px;
    }
    button:disabled { cursor: progress; opacity: .55; }
    button.secondary, .tabs button, .leader-pool-tabs button, .leader-pagination button, .leader-funnel button {
      border: 1px solid var(--line);
      background: var(--surface-2);
      color: var(--ink);
      box-shadow: none;
    }
    button.secondary:hover:not(:disabled), .tabs button:hover:not(:disabled), .leader-funnel button:hover:not(:disabled) {
      border-color: var(--faint);
      background: var(--surface-3);
    }
    .tabs { display: grid; gap: 6px; }
    .tabs button, .leader-funnel button { width: 100%; text-align: left; }
    .tabs button.active, .leader-pool-tabs button.active, .leader-funnel button.active {
      border-color: transparent;
      background: var(--brand-soft);
      color: var(--brand);
      box-shadow: none;
    }
    .leader-pool-tabs { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 16px; }
    .leader-pool-tabs button { width: auto; }
    .leader-funnel {
      display: grid;
      grid-template-columns: repeat(5, minmax(120px, 1fr));
      gap: 8px;
      margin: 12px 0;
    }
    .leader-funnel button { min-height: 72px; padding: 10px 12px; text-align: center; }
    .leader-funnel small { display: block; margin-top: 4px; color: var(--muted); font-size: 11px; line-height: 1.3; }
    .leader-pagination { display: flex; flex-wrap: wrap; justify-content: flex-end; gap: 8px; margin: 10px 0; }
    .leader-pagination button { min-height: 32px; padding: 6px 10px; }
    .layout { display: block; }
    pre, .log {
      margin: 0;
      max-height: 560px;
      overflow: auto;
      padding: 14px;
      color: var(--ink);
      background: var(--bg);
      font: 12px/1.5 var(--font-num);
      white-space: pre-wrap;
      word-break: break-word;
    }
    .log { display: none; max-height: 260px; margin-top: 12px; border-radius: var(--radius-sm); }
    .small, .empty { color: var(--muted); font-size: 12px; }
    .empty { padding: 8px 0; font-size: 13px; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    button.gate-switch {
      display: inline-flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      width: auto;
      min-width: 170px;
      min-height: 38px;
      padding: 4px 5px 4px 12px;
      border: 1px solid var(--line);
      border-radius: 999px;
      background: var(--surface-2);
      color: var(--ink);
    }
    button.gate-switch:hover:not(:disabled) { background: var(--surface-3); }
    .gate-card { display: flex; flex-direction: column; gap: 8px; }
    .gate-card span { margin-bottom: 0; }
    .gate-switch-text { color: var(--ink); font-size: 13px; font-weight: 700; overflow-wrap: anywhere; }
    .gate-switch-track {
      flex: 0 0 48px;
      height: 28px;
      padding: 3px;
      border-radius: 999px;
      background: #33404e;
      transition: background .16s ease;
    }
    .gate-switch-knob {
      display: block;
      width: 22px;
      height: 22px;
      border-radius: 50%;
      background: #f5f7fa;
      box-shadow: 0 1px 3px rgba(0, 0, 0, .28);
      transition: transform .16s ease;
    }
    .gate-switch.enabled .gate-switch-track { background: var(--good); }
    .gate-switch.enabled .gate-switch-knob { transform: translateX(20px); }
    .gate-switch.blocked .gate-switch-track { background: var(--warn); }
    .gate-switch:disabled { cursor: progress; opacity: .62; }
    @media (max-width: 820px) {
      header { align-items: stretch; margin: 8px 12px 0; }
      .top-nav, .header-meta { width: 100%; margin-left: 0; }
      .top-nav { overflow-x: auto; }
      main { padding: 14px 12px 24px; }
      .status-grid, .portfolio-summary, .hero-grid, .signal-grid, .workflow, .layout, .leader-funnel, .leader-status-stack, .config-grid, .config-form {
        grid-template-columns: 1fr;
      }
      .status-grid, .portfolio-summary { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    }
  </style>
</head>
<body>
  <header>
    <div class="brand">
      <span class="brand-mark" aria-hidden="true">G</span>
      <h1>GMGN 扫链监控</h1>
    </div>
    <nav class="top-nav" aria-label="页面菜单">
      <a href="/#portfolio">持仓</a>
      <a href="/leader-pool">Leader 池</a>
      <a href="/copy-config">跟单配置</a>
      <a href="/token-exit-config">代币止损止盈配置</a>
      <a href="/sources">数据源</a>
      <a href="/reports">报告</a>
    </nav>
    <div class="header-meta">
      <div class="header-gate">
        <button id="gateSwitch" class="gate-switch blocked" type="button" onclick="toggleAutomationGate(this)" aria-pressed="false">
          <strong id="gateBadge" class="gate-switch-text">...</strong>
          <span class="gate-switch-track" aria-hidden="true"><span class="gate-switch-knob"></span></span>
        </button>
      </div>
    </div>
  </header>
  <main>
    <div id="summaryWarning" class="notice" data-page="home"></div>
    <div id="failureDetails" class="diagnostics" data-page="home"></div>
    <section id="leaderPool" class="section" data-page="leader-pool">
      <h2>Leader 池</h2>
      <div class="tabs leader-pool-tabs" role="tablist" aria-label="Leader 池页面">
        <button id="leaderPoolTargetTab" type="button" role="tab" aria-selected="false" onclick="switchLeaderPoolTab('target')">Leader 池目标</button>
        <button id="leaderPoolFilterTab" class="active" type="button" role="tab" aria-selected="true" onclick="switchLeaderPoolTab('filter')">Leader 筛选</button>
      </div>
      <div id="leaderPoolTargetPanel" data-leader-tab="target" hidden>
        <div id="leaderPoolStages" class="signal-grid"></div>
        <div class="leader-list-head">
          <h3>来源质量诊断</h3>
          <span class="small">按高质量命中率排序，辅助选择继续评分或扩池来源</span>
        </div>
        <div class="portfolio-table-wrap">
          <table class="source-table">
            <thead><tr><th>来源</th><th>候选</th><th>已评分</th><th>高质量</th><th>接近达标</th><th>淘汰</th><th>命中率</th><th>建议</th></tr></thead>
            <tbody id="leaderSourceQuality"></tbody>
          </table>
        </div>
        <form id="leaderPoolConfigForm" class="config-form" onsubmit="saveLeaderPoolConfig(event)">
          <label>扫链目标
            <input name="discovery_target" type="number" min="1" step="1">
          </label>
          <label>高质量候选目标
            <input name="high_quality_target" type="number" min="1" step="1">
          </label>
          <label>白名单目标
            <input name="whitelist_target" type="number" min="1" step="1">
          </label>
          <label>回测目标
            <input name="backtest_target" type="number" min="1" step="1">
          </label>
          <label>最低评分
            <input name="min_score" type="number" min="0" max="100" step="0.1">
          </label>
          <label>最低胜率 %
            <input name="min_win_rate_percent" type="number" min="0" max="100" step="0.1">
          </label>
          <label>最低交易样本
            <input name="min_total_trades" type="number" min="1" step="1">
          </label>
          <label>单次评分数量
            <input name="score_batch_size" type="number" min="1" step="1">
          </label>
          <label>评分并发数
            <input name="score_concurrency" type="number" min="1" max="20" step="1">
          </label>
          <label>观察窗口
            <input name="lookback_windows" type="text" placeholder="7d,14d,30d">
          </label>
          <button type="submit">保存 Leader 池配置</button>
        </form>
      </div>
      <div id="leaderPoolFilterPanel" data-leader-tab="filter">
        <div class="action-row leader-pool-actions">
          <button type="button" onclick="runLeaderPoolAction('loop_once', this)">推进下一步</button>
          <button type="button" onclick="runLeaderPoolAction('discover', this)">扫链扩池</button>
          <button type="button" onclick="runLeaderPoolAction('score', this)">评分筛选</button>
          <button type="button" onclick="runLeaderPoolAction('backtest', this)">评分回测</button>
          <span id="leaderPoolActionStatus" class="small"></span>
        </div>
        <div id="leaderPoolLoopStatus" class="notice score-notice"></div>
        <div id="leaderPoolNotice" class="notice score-notice"></div>
        <div id="leaderFunnel" class="leader-funnel" aria-label="Leader 筛选漏斗"></div>
        <div class="leader-list-head">
          <h3 id="leaderFunnelTitle">扫链候选</h3>
          <span id="leaderFunnelHint" class="small"></span>
        </div>
        <div id="leaderFunnelPagination" class="leader-pagination"></div>
        <div class="portfolio-table-wrap">
          <table class="source-table">
            <thead><tr><th>钱包</th><th>评分</th><th>胜率</th><th>交易样本</th><th>利润</th><th>标签</th><th>操作</th></tr></thead>
            <tbody id="leaderFunnelLeaders"></tbody>
          </table>
        </div>
        <div class="leader-list-head">
          <h3>评分回测</h3>
          <span id="leaderBacktestSummary" class="small"></span>
        </div>
        <div class="portfolio-table-wrap">
          <table class="source-table">
            <thead><tr><th>钱包</th><th>评分</th><th>回测分</th><th>结果</th><th>胜率</th><th>交易样本</th><th>利润</th><th>标签</th></tr></thead>
            <tbody id="leaderBacktestLeaders"></tbody>
          </table>
        </div>
      </div>
    </section>
    <section id="portfolio" class="section" data-page="home">
      <div class="portfolio-head">
        <div>
          <h2>持仓管理</h2>
          <div id="portfolioNotice" class="small">加载持仓快照中</div>
        </div>
        <button id="portfolioRefreshButton" class="secondary" type="button" onclick="refreshPortfolio(this)">刷新持仓</button>
      </div>
      <div id="portfolioActionNotice" class="notice"></div>
      <div id="portfolioSummary" class="portfolio-summary"></div>
      <div class="portfolio-table-wrap">
        <table class="source-table">
          <thead>
            <tr>
              <th>代币</th>
              <th>数量</th>
              <th>跟单来源</th>
              <th>入场价</th>
              <th>现价</th>
              <th>价值</th>
              <th>未实现盈亏</th>
              <th>更新时间</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody id="portfolioPositions"></tbody>
        </table>
      </div>
    </section>
    <section id="whitelist" class="section" data-page="home">
      <h2>白名单</h2>
      <div id="whitelistScoreNotice" class="notice score-notice"></div>
      <table class="source-table">
        <thead>
          <tr>
            <th>名称</th>
            <th>钱包</th>
            <th>模式</th>
            <th>等级</th>
            <th>评分</th>
            <th>复制权重</th>
            <th>状态</th>
            <th>操作</th>
          </tr>
        </thead>
        <tbody id="whitelistWallets"></tbody>
      </table>
    </section>
    <section id="copyConfig" class="section" data-page="copy-config">
      <h2>跟单配置</h2>
      <div id="copyConfigNotice" class="notice score-notice"></div>
      <div class="portfolio-table-wrap">
        <table class="source-table copy-config-table">
          <thead>
            <tr>
              <th>Leader</th>
              <th>状态</th>
              <th>模式</th>
              <th>复制权重</th>
              <th>单笔 SOL</th>
              <th>日亏 SOL</th>
              <th>每日次数</th>
              <th>滑点 %</th>
              <th>止损 %</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody id="copyConfigRows"></tbody>
        </table>
      </div>
    </section>
    <section id="tokenExitConfig" class="section" data-page="token-exit-config">
      <h2>代币止损止盈配置</h2>
      <div id="tokenExitNotice" class="notice score-notice"></div>
      <div id="tokenExitGrid" class="config-grid"></div>
    </section>
    <section id="sources" class="section" data-page="sources">
      <h2>数据源状态</h2>
      <table class="source-table">
        <thead>
          <tr>
            <th>数据源</th>
            <th>状态</th>
            <th>运行状态</th>
            <th>可触发 alert</th>
            <th>位置</th>
            <th>说明</th>
          </tr>
        </thead>
        <tbody id="dataSources"></tbody>
      </table>
    </section>
    <section id="outputs" class="layout" data-page="reports">
      <section class="panel">
        <h2>审计事件报告</h2>
        <div id="auditSummary" class="signal-grid"></div>
        <div class="table-wrap">
          <table>
            <thead>
              <tr><th>时间</th><th>类型</th><th>动作</th><th>结果</th><th>对象</th><th>来源</th><th>说明</th></tr>
            </thead>
            <tbody id="auditEvents"></tbody>
          </table>
        </div>
      </section>
    </section>
  </main>
  <script>
    let dashboard = null;
    let portfolioSummaryTimer = null;
    let portfolioPositionsTimer = null;
    let portfolioRefreshInFlight = false;
    let portfolioRefreshPromise = null;
    let portfolioNeedsPositionRender = false;
    const leaderFunnelPageSize = 25;

    async function readJson(response) {
      const body = (await response.text()).trim();
      if (!body) return {};
      try {
        return JSON.parse(body);
      } catch (error) {
        throw new Error(body.replace(/\s+/g, ' ').slice(0, 180));
      }
    }

    function errorText(error) {
      return error && error.message ? error.message : String(error);
    }

    async function refresh() {
      const response = await fetch('/api/status');
      dashboard = await readJson(response);
      render();
    }

    function render() {
      const status = dashboard.status || {};
      const summary = readOperationalSummary();
      setGateSwitch(dashboard.automation_gate || {}, summary.automation_gate_status || 'unknown');
      document.getElementById('summaryWarning').textContent = summary.__error || '';
      renderFailureDetails(status);
      renderLeaderPool();
      renderPortfolio();
      renderWhitelist();
      renderCopyConfig();
      renderTokenExitConfig();
      renderDataSources();
      renderAuditReport();
      applyPageMode();
      syncLeaderPoolTab();
      startPortfolioAutoRefresh();
    }

    function currentPage() {
      const path = window.location.pathname;
      return path === '/sources' ? 'sources' : path === '/reports' ? 'reports' : path === '/leader-pool' ? 'leader-pool' : path === '/copy-config' ? 'copy-config' : path === '/token-exit-config' ? 'token-exit-config' : 'home';
    }

    function applyPageMode() {
      const page = currentPage();
      document.documentElement.dataset.page = page;
      document.querySelectorAll('[data-page]').forEach(element => {
        element.classList.toggle('page-hidden', element.dataset.page !== page);
      });
    }

    function readOperationalSummary() {
      const reportOutput = dashboard.outputs?.verification_report;
      if (reportOutput?.read_error) return { __error: `验证报告读取失败：${reportOutput.read_error}` };
      const report = reportOutput?.content;
      if (!report) return {};
      try {
        return JSON.parse(report).operational_summary || {};
      } catch {
        return { __error: '验证报告 JSON 格式错误' };
      }
    }

    function formatTimestamp(value) {
      if (!value) return '';
      const date = new Date(value);
      if (Number.isNaN(date.getTime())) return value;
      return new Intl.DateTimeFormat('zh-CN', {
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        second: '2-digit',
        hour12: false,
      }).format(date);
    }

    function setGateSwitch(gate, fallbackStatus) {
      const status = gate.status || fallbackStatus || 'unknown';
      const enabled = gate.enabled === true || status === 'auto_trading_enabled';
      const button = document.getElementById('gateSwitch');
      const label = document.getElementById('gateBadge');
      label.textContent = gate.status_label || translateStatus(status);
      button.className = `gate-switch ${enabled ? 'enabled' : 'blocked'}`;
      button.setAttribute('aria-pressed', enabled ? 'true' : 'false');
      button.title = enabled ? '点击暂停自动化安全门' : '点击启用自动化安全门';
    }

    function translateStatus(value) {
      const labels = {
        ok: '通过',
        blocked: '已阻断',
        fail: '失败',
        eligible_for_tiny_size_testing: '可小额测试',
        auto_trading_enabled: '自动交易已启用',
        unknown: '未知'
      };
      return labels[value] || value || '未知';
    }

    function translateMode(mode) {
      if (mode === 'paper') return 'Paper（真实信号，模拟成交）';
      if (mode === 'dryrun' || mode === 'dry_run') return 'Dry Run（安全模拟）';
      if (mode === 'real') return '真实模式';
      return mode || '未知';
    }

    function translateExposure(level) {
      if (level === 'tiny_real') return '微型真实';
      if (level === 'monitor') return '监控';
      if (level === 'observe') return '观察';
      if (level === 'dryrun' || level === 'dry_run') return '模拟';
      return level || '未知';
    }

    function renderFailureDetails(status) {
      const diagnostics = dashboard.status_diagnostics || {};
      const failed = diagnostics.failed_steps || [];
      const reasons = diagnostics.reasons || [];
      const box = document.getElementById('failureDetails');
      if (status.status === 'ok' && !failed.length && !reasons.length) {
        box.classList.remove('visible');
        box.textContent = '';
        return;
      }
      box.classList.add('visible');
      box.innerHTML = '';
      const title = document.createElement('strong');
      title.textContent = `验证失败原因：${failed.join('、') || '验证报告未通过'}`;
      const body = document.createElement('div');
      body.textContent = reasons.length ? reasons.join('；') : '建议点击“运行完整验证”重建报告和历史。';
      box.appendChild(title);
      box.appendChild(body);
    }

    function renderLeaderPool() {
      const leaderPool = dashboard.leader_pool || {};
      const config = leaderPool.config || {};
      const stages = leaderPool.stages || [];
      const form = document.getElementById('leaderPoolConfigForm');
      if (form) {
        for (const key of ['discovery_target', 'high_quality_target', 'whitelist_target', 'backtest_target', 'min_score', 'min_win_rate_percent', 'min_total_trades', 'score_batch_size', 'score_concurrency']) {
          if (form.elements[key]) form.elements[key].value = config[key] ?? '';
        }
        if (form.elements.lookback_windows) {
          form.elements.lookback_windows.value = (config.lookback_windows || []).join(',');
        }
      }
      const stageBox = document.getElementById('leaderPoolStages');
      stageBox.innerHTML = '';
      for (const stage of stages) {
        const tile = document.createElement('div');
        tile.className = 'info-tile';
        const title = document.createElement('span');
        title.textContent = stage.label || '';
        const value = document.createElement('strong');
        value.textContent = `${stage.current ?? 0}/${stage.target ?? 0}`;
        const note = document.createElement('small');
        note.textContent = `${formatOneDecimal(stage.progress_percent)}% · 剩余 ${stage.remaining ?? 0} · ${stage.note || ''}`;
        tile.appendChild(title);
        tile.appendChild(value);
        tile.appendChild(note);
        stageBox.appendChild(tile);
      }
      const notice = document.getElementById('leaderPoolNotice');
      const counts = leaderPool.counts || {};
      const quality = leaderPool.quality_summary || {};
      const projection = quality.projected_high_quality_at_current_pool ?? 0;
      notice.textContent = '';
      notice.classList.toggle('visible', false);
      const loopStatus = document.getElementById('leaderPoolLoopStatus');
      const nextAction = leaderPool.next_action || {};
      const loopState = leaderPool.loop_state || {};
      const prerequisites = leaderPool.prerequisites || {};
      const lastAction = leaderPool.last_action || {};
      const actionStatus = document.getElementById('leaderPoolActionStatus');
      if (actionStatus) {
        actionStatus.textContent = '';
      }
      if (loopStatus) {
        renderLeaderPoolStatusCards(loopStatus, {
          lastAction,
          nextAction,
          loopState,
          prerequisites,
          counts,
          quality,
          projection,
        });
      }
      renderLeaderFunnel(leaderPool);
      renderLeaderSourceQuality(leaderPool);
      renderLeaderBacktest(leaderPool);
    }

    function renderLeaderSourceQuality(leaderPool) {
      const body = document.getElementById('leaderSourceQuality');
      if (!body) return;
      const rows = leaderPool.source_quality || [];
      body.innerHTML = '';
      if (!rows.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 8;
        cell.className = 'empty';
        cell.textContent = '暂无来源质量数据。';
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      for (const source of rows) {
        const row = document.createElement('tr');
        if (source.recommendation === '降权或兜底') row.className = 'score-low';
        const values = [
          source.source || 'unknown',
          formatInteger(source.candidates),
          `${formatInteger(source.scored)} / ${formatOneDecimal(source.coverage_percent)}%`,
          formatInteger(source.high_quality),
          formatInteger(source.near_quality),
          formatInteger(source.rejected),
          `${formatOneDecimal(source.hit_rate_percent)}%`,
          source.recommendation || '-',
        ];
        for (const value of values) {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.appendChild(cell);
        }
        body.appendChild(row);
      }
    }

    function renderLeaderPoolStatusCards(container, data) {
      const keyStatus = data.prerequisites.gmgn_api_key_configured ? 'GMGN_API_KEY 已配置' : 'GMGN_API_KEY 未配置';
      const recommendation = data.quality.recommendation || '当前候选质量正常。';
      const cards = [
        ['最近执行', data.lastAction.message || '暂无执行记录', false],
        ['下一步', `${data.nextAction.label || '-'}；${data.nextAction.reason || ''}；${keyStatus}`, Boolean(data.nextAction.blocked)],
        ['当前进度', `扫链 ${data.counts.discovered ?? 0}；已评分 ${data.counts.scored ?? 0}；高质量 ${data.counts.high_quality ?? 0}；白名单 ${data.counts.whitelisted ?? 0}`, false],
        ['质量判断', `评分覆盖 ${formatOneDecimal(data.quality.scoring_coverage_percent ?? 0)}%；高质量命中率 ${formatOneDecimal(data.quality.high_quality_hit_rate_percent ?? 0)}%；当前候选预计产出 ${formatOneDecimal(data.projection)} 个；${recommendation}`, Boolean(data.quality.recommendation)],
      ];
      if (data.loopState.message) {
        cards.splice(2, 0, ['最近循环', data.loopState.message, false]);
      }
      container.innerHTML = '';
      container.classList.toggle('visible', true);
      const stack = document.createElement('div');
      stack.className = 'leader-status-stack';
      for (const [title, body, warn] of cards) {
        const card = document.createElement('div');
        card.className = `leader-status-card${warn ? ' warn' : ''}`;
        const heading = document.createElement('strong');
        heading.textContent = title;
        const text = document.createElement('span');
        text.textContent = body;
        card.appendChild(heading);
        card.appendChild(text);
        stack.appendChild(card);
      }
      container.appendChild(stack);
    }

    function currentLeaderFunnelStage() {
      return document.documentElement.dataset.leaderFunnelStage || 'candidates';
    }

    function selectLeaderFunnelStage(stage) {
      document.documentElement.dataset.leaderFunnelStage = stage || 'candidates';
      setLeaderFunnelPage(stage || 'candidates', 1);
      renderLeaderFunnel(dashboard.leader_pool || {});
    }

    function currentLeaderFunnelPage(stage) {
      const page = Number(document.documentElement.dataset[`leaderFunnelPage${stage}`] || 1);
      return Number.isFinite(page) && page > 0 ? Math.floor(page) : 1;
    }

    function setLeaderFunnelPage(stage, page) {
      document.documentElement.dataset[`leaderFunnelPage${stage}`] = String(Math.max(1, Math.floor(Number(page) || 1)));
    }

    function changeLeaderFunnelPage(stage, page) {
      setLeaderFunnelPage(stage, page);
      renderLeaderFunnel(dashboard.leader_pool || {});
    }

    function renderLeaderFunnel(leaderPool) {
      const funnel = leaderPool.funnel || [];
      const active = currentLeaderFunnelStage();
      const funnelBox = document.getElementById('leaderFunnel');
      funnelBox.innerHTML = '';
      for (const stage of funnel) {
        const button = document.createElement('button');
        const selected = stage.key === active;
        button.type = 'button';
        button.className = selected ? 'active' : '';
        button.onclick = () => selectLeaderFunnelStage(stage.key);
        button.innerHTML = `<span>${stage.label || ''}</span><strong>${stage.count ?? 0}</strong><small>${stage.note || ''}</small>`;
        funnelBox.appendChild(button);
      }
      const selectedStage = funnel.find(stage => stage.key === active) || funnel[0] || {};
      const title = document.getElementById('leaderFunnelTitle');
      const hint = document.getElementById('leaderFunnelHint');
      title.textContent = selectedStage.label || '扫链候选';
      hint.textContent = selectedStage.note || '';
      const leadersBody = document.getElementById('leaderFunnelLeaders');
      leadersBody.innerHTML = '';
      const pagination = document.getElementById('leaderFunnelPagination');
      const leaders = (leaderPool.funnel_lists || {})[active] || [];
      const totalPages = Math.max(1, Math.ceil(leaders.length / leaderFunnelPageSize));
      const page = Math.min(currentLeaderFunnelPage(active), totalPages);
      setLeaderFunnelPage(active, page);
      const pageStart = (page - 1) * leaderFunnelPageSize;
      const visibleLeaders = leaders.slice(pageStart, pageStart + leaderFunnelPageSize);
      renderLeaderFunnelPagination(pagination, active, leaders.length, page, totalPages);
      if (!leaders.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 7;
        cell.className = 'empty';
        cell.textContent = '暂无 Leader 记录。';
        row.appendChild(cell);
        leadersBody.appendChild(row);
        return;
      }
      for (const leader of visibleLeaders) {
        const row = document.createElement('tr');
        const values = [
          shortAddress(leader.wallet_address),
          `${formatOneDecimal(leader.total_score)} ${leader.grade || ''}`,
          `${formatOneDecimal(leader.winrate)}%`,
          formatInteger(leader.total_trades),
          `$${formatNumber(leader.realized_profit)}`,
          (leader.tags || []).join(', '),
        ];
        for (const value of values) {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.appendChild(cell);
        }
        const actionCell = document.createElement('td');
        if (active === 'scored_whitelist') {
          if (leader.in_copy_whitelist) {
            const status = document.createElement('span');
            status.className = 'status-pill';
            status.textContent = '已在跟单白名单';
            actionCell.appendChild(status);
          } else {
            const button = document.createElement('button');
            button.type = 'button';
            button.className = 'secondary';
            button.textContent = '加入跟单白名单';
            button.onclick = () => promoteLeaderToCopyWhitelist(leader.wallet_address, button);
            actionCell.appendChild(button);
          }
          const rejectButton = document.createElement('button');
          rejectButton.type = 'button';
          rejectButton.className = 'secondary';
          rejectButton.textContent = '淘汰回候选';
          rejectButton.onclick = () => recycleScoredLeader(leader.wallet_address, rejectButton);
          actionCell.appendChild(rejectButton);
        } else {
          actionCell.textContent = '-';
        }
        row.appendChild(actionCell);
        leadersBody.appendChild(row);
      }
    }

    function renderLeaderFunnelPagination(container, stage, total, page, totalPages) {
      container.innerHTML = '';
      const summary = document.createElement('span');
      summary.className = 'small';
      if (total <= leaderFunnelPageSize) {
        summary.textContent = `共 ${formatInteger(total)} 条`;
        container.appendChild(summary);
        return;
      }
      const start = (page - 1) * leaderFunnelPageSize + 1;
      const end = Math.min(total, page * leaderFunnelPageSize);
      summary.textContent = `${formatInteger(start)}-${formatInteger(end)} / ${formatInteger(total)} 条`;
      container.appendChild(summary);

      const previous = document.createElement('button');
      previous.type = 'button';
      previous.className = 'secondary';
      previous.textContent = '上一页';
      previous.disabled = page <= 1;
      previous.onclick = () => changeLeaderFunnelPage(stage, page - 1);
      container.appendChild(previous);

      const current = document.createElement('span');
      current.className = 'small';
      current.textContent = `${formatInteger(page)} / ${formatInteger(totalPages)}`;
      container.appendChild(current);

      const next = document.createElement('button');
      next.type = 'button';
      next.className = 'secondary';
      next.textContent = '下一页';
      next.disabled = page >= totalPages;
      next.onclick = () => changeLeaderFunnelPage(stage, page + 1);
      container.appendChild(next);
    }

    function renderLeaderBacktest(leaderPool) {
      const backtest = leaderPool.backtest || {};
      const summary = document.getElementById('leaderBacktestSummary');
      summary.textContent = `记录 ${backtest.count ?? 0}；校准日志 ${backtest.calibration_events ?? 0}`;
      const body = document.getElementById('leaderBacktestLeaders');
      body.innerHTML = '';
      const leaders = backtest.leaders || [];
      if (!leaders.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 8;
        cell.className = 'empty';
        cell.textContent = '暂无评分回测记录。';
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      for (const leader of leaders) {
        const row = document.createElement('tr');
        const weakBacktest = leader.passed === false || Number(leader.backtest_score || 0) < 60;
        row.className = weakBacktest ? 'score-low' : '';
        for (const value of [
          shortAddress(leader.wallet_address),
          `${formatOneDecimal(leader.total_score)} ${leader.grade || ''}`,
          leader.backtest_score === undefined || leader.backtest_score === null ? '-' : formatOneDecimal(leader.backtest_score),
          leader.passed === false ? '未通过' : '通过',
          `${formatOneDecimal(leader.winrate)}%`,
          formatInteger(leader.total_trades),
          `$${formatNumber(leader.realized_profit)}`,
          (leader.tags || []).join(', '),
        ]) {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.appendChild(cell);
        }
        body.appendChild(row);
      }
    }

    function currentLeaderPoolTab() {
      return document.documentElement.dataset.leaderPoolTab || 'filter';
    }

    function switchLeaderPoolTab(tab) {
      document.documentElement.dataset.leaderPoolTab = tab === 'filter' ? 'filter' : 'target';
      syncLeaderPoolTab();
    }

    function syncLeaderPoolTab() {
      const active = currentLeaderPoolTab();
      const tabs = {
        target: document.getElementById('leaderPoolTargetTab'),
        filter: document.getElementById('leaderPoolFilterTab'),
      };
      const panels = {
        target: document.getElementById('leaderPoolTargetPanel'),
        filter: document.getElementById('leaderPoolFilterPanel'),
      };
      for (const [key, button] of Object.entries(tabs)) {
        if (!button) continue;
        const selected = key === active;
        button.classList.toggle('active', selected);
        button.setAttribute('aria-selected', selected ? 'true' : 'false');
      }
      for (const [key, panel] of Object.entries(panels)) {
        if (!panel) continue;
        panel.hidden = key !== active;
      }
    }

    async function promoteLeaderToCopyWhitelist(walletAddress, button) {
      if (!walletAddress) return;
      const status = document.getElementById('leaderPoolActionStatus');
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = '加入中';
      if (status) status.textContent = '正在加入跟单白名单...';
      try {
        const response = await fetch('/api/leader-pool/promote-one', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ wallet_address: walletAddress }),
        });
        const result = await readJson(response);
        dashboard = result.dashboard || dashboard;
        render();
        if (!response.ok || !result.ok) {
          throw new Error(result.error || '加入跟单白名单失败');
        }
        if (status) status.textContent = result.message || '已加入跟单白名单';
      } catch (error) {
        if (status) status.textContent = `加入失败：${String(error)}`;
      } finally {
        button.disabled = false;
        button.textContent = originalText;
      }
    }

    async function recycleScoredLeader(walletAddress, button) {
      if (!walletAddress) return;
      const status = document.getElementById('leaderPoolActionStatus');
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = '处理中';
      if (status) status.textContent = '正在退回扫链候选...';
      try {
        const response = await fetch('/api/leader-pool/recycle-scored', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ wallet_address: walletAddress }),
        });
        const result = await readJson(response);
        dashboard = result.dashboard || dashboard;
        render();
        if (!response.ok || !result.ok) {
          throw new Error(result.error || '退回扫链候选失败');
        }
        if (status) status.textContent = result.message || '已退回扫链候选';
      } catch (error) {
        if (status) status.textContent = `退回失败：${String(error)}`;
      } finally {
        button.disabled = false;
        button.textContent = originalText;
      }
    }

    async function runLeaderPoolAction(action, button) {
      const originalText = button.textContent;
      const status = document.getElementById('leaderPoolActionStatus');
      button.disabled = true;
      const runningText = {
        loop_once: '推进中',
        discover: '扫链中',
        score: '评分中',
        promote: '升级中',
        backtest: '回测中',
      };
      button.textContent = runningText[action] || '执行中';
      if (status) status.textContent = '执行中...';
      try {
        const response = await fetch('/api/leader-pool/actions', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ action, chain: 'sol' }),
        });
        const result = await readJson(response);
        dashboard = result.dashboard || dashboard;
        render();
        if (!response.ok || !result.ok) {
          throw new Error(result.error || result.message || 'Leader 池动作执行失败');
        }
        if (status) status.textContent = result.message || '执行完成';
      } catch (error) {
        if (status) status.textContent = `执行失败：${String(error)}`;
      } finally {
        button.disabled = false;
        button.textContent = originalText;
      }
    }

    async function saveLeaderPoolConfig(event) {
      event.preventDefault();
      const form = event.currentTarget;
      const button = form.querySelector('button[type="submit"]');
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = '保存中';
      const payload = {
        discovery_target: Number(form.elements.discovery_target.value),
        high_quality_target: Number(form.elements.high_quality_target.value),
        whitelist_target: Number(form.elements.whitelist_target.value),
        backtest_target: Number(form.elements.backtest_target.value),
        min_score: Number(form.elements.min_score.value),
        min_win_rate_percent: Number(form.elements.min_win_rate_percent.value),
        min_total_trades: Number(form.elements.min_total_trades.value),
        score_batch_size: Number(form.elements.score_batch_size.value),
        score_concurrency: Number(form.elements.score_concurrency.value),
        lookback_windows: form.elements.lookback_windows.value,
      };
      try {
        const response = await fetch('/api/leader-pool/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const result = await readJson(response);
        if (!response.ok || !result.ok) {
          throw new Error(result.error || 'Leader 池配置保存失败');
        }
        dashboard = result.dashboard || dashboard;
        render();
        document.getElementById('leaderPoolNotice').textContent = 'Leader 池配置已保存。';
      } catch (error) {
        document.getElementById('leaderPoolNotice').textContent = `保存失败：${String(error)}`;
      } finally {
        button.disabled = false;
        button.textContent = originalText;
      }
    }

    function renderPortfolio() {
      const portfolio = dashboard.portfolio || {};
      renderPortfolioSummary(portfolio);
      renderPortfolioPositions(portfolio);
    }

    function renderPortfolioSummary(portfolio) {
      const summary = portfolio.summary || {};
      const valueUnit = portfolio.value_unit || 'SOL';
      const availableUnit = portfolio.available_unit || valueUnit;
      const portfolioNotice = document.getElementById('portfolioNotice');
      portfolioNotice.textContent = portfolio.notice || '';
      portfolioNotice.style.display = portfolio.notice ? '' : 'none';
      const tiles = [
        ['总价值', `${formatNumber(summary.total_value_sol)} ${valueUnit}`, `来源：${portfolio.source || 'none'}`],
        ['打开持仓', `${summary.open_positions ?? 0}/${summary.max_positions ?? 0}`, '超过上限前不应新增计划'],
        ['未实现盈亏', `${formatNumber(summary.daily_pnl_sol)} ${valueUnit}`, `${formatNumber(summary.daily_pnl_percent)}%`],
      ];
      if (portfolio.has_available_balance) {
        tiles.splice(1, 0, ['可用余额', `${formatNumber(summary.available_sol)} ${availableUnit}`, portfolio.wallet_address ? `钱包：${shortAddress(portfolio.wallet_address)}` : '未配置真实钱包']);
      }
      if (portfolio.has_max_drawdown) {
        tiles.push(['最大回撤', `${formatNumber(summary.max_drawdown_percent)}%`, `更新时间：${portfolio.timestamp || '无'}`]);
      }
      const summaryBox = document.getElementById('portfolioSummary');
      summaryBox.innerHTML = '';
      for (const [label, value, note] of tiles) {
        const tile = document.createElement('div');
        tile.className = 'info-tile';
        tile.innerHTML = `<span>${label}</span><strong>${value}</strong><small>${note}</small>`;
        summaryBox.appendChild(tile);
      }
    }

    function renderPortfolioPositions(portfolio) {
      const positions = portfolio.positions || [];
      const valueUnit = portfolio.value_unit || 'SOL';
      const priceUnit = portfolio.price_unit || valueUnit;
      const body = document.getElementById('portfolioPositions');
      body.innerHTML = '';
      if (!positions.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 9;
        cell.className = 'empty';
        cell.textContent = portfolio.notice || '暂无真实钱包持仓数据。';
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      for (const position of positions) {
        const row = document.createElement('tr');
        const values = [
          `${position.symbol || 'unknown'} ${shortAddress(position.token_address)}`,
          formatNumber(position.quantity),
          formatCopySource(position),
          formatPriceWithUnit(position.entry_price_sol, priceUnit, position.has_entry_price),
          formatPriceWithUnit(position.current_price_sol, priceUnit, position.has_current_price),
          `${formatNumber(position.value_sol)} ${valueUnit}`,
          `${formatNumber(position.unrealized_pnl_sol)} ${valueUnit} (${formatNumber(position.unrealized_pnl_percent)}%)`,
          position.last_updated || position.entry_time || '未知',
        ];
        for (const value of values) {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.appendChild(cell);
        }
        const actionCell = document.createElement('td');
        const sellButton = document.createElement('button');
        sellButton.className = 'secondary';
        sellButton.textContent = '卖出';
        sellButton.onclick = () => requestSellPosition(position, sellButton);
        actionCell.appendChild(sellButton);
        row.appendChild(actionCell);
        body.appendChild(row);
      }
    }

    async function requestSellPosition(position, button) {
      const tokenAddress = position.token_address || '';
      const symbol = position.symbol || 'unknown';
      if (!tokenAddress) {
        document.getElementById('portfolioActionNotice').textContent = '卖出失败：缺少代币地址。';
        return;
      }
      const confirmed = window.confirm(`确认真实卖出 ${symbol} 100%？该操作会通过 gmgn-cli 提交链上交易，成交后不可撤销。`);
      if (!confirmed) return;
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = '提交中';
      document.getElementById('portfolioActionNotice').textContent = `正在提交 ${symbol} 的卖出请求...`;
      try {
        const response = await fetch('/api/sell', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            token_address: tokenAddress,
            symbol,
            quantity: position.quantity || 0,
            value: position.value_sol || 0,
            sell_percent: 100,
            confirmed: true,
          }),
        });
        const result = await readJson(response);
        document.getElementById('portfolioActionNotice').textContent = result.success
          ? `真实卖出已提交：${result.tx_hash || result.order_id || symbol}`
          : `卖出未执行：${result.error_message || '请检查 gmgn-cli 配置和安全门'}`;
      } catch (error) {
        document.getElementById('portfolioActionNotice').textContent = `卖出请求失败：${String(error)}`;
      } finally {
        try {
          await loadPortfolio({ renderPositions: true });
        } catch (error) {
          document.getElementById('portfolioNotice').textContent = `刷新失败：${String(error)}`;
        }
        button.disabled = false;
        button.textContent = originalText || '卖出';
      }
    }

    async function loadPortfolio(options = {}) {
      const renderPositions = options.renderPositions !== false;
      if (renderPositions) {
        portfolioNeedsPositionRender = true;
      }
      if (portfolioRefreshPromise) {
        return portfolioRefreshPromise;
      }
      portfolioRefreshInFlight = true;
      portfolioRefreshPromise = (async () => {
        const response = await fetch('/api/portfolio', { cache: 'no-store' });
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const portfolio = await readJson(response);
        dashboard.portfolio = portfolio;
        renderPortfolioSummary(portfolio);
        if (portfolioNeedsPositionRender) {
          renderPortfolioPositions(portfolio);
        }
        portfolioNeedsPositionRender = false;
        return portfolio;
      })();
      try {
        return await portfolioRefreshPromise;
      } finally {
        portfolioRefreshInFlight = false;
        portfolioRefreshPromise = null;
      }
    }

    function startPortfolioAutoRefresh() {
      if (currentPage() !== 'home') return;
      if (!portfolioSummaryTimer) {
        portfolioSummaryTimer = window.setInterval(() => {
          if (currentPage() === 'home') {
            loadPortfolio({ renderPositions: false }).catch(error => {
              document.getElementById('portfolioNotice').textContent = `刷新失败：${String(error)}`;
            });
          }
        }, 10000);
      }
      if (!portfolioPositionsTimer) {
        const refreshPositions = () => {
          if (currentPage() === 'home') {
            loadPortfolio({ renderPositions: true }).catch(error => {
              document.getElementById('portfolioNotice').textContent = `刷新失败：${String(error)}`;
            });
          }
        };
        portfolioPositionsTimer = window.setTimeout(() => {
          refreshPositions();
          portfolioPositionsTimer = window.setInterval(refreshPositions, 30000);
        }, 5000);
      }
    }

    async function refreshPortfolio(button) {
      const target = button || document.getElementById('portfolioRefreshButton');
      const originalText = target ? target.textContent : '';
      if (target) {
        target.disabled = true;
        target.textContent = '刷新中';
      }
      document.getElementById('portfolioNotice').textContent = '正在读取真实钱包 holdings...';
      try {
        await loadPortfolio({ renderPositions: true });
      } catch (error) {
        document.getElementById('portfolioNotice').textContent = `刷新失败：${String(error)}`;
      } finally {
        if (target) {
          target.disabled = false;
          target.textContent = originalText || '刷新持仓';
        }
      }
    }

    function renderWhitelist() {
      const copyConfig = dashboard.copy_trading_config || {};
      const wallets = copyConfig.wallets || [];
      const scoreReport = copyConfig.score_report || {};
      const scoreNotice = document.getElementById('whitelistScoreNotice');
      const lowCount = scoreReport.low_score_count || 0;
      const risk = copyConfig.risk_gates || {};
      const riskLine = risk.max_single_trade_sol == null ? '' : ` 跟单门槛：单笔 ≤ ${risk.max_single_trade_sol} SOL，日亏 ≤ ${risk.max_daily_loss_sol} SOL，持仓 ≤ ${risk.max_positions}，滑点 ≤ ${risk.max_slippage_percent}%，信号 ${risk.max_signal_age_minutes} 分钟内，leader 分 ≥ ${risk.min_leader_score}，CSS 通过 ≥ ${risk.css_pass_score}（观察 ≥ ${risk.css_watch_score}）。`;
      scoreNotice.textContent = `白名单评分每 3 小时刷新；最近评分 ${formatTimestamp(scoreReport.generated_at) || '未生成'}；下次 ${formatTimestamp(scoreReport.next_run_at) || '待定'}。${lowCount ? `发现 ${lowCount} 个低分钱包，请人工复核。` : '当前未发现低分钱包。'}${riskLine}`;
      scoreNotice.classList.toggle('visible', true);
      const body = document.getElementById('whitelistWallets');
      body.innerHTML = '';
      if (!wallets.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 8;
        cell.className = 'empty';
        cell.textContent = '暂无 Leader；请检查 config/wallet_whitelist.json。';
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      for (const wallet of wallets) {
        const row = document.createElement('tr');
        row.className = wallet.score_status === 'low' ? 'score-low' : '';
        const values = [
          wallet.label || '未命名',
          wallet.wallet_address ? `${shortAddress(wallet.wallet_address)} ${wallet.wallet_address}` : '未配置',
          wallet.mode || copyConfig.trade_mode || '未知',
          wallet.grade || '-',
          wallet.total_score ?? '-',
          formatPercent(wallet.copy_weight_percent),
          wallet.enabled === false ? '停用' : '启用',
        ];
        for (const [index, value] of values.entries()) {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.appendChild(cell);
          if (index === 4 && wallet.score_warning) {
            const warning = document.createElement('span');
            warning.className = 'score-warning';
            warning.textContent = wallet.score_warning;
            cell.appendChild(warning);
          }
        }
        const actionCell = document.createElement('td');
        const button = document.createElement('button');
        button.className = wallet.enabled === false ? '' : 'secondary';
        button.textContent = wallet.enabled === false ? '启动' : '暂停';
        button.onclick = () => toggleLeader(wallet.wallet_address, wallet.enabled !== false, button);
        actionCell.appendChild(button);
        row.appendChild(actionCell);
        body.appendChild(row);
      }
    }

    async function toggleLeader(walletAddress, currentlyEnabled, button) {
      if (!walletAddress) return;
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = currentlyEnabled ? '暂停中' : '启动中';
      try {
        const response = await fetch('/api/leaders/toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ wallet_address: walletAddress, enabled: !currentlyEnabled }),
        });
        const result = await readJson(response);
        if (!response.ok || !result.ok) {
          throw new Error(result.error || 'Leader 操作失败');
        }
        dashboard = result.dashboard || dashboard;
        render();
        showLiquidationNotice(result.liquidation);
      } catch (error) {
        button.disabled = false;
        button.textContent = originalText;
        window.alert(errorText(error));
      }
    }

    function renderCopyConfig() {
      const copyConfig = dashboard.copy_trading_config || {};
      const wallets = copyConfig.wallets || [];
      const body = document.getElementById('copyConfigRows');
      const notice = document.getElementById('copyConfigNotice');
      if (!body || !notice) return;
      notice.textContent = '保存仅更新白名单跟单参数；tiny_real 上限仍限制单笔 <= 0.01 SOL、日亏 <= 0.03 SOL、滑点 <= 5%。';
      body.innerHTML = '';
      if (!wallets.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 10;
        cell.className = 'empty';
        cell.textContent = '暂无可配置 Leader。';
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      for (const wallet of wallets) {
        const limits = wallet.risk_limits || {};
        const paused = wallet.enabled === false || wallet.mode === 'paused';
        const row = document.createElement('tr');
        row.className = [wallet.score_status === 'low' ? 'score-low' : '', paused ? 'is-paused' : ''].filter(Boolean).join(' ');
        row.dataset.walletAddress = wallet.wallet_address || '';

        const leaderCell = document.createElement('td');
        leaderCell.className = 'leader-cell';
        const leaderTitle = document.createElement('strong');
        leaderTitle.textContent = wallet.label || '未命名 Leader';
        const leaderMeta = document.createElement('small');
        leaderMeta.textContent = `${shortAddress(wallet.wallet_address)} ${wallet.wallet_address || ''} · ${wallet.grade || '-'} / ${wallet.total_score ?? '-'}`;
        leaderCell.appendChild(leaderTitle);
        leaderCell.appendChild(leaderMeta);
        if (wallet.score_warning) {
          const warning = document.createElement('small');
          warning.className = 'score-warning';
          warning.textContent = wallet.score_warning;
          leaderCell.appendChild(warning);
        }
        row.appendChild(leaderCell);

        const statusCell = document.createElement('td');
        const status = document.createElement('span');
        status.className = paused ? 'status-pill paused' : 'status-pill';
        status.textContent = paused ? '已暂停：不参与自动权重分配' : '启用：权重按评分自动计算';
        statusCell.appendChild(status);
        row.appendChild(statusCell);

        row.appendChild(copyConfigInputCell('mode', wallet.mode || 'follow', `
          <select name="mode">
            <option value="follow">跟随买卖</option>
            <option value="observe">仅观察</option>
            <option value="paused">暂停跟单</option>
          </select>
        `));
        row.querySelector('select[name="mode"]').value = wallet.mode || 'follow';
        row.appendChild(copyConfigInputCell('copy_weight', wallet.copy_weight ?? 0, '<input name="copy_weight" type="number" min="0" max="1" step="0.001" disabled>'));
        row.appendChild(copyConfigInputCell('max_single_trade_sol', limits.max_single_trade_sol ?? 0.01, '<input name="max_single_trade_sol" type="number" min="0" max="0.01" step="0.001">'));
        row.appendChild(copyConfigInputCell('max_daily_loss_sol', limits.max_daily_loss_sol ?? 0.03, '<input name="max_daily_loss_sol" type="number" min="0" max="0.03" step="0.001">'));
        row.appendChild(copyConfigInputCell('max_daily_trades', limits.max_daily_trades ?? 3, '<input name="max_daily_trades" type="number" min="0" max="20" step="1">'));
        row.appendChild(copyConfigInputCell('slippage_percent', limits.slippage_percent ?? 2, '<input name="slippage_percent" type="number" min="0" max="5" step="0.1">'));
        row.appendChild(copyConfigInputCell('stop_loss_percent', limits.stop_loss_percent ?? -40, '<input name="stop_loss_percent" type="number" min="-99" max="0" step="1">'));

        const actionCell = document.createElement('td');
        const saveButton = document.createElement('button');
        saveButton.type = 'button';
        saveButton.textContent = '保存';
        saveButton.onclick = () => saveLeaderConfig(wallet.wallet_address, row);
        actionCell.appendChild(saveButton);
        row.appendChild(actionCell);
        body.appendChild(row);
      }
    }

    function copyConfigInputCell(name, value, html) {
      const cell = document.createElement('td');
      cell.innerHTML = html;
      const field = cell.querySelector(`[name="${name}"]`);
      if (field && field.tagName !== 'SELECT') {
        field.value = value;
      }
      return cell;
    }

    async function saveLeaderConfig(walletAddress, row) {
      if (!walletAddress) return;
      const button = row.querySelector('button');
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = '保存中';
      const payload = {
        wallet_address: walletAddress,
        mode: row.querySelector('[name="mode"]').value,
        copy_weight: Number(row.querySelector('[name="copy_weight"]').value),
        max_single_trade_sol: Number(row.querySelector('[name="max_single_trade_sol"]').value),
        max_daily_loss_sol: Number(row.querySelector('[name="max_daily_loss_sol"]').value),
        max_daily_trades: Number(row.querySelector('[name="max_daily_trades"]').value),
        slippage_percent: Number(row.querySelector('[name="slippage_percent"]').value),
        stop_loss_percent: Number(row.querySelector('[name="stop_loss_percent"]').value),
      };
      try {
        const response = await fetch('/api/leaders/config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const result = await readJson(response);
        if (!response.ok || !result.ok) {
          throw new Error(result.error || '跟单配置保存失败');
        }
        dashboard = result.dashboard || dashboard;
        render();
        document.getElementById('copyConfigNotice').textContent = '跟单配置已保存。';
        showLiquidationNotice(result.liquidation);
      } catch (error) {
        document.getElementById('copyConfigNotice').textContent = `保存失败：${String(error)}`;
      } finally {
        button.disabled = false;
        button.textContent = originalText;
      }
    }

    function showLiquidationNotice(liquidation) {
      if (!liquidation || !liquidation.triggered) return;
      const results = liquidation.results || [];
      const successCount = results.filter(item => item.success).length;
      const failedCount = results.length - successCount;
      const message = `Leader 移出跟单后已触发平仓检查：匹配 ${liquidation.matched_positions || 0} 个持仓，成功 ${successCount}，失败 ${failedCount}。`;
      const portfolioNotice = document.getElementById('portfolioActionNotice');
      const copyNotice = document.getElementById('copyConfigNotice');
      if (portfolioNotice) portfolioNotice.textContent = message;
      if (copyNotice) copyNotice.textContent = message;
      loadPortfolio({ renderPositions: true }).catch(error => {
        if (portfolioNotice) portfolioNotice.textContent = `${message} 持仓刷新失败：${String(error)}`;
      });
    }

    function renderTokenExitConfig() {
      const exitConfig = dashboard.token_exit_config || {};
      const tokens = exitConfig.tokens || [];
      const container = document.getElementById('tokenExitGrid');
      const notice = document.getElementById('tokenExitNotice');
      if (!container || !notice) return;
      notice.textContent = '保存后写入 data/signal_cache.json；后续 TP/SL 扫描会按这些比例判断当前持仓。止盈卖出比例两档合计必须为 100%。';
      container.innerHTML = '';
      if (!tokens.length) {
        const empty = document.createElement('div');
        empty.className = 'empty';
        empty.textContent = '暂无持仓代币可配置。';
        container.appendChild(empty);
        return;
      }
      for (const token of tokens) {
        const tpOrders = token.tp_orders || [];
        const tp1 = tpOrders[0] || { trigger_percent: 100, sell_percent: 50 };
        const tp2 = tpOrders[1] || { trigger_percent: 300, sell_percent: 50 };
        const sl = token.sl_order || { trigger_percent: -40 };
        const card = document.createElement('article');
        card.className = 'leader-config-card';
        const title = document.createElement('h3');
        title.textContent = token.symbol || 'unknown';
        const meta = document.createElement('div');
        meta.className = 'small';
        meta.textContent = `${shortAddress(token.token_address)} · ${token.configured ? '已配置' : '默认参数'}`;
        card.appendChild(title);
        card.appendChild(meta);
        const form = document.createElement('form');
        form.className = 'config-form';
        form.innerHTML = `
          <label>止损 %
            <input name="stop_loss_percent" type="number" min="-99" max="-0.0001" step="any" value="${sl.trigger_percent ?? -40}">
          </label>
          <label>最大滑点 %
            <input name="max_slippage_percent" type="number" min="0" max="5" step="0.1" value="${token.max_slippage_percent ?? 2}">
          </label>
          <label>止盈 1 触发 %
            <input name="tp1_trigger_percent" type="number" min="0.0001" max="10000" step="any" value="${tp1.trigger_percent ?? 100}">
          </label>
          <label>止盈 1 卖出 %
            <input name="tp1_sell_percent" type="number" min="0.0001" max="100" step="any" value="${tp1.sell_percent ?? 50}">
          </label>
          <label>止盈 2 触发 %
            <input name="tp2_trigger_percent" type="number" min="0.0001" max="10000" step="any" value="${tp2.trigger_percent ?? 300}">
          </label>
          <label>止盈 2 卖出 %
            <input name="tp2_sell_percent" type="number" min="0.0001" max="100" step="any" value="${tp2.sell_percent ?? 50}">
          </label>
          <button type="submit">保存 ${token.symbol || '代币'}</button>
        `;
        form.onsubmit = event => {
          event.preventDefault();
          saveTokenExitConfig(token.token_address, form);
        };
        card.appendChild(form);
        container.appendChild(card);
      }
    }

    async function saveTokenExitConfig(tokenAddress, form) {
      if (!tokenAddress) return;
      const button = form.querySelector('button[type="submit"]');
      const originalText = button.textContent;
      button.disabled = true;
      button.textContent = '保存中';
      const payload = {
        token_address: tokenAddress,
        stop_loss_percent: Number(form.elements.stop_loss_percent.value),
        max_slippage_percent: Number(form.elements.max_slippage_percent.value),
        tp1_trigger_percent: Number(form.elements.tp1_trigger_percent.value),
        tp1_sell_percent: Number(form.elements.tp1_sell_percent.value),
        tp2_trigger_percent: Number(form.elements.tp2_trigger_percent.value),
        tp2_sell_percent: Number(form.elements.tp2_sell_percent.value),
      };
      try {
        const response = await fetch('/api/tokens/exit-config', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(payload),
        });
        const result = await readJson(response);
        if (!response.ok || !result.ok) {
          throw new Error(result.error || '代币止损止盈配置保存失败');
        }
        dashboard = result.dashboard || dashboard;
        render();
        document.getElementById('tokenExitNotice').textContent = '代币止损止盈配置已保存。';
      } catch (error) {
        document.getElementById('tokenExitNotice').textContent = `保存失败：${String(error)}`;
      } finally {
        button.disabled = false;
        button.textContent = originalText;
      }
    }

    async function toggleAutomationGate(button) {
      const gate = dashboard.automation_gate || {};
      const currentlyEnabled = gate.enabled === true || gate.status === 'auto_trading_enabled';
      button.disabled = true;
      document.getElementById('gateBadge').textContent = currentlyEnabled ? '暂停中' : '启用中';
      try {
        const response = await fetch('/api/automation-gate/toggle', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled: !currentlyEnabled }),
        });
        const result = await readJson(response);
        if (!response.ok || !result.ok) {
          throw new Error(result.error || '自动化安全门操作失败');
        }
        dashboard = result.dashboard || dashboard;
        render();
      } catch (error) {
        window.alert(errorText(error));
        render();
      } finally {
        button.disabled = false;
      }
    }

    function formatNumber(value) {
      const number = Number(value || 0);
      if (!Number.isFinite(number)) return '0';
      return number.toFixed(Math.abs(number) >= 100 ? 2 : 4);
    }

    function formatOneDecimal(value) {
      const number = Number(value || 0);
      if (!Number.isFinite(number)) return '0.0';
      return number.toFixed(1);
    }

    function formatInteger(value) {
      const number = Number(value || 0);
      if (!Number.isFinite(number)) return '0';
      return String(Math.round(number));
    }

    function formatPriceWithUnit(value, unit, hasValue) {
      if (!hasValue) return '-';
      return `${formatPrice(value)} ${unit}`;
    }

    function formatPrice(value) {
      const number = Number(value);
      if (!Number.isFinite(number) || number === 0) return '-';
      if (Math.abs(number) >= 1) return number.toFixed(4);
      if (Math.abs(number) >= 0.0001) return number.toFixed(8);
      return number.toPrecision(8);
    }

    function formatPercent(value) {
      if (value === undefined || value === null || value === '') return '-';
      const text = String(value);
      return text.endsWith('%') ? text : `${text}%`;
    }

    function formatCopySource(position) {
      const wallet = position.copy_source_wallet || '';
      if (!wallet) return '未记录';
      const label = position.copy_source_label || '白名单 Leader';
      const status = position.copy_source_enabled === false ? '已暂停' : '';
      const inferred = position.copy_source_inferred ? '同持仓推断' : '';
      const notes = [status, inferred].filter(Boolean).join(' · ');
      return notes ? `${label} ${shortAddress(wallet)} · ${notes}` : `${label} ${shortAddress(wallet)}`;
    }

    function shortAddress(value) {
      if (!value) return '';
      return value.length > 12 ? `(${value.slice(0, 4)}...${value.slice(-4)})` : `(${value})`;
    }

    function renderDataSources() {
      const body = document.getElementById('dataSources');
      body.innerHTML = '';
      const sources = dashboard.data_sources || [];
      if (!sources.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 6;
        cell.className = 'empty';
        cell.textContent = '暂无数据源配置。';
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      for (const source of sources) {
        const row = document.createElement('tr');
        for (const key of ['name', 'status', 'health', 'alertable']) {
          const cell = document.createElement('td');
          cell.textContent = source[key];
          row.appendChild(cell);
        }
        const path = document.createElement('td');
        const code = document.createElement('code');
        code.textContent = source.path;
        path.appendChild(code);
        row.appendChild(path);
        const notes = document.createElement('td');
        notes.textContent = source.notes;
        row.appendChild(notes);
        body.appendChild(row);
      }
    }

    function renderAuditReport() {
      const report = dashboard.audit_report || {};
      const summary = document.getElementById('auditSummary');
      const body = document.getElementById('auditEvents');
      if (!summary || !body) return;
      const categories = report.categories || {};
      const cards = [
        ['全部事件', report.total || 0, report.path || 'data/audit_events.jsonl'],
        ['人工配置', categories.manual_config || 0, '配置保存、Leader 启停、白名单移动'],
        ['人工买卖', categories.manual_trade || 0, 'dashboard 人工买入/卖出请求'],
        ['自动买卖', categories.auto_trade || 0, '自动买入、TP/SL、止损卖出'],
        ['跟卖事件', categories.copy_trade || 0, '无论成功或失败均记录'],
        ['失败事件', report.failures || 0, '供复盘筛选'],
      ];
      summary.innerHTML = '';
      for (const [label, value, hint] of cards) {
        const card = document.createElement('article');
        card.className = 'signal-card clickable';
        card.innerHTML = `<span>${label}</span><strong>${value}</strong><small>${hint}</small>`;
        summary.appendChild(card);
      }
      body.innerHTML = '';
      const events = report.recent_events || [];
      if (!events.length) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 7;
        cell.className = 'empty';
        cell.textContent = '暂无审计事件。后续人工配置、人工买卖、自动买卖和跟卖都会写入 data/audit_events.jsonl。';
        row.appendChild(cell);
        body.appendChild(row);
        return;
      }
      for (const event of events) {
        const row = document.createElement('tr');
        row.className = event.success ? '' : 'score-low';
        const values = [
          formatTimestamp(event.timestamp),
          auditCategoryLabel(event.category),
          auditActionLabel(event.action),
          event.success ? '成功' : '失败',
          event.object_id ? `${event.object_type || ''} ${shortAddress(event.object_id)} ${event.object_id}` : event.object_type || '-',
          event.source || '-',
          event.message || '-',
        ];
        for (const value of values) {
          const cell = document.createElement('td');
          cell.textContent = value;
          row.appendChild(cell);
        }
        body.appendChild(row);
      }
    }

    function auditCategoryLabel(value) {
      return {
        manual_config: '人工配置',
        manual_trade: '人工买卖',
        auto_trade: '自动买卖',
        copy_trade: '跟卖',
      }[value] || value || '-';
    }

    function auditActionLabel(value) {
      return {
        trading_config_update: '交易配置',
        leader_toggle: 'Leader 启停',
        leader_config_update: '跟单参数',
        token_exit_config_update: '止盈止损配置',
        automation_gate_toggle: '自动交易开关',
        leader_pool_config_update: 'Leader 池配置',
        leader_promote_to_copy_whitelist: '加入跟单白名单',
        leader_recycle_to_candidates: '退回候选池',
        dashboard_manual_buy: '人工买入',
        dashboard_manual_sell: '人工卖出',
        auto_stop_loss_sell: '自动止损',
        leader_removed_liquidation: '移除 Leader 平仓检查',
        leader_removed_liquidation_sell: '移除 Leader 自动平仓',
        auto_buy: '自动买入',
        auto_copy_sell: '自动跟卖',
        auto_tpsl_sell: '自动 TP/SL',
      }[value] || value || '-';
    }

    refresh().catch(error => {
      document.getElementById('summaryWarning').textContent = `加载失败：${String(error)}`;
    });
  </script>
</body>
</html>
'''


if __name__ == '__main__':
    raise SystemExit(main())
