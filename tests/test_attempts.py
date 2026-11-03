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


class TestARereadKnowsWhatIsSaved:
    """Reading a stack twice must not offer to save it twice.

    A re-read -- after finding a missing sheet, or just because --
    rebuilt every row knowing nothing, so the bar said "6 results
    not saved" about six already in the record. The save itself was
    harmless, an upsert over identical values; the count was a lie,
    and the one thing a save bar must be is true.
    """

    @pytest.fixture
    def saved(self, db):
        record.save_attempts(db, [
            decide("first", "001", "W1", "passed", page=1,
                   reading="ticked")])
        return db

    def rows(self, path, sheets):
        batch = scans_mod.Batch(sheets=sheets)
        return gui_mod._review_rows(batch, path, {})

    def sheet(self, page, call, sid="001", slug="W1"):
        from checkit_printit import pageindex
        entry = pageindex.Page(page=page, kind="student", sid=sid,
                               slug=slug, vseed="401", sheet=1, marks={})
        return scans_mod.Sheet(
            source="copier-1.pdf", at=1, status="placed", run_no=1,
            page=page, entry=entry, code=f"C1-1-{page}",
            cuts={"box": call})

    @pytest.fixture
    def measured(self, monkeypatch):
        monkeypatch.setattr(
            gui_mod.scans_mod, "measure",
            lambda cut: {"call": cut, "inside": 0.03, "beside": 0.0})
        monkeypatch.setattr(gui_mod, "_as_jpeg", lambda img: "jpeg")

    def test_a_saved_paper_comes_back_marked_saved(self, saved, measured):
        rows = self.rows(saved, [self.sheet(1, "ticked")])
        assert rows[0]["recorded"] == "passed"

    def test_an_unsaved_paper_carries_nothing(self, saved, measured):
        rows = self.rows(saved, [self.sheet(2, "ticked", slug="W2")])
        assert rows[0]["recorded"] == ""

    def test_the_record_wins_over_the_suggestion(self, db, measured):
        """He decided "not passed" on a paper the reader calls
        ticked. Re-reading must not quietly offer his own decision
        back to him as a change."""
        record.save_attempts(db, [decide("first", "001", "W1", "failed")])
        rows = self.rows(db, [self.sheet(1, "ticked")])
        assert (rows[0]["recorded"], rows[0]["outcome"]) == (
            "failed", "passed")

    def test_a_paper_whose_run_is_not_in_the_record_is_blank(
            self, saved, measured):
        """`run_by_no` finds nothing, so there is nothing to compare
        against -- and that must read as "not saved", not crash."""
        sheet = self.sheet(1, "ticked")
        sheet = scans_mod.Sheet(
            source=sheet.source, at=sheet.at, status="placed", run_no=77,
            page=1, entry=sheet.entry, code="C1-77-1", cuts=sheet.cuts)
        rows = self.rows(saved, [sheet])
        assert rows[0]["recorded"] == ""


