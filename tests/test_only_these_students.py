"""Printing for a few named students rather than the class.

The thing this guards is a silent wrong answer in both directions. A
run that names one student and prints forty-three wastes a ream and
hands out next week's paper early. A run that names one student and
prints nothing looks like a successful build with an empty folder.
Neither announces itself, so almost every test here is about the
*announcement* as much as the filtering.

Who-prints is deliberately not one of the skill modes. The modes
decide what a student gets -- their own form choices, or a list typed
for everybody. This decides whether they are in the run at all, and
the two compose: a reprint for one student still reads that student's
own choices. Folding them together would have meant retyping those
choices to print one paper, which is the thing being avoided.
"""

import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import assemble as assemble_mod
from checkit_printit import course as course_mod
from checkit_printit import gui as gui_mod
from checkit_printit import printjob
from checkit_printit import publication as pub_mod
from checkit_printit import roster as roster_mod
from checkit_printit import runner
from checkit_printit import seating, theme


def people(*rows):
    """A roster from (name, sid, email) triples."""
    return roster_mod.Roster([
        roster_mod.Student(name=n, section="1", skills=["AD"],
                           sid=sid, email=email)
        for n, sid, email in rows])


THREE = lambda: people(("Ada", "001", "ada@x.edu"),
                       ("Bo", "002", "bo@x.edu"),
                       ("Cy", "003", "cy@x.edu"))


# ------------------------------------------------------------- roster ----

class TestOnly:
    def test_none_is_everybody(self):
        roster, missing = THREE().only(None)
        assert [s.name for s in roster] == ["Ada", "Bo", "Cy"]
        assert missing == []

    def test_it_keeps_only_the_named(self):
        roster, _ = THREE().only(["002"])
        assert [s.name for s in roster] == ["Bo"]

    def test_it_keeps_roster_order_not_the_order_asked_for(self):
        """The printed stack is a stack. Reordering it by the order
        somebody happened to tick boxes would put the pile out of
        step with the seating chart it is handed out from."""
        roster, _ = THREE().only(["003", "001"])
        assert [s.name for s in roster] == ["Ada", "Cy"]

    def test_an_email_finds_them_as_well_as_an_id(self):
        """A job saved on Monday may name somebody by email; the
        import on Wednesday gives them an id. The saved job still has
        to find them."""
        roster, missing = THREE().only(["cy@x.edu"])
        assert [s.name for s in roster] == ["Cy"]
        assert missing == []

    def test_a_key_matching_nobody_comes_back(self):
        roster, missing = THREE().only(["002", "nobody@x.edu"])
        assert [s.name for s in roster] == ["Bo"]
        assert missing == ["nobody@x.edu"]

    def test_an_empty_list_keeps_nobody(self):
        """Distinct from None. `[]` is a run that was switched to
        naming its students and then had them all unticked -- a
        mistake, which something downstream has to refuse rather
        than quietly read as 'everybody'."""
        roster, missing = THREE().only([])
        assert len(roster) == 0
        assert missing == []

    def test_one_student_named_twice_is_printed_once(self):
        """Their id and their email are both keys. Ticking is by
        student, but a hand-written job or an import can carry
        both, and two keys on one person is still one paper."""
        roster, missing = THREE().only(["001", "ada@x.edu"])
        assert [s.name for s in roster] == ["Ada"]
        assert missing == []


# ----------------------------------------------------------- assembly ----

class Pub:
    """Enough of a publication for `build_handouts`."""
    student_versions = {}
    names = True
    ids = True
    codes = True
    only_students = None


