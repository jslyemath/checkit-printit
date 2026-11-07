"""The print record.

What it says is "this paper was handed out", never "this was attempted" --
a build cannot know who was in the room. Outcomes are a later stage with a
table of their own, and until then the wording has to stay honest.
"""

import os
import shutil
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


class TestOneRunsDetail:
    """What the Runs tab draws when you open a run. Nothing new is
    stored for it -- every figure comes out of `printed`."""

    def test_it_counts_papers_and_students(self, db):
        write(db)
        d = record.run_detail(db, "out-1")
        assert d["papers"] == 3
        assert d["students"] == 2

    def test_it_groups_by_skill(self, db):
        write(db)
        got = {r["slug"]: (r["papers"], r["versions"])
               for r in record.run_detail(db, "out-1")["skills"]}
        assert got == {"W1": (2, 2), "D1": (1, 1)}

    def test_it_lists_each_version_s_seed(self, db):
        """The thing a reprint has to reproduce, and the thing Scans
        will match a scanned page against."""
        write(db)
        seeds = {(r["slug"], r["version"]): r["seed"]
                 for r in record.run_detail(db, "out-1")["seeds"]}
        assert seeds == {("W1", "A"): 511, ("W1", "B"): 802,
                         ("D1", "A"): 420}

    def test_an_unknown_run_is_none_not_an_empty_page(self, db):
        write(db)
        assert record.run_detail(db, "never-built") is None

    def test_no_database_at_all_is_none(self, tmp_path):
        assert record.run_detail(str(tmp_path / "nope.db"), "out-1") is None


class TestDelistingAndGrading:
    def test_a_fresh_run_is_neither(self, db):
        write(db)
        row = record.runs(db)[0]
        assert row["delisted"] == 0 and row["graded"] == 0

    def test_delisting_sticks(self, db):
        write(db)
        assert record.set_flags(db, "out-1", delisted=True)["delisted"] == 1
        assert record.runs(db)[0]["delisted"] == 1

    def test_a_flag_not_passed_is_left_alone(self, db):
        """Both are read off the row when the caller does not pass
        them, so setting one cannot silently clear the other."""
        write(db)
        record.set_flags(db, "out-1", delisted=True)
        after = record.set_flags(db, "out-1", delisted=True)
        assert after["delisted"] == 1 and after["graded"] == 0

    def test_grading_a_delisted_run_brings_it_back(self, db):
        """Not refused. The reason a graded run may not be delisted --
        that what was read back has to be findable -- applies just as
        much to one delisted before it was scanned, so the grade wins
        and the run returns to the list."""
        write(db)
        record.set_flags(db, "out-1", delisted=True)
        after = record.set_flags(db, "out-1", graded=True)
        assert after["graded"] == 1
        assert after["delisted"] == 0, "a graded run must be findable"

    def test_a_graded_run_cannot_be_delisted(self, db):
        """Refused in the record, not only in the view. The view is not
        the only caller, and a rule enforced in one place is a rule
        with a way round it."""
        write(db)
        record.set_flags(db, "out-1", graded=True)
        with pytest.raises(record.RecordError, match="graded"):
            record.set_flags(db, "out-1", delisted=True)

    def test_asking_for_both_at_once_is_refused(self, db):
        """Grading un-delists, but only as a consequence. Asking for
        both in one call is a contradiction and is named as one rather
        than silently resolved."""
        write(db)
        with pytest.raises(record.RecordError, match="cannot be delisted"):
            record.set_flags(db, "out-1", delisted=True, graded=True)

    def test_ungrading_is_always_allowed(self, db):
        """It is the undo of a mistake."""
        write(db)
        record.set_flags(db, "out-1", graded=True)
        assert record.set_flags(db, "out-1", graded=False)["graded"] == 0

    def test_an_unknown_run_says_so(self, db):
        write(db)
        with pytest.raises(record.RecordError, match="no run called"):
            record.set_flags(db, "nope", graded=True)


