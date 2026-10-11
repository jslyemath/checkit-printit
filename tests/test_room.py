"""The room: desks, groups, and which paper each seat gets.

Stage one of the seating tab, and the part that decides whether the rest
is easy: the data model, the version assignment, and the `seating.toml`
a room produces. No canvas yet.

The assignment is graph coloring -- seats are vertices, "must differ" is
an edge, letters are colors -- so what is worth testing is the thing
coloring is for: that neighbours differ, that it degrades sensibly when
there are more seats at a table than letters in the bag, and that what it
decided survives the trip out to the file the build actually reads.

No real student appears here.
"""

import json
import os
import random
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import room as room_mod
from checkit_printit import seating as seating_mod

FAR = room_mod.NEIGHBOUR_DISTANCE * 3


def table(shape_id, at, count, spacing=40):
    """A desk with `count` seats in a row on it."""
    return {
        "id": shape_id, "kind": "table", "at": list(at),
        "seats": [{"id": f"{shape_id}-{i}", "at": [i * spacing, 0],
                   "student": f"id{shape_id}{i}"}
                  for i in range(count)],
    }


def section_with(*shapes, groups=None, name="820"):
    s = room_mod.new_section(name)
    s["shapes"] = list(shapes)
    s["groups"] = list(groups or [])
    return s


def group(gid, shape, count, order=None, label=""):
    return {"id": gid, "label": label or gid,
            "seats": [f"{shape}-{i}" for i in range(count)], "order": order}


def versions_at(section, chosen):
    return [chosen[s["id"]] for s in room_mod.seats_of(section)]


def spot_them(section, spots):
    """Set `spot` on the named seats, as the canvas does."""
    for shape in section["shapes"]:
        for seat in shape["seats"]:
            if seat["id"] in spots:
                seat["spot"] = spots[seat["id"]]


def order_them(section, orders):
    """Set `order` -- a seat's place across the whole room."""
    for shape in section["shapes"]:
        for seat in shape["seats"]:
            if seat["id"] in orders:
                seat["order"] = orders[seat["id"]]


class TestTheStackComesOutInOrder:
    def test_a_room_nobody_reordered_prints_as_it_was_built(self):
        s = section_with(table("t1", (0, 0), 4),
                         groups=[group("g1", "t1", 4)])
        assert room_mod.stack_order(s) == ["t1-0", "t1-1", "t1-2", "t1-3"]

    def test_a_seats_spot_decides_where_it_prints_in_its_group(self):
        """`group.order` puts the tables in order; `spot` puts the seats
        in order inside one. Both have to reach `stack_order`, because
        that is what the chart writer asks for the stack."""
        s = section_with(table("t1", (0, 0), 4),
                         groups=[group("g1", "t1", 4)])
        # The canvas always renumbers a whole group, so this is the
        # shape the file really takes: every seat spotted.
        spot_them(s, {"t1-0": 4, "t1-1": 3, "t1-2": 2, "t1-3": 1})
        assert room_mod.stack_order(s) == \
            ["t1-3", "t1-2", "t1-1", "t1-0"]

    def test_a_half_spotted_group_prints_the_spotted_ones_first(self):
        """Only reachable by hand-editing the file -- the canvas spots a
        whole group at a time -- so the rule is chosen to match the one
        a group already follows: a group with no `order` prints after
        every group that has one, and a seat with no `spot` prints after
        every seat that has one. Among themselves, both keep the order
        they were listed in."""
        s = section_with(table("t1", (0, 0), 4),
                         groups=[group("g1", "t1", 4)])
        spot_them(s, {"t1-2": 1})
        assert room_mod.stack_order(s) == ["t1-2", "t1-0", "t1-1", "t1-3"]

    def test_a_groups_seat_list_is_never_reordered_for_printing(self):
        """The list is who sits beside whom, and that is the only record
        of it. Sorting it by `spot` -- which `ordered_groups` used to do
        -- made the chart claim two people sitting diagonally across a
        table were side by side, and the collision check believed it."""
        s = section_with(table("t1", (0, 0), 4),
                         groups=[group("g1", "t1", 4)])
        spot_them(s, {"t1-0": 4, "t1-1": 3, "t1-2": 2, "t1-3": 1})
        assert room_mod.ordered_groups(s)[0]["seats"] == \
            ["t1-0", "t1-1", "t1-2", "t1-3"]

    def test_ordering_a_group_does_not_touch_the_room(self):
        """`ordered_groups` hands back a view for the writer to read.
        Sorting the group's own list in place would quietly reorder the
        document every time anybody asked what order it was in."""
        s = section_with(table("t1", (0, 0), 4),
                         groups=[group("g1", "t1", 4)])
        spot_them(s, {"t1-3": 1})
        before = list(s["groups"][0]["seats"])
        room_mod.ordered_groups(s)
        assert s["groups"][0]["seats"] == before

    def test_by_seat_crosses_the_tables(self):
        """The thing by-group ordering cannot express: one walk round
        the room, taking a paper from each table in turn."""
        s = section_with(table("t1", (0, 0), 2), table("t2", (0, 200), 2),
                         groups=[group("g1", "t1", 2, order=1),
                                 group("g2", "t2", 2, order=2)])
        assert room_mod.stack_order(s) == ["t1-0", "t1-1", "t2-0", "t2-1"]

        s["print_by"] = "seat"
        order_them(s, {"t1-0": 1, "t2-0": 2, "t1-1": 3, "t2-1": 4})
        assert room_mod.stack_order(s) == ["t1-0", "t2-0", "t1-1", "t2-1"]

    def test_by_seat_starts_from_the_by_group_answer(self):
        """Switching the plan with nothing yet dragged must not scramble
        the room: an unnumbered seat keeps the place the by-group stack
        gave it, so the two plans agree until somebody moves a seat."""
        s = section_with(table("t1", (0, 0), 2), table("t2", (0, 200), 2),
                         groups=[group("g1", "t1", 2, order=2),
                                 group("g2", "t2", 2, order=1)])
        by_group = room_mod.stack_order(s)
        s["print_by"] = "seat"
        assert room_mod.stack_order(s) == by_group

        # And one seat moved to the front leaves the rest as they were.
        order_them(s, {"t1-1": 1})
        assert room_mod.stack_order(s) == \
            ["t1-1"] + [x for x in by_group if x != "t1-1"]

    def test_by_seat_ignores_spot_free_of_its_group(self):
        """`order` is across the room, so it outranks `spot`, which is
        only a place inside one group."""
        s = section_with(table("t1", (0, 0), 3),
                         groups=[group("g1", "t1", 3)])
        s["print_by"] = "seat"
        spot_them(s, {"t1-0": 3, "t1-1": 2, "t1-2": 1})
        order_them(s, {"t1-0": 1, "t1-1": 2, "t1-2": 3})
        assert room_mod.stack_order(s) == ["t1-0", "t1-1", "t1-2"]


class TestATableGetsDifferentPapers:
    def test_four_seats_four_letters_are_all_different(self):
        s = section_with(table("t1", (0, 0), 4), groups=[group("g1", "t1", 4)])
        chosen, clashes = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "ABCD",
            rng=random.Random(1))
        assert sorted(versions_at(s, chosen)) == ["A", "B", "C", "D"]
        assert clashes == []

    def test_six_seats_six_letters_are_all_different(self):
        s = section_with(table("t1", (0, 0), 6), groups=[group("g1", "t1", 6)])
        chosen, clashes = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "ABCDEF",
            rng=random.Random(2))
        assert len(set(versions_at(s, chosen))) == 6 and clashes == []

    def test_two_seats_take_two_of_the_six(self):
        """The bag is the course's, not the table's: a pair draws two of
        whatever is available rather than always A and B."""
        s = section_with(table("t1", (0, 0), 2), groups=[group("g1", "t1", 2)])
        seen = set()
        for attempt in range(40):
            chosen, _ = room_mod.assign_versions(
                room_mod.seats_of(s), room_mod.group_of(s), "ABCDEF",
                rng=random.Random(attempt))
            picked = versions_at(s, chosen)
            assert len(set(picked)) == 2, "a table handed out a repeat"
            seen.update(picked)
        assert len(seen) > 2, "it always picks the same two"

    def test_more_seats_than_letters_repeats_as_little_as_possible(self):
        """Five at a table and four letters: something has to give, and
        what gives should be one repeat, not three."""
        s = section_with(table("t1", (0, 0), 5), groups=[group("g1", "t1", 5)])
        chosen, clashes = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "ABCD",
            rng=random.Random(3))
        counts = {}
        for v in versions_at(s, chosen):
            counts[v] = counts.get(v, 0) + 1
        assert sorted(counts.values()) == [1, 1, 1, 2]
        assert len(clashes) == 1, "it gave up more than it had to"

    def test_it_does_not_refuse(self):
        """Ten at a table and two letters is hopeless, and the answer is
        still a chart with the clashes named -- not an error."""
        s = section_with(table("t1", (0, 0), 10), groups=[group("g1", "t1", 10)])
        chosen, clashes = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "AB",
            rng=random.Random(4))
        assert len(chosen) == 10 and clashes


