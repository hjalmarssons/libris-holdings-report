#!/usr/bin/env python3
"""Collect public Libris holdings and rebuild this repository's report."""
import csv
import io
import json
import math
import time
from datetime import date, datetime, timezone
from html import escape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, unquote, urlencode, urlsplit
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
ENTITY = 'https://libris.kb.se/c0qkzx1t9hs5ml77#it'


def request_json(url):
    for attempt in range(4):
        try:
            request = Request(url, headers={'Accept': 'application/ld+json',
                'User-Agent': 'libris-public-report/1.0 (+https://github.com/hjalmarssons/libris-holdings-report)'})
            with urlopen(request, timeout=45) as response:
                return json.load(response)
        except HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
        except (URLError, TimeoutError, ConnectionError):
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)


def collect(fetch=request_json):
    offset, expected, holdings, libraries = 0, None, set(), {}
    while True:
        result = fetch('https://libris.kb.se/find.jsonld?' + urlencode({
            'itemOf.@id': ENTITY, '_limit': 200, '_offset': offset}))
        total, items = result.get('totalItems'), result.get('items')
        if type(total) is not int or total < 0 or not isinstance(items, list):
            raise ValueError('Malformed Libris response')
        if expected is None:
            expected = total
        if total != expected or result.get('itemOffset') != offset or (not items and offset < total):
            raise ValueError('Incomplete or changing Libris pagination; retry later')
        for item in items:
            identity = item.get('@id')
            if (not isinstance(identity, str) or identity in holdings or
                    item.get('@type') != 'Item' or item.get('itemOf', {}).get('@id') != ENTITY):
                raise ValueError('Invalid or duplicate holding')
            holdings.add(identity)
            holders = item.get('heldBy')
            holders = holders if isinstance(holders, list) else [holders]
            if not holders:
                raise ValueError('Missing library')
            for holder in holders:
                if not isinstance(holder, dict):
                    raise ValueError('Missing library')
                parts = urlsplit(holder.get('@id', ''))
                if parts.netloc != 'libris.kb.se' or not parts.path.startswith('/library/'):
                    raise ValueError('Unexpected library identifier')
                sigel = unquote(parts.path[len('/library/'):]).rstrip('/')
                name = holder.get('name') or sigel
                if not sigel or '/' in sigel or not isinstance(name, str):
                    raise ValueError('Invalid library metadata')
                libraries[sigel] = {'sigel': sigel, 'name': name,
                    'uri': 'https://libris.kb.se/library/' + quote(sigel, safe='')}
        offset += len(items)
        if offset > total:
            raise ValueError('Libris returned excess holdings')
        if offset == total:
            return sorted(libraries.values(), key=lambda item: item['name'].casefold())


def graph(history, comparison=None):
    """Daily series plus a single dated reference observation, never a second series."""
    start, end = date.fromisoformat(history[0]['date']), date.fromisoformat(history[-1]['date'])
    maximum = max(1, max(row['count'] for row in history))
    if comparison is not None:
        if type(comparison['count']) is not int or comparison['count'] < 0:
            raise ValueError('Invalid comparison count')
        observed = date.fromisoformat(comparison['date'])
        start, end = min(start, observed), max(end, observed)
        ceiling = max(maximum, comparison['count'])
    else:
        tick = max(1, math.ceil(maximum / 5))
        ceiling = math.ceil(maximum / tick) * tick
    tick = max(1, math.ceil(ceiling / 5))
    ticks = sorted(set(range(0, ceiling + 1, tick)) | {ceiling})
    span = max(1, (end - start).days)
    x = lambda row: 450 if start == end else 70 + (date.fromisoformat(row['date']) - start).days / span * 800
    y = lambda n: 370 - n / ceiling * 275
    lines = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 440" role="img" aria-labelledby="title desc">',
        '<title id="title">Libraries with holdings over time</title>',
        '<desc id="desc">Daily unique Libris library sigels. Missing days appear as gaps. The diamond is a single dated observation of the earlier edition, not historical data.</desc>',
        '<rect width="900" height="440" fill="white"/>',
        '<g font-family="system-ui,sans-serif" font-size="14" fill="#334155">',
        '<text x="70" y="30" font-size="20" font-weight="600">Libraries with holdings</text>']
    if comparison is not None:
        label = f"◇ Ojämlikhetens dimensioner: {comparison['count']} libraries · snapshot {comparison['date']}"
        lines.append(f'<text x="70" y="58" font-size="14" fill="#956526">{escape(label)}</text>')
    for n in ticks:
        lines += [f'<path d="M70 {y(n):.1f}H870" stroke="#e2e8f0"/>',
                  f'<text x="55" y="{y(n)+5:.1f}" text-anchor="end">{n}</text>']
    for a, b in zip(history, history[1:]):
        if (date.fromisoformat(b['date']) - date.fromisoformat(a['date'])).days == 1:
            lines.append(f'<path d="M{x(a):.1f} {y(a["count"]):.1f}L{x(b):.1f} {y(b["count"]):.1f}" stroke="#2563eb" stroke-width="2.5" fill="none"/>')
    for row in history:
        lines.append(f'<circle cx="{x(row):.1f}" cy="{y(row["count"]):.1f}" r="3.5" fill="#2563eb"><title>{row["date"]}: {row["count"]} libraries</title></circle>')
    if comparison is not None:
        cx, cy = x(comparison), y(comparison['count'])
        label = escape(f"{comparison['title']}: {comparison['count']} libraries on {comparison['date']}")
        lines.append(f'<polygon class="comparison-point" points="{cx:.1f},{cy-6:.1f} {cx+6:.1f},{cy:.1f} {cx:.1f},{cy+6:.1f} {cx-6:.1f},{cy:.1f}" fill="#a67538"><title>{label}</title></polygon>')
    labels = {history[i]['date'] for i in sorted({round(n * (len(history) - 1) / 4) for n in range(5)})}
    if comparison is not None and comparison['date'] not in labels:
        # Label the reference date without colliding with nearby daily tick labels.
        labels = {d for d in labels if abs(x({'date': d}) - x(comparison)) >= 95}
        labels.add(comparison['date'])
    for d in sorted(labels):
        anchor = 'middle' if start == end else 'start' if d == start.isoformat() else 'end' if d == end.isoformat() else 'middle'
        lines.append(f'<text x="{x({"date": d}):.1f}" y="395" text-anchor="{anchor}">{d}</text>')
    lines += ['<text x="450" y="425" text-anchor="middle">Observation date (Europe/Stockholm)</text>', '</g></svg>']
    return '\n'.join(lines) + '\n'


