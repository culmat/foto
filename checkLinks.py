#!/usr/bin/env python3
"""Assert that every local target the generated site references really exists.

Byte-exactly. That qualifier is the entire point of this script.

macOS APFS is both case-insensitive and *normalization*-insensitive: a lookup of
"De" + U+0301 + "cembre22" happily returns the directory stored as
"D" + U+00E9 + "cembre22". GitHub Pages compares bytes. So a reference can work
on this laptop, in serve.sh, in every browser here -- and 404 for everyone else,
with nothing to see locally. That is how the Decembre22 / Pentecote22 albums
shipped with every image broken: thumbsup embeds the *raw* album directory name
in media URLs (src/model/structure.js), src/ had picked up NFD names, and the
committed media/ tree is NFC.

Which is why this script must never use Path.exists() / os.stat(): on this
filesystem they return True for exactly the paths that are broken in production.
It instead lists each directory with os.scandir() -- which reports names as
actually stored -- and compares every path segment against that listing. Case
mismatches fall out of the same check for free.

Run as build.sh's last step, after patchHtml.py, so it sees the final markup.

What is checked:
  root *.html   every media/ assets/ public/ geo/ path, percent-decoded, plus
                href="...html" page links
  geo/index.json    its "file" and "page" values
  geo/*.geojson     each feature's "thumb" / "small" / "large" / "page"
                    (raw UTF-8 there, not percent-encoded -- map.js hands them
                    straight to the browser)
"""

import json
import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent

# Prefix-driven rather than attribute-driven: these four directory names are
# unambiguous, so we do not have to keep a list of the attributes thumbsup and
# its lightGallery theme happen to put URLs in (src, href, data-src,
# data-download-url, CSS url(), ...) in sync with an upgrade.
#
# Parentheses are deliberately *inside* the character class: encodeURIComponent
# leaves them literal, and this gallery really does contain
# "20230601_175727(0).jpg" and "20230324_184829 (copy).jpg". Excluding them to
# terminate a CSS url() instead reported those as broken. balanced() below
# handles url() the right way round. Whitespace stays excluded, which is safe
# because a space in a filename always arrives as %20.
RE_ASSET = re.compile(r'''(?:media|assets|public|geo)/[^"'<>\s\\]*''')

# Local page links. Excludes ':' so scheme-bearing URLs cannot match.
RE_PAGE = re.compile(r'''href=["']([^"'?#:]+\.html)["']''')

# Feature properties in geo/*.geojson that name a file we ship.
GEO_KEYS = ('thumb', 'small', 'large', 'page')

_listings = {}


def listing(dirpath):
    """Names as actually stored in dirpath, or None if it is not a directory.

    os.scandir does no normalisation and no case folding -- unlike a stat() of a
    path we constructed -- so this set is the ground truth about what a byte-
    exact HTTP request can resolve.
    """
    key = str(dirpath)
    if key not in _listings:
        try:
            _listings[key] = {entry.name for entry in os.scandir(dirpath)}
        except OSError:
            _listings[key] = None
    return _listings[key]


def resolve(rel):
    """(None) if rel exists byte-exactly under ROOT, else (parent, segment)
    naming the first segment that does not."""
    parts = [p for p in rel.split('/') if p not in ('', '.')]
    if not parts:
        return ('', rel)
    current = ROOT
    for i, part in enumerate(parts):
        names = listing(current)
        if names is None or part not in names:
            return ('/'.join(parts[:i]), part)
        current = current / part
    return None


def visible(name):
    r"""Décembre22 -> D\xe9cembre22, and the NFD form -> Décembre22.

    A terminal renders both spellings identically, which is what made this bug
    so quiet. Escaping is the only way a diagnostic here can be read.
    """
    return name.encode('ascii', 'backslashreplace').decode('ascii')


def suggest(parent, missing):
    """Real names in parent that differ from `missing` only by normalisation or
    case -- i.e. the ones this filesystem would have silently accepted."""
    names = listing(ROOT / parent) if parent else listing(ROOT)
    if not names:
        return []
    def fold(name):
        return unicodedata.normalize('NFC', name).casefold()
    return sorted(n for n in names if fold(n) == fold(missing))


def balanced(url):
    """Drop the ')' that closes an unquoted CSS url(), but keep the ones that are
    part of a filename. A trailing ')' is punctuation only if it is unmatched."""
    while url.endswith(')') and url.count(')') > url.count('('):
        url = url[:-1]
    return url


def urls_from_html(page):
    text = page.read_text(encoding='utf-8')
    for match in RE_ASSET.finditer(text):
        yield unquote(balanced(match.group(0)))
    for match in RE_PAGE.finditer(text):
        yield unquote(match.group(1))


def urls_from_geo():
    index = ROOT / 'geo' / 'index.json'
    if index.is_file():
        for entry in json.loads(index.read_text(encoding='utf-8')):
            for key in ('file', 'page'):
                if entry.get(key):
                    yield index.relative_to(ROOT).as_posix(), entry[key]

    for sidecar in sorted((ROOT / 'geo').glob('*.geojson')):
        data = json.loads(sidecar.read_text(encoding='utf-8'))
        for feature in data.get('features', []):
            props = feature.get('properties', {})
            for key in GEO_KEYS:
                if props.get(key):
                    yield sidecar.relative_to(ROOT).as_posix(), props[key]


def references():
    """(referrer, url) for everything we know how to check."""
    for page in sorted(ROOT.glob('*.html')):
        if page.is_file():
            for url in urls_from_html(page):
                yield page.name, url
    if (ROOT / 'geo').is_dir():
        yield from urls_from_geo()


def main():
    # Keyed by the broken target rather than by reference, so the two renamed
    # album directories read as a handful of problems instead of 166.
    broken = {}
    checked = 0

    for referrer, url in references():
        url = url.split('?')[0].split('#')[0]
        if not url:
            continue
        checked += 1
        miss = resolve(url)
        if miss is None:
            continue
        entry = broken.setdefault(miss, {'count': 0, 'referrers': set(),
                                         'example': url})
        entry['count'] += 1
        entry['referrers'].add(referrer)

    if not broken:
        print('checkLinks: %d reference(s) OK' % checked)
        return 0

    refs = sum(e['count'] for e in broken.values())
    print('checkLinks: %d missing target(s), %d of %d reference(s) broken'
          % (len(broken), refs, checked), file=sys.stderr)
    for (parent, segment), entry in sorted(broken.items()):
        where = '%s/%s' % (parent, visible(segment)) if parent else visible(segment)
        print('\n  %s  -- no such entry' % where, file=sys.stderr)
        for candidate in suggest(parent, segment):
            print('    on disk:  %s   (differs only by unicode form or case)'
                  % visible(candidate), file=sys.stderr)
        print('    %d reference(s) from %s'
              % (entry['count'], ', '.join(sorted(entry['referrers'])[:4])),
              file=sys.stderr)
        print('    e.g. %s' % visible(entry['example']), file=sys.stderr)
    print('\ncheckLinks: these resolve on macOS but 404 on GitHub Pages.',
          file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())