class TestARoomOfLooseDesks:
    """Every seat is a group of one, so the only thing stopping two
    neighbours matching is the geometry."""

    def test_desks_side_by_side_get_different_letters(self):
        shapes = [table(f"d{i}", (i * 60, 0), 1) for i in range(4)]
        s = section_with(*shapes)
        chosen, clashes = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "ABCD",
            rng=random.Random(5))
        assert clashes == []
        assert len(set(chosen.values())) == 4

    def test_desks_across_the_room_may_share(self):
        """Far apart is not a constraint, and pretending it is would run
        the bag of letters out for no reason."""
        shapes = [table(f"d{i}", (i * FAR, 0), 1) for i in range(6)]
        s = section_with(*shapes)
        chosen, clashes = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "AB",
            rng=random.Random(6))
        assert clashes == [], "distant desks were treated as neighbours"

    def test_two_tables_pushed_together_are_neighbours(self):
        """Different groups, adjacent seats. The group says nothing about
        it; only the drawing does."""
        a = table("t1", (0, 0), 2)
        b = table("t2", (80, 0), 2)
        s = section_with(a, b, groups=[group("g1", "t1", 2),
                                       group("g2", "t2", 2)])
        chosen, clashes = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "ABCD",
            rng=random.Random(7))
        assert clashes == []
        assert chosen["t1-1"] != chosen["t2-0"], "adjacent seats matched"


class TestTheShuffleIsAShuffle:
    def test_the_same_seed_gives_the_same_room(self):
        s = section_with(table("t1", (0, 0), 4), groups=[group("g1", "t1", 4)])
        first = room_mod.assign_versions(room_mod.seats_of(s),
                                         room_mod.group_of(s), "ABCD",
                                         rng=random.Random(8))[0]
        again = room_mod.assign_versions(room_mod.seats_of(s),
                                         room_mod.group_of(s), "ABCD",
                                         rng=random.Random(8))[0]
        assert first == again

    def test_different_seeds_move_people(self):
        s = section_with(table("t1", (0, 0), 4), groups=[group("g1", "t1", 4)])
        seen = set()
        for attempt in range(20):
            chosen = room_mod.assign_versions(
                room_mod.seats_of(s), room_mod.group_of(s), "ABCD",
                rng=random.Random(attempt))[0]
            seen.add(tuple(versions_at(s, chosen)))
        assert len(seen) > 1, "it is not shuffling at all"

    def test_the_letters_come_out_roughly_even(self):
        """Not required for correctness -- every distinct paper is drawn
        once either way -- but a room that is all A and one D reads as a
        mistake."""
        shapes = [table(f"t{i}", (0, i * 200), 4) for i in range(6)]
        s = section_with(*shapes,
                         groups=[group(f"g{i}", f"t{i}", 4) for i in range(6)])
        chosen, _ = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "ABCD",
            rng=random.Random(9))
        counts = {}
        for v in chosen.values():
            counts[v] = counts.get(v, 0) + 1
        assert max(counts.values()) - min(counts.values()) <= 1


class TestPrintOrder:
    def test_groups_come_out_in_the_order_they_were_clicked(self):
        s = section_with(table("t1", (0, 0), 2), table("t2", (0, 300), 2),
                         table("t3", (0, 600), 2),
                         groups=[group("g1", "t1", 2, order=3),
                                 group("g2", "t2", 2, order=1),
                                 group("g3", "t3", 2, order=2)])
        assert [g["id"] for g in room_mod.ordered_groups(s)] == \
            ["g2", "g3", "g1"]

    def test_an_unplaced_group_keeps_its_place_rather_than_vanishing(self):
        """The instructor is warned the order is incomplete and may go
        ahead; "roughly right" beats "missing"."""
        s = section_with(table("t1", (0, 0), 2), table("t2", (0, 300), 2),
                         groups=[group("g1", "t1", 2, order=None),
                                 group("g2", "t2", 2, order=1)])
        out = room_mod.ordered_groups(s)
        assert [g["id"] for g in out] == ["g2", "g1"]
        assert room_mod.unplaced(s) == ["g1"]

    def test_a_seat_in_no_group_prints_as_a_group_of_one(self):
        s = section_with(table("t1", (0, 0), 2), table("lone", (0, 400), 1),
                         groups=[group("g1", "t1", 2, order=1)])
        out = room_mod.ordered_groups(s)
        assert [g["seats"] for g in out] == [["t1-0", "t1-1"], ["lone-0"]]


