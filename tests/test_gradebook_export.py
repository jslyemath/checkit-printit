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


def run(sheets, students, prog, not_yet=(), thresholds=None, **over):
    if isinstance(sheets, gb.Sheet):
        sheets = [sheets]
    return gb.plan_export(sheets, profile(**over), students, prog, SKILLS,
                          not_yet=not_yet, thresholds=thresholds)


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


class TestTheSectionInTheFileName:
    """Read after a hyphen or an underscore, not just "three digits".

    `(?<!\\d)(\\d{3})(?!\\d)` picks `106` out of
    `MAT106-820_GradesExport_...`, which made every row of both real
    exports look like a section mismatch -- 42 false notes that buried
    the rest of the report.
    """

    @pytest.mark.parametrize("name, expect", [
        ("26FA Number Systems & Operations MAT106-820_GradesExport_"
         "2026-11-09-05-32.csv", "820"),
        ("26FA Number Systems & Operations MAT106-830_GradesExport_"
         "2026-11-09-05-31.csv", "830"),
        ("MAT106-820.csv", "820"),
        ("MAT 206-001.csv", "001"),
        ("export_830.csv", "830"),
        ("export.csv", ""),
        ("2026-11-09.csv", ""),
    ])
    def test_it_reads_the_section(self, name, expect):
        assert gb.sheet_from(name, [[]]).section == expect

    def test_the_course_code_is_not_mistaken_for_the_section(self):
        """The whole bug, as its own assertion."""
        assert gb.sheet_from("MAT106-820.csv", [[]]).section != "106"

    def test_a_mismatch_is_one_line_per_file_not_one_per_student(self,
                                                                 students):
        """Forty-two near-identical lines is not a report."""
        wrong = sheet([("806000111", "", "", ""),
                       ("806000222", "", "", "")],
                      name="MAT106-830.csv")
        _, report = run(wrong, students,
                        progress(("806000111", "W1", 1, "passed"),
                                 ("806000222", "W1", 1, "passed")))
        mismatch = [n for n in report.notes if "puts in section" in n]
        assert len(mismatch) == 1, mismatch
        assert "2 row(s)" in mismatch[0]
        assert "rows 2, 3" in mismatch[0]

    def test_a_file_with_no_section_in_its_name_says_nothing(self,
                                                             students):
        plain = sheet([("806000111", "", "", "")], name="export.csv")
        _, report = run(plain, students,
                        progress(("806000111", "W1", 1, "passed")))
        assert [n for n in report.notes if "puts in section" in n] == []


class TestTheMarkerIsFoundAnywhere:
    """A retired enrolment is marked on whichever id the LMS chooses.

    Brightspace appends `-DoNotUse` to the **`OrgDefinedId`**, and this
    course matches students on **`OSW_ID`**. The rule used to be checked
    against the student column only, so moving the match from one id to
    the other made it stop firing -- silently. Both rows then looked
    clean, fell through to the duplicate rule, and were separated by
    their grade counts, which happens to pick the live row and is luck
    rather than design.
    """

    def _rows(self):
        """A header with both ids, and a retired row marked on the first."""
        head = ["OrgDefinedId"]
        for slug in SKILLS:
            head.append(f"{slug} Grade Symbol <Selectbox MaxPoints:1 "
                        f"Category:Core Skills Progress>")
        head += ["OSW_ID", "End-of-Line Indicator"]
        return [head,
                ["#2041000001", "", "", "", "806000111", "#"],
                ["#2041000001-DoNotUse", "", "", "", "806000111", "#"]]

    def test_a_marker_in_another_column_still_skips_the_row(self, students):
        one = gb.Sheet(name="MAT106-820.csv", rows=self._rows(),
                       section="820")
        _, report = gb.plan_export(
            [one], profile(student_column="OSW_ID", student_matches="sid"),
            students, progress(("806000111", "W1", 1, "passed")), SKILLS)
        assert report.rows_ignored == ["MAT106-820.csv:3"]
        assert report.rows_matched == 1
        assert report.refused == []
        assert [c.row for c in report.changes] == [2]

    def test_the_note_says_which_column_it_was_found_in(self, students):
        """So a surprising match is visible rather than merely effective."""
        one = gb.Sheet(name="MAT106-820.csv", rows=self._rows(),
                       section="820")
        _, report = gb.plan_export(
            [one], profile(student_column="OSW_ID", student_matches="sid"),
            students, progress(("806000111", "W1", 1, "passed")), SKILLS)
        assert any("in column 1" in n for n in report.notes), report.notes
        assert all("806000111" not in n for n in report.notes)

    def test_without_the_rule_the_rows_are_only_told_apart_by_luck(
            self, students):
        """What used to happen, asserted so the old behaviour is on record.

        With no ignore rule at all the two rows are a duplicate pair,
        and only their grade counts separate them. Here they are equal,
        so it is refused -- which is the honest outcome, and shows that
        the marker rule is doing real work rather than tidying up.
        """
        one = gb.Sheet(name="MAT106-820.csv", rows=self._rows(),
                       section="820")
        _, report = gb.plan_export(
            [one], profile(student_column="OSW_ID", student_matches="sid",
                           ignore_rows=[]),
            students, progress(("806000111", "W1", 1, "passed")), SKILLS)
        assert report.changes == []
        assert any("nothing to choose between them" in r
                   for r in report.refused)

    @pytest.mark.parametrize("row, expect", [
        (["a", "b-DoNotUse", "c"], ("-DoNotUse", 1)),
        (["a-DoNotUse", "b", "c"], ("-DoNotUse", 0)),
        (["a", "b", "c"], None),
        ([], None),
    ])
    def test_ignored_by_reports_the_marker_and_its_column(self, row, expect):
        assert gb.ignored_by(row, ["-DoNotUse"]) == expect

    def test_an_empty_marker_never_matches(self):
        """An empty string is in every cell, so it must be skipped."""
        assert gb.ignored_by(["a", "b"], ["", None]) is None


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
    assert any("more than one file" in r for r in report.refused)
    assert report.changes == []
    # Named by where, not by who.
    assert all("806000111" not in r for r in report.refused)


