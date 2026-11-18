"""Writing a file so that it is replaced whole or not at all.

Almost every file printit keeps was written as

    with open(path, "w") as f:
        f.write(make_the_contents())

and Python empties the file when it opens it -- *before* the contents
are worked out. If that work raises, or the machine stops half way, the
file is left empty or half written. For a roster, a seating chart or
`availability.toml` that is a course's state gone (RV-10, 2026-11-16;
`availability.set_values` raises on purpose, after the emptying).

`atomic_write` takes the finished text, writes it to a temporary file
beside the target, and renames that over the target. A rename within
one folder is all-or-nothing, so a reader sees the old file or the new
one and never anything between.

The platform has its own copy of this, in `checkit.utils`. Two copies
on purpose: printit is installed against a released wheel of the
platform, and a helper only the newest platform has would break every
install pinned to an older one.
"""

import os
import tempfile
import time

#: What a TOML basic string cannot hold as itself, and how to write it.
_TOML_ESCAPES = {"\\": "\\\\", '"': '\\"', "\n": "\\n", "\r": "\\r",
                 "\t": "\\t", "\b": "\\b", "\f": "\\f"}


def toml_string(value):
    """`value` as a TOML basic string, quotes included.

    The one copy. There were nine (`_quote` in manifest, printjob, form
    and seating; `quote` in gradebook and roster; `course._escape`; two
    in `availability`), and none escaped a newline -- so a title pasted
    with a line break in it wrote a file that could not be read back,
    and one of them did not escape a backslash either (review,
    2026-11-16). Any other control character is written as \\uXXXX,
    which is the only form TOML accepts for it.
    """
    out = []
    for ch in str(value):
        if ch in _TOML_ESCAPES:
            out.append(_TOML_ESCAPES[ch])
        elif ord(ch) < 0x20 or ord(ch) == 0x7F:
            out.append(f"\\u{ord(ch):04X}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


#: How long to keep retrying a rename that Windows refuses because
#: something -- a virus scanner, the search indexer, an editor -- has the
#: target open for a moment.
RETRY_FOR = 1.0


def atomic_write(path, text, encoding="utf-8", newline=None):
    """Replace `path` with `text`, whole or not at all.

    `newline` is passed to `open` exactly as a caller would have passed
    it, so a file keeps the line endings it was always written with.
    """
    path = os.fspath(path)
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    fd, temp = tempfile.mkstemp(
        prefix="." + os.path.basename(path) + ".", suffix=".tmp",
        dir=directory)
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline=newline) as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        _replace(temp, path)
    except BaseException:
        try:
            os.remove(temp)
        except OSError:
            pass
        raise
    return path


def _replace(temp, path):
    deadline = time.monotonic() + RETRY_FOR
    while True:
        try:
            os.replace(temp, path)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.05)
