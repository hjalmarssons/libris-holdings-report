#!/usr/bin/env python3
"""Build the public, offline library dot map from the latest holdings observation."""
import argparse
import json
import math
import sys
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import urlencode

from update_report import ROOT, request_json as get_json


def atomic_write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + '.tmp')
    temporary.write_text(content, encoding='utf-8')
    temporary.replace(path)

DIRECTORY = 'https://bibdb.libris.kb.se/api/lib'
WIDTH, HEIGHT = 760, 900
BOUNDS = (9.5, 54.8, 25.0, 69.8)  # west, south, east, north
MAP_VERSION = 2


def background_directory(fetch=get_json):
    """Read all pages of active Libris participants, retaining only map fields."""
    result, seen, offset = {}, set(), 0
    while True:
        url = DIRECTORY + '?' + urlencode({'dump': 'true', 'libris_reg': 1, 'alive': 1,
                                           'level': 'brief', 'n': 200, 'start': offset})
        payload = fetch(url)
        records = payload.get('libraries')
        if not isinstance(records, list):
            raise ValueError('Malformed participant directory response')
        for entry in records:
            if not isinstance(entry, dict) or not isinstance(entry.get('sigel'), str):
                raise ValueError('Participant has no sigel')
            sigel = entry['sigel']
            if sigel in seen:
                raise ValueError('Repeated directory page; refusing an incomplete map')
            seen.add(sigel)
            # Check flags locally as well: API boolean filters require 1, not "true".
            if entry.get('alive') is not True or entry.get('libris_reg') is not True:
                continue
            result[sigel] = {'sigel': sigel, 'name': entry.get('name') or sigel,
                             'uri': 'https://libris.kb.se/library/' + sigel,
                             'latitude': entry.get('latitude'), 'longitude': entry.get('longitude'),
                             'city': '', 'country_code': entry.get('country_code'),
                             'source': DIRECTORY + '?' + urlencode({'sigel': sigel}),
                             'note': 'Active Libris participant; no registered holding for this edition in the latest observation. A network dot represents one directory location.'}
        offset += len(records)
        if len(records) < 200:
            return result
        if offset >= 10000:
            raise ValueError('Unexpected directory size; refusing a truncated map')


def fresh_background(cache, now=None):
    try:
        checked = datetime.fromisoformat(cache['checked_at'])
        now = now or datetime.now(timezone.utc)
        return checked.tzinfo is not None and timedelta(0) <= now - checked < timedelta(days=7)
    except (KeyError, TypeError, ValueError):
        return False


def add_background(data, directory):
    current = {lib['sigel'] for lib in data['libraries'] + data['unmapped']}
    other, missing, outside = [], [], []
    for sigel in sorted(directory, key=str.casefold):
        if sigel in current:
            continue
        entry = directory[sigel]
        if not valid_location(entry):
            missing.append({'sigel': sigel, 'name': entry['name']})
            continue
        west, south, east, north = BOUNDS
        if not (west <= entry['longitude'] <= east and south <= entry['latitude'] <= north):
            outside.append(entry)
            continue
        other.append(entry)
    data.update(other_libraries=other, other_unmapped=missing, other_outside_map=outside,
                participant_count=len(directory), map_version=MAP_VERSION)
    return data


def valid_location(record):
    lat, lon = record.get('latitude'), record.get('longitude')
    return (type(lat) in (int, float) and type(lon) in (int, float)
            and math.isfinite(lat) and math.isfinite(lon)
            and -90 < lat < 90 and -180 <= lon <= 180 and (lat, lon) != (0, 0))


def directory_locations(libraries, fetch=get_json):
    if not libraries:
        return {}
    requested = {x['sigel'] for x in libraries}
    payload = fetch(DIRECTORY + '?' + urlencode({'sigel': ','.join(sorted(requested)), 'n': 200}))
    records = payload.get('libraries')
    if not isinstance(records, list):
        raise ValueError('Malformed library directory response')
    result = {}
    for entry in records:
        sigel = entry.get('sigel')
        if sigel not in requested or sigel in result:
            raise ValueError('Unexpected or duplicate directory sigel')
        city = next((a.get('city') for a in entry.get('address', [])
                     if a.get('address_type') == 'gen' and a.get('city')), '')
        result[sigel] = {'latitude': entry.get('latitude'), 'longitude': entry.get('longitude'),
                         'city': city, 'source': DIRECTORY + '?' + urlencode({'sigel': sigel}),
                         'note': 'Directory location for this sigel; networks and multi-site libraries may have other branches.'}
    return result


