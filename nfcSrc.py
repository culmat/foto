#!/usr/bin/env python3
"""Normalise every name under src/ to Unicode NFC, before thumbsup reads it.

thumbsup slugifies the album *page* name but copies the album *directory* name
into media URLs verbatim (src/model/structure.js, then encodeURIComponent in
src/model/url.js). So the normal form of a directory in src/ leaks straight into
the published HTML, while the committed media/ tree -- written by git, which has
core.precomposeunicode=true -- is always NFC.

When the two disagree the site breaks in the least visible way possible: macOS
APFS is normalization-insensitive, so every local check passes, and only GitHub
Pages, which compares bytes, returns 404. That is exactly how Decembre22.html
and Pentecote22.html shipped with all 166 of their image references pointing at
"De" + U+0301 while the files sit under "D" + U+00E9.

Copying photos in from a phone, a camera, an external disk or Time Machine can
produce either normal form, so pinning it here -- as build.sh's first step --
is the only place the guarantee holds for every future album.

Idempotent: prints nothing and writes nothing when src/ is already NFC.
checkLinks.py, build.sh's last step, is the backstop that catches whatever this
does not.
"""

import os
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SRC = ROOT / 'src'

# NFC must leave the emoji album names byte-identical: patchHtml.py's UNLISTED
# set and the published Peru25<emoji>.html / TMR25<emoji>.html depend on them.
# Composition does not touch U+FE0F, but assert it rather than assume it.
EMOJI_ALBUMS = ('Peru25\U0001f575️', 'TMR25\U0001f575️')


def same_entry(a, b):
    """True if the two paths are the same directory entry -- which is what a
    normalization-insensitive filesystem reports for the NFD and NFC spellings
    of one name, and what tells us a plain rename would be a no-op."""
    try:
        sa, sb = os.lstat(a), os.lstat(b)
    except OSError:
        return False
    return (sa.st_dev, sa.st_ino) == (sb.st_dev, sb.st_ino)


def rename(parent, name, target):
    """Rename via a temporary name.

    On APFS a direct rename from NFD to NFC is a no-op: the destination resolves
    to the same inode, so the kernel has nothing to do and the stored name keeps
    its old bytes. Going through a third name forces the directory entry to be
    rewritten.
    """
    src, dst = parent / name, parent / target
    if os.path.lexists(dst) and not same_entry(src, dst):
        sys.exit('nfcSrc: %s and %s are two different entries -- '
                 'merge them by hand' % (src, dst))

    tmp = parent / ('.nfc-tmp-%d' % os.getpid())
    if os.path.lexists(tmp):
        sys.exit('nfcSrc: %s is in the way' % tmp)

    os.rename(src, tmp)
    os.rename(tmp, dst)
    # Escaped, because a terminal renders the two spellings identically.
    print('nfcSrc: %s -> %s  (in %s)'
          % (name.encode('ascii', 'backslashreplace').decode(),
             target.encode('ascii', 'backslashreplace').decode(),
             parent.relative_to(ROOT).as_posix()))


def main():
    for name in EMOJI_ALBUMS:
        assert unicodedata.normalize('NFC', name) == name, name

    if not SRC.is_dir():
        print('nfcSrc: no %s -- nothing to normalise' % SRC, file=sys.stderr)
        return 0

    renamed = 0
    # Bottom-up, so a directory's own entries are renamed while the path we
    # reached them by is still valid; the directory itself is renamed later,
    # when its parent comes round.
    for dirpath, dirnames, filenames in os.walk(SRC, topdown=False):
        parent = Path(dirpath)
        for name in sorted(dirnames) + sorted(filenames):
            target = unicodedata.normalize('NFC', name)
            if target != name:
                rename(parent, name, target)
                renamed += 1

    if renamed:
        print('nfcSrc: %d name(s) normalised to NFC' % renamed)
    return 0


if __name__ == '__main__':
    sys.exit(main())
