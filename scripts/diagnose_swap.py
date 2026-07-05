#!/usr/bin/env python3
"""Diagnose GMGN auto-copy trading failures."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, "/Users/henry/projects/gmgn")

from gmgn_monitor.config_manager import ConfigManager
from gmgn_monitor.gmgn_api_client import GmgnSigner, GmgnApiClient, GmgnApiError

# 1. Check config
cfg = ConfigManager()
print(f"API key configured: {bool(cfg.gmgn_api_key)}")
print(f"Private key configured: {bool(cfg.gmgn_private_key)}")

# 2. Check signer
if cfg.gmgn_private_key:
    try:
        signer = GmgnSigner.from_pem_content(cfg.gmgn_private_key)
        sig = signer.sign("test message for signing")
        print(f"Signer works: signature length={len(sig)}")
    except Exception as e:
        print(f"Signer FAILED: {e}")

# 3. Check wallet holdings (signed endpoint)
wallet = "BM76JAzFzCEUbPCgBzpTTTiAXkxYFttNVLQDjH4iEqc6"
client = GmgnApiClient(api_key=cfg.gmgn_api_key, private_key_pem=cfg.gmgn_private_key)
try:
    holdings = client.get_wallet_holdings("sol", wallet)
    print(f"Holdings API OK: {len(holdings)} items")
except GmgnApiError as e:
    print(f"Holdings API FAILED: {e.message} (code={e.code}, http={e.http_status})")
except Exception as e:
    print(f"Holdings API UNEXPECTED ERROR: {e}")

# 4. Try a tiny swap to see exact error
try:
    result = client.swap({
        "chain": "sol",
        "from_address": wallet,
        "input_token": "So11111111111111111111111111111111111111112",
        "output_token": "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
        "input_amount": "1000",  # 0.000001 SOL (tiny)
        "slippage": 5.0,
        "auto_slippage": False,
    })
    print(f"Swap API returned: {result}")
except GmgnApiError as e:
    print(f"Swap API FAILED: {e.message} (code={e.code}, http={e.http_status})")
except Exception as e:
    print(f"Swap API UNEXPECTED ERROR: {type(e).__name__}: {e}")
