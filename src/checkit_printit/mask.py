"""Make a masked twin of a tabular file, and check that it is one.

`vault.py` decides what a given student's pseudonym is. This module
decides *which cells are a student at all*, which is the part that can
be got wrong without anybody noticing.

## Nothing is assumed safe

A grades export from a real course has sixty columns, and the tool has
never seen most of them. The tempting rule is a list of column names
that are known to be dangerous, with everything else passed through.
That rule fails in the one direction that matters: a column nobody
thought of carries real data straight out.

So the rule is the other way round. A column is **masked** when it is
recognised as a person, **kept** when it is positively shown to be
harmless, and otherwise **blanked** -- the header stays, the column
stays, every cell in it is emptied. Blanking rather than dropping keeps
the file's shape, which is what makes the twin usable for working out a
round-trip; and it fails closed, because an unrecognised column cannot
leak an empty string.

`keep=` promotes a column to pass-through once a human has looked at it.
There is no option that promotes one without being named.

## How a column is shown to be harmless

In order, and the order matters:

1. **A known label.** `Email`, `OrgDefinedId`, `Last Name` and their
   synonyms, from the table `classlist.py` already keeps. These are
   masked, not kept.
2. **Anything holding an address** -- a cell with an `@` in it -- is
   masked as an address whatever its header says.
3. **Anything holding a run of five or more digits** is treated as a
   possible id and **blanked** unless a label already claimed it. This
   test runs *before* the numeric test below, which is the whole reason
   a 9-digit student number in an unlabelled column does not sail
   through as "just a number".
4. **All values numeric** -- a points or percentage column. Kept.
5. **Few distinct values, all short** (at most twelve distinct, each at
   most 24 characters). A grade vocabulary has a handful of values;
   `🏆Pass` and `💭Not Yet` is two. A free-text comment column has
   roughly one value per student and fails this. **Low cardinality is
   the test**, because it is the one that separates a category from
   prose.
6. Anything else is blanked.

Rule 5 is the one with a real hole in it: a comment column in a class of
eight where three students got the same comment would pass. The output
scan below is what stands behind it.

## Headers are kept verbatim

A column name is authored by the LMS or the instructor, not by a
student, and the names are the entire point of the exercise -- `<slug>
Grade Symbol <Selectbox MaxPoints:1 ...>` is what a profile has to be
written against. Canvas puts a numeric assignment id in the header, so
header text is deliberately exempt from rule 3.

The one real risk is an instructor who named a column after a student.
That is checked for: any header containing a name already in the vault
is reported.

## The output is checked, not trusted

After writing the twin, it is read back and searched for every real
string the vault knows. If one survives, **the twin is deleted** and the
call fails. A masker believed to be correct is not the standard; a
masker whose output has been searched is.

The failure message carries counts and column numbers only, never the
values that leaked -- the point of the exercise is that those values do
not go anywhere, and a terminal is somewhere.
"""

import csv
import dataclasses
import os
import re

from .classlist import SYNONYMS, read_rows
from .vault import ID_KINDS, Vault, VaultError


class MaskError(Exception):
    pass


#: Identity columns the roster importer has no use for and so does not
#: list, which a masker must still recognise.
#:
#: `username` is also one of `classlist.SYNONYMS["alt_id"]`, which is
#: fine: whichever group claims the column, it is masked. What must not
#: happen is neither claiming it -- an LMS class list carries
#: `OrgDefinedId` *and* `Username`, the first takes the `alt_id` slot,
#: and the second then fell through to the content rules, read as free
#: text, and was blanked. Safe, but it threw away a real identifier and
#: with it any question about joining on one.
EXTRA_SYNONYMS = {
    "handle": ["username", "user name", "login", "login id", "logon",
               "net id", "netid", "user", "account", "account name"],
}

#: Every synonym group this module looks for. Order decides who claims a
#: column when two groups could: the class list's groups run first, so
#: nothing the roster importer relies on changes.
ALL_SYNONYMS = dict(SYNONYMS, **EXTRA_SYNONYMS)

#: Which synonym groups name a person, and the vault kind for each.
PII = {"sid": "sid", "alt_id": "alt_id", "handle": "handle", "last": "last",
       "first": "first", "middle": "middle", "full": "full",
       "email": "email"}

#: Which synonym groups are about enrolment rather than identity, and are
#: therefore kept. A section number and a role are shared by many
#: students and are needed by everything downstream.
SAFE_LABELS = ("section", "role")

#: At most this many distinct values for a column to read as a category
#: rather than as prose.
MAX_DISTINCT = 12

#: And no value longer than this.
MAX_LENGTH = 24

