"""The LaTeX package that decides how everything looks.

`printit.sty` is a **working by-hand system**, not an implementation detail of
this tool. Skills can be written as plain `.tex` files against it with no
CheckIt anywhere -- that is how one of the two courses using it works today.
So the package is the interface, and this tool targets it rather than replacing
it.

The default ships here and is installed into a bank's `printit/` folder, where
it is meant to be edited -- the same arrangement as `bank_helpers.sty`, which
CheckIt writes into a new bank for its author to change. Once installed, that
one file decides both what the printed handouts look like and what the
viewer's Assessment tab exports: CheckIt publishes it with the bank so a
browser can reach it.

A bank without one is not broken. Printing falls back to the default bundled
here, and the Assessment tab falls back to CheckIt's plain template.
"""

import os
import shutil

#: Folder inside the bank. Namespaced so it is obvious which tool owns it, and
#: so anything else this tool later ships into a bank -- a default
#: publication.toml, seating templates -- has somewhere to go without a second
#: migration.
BANK_DIR = "printit"

THEME_FILENAME = "printit.sty"

#: Where a bank's theme lived before it belonged to this tool. Detected so an
#: older bank stops with instructions, rather than silently getting the default
#: while its hand-written .tex files still load the old package.
LEGACY_FILENAME = "skillcheckpoints.sty"


class ThemeError(Exception):
    pass


def default_path():
    return os.path.join(os.path.dirname(__file__), "theme", THEME_FILENAME)


def bank_theme_path(bank_path):
    """Where a bank's own copy belongs."""
    return os.path.join(bank_path, BANK_DIR, THEME_FILENAME)


def legacy_path(bank_path):
    return os.path.join(bank_path, LEGACY_FILENAME)


def _migration_instructions(bank_path):
    legacy = legacy_path(bank_path)
    target = bank_theme_path(bank_path)
    return (
        f"{legacy} is this bank's theme, from before the file moved into "
        f"{BANK_DIR}/. To move it:\n"
        f"    git mv {LEGACY_FILENAME} {os.path.join(BANK_DIR, THEME_FILENAME)}\n"
        f"then change \\ProvidesPackage{{skillcheckpoints}} to "
        f"\\ProvidesPackage{{printit}} inside it.\n"
        f"Any .tex of your own saying \\usepackage{{skillcheckpoints}} needs "
        f"updating to \\usepackage{{printit}}."
    )


def install(bank_path, force=False):
    """Write the default into the bank. Returns (path, action).

    `action` is "installed", "kept", or "replaced". An existing theme is never
    overwritten without `force`: that file is the author's, and may be a term's
    worth of layout work.
    """
    target = bank_theme_path(bank_path)
    if os.path.isfile(legacy_path(bank_path)) and not os.path.isfile(target):
        # Writing a fresh default here would leave two themes in the bank, with
        # print using the new one and every hand-written .tex still loading the
        # old one -- a divergence that shows up only once pages are compared.
        raise ThemeError(
            _migration_instructions(bank_path) + "\n\nNothing was written."
        )

    if os.path.isfile(target) and not force:
        return target, "kept"

    action = "replaced" if os.path.isfile(target) else "installed"
    os.makedirs(os.path.dirname(target), exist_ok=True)
    shutil.copyfile(default_path(), target)
    return target, action


def load(bank_path=None):
    """The theme to use, and where it came from.

    Returns `(source, origin)` so a caller can tell the operator which one is in
    play. Silently using a different theme than expected is the kind of thing
    that is only noticed after a hundred pages have printed.
    """
    if bank_path:
        override = bank_theme_path(bank_path)
        if os.path.isfile(override):
            with open(override, encoding="utf-8") as f:
                return f.read(), override
        if os.path.isfile(legacy_path(bank_path)):
            raise ThemeError(_migration_instructions(bank_path))
    path = default_path()
    with open(path, encoding="utf-8") as f:
        return f.read(), path