class TestTheMigration:
    """`CREATE TABLE IF NOT EXISTS` does nothing to a table that
    already exists, so a column added to SCHEMA alone would reach new
    courses only -- and the real course had three runs in it when
    these columns were added."""

    #: `run` as it stood before the two flags. Built by hand rather
    #: than by dropping columns: SQLite's DROP COLUMN chokes on the
    #: comments in the real SCHEMA, and a database written by the old
    #: code is what is actually being simulated.
    OLD_SCHEMA = """
    CREATE TABLE run (
        run_id  TEXT PRIMARY KEY,
        title   TEXT NOT NULL,
        date    TEXT NOT NULL,
        built   TEXT NOT NULL,
        seed    INTEGER NOT NULL,
        output  TEXT NOT NULL,
        extras  INTEGER NOT NULL DEFAULT 0,
        unnamed INTEGER NOT NULL DEFAULT 0
    );
    """

    def old_database(self, path):
        import sqlite3
        raw = sqlite3.connect(path)
        raw.executescript(self.OLD_SCHEMA)
        raw.execute(
            "INSERT INTO run VALUES ('out-old', 'Checkpoint', '2026-09-18',"
            " '2026-09-18T10:00:00', 613, '/out/out-old', 0, 0)")
        raw.commit()
        raw.close()

    def test_a_database_without_the_columns_gains_them(self, db):
        self.old_database(db)
        rows = record.runs(db)
        assert rows and all("delisted" in r and "graded" in r for r in rows)
        assert rows[0]["delisted"] == 0 and rows[0]["graded"] == 0

    def test_the_row_already_there_survives_it(self, db):
        self.old_database(db)
        rows = record.runs(db)
        assert [r["run_id"] for r in rows] == ["out-old"]
        assert rows[0]["seed"] == 613

    def test_the_flags_work_on_a_migrated_row(self, db):
        """Adding the column is half of it; the row has to be usable."""
        self.old_database(db)
        assert record.set_flags(db, "out-old", graded=True)["graded"] == 1


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


class TestRenamingAColumnOnADatabaseThatExists:
    r"""`attempt.page` became `attempt.run_page` on open.

    New machinery: `ADDED` only ever added columns, because
    `CREATE TABLE IF NOT EXISTS` does nothing to a table that is
    already there. A rename has to find the old name, change it, and
    then never do anything again -- and it runs against a file with
    the term's decisions in it, so "never do anything again" is the
    part worth proving.
    """

    @staticmethod
    def old_shape(path):
        """A database as it was before the rename existed."""
        import sqlite3
        db = sqlite3.connect(path)
        db.executescript("""
            CREATE TABLE run (run_id TEXT PRIMARY KEY, run_no INTEGER,
                title TEXT NOT NULL, date TEXT NOT NULL,
                built TEXT NOT NULL, seed INTEGER NOT NULL,
                output TEXT NOT NULL, extras INTEGER NOT NULL DEFAULT 0,
                unnamed INTEGER NOT NULL DEFAULT 0);
            CREATE TABLE attempt (attempt_id INTEGER PRIMARY KEY,
                run_id TEXT NOT NULL, sid TEXT NOT NULL, slug TEXT NOT NULL,
                outcome TEXT NOT NULL, decided TEXT NOT NULL, page INTEGER,
                reading TEXT NOT NULL DEFAULT '', ink REAL, beside REAL,
                UNIQUE(run_id, sid, slug));
            INSERT INTO run VALUES
                ('first', 1, 'T', '2026-10-01', '2026-10-01T09:00', 1, '/o',
                 0, 0);
            INSERT INTO attempt
                (run_id, sid, slug, outcome, decided, page, reading)
                VALUES ('first', '001', 'W1', 'passed', '2026-10-02', 7,
                        'ticked');
        """)
        db.commit()
        db.close()

    def test_the_value_comes_through_under_the_new_name(self, tmp_path):
        path = str(tmp_path / "old.db")
        self.old_shape(path)
        db = record.connect(path)
        try:
            row = db.execute("SELECT * FROM attempt").fetchone()
            assert row["run_page"] == 7
            assert row["outcome"] == "passed" and row["reading"] == "ticked"
        finally:
            db.close()

    def test_the_old_name_is_gone_rather_than_kept_beside_it(self, tmp_path):
        """A copy would leave two columns answering one question, and
        the stale one is the one something later reads."""
        path = str(tmp_path / "old.db")
        self.old_shape(path)
        db = record.connect(path)
        try:
            names = {r["name"] for r in db.execute(
                "PRAGMA table_info(attempt)")}
            assert "run_page" in names and "page" not in names
        finally:
            db.close()

    def test_opening_it_again_changes_nothing(self, tmp_path):
        path = str(tmp_path / "old.db")
        self.old_shape(path)
        shape = []
        for _ in range(3):
            db = record.connect(path)
            shape.append([r["name"] for r in db.execute(
                "PRAGMA table_info(attempt)")])
            db.close()
        assert shape[0] == shape[1] == shape[2]

    def test_a_fresh_database_has_the_same_shape_as_a_migrated_one(
            self, tmp_path):
        """Or the two diverge and only one of them is tested."""
        old = str(tmp_path / "old.db")
        self.old_shape(old)
        db = record.connect(old)
        migrated = [r["name"] for r in db.execute("PRAGMA table_info(attempt)")]
        db.close()
        db = record.connect(str(tmp_path / "new.db"))
        fresh = [r["name"] for r in db.execute("PRAGMA table_info(attempt)")]
        db.close()
        assert migrated == fresh

    def test_a_file_holding_both_names_is_left_alone(self, tmp_path):
        """Only reachable from a half-finished migration or somebody
        editing the file by hand, and both of those happen to a record
        that has a term of work in it. Without the second half of the
        guard SQLite refuses the rename and the course will not open
        at all -- so the cost of being wrong here is the whole app.
        """
        import sqlite3
        path = str(tmp_path / 'both.db')
        self.old_shape(path)
        raw = sqlite3.connect(path)
        raw.execute('ALTER TABLE attempt ADD COLUMN run_page INTEGER')
        raw.commit()
        raw.close()
        db = record.connect(path)          # must not raise
        try:
            names = {r['name'] for r in db.execute(
                'PRAGMA table_info(attempt)')}
            assert {'page', 'run_page'} <= names
        finally:
            db.close()

    def test_saving_into_a_migrated_database_works(self, tmp_path):
        """The rename is on the read path and the write path both."""
        path = str(tmp_path / "old.db")
        self.old_shape(path)
        written, unknown = record.save_attempts(path, [
            {"run_id": "first", "sid": "001", "slug": "W1",
             "outcome": "failed", "page": 9}])
        assert written == 1
        row = record.attempts_for(path, "001")[0]
        assert row["run_page"] == 9 and row["outcome"] == "failed"


