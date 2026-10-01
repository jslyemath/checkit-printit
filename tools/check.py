"""Every check that has to be green, in one exit code.

Written after `pytest -q | tail && git commit` committed and pushed a suite
with six failures in it. A pipeline reports its *last* command's exit code,
so the `&&` saw `tail` succeed. That footgun is listed in CLAUDE.md, had
been read that morning, and still landed a red commit.

The guard against it is not discipline. It is one short command whose exit
code is the whole answer -- and **short output is part of the design**: a
page of pytest dots is what makes people reach for `| tail` in the first
place. One line per check, and detail only for what failed.

    ./.venv/Scripts/python.exe tools/check.py
    ./.venv/Scripts/python.exe tools/check.py --quick   # skip the platform

A check that examined nothing fails, the same rule `verify_run.py` is built
on: a pytest run that collected no tests is a broken invocation, not a
clean one, and it exits 0 often enough to be worth refusing.
"""

import argparse
import os
import re
import subprocess
import sys
import time

TOOLS = os.path.dirname(os.path.abspath(__file__))
PRINTIT = os.path.dirname(TOOLS)
CHECKIT = os.path.join(os.path.dirname(PRINTIT), "checkit")


def venv_python():
    """printit's venv, which has both packages installed editable.

    Not `sys.executable`: this is run by hand as often as by a hook, and
    the system Python has neither package. Falling back to it silently
    would collect zero tests and report a clean run.
    """
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        path = os.path.join(PRINTIT, ".venv", *rel)
        if os.path.isfile(path):
            return path
    return None


class Result:
    def __init__(self, name, ok, detail, output="", seconds=0.0):
        self.name = name
        self.ok = ok
        self.detail = detail
        self.output = output
        self.seconds = seconds


def run(name, argv, cwd, counts_tests=True):
    start = time.monotonic()
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, text=True)
    except OSError as exc:
        return Result(name, False, f"could not run: {exc}")
    took = time.monotonic() - start
    out = (proc.stdout or "") + (proc.stderr or "")

    if counts_tests:
        passed = re.search(r"(\d+) passed", out)
        failed = re.search(r"(\d+) failed", out)
        n = int(passed.group(1)) if passed else 0
        # Exit code first, then "did it look at anything". Both have to
        # hold: pytest exits 5 on an empty collection, but a mistyped path
        # or a conftest that skips everything can still come back 0.
        if proc.returncode != 0:
            why = f"{failed.group(1)} failed" if failed else \
                  f"exit {proc.returncode}"
            return Result(name, False, why, out, took)
        if n == 0:
            return Result(name, False, "collected no tests", out, took)
        return Result(name, True, f"{n} passed", out, took)

    if proc.returncode != 0:
        return Result(name, False, f"exit {proc.returncode}", out, took)
    problems = re.search(r"(\d+) problem", out)
    if problems is None:
        return Result(name, False, "said nothing about problems", out, took)
    return Result(name, True, f"{problems.group(1)} problems", out, took)


def failing_lines(output, limit=12):
    """The lines worth seeing, so nobody has to re-run it to find out.

    Which tests failed beats what the assertion said: the names are what
    you act on, and a `-q` run prints them last, so taking lines in
    document order fills the budget with `E` lines from the first failure
    and never reaches the summary.
    """
    lines = output.splitlines()
    for prefixes in (("FAILED", "ERROR"), ("  FAIL", "E   ")):
        keep, seen = [], set()
        for line in lines:
            if line.startswith(prefixes) and line not in seen:
                seen.add(line)
                keep.append(line)
        if keep:
            extra = len(keep) - limit
            keep = keep[:limit]
            if extra > 0:
                keep.append(f"... and {extra} more")
            return keep
    return lines[-limit:]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--quick", action="store_true",
                        help="skip the platform suite, which is the slow one")
    args = parser.parse_args()

    python = venv_python()
    if python is None:
        print("no venv at checkit-printit/.venv -- nothing would import")
        return 1

    checks = [
        ("printit tests", [python, "-m", "pytest", "-q"], PRINTIT, True),
        ("audit", [python, os.path.join(TOOLS, "audit.py")], PRINTIT, False),
    ]
    if not args.quick:
        if os.path.isdir(os.path.join(CHECKIT, "dashboard", "tests")):
            checks.append(("checkit tests",
                           [python, "-m", "pytest", "dashboard/tests", "-q"],
                           CHECKIT, True))
        else:
            print(f"note: no platform checkout at {CHECKIT}, so its tests "
                  f"were not run")

    width = max(len(name) for name, *_ in checks)
    results = []
    for name, argv, cwd, counts in checks:
        result = run(name, argv, cwd, counts)
        results.append(result)
        mark = "ok  " if result.ok else "FAIL"
        print(f"  {mark}  {name:<{width}}  {result.detail}"
              f"   ({result.seconds:.0f}s)")

    bad = [r for r in results if not r.ok]
    for result in bad:
        print()
        print(f"--- {result.name} ---")
        for line in failing_lines(result.output):
            print(line)

    print()
    print("all clear" if not bad else f"{len(bad)} check(s) failed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
