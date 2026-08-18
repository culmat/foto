#!/usr/bin/env python3
"""Re-inject our hand-authored hooks into thumbsup's generated HTML.

thumbsup rewrites every *.html in the repo root (and all of public/) on each
build, so anything we want in those pages has to be put back afterwards.
build.sh runs this as its last step.

Two independent feature sets are injected, each in its own sentinel region:

  foto-immersive  the fullscreen viewing mode -- PWA metas, immersive.css/js.
                  Every page.
  foto-map        the OSM map mode -- a header link to map.html on pages that
                  have geo data, Leaflet and map.js on map.html itself, and
                  lg-hash.js on the album pages so a map pin can deep-link to
                  one slide.

It also enforces UNLISTED (below), which is a publishing decision rather than a
markup one, but belongs here because this is the last thing to touch index.html.

Idempotent: every injection is delimited by sentinel comments which are stripped
before being re-added, so running this twice -- or after editing the constants
below -- converges, and an already-correct file is not rewritten at all, keeping
mtimes and `git status` clean.

python3 rather than sed: no BSD-vs-GNU `-i ''` split (this repo is used from
both macOS and Linux, cf. review.sh), and no shell word-splitting around the
emoji filenames Peru25*.html / TMR25*.html.
"""

import hashlib
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import quote, unquote

ROOT = Path(__file__).resolve().parent
MARK = 'foto-immersive'
MAP_MARK = 'foto-map'

# Albums that are reachable by direct URL but never listed. They predate this
# script: their pages exist and are linked from nowhere, which used to happen by
# itself because their originals were not in src/ and thumbsup therefore never
# wrote a card for them. Now that every original is back in src/, a build *does*
# write those cards, so the omission has to be re-applied on purpose -- here,
# and in exif2geojson.py, which skips them so they never reach the public map.
# Escapes rather than literal emoji: this string is load-bearing and must not be
# at the mercy of an editor's normalisation.
UNLISTED = {'Peru25\U0001f575\ufe0f', 'TMR25\U0001f575\ufe0f'}

# Hand-authored assets live outside public/, which thumbsup re-copies from the
# Docker image on every build.
CSS = ['assets/immersive.css']
JS = ['assets/immersive.js']

# map.html only -- far too heavy to put on all 37 album pages.
MAP_CSS = ['assets/leaflet/leaflet.css',
           'assets/leaflet/MarkerCluster.css',
           'assets/leaflet/MarkerCluster.Default.css',
           'assets/map.css']
MAP_JS = ['assets/leaflet/leaflet.js',
          'assets/leaflet/leaflet.markercluster.js',
          'assets/map.js']

# The one bit of map styling the other pages need: the header link itself.
LINK_CSS = ['assets/map-link.css']

# Album pages only, and deliberately not cache-stamped: it comes from the
# thumbsup image, so its bytes are versioned by the build, not by us.
# lightGallery 1.x self-registers modules and lg-hash defaults to hash:true, so
# loading the file is the whole integration -- the inline init needs no change.
HASH_JS = 'public/lightgallery/js/lg-hash.js'

# initial-scale=1 is required or viewport-fit=cover is unreliable on iOS.
# viewport-fit=cover is what makes env(safe-area-inset-*) return non-zero.
# user-scalable=no is kept: we implement pinch ourselves in immersive.js and do
# not want Android's native page-zoom competing with it.
VIEWPORT = ('<meta name="viewport" content="width=device-width, initial-scale=1, '
            'user-scalable=no, viewport-fit=cover" />')

# apple-mobile-web-app-capable + black-translucent is the real fallback for
# iPhones without Element.requestFullscreen (before iOS 17.4): Add to Home
# Screen then launches with no Safari chrome at all. immersive.css pads
# #container and .lg-toolbar by env(safe-area-inset-top) to account for it.
PWA = [
    '<meta name="apple-mobile-web-app-capable" content="yes" />',
    '<meta name="mobile-web-app-capable" content="yes" />',
    '<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />',
    '<meta name="theme-color" content="#000000" />',
    '<meta name="color-scheme" content="dark" />',
]

RE_VIEWPORT = re.compile(r'<meta\s+name=["\']viewport["\'][^>]*>', re.I)
RE_HEAD_END = re.compile(r'</head\s*>', re.I)
RE_BODY_END = re.compile(r'</body\s*>', re.I)

# The gallery title comes from thumbsUp_config.json, so match it loosely.
# Verified to occur exactly once in every generated page.
RE_HEADER = re.compile(r'<h1><a href="index\.html">[^<]*</a></h1>')

# An album card in index.html's #albums. The background-image style is what
# distinguishes it from the breadcrumb and header links.
RE_ALBUM_CARD = re.compile(
    r'<a href="([^"]+)"\s+style="background-image[^"]*">.*?</a>', re.S)


def region(mark, slot):
    return re.compile(r'[ \t]*<!-- %s:%s -->.*?<!-- /%s:%s -->\n?'
                      % (mark, slot, mark, slot), re.S)


STRIP = [region(m, s)
         for m in (MARK, MAP_MARK)
         for s in ('head', 'body', 'nav')]

_digests = {}


def stamped(rel):
    """assets/x.css -> assets/x.css?v=<8 hex>, so neither GitHub Pages' cache
    nor the phone's Safari cache can serve a stale override while iterating."""
    if rel not in _digests:
        _digests[rel] = hashlib.sha1((ROOT / rel).read_bytes()).hexdigest()[:8]
    return '%s?v=%s' % (rel, _digests[rel])


