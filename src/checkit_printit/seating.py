"""Seat order, and which version each seat gets.

Two jobs, and they are the same job: students print in seating order so a stack
of paper matches the room, and adjacent seats must not share a version.

**The rule is immediate neighbours, not whole groups.** A table of four seated
A, B, A, B satisfies it with two versions; requiring everyone at a table to
differ would need four, for no gain. Two versions is the intent.

Where nobody shares a table there are no neighbours, so one version is enough
-- a single student making up a checkpoint should not have to invent a second
paper that nobody receives.

This is the interim for the eventual drag-and-drop GUI. The file format is
meant to be what that GUI reads and writes, so it becomes a front end rather
than a replacement.
"""

import dataclasses
import tomllib


class SeatingError(Exception):
    pass


@dataclasses.dataclass
class Seat:
    name: str
    group: int
    version: str
    #: The roster `sid`, when the chart records one.
    #:
    #: A seat used to be a name and nothing else, which made this the
    #: one join in the tool done on a name -- and `api_roster_save`
    #: writes only the roster, so renaming a student in the Roster tab
    #: silently unseated them. `room.json` keyed its seats by id all
    #: along and survived a rename; this file did not.
    #:
    #: Empty for a hand-written chart, and for every chart written
    #: before this key existed. `Chart.order` falls back to the name,
    #: so those keep working exactly as they did.
    sid: str = ""
    pinned: bool = False
    # Which chair at its own table, counting as the file lists them.
    # Kept because the seats are handed back in *stack* order, and once
    # a print order can cross tables those are two different lists --
    # so "who is sitting next to me" has to be remembered rather than
    # read off the position in the one that came back.
    at_table: int = 0


def alternate(count, versions):
    """Assign versions along a run of adjacent seats.

    Cycles, so no two neighbours match. With two versions this is A B A B.
    """
    return [versions[i % len(versions)] for i in range(count)]


def load(path, versions=("A", "B")):
    """Read a seating file.

    ```toml
    versions = ["A", "B"]

    [[group]]
    seats = ["Ada Lovelace", "Alan Turing", "Grace Hopper", "Katherine Johnson"]

    [[group]]
    seats = [{name = "Emmy Noether", version = "B"}, "Srinivasa Ramanujan"]
    ```

    A seat may pin its version. Everything else alternates around the pins,
    which is what lets a deliberate choice survive a re-run.

    **A `[[group]]` is a table, not a pile of paper.** Its list is who
    sits beside whom, which is the only thing here that knows it; the
    order the papers come out is each seat's `at`, and the two part
    company the moment an instructor hands out on a walk round the room
    instead of a stack per table:

    ```toml
    [[group]]
    seats = [{name = "Ada Lovelace", version = "A", at = 1},
             {name = "Alan Turing", version = "B", at = 3}]

    [[group]]
    seats = [{name = "Grace Hopper", version = "A", at = 2},
             {name = "Katherine Johnson", version = "B", at = 4}]
    ```

    Ada still sits with Alan; the stack still alternates tables. Where
    no seat carries an `at` -- every hand-written chart, and every
    written one nobody has reordered -- the stack is the order the file
    reads in, exactly as it was before the key existed. A seat without
    one, in a chart where others have them, prints last.
    """
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    declared = raw.get("versions")
    if declared is None:
        versions = tuple(versions)
    else:
        versions = tuple(declared)
        if not versions:
            raise SeatingError(
                f"{path}: versions is empty. Name at least one, or leave the "
                f"key out to take the default {list(('A', 'B'))}."
            )

    groups = raw.get("group")
    if not groups:
        raise SeatingError(f"{path} has no [[group]] tables.")

    # One version is refused only where it would actually put the same paper
    # in two adjacent hands. Checking the seats rather than the class size is
    # the point: what matters is whether anyone has a neighbour.
    if len(versions) < 2:
        crowded = next(
            (g for g, grp in enumerate(groups, 1)
             if len(grp.get("seats") or []) > 1),
            None,
        )
        if crowded is not None:
            seated = len(groups[crowded - 1].get("seats") or [])
            raise SeatingError(
                f"{path}: only one version ({versions[0]}), but table "
                f"{crowded} seats {seated} people, who would all get the same "
                f"paper. Name a second version."
            )

    found = []                     # (its place in the stack, the seat)
    for g, group in enumerate(groups, 1):
        entries = group.get("seats") or []
        assigned = alternate(len(entries), versions)
        for i, entry in enumerate(entries):
            if isinstance(entry, dict):
                name = (entry.get("name") or "").strip()
                pinned_version = entry.get("version")
                at = entry.get("at")
                sid = str(entry.get("sid") or "").strip()
            else:
                name, pinned_version, at = str(entry).strip(), None, None
                sid = ""
            if not name:
                continue
            if pinned_version is not None and pinned_version not in versions:
                raise SeatingError(
                    f"{path}: seat {name!r} is pinned to version "
                    f"{pinned_version!r}, which is not in {list(versions)}."
                )
            # Refused rather than ignored. A typo in the one key that
            # decides what order a class is handed its papers in should
            # stop the build, not quietly send the seat to the back.
            if at is not None and (not isinstance(at, int)
                                   or isinstance(at, bool) or at < 1):
                raise SeatingError(
                    f"{path}: seat {name!r} is at {at!r} in the stack, "
                    f"which is not a position. Count from 1."
                )
            found.append((at, Seat(
                name=name,
                group=g,
                version=pinned_version or assigned[i],
                sid=sid,
                pinned=pinned_version is not None,
                at_table=i,
            )))

    # The seats come back in stack order, because that is what every
    # caller wants: `Chart.order` turns it into the pile that comes off
    # the printer. Sorting is skipped entirely where no seat claims a
    # place, so a chart written before this key existed is not merely
    # handled but untouched. Stable, and unnumbered seats last -- the
    # rule an unplaced group and an unspotted seat already follow.
    if any(at is not None for at, _ in found):
        found.sort(key=lambda pair: (pair[0] is None, pair[0] or 0))
    return Chart([seat for _, seat in found], versions)