def test_a_student_in_the_wrong_sections_file_is_noted(students):
    """A note, not a refusal: the section is guessed from the file name."""
    b = sheet([("806000111", "", "", "")], name="MAT106-830.csv")
    _, report = run(b, students,
                    progress(("806000111", "W1", 1, "passed")))
    assert any("puts in section 820" in n for n in report.notes)
    assert report.refused == []
    assert len(report.changes) == 1
    assert all("806000111" not in n for n in report.notes)


class TestTheReportCarriesNoIdentity:
    """No printed line may hold a student's id or name.

    Every report in this work gives locations rather than values: the
    masker's leak message gives column numbers, the duplicate report
    gives row numbers. The export broke that in two places, and it
    matters because the report is the thing a person reads out, pastes
    into a message, or shows to somebody who should not see the roster.

    `students_unmatched` is excluded on purpose: it holds ids, and
    `describe` prints its length and never its contents. That is
    asserted below rather than assumed.
    """

    def _everything(self, report):
        lines = [report.describe()]
        lines += list(report.refused) + list(report.notes)
        lines += [f"{k.sheet} {k.row} {k.slug} {k.value}"
                  for k in report.kept]
        lines += [f"{c.sheet} {c.row} {c.column} {c.slug} {c.was} {c.now} "
                  f"{c.why}" for c in report.changes]
        return "\n".join(lines)

    #: Every scenario that makes the export report something. Each is
    #: `(label, sheets, progress rows, not_yet)`. They are separate
    #: runs because some branches end in `continue` and so exclude
    #: others -- a student refused for being in two files reports
    #: nothing else.
    def _scenarios(self):
        duplicates = sheet([("806000111", "", "", ""),
                            ("806000111", PASS, "", ""),
                            ("806999999", "", "", ""),
                            ("806000444-DoNotUse", "", "", "")],
                           name="MAT106-830.csv")
        both = [sheet([("806000111", "", "", "")], name="MAT106-820.csv"),
                sheet([("806000111", "", "", "")], name="MAT106-830.csv")]
        unknown = sheet([("806000111", "Excused", "", "")])
        return [
            ("duplicates, unmatched, marker, section, kept, changes",
             duplicates,
             progress(("806000111", "W1", 1, "passed"),
                      ("806000111", "W2", 0, "failed"),
                      ("806000222", "W1", 1, "passed")), ["W2"]),
            ("one student in two files", both,
             progress(("806000111", "W1", 1, "passed")), []),
            ("a cell holding something unknown", unknown,
             progress(("806000111", "W1", 1, "passed")), []),
            # A kept pass needs all three at once: the cell holds a
            # pass, the record says not passed, and the skill is named.
            ("a pass kept against the record",
             sheet([("806000111", PASS, "", "")]),
             progress(("806000111", "W1", 0, "failed")), ["W1"]),
        ]

    def test_no_line_holds_an_id(self, students):
        """Driven through every branch that reports anything.

        The scenarios are separate runs on purpose. Some branches end
        the student's turn -- being in two files reports nothing else
        about them -- so one arrangement of rows cannot reach them all.
        A single-sheet version of this test left the two-files refusal
        untested, and breaking that refusal to name the student kept
        the suite green.
        """
        seen = set()
        for label, sheets, prog, not_yet in self._scenarios():
            _, report = run(sheets, students, prog, not_yet=not_yet)
            text = self._everything(report)
            for sid in ("806000111", "806000222", "806000333",
                        "806000444", "806999999"):
                assert sid not in text, \
                    f"{sid} reached the report in {label}:\n{text}"
            for name in ("Lovelace", "Turing", "Noether", "Gauss"):
                assert name not in text, \
                    f"{name} reached the report in {label}"
            if report.refused:
                seen.add("refused")
            if report.notes:
                seen.add("notes")
            if report.kept:
                seen.add("kept")
            if report.changes:
                seen.add("changes")
        # And the scenarios really did reach each kind of line, so a
        # future edit cannot quietly stop exercising one.
        assert seen == {"refused", "notes", "kept", "changes"}, seen

    def test_the_count_of_unmatched_students_is_printed_not_the_list(
            self, students):
        _, report = run(sheet([("806000111", "", "", "")]), students, [])
        assert report.students_unmatched, "expected somebody unmatched"
        said = report.describe()
        for sid in report.students_unmatched:
            assert sid not in said
        assert f"{len(report.students_unmatched)} student(s)" in said


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

    def test_a_quoted_row_is_spliced_and_keeps_its_quoting(self, tmp_path,
                                                           students):
        """**This used to be refused**, and the refusal ruled out most
        of the world: every data row of a Canvas export is quoted,
        because every one holds `"Last, First"`. His Brightspace export
        escapes it only by having no name column at all.

        The quoted field here holds a comma, so splitting the line on
        commas would put the mark in the wrong column."""
        path = self._file(tmp_path, quoted=True)
        rows = __import__("csv").reader(
            open(path, encoding="utf-8-sig", newline=""))
        one = gb.Sheet(name="MAT106-820.csv", rows=list(rows), section="820")
        changes, _ = run(one, students,
                         progress(("806000222", "W1", 1, "passed")))
        assert changes, "nothing was planned, so this proves nothing"

        after = gb.splice(path, changes, one.name).decode("utf-8")
        edited = after.splitlines()[2]
        fields = [f[0] for f in gb.fields_of(edited)]

        assert len(fields) == len(head()), "a field was added or lost"
        assert fields[0] == "806000222", "the id moved"
        assert fields[1] == PASS, "the mark did not land in W1"
        assert fields[5] == "3,4", "the quoted field's value changed"
        assert '"3,4"' in edited, \
            "the quoted field lost its quotes, so the file is no " \
            "longer the file that was downloaded"

    def test_an_unterminated_quote_is_refused(self, tmp_path, students):
        """A line that will not parse is a line nobody should be
        editing. Refused rather than guessed at."""
        path = self._file(tmp_path)
        with open(path, "r", encoding="utf-8", newline="") as handle:
            text = handle.read()
        broken = text.replace("806000111,,,,0,3,#", '806000111,,,,0,"3,#')
        assert broken != text, "the fixture line changed shape"
        with open(path, "w", encoding="utf-8", newline="") as handle:
            handle.write(broken)
        one, (changes, _) = self._plan(path, students)
        assert changes, "nothing was planned, so this proves nothing"
        with pytest.raises(GradebookError, match="never closed"):
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


