import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import collect


class CollectionTests(unittest.TestCase):
    def test_discovery_uses_report_paths_and_ignores_other_comment_authors(self):
        class Client:
            def pages(self, url):
                return [
                    {'id': 1, 'user': {'login': 'openeuler-ci-bot'}, 'body': 'https://ci.openeuler.openatom.cn/job/custom/job/trigger/job/other-name//123/console'},
                    {'id': 2, 'user': {'login': 'someone'}, 'body': 'https://ci.openeuler.openatom.cn/job/wrong/job/trigger/job/name/1/'},
                ]
        paths, comments = collect.discover_jobs(Client(), 'api', [{'number': 7}], [])
        self.assertEqual(list(paths), ['custom/trigger/other-name'])
        self.assertEqual(paths['custom/trigger/other-name']['kind'], 'trigger')
        self.assertEqual(paths['custom/trigger/other-name']['evidence'][0]['pr'], 7)
        self.assertEqual(len(comments[7]), 2)

    def test_all_shares_cutoff_and_failure_keeps_previous_snapshot(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root/'data').mkdir()
            old = {'repositories': [{'name': 'ubs-comm', 'status': 'success', 'snapshot': 'repos/ubs-comm.json', 'meta': {'end_ms': 1}}]}
            (root/'data/repositories.json').write_text(json.dumps(old))
            cutoffs = []

            def run(args, config, client):
                cutoffs.append(args.until)
                if config['name'] == 'ubs-comm':
                    raise OSError('unavailable')
                return {'meta': {'repository': config['repository'], 'errors': []}}

            args = argparse.Namespace(until='2026-09-10T00:00:00+00:00', days=30, refresh=False, offline=True, all=True, repo='ubs-engine')
            with patch.object(collect, 'ROOT', root), patch.object(collect, 'run', run), patch.object(collect, 'publish_index'):
                result = collect.collect_many(args)
            self.assertEqual(len(result), 9)
            self.assertEqual(len(set(cutoffs)), 1)
            failed = next(r for r in result if r['name'] == 'ubs-comm')
            self.assertEqual(failed['status'], 'failed')
            self.assertEqual(failed['meta'], {'end_ms': 1})
            self.assertEqual(failed['snapshot'], 'repos/ubs-comm.json')
            self.assertEqual(result[-1]['status'], 'success')


if __name__ == '__main__':
    unittest.main()
