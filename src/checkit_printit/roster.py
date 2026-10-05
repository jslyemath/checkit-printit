"""Who exists, what they chose, and where they sit.

The tool's own format is structured data with real fields. A spreadsheet export
is an *import step*, never the model: the previous pipeline located its columns
by string-searching a grid for `Full Name:` and `Var:`, which is fragile in a
way nothing downstream should inherit.
"""

import csv
import os
import dataclasses
import tomllib


class RosterError(Exception):
    pass


@dataclasses.dataclass
class Student:
    """One student.

    `name` is what prints and what the seating chart matches on. `last` and
    `first` are what the registrar says. They are separate fields because a
    seating chart says "Matt Brienza" and a class list says "Brienza,
    Matthew C." -- with only one of them, every re-import would rename the
    person on the printed page.

    Two id fields because the exports use two numbering systems: a Banner
    student id (`806...`) and a Global id, which the LMS calls OrgDefinedId
    (`20...`). A given export may carry either or both, so a merge matches on
    whichever it has.
    """

    name: str
    skills: list
    section: str = ""
    email: str = ""
    sid: str = ""

    # from the registrar, kept as the record
    last: str = ""
    first: str = ""

    #: What to print instead of `name` -- the *whole* name, not a first
    #: name. "Matt Clifford", not "Matt".
    #:
    #: It meant a first name until 2026-10-01, defaulted from the
    #: registrar's `first` on import, and nothing ever read it. `first`,
    #: `last` and `preferred` are empty on all eight real rosters, so there
    #: was nothing to migrate and the meaning was free to fix. Had it stayed
    #: a first name, every paper would have carried one word.
    preferred: str = ""

    #: the other id system, when an export carries it
    alt_id: str = ""

    #: Every address this student has been seen under, primary included.
    #:
    #: Not tidiness: one student in the first three real class lists appears
    #: as `mcliffo4@oswego.edu` in Banner and `m.clifford@clasnet...` in the
    #: LMS, downloaded the same day, and the Google Form only ever sees the
    #: first. Overwriting on import would have silently stopped her responses
    #: from matching.
    emails: list = dataclasses.field(default_factory=list)

    #: no longer enrolled. Never deleted, because the print record refers to
    #: them. Dropping also empties their seat, which is what actually stops
    #: the printing -- the seating chart is the print list.
    dropped: bool = False

    #: "instructor" or "import". An instructor's drop is sticky: a later class
    #: list that still lists the student does not undo it, because the
    #: registrar is often behind the room. A drop inferred from an import is
    #: undone by an import that disagrees.
    dropped_by: str = ""

    #: Set by seating, not by the roster.
    version: str = ""

    @property
    def display(self):
        """What a person should see: the preferred name, else the roster one.

        Every surface that *shows* this student goes through here -- the
        printed paper, the seating chart, the tables. Every surface that
        *matches* one keeps using `sid`, `alt_id`, `email` and `name`,
        because a name an instructor can retype is not a key.
        """
        return self.preferred or self.name

    def all_emails(self):
        """The primary first, then any other address seen, de-duplicated."""
        out = []
        for e in [self.email] + list(self.emails):
            e = (e or "").strip().lower()
            if e and e not in out:
                out.append(e)
        return out

    def ids(self):
        """Every stable key this student can be matched on, strongest first."""
        keys = [("sid", self.sid), ("alt_id", self.alt_id)]
        keys += [("email", e) for e in self.all_emails()]
        return keys


@dataclasses.dataclass
class Roster:
    students: list

    def __len__(self):
        return len(self.students)

    def __iter__(self):
        return iter(self.students)

    def skills_used(self):
        """Every skill anyone asked for, in first-seen order.

        Order matters: it is what makes the answer key follow the same sequence
        as the handouts, which is how you check one against the other.
        """
        seen = []
        for student in self.students:
            for skill in student.skills:
                if skill not in seen:
                    seen.append(skill)
        return seen


def load(path):
    """Read a roster file. TOML today; the format the tool owns."""
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    entries = raw.get("student")
    if not entries:
        raise RosterError(
            f"{path} lists no students. Expected one or more [[student]] tables."
        )

    students = []
    for i, entry in enumerate(entries, 1):
        name = (entry.get("name") or "").strip()
        if not name:
            raise RosterError(f"student {i} in {path} has no name.")
        skills = entry.get("skills") or []
        if not isinstance(skills, list):
            raise RosterError(f"{name}: `skills` must be a list, not {type(skills).__name__}.")
        students.append(Student(
            name=name,
            skills=[str(s).strip() for s in skills if str(s).strip()],
            section=str(entry.get("section", "")).strip(),
            email=str(entry.get("email", "")).strip(),
            sid=str(entry.get("sid", "")).strip(),
            last=str(entry.get("last", "")).strip(),
            first=str(entry.get("first", "")).strip(),
            preferred=str(entry.get("preferred", "")).strip(),
            alt_id=str(entry.get("alt_id", "")).strip(),
            emails=[str(e).strip().lower()
                    for e in (entry.get("emails") or []) if str(e).strip()],
            dropped=bool(entry.get("dropped", False)),
            dropped_by=str(entry.get("dropped_by", "")).strip(),
        ))
    return Roster(students)