class TestReadingACsvLine:
    """`fields_of` is what makes a quoted row editable at all: it
    gives each field's value *and* its span, so one field can be
    replaced and every other byte of the line copied as it arrived."""

    def test_a_plain_line(self):
        assert [f[0] for f in gb.fields_of("a,b,c")] == ["a", "b", "c"]

    def test_a_quoted_field_may_hold_a_comma(self):
        assert [f[0] for f in gb.fields_of('a,"b,c",d')] == \
            ["a", "b,c", "d"]

    def test_a_doubled_quote_is_one_quote(self):
        assert [f[0] for f in gb.fields_of('a,"say ""hi""",b')] == \
            ["a", 'say "hi"', "b"]

    def test_empty_fields_are_counted(self):
        assert [f[0] for f in gb.fields_of("a,,,b")] == ["a", "", "", "b"]

    def test_a_trailing_comma_leaves_an_empty_field(self):
        assert [f[0] for f in gb.fields_of("a,b,")] == ["a", "b", ""]

    def test_one_empty_line_is_one_empty_field(self):
        assert [f[0] for f in gb.fields_of("")] == [""]

    def test_the_span_covers_the_quotes(self):
        line = 'a,"b,c",d'
        value, start, end = gb.fields_of(line)[1]
        assert line[start:end] == '"b,c"', \
            "the span must include the quotes, or replacing it would " \
            "leave one behind"
        assert value == "b,c"

    def test_replacing_one_span_leaves_every_other_byte(self):
        line = 'x,"b,c",bare,"d"'
        _, start, end = gb.fields_of(line)[2]
        assert line[:start] + "NEW" + line[end:] == 'x,"b,c",NEW,"d"', \
            "a field the LMS quoted unnecessarily has to stay quoted"

    def test_an_unterminated_quote_raises(self):
        with pytest.raises(GradebookError, match="never closed"):
            gb.fields_of('a,"b,c')


class TestWritingACsvField:
    """Minimal quoting: a mark written into a bare cell stays bare."""

    def test_a_plain_value_stays_bare(self):
        assert gb.as_field("Pass") == "Pass"

    def test_a_comma_forces_quotes(self):
        assert gb.as_field("a,b") == '"a,b"'

    def test_a_quote_is_doubled(self):
        assert gb.as_field('say "hi"') == '"say ""hi"""'

    def test_a_newline_forces_quotes(self):
        assert gb.as_field("a\r\nb") == '"a\r\nb"'

    def test_nothing_is_an_empty_field(self):
        assert gb.as_field("") == ""
        assert gb.as_field(None) == ""

    def test_what_it_writes_reads_back_the_same(self):
        for value in ["Pass", "a,b", 'say "hi"', "", "3,4",
                      '"already quoted"', "trailing,"]:
            line = "x," + gb.as_field(value) + ",y"
            assert [f[0] for f in gb.fields_of(line)] == ["x", value, "y"], \
                f"{value!r} did not survive a round trip"


