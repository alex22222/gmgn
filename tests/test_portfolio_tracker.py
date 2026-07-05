import pytest
from datetime import datetime, timezone
from gmgn_monitor.portfolio_tracker import (
    PortfolioTracker,
    Position,
    PortfolioSnapshot,
    PnLStats,
)


class TestPortfolioTracker:
    def test_open_position_deducts_balance(self):
        pt = PortfolioTracker(initial_balance_sol=10.0)
        pos = pt.open_position("token1", entry_price_sol=2.0, quantity=1.0)
        assert pos.token_address == "token1"
        assert pt._available_sol == 8.0

    def test_open_position_insufficient_balance_raises(self):
        pt = PortfolioTracker(initial_balance_sol=1.0)
        with pytest.raises(ValueError):
            pt.open_position("token1", entry_price_sol=2.0, quantity=1.0)

    def test_close_position_returns_realized_pnl(self):
        pt = PortfolioTracker(initial_balance_sol=10.0)
        pt.open_position("token1", entry_price_sol=2.0, quantity=1.0)
        pos, pnl = pt.close_position("token1", exit_price_sol=3.0)
        assert pnl == 1.0
        assert pos.realized_pnl_sol == 1.0
        assert pt._available_sol == 11.0

    def test_update_price_updates_unrealized_pnl(self):
        pt = PortfolioTracker(initial_balance_sol=10.0)
        pt.open_position("token1", entry_price_sol=2.0, quantity=1.0)
        pt.update_price("token1", current_price_sol=3.0)
        pos = pt.get_position("token1")
        assert pos.unrealized_pnl_sol == 1.0

    def test_get_snapshot_total_value(self):
        pt = PortfolioTracker(initial_balance_sol=10.0)
        pt.open_position("token1", entry_price_sol=2.0, quantity=1.0)
        pt.update_price("token1", 3.0)
        snap = pt.get_snapshot()
        # available = 10 - 2 = 8; position value = 3 * 1 = 3; total = 11
        assert snap.total_value_sol == 11.0

    def test_max_drawdown(self):
        pt = PortfolioTracker(initial_balance_sol=10.0)
        pt.open_position("token1", entry_price_sol=2.0, quantity=1.0)
        # value goes up to 12, then down to 9
        pt.update_price("token1", 4.0)
        pt.get_snapshot()
        pt.update_price("token1", 1.0)
        snap = pt.get_snapshot()
        assert snap.max_drawdown_percent > 0

    def test_sharpe_ratio_zero_with_no_returns(self):
        pt = PortfolioTracker(initial_balance_sol=10.0)
        snap = pt.get_snapshot()
        assert snap.sharpe_ratio == 0.0

    def test_sharpe_ratio_zero_with_zero_std(self):
        pt = PortfolioTracker(initial_balance_sol=10.0)
        pt.daily_reset()
        pt.daily_reset()
        snap = pt.get_snapshot()
        assert snap.sharpe_ratio == 0.0

    def test_daily_reset(self):
        pt = PortfolioTracker(initial_balance_sol=10.0)
        pt.open_position("token1", entry_price_sol=2.0, quantity=1.0)
        pt.close_position("token1", exit_price_sol=3.0)
        pt.daily_reset()
        assert pt._daily_pnl_sol == 0.0
        assert len(pt._daily_returns) == 1

    def test_to_dict_serialization(self):
        pt = PortfolioTracker(initial_balance_sol=10.0)
        pos = pt.open_position("token1", entry_price_sol=2.0, quantity=1.0)
        snap = pt.get_snapshot()
        pos_dict = pos.to_dict()
        snap_dict = snap.to_dict()
        assert "token_address" in pos_dict
        assert "total_value_sol" in snap_dict
        pnl_stats = snap.to_pnl_stats()
        pnl_dict = pnl_stats.to_dict()
        assert "daily_pnl_sol" in pnl_dict