class TestBuildHandoutsFilters:
    """`build_handouts` is the deliberate second copy of the filter.

    `assemble` filters too. The duplication is on purpose and is
    written down in both places: `build_handouts` is public and is
    called directly by tests and by the print view, so a filter that
    lived only in `assemble` would be a filter those callers skipped.
    """

    def seated(self, *names):
        return seating.Chart(
            seats=[seating.Seat(name=n, group=0, version="A")
                   for n in names],
            versions=("A",))

    def test_it_prints_only_the_named(self):
        class P(Pub):
            only_students = ("002",)
        handouts, _ = assemble_mod.build_handouts(
            THREE(), self.seated("Ada", "Bo", "Cy"), P(), {("A", "AD"): 401})
        assert [h.name for h in handouts] == ["Bo"]

    def test_a_plain_list_is_filtered_too(self):
        """Callers pass a bare list of students as well as a Roster.
        Both filter paths used to be written `and hasattr(roster,
        "only")`, so a list skipped the filter and printed the whole
        class on a run that named one student -- silently, which is
        the exact failure this feature exists to prevent."""
        class P(Pub):
            only_students = ("002",)
        handouts, _ = assemble_mod.build_handouts(
            list(THREE()), self.seated("Ada", "Bo", "Cy"), P(),
            {("A", "AD"): 401})
        assert [h.name for h in handouts] == ["Bo"]

    def test_none_still_prints_everyone(self):
        handouts, _ = assemble_mod.build_handouts(
            THREE(), self.seated("Ada", "Bo", "Cy"), Pub(),
            {("A", "AD"): 401})
        assert [h.name for h in handouts] == ["Ada", "Bo", "Cy"]

    def test_a_dropped_student_is_not_printed_even_when_named(self):
        """Dropping wins. Naming somebody in a run is not a way to
        un-drop them, and a paper for a departed student is the
        thing `live()` exists to stop."""
        roster = THREE()
        roster.students[1].dropped = True

        class P(Pub):
            only_students = ("002",)
        handouts, _ = assemble_mod.build_handouts(
            roster, self.seated("Ada", "Cy"), P(), {("A", "AD"): 401})
        assert handouts == []


class TestAssembleRefusesAnEmptyRun:
    def pub(self, bank_dir, **kw):
        return pub_mod.Publication(
            course="TEST 101", title="Checkpoint", date="2026-01-01",
            bank_path=bank_dir, **kw)

    def go(self, bank_dir, tmp_path, roster, **kw):
        source, _ = theme.load(bank_dir)
        return assemble_mod.assemble(
            self.pub(bank_dir, **kw), roster, None, str(tmp_path / "out"),
            source, rng=random.Random(1))

    def test_nobody_ticked_is_refused(self, bank_dir, tmp_path):
        with pytest.raises(assemble_mod.AssemblyError,
                           match="none of them is in the roster"):
            self.go(bank_dir, tmp_path, THREE(), only_students=())

    def test_every_name_wrong_is_refused_and_says_which(self, bank_dir,
                                                        tmp_path):
        with pytest.raises(assemble_mod.AssemblyError, match="ghost@x.edu"):
            self.go(bank_dir, tmp_path, THREE(),
                    only_students=("ghost@x.edu",))

    def test_one_good_name_among_bad_ones_still_builds(self, bank_dir,
                                                       tmp_path):
        """A stale key should not cost the paper you meant to print.
        It is reported by the runner instead."""
        report = self.go(bank_dir, tmp_path, THREE(),
                         only_students=("002", "ghost@x.edu"))
        assert report["students"] == 1


# -------------------------------------------------------- composition ----

