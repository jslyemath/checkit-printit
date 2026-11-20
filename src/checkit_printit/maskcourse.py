"""A masked twin of a whole course folder.

`mask.py` masks a file nobody has seen before, so it has to work out
which columns are a person. A course folder is the opposite situation:
**`roster.toml` is an authoritative, structured list of everybody in
it.** So the strategy inverts.

1. **Learn the people properly, once**, from `roster.toml` through
   `roster.load` -- real fields, no guessing, no column sniffing.
2. **Substitute known values everywhere else.** Every other file in the
   folder is rewritten by replacing each real value the vault now knows
   with its pseudonym. A seating chart, a room, a form mapping and the
   record database all name the same people, and none of them has to be
   understood to be masked.
3. **Check every output twice**, because step 2 can only replace what
   step 1 learned.

### The second check is the point

Substitution cannot catch personal data the roster does not contain.
So every written file is also sniffed for anything that still *looks*
personal:

* **An address whose domain is not one of the vault's fake domains.**
  A hard failure. An email pattern is close to unambiguous.
* **A run of nine or more digits that is not a known fake id.** Also a
  failure, but one `--allow-digits` overrides, because a seed or a
  hash can legitimately contain such a run and only the person holding
  the folder can tell. Locations are reported, never values.

If either check fails, **the whole output directory is removed.** A
half-masked course folder is worse than none, because it looks like a
twin.

### Two folders are never copied, and that is not configurable

* **`secrets/`** holds credentials. Nothing masks a credential; the
  only safe handling is not to copy it.
* **`scans/`** holds the scanned PDFs of student papers -- images of
  handwriting, with names written on them. No text substitution
  touches an image, and there is no version of this tool that should
  pretend otherwise.

An unrecognised file is **skipped and reported**, never copied. A file
type nobody has thought about is not one to pass through: that is the
same fail-closed rule `mask.py` applies to a column.
"""

import os
import re
import shutil
import sqlite3

from . import course as course_mod
from . import roster as roster_mod
from .vault import ID_KINDS, VaultError

#: Never copied, whatever is asked. See the module docstring.
NEVER_COPY = {
    "secrets": "credentials, which cannot be masked",
    "scans": "scanned papers: images of handwriting with names on them",
}

#: Rewritten by substitution.
TEXT_EXT = {".toml", ".json", ".txt", ".md", ".csv", ".tsv", ".log", ".xml"}

#: Rewritten cell by cell through sqlite3.
DB_EXT = {".db", ".sqlite", ".sqlite3"}

EMAILISH = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
LONG_DIGITS = re.compile(r"\d{9,}")

#: A table or column name safe to put into SQL. Anything else is
#: refused rather than quoted and hoped for.
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class CourseMaskError(Exception):
    pass


# ----------------------------------------------------------- learning --

def learn(vault, roster_path):
    """Teach the vault every student in a roster. Returns how many.

    Goes through `roster.load`, so the fields are the real ones rather
    than a guess at which column is which. Every spelling each student
    may appear under is then masked immediately -- the filed name, the
    natural name, a preferred name, each id, each address -- because
    masking the rest of the folder is a text substitution and it can
    only replace literals the vault has been asked for.
    """
    people = roster_mod.load(roster_path)
    learn_students(vault, people)
    return len(people.students)


def learn_students(vault, people):
    """`learn`, for students already in hand. Returns how many are new.

    Split out so that `privacy` can teach a course's vault everybody a
    roster names the moment it is read, before anything prints them.
    """
    before = len(vault.people)

    # **Before inventing anything.** The fake pool is historical
    # scientists, a real roster contains Grace and Thomas and Julia, and
    # a pseudonym that is another student's real name makes the output
    # scan unable to tell a leak from a pseudonym doing its job. Two
    # passes over the roster costs nothing and the roster is right here.
    vault.avoid([word for student in people
                 for spelling in student.name_fields()
                 for word in (spelling or "").split()])

    for student in people:
        person, _ = vault.resolve({
            "first": student.first, "last": student.last,
            "full": student.name,
            "sid": student.sid, "alt_id": student.alt_id,
            "emails": student.all_emails(),
        })
        # Every whole-name spelling the app can show: the roster name,
        # the printed name (`display`, preferred parts included) and both
        # filed forms. The Roster shows the parts in either order, so the
        # filed form of each pair is something a page can carry.
        for spelling in (student.name, student.display,
                         f"{student.last}, {student.first}".strip(" ,"),
                         f"{student.shown_last}, {student.shown_first}"
                         .strip(" ,")):
            if spelling.strip():
                vault.mask("full", spelling, person)
        # Then every part on its own, each under the kind it is. A
        # preferred given name is masked like a first name; a preferred
        # surname like a surname, given its own fake when it differs
        # from the registrar's (`Vault._candidates`, DESIGN 22).
        for value, kind in ((student.last, "last"), (student.first, "first"),
                            (student.pref_first, "preferred"),
                            (student.pref_last, "last")):
            if value:
                vault.mask(kind, value, person)
        for field in ID_KINDS:
            value = getattr(student, field, "")
            if value:
                vault.mask(field, value, person)
        for address in student.all_emails():
            vault.mask("email", address, person)
    return len(vault.people) - before


