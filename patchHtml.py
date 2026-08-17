#!/usr/bin/env python3
"""Re-inject the immersive-viewer hooks into thumbsup's generated HTML.

thumbsup rewrites every *.html in the repo root (and all of public/) on each
build, so anything we want in those pages has to be put back afterwards.
build.sh runs this as its last step.

Idempotent: the injection is delimited by sentinel comments which are stripped
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
from pathlib import Path

ROOT = Path(__file__).resolve().parent
MARK = 'foto-immersive'

# Hand-authored assets live outside public/, which thumbsup re-copies from the
# Docker image on every build.
CSS = ['assets/immersive.css']
JS = ['assets/immersive.js']

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
RE_OLD_HEAD = re.compile(r'[ \t]*<!-- %s:head -->.*?<!-- /%s:head -->\n?' % (MARK, MARK), re.S)
RE_OLD_BODY = re.compile(r'[ \t]*<!-- %s:body -->.*?<!-- /%s:body -->\n?' % (MARK, MARK), re.S)


def stamped(rel):
    """assets/x.css -> assets/x.css?v=<8 hex>, so neither GitHub Pages' cache
    nor the phone's Safari cache can serve a stale override while iterating."""
    digest = hashlib.sha1((ROOT / rel).read_bytes()).hexdigest()[:8]
    return '%s?v=%s' % (rel, digest)


def blocks():
    # The first line inherits whatever indentation already precedes </head> or
    # </body>, so it carries none of its own; the last entry restores the two
    # spaces that closing tag sat on.
    head = ['<!-- %s:head -->' % MARK]
    head += ['      ' + meta for meta in PWA]
    head += ['      <link rel="stylesheet" href="%s" />' % stamped(c) for c in CSS]
    head += ['      <!-- /%s:head -->' % MARK, '  ']

    body = ['<!-- %s:body -->' % MARK]
    body += ['    <script src="%s"></script>' % stamped(j) for j in JS]
    body += ['    <!-- /%s:body -->' % MARK, '  ']

    return '\n'.join(head), '\n'.join(body)


def patch(text, head, body):
    """Return the patched page, or None if this file is not one of ours."""
    if not RE_VIEWPORT.search(text):
        return None

    # Replace the theme's meta wholesale, whatever it happens to say today, so a
    # thumbsup upgrade that rewords it cannot silently skip us.
    # lambda replacements throughout: a backslash in VIEWPORT or in an asset
    # path must never be read as a \1 group reference.
    text = RE_VIEWPORT.sub(lambda m: VIEWPORT, text, count=1)
    text = RE_OLD_HEAD.sub('', text)
    text = RE_OLD_BODY.sub('', text)
    text = RE_HEAD_END.sub(lambda m: head + m.group(0), text, count=1)
    text = RE_BODY_END.sub(lambda m: body + m.group(0), text, count=1)
    return text


def main():
    for rel in CSS + JS:
        if not (ROOT / rel).is_file():
            sys.exit('patchHtml: missing %s' % rel)

    pages = sorted(p for p in ROOT.glob('*.html') if p.is_file())
    if not pages:
        sys.exit('patchHtml: no *.html in %s -- did thumbsup run?' % ROOT)

    head, body = blocks()
    written = skipped = 0

    for page in pages:
        before = page.read_text(encoding='utf-8')
        after = patch(before, head, body)
        if after is None:
            print('patchHtml: skip (no viewport meta): %s' % page.name)
            skipped += 1
        elif after != before:
            page.write_text(after, encoding='utf-8')
            written += 1

    print('patchHtml: %d written, %d already current, %d skipped'
          % (written, len(pages) - written - skipped, skipped))


if __name__ == '__main__':
    main()
