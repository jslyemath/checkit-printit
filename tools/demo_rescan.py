r"""Build the Demo course, and show the scan review before and after.

Entirely invented people. The point of the course is to have a place
to exercise the tab that is not his class, and the point of the report
is to show what the re-scan filter changed, on data small enough to
read.

The story it sets up is his: a checkpoint graded a fortnight ago with
one "?" still outstanding, a fresh checkpoint being scanned for the
first time, and a pile that is mostly the fresh one plus the single
corrected paper from the old one that he fed back through.
"""
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "src"))

from checkit_printit import gui as gui_mod          # noqa: E402
from checkit_printit import pageindex               # noqa: E402
from checkit_printit import record as record_mod    # noqa: E402
from checkit_printit import scans                   # noqa: E402

HOME = os.path.expanduser("~/CheckItPrintIt")
COURSE = os.path.join(HOME, "courses", "Demo")
OUT = os.path.join(HOME, "Demo")

OLD, NEW = 1, 2

#: Invented, and deliberately not name-shaped like a real roster: every
#: surname is a tree and every given name is from a different place, so
#: nobody could mistake one of these for a student.
PEOPLE = [
    ("d01", "Alder, Nora", "820"),
    ("d02", "Birch, Omar", "820"),
    ("d03", "Cedar, Priya", "820"),
    ("d04", "Elm, Quentin", "820"),
    ("d05", "Hazel, Rosa", "830"),
    ("d06", "Linden, Sachi", "830"),
    ("d07", "Maple, Tomas", "830"),
    ("d08", "Rowan, Uma", "830"),
]

#: The old checkpoint: one skill, everybody. Page number = position.
OLD_PAPERS = [(n, sid, "N3") for n, (sid, _, _) in enumerate(PEOPLE, 1)]

#: The new one: two skills for the first four, one for the rest.
NEW_PAPERS = []
for n, (sid, _, _) in enumerate(PEOPLE, 1):
    NEW_PAPERS.append((len(NEW_PAPERS) + 1, sid, "N3"))
    if n <= 4:
        NEW_PAPERS.append((len(NEW_PAPERS) + 1, sid, "N4"))