def disagrees_with_room(chart, room):
    """Where `seating.toml` and `room.json` do not say the same thing.

    Returns a list of sentences, empty when they agree.

    The two files overlap in exactly one fact -- who sits where, with
    which version -- and the app writes both in the same save, so they
    agree right up until something edits one of them alone. A filter
    would hide that; a check names it, which is the same reasoning as
    `check_dropped_are_unseated`.

    Compared by student id only. A chart with no ids in it is a
    hand-written or imported one, and the names in it were never
    expected to line up with the room's ids -- so that case returns
    nothing rather than a page of noise about a file somebody wrote
    deliberately.
    """
    from . import room as room_mod

    seated = {}
    for section in room.get("sections") or []:
        for seat in room_mod.live_seats(section):
            who = str(seat.get("student") or "").strip()
            if who:
                seated[who] = str(seat.get("version") or "").strip()

    charted = {s.sid: s for s in chart.seats if s.sid}
    if not charted:
        return []

    problems = []
    for sid in sorted(set(charted) - set(seated)):
        problems.append(
            f"{charted[sid].name} has a seat in seating.toml but not in "
            f"the seating chart.")
    for sid in sorted(set(seated) - set(charted)):
        problems.append(
            f"a student seated in the chart (id {sid}) has no seat in "
            f"seating.toml.")
    for sid in sorted(set(charted) & set(seated)):
        theirs, ours = seated[sid], charted[sid].version
        if theirs and ours and theirs != ours:
            problems.append(
                f"{charted[sid].name} is version {ours} in seating.toml "
                f"and {theirs} in the seating chart.")
    return problems


def blank_seat(text, name):
    """Empty one seat in a seating file, returning (new text, how many).

    A text edit rather than a parse-and-rewrite, because these files carry
    hand-written comments -- which table is which, where a section starts --
    and Python has no TOML writer that would keep them. Only the quoted name
    changes; every other byte survives.

    The seat is emptied, not removed. `alternate()` assigns version letters by
    position, so deleting the entry would re-letter everyone after it at that
    table; leaving a hole keeps their papers the same.
    """
    needle = name.strip()
    if not needle:
        return text, 0
    out, count = [], 0
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            for quoted in (f'"{needle}"', f"'{needle}'"):
                if quoted in line:
                    line = line.replace(quoted, '""')
                    count += 1
        out.append(line)
    return "".join(out), count


def index_by_name(people):
    """Every spelling a seat may legitimately use, to the student's position.

    `seating.toml` holds no id -- a seat is a name and nothing else -- so
    this is the one join in the tool made on a name, and it accepts both the
    roster name and the printed one. A list per spelling, because a clash is
    for the caller to refuse rather than for this to guess at.
    """
    index = {}
    for i, s in enumerate(people):
        for spelling in {s.name, s.display}:
            if spelling:
                index.setdefault(spelling, []).append(i)
    return index


