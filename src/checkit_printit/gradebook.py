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
        if self.student_matches not in ("alt_id", "sid", "handle", "email"):
            problems.append(
                f"`matches` is {self.student_matches!r}; expected alt_id, "
                "sid, handle or email")
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
# What export is: **take the file the instructor exported, fill in the
# cells there is a recorded result for, change nothing else, hand it
# back.** Not "generate a CSV". Nothing here adds or removes a row, and
# nothing writes to a column no skill in the bank claims.


@dataclasses.dataclass
class Change:
    """One cell that would change. Row and column are 1-based."""
    row: int
    column: int
    slug: str
    was: str
    now: str

    @property
    def downgrade(self):
        """Whether this replaces a pass with something that is not one.

        Counted apart and refused by default. A pass already in the
        gradebook may have come from somewhere printit knows nothing
        about -- a skill passed before printit was used, or outside it
        -- and overwriting it is the one genuinely destructive thing
        this export can do.
        """
        return bool(self.was.strip()) and self.was != self.now \
            and self._was_a_pass

    _was_a_pass: bool = False


@dataclasses.dataclass
class ExportReport:
    changes: list = dataclasses.field(default_factory=list)
    downgrades: list = dataclasses.field(default_factory=list)
    already_right: int = 0
    no_result: int = 0
    rows_matched: int = 0
    rows_ignored: list = dataclasses.field(default_factory=list)
    rows_unmatched: list = dataclasses.field(default_factory=list)
    students_unmatched: list = dataclasses.field(default_factory=list)
    skills_unmatched: list = dataclasses.field(default_factory=list)
    refused: list = dataclasses.field(default_factory=list)

    def describe(self):
        lines = [
            f"{len(self.changes)} cell(s) to fill in, "
            f"{self.already_right} already right, "
            f"{self.no_result} left alone for want of a result",
            f"{self.rows_matched} row(s) matched a student",
        ]
        if self.rows_ignored:
            lines.append(f"  {len(self.rows_ignored)} row(s) skipped by an "
                         "ignore rule: " + ", ".join(
                             str(r) for r in self.rows_ignored))
        if self.rows_unmatched:
            lines.append(f"  {len(self.rows_unmatched)} row(s) matched no "
                         "student in the roster: " + ", ".join(
                             str(r) for r in self.rows_unmatched))
        if self.students_unmatched:
            lines.append(f"  {len(self.students_unmatched)} student(s) have "
                         "no row in the gradebook")
        if self.skills_unmatched:
            lines.append("  no column for: " + " ".join(self.skills_unmatched))
        if self.downgrades:
            lines.append(f"  {len(self.downgrades)} cell(s) would replace a "
                         "pass with a non-pass -- refused unless allowed")
        for problem in self.refused:
            lines.append(f"  REFUSED  {problem}")
        return "\n".join(lines)


def _core(value):
    """An id with its punctuation and any trailing marker removed.

    The gradebook writes `#2041000001` and a roster imported from a
    class list holds `2041000001`. The same normalisation the vault uses
    to join two exports about one student.
    """
    from .vault import id_core
    return id_core(value)


def plan_export(rows, profile, students, progress, slugs):
    """Work out every cell to change. Writes nothing.

    `students` is a roster; `progress` is `record.progress(...)`, whose
    rows are keyed by the roster's `sid`. Returns
    `(changes_by_position, ExportReport)`.

    Three rules decide a cell:

    * **ever passed** -> the profile's `passed` string;
    * **attempted and not passed** -> its `not_passed` string;
    * **never attempted, or only absent** -> left exactly as found.

    The third is the one that matters. An absence is not an attempt at
    the skill, and on a gradebook whose subtotals count filled cells,
    writing a non-pass into that student's blank would raise their
    denominator for a paper they never sat.
    """
    report = ExportReport()
    head, body = rows[0], rows[1:]
    columns = match(head, slugs, pairs=profile.pairs)
    report.skills_unmatched = list(columns.missing)

    if profile.student_column not in head:
        report.refused.append(
            f"the file has no column called {profile.student_column!r}")
        return {}, report
    student_column = head.index(profile.student_column)

    #: (sid, slug) -> the progress row
    results = {(r["sid"], r["slug"]): r for r in progress}

    by_key = {}
    for student in students:
        key = _core(getattr(student, profile.student_matches, "") or "")
        if key:
            by_key.setdefault(key, []).append(student)

    seen_students = set()
    changes = {}
    for number, row in enumerate(body, 2):
        if not any(c.strip() for c in row):
            continue
        raw = row[student_column] if student_column < len(row) else ""
        if not raw.strip():
            report.rows_unmatched.append(number)
            continue
        if any(marker and marker in raw for marker in profile.ignore_rows):
            report.rows_ignored.append(number)
            continue

        matched = by_key.get(_core(raw)) or []
        if len(matched) > 1:
            report.refused.append(
                f"row {number}'s id matches {len(matched)} students in the "
                "roster. Two roster entries share an id; fix that first.")
            continue
        if not matched:
            report.rows_unmatched.append(number)
            continue

        student = matched[0]
        if id(student) in seen_students:
            report.refused.append(
                f"row {number} is a second row for a student already matched "
                "on an earlier row. Add an ignore rule for the one that is "
                "not live, or nothing will be written for them.")
            continue
        seen_students.add(id(student))
        report.rows_matched += 1

        for slug, column in sorted(columns.found.items()):
            result = results.get((student.sid, slug))
            if result is None:
                report.no_result += 1
                continue
            if result["passes"]:
                want = profile.passed
            elif result["last_sat"]:
                want = profile.not_passed
            else:
                # Only absences. Not an attempt at the skill.
                report.no_result += 1
                continue

            was = row[column] if column < len(row) else ""
            if was == want:
                report.already_right += 1
                continue
            change = Change(row=number, column=column + 1, slug=slug,
                            was=was, now=want,
                            _was_a_pass=was == profile.passed)
            if change.downgrade:
                report.downgrades.append(change)
            else:
                report.changes.append(change)
            changes[(number, column)] = change

    report.students_unmatched = sorted(
        getattr(s, "sid", "") or s.name for s in students
        if id(s) not in seen_students and not s.dropped)
    return changes, report


def apply_export(rows, changes, allow_downgrades=False):
    """Return new rows with the changes in. The input is left alone."""
    out = [list(r) for r in rows]
    written = 0
    for (number, column), change in changes.items():
        if change.downgrade and not allow_downgrades:
            continue
        row = out[number - 1]
        while len(row) <= column:
            row.append("")
        row[column] = change.now
        written += 1
    return out, written


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
