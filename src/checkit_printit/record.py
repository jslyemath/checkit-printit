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

**Printed is not attempted.** The `printed` table says a paper was handed
out. It cannot know who was in the room, so nothing in it counts as an
attempt and its wording never says so. `attempt` is the separate table that
does, written by Scans when the instructor has looked at the papers, and it
is the only place an outcome is ever read from.

It also does not feed back into printing. Recording is a side effect of a
build, never an input to one -- that is what keeps the print path a function
of its inputs.
"""

import datetime
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
    graded   INTEGER NOT NULL DEFAULT 0,
    -- Set when this run's folder was built again to recover a lost
    -- page index. Who held which page is right -- it comes from the
    -- roster and the seating chart, which are unchanged -- but the
    -- seeds are a fresh draw and not what was printed. Anything
    -- that shows a seed from such a run must say so.
    rebuilt  INTEGER NOT NULL DEFAULT 0
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

-- What was decided about one paper. Written by Scans, read by
-- Progress and by a student's own history.
--
-- Keyed by (run, student, skill) and not by page, because a page is
-- how a sheet is *found* and this is about the occasion: one run,
-- one skill, one student, one decision.
--
-- `run_page` is which page of the *printed job* this paper was, and
-- is NULL for one that never reached the scanner -- the instructor
-- asked to be able to mark one of those by hand, holding the sheet.
-- It is **not** the page of the copier's PDF the image is on; a
-- scanned stack comes back shuffled and split across files, so the
-- two numbers are unrelated. It was called `page`, which read as
-- whichever of those the reader had in mind.
CREATE TABLE IF NOT EXISTS attempt (
    attempt_id INTEGER PRIMARY KEY,
    run_id  TEXT NOT NULL REFERENCES run(run_id) ON DELETE CASCADE,
    sid     TEXT NOT NULL,
    slug    TEXT NOT NULL,
    outcome TEXT NOT NULL,
    decided TEXT NOT NULL,
    run_page INTEGER,
    -- What the reader called it, beside what the instructor
    -- decided. Kept so a disagreement can be looked at instead of
    -- argued about, and so a threshold that turns out to be wrong
    -- can be re-examined against the measurements it was wrong on.
    reading TEXT NOT NULL DEFAULT '',
    ink     REAL,
    beside  REAL,
    UNIQUE(run_id, sid, slug)
);

CREATE INDEX IF NOT EXISTS printed_by_student ON printed(sid, slug);
CREATE INDEX IF NOT EXISTS printed_by_run ON printed(run_id);
CREATE INDEX IF NOT EXISTS attempt_by_student ON attempt(sid, slug);
"""

#: What an attempt may be. Defined here, with the storage, because
#: this is what is written to disk and has to stay stable; the web
#: app's own list supplies the labels for these ids and a test holds
#: the two together.
#:
#: `queried` is the instructor's "?" beside the box -- not a pass,
#: not a refusal to pass, a paper he wants to look at again. It is
#: stored as itself rather than folded into one of the others,
#: because folding it would throw away the only record that it was
#: ever in question.
OUTCOMES = ("passed", "queried", "failed", "absent")


#: Columns renamed after the first databases were written, as
#: `(table, was, now)`. Applied on open, once, and a no-op every time
#: after -- the check is on the column names actually present, so a
#: database that has already been through it is left alone and one
#: restored from an old backup is brought forward.
#:
#: Renaming rather than adding-and-copying because the values do not
#: change: `attempt.page` always held the printed run's page, and only
#: the name was wrong. A copy would leave the old column behind as a
#: second answer to the same question.
RENAMED = [
    ("attempt", "page", "run_page"),
]

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
    "rebuilt": "INTEGER NOT NULL DEFAULT 0",
}


def home_root():
    """The directory every course and every run folder sits under.

    One definition, shared with `course.default_root` -- that one
    returns the `courses/` subfolder, this one the parent, because a
    run's output is a sibling of `courses/` and not inside it.
    """
    home = os.environ.get("CHECKIT_PRINTIT_HOME")
    return home or os.path.join(os.path.expanduser("~"), "CheckItPrintIt")


def _shorten(folder):
    """A run folder as it is stored: relative to the home if it is
    under it, and otherwise exactly as given."""
    if not folder:
        return folder
    root = os.path.abspath(home_root())
    full = os.path.abspath(folder)
    if full == root or full.startswith(root + os.sep):
        return os.path.relpath(full, root)
    return folder


def _resolve(folder):
    """The same thing on the way back out, always absolute.

    Resolved against the home *as it is now*, which is the whole
    point: the record survives the home moving.
    """
    if not folder or os.path.isabs(folder):
        return folder
    return os.path.join(home_root(), folder)


