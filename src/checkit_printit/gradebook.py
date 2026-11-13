"""What one course's gradebook looks like, written down as data.

Exporting results to an LMS does **not** mean generating a CSV. It
means: take the file the instructor exported, fill in the cells there is
a recorded result for, change nothing else, hand it back. Same columns
in the same order, same rows, same untouched values.

That shape of job needs to know almost nothing about any particular
LMS. What it does need is five facts about the file in front of it, and
those five facts are what this module stores:

1. **Which column identifies a student**, and which roster field it
   joins to. One real Brightspace export has `OrgDefinedId` and no name
   column at all, so there is nothing else to go on.
2. **How a skill's column is named**, so a column can be found from a
   bank slug.
3. **The exact strings for a pass and a non-pass.** On the real export
   these are an emoji followed immediately by `Pass` or `Not Yet`, with
   no space -- a detail no amount of guessing would have produced.
4. **Whether a blank cell means "not attempted" or counts as a zero.**
   This one is dangerous: on Brightspace the subtotals count filled
   cells, so writing a non-pass into a blank *raises* that student's
   denominator and lowers their grade.
5. **Which rows and columns must never be written to.**

A profile is derived once by `gradebook map`, saved next to the course's
other state, and is an ordinary readable file that can be corrected by
hand. It is deliberately not GUI state: a decision the tool made about
a column should be greppable and diffable, and a web page that holds it
is a page that has to be opened to find out what the tool believes.

**The physical format of the file -- a byte-order-mark, the line
endings -- is not stored here.** It is read off the file itself at
export time by `mask.sniff`, because it is a property of the file the
instructor hands over on the day and storing it would give it a chance
to go stale.
"""

import dataclasses
import os
import re
import tomllib

FILENAME = "gradebook.toml"

#: What a blank cell may mean, and why the difference matters.
#:
#: `not attempted` -- the LMS leaves it out of the subtotal, so a blank
#: is the correct state for a skill the student has not sat, and
#: printit must leave it alone.
#:
#: `zero` -- the LMS counts a blank as a fail. Then leaving a blank is
#: itself a grade, and the instructor has to decide whether an
#: un-attempted skill should be filled in.
BLANK_MEANINGS = ("not attempted", "zero")

#: The roster fields a gradebook's id column may join to, in the order
#: worth trying them.
#:
#: Here rather than in the CLI, because there were three copies: the
#: CLI's `_ID_PREFERENCE`, the tuple hardcoded inside
#: `Profile.validate`, and the `click.Choice` built from the first --
#: and a fourth was about to be written for the web app. A list of
#: what the tool accepts belongs with the thing that accepts it.
ID_FIELDS = ("alt_id", "handle", "sid", "email")


class GradebookError(Exception):
    pass


# ----------------------------------------------------------- the profile --

@dataclasses.dataclass
class Profile:
    """The five facts, plus a name to recognise it by."""

    name: str = ""

    #: The header of the column holding the student's LMS id.
    student_column: str = ""

    #: Which roster field that column joins to: `alt_id`, `sid`,
    #: `handle` or `email`. Named rather than guessed, because the
    #: overlap between a 10-digit LMS id and a 9-digit student number
    #: is zero and a wrong guess silently matches nobody.
    student_matches: str = "alt_id"

    #: The exact cell contents for a pass and for a non-pass.
    passed: str = ""
    not_passed: str = ""

    #: One of `BLANK_MEANINGS`.
    blank_means: str = "not attempted"

    #: slug -> the exact header of its column, for the ones no rule
    #: could find. Only the exceptions are stored; everything the
    #: matcher can work out is worked out again each time, so a renamed
    #: column is noticed rather than silently remembered wrong.
    pairs: dict = dataclasses.field(default_factory=dict)

    #: A row whose student cell contains any of these is never written
    #: to. On the real export `-DoNotUse` marks a retired enrolment
    #: which shares its base id with a live row *and has marks of its
    #: own in it*.
    ignore_rows: list = dataclasses.field(default_factory=list)

    #: Exact headers never to write to, beyond the ones no slug claims.
    ignore_columns: list = dataclasses.field(default_factory=list)

    def validate(self, headers=None):
        """Raise `GradebookError` on anything that cannot be right.

        Checked against the real headers when they are available,
        because a profile that names a column the file does not have is
        the failure that would otherwise appear as "no results
        exported" with no reason given.
        """
        problems = []
        if not self.student_column:
            problems.append("no student column is named")
        if not self.passed:
            problems.append("no `passed` value is set")
        if not self.not_passed:
            problems.append("no `not_passed` value is set")
        if self.passed and self.passed == self.not_passed:
            problems.append("`passed` and `not_passed` are the same string")
        if self.blank_means not in BLANK_MEANINGS:
            problems.append(
                f"`blank_means` is {self.blank_means!r}; expected one of "
                + ", ".join(repr(m) for m in BLANK_MEANINGS))
        if self.student_matches not in ID_FIELDS:
            problems.append(
                f"`matches` is {self.student_matches!r}; expected "
                + ", ".join(ID_FIELDS))
        if headers is not None:
            if self.student_column and self.student_column not in headers:
                problems.append(
                    f"the file has no column called {self.student_column!r}")
            for slug, header in self.pairs.items():
                if header not in headers:
                    problems.append(
                        f"{slug} is paired with a column the file does not "
                        f"have: {header!r}")
        if problems:
            raise GradebookError(
                "this gradebook profile cannot be used:\n  "
                + "\n  ".join(problems))

    def to_toml(self):
        def quote(value):
            return ('"' + str(value).replace("\\", "\\\\").replace('"', '\\"')
                    + '"')

        lines = [
            "# How this course's gradebook is laid out.",
            "#",
            "# Written by `checkit-printit gradebook map`. Safe to edit, but",
            "# `gradebook map` rewrites the whole file, so a comment added",
            "# here will not survive the next one.",
            "#",
            "# `passed` and `not_passed` are the exact cell contents, which",
            "# on some gradebooks begin with an emoji and have no space",
            "# after it. They are copied, never retyped.",
            "",
            f"name = {quote(self.name)}",
            "",
            "[student]",
            f"column  = {quote(self.student_column)}",
            f"matches = {quote(self.student_matches)}"
            "   # the roster field this id joins to",
            "",
            "[marks]",
            f"passed      = {quote(self.passed)}",
            f"not_passed  = {quote(self.not_passed)}",
            f"blank_means = {quote(self.blank_means)}",
        ]
        if self.blank_means == "not attempted":
            lines.append("# so a blank is left alone: filling it would raise")
            lines.append("# the student's denominator and lower their grade.")
        else:
            lines.append("# so a blank counts against the student, and an")
            lines.append("# un-attempted skill is already a zero.")

        lines += ["", "[pairs]",
                  "# Only the slugs no rule could find. Everything else is",
                  "# matched afresh each run, so a renamed column is noticed."]
        for slug in sorted(self.pairs):
            lines.append(f"{quote(slug)} = {quote(self.pairs[slug])}")

        lines += ["", "[ignore]",
                  "# A row whose student id contains any of these is never",
                  "# written to.",
                  "rows_containing = ["
                  + ", ".join(quote(r) for r in self.ignore_rows) + "]",
                  "",
                  "# Columns no skill in the bank claims. Listed in full,",
                  "# one per line, because a thirty-item array on one line",
                  "# is not something anybody can check.",
                  "columns = ["]
        for column in self.ignore_columns:
            lines.append("  " + quote(column) + ",")
        lines.append("]")
        return "\n".join(lines) + "\n"


