"""The classroom: where the desks are, who sits at them, and which paper.

A bird's-eye drawing of a room. Desks own their seat positions, groups own
their label, their print position and the version letters of the seats in
them, and a seat belonging to no group behaves as a group of one.

This file is **written by the app**, not by hand, which is why it is JSON
and not TOML: it is deeply nested -- sections hold shapes hold seats hold
offsets -- and TOML renders that badly. Not SQLite either, despite the
rule that tool-authored state goes there: that rule earns its keep for
something unbounded, queried, and written by two processes at once, and
this is one small document read whole and written whole, worth diffing
when a room changes.

**It is not what the build reads.** `seating.toml` still is, generated
from this, so the CLI and every existing job folder keep working. The one
difference that matters: a room holds each student's **id**, and resolves
it to a name only when writing the chart out. `seating.toml` joins to the
roster by name -- the only name-keyed join left in the tool -- so a
rename can break a chart today. It cannot break a room.
"""

import json
import math
import os
import random

VERSION = 1

#: Two seats this close, centre to centre, are treated as neighbours even
#: when they are at different desks -- which is what makes a room of loose
#: desks in rows work at all, since every such seat is a group of one.
#:
#: In canvas units, where a seat card is 90 wide. Generous rather than
#: tight: calling two seats neighbours when they are not costs a letter,
#: and missing a real pair puts the same paper side by side.
NEIGHBOUR_DISTANCE = 150.0


class RoomError(Exception):
    pass


# ----------------------------------------------------------- the model --

def empty(versions=("A", "B", "C", "D")):
    """A course with no rooms drawn yet."""
    return {"schema": VERSION, "versions": list(versions), "sections": []}


def new_section(name, order=None):
    return {
        "name": name,
        #: Which section's papers print first. The run covers every
        #: section, so this decides the order of the whole stack.
        "order": order,
        "canvas": {"width": 1200, "height": 800},
        #: Desks and tables. Each owns the seat positions on it.
        "shapes": [],
        #: A group owns its label, its print position, and -- through its
        #: seats -- which version letters are in play.
        "groups": [],
        #: Free-floating text: "front", "door", "whiteboard".
        "notes": [],
    }


def seats_of(section):
    """Every seat in the room, with its absolute position.

    Shapes carry positions relative to themselves, so a desk can be
    dragged without touching the seats on it.
    """
    out = []
    for shape in section.get("shapes") or []:
        ox, oy = shape.get("at") or (0, 0)
        for seat in shape.get("seats") or []:
            sx, sy = seat.get("at") or (0, 0)
            out.append({
                "id": seat.get("id"),
                "shape": shape.get("id"),
                "student": seat.get("student") or "",
                "version": seat.get("version") or "",
                "x": ox + sx,
                "y": oy + sy,
            })
    return out


def group_of(section):
    """seat id -> group id, with ungrouped seats left out.

    A seat in no group is a group of one, which every rule here treats the
    same way; keeping them out of this map means that rule lives in one
    place instead of being spelled out at each use.
    """
    out = {}
    for group in section.get("groups") or []:
        for seat_id in group.get("seats") or []:
            out[seat_id] = group.get("id")
    return out


# ------------------------------------------------- which paper, and why --

def neighbours(seats, grouping, near=NEIGHBOUR_DISTANCE):
    """Pairs of seats that must not hold the same version.

    Two sources, and they are different kinds of claim:

    * **Same group** -- everyone at a table can see everyone else. This is
      semantic, it comes from the instructor, and it is always right.
    * **Close together** -- a heuristic over the drawing, for seats at
      different desks and for a room of rows where every seat is a group
      of one. Wrong occasionally, and the cost of being wrong is one
      letter used where another would have done.
    """
    edges = set()
    for i, a in enumerate(seats):
        for b in seats[i + 1:]:
            together = (grouping.get(a["id"]) is not None
                        and grouping.get(a["id"]) == grouping.get(b["id"]))
            close = math.dist((a["x"], a["y"]), (b["x"], b["y"])) <= near
            if together or close:
                edges.add((a["id"], b["id"]))
    return edges


def _adjacency(seat_ids, edges):
    out = {sid: set() for sid in seat_ids}
    for a, b in edges:
        out[a].add(b)
        out[b].add(a)
    return out