#: A run of this many digits is treated as possibly an id.
ID_DIGITS = 5

EMAILISH = re.compile(r"[^@\s]+@[^@\s]+")
LONG_DIGITS = re.compile(r"\d{%d,}" % ID_DIGITS)


def _looks_numeric(value):
    try:
        float(value.replace(",", "").rstrip("%"))
    except ValueError:
        return False
    return True


# ------------------------------------------------------------- the header --

def find_header(rows, given=None):
    """Which row holds the column names. Returns a 0-based index.

    `classlist.find_mapping` is tried first and is better when it works,
    because it scores every row. But it requires a column naming a
    student, and **a grades export has no name column at all** -- that
    is the first thing §14.6 records about the real file. So it cannot
    be the only answer.

    The fallback is the first row with at least two non-blank cells and
    nothing in it that looks like data: no address, and no long run of
    digits. A header of labels passes; a row of students does not.

    `given` is 1-based, because that is what a spreadsheet shows.
    """
    if given is not None:
        index = int(given) - 1
        if not 0 <= index < len(rows):
            raise MaskError(
                f"--header-row {given} is outside the file, which has "
                f"{len(rows)} rows."
            )
        return index

    try:
        from .classlist import find_mapping
        return find_mapping(rows).header_row
    except Exception:
        pass

    for index, row in enumerate(rows[:60]):
        cells = [c for c in row if c.strip()]
        if len(cells) < 2:
            continue
        if any(EMAILISH.search(c) or LONG_DIGITS.search(c) for c in cells):
            continue
        if not any(re.search(r"[A-Za-z]", c) for c in cells):
            continue
        return index

    raise MaskError(
        "could not find a header row: no row in the first 60 looked like "
        "column names rather than data. Pass --header-row N (1-based) to "
        "say which it is."
    )


# ---------------------------------------------------------- the decisions --

@dataclasses.dataclass
class Decision:
    """What will happen to one column, and why."""
    index: int
    header: str
    action: str          # "mask", "keep" or "blank"
    kind: str = ""       # a vault kind, when masking
    why: str = ""

    @property
    def column(self):
        """The 1-based number a spreadsheet would show."""
        return self.index + 1


@dataclasses.dataclass
class Plan:
    header_row: int
    decisions: list
    prefix_keep: dict = dataclasses.field(default_factory=dict)
    warnings: list = dataclasses.field(default_factory=list)

    def by_kind(self, kind):
        return [d for d in self.decisions if d.kind == kind]

    def describe(self, width=46):
        """A table of every column and its fate.

        Every column is listed, including the kept ones. A report that
        showed only the exceptions would make "nothing to see here" and
        "I did not look" print identically.
        """
        lines = [f"header row {self.header_row + 1}", ""]
        order = {"mask": 0, "blank": 1, "keep": 2}
        for d in sorted(self.decisions, key=lambda d: (order[d.action],
                                                       d.index)):
            # "..." rather than an ellipsis character: this prints to a
            # Windows console, where U+2026 came out as a replacement
            # box.
            label = d.header if len(d.header) <= width \
                else d.header[:width - 3] + "..."
            tag = d.action if not d.kind else f"{d.action} as {d.kind}"
            lines.append(f"  {d.column:>3}  {label:<{width}}  {tag}"
                         + (f"   -- {d.why}" if d.why else ""))
        counts = {a: sum(1 for d in self.decisions if d.action == a)
                  for a in ("mask", "blank", "keep")}
        lines += ["", f"  {counts['mask']} masked, {counts['blank']} blanked, "
                      f"{counts['keep']} kept"]
        for warning in self.warnings:
            lines.append(f"  ! {warning}")
        return "\n".join(lines)


def _label(cell):
    return re.sub(r"\s+", " ", cell.strip().lower()).strip(" :*")


def _labelled(header_cells):
    """field -> column index, from the synonym table. First match wins."""
    labels = [_label(c) for c in header_cells]
    columns, used = {}, set()
    for field, options in ALL_SYNONYMS.items():
        for option in options:
            if option in labels:
                index = labels.index(option)
                if index in used:
                    continue
                columns[field] = index
                used.add(index)
                break
    return columns


