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

from lxml import etree

#: Folder inside the bank. Namespaced so it is obvious which tool owns it, and
#: so anything else this tool later ships into a bank -- a default
#: publication.toml, seating templates -- has somewhere to go without a second
#: migration.
BANK_DIR = "printit"

THEME_FILENAME = "printit.sty"

#: The picture half, which printit.sty \RequirePackage's. Installed beside it
#: because figures are compiled on their own: CheckIt rasterizes a bank's .tikz
#: in a `standalone` document, where the full theme cannot load. Both surfaces
#: load this one file, so a number line drawn for the web and the same line in
#: a handout are the same picture rather than two drawings kept looking alike.
FIGURES_FILENAME = "printitfigures.sty"

#: Everything installed into the bank, in the order it is reported.
INSTALLED_FILENAMES = (THEME_FILENAME, FIGURES_FILENAME)

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


#: Paths as written into bank.xml -- forward slashes, because they are read on
#: whatever machine publishes the bank, not only the one that installed it.
#: The figures package first: printit.sty requires it.
DECLARED_PATHS = (
    (f"{BANK_DIR}/{FIGURES_FILENAME}", "figures"),
    (f"{BANK_DIR}/{THEME_FILENAME}", "theme"),
)

#: Kept for the message shown when a manifest has nowhere obvious to write to.
DECLARED_PATH = f"{BANK_DIR}/{THEME_FILENAME}"


def _declared_paths(manifest):
    """The support paths this manifest already lists.

    Reads the XML, so a mention of a path in prose or a comment is not mistaken
    for a declaration.
    """
    try:
        tree = etree.parse(manifest)
    except etree.XMLSyntaxError as exc:
        raise ThemeError(f"{manifest} is not valid XML: {exc}")
    return {ele.get("path") for ele in tree.iter("{*}file")}


def declare(bank_path):
    """Tell the bank's manifest that this file exists. Returns True if added.

    CheckIt publishes LaTeX support files a bank declares under
    <latex-support>, and knows nothing about this tool -- which is the point.
    A constant in CheckIt naming `printit.sty` would be a hook for something
    that may never be installed. So the declaration is this tool's to write.

    Inserted as text rather than by re-serialising the XML, because bank.xml is
    hand-maintained and full of comments that a round-trip would move or drop.
    """
    manifest = os.path.join(bank_path, "bank.xml")
    with open(manifest, encoding="utf-8") as f:
        xml = f.read()

    # Parsed rather than searched as text. A substring check for the path
    # matched the path written in a *comment* elsewhere in the file, decided
    # the declaration already existed, and silently skipped it -- so the theme
    # was never published and nothing said why.
    present = _declared_paths(manifest)
    if all(path in present for path, _role in DECLARED_PATHS):
        return False

    files = "\n".join(
        f'        <file path="{path}" role="{role}"/>'
        for path, role in DECLARED_PATHS if path not in present)

    # A bank that already has the block gets the missing lines added to it.
    # Opening a second <latex-support> would parse fine and read badly, and
    # would happen again every time this tool grew another file.
    opening = "    <latex-support>\n"
    if opening in xml:
        xml = xml.replace(opening, opening + files + "\n", 1)
        with open(manifest, "w", encoding="utf-8", newline="") as f:
            f.write(xml)
        return True

    entry = (f'    <latex-support>\n'
             f'        <!-- Installed and owned by checkit-printit. CheckIt only\n'
             f'             publishes them, so the viewer can build LaTeX that\n'
             f'             matches the printed handouts. -->\n'
             f'{files}\n'
             f'    </latex-support>\n')

    # After </url>, which every bank has exactly one of, so the declaration
    # lands among the other bank-level settings rather than after the outcomes.
    marker = "</url>\n"
    if xml.count(marker) != 1:
        raise ThemeError(
            f"{manifest} has {xml.count(marker)} <url> lines, so there is no "
            "one obvious place to add the declaration. Add this by hand, "
            f"inside <bank>:\n{entry}"
        )
    xml = xml.replace(marker, marker + entry, 1)
    with open(manifest, "w", encoding="utf-8", newline="") as f:
        f.write(xml)
    return True


def install(bank_path, force=False):
    """Write the default into the bank. Returns (path, action, declared).

    `action` is "installed", "kept", or "replaced". An existing theme is never
    overwritten without `force`: that file is the author's, and may be a term's
    worth of layout work.

    `declared` says whether the manifest gained the declaration on this run --
    reported separately because a run can leave the theme alone and still have
    changed the bank, and saying "nothing written" would then be false.
    """
    target = bank_theme_path(bank_path)
    if os.path.isfile(legacy_path(bank_path)) and not os.path.isfile(target):
        # Writing a fresh default here would leave two themes in the bank, with
        # print using the new one and every hand-written .tex still loading the
        # old one -- a divergence that shows up only once pages are compared.
        raise ThemeError(
            _migration_instructions(bank_path) + "\n\nNothing was written."
        )

    action = "kept" if os.path.isfile(target) and not force else (
        "replaced" if os.path.isfile(target) else "installed")

    os.makedirs(os.path.join(bank_path, BANK_DIR), exist_ok=True)
    for filename in INSTALLED_FILENAMES:
        destination = os.path.join(bank_path, BANK_DIR, filename)
        # The theme is the author's to edit and is left alone unless forced.
        # printitfigures.sty is written whenever it is missing, because
        # printit.sty requires it -- a bank holding one without the other does
        # not compile, and that is a worse state than a refreshed default.
        if os.path.isfile(destination) and not force:
            continue
        shutil.copyfile(
            os.path.join(os.path.dirname(__file__), "theme", filename),
            destination,
        )
    return target, action, declare(bank_path)


def figures_source(bank_path=None):
    """The picture package printit.sty requires, and where it came from.

    Resolved the same way as the theme: the bank's copy if it has one, else the
    packaged default. A document loading printit will not compile without it,
    so it travels into every build folder alongside the theme.
    """
    if bank_path:
        override = os.path.join(bank_path, BANK_DIR, FIGURES_FILENAME)
        if os.path.isfile(override):
            with open(override, encoding="utf-8") as f:
                return f.read(), override
    path = os.path.join(os.path.dirname(__file__), "theme", FIGURES_FILENAME)
    with open(path, encoding="utf-8") as f:
        return f.read(), path


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
