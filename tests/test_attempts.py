"""What was decided about a paper, and what Progress reads back.

`printed` says a paper was handed out; `attempt` says what came of
it. The two are deliberately separate -- a build cannot know who was
in the room -- and the join between them is by (run, student, skill),
not by page, because a page is how a sheet is found and an attempt
is about the occasion.

Most of what is guarded here is a wrong answer that would look like
a right one: a second save stacking a duplicate instead of
correcting, a query counted as a pass, a decision written against a
student the browser named rather than the one the scanner read.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import gui as gui_mod
from checkit_printit import record
from checkit_printit import scans as scans_mod


def handout(sid, papers, name="Someone", version="A"):
    return {"sid": sid, "name": name, "section": "820",
            "version": version, "papers": papers}


@pytest.fixture
def db(tmp_path):
    """Two runs a fortnight apart, so "most recent" has a direction."""
    path = str(tmp_path / "record.db")
    record.write_run(
        path, run_id="first", title="Checkpoint", date="2026-10-01",
        built="2026-10-01T09:00:00", seed=1, output="/out/first", run_no=1,
        handouts=[handout("001", [("W1", 401), ("W2", 402)], "Ada"),
                  handout("002", [("W1", 403)], "Bo")])
    record.write_run(
        path, run_id="second", title="Checkpoint", date="2026-10-15",
        built="2026-10-15T09:00:00", seed=2, output="/out/second", run_no=2,
        handouts=[handout("001", [("W1", 411)], "Ada"),
                  handout("002", [("W1", 413)], "Bo")])
    return path


def decide(run_id, sid, slug, outcome, **kw):
    return {"run_id": run_id, "sid": sid, "slug": slug,
            "outcome": outcome, **kw}


# ------------------------------------------------------------ writing ----

class TestSaving:
    def test_it_writes_one_row_per_decision(self, db):
        written, unknown = record.save_attempts(db, [
            decide("first", "001", "W1", "passed", page=1, reading="ticked"),
            decide("first", "001", "W2", "failed", page=2, reading="empty")])
        assert (written, unknown) == (2, [])

    def test_nothing_to_save_is_not_an_error(self, db):
        assert record.save_attempts(db, []) == (0, [])

    def test_saving_again_corrects_rather_than_stacks(self, db):
        """He looks at the paper again and changes his mind. That is
        one attempt with a different answer, not a second attempt --
        and two rows would make Progress say he sat it twice."""
        record.save_attempts(db, [decide("first", "001", "W1", "failed")])
        record.save_attempts(db, [decide("first", "001", "W1", "passed")])
        rows = record.attempts_for(db, "001")
        assert [(r["slug"], r["outcome"]) for r in rows] == [("W1", "passed")]

    def test_the_same_paper_in_two_runs_is_two_attempts(self, db):
        """Which is the thing the upsert must not collapse."""
        record.save_attempts(db, [
            decide("first", "001", "W1", "failed"),
            decide("second", "001", "W1", "passed")])
        assert len(record.attempts_for(db, "001")) == 2

    def test_an_unscanned_paper_stores_no_page_and_no_reading(self, db):
        """NULL, not zero. "Page 0, no ink" is a reading; this is the
        absence of one, and a count of ink that was never measured
        would be a number somebody later averages."""
        record.save_attempts(db, [decide("first", "002", "W1", "absent")])
        row = record.attempts_for(db, "002")[0]
        assert row["page"] is None
        assert row["reading"] == ""
        assert row["ink"] is None

    def test_the_measurements_are_kept_beside_the_decision(self, db):
        """So a disagreement can be looked at rather than argued
        about, and a threshold that turns out wrong can be
        re-examined against what it was wrong on."""
        record.save_attempts(db, [
            decide("first", "001", "W1", "passed", page=7,
                   reading="unsure", ink=0.0061, beside=0.004)])
        row = record.attempts_for(db, "001")[0]
        assert (row["reading"], row["ink"], row["beside"]) == (
            "unsure", 0.0061, 0.004)


class TestGraded:
    def test_saving_marks_the_run_graded(self, db):
        record.save_attempts(db, [decide("first", "001", "W1", "passed")])
        graded = {r["run_id"]: r["graded"] for r in record.runs(db)}
        assert graded == {"first": 1, "second": 0}

    def test_every_run_in_the_batch_is_marked(self, db):
        """One stack routinely holds two assessments."""
        record.save_attempts(db, [
            decide("first", "001", "W1", "passed"),
            decide("second", "002", "W1", "failed")])
        assert all(r["graded"] for r in record.runs(db))

    def test_a_graded_run_can_no_longer_be_delisted(self, db):
        """The rule already in `set_flags`, reached through saving --
        which is the only way it will ever actually be reached."""
        record.save_attempts(db, [decide("first", "001", "W1", "passed")])
        with pytest.raises(record.RecordError, match="has been graded"):
            record.set_flags(db, "first", delisted=True)


class TestRefusals:
    def test_an_outcome_nothing_can_read_is_refused(self, db):
        """Not reported and carried on with: a value Progress has no
        branch for is not a decision, and writing it would put a row
        in the table that nothing downstream can render."""
        with pytest.raises(record.RecordError, match="is not an outcome"):
            record.save_attempts(db, [decide("first", "001", "W1", "maybe")])

    def test_a_run_that_does_not_exist_is_refused(self, db):
        with pytest.raises(record.RecordError, match="no run called"):
            record.save_attempts(db, [decide("ghost", "001", "W1", "passed")])

    def test_a_refused_batch_writes_nothing(self, db):
        """All or none. A batch half written is worse than one
        refused, because the half is invisible."""
        with pytest.raises(record.RecordError):
            record.save_attempts(db, [
                decide("first", "001", "W1", "passed"),
                decide("first", "001", "W2", "maybe")])
        assert record.attempts_for(db, "001") == []

    def test_a_paper_never_printed_is_reported_and_still_written(self, db):
        """The index and the record disagreeing is worth saying out
        loud. Losing a hundred decisions over one strange row is the
        worse trade, and the decision is his, not the index's."""
        written, unknown = record.save_attempts(db, [
            decide("first", "001", "W1", "passed"),
            decide("first", "009", "W9", "passed")])
        assert written == 2
        assert unknown == [("first", "009", "W9")]


