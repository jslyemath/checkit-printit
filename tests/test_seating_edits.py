"""Stage three of the seating tab: a room that can be changed.

Dragging itself is in the browser and is not tested here (the front-end
harness is deliberately off while the views keep changing). What *is*
tested is everything a drag ends in: the guard on the way back in, what
Save writes, and what it refuses to overwrite.

Every refusal is tested the same way round -- build a room, assert it
passes, then break exactly one thing and assert it does not. A test that
only ever sees a broken room proves the error message exists, not that
the rule fires; this shape proves the raise came from the change.

No real student appears here.
"""

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import room as room_mod
from checkit_printit import seating as seating_mod


def a_room(students=("s1-0", "s1-1", "s1-2", "s1-3")):
    """One section, one 2x2 table, four chairs, filled from `students`."""
    r = room_mod.empty("ABCD")
    section = room_mod.new_section("820", order=1)
    shape = room_mod.make_shape("table-2x2", (300, 200), "s1")
    for seat, who in zip(shape["seats"], students):
        seat["student"] = who or ""
        seat["version"] = "A"
    section["shapes"].append(shape)
    section["groups"].append(
        {"id": "g1", "label": "table 1",
         "seats": [s["id"] for s in shape["seats"]], "order": 1})
    r["sections"].append(section)
    return r


def chairs(room, index=0):
    return room["sections"][index]["shapes"][0]["seats"]


# --------------------------------------------------------------------------
# room.check
# --------------------------------------------------------------------------