class TestTheWholePageView:
    """`/api/scan/sheet` renders one scanned page on demand.

    It is the one endpoint that takes a **path** from the browser,
    which is the kind of thing that is fine until it is not. The
    read throws its page renders away -- a few hundred will not fit
    in memory -- so the file has to be opened again, and a request
    that names a file is a request that can name any file.
    """

    @pytest.fixture
    def course(self, tmp_path, monkeypatch):
        from checkit_printit import course as course_mod
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("Test", bank="", adopt=None)
        c = gui_mod.Course("Test")
        scans = os.path.join(c.path, "scans")
        os.makedirs(scans, exist_ok=True)
        from PIL import Image
        page = Image.new("RGB", (120, 160), "white")
        page.save(os.path.join(scans, "copier-1.pdf"), save_all=True,
                  append_images=[Image.new("RGB", (120, 160), "white")])
        return c

    def test_it_returns_the_page_as_an_image(self, course):
        out = gui_mod.api_scan_sheet(course, {
            "file": os.path.join(course.path, "scans", "copier-1.pdf"),
            "page": 2})
        assert out["page"] == 2
        assert out["file"] == "copier-1.pdf"
        assert out["image"].startswith("data:image/jpeg;base64,")

    def test_a_file_outside_the_scans_folder_is_refused(self, course,
                                                        tmp_path):
        """The browser names the file. Somewhere else on the disk is
        not this course's scans, whatever the request says."""
        other = tmp_path / "elsewhere.pdf"
        other.write_bytes(b"%PDF-1.4\n")
        with pytest.raises(gui_mod.GuiError, match="not a page from this"):
            gui_mod.api_scan_sheet(course, {"file": str(other), "page": 1})

    def test_climbing_out_with_dots_is_refused(self, course):
        sneaky = os.path.join(course.path, "scans", "..", "roster.toml")
        with pytest.raises(gui_mod.GuiError, match="not a page from this"):
            gui_mod.api_scan_sheet(course, {"file": sneaky, "page": 1})

    def test_no_file_at_all_is_refused(self, course):
        with pytest.raises(gui_mod.GuiError, match="not a page from this"):
            gui_mod.api_scan_sheet(course, {"page": 1})

    def test_a_page_the_file_does_not_have_is_refused(self, course):
        with pytest.raises(gui_mod.GuiError, match="has no page"):
            gui_mod.api_scan_sheet(course, {
                "file": os.path.join(course.path, "scans", "copier-1.pdf"),
                "page": 99})

    def test_a_file_that_has_gone_is_refused(self, course):
        gone = os.path.join(course.path, "scans", "nothing.pdf")
        with pytest.raises(gui_mod.GuiError, match="not there any more"):
            gui_mod.api_scan_sheet(course, {"file": gone, "page": 1})


# ----------------------------------------------------------- endpoint ----