# ------------------------------------------------------- the sniffer --

def residual(text, vault):
    """What still looks personal. Returns `(addresses, digit_runs)`.

    Each is a list of line numbers. **Never values** -- the caller
    prints this, and the whole point is that the values do not travel.
    """
    fake_domains = {d.lower() for d in vault.domains.values()}
    fake_ids = set()
    for person in vault.people:
        for field in ID_KINDS:
            if person.fake.get(field):
                fake_ids.add(person.fake[field])
        for address in person.fake.get("emails") or []:
            fake_ids.add(address.partition("@")[0])

    addresses, digits = [], []
    for number, line in enumerate(text.splitlines(), 1):
        for match in EMAILISH.finditer(line):
            domain = match.group(0).rpartition("@")[2].lower()
            if domain not in fake_domains:
                addresses.append(number)
        for match in LONG_DIGITS.finditer(line):
            if match.group(0) not in fake_ids:
                digits.append(number)
    return sorted(set(addresses)), sorted(set(digits))


# -------------------------------------------------------- rewriting --

def mask_text_file(source, destination, vault):
    """Rewrite one text file by substitution. Returns the count.

    `newline=""` on **both** sides, so the original's line endings
    survive byte for byte. Without it the read translates CRLF to LF and
    the write emits LF: the twin then differs from the original on every
    single line, a diff between them is useless, and an unmasked file
    does not match what it came from. Which is most of the point of
    having a twin.
    """
    with open(source, encoding="utf-8", errors="strict", newline="") as f:
        text = f.read()
    out, hits = vault.mask_text(text)
    with open(destination, "w", encoding="utf-8", newline="") as f:
        f.write(out)
    return hits


def mask_database(source, destination, vault):
    """Copy a SQLite file and substitute inside every text cell.

    **Schema-agnostic on purpose.** Every text column of every table is
    put through the same substitution, rather than a list of the columns
    known to hold a name today. A column holding a slug or a date
    matches nothing and is left alone; a column added next month is
    covered without anybody remembering to add it here. The alternative
    -- naming `printed.name`, `printed.sid`, `attempt.sid` and
    `scan_page.sid` -- is a list that goes stale silently, which is the
    failure this codebase keeps meeting.

    **A new file, never an edited copy.** It used to copy the database
    and update the text cells in place. SQLite does not scrub the space
    an update leaves behind, so real names and ids stayed in the file's
    bytes -- readable with `strings` -- while the logical dump, which is
    what the check read, held none (RV-4, 2026-11-16). So the source is
    opened read-only, the destination is created empty, every table,
    index and trigger is recreated from its own `CREATE` statement, and
    rows are inserted already masked. Nothing real is ever written to it.

    Every string value is masked, whatever its column is declared as:
    SQLite stores a value as whatever type it was given, so a declared
    INTEGER column can still hold text.

    Returns the substitution count.
    """
    import urllib.request

    if os.path.exists(destination):
        raise CourseMaskError(
            f"{destination} already exists. A database twin is built "
            "into a new file, never over an old one.")
    hits = 0
    # Closed explicitly, in a finally. `with sqlite3.connect(...)`
    # commits or rolls back the transaction; it does **not** close the
    # connection. On Windows the file then stays locked, and the
    # clean-up that is supposed to delete a twin that failed its checks
    # cannot remove it -- which is how a half-masked course folder was
    # left on disk while the tool reported it deleted.
    src = sqlite3.connect(
        "file:" + urllib.request.pathname2url(os.path.abspath(source))
        + "?mode=ro", uri=True)
    db = sqlite3.connect(destination)
    try:
        schema = src.execute(
            "SELECT type, name, sql FROM sqlite_master"
            " WHERE sql IS NOT NULL AND name NOT LIKE 'sqlite_%'"
            " ORDER BY CASE type WHEN 'table' THEN 0 ELSE 1 END, rowid"
        ).fetchall()
        tables = [name for kind, name, _ in schema if kind == "table"]
        for kind, name, sql in schema:
            if not IDENTIFIER.match(name):
                raise CourseMaskError(
                    f"{source}: {kind} name {name!r} is not a plain "
                    "identifier, so it cannot be quoted safely. Nothing "
                    "was masked.")
        for kind, name, sql in schema:
            if kind == "table":
                db.execute(sql)
        for table in tables:
            columns = []
            for row in src.execute(f'PRAGMA table_info("{table}")'):
                if not IDENTIFIER.match(row[1]):
                    raise CourseMaskError(
                        f"{source}: column {row[1]!r} in {table!r} is not "
                        "a plain identifier. Nothing was masked.")
                columns.append(row[1])
            picked = ", ".join(f'"{c}"' for c in columns)
            holes = ", ".join("?" * len(columns))
            for row in src.execute(
                    f'SELECT {picked} FROM "{table}" ORDER BY rowid'):
                new = []
                for value in row:
                    if isinstance(value, str) and value:
                        masked, n = vault.mask_text(value)
                        hits += n
                        new.append(masked)
                    else:
                        new.append(value)
                db.execute(f'INSERT INTO "{table}" ({picked}) VALUES ({holes})',
                           new)
        # Indexes and triggers last, so no trigger fires on the rows
        # being copied in.
        for kind, name, sql in schema:
            if kind != "table":
                db.execute(sql)
        db.commit()
    finally:
        db.close()
        src.close()
    return hits


