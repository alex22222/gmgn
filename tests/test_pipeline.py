import tempfile
import unittest
from pathlib import Path

from gmgn_monitor.pipeline import run_pipeline


class PipelineTest(unittest.TestCase):
    def test_runs_local_dry_run_pipeline(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_dir = Path(tmp_dir) / 'pipeline'
            outputs = run_pipeline(
                input_path=Path('fixtures/candidates.jsonl'),
                output_dir=output_dir,
                threshold_config_path=Path('config/thresholds.json'),
                risk_config_path=Path('config/risk_limits.json'),
                automation_config_path=Path('config/automation_gate.json'),
                reviews_path=Path('fixtures/outcome_reviews.jsonl'),
                daily_loss_percent=0.0,
            )

            for path in outputs.values():
                self.assertTrue(path.exists())

            self.assertIn('Total candidates: 4', outputs['summary'].read_text(encoding='utf-8'))
            self.assertIn('| reviewed | 2 |', outputs['summary'].read_text(encoding='utf-8'))
            self.assertIn('[ALERT] GOOD', outputs['telegram'].read_text(encoding='utf-8'))
            self.assertIn('Status: auto_trading_enabled', outputs['automation_gate'].read_text(encoding='utf-8'))
            self.assertEqual(list(output_dir.glob('.*.tmp')), [])


if __name__ == '__main__':
    unittest.main()
