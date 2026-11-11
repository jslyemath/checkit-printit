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
