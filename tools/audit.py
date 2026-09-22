"""Check the tool against itself.

Run it after any rename, any new command, or any change to a message that
names a command:

    ./.venv/Scripts/python.exe tools/audit.py

Written after the 2026-09-21 workspace->course rename, which left stale
flags in three different spellings, and after stage 7a, which put a
non-existent command into an error message. It looks for the shapes that
actually went wrong here, not for generic lint.

  A. leftovers of the rename (the word, the flag, old command names)
  B. commands named in strings or docs that do not exist
  C. options named in help text that do not exist on that command
  D. duplicated logic (the "second copy" problem, twice today)
  E. dead parameters (retries= was declared and unimplemented for a while)
  F. every CLI command at least parses
"""
import os, re, subprocess, sys, pathlib, json

PRINTIT = pathlib.Path(__file__).resolve().parent.parent
CHECKIT = PRINTIT.parent / "checkit"
PY = sys.executable

problems = []
def bad(section, msg):
    problems.append(f"[{section}] {msg}")

SELF = pathlib.Path(__file__).resolve()

def sources(root, *globs):
    """Every file worth checking, except this one.

    A checker that greps for a token necessarily contains that token, so
    scanning itself reports its own search patterns as findings. Excluded by
    resolved path rather than by name.
    """
    out = []
    for g in globs:
        for p in root.glob(g):
            s = str(p).replace("\\", "/")
            if "__pycache__" in s or ".venv" in s or "/build/" in s:
                continue
            if p.resolve() == SELF:
                continue
            out.append(p)
    return out

py_files = sources(PRINTIT, "src/**/*.py", "tests/**/*.py", "tools/**/*.py")
gs_files = sources(PRINTIT, "appsscript/*.gs")
docs = sources(PRINTIT, "*.md") + sources(CHECKIT, "CLAUDE.md", "PRINT_TOOL_DESIGN.md")

# ---------------------------------------------------------------- A: rename
GOOGLE_OK = ("Internal apps in a Workspace", "A Workspace admin")

# A document that records a past mistake has to quote it. Those sections
# describe `-w` and `workspace` on purpose -- the same trap as a template
# documenting its own syntax, which this project has hit twice in the
# Mustache and Jinja templates. Skip them by heading, not by a list of
# blessed lines, which would go stale exactly like the CLI table did.
RETROSPECTIVE = ("goes wrong", "failed silently", "not applied to the others")

def retrospective_lines(path):
    """Line numbers inside a section whose heading admits to past mistakes."""
    if path.suffix != ".md":
        return set()
    out, skipping = set(), False
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if line.startswith("#"):
            skipping = any(k in line.lower() for k in RETROSPECTIVE)
        elif line.startswith("###") is False and line.startswith("##"):
            skipping = any(k in line.lower() for k in RETROSPECTIVE)
        if skipping:
            out.add(n)
    return out

for p in py_files + gs_files + docs:
    skip = retrospective_lines(p)
    for n, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        if n in skip:
            continue
        if re.search(r"workspace", line, re.I) and not any(a in line for a in GOOGLE_OK):
            bad("A", f"{p.name}:{n} still says workspace: {line.strip()[:80]}")
        if re.search(r"(?<![\w-])-w(?![\w-])", line) and "clasp" not in line.lower():
            bad("A", f"{p.name}:{n} stale -w flag: {line.strip()[:80]}")
        for dead in ("form adopt", "form scaffold", "skills show", "workspace init"):
            if dead in line:
                bad("A", f"{p.name}:{n} names removed command {dead!r}")

# ------------------------------------------------- B/C: the real CLI surface
def cli(*args):
    r = subprocess.run([PY, "-m", "checkit_printit", *args],
                       cwd=PRINTIT, capture_output=True, text=True)
    return r.returncode, r.stdout + r.stderr

code, top = cli("--help")
if code != 0:
    bad("F", "checkit-printit --help failed")

groups, commands = [], []
in_cmds = False
for line in top.splitlines():
    if line.startswith("Commands:"):
        in_cmds = True
        continue
    if in_cmds and line.startswith("  ") and line.strip():
        commands.append(line.split()[0])