def map_data(snapshot, directory, overrides, first_seen):
    mapped, missing = [], []
    for library in snapshot['libraries']:
        sigel = library['sigel']
        location = directory.get(sigel, {})
        if not valid_location(location):
            location = overrides.get(sigel, {})
        if not valid_location(location):
            missing.append(library)
            continue
        mapped.append({**library, **location, 'first_seen': first_seen.get(sigel),
                       'representative': sigel in overrides and location == overrides[sigel]})
    return {'date': snapshot['date'], 'checked_at': snapshot['checked_at'], 'title': snapshot['title'],
            'count': snapshot['count'], 'libraries': mapped, 'unmapped': missing}


def mercator(lon, lat):
    return math.radians(lon), math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))


def project(lon, lat):
    west, south, east, north = BOUNDS
    x0, y0 = mercator(west, south)
    x1, y1 = mercator(east, north)
    scale = min((WIDTH - 40) / (x1 - x0), (HEIGHT - 180) / (y1 - y0))
    x, y = mercator(lon, lat)
    return (WIDTH / 2 + (x - (x0 + x1) / 2) * scale,
            HEIGHT / 2 - (y - (y0 + y1) / 2) * scale)


def svg_map(data, countries):
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" id="library-map" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="map-title map-desc">',
           f'<title id="map-title">{escape(data["title"])} — libraries with holdings</title>',
           f'<desc id="map-desc">{len(data["libraries"])} of {data["count"]} sigels mapped on {data["date"]}. One blue dot per sigel. Network dots represent one location, not individual branches.</desc>',
           f'<rect width="{WIDTH}" height="{HEIGHT}" fill="#eaf2f7"/>',
           '<g id="map-layer">']
    for feature in countries['features']:
        geometry = feature['geometry']
        polygons = geometry['coordinates'] if geometry['type'] == 'MultiPolygon' else [geometry['coordinates']]
        paths = []
        for polygon in polygons:
            for ring in polygon:
                points = [project(lon, lat) for lon, lat, *_ in ring]
                paths.append('M' + ' L'.join(f'{x:.2f},{y:.2f}' for x, y in points) + ' Z')
        fill = '#ffffff' if feature['properties']['name'] == 'Sweden' else '#e1e8eb'
        svg.append(f'<path d="{" ".join(paths)}" fill="{fill}" fill-rule="evenodd" stroke="#aebfc9" stroke-width="0.8" vector-effect="non-scaling-stroke"/>')
    labels = [('SWEDEN', 16, 65.8), ('NORWAY', 11, 64), ('FINLAND', 24, 65.2), ('Åland', 20.6, 60.3)]
    for label, lon, lat in labels:
        x, y = project(lon, lat)
        svg.append(f'<text x="{x:.2f}" y="{y:.2f}" fill="#657b89" font-size="14" font-family="sans-serif" text-anchor="middle">{label}</text>')
    # Draw the hollow reference circles first so holdings always remain visible.
    svg.append('<g id="other-libraries">')
    for i, library in enumerate(data.get('other_libraries', [])):
        x, y = project(library['longitude'], library['latitude'])
        no_holding = 'no registered holding for either edition in these observations' if data.get('combined') else 'no registered holding for this edition'
        title = escape(f'{library["name"]} ({library["sigel"]}) — {no_holding}')
        svg.append(f'<circle class="other-library" data-index="{i}" tabindex="0" role="button" aria-label="{title}" cx="{x:.3f}" cy="{y:.3f}" r="3.5" fill="none" stroke="#8a99a6" stroke-width="1" vector-effect="non-scaling-stroke"><title>{title}</title></circle>')
    svg.append('</g>')
    for i, library in enumerate(data['libraries']):
        x, y = project(library['longitude'], library['latitude'])
        title = escape(f'{library["name"]} ({library["sigel"]}) — {library["city"]}. {library["note"]}')
        fill, stroke, stroke_width = '#2563eb', '#ffffff', 1
        if data.get('combined'):
            fill = '#2563eb' if library['holds_current'] else 'none'
            stroke = '#dc2626' if library['holds_earlier'] else '#ffffff'
            stroke_width = 2 if library['holds_earlier'] else 1
            status = ('both editions' if library['holds_current'] and library['holds_earlier'] else
                      'Ojämlikhetens dimensioner' if library['holds_earlier'] else 'Välfärd och livsvillkor')
            title += escape(' Holdings: ' + status)
        svg.append(f'<circle class="library-dot" data-index="{i}" tabindex="0" role="button" aria-label="{title}" cx="{x:.3f}" cy="{y:.3f}" r="4.5" fill="{fill}" stroke="{stroke}" stroke-width="{stroke_width}" vector-effect="non-scaling-stroke"><title>{title}</title></circle>')
    svg.extend(['</g>', '<g class="map-caption"><rect x="16" y="16" width="390" height="68" rx="8" fill="white" fill-opacity="0.95"/>',
                f'<text x="30" y="43" font-family="sans-serif" font-size="16" fill="#203245">{escape(data["title"].split(":")[0])}</text>',
                f'<text x="30" y="68" font-family="sans-serif" font-size="14" fill="#627688">{data["date"]} · {len(data["libraries"])} of {data["count"]} sigels mapped</text>',
                '<rect x="16" y="843" width="640" height="40" rx="6" fill="white" fill-opacity="0.95"/>',
                '<circle cx="33" cy="862" r="4.5" fill="#2563eb"/><text x="45" y="867" font-family="sans-serif" font-size="13" fill="#627688">Holding registered</text>',
                '<circle cx="207" cy="862" r="3.5" fill="none" stroke="#8a99a6"/><text x="219" y="867" font-family="sans-serif" font-size="13" fill="#627688">Other Libris participant</text>',
                '<text x="424" y="867" font-family="sans-serif" font-size="11" fill="#627688">Natural Earth / KB · One location per sigel</text>', '</g></svg>'])
    rendered = '\n'.join(svg) + '\n'
    if data.get('combined'):
        # Replace only the legend; the map layer retains the same accessible dots.
        start = rendered.index('<rect x="16" y="843"')
        rendered = rendered[:start] + '''<rect x="16" y="835" width="728" height="56" rx="6" fill="white" fill-opacity="0.97"/>
<g font-family="sans-serif" font-size="12" fill="#627688">
<circle cx="32" cy="852" r="4.5" fill="none" stroke="#dc2626" stroke-width="2"/><text x="44" y="856">Ojämlikhetens dimensioner</text>
<circle cx="260" cy="852" r="4.5" fill="#2563eb"/><text x="272" y="856">Välfärd och livsvillkor</text>
<circle cx="483" cy="852" r="4.5" fill="#2563eb" stroke="#dc2626" stroke-width="2"/><text x="495" y="856">Both</text>
<circle cx="565" cy="852" r="3.5" fill="none" stroke="#8a99a6"/><text x="577" y="856">Other participant</text>
<text x="30" y="879" font-size="11">Natural Earth / KB · One location per sigel · Grey circles exclude the union of both editions’ holdings</text>
</g></g></svg>\n'''
        rendered = rendered.replace('One blue dot per sigel.', 'Red outline: earlier edition; blue fill: current edition; both styles: both editions.')
    return rendered