def path_for(course, root=None):
    from . import course as course_mod
    return os.path.join(course_mod.path_for(course, root), FILENAME)


def load(path):
    if not os.path.isfile(path):
        raise GradebookError(
            f"no gradebook profile at {path}. Make one with "
            "`checkit-printit gradebook map`.")
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    student = raw.get("student") or {}
    marks = raw.get("marks") or {}
    ignore = raw.get("ignore") or {}
    return Profile(
        name=str(raw.get("name", "")),
        student_column=str(student.get("column", "")),
        student_matches=str(student.get("matches", "alt_id")),
        passed=str(marks.get("passed", "")),
        not_passed=str(marks.get("not_passed", "")),
        blank_means=str(marks.get("blank_means", "not attempted")),
        pairs={str(k): str(v) for k, v in (raw.get("pairs") or {}).items()},
        ignore_rows=[str(r) for r in (ignore.get("rows_containing") or [])],
        ignore_columns=[str(c) for c in (ignore.get("columns") or [])],
    )


def save(path, profile):
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(profile.to_toml())


# ---------------------------------------------------------- the matching --

def first_word(header):
    """The first whitespace-separated word of a column name.

    On the real export a skill column is `W1 Grade Symbol <Selectbox
    MaxPoints:1 Category:...>`, so the skill's code is simply the first
    word. 28 of 29 slugs are found this way with no configuration.
    """
    parts = str(header).split()
    return parts[0] if parts else ""


@dataclasses.dataclass
class MatchReport:
    """Which column each slug was found in, and how."""
    found: dict = dataclasses.field(default_factory=dict)   # slug -> index
    how: dict = dataclasses.field(default_factory=dict)     # slug -> rule
    missing: list = dataclasses.field(default_factory=list)  # slugs
    spare: list = dataclasses.field(default_factory=list)   # column indexes
    ambiguous: dict = dataclasses.field(default_factory=dict)

    def describe(self, headers=None, width=46):
        """How each skill was placed, and what the leftovers are.

        `headers` is optional and is used to **name** the columns an
        ambiguous slug could have meant: a list of numbers is not
        enough to choose between them, and choosing is what the reader
        has to do next. `width` truncates those names.
        """
        lines = [f"{len(self.found)} of "
                 f"{len(self.found) + len(self.missing)} skills matched"]
        by_rule = {}
        for slug, rule in self.how.items():
            by_rule.setdefault(rule, []).append(slug)
        for rule, slugs in sorted(by_rule.items()):
            lines.append(f"  {len(slugs):>3} by {rule}: "
                         + " ".join(sorted(slugs)))
        if self.ambiguous:
            lines.append("")
            for slug, where in sorted(self.ambiguous.items()):
                lines.append(
                    f"  {slug} could be any of {len(where)} columns, "
                    "left unmatched rather than guessed:")
                for index in where:
                    label = ""
                    if headers is not None and index < len(headers):
                        label = str(headers[index])
                        if len(label) > width:
                            label = label[:width - 3] + "..."
                    lines.append(f"      {index + 1:>3}  {label}")
        if self.missing:
            lines.append("")
            lines.append("  no column found for: " + " ".join(self.missing))
        return "\n".join(lines)


def match(headers, slugs, pairs=None):
    """Find each slug's column. Returns a `MatchReport`.

    Three passes, most specific first, and a slug that matches more than
    one still-free column at a pass is **left unmatched and reported**
    rather than resolved.

    The passes matter in this order because of `W1` and `W1-E`. A rule
    like "the slug appears as a word anywhere in the header" matches
    `W1` inside `W1-E Grade Symbol`, since a hyphen is a word boundary
    -- so the loose rules only ever see slugs the exact rule could not
    place, and only columns no other slug has claimed.
    """
    pairs = pairs or {}
    report = MatchReport()
    taken = set()

    # Pass 0: what the instructor paired by hand. Highest authority,
    # because it is the only one that knows `FCP` is the column called
    # `Fundamentals Checkpoint`.
    lookup = {h: i for i, h in enumerate(headers)}
    for slug, header in pairs.items():
        if header in lookup and slug in slugs:
            report.found[slug] = lookup[header]
            report.how[slug] = "a pair saved in the profile"
            taken.add(lookup[header])

    rules = (
        ("the first word of the header",
         lambda slug, h: first_word(h) == slug),
        ("the header starting with the slug",
         lambda slug, h: re.match(re.escape(slug) + r"(?![\w-])", h)),
        ("the slug as a word in the header",
         lambda slug, h: re.search(r"(?<![\w-])" + re.escape(slug)
                                   + r"(?![\w-])", h)),
    )
    for label, test in rules:
        for slug in slugs:
            if slug in report.found:
                continue
            hits = [i for i, h in enumerate(headers)
                    if i not in taken and test(slug, h)]
            if len(hits) == 1:
                report.found[slug] = hits[0]
                report.how[slug] = label
                taken.add(hits[0])
            elif len(hits) > 1:
                report.ambiguous[slug] = hits

    report.missing = [s for s in slugs if s not in report.found]
    report.spare = [i for i in range(len(headers)) if i not in taken]
    return report


# ------------------------------------------------------------- the marks --

