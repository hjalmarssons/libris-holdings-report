import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
import update_report as report


def item(key, sigel):
    return {'@id': key, '@type': 'Item', 'itemOf': {'@id': report.ENTITY},
            'heldBy': {'@id': 'https://libris.kb.se/library/' + sigel, 'name': sigel}}


class ReportTests(unittest.TestCase):
    def test_pagination_and_unique_libraries(self):
        pages = iter([{'totalItems': 3, 'itemOffset': 0, 'items': [item('a','S'), item('b','S')]},
                      {'totalItems': 3, 'itemOffset': 2, 'items': [item('c','G')]}])
        self.assertEqual(len(report.collect(lambda url: next(pages))), 2)

    def test_incomplete_and_missing_library_fail(self):
        for response in [{'totalItems': 1, 'itemOffset': 0, 'items': []},
                         {'totalItems': 1, 'itemOffset': 0, 'items': [{'@id':'a','@type':'Item','itemOf':{'@id':report.ENTITY}}]}]:
            with self.assertRaises(ValueError):
                report.collect(lambda url: response)

    def test_missing_day_is_a_gap(self):
        svg = report.graph([{'date':'2026-10-10','count':19},{'date':'2026-10-12','count':21}])
        self.assertNotIn('stroke-width="2.5"',svg)
        self.assertEqual(svg.count('<circle '),2)

    def test_daily_skip_stockholm_date_and_failed_fetch_preserve_data(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            latest={'title':'Test','isbn':'1','libris_id':'c0qkzx1t9hs5ml77','timezone':'Europe/Stockholm',
                    'date':'2026-10-17','checked_at':'2026-10-16T23:30:00+00:00','count':0,'libraries':[],
                    'changes':{'baseline':True,'compared_to':None,'added':[],'removed':[]}}
            (root/'libraries.json').write_text(json.dumps(latest))
            (root/'history.csv').write_text('date,count\n2026-10-17,0\n')
            (root/'template.html').write_text('@@COUNT@@ @@DATE@@ @@CHECKED@@ @@CHANGES@@ @@ROWS@@')
            def fail(url): raise ValueError('Network failed')
            report.rebuild(root,fail,datetime(2026,10,16,23,45,tzinfo=timezone.utc))
            original=(root/'libraries.json').read_bytes()
            with self.assertRaises(ValueError):
                report.rebuild(root,fail,datetime(2026,10,18,12,tzinfo=timezone.utc))
            self.assertEqual((root/'libraries.json').read_bytes(),original)


if __name__ == '__main__': unittest.main()