def interactive_html(data, svg, directory_date, stale):
    encoded = json.dumps(data, ensure_ascii=False).replace('<', '\\u003c').replace('>', '\\u003e').replace('&', '\\u0026')
    rows = []
    for i, lib in enumerate(data['libraries']):
        rows.append(f'<li><button type="button" data-library="{i}">{escape(lib["name"])} <small>{escape(lib["sigel"])}</small></button></li>')
    missing = ', '.join(f'{x["name"]} ({x["sigel"]})' for x in data['unmapped']) or 'none'
    status = f'Coordinates last checked {directory_date}.' + (' Directory unavailable; cached coordinates used.' if stale else '')
    background_status = (f'{len(data.get("other_libraries", []))} other Libris participants shown as hollow circles; '
                         f'{len(data.get("other_unmapped", []))} without usable coordinates; '
                         f'{len(data.get("other_outside_map", []))} outside the map area. '
                         f'Participant directory checked {data.get("participant_checked_at", "never")}.')
    if data.get('participant_cached'):
        background_status += ' Participant directory unavailable; cached data used.'
    html = '''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Library map</title><style>
*{box-sizing:border-box}body{margin:0;background:#f6f8fb;color:#203245;font:15px/1.5 system-ui,sans-serif}main{max-width:1260px;margin:auto;padding:28px}h1{font-size:28px;line-height:1.2;margin:0 0 10px}p{margin:8px 0 16px}.muted,small{color:#627688}.layout{display:grid;grid-template-columns:minmax(0,2fr) minmax(270px,1fr);gap:24px}.map-wrap{position:relative;overflow:hidden;border:1px solid #d1dce4;border-radius:14px;background:#eaf2f7}.map-caption{display:none}svg{display:block;width:100%;height:min(76vh,900px);touch-action:none;cursor:grab}.library-dot,.other-library{cursor:pointer}.library-dot:focus,.other-library:focus{outline:none;stroke:#203245;stroke-width:3}.tools{position:absolute;top:12px;left:12px;display:flex;gap:6px}button{font:inherit;cursor:pointer;background:white;color:#203245;border:1px solid #ced9e1;border-radius:6px;padding:6px 12px}button:focus-visible,a:focus-visible{outline:3px solid #2563eb;outline-offset:2px}aside{background:white;border:1px solid #d1dce4;border-radius:14px;padding:20px}#detail{min-height:160px;border-bottom:1px solid #e1e8ee;margin-bottom:18px}h2{font-size:18px;margin:0 0 10px}ul{list-style:none;padding:0;margin:0;max-height:44vh;overflow:auto}li button{text-align:left;display:block;width:100%;border:0;border-radius:0;padding:8px 0}small{font-size:12px}a{color:#1d4ed8}footer{margin-top:18px;font-size:13px;color:#627688}.key{color:#2563eb;font-size:20px;margin-right:6px}#map-status{min-height:24px}@media(max-width:760px){main{padding:16px}.layout{grid-template-columns:1fr}svg{height:66vh}ul{max-height:40vh}}
</style></head><body><main><h1>Libraries with holdings</h1><p>''' + escape(data['title']) + '''</p><p class="muted">''' + escape(data['date']) + f''' · {len(data['libraries'])} of {data['count']} library sigels mapped</p><div class="layout"><section><div class="map-wrap">''' + svg + '''<div class="tools"><button id="zoom-in" aria-label="Zoom in">+</button><button id="zoom-out" aria-label="Zoom out">−</button><button id="reset">Reset</button></div></div><p class="muted"><span class="key">●</span>Holding registered · <span class="muted">○ Other Libris participant</span>. One location per sigel. Drag to pan, scroll or use +/− to zoom. Select a dot or library name for details.</p><p><label><input type="checkbox" id="show-other" checked> Show other Libris participants</label></p><p id="map-status" aria-live="polite"></p></section><aside><div id="detail" aria-live="polite"><h2>Select a library</h2><p>Network and multi-site library dots represent one location. They do not identify every branch holding a copy.</p></div><h2>Libraries</h2><ul>''' + ''.join(rows) + '''</ul></aside></div><footer><p>Unmapped holding sigels: ''' + escape(missing) + '''.</p><p>''' + escape(background_status) + '''</p><p>''' + escape(status) + ''' The first recorded date is when this tracker first observed the holding, not the acquisition date.</p><p>Locations: <a href="https://biblioteksdatabasen.libris.kb.se/exportinfo/">KB library directory</a>; documented representative fallbacks (see library details). Country outlines: <a href="https://www.naturalearthdata.com/">Natural Earth</a>, public domain. The map works offline; no map tiles, API keys, or external scripts are used.</p></footer></main><script type="application/json" id="map-data">''' + encoded + '''</script><script>
'use strict';
const data = JSON.parse(document.getElementById('map-data').textContent);
const svg = document.getElementById('library-map');
const layer = document.getElementById('map-layer');
const dots = [...document.querySelectorAll('.library-dot')];
const otherDots = [...document.querySelectorAll('.other-library')];
let scale = 1, tx = 0, ty = 0, drag = null;
function render() {
  layer.setAttribute('transform', `translate(${tx} ${ty}) scale(${scale})`);
  for (const dot of dots) dot.setAttribute('r', 4.5 / scale);
  for (const dot of otherDots) dot.setAttribute('r', 3.5 / scale);
}
function point(event) {
  return new DOMPoint(event.clientX, event.clientY).matrixTransform(svg.getScreenCTM().inverse());
}
function zoom(factor, x = 380, y = 450) {
  const next = Math.min(128, Math.max(1, scale * factor));
  tx = x - (x - tx) * next / scale; ty = y - (y - ty) * next / scale; scale = next; render();
}
function select(index, other = false) {
  const lib = other ? data.other_libraries[index] : data.libraries[index];
  const panel = document.getElementById('detail');
  panel.replaceChildren();
  const heading = document.createElement('h2'); heading.textContent = lib.name; panel.append(heading);
  for (const text of [`${lib.sigel} · ${lib.city || 'Location from directory'}`, lib.note,
      ...(data.combined ? [
        `Ojämlikhetens dimensioner (${data.earlier.date}): ${lib.holds_earlier ? 'Yes' : 'No registered holding'}`,
        `Välfärd och livsvillkor (${data.current.date}): ${lib.holds_current ? 'Yes' : 'No registered holding'}`
      ] : other ? ['No registered holding for this edition in the latest observation.'] : [`First recorded holding: ${lib.first_seen || 'unknown'}`]), `${lib.latitude.toFixed(5)}, ${lib.longitude.toFixed(5)}`]) {
    const p = document.createElement('p'); p.textContent = text; panel.append(p);
  }
  for (const [label, url] of [['Libris library', lib.uri], ['Coordinate source', lib.source]]) {
    const a = document.createElement('a'); a.textContent = label; a.href = url;
    const p = document.createElement('p'); p.append(a); panel.append(p);
  }
  document.getElementById('map-status').textContent = `${lib.name} (${lib.sigel})`;
}
for (const dot of [...dots, ...otherDots]) {
  const other = dot.classList.contains('other-library');
  dot.addEventListener('click', () => select(Number(dot.dataset.index), other));
  dot.addEventListener('keydown', event => {if (event.key === 'Enter' || event.key === ' ') {event.preventDefault(); select(Number(dot.dataset.index), other);}});
}
for (const button of document.querySelectorAll('[data-library]')) {
  button.addEventListener('click', () => {
    const i = Number(button.dataset.library), dot = dots[i];
    scale = 48; tx = 380 - Number(dot.getAttribute('cx')) * scale; ty = 450 - Number(dot.getAttribute('cy')) * scale;
    render(); select(i);
  });
}
document.getElementById('show-other').addEventListener('change', event => {
  document.getElementById('other-libraries').style.display = event.target.checked ? '' : 'none';
});
document.getElementById('zoom-in').addEventListener('click', () => zoom(1.7));
document.getElementById('zoom-out').addEventListener('click', () => zoom(1 / 1.7));
document.getElementById('reset').addEventListener('click', () => {scale = 1; tx = ty = 0; render();});
svg.addEventListener('wheel', event => {event.preventDefault(); const p = point(event); zoom(event.deltaY < 0 ? 1.2 : 1 / 1.2, p.x, p.y);}, {passive: false});
svg.addEventListener('pointerdown', event => {if (event.target.closest('.library-dot,.other-library')) return; drag = point(event); svg.setPointerCapture(event.pointerId);});
svg.addEventListener('pointermove', event => {if (!drag) return; const p = point(event); tx += p.x - drag.x; ty += p.y - drag.y; drag = p; render();});
svg.addEventListener('pointerup', () => {drag = null;});
svg.addEventListener('pointercancel', () => {drag = null;});
</script></body></html>'''
    if data.get('combined'):
        html = html.replace('<h1>Libraries with holdings</h1>', '<h1>Combined library holdings</h1>')
        html = html.replace('<span class="key">●</span>Holding registered · <span class="muted">○ Other Libris participant</span>.',
            '<span style="color:#dc2626">○</span> Ojämlikhetens dimensioner · <span class="key">●</span> Välfärd och livsvillkor · red outline with blue fill: both · grey outline: other Libris participant.')
        html = html.replace('<p>Combined book holdings</p>',
            f'<p>Ojämlikhetens dimensioner: {escape(data["earlier"]["date"])} (fixed snapshot) · Välfärd och livsvillkor: {escape(data["current"]["date"])} (latest)</p>')
        html = html.replace(' The first recorded date is when this tracker first observed the holding, not the acquisition date.',
            ' Holdings are compared at the two observation dates shown above. No acquisition dates are inferred.')
    return html