def guess_marks(rows, columns, max_distinct=6):
    """Work out the pass and non-pass strings from the file itself.

    Returns `(passed, not_passed, others)`. The strings are **taken from
    the file**, never composed: on the real export a pass is a trophy
    character followed immediately by `Pass`, with no space, and that
    space is exactly the sort of thing a hand-written guess gets wrong.

    Which of the two is the pass is decided by looking for `pass` in it,
    case-insensitively. If that does not settle it, both come back in
    `others` and the instructor is asked.
    """
    seen = {}
    for row in rows:
        for index in columns:
            if index < len(row):
                value = row[index]
                if value.strip():
                    seen[value] = seen.get(value, 0) + 1
    if not seen:
        return "", "", []
    if len(seen) > max_distinct:
        # Too many to be a pass/not-pass vocabulary. Something is wrong
        # with the column selection, and saying so beats picking two.
        return "", "", sorted(seen, key=seen.get, reverse=True)

    passes = [v for v in seen if "pass" in v.lower()]
    if len(passes) != 1:
        return "", "", sorted(seen, key=seen.get, reverse=True)
    passed = passes[0]
    rest = [v for v in seen if v != passed]
    if len(rest) == 1:
        return passed, rest[0], []
    # A pass and several other things. The instructor's rule is that
    # the pass passes and everything else does not, so the most common
    # of the rest is the one to write -- but the others are reported,
    # because a mark nobody knew about is worth seeing.
    rest.sort(key=seen.get, reverse=True)
    return passed, rest[0], rest[1:]


# ---------------------------------------------------------- the export --
#
# What export is: **take the files the instructor exported, fill in the
# cells there is a recorded result for, change nothing else, hand them
# back.** Not "generate a CSV". Nothing here adds or removes a row.
#
# The rules are not invented. They are the ones
# `apply_to_brightspace.py` -- the instructor's own script, in
# production since October -- already follows, and they are stricter
# than the obvious ones in several places. Where this module and that
# script disagree, that script is right.


@dataclasses.dataclass
class Sheet:
    """One exported file. A course with two sections exports two."""
    name: str
    rows: list
    #: Where the header sits in the file, 1-based, for splicing.
    header_line: int = 1
    #: Inferred from the file name when it carries one.
    section: str = ""

    @property
    def head(self):
        return self.rows[0]

    @property
    def body(self):
        return self.rows[1:]


def sheet_from(path, rows, header_line=1):
    """A `Sheet`, with the section read out of the file name if it is there.

    The section is only used to check that students are in the file for
    their own section, so guessing wrong is a false warning and never a
    wrong write. A three-digit group in the name is the convention his
    exports already follow.
    """
    import os as _os
    name = _os.path.basename(path)
    # **After a hyphen or an underscore.** A bare "three digits not
    # surrounded by digits" picks `106` out of
    # `MAT106-820_GradesExport_...`, which made every row in both of
    # his real exports look like a section mismatch -- 42 false notes.
    # His own script anchors on `MAT\d+-(\d{3})`; this is the same idea
    # without the course code baked in.
    found = re.search(r"[-_](\d{3})(?!\d)", name)
    return Sheet(name=name, rows=rows, header_line=header_line,
                 section=found.group(1) if found else "")


@dataclasses.dataclass
class Change:
    """One cell that will change. Row and column are 1-based."""
    sheet: str
    row: int
    column: int
    slug: str
    was: str
    now: str
    why: str = ""


@dataclasses.dataclass
class Kept:
    """One cell deliberately left as it is, and why."""
    sheet: str
    row: int
    column: int
    slug: str
    value: str
    why: str


@dataclasses.dataclass
class ExportReport:
    changes: list = dataclasses.field(default_factory=list)
    kept: list = dataclasses.field(default_factory=list)
    already_right: int = 0
    not_written: int = 0
    rows_matched: int = 0
    rows_ignored: list = dataclasses.field(default_factory=list)
    rows_unmatched: list = dataclasses.field(default_factory=list)
    students_unmatched: list = dataclasses.field(default_factory=list)
    skills_unmatched: list = dataclasses.field(default_factory=list)
    notes: list = dataclasses.field(default_factory=list)
    refused: list = dataclasses.field(default_factory=list)

    #: slug -> how many cells held a pass but not enough of them, for a
    #: skill whose threshold is above one. Reported rather than left
    #: silent: "not written" is the right action and a surprising one
    #: to read, because the student *has* passed the skill once.
    short: dict = dataclasses.field(default_factory=dict)

    def kept_passes(self):
        """Cells where a pass stands against a non-pass result.

        Never written, and not behind a flag. His rule: a pass already
        in the gradebook is never replaced, because it may have come
        from somewhere printit knows nothing about.
        """
        return [k for k in self.kept if k.why == "a pass is never replaced"]

    def for_sheet(self, name):
        return [c for c in self.changes if c.sheet == name]

    def describe(self):
        lines = [
            f"{len(self.changes)} cell(s) to write, "
            f"{self.already_right} already right, "
            f"{self.not_written} not written",
            f"{self.rows_matched} row(s) matched a student",
        ]
        passes = self.kept_passes()
        if passes:
            lines.append(f"  {len(passes)} cell(s) keep a pass the record "
                         "does not agree with -- never replaced")
        if self.rows_ignored:
            lines.append(f"  {len(self.rows_ignored)} row(s) skipped by an "
                         "ignore rule: "
                         + ", ".join(str(r) for r in self.rows_ignored))
        for note in self.notes:
            lines.append(f"  {note}")
        if self.rows_unmatched:
            lines.append(f"  {len(self.rows_unmatched)} row(s) matched no "
                         "student: "
                         + ", ".join(str(r) for r in self.rows_unmatched))
        if self.students_unmatched:
            lines.append(f"  {len(self.students_unmatched)} student(s) have "
                         "no row in any of these files")
        if self.skills_unmatched:
            lines.append("  no column for: " + " ".join(self.skills_unmatched))
        # Said out loud, because "not written" for a student who has
        # passed the skill once reads as a bug until you remember the
        # skill needs two.
        for slug, n in sorted(self.short.items()):
            lines.append(f"  {slug}: {n} student(s) have a pass but not "
                         f"enough of them yet, so nothing was written")
        for problem in self.refused:
            lines.append(f"  REFUSED  {problem}")
        return "\n".join(lines)


def _core(value):
    """An id with its punctuation and any trailing marker removed.

    A 9-digit student id is written plainly in both the roster and the
    gradebook, but the same normalisation that lets the vault join two
    exports costs nothing and absorbs a stray `#`.
    """
    from .vault import id_core
    return id_core(value)


