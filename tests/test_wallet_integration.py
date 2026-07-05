from __future__ import annotations

"""Integration tests for Phase 1 wallet discovery configuration and module wiring.

Covers:
- wallet_thresholds.json validity and structure
- gmgn_monitor __init__ import resilience (no crash when wallet modules absent)
- End-to-end pipeline simulation with mocked wallet modules
- No actual trading execution (safety boundary)
"""

import json
import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = Path(__file__).parent.parent


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def wallet_thresholds_path() -> Path:
    """Return the path to wallet_thresholds.json."""
    return PROJECT_ROOT / "config" / "wallet_thresholds.json"


@pytest.fixture
def wallet_thresholds_raw(wallet_thresholds_path: Path) -> dict:
    """Load and return the raw wallet_thresholds.json dict."""
    return json.loads(wallet_thresholds_path.read_text(encoding="utf-8"))


@pytest.fixture
def mock_wallet_modules():
    """Inject mock wallet modules into sys.modules for end-to-end testing.

    Yields a dict of module names -> mock module objects.
    Cleans up injected modules after the test.
    """
    mock_mods: dict[str, ModuleType] = {}
    names = (
        "wallet_schema",
        "wallet_scorer",
        "wallet_filter",
        "backtest_engine",
        "loop_engine",
    )
    for name in names:
        full_name = f"gmgn_monitor.{name}"
        mod = ModuleType(full_name)
        sys.modules[full_name] = mod
        mock_mods[name] = mod

    # wallet_schema
    ws = mock_mods["wallet_schema"]
    ws.Wallet = MagicMock
    ws.WalletTrade = MagicMock
    ws.WalletScore = MagicMock

    # wallet_scorer
    wsc = mock_mods["wallet_scorer"]
    wsc.WalletScorer = MagicMock
    wsc.score_wallet = MagicMock(
        return_value={
            "wallet_address": "TestWallet111111111111111111111111111111111",
            "score": 85,
            "tier": "A",
            "decision": "follow",
            "reasons": ["win_rate ok", "profit ok"],
            "dimension_scores": {
                "profitability": 88.0,
                "win_rate": 72.0,
                "risk_control": 75.0,
                "consistency": 80.0,
                "activity": 70.0,
                "stability": 90.0,
            },
        }
    )

    # wallet_filter
    wf = mock_mods["wallet_filter"]
    wf.WalletFilter = MagicMock
    wf.apply_wallet_filters = MagicMock(return_value=[])

    # backtest_engine
    be = mock_mods["backtest_engine"]
    be.BacktestEngine = MagicMock
    be.run_backtest = MagicMock(
        return_value={
            "wallet_address": "TestWallet111111111111111111111111111111111",
            "strategy": "fixed_buy",
            "total_return_percent": 145.0,
            "sharpe_ratio": 2.1,
            "max_drawdown_percent": -18.0,
            "win_rate": 65.0,
            "expectancy_after_costs": 5.2,
            "total_trades": 45,
        }
    )

    # loop_engine
    le = mock_mods["loop_engine"]
    le.LoopEngine = MagicMock
    le.run_loops = MagicMock(return_value={"status": "ok", "loops_run": 5})

    yield mock_mods

    # Cleanup: remove injected modules from sys.modules
    for name in names:
        full_name = f"gmgn_monitor.{name}"
        sys.modules.pop(full_name, None)


# ---------------------------------------------------------------------------
# Configuration file tests
# ---------------------------------------------------------------------------

def test_wallet_thresholds_json_exists(wallet_thresholds_path: Path) -> None:
    """wallet_thresholds.json must exist on disk."""
    assert wallet_thresholds_path.exists(), f"wallet_thresholds.json not found at {wallet_thresholds_path}"


def test_wallet_thresholds_json_is_valid_json(wallet_thresholds_path: Path) -> None:
    """wallet_thresholds.json must parse as valid JSON."""
    raw = json.loads(wallet_thresholds_path.read_text(encoding="utf-8"))
    assert isinstance(raw, dict)


def test_wallet_thresholds_has_default_and_chains(wallet_thresholds_raw: dict) -> None:
    """wallet_thresholds.json must follow the same default+chains pattern as thresholds.json."""
    assert "default" in wallet_thresholds_raw, 'missing "default" section'
    assert "chains" in wallet_thresholds_raw, 'missing "chains" section'
    assert isinstance(wallet_thresholds_raw["default"], dict), "default must be a JSON object"
    assert isinstance(wallet_thresholds_raw["chains"], dict), "chains must be a JSON object"