# ------------------------------------------------------------ reading ----

class TestAStudentsHistory:
    def test_it_comes_back_oldest_first(self, db):
        record.save_attempts(db, [
            decide("second", "001", "W1", "passed"),
            decide("first", "001", "W1", "failed")])
        assert [r["date"] for r in record.attempts_for(db, "001")] == [
            "2026-10-01", "2026-10-15"]

    def test_it_carries_the_seed_the_paper_was_drawn_at(self, db):
        """"W1, 1 October, seed 401, not passed" without three more
        queries -- and the seed is how that exact paper is found
        again."""
        record.save_attempts(db, [decide("first", "001", "W1", "failed")])
        row = record.attempts_for(db, "001")[0]
        assert (row["seed"], row["version"], row["title"]) == (
            401, "A", "Checkpoint")

    def test_a_student_with_no_attempts_is_empty_not_an_error(self, db):
        assert record.attempts_for(db, "001") == []

    def test_an_absent_database_is_empty_not_an_error(self, tmp_path):
        missing = str(tmp_path / "nothing.db")
        assert record.attempts_for(missing, "001") == []
        assert record.progress(missing) == []


class TestProgress:
    def rows(self, db):
        return {(r["sid"], r["slug"]): r for r in record.progress(db)}

    def test_it_counts_attempts_and_passes(self, db):
        record.save_attempts(db, [
            decide("first", "001", "W1", "failed"),
            decide("second", "001", "W1", "passed")])
        row = self.rows(db)[("001", "W1")]
        assert (row["attempts"], row["passes"]) == (2, 1)

    def test_a_query_is_an_attempt_and_is_not_a_pass(self, db):
        """A "?" beside the box is a paper still in question.
        Calling it either way would decide something he deliberately
        did not."""
        record.save_attempts(db, [decide("first", "001", "W1", "queried")])
        row = self.rows(db)[("001", "W1")]
        assert (row["attempts"], row["passes"], row["queries"]) == (1, 0, 1)

    def test_absent_is_an_attempt_that_is_not_a_pass(self, db):
        """It is a recorded occasion -- the paper was printed and he
        said what happened -- so it counts, the way a blank paper
        counts."""
        record.save_attempts(db, [decide("first", "002", "W1", "absent")])
        row = self.rows(db)[("002", "W1")]
        assert (row["attempts"], row["passes"]) == (1, 0)

    def test_last_is_the_most_recent_by_date_not_by_insertion(self, db):
        """Saved out of order, because a stack can hold two
        assessments and nothing says which is read first."""
        record.save_attempts(db, [
            decide("second", "001", "W1", "failed"),
            decide("first", "001", "W1", "passed")])
        assert self.rows(db)[("001", "W1")]["last"] == "failed"

    def test_a_skill_nobody_attempted_is_simply_absent(self, db):
        """Progress draws every skill in the bank; which ones have a
        row here is what tells it which cells are empty."""
        record.save_attempts(db, [decide("first", "001", "W1", "passed")])
        assert ("001", "W2") not in self.rows(db)

    def test_students_do_not_bleed_into_each_other(self, db):
        record.save_attempts(db, [
            decide("first", "001", "W1", "passed"),
            decide("first", "002", "W1", "failed")])
        rows = self.rows(db)
        assert rows[("001", "W1")]["passes"] == 1
        assert rows[("002", "W1")]["passes"] == 0


