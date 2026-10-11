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


#: The nine places a group's label may sit on a desk: eight around the
#: perimeter and the middle, as fractions of the shape's own box. The
#: same nine for every shape, because a hexagon's corners are not where
#: a label wants to be and a rule that holds everywhere is one a person
#: learns once.
#:
#: The canvas has its own copy of these fractions, since it is the one
#: that draws them. This copy exists so the names can be *checked* on
#: the way in -- see `check`.
ANCHORS = ("nw", "n", "ne", "w", "c", "e", "sw", "s", "se")


#: The desks and tables a room can be drawn with, and where people sit at
#: them. Sizes are canvas units, which are CSS pixels at 100% zoom; a name
#: card is 104 by 54, so a seat needs about that much room around its
#: anchor.
#:
#: The anchors are only a starting point -- a real room has a table pushed
#: against a wall with nobody on the far side -- so they are copied into
#: the shape when it is added and can be dragged from there. Changing this
#: table does not reach back into a room already drawn.
SHAPES = {
    "desk": {
        "label": "desk", "w": 124, "h": 78, "css": "rect",
        "seats": [(0, 0)],
    },
    "table-1x2": {
        "label": "table, 2 across", "w": 252, "h": 78, "css": "rect",
        "seats": [(-63, 0), (63, 0)],
    },
    "table-2x2": {
        "label": "table, 2 by 2", "w": 252, "h": 168, "css": "rect",
        "seats": [(-63, -44), (63, -44), (-63, 44), (63, 44)],
    },
    "table-1x3": {
        "label": "table, 3 across", "w": 376, "h": 78, "css": "rect",
        "seats": [(-126, 0), (0, 0), (126, 0)],
    },
    "round": {
        "label": "round table", "w": 236, "h": 236, "css": "circle",
        "seats": [(0, -74), (74, 0), (0, 74), (-74, 0)],
    },
    "oval": {
        "label": "oval table", "w": 420, "h": 230, "css": "circle",
        "seats": [(-130, -58), (0, -70), (130, -58),
                  (-130, 58), (0, 70), (130, 58)],
    },
    "hex": {
        "label": "hexagon", "w": 320, "h": 260, "css": "hex",
        "seats": [(0, -104), (116, -52), (116, 52),
                  (0, 104), (-116, 52), (-116, -52)],
    },
    "trapezoid": {
        "label": "trapezoid", "w": 360, "h": 120, "css": "trapezoid",
        "seats": [(-110, 24), (0, 24), (110, 24)],
    },
    # One seat, below the apex where the table is widest. A corner
    # desk, a lectern, the one chair wedged into a diagonal wall.
    "triangle": {
        "label": "triangle", "w": 170, "h": 140, "css": "triangle",
        "seats": [(0, 22)],
    },
}


def make_shape(kind, at, shape_id, seat_ids=None):
    """A shape of this kind, with its default seats, ready to drop in."""
    try:
        spec = SHAPES[kind]
    except KeyError:
        raise RoomError(
            f"{kind!r} is not a shape. There is "
            f"{', '.join(sorted(SHAPES))}.") from None
    ids = list(seat_ids or [])
    seats = []
    for i, (sx, sy) in enumerate(spec["seats"]):
        seats.append({
            "id": ids[i] if i < len(ids) else f"{shape_id}-{i}",
            "at": [sx, sy], "student": "", "version": "",
        })
    return {"id": shape_id, "kind": kind, "at": list(at), "seats": seats}


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
        # Generous, because the only thing this size does is bound
        # where furniture may go -- fitting and centring measure the
        # content. The canvas grows further if anything is dragged
        # past an edge; this is just somewhere roomy to start.
        "canvas": {"width": 2400, "height": 1600},
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


def live_seats(section):
    """The seat objects themselves, for code that changes one.

    `seats_of` looks like the obvious way to reach every seat and is
    not: it is a **view**, building a fresh dict per seat with absolute
    positions and a fixed set of keys. So it silently drops `pinned`,
    `spot` and `order`, and anything written to what it hands back is
    thrown away with it.

    Reading where a seat is asks that one. Reading a field it does not
    carry, or changing a seat at all, asks this one.
    """
    for shape in section.get("shapes") or []:
        for seat in shape.get("seats") or []:
            yield seat


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

    Graph coloring: seats are vertices, "must differ" is an edge, letters
    are colors. Greedy, most-constrained seat first, choosing at random
    among the letters that are legal -- random because the instructor asked
    for a shuffle, and preferring the least-used letter so the stack stays
    balanced.

    **When letters run short** -- five seats at a table and four versions
    -- there is no legal choice, so it takes the letter that appears least
    often among that seat's own neighbours. "Impossible" becomes "as far
    apart as it can be" rather than a refusal.

    Then a bounded repair: for each remaining clash, try recoloring one
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