class TestTheRoomComingBackIsChecked:
    """`check` is the door a room arrives by from the browser. Each rule
    here guards something that fails *quietly* further down -- which is
    what earns a refusal rather than a shrug."""

    def test_a_good_room_passes(self):
        assert room_mod.check(a_room()) is not None

    def test_a_room_from_another_printit_is_refused(self):
        r = a_room()
        r["schema"] = room_mod.VERSION + 1
        with pytest.raises(room_mod.RoomError, match="schema"):
            room_mod.check(r)

    def test_a_room_with_no_letters_to_hand_out_is_refused(self):
        r = a_room()
        r["versions"] = []
        with pytest.raises(room_mod.RoomError, match="version letter"):
            room_mod.check(r)

    def test_a_shape_this_build_cannot_draw_is_refused(self):
        """The canvas skips an unknown shape, so the desk and everyone at
        it vanish from the drawing while staying in the file. Silent."""
        r = a_room()
        r["sections"][0]["shapes"][0]["kind"] = "pentagon"
        with pytest.raises(room_mod.RoomError) as caught:
            room_mod.check(r)
        assert "pentagon" in str(caught.value)
        assert "table-2x2" in str(caught.value), "say what there is instead"

    def test_two_chairs_with_one_id_are_refused(self):
        """A group names its members by seat id, so a repeat quietly puts
        the wrong person in a group -- and so on the wrong paper."""
        r = a_room()
        chairs(r)[1]["id"] = chairs(r)[0]["id"]
        with pytest.raises(room_mod.RoomError, match="both called"):
            room_mod.check(r)

    def test_one_student_in_two_chairs_is_refused(self):
        """Two papers printed for one person, and two lines in the chart."""
        r = a_room()
        chairs(r)[2]["student"] = chairs(r)[0]["student"]
        with pytest.raises(room_mod.RoomError, match="two seats"):
            room_mod.check(r)

    def test_a_stranger_in_a_chair_is_refused(self):
        r = a_room()
        known = {"s1-0", "s1-1", "s1-2", "s1-3"}
        assert room_mod.check(r, known) is not None
        chairs(r)[0]["student"] = "nobody"
        with pytest.raises(room_mod.RoomError, match="not on the roster"):
            room_mod.check(r, known)

    def test_an_older_key_still_passes(self):
        """`known` is every key the roster answers to, not just the
        preferred one, so a room written before a student gained an SID
        still loads rather than being refused as a stranger."""
        r = a_room(students=("ada@example.edu", "s1-1", "s1-2", "s1-3"))
        room_mod.check(r, {"806001", "ada@example.edu", "s1-1", "s1-2",
                           "s1-3"})

    def test_no_roster_means_no_opinion(self):
        """A course can have a room before it has a roster."""
        room_mod.check(a_room(), None)

    @pytest.mark.parametrize("bad", [
        [float("nan"), 0], [0, float("inf")], ["300", 200], [300],
        [300, 200, 100], None, [True, False],
    ])
    def test_a_position_that_is_not_two_numbers_is_refused(self, bad):
        """`[true, false]` is in here on purpose: `isinstance(True, int)`
        is true in Python and JSON gives real bools, so without the bool
        test a chair could legally sit at (1, 0).

        NaN is the one that matters most. Every comparison against it is
        false, so the seat would be nobody's neighbour, take a letter
        with no constraint on it, and clash on paper with nothing said.
        """
        r = a_room()
        chairs(r)[0]["at"] = bad
        with pytest.raises(room_mod.RoomError, match="not a position"):
            room_mod.check(r)

    def test_a_desk_at_a_position_that_is_not_one_is_refused(self):
        r = a_room()
        r["sections"][0]["shapes"][0]["at"] = ["middle", "left"]
        with pytest.raises(room_mod.RoomError, match="not a position"):
            room_mod.check(r)

    def test_a_canvas_with_no_size_is_refused(self):
        r = a_room()
        r["sections"][0]["canvas"]["width"] = 0
        with pytest.raises(room_mod.RoomError, match="not a size"):
            room_mod.check(r)

    def test_a_group_naming_a_chair_that_is_not_there_is_refused(self):
        r = a_room()
        r["sections"][0]["groups"][0]["seats"].append("s9-9")
        with pytest.raises(room_mod.RoomError, match="not in that room"):
            room_mod.check(r)

    def test_a_group_may_not_reach_into_another_section(self):
        """Sections are separate charts. A group spanning two of them has
        no meaning, and `seats_of` would never find the far seat."""
        r = a_room()
        second = room_mod.new_section("830", order=2)
        second["shapes"].append(room_mod.make_shape("desk", (100, 100), "s2"))
        r["sections"].append(second)
        assert room_mod.check(r) is not None
        r["sections"][0]["groups"][0]["seats"].append("s2-0")
        with pytest.raises(room_mod.RoomError, match="not in that room"):
            room_mod.check(r)

    def test_and_may_not_reach_backwards_into_one_either(self):
        """The direction the test above cannot see. Checking a group
        against every seat in the *room* rather than every seat in its
        own section passes the forward case by accident -- the far
        section has not been walked yet -- and only fails when the group
        is in the later section. Which is the ordering a real room has,
        because 830 is drawn after 820."""
        r = a_room()
        second = room_mod.new_section("830", order=2)
        second["shapes"].append(room_mod.make_shape("desk", (100, 100), "s2"))
        second["groups"].append(
            {"id": "g2", "label": "table 8", "seats": ["s2-0"], "order": 1})
        r["sections"].append(second)
        assert room_mod.check(r) is not None
        r["sections"][1]["groups"][0]["seats"].append("s1-0")
        with pytest.raises(room_mod.RoomError, match="not in that room"):
            room_mod.check(r)

    def test_a_place_in_the_print_order_that_is_not_a_number_is_refused(self):
        r = a_room()
        r["sections"][0]["groups"][0]["order"] = "first"
        with pytest.raises(room_mod.RoomError, match="print order"):
            room_mod.check(r)

    def test_a_desk_may_carry_its_own_size(self):
        r = a_room()
        shape = r["sections"][0]["shapes"][0]
        shape["w"], shape["h"] = 400, 90
        assert room_mod.check(r) is not None
        for bad in (0, -10, "wide", True):
            shape["w"] = bad
            with pytest.raises(room_mod.RoomError, match="not a size"):
                room_mod.check(r)

    def test_a_desk_may_be_turned(self):
        r = a_room()
        shape = r["sections"][0]["shapes"][0]
        for ok in (0, 45, -90, 359):
            shape["angle"] = ok
            assert room_mod.check(r) is not None
        for bad in (360, -400, "sideways", True):
            shape["angle"] = bad
            with pytest.raises(room_mod.RoomError, match="degrees"):
                room_mod.check(r)

    def test_turning_a_desk_does_not_reach_the_chart(self):
        """Rotating rewrites the seats' own offsets, so a seat is
        always simply where it says it is. Nothing downstream -- the
        neighbour distances, the colouring, `seating.toml` -- has to
        learn about angles, which is the whole reason it is stored
        that way round."""
        r = a_room()
        shape = r["sections"][0]["shapes"][0]
        before = room_mod.seats_of(r["sections"][0])
        shape["angle"] = 90
        after = room_mod.seats_of(r["sections"][0])
        assert [(s["x"], s["y"]) for s in before] == \
               [(s["x"], s["y"]) for s in after], \
            "seats_of must read the offsets and not the angle"

    def test_a_colour_is_an_angle_on_the_wheel(self):
        """One number, because the three shades the canvas draws are
        derived from it rather than stored."""
        r = a_room()
        group = r["sections"][0]["groups"][0]
        group["hue"] = 150
        assert room_mod.check(r) is not None
        # No hue at all is the normal state: a group that has never
        # been coloured takes one off the palette by position.
        group["hue"] = None
        assert room_mod.check(r) is not None
        for bad in (-1, 360, 400, "blue", True, float("nan")):
            group["hue"] = bad
            with pytest.raises(room_mod.RoomError, match="colour wheel"):
                room_mod.check(r)

    def test_how_vivid_a_colour_is_scales_the_standard_one(self):
        """Hue says which colour; chroma says how much of it. Lightness
        is not stored at all -- it is what decides whether a name can
        be read from the back of the room, so the picker does not get
        to set it."""
        r = a_room()
        group = r["sections"][0]["groups"][0]
        group["hue"] = 150
        # Absent is the normal state and means the standard strength,
        # so every group drawn before the picker existed is unchanged.
        assert "chroma" not in group
        assert room_mod.check(r) is not None
        for ok in (0, 0.4, 1, 1.4, None):
            group["chroma"] = ok
            assert room_mod.check(r) is not None, f"{ok!r} should pass"
        for bad in (-0.1, 1.5, 2, "vivid", True, float("nan")):
            group["chroma"] = bad
            with pytest.raises(room_mod.RoomError, match="chroma"):
                room_mod.check(r)

    def test_a_label_may_only_hang_on_a_desk_that_is_there(self):
        """It would silently fall back to the middle of the group's
        seats, and look like the anchor had been forgotten."""
        r = a_room()
        r["sections"][0]["groups"][0]["label_at"] = {"shape": "s1",
                                                     "anchor": "s"}
        assert room_mod.check(r) is not None
        r["sections"][0]["groups"][0]["label_at"] = {"shape": "s9",
                                                     "anchor": "s"}
        with pytest.raises(room_mod.RoomError, match="not a desk"):
            room_mod.check(r)

    def test_a_label_sits_in_one_of_the_nine_places(self):
        r = a_room()
        for anchor in room_mod.ANCHORS:
            r["sections"][0]["groups"][0]["label_at"] = {"shape": "s1",
                                                         "anchor": anchor}
            assert room_mod.check(r) is not None
        r["sections"][0]["groups"][0]["label_at"] = {"shape": "s1",
                                                     "anchor": "middle-ish"}
        with pytest.raises(room_mod.RoomError) as caught:
            room_mod.check(r)
        assert "nw" in str(caught.value), "say what the nine are"

    def test_the_canvas_draws_the_nine_the_model_allows(self):
        """Two copies of the same list, in two languages: the model
        checks the names and the canvas draws the positions. They have
        to agree, and nothing but a test can make them."""
        import pathlib
        js = (pathlib.Path(__file__).parent.parent / "src" / "checkit_printit"
              / "gui" / "static" / "seating" / "seating.js"
              ).read_text(encoding="utf-8")
        block = js.split("const ANCHORS = {", 1)[1].split("};", 1)[0]
        drawn = {part.split(":")[0].strip()
                 for part in block.split(",") if ":" in part}
        assert drawn == set(room_mod.ANCHORS), (
            f"the canvas draws {sorted(drawn)}, the model allows "
            f"{sorted(room_mod.ANCHORS)}")

    def test_an_empty_chair_is_fine(self):
        """The commonest state in a real room, and an over-strict check
        is as much a bug as a missing one."""
        r = a_room(students=("s1-0", "", "", "s1-3"))
        room_mod.check(r, {"s1-0", "s1-3"})

    def test_a_chair_in_no_group_is_fine(self):
        r = a_room()
        r["sections"][0]["groups"] = []
        room_mod.check(r)

    def test_a_room_with_nothing_in_it_is_fine(self):
        room_mod.check(room_mod.empty("ABCD"))

    def test_save_does_not_check(self, tmp_path):
        """Deliberate, and worth pinning: the CLI and the tests build
        partial rooms on purpose, so the guard belongs at the one door
        untrusted data comes through, not at every write."""
        r = a_room()
        r["sections"][0]["shapes"][0]["kind"] = "pentagon"
        room_mod.save(str(tmp_path / "room.json"), r)
        assert (tmp_path / "room.json").is_file()


