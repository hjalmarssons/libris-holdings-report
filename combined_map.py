#!/usr/bin/env python3
"""Replace public map outputs with the two-edition comparison map."""
import json
from pathlib import Path

import library_map as maps
from update_report import ROOT


def union_libraries(earlier, current):
    def indexed(snapshot):
        libraries = snapshot['libraries']
        result = {lib['sigel']: lib for lib in libraries}
        if snapshot['count'] != len(result) or len(result) != len(libraries):
            raise ValueError('Invalid or duplicate library sigels in observation')
        return result
    a, b = indexed(earlier), indexed(current)
    return sorted([
        {**(b.get(sigel) or a[sigel]), 'holds_earlier': sigel in a,
         'holds_current': sigel in b}
        for sigel in a.keys() | b.keys()
    ], key=lambda lib: (lib['name'].casefold(), lib['sigel'].casefold()))


def build(root=ROOT):
    def read(name):
        return json.loads((root / name).read_text(encoding='utf-8'))
    earlier, current = read('comparison-libraries.json'), read('libraries.json')
    reference = read('comparison.json')
    if any(earlier[k] != reference[k] for k in ('libris_id', 'date', 'count')):
        raise ValueError('Comparison map and graph snapshots disagree')
    baseline = read('library-map.json')
    if baseline['checked_at'] != current['checked_at'] or baseline['count'] != current['count']:
        raise ValueError('Current map must be refreshed before the combined map')
    libraries = union_libraries(earlier, current)
    snapshot = {'date': current['date'], 'checked_at': current['checked_at'],
                'title': 'Combined book holdings', 'count': len(libraries), 'libraries': libraries}
    locations = dict(earlier['locations'])
    current_cache = read('library-locations.json')
    for sigel, location in current_cache['libraries'].items():
        if maps.valid_location(location) or not maps.valid_location(locations.get(sigel, {})):
            locations[sigel] = location
    data = maps.map_data(snapshot, locations, read('location-overrides.json'), {})
    participants = read('libris-participants.json')
    maps.add_background(data, participants['libraries'])
    # The single-book cache remains separate, so backup attempts can reuse it.
    data.update(combined=True,
                earlier={k: earlier[k] for k in ('title', 'libris_id', 'date', 'checked_at', 'count')},
                current={k: current[k] for k in ('title', 'libris_id', 'date', 'checked_at', 'count')},
                both_count=sum(lib['holds_earlier'] and lib['holds_current'] for lib in libraries),
                participant_checked_at=baseline['participant_checked_at'],
                participant_cached=baseline['participant_cached'],
                directory_checked_at=min(earlier['directory_checked_at'], current_cache['checked_at']),
                cached_coordinates=baseline['cached_coordinates'])
    # Older-edition locations are a saved directory snapshot; holding dates stay explicit.
    for lib in data.get('other_libraries', []):
        lib['note'] = ('Active Libris participant; no registered holding for either edition '
                       'in the two observations. A network dot represents one directory location.')
    svg = maps.svg_map(data, read('map-countries.geojson'))
    html = maps.interactive_html(data, svg, data['directory_checked_at'], data['cached_coordinates'])
    for path, text in {
        'map.svg': svg,
        'map.html': html,
        'combined-library-map.json': json.dumps(data, ensure_ascii=False, indent=2) + '\n',
    }.items():
        maps.atomic_write(root / path, text)
    print(f"Combined holdings: {len(libraries)} sigels; {data['both_count']} both; {len(data['libraries'])} mapped")
    return data


if __name__ == '__main__':
    build()
