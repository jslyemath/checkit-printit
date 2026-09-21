"""The print record.

What it says is "this paper was handed out", never "this was attempted" --
a build cannot know who was in the room. Outcomes are a later stage with a
table of their own, and until then the wording has to stay honest.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import record


def handout(sid, name, papers, version="A", section="820"):
    return {"sid": sid, "name": name, "section": section,
            "version": version, "papers": papers}


ONE_RUN = [
    handout("806000001", "Ada Lovelace", [("W1", 511), ("D1", 420)]),
    handout("806000002", "Alan Turing", [("W1", 802)], version="B"),
]


@pytest.fixture
def db(tmp_path):
    return str(tmp_path / "record.db")


def write(db, run_id="out-1", date="2026-09-18", handouts=None, **kw):
    return record.write_run(
        db, run_id=run_id, title=kw.get("title", "Skill Checkpoint"),
        date=date, built="2026-09-18T10:00:00", seed=kw.get("seed", 613),
        output=f"/out/{run_id}",
        handouts=ONE_RUN if handouts is None else handouts,
        extras=kw.get("extras", 0))


class TestWriting:
    def test_one_row_per_paper_not_per_student(self, db):
        rows, _ = write(db)
        assert rows == 3

    def test_the_database_is_created_on_first_write(self, tmp_path):
        path = str(tmp_path / "deeper" / "record.db")
        write(path)
        assert os.path.isfile(path)

    def test_reading_an_absent_database_is_empty_not_an_error(self, tmp_path):
        missing = str(tmp_path / "nothing.db")
        assert record.runs(missing) == []
        assert record.for_student(missing, "806000001") == []
        assert record.times_printed(missing, "806000001") == {}

    def test_a_handout_with_no_id_is_counted_but_not_attributed(self, db):
        """Printing with names off cannot say who received what, and inventing
        an owner would be worse than admitting it."""
        rows, unnamed = write(db, handouts=ONE_RUN + [
            handout("", "Blank", [("W1", 999)])])
        assert rows == 3 and unnamed == 1
        assert record.runs(db)[0]["unnamed"] == 1

    def test_rebuilding_the_same_folder_replaces_rather_than_duplicates(self, db):
        """A run is identified by the folder it wrote. Building into it twice
        is one printing event recorded once."""
        write(db)
        write(db)
        assert len(record.runs(db)) == 1
        assert record.runs(db)[0]["papers"] == 3

    def test_a_different_folder_is_a_different_run(self, db):
        """Which is what a replay produces, correctly: a second printing."""
        write(db, run_id="out-1")
        write(db, run_id="out-2")
        assert len(record.runs(db)) == 2


class TestAsking:
    def test_what_a_student_was_handed(self, db):
        write(db)
        rows = record.for_student(db, "806000001")
        assert [(r["slug"], r["seed"]) for r in rows] == [("D1", 420), ("W1", 511)]

    def test_the_version_letter_is_kept(self, db):
        write(db)
        assert record.for_student(db, "806000002")[0]["version"] == "B"

    def test_counts_are_per_skill(self, db):
        write(db, run_id="out-1")
        write(db, run_id="out-2", date="2026-09-25")
        assert record.times_printed(db, "806000001") == {"D1": 2, "W1": 2}

    def test_counting_one_skill(self, db):
        write(db)
        assert record.times_printed(db, "806000001", "W1") == {"W1": 1}

    def test_a_student_with_nothing_printed(self, db):
        write(db)
        assert record.times_printed(db, "806009999") == {}

    def test_totals_per_skill_separate_papers_from_people(self, db):
        write(db, run_id="out-1")
        write(db, run_id="out-2", date="2026-09-25")
        totals = {r["slug"]: (r["papers"], r["students"])
                  for r in record.skill_totals(db)}
        assert totals["W1"] == (4, 2), "four papers, but only two students"

    def test_runs_come_back_oldest_first(self, db):
        """Named so alphabetical order is the opposite of date order: GROUP BY
        alone returns them by run_id, which made an earlier version of this
        test pass without any ORDER BY at all."""
        write(db, run_id="a-october", date="2026-10-01")
        write(db, run_id="z-september", date="2026-09-01")
        assert [r["run_id"] for r in record.runs(db)] == \
            ["z-september", "a-october"]

    def test_a_run_remembers_its_seed_so_it_can_be_found_again(self, db):
        write(db, seed=918)
        assert record.runs(db)[0]["seed"] == 918


class TestWhatTheBuildHandsOver:
    """The record is only as good as what assemble reports, and nothing else
    here goes through assemble."""

    def build(self, bank_dir, tmp_path):
        import random
        from checkit_printit import assemble as assemble_mod, seating, theme
        from checkit_printit.publication import Publication
        from checkit_printit.roster import Roster, Student

        chart = tmp_path / "s.toml"
        chart.write_text('[[group]]\nseats = ["Ada Lovelace", "Alan Turing"]\n',
                         encoding="utf-8")
        roster = Roster([
            Student(name="Ada Lovelace", skills=["AD"], sid="806000001",
                    section="820"),
            Student(name="Alan Turing", skills=["AD"], sid="806000002",
                    section="820"),
        ])
        source, _ = theme.load(bank_dir)
        return assemble_mod.assemble(
            Publication(bank_path=bank_dir, title="T", date="2026-09-18"),
            roster, seating.load(str(chart)), str(tmp_path / "out"), source,
            rng=random.Random(1), run_seed=5)

    def test_every_handout_carries_the_student_id(self, bank_dir, tmp_path):
        """Without it the record cannot attribute a paper, and joining back on
        a name would reintroduce the thing ids exist to avoid."""
        report = self.build(bank_dir, tmp_path)
        assert [h["sid"] for h in report["handouts"]] == \
            ["806000001", "806000002"]

    def test_every_handout_carries_its_version_letter(self, bank_dir, tmp_path):
        report = self.build(bank_dir, tmp_path)
        assert [h["version"] for h in report["handouts"]] == ["A", "B"]

    def test_the_report_can_be_recorded_as_it_stands(self, bank_dir, tmp_path):
        report = self.build(bank_dir, tmp_path)
        path = str(tmp_path / "record.db")
        rows, unnamed = record.write_run(
            path, run_id="out", title="T", date="2026-09-18",
            built="2026-09-18T10:00:00", seed=5, output="/out",
            handouts=report["handouts"])
        assert rows == 2 and unnamed == 0
        assert record.times_printed(path, "806000001") == {"AD": 1}