class TestThresholds:
    """A skill can need more than one pass -- `course.thresholds` says
    which, and Progress has always read it.

    **The export did not.** It branched on `passes` being non-zero, so
    a skill needing two was written as passed after one: Progress
    showing it unearned while the gradebook said otherwise, the tool's
    two halves disagreeing in the direction of overstating a grade. No
    skill in his course needs two, which is why it went unnoticed.
    """

    def test_one_pass_is_not_enough_when_two_are_needed(self, students):
        changes, report = run(
            sheet([("806000111", "", "", "")]), students,
            progress(("806000111", "W1", 1, "passed")),
            thresholds={"W1": 2})
        assert not changes, "one pass of two was exported as a pass"
        assert report.short == {"W1": 1}, \
            "and it has to say so, because 'not written' for a student " \
            "who has passed once reads as a bug"

    def test_two_passes_earn_it(self, students):
        changes, _ = run(sheet([("806000111", "", "", "")]), students,
                         progress(("806000111", "W1", 2, "passed")),
                         thresholds={"W1": 2})
        assert [(c.slug, c.now) for c in changes.values()] == [("W1", PASS)]

    def test_more_than_enough_still_earns_it(self, students):
        changes, _ = run(sheet([("806000111", "", "", "")]), students,
                         progress(("806000111", "W1", 3, "passed")),
                         thresholds={"W1": 2})
        assert len(changes) == 1

    def test_a_skill_not_named_needs_one(self, students):
        """`thresholds` holds only the exceptions, so an absent slug
        must not be read as needing zero or as needing the same as its
        neighbour."""
        changes, _ = run(sheet([("806000111", "", "", "")]), students,
                         progress(("806000111", "W2", 1, "passed")),
                         thresholds={"W1": 2})
        assert [(c.slug, c.now) for c in changes.values()] == [("W2", PASS)]

    def test_no_thresholds_at_all_behaves_as_before(self, students):
        """His course today. One pass, one write."""
        changes, _ = run(sheet([("806000111", "", "", "")]), students,
                         progress(("806000111", "W1", 1, "passed")))
        assert len(changes) == 1

    def test_being_short_does_not_write_a_non_pass_unasked(self, students):
        """Short of the threshold is not the same as having failed, and
        a non-pass still only goes in for a named skill."""
        changes, _ = run(sheet([("806000111", "", "", "")]), students,
                         progress(("806000111", "W1", 1, "passed")),
                         thresholds={"W1": 2})
        assert not changes

    def test_short_of_the_threshold_can_be_written_as_not_yet(self, students):
        """And when the skill *is* named, a non-pass is the honest
        thing to write: they have not earned it yet."""
        changes, _ = run(sheet([("806000111", "", "", "")]), students,
                         progress(("806000111", "W1", 1, "passed")),
                         not_yet=("W1",), thresholds={"W1": 2})
        assert [(c.slug, c.now) for c in changes.values()] == \
            [("W1", NOT_YET)]

    def test_a_pass_already_there_is_still_never_replaced(self, students):
        """Even short of the threshold. A pass in the gradebook may
        have come from somewhere printit knows nothing about."""
        changes, report = run(
            sheet([("806000111", PASS, "", "")]), students,
            progress(("806000111", "W1", 1, "passed")),
            not_yet=("W1",), thresholds={"W1": 2})
        assert not changes
        assert report.kept_passes(), "the pass was not reported as kept"


# ------------------------------------------------- auditing the result --

