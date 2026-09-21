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

SCHEMA = """
CREATE TABLE IF NOT EXISTS run (
    run_id  TEXT PRIMARY KEY,   -- the output folder's name
    title   TEXT NOT NULL,
    date    TEXT NOT NULL,
    built   TEXT NOT NULL,
    seed    INTEGER NOT NULL,   -- so a run can be found again from the record
    output  TEXT NOT NULL,
    extras  INTEGER NOT NULL DEFAULT 0,
    unnamed INTEGER NOT NULL DEFAULT 0
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

CREATE INDEX IF NOT EXISTS printed_by_student ON printed(sid, slug);
CREATE INDEX IF NOT EXISTS printed_by_run ON printed(run_id);
"""


def connect(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    db = sqlite3.connect(path)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    return db


def write_run(path, run_id, title, date, built, seed, output, handouts,
              extras=0):
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
                "INSERT INTO run (run_id, title, date, built, seed, output,"
                " extras, unnamed) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, title, date, built, int(seed), output, int(extras),
                 unnamed))
            db.executemany(
                "INSERT INTO printed (run_id, sid, name, section, slug, seed,"
                " version) VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
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