# ------------------------------------------------------- review rows ----

class TestOneRowPerPaper:
    """A row is a paper, not a sheet.

    `batch.placed` holds every placed sheet, and a real stack has
    the same sheet in it more than once often enough that
    `duplicates` is one of the three questions the batch answers.
    Built per sheet, the grid showed one paper twice under one id:
    eleven rows for ten papers, and `setOutcome` -- which finds by
    id -- decided only the first of the pair.
    """

    def sheet(self, page, call, at=1, source="copier-1.pdf",
              kind="student"):
        """A placed sheet whose box reads `call`.

        `measure` is stubbed per test rather than drawing an image:
        what is under test here is the grouping, and a real crop
        would make these tests about the reader instead.
        """
        from checkit_printit import pageindex
        entry = pageindex.Page(
            page=page, kind=kind, sid="001" if kind == "student" else "",
            slug="W1", vseed="401", sheet=1, marks={})
        return scans_mod.Sheet(
            source=source, at=at, status="placed", run_no=1, page=page,
            entry=entry, code=f"C1-1-{page}", cuts={"box": call})

    @pytest.fixture
    def measured(self, monkeypatch):
        """`measure` returns whatever the cut "image" says it is."""
        monkeypatch.setattr(
            gui_mod.scans_mod, "measure",
            lambda cut: {"call": cut, "inside": 0.03, "beside": 0.0})
        monkeypatch.setattr(gui_mod, "_as_jpeg", lambda img: f"jpeg:{img}")

    def rows(self, sheets):
        batch = scans_mod.Batch(sheets=sheets)
        return gui_mod._review_rows(batch, "/no/such/record.db", {})

    def test_one_sheet_is_one_row(self, measured):
        rows = self.rows([self.sheet(1, "ticked")])
        assert [r["id"] for r in rows] == ["1-1"]
        assert rows[0]["outcome"] == "passed"

    def test_the_same_paper_twice_is_still_one_row(self, measured):
        rows = self.rows([self.sheet(1, "ticked"),
                          self.sheet(1, "ticked", at=6)])
        assert [r["id"] for r in rows] == ["1-1"]

    def test_both_squares_are_carried(self, measured):
        """He is agreeing with the paper. When there are two
        pictures of it, he gets two."""
        rows = self.rows([self.sheet(1, "ticked"),
                          self.sheet(1, "ticked", at=6)])
        assert len(rows[0]["crops"]) == 2

    def test_copies_that_agree_still_suggest(self, measured):
        rows = self.rows([self.sheet(1, "ticked"),
                          self.sheet(1, "ticked", at=6)])
        assert (rows[0]["read"], rows[0]["outcome"]) == ("ticked", "passed")

    def test_copies_that_disagree_suggest_nothing(self, measured):
        """A double feed that lost a tick. One of the two is wrong,
        and which one is a question for somebody holding the paper
        -- so the row goes into "needs you" with no answer filled
        in."""
        rows = self.rows([self.sheet(1, "ticked"),
                          self.sheet(1, "empty", at=6)])
        assert (rows[0]["read"], rows[0]["outcome"]) == ("", "")
        assert len(rows[0]["crops"]) == 2

    def test_different_papers_stay_different_rows(self, measured):
        rows = self.rows([self.sheet(1, "ticked"), self.sheet(2, "empty")])
        assert sorted(r["id"] for r in rows) == ["1-1", "1-2"]

    def test_an_answer_key_is_not_a_row(self, measured):
        """A key travels with the handouts and lands in the stack as
        an ordinary accident. Recording one would invent a
        student's work."""
        assert self.rows([self.sheet(3, "ticked", kind="key")]) == []


# ----------------------------------------------------------- endpoint ----