def shuffle_seats(section, rng=None):
    """Deal the people who are sitting down into different chairs.

    Returns how many of them moved.

    **Only the unpinned chairs, and only the people already in them.**
    A pin is an accommodation, so a shuffle has to step round it; and
    the unseated rail is somewhere a person was put on purpose, so a
    shuffle that emptied it into the room would be undoing a decision
    rather than making one. An empty chair shuffles like anybody else,
    which is what keeps the gaps from all collecting at one table.

    The version letters are deliberately untouched. A letter belongs
    to the chair, not to the person -- the coloring is of the room --
    so the arrangement stays legal however the people are rearranged,
    and nobody needs re-coloring after a shuffle.
    """
    rng = rng or random.Random()
    # `live_seats`, not `seats_of`: the latter is a view that drops
    # `pinned` and discards every write, so a shuffle written against
    # it permutes six throwaway dicts and reports that it moved five
    # people. Which it did.
    free = [seat for seat in live_seats(section) if not seat.get("pinned")]
    before = [seat.get("student") or "" for seat in free]
    if len(set(before)) < 2:
        return 0                      # nothing here to tell apart

    # A permutation that changes nothing is a correct answer and a
    # broken button. With two free chairs it is every other press, so
    # it is re-rolled rather than left to luck. Bounded, because "keep
    # going until it differs" on input that cannot differ is a hang,
    # and the guard above is the only thing standing between them.
    after = before
    for _ in range(20):
        after = before[:]
        rng.shuffle(after)
        if after != before:
            break
    for seat, who in zip(free, after):
        seat["student"] = who
    return sum(1 for was, now in zip(before, after) if was != now)


def seat_students(section, students):
    """Put these people into the empty chairs. Returns how many sat.

    In stack order, which is the order the papers come off the printer
    and therefore the order somebody walking the room would meet them.
    A class seated this way comes out in the same order it is listed,
    which is the least surprising thing a "seat everyone" button can
    do -- the alternative, filling in whatever order the room was
    built, scatters an alphabetical list across the tables.

    Pinned chairs are left alone even when empty: a pin on an empty
    chair is "keep this one free", which is a real thing to want next
    to a door or a projector. Anybody who does not fit stays standing;
    this never evicts somebody to make room.
    """
    waiting = [who for who in students if who]
    if not waiting:
        return 0
    by_id = {seat["id"]: seat for seat in live_seats(section)}
    sat = 0
    for sid in stack_order(section):
        if not waiting:
            break
        seat = by_id.get(sid)
        if seat is None or seat.get("pinned") or seat.get("student"):
            continue
        seat["student"] = waiting.pop(0)
        sat += 1
    return sat


def clear_seats(section):
    """Stand everybody up. Returns how many were sitting.

    Every unpinned chair, which is the same exemption the shuffle
    makes and for the same reason: a pinned seat is an arrangement
    somebody made on purpose, and a button called "clear everyone"
    should not quietly undo the one decision in the room that was
    about a person rather than a layout.
    """
    gone = 0
    for seat in live_seats(section):
        if seat.get("pinned") or not seat.get("student"):
            continue
        seat["student"] = ""
        gone += 1
    return gone


# --------------------------------------------------- out to the CLI's file --

