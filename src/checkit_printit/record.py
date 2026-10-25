"""What was printed, for whom, at which seed.

SQLite rather than TOML, for two reasons that are not about size. Every
question asked of this is a query -- "how many times has she had W1", "what
did this student get on the eighteenth" -- which is one line here and a
hand-rolled index over a file otherwise. And two processes write it: the CLI
at build time, and the eventual gradebook editor changing a single field.
SQLite updates one row under a lock; rewriting a file to change one field
races, and the loser's write disappears without a word.

Everything a human authors stays TOML, so it can be diffed and hand-fixed.
The rule is: if a human is the author, TOML; if the tool is, SQLite.

**Printed is not attempted.** This table says a paper was handed out. It
cannot know who was in the room, so nothing here counts as an attempt and the
wording never says so. Outcomes are a later stage with a table of their own.

It also does not feed back into printing. Recording is a side effect of a
build, never an input to one -- that is what keeps the print path a function
of its inputs.
"""

import os
import sqlite3


class RecordError(Exception):
    """Something asked of the record that it cannot do.

    One class, because a caller has one thing to catch and one message
    to show -- the same shape `ResponseError` and `SeatingError` have.
    """


SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
    run_id  TEXT PRIMARY KEY,   -- the output folder's name
    -- What identifies this run *to a scanner*, and the reason it is
    -- not the seed: a replay carries the replayed run's seed on
    -- purpose, so two runs routinely share one. This is allocated
    -- once per course and never reused, so a code resolves to
    -- exactly one run. Small on purpose -- it has to fit in a QR
    -- symbol alongside a page number.
    run_no  INTEGER,
    title   TEXT NOT NULL,
    date    TEXT NOT NULL,
    built   TEXT NOT NULL,
    seed    INTEGER NOT NULL,   -- so a run can be found again from the record
    output  TEXT NOT NULL,
    extras  INTEGER NOT NULL DEFAULT 0,
    unnamed INTEGER NOT NULL DEFAULT 0,
    -- Moved to the bottom of the Runs list, not hidden and never
    -- deleted: the printed rows under it are the only record that a
    -- paper existed, and Scans may still have to place a loose sheet
    -- from it.
    delisted INTEGER NOT NULL DEFAULT 0,
    -- Set when Scans has read this run back. A graded run cannot be
    -- delisted -- see `set_flags`.
    graded   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS printed (
    printed_id INTEGER PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    sid        TEXT NOT NULL,   -- never the name: names change, ids do not
    name       TEXT NOT NULL,   -- as printed, for reading the log back
    section    TEXT NOT NULL DEFAULT '',
    slug       TEXT NOT NULL,
    seed       INTEGER NOT NULL,
    version    TEXT NOT NULL DEFAULT ''
);

