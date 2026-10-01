"""The preferred name, and the one rule that keeps it safe.

`preferred` is the whole name to print -- "Matt Clifford", not "Matt". It
used to mean a first name, defaulted from the registrar's `first` on import,
and nothing read it; it was empty on all eight real rosters, so the meaning
was free to fix and there was nothing to migrate.

The rule these tests exist to hold:

    Everything that *shows* a student goes through `Student.display`.
    Everything that *matches* one keeps using sid, alt_id, email and name.

The seating chart is the single exception, because the file holds no id at
all -- a seat is a name and nothing else -- so it accepts either spelling.

No real student appears here.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import assemble, classlist, roster as roster_mod
from checkit_printit import seating as seating_mod
from checkit_printit.roster import Roster, Student


class Pub:
    """Enough of a publication for `build_handouts` and `main_tex`."""
    student_versions = {}
    names = True
    course = "MAT 106"
    semester = "Fall 2026"
    professor = "Slye"
    full_title = "Skill Checkpoint"


def chart_of(*names, versions=("A", "B")):
    return seating_mod.Chart(
        seats=[seating_mod.Seat(name=n, group=0, version=versions[i % len(versions)])
               for i, n in enumerate(names)],
        versions=tuple(versions),
    )


class TestWhatDisplayMeans:
    def test_without_a_preferred_name_it_is_the_roster_name(self):
        assert Student(name="Ada Lovelace", skills=[]).display == "Ada Lovelace"

    def test_with_one_it_is_the_preferred_name(self):
        s = Student(name="Augusta Lovelace", skills=[], preferred="Ada Lovelace")
        assert s.display == "Ada Lovelace"

    def test_blank_and_whitespace_are_not_a_name(self):
        """An empty box means "use the roster name", not "print nothing"."""
        assert Student(name="Ada Lovelace", skills=[], preferred="").display \
            == "Ada Lovelace"

    def test_it_never_replaces_the_key(self):
        """`name` is what the roster file and the record are keyed on."""
        s = Student(name="Augusta Lovelace", skills=[], preferred="Ada Lovelace")
        assert s.name == "Augusta Lovelace"


class TestTheRosterFileKeepsIt:
    def test_it_survives_a_write_and_a_read(self, tmp_path):
        """It used to be dropped on write whenever it equalled `first`, which
        was always, because the import set it from `first`."""
        people = Roster([Student(name="Augusta Lovelace", skills=["AD"],
                                 sid="806001", preferred="Ada Lovelace")])
        path = tmp_path / "roster.toml"
        path.write_text(roster_mod.to_toml(people, "test"), encoding="utf-8")
        back = roster_mod.load(str(path))
        assert list(back)[0].preferred == "Ada Lovelace"
        assert list(back)[0].display == "Ada Lovelace"

    def test_it_survives_even_when_it_equals_the_first_name(self, tmp_path):
        """The condition used to be `preferred != first`, so an instructor
        who typed the registrar's first name -- wanting exactly that on the
        paper -- had it silently dropped and got the full name instead.

        This is the case the other round-trip test misses, because its
        student has no `first` at all.
        """
        people = Roster([Student(name="Augusta Lovelace", skills=["AD"],
                                 sid="806001", first="Augusta", last="Lovelace",
                                 preferred="Augusta")])
        path = tmp_path / "roster.toml"
        path.write_text(roster_mod.to_toml(people, "test"), encoding="utf-8")
        assert list(roster_mod.load(str(path)))[0].display == "Augusta"

    def test_no_preferred_name_writes_no_key(self, tmp_path):
        people = Roster([Student(name="Ada Lovelace", skills=[], sid="806001")])
        text = roster_mod.to_toml(people, "test")
        assert "preferred" not in text


class TestAnImportDoesNotInventOne:
    """The live hazard. `parse` set `preferred=first`, so the next real class
    list would have given every student a printed name of one word."""

    CSV = ('"Student ID","Student Last Name","Student First Name","Student MI",'
           '"Subject","Course","Section","Email","Global ID"\n'
           '"806000001","Lovelace","Augusta","Ada","MAT","106","820",'
           '"alovelace@example.edu","2000000001"\n')

    @pytest.fixture
    def imported(self, tmp_path):
        p = tmp_path / "list.csv"
        p.write_text(self.CSV, encoding="utf-8")
        # parse returns (students, mapping, skipped).
        return classlist.parse(str(p))[0]

    def test_the_registrar_does_not_supply_a_preferred_name(self, imported):
        assert imported[0].preferred == ""

    def test_so_the_full_name_prints(self, imported):
        assert imported[0].display == "Augusta Lovelace"

    def test_a_merge_does_not_backfill_it_either(self, imported, tmp_path):
        existing = Roster([Student(name="Augusta Lovelace", skills=["AD"],
                                   sid="806000001")])
        merged, _ = classlist.merge(existing, imported)
        assert list(merged)[0].preferred == ""

    def test_and_a_merge_keeps_one_the_instructor_typed(self, imported):
        """Instructor-authored fields survive a re-import; see classlist's
        own note on what an import may overwrite."""
        existing = Roster([Student(name="Augusta Lovelace", skills=["AD"],
                                   sid="806000001", preferred="Ada Lovelace")])
        merged, _ = classlist.merge(existing, imported)
        assert list(merged)[0].display == "Ada Lovelace"


class TestItReachesThePaper:
    def _handouts(self, student, chart=None):
        seeds = {("A", "AD"): 401, ("B", "AD"): 402}
        return assemble.build_handouts(Roster([student]), chart, Pub(), seeds)[0]

    def test_the_handout_carries_the_printed_name(self):
        s = Student(name="Augusta Lovelace", skills=["AD"], sid="806001",
                    preferred="Ada Lovelace")
        assert self._handouts(s)[0].name == "Ada Lovelace"

    def test_and_the_roster_name_when_there_is_none(self):
        s = Student(name="Ada Lovelace", skills=["AD"], sid="806001")
        assert self._handouts(s)[0].name == "Ada Lovelace"

    def test_the_tex_sets_it(self):
        """The whole point: `\\setname` is what a student reads."""
        s = Student(name="Augusta Lovelace", skills=["AD"], sid="806001",
                    preferred="Ada Lovelace")
        tex = assemble.main_tex(Pub(), self._handouts(s), [], None)
        assert r"\setname{Ada Lovelace}" in tex
        assert "Augusta" not in tex

    def test_names_off_still_blanks_it(self):
        """A preferred name must not sneak past `--no-names`."""
        s = Student(name="Augusta Lovelace", skills=["AD"], sid="806001",
                    preferred="Ada Lovelace")
        class Anon(Pub):
            names = False
        seeds = {("A", "AD"): 401}
        handouts = assemble.build_handouts(Roster([s]), None, Anon(), seeds)[0]
        tex = assemble.main_tex(Anon(), handouts, [], None)
        assert r"\setname{Blank}" in tex
        assert "Ada" not in tex

    def test_the_record_gets_the_printed_name(self):
        """`record.printed.name` is documented as "as printed"; `sid` is the
        key, so this is for reading the log back."""
        s = Student(name="Augusta Lovelace", skills=["AD"], sid="806001",
                    preferred="Ada Lovelace")
        report = assemble._report_dict(self._handouts(s), [], None, [("AD", 401)],
                                       [], None, {}, {}, Roster([s]))
        assert report["handouts"][0]["name"] == "Ada Lovelace"
        assert report["handouts"][0]["sid"] == "806001"


class TestTheChartTakesEitherSpelling:
    """The one join made on a name, because `seating.toml` holds no id."""

    STUDENT = dict(name="Augusta Lovelace", skills=["AD"], sid="806001",
                   preferred="Ada Lovelace")

    def test_a_seat_under_the_roster_name_matches(self):
        people = Roster([Student(**self.STUDENT)])
        ordered, unseated = chart_of("Augusta Lovelace").order(people)
        assert [s.sid for s in ordered] == ["806001"] and unseated == []

    def test_a_seat_under_the_printed_name_matches_too(self):
        """An instructor who types the chart from the printed list should not
        silently lose a student."""
        people = Roster([Student(**self.STUDENT)])
        ordered, unseated = chart_of("Ada Lovelace").order(people)
        assert [s.sid for s in ordered] == ["806001"] and unseated == []

    def test_a_seat_matching_nobody_leaves_them_unseated(self):
        people = Roster([Student(**self.STUDENT)])
        ordered, unseated = chart_of("Grace Hopper").order(people)
        assert ordered == [] and [s.sid for s in unseated] == ["806001"]

    def test_one_student_in_two_seats_is_refused(self):
        """Both spellings index the same person, so a chart naming each once
        names one person twice. Printing them both is two papers for one
        student and a short stack at the far end of the room."""
        people = Roster([Student(**self.STUDENT)])
        chart = chart_of("Augusta Lovelace", "Ada Lovelace")
        with pytest.raises(seating_mod.SeatingError, match="two seats"):
            chart.order(people)

    def test_an_ambiguous_seat_is_refused(self):
        """One student's roster name is another's printed name. Guessing
        would hand somebody the wrong paper."""
        people = Roster([
            Student(name="Augusta Lovelace", skills=["AD"], sid="806001",
                    preferred="Ada Lovelace"),
            Student(name="Ada Lovelace", skills=["AD"], sid="806002"),
        ])
        with pytest.raises(seating_mod.SeatingError, match="matches 2 students"):
            chart_of("Ada Lovelace").order(people)

    def test_the_seat_version_still_rides_along(self):
        people = Roster([Student(**self.STUDENT)])
        ordered, _ = chart_of("x", "Ada Lovelace").order(people)
        assert ordered[0].version == "B"


class TestDroppingFindsTheSeat:
    CHART = ('[[group]]\nseats = ["Ada Lovelace", "Grace Hopper"]\n')

    def _drop(self, tmp_path, seat_name):
        people = Roster([Student(name="Augusta Lovelace", skills=["AD"],
                                 sid="806001", preferred="Ada Lovelace")])
        rp = tmp_path / "roster.toml"
        rp.write_text(roster_mod.to_toml(people, "test"), encoding="utf-8")
        sp = tmp_path / "seating.toml"
        sp.write_text(f'[[group]]\nseats = ["{seat_name}", "Grace Hopper"]\n',
                      encoding="utf-8")
        result = roster_mod.set_dropped(str(rp), "806001", True, str(sp))
        return result, sp.read_text(encoding="utf-8")

    def test_a_seat_under_the_printed_name_is_emptied(self, tmp_path):
        result, text = self._drop(tmp_path, "Ada Lovelace")
        assert result.seats_emptied == 1
        assert "Ada Lovelace" not in text and "Grace Hopper" in text

    def test_a_seat_under_the_roster_name_is_emptied(self, tmp_path):
        result, text = self._drop(tmp_path, "Augusta Lovelace")
        assert result.seats_emptied == 1
        assert "Augusta Lovelace" not in text

    def test_the_seat_is_emptied_not_removed(self, tmp_path):
        """Version letters come from position, so a hole keeps the
        tablemates' papers unchanged."""
        _, text = self._drop(tmp_path, "Ada Lovelace")
        assert '"", "Grace Hopper"' in text