class TestTheChartItProduces:
    """The build reads `seating.toml`, so a room has to emit one that
    behaves exactly as a hand-written chart does."""

    def room_of(self, section, versions="ABCD", seed=11):
        chosen, _ = room_mod.assign_versions(
            room_mod.seats_of(section), room_mod.group_of(section),
            versions, rng=random.Random(seed))
        room_mod.apply_versions(section, chosen)
        r = room_mod.empty(list(versions))
        r["sections"] = [section]
        return r, chosen

    def names(self, student_id):
        return f"Student {student_id}" if student_id else ""

    def test_every_letter_the_room_chose_survives_the_round_trip(
            self, tmp_path):
        """The whole point of stage one. If this does not hold, the canvas
        is drawing something the printer disagrees with."""
        s = section_with(table("t1", (0, 0), 4), table("t2", (0, 300), 4),
                         groups=[group("g1", "t1", 4, order=1),
                                 group("g2", "t2", 4, order=2)])
        r, chosen = self.room_of(s)
        path = tmp_path / "seating.toml"
        path.write_text(seating_mod.to_toml(r, self.names), encoding="utf-8")

        chart = seating_mod.load(str(path), versions=r["versions"])
        by_name = {seat.name: seat.version for seat in chart}
        for seat in room_mod.seats_of(s):
            assert by_name[self.names(seat["student"])] == chosen[seat["id"]]

    def test_the_seats_are_pinned_not_recomputed(self, tmp_path):
        """`alternate` would cycle A B C D down the list. The room chose a
        shuffle, so the letters have to be written down."""
        s = section_with(table("t1", (0, 0), 4), groups=[group("g1", "t1", 4)])
        r, chosen = self.room_of(s, seed=12)
        text = seating_mod.to_toml(r, self.names)
        assert "version =" in text
        path = tmp_path / "s.toml"
        path.write_text(text, encoding="utf-8")
        assert all(seat.pinned for seat in
                   seating_mod.load(str(path), versions=r["versions"]))

    def test_print_order_is_file_order(self, tmp_path):
        s = section_with(table("t1", (0, 0), 2), table("t2", (0, 300), 2),
                         groups=[group("g1", "t1", 2, order=2),
                                 group("g2", "t2", 2, order=1)])
        r, _ = self.room_of(s)
        path = tmp_path / "s.toml"
        path.write_text(seating_mod.to_toml(r, self.names), encoding="utf-8")
        chart = seating_mod.load(str(path), versions=r["versions"])
        assert [seat.name for seat in chart][:2] == \
            ["Student idt20", "Student idt21"]

    def test_sections_come_out_in_their_order(self, tmp_path):
        a = section_with(table("t1", (0, 0), 2),
                         groups=[group("g1", "t1", 2)], name="830")
        b = section_with(table("t2", (0, 0), 2),
                         groups=[group("g2", "t2", 2)], name="820")
        a["order"], b["order"] = 2, 1
        for sec in (a, b):
            chosen, _ = room_mod.assign_versions(
                room_mod.seats_of(sec), room_mod.group_of(sec), "ABCD",
                rng=random.Random(13))
            room_mod.apply_versions(sec, chosen)
        r = room_mod.empty("ABCD")
        r["sections"] = [a, b]
        text = seating_mod.to_toml(r, self.names)
        assert text.index("section 820") < text.index("section 830")

    def test_an_empty_chair_is_written_as_one(self, tmp_path):
        """A seat nobody sits in still exists in the room, and the chart
        has to say so rather than closing the gap."""
        s = section_with(table("t1", (0, 0), 3), groups=[group("g1", "t1", 3)])
        s["shapes"][0]["seats"][1]["student"] = ""
        r, _ = self.room_of(s)
        assert '""' in seating_mod.to_toml(r, self.names)

    def test_a_well_colored_room_has_no_collisions(self, tmp_path):
        """`collisions()` is the build's own check, and it still runs over
        what the app chose."""
        s = section_with(table("t1", (0, 0), 4), groups=[group("g1", "t1", 4)])
        r, _ = self.room_of(s)
        path = tmp_path / "s.toml"
        path.write_text(seating_mod.to_toml(r, self.names), encoding="utf-8")
        assert seating_mod.load(str(path),
                                versions=r["versions"]).collisions() == []

    def test_an_untouched_room_writes_no_stack_numbers(self, tmp_path):
        """The reason the order is derived and not stored: a room nobody
        has reordered produces the file it always did, byte for byte."""
        s = section_with(table("t1", (0, 0), 2), table("t2", (0, 300), 2),
                         groups=[group("g1", "t1", 2, order=1),
                                 group("g2", "t2", 2, order=2)])
        r, _ = self.room_of(s)
        assert "at =" not in seating_mod.to_toml(r, self.names)

    def test_a_stack_that_crosses_tables_reaches_the_file(self, tmp_path):
        """The gap this closes. By seat, the stack takes one paper from
        each table in turn, and no ordering of `[[group]]` tables can
        say that -- so each seat carries its own place in it."""
        s = section_with(table("t1", (0, 0), 2), table("t2", (0, 300), 2),
                         groups=[group("g1", "t1", 2, order=1),
                                 group("g2", "t2", 2, order=2)])
        s["print_by"] = "seat"
        order_them(s, {"t1-0": 1, "t2-0": 2, "t1-1": 3, "t2-1": 4})
        r, _ = self.room_of(s)
        path = tmp_path / "s.toml"
        path.write_text(seating_mod.to_toml(r, self.names), encoding="utf-8")

        chart = seating_mod.load(str(path), versions=r["versions"])
        assert [seat.name for seat in chart] == [
            "Student idt10", "Student idt20",
            "Student idt11", "Student idt21"]

    def test_the_tables_are_still_tables_in_a_crossing_stack(self, tmp_path):
        """Same file as above, read the other way: the stack interleaves
        the tables and the `[[group]]` blocks do not, so each seat still
        knows which table it is at and who is beside it."""
        s = section_with(table("t1", (0, 0), 2), table("t2", (0, 300), 2),
                         groups=[group("g1", "t1", 2, order=1),
                                 group("g2", "t2", 2, order=2)])
        s["print_by"] = "seat"
        order_them(s, {"t1-0": 1, "t2-0": 2, "t1-1": 3, "t2-1": 4})
        r, _ = self.room_of(s)
        path = tmp_path / "s.toml"
        path.write_text(seating_mod.to_toml(r, self.names), encoding="utf-8")

        chart = seating_mod.load(str(path), versions=r["versions"])
        beside = {frozenset((a.name, b.name)) for a, b in chart.neighbours()}
        assert beside == {
            frozenset(("Student idt10", "Student idt11")),
            frozenset(("Student idt20", "Student idt21")),
        }

    def test_reordering_within_a_group_leaves_the_table_alone(self, tmp_path):
        """A by-group stack can also need numbers -- the instructor can
        reorder a table's own run -- and the table's list must not be
        the thing that carries it."""
        s = section_with(table("t1", (0, 0), 4), groups=[group("g1", "t1", 4)])
        spot_them(s, {"t1-0": 4, "t1-1": 3, "t1-2": 2, "t1-3": 1})
        r, _ = self.room_of(s)
        text = seating_mod.to_toml(r, self.names)
        assert "at = 1" in text
        # Listed as they sit, which here is the order the ids were made.
        assert text.index("Student idt10") < text.index("Student idt13")
        path = tmp_path / "s.toml"
        path.write_text(text, encoding="utf-8")
        chart = seating_mod.load(str(path), versions=r["versions"])
        assert [seat.name for seat in chart][0] == "Student idt13"

    def test_an_empty_chair_carries_no_number(self, tmp_path):
        """`""` has nowhere to put one, and its place in the stack is
        nobody's paper. The numbers on the rest must still sort."""
        s = section_with(table("t1", (0, 0), 3), groups=[group("g1", "t1", 3)])
        s["shapes"][0]["seats"][0]["student"] = ""
        s["print_by"] = "seat"
        order_them(s, {"t1-2": 1, "t1-1": 2, "t1-0": 3})
        r, _ = self.room_of(s)
        text = seating_mod.to_toml(r, self.names)
        assert '""' in text and '"", at' not in text
        path = tmp_path / "s.toml"
        path.write_text(text, encoding="utf-8")
        chart = seating_mod.load(str(path), versions=r["versions"])
        assert [seat.name for seat in chart] == \
            ["Student idt12", "Student idt11"]


