from __future__ import annotations

__all__ = [
    "POPULAR_SOLANA_TOKENS",
    "get_default_token_addresses",
]

POPULAR_SOLANA_TOKENS = [
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
    "So11111111111111111111111111111111111111112",      # Wrapped SOL
    "DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263",  # BONK
    "7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZRuJosgAsU",  # SAMO
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
    "J1toso1uCk3RLmjorhTtrVwY9WRJXTkB5QnJYXyD5pn",  # JitoSOL
    "bSo13r4TkiE4KumL71LsHTPpL2euBYLFx6h9HP3piy1",  # BlazeStake SOL
    "7dHbWXmci3dT8UFYWYZweBLXgycu7Y3iL6trKn1Y7ARj",  # stSOL
    "mSoLzYCxHdYgdzU16g5QSh3i5K3z3KZK7ytfqcJm7So",  # mSOL
    "HZ1J1niP1JP4JkH5z9wDkMp8DQ6Zc3J3v3w5v1w5v1w",  # PYTH
]


def get_default_token_addresses(chain: str = "sol", count: int = 5) -> list[str]:
    """Get a list of default token addresses for a chain.

    Args:
        chain: Blockchain identifier (``"sol"`` or ``"solana"`` for Solana).
        count: Maximum number of addresses to return.

    Returns:
        A list of token contract addresses. Returns an empty list for
        unsupported chains.
    """
    chain_lower = chain.lower()
    if chain_lower in ("sol", "solana"):
        return POPULAR_SOLANA_TOKENS[:count]
    return []
