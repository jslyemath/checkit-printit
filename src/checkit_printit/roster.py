"""Who exists, what they chose, and where they sit.

The tool's own format is structured data with real fields. A spreadsheet export
is an *import step*, never the model: the previous pipeline located its columns
by string-searching a grid for `Full Name:` and `Var:`, which is fragile in a
way nothing downstream should inherit.
"""

import csv
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

    # the display first name; `name` is the display full name
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

    #: no longer enrolled. Excluded from printing and from the form; never
    #: deleted, because the print record has to survive.
    dropped: bool = False

    #: Set by seating, not by the roster.
    version: str = ""

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
        ))
    return Roster(students)


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


def to_toml(roster):
    """Serialise a roster, for the import step to write out."""
    def quote(s):
        return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = ["# Written by `checkit-printit import`. Edit freely -- this is the",
             "# tool's own format, and nothing regenerates it.", ""]
    for s in roster:
        lines.append("[[student]]")
        lines.append(f"name      = {quote(s.name)}")
        if s.last:
            lines.append(f"last      = {quote(s.last)}")
        if s.first:
            lines.append(f"first     = {quote(s.first)}")
        if s.preferred and s.preferred != s.first:
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