class TestTheShuffleStepsRoundAPin:
    """A pin is an accommodation -- a student who has to sit where they
    are -- so the one thing a shuffle must never do is move one."""

    def room(self, seats=6, pinned=()):
        s = section_with(table("t1", (0, 0), seats),
                         groups=[group("g1", "t1", seats)])
        for shape in s["shapes"]:
            for seat in shape["seats"]:
                if seat["id"] in pinned:
                    seat["pinned"] = True
        return s

    def who(self, section):
        return {seat["id"]: seat.get("student") or ""
                for seat in room_mod.seats_of(section)}

    def test_it_moves_people(self):
        s = self.room()
        before = self.who(s)
        moved = room_mod.shuffle_seats(s, random.Random(4))
        assert moved > 0
        assert self.who(s) != before

    def test_everybody_is_still_there(self):
        """A shuffle is a permutation. Losing or duplicating a student
        is the one way it can be worse than doing nothing."""
        s = self.room()
        before = sorted(self.who(s).values())
        room_mod.shuffle_seats(s, random.Random(5))
        assert sorted(self.who(s).values()) == before

    def test_a_pinned_seat_keeps_its_person(self):
        s = self.room(pinned={"t1-2"})
        before = self.who(s)["t1-2"]
        for seed in range(25):
            here = self.room(pinned={"t1-2"})
            room_mod.shuffle_seats(here, random.Random(seed))
            assert self.who(here)["t1-2"] == before, f"moved on seed {seed}"

    def test_pinning_everybody_leaves_the_room_alone(self):
        s = self.room(pinned={f"t1-{i}" for i in range(6)})
        before = self.who(s)
        assert room_mod.shuffle_seats(s, random.Random(6)) == 0
        assert self.who(s) == before

    def test_one_free_chair_cannot_shuffle(self):
        """Five pinned and one loose: there is nowhere for the sixth to
        go, and the button has to say so rather than report a move.

        The count is also asserted, because the answer has to be right
        however it is arrived at -- but the count alone does not test
        the guard. Without it the re-roll loop simply spins twenty
        times over a list of one and returns zero anyway, which is the
        same answer reached by brute force. What the guard promises is
        that it does not try."""
        class Counting(random.Random):
            tries = 0

            def shuffle(self, seq):
                Counting.tries += 1
                super().shuffle(seq)

        s = self.room(pinned={f"t1-{i}" for i in range(5)})
        assert room_mod.shuffle_seats(s, Counting(7)) == 0
        assert Counting.tries == 0, "it tried to shuffle one chair"

    def test_a_room_of_empty_chairs_is_not_shuffled_either(self):
        """The same guard, reached the other way: six free chairs with
        nobody in any of them is six identical values, and no ordering
        of them is a different room."""
        class Counting(random.Random):
            tries = 0

            def shuffle(self, seq):
                Counting.tries += 1
                super().shuffle(seq)

        s = self.room()
        for seat in room_mod.live_seats(s):
            seat["student"] = ""
        assert room_mod.shuffle_seats(s, Counting(7)) == 0
        assert Counting.tries == 0

    def test_an_empty_chair_shuffles_like_anyone(self):
        """Otherwise every gap collects at the end of the room."""
        s = self.room()
        for shape in s["shapes"]:
            shape["seats"][0]["student"] = ""
        landed = set()
        for seed in range(30):
            here = self.room()
            for shape in here["shapes"]:
                shape["seats"][0]["student"] = ""
            room_mod.shuffle_seats(here, random.Random(seed))
            for sid, who in self.who(here).items():
                if not who:
                    landed.add(sid)
        assert len(landed) > 1, "the empty chair never moved"

    def test_it_never_hands_everybody_back_their_own_chair(self):
        """A permutation that changes nothing is a correct answer and a
        broken button. With two free chairs it is half of all presses,
        so it is re-rolled rather than left to luck."""
        for seed in range(40):
            s = self.room(pinned={f"t1-{i}" for i in range(4)})
            before = self.who(s)
            assert room_mod.shuffle_seats(s, random.Random(seed)) == 2
            assert self.who(s) != before, f"nothing moved on seed {seed}"

    def test_the_letters_stay_on_the_chairs(self):
        """A version belongs to the chair, because the coloring is of
        the room. Letters travelling with people would let a shuffle
        seat the same paper next to itself."""
        s = self.room()
        chosen, _ = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "ABCD",
            rng=random.Random(8))
        room_mod.apply_versions(s, chosen)
        before = {seat["id"]: seat["version"]
                  for seat in room_mod.seats_of(s)}
        room_mod.shuffle_seats(s, random.Random(9))
        assert {seat["id"]: seat["version"]
                for seat in room_mod.seats_of(s)} == before

    def test_the_unseated_are_left_standing(self):
        """The rail is somewhere a person was put on purpose. A shuffle
        that emptied it into the room would be undoing a decision."""
        s = self.room()
        for shape in s["shapes"]:
            shape["seats"][5]["student"] = ""
        seated = {w for w in self.who(s).values() if w}
        room_mod.shuffle_seats(s, random.Random(10))
        assert {w for w in self.who(s).values() if w} == seated

    def checkable(self):
        """A room `check` will look at. The `table` helper above uses a
        shape kind that only the seat maths cares about; validation
        wants one from the palette."""
        s = room_mod.new_section("820")
        s["shapes"] = [room_mod.make_shape("table-1x3", (200, 200), "t1")]
        ids = [seat["id"] for seat in s["shapes"][0]["seats"]]
        s["groups"] = [{"id": "g1", "label": "1", "seats": ids,
                        "order": 1}]
        r = room_mod.empty("AB")
        r["sections"] = [s]
        return r, s

    def test_a_pin_is_yes_or_no(self):
        r, s = self.checkable()
        s["shapes"][0]["seats"][0]["pinned"] = "yes please"
        with pytest.raises(room_mod.RoomError, match="not yes or no"):
            room_mod.check(r)

    def test_a_pin_may_be_set(self):
        r, s = self.checkable()
        s["shapes"][0]["seats"][0]["pinned"] = True
        room_mod.check(r)          # no complaint

    def test_an_unpinned_room_says_nothing_about_pins(self):
        """Absent is the normal state, like every other optional field
        on a seat."""
        r, s = self.checkable()
        room_mod.check(r)
        assert all("pinned" not in seat
                   for seat in room_mod.live_seats(s))


class TestGluingGroupsTogether:
    """Merging is a fact about the group, not about the geometry: the
    desks do not move, and splitting does not have to remember where
    they were."""

    def room(self):
        s = section_with(table("t1", (0, 0), 2), table("t2", (0, 300), 2),
                         table("t3", (0, 600), 2),
                         groups=[group("g1", "t1", 2, order=1,
                                       label="Table 1"),
                                 group("g2", "t2", 2, order=2,
                                       label="Table 2"),
                                 group("g3", "t3", 2, order=3,
                                       label="Table 3")])
        s["groups"][0]["hue"] = 120
        return s

    def ids(self, s):
        return [g["id"] for g in s["groups"]]

    def test_two_become_one(self):
        s = self.room()
        kept = room_mod.merge_groups(s, ["g1", "g2"])
        assert kept["id"] == "g1"
        assert self.ids(s) == ["g1", "g3"]
        assert kept["seats"] == ["t1-0", "t1-1", "t2-0", "t2-1"]

    def test_nothing_moves(self):
        s = self.room()
        before = [sh["at"][:] for sh in s["shapes"]]
        room_mod.merge_groups(s, ["g1", "g2"])
        assert [sh["at"] for sh in s["shapes"]] == before

    def test_the_survivor_is_the_one_that_printed_first(self):
        """So the merged group lands where the earliest of its parts
        was and the rest of the stack shifts as little as it can.

        The orders here run backwards against the order the groups
        are listed in, which is the only arrangement that can tell
        the two apart: picking by list position gives the same answer
        as picking by print order in every tidy room."""
        s = self.room()
        for g, order in zip(s["groups"], [3, 2, 1]):
            g["order"] = order
        kept = room_mod.merge_groups(s, ["g1", "g2"])
        assert kept["id"] == "g2", "g2 prints before g1"
        assert kept["label"] == "Table 2"

    def test_it_keeps_one_label_and_one_colour(self):
        s = self.room()
        kept = room_mod.merge_groups(s, ["g1", "g2"])
        assert kept["label"] == "Table 1"
        assert kept["hue"] == 120

    def test_the_order_closes_up(self):
        s = self.room()
        room_mod.merge_groups(s, ["g1", "g2"])
        assert [g["order"] for g in s["groups"]] == [1, 2]

    def test_one_group_is_not_a_merge(self):
        s = self.room()
        assert room_mod.merge_groups(s, ["g1"]) is None
        assert len(s["groups"]) == 3

    def test_every_seat_survives(self):
        s = self.room()
        before = sorted(x["id"] for x in room_mod.live_seats(s))
        room_mod.merge_groups(s, ["g1", "g2", "g3"])
        after = sorted(sid for g in s["groups"] for sid in g["seats"])
        assert after == before

    # ----------------------------------------------- and apart again --
    def test_splitting_gives_one_group_per_desk(self):
        s = self.room()
        room_mod.merge_groups(s, ["g1", "g2"])
        out = room_mod.split_group(s, "g1")
        assert len(out) == 2
        assert [sorted(g["seats"]) for g in out] == \
            [["t1-0", "t1-1"], ["t2-0", "t2-1"]]

    def test_splitting_keeps_the_colour_so_the_eye_can_follow(self):
        s = self.room()
        room_mod.merge_groups(s, ["g1", "g2"])
        out = room_mod.split_group(s, "g1")
        assert all(g.get("hue") == 120 for g in out)

    def test_a_round_trip_puts_the_seats_back(self):
        s = self.room()
        before = {g["id"]: sorted(g["seats"]) for g in s["groups"]}
        room_mod.merge_groups(s, ["g1", "g2"])
        room_mod.split_group(s, "g1")
        now = sorted(sorted(g["seats"]) for g in s["groups"])
        assert now == sorted(before.values())

    def test_splitting_something_already_apart_does_nothing(self):
        s = self.room()
        out = room_mod.split_group(s, "g2")
        assert len(out) == 1 and len(s["groups"]) == 3

    def test_the_new_groups_get_their_own_ids(self):
        s = self.room()
        room_mod.merge_groups(s, ["g1", "g2", "g3"])
        out = room_mod.split_group(s, "g1")
        ids = [g["id"] for g in out]
        assert len(set(ids)) == 3, ids
        assert all(g["id"] for g in s["groups"])

    def test_a_merged_room_still_checks(self):
        s = room_mod.new_section("820")
        s["shapes"] = [room_mod.make_shape("table-1x2", (200, 200), "a"),
                       room_mod.make_shape("table-1x2", (600, 200), "b")]
        s["groups"] = [
            {"id": "ga", "label": "Table 1", "order": 1,
             "seats": [x["id"] for x in s["shapes"][0]["seats"]]},
            {"id": "gb", "label": "Table 2", "order": 2,
             "seats": [x["id"] for x in s["shapes"][1]["seats"]]}]
        r = room_mod.empty("AB")
        r["sections"] = [s]
        room_mod.merge_groups(s, ["ga", "gb"])
        room_mod.check(r)          # no complaint
        room_mod.split_group(s, "ga")
        room_mod.check(r)


