"""A run is not refused because of a skill it does not print.

RV-13 of the 2026-11-16 review. `choose_seeds` draws for every skill in
the bank, so that a run seed always deals the same papers. But a skill
that could not be drawn -- never generated, too few printable seeds, a
stale variant -- raised, and refused a run that never prints it: adding a
half-written outcome to bank.xml stopped all printing until it had been
generated.

The draw order is unchanged on purpose. A skill that cannot be drawn is
now skipped, and only when nobody needs it -- and every run that ever
succeeded had no such skill, so the same seed still deals the same papers.
"""

import os
import random
import shutil

import pytest

from checkit_printit import assemble
from checkit_printit.bank import Bank, BankError
from checkit_printit.publication import Publication

#: What `choose_seeds` drew for this bank under Random(5) before the change,
#: recorded so the change can be shown to draw exactly the same.
BEFORE = {("A", "AD"): 439, ("B", "AD"): 416, ("A", "SU"): 422,
          ("B", "SU"): 433, ("A", "VR"): 400, ("B", "VR"): 428}


@pytest.fixture
def bank_with_a_new_outcome(bank_dir, tmp_path):
    """The test bank plus NEW: declared in bank.xml, never generated."""
    root = tmp_path / "bank"
    shutil.copytree(bank_dir, root)
    xml = (root / "bank.xml").read_text(encoding="utf-8")
    xml = xml.replace("</outcomes>", """    <outcome>
            <title>New</title>
            <slug>NEW</slug>
            <path>outcomes/NEW</path>
            <description>Not generated yet.</description>
        </outcome>
    </outcomes>""")
    (root / "bank.xml").write_text(xml, encoding="utf-8")
    (root / "outcomes" / "NEW").mkdir()
    return str(root)


def pub(path, **kw):
    return Publication(bank_path=path, variants={"VR": "small"}, **kw)


def test_the_same_seed_still_deals_the_same_papers(bank_dir):
    got = assemble.choose_seeds(Bank(bank_dir), ["A", "B"], pub(bank_dir),
                                random.Random(5))
    assert got == BEFORE


def test_an_ungenerated_skill_nobody_prints_is_skipped(bank_with_a_new_outcome):
    path = bank_with_a_new_outcome
    got = assemble.choose_seeds(Bank(path), ["A", "B"], pub(path),
                                random.Random(5), needed={"AD"})
    assert got == BEFORE, "and the others are drawn exactly as before"


def test_an_ungenerated_skill_somebody_prints_is_still_refused(
        bank_with_a_new_outcome):
    path = bank_with_a_new_outcome
    with pytest.raises(BankError, match="NEW"):
        assemble.choose_seeds(Bank(path), ["A", "B"], pub(path),
                              random.Random(5), needed={"AD", "NEW"})


def test_a_stale_variant_on_an_unprinted_skill_is_skipped(bank_dir):
    publication = Publication(bank_path=bank_dir, variants={"VR": "retired"})
    got = assemble.choose_seeds(Bank(bank_dir), ["A", "B"], publication,
                                random.Random(5), needed={"AD", "SU"})
    assert ("A", "VR") not in got
    assert got[("A", "AD")] == BEFORE[("A", "AD")]


def test_the_whole_build_goes_through(bank_with_a_new_outcome, tmp_path):
    """Through `assemble`, which is what works out who needs what."""
    from checkit_printit import roster as roster_mod
    from checkit_printit import theme
    path = bank_with_a_new_outcome
    source, _ = theme.load(path)
    people = roster_mod.Roster([roster_mod.Student(
        name="Ada", skills=["AD"], sid="001", section="1")])
    report = assemble.assemble(pub(path, title="T", date="2026-01-01"),
                               people, None, str(tmp_path / "out"), source,
                               rng=random.Random(1), dry_run=True)
    assert report["skills"] == ["AD"]
