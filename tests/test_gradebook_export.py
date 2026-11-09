"""Filling an LMS export's cells, and leaving everything else alone.

What export is: take the file the instructor exported, fill in the
cells there is a recorded result for, change nothing else, hand it back.

Every id and name here is invented.
"""

import os

import pytest

from checkit_printit import gradebook as gb
from checkit_printit import record
from checkit_printit import roster as roster_mod
from checkit_printit.gradebook import Profile

PASS = "\U0001f3c6Pass"
NOT_YET = "\U0001f4adNot Yet"

SKILLS = ["W1", "W2", "W3"]

ROSTER = '''
[[student]]
name   = "Ada Lovelace"
sid    = "806000111"
alt_id = "2041000001"
skills = []

[[student]]
name   = "Alan Turing"
sid    = "806000222"
alt_id = "2041000002"
skills = []

[[student]]
name   = "Emmy Noether"
sid    = "806000333"
alt_id = "2041000003"
skills = []

[[student]]
name    = "Carl Gauss"
sid     = "806000444"
alt_id  = "2041000004"
dropped = true
skills  = []
'''


def head():
    out = ["OrgDefinedId"]
    for slug in SKILLS:
        out.append(f"{slug} Grade Symbol <Selectbox MaxPoints:1 "
                   f"Category:Core Skills Progress>")
    out += ["Core Skills Progress Subtotal Numerator",
            "Tokens Text Grade <Text>", "End-of-Line Indicator"]
    return out


def sheet(rows):
    """A gradebook: the header, then `rows` as (id, w1, w2, w3)."""
    out = [head()]
    for ident, w1, w2, w3 in rows:
        out.append([ident, w1, w2, w3, "0", "3", "#"])
    return out


def profile(**over):
    fields = dict(
        name="test", student_column="OrgDefinedId", student_matches="alt_id",
        passed=PASS, not_passed=NOT_YET, blank_means="not attempted",
        ignore_rows=["-DoNotUse"],
        ignore_columns=["Core Skills Progress Subtotal Numerator",
                        "Tokens Text Grade <Text>", "End-of-Line Indicator"])
    fields.update(over)
    return Profile(**fields)


@pytest.fixture
def students(tmp_path):
    path = tmp_path / "roster.toml"
    path.write_text(ROSTER, encoding="utf-8")
    return roster_mod.load(str(path))


def progress(*rows):
    """`record.progress`-shaped rows: (sid, slug, passes, last_sat)."""
    return [{"sid": sid, "slug": slug, "attempts": 1, "passes": passes,
             "queries": 0, "absents": 0, "last": last_sat or "absent",
             "passed_in": None, "last_sat": last_sat, "last_date": "2026-11-01"}
            for sid, slug, passes, last_sat in rows]


# ------------------------------------------------------- the three rules --

def test_a_pass_is_written(students):
    rows = sheet([("#2041000001", "", "", "")])
    changes, report = gb.plan_export(
        rows, profile(), students,
        progress(("806000111", "W1", 1, "passed")), SKILLS)
    assert len(report.changes) == 1
    change = report.changes[0]
    assert (change.row, change.slug, change.was, change.now) == \
        (2, "W1", "", PASS)


def test_an_attempt_that_did_not_pass_is_written(students):
    rows = sheet([("#2041000001", "", "", "")])
    _, report = gb.plan_export(
        rows, profile(), students,
        progress(("806000111", "W1", 0, "failed")), SKILLS)
    assert [c.now for c in report.changes] == [NOT_YET]


def test_a_query_counts_as_an_attempt_that_did_not_pass(students):
    """His rule: the pass passes and everything else does not."""
    _, report = gb.plan_export(
        sheet([("#2041000001", "", "", "")]), profile(), students,
        progress(("806000111", "W1", 0, "queried")), SKILLS)
    assert [c.now for c in report.changes] == [NOT_YET]


def test_only_absences_leaves_the_cell_alone(students):
    """An absence is not an attempt at the skill.

    The subtotals count filled cells, so writing a non-pass here would
    raise this student's denominator for a paper they never sat.
    """
    _, report = gb.plan_export(
        sheet([("#2041000001", "", "", "")]), profile(), students,
        progress(("806000111", "W1", 0, None)), SKILLS)
    assert report.changes == []
    assert report.no_result >= 1


def test_no_record_at_all_leaves_the_cell_alone(students):
    _, report = gb.plan_export(
        sheet([("#2041000001", "", "", "")]), profile(), students,
        [], SKILLS)
    assert report.changes == []
    assert report.no_result == 3


def test_a_cell_already_right_is_not_a_change(students):
    _, report = gb.plan_export(
        sheet([("#2041000001", PASS, "", "")]), profile(), students,
        progress(("806000111", "W1", 1, "passed")), SKILLS)
    assert report.changes == []
    assert report.already_right == 1


# ------------------------------------------------------------ downgrades --

def test_replacing_a_pass_is_held_back(students):
    """A pass in the gradebook may not have come from printit."""
    rows = sheet([("#2041000001", PASS, "", "")])
    changes, report = gb.plan_export(
        rows, profile(), students,
        progress(("806000111", "W1", 0, "failed")), SKILLS)
    assert report.changes == []
    assert len(report.downgrades) == 1
    assert report.downgrades[0].was == PASS

    out, written = gb.apply_export(rows, changes)
    assert written == 0
    assert out[1][1] == PASS, "a pass was overwritten without being allowed"

    out, written = gb.apply_export(rows, changes, allow_downgrades=True)
    assert written == 1
    assert out[1][1] == NOT_YET


