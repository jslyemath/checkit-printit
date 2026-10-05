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
    pinned: bool = False


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

    seats = []
    for g, group in enumerate(groups, 1):
        entries = group.get("seats") or []
        assigned = alternate(len(entries), versions)
        for i, entry in enumerate(entries):
            if isinstance(entry, dict):
                name = (entry.get("name") or "").strip()
                pinned_version = entry.get("version")
            else:
                name, pinned_version = str(entry).strip(), None
            if not name:
                continue
            if pinned_version is not None and pinned_version not in versions:
                raise SeatingError(
                    f"{path}: seat {name!r} is pinned to version "
                    f"{pinned_version!r}, which is not in {list(versions)}."
                )
            seats.append(Seat(
                name=name,
                group=g,
                version=pinned_version or assigned[i],
                pinned=pinned_version is not None,
            ))
    return Chart(seats, versions)


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
        found = []
        for a, b in zip(self.seats, self.seats[1:]):
            if a.group == b.group and a.version == b.version:
                found.append((a, b))
        return found

    def order(self, roster):
        """The roster, in seating order.

        Students in the chart come first, in seat order, each carrying its
        version. Anyone in the roster but not seated follows, so a missing seat
        loses a student's place in the stack but never the student.
        """
        people = list(roster)
        index = index_by_name(people)

        ordered, seated = [], set()
        for seat in self.seats:
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
    The room holds ids; `seating.toml` holds names, because that is what a
    chart has always held and what `Chart.order` matches on. The roster
    name rather than the printed one: two students can share a printed
    name, and this is the file that has to identify them.

    **Every seat is pinned.** The app decides the letters now -- by
    colouring the room, where `alternate` could only cycle a list -- so
    the letters are written down rather than recomputed. `alternate`
    remains for a chart this tool did not write.

    Groups come out in print order, sections in theirs, so the stack comes
    off the printer in the order it is handed out.
    """
    from . import room as room_mod

    lines = [
        f"# Written by `{written_by}` from this course's room.",
        "#",
        GENERATED_MARK + ", and the next write",
        "# will overwrite this. Every seat names its version because the",
        "# room chose it; a hand-written chart may leave them out and have",
        "# them alternate instead.",
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

    for section in sections:
        lines.append(f"# ---- section {section.get('name', '')}")
        lines.append("")
        where = {s["id"]: s for s in room_mod.seats_of(section)}
        for group in room_mod.ordered_groups(section):
            label = group.get("label") or ""
            if label:
                lines.append(f"# {label}")
            entries = []
            for seat_id in group.get("seats") or []:
                seat = where.get(seat_id)
                if seat is None:
                    continue
                name = name_of(seat.get("student") or "")
                if not name:
                    entries.append('""')          # an empty chair
                    continue
                version = seat.get("version") or ""
                entries.append(
                    "{name = " + _quote(name)
                    + (", version = " + _quote(version) if version else "")
                    + "}")
            lines.append("[[group]]")
            lines.append("seats = [" + ", ".join(entries) + "]")
            lines.append("")
    return "\n".join(lines)