def ordered_groups(section):
    """Groups in print order, each group's seats in the order they sit.

    An unplaced group keeps its existing position rather than being
    dropped: the instructor is warned that the order is incomplete and may
    go ahead, and "went out roughly right" beats "went out missing".

    **A group's seat list says who sits beside whom, and nothing else.**
    It used to say the print order too, sorted by `spot`, and the two
    cannot be the same list: the collision check reads consecutive
    entries as neighbours, so a group reordered for printing would have
    it comparing two people sitting diagonally across a table and
    reporting a clash that nobody can see. The stack is `stack_order`.

    Which means the list comes out **swept** -- round the table from its
    top left seat -- and not in the order the room happens to hold the
    ids in. Those are different for eleven of the twelve tables in the
    real room: a 2x2 is built top left, top right, bottom left, bottom
    right, so the raw list calls two diagonal seats adjacent and misses
    both of the pairs along the sides. The sweep is the only record of
    the seating there is, and it costs nothing, because it is derived
    from where the seats are.
    """
    groups = list(section.get("groups") or [])
    placed = [g for g in groups if g.get("order") is not None]
    rest = [g for g in groups if g.get("order") is None]
    placed.sort(key=lambda g: g["order"])

    where = seat_points(section)
    out = []
    for group in placed + rest:
        copy = dict(group)
        copy["seats"] = seat_sweep(copy.get("seats") or [], where)
        out.append(copy)
    grouped = {sid for g in groups for sid in (g.get("seats") or [])}
    for seat in seats_of(section):
        if seat["id"] not in grouped:
            # A seat of its own, in the order it is drawn.
            out.append({"id": f"solo:{seat['id']}", "label": "",
                        "seats": [seat["id"]], "order": None})
    return out


#: What the canvas can be tinted. **Not** "paper", which in this tool
#: is the sheet that comes out of the printer -- `seat.version` picks
#: one of those, and a field called `paper` sitting next to it would be
#: read as the same question. The canvas is the background.
#:
#: A named set rather than a free color, because the group colors are
#: designed against this surface: all four are light, and differ in
#: lightness and warmth only. Somewhere to put a dark one would mean
#: a second set of card colors, which is a larger decision than
#: "the projector in this room runs blue".
BACKGROUNDS = ("grey", "white", "warm", "cool")

#: A name card in room units, which is what decides whether a group of
#: seats counts as a line or as a ring. Matches `CARD_W`/`CARD_H` in
#: `seating.js` and `.seatcard` in `seating.css`.
CARD_W, CARD_H = 104, 54

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def seat_points(section):
    """Every seat's position on the canvas, by id.

    A seat anchor is an offset from its desk's centre, and a seat that
    was dragged off its desk keeps the offset that takes it there, so
    the sum is the whole answer and no rotation is applied here: turning
    a desk rewrites its seats' offsets.
    """
    out = {}
    for shape in section.get("shapes") or []:
        at = shape.get("at") or [0, 0]
        for seat in shape.get("seats") or []:
            spot = seat.get("at") or [0, 0]
            out[seat["id"]] = (at[0] + spot[0], at[1] + spot[1])
    return out


def seat_sweep(ids, where):
    """These seats in the order somebody walking the table would reach
    them: clockwise from the top left.

    **This is a second copy of `slotsOf` in `seating.js`, deliberately.**
    The canvas needs the answer live, on every redraw while a seat is
    being dragged, and the writer needs it when there is no canvas at
    all -- so one of them cannot ask the other. They are pinned
    together by `TestTheSweepMatchesTheCanvas`, and a change to either
    belongs in both.

    A row, a column and a ring want different answers. Sorting a row of
    three by the angle round its own centre is nonsense, because the
    middle seat *is* the centre and has no angle; sorting a 2x2 left to
    right would letter it in reading order rather than clockwise. So
    seats within one card of a single line are ordered along it, and
    anything else is swept.

    The sweep starts at the top left **seat's** own bearing and not at a
    fixed -135 degrees, which is the obvious choice and is wrong: a
    2x2's corner sits at about -145, ten degrees before that line, so it
    wrapped the whole way round and came last. A 2x2 lettered D A C B.
    The line through the seat cannot be just past the seat.

    The seat letters the canvas draws are this order mapped onto
    `ALPHABET`; `seat_letters` does that and nothing else.
    """
    here = [i for i in ids if i in where]
    if len(here) < 2:
        return list(here)
    xs = [where[i][0] for i in here]
    ys = [where[i][1] for i in here]
    if max(ys) - min(ys) < CARD_H:
        return sorted(here, key=lambda i: where[i][0])
    if max(xs) - min(xs) < CARD_W:
        return sorted(here, key=lambda i: where[i][1])

    cx = (min(xs) + max(xs)) / 2
    cy = (min(ys) + max(ys)) / 2
    # The first minimum, as the canvas's `reduce` also takes.
    first = min(here, key=lambda i: where[i][0] + where[i][1])
    base = math.atan2(where[first][1] - cy, where[first][0] - cx)

    def swept(i):
        # Python's `%` is already non-negative for a positive modulus,
        # where the canvas has to say so twice.
        return (math.atan2(where[i][1] - cy, where[i][0] - cx)
                - base) % (2 * math.pi)
    return sorted(here, key=swept)


