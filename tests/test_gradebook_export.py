"""Filling LMS exports' cells, and leaving everything else alone.

**The rules under test are not invented here.** They are the ones
`apply_to_brightspace.py` -- the instructor's own script, in production
since October -- already follows, and they are stricter than the
obvious ones:

* a non-pass is written **only for skills named explicitly**, and
  **only into an empty cell**, because entering one raises that
  student's denominator where the subtotals count filled cells;
* a pass already in the gradebook is **never** replaced, not even
  behind a flag;
* a cell holding anything else **stops the export**;
* a student on two rows loses to the row with more grades, and a tie
  stops the export;
* a student in **two files** stops the export, since a course exports
  one file per section and nobody belongs to two.

Matching is on the student id, not an email: an address that reached
Brightspace from another institution is often stale.

Every id and name here is invented.
"""

import os

import pytest

from checkit_printit import gradebook as gb
from checkit_printit import record
from checkit_printit import roster as roster_mod
from checkit_printit.gradebook import GradebookError, Profile

PASS = "\U0001f3c6Pass"
NOT_YET = "\U0001f4adNot Yet"

SKILLS = ["W1", "W2", "W3"]

ROSTER = '''
[[student]]
name    = "Ada Lovelace"
sid     = "806000111"
section = "820"
skills  = []

[[student]]
name    = "Alan Turing"
sid     = "806000222"
section = "820"
skills  = []

[[student]]
name    = "Emmy Noether"
sid     = "806000333"
section = "830"
skills  = []

[[student]]
name    = "Carl Gauss"
sid     = "806000444"
section = "820"
dropped = true
skills  = []
'''


def head():
    out = ["OSW_ID"]
    for slug in SKILLS:
        out.append(f"{slug} Grade Symbol <Selectbox MaxPoints:1 "
                   f"Category:Core Skills Progress>")
    out += ["Core Skills Progress Subtotal Numerator",
            "Tokens Text Grade <Text>", "End-of-Line Indicator"]
    return out


def sheet(rows, name="MAT106-820.csv"):
    """One file: the header, then `rows` as (id, w1, w2, w3)."""
    out = [head()]
    for ident, w1, w2, w3 in rows:
        out.append([ident, w1, w2, w3, "0", "3", "#"])
    return gb.Sheet(name=name, rows=out,
                    section="820" if "820" in name else
                            ("830" if "830" in name else ""))


def profile(**over):
    fields = dict(
        name="test", student_column="OSW_ID", student_matches="sid",
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
             "passed_in": None, "last_sat": last_sat,
             "last_date": "2026-11-01"}
            for sid, slug, passes, last_sat in rows]


def run(sheets, students, prog, not_yet=(), **over):
    if isinstance(sheets, gb.Sheet):
        sheets = [sheets]
    return gb.plan_export(sheets, profile(**over), students, prog, SKILLS,
                          not_yet=not_yet)


# ------------------------------------------------------------- a pass in --

def test_a_pass_fills_an_empty_cell(students):
    _, report = run(sheet([("806000111", "", "", "")]), students,
                    progress(("806000111", "W1", 1, "passed")))
    assert [(c.row, c.slug, c.was, c.now) for c in report.changes] == \
        [(2, "W1", "", PASS)]


def test_a_pass_replaces_a_non_pass(students):
    """An upgrade is always allowed; it cannot lower anybody."""
    _, report = run(sheet([("806000111", NOT_YET, "", "")]), students,
                    progress(("806000111", "W1", 1, "passed")))
    assert [(c.was, c.now) for c in report.changes] == [(NOT_YET, PASS)]


def test_a_pass_already_there_is_not_a_change(students):
    _, report = run(sheet([("806000111", PASS, "", "")]), students,
                    progress(("806000111", "W1", 1, "passed")))
    assert report.changes == []
    assert report.already_right == 1


# --------------------------------------------------------- a non-pass in --

def test_a_non_pass_is_not_written_unless_the_skill_is_named(students):
    """The rule that stops a denominator creeping up by accident."""
    _, report = run(sheet([("806000111", "", "", "")]), students,
                    progress(("806000111", "W1", 0, "failed")))
    assert report.changes == []
    assert report.not_written >= 1


def test_a_named_skill_writes_a_non_pass_into_a_blank(students):
    _, report = run(sheet([("806000111", "", "", "")]), students,
                    progress(("806000111", "W1", 0, "failed")),
                    not_yet=["W1"])
    assert [(c.slug, c.was, c.now) for c in report.changes] == \
        [("W1", "", NOT_YET)]


