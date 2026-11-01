from __future__ import annotations

import unittest

from gmgn_monitor.paper_trade_executor import PaperBuyExecutor, PaperSellExecutor
from gmgn_monitor.portfolio_tracker import PortfolioTracker
from gmgn_monitor.sell_executor import SellSignal
from gmgn_monitor.trade_signal import TradeSignal


class PaperTradeExecutorTests(unittest.TestCase):
    def test_paper_buy_and_sell_roundtrip(self) -> None:
        portfolio = PortfolioTracker(initial_balance_sol=10.0)
        buy = PaperBuyExecutor(portfolio=portfolio)
        sell = PaperSellExecutor(portfolio=portfolio)
        signal = TradeSignal(
            signal_id="paper-1",
            wallet_address="Leader111",
            target_token="TokenPaper111",
            signal_type="NEW_POSITION",
            urgency_score=70,
            confidence_score=70,
            quality_score=70,
            recommended_amount_sol=0.01,
        )

        buy_result = buy.execute_trade(signal)
        self.assertTrue(buy_result.success)
        self.assertIsNotNone(portfolio.get_position("TokenPaper111"))

        sell_result = sell.execute_sell(
            SellSignal(
                signal_id="paper-sell-1",
                token_address="TokenPaper111",
                sell_percent=100.0,
                trigger_type="COPY_EXIT",
                reason="test",
            )
        )
        self.assertTrue(sell_result.success)
        self.assertIsNone(portfolio.get_position("TokenPaper111"))


if __name__ == "__main__":
    unittest.main()