def seat_letters(ids, where):
    """Which chair at this table each seat is, by id.

    Never stored. A seat letter is derived from where the seat is, so
    "re-letter them when one moves" needs no bookkeeping, and it is not
    the print version: a letter says *which chair* and a version says
    *which paper*, and six chairs wanting three papers is reasonable.
    """
    return {sid: (ALPHABET[i] if i < len(ALPHABET) else str(i + 1))
            for i, sid in enumerate(seat_sweep(ids, where))}


def stack_order(section):
    """Every seat in this section, in the order its paper comes out.

    Two plans, and the second starts from the first.

    **By group** the stack is a pile per table: group after group in
    `group.order`, and inside each one by `seat.spot`. **By seat** it is
    one walk round the room, which crosses tables -- so it is seeded
    with the by-group answer and then moved by `seat.order`. Switching
    plans therefore starts from the order you already had rather than
    from nothing, and a room nobody has reordered carries no numbers at
    all in either plan: absent is the normal state for both fields.

    This is the twin of `roomRun` in the canvas, which is the same list
    with the seats still on screen.
    """
    spots, orders = {}, {}
    for shape in section.get("shapes") or []:
        for seat in shape.get("seats") or []:
            if seat.get("spot") is not None:
                spots[seat["id"]] = seat["spot"]
            if seat.get("order") is not None:
                orders[seat["id"]] = seat["order"]

    run = []
    for group in ordered_groups(section):
        # Already swept, so a table nobody has reordered prints round
        # itself from its top left seat -- the order the canvas has
        # always shown, and the order somebody handing the papers out
        # would walk anyway. `sorted` is stable, so `spot` moves only
        # the seats that carry one.
        #
        # One level up the rule stays the plainer one, because a group
        # has no geometry of its own: an unplaced group prints after
        # the placed ones, in the order it was listed.
        run.extend(sorted(group.get("seats") or [],
                          key=lambda sid: spots.get(sid, math.inf)))

    if (section.get("print_by") or "group") != "seat":
        return run
    return sorted(run, key=lambda sid: orders.get(sid, math.inf))


def empty_seats_for(room, ids):
    """Take these students out of their chairs, and leave the chairs.

    Emptied rather than removed, for the reason the chart gives: a seat
    carries its version letter, so taking the seat away would re-letter
    everyone else at that table because one person left.

    Returns how many chairs were emptied. Takes several ids for one
    student because a room may have been written under an older key.
    """
    wanted = {i for i in ids if i}
    count = 0
    for section in room.get("sections") or []:
        for shape in section.get("shapes") or []:
            for seat in shape.get("seats") or []:
                if seat.get("student") and seat["student"] in wanted:
                    seat["student"] = ""
                    count += 1
    return count


def unplaced(section):
    """Groups with no position in the print order, for the warning."""
    return [g.get("label") or g.get("id")
            for g in (section.get("groups") or [])
            if g.get("order") is None]


def _number(value):
    """A real, finite number -- and not a bool.

    `isinstance(True, int)` is true in Python and `json` turns `true` into
    a bool, so without the second test a seat could sit at `[true, true]`
    and be drawn, quite legally, at (1, 1).
    """
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and math.isfinite(value))


def _point(value, what):
    if (not isinstance(value, (list, tuple)) or len(value) != 2
            or not all(_number(n) for n in value)):
        raise RoomError(
            f"{what}: {value!r} is not a position. A position is two "
            f"numbers -- and a NaN among them is worse than a wrong one, "
            f"because every comparison against NaN is false, so the seat "
            f"would quietly be nobody's neighbour and clash on paper.")