# --------------------------------------------------------------------------
# Who wrote the chart
# --------------------------------------------------------------------------

class TestWhetherTheChartIsOurs:
    """Overwriting `seating.toml` is how a term's seating disappears, so
    the tab only rewrites one it wrote itself."""

    def test_a_chart_this_tool_wrote_is_recognised(self, tmp_path):
        """The round trip, not the string: if someone rewords the header
        the detector stops recognising its own output, and the app
        quietly starts refusing to update a chart it owns."""
        path = tmp_path / "seating.toml"
        path.write_text(seating_mod.to_toml(a_room(), lambda k: k),
                        encoding="utf-8")
        assert seating_mod.was_generated(str(path))

    def test_a_chart_someone_typed_is_not(self, tmp_path):
        path = tmp_path / "seating.toml"
        path.write_text('versions = ["A", "B"]\n\n[[group]]\n'
                        'seats = ["Ada Lovelace"]\n', encoding="utf-8")
        assert not seating_mod.was_generated(str(path))

    def test_an_imported_chart_is_not(self, tmp_path):
        """The 10-02 shape: a chart written from a Control Center export
        carries its own provenance line and must not be touched."""
        path = tmp_path / "seating.toml"
        path.write_text("# The seating chart for this run, taken from the "
                        "Control Center export.\n#\n"
                        '# Row order IS the order.\n\nversions = ["A"]\n',
                        encoding="utf-8")
        assert not seating_mod.was_generated(str(path))

    def test_a_chart_that_is_not_there_is_ours_to_write(self, tmp_path):
        assert not seating_mod.was_generated(str(tmp_path / "nothing.toml"))

    def test_the_mark_is_in_the_header_not_hunted_for(self, tmp_path):
        """Only the first few lines are read. A chart whose body happens
        to contain the sentence -- a comment someone pasted -- is still
        theirs."""
        path = tmp_path / "seating.toml"
        path.write_text('versions = ["A"]\n' + "\n" * 20
                        + seating_mod.GENERATED_MARK + "\n", encoding="utf-8")
        assert not seating_mod.was_generated(str(path))


