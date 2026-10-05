"""The room: desks, groups, and which paper each seat gets.

Stage one of the seating tab, and the part that decides whether the rest
is easy: the data model, the version assignment, and the `seating.toml`
a room produces. No canvas yet.

The assignment is graph colouring -- seats are vertices, "must differ" is
an edge, letters are colours -- so what is worth testing is the thing
colouring is for: that neighbours differ, that it degrades sensibly when
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

    def test_a_well_coloured_room_has_no_collisions(self, tmp_path):
        """`collisions()` is the build's own check, and it still runs over
        what the app chose."""
        s = section_with(table("t1", (0, 0), 4), groups=[group("g1", "t1", 4)])
        r, _ = self.room_of(s)
        path = tmp_path / "s.toml"
        path.write_text(seating_mod.to_toml(r, self.names), encoding="utf-8")
        assert seating_mod.load(str(path),
                                versions=r["versions"]).collisions() == []


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
    the colourer used.

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
    coloured before them."""

    def ringed(self):
        s = room_mod.new_section("x")
        for i, at in enumerate([(140, 0), (-140, 0), (0, 140), (0, -140)]):
            s["shapes"].append({
                "id": f"l{i}", "kind": "desk", "at": list(at),
                "seats": [{"id": f"l{i}-0", "at": [0, 0],
                           "student": f"s{i}"}]})
        # Listed last on purpose: in file order it is coloured after every
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