class TestARunFolderSurvivesTheHomeMoving:
    r"""The folder is stored relative to the home and resolved on read.

    It used to be absolute, which meant the nine rows in the live
    record all broke if `~/CheckItPrintIt` moved -- and moving it is
    supported, `CHECKIT_PRINTIT_HOME` exists for exactly that. A
    second machine, a renamed account or a restored backup and the
    record pointed at nothing.

    Readers are unchanged: `runs`, `run_by_no`, `run_detail` and
    `set_flags` all hand back an absolute path, resolved against the
    home *as it is now*. Only the database holds the short form.
    """

    @staticmethod
    def make(home, where, run_id="first"):
        record.write_run(
            str(home / "record.db"), run_id=run_id, title="T",
            date="2026-10-01", built="2026-10-01T09:00", seed=1,
            output=str(where), handouts=[], run_no=1)

    def test_a_folder_under_the_home_is_stored_short(self, tmp_path,
                                                     monkeypatch):
        import sqlite3
        home = tmp_path / "Home"
        (home / "MAT 106" / "Checkpoint").mkdir(parents=True)
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(home))
        self.make(home, home / "MAT 106" / "Checkpoint")
        raw = sqlite3.connect(home / "record.db")
        stored = raw.execute("SELECT output FROM run").fetchone()[0]
        raw.close()
        assert not os.path.isabs(stored), stored
        assert "MAT 106" in stored

    def test_a_reader_still_gets_an_absolute_path(self, tmp_path,
                                                  monkeypatch):
        """Every caller of these was written against an absolute path
        and none of them changed."""
        home = tmp_path / "Home"
        want = home / "MAT 106" / "Checkpoint"
        want.mkdir(parents=True)
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(home))
        self.make(home, want)
        path = str(home / "record.db")
        for got in (record.runs(path)[0]["output"],
                    record.run_by_no(path, 1)["output"],
                    record.run_detail(path, "first")["output"],
                    record.set_flags(path, "first", graded=True)["output"]):
            assert os.path.isabs(got)
            assert os.path.samefile(got, want)

    def test_it_resolves_against_the_home_as_it_is_now(self, tmp_path,
                                                       monkeypatch):
        """The whole point. Written under one home, read under
        another, and it finds the folder in the new place."""
        first = tmp_path / "First"
        (first / "MAT 106" / "Checkpoint").mkdir(parents=True)
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(first))
        self.make(first, first / "MAT 106" / "Checkpoint")

        moved = tmp_path / "Moved"
        (moved / "MAT 106" / "Checkpoint").mkdir(parents=True)
        shutil.copy(first / "record.db", moved / "record.db")
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(moved))

        got = record.runs(str(moved / "record.db"))[0]["output"]
        assert os.path.isdir(got)
        assert str(moved) in got and str(first) not in got

    def test_a_folder_somewhere_else_entirely_stays_absolute(
            self, tmp_path, monkeypatch):
        """The output path can be pointed anywhere, and then there is
        nothing for it to be relative to. Stored as given rather than
        mangled into a path out of the home with `..` in it."""
        import sqlite3
        home = tmp_path / "Home"
        home.mkdir()
        outside = tmp_path / "Outside" / "Job"
        outside.mkdir(parents=True)
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(home))
        self.make(home, outside)
        raw = sqlite3.connect(home / "record.db")
        stored = raw.execute("SELECT output FROM run").fetchone()[0]
        raw.close()
        assert os.path.isabs(stored)
        assert os.path.samefile(stored, outside)

    def test_rows_already_absolute_are_shortened_on_open(self, tmp_path,
                                                         monkeypatch):
        """The migration, which is what the live record needs. Written
        the old way, then opened once."""
        import sqlite3
        home = tmp_path / "Home"
        inside = home / "MAT 106" / "Checkpoint"
        inside.mkdir(parents=True)
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(home))
        self.make(home, inside)
        # Put it back the old way, behind record's back.
        raw = sqlite3.connect(home / "record.db")
        raw.execute("UPDATE run SET output = ?", (str(inside),))
        raw.commit()
        raw.close()

        record.connect(str(home / "record.db")).close()

        raw = sqlite3.connect(home / "record.db")
        stored = raw.execute("SELECT output FROM run").fetchone()[0]
        raw.close()
        assert not os.path.isabs(stored), stored
        assert os.path.samefile(
            record.runs(str(home / "record.db"))[0]["output"], inside)


