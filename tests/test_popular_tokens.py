from __future__ import annotations

import pytest

from gmgn_monitor.popular_tokens import (
    POPULAR_SOLANA_TOKENS,
    get_default_token_addresses,
)


class TestPopularTokens:
    def test_get_default_token_addresses_solana(self) -> None:
        result = get_default_token_addresses("sol", count=5)
        assert len(result) == 5
        assert all(isinstance(addr, str) for addr in result)

    def test_get_default_token_addresses_other_chain(self) -> None:
        result = get_default_token_addresses("eth", count=5)
        assert result == []

    def test_get_default_token_addresses_returns_correct_count(self) -> None:
        result = get_default_token_addresses("sol", count=3)
        assert len(result) == 3

    def test_get_default_token_addresses_returns_known_addresses(self) -> None:
        result = get_default_token_addresses("sol", count=5)
        assert result[0] == "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"  # USDC
        assert result[1] == "So11111111111111111111111111111111111111112"      # Wrapped SOL

    def test_get_default_token_addresses_count_greater_than_available(self) -> None:
        result = get_default_token_addresses("sol", count=100)
        assert len(result) == len(POPULAR_SOLANA_TOKENS)
        assert result == POPULAR_SOLANA_TOKENS

    def test_get_default_token_addresses_zero_count(self) -> None:
        result = get_default_token_addresses("sol", count=0)
        assert result == []

    def test_popular_solana_tokens_list_not_empty(self) -> None:
        assert len(POPULAR_SOLANA_TOKENS) > 0
        assert all(isinstance(addr, str) for addr in POPULAR_SOLANA_TOKENS)

    def test_get_default_token_addresses_case_insensitive(self) -> None:
        result = get_default_token_addresses("SOL", count=3)
        assert len(result) == 3
