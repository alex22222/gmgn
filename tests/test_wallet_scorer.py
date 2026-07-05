import unittest
from datetime import datetime, timezone

from gmgn_monitor.wallet_scorer import (
    WalletScoringWeights,
    _add_score,
    _collect_risk_flags,
    _compute_decision,
    _compute_grade,
    _compute_quality_multiplier,
    _get_nested,
    _hard_reject_reasons,
    _parse_days_alive,
    _score_activity,
    _score_consistency,
    _score_profitability,
    _score_risk_control,
    _score_stability,
    _score_win_rate,
    score_wallet,
)


def wallet_features(**overrides):
    """Build a realistic wallet feature dict with sensible defaults."""
    now = datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')
    data = {
        'wallet_address': '7xKXtg2CW87d97TXJSDpbD5jBkheTqA83TZR6Y7Q5XqK',
        'chain': 'solana',
        'first_seen_at': '2025-01-15T08:30:00Z',
        'last_active_at': now,
        'total_transactions': 342,
        'profit_metrics': {
            'total_pnl_sol': 125.5,
            'total_pnl_usd': 6850.0,
            'avg_profit_per_trade_sol': 0.85,
            'win_rate_percent': 68.5,
            'profit_loss_ratio': 2.8,
            'max_consecutive_wins': 12,
            'max_consecutive_losses': 4,
            'profit_sol_30d': 95.0,
            'profit_usd_30d': 5200.0,
        },
        'risk_metrics': {
            'max_drawdown_percent': 42.0,
            'avg_drawdown_percent': 18.5,
            'volatility_7d': 0.35,
            'sharpe_ratio': 1.85,
            'sortino_ratio': 2.45,
            'var_95': -15.2,
        },
        'frequency_metrics': {
            'trades_7d': 72,
            'trades_30d': 280,
            'avg_daily_trades': 9.3,
            'avg_holding_hours': 36.5,
            'median_holding_hours': 28.0,
            'max_holding_hours': 168.0,
            'min_holding_hours': 0.5,
        },
        'behavioral_metrics': {
            'sniper_detected': False,
            'bot_pattern_score': 12.0,
            'mev_usage_percent': 15.0,
            'turboslippage_usage_percent': 45.0,
            'new_token_buy_percent': 35.0,
            'stablecoin_holding_percent': 22.0,
            'diversification_index': 0.68,
        },
        'capital_metrics': {
            'avg_position_sol': 2.5,
            'max_position_sol': 15.0,
            'median_position_sol': 1.8,
            'total_volume_sol': 850.0,
            'profit_sol_30d': 95.0,
            'profit_usd_30d': 5200.0,
        },
        'token_preference': {
            'favorite_token_categories': ['meme', 'ai', 'defi'],
            'pump_fun_interaction_percent': 65.0,
            'graduated_token_rate': 12.0,
            'early_entry_rate': 28.0,
        },
    }
    data.update(overrides)
    return data


