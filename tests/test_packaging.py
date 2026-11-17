"""What an installed copy has to carry with it.

Every check run against a working tree passes, because the repository has
every file. The failures here are all of one shape: a file the code needs
at run time, sitting somewhere `pyproject.toml`'s package data does not
reach, so a wheel ships without it. It has happened twice -- `gui/static`
with one star instead of two, and then (RV-9 of the 2026-11-16 review)
the Apps Script, which lived at the repository root, so `form create` and
`form attach` worked only from an editable install.

These read the package-data patterns out of pyproject.toml and resolve
them the way setuptools does, rather than trusting a list written here.
"""

import glob
import os
import tomllib

import checkit_printit
from checkit_printit import provision

PACKAGE = os.path.dirname(os.path.abspath(checkit_printit.__file__))
ROOT = os.path.dirname(os.path.dirname(PACKAGE))


def shipped():
    """Every file the package data patterns select, relative to the package."""
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
        patterns = tomllib.load(f)["tool"]["setuptools"]["package-data"][
            "checkit_printit"]
    out = set()
    for pattern in patterns:
        for path in glob.glob(os.path.join(PACKAGE, pattern), recursive=True):
            if os.path.isfile(path):
                out.add(os.path.relpath(path, PACKAGE).replace(os.sep, "/"))
    return out


def test_the_script_is_looked_for_inside_the_package():
    where = os.path.abspath(provision.script_sources())
    assert where.startswith(PACKAGE + os.sep), where


def test_the_script_is_there():
    for name in ("Code.gs", "appsscript.json"):
        assert os.path.isfile(os.path.join(provision.script_sources(), name))


def test_the_script_is_shipped():
    files = shipped()
    assert "appsscript/Code.gs" in files
    assert "appsscript/appsscript.json" in files


def test_the_rest_of_what_runs_is_shipped():
    """The others the code opens by path, so a pattern edited for one
    cannot quietly drop another."""
    files = shipped()
    for needed in ("theme/printit.sty", "theme/printitfigures.sty",
                   "gui/static/index.html", "gui/static/app.js",
                   "gui/static/seating/seating.js", "data/digits.npz"):
        assert needed in files, needed