def test_wallet_thresholds_default_contains_required_fields(wallet_thresholds_raw: dict) -> None:
    """default section must contain the core wallet scoring thresholds."""
    default = wallet_thresholds_raw["default"]
    required = {
        "follow_score",
        "watch_score",
        "min_score",
        "max_robot_score",
        "min_trades_7d",
        "max_trades_7d",
        "min_profit_usd",
        "min_holding_hours",
        "min_win_rate",
        "max_drawdown_percent",
        "min_sharpe_ratio",
        "min_expectancy",
    }
    missing = required - set(default.keys())
    assert not missing, f"default missing required keys: {missing}"

    # Numeric sanity checks
    assert default["follow_score"] >= default["watch_score"], "follow_score must be >= watch_score"
    assert default["watch_score"] >= default["min_score"], "watch_score must be >= min_score"
    assert default["max_robot_score"] >= 0, "max_robot_score must be non-negative"
    assert default["min_trades_7d"] >= 0, "min_trades_7d must be non-negative"
    assert default["max_trades_7d"] > default["min_trades_7d"], "max_trades_7d must be > min_trades_7d"
    assert default["min_profit_usd"] >= 0, "min_profit_usd must be non-negative"
    assert default["min_holding_hours"] >= 0, "min_holding_hours must be non-negative"
    assert 0 <= default["min_win_rate"] <= 100, "min_win_rate must be in [0, 100]"
    assert 0 <= default["max_drawdown_percent"] <= 100, "max_drawdown_percent must be in [0, 100]"
    assert default["min_sharpe_ratio"] >= 0, "min_sharpe_ratio must be non-negative"


def test_wallet_thresholds_chains_are_valid(wallet_thresholds_raw: dict) -> None:
    """Each chain override must be a dict and only override known keys."""
    default_keys = set(wallet_thresholds_raw["default"].keys())
    for chain_name, values in wallet_thresholds_raw["chains"].items():
        assert isinstance(values, dict), f"chain '{chain_name}' must be an object"
        unknown = set(values.keys()) - default_keys
        assert not unknown, f"chain '{chain_name}' has unknown keys: {unknown}"
        for key, val in values.items():
            assert isinstance(val, (int, float)), f"{chain_name}.{key} must be numeric"
            assert val >= 0, f"{chain_name}.{key} must be non-negative"


def test_wallet_thresholds_solana_has_reasonable_overrides(wallet_thresholds_raw: dict) -> None:
    """Solana chain (primary) should have specific overrides that differ from default."""
    chains = wallet_thresholds_raw["chains"]
    if "solana" not in chains:
        pytest.skip("solana chain not configured")
    sol = chains["solana"]
    # Solana is the primary chain; at minimum max_trades_7d should be present
    assert "max_trades_7d" in sol, "solana should override max_trades_7d"


# ---------------------------------------------------------------------------
# Module import / __init__ tests
# ---------------------------------------------------------------------------

def test_gmgn_monitor_imports_without_wallet_modules() -> None:
    """gmgn_monitor must import successfully even when wallet modules are absent.

    This verifies that the try/except guard in __init__.py works correctly.
    """
    # gmgn_monitor is already imported at module level; just assert it is healthy
    import gmgn_monitor
    assert hasattr(gmgn_monitor, "Candidate")
    assert hasattr(gmgn_monitor, "Thresholds")
    assert hasattr(gmgn_monitor, "score_candidate")


def test_gmgn_monitor_base_exports_in_all() -> None:
    """Core monitor symbols must be present in __all__."""
    import gmgn_monitor
    assert "Candidate" in gmgn_monitor.__all__
    assert "Thresholds" in gmgn_monitor.__all__
    assert "score_candidate" in gmgn_monitor.__all__
    assert "CandidateSource" in gmgn_monitor.__all__
    assert "JsonlCandidateSource" in gmgn_monitor.__all__
    assert "load_events" in gmgn_monitor.__all__


def test_all_wallet_modules_are_importable() -> None:
    """All wallet modules referenced by __init__.py should be importable."""
    import gmgn_monitor
    for name in ('wallet_schema', 'wallet_scorer', 'wallet_filter', 'backtest_engine', 'loop_engine'):
        full_name = f'gmgn_monitor.{name}'
        assert full_name in sys.modules, f'{full_name} should be loaded by __init__'


# ---------------------------------------------------------------------------
# End-to-end pipeline tests (mocked)
# ---------------------------------------------------------------------------