class WalletScorerTest(unittest.TestCase):
    # ------------------------------------------------------------------
    # End-to-end decision tests
    # ------------------------------------------------------------------

    def test_copy_for_strong_wallet(self):
        result = score_wallet(wallet_features())

        self.assertEqual(result['decision'], 'copy')
        self.assertEqual(result['grade'], 'A')
        self.assertGreaterEqual(result['total_score'], 80.0)
        self.assertIn('profitability score', ' '.join(result['reasons']))

    def test_watch_for_moderate_wallet(self):
        features = wallet_features(
            profit_metrics={
                'win_rate_percent': 58.0,
                'profit_loss_ratio': 2.0,
                'max_consecutive_losses': 4,
                'profit_sol_30d': 50.0,
                'profit_usd_30d': 2500.0,
                'total_pnl_sol': 80.0,
                'total_pnl_usd': 4000.0,
                'avg_profit_per_trade_sol': 0.5,
                'max_consecutive_wins': 7,
            },
            risk_metrics={
                'max_drawdown_percent': 40.0,
                'sharpe_ratio': 1.5,
                'sortino_ratio': 2.0,
                'avg_drawdown_percent': 20.0,
                'volatility_7d': 0.4,
                'var_95': -20.0,
            },
            frequency_metrics={
                'trades_7d': 45,
                'trades_30d': 200,
                'avg_daily_trades': 6.0,
                'avg_holding_hours': 36.5,
                'median_holding_hours': 28.0,
                'max_holding_hours': 168.0,
                'min_holding_hours': 0.5,
            },
        )
        result = score_wallet(features)

        self.assertEqual(result['decision'], 'watch')
        self.assertEqual(result['grade'], 'B')
        self.assertGreaterEqual(result['total_score'], 70.0)
        self.assertLess(result['total_score'], 80.0)

    def test_observe_for_weak_wallet(self):
        features = wallet_features(
            profit_metrics={
                'win_rate_percent': 50.0,
                'profit_loss_ratio': 1.2,
                'max_consecutive_losses': 8,
                'profit_sol_30d': 10.0,
                'profit_usd_30d': 500.0,
                'total_pnl_sol': 20.0,
                'total_pnl_usd': 1000.0,
                'avg_profit_per_trade_sol': 0.1,
                'max_consecutive_wins': 3,
            },
            risk_metrics={
                'max_drawdown_percent': 60.0,
                'sharpe_ratio': 0.6,
                'sortino_ratio': 0.9,
                'avg_drawdown_percent': 35.0,
                'volatility_7d': 0.6,
                'var_95': -35.0,
            },
            frequency_metrics={
                'trades_7d': 12,
                'trades_30d': 50,
                'avg_daily_trades': 2.0,
                'avg_holding_hours': 8.0,
                'median_holding_hours': 6.0,
                'max_holding_hours': 24.0,
                'min_holding_hours': 0.5,
            },
            behavioral_metrics={
                'sniper_detected': False,
                'bot_pattern_score': 15.0,
                'mev_usage_percent': 10.0,
                'turboslippage_usage_percent': 30.0,
                'new_token_buy_percent': 30.0,
                'stablecoin_holding_percent': 10.0,
                'diversification_index': 0.40,
            },
        )
        result = score_wallet(features)

        self.assertEqual(result['decision'], 'observe')
        self.assertEqual(result['grade'], 'D')
        self.assertGreaterEqual(result['total_score'], 40.0)
        self.assertLess(result['total_score'], 70.0)

    def test_reject_for_low_score(self):
        features = wallet_features(
            profit_metrics={
                'win_rate_percent': 32.0,
                'profit_loss_ratio': 0.8,
                'max_consecutive_losses': 12,
                'profit_sol_30d': -5.0,
                'profit_usd_30d': -250.0,
                'total_pnl_sol': -10.0,
                'total_pnl_usd': -500.0,
                'avg_profit_per_trade_sol': -0.2,
                'max_consecutive_wins': 2,
            },
            risk_metrics={
                'max_drawdown_percent': 80.0,
                'sharpe_ratio': -0.5,
                'sortino_ratio': -0.3,
                'avg_drawdown_percent': 50.0,
                'volatility_7d': 0.8,
                'var_95': -50.0,
            },
            frequency_metrics={
                'trades_7d': 12,
                'trades_30d': 50,
                'avg_daily_trades': 2.0,
                'avg_holding_hours': 2.0,
                'median_holding_hours': 1.0,
                'max_holding_hours': 8.0,
                'min_holding_hours': 0.2,
            },
            behavioral_metrics={
                'sniper_detected': False,
                'bot_pattern_score': 45.0,
                'mev_usage_percent': 60.0,
                'turboslippage_usage_percent': 80.0,
                'new_token_buy_percent': 80.0,
                'stablecoin_holding_percent': 0.0,
                'diversification_index': 0.15,
            },
        )
        # High observe threshold forces rejection for this weak wallet
        weights = WalletScoringWeights(observe_threshold=55.0)
        result = score_wallet(features, weights)

        self.assertEqual(result['decision'], 'reject')
        self.assertIn('score below observe threshold', result['reasons'])

    # ------------------------------------------------------------------
    # Hard-reject tests
    # ------------------------------------------------------------------

    def test_hard_reject_robot(self):
        features = wallet_features(
            behavioral_metrics={'bot_pattern_score': 75.0},
        )
        result = score_wallet(features)

        self.assertEqual(result['decision'], 'reject')
        self.assertEqual(result['total_score'], 0.0)
        self.assertIn('robot detected', ' '.join(result['reasons']))

    def test_hard_reject_insufficient_trades(self):
        features = wallet_features(
            frequency_metrics={'trades_7d': 5},
        )
        result = score_wallet(features)

        self.assertEqual(result['decision'], 'reject')
        self.assertEqual(result['total_score'], 0.0)
        self.assertIn('insufficient trades', ' '.join(result['reasons']))

    def test_hard_reject_ultra_high_frequency(self):
        features = wallet_features(
            frequency_metrics={'trades_7d': 550},
        )
        result = score_wallet(features)

        self.assertEqual(result['decision'], 'reject')
        self.assertIn('ultra-high frequency bot', ' '.join(result['reasons']))

    def test_hard_reject_low_win_rate(self):
        features = wallet_features(
            profit_metrics={
                'win_rate_percent': 25.0,
                'profit_loss_ratio': 1.2,
                'max_consecutive_losses': 3,
                'profit_sol_30d': 10.0,
                'profit_usd_30d': 500.0,
                'total_pnl_sol': 20.0,
                'total_pnl_usd': 1000.0,
                'avg_profit_per_trade_sol': 0.1,
                'max_consecutive_wins': 3,
            },
            frequency_metrics={'trades_30d': 60},
        )
        result = score_wallet(features)

        self.assertEqual(result['decision'], 'reject')
        self.assertIn('win rate too low', ' '.join(result['reasons']))

    def test_hard_reject_sniper(self):
        features = wallet_features(
            frequency_metrics={'avg_holding_hours': 0.5},
            total_transactions=150,
        )
        result = score_wallet(features)

        self.assertEqual(result['decision'], 'reject')
        self.assertIn('sniper detected', ' '.join(result['reasons']))

    def test_hard_reject_consistent_losses(self):
        features = wallet_features(
            profit_metrics={
                'win_rate_percent': 35.0,
                'profit_loss_ratio': 0.8,
                'max_consecutive_losses': 8,
                'profit_sol_30d': -10.0,
                'profit_usd_30d': -500.0,
                'total_pnl_sol': -20.0,
                'total_pnl_usd': -1000.0,
                'avg_profit_per_trade_sol': -0.3,
                'max_consecutive_wins': 2,
            },
            frequency_metrics={'trades_30d': 60},
        )
        result = score_wallet(features)

        self.assertEqual(result['decision'], 'reject')
        self.assertIn('consistent losses', ' '.join(result['reasons']))

    # ------------------------------------------------------------------
    # Quality multiplier tests
    # ------------------------------------------------------------------

    def test_quality_multiplier_with_risk_flags(self):
        features = wallet_features(
            behavioral_metrics={'sniper_detected': True},
        )
        result = score_wallet(features)

        self.assertLess(result['quality_multiplier'], 1.0)
        self.assertTrue(result['risk_flags']['high_frequency_bot'])

    def test_quality_multiplier_with_bot_score(self):
        features = wallet_features(
            behavioral_metrics={'bot_pattern_score': 25.0},
        )
        result = score_wallet(features)

        self.assertLess(result['quality_multiplier'], 1.0)

    def test_quality_multiplier_with_low_win_rate(self):
        features = wallet_features(
            profit_metrics={'win_rate_percent': 45.0},
        )
        result = score_wallet(features)

        self.assertLess(result['quality_multiplier'], 1.0)

    # ------------------------------------------------------------------
    # Dimension edge-case tests
    # ------------------------------------------------------------------

    def test_perfect_profitability_score(self):
        features = wallet_features(
            profit_metrics={
                'win_rate_percent': 80.0,
                'profit_loss_ratio': 4.0,
                'profit_sol_30d': 200.0,
            },
            capital_metrics={'avg_position_sol': 2.0},
            frequency_metrics={'trades_30d': 100},
        )
        score = _score_profitability(features)
        self.assertEqual(score, 100.0)

    def test_zero_profitability_score(self):
        features = wallet_features(
            profit_metrics={
                'win_rate_percent': 0.0,
                'profit_loss_ratio': 0.0,
                'profit_sol_30d': 0.0,
            },
            capital_metrics={'avg_position_sol': 1.0},
            frequency_metrics={'trades_30d': 10},
        )
        score = _score_profitability(features)
        self.assertEqual(score, 0.0)

    def test_perfect_risk_control_score(self):
        features = wallet_features(
            risk_metrics={
                'max_drawdown_percent': 10.0,
                'sharpe_ratio': 3.0,
                'sortino_ratio': 3.0,
            },
        )
        score = _score_risk_control(features)
        self.assertEqual(score, 100.0)

    def test_high_drawdown_risk_control(self):
        features = wallet_features(
            risk_metrics={
                'max_drawdown_percent': 90.0,
                'sharpe_ratio': 0.0,
                'sortino_ratio': 0.0,
            },
        )
        score = _score_risk_control(features)
        self.assertEqual(score, 0.0)

    def test_win_rate_dimension_tiers(self):
        self.assertEqual(_score_win_rate({'profit_metrics': {'win_rate_percent': 75.0}}), 100.0)
        self.assertEqual(_score_win_rate({'profit_metrics': {'win_rate_percent': 65.0}}), 85.0)
        self.assertEqual(_score_win_rate({'profit_metrics': {'win_rate_percent': 55.0}}), 65.0)
        self.assertEqual(_score_win_rate({'profit_metrics': {'win_rate_percent': 45.0}}), 45.0)
        self.assertEqual(_score_win_rate({'profit_metrics': {'win_rate_percent': 35.0}}), 25.0)
        self.assertEqual(_score_win_rate({'profit_metrics': {'win_rate_percent': 20.0}}), 16.0)

    def test_activity_optimal_range(self):
        features = {
            'frequency_metrics': {
                'trades_7d': 75,
                'avg_daily_trades': 10,
                'trades_30d': 300,
            },
        }
        score = _score_activity(features)
        self.assertGreaterEqual(score, 80.0)

    def test_stability_with_very_new_wallet(self):
        features = {
            'first_seen_at': '2099-01-01T00:00:00Z',
            'profit_metrics': {'total_pnl_sol': 0.0, 'profit_sol_30d': 0.0},
            'behavioral_metrics': {'bot_pattern_score': 50.0},
        }
        score = _score_stability(features)
        # 0 (age) + 10 (default profit consistency) + 20 (bot score penalty) = 30
        self.assertEqual(score, 30.0)

    # ------------------------------------------------------------------
    # Missing / malformed data tests
    # ------------------------------------------------------------------

    def test_missing_nested_data_defaults_to_zero(self):
        features = {'wallet_address': 'test123'}
        result = score_wallet(features)

        self.assertEqual(result['decision'], 'reject')
        self.assertEqual(result['total_score'], 0.0)

    def test_empty_feature_dict_hard_reject(self):
        result = score_wallet({})

        self.assertEqual(result['decision'], 'reject')
        self.assertIn('insufficient trades', ' '.join(result['reasons']))

    def test_partial_missing_nested_keys(self):
        features = wallet_features()
        del features['profit_metrics']['win_rate_percent']
        result = score_wallet(features)

        # Should still compute without crashing, just with lower profitability
        self.assertIsInstance(result['total_score'], float)

    # ------------------------------------------------------------------
    # Config / weights tests
    # ------------------------------------------------------------------

    def test_custom_weights_change_score(self):
        default_weights = WalletScoringWeights()
        high_profit_weights = WalletScoringWeights(
            profitability=0.50,
            win_rate=0.10,
            risk_control=0.10,
            consistency=0.10,
            activity=0.10,
            stability=0.10,
        )

        features = wallet_features()
        result_default = score_wallet(features, default_weights)
        result_high = score_wallet(features, high_profit_weights)

        # With higher profitability weight, the total should be different
        self.assertNotEqual(result_default['total_score'], result_high['total_score'])

    def test_invalid_weights_sum_raises(self):
        bad_weights = WalletScoringWeights(
            profitability=0.50,
            win_rate=0.50,
            risk_control=0.50,
            consistency=0.50,
            activity=0.50,
            stability=0.50,
        )
        features = wallet_features()

        with self.assertRaises(ValueError) as ctx:
            score_wallet(features, bad_weights)
        self.assertIn('dimension weights must sum', str(ctx.exception).lower())

    def test_negative_weights_sum_raises(self):
        bad_weights = WalletScoringWeights(
            profitability=-1.0,
            win_rate=1.0,
            risk_control=1.0,
            consistency=1.0,
            activity=1.0,
            stability=1.0,
        )
        features = wallet_features()

        with self.assertRaises(ValueError) as ctx:
            score_wallet(features, bad_weights)
        self.assertIn('dimension weights must sum', str(ctx.exception).lower())

    # ------------------------------------------------------------------
    # Helper function tests
    # ------------------------------------------------------------------

    def test_add_score_returns_points_on_true(self):
        reasons = []
        points = _add_score(True, 25, reasons, 'test reason')
        self.assertEqual(points, 25)
        self.assertIn('test reason', reasons)

    def test_add_score_returns_zero_on_false(self):
        reasons = []
        points = _add_score(False, 25, reasons, 'test reason')
        self.assertEqual(points, 0)
        self.assertNotIn('test reason', reasons)

    def test_get_nested_existing_path(self):
        data = {'a': {'b': {'c': 42}}}
        self.assertEqual(_get_nested(data, 'a', 'b', 'c'), 42)

    def test_get_nested_missing_key(self):
        data = {'a': {'b': {}}}
        self.assertIsNone(_get_nested(data, 'a', 'b', 'c'))

    def test_get_nested_non_dict_intermediate(self):
        data = {'a': {'b': 42}}
        self.assertIsNone(_get_nested(data, 'a', 'b', 'c'))

    def test_parse_days_alive_valid(self):
        days = _parse_days_alive('2020-01-01T00:00:00Z')
        self.assertGreater(days, 0)

    def test_parse_days_alive_empty(self):
        self.assertEqual(_parse_days_alive(''), 0)

    def test_parse_days_alive_invalid(self):
        self.assertEqual(_parse_days_alive('not-a-date'), 0)

    def test_compute_grade(self):
        self.assertEqual(_compute_grade(85.0), 'A')
        self.assertEqual(_compute_grade(75.0), 'B')
        self.assertEqual(_compute_grade(65.0), 'C')
        self.assertEqual(_compute_grade(45.0), 'D')
        self.assertEqual(_compute_grade(35.0), 'E')

    def test_compute_decision(self):
        weights = WalletScoringWeights()
        self.assertEqual(_compute_decision(85.0, weights), 'copy')
        self.assertEqual(_compute_decision(75.0, weights), 'watch')
        self.assertEqual(_compute_decision(50.0, weights), 'observe')
        self.assertEqual(_compute_decision(35.0, weights), 'reject')

    def test_collect_risk_flags(self):
        features = wallet_features(
            behavioral_metrics={'sniper_detected': True, 'mev_usage_percent': 60.0},
            token_preference={'pump_fun_interaction_percent': 85.0},
        )
        flags = _collect_risk_flags(features)
        self.assertTrue(flags['high_frequency_bot'])
        self.assertTrue(flags['pump_fun_gambler'])
        self.assertTrue(flags['mev_attacker'])
        self.assertFalse(flags['insider_related'])

    def test_hard_reject_reasons_empty_for_good_wallet(self):
        features = wallet_features()
        weights = WalletScoringWeights()
        reasons = _hard_reject_reasons(features, weights)
        self.assertEqual(reasons, [])

    def test_consistency_holding_cv(self):
        features = {
            'frequency_metrics': {
                'avg_holding_hours': 30.0,
                'median_holding_hours': 15.0,
                'trades_7d': 60,
            },
            'profit_metrics': {'max_consecutive_losses': 3},
        }
        score = _score_consistency(features)
        self.assertGreater(score, 0.0)

    def test_quality_multiplier_combined_penalties(self):
        features = wallet_features(
            behavioral_metrics={'sniper_detected': True, 'bot_pattern_score': 25.0},
            profit_metrics={'win_rate_percent': 45.0},
        )
        weights = WalletScoringWeights()
        multiplier = _compute_quality_multiplier(features, weights)
        # 0.5 * 0.7 * 0.8 = 0.28
        self.assertAlmostEqual(multiplier, 0.28, places=5)


if __name__ == '__main__':
    unittest.main()