def _as_row(row):
    """A record row as a dict, with its folder resolved."""
    out = dict(row)
    if "output" in out.keys():
        out["output"] = _resolve(out["output"])
    return out


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
    for table, was, now in RENAMED:
        names = {r["name"] for r in db.execute(f"PRAGMA table_info({table})")}
        if was in names and now not in names:
            db.execute(f"ALTER TABLE {table} RENAME COLUMN {was} TO {now}")
    # Run folders were stored absolute until 2026-11-07, which broke
    # every one of them if the home moved. Shortened here, once: a row
    # already relative is left alone by `_shorten`, and one pointing
    # somewhere outside the home stays absolute because there is
    # nothing for it to be relative to.
    for row in db.execute(
            "SELECT run_id, output FROM run WHERE output <> ''").fetchall():
        short = _shorten(row["output"])
        if short != row["output"]:
            db.execute("UPDATE run SET output = ? WHERE run_id = ?",
                       (short, row["run_id"]))
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
        return _as_row(row) if row else None
    finally:
        db.close()


def write_run(path, run_id, title, date, built, seed, output, handouts,
              extras=0, run_no=None, rebuilt=False):
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
                " seed, output, extras, unnamed, rebuilt)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, run_no and int(run_no), title, date, built,
                 int(seed), _shorten(output), int(extras), unnamed,
                 int(bool(rebuilt))))
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
        return [_as_row(r) for r in db.execute(
            "SELECT r.*, COUNT(p.printed_id) AS papers,"
            " COUNT(DISTINCT p.sid) AS students"
            " FROM run r LEFT JOIN printed p ON p.run_id = r.run_id"
            " GROUP BY r.run_id ORDER BY r.date, r.built")]
    finally:
        db.close()


def names_printed(path):
    """`{sid: name}`, the most recent name printed for each student.

    The record rather than the roster, because this is for reading a
    paper back: what the sheet in your hand says is the name it was
    printed with, and a student who changed their name mid-term would
    otherwise be shown under a name that is not on the page.

    Most recent wins -- a run prints one name per student, and the
    later run is the better guess for a paper whose run is unknown.
    """
    if not os.path.isfile(path):
        return {}
    db = connect(path)
    try:
        return {r["sid"]: r["name"] for r in db.execute(
            "SELECT p.sid, p.name FROM printed p JOIN run r"
            " ON r.run_id = p.run_id WHERE p.sid != ''"
            " ORDER BY r.built ASC")}
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
        out = _as_row(row)
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
        return _as_row(db.execute("SELECT * FROM run WHERE run_id = ?",
                                  (run_id,)).fetchone())
    finally:
        db.close()


def discard_run(path, run_id):
    """Remove a run and every paper recorded under it.

    For a job that was built and never handed out -- a rebuild while
    fixing something, a test print. Those rows are not history, they
    are a record of a PDF that existed for ten minutes, and they
    follow a student around: `history` reads `printed`, so each one
    shows up in a drill-in as a paper that was never on a desk.

    **Refused once anything has been read back from it**, for the
    same reason a graded run cannot be delisted: a decision has to
    stay findable, and the run is where it is found. That makes this
    safe to offer -- the only runs it can touch are ones no judgement
    depends on.

    Returns how many printed rows went with it. The run number is
    not reused: `meta.last_run_no` is the high-water mark and is left
    alone, so a code on a sheet from a discarded run still fails to
    resolve rather than resolving to somebody else's job.
    """
    if not os.path.isfile(path):
        raise RecordError(f"{path} does not exist, so there are no runs.")
    db = connect(path)
    try:
        row = db.execute("SELECT graded FROM run WHERE run_id = ?",
                         (run_id,)).fetchone()
        if row is None:
            raise RecordError(f"no run called {run_id!r}.")
        marks = db.execute(
            "SELECT COUNT(*) FROM attempt WHERE run_id = ?",
            (run_id,)).fetchone()[0]
        if row["graded"] or marks:
            raise RecordError(
                f"{run_id} has been graded, so it cannot be discarded. "
                f"What was read back from it is the record of an "
                f"attempt, and the run is where it is found.")
        papers = db.execute(
            "SELECT COUNT(*) FROM printed WHERE run_id = ?",
            (run_id,)).fetchone()[0]
        db.execute("DELETE FROM run WHERE run_id = ?", (run_id,))
        db.commit()
        return papers
    finally:
        db.close()


def printed_pairs(path):
    """`{(run_id, sid, slug)}` -- every paper this course ever printed.

    `save_attempts` builds the same set to decide what to *report* as
    strange. This one exists so a caller can decide what to *refuse*:
    a correction arriving from the browser says whose paper something
    is, and the only safe answer is "only if that student was handed
    that skill in that run".
    """
    if not os.path.isfile(path):
        return set()
    db = connect(path)
    try:
        return {(r["run_id"], str(r["sid"]), r["slug"]) for r in db.execute(
            "SELECT run_id, sid, slug FROM printed")}
    finally:
        db.close()