class TestDiscardingARunThatWasNeverHandedOut:
    """A day of fixes leaves runs nobody ever sat.

    Each one puts a row in `printed` for every student it would have
    been for, and `history` is built from `printed` -- so they follow
    a student into their drill-in as papers that never existed.
    `delisted` does not help: it moves a run down the Runs list and
    leaves every printed row where it was.
    """

    @staticmethod
    def two_runs(db):
        write(db, run_id="out-1", date="2026-09-18")
        write(db, run_id="out-2", date="2026-10-02")
        return db

    def test_the_run_and_its_papers_go_together(self, db):
        self.two_runs(db)
        gone = record.discard_run(db, "out-2")
        assert gone == 3, "three papers were printed in that run"
        assert [r["run_id"] for r in record.runs(db)] == ["out-1"]

    def test_the_papers_stop_following_the_student(self, db):
        """The reason for the whole thing."""
        self.two_runs(db)
        assert len(record.history(db, "806000001", "W1")) == 2
        record.discard_run(db, "out-2")
        left = record.history(db, "806000001", "W1")
        assert [r["run_id"] for r in left] == ["out-1"]

    def test_a_graded_run_is_refused(self, db):
        """The same rule that stops a graded run being delisted, and
        for the same reason: a decision has to stay findable."""
        self.two_runs(db)
        record.save_attempts(db, [{
            "run_id": "out-2", "sid": "806000001", "slug": "W1",
            "outcome": "passed"}])
        with pytest.raises(record.RecordError):
            record.discard_run(db, "out-2")
        assert len(record.runs(db)) == 2

    def test_a_run_holding_marks_is_refused_even_unflagged(self, db):
        """Not the same check twice. `graded` is a flag somebody
        could clear; the attempt rows are the thing that actually has
        to stay findable."""
        self.two_runs(db)
        record.save_attempts(db, [{
            "run_id": "out-2", "sid": "806000001", "slug": "W1",
            "outcome": "passed"}])
        conn = record.connect(db)
        conn.execute("UPDATE run SET graded = 0 WHERE run_id = 'out-2'")
        conn.commit()
        conn.close()
        with pytest.raises(record.RecordError):
            record.discard_run(db, "out-2")

    def test_a_run_flagged_graded_with_no_marks_is_refused(self, db):
        """Reachable from the Runs tab, which can set the flag on its
        own. It is him saying "I have read this one back", and
        discarding it would contradict that -- the fact that nothing
        was written yet is not a reason to disbelieve him.

        The mirror of the test above: that one has marks and no flag,
        this one a flag and no marks, and only checking both covers
        the pair.
        """
        self.two_runs(db)
        record.set_flags(db, 'out-2', graded=True)
        with pytest.raises(record.RecordError):
            record.discard_run(db, 'out-2')
        assert len(record.runs(db)) == 2

    def test_a_run_that_is_not_there_says_so(self, db):
        self.two_runs(db)
        with pytest.raises(record.RecordError):
            record.discard_run(db, "nonesuch")

    def test_the_run_number_is_not_handed_out_again(self, db):
        """A sheet from a discarded run carries a code. It has to go
        on failing to resolve, rather than resolving to whatever job
        was given its number afterwards."""
        self.two_runs(db)
        first = record.next_run_no(db, "out-3")
        record.discard_run(db, "out-2")
        assert record.next_run_no(db, "out-4") >= first

    def test_only_that_run_s_papers_go(self, db):
        self.two_runs(db)
        record.discard_run(db, "out-2")
        left = record.printed_pairs(db)
        assert {r for r, _, _ in left} == {"out-1"}
        assert len(left) == 3