class NotFound(RosterError):
    pass


class Ambiguous(RosterError):
    pass


def find(roster, who):
    """One student, by id, address or name. Refuses to guess.

    Identifiers are tried strongest first, so a name that happens to look like
    somebody else's cannot beat an exact id.
    """
    needle = who.strip().lower()
    if not needle:
        raise NotFound("name somebody to look for.")

    for attr in ("sid", "alt_id"):
        hits = [s for s in roster if getattr(s, attr).lower() == needle]
        if len(hits) == 1:
            return hits[0]

    hits = [s for s in roster if needle in s.all_emails()]
    if len(hits) == 1:
        return hits[0]

    hits = [s for s in roster if s.name.strip().lower() == needle]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise Ambiguous(f"{who!r} matches {len(hits)} students. Use a student "
                        f"id or an email address instead.")

    hits = [s for s in roster if needle in s.name.strip().lower()]
    if len(hits) == 1:
        return hits[0]
    if len(hits) > 1:
        raise Ambiguous(
            f"{who!r} matches {len(hits)} students: "
            + ", ".join(sorted(s.name for s in hits))
            + ". Be more specific, or use an id."
        )
    raise NotFound(f"no student matching {who!r}.")


def keys_of(student):
    """Every id a per-run table may be keyed by, strongest first.

    The name is last and is a weak key. It is here because a roster built
    from a spreadsheet may carry nothing else, not because it is safe.
    """
    return tuple(k for k in (student.sid, student.alt_id, student.email,
                             student.name) if k)


def key_of(student):
    """The one id this student is filed under.

    `keys_of` is what a *lookup* tries, strongest first; this is what a
    *write* uses, so a student's pulled choices and their override land
    under the same key and the later one replaces the earlier.
    """
    keys = keys_of(student)
    return keys[0] if keys else ""


def apply_overrides(roster, overrides):
    """Replace one student's chosen skills, for this run only.

    Returns `(roster, unmatched)`. The unmatched keys are reported rather
    than dropped: a line the instructor typed that silently does nothing is
    how this went wrong in the first place.
    """
    if not overrides:
        return roster, []
    used, out = set(), []
    for student in roster:
        for key in keys_of(student):
            if key in overrides:
                out.append(dataclasses.replace(student,
                                               skills=list(overrides[key])))
                used.add(key)
                break
        else:
            out.append(student)
    return Roster(out), sorted(set(overrides) - used)


def apply_selection_modes(roster, simply_print=(), default_when_missing=(),
                          append_for_everyone=()):
    """The three selection overrides, which compose.

    - `simply_print`: everyone gets exactly these; individual choices ignored.
      For a day when the whole class sits the same thing.
    - `default_when_missing`: what a student who chose nothing gets.
    - `append_for_everyone`: added on top of whatever each student ends with.

    Returns a new Roster; the input is left alone so a caller can report on
    both.
    """
    out = []
    for student in roster:
        if simply_print:
            chosen = list(simply_print)
        elif student.skills:
            chosen = list(student.skills)
        else:
            chosen = list(default_when_missing)

        for skill in append_for_everyone:
            if skill not in chosen:
                chosen.append(skill)

        out.append(dataclasses.replace(student, skills=chosen))
    return Roster(out)


# ---------------------------------------------------------------- dropping --

@dataclasses.dataclass
class DropResult:
    """What `set_dropped` did, for a caller to render however it likes."""
    student: "Student"
    changed: bool
    dropped: bool
    seats_emptied: int = 0
    seating_checked: bool = False
    #: Chairs emptied in `room.json`, counted apart from the chart's so
    #: one person leaving one chair is not reported as two seats.
    room_emptied: int = 0


def set_dropped(roster_path, who, dropped, seating_path=None, room_path=None):
    """Flag a student dropped, or undo it. Empties their seat on the way out.

    The roster keeps them, because the print record refers to them. The
    seating chart loses them, because the chart is the print list and that is
    what actually stops the printing. The seat is emptied rather than removed:
    version letters come from position, so deleting the entry would re-letter
    that student's tablemates.

    **The room as well, when there is one.** The seating tab writes the
    chart from `room.json`, so a drop that cleared only the chart would be
    undone the next time anybody saved that tab -- the student would walk
    back onto the printed list with nothing having gone wrong on screen.
    The room matches on id, which is why it is passed the whole list of
    keys rather than a name.

    Raises RosterError for a name that matches nothing or several people.
    Returns a DropResult; it never prints, so the CLI and the GUI can share it.
    """
    from . import room as room_mod
    from . import seating as seating_mod

    people = load(roster_path)
    student = find(people, who)

    if student.dropped == dropped:
        return DropResult(student=student, changed=False, dropped=dropped)

    student.dropped = dropped
    student.dropped_by = "instructor" if dropped else ""
    with open(roster_path, "w", encoding="utf-8") as f:
        f.write(to_toml(people, "checkit-printit roster drop"))

    result = DropResult(student=student, changed=True, dropped=dropped)

    if dropped and seating_path and os.path.isfile(seating_path):
        result.seating_checked = True
        with open(seating_path, encoding="utf-8") as f:
            text = f.read()
        count = 0
        # Both spellings, for the same reason `Chart.order` reads both.
        for spelling in {student.name, student.display}:
            text, emptied = seating_mod.blank_seat(text, spelling)
            count += emptied
        new = text
        result.seats_emptied = count
        if count:
            with open(seating_path, "w", encoding="utf-8") as f:
                f.write(new)

    if dropped and room_path and os.path.isfile(room_path):
        try:
            room = room_mod.load(room_path)
        except room_mod.RoomError:
            # A room this printit cannot read is not one to rewrite. The
            # chart has already been cleared, which is what stops the
            # printing; the room is the drawing.
            pass
        else:
            emptied = room_mod.empty_seats_for(room, keys_of(student))
            if emptied:
                room_mod.save(room_path, room)
            result.room_emptied = emptied
    return result