def _stored_strings(path):
    """Every string a database legitimately holds: each text value in
    each table, and the text of its schema. See `_verify`."""
    import urllib.request
    db = sqlite3.connect(
        "file:" + urllib.request.pathname2url(os.path.abspath(path))
        + "?mode=ro", uri=True)
    try:
        out = set()
        for name, sql in db.execute(
                "SELECT name, sql FROM sqlite_master WHERE sql IS NOT NULL"):
            out.update((name, sql))
            if not IDENTIFIER.match(name):
                continue
            if sql.lstrip().upper().startswith("CREATE TABLE"):
                for row in db.execute(f'SELECT * FROM "{name}"'):
                    out.update(v for v in row if isinstance(v, str) and v)
        return out
    finally:
        db.close()


def database_text(path):
    """The whole database as SQL text, for checking what was written.

    Read-only, because it is also handed the real course's own database
    as the original to compare against."""
    import urllib.request
    db = sqlite3.connect(
        "file:" + urllib.request.pathname2url(os.path.abspath(path))
        + "?mode=ro", uri=True)
    try:
        return "\n".join(db.iterdump())
    finally:
        db.close()


# ------------------------------------------------------------- the job --

class Report:
    def __init__(self):
        self.students = 0
        self.written = []        # (relative path, substitutions)
        self.skipped = []        # (relative path, why)
        self.out_path = ""

    def describe(self):
        lines = [f"{self.students} students learned from roster.toml", ""]
        for path, hits in self.written:
            lines.append(f"  masked   {path:<24} {hits} substitution(s)")
        for path, why in self.skipped:
            lines.append(f"  skipped  {path:<24} {why}")
        return "\n".join(lines)


def mask_course(course_path, out_path, vault, allow_digits=False):
    """Write a masked twin of a course folder, then check it.

    Raises `CourseMaskError` -- after removing the output directory --
    if any real value survives, or if anything in the output still looks
    like an address or an unexplained long number.
    """
    course_path = os.path.abspath(course_path)
    out_path = os.path.abspath(out_path)
    roster_path = os.path.join(course_path, "roster.toml")

    if not os.path.isdir(course_path):
        raise CourseMaskError(f"{course_path} is not a directory.")
    if not os.path.isfile(roster_path):
        raise CourseMaskError(
            f"{course_path} has no roster.toml, so there is no authoritative "
            "list of who is in it. Masking a course folder without one would "
            "be guesswork over every other file.")
    if out_path == course_path or out_path.startswith(course_path + os.sep):
        raise CourseMaskError(
            "the twin would be written inside the course folder. Choose a "
            "destination outside it -- a twin in there would be masked again "
            "by the next run, and shipped by anything that copies the "
            "course.")
    root = os.path.abspath(course_mod.default_root())
    if out_path == root or out_path.startswith(root + os.sep):
        raise CourseMaskError(
            f"the twin would be written under {root}, where the courses "
            "live. Choose somewhere else: everything in there is treated as "
            "real.")
    if os.path.exists(out_path) and os.listdir(out_path):
        raise CourseMaskError(
            f"{out_path} already exists and is not empty. Nothing was "
            "written -- delete it, or choose another destination.")

    report = Report()
    try:
        report.students = learn(vault, roster_path)
    except roster_mod.RosterError as exc:
        raise CourseMaskError(f"{roster_path}: {exc}") from None

    os.makedirs(out_path, exist_ok=True)
    try:
        _walk(course_path, out_path, vault, report)
        _verify(out_path, vault, report, allow_digits, course_path)
    except Exception as first:
        # **Not `ignore_errors=True`.** That is what this was, and it
        # turned "the twin was deleted" into something the tool said
        # rather than something that happened: a locked SQLite file made
        # the removal fail and the call returned quietly, leaving a
        # half-masked course folder on disk under a message saying it
        # had been destroyed. A removal that fails now says so, loudly,
        # alongside the original failure.
        try:
            shutil.rmtree(out_path)
        except OSError as exc:
            raise CourseMaskError(
                f"{first}\n\nAND the half-made twin could not be deleted: "
                f"{exc}\nDelete {out_path} by hand. Do not send anything "
                "from it -- it is only partly masked."
            ) from None
        raise
    report.out_path = out_path
    return report