class TestTheSaveEndpoint:
    """The page may correct the student. It may not invent one.

    Which page, and what was measured on it, still come only from the
    server's own copy of the read. The student does not: re-matching
    a paper is the one case where the page knows something the server
    does not, and while the server ignored it every re-match was
    thrown away on save and every hand-matched page written nowhere
    at all, both reporting success.

    So a decision may name a student -- and is taken only where the
    print record says that student was handed that skill in that run.
    A stale page still cannot attach a decision to somebody who was
    never given the paper, which is the mistake nobody would notice.
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

    def test_the_browser_cannot_invent_a_student(self, course, read):
        """A sid nobody was printed anything for is refused outright.

        It used to be ignored, and that silence is what made the bug
        above possible: a correction and an invention looked the same
        from here, so both were dropped. Refusing says which.
        """
        with pytest.raises(gui_mod.GuiError, match="did not print"):
            gui_mod.api_scan_save(course, {"decisions": [
                {"id": "1-1", "outcome": "passed",
                 "sid": "999", "skill": "W9", "run": 1}]})
        path = course.file("record")
        assert record.attempts_for(path, "999") == [], (
            "the browser's sid reached the database")
        assert record.attempts_for(path, "001") == [], (
            "the rest of the save went in anyway")

    def test_the_page_may_still_say_nothing(self, course, read):
        """An ordinary decision names no student, and the server's
        own answer stands. This is every row he has not re-matched."""
        gui_mod.api_scan_save(course, {"decisions": [
            {"id": "1-1", "outcome": "passed"}]})
        mine = record.attempts_for(course.file("record"), "001")
        assert [(r["slug"], r["page"], r["ink"]) for r in mine] == [
            ("W1", 1, 0.03)]

    def test_a_rematch_reaches_the_record(self, course, read):
        """The whole point. Ada's W1 is really Bo's, and Bo was handed
        a W1 in that run, so the mark goes to Bo."""
        gui_mod.api_scan_save(course, {"decisions": [
            {"id": "1-1", "outcome": "passed",
             "sid": "002", "skill": "W1", "run": 1}]})
        path = course.file("record")
        assert [r["slug"] for r in record.attempts_for(path, "002")] == ["W1"]
        assert record.attempts_for(path, "001") == [], (
            "the mark stayed on the student the code named")

    def test_a_rematch_to_a_paper_they_never_had_is_refused(self, course,
                                                            read):
        """Bo was printed W1 in that run and not W2. A paper cannot be
        moved to somebody who was never given that skill, however much
        the handwriting looks like theirs."""
        with pytest.raises(gui_mod.GuiError, match="did not print"):
            gui_mod.api_scan_save(course, {"decisions": [
                {"id": "1-2", "outcome": "passed",
                 "sid": "002", "skill": "W2", "run": 1}]})
        assert record.attempts_for(course.file("record"), "002") == []

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

    @pytest.fixture
    def loose(self, monkeypatch):
        """One page in the stack that the reader could not place."""
        class Sheet:
            source = "/anywhere/copier-2.pdf"
            at = 7
            placed = False
        monkeypatch.setattr(gui_mod.SCANNING, "sheets", [Sheet()])

    def test_a_page_matched_by_hand_is_written(self, course, read, loose):
        """It has no row in the read -- the reader never placed it --
        so nothing finds it by id. It is found by the file and page it
        came from, which the server knows from its own sheets."""
        out = gui_mod.api_scan_save(course, {"decisions": [
            {"id": "hand-copier-2.pdf-7", "outcome": "passed",
             "sid": "002", "skill": "W1", "run": 1,
             "file": "copier-2.pdf", "page": 7, "byHand": True}]})
        assert out["saved"] == 1
        row = record.attempts_for(course.file("record"), "002")[0]
        # No page in the job and no reading: there was no box to read.
        assert (row["slug"], row["page"], row["reading"]) == ("W1", None, "")

    def test_a_hand_match_not_in_the_stack_is_refused(self, course, read,
                                                      loose):
        """A page the server never saw is a page it cannot vouch for."""
        with pytest.raises(gui_mod.GuiError, match="not in the stack"):
            gui_mod.api_scan_save(course, {"decisions": [
                {"id": "hand-copier-9.pdf-3", "outcome": "passed",
                 "sid": "002", "skill": "W1", "run": 1,
                 "file": "copier-9.pdf", "page": 3, "byHand": True}]})

    def test_a_hand_match_to_a_paper_they_never_had_is_refused(
            self, course, read, loose):
        with pytest.raises(gui_mod.GuiError, match="did not print"):
            gui_mod.api_scan_save(course, {"decisions": [
                {"id": "hand-copier-2.pdf-7", "outcome": "passed",
                 "sid": "002", "skill": "W2", "run": 1,
                 "file": "copier-2.pdf", "page": 7, "byHand": True}]})
        assert record.attempts_for(course.file("record"), "002") == []

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


class TestTheRowsOwnPictureOfTheBox:
    """The crop the row shows, cut round the box that was found.

    Four margins, not one. The instructor's `?` sits to the *right*
    of the box and reaches 0.60 to 0.89 box-widths out, so a flat
    0.45 on every side cut all six of them in half -- which is what
    he reported. The left stays tight because the skill slug is
    printed there.

    What is guarded here is the way four numbers go wrong: in the
    wrong order. A transposed pair leaves the picture the same total
    size, so nothing else in the suite would notice.
    """

    def crop(self):
        from PIL import Image
        return Image.new("RGB", (400, 300), (255, 255, 255))

    def test_the_right_margin_is_the_widest(self):
        """Or a question mark beside the box is cut off."""
        left, top, right, bottom = gui_mod.SHOT_MARGIN
        assert right > left
        assert right > top
        assert right > bottom

    def test_it_clears_the_widest_question_mark_measured(self):
        """0.89 box-widths, on the 2026-10-26 stack."""
        assert gui_mod.SHOT_MARGIN[2] > 0.89

    def test_each_margin_goes_to_its_own_side(self):
        """The transposition test.

        Asserted as where the box ends up rather than how big the
        picture is: the size is the same whichever way a pair is
        swapped, so it cannot see the mistake. Where the box sits
        can. With more room to the right than the left the box is
        left of centre, and with more above than below it is low.

        Not written as the arithmetic `_tight` does -- a test that
        recomputes the thing it is checking agrees with any bug in
        it, and the first draft of this one did exactly that and
        failed, because each edge rounds on its own.
        """
        painted = self.crop()
        got = gui_mod._tight(painted, {"box": (100, 100, 150, 150)})
        left, top, right, bottom = gui_mod.SHOT_MARGIN
        # Where the box's own middle landed inside the picture.
        across = (125 - round(100 - 50 * left)) / got.width
        down = (125 - round(100 - 50 * top)) / got.height
        assert right > left and across < 0.5
        assert top > bottom and down > 0.5

    def test_a_box_near_an_edge_is_not_asked_for_pixels_that_are_not_there(self):
        """The crop is clamped to the picture, so a box in the corner
        comes back smaller rather than raising."""
        got = gui_mod._tight(self.crop(), {"box": (2, 2, 52, 52)})
        assert got.width > 0 and got.height > 0

    def test_no_box_means_the_whole_crop(self):
        """Nothing to centre on, and the reading failed -- which is
        exactly when he should see everything there was to look at."""
        whole = self.crop()
        assert gui_mod._tight(whole, {"box": None}).size == whole.size


class TestASecondStackJoinsTheFirst:
    """The copier mails a tray at a time.

    So a run arrives as two or three PDFs over ten minutes, and the
    second read has to add to the first. Replacing it is wrong in the
    direction that costs most: the missing list would name students
    whose papers are sitting in the file read first, and those are
    exactly the students who would then be chased for work they handed
    in.
    """

    class Leaf:
        """Enough of a `Sheet` for the joining: where it came from."""

        def __init__(self, source, tag):
            self.source, self.tag = source, tag

        def __repr__(self):
            return f"<{self.tag}>"

    def leaves(self, source, *tags):
        return [self.Leaf(source, tag) for tag in tags]

    def test_pages_from_a_new_file_are_added_to_what_was_there(self):
        was = self.leaves("/scans/tray1.pdf", "a", "b")
        now = self.leaves("/scans/tray2.pdf", "c")
        got = gui_mod._joined(was, now, ["/scans/tray2.pdf"])
        assert [s.tag for s in got] == ["a", "b", "c"]

    def test_reading_a_file_again_replaces_its_pages(self):
        """Not doubles them. Dropping the same stack twice is a slip,
        and the duplicates table is for paper that really did go
        through the feeder twice -- burying that under self-inflicted
        pairs would make the one signal worth having useless."""
        was = (self.leaves("/scans/tray1.pdf", "a", "b")
               + self.leaves("/scans/tray2.pdf", "c"))
        now = self.leaves("/scans/tray1.pdf", "a2", "b2", "extra")
        got = gui_mod._joined(was, now, ["/scans/tray1.pdf"])
        assert [s.tag for s in got] == ["c", "a2", "b2", "extra"]

    def test_the_very_first_read_starts_from_nothing(self):
        got = gui_mod._joined([], self.leaves("/scans/one.pdf", "a"),
                              ["/scans/one.pdf"])
        assert [s.tag for s in got] == ["a"]

    def test_file_names_keep_the_order_they_were_first_read_in(self):
        order = gui_mod._file_order([], ["/scans/b.pdf", "/scans/a.pdf"])
        order = gui_mod._file_order(order, ["/scans/c.pdf"])
        assert order == ["b.pdf", "a.pdf", "c.pdf"]

    def test_a_file_read_twice_is_still_listed_once(self):
        order = gui_mod._file_order(["b.pdf"], ["/scans/b.pdf"])
        assert order == ["b.pdf"]

    def test_clearing_forgets_the_pile(self):
        """There has to be a way to say "wrong stack". Without one the
        only way out of an accumulating read is to restart the
        server."""
        job = gui_mod.Scanning()
        job.sheets = self.leaves("/scans/tray1.pdf", "a")
        job.files, job.result = ["tray1.pdf"], {"counts": {}}
        job.clear()
        assert job.sheets == [] and job.files == [] and job.result is None

    def test_clearing_is_refused_while_a_read_is_running(self):
        """Half a pile is worse than either whole one: the thread
        would finish and join its sheets onto the empty list, so the
        instructor would be looking at one tray with a missing list
        built as though the others had never been read."""
        job = gui_mod.Scanning()
        job.running = True
        with pytest.raises(gui_mod.GuiError, match="being read right now"):
            job.clear()

    def test_the_status_says_how_much_is_in_the_pile(self):
        """The strip counts from this rather than from what was last
        dropped, because what was last dropped is one tray of three."""
        job = gui_mod.Scanning()
        job.sheets = self.leaves("/scans/tray1.pdf", "a", "b")
        job.files = ["tray1.pdf"]
        said = job.status()
        assert said["pages"] == 2 and said["files"] == ["tray1.pdf"]


class TestSavingAPaperMatchedByItsGrid:
    """A run printed without names: the footer code says which page it
    is, and nothing on the sheet says whose. The student comes from the
    nine digits they wrote in the header, which the server works out and
    puts in the row -- so by the time the browser sends a decision back,
    the student is the server's own answer and not a claim.

    Which matters, because `owner` treats a decision that names a
    *different* student as a re-match and refuses it unless the record
    says that pair was printed. A by-id row would be refused by that
    rule if the sid the page echoes were read as a correction, and the
    whole feature would fail at its last step while every part of it
    worked.
    """

    @pytest.fixture
    def course(self, tmp_path, monkeypatch, db):
        from checkit_printit import course as course_mod
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("Test", bank="", adopt=None)
        import shutil
        shutil.copy(db, course_mod.file_in("Test", "record"))
        return gui_mod.Course("Test")

    def read(self, monkeypatch, sid, skill):
        """A finished read holding one paper printed without a name.

        `unowned` stays true -- the *paper* carries nobody's name,
        which is a fact about the print job -- while `sid` is filled
        in, because the grid said who wrote on it.
        """
        result = {"review": [
            {"id": "1-9", "run": 1, "page": 9, "sid": sid, "name": "Ada",
             "skill": skill, "scanned": True, "crops": ["x"],
             "unowned": True, "byId": True, "sureOfId": -0.4,
             "read": "ticked", "ink": 0.03, "beside": 0.0,
             "outcome": "passed"}]}
        monkeypatch.setattr(gui_mod.SCANNING, "result", result)
        return result

    def test_the_student_the_grid_named_is_saved(self, course, monkeypatch):
        self.read(monkeypatch, "001", "W2")
        out = gui_mod.api_scan_save(course, {"decisions": [
            {"id": "1-9", "outcome": "passed",
             "sid": "001", "skill": "W2"}]})
        assert out["saved"] == 1
        assert out["unprinted"] == []
        rows = record.attempts_for(course.file("record"), "001")
        assert ("W2", "passed") in [(r["slug"], r["outcome"]) for r in rows]

    def test_a_spare_is_saved_and_reported_rather_than_refused(
            self, course, monkeypatch):
        """Somebody picked up a spare. A spare is printed with nobody
        assigned to it, so the record does not say that student was
        handed that skill in that job -- and that is the normal case
        for a spare, not a reason to throw the decision away.

        So it saves, and comes back under `unprinted` for him to see.
        """
        self.read(monkeypatch, "002", "W2")       # 002 was given W1 only
        out = gui_mod.api_scan_save(course, {"decisions": [
            {"id": "1-9", "outcome": "passed",
             "sid": "002", "skill": "W2"}]})
        assert out["saved"] == 1
        assert out["unprinted"] == [{"sid": "002", "skill": "W2"}]

    def test_naming_somebody_else_is_still_a_re_match(
            self, course, monkeypatch):
        """The grid can be misread, and then he corrects it -- which is
        a re-match like any other and goes through the printed check.
        Reading the id does not open a way round it."""
        self.read(monkeypatch, "001", "W2")
        with pytest.raises(gui_mod.GuiError):
            gui_mod.api_scan_save(course, {"decisions": [
                {"id": "1-9", "outcome": "passed",
                 "sid": "002", "skill": "W2", "run": 1}]})

    def test_a_grid_that_could_not_be_read_still_refuses(
            self, course, monkeypatch):
        """No sid in the row and none from the page: there is nobody to
        record it against, and a row with no student is a mark
        belonging to the whole class."""
        self.read(monkeypatch, "", "W2")
        with pytest.raises(gui_mod.GuiError):
            gui_mod.api_scan_save(course, {"decisions": [
                {"id": "1-9", "outcome": "passed"}]})


class TestARowWhoseStudentCameFromTheGrid:
    """What `_review_rows` makes of a paper printed without a name.

    The sheet carries `read_sid`, worked out from the nine digits in
    the header. The row has to carry a *name*, a section and the flag
    that rings the handwriting -- the same fields a paper with a
    printed code gets, so that the table does not need two ways of
    drawing a row.
    """

    @pytest.fixture
    def measured(self, monkeypatch):
        monkeypatch.setattr(
            gui_mod.scans_mod, "measure",
            lambda cut: {"call": cut, "inside": 0.03, "beside": 0.0})
        monkeypatch.setattr(gui_mod, "_as_jpeg", lambda img: f"jpeg:{img}")

    def sheet(self, sid="", read_sid="", read_score=None):
        """A placed sheet off a run printed without names.

        `entry.sid` is empty on such a page and always has been --
        `assemble` writes no student into the index for a blank-name
        handout, which is exactly why the grid has to be read at all.
        """
        from checkit_printit import pageindex
        entry = pageindex.Page(page=1, kind="student", sid=sid, slug="W1",
                               vseed="401", sheet=1, marks={})
        return scans_mod.Sheet(
            source="copier-1.pdf", at=1, status="placed", run_no=1, page=1,
            entry=entry, code="C1-1-1", cuts={"box": "ticked"},
            read_sid=read_sid, read_score=read_score)

    def rows(self, sheets, names=None, sections=None):
        return gui_mod._review_rows(
            scans_mod.Batch(sheets=sheets), "/no/such/record.db",
            names if names is not None else {}, sections)

    def test_the_read_id_becomes_the_row_s_student(self, measured):
        rows = self.rows([self.sheet(read_sid="001", read_score=-0.4)],
                         names={"001": "Ada Byron"},
                         sections={"001": "820"})
        assert rows[0]["sid"] == "001"
        assert rows[0]["name"] == "Ada Byron"
        assert rows[0]["section"] == "820", (
            "the section comes with the student, so it fills itself in")
        assert rows[0]["sureOfId"] == -0.4

    def test_it_sorts_under_the_surname_like_any_other_row(self, measured):
        """Not a separate kind of row. Once the student is known the
        paper is an ordinary paper, and the Scans table and the Roster
        have to put them in the same place."""
        rows = self.rows([self.sheet(read_sid="001")],
                         names={"001": "Ada Byron"})
        assert rows[0]["sort_last"].lower().startswith("byron")

    def test_the_handwriting_is_flagged_for_a_look(self, measured):
        """`byId` rings the handwritten name in warning yellow. Only
        on these rows: they are the only ones where the handwriting is
        the only check there is, every other row having a printed name
        to agree with -- and a highlight that is always on is not a
        highlight."""
        rows = self.rows([self.sheet(read_sid="001")], names={"001": "Ada"})
        assert rows[0]["byId"] is True

    def test_a_printed_code_is_not_flagged(self, measured):
        rows = self.rows([self.sheet(sid="001")], names={"001": "Ada"})
        assert rows[0]["byId"] is False
        assert rows[0]["sid"] == "001"

    def test_a_grid_nobody_could_read_leaves_the_row_blank(self, measured):
        """And blank is the point. The row shows a dash and a match
        button, and the save refuses it until he says whose it is;
        inventing somebody for him to catch would be worse, because
        the blank row is the one he looks at."""
        rows = self.rows([self.sheet()], names={"001": "Ada"})
        assert rows[0]["sid"] == ""
        assert rows[0]["name"] == ""
        assert rows[0]["byId"] is False
        assert rows[0]["unowned"] is True
