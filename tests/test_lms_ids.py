"""Getting the LMS id onto the roster, which the export cannot run without.

The gradebook names a student only by `OrgDefinedId`. The roster holds
a 9-digit student id and an email address and, until this is done, no
LMS id at all -- so no gradebook row can be matched to anybody.

The question these tests answer is whether a **new** importer is needed
or whether `roster import` already does it. Every name and id here is
invented.
"""

import pytest

from checkit_printit import classlist
from checkit_printit import roster as roster_mod

#: What the roster looks like before: ids and addresses, no LMS id.
BEFORE = '''
[[student]]
name   = "Ada Lovelace"
last   = "Lovelace"
first  = "Ada"
sid    = "806000111"
email  = "alovelace@institute.edu"
section = "820"
skills = ["W1"]

[[student]]
name   = "Alan Turing"
last   = "Turing"
first  = "Alan"
sid    = "806000222"
email  = "aturing@institute.edu"
section = "820"
skills = []

[[student]]
name   = "Emmy Noether"
last   = "Noether"
first  = "Emmy"
sid    = "806000333"
email  = "enoether@institute.edu"
section = "830"
skills = []
'''

#: A Brightspace class list: the LMS id, and an address to join on.
CLASSLIST = """\
OrgDefinedId,Username,Last Name,First Name,Email,Role
#2041000001,alovelace,Lovelace,Ada,alovelace@institute.edu,Student
#2041000002,aturing,Turing,Alan,aturing@institute.edu,Student
#2041000009,instructor,Faculty,A,lecturer@institute.edu,Instructor
"""


@pytest.fixture
def before(tmp_path):
    path = tmp_path / "roster.toml"
    path.write_text(BEFORE, encoding="utf-8")
    return roster_mod.load(str(path))


@pytest.fixture
def incoming(tmp_path):
    path = tmp_path / "classlist.csv"
    path.write_text(CLASSLIST, encoding="utf-8")
    return classlist.parse(str(path))


def test_the_existing_importer_reads_the_lms_id(incoming):
    """`OrgDefinedId` is already in the synonym table, as `alt_id`."""
    students, mapping, _ = incoming
    assert "alt_id" in mapping.columns
    assert [s.alt_id for s in students] == ["#2041000001", "#2041000002"]


def test_the_instructor_row_is_dropped(incoming):
    students, _, notes = incoming
    assert len(students) == 2
    assert any("non-student" in n for n in notes)


def test_the_id_lands_on_the_right_student(before, incoming):
    """Joined on the address, which is what both files carry.

    This is the whole of what the export needs, and it needs no new
    command: `roster import` already matches on every id a student
    answers to, and an address is one of them.
    """
    students, _, _ = incoming
    merged, report = classlist.merge(before, students, scope={"820"})

    by_sid = {s.sid: s for s in merged}
    assert by_sid["806000111"].alt_id == "#2041000001"
    assert by_sid["806000222"].alt_id == "#2041000002"
    assert len(merged) == 3, "a student was added rather than matched"
    assert report.added == []


def test_nothing_the_instructor_authored_is_overwritten(before, incoming):
    students, _, _ = incoming
    merged, _ = classlist.merge(before, students, scope={"820"})
    ada = [s for s in merged if s.sid == "806000111"][0]
    assert ada.skills == ["W1"], "the chosen skills were lost"
    assert ada.name == "Ada Lovelace"


def test_a_section_the_file_does_not_cover_is_not_dropped(before, incoming):
    """The trap. A Brightspace class list carries no section column.

    Without a scope, `merge` treats the file as covering everybody, so
    importing one section's class list marks the other section dropped
    -- and a dropped student loses their seat, which is what stops
    their paper printing. `--covers` is the answer and it has to be
    passed, because the file cannot say.
    """
    students, _, _ = incoming
    merged, report = classlist.merge(before, students, scope={"820"})
    emmy = [s for s in merged if s.sid == "806000333"][0]
    assert not emmy.dropped
    assert report.dropped == []

    # And what happens without the scope, so the danger is visible.
    again = roster_mod.load.__wrapped__ if False else None   # noqa: F841
    fresh, report = classlist.merge(
        roster_mod.Roster([s for s in before]), students, scope=None)
    dropped = [s for s in fresh if s.dropped]
    assert [s.sid for s in dropped] == ["806000333"]


def test_the_id_keeps_its_hash_and_still_joins(before, incoming):
    """The gradebook writes `#2041000001`; the stored id keeps the `#`.

    It does not matter which spelling is stored, because the export
    joins on the alphanumeric core -- but it does matter that whatever
    is stored is *stable*, so a second import does not look like a
    change.
    """
    students, _, _ = incoming
    merged, _ = classlist.merge(before, students, scope={"820"})
    again, report = classlist.merge(merged, students, scope={"820"})
    assert report.updated == [], f"a second import changed something: {report.updated}"
    assert [s.alt_id for s in again if s.alt_id] == \
        ["#2041000001", "#2041000002"]


def test_the_export_can_then_find_everybody(before, incoming):
    """End to end: ids imported, then a gradebook row matched."""
    from checkit_printit import gradebook as gb

    students, _, _ = incoming
    merged, _ = classlist.merge(before, students, scope={"820"})

    head = ["OrgDefinedId",
            "W1 Grade Symbol <Selectbox MaxPoints:1 Category:Core>"]
    rows = [head, ["#2041000001", ""], ["#2041000002", ""]]
    profile = gb.Profile(
        name="t", student_column="OrgDefinedId", student_matches="alt_id",
        passed="P", not_passed="N", blank_means="not attempted")
    progress = [{"sid": "806000111", "slug": "W1", "attempts": 1,
                 "passes": 1, "queries": 0, "absents": 0, "last": "passed",
                 "passed_in": "r1", "last_sat": "passed",
                 "last_date": "2026-11-01"}]
    _, report = gb.plan_export(rows, profile, merged, progress, ["W1"])

    assert report.rows_matched == 2
    assert report.rows_unmatched == []
    assert [(c.row, c.now) for c in report.changes] == [(2, "P")]
