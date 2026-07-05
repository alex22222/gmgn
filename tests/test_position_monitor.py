from __future__ import annotations

from unittest.mock import patch

from gmgn_monitor.position_monitor import PositionMonitor


class _FakeBirdeye:
    def __init__(self, result=None, error: Exception | None = None):
        self._result = result
        self._error = error

    def get_token_price(self, token_address: str, chain: str = "sol"):
        if self._error:
            raise self._error
        return self._result


def test_fetch_token_price_uses_birdeye_when_available():
    monitor = PositionMonitor(birdeye_client=_FakeBirdeye({"price": "0.0123"}))

    with patch("gmgn_monitor.position_monitor.fetch_tokens_payload") as fetch_tokens:
        assert monitor.fetch_token_price("Token111") == 0.0123

    fetch_tokens.assert_not_called()


def test_fetch_token_price_falls_back_to_dexscreener_when_birdeye_fails():
    monitor = PositionMonitor(birdeye_client=_FakeBirdeye(error=RuntimeError("boom")))

    with patch("gmgn_monitor.position_monitor.fetch_tokens_payload") as fetch_tokens:
        fetch_tokens.return_value = [{
            "baseToken": {"address": "Token111"},
            "priceUsd": "0.0456",
        }]

        assert monitor.fetch_token_price("Token111", chain="sol") == 0.0456

    fetch_tokens.assert_called_once_with("solana", ["Token111"])


def test_fetch_token_price_falls_back_to_dexscreener_when_birdeye_price_zero():
    monitor = PositionMonitor(birdeye_client=_FakeBirdeye({"price": 0}))

    with patch("gmgn_monitor.position_monitor.fetch_tokens_payload") as fetch_tokens:
        fetch_tokens.return_value = [{
            "baseToken": {"address": "Token111"},
            "priceUsd": "0.0789",
        }]

        assert monitor.fetch_token_price("Token111") == 0.0789
