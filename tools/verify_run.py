"""Check a finished print run against the job that asked for it.

Written after several hand-rolled checks reported clean numbers while looking
at the wrong thing: one split `main.tex` on a marker string that does not
exist, so answer-key pages were counted as extras and the total still looked
plausible; another validated the seeds a `--preview` had drawn rather than the
ones the build actually wrote.

So the rule here is that **a check which examined nothing fails**. Every check
reports how many items it looked at, and a count of zero is an error rather
than a silent pass. Missing markers, missing files and empty sections are
failures, not skips.

    python tools/verify_run.py <job-dir> <output-dir> [--against <earlier-out-dir> ...]

Exits 0 only if every check passed.
"""

import argparse
import collections
import os
import pathlib
import re
import sys

from checkit_printit import publication as pub_mod
from checkit_printit import roster as roster_mod
from checkit_printit import seating as seating_mod

SKILLPAGE = re.compile(r"skillpage\{([A-Za-z0-9._-]+)/[^}]*?v(\d+)\}")
SETNAME = re.compile(r"setname\{([^}]*)\}")
PAGES = re.compile(r"Output written on .*?\((\d+) pages")

MARK_STUDENTS = "% ---- student copies"
MARK_EXTRAS = "% ---- extras"
MARK_KEYS = "% ---- answer keys"


class Report:
    """Pass/fail accumulator. A check that examined nothing is a failure."""

    def __init__(self):
        self.rows = []

    def record(self, name, examined, problems, detail=""):
        if examined == 0:
            self.rows.append(("VACUOUS", name, "examined nothing", detail))
        elif problems:
            self.rows.append(("FAIL", name, f"{len(problems)} of {examined}", detail))
        else:
            self.rows.append(("ok", name, f"{examined} checked", detail))
        return not problems and examined > 0

    def error(self, name, detail):
        self.rows.append(("FAIL", name, "could not run", detail))

    def not_applicable(self, name, why):
        """Structurally nothing to check -- a lone student has no neighbour.

        Kept distinct from "ok" on purpose: a check that examined nothing must
        never read as one that passed.
        """
        self.rows.append(("n/a", name, "nothing to check", why))

    def print(self):
        width = max(len(r[1]) for r in self.rows)
        for status, name, count, detail in self.rows:
            line = f"  {status:8} {name:<{width}}  {count}"
            if detail:
                line += f"\n           {detail}"
            print(line)
        bad = [r for r in self.rows if r[0] not in ("ok", "n/a")]
        skipped = [r for r in self.rows if r[0] == "n/a"]
        passed = len(self.rows) - len(bad) - len(skipped)
        print()
        summary = f"{passed} passed, {len(bad)} failed"
        if skipped:
            summary += f", {len(skipped)} not applicable"
        print(summary)
        return not bad


def sections(text, report, want_extras, want_keys):
    """Split main.tex on its markers, failing loudly if one is absent."""
    for marker, needed in [(MARK_STUDENTS, True),
                           (MARK_EXTRAS, want_extras),
                           (MARK_KEYS, want_keys)]:
        if needed and marker not in text:
            report.error("section markers", f"{marker!r} is not in main.tex")
            return None
    body = text.split(MARK_STUDENTS, 1)[1] if MARK_STUDENTS in text else text
    students, rest = (body.split(MARK_EXTRAS, 1) + [""])[:2] if want_extras else (body, "")
    if want_keys:
        source = rest if want_extras else students
        head, keys = source.split(MARK_KEYS, 1)
        if want_extras:
            rest = head
        else:
            students = head
    else:
        keys = ""
    report.record("section markers", 3 if want_keys else 2, [], "")
    return students, rest, keys