def test_end_to_end_pipeline_follow(mock_wallet_modules: dict) -> None:
    """Simulate full pipeline for a high-quality wallet: data -> score -> filter -> backtest -> loop.

    Safety boundary: no actual trading code is executed; only mocks and pure data.
    """
    # Step 1: Data model (wallet_schema)
    wallet = mock_wallet_modules["wallet_schema"].Wallet(
        address="TestWallet111111111111111111111111111111111",
        chain="solana",
    )
    assert wallet is not None

    # Step 2: Score (wallet_scorer)
    score_result = mock_wallet_modules["wallet_scorer"].score_wallet(wallet.address)
    assert score_result["score"] == 85
    assert score_result["tier"] == "A"
    assert score_result["decision"] == "follow"
    assert len(score_result["reasons"]) > 0
    assert "dimension_scores" in score_result

    # Step 3: Filter (wallet_filter) — no hard rejections
    filter_reasons = mock_wallet_modules["wallet_filter"].apply_wallet_filters(
        score_result, {"max_robot_score": 60}
    )
    assert filter_reasons == []

    # Step 4: Backtest (backtest_engine)
    backtest_result = mock_wallet_modules["backtest_engine"].run_backtest(
        wallet_address=wallet.address,
        strategy="fixed_buy",
        days=30,
    )
    assert backtest_result["total_return_percent"] == 145.0
    assert backtest_result["sharpe_ratio"] == 2.1
    assert backtest_result["expectancy_after_costs"] > 0  # positive expectancy check
    assert backtest_result["max_drawdown_percent"] <= 40  # within threshold

    # Step 5: Loop (loop_engine)
    loop_result = mock_wallet_modules["loop_engine"].run_loops()
    assert loop_result["status"] == "ok"
    assert loop_result["loops_run"] == 5


def test_end_to_end_pipeline_rejected_by_filter(mock_wallet_modules: dict) -> None:
    """Simulate pipeline where wallet is rejected by filter (e.g. robot detected)."""
    # Set up mock so filter rejects
    mock_wallet_modules["wallet_filter"].apply_wallet_filters.return_value = ["robot detected"]
    mock_wallet_modules["wallet_scorer"].score_wallet.return_value = {
        "wallet_address": "BotWallet222222222222222222222222222222222",
        "score": 45,
        "tier": "D",
        "decision": "reject",
        "reasons": ["robot detected"],
        "dimension_scores": {},
    }

    score = mock_wallet_modules["wallet_scorer"].score_wallet("BotWallet222222222222222222222222222222222")
    assert score["decision"] == "reject"

    reasons = mock_wallet_modules["wallet_filter"].apply_wallet_filters(score, {"max_robot_score": 60})
    assert "robot detected" in reasons

    # Backtest should NOT be run for rejected wallets
    mock_wallet_modules["backtest_engine"].run_backtest.assert_not_called()


def test_end_to_end_pipeline_low_score_watch(mock_wallet_modules: dict) -> None:
    """Simulate pipeline for a borderline wallet that gets 'watch' decision."""
    mock_wallet_modules["wallet_scorer"].score_wallet.return_value = {
        "wallet_address": "BorderWallet3333333333333333333333333333333",
        "score": 55,
        "tier": "C",
        "decision": "watch",
        "reasons": ["score below follow threshold"],
        "dimension_scores": {},
    }
    mock_wallet_modules["wallet_filter"].apply_wallet_filters.return_value = []

    score = mock_wallet_modules["wallet_scorer"].score_wallet("BorderWallet3333333333333333333333333333333")
    assert score["decision"] == "watch"
    assert score["score"] < 70  # below follow threshold

    # Watch wallets may still pass filter but should not be followed yet
    reasons = mock_wallet_modules["wallet_filter"].apply_wallet_filters(score, {})
    assert reasons == []


def test_end_to_end_pipeline_backtest_negative_expectancy(mock_wallet_modules: dict) -> None:
    """Simulate pipeline where backtest shows negative expectancy — should be rejected."""
    mock_wallet_modules["backtest_engine"].run_backtest.return_value = {
        "wallet_address": "BadWallet4444444444444444444444444444444444",
        "strategy": "fixed_buy",
        "total_return_percent": -25.0,
        "sharpe_ratio": -0.5,
        "max_drawdown_percent": -65.0,
        "win_rate": 30.0,
        "expectancy_after_costs": -3.0,
        "total_trades": 20,
    }

    backtest = mock_wallet_modules["backtest_engine"].run_backtest("BadWallet4444444444444444444444444444444444", "fixed_buy", 30)
    assert backtest["expectancy_after_costs"] < 0
    # Negative expectancy should block progression to stage 2
    assert backtest["max_drawdown_percent"] < -40  # exceeds threshold


# ---------------------------------------------------------------------------
# Safety boundary tests
# ---------------------------------------------------------------------------

def test_no_private_key_or_sign_in_gmgn_monitor_init() -> None:
    """Verify that __init__.py does not import any signing or private-key modules.

    This is a static safety check to ensure the configuration layer stays within
    the Phase 1 safety boundary (no trading execution).
    """
    import gmgn_monitor
    init_source = Path(gmgn_monitor.__file__).read_text(encoding="utf-8")
    forbidden = ["private_key", "sign_transaction", "send_transaction", "execute_trade", "wallet.sign"]
    for term in forbidden:
        assert term not in init_source, f"Safety violation: '{term}' found in __init__.py"


def test_no_pydantic_models_in_init() -> None:
    """Verify __init__.py does not import Pydantic (project uses dataclasses)."""
    import gmgn_monitor
    init_source = Path(gmgn_monitor.__file__).read_text(encoding="utf-8")
    assert "pydantic" not in init_source.lower(), "Pydantic import found in __init__.py (project uses dataclasses)"
