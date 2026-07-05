import tempfile
import unittest
from pathlib import Path

from gmgn_monitor.wallet_config import WalletScoringConfig, load_wallet_scoring_config
from gmgn_monitor.wallet_scorer import WalletScoringWeights


class WalletConfigTest(unittest.TestCase):
    # ------------------------------------------------------------------
    # Happy-path loading
    # ------------------------------------------------------------------

    def test_unknown_chain_uses_default_weights(self):
        config = WalletScoringConfig(
            default=WalletScoringWeights(profitability=0.30, win_rate=0.15),
        )

        weights = config.for_chain('unknown')
        self.assertEqual(weights.profitability, 0.30)
        self.assertEqual(weights.win_rate, 0.15)

    def test_chain_override_inherits_default_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text(
                '{"default":{"profitability":0.25,"win_rate":0.20,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10,'
                '"copy_threshold":80.0,"watch_threshold":70.0,"observe_threshold":40.0},'
                '"chains":{"base":{"profitability":0.30,"win_rate":0.15,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10,"max_trades_7d":400}}}', encoding='utf-8',
            )
            config = load_wallet_scoring_config(path)

        base = config.for_chain('base')
        self.assertEqual(base.profitability, 0.30)
        self.assertEqual(base.win_rate, 0.15)  # overridden in chain
        self.assertEqual(base.max_trades_7d, 400)

        solana = config.for_chain('solana')
        self.assertEqual(solana.profitability, 0.25)
        self.assertEqual(solana.max_trades_7d, 500)  # default value

    # ------------------------------------------------------------------
    # Validation / failure tests
    # ------------------------------------------------------------------

    def test_unknown_field_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text(
                '{"default":{"profitability":0.25,"win_rate":0.20,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10,"not_a_field":1}}',
                encoding='utf-8',
            )
            with self.assertRaises(ValueError) as ctx:
                load_wallet_scoring_config(path)
            self.assertIn('unknown wallet scoring weight fields', str(ctx.exception))

    def test_config_must_be_object(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text('[]', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'wallet scoring config must be an object'):
                load_wallet_scoring_config(path)

    def test_invalid_json_reports_path_and_line(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text('{\nnot-json\n', encoding='utf-8')

            with self.assertRaisesRegex(
                ValueError,
                r'wallet_scoring_weights\.json:2: invalid wallet scoring config JSON:',
            ):
                load_wallet_scoring_config(path)

    def test_invalid_utf8_reports_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_bytes(b'\xff')

            with self.assertRaisesRegex(
                ValueError,
                r'wallet_scoring_weights\.json: invalid wallet scoring config UTF-8:',
            ):
                load_wallet_scoring_config(path)

    def test_read_error_reports_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.mkdir()

            with self.assertRaisesRegex(
                ValueError,
                r'wallet_scoring_weights\.json: invalid wallet scoring config read:',
            ):
                load_wallet_scoring_config(path)

    def test_chain_weights_must_be_object(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text(
                '{"default":{"profitability":0.25,"win_rate":0.20,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10},'
                '"chains":{"base":[]}}',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'base wallet scoring weights must be an object'):
                load_wallet_scoring_config(path)

    def test_weight_must_be_numeric(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text(
                '{"default":{"profitability":true,"win_rate":0.20,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10}}',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'profitability must be numeric'):
                load_wallet_scoring_config(path)

    def test_weight_must_be_finite(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text(
                '{"default":{"profitability":null,"win_rate":0.20,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10}}',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'profitability must be numeric'):
                load_wallet_scoring_config(path)

    def test_dimension_weight_must_be_between_0_and_1(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text(
                '{"default":{"profitability":1.5,"win_rate":0.20,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10}}',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'profitability weight must be between 0 and 1'):
                load_wallet_scoring_config(path)

    def test_threshold_must_be_between_0_and_100(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text(
                '{"default":{"profitability":0.25,"win_rate":0.20,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10,"copy_threshold":150}}',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'copy_threshold must be between 0 and 100'):
                load_wallet_scoring_config(path)

    def test_integer_field_must_be_integer(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text(
                '{"default":{"profitability":0.25,"win_rate":0.20,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10,"min_trades_for_scoring":10.5}}',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'min_trades_for_scoring must be an integer'):
                load_wallet_scoring_config(path)

    def test_weights_must_sum_to_1(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text(
                '{"default":{"profitability":0.50,"win_rate":0.50,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10}}',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'dimension weights must sum to 1.0'):
                load_wallet_scoring_config(path)

    def test_chain_weights_must_also_sum_to_1(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'wallet_scoring_weights.json'
            path.write_text(
                '{"default":{"profitability":0.25,"win_rate":0.20,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10},'
                '"chains":{"base":{"profitability":0.50,"win_rate":0.50,"risk_control":0.20,'
                '"consistency":0.15,"activity":0.10,"stability":0.10}}}', encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'dimension weights must sum to 1.0'):
                load_wallet_scoring_config(path)

    # ------------------------------------------------------------------
    # Default values validation
    # ------------------------------------------------------------------

    def test_default_weights_sum_to_1(self):
        weights = WalletScoringWeights()
        total = (
            weights.profitability
            + weights.win_rate
            + weights.risk_control
            + weights.consistency
            + weights.activity
            + weights.stability
        )
        self.assertAlmostEqual(total, 1.0, places=5)

    def test_load_real_config_file(self):
        """Load the committed config file and verify it parses."""
        import pathlib
        config_path = pathlib.Path(__file__).parent.parent / 'config' / 'wallet_scoring_weights.json'
        if not config_path.exists():
            self.skipTest('committed config file not found')

        config = load_wallet_scoring_config(config_path)
        self.assertEqual(config.default.profitability, 0.25)
        self.assertEqual(config.for_chain('solana').max_trades_7d, 500)
        self.assertEqual(config.for_chain('base').max_trades_7d, 400)
        self.assertEqual(config.for_chain('bsc').max_trades_7d, 600)


if __name__ == '__main__':
    unittest.main()