def save_attempts(path, rows):
    """Record what was decided about a batch of papers.

    `rows` carry `run_id`, `sid`, `slug`, `outcome`, and optionally
    `page` -- which page of the printed run -- plus `reading`,
    `ink` and `beside`. Every run named is marked
    graded, because having a decision in it is exactly what graded
    means.

    Returns `(written, unknown)`. `unknown` holds any row whose
    (run, student, skill) was never printed -- the page index and
    the print record disagreeing, which is worth saying out loud.
    The row is still written: losing a hundred decisions because one
    of them is strange is the worse trade, and the decision is the
    instructor's, not the index's.
    """
    if not rows:
        return 0, []
    db = connect(path)
    try:
        now = datetime.datetime.now().isoformat(timespec="seconds")
        printed = {(r["run_id"], r["sid"], r["slug"]) for r in db.execute(
            "SELECT run_id, sid, slug FROM printed")}
        known_runs = {r["run_id"] for r in db.execute(
            "SELECT run_id FROM run")}
        unknown, written, runs_touched = [], 0, set()
        for row in rows:
            outcome = row["outcome"]
            if outcome not in OUTCOMES:
                # Not a "report it and carry on": an outcome the rest
                # of the app cannot read is not a decision, and
                # writing it would put a value in the table that
                # Progress has no branch for.
                raise RecordError(
                    f"{outcome!r} is not an outcome. It is one of "
                    f"{', '.join(OUTCOMES)}.")
            key = (row["run_id"], str(row["sid"]), row["slug"])
            if row["run_id"] not in known_runs:
                raise RecordError(
                    f"no run called {row['run_id']!r}, so there is "
                    f"nothing to attach these papers to.")
            if key not in printed:
                unknown.append(key)
            db.execute(
                "INSERT INTO attempt"
                " (run_id, sid, slug, outcome, decided, run_page,"
                "  reading, ink, beside)"
                " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
                " ON CONFLICT(run_id, sid, slug) DO UPDATE SET"
                "   outcome = excluded.outcome,"
                "   decided = excluded.decided,"
                "   run_page = excluded.run_page,"
                "   reading = excluded.reading,"
                "   ink     = excluded.ink,"
                "   beside  = excluded.beside",
                (key[0], key[1], key[2], outcome, now, row.get("page"),
                 row.get("reading", "") or "", row.get("ink"),
                 row.get("beside")))
            written += 1
            runs_touched.add(row["run_id"])
        # Graded means "something has been read back from this run",
        # which is now true of every run in the batch. Done in the
        # same transaction: a saved decision on an ungraded run would
        # let the run be delisted out from under it.
        for run_id in runs_touched:
            db.execute("UPDATE run SET graded = 1 WHERE run_id = ?",
                       (run_id,))
        db.commit()
        return written, sorted(unknown)
    finally:
        db.close()


def attempts_for(path, sid):
    """One student's attempts, oldest first. Their history page.

    Joined to `run` for the date and to `printed` for the seed, so a
    caller can say "W2, 9 October, seed 412, not passed" without
    three more queries.
    """
    if not os.path.isfile(path):
        return []
    db = connect(path)
    try:
        return [dict(r) for r in db.execute(
            "SELECT a.*, r.title, r.date, r.run_no, p.seed, p.version"
            " FROM attempt a"
            " JOIN run r ON r.run_id = a.run_id"
            " LEFT JOIN printed p"
            "   ON p.run_id = a.run_id AND p.sid = a.sid"
            "  AND p.slug = a.slug"
            " WHERE a.sid = ?"
            " ORDER BY r.date, r.built, a.slug", (str(sid),))]
    finally:
        db.close()


