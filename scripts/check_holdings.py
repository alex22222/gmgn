#!/usr/bin/env python3
"""Show wallet holdings."""
from __future__ import annotations
import json, sys
sys.path.insert(0, "/Users/henry/projects/gmgn")

from gmgn_monitor.config_manager import ConfigManager
from gmgn_monitor.gmgn_api_client import GmgnApiClient

cfg = ConfigManager()
client = GmgnApiClient(api_key=cfg.gmgn_api_key, private_key_pem=cfg.gmgn_private_key)
wallet = "BM76JAzFzCEUbPCgBzpTTTiAXkxYFttNVLQDjH4iEqc6"
holdings = client.get_wallet_holdings("sol", wallet)
print(json.dumps(holdings, indent=2, default=str))
