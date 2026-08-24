#!/usr/bin/env python3
"""Extract per-photo GPS from the src/ originals into geo/<PageStem>.geojson.

thumbsup strips EXIF while resizing -- nothing under media/ carries coordinates
-- and src/ is gitignored, so the coordinates have to be committed as a sidecar
if the published site is ever to show a map.

One FeatureCollection per album is what makes that portable: run this wherever
the originals happen to live, copy the resulting .geojson into geo/, re-run to
refresh the index, commit. Nothing else is hand-edited, so two machines holding
different halves of the archive can each contribute without conflicting.

geo/index.json is *derived*. Never hand-edit it; resolve a merge conflict by
re-running this script.

python3 rather than bash for the same reasons patchHtml.py gives (emoji album
names, macOS/Linux tool differences), plus one this file cannot avoid: album
directories under src/ are NFD on macOS while media/ and the generated HTML are
NFC, so every name has to be normalised before it can be used as a path.

Incremental: reading EXIF off all 1220 originals costs ~23s and almost none of
it is ever needed twice, so results are cached in geo/.cache.json keyed by path
+ mtime + size -- the same thing thumbsup caches in thumbsup.db, whose timestamp
column is likewise the source file's mtime. Caching a *negative* result matters
as much as a positive one: two thirds of the archive has no GPS at all, and
re-reading those files was most of the wasted time. Whatever does miss the cache
goes through a single batched exiftool call rather than one per album.
"""

import json
import os
import re
import subprocess
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

# Single source of truth for which albums stay off the public listings; see the
# note there. Importing patchHtml is side-effect-free (it guards main()).
from patchHtml import UNLISTED

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'src'
GEO = ROOT / 'geo'
CACHE = GEO / '.cache.json'

# Bump to invalidate every cached entry at once -- required whenever TAGS or the
# parsing below changes, or a fix would be masked by stale results.
CACHE_VERSION = 1

# <li data-src="media/large/<AlbumDir>/<file>.jpg" ...> -- the album pages' own
# markup is the only authority on two things we cannot otherwise derive: which
# .html file an album directory became, and what slide index each photo has.
# Deliberately not cached: both change when thumbsup reorders an album.
RE_MEDIA = re.compile(r'data-src="media/large/([^/"]+)/([^"]+)"')

# Fields we ask exiftool for. -n gives decimal degrees *with the hemisphere sign
# already applied* (verified: Peru comes back -5.94, -77.93), so GPSLatitudeRef
# and GPSLongitudeRef are not needed. GPSAltitudeRef still is: it is a separate
# below-sea-level flag that -n does not fold into the value.
TAGS = ['-GPSLatitude', '-GPSLongitude', '-GPSAltitude', '-GPSAltitudeRef',
        '-DateTimeOriginal', '-OffsetTimeOriginal']


def nfc(name):
    """Normalise to NFC, the form everything committed here uses.

    nfcSrc.py pins src/ to NFC before each build and git commits media/ as NFC
    (core.precomposeunicode=true). The HTML follows from src/, because thumbsup
    percent-encodes the raw album directory name into media URLs -- so when src/
    drifts to NFD the generated HTML does too, and the album 404s on GitHub
    Pages while resolving fine on macOS. nfcSrc.py and checkLinks.py exist to
    stop that; normalising here keeps this script right either way.
    """
    return unicodedata.normalize('NFC', name)


def slug(name):
    """Approximate thumbsup's album -> page-name transform: fold diacritics.

    An approximation, not a reimplementation: thumbsup runs slugify with a
    precomposed charmap, which also turns '&' into 'and', drops '.', maps spaces
    to '-' and transliterates 'ß' -> 'ss' and 'ø' -> 'o'. None of that is done
    here. It agrees on every album currently in src/ -- Decembre22.html for
    'Décembre22', 'Peru25<emoji>.html' keeping its emoji -- and is only the
    fallback for an album that has no page yet; for everything else the page is
    found by scanning the HTML, which is exact.
    """
    decomposed = unicodedata.normalize('NFKD', nfc(name))
    return ''.join(c for c in decomposed if not unicodedata.combining(c))