def ignored_by(row, markers):
    """`(marker, column index)` if any marker appears in this row, else None.

    Every cell, not only the one holding the id being matched on. The
    LMS marks a retired enrolment on whichever identifier it likes --
    Brightspace appends `-DoNotUse` to `OrgDefinedId` -- and a rule that
    only inspected the student column stopped firing when the match
    moved to a different id column, without saying so.

    The column is returned so a caller can report *where* the marker
    was found. A marker matching somewhere unexpected is then visible
    instead of just effective.
    """
    for marker in markers:
        if not marker:
            continue
        for index, cell in enumerate(row):
            if marker in cell:
                return marker, index
    return None


def _filled(row, columns):
    return sum(1 for i in columns if i < len(row) and row[i].strip())


def plan_export(sheets, profile, students, progress, slugs, not_yet=(),
                thresholds=None):
    """Work out every cell to change, across every file. Writes nothing.

    `sheets` is a list of `Sheet`. `students` is a roster; `progress` is
    `record.progress(...)`, keyed by the roster's `sid`. `not_yet` is
    the set of slugs for which a non-pass may be written at all.

    `thresholds` is `{slug: passes needed}` from `course.thresholds`,
    holding only the skills that need more than one. **It has to be
    passed, and it was not.** This branched on `passes` being non-zero,
    so a skill set to need two passes was exported as passed after
    one -- Progress showing it unearned while the gradebook said
    otherwise, with the tool's two halves disagreeing in the direction
    of overstating a grade. No skill in his course needs two today,
    which is why it went unnoticed.

    Returns `(changes, report)`, where `changes` maps
    `(sheet name, row, column)` to a `Change`.

    **A pass** goes in where the cell is empty or holds the non-pass
    value. **A non-pass** goes in only when its slug is named in
    `not_yet` *and* the cell is empty -- writing it raises the student's
    denominator wherever the subtotals count filled cells, so it is a
    deliberate act for the skills in play. **A pass is never replaced.**
    **An absence writes nothing**, being no attempt at the skill. And a
    cell holding anything else **stops the export**, because
    overwriting a value this tool does not understand is guessing.
    """
    report = ExportReport()
    not_yet = set(not_yet)
    changes = {}

    unknown = sorted(s for s in not_yet if s not in slugs)
    if unknown:
        report.refused.append(
            "asked to write a non-pass for " + ", ".join(unknown)
            + ", which the bank does not publish")

    columns, student_columns, skill_columns = {}, {}, {}
    for sheet in sheets:
        found = match(sheet.head, slugs, pairs=profile.pairs)
        columns[sheet.name] = found
        skill_columns[sheet.name] = sorted(found.found.values())
        for slug in found.missing:
            if slug not in report.skills_unmatched:
                report.skills_unmatched.append(slug)
        if profile.student_column not in sheet.head:
            report.refused.append(
                f"{sheet.name} has no column called "
                f"{profile.student_column!r}")
            continue
        student_columns[sheet.name] = sheet.head.index(profile.student_column)
    if report.refused:
        return {}, report

    results = {(r["sid"], r["slug"]): r for r in progress}

    by_key = {}
    for student in students:
        key = _core(getattr(student, profile.student_matches, "") or "")
        if key:
            by_key.setdefault(key, []).append(student)

    #: (file, file's section, roster's section) -> row numbers
    wrong_section = {}

    #: student -> [(sheet, row number, row)]
    rows_for = {}
    for sheet in sheets:
        column = student_columns[sheet.name]
        for number, row in enumerate(sheet.body, 2):
            if not any(c.strip() for c in row):
                continue
            raw = row[column] if column < len(row) else ""
            if not raw.strip():
                report.rows_unmatched.append(f"{sheet.name}:{number}")
                continue
            # Anywhere in the row, not just in the id being matched
            # on. Brightspace puts `-DoNotUse` on the `OrgDefinedId`,
            # and he matches on `OSW_ID` -- so looking only at the
            # student column made the rule stop firing the moment the
            # match moved to the other id, silently.
            found = ignored_by(row, profile.ignore_rows)
            if found:
                marker, where = found
                report.rows_ignored.append(f"{sheet.name}:{number}")
                note = (f"{sheet.name} row {number} skipped: "
                        f"{marker!r} in column {where + 1}")
                if note not in report.notes:
                    report.notes.append(note)
                continue
            matched = by_key.get(_core(raw)) or []
            if len(matched) > 1:
                report.refused.append(
                    f"{sheet.name} row {number}: this id matches "
                    f"{len(matched)} students in the roster. Two roster "
                    "entries share an id; fix that first.")
                continue
            if not matched:
                report.rows_unmatched.append(f"{sheet.name}:{number}")
                continue
            rows_for.setdefault(id(matched[0]), []).append(
                (sheet, number, row))

    for student in students:
        here = rows_for.get(id(student)) or []
        if not here:
            continue

        files = {sheet.name for sheet, _, _ in here}
        if len(files) > 1:
            # His check. A student in two sections' exports means one of
            # them is wrong about who is enrolled, and writing to both
            # would record the same result twice.
            # Named by where, not by who: this message is printed,
            # and a report that can carry a student's id is a report
            # that cannot be shown to anybody.
            report.refused.append(
                "one student appears in more than one file, at "
                + "; ".join(f"{sheet.name} row {number}"
                            for sheet, number, _ in sorted(
                                here, key=lambda item: (item[0].name,
                                                        item[1])))
                + ". A student should be in the export for one section "
                "only.")
            continue

        sheet = here[0][0]
        if sheet.section and student.section \
                and sheet.section != student.section:
            # Counted per file and per roster section, not one line
            # per student: forty-two near-identical lines buried the
            # rest of the report when the inference above was wrong.
            wrong_section.setdefault((sheet.name, sheet.section,
                                      student.section), []).append(
                                          here[0][1])

        if len(here) > 1:
            # His rule: update the row with more grades on it. A tie is
            # refused, because there is then nothing to choose by.
            graded = skill_columns[sheet.name]
            ranked = sorted(here, key=lambda item: _filled(item[2], graded),
                            reverse=True)
            if _filled(ranked[0][2], graded) == _filled(ranked[1][2], graded):
                report.refused.append(
                    f"{sheet.name} rows "
                    + ", ".join(str(n) for _, n, _ in here)
                    + " are the same student with the same number of "
                    "grades, so there is nothing to choose between them. "
                    "Add an ignore rule for the one that is not live.")
                continue
            report.notes.append(
                f"{sheet.name} rows "
                + ", ".join(str(n) for _, n, _ in here)
                + f" are one student; writing to row {ranked[0][1]} "
                f"({_filled(ranked[0][2], graded)} grades) and leaving the "
                "other(s) alone")
            here = [ranked[0]]

        sheet, number, row = here[0]
        report.rows_matched += 1

        for slug, column in sorted(columns[sheet.name].found.items()):
            result = results.get((student.sid, slug))
            if result is None:
                report.not_written += 1
                continue
            was = row[column] if column < len(row) else ""

            if was.strip() and was not in (profile.passed,
                                           profile.not_passed):
                report.refused.append(
                    f"{sheet.name} row {number}, {slug}: the cell holds a "
                    "value this tool does not know, so nothing was planned "
                    "for it")
                continue

            key = (sheet.name, number, column)
            # `>= needed`, not "any pass at all". `thresholds` holds
            # only the exceptions, so a slug absent from it needs one.
            needed = (thresholds or {}).get(slug, 1)
            if needed > 1 and 0 < (result["passes"] or 0) < needed:
                report.short[slug] = report.short.get(slug, 0) + 1
            if (result["passes"] or 0) >= needed:
                if was == profile.passed:
                    report.already_right += 1
                    continue
                changes[key] = Change(
                    sheet=sheet.name, row=number, column=column + 1,
                    slug=slug, was=was, now=profile.passed,
                    why="passed on the record")
                continue

            if not result["last_sat"]:
                report.not_written += 1          # only absences
                continue
            if slug not in not_yet:
                report.not_written += 1
                continue
            if was == profile.passed:
                report.kept.append(Kept(
                    sheet=sheet.name, row=number, column=column + 1,
                    slug=slug, value=was, why="a pass is never replaced"))
                continue
            if was == profile.not_passed:
                report.already_right += 1
                continue
            changes[key] = Change(
                sheet=sheet.name, row=number, column=column + 1, slug=slug,
                was=was, now=profile.not_passed,
                why="not passed, and this skill was named")

    for (name, theirs, ours), numbers in sorted(wrong_section.items()):
        report.notes.append(
            f"{name}: {len(numbers)} row(s) hold students the roster puts "
            f"in section {ours}, while this file looks like section "
            f"{theirs} -- rows "
            + ", ".join(str(n) for n in sorted(numbers)[:10])
            + (" ..." if len(numbers) > 10 else ""))

    report.changes = sorted(changes.values(),
                            key=lambda c: (c.sheet, c.row, c.column))
    # **Ids, and never printed.** `describe` reports the count only,
    # because a student with no row is ordinary when the exports cover
    # one section each, and because a list of ids in a report is the
    # thing this module is otherwise careful never to produce. The
    # count is the useful part; who they are is in the course's own
    # records, where it belongs.
    report.students_unmatched = sorted(
        getattr(s, "sid", "") or s.name for s in students
        if id(s) not in rows_for and not s.dropped)
    return changes, report