# --------------------------------------------------------------------------
# Saving from the tab
# --------------------------------------------------------------------------

@pytest.fixture
def course(tmp_path, monkeypatch, bank_dir):
    from checkit_printit import course as course_mod
    from checkit_printit import gui as gui_mod
    from checkit_printit import roster as roster_mod
    from checkit_printit.roster import Roster, Student
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    course_mod.init("P", bank=str(bank_dir), adopt=None)
    people = Roster([
        Student(name="Ada Lovelace", skills=[], sid="s1-0", section="820"),
        Student(name="Blaise Pascal", skills=[], sid="s1-1", section="820"),
        Student(name="Carl Gauss", skills=[], sid="s1-2", section="820"),
        Student(name="Doris Day", skills=[], sid="s1-3", section="830"),
    ])
    with open(course_mod.file_in("P", "roster"), "w", encoding="utf-8") as f:
        f.write(roster_mod.to_toml(people, "test"))
    return gui_mod.Course("P"), gui_mod, course_mod


class TestSaving:
    def test_the_route_is_wired(self):
        """A handler nothing routes to is a handler nobody can reach --
        which is how the response pull sat finished and invisible."""
        from checkit_printit import gui as gui_mod
        assert gui_mod.ROUTES["/api/seating/save"] is gui_mod.api_seating_save

    def test_a_room_is_written(self, course):
        obj, gui_mod, course_mod = course
        gui_mod.api_seating_save(obj, {"room": a_room()})
        on_disk = room_mod.load(course_mod.file_in("P", "room"))
        assert [s["name"] for s in on_disk["sections"]] == ["820"]

    def test_a_drag_round_trips(self, course):
        """What a swap actually is, once the browser is done: two
        `student` fields exchanged, read back off the disk."""
        obj, gui_mod, course_mod = course
        r = a_room()
        seats = chairs(r)
        seats[0]["student"], seats[1]["student"] = \
            seats[1]["student"], seats[0]["student"]
        gui_mod.api_seating_save(obj, {"room": r})
        back = chairs(room_mod.load(course_mod.file_in("P", "room")))
        assert [s["student"] for s in back][:2] == ["s1-1", "s1-0"]

    def test_a_swap_leaves_the_letters_on_the_chairs(self, course):
        """The colouring is of the *room*: letters belong to chairs, not
        to people, or two neighbours trading places could end up holding
        the same paper."""
        obj, gui_mod, course_mod = course
        r = a_room()
        for letter, seat in zip("ABCD", chairs(r)):
            seat["version"] = letter
        chairs(r)[0]["student"], chairs(r)[1]["student"] = "s1-1", "s1-0"
        gui_mod.api_seating_save(obj, {"room": r})
        back = chairs(room_mod.load(course_mod.file_in("P", "room")))
        assert [s["version"] for s in back] == ["A", "B", "C", "D"]

    def test_a_bad_room_is_refused(self, course):
        obj, gui_mod, _ = course
        r = a_room()
        chairs(r)[1]["student"] = chairs(r)[0]["student"]
        with pytest.raises(gui_mod.GuiError, match="two seats"):
            gui_mod.api_seating_save(obj, {"room": r})

    def test_a_refused_room_is_not_written(self, course):
        """The order matters and nothing else would notice it being
        wrong: check *then* save, so a refusal leaves the last good room
        on disk instead of a half-written one."""
        obj, gui_mod, course_mod = course
        gui_mod.api_seating_save(obj, {"room": a_room()})
        good = json.dumps(room_mod.load(course_mod.file_in("P", "room")))

        broken = a_room()
        broken["sections"][0]["shapes"][0]["kind"] = "pentagon"
        with pytest.raises(gui_mod.GuiError):
            gui_mod.api_seating_save(obj, {"room": broken})
        assert json.dumps(
            room_mod.load(course_mod.file_in("P", "room"))) == good

    def test_a_request_with_no_room_says_so(self, course):
        obj, gui_mod, _ = course
        with pytest.raises(gui_mod.GuiError, match="no room"):
            gui_mod.api_seating_save(obj, {})

    def test_the_canvas_gets_the_saved_room_back(self, course):
        """So the tab resyncs off the answer rather than guessing it
        matched -- the same reason the roster save returns the table."""
        obj, gui_mod, _ = course
        out = gui_mod.api_seating_save(obj, {"room": a_room()})
        assert out["room"]["sections"][0]["name"] == "820"
        assert out["names"], "and the names, or the next draw is blank"