def check(room, known=None):
    """Refuse a room that would print wrongly, before it is written.

    This is the boundary. A room arriving from the browser is the only one
    this code did not build itself, and `save` deliberately does **not**
    call this -- the CLI and the tests build small partial rooms on
    purpose -- so the guard sits where untrusted data actually arrives
    rather than at every place a room is written.

    Every rule here is one that fails **quietly** downstream, which is
    what earns it a refusal rather than a shrug:

    * a shape of a kind this build does not know is skipped by the canvas,
      so the desk and everyone at it vanish from the drawing while staying
      in the file;
    * a student in two seats is printed twice and appears twice in the
      chart;
    * a student in a seat the roster has never heard of has nothing
      printed for them at all.

    `known` is the ids a seat may name -- every key the roster answers to,
    not only the preferred one, so a room written before a student gained
    an SID still loads. None means there is no roster to check against.
    """
    if not isinstance(room, dict):
        raise RoomError("a room is a JSON object.")
    if room.get("schema") != VERSION:
        raise RoomError(
            f"that room says schema {room.get('schema')!r}; this printit "
            f"reads and writes {VERSION}.")

    versions = room.get("versions")
    if not isinstance(versions, list) or not versions:
        raise RoomError(
            "a room needs at least one version letter: they are what it "
            "has to hand out.")
    for v in versions:
        if not isinstance(v, str) or not v.strip():
            raise RoomError(f"{v!r} is not a version letter.")

    sections = room.get("sections")
    if not isinstance(sections, list):
        raise RoomError("a room's sections are a list.")

    everywhere, seated = {}, {}
    for section in sections:
        if not isinstance(section, dict):
            raise RoomError("a section is a JSON object.")
        where = section.get("name") or "an unnamed section"

        canvas = section.get("canvas") or {}
        for side in ("width", "height"):
            if not _number(canvas.get(side)) or canvas[side] <= 0:
                raise RoomError(
                    f"{where}: the canvas {side} is {canvas.get(side)!r}, "
                    f"which is not a size.")

        # Per section, because two classes can meet in two rooms, and
        # the projector in one of them is the reason to change this at
        # all. Absent is the default, which is `grey`.
        tint = canvas.get("background")
        if tint is not None and tint not in BACKGROUNDS:
            raise RoomError(
                f"{where}: the background is {tint!r}. It is one of "
                f"{', '.join(BACKGROUNDS)}.")

        # Whether this room's stack comes out group by group or seat
        # by seat. Per section, because one class may want handing a
        # pile to each table while the next is handed out one at a
        # time on a walk round -- that is a fact about how a lesson
        # runs, and the two lessons are different rooms.
        plan = section.get("print_by")
        if plan is not None and plan not in ("group", "seat"):
            raise RoomError(
                f"{where}: the printing is ordered {plan!r}. It goes by "
                f"'group' or by 'seat'.")

        shapes = section.get("shapes")
        if not isinstance(shapes, list):
            raise RoomError(f"{where}: the shapes are a list.")

        here = set()
        for shape in shapes:
            if not isinstance(shape, dict):
                raise RoomError(f"{where}: a shape is a JSON object.")
            kind = shape.get("kind")
            if kind not in SHAPES:
                raise RoomError(
                    f"{where}: {kind!r} is not a shape. There is "
                    f"{', '.join(sorted(SHAPES))}.")
            _point(shape.get("at"), f"{where}: the {kind}")

            # A desk dragged to its own size, rather than the kind's.
            # Stored on the shape so a widened 2x2 and a "3 across"
            # are the same thing in the file as on screen.
            for side in ("w", "h"):
                span = shape.get(side)
                if span is None:
                    continue
                if not _number(span) or span <= 0:
                    raise RoomError(
                        f"{where}: the {kind} is {span!r} {side}, which is "
                        f"not a size.")

            # Which way it is standing. The chairs do not need it --
            # rotating a desk rewrites their offsets, so a seat is
            # always simply where it says it is -- but the silhouette
            # does, and so does a second rotation.
            angle = shape.get("angle")
            if angle is not None:
                if not _number(angle) or not -360 < angle < 360:
                    raise RoomError(
                        f"{where}: the {kind} is turned {angle!r}, which is "
                        f"not a number of degrees.")

            for seat in shape.get("seats") or []:
                if not isinstance(seat, dict):
                    raise RoomError(f"{where}: a seat is a JSON object.")
                sid = seat.get("id")
                if not isinstance(sid, str) or not sid:
                    raise RoomError(f"{where}: a seat has no id.")
                if sid in everywhere:
                    raise RoomError(
                        f"two seats are both called {sid!r}. A group names "
                        f"its members by seat id, so a repeat puts the "
                        f"wrong person in a group.")
                everywhere[sid] = where
                here.add(sid)
                _point(seat.get("at"), f"{where}: seat {sid!r}")
                # Where this seat comes in the stack. `spot` is its
                # place inside its own group, `order` its place across
                # the whole room; which is in force depends on how the
                # instructor chose to order the printing, and a room
                # may carry both.
                #
                # Absent is the normal state for each. A group nobody
                # has reordered prints in seat order -- the clockwise
                # lettering the canvas works out for itself -- so a
                # room nobody has touched stores neither and reads the
                # same.
                for field in ("spot", "order"):
                    at = seat.get(field)
                    if at is None:
                        continue
                    if not _number(at) or int(at) != at or at < 1:
                        raise RoomError(
                            f"{where}: a seat is {at!r} in the print "
                            f"order, which is not a position.")

                # Pinned: whoever is in this chair stays in it. An
                # accommodation, usually -- a student who has to sit
                # where they are -- which is why a shuffle steps
                # round it and a drag refuses rather than asking.
                #
                # Not the same word as `seating.Seat.pinned`, which
                # is about a version letter being written down in the
                # chart rather than worked out. Different file,
                # different question.
                held = seat.get("pinned")
                if held is not None and not isinstance(held, bool):
                    raise RoomError(
                        f"{where}: a seat is pinned {held!r}, which is "
                        f"not yes or no.")

                who = seat.get("student") or ""
                if not who:
                    continue
                if not isinstance(who, str):
                    raise RoomError(f"{where}: {who!r} is not a student id.")
                if who in seated:
                    raise RoomError(
                        f"{who} is sitting in two seats, {seated[who]} and "
                        f"{sid}. They would be printed twice.")
                seated[who] = sid
                if known is not None and who not in known:
                    raise RoomError(
                        f"seat {sid} holds {who}, who is not on the roster. "
                        f"Nothing would print for them.")

        shape_ids = {s.get("id") for s in shapes}
        for group in section.get("groups") or []:
            named = group.get("label") or group.get("id")
            for sid in group.get("seats") or []:
                if sid not in here:
                    raise RoomError(
                        f"{where}: group {named!r} names seat {sid!r}, "
                        f"which is not in that room.")
            order = group.get("order")
            if order is not None and not isinstance(order, int):
                raise RoomError(
                    f"{where}: group {named!r} is {order!r} in the print "
                    f"order, which is not a position.")

            # A group's color: an angle, and optionally how vivid to
            # be at that angle. Two numbers, not a palette of six --
            # the three shades the canvas draws are derived from these
            # rather than stored, which is what keeps every group the
            # same design however the color was chosen.
            #
            # Lightness is deliberately NOT stored. It is what decides
            # whether a name on a card can be read, on a screen and on
            # a projector and on paper, and it is the one part of a
            # color an instructor should not be able to get wrong by
            # picking something pretty.
            hue = group.get("hue")
            if hue is not None:
                if not _number(hue) or not 0 <= hue < 360:
                    raise RoomError(
                        f"{where}: group {named!r} has hue {hue!r}, which "
                        f"is not an angle on the color wheel.")

            chroma = group.get("chroma")
            if chroma is not None:
                if not _number(chroma) or not 0 <= chroma <= 1.4:
                    raise RoomError(
                        f"{where}: group {named!r} has chroma {chroma!r}. "
                        f"It scales the standard color, so 0 is grey, 1 "
                        f"is the usual strength, and 1.4 is as far as it "
                        f"goes.")

            # Where its label sits: a desk, and one of the nine places
            # on that desk. Checked because a label pinned to a desk
            # that is not there would silently fall back to the middle
            # of the group's seats, and look like the anchor had simply
            # been forgotten.
            at = group.get("label_at")
            if at is not None:
                if not isinstance(at, dict):
                    raise RoomError(
                        f"{where}: group {named!r} has label_at {at!r}, "
                        f"which is not a place.")
                if at.get("shape") not in shape_ids:
                    raise RoomError(
                        f"{where}: group {named!r} hangs its label on "
                        f"{at.get('shape')!r}, which is not a desk in "
                        f"that room.")
                if at.get("anchor") not in ANCHORS:
                    raise RoomError(
                        f"{where}: group {named!r} hangs its label at "
                        f"{at.get('anchor')!r}. It is one of "
                        f"{', '.join(sorted(ANCHORS))}.")
    return room


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