def apply_export(sheet, changes):
    """New rows for one sheet, with its changes in. The input is untouched.

    Used for checking and for tests. The file that is actually written
    is produced by `splice`, which does not go through this.
    """
    out = [list(r) for r in sheet.rows]
    for (name, number, column), change in changes.items():
        if name != sheet.name:
            continue
        row = out[number - 1]
        while len(row) <= column:
            row.append("")
        row[column] = change.now
    return out


# ------------------------------------------------- auditing the result --

#: What an audit finding is about. Ordered worst first, which is the
#: order they are reported in.
FINDING_KINDS = (
    # A cell that held a pass and does not any more. The one thing
    # this tool promises never to do.
    "regression",
    # A cell changed that the record does not justify, or changed to a
    # value that is neither the pass nor the non-pass string.
    "unbacked",
    # A cell changed outside any column a skill claims, or in a column
    # the profile says to leave alone.
    "stray",
    # The row count, a row's width, or the header row moved.
    "shape",
    # A column mapped to a slug whose name is nowhere in its header.
    "mismapped",
    # The record says passed and the file does not, with a column and a
    # row that both exist. The inverse check: an export that quietly
    # did nothing passes every other test here.
    "missed",
)


@dataclasses.dataclass
class AuditFinding:
    kind: str
    #: File, row and column. **Never a student.** Same rule as
    #: `ExportReport`: this is printed, and a report that can carry a
    #: name is a report that cannot be shown to anybody.
    where: str
    says: str


@dataclasses.dataclass
class AuditReport:
    findings: list = dataclasses.field(default_factory=list)
    #: Cells compared, cells that differ, and cells that held a pass
    #: before and still do -- the last being the number that answers
    #: "nothing regressed" in the affirmative rather than by silence.
    compared: int = 0
    changed: int = 0
    passes_held: int = 0
    #: Changed cells the record positively accounts for.
    backed: int = 0
    rows_skipped: int = 0
    #: Lines of the file that came through byte for byte. Filled by the
    #: caller from `changed_lines`, because it is a fact about the
    #: bytes and this function is given rows.
    lines_identical: int = 0

    @property
    def ok(self):
        return not self.findings

    def of_kind(self, kind):
        return [f for f in self.findings if f.kind == kind]

    def describe(self):
        lines = [
            f"{self.compared} cell(s) compared, {self.changed} changed, "
            f"{self.backed} of those backed by the record",
            f"{self.passes_held} cell(s) already held a pass and still do",
        ]
        if self.rows_skipped:
            lines.append(f"{self.rows_skipped} row(s) skipped by an ignore "
                         "rule and checked for not having moved")
        if self.ok:
            lines.append("no findings")
            return "\n".join(lines)
        for kind in FINDING_KINDS:
            for finding in self.of_kind(kind):
                lines.append(f"  {kind.upper():11s} {finding.where}: "
                             f"{finding.says}")
        return "\n".join(lines)


def names_a_slug(header, slug):
    """Whether `header` plausibly belongs to `slug`, by a dumb rule.

    Deliberately dumber than `match`. The audit's job is not to work
    the mapping out a second time -- a second heuristic is a second
    thing to be wrong -- but to check the one that was used against a
    rule simple enough to read: the header starts with the slug, and
    the next character is not a letter or a digit, so `N3` does not
    claim `N30`.
    """
    if not header.startswith(slug):
        return False
    rest = header[len(slug):]
    return not rest[:1].isalnum()