def progress(path):
    """Per (student, skill): how it has gone. What Progress draws.

    `attempts` counts occasions, `passes` how many of them passed.
    A query is an attempt and is not a pass -- it is a paper still
    in question, and calling it either would be deciding something
    the instructor deliberately did not.

    `last` is the most recent outcome and `last_date` when.
    `passed_in` is the run of the *latest passing* attempt, or None:
    a student who passed in October and sat it again in November
    still passed in October, and `last` would say November.
    """
    if not os.path.isfile(path):
        return []
    db = connect(path)
    try:
        return [dict(r) for r in db.execute("""
            SELECT a.sid, a.slug,
                   COUNT(*) AS attempts,
                   SUM(a.outcome = 'passed') AS passes,
                   SUM(a.outcome = 'queried') AS queries,
                   SUM(a.outcome = 'absent') AS absents,
                   (SELECT b.outcome FROM attempt b
                     JOIN run br ON br.run_id = b.run_id
                     WHERE b.sid = a.sid AND b.slug = a.slug
                     ORDER BY br.date DESC, br.built DESC LIMIT 1) AS last,
                   (SELECT b.run_id FROM attempt b
                     JOIN run br ON br.run_id = b.run_id
                     WHERE b.sid = a.sid AND b.slug = a.slug
                       AND b.outcome = 'passed'
                     ORDER BY br.date DESC, br.built DESC
                     LIMIT 1) AS passed_in,
                   -- The most recent outcome that was not an absence.
                   -- `last` answers "what happened last"; this answers
                   -- "what happened last time they sat it", and the
                   -- grid wants the second: a student who missed the
                   -- latest paper has not thereby stopped being in
                   -- question about the one before.
                   (SELECT b.outcome FROM attempt b
                     JOIN run br ON br.run_id = b.run_id
                     WHERE b.sid = a.sid AND b.slug = a.slug
                       AND b.outcome <> 'absent'
                     ORDER BY br.date DESC, br.built DESC
                     LIMIT 1) AS last_sat,
                   MAX(r.date) AS last_date
              FROM attempt a
              JOIN run r ON r.run_id = a.run_id
             GROUP BY a.sid, a.slug
             ORDER BY a.sid, a.slug""")]
    finally:
        db.close()


def history(path, sid, slug):
    """Every time this student was printed this skill, oldest first.

    Driven off `printed` rather than `attempt`, so a run that was
    handed out and never scanned is in the list with nothing
    recorded against it. That row is the point: it is the paper he
    is holding, months later, with no stack left to re-read.

    `outcome` is None for such a row. Everything else -- the seed,
    the version, the date -- comes from the printing, so the paper
    can be found again whether or not anybody graded it.
    """
    if not os.path.isfile(path):
        return []
    db = connect(path)
    try:
        return [dict(r) for r in db.execute(
            "SELECT p.run_id, r.title, r.date, r.run_no, r.delisted,"
            "       r.rebuilt,"
            "       p.seed, p.version,"
            "       a.outcome, a.decided, a.run_page, a.reading"
            "  FROM printed p"
            "  JOIN run r ON r.run_id = p.run_id"
            "  LEFT JOIN attempt a"
            "    ON a.run_id = p.run_id AND a.sid = p.sid"
            "   AND a.slug = p.slug"
            " WHERE p.sid = ? AND p.slug = ?"
            " ORDER BY r.date, r.built", (str(sid), str(slug)))]
    finally:
        db.close()


def papers_in(path, run_id):
    """`{(sid, slug)}` for one run, or None if it has never been built.

    None and an empty set are different answers: nothing recorded
    under that folder at all, against a run that recorded no
    attributable papers. Only the first means "nothing to collide
    with".
    """
    if not os.path.isfile(path):
        return None
    db = connect(path)
    try:
        if db.execute("SELECT 1 FROM run WHERE run_id = ?",
                      (run_id,)).fetchone() is None:
            return None
        return {(r["sid"], r["slug"]) for r in db.execute(
            "SELECT sid, slug FROM printed WHERE run_id = ?", (run_id,))}
    finally:
        db.close()


def recorded_in(path, run_ids):
    """`{(run_id, sid, slug): outcome}` for these runs.

    One query for a whole batch, because the review grid asks about
    every paper in a stack at once and a lookup per row would be a
    few hundred round trips to answer one question.
    """
    run_ids = [r for r in run_ids if r]
    if not run_ids or not os.path.isfile(path):
        return {}
    db = connect(path)
    try:
        holes = ", ".join("?" * len(run_ids))
        return {(r["run_id"], r["sid"], r["slug"]): r["outcome"]
                for r in db.execute(
                    "SELECT run_id, sid, slug, outcome FROM attempt"
                    f" WHERE run_id IN ({holes})", run_ids)}
    finally:
        db.close()


def graded_runs(path, keep=None):
    """The runs that have been graded, newest first.

    `keep` caps the list; None is all of them. The cap used to be the
    whole answer to "what counts as recent", fixed at two. It is the
    reader's number now and lives in their browser, so the server
    sends the order and the browser takes as many as it wants.

    What "recently passed" means. A grading set is a run something
    has been read back from, which is exactly what `graded` records
    -- so this is the record's own answer rather than a guess from
    dates, and it stays right when two runs share one date.
    """
    if not os.path.isfile(path):
        return []
    db = connect(path)
    try:
        rows = db.execute(
            "SELECT run_id FROM run WHERE graded = 1"
            " ORDER BY date DESC, built DESC")
        out = [r["run_id"] for r in rows]
        return out if keep is None else out[:int(keep)]
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