-- Small facts about the course that are not about one run. At
-- present just `last_run_no`, the highest run number ever issued,
-- which has to outlive the row that was given it.
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS printed_by_student ON printed(sid, slug);
CREATE INDEX IF NOT EXISTS printed_by_run ON printed(run_id);
"""


#: Columns added to `run` after the first databases were written.
#: `CREATE TABLE IF NOT EXISTS` does nothing to a table that exists,
#: so a column added to SCHEMA alone reaches new courses only -- and
#: the real one has three runs in it already.
ADDED = {
    "delisted": "INTEGER NOT NULL DEFAULT 0",
    "graded": "INTEGER NOT NULL DEFAULT 0",
    # Nullable, because the runs already in a record were built
    # before run numbers existed and there is no honest number to
    # give them. A paper from one of those carries a seed-based code
    # or none at all, and `run_by_no` will not match it -- which is
    # correct: those runs cannot be scanned by code.
    "run_no": "INTEGER",
}


def connect(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    have = {r["name"] for r in db.execute("PRAGMA table_info(run)")}
    for column, decl in ADDED.items():
        if column not in have:
            db.execute(f"ALTER TABLE run ADD COLUMN {column} {decl}")
    db.commit()
    return db


def _high_water(db):
    """The highest run number ever issued in this course.

    Kept in `meta` rather than read off the rows, because the rows
    can go. The maximum over surviving rows is the same number right
    up until something is deleted, and then it quietly hands that
    run's number to the next one -- which is the misattribution run
    numbers exist to prevent.

    MAX over the rows is still taken, for a record written before
    this table existed.
    """
    row = db.execute("SELECT value FROM meta WHERE key = 'last_run_no'"
                     ).fetchone()
    stored = int(row["value"]) if row else 0
    present = db.execute("SELECT MAX(run_no) FROM run").fetchone()[0] or 0
    return max(stored, int(present))


def next_run_no(path, run_id):
    """The number this run should carry. Allocated, then reused.

    Building into the same folder twice is one printing event, so the
    number is looked up by `run_id` first and only allocated when the
    folder is new. Otherwise a rebuild would burn a number and, worse,
    change what the code on the reprinted paper says.

    Pure: asking does not allocate. The mark moves when the run is
    actually written, so a build that fails between here and there
    leaves no gap.
    """
    db = connect(path)
    try:
        row = db.execute("SELECT run_no FROM run WHERE run_id = ?",
                         (run_id,)).fetchone()
        if row is not None and row["run_no"]:
            return int(row["run_no"])
        return _high_water(db) + 1
    finally:
        db.close()


def run_by_no(path, run_no):
    """The run a scanned code names, or None.

    None has two meanings and the caller has to tell them apart: a
    code from another course, or a run that has been deleted. Neither
    is recoverable here.
    """
    if not os.path.isfile(path):
        return None
    db = connect(path)
    try:
        row = db.execute("SELECT * FROM run WHERE run_no = ?",
                         (int(run_no),)).fetchone()
        return dict(row) if row else None
    finally:
        db.close()


def write_run(path, run_id, title, date, built, seed, output, handouts,
              extras=0, run_no=None):
    """Record one print run. Re-recording the same run replaces it.

    A run is identified by its output folder, so building into the same folder
    twice is one printing event recorded once rather than a duplicate. Building
    into a new folder -- which a replay does -- is a second event, correctly.

    A handout with no student id is counted but not attributed: a run printed
    with names off cannot say who received what, and inventing an owner would
    be worse than admitting it.
    """
    rows, unnamed = [], 0
    for h in handouts:
        if not h.get("sid"):
            unnamed += 1
            continue
        for slug, paper_seed in h["papers"]:
            rows.append((run_id, h["sid"], h.get("name", ""),
                         h.get("section", ""), slug, int(paper_seed),
                         h.get("version", "")))

    db = connect(path)
    try:
        with db:
            # The papers go with it: `printed.run_id` cascades, and
            # `PRAGMA foreign_keys` is set in connect(), which is the only way
            # in. Deleting them separately as well would be a second guard
            # that no test can tell from the first.
            db.execute("DELETE FROM run WHERE run_id = ?", (run_id,))
            db.execute(
                "INSERT INTO run (run_id, run_no, title, date, built,"
                " seed, output, extras, unnamed)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, run_no and int(run_no), title, date, built,
                 int(seed), output, int(extras), unnamed))
            db.executemany(
                "INSERT INTO printed (run_id, sid, name, section, slug, seed,"
                " version) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            if run_no:
                db.execute(
                    "INSERT INTO meta (key, value) VALUES ('last_run_no', ?)"
                    " ON CONFLICT(key) DO UPDATE SET value = ?"
                    " WHERE CAST(value AS INTEGER) < ?",
                    (str(int(run_no)), str(int(run_no)), int(run_no)))
    finally:
        db.close()
    return len(rows), unnamed


# ------------------------------------------------------------- questions --

def runs(path):
    if not os.path.isfile(path):
        return []
    db = connect(path)
    try:
        return [dict(r) for r in db.execute(
            "SELECT r.*, COUNT(p.printed_id) AS papers,"
            " COUNT(DISTINCT p.sid) AS students"
            " FROM run r LEFT JOIN printed p ON p.run_id = r.run_id"
            " GROUP BY r.run_id ORDER BY r.date, r.built")]
    finally:
        db.close()


def run_detail(path, run_id):
    """One run: its own row, and what it printed, per skill.

    Returns None where the run is unknown, so a caller can say so
    rather than draw an empty page.

    The per-skill rows are what the detail view is for -- which skills
    were in the run, how many papers of each, and the seed behind every
    version. All of it is already in `printed`; nothing new is stored.
    """
    if not os.path.isfile(path):
        return None
    db = connect(path)
    try:
        row = db.execute(
            "SELECT r.*, COUNT(p.printed_id) AS papers,"
            " COUNT(DISTINCT p.sid) AS students"
            " FROM run r LEFT JOIN printed p ON p.run_id = r.run_id"
            " WHERE r.run_id = ? GROUP BY r.run_id", (run_id,)).fetchone()
        if row is None or row["run_id"] is None:
            return None
        out = dict(row)
        out["skills"] = [dict(r) for r in db.execute(
            "SELECT slug, COUNT(*) AS papers,"
            " COUNT(DISTINCT version) AS versions"
            " FROM printed WHERE run_id = ?"
            " GROUP BY slug ORDER BY slug", (run_id,))]
        # One row per paper actually drawn, which is the thing a
        # reprint has to reproduce and the thing Scans will match a
        # scanned page against.
        out["seeds"] = [dict(r) for r in db.execute(
            "SELECT DISTINCT slug, version, seed FROM printed"
            " WHERE run_id = ? ORDER BY slug, version", (run_id,))]
        return out
    finally:
        db.close()


def set_flags(path, run_id, delisted=None, graded=None):
    """Set `delisted` / `graded` on one run. Returns the row after.

    **A graded run cannot be delisted.** Refused here rather than only
    in the view, because the view is not the only caller and a rule
    enforced in one place is a rule with a way round it.

    **Grading a delisted run brings it back into the list.** Not
    refused: the reason a graded run may not be delisted is that what
    was read back from it has to be findable, and that reason applies
    just as much to a run delisted before it was scanned. Refusing
    would block a legitimate scan to protect a tidier list.

    Ungrading is always allowed -- it is the undo of a mistake.
    """
    if not os.path.isfile(path):
        raise RecordError(f"{path} does not exist, so there are no runs.")
    db = connect(path)
    try:
        row = db.execute("SELECT * FROM run WHERE run_id = ?",
                         (run_id,)).fetchone()
        if row is None:
            raise RecordError(f"no run called {run_id!r}.")
        want_graded = row["graded"] if graded is None else int(bool(graded))
        want_delisted = (row["delisted"] if delisted is None
                         else int(bool(delisted)))
        if delisted and want_graded:
            raise RecordError(
                f"{run_id} has been graded, so it cannot be delisted. "
                f"What was read back from it is the record of an "
                f"attempt, and the list is where it is found.")
        if graded and want_delisted:
            want_delisted = 0
        db.execute("UPDATE run SET delisted = ?, graded = ? WHERE run_id = ?",
                   (want_delisted, want_graded, run_id))
        db.commit()
        return dict(db.execute("SELECT * FROM run WHERE run_id = ?",
                               (run_id,)).fetchone())
    finally:
        db.close()


def for_student(path, sid):
    """Every paper this student has been handed, oldest first."""
    if not os.path.isfile(path):
        return []
    db = connect(path)
    try:
        return [dict(r) for r in db.execute(
            "SELECT p.slug, p.seed, p.version, r.title, r.date, r.run_id"
            " FROM printed p JOIN run r ON r.run_id = p.run_id"
            " WHERE p.sid = ? ORDER BY r.date, p.slug", (sid,))]
    finally:
        db.close()


def times_printed(path, sid, slug=None):
    """How many papers this student has received, per skill.

    Printed, not attempted -- the build cannot know who was in the room.
    """
    if not os.path.isfile(path):
        return {}
    db = connect(path)
    try:
        if slug:
            row = db.execute(
                "SELECT COUNT(*) AS n FROM printed WHERE sid = ? AND slug = ?",
                (sid, slug)).fetchone()
            return {slug: row["n"]}
        return {r["slug"]: r["n"] for r in db.execute(
            "SELECT slug, COUNT(*) AS n FROM printed WHERE sid = ?"
            " GROUP BY slug ORDER BY slug", (sid,))}
    finally:
        db.close()


def skill_totals(path):
    """Per skill: how many papers, to how many different students."""
    if not os.path.isfile(path):
        return []
    db = connect(path)
    try:
        return [dict(r) for r in db.execute(
            "SELECT slug, COUNT(*) AS papers, COUNT(DISTINCT sid) AS students"
            " FROM printed GROUP BY slug ORDER BY slug")]
    finally:
        db.close()
