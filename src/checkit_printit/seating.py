"""Seat order, and which version each seat gets.

Two jobs, and they are the same job: students print in seating order so a stack
of paper matches the room, and adjacent seats must not share a version.

**The rule is immediate neighbours, not whole groups.** A table of four seated
A, B, A, B satisfies it with two versions; requiring everyone at a table to
differ would need four, for no gain. Two versions is the intent.

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

    versions = tuple(raw.get("versions") or versions)
    if len(versions) < 2:
        raise SeatingError(
            f"{path}: at least two versions are needed, or neighbours cannot "
            f"differ. Got {list(versions)}."
        )

    groups = raw.get("group")
    if not groups:
        raise SeatingError(f"{path} has no [[group]] tables.")

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
        by_name = {s.name: s for s in roster}
        ordered, seated = [], set()
        for seat in self.seats:
            student = by_name.get(seat.name)
            if student is None:
                continue
            ordered.append(dataclasses.replace(student, version=seat.version))
            seated.add(seat.name)
        unseated = [s for s in roster if s.name not in seated]
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