def _walk(course_path, out_path, vault, report):
    for entry in sorted(os.listdir(course_path)):
        source = os.path.join(course_path, entry)
        if os.path.isdir(source):
            if entry in NEVER_COPY:
                report.skipped.append((entry + "/", NEVER_COPY[entry]))
            else:
                report.skipped.append(
                    (entry + "/", "a directory nobody has classified"))
            continue

        extension = os.path.splitext(entry)[1].lower()
        destination = os.path.join(out_path, entry)
        if extension in TEXT_EXT:
            try:
                hits = mask_text_file(source, destination, vault)
            except UnicodeDecodeError:
                report.skipped.append((entry, "not readable as UTF-8 text"))
                continue
            report.written.append((entry, hits))
        elif extension in DB_EXT:
            report.written.append(
                (entry, mask_database(source, destination, vault)))
        else:
            report.skipped.append(
                (entry, f"{extension or 'no extension'}: not a type this "
                        "masks"))


def _verify(out_path, vault, report, allow_digits, course_path=None):
    """The two checks, over everything written. Raises on any failure.

    `course_path` is where the originals are. Given, the leak scan lets
    off a real value found only strictly inside a word the original
    already held -- see `Vault.leaks`.
    """
    problems = []
    for name, _ in report.written:
        path = os.path.join(out_path, name)
        source = os.path.join(course_path, name) if course_path else None
        original = None
        if os.path.splitext(name)[1].lower() in DB_EXT:
            text = database_text(path)
            if source:
                original = database_text(source)
        else:
            with open(path, encoding="utf-8", errors="replace") as f:
                text = f.read()
            if source:
                with open(source, encoding="utf-8", errors="replace") as f:
                    original = f.read()

        leaked = vault.leaks(text, original=original)
        if leaked:
            problems.append(f"{name}: {len(leaked)} real value(s) survive")
        if os.path.splitext(name)[1].lower() in DB_EXT:
            # The file's bytes as well as its dump: what somebody handed
            # it can read is the bytes, and the dump cannot see a value
            # left in free space (RV-4).
            #
            # Asked as exactly that question: every value the database
            # holds -- its text cells and its schema -- is blanked out of
            # the bytes, and what is left is scanned. A real value there
            # is one the contents do not account for.
            #
            # Not a scan of the raw bytes as they stand. The word-level
            # judgement above cannot be made on bytes -- a length byte
            # that happens to be a letter sits flush against the text and
            # spells a short name, which refused one real twin in four at
            # random (2026-11-17) -- and an index stores its column's
            # values a second time, which this blanks as well.
            #
            # Blanking is not quite enough on its own: a long index key
            # is split across an overflow page, so a *fragment* of a
            # stored string survives it. A value left over that is part
            # of a stored string has been judged already, by the check of
            # the contents; one that is part of nothing stored -- an old
            # real name in free space -- is the leak this is for.
            with open(path, "rb") as f:
                raw = f.read()
            stored = _stored_strings(path)
            for value in sorted(stored, key=len, reverse=True):
                raw = raw.replace(value.encode("utf-8"), b"\0" * len(value))
            stored_low = [s.lower() for s in stored]
            in_bytes = {
                v for v in vault.leaks(raw.decode("utf-8", errors="replace"))
                if not any(v.lower() in s for s in stored_low)}
            if in_bytes:
                problems.append(
                    f"{name}: {len(in_bytes)} real value(s) in the file's "
                    "bytes that its contents do not show")
        addresses, digits = residual(text, vault)
        if addresses:
            problems.append(
                f"{name}: address-shaped text on line(s) "
                + ", ".join(str(n) for n in addresses[:12])
                + (" ..." if len(addresses) > 12 else ""))
        if digits and not allow_digits:
            problems.append(
                f"{name}: {len(digits)} line(s) with a 9+ digit run that is "
                "not a known pseudonym, first at line " + str(digits[0])
                + ". Pass --allow-digits if these are seeds or hashes.")
    if problems:
        raise CourseMaskError(
            "the twin did not pass its own checks, so it was deleted:\n  "
            + "\n  ".join(problems)
            + "\n\nNo values are printed here on purpose. Run "
              "`checkit-printit vault check` on the course's own files to "
              "see what the vault does and does not know about.")
