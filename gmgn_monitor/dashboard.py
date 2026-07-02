from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse

from .status import build_status


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
        'name': 'DEX Screener Search',
        'status': '只读原型',
        'path': 'gmgn_monitor/dexscreener.py',
        'paths': ['fixtures/dexscreener_search_sample.json', 'data/dexscreener_candidates.jsonl', 'data/dexscreener_events.jsonl'],
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
        if path == '/':
            self._send_text(INDEX_HTML, 'text/html; charset=utf-8')
            return
        if path == '/api/status':
            self._send_json(build_dashboard_payload(self.root))
            return
        self.send_error(404)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
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
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, body: str, content_type: str, status: int = 200) -> None:
        data = body.encode('utf-8')
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(data)))
        self.end_headers()
        self.wfile.write(data)


def make_handler(root: Path) -> type[DashboardHandler]:
    root = root.resolve()

    class BoundDashboardHandler(DashboardHandler):
        pass

    BoundDashboardHandler.root = root
    return BoundDashboardHandler


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
        'data_sources': build_data_sources(root),
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
    print(f'GMGN dashboard: http://{host}:{selected_port}')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('GMGN dashboard stopped')
    finally:
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
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>GMGN 扫链监控</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f7f8fa;
      --panel: #ffffff;
      --ink: #17202a;
      --muted: #607080;
      --line: #d9e0e7;
      --accent: #1b7f6f;
      --warn: #9d5a00;
      --bad: #b3261e;
      --good: #1a7f37;
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--ink);
      font: 14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }
    header {
      border-bottom: 1px solid var(--line);
      background: var(--panel);
      padding: 16px 24px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 16px;
      position: sticky;
      top: 0;
      z-index: 2;
    }
    h1 {
      font-size: 20px;
      margin: 0;
      letter-spacing: 0;
    }
    main {
      max-width: 1320px;
      margin: 0 auto;
      padding: 20px 24px 28px;
    }
    .status-grid {
      display: grid;
      grid-template-columns: repeat(4, minmax(150px, 1fr));
      gap: 12px;
      margin-bottom: 16px;
    }
    .metric, .section, .output {
      background: var(--panel);
      border: 1px solid var(--line);
      border-radius: 8px;
    }
    .metric {
      padding: 12px;
      min-height: 82px;
    }
    .metric span {
      display: block;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 7px;
    }
    .metric strong {
      display: block;
      font-size: 22px;
      line-height: 1.1;
      overflow-wrap: anywhere;
    }
    .notice {
      color: var(--bad);
      font-size: 13px;
      margin: -6px 0 14px;
    }
    .badge {
      border-radius: 999px;
      display: inline-flex;
      align-items: center;
      font-weight: 700;
      line-height: 1;
      padding: 7px 10px;
      text-transform: uppercase;
    }
    .ok { background: #e8f5ee; color: var(--good); }
    .blocked { background: #fff3df; color: var(--warn); }
    .fail { background: #fdecea; color: var(--bad); }
    .section {
      padding: 14px;
      margin-bottom: 16px;
    }
    .section h2 {
      font-size: 15px;
      margin: 0 0 12px;
    }
    .actions {
      display: flex;
      flex-wrap: wrap;
      gap: 8px;
    }
    .workflow {
      display: grid;
      grid-template-columns: repeat(5, minmax(0, 1fr));
      gap: 10px;
    }
    .workflow-step {
      border: 1px solid var(--line);
      border-radius: 8px;
      min-height: 150px;
      padding: 12px;
    }
    .workflow-step strong {
      display: block;
      font-size: 13px;
      line-height: 1.25;
      margin-bottom: 8px;
    }
    .workflow-step p {
      color: var(--muted);
      font-size: 12px;
      margin: 0 0 10px;
    }
    .workflow-step span {
      color: var(--accent);
      display: block;
      font-size: 12px;
      font-weight: 700;
      overflow-wrap: anywhere;
    }
    .source-table {
      border-collapse: collapse;
      width: 100%;
    }
    .source-table th, .source-table td {
      border-top: 1px solid var(--line);
      padding: 9px 8px;
      text-align: left;
      vertical-align: top;
    }
    .source-table th {
      color: var(--muted);
      font-size: 12px;
      font-weight: 700;
    }
    .source-table td {
      font-size: 13px;
    }
    .source-table code {
      font: 12px/1.4 ui-monospace, SFMono-Regular, Menlo, monospace;
      overflow-wrap: anywhere;
    }
    button {
      appearance: none;
      background: var(--ink);
      border: 1px solid var(--ink);
      border-radius: 7px;
      color: #fff;
      cursor: pointer;
      font: inherit;
      font-weight: 650;
      min-height: 36px;
      padding: 8px 11px;
    }
    button.secondary {
      background: #fff;
      color: var(--ink);
      border-color: var(--line);
    }
    button:disabled {
      cursor: progress;
      opacity: .55;
    }
    .layout {
      display: grid;
      grid-template-columns: 220px minmax(0, 1fr);
      gap: 16px;
      align-items: start;
    }
    .tabs {
      display: grid;
      gap: 6px;
    }
    .tabs button {
      background: #fff;
      border-color: var(--line);
      color: var(--ink);
      justify-content: flex-start;
      text-align: left;
      width: 100%;
    }
    .tabs button.active {
      border-color: var(--accent);
      color: var(--accent);
    }
    .output h2 {
      border-bottom: 1px solid var(--line);
      font-size: 15px;
      margin: 0;
      padding: 12px 14px;
    }
    pre {
      margin: 0;
      max-height: 560px;
      overflow: auto;
      padding: 14px;
      white-space: pre-wrap;
      word-break: break-word;
      font: 12px/1.5 ui-monospace, SFMono-Regular, Menlo, monospace;
    }
    .log {
      background: #111820;
      border-radius: 8px;
      color: #e8edf2;
      display: none;
      margin-top: 12px;
      max-height: 260px;
    }
    .log.visible { display: block; }
    .small {
      color: var(--muted);
      font-size: 12px;
    }
    @media (max-width: 820px) {
      header { align-items: flex-start; flex-direction: column; }
      main { padding: 14px; }
      .status-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
      .workflow { grid-template-columns: 1fr; }
      .layout { grid-template-columns: 1fr; }
    }
  </style>
</head>
<body>
  <header>
    <h1>GMGN 扫链监控</h1>
    <div id="headline" class="small">加载中</div>
  </header>
  <main>
    <section class="status-grid" aria-label="状态指标">
      <div class="metric"><span>系统状态</span><strong id="statusBadge" class="badge">...</strong></div>
      <div class="metric"><span>自动化安全门</span><strong id="gateBadge" class="badge blocked">...</strong></div>
      <div class="metric"><span>候选数量</span><strong id="candidateCount">...</strong></div>
      <div class="metric"><span>报告年龄</span><strong id="reportAge">...</strong></div>
    </section>
    <div id="summaryWarning" class="notice"></div>
    <section class="section">
      <h2>操作命令</h2>
      <div id="actions" class="actions"></div>
      <pre id="commandLog" class="log"></pre>
    </section>
    <section class="section">
      <h2>用户执行流程</h2>
      <div id="userFlow" class="workflow"></div>
    </section>
    <section class="section">
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
    <section class="layout">
      <nav id="tabs" class="tabs" aria-label="输出文件"></nav>
      <section class="output">
        <h2 id="outputTitle">输出结果</h2>
        <pre id="outputContent"></pre>
      </section>
    </section>
  </main>
  <script>
    let currentOutput = 'daily_summary';
    let dashboard = null;

    async function refresh() {
      const response = await fetch('/api/status');
      dashboard = await response.json();
      render();
    }

    function render() {
      const status = dashboard.status || {};
      const summary = readOperationalSummary();
      setBadge('statusBadge', status.status || 'unknown');
      setBadge('gateBadge', summary.automation_gate_status || 'unknown');
      document.getElementById('candidateCount').textContent = summary.candidate_count ?? 0;
      document.getElementById('reportAge').textContent = `${status.report_age_minutes ?? 'n/a'} 分钟`;
      document.getElementById('headline').textContent = `报告时间 ${status.report_generated_at || '未生成'}`;
      document.getElementById('summaryWarning').textContent = summary.__error || '';
      renderActions();
      renderUserFlow();
      renderDataSources();
      renderTabs();
      renderOutput();
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

    function setBadge(id, value) {
      const element = document.getElementById(id);
      element.textContent = translateStatus(value);
      element.className = `badge ${value === 'ok' ? 'ok' : value === 'blocked' ? 'blocked' : value === 'eligible_for_tiny_size_testing' ? 'ok' : 'fail'}`;
    }

    function translateStatus(value) {
      const labels = {
        ok: '正常',
        blocked: '已阻断',
        fail: '失败',
        eligible_for_tiny_size_testing: '可小额测试',
        unknown: '未知'
      };
      return labels[value] || value || '未知';
    }

    function renderActions() {
      const actions = document.getElementById('actions');
      actions.innerHTML = '';
      for (const action of dashboard.actions || []) {
        const button = document.createElement('button');
        button.textContent = action.label;
        button.title = action.command;
        button.onclick = () => runAction(action.id, button);
        actions.appendChild(button);
      }
      const refreshButton = document.createElement('button');
      refreshButton.className = 'secondary';
      refreshButton.textContent = '重新加载视图';
      refreshButton.onclick = refresh;
      actions.appendChild(refreshButton);
    }

    function renderUserFlow() {
      const container = document.getElementById('userFlow');
      container.innerHTML = '';
      for (const step of dashboard.user_flow || []) {
        const item = document.createElement('article');
        item.className = 'workflow-step';
        const title = document.createElement('strong');
        title.textContent = step.title;
        const body = document.createElement('p');
        body.textContent = step.body;
        const action = document.createElement('span');
        action.textContent = step.action;
        item.appendChild(title);
        item.appendChild(body);
        item.appendChild(action);
        container.appendChild(item);
      }
    }

    function renderDataSources() {
      const body = document.getElementById('dataSources');
      body.innerHTML = '';
      for (const source of dashboard.data_sources || []) {
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

    function renderTabs() {
      const tabs = document.getElementById('tabs');
      tabs.innerHTML = '';
      for (const [id, output] of Object.entries(dashboard.outputs || {})) {
        const button = document.createElement('button');
        button.className = id === currentOutput ? 'active' : '';
        button.textContent = output.label;
        button.onclick = () => {
          currentOutput = id;
          renderTabs();
          renderOutput();
        };
        tabs.appendChild(button);
      }
    }

    function renderOutput() {
      const output = dashboard.outputs?.[currentOutput];
      document.getElementById('outputTitle').textContent = output ? `${output.label} - ${output.path}` : '输出结果';
      document.getElementById('outputContent').textContent = output?.read_error ? `读取失败：${output.read_error}` : (output?.content || '尚未生成输出。');
    }

    async function runAction(actionId, button) {
      const buttons = document.querySelectorAll('button');
      buttons.forEach(item => item.disabled = true);
      const log = document.getElementById('commandLog');
      log.classList.add('visible');
      log.textContent = `正在运行 ${actionId}...`;
      try {
        const response = await fetch(`/api/actions/${actionId}`, { method: 'POST' });
        const result = await response.json();
        dashboard = result.dashboard || dashboard;
        log.textContent = `${result.command}\n\n退出码 ${result.returncode}\n\n${result.stdout || ''}${result.stderr ? '\n' + result.stderr : ''}`;
        render();
      } catch (error) {
        log.textContent = String(error);
      } finally {
        buttons.forEach(item => item.disabled = false);
      }
    }

    refresh().catch(error => {
      document.getElementById('headline').textContent = String(error);
    });
  </script>
</body>
</html>
'''


if __name__ == '__main__':
    raise SystemExit(main())
