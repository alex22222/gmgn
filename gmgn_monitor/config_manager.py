from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


__all__ = [
    "ConfigManager",
    "DEFAULT_ITERATION_PARAMS",
    "DEFAULT_CHAIN_CONFIG",
    "SUPPORTED_CHAINS",
]


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_ITERATION_PARAMS: dict[str, Any] = {
    "wallet_count": 200,
    "backtest_limit": 10,
    "whitelist_min_score": 50,
    "chain": "sol",
    "score_threshold": 40,
    "max_backtest_wallets": 50,
}

DEFAULT_CHAIN_CONFIG: dict[str, Any] = {
    "sol": {
        "chain_id": "solana",
        "rpc_url": "https://api.mainnet-beta.solana.com",
        "native_token": "SOL",
        "native_token_price_usd": 150.0,
    },
    "bsc": {
        "chain_id": "bsc",
        "rpc_url": "https://bsc-dataseed.binance.org",
        "native_token": "BNB",
        "native_token_price_usd": 600.0,
    },
    "base": {
        "chain_id": "base",
        "rpc_url": "https://mainnet.base.org",
        "native_token": "ETH",
        "native_token_price_usd": 3500.0,
    },
    "eth": {
        "chain_id": "ethereum",
        "rpc_url": "https://eth.llamarpc.com",
        "native_token": "ETH",
        "native_token_price_usd": 3500.0,
    },
}

SUPPORTED_CHAINS: set[str] = {"sol", "bsc", "base", "eth"}

_ENV_GMGN_API_KEY = "GMGN_API_KEY"
_ENV_GMGN_PRIVATE_KEY = "GMGN_PRIVATE_KEY"
_ENV_GMGN_WALLET_ADDRESS = "GMGN_WALLET_ADDRESS"


# ---------------------------------------------------------------------------
# ConfigManager
# ---------------------------------------------------------------------------

class ConfigManager:
    """Manage API keys and iteration settings from env vars, config files, and defaults.

    The configuration hierarchy (highest precedence first):
    1. Environment variables (``GMGN_API_KEY``, ``GMGN_PRIVATE_KEY``)
    2. Explicitly loaded config file (``~/.config/gmgn/config.json``)
    3. Built-in defaults

    Usage::

        config = ConfigManager()
        api_key = config.gmgn_api_key
        params = config.get_iteration_params()
    """

    def __init__(self, config_path: str | None = None) -> None:
        self._config_path = Path(config_path or self._default_config_path())
        self._config_data: dict[str, Any] = {}
        self._load_config_file()

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def gmgn_api_key(self) -> str | None:
        """Return the GMGN API key from environment variable or config file."""
        env = os.environ.get(_ENV_GMGN_API_KEY)
        if env:
            return env
        return self._config_data.get("gmgn_api_key")

    @property
    def gmgn_signing_key(self) -> str | None:
        """Return the GMGN signing key from environment variable or config file.

        This key is reserved for Phase 2 (on-chain execution).
        """
        env = os.environ.get(_ENV_GMGN_PRIVATE_KEY)
        if env:
            return env
        return self._config_data.get("gmgn_signing_key")

    @property
    def gmgn_private_key(self) -> str | None:
        """Return the GMGN private key for Ed25519 API signing.

        Resolution order:
        1. ``GMGN_PRIVATE_KEY`` environment variable
        2. ``gmgn_private_key`` field in config.json
        3. Contents of ``~/.config/gmgn/keypair.pem``
        """
        env = os.environ.get(_ENV_GMGN_PRIVATE_KEY)
        if env:
            return env
        cfg = self._config_data.get("gmgn_private_key")
        if cfg:
            return cfg
        pem_path = self._config_path.parent / "keypair.pem"
        if pem_path.exists():
            with open(pem_path, "r", encoding="utf-8") as f:
                return f.read()
        return None

    @property
    def gmgn_wallet_address(self) -> str | None:
        """Return the configured wallet address, if present.

        Kept as a compatibility property for dashboard and operational scripts.
        It only returns an address string; it does not imply trading is enabled.
        """
        env = os.environ.get(_ENV_GMGN_WALLET_ADDRESS)
        if env:
            return env
        return self._config_data.get("gmgn_wallet_address") or self._config_data.get("wallet_address")

    @property
    def has_private_key(self) -> bool:
        """Return True if a private key is available for signed-auth requests."""
        return self.gmgn_private_key is not None

    def validate_api_keys(self) -> dict[str, bool]:
        """Validate which API credentials are available.

        Returns a dict of ``{credential: available}`` status.
        """
        return {
            "api_key": bool(self.gmgn_api_key),
            "private_key": bool(self.gmgn_private_key),
        }

    # ------------------------------------------------------------------
    # Iteration params
    # ------------------------------------------------------------------

    def get_iteration_params(self) -> dict[str, Any]:
        """Return a dict of iteration parameters merged from config and defaults.

        Keys:
            - ``wallet_count``: int (default 200)
            - ``backtest_limit``: int (default 10)
            - ``whitelist_min_score``: int (default 50)
            - ``chain``: str (default "sol")
            - ``score_threshold``: int (default 40)
            - ``max_backtest_wallets``: int (default 50)
        """
        stored = self._config_data.get("iteration_params", {})
        if not isinstance(stored, dict):
            stored = {}
        merged = dict(DEFAULT_ITERATION_PARAMS)
        merged.update(stored)
        return merged

    def save_iteration_config(self, params: dict[str, Any]) -> None:
        """Persist iteration parameters to the config file.

        Only keys that are present in :data:`DEFAULT_ITERATION_PARAMS` are
        written; unknown keys are silently ignored.
        """
        allowed = set(DEFAULT_ITERATION_PARAMS)
        filtered = {k: v for k, v in params.items() if k in allowed}
        self._config_data["iteration_params"] = filtered
        self._write_config_file()

    # ------------------------------------------------------------------
    # Chain config
    # ------------------------------------------------------------------

    def get_chain_config(self, chain: str = "sol") -> dict[str, Any]:
        """Return chain-specific settings for *chain* (default ``"sol"``).

        Supported chains: ``sol``, ``bsc``, ``base``, ``eth``.
        """
        chain = chain.lower()
        if chain not in SUPPORTED_CHAINS:
            chain = "sol"
        stored = self._config_data.get("chains", {})
        if not isinstance(stored, dict):
            stored = {}
        merged = dict(DEFAULT_CHAIN_CONFIG[chain])
        merged.update(stored.get(chain, {}))
        return merged

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _default_config_path() -> str:
        """Return the default configuration file path.

        Uses ``~/.config/gmgn/config.json`` on all platforms.
        """
        return os.path.expanduser("~/.config/gmgn/config.json")

    def _load_config_file(self) -> None:
        """Load the JSON config file if it exists."""
        if self._config_path.exists():
            try:
                raw = self._config_path.read_text(encoding="utf-8")
                data = json.loads(raw)
                if isinstance(data, dict):
                    self._config_data = data
            except (json.JSONDecodeError, OSError):
                self._config_data = {}

    def _write_config_file(self) -> None:
        """Write the current configuration to disk, creating parent dirs if needed."""
        self._config_path.parent.mkdir(parents=True, exist_ok=True)
        self._config_path.write_text(
            json.dumps(self._config_data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
