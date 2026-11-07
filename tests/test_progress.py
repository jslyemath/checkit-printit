"""The Progress grid: what it reads, and what it lets you change.

The grid itself is 45 by 29 and almost wordless, so everything that
could make it quietly wrong is here: a skill that disappears because
nobody has attempted it, a student still on it after they left, a
threshold read as a default, a result recorded against a paper that
was never printed.

What a cell *looks like* is decided in `app.js` and checked in the
browser. These are about what the server tells it.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import course as course_mod
from checkit_printit import gui as gui_mod
from checkit_printit import record


ROSTER = '''
[[student]]
name = "Ada Lovelace"
sid = "001"
section = "820"

[[student]]
name = "Bo Peep"
sid = "002"
section = "820"

[[student]]
name = "Gone Away"
sid = "003"
section = "820"
dropped = true
'''


def handout(sid, papers, name="Someone"):
    return {"sid": sid, "name": name, "section": "820",
            "version": "A", "papers": papers}


@pytest.fixture
def course(tmp_path, monkeypatch, bank_dir):
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    course_mod.init("Test", bank=str(bank_dir), adopt=None)
    with open(course_mod.file_in("Test", "roster"), "w",
              encoding="utf-8") as fh:
        fh.write(ROSTER)
    path = course_mod.file_in("Test", "record")
    record.write_run(
        path, run_id="first", title="Checkpoint", date="2026-10-01",
        built="2026-10-01T09:00:00", seed=1, output="/out/1", run_no=1,
        handouts=[handout("001", [("AD", 401), ("SU", 402)], "Ada"),
                  handout("002", [("AD", 403)], "Bo")])
    record.write_run(
        path, run_id="second", title="Redo", date="2026-10-15",
        built="2026-10-15T09:00:00", seed=2, output="/out/2", run_no=2,
        handouts=[handout("001", [("AD", 411)], "Ada")])
    return gui_mod.Course("Test")


def decide(run_id, sid, slug, outcome, **kw):
    return {"run_id": run_id, "sid": sid, "slug": slug,
            "outcome": outcome, **kw}


# -------------------------------------------------------- the history ----

class TestHistory:
    """Driven off `printed`, not `attempt`.

    A run handed out and never scanned has to be in the list with
    nothing against it: that row is the paper he is holding months
    later with no stack left to re-read, and it is the only place
    he can record it.
    """

    def test_a_printing_with_no_result_is_still_a_row(self, course):
        rows = record.history(course.file("record"), "001", "AD")
        assert [r["run_id"] for r in rows] == ["first", "second"]
        assert [r["outcome"] for r in rows] == [None, None]

    def test_oldest_first(self, course):
        rows = record.history(course.file("record"), "001", "AD")
        assert [r["date"] for r in rows] == ["2026-10-01", "2026-10-15"]

    def test_it_carries_what_finds_the_paper_again(self, course):
        """Seed and version are what `--seed` and the manifest take."""
        row = record.history(course.file("record"), "001", "AD")[0]
        assert (row["seed"], row["version"], row["title"]) == (
            401, "A", "Checkpoint")

    def test_a_skill_never_printed_for_them_is_empty(self, course):
        assert record.history(course.file("record"), "002", "SU") == []

    def test_an_absent_database_is_empty_not_an_error(self, tmp_path):
        assert record.history(str(tmp_path / "no.db"), "001", "AD") == []


class TestGradingSets:
    def test_only_graded_runs_count(self, course):
        path = course.file("record")
        assert record.graded_runs(path) == []
        record.save_attempts(path, [decide("first", "001", "AD", "passed")])
        assert record.graded_runs(path) == ["first"]

    def test_newest_first_and_capped(self, course):
        path = course.file("record")
        record.save_attempts(path, [decide("first", "001", "AD", "passed"),
                                    decide("second", "001", "AD", "passed")])
        assert record.graded_runs(path) == ["second", "first"]
        assert record.graded_runs(path, keep=1) == ["second"]


# --------------------------------------------------------- the thresholds -

class TestThresholds:
    def test_nothing_listed_is_nothing_to_say(self, course):
        assert course_mod.thresholds("Test") == {}

    def test_a_listed_skill_comes_back(self, course, tmp_path):
        path = os.path.join(course_mod.path_for("Test"), "course.toml")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('\nAD = 2\n')
        assert course_mod.thresholds("Test") == {"AD": 2}

    @pytest.mark.parametrize("value", ["0", '"two"', "1.5", "-1", "true"])
    def test_a_value_that_is_not_a_count_is_refused(self, course, value):
        """`AD = 0` makes a skill impossible to pass. Reading it as 1
        would hide a typo in the one file a human edits by hand."""
        path = os.path.join(course_mod.path_for("Test"), "course.toml")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(f'\nAD = {value}\n')
        with pytest.raises(course_mod.CourseError, match="whole number"):
            course_mod.thresholds("Test")


# ------------------------------------------------------------ the grid ----

class TestTheGrid:
    def test_every_skill_in_the_bank_is_a_column(self, course):
        """Including the ones not offered yet: the empty columns are
        the shape of the term, and a grid that grew a column each
        time somebody sat something would never look the same twice."""
        out = gui_mod.api_progress(course, {})
        assert [s["slug"] for s in out["skills"]] == ["AD", "SU", "VR"]

    def test_a_skill_attempted_but_gone_from_the_bank_still_shows(
            self, course):
        """Otherwise the work disappears from the grid with nothing
        saying it did."""
        record.save_attempts(course.file("record"),
                             [decide("first", "001", "AD", "passed")])
        # A paper for a slug the bank does not have.
        record.save_attempts(course.file("record"),
                             [decide("first", "001", "OLD", "passed")])
        out = gui_mod.api_progress(course, {})
        assert "OLD" in [s["slug"] for s in out["skills"]]

    def test_a_dropped_student_is_not_a_row(self, course):
        out = gui_mod.api_progress(course, {})
        assert [s["name"] for s in out["students"]] == ["Ada Lovelace",
                                                        "Bo Peep"]

    def test_the_default_threshold_is_one(self, course):
        out = gui_mod.api_progress(course, {})
        assert {s["threshold"] for s in out["skills"]} == {1}

    def test_a_course_threshold_reaches_the_grid(self, course):
        path = os.path.join(course_mod.path_for("Test"), "course.toml")
        with open(path, "a", encoding="utf-8") as fh:
            fh.write('\nAD = 2\n')
        out = gui_mod.api_progress(course, {})
        by = {s["slug"]: s["threshold"] for s in out["skills"]}
        assert (by["AD"], by["SU"]) == (2, 1)

    def test_cells_are_keyed_by_student_then_skill(self, course):
        record.save_attempts(course.file("record"), [
            decide("first", "001", "AD", "passed"),
            decide("first", "001", "SU", "queried")])
        out = gui_mod.api_progress(course, {})
        assert out["cells"]["001"]["AD"]["passes"] == 1
        assert out["cells"]["001"]["SU"]["queries"] == 1

    def test_a_cell_says_which_run_the_pass_came_from(self, course):
        """"Recently passed" is about the passing run, not the last
        one: a student who passed in October and sat it again in
        November still passed in October."""
        record.save_attempts(course.file("record"), [
            decide("first", "001", "AD", "passed"),
            decide("second", "001", "AD", "failed")])
        out = gui_mod.api_progress(course, {})
        cell = out["cells"]["001"]["AD"]
        assert (cell["passedIn"], cell["last"]) == ("first", "failed")

    def test_nothing_attempted_is_an_empty_cells_map(self, course):
        out = gui_mod.api_progress(course, {})
        assert out["cells"] == {}
        assert len(out["students"]) == 2


# -------------------------------------------------------- the drill-in ----

class TestTheDrillIn:
    def test_it_lists_every_printing(self, course):
        out = gui_mod.api_progress_cell(course, {"sid": "001",
                                                 "slug": "AD"})
        assert [p["runId"] for p in out["papers"]] == ["first", "second"]

    def test_a_request_with_no_cell_is_refused(self, course):
        with pytest.raises(gui_mod.GuiError, match="which cell"):
            gui_mod.api_progress_cell(course, {"sid": "001"})

    def test_setting_a_result_records_it(self, course):
        out = gui_mod.api_progress_set(course, {
            "sid": "001", "slug": "AD", "runId": "first",
            "outcome": "passed"})
        assert out["papers"][0]["outcome"] == "passed"

    def test_it_returns_the_history_so_the_page_need_not_ask(self, course):
        out = gui_mod.api_progress_set(course, {
            "sid": "001", "slug": "AD", "runId": "second",
            "outcome": "failed"})
        assert [p["outcome"] for p in out["papers"]] == ["", "failed"]

    def test_the_scanner_s_reading_is_kept_when_he_overrules_it(
            self, course):
        """He is overruling the call, not claiming the ink was
        different. Throwing the measurement away would lose the only
        evidence of why the reader said what it did."""
        record.save_attempts(course.file("record"), [
            decide("first", "001", "AD", "failed", page=4,
                   reading="empty", ink=0.001)])
        gui_mod.api_progress_set(course, {
            "sid": "001", "slug": "AD", "runId": "first",
            "outcome": "passed"})
        row = record.attempts_for(course.file("record"), "001")[0]
        assert (row["outcome"], row["run_page"], row["reading"]) == (
            "passed", 4, "empty")

    def test_a_paper_never_printed_for_them_is_refused(self, course):
        """Not written and reported, as in a scan: here there is no
        stack and no index, just a request naming a pairing that
        does not exist. That is a bug, not a disagreement."""
        with pytest.raises(gui_mod.GuiError, match="never printed"):
            gui_mod.api_progress_set(course, {
                "sid": "002", "slug": "SU", "runId": "first",
                "outcome": "passed"})

    def test_an_outcome_nothing_can_read_is_refused(self, course):
        with pytest.raises(gui_mod.GuiError, match="is not an outcome"):
            gui_mod.api_progress_set(course, {
                "sid": "001", "slug": "AD", "runId": "first",
                "outcome": "maybe"})

    def test_a_request_missing_the_paper_is_refused(self, course):
        with pytest.raises(gui_mod.GuiError, match="which paper"):
            gui_mod.api_progress_set(course, {
                "sid": "001", "slug": "AD", "outcome": "passed"})

    def test_recording_by_hand_marks_the_run_graded(self, course):
        """The same table Scans writes, through the same function, so
        a decision typed here and one read off a stack are the same
        kind of thing."""
        gui_mod.api_progress_set(course, {
            "sid": "001", "slug": "AD", "runId": "first",
            "outcome": "passed"})
        graded = {r["run_id"]: r["graded"]
                  for r in record.runs(course.file("record"))}
        assert graded["first"] == 1