@dataclasses.dataclass
class Chart:
    seats: list
    versions: tuple

    def __iter__(self):
        return iter(self.seats)

    def __len__(self):
        return len(self.seats)

    def version_of(self, name):
        for seat in self.seats:
            if seat.name == name:
                return seat.version
        return None

    def neighbours(self):
        """Pairs of seats that sit next to each other at a table.

        Beside each other at the same table, in the order that table
        listed them -- *not* next to each other in the stack. Those were
        one list until a print order could cross tables; now a walk
        round the room interleaves them, and "the next entry along"
        would be somebody at another table half the time, which this
        would read as nobody having a neighbour at all.

        A table is read as a line and not a ring, so the first and last
        seats are not compared. That is the existing reading and it is
        deliberate: a chart knows who is listed beside whom and not the
        geometry, and inventing the wrap would invent an adjacency for
        every row of desks as well.
        """
        tables = {}
        for seat in self.seats:
            tables.setdefault(seat.group, []).append(seat)
        pairs = []
        for group in sorted(tables):
            run = sorted(tables[group], key=lambda s: s.at_table)
            pairs.extend(zip(run, run[1:]))
        return pairs

    def collisions(self):
        """Adjacent seats in the same group sharing a version.

        Only possible once a seat is pinned -- plain alternation cannot collide.
        Reported rather than raised: a pin is a deliberate act, and the operator
        may have a reason.

        This is what the *chart* says. A per-run pin in a publication's
        `[versions]` changes the paper without touching the chart, so a
        build must ask `assemble.printed_collisions` instead; this one
        would answer for a room that is not the one being printed.
        """
        return [(a, b) for a, b in self.neighbours()
                if a.version == b.version]

    def order(self, roster):
        """The roster, in seating order.

        Students in the chart come first, in seat order, each carrying its
        version. Anyone in the roster but not seated follows, so a missing seat
        loses a student's place in the stack but never the student.
        """
        people = list(roster)
        index = index_by_name(people)
        # The id wins where the chart records one. That is the whole
        # point of recording it: a renamed student keeps their seat,
        # their place in the stack and their version letter, where
        # before the seat simply stopped matching anybody.
        by_sid = {}
        for i, student in enumerate(people):
            if student.sid:
                by_sid.setdefault(student.sid, []).append(i)

        ordered, seated = [], set()
        for seat in self.seats:
            hits = by_sid.get(seat.sid) if seat.sid else None
            if not hits:
                hits = index.get(seat.name)
            if not hits:
                continue
            if len(hits) > 1:
                raise SeatingError(
                    f"seat {seat.name!r} matches {len(hits)} students. One of "
                    f"them has it as a printed name and another as a roster "
                    f"name; give the seat whichever is unique."
                )
            if hits[0] in seated:
                raise SeatingError(
                    f"{people[hits[0]].display} is in two seats. Accepting "
                    f"both spellings means a chart naming each once names "
                    f"the same person twice; empty one of them."
                )
            seated.add(hits[0])
            ordered.append(dataclasses.replace(people[hits[0]],
                                               version=seat.version))
        unseated = [s for i, s in enumerate(people) if i not in seated]
        return ordered, unseated


TEMPLATE = '''# Where students sit. One [[group]] per table.
#
# Versions alternate along each group, so immediate neighbours never share one,
# and the pattern restarts at each table because two tables are not adjacent.
#
# Students print in this order, so the stack matches the room.

versions = ["A", "B"]

[[group]]
seats = ["Ada Lovelace", "Alan Turing", "Grace Hopper", "Katherine Johnson"]

# A seat may pin its version; everything else alternates around it.
# [[group]]
# seats = [{name = "Emmy Noether", version = "B"}, "Srinivasa Ramanujan"]
'''


