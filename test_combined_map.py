import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import combined_map


LOCATION = {'latitude': 59.3, 'longitude': 18.0, 'city': 'Stockholm',
            'source': 'https://bibdb.libris.kb.se/api/lib', 'note': 'Directory location'}


def library(sigel):
    return {'sigel': sigel, 'name': 'Library ' + sigel,
            'uri': 'https://libris.kb.se/library/' + sigel}


def snapshot(sigels, date, title):
    return {'libraries': [library(s) for s in sigels], 'count': len(sigels), 'date': date,
            'checked_at': date + 'T12:00:00+00:00', 'title': title, 'libris_id': title}


class CombinedMapTests(unittest.TestCase):
    def seed(self, root):
        earlier = snapshot(['A', 'B', 'MISSING'], '2026-10-19', 'earlier')
        earlier.update(locations={'A': LOCATION, 'B': LOCATION}, directory_checked_at='2026-10-19')
        current = snapshot(['B', 'C'], '2026-10-21', 'current')
        fixtures = {
            'comparison-libraries.json': earlier,
            'comparison.json': {k: earlier[k] for k in ('libris_id', 'date', 'count')},
            'libraries.json': current,
            'library-map.json': {'checked_at': current['checked_at'], 'count': 2,
                'participant_checked_at': '2026-10-21', 'participant_cached': False,
                'cached_coordinates': False},
            'library-locations.json': {'checked_at': '2026-10-21', 'libraries': {
                'B': {'latitude': None, 'longitude': None}, 'C': LOCATION}},
            'location-overrides.json': {}, 'map-countries.geojson': {'features': []},
            'libris-participants.json': {'checked_at': '2026-10-21',
                'libraries': {s: {**library(s), **LOCATION} for s in ['A','B','C','D','MISSING']}}}
        for path, content in fixtures.items():
            (root/path).write_text(json.dumps(content))
        return fixtures

    def test_union_styles_dates_and_unmapped_exclude_all_holders_from_grey(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixtures = self.seed(root)
            original = {path: (root/path).read_bytes() for path in fixtures}
            data = combined_map.build(root)
            self.assertEqual(data['count'], 4)
            self.assertEqual(data['both_count'], 1)
            self.assertEqual([x['sigel'] for x in data['unmapped']], ['MISSING'])
            self.assertEqual([x['sigel'] for x in data['other_libraries']], ['D'])
            nodes = list(ET.fromstring((root/'map.svg').read_text()).iter())
            dots = [n for n in nodes if n.get('class') == 'library-dot']
            self.assertEqual([(n.get('fill'), n.get('stroke')) for n in dots],
                [('none','#dc2626'), ('#2563eb','#dc2626'), ('#2563eb','#ffffff')])
            self.assertEqual(len([n for n in nodes if n.get('class') == 'other-library']), 1)
            html = (root/'map.html').read_text()
            self.assertIn('red outline with blue fill: both', html)
            self.assertIn('2026-10-19 (fixed snapshot)', html)
            self.assertIn('2026-10-21 (latest)', html)
            self.assertEqual(original, {path: (root/path).read_bytes() for path in fixtures})

    def test_next_observation_removes_blue_fill_but_keeps_earlier_red_outline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.seed(root)
            combined_map.build(root)
            current = snapshot(['C'], '2026-10-22', 'current')
            (root/'libraries.json').write_text(json.dumps(current))
            baseline = json.loads((root/'library-map.json').read_text())
            baseline.update(checked_at=current['checked_at'], count=1)
            (root/'library-map.json').write_text(json.dumps(baseline))
            data = combined_map.build(root)
            b = next(x for x in data['libraries'] if x['sigel'] == 'B')
            self.assertTrue(b['holds_earlier'])
            self.assertFalse(b['holds_current'])
            self.assertEqual(data['both_count'], 0)
            self.assertEqual(data['current']['date'], '2026-10-22')
            self.assertEqual(data['earlier']['date'], '2026-10-19')

    def test_inconsistent_or_duplicate_input_fails_before_replacing_map(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.seed(root)
            combined_map.build(root)
            original = (root/'map.svg').read_bytes()
            reference = json.loads((root/'comparison.json').read_text())
            reference['count'] = 100
            (root/'comparison.json').write_text(json.dumps(reference))
            with self.assertRaisesRegex(ValueError, 'snapshots disagree'):
                combined_map.build(root)
            self.assertEqual((root/'map.svg').read_bytes(), original)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            combined_map.union_libraries(snapshot(['A', 'A'], '2026-10-19', 'earlier'),
                                         snapshot(['B'], '2026-10-21', 'current'))


if __name__ == '__main__':
    unittest.main()