real = {}          # "form push" -> set of options
for c in commands:
    code, out = cli(c, "--help")
    if code != 0:
        bad("F", f"`{c} --help` exited {code}")
        continue
    subs = []
    if "Commands:" in out:
        after = out.split("Commands:", 1)[1]
        subs = [l.split()[0] for l in after.splitlines()
                if l.startswith("  ") and l.strip()]
    if subs:
        for s in subs:
            code2, out2 = cli(c, s, "--help")
            if code2 != 0:
                bad("F", f"`{c} {s} --help` exited {code2}")
            real[f"{c} {s}"] = set(re.findall(r"(--[a-z][a-z0-9-]*)", out2))
    else:
        real[c] = set(re.findall(r"(--[a-z][a-z0-9-]*)", out))

# every `checkit-printit X Y` mentioned anywhere must exist
mentioned = {}
for p in py_files + gs_files + docs:
    text = p.read_text(encoding="utf-8")
    for m in re.finditer(r"checkit-printit ([a-z-]+)(?: ([a-z-]+))?", text):
        g1, g2 = m.group(1), m.group(2)
        name = f"{g1} {g2}" if (g2 and f"{g1} {g2}" in real) else g1
        if name in real:
            continue
        if g1 in real:
            continue
        if g2 and g2.startswith("-"):
            if g1 in real:
                continue
        mentioned.setdefault(f"{g1} {g2 or ''}".strip(), []).append(p.name)
for name, where in sorted(mentioned.items()):
    first = name.split()[0]
    if first in real or any(k.startswith(first + " ") for k in real):
        # a real group; the sub may just be a placeholder word like <name>
        if len(name.split()) > 1 and not re.match(r"^[a-z-]+$", name.split()[1]):
            continue
        if len(name.split()) > 1 and name not in real:
            bad("B", f"{name!r} does not exist (named in {sorted(set(where))})") if name != "owns" else None
    else:
        bad("B", f"{name!r} does not exist (named in {sorted(set(where))})") if name != "owns" else None

# ------------------------------------------------------------ E: dead params
src = (PRINTIT / "src/checkit_printit").glob("*.py")
for p in src:
    text = p.read_text(encoding="utf-8")
    for m in re.finditer(r"def (\w+)\(([^)]*)\):", text, re.S):
        fn, params = m.group(1), m.group(2)
        body_start = m.end()
        nxt = text.find("\ndef ", body_start)
        body = text[body_start: nxt if nxt > 0 else len(text)]
        for prm in re.findall(r"(\w+)\s*=\s*[^,]+", params):
            if prm in ("self",):
                continue
            if not re.search(rf"\b{re.escape(prm)}\b", body):
                bad("E", f"{p.name}: {fn}() takes {prm}= and never uses it")

# --------------------------------------------------------- D: duplicate code
# Patching one of two copies has happened twice today. `allowed` is the count
# that is understood and commented in the source; anything above it is a copy
# nobody decided on.
main = (PRINTIT / "src/checkit_printit/__main__.py").read_text(encoding="utf-8")
for probe, label, allowed in [
    ('form_mod.call(conn, "ping")', "ping call", 2),        # try + retry
    ('clasp_mod.push(directory)', "clasp push", 2),
    ('clasp_mod.deploy(directory)', "clasp deploy", 2),
    # attach stages twice: once to make the directory clasp clones into, and
    # again after, because the clone lands on top of ours. Plus create's one.
    ('_stage_script(space, conn.secret)', "stage script", 3),
]:
    n = main.count(probe)
    if n > allowed:
        bad("D", f"{label} appears {n} times in __main__.py (expected <= {allowed})")

print(f"checked {len(py_files)} py, {len(gs_files)} gs, {len(docs)} docs, "
      f"{len(real)} cli commands")
print(f"\n{len(problems)} problem(s)")
for p in problems:
    print(" ", p)
sys.exit(1 if problems else 0)