class TestFillingAndEmptyingTheRoom:
    """"Seat everyone" and "Clear everyone". Both keep the shuffle's
    exemption, because a pin is the one arrangement in the room that
    is about a person rather than a layout."""

    def room(self, seats=4, pinned=(), empty=()):
        s = section_with(table("t1", (0, 0), seats),
                         groups=[group("g1", "t1", seats)])
        for seat in room_mod.live_seats(s):
            if seat["id"] in pinned:
                seat["pinned"] = True
            if seat["id"] in empty:
                seat["student"] = ""
        return s

    def who(self, section):
        return {s["id"]: s.get("student") or ""
                for s in room_mod.live_seats(section)}

    # ------------------------------------------------ seating them --
    def test_they_fill_the_empty_chairs(self):
        s = self.room(empty={"t1-1", "t1-3"})
        assert room_mod.seat_students(s, ["ann", "bo"]) == 2
        assert self.who(s)["t1-1"] == "ann"
        assert self.who(s)["t1-3"] == "bo"

    def test_a_sitting_student_is_not_displaced(self):
        s = self.room(empty={"t1-2"})
        before = self.who(s)
        room_mod.seat_students(s, ["ann"])
        for sid, who in self.who(s).items():
            if sid != "t1-2":
                assert who == before[sid]

    def test_an_empty_pinned_chair_stays_empty(self):
        """A pin on an empty chair is "keep this one free", which is a
        real thing to want beside a door or a projector."""
        s = self.room(empty={"t1-0", "t1-2"}, pinned={"t1-0"})
        assert room_mod.seat_students(s, ["ann", "bo"]) == 1
        assert self.who(s)["t1-0"] == ""
        assert self.who(s)["t1-2"] == "ann"

    def test_they_sit_down_in_stack_order(self):
        """Not in the order the room was built, which would scatter an
        alphabetical list across the tables."""
        s = self.room(empty={"t1-0", "t1-1", "t1-2", "t1-3"})
        spot_them(s, {"t1-0": 4, "t1-1": 3, "t1-2": 2, "t1-3": 1})
        room_mod.seat_students(s, ["first", "second"])
        assert self.who(s)["t1-3"] == "first"
        assert self.who(s)["t1-2"] == "second"

    def test_nobody_is_evicted_when_the_room_runs_out(self):
        s = self.room(empty={"t1-1"})
        assert room_mod.seat_students(s, ["ann", "bo", "cal"]) == 1
        assert sorted(self.who(s).values()).count("") == 0

    def test_seating_nobody_is_not_an_error(self):
        s = self.room()
        assert room_mod.seat_students(s, []) == 0

    # ----------------------------------------------- clearing them --
    def test_clearing_stands_everybody_up(self):
        s = self.room()
        assert room_mod.clear_seats(s) == 4
        assert set(self.who(s).values()) == {""}

    def test_clearing_leaves_a_pinned_seat_sitting(self):
        s = self.room(pinned={"t1-2"})
        was = self.who(s)["t1-2"]
        assert room_mod.clear_seats(s) == 3
        assert self.who(s)["t1-2"] == was

    def test_clearing_an_empty_room_counts_nobody(self):
        s = self.room(empty={"t1-0", "t1-1", "t1-2", "t1-3"})
        assert room_mod.clear_seats(s) == 0

    def test_clearing_keeps_the_desks_and_the_groups(self):
        """It stands people up; it does not undraw the room."""
        s = self.room()
        room_mod.clear_seats(s)
        assert len(s["shapes"][0]["seats"]) == 4
        assert s["groups"][0]["seats"] == ["t1-0", "t1-1", "t1-2", "t1-3"]

    def test_clearing_keeps_the_letters_on_the_chairs(self):
        """A version belongs to the chair. Emptying the room and
        filling it again must not need a re-coloring."""
        s = self.room()
        chosen, _ = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "ABCD",
            rng=random.Random(3))
        room_mod.apply_versions(s, chosen)
        before = {x["id"]: x["version"] for x in room_mod.live_seats(s)}
        room_mod.clear_seats(s)
        assert {x["id"]: x["version"]
                for x in room_mod.live_seats(s)} == before


class TestTheCanvasBackground:
    """Per section, because two classes can meet in two rooms and the
    projector in one of them is the whole reason to change it.

    Called background and not paper: in this tool `paper` is the sheet
    that comes out of the printer, and a field by that name sitting
    beside `seat.version` would be read as the same question."""

    def room(self, tint=None):
        s = room_mod.new_section("820")
        s["shapes"] = [room_mod.make_shape("table-1x2", (200, 200), "t1")]
        if tint is not None:
            s["canvas"]["background"] = tint
        r = room_mod.empty("AB")
        r["sections"] = [s]
        return r

    def test_absent_is_the_default(self):
        """A room nobody has re-tinted stores nothing, like every other
        optional field here."""
        r = self.room()
        room_mod.check(r)
        assert "background" not in r["sections"][0]["canvas"]

    @pytest.mark.parametrize("tint", room_mod.BACKGROUNDS)
    def test_every_named_one_is_allowed(self, tint):
        room_mod.check(self.room(tint))

    def test_anything_else_is_refused(self):
        """Fail loudly. A free color would quietly break the group
        colors, which are designed against this surface."""
        with pytest.raises(room_mod.RoomError, match="background"):
            room_mod.check(self.room("#ff00ff"))

    def test_they_are_all_light(self):
        """The four differ in lightness and warmth only. A dark one
        would need a second set of card colors, which is a larger
        decision than "the projector in this room runs blue" -- so if
        one is ever added, this test should fail and be thought about
        rather than deleted."""
        assert set(room_mod.BACKGROUNDS) == {"grey", "white", "warm", "cool"}

    def test_it_survives_a_round_trip(self, tmp_path):
        r = self.room("warm")
        path = tmp_path / "room.json"
        room_mod.save(str(path), r)
        assert room_mod.load(str(path))["sections"][0]["canvas"]["background"] \
            == "warm"


