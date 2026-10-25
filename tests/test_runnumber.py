"""The number that identifies a run, which the seed does not.

`choose_run_seed` carries a replayed run's seed on purpose, and a
replay writes to a new folder, which is a new row -- so a reprint has
always produced two runs sharing one seed. That was tolerable while
nothing read the seed back. A scanned footer code does, and because a
replay exists to *fix* something, the two runs can have different
page-to-student mappings: resolving by seed would not merely be
ambiguous, it would hand a paper to the wrong student.
"""

import os

import pytest

from checkit_printit import record as record_mod


@pytest.fixture
def db_path(tmp_path):
    return str(tmp_path / "course" / "record.db")


def add(path, run_id, seed, run_no):
    record_mod.write_run(path, run_id=run_id, title="T", date="2026-01-01",
                         built="2026-01-01T09:00", seed=seed,
                         output=f"/out/{run_id}", handouts=[], run_no=run_no)


class TestAllocating:
    def test_the_first_run_is_one(self, db_path):
        assert record_mod.next_run_no(db_path, "first") == 1

    def test_the_next_run_is_the_one_after(self, db_path):
        add(db_path, "first", 100, record_mod.next_run_no(db_path, "first"))
        assert record_mod.next_run_no(db_path, "second") == 2

    def test_building_the_same_folder_again_keeps_its_number(self, db_path):
        """One folder is one printing event, re-recorded. A rebuild
        that took a fresh number would change what the reprinted
        paper says about itself."""
        add(db_path, "first", 100, record_mod.next_run_no(db_path, "first"))
        assert record_mod.next_run_no(db_path, "first") == 1
        assert record_mod.next_run_no(db_path, "first") == 1

    def test_a_deleted_run_does_not_hand_its_number_on(self, db_path):
        """Counting from the highest ever issued, not from the number
        of rows. Counting rows would give a deleted run's number to
        the next one, and two stacks of paper would claim to be the
        same run -- with the older stack's claim being the wrong
        one, silently."""
        for n, name in enumerate(("a", "b", "c"), start=1):
            add(db_path, name, 100 + n, n)
        db = record_mod.connect(db_path)
        with db:
            db.execute("DELETE FROM run WHERE run_id = 'c'")
        db.close()
        assert record_mod.next_run_no(db_path, "d") == 4

    def test_a_replay_shares_the_seed_and_not_the_number(self, db_path):
        """The case the whole thing exists for."""
        add(db_path, "monday", 777, record_mod.next_run_no(db_path, "monday"))
        add(db_path, "monday reprint", 777,
            record_mod.next_run_no(db_path, "monday reprint"))
        rows = {r["run_id"]: r for r in record_mod.runs(db_path)}
        assert rows["monday"]["seed"] == rows["monday reprint"]["seed"]
        assert rows["monday"]["run_no"] != rows["monday reprint"]["run_no"]


class TestResolving:
    def test_a_number_finds_its_run(self, db_path):
        add(db_path, "monday", 777, 1)
        assert record_mod.run_by_no(db_path, 1)["run_id"] == "monday"

    def test_an_unknown_number_is_none_rather_than_a_guess(self, db_path):
        add(db_path, "monday", 777, 1)
        assert record_mod.run_by_no(db_path, 2) is None

    def test_no_record_at_all_is_none(self, tmp_path):
        assert record_mod.run_by_no(str(tmp_path / "nothing.db"), 1) is None

    def test_a_run_from_before_numbers_existed_matches_nothing(self, db_path):
        """`run_no` is nullable because the runs already in a record
        were built before this existed. A paper from one of those
        carries no usable code, and saying so is better than
        attaching it to whichever row happens to sort first."""
        add(db_path, "old", 777, None)
        assert record_mod.run_by_no(db_path, 1) is None
        assert record_mod.runs(db_path)[0]["run_no"] is None


class TestTheBuild:
    """Through `runner.run`, which is what allocates."""

    def publication(self, bank_dir, tmp_path, course):
        pub = tmp_path / "publication.toml"
        pub.write_text(
            "[course]\n"
            'name   = "TEST 101"\n'
            'title  = "T"\n'
            'date   = "2026-01-01"\n'
            f'folder = "{course}"\n'
            "\n[bank]\n"
            "path = '" + str(bank_dir) + "'\n"
            "\n[roster]\npath = 'roster.toml'\n"
            "\n[print]\nkeys = false\n", encoding="utf-8")
        (tmp_path / "roster.toml").write_text(
            '[[student]]\nname = "Ada"\nsection = "1"\n'
            'sid = "800000111"\nskills = ["AD"]\n', encoding="utf-8")
        return pub

    @pytest.fixture
    def home(self, tmp_path, monkeypatch):
        """A print-it home of its own.

        Not decoration: building against the instructor's real job
        file wrote four junk rows into his live record, because a
        publication that names a course records unconditionally.
        """
        root = tmp_path / "home"
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(root))
        from checkit_printit import course as course_mod
        course_mod.init("Scratch")
        # A course folder implies a seating chart, and `runner.run`
        # refuses a publication whose chart is missing.
        (root / "courses" / "Scratch" / "seating.toml").write_text(
            '[[group]]\nseats = ["Ada"]\n', encoding="utf-8")
        return root

    def build(self, bank_dir, tmp_path, home, out, **kw):
        from checkit_printit import runner
        pub = self.publication(bank_dir, tmp_path, "Scratch")
        return runner.run(str(pub), out=str(tmp_path / out),
                          do_compile=False, install_theme=False, **kw)

    def test_a_recorded_run_gets_a_number(self, bank_dir, tmp_path, home):
        result = self.build(bank_dir, tmp_path, home, "one", seed=1)
        assert result.run_id == 1

    def test_the_number_reaches_the_document(self, bank_dir, tmp_path, home):
        self.build(bank_dir, tmp_path, home, "one", seed=1)
        main = (tmp_path / "one" / "main.tex").read_text(encoding="utf-8")
        assert r"\setrunid{1}" in main

    def test_no_record_means_no_number_and_no_declaration(
            self, bank_dir, tmp_path, home):
        """A throwaway build has nothing to look a code up in, so it
        prints none. `\\setrunid` is what switches the whole
        mechanism on, and leaving it out is how that is said."""
        result = self.build(bank_dir, tmp_path, home, "one", seed=1,
                            keep_record=False)
        assert result.run_id is None
        main = (tmp_path / "one" / "main.tex").read_text(encoding="utf-8")
        assert r"\setrunid" not in main

    def test_no_record_writes_nothing_to_the_record(self, bank_dir, tmp_path,
                                                    home):
        self.build(bank_dir, tmp_path, home, "one", seed=1, keep_record=False)
        path = str(home / "courses" / "Scratch" / "record.db")
        assert not os.path.isfile(path) or not record_mod.runs(path)

    def test_an_ordinary_build_does_write_to_it(self, bank_dir, tmp_path,
                                                home):
        """The other half: without this, the test above would also
        pass if recording were broken for everybody."""
        self.build(bank_dir, tmp_path, home, "one", seed=1)
        path = str(home / "courses" / "Scratch" / "record.db")
        assert len(record_mod.runs(path)) == 1