class TestWhatSaveDoesToTheChart:
    """A room nothing reads is a toy: the build opens `seating.toml`. But
    overwriting that file is how a term's seating disappears."""

    def test_it_writes_a_chart_when_there_is_none(self, course):
        obj, gui_mod, course_mod = course
        gui_mod.api_seating_save(obj, {"room": a_room()})
        chart = course_mod.file_in("P", "seating")
        assert os.path.isfile(chart)
        assert "Ada Lovelace" in open(chart, encoding="utf-8").read()

    def test_it_pins_what_the_room_said(self, course):
        """Not re-derived. The room chose the letters by colouring it,
        and `alternate` could only cycle a list."""
        obj, gui_mod, course_mod = course
        r = a_room()
        for letter, seat in zip("ABCD", chairs(r)):
            seat["version"] = letter
        gui_mod.api_seating_save(obj, {"room": r})
        chart = seating_mod.load(course_mod.file_in("P", "seating"))
        got = {s.name: s.version for s in chart.seats if s.name}
        assert got["Ada Lovelace"] == "A"
        assert got["Doris Day"] == "D"

    def test_it_rewrites_a_chart_it_wrote_before(self, course):
        obj, gui_mod, course_mod = course
        gui_mod.api_seating_save(obj, {"room": a_room()})
        r = a_room(students=("s1-3", "s1-2", "s1-1", "s1-0"))
        out = gui_mod.api_seating_save(obj, {"room": r})
        assert "rewritten" in out["note"]
        chart = seating_mod.load(course_mod.file_in("P", "seating"))
        assert [s.name for s in chart.seats][0] == "Doris Day"

    def test_it_leaves_an_imported_chart_alone(self, course):
        """The 10-02 lesson, enforced: a file that carries an instruction
        is not a file to reach past. The answer says so, rather than the
        app quietly deciding it knows better."""
        obj, gui_mod, course_mod = course
        chart = course_mod.file_in("P", "seating")
        mine = ('# From the Control Center export.\nversions = ["A"]\n\n'
                '[[group]]\nseats = ["Ada Lovelace"]\n')
        with open(chart, "w", encoding="utf-8") as f:
            f.write(mine)

        out = gui_mod.api_seating_save(obj, {"room": a_room()})
        assert open(chart, encoding="utf-8").read() == mine
        assert "left alone" in out["note"]
        # The room itself still saved: the refusal is about the chart.
        assert room_mod.load(course_mod.file_in("P", "room"))["sections"]

    def test_an_empty_room_does_not_replace_a_real_chart(self, course):
        """A fresh course opened in the tab, nudged, and saved must not
        turn a term's chart into an empty one."""
        obj, gui_mod, course_mod = course
        gui_mod.api_seating_save(obj, {"room": a_room()})
        chart = course_mod.file_in("P", "seating")
        before = open(chart, encoding="utf-8").read()

        bare = room_mod.empty("ABCD")
        bare["sections"].append(room_mod.new_section("820"))
        out = gui_mod.api_seating_save(obj, {"room": bare})
        assert open(chart, encoding="utf-8").read() == before
        assert "Nobody is sitting" in out["note"]

    def test_the_tab_is_told_which_it_will_be_before_pressing_save(self, course):
        obj, gui_mod, course_mod = course
        assert gui_mod.api_seating(obj, {})["chartIsOurs"] is True
        with open(course_mod.file_in("P", "seating"), "w",
                  encoding="utf-8") as f:
            f.write('versions = ["A"]\n')
        assert gui_mod.api_seating(obj, {})["chartIsOurs"] is False


