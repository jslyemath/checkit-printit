"""Building a second job into the first one's folder.

A run is identified by its output folder, and the folder is named
`{title} {date}`. A job whose title and date have not been changed
since the last build therefore lands on top of the previous run:
`assemble` rewrites `main.pages`, which is the only record of which
printed page belonged to whom, and `write_run` deletes the run row,
which cascades away every `printed` row under it. The run *number*
survives, because the folder already had one -- so the footer codes
on papers already in the world still resolve, to the new index,
confidently and wrongly.

That happened on 2026-10-27 to a live run of 86 papers. The day
after, scanning those papers placed four of sixty-two pages, all
four against the wrong student.

What is refused is a build whose papers differ from the ones the
record says that folder produced. Rebuilding the same run is not
refused: it happens after a failed compile and after a theme change,
and it destroys nothing.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import assemble as assemble_mod
from checkit_printit import record


class Pub:
    """Enough of a publication for `build_handouts`."""
    student_versions = {}
    names = True
    ids = True
    codes = True
    only_students = None
    keys = False
    key_copies = 1
    extras = ()


def students(*rows):
    from checkit_printit import roster as roster_mod
    return roster_mod.Roster([
        roster_mod.Student(name=n, section="1", skills=list(sk), sid=sid)
        for n, sid, sk in rows])


THREE = lambda: students(("Ada", "001", ["AD", "SU"]),
                         ("Bo", "002", ["AD"]))


def handouts_for(roster, publication=None):
    seeds = {("A", "AD"): 401, ("A", "SU"): 402}
    got, _ = assemble_mod.build_handouts(
        roster, None, publication or Pub(), seeds)
    return got


# ------------------------------------------------------- what a run is ---

class TestPapersOf:
    """The identity of a run, for "same run again or a different one?"."""

    def test_it_is_who_got_what(self):
        assert assemble_mod.papers_of(handouts_for(THREE())) == {
            ("001", "AD"), ("001", "SU"), ("002", "AD")}

    def test_seeds_are_not_part_of_it(self):
        """Redrawing the same papers for the same people is a
        rebuild, not a different run. If the seed counted, every
        rebuild without `--seed` would be refused."""
        a = assemble_mod.build_handouts(
            THREE(), None, Pub(), {("A", "AD"): 1, ("A", "SU"): 2})[0]
        b = assemble_mod.build_handouts(
            THREE(), None, Pub(), {("A", "AD"): 9, ("A", "SU"): 8})[0]
        assert assemble_mod.papers_of(a) == assemble_mod.papers_of(b)

    def test_a_paper_with_no_student_is_not_in_it(self):
        """A run printed with names off records no owner, so there
        is nothing to compare and nothing to lose."""
        anon = students(("Ada", "", ["AD"]))
        assert assemble_mod.papers_of(handouts_for(anon)) == set()


# ---------------------------------------------------------- the refusal --

class TestAssembleRefusesACollision:
    def go(self, bank_dir, tmp_path, already, skills=("AD",)):
        from checkit_printit import publication as pub_mod
        from checkit_printit import theme
        import random
        source, _ = theme.load(bank_dir)
        roster = students(("Ada", "001", list(skills)))
        publication = pub_mod.Publication(
            course="TEST 101", title="Checkpoint", date="2026-01-01",
            bank_path=bank_dir)
        return assemble_mod.assemble(
            publication, roster, None, str(tmp_path / "out"), source,
            rng=random.Random(1), already=already)

    def test_the_same_papers_are_a_rebuild(self, bank_dir, tmp_path):
        self.go(bank_dir, tmp_path, already={("001", "AD")})

    def test_different_papers_are_refused(self, bank_dir, tmp_path):
        with pytest.raises(assemble_mod.FolderInUse,
                           match="already holds a different run"):
            self.go(bank_dir, tmp_path, already={("002", "SU")})

    def test_none_means_do_not_check(self, bank_dir, tmp_path):
        """No course, no record, or `--replace`. All three arrive
        here as None, and None must build."""
        self.go(bank_dir, tmp_path, already=None)

    def test_an_empty_set_still_checks(self, bank_dir, tmp_path):
        """A run that recorded no attributable papers is not the
        same as no run at all. Distinguishing them is why
        `papers_in` returns None rather than an empty set."""
        with pytest.raises(assemble_mod.FolderInUse):
            self.go(bank_dir, tmp_path, already=set())

    def test_it_refuses_before_writing_anything(self, bank_dir, tmp_path):
        """The whole point. A refusal after `main.pages` has been
        rewritten is not a refusal."""
        out = tmp_path / "out"
        with pytest.raises(assemble_mod.FolderInUse):
            self.go(bank_dir, tmp_path, already={("002", "SU")})
        assert not out.exists()

    def test_the_message_counts_what_would_be_lost(self, bank_dir,
                                                   tmp_path):
        """"86 papers for 43 students" is the sentence that makes
        somebody stop. A bare "folder in use" is one they click
        through."""
        with pytest.raises(assemble_mod.FolderInUse) as caught:
            self.go(bank_dir, tmp_path,
                    already={("002", "SU"), ("003", "SU")})
        said = str(caught.value)
        assert "2 paper(s) for 2 student(s)" in said
        assert "1 for 1 here" in said
        assert "who held 2 printed paper(s)" in said

    def test_it_carries_both_sets_for_the_caller(self, bank_dir, tmp_path):
        with pytest.raises(assemble_mod.FolderInUse) as caught:
            self.go(bank_dir, tmp_path, already={("002", "SU")})
        assert caught.value.was == {("002", "SU")}
        assert caught.value.now == {("001", "AD")}

    def test_a_preview_refuses_too(self, bank_dir, tmp_path):
        """A preview writes nothing, so it could be allowed. It is
        not: the value of this is learning about it *before*
        pressing Build, and a preview that passes where a build
        refuses is its own trap."""
        from checkit_printit import publication as pub_mod
        from checkit_printit import theme
        import random
        source, _ = theme.load(bank_dir)
        publication = pub_mod.Publication(
            course="TEST 101", title="Checkpoint", date="2026-01-01",
            bank_path=bank_dir)
        with pytest.raises(assemble_mod.FolderInUse):
            assemble_mod.assemble(
                publication, students(("Ada", "001", ["AD"])), None,
                str(tmp_path / "out"), source, rng=random.Random(1),
                dry_run=True, already={("002", "SU")})

    def test_it_is_an_assembly_error_so_old_callers_still_catch_it(self):
        assert issubclass(assemble_mod.FolderInUse,
                          assemble_mod.AssemblyError)


# --------------------------------------------------- what the record says -

class TestPapersIn:
    @pytest.fixture
    def db(self, tmp_path):
        path = str(tmp_path / "record.db")
        record.write_run(
            path, run_id="Checkpoint 2026-10-26", title="Checkpoint",
            date="2026-10-26", built="2026-10-26T10:48:00", seed=1,
            output="/out", run_no=1,
            handouts=[{"sid": "001", "name": "Ada", "section": "1",
                       "version": "A", "papers": [("N3", 401),
                                                  ("N4", 402)]}])
        # A second run, because with one run in the table "filter by
        # this run" and "do not filter at all" give the same answer
        # and the filter could be deleted unnoticed. His record has
        # six.
        record.write_run(
            path, run_id="SCP Token Redo 2026-10-27", title="Redo",
            date="2026-10-27", built="2026-10-27T10:03:00", seed=2,
            output="/out2", run_no=2,
            handouts=[{"sid": "002", "name": "Bo", "section": "1",
                       "version": "A", "papers": [("W7", 663)]}])
        return path

    def test_it_is_the_pairs_that_run_printed(self, db):
        assert record.papers_in(db, "Checkpoint 2026-10-26") == {
            ("001", "N3"), ("001", "N4")}

    def test_another_run_s_papers_do_not_leak_in(self, db):
        assert record.papers_in(db, "SCP Token Redo 2026-10-27") == {
            ("002", "W7")}

    def test_a_folder_never_built_is_none_not_empty(self, db):
        """None means "nothing to collide with"; an empty set means
        "a run that recorded nobody". `assemble` treats them
        differently and must be able to."""
        assert record.papers_in(db, "Some Other Run") is None

    def test_an_absent_database_is_none(self, tmp_path):
        assert record.papers_in(str(tmp_path / "no.db"), "x") is None


# ------------------------------------------------- through the runner ----

class TestTheRunnerPassesItOn:
    """The pieces above, wired. Driven through `runner.run`, because
    the bug was not in any one of them -- it was that nothing asked
    the question."""

    @pytest.fixture
    def course(self, tmp_path, monkeypatch, bank_dir):
        from checkit_printit import course as course_mod
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("Test", bank=str(bank_dir), adopt=None)
        with open(course_mod.file_in("Test", "roster"), "w",
                  encoding="utf-8") as fh:
            fh.write('[[student]]\nname = "Ada"\nsid = "001"\n'
                     '[[student]]\nname = "Bo"\nsid = "002"\n')
        # A chart, because the build reads one and the page order
        # comes from it -- which is the whole reason a collision
        # matters.
        with open(course_mod.file_in("Test", "seating"), "w",
                  encoding="utf-8") as fh:
            fh.write('[[group]]\nseats = ["Ada", "Bo"]\n')
        return tmp_path

    def job(self, root, skills, only=None):
        from checkit_printit import printjob
        draft = dict(printjob.DEFAULTS)
        draft.update({"title": "Checkpoint", "date": "2026-10-26",
                      "mode": "same", "simply_print": list(skills),
                      "keys": False})
        if only:
            draft.update({"who": "these", "only": list(only)})
        folder = printjob.write_job("Test", draft, "Test", root=str(root))
        return os.path.join(folder, "publication.toml")

    def build(self, root, path, **kw):
        from checkit_printit import runner
        return runner.run(path, out=str(root / "Test" / "Checkpoint "
                                        "2026-10-26"),
                          do_compile=False, install_theme=False, seed=7,
                          **kw)

    def test_the_second_job_is_refused(self, course):
        first = self.job(course, ["AD", "SU"])
        self.build(course, first)
        second = self.job(course, ["SU"], only=["001"])
        with pytest.raises(assemble_mod.FolderInUse):
            self.build(course, second)

    def test_the_first_run_survives_the_refusal(self, course):
        first = self.job(course, ["AD", "SU"])
        self.build(course, first)
        second = self.job(course, ["SU"], only=["001"])
        with pytest.raises(assemble_mod.FolderInUse):
            self.build(course, second)
        path = os.path.join(course, "courses", "Test", "record.db")
        assert record.papers_in(path, "Checkpoint 2026-10-26") == {
            ("001", "AD"), ("001", "SU"), ("002", "AD"), ("002", "SU")}

    def test_replace_gets_through(self, course):
        first = self.job(course, ["AD", "SU"])
        self.build(course, first)
        second = self.job(course, ["SU"], only=["001"])
        result = self.build(course, second, replace=True)
        assert result.report["students"] == 1

    def test_a_rebuild_of_the_same_job_is_allowed(self, course):
        first = self.job(course, ["AD", "SU"])
        self.build(course, first)
        again = self.job(course, ["AD", "SU"])
        assert self.build(course, again).report["students"] == 2

    def test_a_course_with_no_record_yet_builds(self, course):
        assert self.build(course, self.job(course, ["AD"])) is not None


class TestRecoveringALostIndex:
    """`--rebuilt`: build into the folder again to recover the page
    index, and say in the record that the seeds are a fresh draw.

    Who held which page comes back exactly -- it is the roster and
    the chart, and `main_tex` puts students before extras and keys.
    The seeds do not, because they lived in the manifest that the
    overwriting build replaced. The flag exists so nothing later
    reads those seeds as what was printed.
    """

    @pytest.fixture
    def course(self, tmp_path, monkeypatch, bank_dir):
        from checkit_printit import course as course_mod
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("Test", bank=str(bank_dir), adopt=None)
        with open(course_mod.file_in("Test", "roster"), "w",
                  encoding="utf-8") as fh:
            fh.write('[[student]]\nname = "Ada"\nsid = "001"\n'
                     '[[student]]\nname = "Bo"\nsid = "002"\n')
        with open(course_mod.file_in("Test", "seating"), "w",
                  encoding="utf-8") as fh:
            fh.write('[[group]]\nseats = ["Ada", "Bo"]\n')
        return tmp_path

    def job(self, root, skills):
        from checkit_printit import printjob
        draft = dict(printjob.DEFAULTS)
        draft.update({"title": "Checkpoint", "date": "2026-10-26",
                      "mode": "same", "simply_print": list(skills),
                      "keys": False})
        folder = printjob.write_job("Test", draft, "Test", root=str(root))
        return os.path.join(folder, "publication.toml")

    def build(self, root, path, **kw):
        from checkit_printit import runner
        return runner.run(
            path, out=str(root / "Test" / "Checkpoint 2026-10-26"),
            do_compile=False, install_theme=False, seed=7, **kw)

    def db(self, root):
        return os.path.join(root, "courses", "Test", "record.db")

    def test_an_ordinary_run_is_not_marked(self, course):
        self.build(course, self.job(course, ["AD"]))
        assert record.run_by_no(self.db(course), 1)["rebuilt"] == 0

    def test_a_rebuilt_run_is_marked(self, course):
        self.build(course, self.job(course, ["AD"]), rebuilt=True)
        assert record.run_by_no(self.db(course), 1)["rebuilt"] == 1

    def test_the_result_says_so_too(self, course):
        r = self.build(course, self.job(course, ["AD"]), rebuilt=True)
        assert r.rebuilt is True

    def test_rebuilt_does_not_also_need_replace(self, course):
        """Recovering an index *is* replacing a run on purpose.
        Asking for both would be asking the same question twice and
        getting the answer wrong once."""
        self.build(course, self.job(course, ["AD", "SU"]))
        self.build(course, self.job(course, ["AD"]), rebuilt=True)
        assert record.papers_in(self.db(course),
                                "Checkpoint 2026-10-26") == {
            ("001", "AD"), ("002", "AD")}

    def test_the_run_keeps_its_number(self, course):
        """The whole point. The printed papers carry that number in
        their footer code, and a new one would leave them naming a
        run that does not exist."""
        first = self.build(course, self.job(course, ["AD", "SU"]))
        again = self.build(course, self.job(course, ["AD", "SU"]),
                           rebuilt=True)
        assert again.run_id == first.run_id == 1

    def test_the_mark_survives_a_later_ordinary_rebuild(self, course):
        """It should not: a later build of the same job draws seeds
        the same way, so if it is no longer a recovery the mark
        should go. Written down because the opposite is arguable --
        the seeds are still not Monday's. The rule chosen is that
        the flag describes *this* build, and a build that does not
        claim to be a recovery is not one."""
        self.build(course, self.job(course, ["AD"]), rebuilt=True)
        self.build(course, self.job(course, ["AD"]))
        assert record.run_by_no(self.db(course), 1)["rebuilt"] == 0


class TestTheNameCropIsItsOwnShape:
    """The grading box's padding does not transfer to the name.

    Every pad is a multiple of the mark's own *width*, which suits a
    roughly square box. A name is ten times wider than it is tall, so
    the box's 1.05 to the right would take half the page and its 0.45
    above would reach the header rule.
    """

    def test_the_name_has_its_own_pad_and_height(self):
        from checkit_printit import scans
        pad, height = scans.PADS["name"]
        assert pad == scans.NAME_PAD
        assert height == scans.NAME_HEIGHT

    def test_it_reaches_far_less_sideways_than_the_box(self):
        from checkit_printit import scans
        assert scans.NAME_PAD[2] < scans.PAD[2] / 10

    def test_anything_without_its_own_pad_gets_the_box_s(self):
        """So adding a mark cannot silently get a name-shaped crop."""
        from checkit_printit import scans
        assert "box" not in scans.PADS

    def test_cuts_gives_each_mark_the_pad_the_table_says(self,
                                                         monkeypatch):
        """The three above check what is in the table. This checks
        that the cutting reads it -- a version that ignored the
        table passed all three."""
        import types
        from checkit_printit import pageindex, scans

        asked = {}

        def fake_cut(image, mark, anchor, carry, pad=None, height=None):
            asked[mark] = (pad, height)
            return "crop"

        monkeypatch.setattr(scans, "cut_out", fake_cut)
        monkeypatch.setattr(scans, "_corners", lambda s: None)
        monkeypatch.setattr(scans, "placement",
                            lambda anchor, corners: (lambda x, y: (x, y)))

        marks = {"box": pageindex.Mark(1, 2, 3, 4, 5),
                 "name": pageindex.Mark(6, 7, 8, 9, 10)}
        entry = pageindex.Page(page=1, kind="student", sid="001",
                               slug="W1", vseed="401", sheet=1,
                               marks=marks)
        cuts = scans._cuts(
            image=None, entry=entry, page=1,
            symbols=[types.SimpleNamespace(text="C1-1-1")],
            anchors={1: object()}, want=("box", "name"))

        assert set(cuts) == {"box", "name"}
        assert asked[marks["box"]] == (scans.PAD, 120)
        assert asked[marks["name"]] == (scans.NAME_PAD,
                                        scans.NAME_HEIGHT)