class TestTheSweepMatchesTheCanvas:
    """`room.seat_sweep` is a second copy of `slotsOf` in `seating.js`,
    because the canvas needs the answer on every redraw and the chart
    writer needs it with no canvas at all. These are what hold the two
    together: every shape in the palette, by the letters the canvas is
    known to draw on it.

    If one copy is changed, these fail, and that is the point.
    """

    def letters(self, kind):
        """The palette's own geometry, lettered."""
        shape = room_mod.make_shape(kind, (0, 0), "s")
        where = room_mod.seat_points({"shapes": [shape]})
        ids = [seat["id"] for seat in shape["seats"]]
        got = room_mod.seat_letters(ids, where)
        return "".join(got[sid] for sid in ids)

    def test_a_row_runs_left_to_right(self):
        assert self.letters("table-1x3") == "ABC"
        assert self.letters("table-1x2") == "AB"
        assert self.letters("trapezoid") == "ABC"

    def test_a_single_desk_is_its_own_a(self):
        assert self.letters("desk") == "A"

    def test_a_two_by_two_goes_round_and_not_across(self):
        """The regression. Anchored at a fixed -135 degrees the top left
        corner of a 2x2 sits about ten degrees *before* the start of the
        sweep, so it wrapped the whole way round and lettered last: the
        table came out D A C B. The seats are listed top left, top
        right, bottom left, bottom right, so clockwise is A B D C."""
        assert self.letters("table-2x2") == "ABDC"

    def test_a_round_table_goes_round(self):
        """Listed top, right, bottom, left, which is already clockwise."""
        assert self.letters("round") == "ABCD"

    def test_a_hexagon_starts_at_its_top_left_seat(self):
        """Six seats listed from the top going clockwise, so the sweep
        has to start one place in: the top left seat is the upper-left
        one, not the top one."""
        assert self.letters("hex") == "BCDEFA"

    def test_an_oval_letters_both_rows(self):
        """Two rows of three. Listed left to right along the top and
        then along the bottom; clockwise is along the top and *back*
        along the bottom."""
        assert self.letters("oval") == "ABCFED"

    def test_a_row_nudged_out_of_line_still_reads_along_it(self):
        """The case the straight-line branch is actually for. Three
        seats dead level sweep to the right answer by accident -- on a
        horizontal line every seat left of centre has the bearing pi
        and every seat right of it has 0, so a stable sort keeps them
        in order anyway. Nudge one seat 20 units down, which is well
        inside a card and still plainly a row, and the sweep puts it
        last: A C B."""
        shape = {"id": "s", "kind": "desk", "at": [0, 0],
                 "seats": [{"id": "l", "at": [0, 0], "student": ""},
                           {"id": "m", "at": [120, 20], "student": ""},
                           {"id": "r", "at": [240, -20], "student": ""}]}
        where = room_mod.seat_points({"shapes": [shape]})
        got = room_mod.seat_letters(["l", "m", "r"], where)
        assert (got["l"], got["m"], got["r"]) == ("A", "B", "C")

    def test_a_column_nudged_out_of_line_still_reads_down_it(self):
        """The same, turned ninety degrees: a row of desks against a
        wall, none of them quite square to it.

        The nudge leans left and then right, not right and then left.
        Lean it the other way and the sweep happens to come out in
        order anyway, which is how a first draft of this test passed
        with the straight-line branch deleted."""
        shape = {"id": "s", "kind": "desk", "at": [0, 0],
                 "seats": [{"id": "hi", "at": [0, 0], "student": ""},
                           {"id": "mid", "at": [-30, 120], "student": ""},
                           {"id": "lo", "at": [30, 240], "student": ""}]}
        where = room_mod.seat_points({"shapes": [shape]})
        got = room_mod.seat_letters(["hi", "mid", "lo"], where)
        assert (got["hi"], got["mid"], got["lo"]) == ("A", "B", "C")

    def test_a_column_runs_top_to_bottom(self):
        """Not in the palette -- it is what a row of desks against a
        wall becomes. Sorting these by angle would be nonsense, so
        seats within one card of a vertical line go down it."""
        shape = {"id": "s", "kind": "desk", "at": [0, 0],
                 "seats": [{"id": "lo", "at": [0, 120], "student": ""},
                           {"id": "hi", "at": [0, -120], "student": ""},
                           {"id": "mid", "at": [0, 0], "student": ""}]}
        where = room_mod.seat_points({"shapes": [shape]})
        got = room_mod.seat_letters(["lo", "hi", "mid"], where)
        assert (got["hi"], got["mid"], got["lo"]) == ("A", "B", "C")

    def test_past_z_it_counts(self):
        """A group of twenty-seven is absurd and must not crash."""
        shape = {"id": "s", "kind": "desk", "at": [0, 0],
                 "seats": [{"id": f"s{i}", "at": [i * 120, 0],
                            "student": ""} for i in range(27)]}
        where = room_mod.seat_points({"shapes": [shape]})
        got = room_mod.seat_letters([f"s{i}" for i in range(27)], where)
        assert got["s25"] == "Z" and got["s26"] == "27"

    def test_a_group_of_nobody_is_not_an_error(self):
        assert room_mod.seat_letters([], {}) == {}
        assert room_mod.seat_sweep(["gone"], {}) == []


class TestAnUntouchedTablePrintsAsItSits:
    def test_the_stack_takes_the_chair_order_not_the_list_order(self):
        """What this fixed. A 2x2 is listed top left, top right, bottom
        left, bottom right; it *prints* clockwise, which is top left,
        top right, bottom right, bottom left. The canvas has always
        shown the second and the chart used to write the first."""
        shape = room_mod.make_shape("table-2x2", (0, 0), "t")
        s = room_mod.new_section("820")
        s["shapes"] = [shape]
        ids = [seat["id"] for seat in shape["seats"]]
        s["groups"] = [{"id": "g", "label": "1", "seats": list(ids),
                        "order": 1}]
        tl, tr, bl, br = ids
        assert room_mod.stack_order(s) == [tl, tr, br, bl]

    def test_a_spot_still_wins_over_the_chair(self):
        """The sweep is only the default. Once the instructor has said
        what order a table hands out in, that is the order."""
        shape = room_mod.make_shape("table-2x2", (0, 0), "t")
        s = room_mod.new_section("820")
        s["shapes"] = [shape]
        ids = [seat["id"] for seat in shape["seats"]]
        s["groups"] = [{"id": "g", "label": "1", "seats": list(ids),
                        "order": 1}]
        spot_them(s, {sid: 4 - i for i, sid in enumerate(ids)})
        assert room_mod.stack_order(s) == list(reversed(ids))


class TestTwoSectionsStayApart:
    """A chart is a flat list of tables with no sections in it, so the
    stack numbers have to be one sequence across the whole file. These
    were written after the real two-section room came out interleaved
    while every test here had one section."""

    def names(self, student_id):
        return f"Student {student_id}" if student_id else ""

    # Table by table, which is what a section nobody reordered does.
    PLAIN_820 = ["Student ida0", "Student ida1",
                 "Student idb0", "Student idb1"]
    PLAIN_830 = ["Student idy0", "Student idy1",
                 "Student idz0", "Student idz1"]
    # One from each table in turn, which is what reordering buys.
    CROSSED_830 = ["Student idy0", "Student idz0",
                   "Student idy1", "Student idz1"]

    def two(self, reorder=None):
        """820 then 830, two tables each. `reorder` names the section
        whose printing crosses its tables, or neither."""
        a = section_with(table("a", (0, 0), 2), table("b", (0, 200), 2),
                         groups=[group("ga", "a", 2, order=1),
                                 group("gb", "b", 2, order=2)], name="820")
        z = section_with(table("y", (0, 0), 2), table("z", (0, 200), 2),
                         groups=[group("gy", "y", 2, order=1),
                                 group("gz", "z", 2, order=2)], name="830")
        a["order"], z["order"] = 1, 2
        if reorder == "820":
            a["print_by"] = "seat"
            order_them(a, {"a-0": 1, "b-0": 2, "a-1": 3, "b-1": 4})
        if reorder == "830":
            z["print_by"] = "seat"
            order_them(z, {"y-0": 1, "z-0": 2, "y-1": 3, "z-1": 4})
        r = room_mod.empty("ABCD")
        r["sections"] = [a, z]
        for sec in (a, z):
            chosen, _ = room_mod.assign_versions(
                room_mod.seats_of(sec), room_mod.group_of(sec), "ABCD",
                rng=random.Random(7))
            room_mod.apply_versions(sec, chosen)
        return r

    def read(self, tmp_path, room):
        path = tmp_path / "s.toml"
        path.write_text(seating_mod.to_toml(room, self.names),
                        encoding="utf-8")
        return [s.name for s in
                seating_mod.load(str(path), versions=room["versions"])]

    def test_the_sections_do_not_interleave(self, tmp_path):
        """A counter that restarted per section would give 830's first
        seat the number 1 as well, and the two would come off the
        printer shuffled into each other."""
        order = self.read(tmp_path, self.two(reorder="820"))
        first = [n for n in order if "ida" in n or "idb" in n]
        second = [n for n in order if "idy" in n or "idz" in n]
        assert order == first + second, "a section split across the stack"

    def test_a_bare_section_is_not_dragged_behind_a_numbered_one(
            self, tmp_path):
        """The arrangement that can actually fail: 830 is reordered and
        820 is not. Number only the section that asked and 820's seats
        have none, which puts them after everyone who does -- so the
        class that prints first comes out second. Numbering is all or
        nothing across the file for this reason."""
        order = self.read(tmp_path, self.two(reorder="830"))
        assert order == self.PLAIN_820 + self.CROSSED_830

    def test_the_reordered_section_still_crosses_its_own_tables(
            self, tmp_path):
        """And the point of all of it: 820 reordered hands out a-0,
        b-0, a-1, b-1 -- one from each table in turn."""
        order = self.read(tmp_path, self.two(reorder="820"))
        assert order[:4] == ["Student ida0", "Student idb0",
                             "Student ida1", "Student idb1"]

    def test_two_plain_sections_are_still_written_bare(self, tmp_path):
        """Neither one reordered: no numbers anywhere, which is the file
        this tool has always written."""
        assert "at =" not in seating_mod.to_toml(self.two(), self.names)