def nfc(name):
    return unicodedata.normalize('NFC', name)


def geo_stems():
    """Page stems that have a committed geo/<stem>.geojson."""
    geo = ROOT / 'geo'
    if not geo.is_dir():
        return set()
    return {nfc(p.stem) for p in geo.glob('*.geojson')}


def head_block(page, linked):
    # The first line inherits whatever indentation already precedes </head>, so
    # it carries none of its own; the last entry restores the two spaces that
    # closing tag sat on.
    lines = ['<!-- %s:head -->' % MARK]
    lines += ['      ' + meta for meta in PWA]
    lines += ['      <link rel="stylesheet" href="%s" />' % stamped(c) for c in CSS]
    lines += ['      <!-- /%s:head -->' % MARK]

    sheets = MAP_CSS if page == 'map.html' else (LINK_CSS if linked else [])
    if sheets:
        lines += ['      <!-- %s:head -->' % MAP_MARK]
        lines += ['      <link rel="stylesheet" href="%s" />' % stamped(c)
                  for c in sheets]
        lines += ['      <!-- /%s:head -->' % MAP_MARK]

    lines += ['  ']
    return '\n'.join(lines)


def body_block(page):
    lines = ['<!-- %s:body -->' % MARK]
    lines += ['    <script src="%s"></script>' % stamped(j) for j in JS]
    lines += ['    <!-- /%s:body -->' % MARK]

    scripts = MAP_JS if page == 'map.html' else [HASH_JS]
    lines += ['    <!-- %s:body -->' % MAP_MARK]
    lines += ['    <script src="%s"></script>'
              % (stamped(s) if s.startswith('assets/') else s) for s in scripts]
    lines += ['    <!-- /%s:body -->' % MAP_MARK]

    lines += ['  ']
    return '\n'.join(lines)


def nav_block(page, stems):
    """The header link into map mode, or None where there is nothing to link to."""
    if page == 'map.html':
        return None                       # already there
    if page == 'index.html':
        target = 'map.html' if stems else None
    else:
        stem = nfc(page[:-len('.html')])
        target = 'map.html?album=' + quote(stem, safe='') if stem in stems else None
    if target is None:
        return None

    return '\n'.join([
        '',
        '        <!-- %s:nav -->' % MAP_MARK,
        '        <a class="map-link" href="%s">Map</a>' % target,
        '        <!-- /%s:nav -->' % MAP_MARK,
    ])


def strip_unlisted(text, dropped):
    """Remove index.html cards for UNLISTED albums.

    Silently -- no placeholder comment, since naming them in the published
    markup would give away exactly what the omission is protecting.
    """
    def drop(match):
        if nfc(Path(unquote(match.group(1))).stem) in UNLISTED:
            dropped.append(match.group(1))
            return ''
        return match.group(0)

    return RE_ALBUM_CARD.sub(drop, text)


def patch(text, page, stems, dropped):
    """Return the patched page, or None if this file is not one of ours."""
    if not RE_VIEWPORT.search(text):
        return None

    # Replace the theme's meta wholesale, whatever it happens to say today, so a
    # thumbsup upgrade that rewords it cannot silently skip us.
    # lambda replacements throughout: a backslash in VIEWPORT or in an asset
    # path must never be read as a \1 group reference.
    text = RE_VIEWPORT.sub(lambda m: VIEWPORT, text, count=1)

    # Strip every region we own, including ones this page no longer qualifies
    # for, so a page that loses its geo data also loses its map link.
    for rx in STRIP:
        text = rx.sub('', text)

    if page == 'index.html':
        text = strip_unlisted(text, dropped)

    nav = nav_block(page, stems)
    head, body = head_block(page, nav is not None), body_block(page)
    text = RE_HEAD_END.sub(lambda m: head + m.group(0), text, count=1)
    text = RE_BODY_END.sub(lambda m: body + m.group(0), text, count=1)

    if nav:
        text = RE_HEADER.sub(lambda m: m.group(0) + nav, text, count=1)

    return text


def main():
    required = list(CSS) + list(JS)
    if (ROOT / 'map.html').is_file():
        required += MAP_CSS + MAP_JS + LINK_CSS
    for rel in required:
        if not (ROOT / rel).is_file():
            sys.exit('patchHtml: missing %s' % rel)

    pages = sorted(p for p in ROOT.glob('*.html') if p.is_file())
    if not pages:
        sys.exit('patchHtml: no *.html in %s -- did thumbsup run?' % ROOT)

    stems = geo_stems()
    dropped = []
    written = skipped = linked = 0

    for page in pages:
        name = nfc(page.name)
        before = page.read_text(encoding='utf-8')
        after = patch(before, name, stems, dropped)
        if after is None:
            print('patchHtml: skip (no viewport meta): %s' % page.name)
            skipped += 1
            continue
        if nav_block(name, stems):
            linked += 1
        if after != before:
            page.write_text(after, encoding='utf-8')
            written += 1

    print('patchHtml: %d written, %d already current, %d skipped'
          % (written, len(pages) - written - skipped, skipped))
    print('patchHtml: map link on %d page(s), %d unlisted card(s) removed'
          % (linked, len(dropped)))


if __name__ == '__main__':
    main()