class TestItComposesWithTheSkillModes:
    """The filter says who; the modes say what. Both apply."""

    def pub(self, bank_dir, **kw):
        return pub_mod.Publication(
            course="TEST 101", title="Checkpoint", date="2026-01-01",
            bank_path=bank_dir, **kw)

    def go(self, bank_dir, tmp_path, roster, **kw):
        source, _ = theme.load(bank_dir)
        roster = roster_mod.apply_selection_modes(
            roster,
            simply_print=kw.pop("simply_print", []),
            default_when_missing=kw.pop("default_when_missing", []),
            append_for_everyone=kw.pop("append_for_everyone", []))
        return assemble_mod.assemble(
            self.pub(bank_dir, **kw), roster, None, str(tmp_path / "out"),
            source, rng=random.Random(1))

    def test_simply_print_still_decides_the_skills(self, bank_dir, tmp_path):
        report = self.go(bank_dir, tmp_path, THREE(),
                         simply_print=["AD", "SU"], only_students=("002",))
        assert report["students"] == 1
        assert sorted(report["skills"]) == ["AD", "SU"], \
            "the filter changed who prints, not what they get"

    def test_append_for_everyone_means_everyone_in_the_run(self, bank_dir,
                                                           tmp_path):
        report = self.go(bank_dir, tmp_path, THREE(),
                         append_for_everyone=["SU"], only_students=("002",))
        assert report["students"] == 1
        assert sorted(report["skills"]) == ["AD", "SU"]

    def test_a_per_student_override_still_applies(self, bank_dir, tmp_path):
        """The two were built to work together: printing one student
        a list you type is an override plus a filter, not a third
        mode."""
        roster, unmatched = roster_mod.apply_overrides(
            THREE(), {"002": ["SU"]})
        assert unmatched == []
        report = self.go(bank_dir, tmp_path, roster, only_students=("002",))
        assert report["skills"] == ["SU"]


# ----------------------------------------------------------- the file ----

class TestWhatGetsWritten:
    """Absent, present-and-empty, and present-with-names are three
    different states in the job file, and the difference is load
    bearing: absent is everybody, empty is refused."""

    def test_all_writes_no_key_at_all(self):
        text = printjob.publication_text(
            "Test", {**printjob.DEFAULTS, "who": "all", "only": ["001"]},
            "TEST 101")
        assert "only_students" not in text

    def test_these_writes_the_names(self):
        text = printjob.publication_text(
            "Test", {**printjob.DEFAULTS, "who": "these", "only": ["001", "002"]},
            "TEST 101")
        assert 'only_students = ["001", "002"]' in text

    def test_these_with_nobody_writes_an_empty_list(self):
        """Not omitted. Omitting it would turn an obvious mistake
        into a class set."""
        text = printjob.publication_text(
            "Test", {**printjob.DEFAULTS, "who": "these", "only": []},
            "TEST 101")
        assert "only_students = []" in text

    def test_absent_loads_as_none_and_empty_as_empty(self, tmp_path):
        def load(line):
            p = tmp_path / "publication.toml"
            p.write_text(
                '[course]\ntitle = "T"\ndate = "2026-01-01"\n'
                '[bank]\npath = "."\n[roster]\npath = "r.toml"\n'
                f'[selection]\n{line}\n', encoding="utf-8")
            return pub_mod.load(str(p)).only_students

        assert load("") is None
        assert load("only_students = []") == ()
        assert load('only_students = ["001"]') == ("001",)


class TestTheDraftClearsItself:
    @pytest.fixture
    def space(self, tmp_path, monkeypatch, bank_dir):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("Test", bank=str(bank_dir), adopt=None)
        return "Test"

    def test_switching_back_to_all_forgets_the_list(self, space):
        """A list left over from last week is one radio click away
        from printing a class set as a single sheet. The draft drops
        it when the run is for everybody."""
        printjob.save_draft(space, {**printjob.DEFAULTS, "who": "these",
                                    "only": ["001"]})
        assert printjob.load_draft(space)["only"] == ["001"]
        printjob.save_draft(space, {**printjob.DEFAULTS, "who": "all",
                                    "only": ["001"]})
        assert printjob.load_draft(space)["only"] == []

    def test_the_choice_survives_a_reload(self, space):
        """It did not. `save_draft` wrote `only` and not `who`, so a
        run set to name its students came back set to the whole
        class with the names still in the file -- and the build
        gates on `who`, so it would have printed the class."""
        printjob.save_draft(space, {**printjob.DEFAULTS, "who": "these",
                                    "only": ["001"]})
        back = printjob.load_draft(space)
        assert (back["who"], back["only"]) == ("these", ["001"])

    def _hand_written(self, space, line):
        """A draft file as a person or an older version left it.

        Going through `save_draft` here would test `save_draft`:
        the two tests below are about what `load_draft` makes of a
        file it did not write, and the first version of them passed
        for exactly that reason while the value was being dropped
        on the floor.
        """
        with open(printjob.draft_path(space), "w", encoding="utf-8") as fh:
            fh.write('mode = "chose"\ntitle = "T"\n'
                     f'date = "2026-01-01"\n{line}\n')
        return printjob.load_draft(space)

    def test_a_draft_from_before_the_filter_is_a_run_for_everybody(self,
                                                                   space):
        """Which is what every run was then."""
        assert self._hand_written(space, "")["who"] == "all"

    def test_a_nonsense_who_is_not_trusted(self, space):
        assert self._hand_written(space, 'who = "SOME"')["who"] == "all"


