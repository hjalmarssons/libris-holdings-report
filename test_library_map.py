import json
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import URLError

import library_map as maps

LIBRARIES = [{'sigel': 'A', 'name': '<Test & library>', 'uri': 'https://libris.kb.se/library/A'},
             {'sigel': 'B', 'name': 'Network', 'uri': 'https://libris.kb.se/library/B'}]
SNAPSHOT = {'date': '2026-10-17', 'checked_at': '2026-10-17T08:00:00+00:00',
            'count': 2, 'libraries': LIBRARIES, 'title': '</script><script>bad()</script>'}
LOCATION = {'latitude': 59.3, 'longitude': 18.0, 'city': 'Stockholm', 'source': 'https://example.org/', 'note': 'Directory location'}
COUNTRIES = {'features': []}


class LibraryMapTests(unittest.TestCase):
    def test_invalid_coordinates_not_plotted_including_zero_sentinel(self):
        for lat, lon in [(None, None), (0, 0), (True, 18), (float('nan'), 18), (59, float('inf')), (91, 18)]:
            self.assertFalse(maps.valid_location({'latitude': lat, 'longitude': lon}))
        data = maps.map_data(SNAPSHOT, {'A': LOCATION}, {}, {})
        self.assertEqual([x['sigel'] for x in data['unmapped']], ['B'])
        self.assertEqual(len(data['libraries']), 1)

    def test_fallback_is_labeled_and_does_not_replace_directory_coordinate(self):
        override = {**LOCATION, 'latitude': 60, 'note': 'Representative network location'}
        data = maps.map_data(SNAPSHOT, {'A': LOCATION, 'B': {'latitude': 0, 'longitude': 0}},
                             {'A': override, 'B': override}, {'A': '2026-10-07'})
        self.assertEqual(data['libraries'][0]['latitude'], 59.3)
        self.assertFalse(data['libraries'][0]['representative'])
        self.assertEqual(data['libraries'][1]['latitude'], 60)
        self.assertTrue(data['libraries'][1]['representative'])
        self.assertEqual(data['libraries'][0]['first_seen'], '2026-10-07')

    def test_directory_validation_and_only_public_location_fields_retained(self):
        def fetch(url):
            self.assertIn('sigel=A%2CB', url)
            return {'libraries': [{'sigel': 'A', **LOCATION, 'email': 'not-retained',
                                   'address': [{'address_type': 'gen', 'city': 'Stockholm'}]}]}
        result = maps.directory_locations(LIBRARIES, fetch)
        self.assertNotIn('email', json.dumps(result))
        self.assertEqual(result['A']['city'], 'Stockholm')
        with self.assertRaises(ValueError):
            maps.directory_locations(LIBRARIES, lambda url: {'libraries': [{'sigel': 'OTHER'}]})
        with self.assertRaises(ValueError):
            maps.directory_locations(LIBRARIES, lambda url: {'libraries': 'not a list'})

    def test_each_current_sigel_has_same_dot_style_and_html_data_is_escaped(self):
        data = maps.map_data(SNAPSHOT, {'A': LOCATION, 'B': LOCATION}, {}, {})
        svg = maps.svg_map(data, COUNTRIES)
        self.assertEqual(svg.count('class="library-dot"'), 2)
        dots = [node for node in ET.fromstring(svg).iter('{http://www.w3.org/2000/svg}circle') if node.get('class') == 'library-dot']
        self.assertTrue(all(node.get('fill') == '#2563eb' and node.get('r') == '4.5' for node in dots))
        self.assertIn('&lt;Test &amp; library&gt;', svg)
        html = maps.interactive_html(data, svg, '2026-10-17', False)
        self.assertNotIn('</script><script>bad()', html)
        self.assertIn('\\u003c/script\\u003e', html)

    def test_directory_outage_uses_cache_but_not_removed_holdings(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'data/snapshots').mkdir(parents=True)
            (root / 'libraries.json').write_text(json.dumps(SNAPSHOT))
            (root / 'first-seen.json').write_text(json.dumps({'A': '2026-10-07'}))
            (root / 'library-locations.json').write_text(json.dumps({'checked_at': '2026-10-16',
                'libraries': {'A': LOCATION, 'REMOVED': LOCATION}}))
            (root / 'location-overrides.json').write_text('{}')
            (root / 'map-countries.geojson').write_text(json.dumps(COUNTRIES))
            def fail(url):
                raise URLError('Unavailable')
            data = maps.build(root, fetch=fail)
            self.assertTrue(data['cached_coordinates'])
            self.assertEqual(data['directory_checked_at'], '2026-10-16')
            self.assertEqual([x['sigel'] for x in data['libraries']], ['A'])
            self.assertEqual([x['sigel'] for x in data['unmapped']], ['B'])
            self.assertTrue((root / 'map.html').exists())
            self.assertEqual(json.loads((root / 'libraries.json').read_text()), SNAPSHOT)

    def test_projection_places_current_locations_inside_map(self):
        for lon, lat in [(10.5, 55.5), (24, 69), (19.94, 60.10), (12.95, 57.72)]:
            x, y = maps.project(lon, lat)
            self.assertTrue(0 < x < maps.WIDTH)
            self.assertTrue(0 < y < maps.HEIGHT)

    def test_backup_attempt_reuses_map_for_same_observation(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / 'data/snapshots').mkdir(parents=True)
            (root / 'libraries.json').write_text(json.dumps(SNAPSHOT))
            (root / 'location-overrides.json').write_text('{}')
            (root / 'map-countries.geojson').write_text(json.dumps(COUNTRIES))
            calls = []
            def fetch(url):
                calls.append(url)
                return {'libraries': [{'sigel': lib['sigel'], **LOCATION} for lib in LIBRARIES]}
            first = maps.build(root, fetch)
            second = maps.build(root, fetch, if_needed=True)
            self.assertEqual(first, second)
            self.assertEqual(len(calls), 2)  # Holdings locations and the participant list, once each.

    def test_reference_pagination_and_active_participant_filter(self):
        def row(sigel, **changes):
            return {'sigel': sigel, 'name': sigel, 'alive': True, 'libris_reg': True, **LOCATION, **changes}
        pages = [[row(str(i)) for i in range(200)],
                 [row('last'), row('closed', alive=False), row('statistics-only', libris_reg=False)]]
        calls = []
        def fetch(url):
            calls.append(url)
            return {'libraries': pages[len(calls) - 1]}
        directory = maps.background_directory(fetch)
        self.assertEqual(len(directory), 201)
        self.assertNotIn('closed', directory)
        self.assertNotIn('statistics-only', directory)
        self.assertIn('start=200', calls[1])
        with self.assertRaises(ValueError):
            maps.background_directory(lambda url: {'libraries': [row('duplicate')] * 200})

    def test_current_holdings_are_excluded_from_hollow_circles_even_when_unmapped(self):
        data = maps.map_data(SNAPSHOT, {'A': LOCATION}, {}, {})
        reference = {key: {'sigel': key, 'name': key, **LOCATION} for key in ['A', 'B', 'C']}
        reference['missing'] = {'sigel': 'missing', 'name': 'Missing', 'latitude': None, 'longitude': None}
        reference['outside'] = {'sigel': 'outside', 'name': 'Outside', **LOCATION, 'latitude': 40}
        maps.add_background(data, reference)
        self.assertEqual([x['sigel'] for x in data['other_libraries']], ['C'])
        self.assertEqual([x['sigel'] for x in data['other_unmapped']], ['missing'])
        self.assertEqual([x['sigel'] for x in data['other_outside_map']], ['outside'])
        svg = maps.svg_map(data, COUNTRIES)
        circles = [node for node in ET.fromstring(svg).iter('{http://www.w3.org/2000/svg}circle') if node.get('class') == 'other-library']
        self.assertEqual(len(circles), 1)
        self.assertEqual(circles[0].get('fill'), 'none')
        self.assertLess(svg.index('class="other-library"'), svg.index('class="library-dot"'))

    def test_participant_cache_refreshes_weekly(self):
        now = datetime(2026, 10, 17, tzinfo=timezone.utc)
        self.assertTrue(maps.fresh_background({'checked_at': (now - timedelta(days=6)).isoformat()}, now))
        self.assertFalse(maps.fresh_background({'checked_at': (now - timedelta(days=7)).isoformat()}, now))
        self.assertFalse(maps.fresh_background({'checked_at': 'never'}, now))


if __name__ == '__main__':
    unittest.main()