# ---------------------------------------------------------------------------
# Importing
# ---------------------------------------------------------------------------

def from_spreadsheet_export(path, name_column="Full Name:", skill_columns=None,
                            section_column="Sec:", email_column="Email:",
                            sid_column="SID:"):
    """Read the Apps Script's CSV export into the tool's own shape.

    Deliberately a one-way import rather than a supported input format. Run it
    once, look at the TOML it produces, correct anything it got wrong, and never
    think about column positions again.

    The header row is found by looking for `name_column` anywhere in the file,
    because the export has preamble rows above it.
    """
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.reader(f))

    header_row = header_col = None
    for r, row in enumerate(rows):
        for c, cell in enumerate(row):
            if cell.strip() == name_column:
                header_row, header_col = r, c
                break
        if header_row is not None:
            break
    if header_row is None:
        raise RosterError(
            f"{path} has no {name_column!r} cell, so the header row cannot be "
            "found. Check the export, or pass name_column="
        )

    header = rows[header_row]

    def column(label):
        for c, cell in enumerate(header):
            if cell.strip() == label:
                return c
        return None

    cols = {
        "section": column(section_column),
        "email": column(email_column),
        "sid": column(sid_column),
    }
    if skill_columns is None:
        # Everything right of the last identified column is a skill choice.
        known = [c for c in list(cols.values()) + [header_col] if c is not None]
        skill_columns = range(max(known) + 1, len(header))

    def cell(row, index):
        if index is None or index >= len(row):
            return ""
        return str(row[index]).strip()

    students = []
    for row in rows[header_row + 1:]:
        name = cell(row, header_col)
        if not name:
            continue
        skills = [cell(row, c) for c in skill_columns]
        students.append(Student(
            name=name,
            skills=[s for s in skills if s],
            section=cell(row, cols["section"]),
            email=cell(row, cols["email"]),
            sid=cell(row, cols["sid"]),
        ))
    return Roster(students)


def to_toml(roster, written_by="checkit-printit"):
    """Serialise a roster. `written_by` is the command to blame for it.

    Several commands regenerate this file -- `roster import`, `roster drop`,
    `roster restore` and `form pull` -- so the header has to say which one
    did, and must not claim that nothing will do it again. It used to say
    exactly that, while `form pull` rewrote it.
    """
    def quote(s):
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = [f"# Written by `{written_by}`. This is the tool's own format, and",
             "# it is safe to edit -- but `roster import`, `roster drop`,",
             "# `roster restore` and `form pull` all rewrite the whole file,",
             "# so a comment added here will not survive the next one.", ""]
    for s in roster:
        lines.append("[[student]]")
        lines.append(f"name      = {quote(s.name)}")
        if s.last:
            lines.append(f"last      = {quote(s.last)}")
        if s.first:
            lines.append(f"first     = {quote(s.first)}")
        if s.preferred:
            lines.append(f"preferred = {quote(s.preferred)}")
        if s.sid:
            lines.append(f"sid       = {quote(s.sid)}")
        if s.alt_id:
            lines.append(f"alt_id    = {quote(s.alt_id)}")
        if s.email:
            lines.append(f"email     = {quote(s.email)}")
        others = [e for e in s.all_emails() if e != s.email.strip().lower()]
        if others:
            lines.append("emails    = [" + ", ".join(quote(e) for e in others)
                         + "]  # also seen under these")
        if s.section:
            lines.append(f"section   = {quote(s.section)}")
        if s.dropped:
            lines.append("dropped   = true")
            if s.dropped_by:
                lines.append(f"dropped_by = {quote(s.dropped_by)}")
        lines.append("skills    = [" + ", ".join(quote(k) for k in s.skills) + "]")
        lines.append("")
    return "\n".join(lines)


TEMPLATE = '''# Who exists, and what each of them chose.
#
# The tool's own format. To start from a spreadsheet export instead:
#     checkit-printit import "Control Center.csv" -o roster.toml

[[student]]
name    = "Ada Lovelace"
section = "800"
skills  = ["W1", "N3"]

[[student]]
name    = "Alan Turing"
section = "800"
skills  = ["W1", "D2"]
'''