def changed_lines(before, after):
    """Which 1-based lines of two files' bytes differ, and how many.

    `(numbers, same_count)`. Bytes, not parsed cells, because that is
    the promise `splice` makes and the one a parsed comparison cannot
    check: a cell whose value is unchanged and whose quoting is not
    reads as identical through `csv.reader` and is a different file as
    far as the LMS is concerned.

    Line endings are kept, so a file that arrived CRLF and left LF
    shows up as every line differing rather than as nothing.
    """
    old = before.decode("utf-8-sig").splitlines(keepends=True)
    new = after.decode("utf-8-sig").splitlines(keepends=True)
    numbers = [n for n, (a, b) in enumerate(zip(old, new), 1) if a != b]
    numbers += list(range(min(len(old), len(new)) + 1,
                          max(len(old), len(new)) + 1))
    return numbers, sum(1 for a, b in zip(old, new) if a == b)


def audit_export(before, after, name, profile, students, progress, slugs,
                 not_yet=(), thresholds=None, columns=None, header_line=1):
    """Check a written file against the record, not against the plan.

    `before` and `after` are the file's rows, header first, as
    `Sheet.rows` holds them. Returns an `AuditReport`.

    **Why this exists when `verify_export` already does.**
    `verify_export` checks that the write did what the plan said. A
    plan that is wrong and a write that is faithful to it come back
    clean, because the plan is both the question and the answer. This
    asks a different question -- does every cell in the file agree
    with what the record says about that student and that skill --
    and it asks it of the bytes that are about to be uploaded.

    **What is genuinely independent of `plan_export`, and what is
    not.** Worth stating plainly, because an audit that quietly shares
    the bug it is looking for is worse than none.

    *Independent.* The headline check -- no cell that held a pass
    holds anything else afterwards -- compares the two files and
    nothing else. It needs no mapping, no roster, no record, and no
    agreement with the planner about anything. So do the shape checks
    and the check that nothing changed outside a skill's column.

    *Shared.* Joining a row to a student uses the same `_core`
    normalisation and the same `ignored_by` rule, and resolving a
    column to a slug uses the mapping the planner arrived at. Writing
    a second normaliser would invent disagreements rather than find
    them. The mapping is *checked* instead of recomputed, by
    `names_a_slug`, which is strict where `match` is clever.

    So: a planner that writes to the wrong cell, overwrites a pass,
    invents a result, or silently writes nothing is caught here. A
    roster whose ids are wrong in the same way in both places is not.
    """
    report = AuditReport()
    thresholds = thresholds or {}
    not_yet = set(not_yet)
    passed, not_passed = profile.passed, profile.not_passed

    # ---- shape, before anything is read cell by cell -----------------
    if header_line != 1:
        # Everything below indexes rows from `before[0]` being the
        # header, which is also what `Sheet.head` and `plan_export`
        # assume. Rather than audit the wrong rows quietly, say so: a
        # file with a preamble would otherwise come back clean having
        # compared a student's row against a title line.
        report.findings.append(AuditFinding(
            "shape", name,
            f"the header is on line {header_line} and this audit can only "
            "read a file whose first line is the header"))
        return report
    if len(before) != len(after):
        report.findings.append(AuditFinding(
            "shape", name,
            f"the row count changed, {len(before)} -> {len(after)}"))
        return report
    if not before:
        return report
    if before[0] != after[0]:
        report.findings.append(AuditFinding(
            "shape", f"{name} row 1", "the header row was written to"))
        return report

    head = after[0]

    # ---- which column is which skill, and is that defensible ---------
    if columns is None:
        found = match(head, slugs, pairs=profile.pairs)
        columns = dict(found.found)
    slug_at = {column: slug for slug, column in columns.items()}
    for slug, column in sorted(columns.items()):
        if column >= len(head):
            report.findings.append(AuditFinding(
                "mismapped", f"{name} column {column + 1}",
                f"mapped to {slug} and the header row has no such column"))
            continue
        header = head[column]
        if names_a_slug(header, slug):
            continue
        if profile.pairs.get(slug) == header:
            continue        # named by hand in the profile, which is the
            #                 point of `pairs`: a column whose header
            #                 does not carry its slug at all.
        report.findings.append(AuditFinding(
            "mismapped", f"{name} column {column + 1}",
            f"mapped to {slug}, but its header does not begin with it "
            f"and the profile does not pair them: {header!r}"))
    for header in profile.ignore_columns:
        if header in head and head.index(header) in slug_at:
            report.findings.append(AuditFinding(
                "mismapped", f"{name} column {head.index(header) + 1}",
                f"the profile says to leave {header!r} alone and a skill "
                f"claims it"))

    # ---- the record, and who each row is -----------------------------
    results = {(r["sid"], r["slug"]): r for r in progress}
    by_key = {}
    for student in students:
        key = _core(getattr(student, profile.student_matches, "") or "")
        if key:
            by_key.setdefault(key, []).append(student)
    student_at = (head.index(profile.student_column)
                  if profile.student_column in head else None)
    if student_at is None:
        report.findings.append(AuditFinding(
            "shape", name,
            f"no column called {profile.student_column!r}"))
        return report

    def whose(row):
        """The one student this row belongs to, or None."""
        raw = row[student_at] if student_at < len(row) else ""
        if not raw.strip():
            return None
        found = by_key.get(_core(raw)) or []
        return found[0] if len(found) == 1 else None

    #: (sid, slug) -> [(row number, column)], so the coverage pass can
    #: tell "this skill has no column" from "this cell was left
    #: behind". A list and not one entry because a student can hold two
    #: rows -- a retired enrolment beside a live one -- and
    #: `plan_export` deliberately writes to only one of them. The pass
    #: being in *any* of their rows is what matters; demanding it in
    #: the one this loop happened to see last would invent a finding.
    reachable = {}

    for index in range(1, len(after)):
        old, new = before[index], after[index]
        number = index + 1
        if len(old) != len(new):
            report.findings.append(AuditFinding(
                "shape", f"{name} row {number}",
                f"the row's width changed, {len(old)} -> {len(new)}"))
            continue

        skipped = bool(ignored_by(new, profile.ignore_rows))
        if skipped:
            report.rows_skipped += 1
        student = None if skipped else whose(new)
        if student is not None:
            for slug, column in columns.items():
                reachable.setdefault((student.sid, slug), []).append(
                    (number, column))

        for column, (a, b) in enumerate(zip(old, new)):
            report.compared += 1
            if a == b:
                if a == passed:
                    report.passes_held += 1
                continue
            report.changed += 1
            at = f"{name} row {number}, column {column + 1}"

            # 1. The promise. No mapping, no roster, no record: if it
            #    said pass and no longer does, that is the finding, and
            #    nothing about why it happened makes it not one.
            if a == passed:
                report.findings.append(AuditFinding(
                    "regression", at,
                    f"held {passed!r} and now holds {b!r} -- a pass is "
                    "never replaced"))
                continue

            # 2. Changed where nothing should be written at all.
            if skipped:
                report.findings.append(AuditFinding(
                    "stray", at,
                    "this row is skipped by an ignore rule and was "
                    f"written to anyway: {a!r} -> {b!r}"))
                continue
            slug = slug_at.get(column)
            if slug is None:
                # **No cell contents here.** Every other finding quotes
                # a skill column, whose values are the two mark
                # strings. This one is about a column no skill claims,
                # and those are the id, the email and the name -- so
                # the first version of this printed a student's
                # OrgDefinedId into a report that goes on screen and
                # into a log. The header says which column it was,
                # which is the part that identifies the bug; who the
                # row belongs to is in the course's own records.
                which = (f"{head[column]!r}" if column < len(head)
                         else "past the end of the header row")
                report.findings.append(AuditFinding(
                    "stray", at,
                    f"no skill claims this column ({which}) and its value "
                    "changed"))
                continue
            if b not in (passed, not_passed):
                report.findings.append(AuditFinding(
                    "unbacked", at,
                    f"written as {b!r}, which is neither the pass nor the "
                    "non-pass value"))
                continue

            # 3. Does the record say so.
            if student is None:
                report.findings.append(AuditFinding(
                    "unbacked", at,
                    "changed, and this row joins to no single student in "
                    "the roster"))
                continue
            result = results.get((student.sid, slug))
            if result is None:
                report.findings.append(AuditFinding(
                    "unbacked", at,
                    f"written as {b!r} for {slug}, and the record holds no "
                    "attempt at that skill for this row's student"))
                continue
            needed = thresholds.get(slug, 1)
            got = result["passes"] or 0
            if b == passed and got < needed:
                report.findings.append(AuditFinding(
                    "unbacked", at,
                    f"written as a pass for {slug} on {got} pass(es), "
                    f"where {needed} are needed"))
                continue
            if b == not_passed:
                if got >= needed:
                    report.findings.append(AuditFinding(
                        "unbacked", at,
                        f"written as a non-pass for {slug}, and the record "
                        f"has {got} pass(es) of the {needed} needed"))
                    continue
                if not result["last_sat"]:
                    report.findings.append(AuditFinding(
                        "unbacked", at,
                        f"written as a non-pass for {slug}, and the record "
                        "has no sitting of it -- only absences"))
                    continue
                if slug not in not_yet:
                    report.findings.append(AuditFinding(
                        "unbacked", at,
                        f"written as a non-pass for {slug}, which was not "
                        "among the skills a non-pass was asked for"))
                    continue
            report.backed += 1

    # ---- the inverse: a pass on the record that is not in the file ----
    #
    # Every other check here would pass a file that was never written
    # to at all. This is the one that notices.
    for (sid, slug), places in sorted(reachable.items()):
        result = results.get((sid, slug))
        if result is None:
            continue
        if (result["passes"] or 0) < thresholds.get(slug, 1):
            continue
        held = []
        for number, column in places:
            row = after[number - 1]
            held.append((number, column,
                         row[column] if column < len(row) else ""))
        if any(now == passed for _, _, now in held):
            continue
        # A value the tool does not understand. `plan_export` refuses
        # rather than overwriting one, so finding it here is the
        # expected outcome and not a fault.
        if any(now.strip() and now != not_passed for _, _, now in held):
            continue
        number, column, now = held[0]
        report.findings.append(AuditFinding(
            "missed", f"{name} row {number}, column {column + 1}",
            f"the record has {slug} passed for this row's student and the "
            f"file holds {now!r}"))
    return report