def handouts(chunk):
    """Every `\\setname` and the skill pages that follow it, in order."""
    out = []
    current = None
    for line in chunk.splitlines():
        m = SETNAME.search(line)
        if m:
            current = (m.group(1), [])
            out.append(current)
            continue
        m = SKILLPAGE.search(line)
        if m and current is not None:
            current[1].append((m.group(1), int(m.group(2))))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("job_dir")
    ap.add_argument("out_dir")
    ap.add_argument("--against", action="append", default=[],
                    help="an earlier output folder whose seeds must not recur")
    args = ap.parse_args()

    job = pathlib.Path(args.job_dir)
    out = pathlib.Path(args.out_dir)
    report = Report()

    for f in ["main.tex", "main.pdf", "main.log"]:
        if not (out / f).is_file():
            report.error("output files", f"{out / f} is missing")
            report.print()
            return 1
    report.record("output files", 3, [], "")

    # The job files are inputs to this check, so a bad one is a failed check
    # rather than a traceback -- the operator needs the other rows too.
    try:
        publication = pub_mod.load(str(job / "publication.toml"))
        roster = roster_mod.apply_selection_modes(
            roster_mod.load(publication.roster_path),
            simply_print=publication.simply_print,
            default_when_missing=publication.default_when_missing,
            append_for_everyone=publication.append_for_everyone,
        )
        chart = (seating_mod.load(publication.seating_path)
                 if publication.seating_path else None)
    except (OSError, pub_mod.PublicationError, roster_mod.RosterError,
            seating_mod.SeatingError) as exc:
        report.error("the job files load", str(exc))
        report.print()
        return 1
    report.record("the job files load", 1, [], "")
    text = (out / "main.tex").read_text(encoding="utf-8", errors="replace")

    want_extras = bool(publication.extras)
    want_keys = bool(publication.keys)
    split = sections(text, report, want_extras, want_keys)
    if split is None:
        report.print()
        return 1
    student_chunk, extras_chunk, keys_chunk = split

    # ---- every student got exactly what the roster says
    printed = dict(handouts(student_chunk))
    problems = []
    for student in roster:
        got = printed.get(student.name)
        if got is None:
            problems.append(f"{student.name} is not in the PDF")
        elif sorted(s for s, _ in got) != sorted(student.skills):
            problems.append(f"{student.name}: wanted {sorted(student.skills)}, "
                            f"got {sorted(s for s, _ in got)}")
    report.record("students match the roster", len(list(roster)), problems,
                  "; ".join(problems[:3]))

    # ---- extras
    if want_extras:
        ex = [p for _, pages in handouts(extras_chunk) for p in pages]
        counted = collections.Counter(slug for slug, _ in ex)
        problems = []
        for extra in publication.extras:
            if counted[extra.skill] != extra.copies:
                problems.append(f"{extra.skill}: asked {extra.copies}, "
                                f"got {counted[extra.skill]}")
        report.record("extras", len(publication.extras), problems,
                      "; ".join(problems))

    # ---- keys: one page per distinct paper actually handed out
    if want_keys:
        used = {p for _, pages in handouts(student_chunk) for p in pages}
        used |= {p for _, pages in handouts(extras_chunk) for p in pages}
        key_pages = set(SKILLPAGE.findall(keys_chunk))
        key_pages = {(s, int(v)) for s, v in key_pages}
        missing = used - key_pages
        report.record("a key for every paper printed", len(used),
                      sorted(missing)[:5], f"{len(key_pages)} key pages")

    # ---- no two people at one table hold the same paper
    if chart:
        seats = list(chart)
        problems = []
        pairs = 0
        for a, b in zip(seats, seats[1:]):
            if a.group != b.group:
                continue
            pairs += 1
            shared = set(printed.get(a.name, [])) & set(printed.get(b.name, []))
            if shared:
                problems.append(f"{a.name} and {b.name} share {sorted(shared)}")
        if pairs == 0:
            report.not_applicable("neighbours hold different papers",
                                  "no two seats are adjacent in this chart")
        else:
            report.record("neighbours hold different papers", pairs, problems,
                          "; ".join(problems[:3]))

    # ---- nothing reused from an earlier run
    if args.against:
        mine = collections.defaultdict(set)
        for slug, seed in SKILLPAGE.findall(text):
            mine[slug].add(int(seed))
        problems = []
        examined = 0
        for earlier in args.against:
            path = pathlib.Path(earlier) / "main.tex"
            if not path.is_file():
                report.error("no seed reused", f"{path} is missing")
                continue
            prior = collections.defaultdict(set)
            for slug, seed in SKILLPAGE.findall(
                    path.read_text(encoding="utf-8", errors="replace")):
                prior[slug].add(int(seed))
            for slug, seeds in mine.items():
                examined += len(seeds)
                for s in sorted(seeds & prior.get(slug, set())):
                    problems.append(f"{slug} v{s} also in {pathlib.Path(earlier).name}")
        report.record("no seed reused", examined, problems, "; ".join(problems[:5]))

    # ---- the compile actually succeeded
    log = (out / "main.log").read_text(encoding="utf-8", errors="replace")
    errors = [l.strip() for l in log.splitlines() if l.startswith("!")]
    pages = PAGES.search(log)
    if not pages:
        report.error("clean compile", "main.log has no 'Output written' line")
    else:
        report.record("clean compile", 1, errors,
                      f"{pages.group(1)} pages, {len(errors)} pdflatex errors")

    print(f"job  {job}")
    print(f"out  {out}")
    print()
    return 0 if report.print() else 1


if __name__ == "__main__":
    sys.exit(main())