def rebuild(root=ROOT, fetch=request_json, now=None):
    latest = json.loads((root / 'libraries.json').read_text(encoding='utf-8'))
    today = (now or datetime.now(timezone.utc)).astimezone(ZoneInfo('Europe/Stockholm')).date().isoformat()
    history = []
    with (root / 'history.csv').open(encoding='utf-8', newline='') as stream:
        for row in csv.DictReader(stream):
            date.fromisoformat(row['date'])
            count = int(row['count'])
            if count < 0 or (history and row['date'] <= history[-1]['date']):
                raise ValueError('Invalid count history')
            history.append({'date': row['date'], 'count': count})
    if not history or history[-1] != {'date': latest['date'], 'count': latest['count']}:
        raise ValueError('History and library data disagree')
    if latest['count'] != len({item['sigel'] for item in latest['libraries']}):
        raise ValueError('Invalid saved library list')
    if latest['date'] > today:
        raise ValueError('Saved observation is in the future')
    if latest['date'] != today:
        libraries = collect(fetch)
        before = {item['sigel'] for item in latest['libraries']}
        after = {item['sigel'] for item in libraries}
        latest = {key: latest[key] for key in ('title', 'isbn', 'libris_id', 'timezone')} | {
            'date': today, 'checked_at': (now or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec='seconds'),
            'count': len(libraries), 'libraries': libraries,
            'changes': {'baseline': False, 'compared_to': latest['date'],
                        'added': sorted(after - before), 'removed': sorted(before - after)}}
        history.append({'date': today, 'count': latest['count']})
    comparison_path = root / 'comparison.json'
    comparison = json.loads(comparison_path.read_text(encoding='utf-8')) if comparison_path.exists() else None
    if comparison is not None and 'libraries' in comparison:
        raise ValueError('Public comparison must contain only aggregate metadata')
    comparison_html = '' if comparison is None else (
        '<p class="note">Earlier book: <a href="https://libris.kb.se/' + escape(comparison['libris_id'], quote=True) + '">Ojämlikhetens dimensioner</a>: <strong>' + str(comparison['count']) + ' library sigels</strong>, observed ' + escape(comparison['date']) + '. A single dated snapshot; its count sets the upper scale unless the daily series exceeds it.</p>')
    changes = latest['changes']
    change_text = ('First observation: baseline established.' if changes['baseline'] else
        f"Compared with {changes['compared_to']}: added {', '.join(changes['added']) or 'none'}; removed {', '.join(changes['removed']) or 'none'}.")
    rows = ''.join(f'<tr><td><a href="https://libris.kb.se/library/{quote(item["sigel"], safe="")}">{escape(item["name"])}</a></td><td>{escape(item["sigel"])}</td></tr>' for item in latest['libraries'])
    html = (root / 'template.html').read_text(encoding='utf-8')
    for name, value in {'COUNT': latest['count'], 'DATE': escape(latest['date']),
                        'CHECKED': escape(latest['checked_at']), 'CHANGES': escape(change_text), 'ROWS': rows, 'COMPARISON': comparison_html}.items():
        html = html.replace('@@' + name + '@@', str(value))
    if '@@' in html:
        raise ValueError('Unresolved report placeholder')
    stream = io.StringIO(newline='')
    writer = csv.writer(stream, lineterminator='\n')
    writer.writerow(['date', 'count'])
    writer.writerows((row['date'], row['count']) for row in history)
    outputs = {'libraries.json': json.dumps(latest, ensure_ascii=False, indent=2) + '\n',
               'history.csv': stream.getvalue(), 'history.svg': graph(history, comparison), 'index.html': html}
    for filename, content in outputs.items():
        temporary = root / (filename + '.tmp')
        temporary.write_text(content, encoding='utf-8')
        temporary.replace(root / filename)
    print(f"{latest['date']}: {latest['count']} library sigels")


if __name__ == '__main__':
    rebuild()
