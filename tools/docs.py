"""Check what the documentation claims against what the code does.

Written after a sweep found the printit map describing a payload
that had been replaced the same week, in a section that duplicated a
newer one three hundred lines above it. Reading for feel finds the
things that look wrong; it does not find the things that have quietly
*become* wrong, because they still read perfectly.

So each entry here is a claim some document makes, paired with a way
to test it. The claims worth automating are the ones that go stale
without anybody touching the document: a CLI flag added, a macro
renamed, a column migrated, a dependency introduced.

Not a substitute for reading. `CODEBASE_NOTES.md` cannot be checked
this way and neither can a design decision -- what this catches is
drift, not wrongness.

    ./.venv/Scripts/python.exe tools/docs.py
"""

import os
import pathlib
import re
import subprocess
import sys
import tempfile

TOOLS = pathlib.Path(__file__).resolve().parent
PRINTIT = TOOLS.parent
CHECKIT = PRINTIT.parent / "checkit"

problems = []
passed = []


def check(what, ok, detail=""):
    print(f"{'ok   ' if ok else 'STALE'}  {what}"
          f"{'' if ok else '  -- ' + detail}")
    (passed if ok else problems).append(what)


def checked():
    return len(passed)


def python():
    for rel in (("Scripts", "python.exe"), ("bin", "python")):
        path = PRINTIT / ".venv" / rel[0] / rel[1]
        if path.is_file():
            return str(path)
    sys.exit("no venv at checkit-printit/.venv")


def read(path):
    return pathlib.Path(path).read_text(encoding="utf-8")


def cli(*argv):
    return subprocess.run([python(), "-m", "checkit_printit", *argv],
                          capture_output=True, text=True).stdout


def pairs(flags):
    """`--no-x` and `--x` are one flag, documented once."""
    out = set()
    for flag in flags:
        out.add(flag[5:] if flag.startswith("--no-") else flag[2:])
    return out


def main():
    printit_map = read(PRINTIT / "CLAUDE.md")
    readme = read(PRINTIT / "README.md")
    sty = read(PRINTIT / "src/checkit_printit/theme/printit.sty")
    assemble = read(PRINTIT / "src/checkit_printit/assemble.py")
    pyproject = read(PRINTIT / "pyproject.toml")

    platform_map = read(CHECKIT / "CLAUDE.md") if CHECKIT.is_dir() else ""
    design = (read(CHECKIT / "PRINT_TOOL_DESIGN.md")
              if CHECKIT.is_dir() else "")

    # --- the CLI surface
    commands = set(re.findall(r"^  ([a-z]+)\s", cli("--help"), re.M))
    check("there are commands to check", bool(commands))
    if platform_map and "has grown a lot" in platform_map:
        named = set(re.findall(
            r"`([a-z]+)`",
            platform_map.split("has grown a lot")[1].split("\n\n")[0]))
        check("every CLI command is named in checkit/CLAUDE.md",
              commands <= named, f"missing {sorted(commands - named)}")

    # Aliases of the same option are one thing to document; `-o` is
    # listed in the README and `--out` is the same flag.
    aliases = {"out": "-o", "publication": "-p"}
    flags = pairs(set(re.findall(r"(--[a-z-]+)", cli("build", "--help")))
                  - {"--help"})
    missing = {f for f in flags
               if f"--{f}" not in readme and aliases.get(f, "\0") not in readme}
    check("every `build` flag appears in the README",
          not missing, f"missing {sorted(missing)}")

    # --- the theme and the document have to agree, and the map has
    # --- to name what they agree on
    emitted = set(re.findall(r"\\\\(set[a-z]+)\{", assemble))
    check("main_tex emits some macros", bool(emitted))
    undefined = [m for m in emitted
                 if f"newcommand{{\\{m}}}" not in sty
                 and f"providecommand{{\\{m}}}" not in assemble]
    check("every macro main_tex emits is defined in the theme",
          not undefined, str(undefined))
    unmapped = [m for m in emitted if m not in printit_map]
    check("every macro main_tex emits is named in printit/CLAUDE.md",
          not unmapped, str(unmapped))

    # --- the record's shape
    sys.path.insert(0, str(PRINTIT / "src"))
    from checkit_printit import record
    with tempfile.TemporaryDirectory() as d:
        db = record.connect(os.path.join(d, "r.db"))
        columns = {r[1] for r in db.execute("PRAGMA table_info(run)")}
        tables = {r[0] for r in db.execute(
            "SELECT name FROM sqlite_master WHERE type='table'")}
        db.close()
    for column in ("run_no", "graded", "delisted"):
        check(f"`{column}` is documented in printit/CLAUDE.md",
              column not in columns or column in printit_map)
    check("the meta table is documented",
          "meta" not in tables or "last_run_no" in printit_map)

    # --- dependencies
    deps = set(re.findall(r'^\s*"([a-z0-9-]+)[>=@]', pyproject, re.M))
    for dep in sorted(deps - {"click", "jinja2", "openpyxl"}):
        check(f"{dep} is mentioned somewhere in the docs",
              dep in printit_map or dep in readme or dep in platform_map
              or dep in design)

    # --- the design's own cross-references
    if design:
        sections = set(re.findall(r"^### (1[0-9]\.\d+)", design, re.M))
        referenced = set(re.findall(r"see (1[0-9]\.\d+)", design))
        check("every 'see 14.x' points at a section that exists",
              referenced <= sections,
              f"dangling {sorted(referenced - sections)}")

    # --- nothing still presents the payload's older shapes as current
    payload = re.search(r"\\newcommand\{\\cippayload\}\{([^}]*)\}", sty)
    check("the payload is findable in the theme", payload is not None)
    if payload:
        for name, body in (("printit/CLAUDE.md", printit_map),
                           ("README.md", readme),
                           ("checkit/CLAUDE.md", platform_map)):
            stale = [old for old in ("C1-<runseed>", "CIP1*")
                     if old in body]
            check(f"{name} does not present an older payload as current",
                  not stale, str(stale))

    # `check.py` reads "N problem(s)" out of this and refuses a check
    # that never says one -- a run that examined nothing is a broken
    # invocation, not a clean one. So the count is printed either way.
    print(f"\n{len(problems)} problem(s) across {len(problems) + checked()} "
          f"documented claims")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