def page_index():
    """{album dir (NFC): (page filename, {photo filename: slide index})}.

    Built by reading the generated pages rather than guessing at slugs, so
    accented and emoji album names resolve exactly.
    """
    index = {}
    for page in sorted(ROOT.glob('*.html')):
        order = {}
        album = None
        for match in RE_MEDIA.finditer(page.read_text(encoding='utf-8')):
            album = nfc(unquote(match.group(1)))
            name = nfc(unquote(match.group(2)))
            order.setdefault(name, len(order))
        if album is not None:
            index[album] = (page.name, order)
    return index


# --- the cache -----------------------------------------------------------

def cache_key(path):
    """Repo-relative where possible, so the cache survives moving the checkout;
    absolute for originals kept outside it (a USB disk, the other machine)."""
    resolved = path.resolve()
    try:
        return resolved.relative_to(ROOT).as_posix()
    except ValueError:
        return resolved.as_posix()


def stamp_of(path):
    """(mtime in ms, size) -- thumbsup.db uses the same millisecond convention."""
    info = path.stat()
    return int(info.st_mtime * 1000), info.st_size


def load_cache():
    if not CACHE.is_file():
        return {}
    try:
        data = json.loads(CACHE.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return {}                     # corrupt or truncated: just rebuild it
    if data.get('version') != CACHE_VERSION:
        return {}
    files = data.get('files')
    return files if isinstance(files, dict) else {}


def save_cache(files):
    payload = json.dumps({'version': CACHE_VERSION, 'files': files},
                         ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'))
    write_if_changed(CACHE, payload + '\n')


# --- exiftool ------------------------------------------------------------

def exif_scan(paths):
    """{path string: exiftool row} for the geotagged files among `paths`.

    One call for the whole run, with the file list on stdin via `-@ -`: 34
    invocations cost 23s against 14s for one, and the list is usually empty.
    -if keeps the output to geotagged files only; anything absent from the
    result simply has no GPS, which the caller caches as a negative.
    """
    if not paths:
        return {}

    cmd = ['exiftool', '-json', '-n', '-q', '-if', '$GPSLatitude']
    cmd += TAGS + ['-@', '-']
    try:
        proc = subprocess.run(cmd, input='\n'.join(paths),
                              capture_output=True, text=True)
    except FileNotFoundError:
        sys.exit('exif2geojson: exiftool not found on PATH')

    out = proc.stdout.strip()
    if not out:
        # exit 2 is exiftool for "no file satisfied -if", i.e. nothing in this
        # batch has GPS. Common, and not a failure.
        if proc.returncode not in (0, 1, 2):
            sys.exit('exif2geojson: exiftool failed (%d): %s'
                     % (proc.returncode, proc.stderr.strip()))
        return {}

    rows = {}
    for row in json.loads(out):
        rows[row.get('SourceFile', '')] = row
    # exiftool echoes SourceFile back verbatim, but match normalisation-
    # insensitively as well so an NFD path can never silently miss.
    folded = {nfc(k): v for k, v in rows.items()}
    return {p: rows.get(p) or folded.get(nfc(p)) for p in paths
            if p in rows or nfc(p) in folded}


def timestamp(row):
    """'2025:10:12 12:50:22' + '+02:00' -> '2025-10-12T12:50:22+02:00'."""
    raw = row.get('DateTimeOriginal')
    if not isinstance(raw, str) or raw.startswith('0000'):
        return None
    try:
        date, time = raw.split(' ', 1)
    except ValueError:
        return None
    stamp = '%sT%s' % (date.replace(':', '-'), time)
    offset = row.get('OffsetTimeOriginal')
    return stamp + offset if isinstance(offset, str) and offset else stamp


def altitude(row):
    alt = row.get('GPSAltitude')
    if not isinstance(alt, (int, float)):
        return None
    # Ref 1 means below sea level and is stored separately from the magnitude.
    if row.get('GPSAltitudeRef') in (1, '1') and alt > 0:
        alt = -alt
    return round(alt, 1)


def gps_of(row):
    """An exiftool row reduced to the only fields worth caching, already
    rounded so that a cached run and a fresh one emit identical JSON."""
    if row is None:
        return None
    lat, lon = row.get('GPSLatitude'), row.get('GPSLongitude')
    if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
        return None
    return {'lat': round(lat, 7), 'lon': round(lon, 7),
            'alt': altitude(row), 'date': timestamp(row)}


# --- output --------------------------------------------------------------

def feature(name, gps, album, page, order):
    # RFC 7946 order: [lon, lat, alt]. Leaflet wants the opposite; map.js flips.
    coords = [gps['lon'], gps['lat']]
    if gps.get('alt') is not None:
        coords.append(gps['alt'])

    props = {
        'album': album,
        'page': page,
        'file': name,
        'thumb': 'media/thumbs/%s/%s' % (album, name),
        'small': 'media/small/%s/%s' % (album, name),
        'large': 'media/large/%s/%s' % (album, name),
    }
    if gps.get('date'):
        props['date'] = gps['date']
    if name in order:
        props['slide'] = order[name]

    return {'type': 'Feature',
            'geometry': {'type': 'Point', 'coordinates': coords},
            'properties': props}


def write_if_changed(path, text):
    if path.is_file() and path.read_text(encoding='utf-8') == text:
        return False
    path.write_text(text, encoding='utf-8')
    return True


def dump(obj):
    # ensure_ascii=False keeps accents and emoji legible in diffs.
    return json.dumps(obj, ensure_ascii=False, indent=1) + '\n'


def build_album(album, located, index):
    """Write (or remove) one album's geojson from already-resolved GPS.

    `located` is [(filename, gps dict)] for the geotagged photos only.
    """
    page, order = index.get(album, (slug(album) + '.html', {}))
    features = [feature(name, gps, album, page, order) for name, gps in located]
    # Chronological, so a track polyline joins them in the order they were taken.
    features.sort(key=lambda f: (f['properties'].get('date') or '',
                                 f['properties']['file']))

    target = GEO / (Path(page).stem + '.geojson')
    if not features:
        # Only ever prune an album we actually just looked at -- never one whose
        # originals live on another machine, or merging would destroy itself.
        if target.is_file():
            target.unlink()
            return 'no GPS (removed stale %s)' % target.name
        return 'no GPS'

    collection = {'type': 'FeatureCollection',
                  'album': album, 'page': page, 'mediaDir': album,
                  'features': features}
    changed = write_if_changed(target, dump(collection))
    return '%d photo(s)%s' % (len(features), '' if changed else ' (unchanged)')


def build_index():
    """Rebuild geo/index.json from whatever geojson files are present."""
    entries = []
    for path in sorted(GEO.glob('*.geojson')):
        data = json.loads(path.read_text(encoding='utf-8'))
        features = data.get('features') or []
        if not features:
            continue
        lons = [f['geometry']['coordinates'][0] for f in features]
        lats = [f['geometry']['coordinates'][1] for f in features]
        dates = sorted(f['properties']['date'] for f in features
                       if f['properties'].get('date'))
        entries.append({
            'album': data.get('album', path.stem),
            'page': data.get('page', path.stem + '.html'),
            'file': 'geo/' + path.name,
            'count': len(features),
            'bbox': [round(min(lons), 6), round(min(lats), 6),
                     round(max(lons), 6), round(max(lats), 6)],
            'start': dates[0][:10] if dates else None,
            'end': dates[-1][:10] if dates else None,
        })
    entries.sort(key=lambda e: (e['start'] or '', e['album']), reverse=True)
    write_if_changed(GEO / 'index.json', dump(entries))
    return entries


def candidates(album_dir):
    """Every regular file in an album. Anything exiftool cannot read simply
    yields no GPS and is cached as such, so there is no extension list to
    keep in step with the archive."""
    return sorted((p for p in album_dir.iterdir()
                   if p.is_file() and not p.name.startswith('.')),
                  key=lambda p: p.name)


def main():
    flags = [a for a in sys.argv[1:] if a.startswith('--')]
    targets = [a for a in sys.argv[1:] if not a.startswith('--')]
    unknown = [f for f in flags if f != '--no-cache']
    if unknown:
        sys.exit('exif2geojson: unknown option: %s\n'
                 'usage: exif2geojson.py [--no-cache] [album-dir ...]'
                 % ', '.join(unknown))

    GEO.mkdir(exist_ok=True)

    if targets:
        albums = [Path(a) for a in targets]
        missing = [a for a in albums if not a.is_dir()]
        if missing:
            sys.exit('exif2geojson: not a directory: %s'
                     % ', '.join(str(m) for m in missing))
    elif SRC.is_dir():
        albums = sorted(p for p in SRC.iterdir() if p.is_dir())
    else:
        albums = []
        print('exif2geojson: no src/ here -- refreshing the index only')

    index = page_index()
    # Always read the cache, even under --no-cache: entries for originals this
    # run cannot see (another album, another machine's disk) have to survive the
    # rewrite below, or --no-cache on one album would discard all the rest.
    cache = load_cache()
    use_hits = '--no-cache' not in flags
    fresh = {}
    plan = []
    misses = []

    # 1. Stat everything and split into cache hits and misses. ~0.09s for the
    #    whole archive, against ~23s to re-read it all through exiftool.
    for album_dir in albums:
        album = nfc(album_dir.name)
        if album in UNLISTED:
            plan.append((album_dir, album, None))
            continue
        files = []
        for path in candidates(album_dir):
            key = cache_key(path)
            mtime, size = stamp_of(path)
            hit = cache.get(key) if use_hits else None
            if isinstance(hit, dict) and hit.get('mtime') == mtime \
                    and hit.get('size') == size:
                files.append((path, key, mtime, size, hit.get('gps'), True))
            else:
                files.append((path, key, mtime, size, None, False))
                misses.append(str(path))
        plan.append((album_dir, album, files))

    # 2. One exiftool call for everything that missed -- usually none at all.
    scanned = exif_scan(misses)

    # 3. Resolve, remember, and write each album.
    for album_dir, album, files in plan:
        if files is None:
            print('exif2geojson: %-26s %s' % (album, 'skip (unlisted)'))
            continue
        located = []
        rescanned = 0
        for path, key, mtime, size, gps, hit in files:
            if not hit:
                rescanned += 1
                gps = gps_of(scanned.get(str(path)))
            fresh[key] = {'mtime': mtime, 'size': size, 'gps': gps}
            if gps:
                located.append((nfc(path.name), gps))
        status = build_album(album, located, index)
        if rescanned:
            status += ', %d scanned' % rescanned
        print('exif2geojson: %-26s %s' % (album, status))

    # 4. Persist. Entries are dropped only for directories this run actually
    #    walked, so originals held on another machine keep their cache -- the
    #    same rule that stops build_album deleting their sidecar.
    walked = tuple(cache_key(d) + '/' for d, _, files in plan if files is not None)
    kept = {k: v for k, v in cache.items()
            if k not in fresh and not k.startswith(walked)}
    kept.update(fresh)
    save_cache(kept)

    entries = build_index()
    print('exif2geojson: %d album(s), %d photo(s) on the map '
          '(%d file(s): %d cached, %d scanned)'
          % (len(entries), sum(e['count'] for e in entries),
             len(fresh), len(fresh) - len(misses), len(misses)))


if __name__ == '__main__':
    main()