def verify_export(before, after, changes, sheet_name):
    """Check that exactly the planned cells of one sheet differ.

    The post-condition. A plan that is right and a write that is wrong
    look identical from the plan's side; his own script does this with
    a second independent planner, and this is the cheaper half of the
    same idea.
    """
    problems = []
    if len(before) != len(after):
        return [f"{sheet_name}: the row count changed, {len(before)} -> "
                f"{len(after)}"]
    planned = {(number, column)
               for (name, number, column) in changes if name == sheet_name}
    for index, (old, new) in enumerate(zip(before, after)):
        if len(old) != len(new):
            problems.append(f"{sheet_name} row {index + 1} changed width")
            continue
        for column, (a, b) in enumerate(zip(old, new)):
            if a == b:
                continue
            if index == 0:
                problems.append(f"{sheet_name}: the header row was written "
                                "to")
            elif (index + 1, column) not in planned:
                problems.append(
                    f"{sheet_name} row {index + 1}, column {column + 1} "
                    "changed and was not in the plan")
    for number, column in planned:
        want = changes[(sheet_name, number, column)].now
        if after[number - 1][column] != want:
            problems.append(
                f"{sheet_name} row {number}, column {column + 1} was "
                "planned and did not change")
    return problems


def fields_of(line):
    """`[(value, start, end)]` for one CSV line, with source spans.

    The value is what the field *means*, with its surrounding quotes
    removed and any doubled quote inside it halved. `start` and `end`
    bracket the field's own characters in `line`, quotes included --
    so a caller can replace one field's text and copy every other byte
    of the line exactly as it arrived.

    That is the whole point. `line.split(",")` cannot do it, because a
    quoted field may hold a comma; a CSV writer cannot either, because
    re-serialising normalises quoting and a field the LMS quoted
    unnecessarily would come back bare. Spans give both: real parsing,
    and untouched text preserved to the byte.

    Unterminated quotes raise, rather than being guessed at: a line
    that does not parse is a line nobody should be editing.
    """
    spans, at, n = [], 0, len(line)
    while True:
        start = at
        if at < n and line[at] == '"':
            at += 1
            chunk = []
            while True:
                if at >= n:
                    raise GradebookError(
                        "a quoted field is never closed, so this line "
                        "cannot be read as CSV")
                if line[at] == '"':
                    # A doubled quote is one literal quote; a single one
                    # ends the field.
                    if at + 1 < n and line[at + 1] == '"':
                        chunk.append('"')
                        at += 2
                        continue
                    at += 1
                    break
                chunk.append(line[at])
                at += 1
            value = "".join(chunk)
        else:
            while at < n and line[at] != ",":
                at += 1
            value = line[start:at]
        spans.append((value, start, at))
        if at < n and line[at] == ",":
            at += 1
            continue
        break
    return spans


