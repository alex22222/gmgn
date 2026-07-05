from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from gmgn_monitor.config_manager import (
    ConfigManager,
    DEFAULT_CHAIN_CONFIG,
    DEFAULT_ITERATION_PARAMS,
    SUPPORTED_CHAINS,
    __all__,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_config(tmp_path: Path) -> Path:
    return tmp_path / "config.json"


# ---------------------------------------------------------------------------
# Initialization and defaults
# ---------------------------------------------------------------------------

class TestConfigManagerInit:
    def test_default_path(self) -> None:
        config = ConfigManager()
        assert config._config_path == Path(os.path.expanduser("~/.config/gmgn/config.json"))

    def test_custom_path(self, tmp_config: Path) -> None:
        config = ConfigManager(config_path=str(tmp_config))
        assert config._config_path == tmp_config

    def test_creates_parent_dirs_on_save(self, tmp_path: Path) -> None:
        config_path = tmp_path / "nested" / "gmgn" / "config.json"
        config = ConfigManager(config_path=str(config_path))
        config.save_iteration_config({"wallet_count": 50})
        assert config_path.exists()


# ---------------------------------------------------------------------------
# API keys
# ---------------------------------------------------------------------------

class TestConfigManagerApiKeys:
    def test_no_env_vars_returns_none(self, tmp_config: Path) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigManager(config_path=str(tmp_config))
            assert config.gmgn_api_key is None
            assert config.gmgn_private_key is None

    def test_reads_env_vars(self, tmp_config: Path) -> None:
        with patch.dict(
            os.environ,
            {"GMGN_API_KEY": "test-api-key", "GMGN_PRIVATE_KEY": "test-private-key"},
        ):
            config = ConfigManager(config_path=str(tmp_config))
            assert config.gmgn_api_key == "test-api-key"
            assert config.gmgn_private_key == "test-private-key"

    def test_config_file_overrides_none(self, tmp_config: Path) -> None:
        tmp_config.write_text(
            json.dumps({"gmgn_api_key": "file-key"}),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigManager(config_path=str(tmp_config))
            assert config.gmgn_api_key == "file-key"

    def test_env_var_overrides_config_file(self, tmp_config: Path) -> None:
        tmp_config.write_text(
            json.dumps({"gmgn_api_key": "file-key"}),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {"GMGN_API_KEY": "env-key"}):
            config = ConfigManager(config_path=str(tmp_config))
            assert config.gmgn_api_key == "env-key"

    def test_empty_string_env_is_none(self, tmp_config: Path) -> None:
        with patch.dict(os.environ, {"GMGN_API_KEY": ""}):
            config = ConfigManager(config_path=str(tmp_config))
            assert config.gmgn_api_key is None

    def test_wallet_address_reads_env_var(self, tmp_config: Path) -> None:
        with patch.dict(os.environ, {"GMGN_WALLET_ADDRESS": "WalletEnv111"}):
            config = ConfigManager(config_path=str(tmp_config))
            assert config.gmgn_wallet_address == "WalletEnv111"

    def test_wallet_address_reads_config_aliases(self, tmp_config: Path) -> None:
        tmp_config.write_text(
            json.dumps({"wallet_address": "WalletFile111"}),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigManager(config_path=str(tmp_config))
            assert config.gmgn_wallet_address == "WalletFile111"

        tmp_config.write_text(
            json.dumps({"gmgn_wallet_address": "WalletGmgn111", "wallet_address": "WalletFile111"}),
            encoding="utf-8",
        )
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigManager(config_path=str(tmp_config))
            assert config.gmgn_wallet_address == "WalletGmgn111"


# ---------------------------------------------------------------------------
# Iteration params
# ---------------------------------------------------------------------------

class TestConfigManagerIterationParams:
    def test_default_params(self, tmp_config: Path) -> None:
        config = ConfigManager(config_path=str(tmp_config))
        params = config.get_iteration_params()
        assert params["wallet_count"] == 200
        assert params["backtest_limit"] == 10
        assert params["whitelist_min_score"] == 50
        assert params["chain"] == "sol"
        assert params["score_threshold"] == 40
        assert params["max_backtest_wallets"] == 50

    def test_loaded_params_override_defaults(self, tmp_config: Path) -> None:
        tmp_config.write_text(
            json.dumps({"iteration_params": {"wallet_count": 500}}),
            encoding="utf-8",
        )
        config = ConfigManager(config_path=str(tmp_config))
        params = config.get_iteration_params()
        assert params["wallet_count"] == 500
        assert params["backtest_limit"] == 10  # still default

    def test_invalid_iteration_params_type_ignored(self, tmp_config: Path) -> None:
        tmp_config.write_text(
            json.dumps({"iteration_params": "not_a_dict"}),
            encoding="utf-8",
        )
        config = ConfigManager(config_path=str(tmp_config))
        params = config.get_iteration_params()
        assert params["wallet_count"] == DEFAULT_ITERATION_PARAMS["wallet_count"]

    def test_save_iteration_config(self, tmp_config: Path) -> None:
        config = ConfigManager(config_path=str(tmp_config))
        config.save_iteration_config({"wallet_count": 300, "backtest_limit": 20})
        assert tmp_config.exists()
        raw = json.loads(tmp_config.read_text(encoding="utf-8"))
        assert raw["iteration_params"]["wallet_count"] == 300
        assert raw["iteration_params"]["backtest_limit"] == 20

    def test_save_ignores_unknown_keys(self, tmp_config: Path) -> None:
        config = ConfigManager(config_path=str(tmp_config))
        config.save_iteration_config({"wallet_count": 100, "unknown_key": "ignored"})
        raw = json.loads(tmp_config.read_text(encoding="utf-8"))
        assert "unknown_key" not in raw["iteration_params"]


# ---------------------------------------------------------------------------
# Chain config
# ---------------------------------------------------------------------------

class TestConfigManagerChainConfig:
    def test_default_chain_configs(self, tmp_config: Path) -> None:
        config = ConfigManager(config_path=str(tmp_config))
        for chain in SUPPORTED_CHAINS:
            cfg = config.get_chain_config(chain)
            assert cfg["chain_id"] == DEFAULT_CHAIN_CONFIG[chain]["chain_id"]
            assert cfg["native_token"] == DEFAULT_CHAIN_CONFIG[chain]["native_token"]

    def test_unsupported_chain_falls_back_to_sol(self, tmp_config: Path) -> None:
        config = ConfigManager(config_path=str(tmp_config))
        cfg = config.get_chain_config("unsupported")
        assert cfg["chain_id"] == "solana"

    def test_chain_config_case_insensitive(self, tmp_config: Path) -> None:
        config = ConfigManager(config_path=str(tmp_config))
        assert config.get_chain_config("SOL") == config.get_chain_config("sol")
        assert config.get_chain_config("BSC") == config.get_chain_config("bsc")

    def test_chain_config_override_from_file(self, tmp_config: Path) -> None:
        tmp_config.write_text(
            json.dumps(
                {
                    "chains": {
                        "sol": {"native_token_price_usd": 200.0}
                    }
                }
            ),
            encoding="utf-8",
        )
        config = ConfigManager(config_path=str(tmp_config))
        cfg = config.get_chain_config("sol")
        assert cfg["native_token_price_usd"] == 200.0
        assert cfg["chain_id"] == "solana"  # still default

    def test_chain_config_invalid_chains_type_ignored(self, tmp_config: Path) -> None:
        tmp_config.write_text(
            json.dumps({"chains": "not_a_dict"}),
            encoding="utf-8",
        )
        config = ConfigManager(config_path=str(tmp_config))
        cfg = config.get_chain_config("sol")
        assert cfg["chain_id"] == "solana"


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestConfigManagerValidation:
    def test_validate_both_missing(self, tmp_config: Path) -> None:
        with patch.dict(os.environ, {}, clear=True):
            config = ConfigManager(config_path=str(tmp_config))
            result = config.validate_api_keys()
            assert result == {"gmgn_api_key": False, "gmgn_private_key": False}

    def test_validate_api_key_present(self, tmp_config: Path) -> None:
        with patch.dict(os.environ, {"GMGN_API_KEY": "key"}):
            config = ConfigManager(config_path=str(tmp_config))
            result = config.validate_api_keys()
            assert result == {"gmgn_api_key": True, "gmgn_private_key": False}

    def test_validate_both_present(self, tmp_config: Path) -> None:
        with patch.dict(
            os.environ,
            {"GMGN_API_KEY": "key", "GMGN_PRIVATE_KEY": "pk"},
        ):
            config = ConfigManager(config_path=str(tmp_config))
            result = config.validate_api_keys()
            assert result == {"gmgn_api_key": True, "gmgn_private_key": True}

    def test_validate_private_key_only(self, tmp_config: Path) -> None:
        with patch.dict(os.environ, {"GMGN_PRIVATE_KEY": "pk"}):
            config = ConfigManager(config_path=str(tmp_config))
            result = config.validate_api_keys()
            assert result == {"gmgn_api_key": False, "gmgn_private_key": True}


# ---------------------------------------------------------------------------
# Config file I/O
# ---------------------------------------------------------------------------

class TestConfigManagerFileIO:
    def test_loads_existing_json(self, tmp_config: Path) -> None:
        data = {"gmgn_api_key": "loaded", "iteration_params": {"wallet_count": 50}}
        tmp_config.write_text(json.dumps(data), encoding="utf-8")
        config = ConfigManager(config_path=str(tmp_config))
        assert config._config_data == data

    def test_loads_missing_file_as_empty(self, tmp_config: Path) -> None:
        config = ConfigManager(config_path=str(tmp_config))
        assert config._config_data == {}

    def test_loads_invalid_json_as_empty(self, tmp_config: Path) -> None:
        tmp_config.write_text("not json", encoding="utf-8")
        config = ConfigManager(config_path=str(tmp_config))
        assert config._config_data == {}

    def test_roundtrip_save_and_load(self, tmp_config: Path) -> None:
        config1 = ConfigManager(config_path=str(tmp_config))
        config1.save_iteration_config({"wallet_count": 999})
        config2 = ConfigManager(config_path=str(tmp_config))
        assert config2.get_iteration_params()["wallet_count"] == 999


# ---------------------------------------------------------------------------
# Exports
# ---------------------------------------------------------------------------

class TestConfigManagerExports:
    def test_all_list(self) -> None:
        assert "ConfigManager" in __all__
        assert "DEFAULT_ITERATION_PARAMS" in __all__
        assert "DEFAULT_CHAIN_CONFIG" in __all__
        assert "SUPPORTED_CHAINS" in __all__
