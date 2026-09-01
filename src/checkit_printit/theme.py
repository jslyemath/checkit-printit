"""The LaTeX package that decides how everything looks.

`skillcheckpoints.sty` is a **working by-hand system**, not an implementation
detail of this tool. Skills can be written as plain `.tex` files against it with
no CheckIt anywhere -- that is how one of the two courses using it works today.
So the package is the interface, and this tool targets it rather than replacing
it.

The default ships here. A bank may drop its own `skillcheckpoints.sty` in its
root to replace it wholesale -- the same convention `checkit`'s `tikz.py`
already uses for `tikz_preamble.tex`, so it is one rule rather than two.
"""

import os

THEME_FILENAME = "skillcheckpoints.sty"


def default_path():
    return os.path.join(os.path.dirname(__file__), "theme", THEME_FILENAME)


def load(bank_path=None):
    """The theme to use, and where it came from.

    Returns `(source, origin)` so a caller can tell the operator which one is in
    play. Silently using a different theme than expected is the kind of thing
    that is only noticed after a hundred pages have printed.
    """
    if bank_path:
        override = os.path.join(bank_path, THEME_FILENAME)
        if os.path.isfile(override):
            with open(override, encoding="utf-8") as f:
                return f.read(), override
    path = default_path()
    with open(path, encoding="utf-8") as f:
        return f.read(), path