def as_field(value):
    """`value` as CSV text, quoted only if it has to be.

    Minimal quoting on purpose: a mark written into a bare cell should
    stay bare, so the only lines that gain quotes are the ones whose
    content requires them.
    """
    text = "" if value is None else str(value)
    if any(ch in text for ch in ',"\r\n'):
        return '"' + text.replace('"', '""') + '"'
    return text


def splice(path, changes, sheet_name, header_line=1):
    """The bytes to write for one file: changed lines edited, rest copied.

    **Untouched lines are copied byte for byte, and so is every
    untouched field of an edited line.** Re-serialising through a CSV
    writer normalises quoting, so a cell the LMS quoted unnecessarily
    would come back bare and the file would no longer be the file that
    was downloaded -- which is the whole promise of a round-trip.

    This used to refuse any line containing a quote character, because
    it split on commas and that is wrong for a quoted field. The
    refusal was honest but it ruled out most of the world: **every data
    row of a Canvas export is quoted**, because every one holds
    `"Last, First"`. His own Brightspace export escapes it only by
    having no name column at all. So the line is parsed properly now,
    by `fields_of`, and only the changed field's own span is replaced.
    """
    with open(path, "rb") as f:
        raw = f.read()
    bom = raw.startswith(b"\xef\xbb\xbf")
    lines = raw.decode("utf-8-sig").splitlines(keepends=True)

    by_row = {}
    for (name, number, column), change in changes.items():
        if name == sheet_name:
            by_row.setdefault(number, []).append(change)

    out = []
    for index, line in enumerate(lines, 1):
        row_number = index - header_line + 1
        if row_number not in by_row:
            out.append(line)
            continue
        body = line.rstrip("\r\n")
        ending = line[len(body):]
        try:
            spans = fields_of(body)
        except GradebookError as exc:
            raise GradebookError(
                f"{path}, line {index}: {exc}. Nothing was written.")

        # Right to left, so replacing one field cannot move the spans
        # of the ones still to be replaced.
        edits = sorted(by_row[row_number],
                       key=lambda c: c.column, reverse=True)
        for change in edits:
            position = change.column - 1
            if position >= len(spans):
                # A short row, which a trailing empty cell produces.
                # Commas are appended to reach the column rather than
                # the row being rewritten, so everything already on the
                # line keeps its own text.
                body += "," * (position - len(spans) + 1)
                spans = fields_of(body)
            value, start, end = spans[position]
            if value != change.was:
                raise GradebookError(
                    f"{path}, line {index}: the cell this was planned "
                    "against has changed. Export again and re-run.")
            body = body[:start] + as_field(change.now) + body[end:]
            spans = fields_of(body)
        out.append(body + ending)

    text = "".join(out)
    return (b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8")


# --------------------------------------------- does a blank cell count? --

def category_of(header):
    """The category an exporter wrote into a column name, or "".

    Brightspace writes `... MaxPoints:1 Category:Core Skills Progress>`.
    Reading it is worth the specificity, because a subtotal column
    usually covers one category rather than every skill, and without
    that grouping the arithmetic below cannot be checked at all.
    """
    found = re.search(r"Category:\s*([^<>]+)", str(header))
    return found.group(1).strip() if found else ""


def _numeric(value):
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def blank_evidence(rows, headers, skill_columns, passed):
    """Whether a blank cell is counted, judged from the file itself.

    Returns `(meaning, evidence)`. `evidence` is empty when the file
    does not settle it, and the meaning is then the cautious default.

    The method: group the skill columns by the category their headers
    declare, then look for a numeric column that equals, in every row,
    the number of **filled** cells in that group. If one exists, the
    gradebook is counting attempts rather than skills -- so a blank is
    "not attempted", and writing a non-pass into one would raise that
    student's denominator and lower their grade.

    Checked rather than configured, because it is the most destructive
    thing the export could get wrong and because the file knows the
    answer. A column that equals the number of *passes* instead is
    rejected: that is a numerator, and it says nothing about blanks.
    """
    groups = {}
    for index in skill_columns:
        groups.setdefault(category_of(headers[index]), []).append(index)

    for category, columns in sorted(groups.items()):
        if len(columns) < 2:
            continue
        for candidate in range(len(headers)):
            if candidate in skill_columns:
                continue
            checked = agree_filled = agree_passes = 0
            for row in rows:
                if candidate >= len(row):
                    continue
                value = _numeric(row[candidate])
                if value is None:
                    continue
                checked += 1
                filled = sum(1 for i in columns
                             if i < len(row) and row[i].strip())
                passes = sum(1 for i in columns
                             if i < len(row) and row[i] == passed)
                agree_filled += value == filled
                agree_passes += value == passes
            if checked >= 2 and agree_filled == checked \
                    and agree_passes != checked:
                return "not attempted", (
                    f"column {candidate + 1}, "
                    f"{headers[candidate][:44]!r}, equals the number of "
                    f"filled cells among the {len(columns)} "
                    f"{category or 'skill'} columns in all {checked} rows")
    return "not attempted", ""


# ------------------------------------------------------- shared base ids --

def shared_base_ids(rows, column):
    """Rows whose student id differs only by a trailing marker.

    Returns `{base: [(row number, full id), ...]}` for bases with more
    than one row. On the real export this finds one pair: a live row and
    the same id with `-DoNotUse` after it, which is a retired enrolment
    **with six marks and its own subtotals in it**.

    Reported rather than acted on. Which of the two is live is the
    instructor's call, and the answer becomes an `ignore` rule.
    """
    groups = {}
    for number, row in enumerate(rows, 2):
        if column >= len(row):
            continue
        value = row[column].strip()
        if not value:
            continue
        base = re.sub(r"(?<=\d)\D+$", "", value)
        groups.setdefault(base, []).append((number, value))
    return {base: rows_ for base, rows_ in groups.items() if len(rows_) > 1}