# ------------------------------------------------------- the endpoint ----

class TestTheSaveEndpointRefuses:
    """`load_draft` reads an unrecognised value as "all", which is
    right for a file an older version wrote and wrong for a request
    arriving now: that is a caller bug, and reading it quietly turns
    it into a class set nobody asked for. The `mode` check beside it
    makes the same argument and had no test either."""

    @pytest.fixture
    def course(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("Test", bank="", adopt=None)
        with open(course_mod.file_in("Test", "roster"), "w",
                  encoding="utf-8") as fh:
            fh.write('[[student]]\nname = "Ada"\nsid = "001"\n')
        return gui_mod.Course("Test")

    def save(self, course, **draft):
        return gui_mod.api_print_save(
            course, {"draft": {**printjob.DEFAULTS, **draft}})

    def test_a_nonsense_who_is_refused(self, course):
        with pytest.raises(gui_mod.GuiError, match="is not who a run is for"):
            self.save(course, who="SOME")

    def test_a_nonsense_mode_is_refused(self, course):
        with pytest.raises(gui_mod.GuiError, match="is not a mode"):
            self.save(course, mode="SOME")

    def test_a_real_who_goes_through(self, course):
        self.save(course, who="these", only=["001"])
        assert printjob.load_draft("Test")["who"] == "these"


# -------------------------------------------------------- the reports ----

class TestTheRunnerSaysWhoMissed:
    """Three reasons a named student prints nothing, and they are not
    the same problem: dropped is visible on the roster page, absent is
    a typo, and matched is fine. Reporting all three as 'matched
    nobody' sends you hunting for a typo that is not there."""

    def job(self, tmp_path, bank_dir, roster_text, only):
        (tmp_path / "roster.toml").write_text(roster_text, encoding="utf-8")
        names = ", ".join(f'"{k}"' for k in only)
        p = tmp_path / "publication.toml"
        p.write_text(
            '[course]\ntitle = "T"\ndate = "2026-01-01"\n'
            f'[bank]\npath = "{bank_dir}"\n'.replace("\\", "/")
            + f'[roster]\npath = "{tmp_path}/roster.toml"\n'.replace(
                "\\", "/")
            + f"[selection]\nonly_students = [{names}]\n"
            + 'simply_print = ["AD"]\n', encoding="utf-8")
        return runner.run(str(p), out=str(tmp_path / "out"),
                          do_compile=False, install_theme=False, seed=1,
                          keep_record=False)

    ROSTER = ('[[student]]\nname = "Ada"\nsid = "001"\n'
              '[[student]]\nname = "Bo"\nsid = "002"\ndropped = true\n')

    def test_a_dropped_student_is_named_as_dropped(self, tmp_path, bank_dir):
        result = self.job(tmp_path, bank_dir, self.ROSTER, ["001", "002"])
        assert result.dropped_students == ("002",)
        assert result.unmatched_students == ()

    def test_a_typo_is_named_as_absent(self, tmp_path, bank_dir):
        result = self.job(tmp_path, bank_dir, self.ROSTER, ["001", "0O1"])
        assert result.unmatched_students == ("0O1",)
        assert result.dropped_students == ()

    def test_naming_only_a_dropped_student_says_dropped(self, tmp_path,
                                                        bank_dir):
        """Not "not in the roster". They are in the roster, greyed
        out on the page you are looking at."""
        with pytest.raises(runner.BuildError, match="has been dropped"):
            self.job(tmp_path, bank_dir, self.ROSTER, ["002"])

    def test_naming_only_a_typo_says_not_in_the_roster(self, tmp_path,
                                                       bank_dir):
        with pytest.raises(runner.BuildError,
                           match="is not in the roster"):
            self.job(tmp_path, bank_dir, self.ROSTER, ["0O1"])

    def test_naming_nobody_says_tick_somebody(self, tmp_path, bank_dir):
        with pytest.raises(runner.BuildError, match="no student is named"):
            self.job(tmp_path, bank_dir, self.ROSTER, [])

    def test_the_counts_say_how_much_of_the_class(self, tmp_path, bank_dir):
        result = self.job(tmp_path, bank_dir, self.ROSTER, ["001"])
        assert (result.printed_for, result.roster_size) == (1, 1), \
            "roster_size counts the live roster, not the dropped student"

    def test_an_unfiltered_run_is_for_the_whole_class(self, tmp_path,
                                                      bank_dir):
        (tmp_path / "roster.toml").write_text(self.ROSTER, encoding="utf-8")
        p = tmp_path / "publication.toml"
        p.write_text(
            '[course]\ntitle = "T"\ndate = "2026-01-01"\n'
            f'[bank]\npath = "{bank_dir}"\n'.replace("\\", "/")
            + f'[roster]\npath = "{tmp_path}/roster.toml"\n'.replace(
                "\\", "/")
            + '[selection]\nsimply_print = ["AD"]\n', encoding="utf-8")
        result = runner.run(str(p), out=str(tmp_path / "out"),
                            do_compile=False, install_theme=False, seed=1,
                            keep_record=False)
        assert result.printed_for == result.roster_size == 1
        assert result.dropped_students == ()

    def test_the_cli_flag_beats_the_file(self, tmp_path, bank_dir):
        (tmp_path / "roster.toml").write_text(
            '[[student]]\nname = "Ada"\nsid = "001"\n'
            '[[student]]\nname = "Bo"\nsid = "002"\n', encoding="utf-8")
        p = tmp_path / "publication.toml"
        p.write_text(
            '[course]\ntitle = "T"\ndate = "2026-01-01"\n'
            f'[bank]\npath = "{bank_dir}"\n'.replace("\\", "/")
            + f'[roster]\npath = "{tmp_path}/roster.toml"\n'.replace(
                "\\", "/")
            + '[selection]\nonly_students = ["001"]\n'
            + 'simply_print = ["AD"]\n', encoding="utf-8")
        result = runner.run(str(p), out=str(tmp_path / "out"),
                            do_compile=False, install_theme=False, seed=1,
                            keep_record=False, only=["002"])
        assert result.printed_for == 1
        assert result.publication.only_students == ("002",)

    def test_no_flag_leaves_the_file_alone(self, tmp_path, bank_dir):
        """Click gives `()` for an option that was not passed, which
        must not read as 'print for nobody'."""
        (tmp_path / "roster.toml").write_text(
            '[[student]]\nname = "Ada"\nsid = "001"\n'
            '[[student]]\nname = "Bo"\nsid = "002"\n', encoding="utf-8")
        p = tmp_path / "publication.toml"
        p.write_text(
            '[course]\ntitle = "T"\ndate = "2026-01-01"\n'
            f'[bank]\npath = "{bank_dir}"\n'.replace("\\", "/")
            + f'[roster]\npath = "{tmp_path}/roster.toml"\n'.replace(
                "\\", "/")
            + '[selection]\nonly_students = ["001"]\n'
            + 'simply_print = ["AD"]\n', encoding="utf-8")
        result = runner.run(str(p), out=str(tmp_path / "out"),
                            do_compile=False, install_theme=False, seed=1,
                            keep_record=False, only=())
        assert result.publication.only_students == ("001",)