class TestWhoIsSittingNextToMe:
    """A chart read straight from text, because the question is about the
    format and not about the room that produced it."""

    def chart(self, tmp_path, text):
        path = tmp_path / "s.toml"
        path.write_text(text, encoding="utf-8")
        return seating_mod.load(str(path))

    def test_the_stack_is_the_order_the_seats_come_back(self, tmp_path):
        c = self.chart(tmp_path, """
versions = ["A", "B"]

[[group]]
seats = [{name = "Wren", at = 1}, {name = "Ash", at = 3}]

[[group]]
seats = [{name = "Fen", at = 2}, {name = "Oak", at = 4}]
""")
        assert [s.name for s in c] == ["Wren", "Fen", "Ash", "Oak"]

    def test_a_diagonal_pair_is_not_a_collision(self, tmp_path):
        """The bug this format change fixes. Seated A B A B round a
        table, nobody can see their own paper twice. Print those four
        in the order 1 3 2 4 and the stack reads A A B B -- so a check
        that walked the stack reported two clashes that do not exist.
        It has to walk the table."""
        c = self.chart(tmp_path, """
versions = ["A", "B"]

[[group]]
seats = [{name = "Wren", version = "A", at = 1},
         {name = "Ash", version = "B", at = 3},
         {name = "Fen", version = "A", at = 2},
         {name = "Oak", version = "B", at = 4}]
""")
        assert [s.name for s in c] == ["Wren", "Fen", "Ash", "Oak"]
        assert [(a.name, b.name) for a, b in c.neighbours()] == [
            ("Wren", "Ash"), ("Ash", "Fen"), ("Fen", "Oak")]
        assert c.collisions() == []

    def test_a_real_clash_at_a_table_is_still_found(self, tmp_path):
        """The other half: moving the check onto the table must not
        make it stop reporting."""
        c = self.chart(tmp_path, """
versions = ["A", "B"]

[[group]]
seats = [{name = "Wren", version = "A", at = 1},
         {name = "Ash", version = "A", at = 3}]
""")
        assert [(a.name, b.name) for a, b in c.collisions()] == \
            [("Wren", "Ash")]

    def test_two_tables_are_never_neighbours(self, tmp_path):
        """Same letter, adjacent in the stack, different tables. They
        cannot see each other, and that was already the rule."""
        c = self.chart(tmp_path, """
versions = ["A", "B"]

[[group]]
seats = [{name = "Wren", version = "A", at = 1}]

[[group]]
seats = [{name = "Ash", version = "A", at = 2}]
""")
        assert c.collisions() == []

    def test_a_seat_with_no_number_prints_last(self, tmp_path):
        """The rule an unplaced group and an unspotted seat already
        follow: having no position puts you after everyone who has one,
        not before them."""
        c = self.chart(tmp_path, """
versions = ["A", "B"]

[[group]]
seats = [{name = "Wren", at = 2}, {name = "Ash"}, {name = "Fen", at = 1}]
""")
        assert [s.name for s in c] == ["Fen", "Wren", "Ash"]

    def test_a_chart_with_no_numbers_is_untouched(self, tmp_path):
        """Every hand-written chart. The sort is skipped entirely."""
        c = self.chart(tmp_path, """
versions = ["A", "B"]

[[group]]
seats = ["Wren", "Ash", "Fen"]
""")
        assert [s.name for s in c] == ["Wren", "Ash", "Fen"]

    @pytest.mark.parametrize("at", ["0", '"3"', "1.5", "-2"])
    def test_a_nonsense_position_is_refused(self, tmp_path, at):
        """Fail loudly. This is the one key that decides what order a
        class is handed its papers in, so a typo in it should stop the
        build rather than quietly send somebody to the back."""
        with pytest.raises(seating_mod.SeatingError, match="stack"):
            self.chart(tmp_path, f"""
versions = ["A", "B"]

[[group]]
seats = [{{name = "Wren", at = {at}}}]
""")


class TestTheFileItself:
    def test_it_round_trips(self, tmp_path):
        r = room_mod.empty("ABCD")
        r["sections"] = [section_with(table("t1", (0, 0), 4))]
        path = str(tmp_path / "room.json")
        room_mod.save(path, r)
        assert room_mod.load(path) == r

    def test_a_missing_room_is_an_empty_one(self, tmp_path):
        assert room_mod.load(str(tmp_path / "nope.json"))["sections"] == []

    def test_a_room_from_another_version_is_refused(self, tmp_path):
        """Rather than half-read: this file is the drawing, and guessing
        at a shape it does not have would lose a room."""
        path = tmp_path / "room.json"
        path.write_text(json.dumps({"schema": 99, "sections": []}),
                        encoding="utf-8")
        with pytest.raises(room_mod.RoomError, match="different version"):
            room_mod.load(str(path))

    def test_broken_json_says_so(self, tmp_path):
        path = tmp_path / "room.json"
        path.write_text("{not json", encoding="utf-8")
        with pytest.raises(room_mod.RoomError, match="not readable as JSON"):
            room_mod.load(str(path))


def row_of_desks(count, gap=100):
    """Single desks in a line, every one its own group of one. Closer
    together than NEIGHBOUR_DISTANCE, so each is a neighbour of the next
    and of nobody else."""
    s = room_mod.new_section("x")
    for i in range(count):
        s["shapes"].append({
            "id": f"d{i}", "kind": "desk", "at": [i * gap, 0],
            "seats": [{"id": f"d{i}-0", "at": [0, 0], "student": f"s{i}"}]})
    return s


def clash_count(section, chosen, near=room_mod.NEIGHBOUR_DISTANCE):
    """Score the answer against the real room, not against whatever graph
    the colorer used.

    This is the whole reason three mutations survived the first run:
    `assign_versions` returns clashes measured against its own adjacency,
    so removing an edge rule makes it report a clean room. A test that
    believed that report was checking nothing.
    """
    seats = room_mod.seats_of(section)
    edges = room_mod.neighbours(seats, room_mod.group_of(section), near=near)
    return sum(1 for a, b in edges if chosen[a] == chosen[b])


class TestTheDistanceRuleDoesSomething:
    """A room of loose desks has no groups at all, so proximity is the
    only thing standing between two neighbours and the same paper."""

    def test_a_row_of_desks_never_repeats_along_it(self):
        s = row_of_desks(10)
        seats, grouping = room_mod.seats_of(s), room_mod.group_of(s)
        for seed in range(20):
            chosen, _ = room_mod.assign_versions(
                seats, grouping, "ABC", rng=random.Random(seed))
            assert clash_count(s, chosen) == 0, f"seed {seed} sat two "
            "neighbours on the same paper"

    def test_without_consulting_neighbours_it_would_not(self):
        """Measured, not assumed: ignoring proximity clashes on 77 seeds
        in 80. The point is that the test above is capable of failing."""
        s = row_of_desks(10)
        seats, grouping = room_mod.seats_of(s), room_mod.group_of(s)
        blind = [clash_count(s, room_mod.assign_versions(
                     seats, grouping, "ABC", rng=random.Random(seed),
                     near=0.0)[0])
                 for seed in range(20)]
        assert sum(1 for n in blind if n) > 10


class TestTheBusiestSeatGoesFirst:
    """One desk ringed by four, and only two letters. The centre must take
    one and all four leaves the other -- which only works if the centre is
    colored before them."""

    def ringed(self):
        s = room_mod.new_section("x")
        for i, at in enumerate([(140, 0), (-140, 0), (0, 140), (0, -140)]):
            s["shapes"].append({
                "id": f"l{i}", "kind": "desk", "at": list(at),
                "seats": [{"id": f"l{i}-0", "at": [0, 0],
                           "student": f"s{i}"}]})
        # Listed last on purpose: in file order it is colored after every
        # leaf, by which time both letters are next door.
        s["shapes"].append({"id": "c", "kind": "desk", "at": [0, 0],
                            "seats": [{"id": "c-0", "at": [0, 0],
                                       "student": "sc"}]})
        return s

    def test_the_ring_works_out_with_only_two_letters(self):
        s = self.ringed()
        seats, grouping = room_mod.seats_of(s), room_mod.group_of(s)
        for seed in range(20):
            chosen, _ = room_mod.assign_versions(
                seats, grouping, "AB", rng=random.Random(seed))
            assert clash_count(s, chosen) == 0, f"seed {seed}"

    def test_the_leaves_agree_and_the_centre_differs(self):
        s = self.ringed()
        chosen, _ = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "AB",
            rng=random.Random(1))
        leaves = {chosen[f"l{i}-0"] for i in range(4)}
        assert len(leaves) == 1
        assert chosen["c-0"] not in leaves


