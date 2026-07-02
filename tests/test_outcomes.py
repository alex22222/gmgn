import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from gmgn_monitor.outcomes import apply_reviews, load_reviews


class OutcomesTest(unittest.TestCase):
    def test_applies_review_without_changing_decision_or_score(self):
        event = {
            'token_address': 'Token1',
            'decision': 'alert',
            'score': 100,
            'outcome': {'reviewed': False, 'notes': ''},
        }

        updated = apply_reviews([event], {
            'Token1': {
                'reviewed': True,
                'reviewed_at': '2026-07-01T16:30:00Z',
                'price_change_5m_percent': 12.5,
                'notes': 'reviewed',
            },
        })[0]

        self.assertEqual(updated['decision'], 'alert')
        self.assertEqual(updated['score'], 100)
        self.assertEqual(updated['outcome']['reviewed'], True)
        self.assertEqual(updated['outcome']['notes'], 'reviewed')

    def test_unmatched_review_leaves_event_unchanged(self):
        event = {
            'token_address': 'Token1',
            'decision': 'watch',
            'score': 60,
            'outcome': {'reviewed': False},
        }

        updated = apply_reviews([event], {'Other': {'reviewed': True}})[0]

        self.assertEqual(updated, event)

    def test_load_reviews_accepts_valid_review(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'reviews.jsonl'
            path.write_text(
                '{"token_address":"Token1","reviewed":true,"reviewed_at":"2026-07-01T16:30:00Z"}\n',
                encoding='utf-8',
            )

            reviews = load_reviews(path)

        self.assertEqual(reviews['Token1']['reviewed'], True)

    def test_load_reviews_rejects_blank_token_address(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'reviews.jsonl'
            path.write_text('{"token_address":"   ","reviewed":true}\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'review token_address must be non-empty'):
                load_reviews(path)

    def test_load_reviews_rejects_non_boolean_reviewed(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'reviews.jsonl'
            path.write_text('{"token_address":"Token1","reviewed":"yes"}\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'reviewed must be boolean'):
                load_reviews(path)

    def test_load_reviews_rejects_invalid_reviewed_at(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'reviews.jsonl'
            path.write_text('{"token_address":"Token1","reviewed_at":"not-a-time"}\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'reviewed_at must be ISO timestamp or null'):
                load_reviews(path)

    def test_load_reviews_rejects_non_numeric_price_change(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'reviews.jsonl'
            path.write_text('{"token_address":"Token1","price_change_5m_percent":"up"}\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'price_change_5m_percent must be finite number or null'):
                load_reviews(path)

    def test_load_reviews_rejects_non_finite_price_change(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'reviews.jsonl'
            path.write_text('{"token_address":"Token1","max_drawdown_percent":NaN}\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'max_drawdown_percent must be finite number or null'):
                load_reviews(path)

    def test_load_reviews_rejects_non_string_notes(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'reviews.jsonl'
            path.write_text('{"token_address":"Token1","notes":123}\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'notes must be string'):
                load_reviews(path)

    def test_load_reviews_rejects_duplicate_token_address(self):
        with TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'reviews.jsonl'
            path.write_text(
                '{"token_address":"Token1","reviewed":true}\n'
                '{"token_address":"Token1","reviewed":false}\n',
                encoding='utf-8',
            )

            with self.assertRaisesRegex(ValueError, 'duplicate review token_address: Token1'):
                load_reviews(path)


if __name__ == '__main__':
    unittest.main()