class TestTheDroppedCheckSeesEitherSpelling:
    """`check_dropped_are_unseated` is the guard that stops a departed
    student's paper printing. Looking at one spelling would let the other
    through."""

    def _check(self, seat_name):
        people = Roster([Student(name="Augusta Lovelace", skills=["AD"],
                                 sid="806001", preferred="Ada Lovelace",
                                 dropped=True)])
        assemble.check_dropped_are_unseated(people, chart_of(seat_name))

    def test_a_dropped_student_seated_under_the_printed_name_is_caught(self):
        with pytest.raises(assemble.AssemblyError, match="Ada Lovelace"):
            self._check("Ada Lovelace")

    def test_and_under_the_roster_name(self):
        with pytest.raises(assemble.AssemblyError, match="Ada Lovelace"):
            self._check("Augusta Lovelace")

    def test_someone_else_in_the_seat_is_not_a_problem(self):
        self._check("Grace Hopper")

class TestThePrintJobViewShowsIt:
    """`api_print` builds the "Who gets what" table. Reaching the roster file
    is not the same as reaching the screen: the view computed `preferred or
    name` inline before there was one definition, and a view that quietly
    stopped reading it would look like a caching bug -- which is exactly how
    this was first reported."""

    @pytest.fixture
    def course(self, tmp_path, monkeypatch, bank_dir):
        from checkit_printit import course as course_mod
        from checkit_printit import gui as gui_mod
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("P", bank=str(bank_dir), adopt=None)
        people = Roster([
            Student(name="Augusta Lovelace", skills=["AD"], sid="806001",
                    preferred="Ada Lovelace", section="820"),
            Student(name="Grace Hopper", skills=["AD"], sid="806002",
                    section="820"),
        ])
        path = os.path.join(str(tmp_path), "courses", "P", "roster.toml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(roster_mod.to_toml(people, "test"))
        return gui_mod.Course("P"), gui_mod

    def test_the_table_shows_the_printed_name(self, course):
        obj, gui_mod = course
        rows = {s["sid"] if "sid" in s else s["key"]: s
                for s in gui_mod.api_print(obj, {})["students"]}
        assert rows["806001"]["display"] == "Ada Lovelace"

    def test_and_the_roster_name_for_everyone_else(self, course):
        obj, gui_mod = course
        rows = {s["key"]: s for s in gui_mod.api_print(obj, {})["students"]}
        assert rows["806002"]["display"] == "Grace Hopper"

    def test_the_roster_name_is_still_sent_for_the_hover(self, course):
        """The table shows the printed name and puts the roster one on
        hover, so the two can be reconciled without opening a file."""
        obj, gui_mod = course
        rows = {s["key"]: s for s in gui_mod.api_print(obj, {})["students"]}
        assert rows["806001"]["name"] == "Augusta Lovelace"

class TestTheCollisionWarningLooksAtThePaper:
    """`Chart.collisions` compares the letters in the chart. A per-run pin in
    `[versions]` changes the paper and leaves the chart alone -- that is what
    it is for -- so the only mechanism that can put the same questions in two
    adjacent hands was the one the build could not see.

    Measured before the fix: a 48-student run with a pinned collision
    reported `0 collision(s)`, and `verify_run` found it in the PDF.
    """

    def _run(self, pinned):
        people = Roster([
            Student(name="Augusta Lovelace", skills=["AD"], sid="806001",
                    preferred="Ada Lovelace"),
            Student(name="Grace Hopper", skills=["AD"], sid="806002"),
        ])
        chart = chart_of("Augusta Lovelace", "Grace Hopper")   # A then B

        class P(Pub):
            student_versions = pinned
        seeds = {("A", "AD"): 401, ("B", "AD"): 402}
        handouts, _ = assemble.build_handouts(people, chart, P(), seeds)
        return assemble.printed_collisions(chart, people, handouts)

    def test_alternating_seats_do_not_collide(self):
        assert self._run({}) == []

    def test_a_pin_onto_the_neighbours_version_is_reported(self):
        found = self._run({"806001": "B"})
        assert len(found) == 1
        a, b, version = found[0]
        assert {a.name, b.name} == {"Augusta Lovelace", "Grace Hopper"}

    def test_it_names_the_version_that_printed_not_the_seats(self):
        """The seat still says A. Reporting A would send the instructor to
        the wrong paper."""
        _, _, version = self._run({"806001": "B"})[0]
        assert version == "B"

    def test_the_chart_itself_still_says_there_is_no_collision(self):
        """The two answers differ, which is the whole reason for the new
        one. If this ever starts failing, the pin began editing the chart.
        """
        chart = chart_of("Augusta Lovelace", "Grace Hopper")
        assert chart.collisions() == []

    def test_the_report_asks_for_the_printed_one(self):
        """The wiring, not the function. Pointing `_report_dict` back at
        `chart.collisions()` reinstates the whole bug, and every test that
        calls `printed_collisions` directly stays green."""
        people = Roster([
            Student(name="Augusta Lovelace", skills=["AD"], sid="806001",
                    preferred="Ada Lovelace"),
            Student(name="Grace Hopper", skills=["AD"], sid="806002"),
        ])
        chart = chart_of("Augusta Lovelace", "Grace Hopper")

        class P(Pub):
            student_versions = {"806001": "B"}
        seeds = {("A", "AD"): 401, ("B", "AD"): 402}
        handouts, unseated = assemble.build_handouts(people, chart, P(), seeds)
        report = assemble._report_dict(handouts, [], None, [("AD", 402)],
                                       unseated, chart, {}, {}, people)
        assert len(report["collisions"]) == 1
        assert report["collisions"][0][2] == "B"

    def test_the_version_is_read_by_id_not_by_printed_name(self):
        """Two students can share a printed name -- a preferred name may be
        somebody else's roster name -- and then a name lookup reads the
        wrong row. The seat resolves to one student; the version must come
        from that student's id.
        """
        people = Roster([
            # Prints as "Ada Lovelace", and is seated.
            Student(name="Augusta Lovelace", skills=["AD"], sid="806001",
                    preferred="Ada Lovelace"),
            Student(name="Grace Hopper", skills=["AD"], sid="806002"),
            # Also prints as "Ada Lovelace", and is not seated at all.
            Student(name="Ada Lovelace", skills=["AD"], sid="806003"),
        ])
        chart = chart_of("Augusta Lovelace", "Grace Hopper")   # A then B

        class P(Pub):
            student_versions = {"806001": "B"}                 # onto B
        seeds = {("A", "AD"): 401, ("B", "AD"): 402}
        handouts, _ = assemble.build_handouts(people, chart, P(), seeds)
        found = assemble.printed_collisions(chart, people, handouts)
        assert len(found) == 1, (
            "the seated student holds B and so does their neighbour; reading "
            "the version by printed name picks up the unseated namesake's A")

    def test_a_pin_resolved_through_the_printed_name_is_seen_too(self):
        """The seat may be written either way; the pin is keyed by id. Both
        have to land on the same student or the check reads the wrong row."""
        people = Roster([
            Student(name="Augusta Lovelace", skills=["AD"], sid="806001",
                    preferred="Ada Lovelace"),
            Student(name="Grace Hopper", skills=["AD"], sid="806002"),
        ])
        chart = chart_of("Ada Lovelace", "Grace Hopper")

        class P(Pub):
            student_versions = {"806001": "B"}
        seeds = {("A", "AD"): 401, ("B", "AD"): 402}
        handouts, _ = assemble.build_handouts(people, chart, P(), seeds)
        assert len(assemble.printed_collisions(chart, people, handouts)) == 1

    def test_an_unseated_student_is_not_a_collision(self):
        people = Roster([Student(name="Ada Lovelace", skills=["AD"], sid="806001")])
        chart = chart_of("Grace Hopper", "Someone Else")
        seeds = {("A", "AD"): 401, ("B", "AD"): 402}
        handouts, _ = assemble.build_handouts(people, chart, Pub(), seeds)
        assert assemble.printed_collisions(chart, people, handouts) == []

    def test_different_tables_are_never_adjacent(self):
        people = Roster([
            Student(name="Ada Lovelace", skills=["AD"], sid="806001"),
            Student(name="Grace Hopper", skills=["AD"], sid="806002"),
        ])
        chart = seating_mod.Chart(
            seats=[seating_mod.Seat(name="Ada Lovelace", group=0, version="A"),
                   seating_mod.Seat(name="Grace Hopper", group=1, version="A")],
            versions=("A", "B"))
        seeds = {("A", "AD"): 401, ("B", "AD"): 402}
        handouts, _ = assemble.build_handouts(people, chart, Pub(), seeds)
        assert assemble.printed_collisions(chart, people, handouts) == []
