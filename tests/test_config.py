import tempfile
import unittest
from pathlib import Path

from gmgn_monitor.config import ThresholdConfig, load_threshold_config
from gmgn_monitor.scoring import Thresholds


class ThresholdConfigTest(unittest.TestCase):
    def test_unknown_chain_uses_default_thresholds(self):
        config = ThresholdConfig(default=Thresholds(min_liquidity=123.0))

        self.assertEqual(config.for_chain('unknown').min_liquidity, 123.0)

    def test_chain_override_inherits_default_values(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'thresholds.json'
            path.write_text(
                '{"default":{"min_liquidity":100,"watch_score":55},"chains":{"base":{"min_liquidity":50}}}',
                encoding='utf-8',
            )

            config = load_threshold_config(path)

        self.assertEqual(config.for_chain('base').min_liquidity, 50)
        self.assertEqual(config.for_chain('base').watch_score, 55)
        self.assertEqual(config.for_chain('solana').min_liquidity, 100)

    def test_unknown_threshold_field_fails_fast(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'thresholds.json'
            path.write_text('{"default":{"not_a_threshold":1}}', encoding='utf-8')

            with self.assertRaises(ValueError):
                load_threshold_config(path)

    def test_threshold_config_must_be_object(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'thresholds.json'
            path.write_text('[]', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'threshold config must be an object'):
                load_threshold_config(path)

    def test_invalid_threshold_json_reports_path_and_line(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'thresholds.json'
            path.write_text('{\nnot-json\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, r'thresholds\.json:2: invalid threshold config JSON:'):
                load_threshold_config(path)

    def test_invalid_threshold_utf8_reports_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'thresholds.json'
            path.write_bytes(b'\xff')

            with self.assertRaisesRegex(ValueError, r'thresholds\.json: invalid threshold config UTF-8:'):
                load_threshold_config(path)

    def test_threshold_read_error_reports_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'thresholds.json'
            path.mkdir()

            with self.assertRaisesRegex(ValueError, r'thresholds\.json: invalid threshold config read:'):
                load_threshold_config(path)

    def test_chain_threshold_override_must_be_object(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'thresholds.json'
            path.write_text('{"chains":{"base":[]}}', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'base thresholds must be an object'):
                load_threshold_config(path)

    def test_threshold_values_must_be_valid_numbers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'thresholds.json'
            path.write_text('{"default":{"min_liquidity":true}}', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'min_liquidity must be numeric'):
                load_threshold_config(path)

    def test_threshold_values_must_be_non_negative(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'thresholds.json'
            path.write_text('{"default":{"min_tx_count_1m":-1}}', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'min_tx_count_1m must be non-negative'):
                load_threshold_config(path)

    def test_percentage_thresholds_cannot_exceed_100(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'thresholds.json'
            path.write_text('{"default":{"max_top10_holder_percent":101}}', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'max_top10_holder_percent must be at most 100'):
                load_threshold_config(path)

    def test_alert_score_must_not_be_below_watch_score(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'thresholds.json'
            path.write_text('{"default":{"alert_score":50,"watch_score":60}}', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'alert_score must be greater than or equal to watch_score'):
                load_threshold_config(path)


if __name__ == '__main__':
    unittest.main()