def test_a_named_skill_still_never_replaces_a_pass(students):
    """Stated as a rule, not as a default.

    There is no flag for this. A pass in the gradebook may have come
    from before printit, or from outside it, and replacing it is the
    one irreversible thing an export could do.
    """
    one = sheet([("806000111", PASS, "", "")])
    changes, report = run(one, students,
                          progress(("806000111", "W1", 0, "failed")),
                          not_yet=["W1"])
    assert report.changes == []
    assert [k.slug for k in report.kept_passes()] == ["W1"]
    assert gb.apply_export(one, changes)[1][1] == PASS


def test_there_is_no_way_to_ask_for_a_pass_to_be_replaced(students):
    """Asserted because a flag existed for one commit, and should not.

    He said: we should never replace a pass with anything lower. A
    default can be overridden; a rule that takes no argument cannot.
    """
    import inspect
    assert list(inspect.signature(gb.apply_export).parameters) == \
        ["sheet", "changes"]
    assert "allow" not in str(inspect.signature(gb.plan_export))


def test_a_non_pass_already_there_is_not_a_change(students):
    _, report = run(sheet([("806000111", NOT_YET, "", "")]), students,
                    progress(("806000111", "W1", 0, "failed")),
                    not_yet=["W1"])
    assert report.changes == []
    assert report.already_right == 1


def test_a_skill_named_that_the_bank_does_not_publish_is_refused(students):
    _, report = run(sheet([("806000111", "", "", "")]), students, [],
                    not_yet=["NOPE"])
    assert any("does not publish" in r for r in report.refused)


# ----------------------------------------------------- what writes nothing --

def test_only_absences_writes_nothing(students):
    """An absence is not an attempt at the skill."""
    _, report = run(sheet([("806000111", "", "", "")]), students,
                    progress(("806000111", "W1", 0, None)), not_yet=SKILLS)
    assert report.changes == []
    assert report.not_written >= 1


def test_no_record_writes_nothing(students):
    _, report = run(sheet([("806000111", "", "", "")]), students, [],
                    not_yet=SKILLS)
    assert report.changes == []
    assert report.not_written == 3


def test_a_query_counts_as_an_attempt_that_did_not_pass(students):
    _, report = run(sheet([("806000111", "", "", "")]), students,
                    progress(("806000111", "W1", 0, "queried")),
                    not_yet=["W1"])
    assert [c.now for c in report.changes] == [NOT_YET]


# ------------------------------------------------------ an unknown value --

def test_a_cell_holding_something_unknown_stops_the_export(students):
    """Overwriting it would be guessing at what it means."""
    _, report = run(sheet([("806000111", "Excused", "", "")]), students,
                    progress(("806000111", "W1", 1, "passed")))
    assert report.changes == []
    assert any("does not know" in r for r in report.refused)


# ----------------------------------------------------------- the joining --

def test_it_matches_on_the_student_id(students):
    _, report = run(sheet([("806000111", "", "", "")]), students,
                    progress(("806000111", "W1", 1, "passed")))
    assert report.rows_matched == 1
    assert report.rows_unmatched == []


def test_punctuation_around_the_id_does_not_stop_the_join(students):
    _, report = run(sheet([("#806000111", "", "", "")]), students,
                    progress(("806000111", "W1", 1, "passed")))
    assert report.rows_matched == 1


def test_a_retired_enrolment_is_skipped_by_its_marker(students):
    one = sheet([("806000111", "", "", ""),
                 ("806000111-DoNotUse", "", "", "")])
    changes, report = run(one, students,
                          progress(("806000111", "W1", 1, "passed")))
    assert report.rows_ignored == ["MAT106-820.csv:3"]
    assert report.rows_matched == 1
    assert gb.apply_export(one, changes)[2] == one.rows[2]


def test_a_duplicate_row_loses_to_the_one_with_more_grades(students):
    """His rule, and the order in the file must not decide it.

    The first version of this test put the better row first, so taking
    the file's own order gave the same answer as counting grades and
    breaking the counting changed nothing. The empty row comes first
    now, which is the arrangement that tells them apart.
    """
    one = sheet([("806000111", "", "", ""),
                 ("806000111", PASS, PASS, "")])
    _, report = run(one, students,
                    progress(("806000111", "W3", 1, "passed")))
    assert report.refused == []
    assert [c.row for c in report.changes] == [3]
    assert any("writing to row 3" in n for n in report.notes)


