from __future__ import annotations

from gmgn_monitor.copy_risk import CopyRiskProfile
from gmgn_monitor.sell_executor import SellExecutor, SellSignal


class _FakeClient:
    def __init__(self, holdings):
        self._holdings = holdings
        self.swap_called = False

    def get_wallet_holdings(self, chain: str, wallet_address: str):
        return self._holdings

    def swap(self, params):
        self.swap_called = True
        return {"tx_hash": "api_tx"}


class _FakeRiskManager:
    def is_kill_switch_active(self):
        return False

    def is_circuit_breaker_active(self):
        return False


class _FakeOrder:
    order_id = "order-1"


class _FakeOrderManager:
    def create_sell_order(self, token_address: str, amount_sol: float, signal_id: str):
        return _FakeOrder()

    def submit_order(self, order_id: str, tx_hash: str | None = None):
        return None

    def confirm_order(self, order_id: str, actual_amount: float, actual_slippage: float, gas_cost: float):
        return None


class _FakePortfolio:
    def get_position(self, token_address: str):
        return None


def _make_executor(holdings) -> SellExecutor:
    executor = SellExecutor.__new__(SellExecutor)
    executor._chain = "sol"
    executor._wallet_address = "Wallet111"
    executor._client = _FakeClient(holdings)
    executor._risk_manager = _FakeRiskManager()
    executor._order_manager = _FakeOrderManager()
    executor._portfolio_tracker = _FakePortfolio()
    executor._auto_confirm = True
    executor._copy_risk = CopyRiskProfile()
    executor._gate_override = {"force_open": True}
    return executor


def test_get_token_balance_reads_gmgn_cli_list_token_shape():
    executor = _make_executor({
        "list": [{
            "balance": "144917.486034",
            "token": {
                "token_address": "3Q1Lu5TGWPvoA95HwTu7uPkjNLXj498moxfko2Pkpump",
                "symbol": "Catfish",
            },
        }]
    })

    balance = executor.get_token_balance("3Q1Lu5TGWPvoA95HwTu7uPkjNLXj498moxfko2Pkpump")

    assert balance == 144917.486034


def test_get_token_balance_keeps_nested_data_holdings_support():
    executor = _make_executor({
        "data": {
            "holdings": [{
                "token_address": "Token111",
                "ui_amount": "12.5",
            }]
        }
    })

    balance = executor.get_token_balance("token111")

    assert balance == 12.5


def test_execute_sell_prefers_gmgn_cli_percent_swap(monkeypatch):
    token = "Token111"
    executor = _make_executor({
        "data": {
            "holdings": [{
                "token_address": token,
                "balance": "12.5",
            }]
        }
    })
    commands = []

    class _Completed:
        def __init__(self, returncode=0, stdout="", stderr=""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def fake_run(command, **kwargs):
        commands.append(command)
        if command[:3] == ["gmgn-cli", "config", "--check"]:
            return _Completed(stdout="ok")
        return _Completed(stdout='{"tx_hash":"cli_tx","actual_slippage_percent":1.2,"gas_cost_sol":0.001}')

    monkeypatch.setattr("gmgn_monitor.sell_executor.shutil.which", lambda name: "/usr/local/bin/gmgn-cli")
    monkeypatch.setattr("gmgn_monitor.sell_executor.subprocess.run", fake_run)

    result = executor.execute_sell(SellSignal(
        signal_id="sell-1",
        token_address=token,
        sell_percent=100.0,
        trigger_type="COPY_EXIT",
        max_slippage_percent=5.0,
    ))

    assert result.success is True
    assert result.tx_hash == "cli_tx"
    assert executor._client.swap_called is False
    assert commands[1][:2] == ["gmgn-cli", "swap"]
    assert "--percent" in commands[1]
    assert commands[1][commands[1].index("--percent") + 1] == "100"
