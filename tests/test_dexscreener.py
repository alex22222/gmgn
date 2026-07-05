import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

from gmgn_monitor.dexscreener import (
    DexScreenerLatestProfilesSource,
    DexScreenerPayloadSource,
    DexScreenerSearchSource,
    main,
    map_pair_to_candidate,
    map_profile_to_candidate,
    write_jsonl,
)
from gmgn_monitor.schema import Candidate
from gmgn_monitor.scoring import score_candidate


class DexScreenerTest(unittest.TestCase):
    class Response:
        def __init__(self, body: bytes):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, traceback):
            return False

        def read(self):
            return self.body

    def test_maps_pair_to_schema_valid_candidate(self):
        payload = json.loads(Path('fixtures/dexscreener_search_sample.json').read_text(encoding='utf-8'))
        candidate = map_pair_to_candidate(payload['pairs'][0])

        Candidate.from_dict(candidate)
        self.assertEqual(candidate['chain'], 'solana')
        self.assertEqual(candidate['symbol'], 'DEX')
        self.assertEqual(candidate['liquidity'], 12000.0)
        self.assertEqual(candidate['volume_5m'], 2500.0)
        self.assertEqual(candidate['tx_count_1m'], 60.0)

    def test_mapped_candidate_is_rejected_until_safety_is_enriched(self):
        payload = json.loads(Path('fixtures/dexscreener_search_sample.json').read_text(encoding='utf-8'))
        candidate = Candidate.from_dict(map_pair_to_candidate(payload['pairs'][0]))

        result = score_candidate(candidate)

        self.assertEqual(result['decision'], 'reject')
        self.assertIn('honeypot risk present', result['reasons'])

    def test_maps_latest_profile_fallback_to_schema_valid_rejected_candidate(self):
        candidate_data = map_profile_to_candidate({
            'chainId': 'solana',
            'tokenAddress': 'Profile111111111111111111111111111111111111',
        })
        candidate = Candidate.from_dict(candidate_data)

        result = score_candidate(candidate)

        self.assertEqual(candidate_data['source'], 'dexscreener:token-profiles')
        self.assertEqual(candidate_data['symbol'], 'UNKNOWN')
        self.assertEqual(result['decision'], 'reject')
        self.assertIn('honeypot risk present', result['reasons'])

    def test_latest_profiles_source_enriches_pairs_from_token_endpoint(self):
        profile_payload = json.dumps([
            {'chainId': 'solana', 'tokenAddress': 'Token1111111111111111111111111111111111111'},
        ]).encode('utf-8')
        token_payload = json.dumps([
            {
                'chainId': 'solana',
                'baseToken': {'address': 'Token1111111111111111111111111111111111111', 'symbol': 'LIVE'},
                'fdv': 42000,
                'liquidity': {'usd': 9000},
                'volume': {'m5': 1800},
                'txns': {'m5': {'buys': 8, 'sells': 7}},
            },
        ]).encode('utf-8')

        with patch('gmgn_monitor.dexscreener.urlopen') as urlopen:
            urlopen.side_effect = [self.Response(profile_payload), self.Response(token_payload)]
            records = list(DexScreenerLatestProfilesSource(limit=1).load())

        Candidate.from_dict(records[0])
        self.assertEqual(records[0]['source'], 'dexscreener:token-profiles')
        self.assertEqual(records[0]['symbol'], 'LIVE')
        self.assertEqual(records[0]['liquidity'], 9000.0)
        self.assertEqual(records[0]['tx_count_1m'], 15.0)
        self.assertIn('/token-profiles/latest/v1', urlopen.call_args_list[0].args[0].full_url)
        self.assertIn('/tokens/v1/solana/Token1111111111111111111111111111111111111', urlopen.call_args_list[1].args[0].full_url)

    def test_latest_profiles_source_falls_back_when_pair_is_missing(self):
        profile_payload = json.dumps([
            {'chainId': 'solana', 'tokenAddress': 'Token1111111111111111111111111111111111111'},
        ]).encode('utf-8')

        with patch('gmgn_monitor.dexscreener.urlopen') as urlopen:
            urlopen.side_effect = [self.Response(profile_payload), self.Response(b'[]')]
            records = list(DexScreenerLatestProfilesSource(limit=1).load())

        Candidate.from_dict(records[0])
        self.assertEqual(records[0]['source'], 'dexscreener:token-profiles')
        self.assertEqual(records[0]['symbol'], 'UNKNOWN')
        self.assertEqual(records[0]['liquidity'], 0.0)

    def test_latest_profiles_source_rejects_malformed_profile_payload(self):
        with patch('gmgn_monitor.dexscreener.urlopen') as urlopen:
            urlopen.return_value = self.Response(b'{}')

            with self.assertRaisesRegex(ValueError, 'DEX Screener token profiles payload must be a list'):
                list(DexScreenerLatestProfilesSource(limit=1).load())

    def test_latest_profiles_source_rejects_malformed_tokens_payload(self):
        profile_payload = json.dumps([
            {'chainId': 'solana', 'tokenAddress': 'Token1111111111111111111111111111111111111'},
        ]).encode('utf-8')

        with patch('gmgn_monitor.dexscreener.urlopen') as urlopen:
            urlopen.side_effect = [self.Response(profile_payload), self.Response(b'{}')]

            with self.assertRaisesRegex(ValueError, 'DEX Screener tokens payload must be a list'):
                list(DexScreenerLatestProfilesSource(limit=1).load())

    def test_dirty_numeric_values_map_to_schema_valid_unsafe_defaults(self):
        candidate = map_pair_to_candidate({
            'baseToken': {'address': 'Dirty11111111111111111111111111111111111111', 'symbol': 'DIRTY'},
            'chainId': 'solana',
            'fdv': float('nan'),
            'liquidity': {'usd': True},
            'txns': {'m5': {'buys': 12.5, 'sells': -1}},
            'volume': {'m5': -100},
        })

        Candidate.from_dict(candidate)
        self.assertEqual(candidate['liquidity'], 0.0)
        self.assertEqual(candidate['market_cap'], 0.0)
        self.assertEqual(candidate['tx_count_1m'], 0.0)
        self.assertEqual(candidate['volume_5m'], 0.0)

    def test_dirty_nested_objects_map_to_schema_valid_unsafe_defaults(self):
        candidate = map_pair_to_candidate({
            'baseToken': [],
            'chainId': 'solana',
            'pairAddress': 'Pair111111111111111111111111111111111111111',
            'fdv': 1000,
            'liquidity': [],
            'txns': [],
            'volume': 'bad',
        })

        Candidate.from_dict(candidate)
        self.assertEqual(candidate['symbol'], 'UNKNOWN')
        self.assertEqual(candidate['token_address'], 'Pair111111111111111111111111111111111111111')
        self.assertEqual(candidate['liquidity'], 0.0)
        self.assertEqual(candidate['tx_count_1m'], 0.0)
        self.assertEqual(candidate['volume_5m'], 0.0)

    def test_dirty_identifier_values_map_to_schema_valid_defaults(self):
        candidate = map_pair_to_candidate({
            'baseToken': {'address': 123, 'symbol': '   '},
            'chainId': [],
            'pairAddress': '   ',
            'fdv': 1000,
        })

        Candidate.from_dict(candidate)
        self.assertEqual(candidate['chain'], 'unknown')
        self.assertEqual(candidate['token_address'], 'unknown')
        self.assertEqual(candidate['symbol'], 'UNKNOWN')

    def test_identifier_values_are_trimmed(self):
        candidate = map_pair_to_candidate({
            'baseToken': {'address': ' Token1111111111111111111111111111111111111 ', 'symbol': ' DEX '},
            'chainId': ' solana ',
        })

        Candidate.from_dict(candidate)
        self.assertEqual(candidate['chain'], 'solana')
        self.assertEqual(candidate['token_address'], 'Token1111111111111111111111111111111111111')
        self.assertEqual(candidate['symbol'], 'DEX')

    def test_write_jsonl_replaces_output_without_temp_leftovers(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'nested/candidates.jsonl'
            output_path.parent.mkdir()
            output_path.write_text('old\n', encoding='utf-8')

            write_jsonl([{'symbol': 'DEX', 'chain': 'solana'}], output_path)

            temp_files = list(output_path.parent.glob('.candidates.jsonl.*.tmp'))
            self.assertEqual(output_path.read_text(encoding='utf-8'), '{"chain": "solana", "symbol": "DEX"}\n')
            self.assertEqual(temp_files, [])

    def test_payload_source_requires_object_payload(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'payload.json'
            path.write_text('[]', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'DEX Screener payload must be an object'):
                list(DexScreenerPayloadSource(path).load())

    def test_payload_source_requires_pairs_list(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'payload.json'
            path.write_text('{"pairs":{}}', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'DEX Screener pairs must be a list'):
                list(DexScreenerPayloadSource(path).load())

    def test_payload_source_requires_pair_objects(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'payload.json'
            path.write_text('{"pairs":[[]]}', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'DEX Screener pair 1 must be an object'):
                list(DexScreenerPayloadSource(path).load())

    def test_payload_source_reports_invalid_json_with_path_and_line(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'payload.json'
            path.write_text('{\nnot-json\n', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'payload.json:2: invalid DEX Screener JSON'):
                list(DexScreenerPayloadSource(path).load())

    def test_payload_source_reports_invalid_utf8_with_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'payload.json'
            path.write_bytes(b'\xff')

            with self.assertRaisesRegex(ValueError, 'payload.json: invalid DEX Screener UTF-8'):
                list(DexScreenerPayloadSource(path).load())

    def test_payload_source_requires_positive_limit(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            path = Path(tmp_dir) / 'payload.json'
            path.write_text('{"pairs":[]}', encoding='utf-8')

            with self.assertRaisesRegex(ValueError, 'DEX Screener limit must be greater than 0'):
                list(DexScreenerPayloadSource(path, limit=0).load())

            with self.assertRaisesRegex(ValueError, 'DEX Screener limit must be greater than 0'):
                list(DexScreenerPayloadSource(path, limit=-1).load())

    def test_search_source_requires_non_empty_query(self):
        with self.assertRaisesRegex(ValueError, 'DEX Screener query must be a non-empty string'):
            DexScreenerSearchSource('')

        with self.assertRaisesRegex(ValueError, 'DEX Screener query must be a non-empty string'):
            DexScreenerSearchSource('   ')

    def test_search_source_strips_query_whitespace(self):
        source = DexScreenerSearchSource('  pump token  ')

        self.assertEqual(source.query, 'pump token')

    def test_main_reports_invalid_payload_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload_path = Path(tmp_dir) / 'payload.json'
            output_path = Path(tmp_dir) / 'candidates.jsonl'
            payload_path.write_text('[]', encoding='utf-8')

            stderr = io.StringIO()
            with patch('sys.argv', [
                'dexscreener',
                '--query', 'pump',
                '--payload', str(payload_path),
                '--output', str(output_path),
            ]):
                with redirect_stderr(stderr):
                    code = main()

        self.assertEqual(code, 2)
        self.assertIn('invalid DEX Screener data: DEX Screener payload must be an object', stderr.getvalue())
        self.assertFalse(output_path.exists())

    def test_main_reports_invalid_limit_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload_path = Path(tmp_dir) / 'payload.json'
            output_path = Path(tmp_dir) / 'candidates.jsonl'
            payload_path.write_text('{"pairs":[]}', encoding='utf-8')

            stderr = io.StringIO()
            with patch('sys.argv', [
                'dexscreener',
                '--query', 'pump',
                '--payload', str(payload_path),
                '--limit', '0',
                '--output', str(output_path),
            ]):
                with redirect_stderr(stderr):
                    code = main()

        self.assertEqual(code, 2)
        self.assertIn('invalid DEX Screener data: DEX Screener limit must be greater than 0', stderr.getvalue())
        self.assertFalse(output_path.exists())

    def test_main_reports_empty_live_query_without_network_fetch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'candidates.jsonl'

            stderr = io.StringIO()
            with patch('gmgn_monitor.dexscreener.urlopen') as urlopen:
                with patch('sys.argv', [
                    'dexscreener',
                    '--query', ' ',
                    '--output', str(output_path),
                ]):
                    with redirect_stderr(stderr):
                        code = main()

        self.assertEqual(code, 2)
        self.assertIn('invalid DEX Screener data: DEX Screener query must be a non-empty string', stderr.getvalue())
        self.assertFalse(output_path.exists())
        urlopen.assert_not_called()

    def test_main_reports_missing_live_query_without_network_fetch(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'candidates.jsonl'

            stderr = io.StringIO()
            with patch('gmgn_monitor.dexscreener.urlopen') as urlopen:
                with patch('sys.argv', [
                    'dexscreener',
                    '--output', str(output_path),
                ]):
                    with redirect_stderr(stderr):
                        code = main()

        self.assertEqual(code, 2)
        self.assertIn('invalid DEX Screener data: DEX Screener query must be a non-empty string', stderr.getvalue())
        self.assertFalse(output_path.exists())
        urlopen.assert_not_called()

    def test_main_allows_payload_without_query(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload_path = Path(tmp_dir) / 'payload.json'
            output_path = Path(tmp_dir) / 'candidates.jsonl'
            payload_path.write_text('{"pairs":[]}', encoding='utf-8')

            stderr = io.StringIO()
            stdout = io.StringIO()
            with patch('sys.argv', [
                'dexscreener',
                '--payload', str(payload_path),
                '--output', str(output_path),
            ]):
                with redirect_stdout(stdout), redirect_stderr(stderr):
                    code = main()

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), '')
            self.assertIn('wrote 0 read-only candidates', stdout.getvalue())
            self.assertEqual(output_path.read_text(encoding='utf-8'), '')

    def test_main_reports_payload_read_error_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload_path = Path(tmp_dir) / 'payload.json'
            output_path = Path(tmp_dir) / 'candidates.jsonl'
            payload_path.mkdir()

            stderr = io.StringIO()
            with patch('sys.argv', [
                'dexscreener',
                '--payload', str(payload_path),
                '--output', str(output_path),
            ]):
                with redirect_stderr(stderr):
                    code = main()

        self.assertEqual(code, 2)
        self.assertIn('invalid DEX Screener data:', stderr.getvalue())
        self.assertIn('invalid DEX Screener read:', stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())
        self.assertFalse(output_path.exists())

    def test_main_uses_stripped_live_query_url(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'candidates.jsonl'

            stderr = io.StringIO()
            stdout = io.StringIO()
            with patch('gmgn_monitor.dexscreener.urlopen') as urlopen:
                urlopen.return_value = self.Response(b'{"pairs":[]}')
                with patch('sys.argv', [
                    'dexscreener',
                    '--query', '  pump token  ',
                    '--output', str(output_path),
                ]):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main()

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), '')
            self.assertIn('q=pump+token', urlopen.call_args.args[0].full_url)
            self.assertEqual(urlopen.call_args.args[0].headers['User-agent'], 'gmgn-monitor/0.1 read-only')
            self.assertEqual(output_path.read_text(encoding='utf-8'), '')

    def test_main_fetches_latest_profiles_without_query(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'candidates.jsonl'
            profile_payload = json.dumps([
                {'chainId': 'solana', 'tokenAddress': 'Token1111111111111111111111111111111111111'},
            ]).encode('utf-8')
            token_payload = json.dumps([
                {
                    'chainId': 'solana',
                    'baseToken': {'address': 'Token1111111111111111111111111111111111111', 'symbol': 'LIVE'},
                    'fdv': 42000,
                    'liquidity': {'usd': 9000},
                    'volume': {'m5': 1800},
                    'txns': {'m5': {'buys': 8, 'sells': 7}},
                },
            ]).encode('utf-8')

            stderr = io.StringIO()
            stdout = io.StringIO()
            with patch('gmgn_monitor.dexscreener.urlopen') as urlopen:
                urlopen.side_effect = [self.Response(profile_payload), self.Response(token_payload)]
                with patch('sys.argv', [
                    'dexscreener',
                    '--latest-profiles',
                    '--limit', '1',
                    '--output', str(output_path),
                ]):
                    with redirect_stdout(stdout), redirect_stderr(stderr):
                        code = main()

            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), '')
            self.assertIn('wrote 1 read-only candidates', stdout.getvalue())
            self.assertIn('"source": "dexscreener:token-profiles"', output_path.read_text(encoding='utf-8'))

    def test_main_reports_malformed_latest_profiles_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'candidates.jsonl'

            stderr = io.StringIO()
            with patch('gmgn_monitor.dexscreener.urlopen') as urlopen:
                urlopen.return_value = self.Response(b'{}')
                with patch('sys.argv', [
                    'dexscreener',
                    '--latest-profiles',
                    '--limit', '1',
                    '--output', str(output_path),
                ]):
                    with redirect_stderr(stderr):
                        code = main()

        self.assertEqual(code, 2)
        self.assertIn('invalid DEX Screener data:', stderr.getvalue())
        self.assertIn('DEX Screener token profiles payload must be a list', stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())
        self.assertFalse(output_path.exists())

    def test_main_reports_malformed_live_response_json(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'candidates.jsonl'

            stderr = io.StringIO()
            with patch('gmgn_monitor.dexscreener.urlopen') as urlopen:
                urlopen.return_value = self.Response(b'{\nnot-json\n')
                with patch('sys.argv', [
                    'dexscreener',
                    '--query', 'pump',
                    '--output', str(output_path),
                ]):
                    with redirect_stderr(stderr):
                        code = main()

        self.assertEqual(code, 2)
        self.assertIn('invalid DEX Screener data:', stderr.getvalue())
        self.assertIn('invalid DEX Screener response JSON at line 2', stderr.getvalue())
        self.assertFalse(output_path.exists())

    def test_main_reports_malformed_live_response_utf8(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            output_path = Path(tmp_dir) / 'candidates.jsonl'

            stderr = io.StringIO()
            with patch('gmgn_monitor.dexscreener.urlopen') as urlopen:
                urlopen.return_value = self.Response(b'\xff')
                with patch('sys.argv', [
                    'dexscreener',
                    '--query', 'pump',
                    '--output', str(output_path),
                ]):
                    with redirect_stderr(stderr):
                        code = main()

        self.assertEqual(code, 2)
        self.assertIn('invalid DEX Screener data:', stderr.getvalue())
        self.assertIn('invalid DEX Screener response UTF-8', stderr.getvalue())
        self.assertFalse(output_path.exists())

    def test_main_reports_missing_payload_file_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload_path = Path(tmp_dir) / 'missing.json'
            output_path = Path(tmp_dir) / 'candidates.jsonl'

            stderr = io.StringIO()
            with patch('sys.argv', [
                'dexscreener',
                '--query', 'pump',
                '--payload', str(payload_path),
                '--output', str(output_path),
            ]):
                with redirect_stderr(stderr):
                    code = main()

        self.assertEqual(code, 2)
        self.assertIn('invalid DEX Screener data:', stderr.getvalue())
        self.assertIn('invalid DEX Screener read:', stderr.getvalue())
        self.assertIn('missing.json', stderr.getvalue())
        self.assertNotIn('Traceback', stderr.getvalue())
        self.assertFalse(output_path.exists())

    def test_main_reports_malformed_payload_json_with_path(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload_path = Path(tmp_dir) / 'payload.json'
            output_path = Path(tmp_dir) / 'candidates.jsonl'
            payload_path.write_text('{\nnot-json\n', encoding='utf-8')

            stderr = io.StringIO()
            with patch('sys.argv', [
                'dexscreener',
                '--query', 'pump',
                '--payload', str(payload_path),
                '--output', str(output_path),
            ]):
                with redirect_stderr(stderr):
                    code = main()

        self.assertEqual(code, 2)
        self.assertIn('invalid DEX Screener data:', stderr.getvalue())
        self.assertIn('payload.json:2: invalid DEX Screener JSON', stderr.getvalue())
        self.assertFalse(output_path.exists())

    def test_main_reports_output_write_failure_without_traceback(self):
        with tempfile.TemporaryDirectory() as tmp_dir:
            payload_path = Path(tmp_dir) / 'payload.json'
            payload_path.write_text('{"pairs":[]}', encoding='utf-8')
            blocked_parent = Path(tmp_dir) / 'blocked'
            blocked_parent.write_text('not-a-directory\n', encoding='utf-8')
            output_path = blocked_parent / 'candidates.jsonl'

            stderr = io.StringIO()
            with patch('sys.argv', [
                'dexscreener',
                '--query', 'pump',
                '--payload', str(payload_path),
                '--output', str(output_path),
            ]):
                with redirect_stderr(stderr):
                    code = main()

        self.assertEqual(code, 2)
        self.assertIn('failed to write DEX Screener data:', stderr.getvalue())
        self.assertIn('blocked', stderr.getvalue())
        self.assertFalse(output_path.exists())


if __name__ == '__main__':
    unittest.main()