def _quote(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


#: The line `to_toml` stamps on a chart it wrote, and the line
#: `was_generated` looks for. One string, because the writer and the
#: reader of a format drifting apart is how a "second copy" bug starts:
#: reword the sentence and the detector silently stops recognising its
#: own output, and the app starts refusing to update a chart it owns.
GENERATED_MARK = "# Generated: the room file is the one to edit"


def was_generated(path):
    """Did this tool write that chart, or did a person or an import?

    Only the first few lines are read: the mark is a header, and a chart
    is long. Anything unreadable answers no, which is the safe way round
    -- the question is only ever asked before overwriting.
    """
    try:
        with open(path, encoding="utf-8") as f:
            for _ in range(8):
                line = f.readline()
                if not line:
                    break
                if line.startswith(GENERATED_MARK):
                    return True
    except OSError:
        return False
    return False


def to_toml(room, name_of, written_by="the seating chart tab"):
    """Write the chart a room describes.

    `name_of` turns a student id into the name the roster knows them by.
    The room holds ids and so, now, does each seat: `sid` is written
    beside the name and is what `Chart.order` matches on first. The
    name stays because a chart is meant to be read and hand-edited, and
    a wall of nine-digit numbers is not -- but it is no longer the join.
    Renaming a student used to unseat them silently, because
    `api_roster_save` writes the roster and nothing else.

    The roster name rather than the printed one: two students can share
    a printed name, and this is the file that has to identify them.

    **Every seat is pinned.** The app decides the letters now -- by
    coloring the room, where `alternate` could only cycle a list -- so
    the letters are written down rather than recomputed. `alternate`
    remains for a chart this tool did not write.

    Sections come out in their order, and groups in theirs, so a stack
    handed out table by table comes off the printer already sorted. A
    stack that crosses tables cannot be written as an order of tables,
    so each seat carries its place in it as `at` -- and only then: a
    room whose printing nobody has reordered produces exactly the file
    it always did.
    """
    from . import room as room_mod

    # Said truthfully, not aspirationally. The header used to state
    # that every seat names its version "because the room chose it",
    # and a room where nobody has run the coloring chose nothing -- so
    # the file asserted the opposite of what it contained, and the
    # letters a build then used came from `alternate` with nothing
    # anywhere admitting it.
    chose = any(
        (seat.get("version") or "").strip()
        for section in room.get("sections") or []
        for seat in room_mod.live_seats(section)
        if (seat.get("student") or "").strip()
    )
    lines = [
        f"# Written by `{written_by}` from this course's room.",
        "#",
        GENERATED_MARK + ", and the next write",
        "# will overwrite this.",
    ]
    lines += ([
        "# Every seat names its version because the room chose it.",
    ] if chose else [
        "#",
        "# NO VERSIONS ARE SET. No seat in the room carries a letter, so",
        "# none is written here and a build will alternate A B C D along",
        "# each table instead -- which is safe within a table and knows",
        "# nothing about who sits near whom across the room. Assign them",
        "# in Printing mode, under the corner menu: Shuffle versions.",
    ])
    lines += [
        "",
        "versions = [" + ", ".join(_quote(v) for v in room["versions"]) + "]",
        "",
    ]

    sections = sorted(
        room.get("sections") or [],
        # An unplaced section goes last rather than first, which is what
        # `None` would sort as.
        key=lambda s: (s.get("order") is None, s.get("order") or 0,
                       s.get("name") or ""))

    # Every section worked out before anything is written, because the
    # numbering is **one sequence for the whole file**. A chart is a
    # flat list of tables: it has no sections in it at all, only a
    # comment saying where one begins. A counter that restarted per
    # section would put 830's first seat level with 820's, and the two
    # would come off the printer shuffled into each other.
    #
    # Found by writing the real two-section room. Every test had one.
    laid = []
    for section in sections:
        where = {s["id"]: s for s in room_mod.seats_of(section)}
        plan = room_mod.ordered_groups(section)
        reading = [sid for g in plan for sid in (g.get("seats") or [])]
        who = {sid: name_of((where.get(sid) or {}).get("student") or "")
               for sid in reading}
        laid.append((section, where, plan, reading, who,
                     room_mod.stack_order(section)))

    # Numbered at all only where some section's stack is not already
    # the order it reads in -- handing out table by table with nothing
    # reordered, those are the same list, and an untouched room writes
    # the file it always did. One section needing numbers means every
    # section gets them: a seat without one prints last, so a section
    # left bare would be dragged to the end of the stack.
    #
    # Only a seat that prints gets one. An empty chair is written as
    # `""`, which has nowhere to put it, and its place in the stack is
    # nobody's paper.
    numbered = {}
    if any(stack != reading for _, _, _, reading, _, stack in laid):
        numbered = {sid: n for n, sid in enumerate(
            (sid for _, _, _, _, who, stack in laid
             for sid in stack if who.get(sid)), 1)}

    body = []
    for section, where, plan, _, who, _ in laid:
        body.append(f"# ---- section {section.get('name', '')}")
        body.append("")
        for group in plan:
            label = group.get("label") or ""
            if label:
                body.append(f"# {label}")
            entries = []
            for seat_id in group.get("seats") or []:
                seat = where.get(seat_id)
                if seat is None:
                    continue
                name = who.get(seat_id) or ""
                if not name:
                    entries.append('""')          # an empty chair
                    continue
                version = seat.get("version") or ""
                at = numbered.get(seat_id)
                # The id the room already keyed this seat by. Written
                # second, after the name, so the file still reads as a
                # list of people.
                sid = str(seat.get("student") or "").strip()
                entries.append(
                    "{name = " + _quote(name)
                    + (", sid = " + _quote(sid) if sid else "")
                    + (", version = " + _quote(version) if version else "")
                    + (f", at = {at}" if at else "")
                    + "}")
            body.append("[[group]]")
            body.append("seats = [" + ", ".join(entries) + "]")
            body.append("")

    # Said here rather than in the header above, because it is only
    # true of a room that was actually reordered and a standing note
    # about a key the file does not contain is worse than no note.
    if numbered:
        lines += [
            "# A seat's `at` is its place in the stack. The tables below say",
            "# who sits beside whom; `at` says what order the papers come",
            "# out, which stopped being the same list when the printing was",
            "# reordered to cross the tables.",
            "",
        ]
    return "\n".join(lines + body)