def write_index(folder, run_no, papers):
    os.makedirs(folder, exist_ok=True)
    lines = [f"run*{run_no}"]
    for page, sid, slug in papers:
        lines.append(f"{page}*student*{sid}*{slug}*100*1")
    with open(os.path.join(folder, pageindex.FILENAME), "w",
              encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")
    return pageindex.load(folder)


def build():
    for folder in (COURSE, OUT):
        shutil.rmtree(folder, ignore_errors=True)
    os.makedirs(COURSE, exist_ok=True)

    with open(os.path.join(COURSE, "course.toml"), "w",
              encoding="utf-8") as handle:
        handle.write(
            '# A synthetic course, for exercising the app without\n'
            '# touching a real class. Every person in it is invented.\n'
            'name = "Demo"\n'
            'code = "DEMO 101"\n'
            'semester = "26FA"\n'
            'professor = "A. Demonstrator"\n')

    with open(os.path.join(COURSE, "roster.toml"), "w",
              encoding="utf-8") as handle:
        handle.write("# Invented people. Not a class.\n")
        for sid, name, section in PEOPLE:
            handle.write(f'\n[[student]]\nname = "{name}"\n'
                         f'sid = "{sid}"\nsection = "{section}"\n'
                         f'email = "{sid}@example.invalid"\n')

    path = os.path.join(COURSE, "record.db")
    folders = {OLD: os.path.join(OUT, "Checkpoint A 2026-10-26"),
               NEW: os.path.join(OUT, "Checkpoint B 2026-11-02")}
    indexes = {OLD: write_index(folders[OLD], OLD, OLD_PAPERS),
               NEW: write_index(folders[NEW], NEW, NEW_PAPERS)}

    names = {sid: name for sid, name, _ in PEOPLE}
    sections = {sid: sec for sid, _, sec in PEOPLE}

    for run_no, run_id, title, date, papers in (
            (OLD, "chk-a", "Checkpoint A", "2026-10-26", OLD_PAPERS),
            (NEW, "chk-b", "Checkpoint B", "2026-11-02", NEW_PAPERS)):
        handouts = {}
        for _, sid, slug in papers:
            handouts.setdefault(sid, {
                "sid": sid, "name": names[sid],
                "section": sections[sid], "version": "A",
                "papers": []})["papers"].append((slug, 100))
        record_mod.write_run(
            path, run_id=run_id, title=title, date=date,
            built=f"{date}T09:00", seed=7, output=folders[run_no],
            handouts=list(handouts.values()), run_no=run_no)

    # Checkpoint A was graded a fortnight ago. Page 3 is the "?" he has
    # since turned into a tick. Page 8 was handed out and never came
    # back and never got marked by hand -- the paper that makes the
    # run-level half of the filter visible.
    record_mod.save_attempts(path, [
        {"run_id": "chk-a", "sid": sid, "slug": slug,
         "outcome": "queried" if page == 3 else "passed",
         "page": page, "reading": "ticked"}
        for page, sid, slug in OLD_PAPERS if page != 8])

    return path, indexes, names, sections


def sheet(run_no, index, page, scan_page):
    entry = index.get(page)
    return scans.Sheet(source="demo-stack.pdf", scan_page=scan_page,
                       status="placed", run_no=run_no,
                       run_page=page, entry=entry)


def report(path, indexes, names, sections):
    resolve = scans.index_reader(path)

    # The pile he actually put through: four papers of the new
    # checkpoint, and the one corrected "?" from the old one.
    pile = [sheet(NEW, indexes[NEW], p, n)
            for n, p in enumerate([1, 2, 3, 5], start=1)]
    pile.append(sheet(OLD, indexes[OLD], 3, 5))
    batch = scans.Batch(sheets=pile)

    print("=" * 70)
    print("THE PILE: 5 sheets")
    print("=" * 70)
    for s in batch.placed:
        who = names[s.entry.sid]
        print(f"  scan page {s.scan_page}: {s.entry.slug:<3} "
              f"{who:<16} from run {s.run_no} page {s.run_page}")
    print()

    print("=" * 70)
    print("BEFORE -- what the tab used to build the review table from")
    print("=" * 70)
    before = batch.missing(resolve)
    rows_before = len(batch.placed) + sum(len(v) for v in before.values())
    for run_no, pages in sorted(before.items()):
        index = indexes[run_no]
        print(f"  run {run_no}: {len(pages)} 'missing' papers -> "
              f"pages {pages}")
    print(f"\n  review table: {len(batch.placed)} scanned + "
          f"{sum(len(v) for v in before.values())} absent = "
          f"{rows_before} rows")
    print(f"  of which {len(before.get(OLD, []))} are Checkpoint A "
          f"papers graded a fortnight ago.")
    print()

    print("=" * 70)
    print("AFTER -- what it builds from now")
    print("=" * 70)
    keeper = gui_mod._Pile(batch, path)
    after = keeper.missing(resolve)
    held = keeper.held_back(resolve)
    print(f"  runs being scanned for the first time: "
          f"{sorted(keeper.first_time)}")
    print(f"  papers that came back having been graded already: "
          f"{sorted(keeper.rescanned)}")
    for run_no, pages in sorted(after.items()):
        print(f"  run {run_no}: {len(pages)} absentees worth asking "
              f"about -> pages {pages}")
    for run_no, n in sorted(held.items()):
        print(f"  run {run_no}: {n} absentees held back (already "
              f"answered for)")
    print()

    rows = gui_mod._review_rows(batch, path, names, sections)
    print("=" * 70)
    print(f"THE REVIEW TABLE: {rows_before} rows -> {len(rows)} rows")
    print("=" * 70)
    print(f"  {'Name':<16} {'Sec':<4} {'Assessment':<14} {'Skill':<6} "
          f"{'Scanned':<8} {'Re-scan':<8} {'On record':<10} Suggests")
    print("  " + "-" * 92)
    for row in rows:
        print(f"  {row['name']:<16} {row['section']:<4} "
              f"{row['assessment']:<14} {row['skill']:<6} "
              f"{'yes' if row['scanned'] else 'no':<8} "
              f"{'YES' if row['rescan'] else '-':<8} "
              f"{row['recorded'] or '-':<10} {row['outcome'] or '-'}")

    print()
    print("  Read the table against the pile:")
    print("   * 4 rows for the new checkpoint's scanned papers.")
    print("   * 1 row for the corrected '?', marked Re-scan, arriving")
    print("     with 'queried' already on the record so the change is")
    print("     visible as a correction rather than a fresh read.")
    print(f"   * {len(after.get(NEW, []))} rows for the new "
          f"checkpoint's papers that were not in the pile.")
    print("   * and NOTHING from Checkpoint A beyond the one sheet he")
    print(f"     actually fed in -- {len(before.get(OLD, []))} rows "
          f"that used to appear, including page 8, which was never")
    print("     graded at all and so could only be kept out by the")
    print("     run-level half of the rule.")

    print()
    print("=" * 70)
    print("AND THE CLASH FLAG")
    print("=" * 70)
    pairs = {}
    for row in rows:
        pairs.setdefault((row["sid"], row["skill"]), []).append(row)
    both = {k: v for k, v in pairs.items() if len(v) > 1}
    print(f"  (student, skill) pairs appearing twice: {len(both)}")
    for (sid, slug), group in both.items():
        runs = sorted(r["run"] for r in group)
        print(f"    {names[sid]} / {slug}: runs {runs}")
        print(f"      old key (student, skill)      -> flagged as a "
              f"clash")
        print(f"      new key (run, student, skill) -> not flagged; two "
              f"attempts, weeks apart")
    if not both:
        print("    none in this pile -- feed a second N3 paper in to see")
        print("    it, which is what the tests do.")


if __name__ == "__main__":
    path, indexes, names, sections = build()
    print(f"built the Demo course at {COURSE}")
    print(f"print output at {OUT}")
    print(f"serve it with: printit-demo (port 8768)\n")
    report(path, indexes, names, sections)
