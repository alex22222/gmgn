from __future__ import annotations

from gmgn_monitor.source_priority import FIELD_SOURCE_PRIORITY, merge_wallet_data


class TestFieldSourcePriority:
    """Tests for the priority mapping."""

    def test_priority_map_is_dict(self):
        assert isinstance(FIELD_SOURCE_PRIORITY, dict)
        assert "total_profit" in FIELD_SOURCE_PRIORITY
        assert "win_rate" in FIELD_SOURCE_PRIORITY
        assert "portfolio_value" in FIELD_SOURCE_PRIORITY

    def test_priority_lists_are_nonempty(self):
        for field, sources in FIELD_SOURCE_PRIORITY.items():
            assert isinstance(sources, list)
            assert len(sources) > 0


class TestMergeWalletData:
    """Tests for merge_wallet_data."""

    def test_single_source_direct_value(self):
        data = {"gmgn": {"total_profit": 5000}}
        result = merge_wallet_data(data)
        assert result["total_profit"] == 5000

    def test_multi_source_highest_priority_wins(self):
        data = {
            "birdeye": {"total_profit": 3000},
            "gmgn": {"total_profit": 5000},
        }
        result = merge_wallet_data(data)
        # gmgn has higher priority for total_profit
        assert result["total_profit"] == 5000

    def test_lower_priority_used_when_higher_missing(self):
        data = {
            "birdeye": {"total_profit": 3000},
        }
        result = merge_wallet_data(data)
        assert result["total_profit"] == 3000

    def test_none_value_skipped(self):
        data = {
            "gmgn": {"total_profit": None},
            "birdeye": {"total_profit": 3000},
        }
        result = merge_wallet_data(data)
        assert result["total_profit"] == 3000

    def test_missing_field_returns_empty_dict(self):
        data = {"unknown_source": {"some_field": 123}}
        result = merge_wallet_data(data)
        # unknown_source is not in any priority list, so result is empty
        assert result == {}

    def test_portfolio_value_extraction(self):
        data = {
            "helius": {"portfolio": {"total_value": 12000}},
        }
        result = merge_wallet_data(data)
        assert result["portfolio_value"] == 12000

    def test_portfolio_value_from_balances(self):
        data = {
            "helius": {"balances": [{"value": 5000}, {"value": 7000}]},
        }
        result = merge_wallet_data(data)
        assert result["portfolio_value"] == 12000

    def test_token_price_extraction(self):
        data = {
            "birdeye": {"price": 2.5},
        }
        result = merge_wallet_data(data)
        assert result["token_price"] == 2.5

    def test_transactions_extraction(self):
        data = {
            "solscan": {"transactions": [{"tx": "abc"}]},
        }
        result = merge_wallet_data(data)
        assert result["transactions"] == [{"tx": "abc"}]

    def test_nested_data_wrapper(self):
        data = {
            "gmgn": {"data": {"win_rate": 0.75}},
        }
        result = merge_wallet_data(data)
        assert result["win_rate"] == 0.75

    def test_empty_input(self):
        result = merge_wallet_data({})
        assert result == {}

    def test_non_dict_source_skipped(self):
        data = {
            "gmgn": "not a dict",
            "birdeye": {"total_profit": 1000},
        }
        result = merge_wallet_data(data)
        assert result["total_profit"] == 1000