def test_duplicate_rows_with_the_same_count_are_refused(students):
    one = sheet([("806000111", "", "", ""), ("806000111", "", "", "")])
    _, report = run(one, students,
                    progress(("806000111", "W1", 1, "passed")))
    assert any("nothing to choose between them" in r for r in report.refused)
    assert report.changes == []


def test_a_row_matching_nobody_is_reported(students):
    _, report = run(sheet([("806999999", "", "", "")]), students, [])
    assert report.rows_unmatched == ["MAT106-820.csv:2"]


def test_a_student_with_no_row_is_reported(students):
    _, report = run(sheet([("806000111", "", "", "")]), students, [])
    assert "806000222" in report.students_unmatched
    assert "806000444" not in report.students_unmatched, "a dropped student"


def test_a_missing_student_column_is_refused(students):
    _, report = run(sheet([("806000111", "", "", "")]), students, [],
                    student_column="Nope")
    assert any("no column called" in r for r in report.refused)


# ------------------------------------------------- more than one section --

def test_two_files_are_planned_together(students):
    a = sheet([("806000111", "", "", "")], name="MAT106-820.csv")
    b = sheet([("806000333", "", "", "")], name="MAT106-830.csv")
    _, report = run([a, b], students,
                    progress(("806000111", "W1", 1, "passed"),
                             ("806000333", "W2", 1, "passed")))
    assert report.rows_matched == 2
    assert {c.sheet for c in report.changes} == {"MAT106-820.csv",
                                                 "MAT106-830.csv"}
    assert report.students_unmatched == ["806000222"]


def test_a_student_in_two_files_stops_the_export(students):
    """Only checkable with both files in hand, which is why they go together."""
    a = sheet([("806000111", "", "", "")], name="MAT106-820.csv")
    b = sheet([("806000111", "", "", "")], name="MAT106-830.csv")
    _, report = run([a, b], students,
                    progress(("806000111", "W1", 1, "passed")))
    assert any("appears in 2 files" in r for r in report.refused)
    assert report.changes == []


def test_a_student_in_the_wrong_sections_file_is_noted(students):
    """A note, not a refusal: the section is guessed from the file name."""
    b = sheet([("806000111", "", "", "")], name="MAT106-830.csv")
    _, report = run(b, students,
                    progress(("806000111", "W1", 1, "passed")))
    assert any("roster says 820" in n for n in report.notes)
    assert report.refused == []
    assert len(report.changes) == 1


def test_changes_are_reported_per_file(students):
    a = sheet([("806000111", "", "", "")], name="MAT106-820.csv")
    b = sheet([("806000333", "", "", "")], name="MAT106-830.csv")
    _, report = run([a, b], students,
                    progress(("806000111", "W1", 1, "passed"),
                             ("806000333", "W2", 1, "passed")))
    assert len(report.for_sheet("MAT106-820.csv")) == 1
    assert len(report.for_sheet("MAT106-830.csv")) == 1


# ---------------------------------------------- everything else untouched --

def test_no_other_cell_is_written(students):
    one = sheet([("806000111", "", "", ""), ("806000222", "", "", "")])
    changes, _ = run(one, students,
                     progress(("806000111", "W1", 1, "passed"),
                              ("806000222", "W2", 0, "failed")),
                     not_yet=["W2"])
    out = gb.apply_export(one, changes)
    differ = [(r, c) for r in range(len(one.rows))
              for c in range(len(one.rows[r]))
              if one.rows[r][c] != out[r][c]]
    assert sorted(differ) == [(1, 1), (2, 2)]


def test_the_input_rows_are_left_alone(students):
    one = sheet([("806000111", "", "", "")])
    before = [list(r) for r in one.rows]
    changes, _ = run(one, students,
                     progress(("806000111", "W1", 1, "passed")))
    gb.apply_export(one, changes)
    assert one.rows == before


def test_the_header_is_never_written_to(students):
    one = sheet([("806000111", "", "", "")])
    changes, _ = run(one, students,
                     progress(("806000111", "W1", 1, "passed")))
    assert gb.apply_export(one, changes)[0] == head()


# -------------------------------------------------- the post-condition --

def test_verify_passes_on_a_correct_write(students):
    one = sheet([("806000111", "", "", "")])
    changes, _ = run(one, students,
                     progress(("806000111", "W1", 1, "passed")))
    out = gb.apply_export(one, changes)
    assert gb.verify_export(one.rows, out, changes, one.name) == []


