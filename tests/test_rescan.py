"""Putting a few corrected papers back through must not raise the job.

The instructor changed some "?" marks to ticks, fed those papers in,
and the Scans tab brought up the whole eighty-six-paper job they came
from as missing -- then flagged half of it as duplicate entries. Both
halves of that are tested here.

`_review_rows` and `_batch_json` had no tests at all, which is why
1,487 of them passed while this was happening.

**Real page-index files on disk, and the real resolver.** The first
version of this built fake index objects and handed them in, and three
of its tests passed while the absentee half of the table was empty:
`_review_rows` builds its own reader from the record, so the fakes
were never consulted. A fixture the code under test cannot see is a
fixture that proves nothing.
"""
import os

import pytest

from checkit_printit import gui as gui_mod
from checkit_printit import pageindex
from checkit_printit import record as record_mod
from checkit_printit import scans

RUN_OLD = 1          # graded three weeks ago
RUN_NEW = 2          # being scanned for the first time

#: The one '?' in the old run -- the paper he came back to fix.
QUERIED = 5

#: A paper of the old run that was never graded at all: handed out,
#: never scanned, never marked by hand.
#:
#: **It is what makes the run-level filter testable.** With every
#: paper of the old job recorded, the per-paper filter removes all of
#: them on its own, and a test asserting "the job does not come up"
#: passes with the run-level check deleted -- which is exactly what
#: the breakage harness found, twice. This page is recorded nowhere,
#: so only the run-level check can keep it out.
UNGRADED = 8