class TestWhenLettersRunShort:
    """Ten tables of six with four letters is hopeless by a wide margin,
    so what is being checked is how well it gives up.

    The bounds are quality floors, not fixed points: an algorithm that
    does better should raise them, and one that quietly does worse should
    be caught. Both were measured against the alternatives.
    """

    def crowded(self, seed, tables=10, per_table=6):
        rng = random.Random(seed)
        s = room_mod.new_section("x")
        for t in range(tables):
            at = (rng.randrange(0, 800), rng.randrange(0, 500))
            seats = [{"id": f"t{t}-{i}", "at": [i * 45, 0],
                      "student": f"s{t}{i}"} for i in range(per_table)]
            s["shapes"].append({"id": f"t{t}", "kind": "table",
                                "at": list(at), "seats": seats})
            s["groups"].append({"id": f"g{t}", "label": f"t{t}",
                                "seats": [x["id"] for x in seats],
                                "order": t})
        return s

    def test_the_repair_pass_earns_its_place(self):
        """Without it this room scores 57. Measured across 300 random
        rooms, repair helped in 124 to 260 of them and never hurt."""
        s = self.crowded(0)
        _, clashes = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "ABCD",
            rng=random.Random(0))
        assert len(clashes) <= 53

    def test_the_repeat_goes_where_it_is_least_crowded(self):
        """With no legal letter left, taking the one rarest among a seat's
        own neighbours beats taking any. Without it this room scores 52."""
        s = self.crowded(29)
        _, clashes = room_mod.assign_versions(
            room_mod.seats_of(s), room_mod.group_of(s), "ABCD",
            rng=random.Random(29))
        assert len(clashes) <= 44


class TestTheShapePalette:
    """Desks a room can be drawn with. The anchors are a starting point --
    a real room has a table against a wall with nobody on the far side --
    so they are copied into the shape and dragged from there."""

    @pytest.mark.parametrize("kind", sorted(room_mod.SHAPES))
    def test_every_shape_can_be_made(self, kind):
        shape = room_mod.make_shape(kind, (100, 100), "s1")
        spec = room_mod.SHAPES[kind]
        assert len(shape["seats"]) == len(spec["seats"])
        assert shape["kind"] == kind and shape["at"] == [100, 100]

    @pytest.mark.parametrize("kind", sorted(room_mod.SHAPES))
    def test_the_seats_sit_inside_the_shape(self, kind):
        """An anchor outside its own desk is a typo in the table, and the
        card would float off the edge of it on the canvas."""
        spec = room_mod.SHAPES[kind]
        for sx, sy in spec["seats"]:
            assert abs(sx) <= spec["w"] / 2, f"{kind}: {sx} is off the side"
            assert abs(sy) <= spec["h"] / 2, f"{kind}: {sy} is off the end"

    @pytest.mark.parametrize("kind", sorted(room_mod.SHAPES))
    def test_the_seats_are_far_enough_apart_to_read(self, kind):
        """A card is 104 by 54. Two anchors closer than that overlap, and
        two overlapping names on a projector are worse than none."""
        import math
        seats = room_mod.SHAPES[kind]["seats"]
        for i, a in enumerate(seats):
            for b in seats[i + 1:]:
                assert abs(a[0] - b[0]) >= 104 or abs(a[1] - b[1]) >= 54, \
                    f"{kind}: {a} and {b} overlap"

    def test_seat_ids_are_unique_within_a_shape(self):
        ids = [s["id"] for s in
               room_mod.make_shape("table-2x2", (0, 0), "t9")["seats"]]
        assert len(set(ids)) == len(ids)

    def test_a_shape_that_does_not_exist_says_what_does(self):
        with pytest.raises(room_mod.RoomError, match="table-2x2"):
            room_mod.make_shape("banquette", (0, 0), "s1")


class TestWhatTheCanvasIsHanded:
    @pytest.fixture
    def course(self, tmp_path, monkeypatch, bank_dir):
        from checkit_printit import course as course_mod
        from checkit_printit import gui as gui_mod
        from checkit_printit import roster as roster_mod
        from checkit_printit.roster import Roster, Student
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("P", bank=str(bank_dir), adopt=None)
        people = Roster([
            Student(name="Ada Lovelace", skills=[], sid="806001"),
            Student(name="Prince", skills=[], sid="806002"),
            Student(name="Augusta Lovelace", skills=[], sid="806003",
                    preferred="Ada B Lovelace"),
        ])
        with open(course_mod.file_in("P", "roster"), "w",
                  encoding="utf-8") as f:
            f.write(roster_mod.to_toml(people, "test"))
        return gui_mod.Course("P"), gui_mod

    def test_a_course_with_no_room_drawn_still_loads(self, course):
        obj, gui_mod = course
        out = gui_mod.api_seating(obj, {})
        assert out["room"]["sections"] == []
        assert out["shapes"], "the palette is what lets you draw the first one"

    def test_names_arrive_split_for_a_two_line_card(self, course):
        obj, gui_mod = course
        names = gui_mod.api_seating(obj, {})["names"]
        assert names["806001"] == {"full": "Ada Lovelace",
                                   "top": "Ada", "bottom": "Lovelace"}

    def test_one_word_is_one_line(self, course):
        """Not "Prince" over an empty second line, which reads as a card
        that failed to load."""
        obj, gui_mod = course
        assert gui_mod.api_seating(obj, {})["names"]["806002"] == {
            "full": "Prince", "top": "Prince", "bottom": ""}

    def test_it_splits_once_not_on_every_space(self, course):
        """The bottom line is everything after the first name, so a
        middle name or a compound surname stays together."""
        obj, gui_mod = course
        assert gui_mod.api_seating(obj, {})["names"]["806003"]["bottom"] == \
            "B Lovelace"

    def test_it_is_the_printed_name(self, course):
        """The card shows what the paper shows, so a student holding one
        can be found in the room."""
        obj, gui_mod = course
        assert gui_mod.api_seating(obj, {})["names"]["806003"]["full"] == \
            "Ada B Lovelace"

    def test_the_room_comes_through(self, course, tmp_path):
        from checkit_printit import course as course_mod
        obj, gui_mod = course
        r = room_mod.empty("ABCD")
        section = room_mod.new_section("820", order=1)
        section["shapes"].append(
            room_mod.make_shape("table-2x2", (300, 200), "s1"))
        r["sections"].append(section)
        room_mod.save(course_mod.file_in("P", "room"), r)

        out = gui_mod.api_seating(obj, {})
        assert [s["name"] for s in out["room"]["sections"]] == ["820"]
        assert len(out["room"]["sections"][0]["shapes"][0]["seats"]) == 4

    def test_the_route_is_wired(self):
        from checkit_printit import gui as gui_mod
        assert gui_mod.ROUTES["/api/seating"] is gui_mod.api_seating


class TestTheRoomIsItsOwnFile:
    """The room is JSON the app writes; the chart is TOML the build reads.
    They live in the same folder and nothing said they must differ, so
    pointing one at the other broke no test -- and saving a room would
    then have written JSON over a seating chart."""

    def test_the_two_files_are_not_the_same_file(self):
        from checkit_printit import course as course_mod
        assert course_mod.FILENAMES["room"] != course_mod.FILENAMES["seating"]

    def test_and_their_paths_differ(self, tmp_path, monkeypatch):
        from checkit_printit import course as course_mod
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        assert (course_mod.file_in("P", "room")
                != course_mod.file_in("P", "seating"))

    def test_the_room_is_json_and_the_chart_is_toml(self):
        from checkit_printit import course as course_mod
        assert course_mod.FILENAMES["room"].endswith(".json")
        assert course_mod.FILENAMES["seating"].endswith(".toml")

    def test_saving_a_room_leaves_the_chart_alone(self, tmp_path,
                                                  monkeypatch, bank_dir):
        """The one that would actually hurt: a chart is the only record of
        where a class sits, and the build reads it."""
        from checkit_printit import course as course_mod
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("P", bank=str(bank_dir), adopt=None)
        chart = course_mod.file_in("P", "seating")
        with open(chart, "w", encoding="utf-8") as f:
            f.write('versions = ["A", "B"]\n\n[[group]]\nseats = ["X"]\n')
        before = open(chart, encoding="utf-8").read()

        r = room_mod.empty("ABCD")
        r["sections"].append(room_mod.new_section("820"))
        room_mod.save(course_mod.file_in("P", "room"), r)

        assert open(chart, encoding="utf-8").read() == before