@pytest.mark.parametrize("damage, expect", [
    (lambda out: out[1].__setitem__(2, "oops"), "not in the plan"),
    (lambda out: out[0].__setitem__(0, "oops"), "header row"),
    (lambda out: out[1].__setitem__(1, ""), "did not change"),
    (lambda out: out.pop(), "row count changed"),
])
def test_verify_catches_a_write_that_strayed(students, damage, expect):
    """A right plan and a wrong write look the same from the plan's side."""
    one = sheet([("806000111", "", "", "")])
    changes, _ = run(one, students,
                     progress(("806000111", "W1", 1, "passed")))
    out = gb.apply_export(one, changes)
    damage(out)
    problems = gb.verify_export(one.rows, out, changes, one.name)
    assert any(expect in p for p in problems), problems


# ----------------------------------------------------- the actual write --

class TestSplice:
    """Untouched lines are copied byte for byte.

    Re-serialising through a CSV writer normalises quoting, so a cell
    the LMS quoted unnecessarily would come back bare and the uploaded
    file would no longer be the downloaded one.
    """

    def _file(self, tmp_path, ending="\r\n", bom=False, quoted=False):
        lines = [",".join(head())]
        lines.append("806000111,,,,0,3,#")
        lines.append('806000222,,,,0,"3,4",#' if quoted
                     else "806000222,,,,0,3,#")
        text = ending.join(lines) + ending
        path = tmp_path / "MAT106-820.csv"
        with open(path, "w", encoding="utf-8-sig" if bom else "utf-8",
                  newline="") as f:
            f.write(text)
        return str(path)

    def _plan(self, path, students, name="MAT106-820.csv"):
        from checkit_printit import mask as mask_mod
        rows = mask_mod.read_rows(path)
        one = gb.Sheet(name=name, rows=rows, section="820")
        return one, run(one, students,
                        progress(("806000111", "W1", 1, "passed")))

    @pytest.mark.parametrize("ending", ["\n", "\r\n"])
    @pytest.mark.parametrize("bom", [False, True])
    def test_it_keeps_the_endings_and_the_bom(self, tmp_path, students,
                                              ending, bom):
        path = self._file(tmp_path, ending=ending, bom=bom)
        one, (changes, _) = self._plan(path, students)
        data = gb.splice(path, changes, one.name)

        assert data.startswith(b"\xef\xbb\xbf") is bom
        body = data[3:] if bom else data
        if ending == "\r\n":
            assert body.count(b"\r\n") == 3
            assert body.count(b"\n") == body.count(b"\r\n")
        else:
            assert b"\r" not in body

    def test_untouched_lines_are_identical(self, tmp_path, students):
        path = self._file(tmp_path)
        with open(path, "rb") as f:
            before = f.read().split(b"\r\n")
        one, (changes, _) = self._plan(path, students)
        after = gb.splice(path, changes, one.name).split(b"\r\n")

        assert before[0] == after[0], "the header line changed"
        assert before[2] == after[2], "an untouched row changed"
        assert before[1] != after[1], "the edited row did not change"

    def test_only_the_planned_cell_changes_on_the_edited_line(
            self, tmp_path, students):
        path = self._file(tmp_path)
        one, (changes, _) = self._plan(path, students)
        after = gb.splice(path, changes, one.name).decode("utf-8")
        edited = after.splitlines()[1].split(",")
        assert edited[0] == "806000111"
        assert edited[1] == PASS
        assert edited[2:] == ["", "", "0", "3", "#"]

    def test_a_quoted_line_is_refused_rather_than_mangled(self, tmp_path,
                                                          students):
        """Splitting such a line on commas would be wrong."""
        path = self._file(tmp_path, quoted=True)
        rows = __import__("csv").reader(
            open(path, encoding="utf-8-sig", newline=""))
        one = gb.Sheet(name="MAT106-820.csv", rows=list(rows), section="820")
        changes, _ = run(one, students,
                         progress(("806000222", "W1", 1, "passed")))
        with pytest.raises(GradebookError, match="quoted fields"):
            gb.splice(path, changes, one.name)

    def test_a_cell_that_moved_under_us_is_refused(self, tmp_path, students):
        """Between planning and writing, the file must not have changed."""
        path = self._file(tmp_path)
        one, (changes, _) = self._plan(path, students)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(",".join(head()) + "\r\n"
                    + f"806000111,{PASS},,,0,3,#\r\n")
        with pytest.raises(GradebookError, match="has changed"):
            gb.splice(path, changes, one.name)


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

    one = sheet([("806000111", "", "", ""), ("806000222", "", "", "")])
    _, report = run(one, students, record.progress(path), not_yet=["W2"])

    assert {(c.row, c.slug): c.now for c in report.changes} == \
        {(2, "W1"): PASS, (2, "W2"): NOT_YET}