class TestADroppedStudentStaysDropped:
    """The one that would have been silent. `set_dropped` cleared the
    chart and knew nothing about the room; once the tab writes the chart
    from the room, the next save would have walked them back onto the
    printed list with nothing going wrong on screen."""

    def test_dropping_empties_their_chair_in_the_room(self, course):
        from checkit_printit import roster as roster_mod
        obj, gui_mod, course_mod = course
        gui_mod.api_seating_save(obj, {"room": a_room()})

        done = roster_mod.set_dropped(
            course_mod.file_in("P", "roster"), "Ada Lovelace", True,
            course_mod.file_in("P", "seating"),
            course_mod.file_in("P", "room"))
        assert done.room_emptied == 1
        back = chairs(room_mod.load(course_mod.file_in("P", "room")))
        assert [s["student"] for s in back][0] == ""

    def test_the_chair_itself_stays(self, course):
        """Emptied, not removed -- the chair keeps its version letter, so
        nobody else at the table is re-lettered because one person left."""
        from checkit_printit import roster as roster_mod
        obj, gui_mod, course_mod = course
        r = a_room()
        for letter, seat in zip("ABCD", chairs(r)):
            seat["version"] = letter
        gui_mod.api_seating_save(obj, {"room": r})

        roster_mod.set_dropped(
            course_mod.file_in("P", "roster"), "Ada Lovelace", True,
            course_mod.file_in("P", "seating"),
            course_mod.file_in("P", "room"))
        back = chairs(room_mod.load(course_mod.file_in("P", "room")))
        assert len(back) == 4
        assert [s["version"] for s in back] == ["A", "B", "C", "D"]

    def test_the_next_save_does_not_reseat_them(self, course):
        """The failure this is all for, end to end."""
        from checkit_printit import roster as roster_mod
        obj, gui_mod, course_mod = course
        gui_mod.api_seating_save(obj, {"room": a_room()})
        roster_mod.set_dropped(
            course_mod.file_in("P", "roster"), "Ada Lovelace", True,
            course_mod.file_in("P", "seating"),
            course_mod.file_in("P", "room"))

        fresh = room_mod.load(course_mod.file_in("P", "room"))
        gui_mod.api_seating_save(obj, {"room": fresh})
        chart = open(course_mod.file_in("P", "seating"),
                     encoding="utf-8").read()
        assert "Ada Lovelace" not in chart
        assert "Blaise Pascal" in chart, "and nobody else lost their seat"

    def test_the_gui_drop_passes_the_room(self, course):
        """Through the handler the browser actually calls, not the
        function underneath it: a fix that reaches one path and not the
        other is this codebase's commonest bug."""
        obj, gui_mod, course_mod = course
        gui_mod.api_seating_save(obj, {"room": a_room()})
        gui_mod.api_roster_drop(obj, {"who": "Ada Lovelace", "dropped": True})
        back = chairs(room_mod.load(course_mod.file_in("P", "room")))
        assert [s["student"] for s in back][0] == ""

    def test_they_are_not_offered_a_chair_again(self, course):
        """Dropped students are left out of the names the canvas draws
        from, so they cannot be dragged back in by accident."""
        obj, gui_mod, _ = course
        gui_mod.api_roster_drop(obj, {"who": "Ada Lovelace", "dropped": True})
        out = gui_mod.api_seating(obj, {})
        assert "s1-0" not in out["names"]
        assert "s1-1" in out["names"]

    def test_a_room_that_cannot_be_read_is_not_rewritten(self, course,
                                                         tmp_path):
        """A room from a newer printit is not ours to edit. The chart is
        what stops the printing and it has already been cleared."""
        from checkit_printit import roster as roster_mod
        obj, gui_mod, course_mod = course
        path = course_mod.file_in("P", "room")
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"schema": room_mod.VERSION + 1}, f)
        before = open(path, encoding="utf-8").read()

        done = roster_mod.set_dropped(
            course_mod.file_in("P", "roster"), "Ada Lovelace", True,
            course_mod.file_in("P", "seating"), path)
        assert done.room_emptied == 0
        assert open(path, encoding="utf-8").read() == before


class TestWhoIsStillStanding:
    """The tray needs to know who has no chair and which section they are
    in, or a new student can never be put into the room at all."""

    def test_sections_come_through(self, course):
        obj, gui_mod, _ = course
        out = gui_mod.api_seating(obj, {})
        assert out["sections"]["s1-0"] == "820"
        assert out["sections"]["s1-3"] == "830"

    def test_everyone_on_the_roster_is_offered(self, course):
        """Including people no room has ever seated -- that is the point
        of the tray."""
        obj, gui_mod, _ = course
        out = gui_mod.api_seating(obj, {})
        assert set(out["names"]) == {"s1-0", "s1-1", "s1-2", "s1-3"}