def classify(values):
    """(action, why) for a column, from its contents alone.

    Called only for a column no label claimed. See the module docstring
    for the order of the tests and why rule 3 comes before rule 4.
    """
    filled = [v for v in values if v.strip()]
    if not filled:
        return "keep", "empty"
    if any(EMAILISH.search(v) for v in filled):
        return "mask", "holds an address"
    if any(LONG_DIGITS.search(v) for v in filled):
        return "blank", f"a run of {ID_DIGITS}+ digits: possibly an id"
    if all(_looks_numeric(v) for v in filled):
        return "keep", "all numeric"
    distinct = {v.strip() for v in filled}
    if (len(distinct) <= MAX_DISTINCT
            and max(len(v.strip()) for v in filled) <= MAX_LENGTH):
        return "keep", (f"{len(distinct)} distinct short value"
                        + ("" if len(distinct) == 1 else "s"))
    return "blank", (f"{len(distinct)} distinct values in {len(filled)} rows: "
                     "reads as free text")


def common_prefix(values, min_rows=5):
    """How many leading alphanumerics every value shares.

    A prefix every row carries -- an institution's `806` -- cannot
    distinguish one student from another, so carrying it into the twin
    leaks nothing and keeps ids realistic. A prefix *some* rows share is
    a different thing and is not used.

    Two guards, because a shared prefix can be a coincidence:
    `min_rows` values are required before any is trusted, and at most
    half of the shortest value is ever kept.
    """
    filled = [re.sub(r"[^0-9A-Za-z]", "", v) for v in values if v.strip()]
    filled = [v for v in filled if v]
    if len(filled) < min_rows:
        return 0
    first = filled[0]
    shared = len(first)
    for value in filled[1:]:
        shared = min(shared, len(os.path.commonprefix([first, value])))
        if not shared:
            return 0
    return min(shared, min(len(v) for v in filled) // 2)


def plan(rows, header_row=None, keep=(), mask_as=None, vault=None):
    """Decide what happens to every column. Reads nothing, writes nothing.

    Separate from `apply` so that the decisions can be printed and
    argued with before any file is written. `vault columns` is exactly
    this and nothing else.
    """
    index = find_header(rows, header_row)
    header = rows[index]
    body = rows[index + 1:]
    width = max([len(header)] + [len(r) for r in body] or [0])
    keep_lower = {_label(k) for k in keep}
    forced = {int(c) - 1: k for c, k in (mask_as or {}).items()}

    labelled = _labelled(header)
    owner = {col: field for field, col in labelled.items()}

    decisions, prefixes, warnings = [], {}, []
    for col in range(width):
        label = header[col] if col < len(header) else ""
        values = [r[col] if col < len(r) else "" for r in body]

        if col in forced:
            kind = forced[col]
            if kind not in PII.values():
                raise MaskError(
                    f"--mask-as {col + 1}={kind}: {kind!r} is not a kind. "
                    f"Expected one of {', '.join(sorted(set(PII.values())))}."
                )
            decisions.append(Decision(col, label, "mask", kind,
                                      "named on the command line"))
            if kind in ID_KINDS:
                prefixes[kind] = common_prefix(values)
            continue

        if _label(label) in keep_lower:
            decisions.append(Decision(col, label, "keep",
                                      why="named by --keep"))
            continue

        field = owner.get(col)
        if field in PII:
            kind = PII[field]
            decisions.append(Decision(col, label, "mask", kind,
                                      f"header reads as {field}"))
            if kind in ID_KINDS:
                prefixes[kind] = common_prefix(values)
            continue
        if field in SAFE_LABELS:
            decisions.append(Decision(col, label, "keep",
                                      why=f"header reads as {field}"))
            continue

        action, why = classify(values)
        kind = "email" if action == "mask" else ""
        decisions.append(Decision(col, label, action, kind, why))

    if vault is not None:
        warnings += _header_warnings(header, vault)
    return Plan(header_row=index, decisions=decisions, prefix_keep=prefixes,
                warnings=warnings)


def _header_warnings(header, vault):
    """Headers that contain a name the vault already knows.

    Cheap, and it catches the one real way a header can be personal: an
    instructor who named a column after a student. Reported by column
    number, never by quoting the header back -- the header is the thing
    that would carry the name.
    """
    out = []
    reals = {v.lower() for v in vault.real_values(min_length=4)}
    for col, cell in enumerate(header, 1):
        low = cell.lower()
        if any(real in low for real in reals):
            out.append(f"column {col}'s header contains a value the vault "
                       "knows as real. It was NOT masked, because headers "
                       "never are. Rename it in the file, or --drop it.")
    return out


# --------------------------------------------------------------- applying --

@dataclasses.dataclass
class Report:
    plan: Plan
    rows_written: int
    people_seen: int
    people_new: int
    out_path: str = ""

    def describe(self):
        return (f"{self.rows_written} rows, {self.people_seen} students "
                f"({self.people_new} new to the vault)")


def apply(rows, the_plan, vault, limit=None):
    """Rewrite the rows. Returns `(rows, people_seen, people_new)`.

    The vault is mutated: a student seen for the first time is added to
    it. The caller saves it -- deliberately, so that a masking run that
    fails its output check does not leave a vault describing a twin that
    was deleted.
    """
    vault.prefix_keep = dict(the_plan.prefix_keep)
    header = rows[the_plan.header_row]
    body = rows[the_plan.header_row + 1:]
    if limit is not None:
        body = body[:limit]

    masked = {d.index: d for d in the_plan.decisions if d.action == "mask"}
    blanked = {d.index for d in the_plan.decisions if d.action == "blank"}
    out = [list(rows[r]) for r in range(the_plan.header_row + 1)]

    seen, new = set(), 0
    for row in body:
        row = list(row)
        if not any(c.strip() for c in row):
            out.append(row)
            continue

        fields = {}
        for col, decision in masked.items():
            value = row[col].strip() if col < len(row) else ""
            if not value:
                continue
            if decision.kind == "email":
                fields.setdefault("emails", []).append(value)
            else:
                fields[decision.kind] = value

        if not any(fields.get(k) for k in
                   ID_KINDS + ("emails", "full", "last", "first")):
            # Nothing identifying in it. A totals row, or a spacer.
            for col in blanked:
                if col < len(row):
                    row[col] = ""
            out.append(row)
            continue

        person, created = vault.resolve(fields)
        if created:
            new += 1
        seen.add(person.tag)

        for col, decision in masked.items():
            if col < len(row) and row[col].strip():
                row[col] = vault.mask(decision.kind, row[col], person)
        for col in blanked:
            if col < len(row):
                row[col] = ""
        out.append(row)

    return out, len(seen), new


def write_csv(path, rows):
    """UTF-8, no BOM, LF endings -- what §14.6 found in the real export.

    The twin is **not** byte-faithful: quoting is normalised by the
    writer, so a cell the LMS quoted unnecessarily comes back bare. That
    is fine for a file meant to be read and reasoned about, and is
    stated here so nobody tries to feed a twin back to an LMS.
    """
    os.makedirs(os.path.dirname(os.path.abspath(path)) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerows(rows)


def mask_file(path, out_path, vault, header_row=None, keep=(), mask_as=None,
              limit=None, min_length=3):
    """Write a masked twin of `path`, then check that it is one.

    Returns a `Report`. Raises `MaskError` -- after **deleting the
    output** -- if any real value the vault knows survives in it.

    The vault is saved by the caller, not here. A vault written before
    the check would describe a file that the check then destroyed.
    """
    rows = read_rows(path)
    if not rows:
        raise MaskError(f"{path} is empty.")
    the_plan = plan(rows, header_row=header_row, keep=keep, mask_as=mask_as,
                    vault=vault)
    out_rows, seen, new = apply(rows, the_plan, vault, limit=limit)
    write_csv(out_path, out_rows)

    with open(out_path, encoding="utf-8") as f:
        written = f.read()
    leaked = vault.leaks(written, min_length=min_length)
    if leaked:
        where = _locate(out_rows, leaked)
        os.remove(out_path)
        raise MaskError(
            f"{len(leaked)} real value(s) survived into the masked file, so "
            f"it was deleted and nothing was handed over.\n"
            f"They are in column(s) {', '.join(str(c) for c in where)}.\n"
            "The values themselves are deliberately not printed. Run "
            "`checkit-printit vault check` on the file to see them, or "
            "re-run with --mask-as <column>=<kind> for those columns."
        )
    return Report(plan=the_plan, rows_written=len(out_rows),
                  people_seen=seen, people_new=new, out_path=out_path)


def _locate(rows, leaked):
    """Which column numbers hold a leaked value. Numbers only, no values."""
    low = [v.lower() for v in leaked]
    found = set()
    for row in rows:
        for col, cell in enumerate(row, 1):
            cell_low = cell.lower()
            if any(v in cell_low for v in low):
                found.add(col)
    return sorted(found)


# ------------------------------------------------------------- unmasking --

def unmask_file(path, out_path, vault):
    """Put the real values back into a file. Returns the replacement count.

    A plain text pass, so it works on whatever came back -- a corrected
    CSV, a profile, a diff, a patch, an answer pasted into a file. The
    count is returned so a caller can refuse a zero: zero reads as
    "nothing needed changing" and almost always means "this vault does
    not describe this file".
    """
    with open(path, encoding="utf-8") as f:
        text = f.read()
    out, hits = vault.unmask_text(text)
    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".",
                exist_ok=True)
    with open(out_path, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    return hits