def write_index(folder, run_no, howmany, slug="N3"):
    """A real `main.pages`: a run header and one student page each.

    `page*kind*sid*slug*vseed*sheet`, which is the format `parse`
    reads. Written rather than mocked so the resolver, the reader and
    `Page.gradable` are all the real ones.
    """
    os.makedirs(folder, exist_ok=True)
    lines = [f"run*{run_no}"]
    for n in range(1, howmany + 1):
        lines.append(f"{n}*student*sid{run_no}{n:02d}*{slug}*100*1")
    with open(os.path.join(folder, pageindex.FILENAME), "w",
              encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return pageindex.load(folder)


@pytest.fixture
def world(tmp_path):
    """A record with two runs, their indexes, and the real resolver.

    The old run has eight papers and every one already decided -- one
    of them a '?'. The new run has four and nothing decided.
    """
    path = str(tmp_path / "record.db")
    folders = {RUN_OLD: str(tmp_path / "old"), RUN_NEW: str(tmp_path / "new")}
    old = write_index(folders[RUN_OLD], RUN_OLD, 8)
    new = write_index(folders[RUN_NEW], RUN_NEW, 4)

    for run_id, run_no, index in (("old", RUN_OLD, old),
                                  ("new", RUN_NEW, new)):
        record_mod.write_run(
            path, run_id=run_id, title=f"Job {run_no}",
            date="2026-10-26" if run_no == RUN_OLD else "2026-11-02",
            built="2026-10-26T09:00", seed=1, output=folders[run_no],
            handouts=[{"sid": e.sid, "name": f"Student {e.page}",
                       "section": "820", "version": "A",
                       "papers": [(e.slug, 100)]}
                      for e in index.pages.values()],
            run_no=run_no)

    record_mod.save_attempts(path, [
        {"run_id": "old", "sid": e.sid, "slug": e.slug,
         "outcome": "queried" if e.page == QUERIED else "passed",
         "page": e.page, "reading": "ticked"}
        for e in old.pages.values() if e.page != UNGRADED])

    resolve = scans.index_reader(path)
    assert resolve(RUN_OLD) is not None and resolve(RUN_NEW) is not None, \
        "the real resolver cannot find these runs, so nothing below is " \
        "testing the real path"
    return path, old, new, resolve


def sheet_for(run_no, entry, scan_page=1):
    return scans.Sheet(source="stack.pdf", scan_page=scan_page,
                       status="placed", run_no=run_no,
                       run_page=entry.page, entry=entry)


class TestARunBeingRescanned:
    """Its absentees are not questions. They were answered weeks ago."""

    def test_the_rest_of_the_job_does_not_come_up(self, world):
        path, old, _, resolve = world
        one_stray = scans.Batch(sheets=[sheet_for(RUN_OLD,
                                                  old.get(QUERIED))])

        # What the batch itself still says, which is the old behaviour.
        # Asserted so a filter that works because the cascade stopped
        # happening cannot pass this.
        assert one_stray.missing(resolve) == {RUN_OLD: [1, 2, 3, 4, 6, 7, 8]}

        pile = gui_mod._Pile(one_stray, path)
        assert pile.missing(resolve) == {}

    def test_an_ungraded_paper_in_an_old_job_stays_out_too(self, world):
        """The run-level check on its own.

        Page 8 of the old job was never graded, so the per-paper
        filter has no reason to drop it. What keeps it out is that the
        job is not being scanned for the first time -- he fed in one
        corrected paper, not the class. Without this the two filters
        are indistinguishable, and `missing` passed its own test with
        the run-level check deleted."""
        path, old, _, resolve = world
        one_stray = scans.Batch(sheets=[sheet_for(RUN_OLD,
                                                  old.get(QUERIED))])
        assert UNGRADED in one_stray.missing(resolve)[RUN_OLD], \
            "the fixture graded every paper, so this proves nothing"
        pile = gui_mod._Pile(one_stray, path)
        assert pile.recorded(RUN_OLD, old.get(UNGRADED).sid, "N3") == "", \
            "page 8 is supposed to have no result at all"
        assert pile.missing(resolve) == {}

    def test_a_first_time_run_still_reports_its_absentees(self, world):
        """The other half. Without this the test above would pass if
        `missing` had simply stopped answering."""
        path, _, new, resolve = world
        short = scans.Batch(sheets=[sheet_for(RUN_NEW, new.get(1))])
        pile = gui_mod._Pile(short, path)
        assert pile.missing(resolve) == {RUN_NEW: [2, 3, 4]}

    def test_a_settled_paper_is_not_asked_about_twice(self, world):
        """Inside a first-time run, a paper that already has a result
        is not a question either -- and one that does not, is."""
        path, _, new, resolve = world
        record_mod.save_attempts(path, [
            {"run_id": "new", "sid": new.get(3).sid, "slug": "N3",
             "outcome": "absent", "page": 3}])
        short = scans.Batch(sheets=[sheet_for(RUN_NEW, new.get(1))])
        pile = gui_mod._Pile(short, path)
        assert pile.missing(resolve) == {RUN_NEW: [2, 4]}

    def test_what_was_held_back_is_still_counted(self, world):
        """Dropped from the table, not from the page. A run short of
        papers is worth knowing about even when its rows are not
        worth answering, and a filter whose count quietly goes to
        zero is how a real shortage hides."""
        path, old, _, resolve = world
        one_stray = scans.Batch(sheets=[sheet_for(RUN_OLD,
                                                  old.get(QUERIED))])
        pile = gui_mod._Pile(one_stray, path)
        assert pile.held_back(resolve) == {RUN_OLD: 7}

    def test_nothing_is_held_back_from_a_first_time_run(self, world):
        path, _, new, resolve = world
        short = scans.Batch(sheets=[sheet_for(RUN_NEW, new.get(1))])
        pile = gui_mod._Pile(short, path)
        assert pile.held_back(resolve) == {}


class TestMarkingARescan:
    def test_a_paper_with_a_result_already_is_a_rescan(self, world):
        path, old, new, _ = world
        both = scans.Batch(sheets=[sheet_for(RUN_OLD, old.get(QUERIED)),
                                   sheet_for(RUN_NEW, new.get(1), 2)])
        pile = gui_mod._Pile(both, path)
        assert pile.is_rescan(RUN_OLD, QUERIED) is True
        assert pile.is_rescan(RUN_NEW, 1) is False

    def test_a_run_with_one_new_paper_is_first_time(self, world):
        path, old, new, _ = world
        both = scans.Batch(sheets=[sheet_for(RUN_OLD, old.get(QUERIED)),
                                   sheet_for(RUN_NEW, new.get(1), 2)])
        pile = gui_mod._Pile(both, path)
        assert pile.first_time == {RUN_NEW}


class TestTheReviewTable:
    """End to end, the shape he actually saw."""

    def names(self, path):
        return record_mod.names_printed(path)

    def rows_for(self, path, sheets):
        return gui_mod._review_rows(scans.Batch(sheets=sheets), path,
                                    self.names(path))

    def test_a_stray_sheet_makes_three_rows_not_eleven(self, world):
        path, old, new, _ = world
        rows = self.rows_for(path, [
            sheet_for(RUN_OLD, old.get(QUERIED)),
            sheet_for(RUN_NEW, new.get(1), 2),
            sheet_for(RUN_NEW, new.get(2), 3)])

        scanned = [r for r in rows if r["scanned"]]
        absent = [r for r in rows if not r["scanned"]]

        assert len(scanned) == 3, "every scanned paper is a row"
        # The new run is short of papers 3 and 4. The old run is short
        # of seven, and not one of them belongs here.
        assert sorted(r["page"] for r in absent) == [3, 4]
        assert {r["run"] for r in absent} == {RUN_NEW}
        assert len(rows) == 5

    def test_without_the_stray_the_table_is_the_same_size(self, world):
        """The stray sheet adds itself and nothing else. Run alongside
        the test above, this is what says the seven absentees are gone
        because of the filter rather than because of the fixture."""
        path, _, new, _ = world
        rows = self.rows_for(path, [sheet_for(RUN_NEW, new.get(1), 2),
                                    sheet_for(RUN_NEW, new.get(2), 3)])
        assert len(rows) == 4

    def test_the_rescanned_row_says_so(self, world):
        path, old, new, _ = world
        rows = self.rows_for(path, [sheet_for(RUN_OLD, old.get(QUERIED)),
                                    sheet_for(RUN_NEW, new.get(1), 2)])
        marked = {(r["run"], r["page"]): r["rescan"] for r in rows}
        assert marked[(RUN_OLD, QUERIED)] is True
        assert marked[(RUN_NEW, 1)] is False

    def test_every_row_names_its_assessment(self, world):
        path, old, new, _ = world
        rows = self.rows_for(path, [sheet_for(RUN_OLD, old.get(QUERIED)),
                                    sheet_for(RUN_NEW, new.get(1), 2)])
        assert {r["assessment"] for r in rows} == {"Job 1", "Job 2"}
        for row in rows:
            assert row["assessment"], \
                "a row with no assessment cannot say which job it " \
                "came from"

    def test_an_absentee_row_names_its_assessment_too(self, world):
        path, _, new, _ = world
        rows = self.rows_for(path, [sheet_for(RUN_NEW, new.get(1))])
        absent = [r for r in rows if not r["scanned"]]
        assert absent, "the fixture produced no absentee rows"
        assert {r["assessment"] for r in absent} == {"Job 2"}

    def test_every_row_carries_the_date_it_was_sat(self, world):
        """The title is only half of it. Two assessments can share a
        name -- the same skill set reprinted a fortnight later is the
        ordinary case -- so a row naming its title still cannot say
        which sitting the paper is from. He asked for the date after
        finding that out on his own stack."""
        path, old, new, _ = world
        rows = self.rows_for(path, [sheet_for(RUN_OLD, old.get(QUERIED)),
                                    sheet_for(RUN_NEW, new.get(1), 2)])
        by_run = {r["run"]: r["date"] for r in rows}
        assert by_run[RUN_OLD] == "2026-10-26"
        assert by_run[RUN_NEW] == "2026-11-02"

    def test_the_date_is_iso_so_the_column_can_sort(self, world):
        """Shown m/d and sorted on this. The two are not the same
        string and only one of them orders: "11/9" sorts after
        "11/12" as text, and the year the view drops is exactly what
        makes the comparison work."""
        path, old, new, _ = world
        rows = self.rows_for(path, [sheet_for(RUN_OLD, old.get(QUERIED)),
                                    sheet_for(RUN_NEW, new.get(1), 2)])
        for row in rows:
            assert len(row["date"]) == 10 and row["date"][4] == "-", \
                f"{row['date']!r} is not an ISO date"

    def test_an_absentee_row_carries_its_date_too(self, world):
        path, _, new, _ = world
        rows = self.rows_for(path, [sheet_for(RUN_NEW, new.get(1))])
        absent = [r for r in rows if not r["scanned"]]
        assert absent, "the fixture produced no absentee rows"
        assert {r["date"] for r in absent} == {"2026-11-02"}

    def test_the_corrected_query_keeps_its_recorded_answer(self, world):
        """The '?' he came to fix. The row has to arrive carrying what
        the record holds, so the table shows it as a correction rather
        than as a fresh read."""
        path, old, _, _ = world
        rows = self.rows_for(path, [sheet_for(RUN_OLD, old.get(QUERIED))])
        row = next(r for r in rows if r["page"] == QUERIED)
        assert row["recorded"] == "queried"


class TestTheJobCards:
    def test_a_rescanned_job_is_counted_and_not_called_short(self, world):
        path, old, new, _ = world
        batch = scans.Batch(sheets=[sheet_for(RUN_OLD, old.get(QUERIED)),
                                    sheet_for(RUN_NEW, new.get(1), 2)])
        out = gui_mod._batch_json(batch, path)
        cards = {r["no"]: r for r in out["runs"]}

        assert cards[RUN_OLD]["rescanned"] == 1
        assert cards[RUN_OLD]["firstTime"] is False
        assert cards[RUN_OLD]["settled"] == 7

        assert cards[RUN_NEW]["rescanned"] == 0
        assert cards[RUN_NEW]["firstTime"] is True
        assert cards[RUN_NEW]["settled"] == 0

        # And the missing list the cards count from carries only the
        # new run's absentees.
        assert {m["run"] for m in out["missing"]} == {RUN_NEW}
        assert len(out["missing"]) == 3