class TestTheSaveEndpoint:
    """The browser sends judgment and nothing else.

    Which student, which skill, which page and what was measured all
    come from the server's own copy of the read. A page that has been
    reloaded, edited or simply gone stale then cannot attach a
    decision to a different student -- which is the one mistake here
    that nobody would ever notice.
    """

    @pytest.fixture
    def course(self, tmp_path, monkeypatch, db):
        from checkit_printit import course as course_mod
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("Test", bank="", adopt=None)
        # The fixture's record, where the course keeps its own.
        import shutil
        shutil.copy(db, course_mod.file_in("Test", "record"))
        return gui_mod.Course("Test")

    @pytest.fixture
    def read(self, monkeypatch):
        """A finished read sitting in the server, as after a scan."""
        result = {"review": [
            {"id": "1-1", "run": 1, "page": 1, "sid": "001", "name": "Ada",
             "skill": "W1", "scanned": True, "crops": ["x"],
             "read": "ticked", "ink": 0.03, "beside": 0.0,
             "outcome": "passed"},
            {"id": "1-2", "run": 1, "page": 2, "sid": "001", "name": "Ada",
             "skill": "W2", "scanned": True, "crops": ["x"],
             "read": "empty", "ink": 0.0, "beside": 0.0,
             "outcome": "failed"},
            {"id": "1-3", "run": 1, "page": 3, "sid": "002", "name": "Bo",
             "skill": "W1", "scanned": False, "crops": [],
             "read": "", "ink": 0, "beside": 0, "outcome": ""},
        ]}
        monkeypatch.setattr(gui_mod.SCANNING, "result", result)
        return result

    def test_it_saves_what_was_decided(self, course, read):
        out = gui_mod.api_scan_save(course, {"decisions": [
            {"id": "1-1", "outcome": "passed"},
            {"id": "1-2", "outcome": "failed"}]})
        assert out["saved"] == 2
        assert out["runs"] == ["first"]

    def test_the_browser_cannot_name_the_student(self, course, read):
        """The decision carries an id and an outcome. Everything else
        is looked up. A page sending a different sid changes
        nothing, because it is never asked for one."""
        gui_mod.api_scan_save(course, {"decisions": [
            {"id": "1-1", "outcome": "passed",
             "sid": "999", "slug": "W9", "page": 77, "ink": 1.0}]})
        rows = record.attempts_for(course.file("record"), "999")
        assert rows == [], "the browser's sid reached the database"
        mine = record.attempts_for(course.file("record"), "001")
        assert [(r["slug"], r["page"], r["ink"]) for r in mine] == [
            ("W1", 1, 0.03)]

    def test_a_paper_with_no_decision_is_skipped(self, course, read):
        """Not the same as `absent`, which is a decision: "no paper
        came and I am recording that"."""
        out = gui_mod.api_scan_save(course, {"decisions": [
            {"id": "1-1", "outcome": "passed"},
            {"id": "1-3", "outcome": ""}]})
        assert out["saved"] == 1

    def test_an_unscanned_paper_saves_without_a_page(self, course, read):
        gui_mod.api_scan_save(course, {"decisions": [
            {"id": "1-3", "outcome": "absent"}]})
        row = record.attempts_for(course.file("record"), "002")[0]
        assert (row["page"], row["reading"], row["ink"]) == (None, "", None)

    def test_an_outcome_nothing_can_read_is_refused(self, course, read):
        with pytest.raises(gui_mod.GuiError, match="is not an outcome"):
            gui_mod.api_scan_save(course, {"decisions": [
                {"id": "1-1", "outcome": "maybe"}]})

    def test_nonsense_is_refused_even_for_a_row_that_is_not_here(
            self, course, read):
        """A decision for an id the read does not have is dropped
        below, so the record never sees it. Without the check at the
        top, a stale page could send anything at all and be told it
        had been saved."""
        with pytest.raises(gui_mod.GuiError, match="is not an outcome"):
            gui_mod.api_scan_save(course, {"decisions": [
                {"id": "9-99", "outcome": "maybe"}]})

    def test_deciding_nothing_is_refused(self, course, read):
        with pytest.raises(gui_mod.GuiError, match="nothing was decided"):
            gui_mod.api_scan_save(course, {"decisions": []})

    def test_no_stack_in_hand_says_to_read_it_again(self, course,
                                                    monkeypatch):
        """The read lives in memory, so a restart between scanning
        and saving loses it. Refused and said plainly -- the
        alternative is taking the page's word for whose paper was
        whose."""
        monkeypatch.setattr(gui_mod.SCANNING, "result", None)
        with pytest.raises(gui_mod.GuiError, match="Read the PDFs again"):
            gui_mod.api_scan_save(course, {"decisions": [
                {"id": "1-1", "outcome": "passed"}]})

    def test_a_run_this_course_does_not_have_is_named(self, course,
                                                      monkeypatch):
        """A code from another course, or a run since deleted. The
        decision has nowhere to go, so it is reported rather than
        dropped in silence."""
        monkeypatch.setattr(gui_mod.SCANNING, "result", {"review": [
            {"id": "9-1", "run": 9, "page": 1, "sid": "001", "name": "Ada",
             "skill": "W1", "scanned": True, "crops": ["x"],
             "read": "ticked", "ink": 0.03, "beside": 0.0,
             "outcome": "passed"}]})
        out = gui_mod.api_scan_save(course, {"decisions": [
            {"id": "9-1", "outcome": "passed"}]})
        assert out["saved"] == 0
        assert out["noRun"] == [9]