class TestAuditingTheWrittenFile:
    """`audit_export` checks the file against the *record*.

    `verify_export` checks it against the plan, which cannot fail when
    the plan is the thing that is wrong: it is both the question and
    the answer. These tests damage the written file in ways a faithful
    write of a wrong plan would produce, and every one of them has to
    be noticed.

    He asked for this before his first Brightspace upload, in those
    words: outside validation.
    """

    def audit(self, one, out, students, prog, not_yet=(), thresholds=None,
              **over):
        return gb.audit_export(
            one.rows, out, one.name, profile(**over), students, prog,
            SKILLS, not_yet=not_yet, thresholds=thresholds)

    def written(self, one, students, prog, **kw):
        changes, _ = run(one, students, prog, **kw)
        return gb.apply_export(one, changes)

    def test_a_faithful_write_has_nothing_to_report(self, students):
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        report = self.audit(one, self.written(one, students, prog), students,
                            prog)
        assert report.ok, report.describe()
        assert report.changed == 1
        assert report.backed == 1

    def test_a_pass_replaced_by_a_non_pass_is_a_regression(self, students):
        """The one thing he named. No mapping, no roster and no record
        are needed to see it: the cell said pass and does not now."""
        one = sheet([("806000111", PASS, "", "")])
        prog = progress(("806000111", "W1", 0, "failed"))
        out = self.written(one, students, prog, not_yet=("W1",))
        out[1][1] = NOT_YET                      # what must never happen
        report = self.audit(one, out, students, prog, not_yet=("W1",))
        assert [f.kind for f in report.findings] == ["regression"]

    def test_a_pass_blanked_is_also_a_regression(self, students):
        """The quieter half, and the one a "did anything become Not
        Yet" check would miss. An emptied cell is a lost grade
        wherever the subtotal counts filled cells."""
        one = sheet([("806000111", PASS, "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        out = self.written(one, students, prog)
        out[1][1] = ""
        report = self.audit(one, out, students, prog)
        # Both, and rightly so: the cell lost a pass, *and* the record
        # still says that skill is passed, which the coverage pass has
        # its own thing to say about.
        assert [f.kind for f in report.findings] == ["regression", "missed"]

    def test_a_pass_the_record_holds_and_the_file_does_not_is_missed(
            self, students):
        """The inverse check. A file that was never written to at all
        passes every other test here -- nothing regressed, nothing
        strayed, nothing is unbacked -- so this is the one that
        notices an export that quietly did nothing."""
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        report = self.audit(one, [list(r) for r in one.rows], students, prog)
        assert [f.kind for f in report.findings] == ["missed"]

    def test_a_pass_with_no_result_behind_it_is_unbacked(self, students):
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        out = self.written(one, students, prog)
        out[1][2] = PASS                         # W2, which has no record
        report = self.audit(one, out, students, prog)
        assert [f.kind for f in report.findings] == ["unbacked"]

    def test_a_pass_short_of_its_threshold_is_unbacked(self, students):
        """The bug that shipped once already, caught from the other
        side: a skill needing two passes written as passed after one."""
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        out = [list(r) for r in one.rows]
        out[1][1] = PASS
        report = self.audit(one, out, students, prog, thresholds={"W1": 2})
        assert [f.kind for f in report.findings] == ["unbacked"]
        assert "2 are needed" in report.findings[0].says

    def test_a_non_pass_for_a_skill_nobody_named_is_unbacked(self, students):
        """Writing one raises the student's denominator, so it is a
        deliberate act for the skills in play -- and a file holding one
        that was never asked for is a file to look at."""
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 0, "failed"))
        out = [list(r) for r in one.rows]
        out[1][1] = NOT_YET
        report = self.audit(one, out, students, prog)       # no not_yet
        assert [f.kind for f in report.findings] == ["unbacked"]

    def test_a_non_pass_over_a_passing_record_is_unbacked(self, students):
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        out = [list(r) for r in one.rows]
        out[1][1] = NOT_YET
        report = self.audit(one, out, students, prog, not_yet=("W1",))
        kinds = [f.kind for f in report.findings]
        assert "unbacked" in kinds

    def test_a_non_pass_on_nothing_but_absences_is_unbacked(self, students):
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 0, None))
        out = [list(r) for r in one.rows]
        out[1][1] = NOT_YET
        report = self.audit(one, out, students, prog, not_yet=("W1",))
        assert [f.kind for f in report.findings] == ["unbacked"]
        assert "only absences" in report.findings[0].says

    def test_a_cell_outside_every_skill_column_is_stray(self, students):
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        out = self.written(one, students, prog)
        out[1][5] = "9"                          # the Tokens column
        report = self.audit(one, out, students, prog)
        assert [f.kind for f in report.findings] == ["stray"]

    def test_a_stray_finding_never_quotes_the_cell(self, students):
        """Every other finding quotes a skill column, whose values are
        the two mark strings. This one is about a column no skill
        claims -- the id, the email, the name -- and the first version
        printed a student's OrgDefinedId into a report that goes on
        screen and into a log."""
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        out = self.written(one, students, prog)
        out[1][0] = "806000111-changed"
        report = self.audit(one, out, students, prog)
        assert [f.kind for f in report.findings] == ["stray"]
        said = report.findings[0].says + report.findings[0].where
        assert "806000111" not in said, said

    def test_a_write_into_an_ignored_row_is_stray(self, students):
        """`-DoNotUse` marks a retired enrolment that has marks of its
        own. Nothing may be written there at all."""
        one = sheet([("806000111-DoNotUse", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        out = [list(r) for r in one.rows]
        out[1][1] = PASS
        report = self.audit(one, out, students, prog)
        assert [f.kind for f in report.findings] == ["stray"]

    def test_a_dropped_row_is_a_shape_finding(self, students):
        one = sheet([("806000111", "", "", ""), ("806000222", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        out = self.written(one, students, prog)
        out.pop()
        report = self.audit(one, out, students, prog)
        assert [f.kind for f in report.findings] == ["shape"]

    def test_a_written_header_is_a_shape_finding(self, students):
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        out = self.written(one, students, prog)
        out[0][1] = "something else"
        report = self.audit(one, out, students, prog)
        assert [f.kind for f in report.findings] == ["shape"]

    def test_a_file_whose_header_is_not_the_first_line_is_refused(
            self, students):
        """Rather than audited wrongly. Everything here indexes from
        `before[0]` being the header, which is what `Sheet.head` and
        `plan_export` assume too; a file with a preamble would come
        back clean having compared a student's row to a title line."""
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        report = gb.audit_export(
            one.rows, [list(r) for r in one.rows], one.name, profile(),
            students, prog, SKILLS, header_line=3)
        assert [f.kind for f in report.findings] == ["shape"]
        assert "first line is the header" in report.findings[0].says

    def test_a_column_mapped_to_a_slug_its_header_never_names(self,
                                                              students):
        """The mapping is checked, not worked out a second time -- a
        second heuristic is a second thing to be wrong. `names_a_slug`
        is strict where `match` is clever."""
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        report = gb.audit_export(
            one.rows, [list(r) for r in one.rows], one.name, profile(),
            students, prog, SKILLS,
            columns={"W1": 5})          # the Tokens column
        assert "mismapped" in [f.kind for f in report.findings]

    def test_a_hand_paired_column_is_not_mismapped(self, students):
        """`pairs` exists precisely for a column whose header does not
        carry its slug at all -- his `FCP` is one.

        `ignore_columns` is cleared here, because the fixture's default
        lists this very header and the first version of this test
        therefore failed on the *other* check: a column the profile
        says to leave alone that a skill also claims. Which is the
        right answer to a different question, and is now asked below."""
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        report = gb.audit_export(
            one.rows, [list(r) for r in one.rows], one.name,
            profile(pairs={"W1": one.rows[0][5]}, ignore_columns=[]),
            students, prog, SKILLS, columns={"W1": 5})
        assert "mismapped" not in [f.kind for f in report.findings]

    def test_a_column_the_profile_ignores_may_not_also_be_claimed(
            self, students):
        """Two statements that contradict each other: this column is
        not to be written to, and this skill lives in it. Whichever is
        wrong, writing to it is not safe."""
        one = sheet([("806000111", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        report = gb.audit_export(
            one.rows, [list(r) for r in one.rows], one.name,
            profile(ignore_columns=[one.rows[0][5]]), students, prog,
            SKILLS, columns={"W1": 5})
        assert "mismapped" in [f.kind for f in report.findings]
        assert any("leave" in f.says for f in report.findings)

    def test_a_longer_slug_does_not_claim_a_shorter_ones_column(self):
        """`N3` must not match `N30`'s header, which is the whole
        reason the rule looks at the next character."""
        assert gb.names_a_slug("W1 Grade Symbol <Selectbox>", "W1")
        assert gb.names_a_slug("W1", "W1")
        assert not gb.names_a_slug("W10 Grade Symbol", "W1")
        assert not gb.names_a_slug("Tokens Text Grade", "W1")

    def test_the_count_of_untouched_passes_is_reported(self, students):
        """The number that answers "nothing regressed" in the
        affirmative rather than by silence."""
        one = sheet([("806000111", PASS, PASS, "")])
        prog = progress(("806000111", "W3", 1, "passed"))
        report = self.audit(one, self.written(one, students, prog), students,
                            prog)
        assert report.ok, report.describe()
        assert report.passes_held == 2

    def test_a_student_on_two_rows_is_covered_by_either(self, students):
        """`plan_export` writes to the row with more grades and leaves
        the other alone, so demanding the pass in both rows would
        invent a finding. The first version of the coverage check kept
        only the last row it saw and did exactly that."""
        one = sheet([("806000111", PASS, "", ""),
                     ("806000111-DoNotUse", "", "", "")])
        prog = progress(("806000111", "W1", 1, "passed"))
        report = self.audit(one, [list(r) for r in one.rows], students, prog)
        assert report.ok, report.describe()


class TestWhichLinesMoved:
    """Bytes, which the parsed comparison cannot speak for.

    A cell whose value is unchanged and whose quoting is not reads as
    identical through `csv.reader`, and is a different file as far as
    the LMS is concerned.
    """

    def test_an_identical_file_has_no_moved_lines(self):
        data = b"a,b\r\n1,2\r\n"
        assert gb.changed_lines(data, data) == ([], 2)

    def test_the_line_that_changed_is_named(self):
        moved, same = gb.changed_lines(b"a,b\r\n1,2\r\n3,4\r\n",
                                       b"a,b\r\n1,9\r\n3,4\r\n")
        assert (moved, same) == ([2], 2)

    def test_requoting_a_cell_counts_as_a_change(self):
        """The case the row comparison is blind to: both parse to the
        same value."""
        moved, _ = gb.changed_lines(b'a,b\r\n1,"2"\r\n', b"a,b\r\n1,2\r\n")
        assert moved == [2]

    def test_changed_line_endings_show_up(self):
        """A file that arrived CRLF and left LF is not the file that
        was downloaded."""
        moved, _ = gb.changed_lines(b"a,b\r\n1,2\r\n", b"a,b\n1,2\n")
        assert moved == [1, 2]

    def test_a_line_added_at_the_end_is_counted(self):
        moved, _ = gb.changed_lines(b"a,b\r\n1,2\r\n", b"a,b\r\n1,2\r\n3,4\r\n")
        assert moved == [3]


# ----------------------------- making it a file the LMS will read --

#: A header row shaped like his real Brightspace export: the computed
#: columns among the real ones, in the places the export puts them.
TRIM_HEAD = [
    "OrgDefinedId",
    "\U0001f4cc Grading Scheme Reminder Text Grade <Text>",
    "Total Core Skills Passed Formula Grade <Formula MaxPoints:22>",
    "W1 Grade Symbol <Selectbox MaxPoints:1 Category:Core Skills Progress>",
    "W2 Grade Symbol <Selectbox MaxPoints:1 Category:Core Skills Progress>",
    "Core Skills Progress Subtotal Numerator",
    "Core Skills Progress Subtotal Denominator",
    "W3 Grade Symbol <Selectbox MaxPoints:1 Category:Core Skills Progress>",
    "Calculated Final Grade Numerator",
    "Calculated Final Grade Denominator",
    "Adjusted Final Grade Numerator",
    "Adjusted Final Grade Denominator",
    "OSW_ID",
    "End-of-Line Indicator",
]


class TestTrimmingForImport:
    """Brightspace will not accept its own export.

    The file it hands you carries columns it computes for itself --
    formula items, each category's subtotal, the calculated final
    grade -- and the import refuses the whole file over them rather
    than skipping them: "The import file selected cannot be read."
    His own export is otherwise a faultless CSV, 21 rows all 61
    fields wide, no quoting, no embedded commas, so nothing
    structural explains it.
    """

    def test_the_computed_columns_are_the_ones_dropped(self):
        keep, dropped = gb.importable_columns(TRIM_HEAD)
        assert [TRIM_HEAD[i] for i, _, _ in dropped] == [
            "Total Core Skills Passed Formula Grade <Formula MaxPoints:22>",
            "Core Skills Progress Subtotal Numerator",
            "Core Skills Progress Subtotal Denominator",
            "Calculated Final Grade Numerator",
            "Calculated Final Grade Denominator",
            # Not computed -- not a grade item at all. See below.
            "OSW_ID",
        ]
        assert len(keep) == len(TRIM_HEAD) - 6

    def test_every_skill_column_survives(self):
        keep, _ = gb.importable_columns(TRIM_HEAD)
        kept = [TRIM_HEAD[i] for i in keep]
        for slug in ("W1", "W2", "W3"):
            assert any(h.startswith(slug + " ") for h in kept), slug

    def test_the_adjusted_final_grade_survives(self):
        """Only the *calculated* final grade is computed. The adjusted
        one is the column an instructor is meant to write in."""
        keep, _ = gb.importable_columns(TRIM_HEAD)
        kept = [TRIM_HEAD[i] for i in keep]
        assert "Adjusted Final Grade Numerator" in kept
        assert "Adjusted Final Grade Denominator" in kept

    def test_the_identifier_and_the_end_marker_survive(self):
        keep, _ = gb.importable_columns(TRIM_HEAD)
        kept = [TRIM_HEAD[i] for i in keep]
        assert kept[0] == "OrgDefinedId"
        assert kept[-1] == "End-of-Line Indicator"

    def test_a_column_that_is_not_a_grade_item_goes(self):
        """`OSW_ID` is his own column and Brightspace has no grade
        item to match it to. Deleting it by hand is what got him past
        "the import file selected cannot be read" -- which was a
        different error from the one the computed columns cause, and
        the first version of this aimed at the wrong one.

        A Brightspace export labels every grade item with a
        `<Type ...>` suffix, so an unlabelled column that is not one
        of `FIXED_COLUMNS` is not a grade item. 48 of his 61 carry a
        suffix; of the 13 that do not, twelve are fixed columns and
        the thirteenth is this."""
        keep, dropped = gb.importable_columns(TRIM_HEAD)
        assert "OSW_ID" not in [TRIM_HEAD[i] for i in keep]
        why = next(w for i, h, w in dropped if h == "OSW_ID")
        assert "not a grade item" in why

    def test_the_fixed_columns_are_not_mistaken_for_grade_items(self):
        """They carry no `<Type>` suffix either, and every one of them
        belongs in the import file."""
        head = ["OrgDefinedId", "Username", "Last Name", "First Name",
                "Email", "W1 Points Grade <Numeric MaxPoints:1>",
                "Adjusted Final Grade Numerator",
                "Adjusted Final Grade Denominator",
                "End-of-Line Indicator"]
        keep, dropped = gb.importable_columns(head)
        assert dropped == []
        assert keep == list(range(len(head)))

    def test_a_gradebook_with_none_of_them_is_untouched(self):
        """The rule is written in terms of what Brightspace computes,
        so it is a no-op elsewhere -- a Canvas export goes through
        whole. A trim that fired on another LMS would be silently
        throwing columns away."""
        head = ["Student", "ID", "SIS Login ID", "W1", "Current Score"]
        keep, dropped = gb.importable_columns(head)
        assert dropped == []
        assert keep == list(range(len(head)))

    def test_each_kept_field_keeps_its_own_text(self):
        """Separators are rebuilt and fields are not. A cell the LMS
        quoted has to stay quoted and one it left bare has to stay
        bare, which is the same promise `splice` makes."""
        data = (b'a,b,Core Skills Progress Subtotal Numerator,d\r\n'
                b'1,"x, y",99,"4"\r\n')
        out = gb.drop_columns(data, [0, 1, 3])
        assert out == b'a,b,d\r\n1,"x, y","4"\r\n'

    def test_the_line_endings_and_bom_are_carried_through(self):
        data = (b"\xef\xbb\xbfa,Core Skills Progress Subtotal Numerator,c"
                b"\r\n1,2,3\r\n")
        out = gb.drop_columns(data, [0, 2])
        assert out.startswith(b"\xef\xbb\xbf")
        assert out.count(b"\r\n") == 2
        assert out.count(b"\n") == out.count(b"\r\n")

    def test_a_short_row_is_padded_rather_than_refused(self):
        """A trailing empty cell produces one, and throwing the file
        away over a cell that was never there would be worse than
        writing the blank it stands for."""
        out = gb.drop_columns(b"a,b,c\r\n1\r\n", [0, 2])
        assert out == b"a,c\r\n1,\r\n"

    def test_a_faithful_trim_has_nothing_to_report(self):
        rows = [TRIM_HEAD, ["#1", "", "3", PASS, "", "1", "3", "", "5",
                            "10", "", "", "806000111", "#"]]
        keep, _ = gb.importable_columns(TRIM_HEAD)
        trimmed = [[r[i] for i in keep] for r in rows]
        assert gb.verify_dropped(rows, trimmed, keep, "f.csv") == []

    def test_a_trim_that_moved_a_value_is_caught(self):
        rows = [TRIM_HEAD, ["#1", "", "3", PASS, "", "1", "3", "", "5",
                            "10", "", "", "806000111", "#"]]
        keep, _ = gb.importable_columns(TRIM_HEAD)
        trimmed = [[r[i] for i in keep] for r in rows]
        trimmed[1][3] = "something else"
        problems = gb.verify_dropped(rows, trimmed, keep, "f.csv")
        assert problems and "did not survive" in problems[0]

    def test_a_trim_that_lost_a_column_is_caught(self):
        rows = [TRIM_HEAD, ["#1"] + [""] * 13]
        keep, _ = gb.importable_columns(TRIM_HEAD)
        trimmed = [[r[i] for i in keep][:-1] for r in rows]
        problems = gb.verify_dropped(rows, trimmed, keep, "f.csv")
        assert problems and "field(s) after trimming" in problems[0]


class TestTheAuditFollowsTheTrim:
    """The audit compares columns by number, and the file he uploads
    has fewer of them than the file he downloaded. Without this it
    would report the header as rewritten and stop -- on the only file
    that matters."""

    def rows_for(self, students):
        return [TRIM_HEAD,
                ["#1", "", "3", "", "", "1", "3", "", "5", "10", "", "",
                 "806000111", "#"]]

    def profile_for(self):
        return Profile(name="t", student_column="OSW_ID",
                       student_matches="sid", passed=PASS,
                       not_passed=NOT_YET, blank_means="not attempted")

    def test_a_trimmed_file_lines_up_by_header(self):
        keep, _ = gb.importable_columns(TRIM_HEAD)
        aligned = gb.align_columns(TRIM_HEAD, [TRIM_HEAD[i] for i in keep])
        assert aligned is not None
        assert len(aligned) == len(keep)
        assert all(TRIM_HEAD[before] == TRIM_HEAD[keep[after]]
                   for before, after in aligned.items())

    def test_a_reordered_header_is_not_an_alignment(self):
        """Same headers, different order. At that point nothing here
        can say which column is which, so it refuses rather than
        guessing."""
        shuffled = list(reversed(TRIM_HEAD))
        assert gb.align_columns(TRIM_HEAD, shuffled) is None

    def test_a_renamed_header_is_not_an_alignment(self):
        changed = list(TRIM_HEAD)
        changed[3] = "W1 something else"
        assert gb.align_columns(TRIM_HEAD, changed) is None

    def test_the_written_cell_is_found_at_its_new_position(self, students):
        """The whole point: a pass written into W1 is at column 4 in
        the export and column 3 after the trim, and the audit has to
        see one cell, not two."""
        rows = self.rows_for(students)
        keep, _ = gb.importable_columns(TRIM_HEAD)
        after = [[r[i] for i in keep] for r in rows]
        after[1][keep.index(3)] = PASS           # W1
        report = gb.audit_export(
            rows, after, "f.csv", self.profile_for(), students,
            progress(("806000111", "W1", 1, "passed")), ["W1", "W2", "W3"],
            columns={"W1": 3})
        assert report.ok, report.describe()
        assert report.changed == 1
        assert report.columns_dropped == 6

    def test_the_student_is_resolved_without_the_column_joined_on(
            self, students):
        """His profile joins on `OSW_ID`, which the trim now removes
        because it is not a grade item. Read out of the *written* file
        that made every student unresolvable and turned every written
        cell into an `unbacked` finding -- on the file he actually
        uploads. The id is taken from the exported row, which is
        where it has always been and which is never written to."""
        rows = self.rows_for(students)
        keep, _ = gb.importable_columns(TRIM_HEAD)
        assert TRIM_HEAD.index("OSW_ID") not in keep, \
            "the fixture no longer drops the column being tested"
        after = [[r[i] for i in keep] for r in rows]
        after[1][keep.index(3)] = PASS
        report = gb.audit_export(
            rows, after, "f.csv", self.profile_for(), students,
            progress(("806000111", "W1", 1, "passed")), ["W1", "W2", "W3"],
            columns={"W1": 3})
        assert report.ok, report.describe()
        assert report.backed == 1

    def test_a_regression_is_still_caught_through_the_trim(self, students):
        rows = self.rows_for(students)
        rows[1][3] = PASS
        keep, _ = gb.importable_columns(TRIM_HEAD)
        after = [[r[i] for i in keep] for r in rows]
        after[1][keep.index(3)] = NOT_YET
        report = gb.audit_export(
            rows, after, "f.csv", self.profile_for(), students,
            progress(("806000111", "W1", 0, "failed")), ["W1", "W2", "W3"],
            not_yet=("W1",), columns={"W1": 3})
        assert "regression" in [f.kind for f in report.findings]

    def test_dropping_a_column_the_lms_can_read_is_a_finding(self,
                                                             students):
        """Trimming only removes what Brightspace computes. Taking out
        an importable column means that grade item silently will not
        be imported, and nothing else here would say so."""
        rows = self.rows_for(students)
        keep, _ = gb.importable_columns(TRIM_HEAD)
        keep = [i for i in keep if i != 4]       # W2, which is importable
        after = [[r[i] for i in keep] for r in rows]
        report = gb.audit_export(
            rows, after, "f.csv", self.profile_for(), students,
            progress(("806000111", "W1", 0, "failed")), ["W1", "W2", "W3"],
            columns={"W1": 3})
        assert "stray" in [f.kind for f in report.findings]
        assert any("can read back" in f.says for f in report.findings)