def test_filling_a_blank_is_not_a_downgrade(students):
    _, report = gb.plan_export(
        sheet([("#2041000001", "", "", "")]), profile(), students,
        progress(("806000111", "W1", 0, "failed")), SKILLS)
    assert report.downgrades == []
    assert len(report.changes) == 1


# ----------------------------------------------------------- the joining --

def test_the_hash_prefix_does_not_stop_the_join(students):
    """The gradebook writes `#2041000001`; the roster holds it bare."""
    _, report = gb.plan_export(
        sheet([("#2041000001", "", "", "")]), profile(), students,
        progress(("806000111", "W1", 1, "passed")), SKILLS)
    assert report.rows_matched == 1
    assert report.rows_unmatched == []


def test_a_retired_enrolment_is_skipped(students):
    rows = sheet([("#2041000001", "", "", ""),
                  ("#2041000001-DoNotUse", "", "", "")])
    changes, report = gb.plan_export(
        rows, profile(), students,
        progress(("806000111", "W1", 1, "passed")), SKILLS)
    assert report.rows_ignored == [3]
    assert report.rows_matched == 1
    assert all(c.row == 2 for c in report.changes)

    out, _ = gb.apply_export(rows, changes)
    assert out[2] == rows[2], "the retired row was touched"


def test_two_live_rows_for_one_student_are_refused(students):
    """Without the marker there is nothing to tell them apart by."""
    rows = sheet([("#2041000001", "", "", ""), ("2041000001", "", "", "")])
    _, report = gb.plan_export(
        rows, profile(), students,
        progress(("806000111", "W1", 1, "passed")), SKILLS)
    assert any("second row" in r for r in report.refused)


def test_a_row_matching_nobody_is_reported(students):
    _, report = gb.plan_export(
        sheet([("#2049999999", "", "", "")]), profile(), students,
        [], SKILLS)
    assert report.rows_unmatched == [2]
    assert report.rows_matched == 0


def test_a_student_with_no_row_is_reported(students):
    _, report = gb.plan_export(
        sheet([("#2041000001", "", "", "")]), profile(), students,
        [], SKILLS)
    assert "806000222" in report.students_unmatched
    assert "806000333" in report.students_unmatched


def test_a_dropped_student_is_not_reported_as_missing(students):
    _, report = gb.plan_export(
        sheet([("#2041000001", "", "", "")]), profile(), students,
        [], SKILLS)
    assert "806000444" not in report.students_unmatched


def test_a_missing_student_column_is_refused(students):
    _, report = gb.plan_export(
        sheet([("#2041000001", "", "", "")]),
        profile(student_column="Nope"), students, [], SKILLS)
    assert any("no column called" in r for r in report.refused)


# ---------------------------------------------- everything else untouched --

def test_no_other_cell_is_written(students):
    rows = sheet([("#2041000001", "", "", ""), ("#2041000002", "", "", "")])
    changes, _ = gb.plan_export(
        rows, profile(), students,
        progress(("806000111", "W1", 1, "passed"),
                 ("806000222", "W2", 0, "failed")), SKILLS)
    out, written = gb.apply_export(rows, changes)
    assert written == 2

    differ = [(r, c) for r in range(len(rows))
              for c in range(len(rows[r])) if rows[r][c] != out[r][c]]
    assert sorted(differ) == [(1, 1), (2, 2)]


def test_the_input_rows_are_left_alone(students):
    rows = sheet([("#2041000001", "", "", "")])
    before = [list(r) for r in rows]
    changes, _ = gb.plan_export(
        rows, profile(), students,
        progress(("806000111", "W1", 1, "passed")), SKILLS)
    gb.apply_export(rows, changes)
    assert rows == before


def test_the_header_is_never_written_to(students):
    rows = sheet([("#2041000001", "", "", "")])
    changes, _ = gb.plan_export(
        rows, profile(), students,
        progress(("806000111", "W1", 1, "passed")), SKILLS)
    out, _ = gb.apply_export(rows, changes)
    assert out[0] == head()


# --------------------------------------- against the real record database --

def test_it_works_against_a_real_record_database(tmp_path, students,
                                                 monkeypatch):
    """The shape of `record.progress` is pinned, not assumed.

    Every other test here hands `plan_export` dictionaries built by
    hand. If the real query returns different keys -- `last_sat`
    spelled otherwise, say -- those tests all pass and the export is
    broken. So one test goes through the database.
    """
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    path = str(tmp_path / "record.db")
    record.write_run(
        path, run_id="r1", title="Checkpoint", date="2026-10-01",
        built="2026-10-01T09:00:00", seed=1, output="/out/1", run_no=1,
        handouts=[{"sid": "806000111", "name": "A", "section": "820",
                   "version": "A", "papers": [("W1", 401), ("W2", 402)]},
                  {"sid": "806000222", "name": "B", "section": "820",
                   "version": "B", "papers": [("W1", 403)]}])
    written, unknown = record.save_attempts(path, [
        {"run_id": "r1", "sid": "806000111", "slug": "W1",
         "outcome": "passed"},
        {"run_id": "r1", "sid": "806000111", "slug": "W2",
         "outcome": "failed"},
        {"run_id": "r1", "sid": "806000222", "slug": "W1",
         "outcome": "absent"},
    ])
    assert written == 3 and unknown == []

    rows = sheet([("#2041000001", "", "", ""), ("#2041000002", "", "", "")])
    _, report = gb.plan_export(rows, profile(), students,
                               record.progress(path), SKILLS)

    by_cell = {(c.row, c.slug): c.now for c in report.changes}
    assert by_cell == {(2, "W1"): PASS, (2, "W2"): NOT_YET}, by_cell
    # The absence wrote nothing.
    assert (3, "W1") not in by_cell