def build(root, fetch=get_json, if_needed=False):
    snapshot = json.loads((root / 'libraries.json').read_text(encoding='utf-8'))
    map_path = root / 'library-map.json'
    background_path = root / 'libris-participants.json'
    background_cache = json.loads(background_path.read_text(encoding='utf-8')) if background_path.exists() else {'checked_at': 'never', 'libraries': {}}
    if if_needed and map_path.exists() and all((root / name).exists() for name in ('map.svg', 'map.html')):
        previous = json.loads(map_path.read_text(encoding='utf-8'))
        if (previous.get('map_version') == MAP_VERSION and previous.get('checked_at') == snapshot['checked_at']
                and not previous.get('cached_coordinates', True) and not previous.get('unmapped', [])
                and not previous.get('participant_cached', True) and fresh_background(background_cache)):
            print('Map already matches the latest observation; skipping directory requests')
            return previous
    cache_path = root / 'library-locations.json'
    cache = json.loads(cache_path.read_text(encoding='utf-8')) if cache_path.exists() else {'libraries': {}, 'checked_at': 'never'}
    stale = False
    try:
        locations = directory_locations(snapshot['libraries'], fetch)
        cache = {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'libraries': locations}
        atomic_write(cache_path, json.dumps(cache, ensure_ascii=False, indent=2) + '\n')
    except (ValueError, OSError) as error:
        stale = True
        print(f'::warning::Library directory unavailable; using cached coordinates: {error}', file=sys.stderr)
    overrides = json.loads((root / 'location-overrides.json').read_text(encoding='utf-8'))
    first_seen_path = root / 'first-seen.json'
    first_seen = json.loads(first_seen_path.read_text(encoding='utf-8')) if first_seen_path.exists() else {}
    for lib in snapshot['libraries']:
        first_seen.setdefault(lib['sigel'], snapshot['date'])
    atomic_write(first_seen_path, json.dumps(first_seen, ensure_ascii=False, indent=2) + '\n')
    data = map_data(snapshot, cache['libraries'], overrides, first_seen)
    data['directory_checked_at'], data['cached_coordinates'] = cache['checked_at'], stale
    background_stale = False
    if not fresh_background(background_cache):
        try:
            participants = background_directory(fetch)
            background_cache = {'checked_at': datetime.now(timezone.utc).isoformat(timespec='seconds'), 'libraries': participants}
            atomic_write(background_path, json.dumps(background_cache, ensure_ascii=False, indent=2) + '\n')
        except (ValueError, OSError) as error:
            background_stale = True
            print(f'::warning::Participant directory unavailable; using cached data: {error}', file=sys.stderr)
    add_background(data, background_cache['libraries'])
    data['participant_checked_at'], data['participant_cached'] = background_cache['checked_at'], background_stale
    countries = json.loads((root / 'map-countries.geojson').read_text(encoding='utf-8'))
    svg = svg_map(data, countries)
    atomic_write(root / 'map.svg', svg)
    atomic_write(root / 'map.html', interactive_html(data, svg, cache['checked_at'], stale))
    atomic_write(root / 'library-map.json', json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    if data['unmapped']:
        print('::warning::Unmapped library sigels: ' + ', '.join(lib['sigel'] for lib in data['unmapped']))
    print(f'{data["date"]}: mapped {len(data["libraries"])} of {data["count"]} library sigels')
    return data


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--if-needed', action='store_true', help='Reuse a complete map for the same observation')
    args = parser.parse_args()
    build(args.root, if_needed=args.if_needed)