def assign_versions(seats, grouping, versions, rng=None,
                    near=NEIGHBOUR_DISTANCE, passes=4):
    """Give every seat a version letter, avoiding neighbours matching.

    Graph colouring: seats are vertices, "must differ" is an edge, letters
    are colours. Greedy, most-constrained seat first, choosing at random
    among the letters that are legal -- random because the instructor asked
    for a shuffle, and preferring the least-used letter so the stack stays
    balanced.

    **When letters run short** -- five seats at a table and four versions
    -- there is no legal choice, so it takes the letter that appears least
    often among that seat's own neighbours. "Impossible" becomes "as far
    apart as it can be" rather than a refusal.

    Then a bounded repair: for each remaining clash, try recolouring one
    end and keep it if the total number of clashes drops. These graphs are
    about fifty vertices and nearly planar, so greedy is on or near optimal
    almost always and this finishes in microseconds. It cannot loop.

    Returns `(assignment, clashes)` -- the clashes being pairs that still
    match, which the canvas can mark and `seating.collisions` will report
    again at build time.
    """
    rng = rng or random.Random()
    versions = list(versions)
    if not versions:
        raise RoomError("no version letters to hand out.")
    if not seats:
        return {}, []

    ids = [s["id"] for s in seats]
    adjacent = _adjacency(ids, neighbours(seats, grouping, near))

    # Most constrained first: a seat with many neighbours has the fewest
    # letters left by the time it is reached, so it should choose early.
    order = sorted(ids, key=lambda sid: (-len(adjacent[sid]), rng.random()))

    used = {v: 0 for v in versions}
    chosen = {}
    for sid in order:
        taken = {chosen[n] for n in adjacent[sid] if n in chosen}
        legal = [v for v in versions if v not in taken]
        if legal:
            fewest = min(used[v] for v in legal)
            pick = rng.choice([v for v in legal if used[v] == fewest])
        else:
            # Every letter is already next door. Take whichever is least
            # present among the neighbours, so the repeat is as far away
            # as this seat can put it.
            near_counts = {v: 0 for v in versions}
            for n in adjacent[sid]:
                if n in chosen:
                    near_counts[chosen[n]] += 1
            fewest = min(near_counts.values())
            pick = rng.choice([v for v in versions
                               if near_counts[v] == fewest])
        chosen[sid] = pick
        used[pick] += 1

    def clashing():
        return [(a, b) for a in ids for b in adjacent[a]
                if a < b and chosen[a] == chosen[b]]

    for _ in range(passes):
        bad = clashing()
        if not bad:
            break
        before = len(bad)
        for a, _b in bad:
            here = chosen[a]
            for candidate in versions:
                if candidate == here:
                    continue
                chosen[a] = candidate
                if len(clashing()) < before:
                    before = len(clashing())
                    break
                chosen[a] = here
        if len(clashing()) == before and before == len(bad):
            break           # a pass that changed nothing will not change one

    return chosen, clashing()


def apply_versions(section, assignment):
    """Write the chosen letters onto the seats themselves.

    Stored rather than recomputed, because the choosing is a shuffle: run
    it again and it answers differently, and a chart that changed every
    time it was written would hand a student a different paper for no
    reason.
    """
    for shape in section.get("shapes") or []:
        for seat in shape.get("seats") or []:
            if seat.get("id") in assignment:
                seat["version"] = assignment[seat["id"]]
    return section


# --------------------------------------------------- out to the CLI's file --

def ordered_groups(section):
    """Groups in print order, with ungrouped seats as groups of one.

    An unplaced group keeps its existing position rather than being
    dropped: the instructor is warned that the order is incomplete and may
    go ahead, and "went out roughly right" beats "went out missing".
    """
    groups = list(section.get("groups") or [])
    placed = [g for g in groups if g.get("order") is not None]
    rest = [g for g in groups if g.get("order") is None]
    placed.sort(key=lambda g: g["order"])

    out = [dict(g) for g in placed + rest]
    grouped = {sid for g in groups for sid in (g.get("seats") or [])}
    for seat in seats_of(section):
        if seat["id"] not in grouped:
            # A seat of its own, in the order it is drawn.
            out.append({"id": f"solo:{seat['id']}", "label": "",
                        "seats": [seat["id"]], "order": None})
    return out


def unplaced(section):
    """Groups with no position in the print order, for the warning."""
    return [g.get("label") or g.get("id")
            for g in (section.get("groups") or [])
            if g.get("order") is None]


def load(path):
    if not os.path.isfile(path):
        return empty()
    with open(path, encoding="utf-8") as f:
        try:
            room = json.load(f)
        except ValueError as exc:
            raise RoomError(f"{path}: not readable as JSON ({exc})") from None
    if room.get("schema") != VERSION:
        raise RoomError(
            f"{path}: written by a different version of printit "
            f"(schema {room.get('schema')!r}, this one reads {VERSION}).")
    return room


def save(path, room):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(room, f, indent=2, sort_keys=False)
        f.write("\n")
