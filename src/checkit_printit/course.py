"""Where a course's state lives between print jobs.

A job folder resolves its roster relative to itself, so every job used to
carry its own copy. Three copies of the same forty-eight students existed on
one machine, and a student who dropped had to be remembered and re-applied at
the next copy. Nothing detected the drift, because three files that disagree
are three valid files.

So the things that outlive a job -- who exists, where they sit, what is open
for retake, which form to talk to, what has been printed -- live in one place
and a job names it.

    ~/CheckItPrintIt/courses/MAT 106/
    |-- course.toml         identity, and the bank it prints from
    |-- roster.toml         every student, dropped ones included
    |-- seating.toml        groups and desks; the print list
    |-- availability.toml   skills open for retake, and the next assessment
    |-- form.toml           form id and item ids
    |-- record.db           what was printed, to whom, at which seed
    `-- secrets/            credentials, kept apart from configuration

**One course folder need not be one course.** An instructor may run both
sections of MAT 106 from a single folder, with one form and `section` as a
roster field. Another may make "MAT 106 820" and "MAT 106 830" and keep
them wholly apart -- a separate form, seating chart, availability list and
print record for each. Both are supported, neither is the default, and
nothing derives the directory name from the course code: it is named by
whoever makes it.

Outside every repository, always: these files carry names, student ids and
email addresses.
"""

import os
import shutil

COURSES = "courses"
CONFIG = "course.toml"
SECRETS = "secrets"

#: Written by `init`, read by everything else.
FILENAMES = {
    "roster": "roster.toml",
    "seating": "seating.toml",
    "availability": "availability.toml",
    "form": "form.toml",
    "record": "record.db",
    "room": "room.json",
}


class CourseError(Exception):
    pass


def default_root():
    """Where courses live.

    Beside the job folders and the printed output, under one root that is
    deliberately not a repository. `CHECKIT_PRINTIT_HOME` moves all three
    together, which is what a second machine or a test needs.
    """
    home = os.environ.get("CHECKIT_PRINTIT_HOME")
    if home:
        return os.path.join(home, COURSES)
    return os.path.join(os.path.expanduser("~"), "CheckItPrintIt", COURSES)


def path_for(name, root=None):
    safe = str(name).strip().rstrip(". ")
    if not safe or safe in (".", "..") or os.path.sep in safe or "/" in safe:
        raise CourseError(
            f"{name!r} is not usable as a course name -- it becomes a "
            f"directory, so no slashes and no dots on their own."
        )
    return os.path.join(root or default_root(), safe)


def exists(name, root=None):
    return os.path.isfile(os.path.join(path_for(name, root), CONFIG))


def file_in(name, which, root=None):
    try:
        filename = FILENAMES[which]
    except KeyError:
        raise CourseError(f"a course has no {which!r}.") from None
    return os.path.join(path_for(name, root), filename)


CONFIG_TEMPLATE = '''# This course. Everything here outlives a single print job.
#
# A job's publication.toml points here from inside its own [course] table,
# rather than carrying its own copies of the roster and seating chart:
#
#     [course]
#     name   = "MAT 106"     # what prints in the header
#     folder = "{name}"      # this directory
#
# `folder` is a key in that table, not a table of its own, because a
# publication file already has a [course] table and TOML refuses a
# duplicate.
#
# Nothing forces one folder per course. Make one per section instead if
# you would rather keep two rosters, two forms and two records apart.

name      = "{name}"
code      = "{code}"
semester  = ""
professor = ""

[bank]
path = "{bank}"
'''

AVAILABILITY_TEMPLATE = '''# Which skills are open for retake, and what the next assessment is.
#
# Descriptions are not here -- they come from the bank's bank.xml, which is
# already the single source for the printed skill headers. A second copy is
# how they drift.
#
#   name    what it is called, e.g. "Skill Checkpoint Redo"
#   date    when it happens, 2026-09-18
#   due     when the form closes, 2026-09-17T23:59:00
#   choose  how many skills a student may pick; 0 means any number
#   limit   at most | at least | exactly
#   skills  the slugs open for retake
#
# Set them with `checkit-printit skills set` and `skills open`, or by hand.

[assessment]
name   = ""
date   = ""
due    = ""
choose = 0
limit  = "at most"

skills = []
'''


def bank_for(name, root=None):
    """The bank this course prints from, or None.

    None is a normal state rather than a failure: a course can exist before
    it is pointed at a bank, and the views that do not need one still load.

    One function because there were two -- the CLI's `_bank_for` and the web
    app's `Course.bank` -- which is the shape of bug this codebase keeps
    finding late.
    """
    import tomllib
    from .bank import Bank, BankError
    here = path_for(name, root)
    config = os.path.join(here, CONFIG)
    if not os.path.isfile(config):
        return None
    with open(config, "rb") as f:
        declared = str(tomllib.load(f).get("bank", {}).get("path", "")).strip()
    if not declared:
        return None
    try:
        return Bank(os.path.normpath(os.path.join(here, declared)))
    except BankError:
        return None


#: The scalars at the top of `course.toml`, in the order written.
IDENTITY = ("name", "code", "semester", "professor")


def identity(name, root=None):
    """The four header scalars, each defaulting to "".

    `semester` and `professor` print in the top right corner of every
    paper, via `\\date` and `\\author`, and the template creates them
    empty.
    """
    import tomllib
    config = os.path.join(path_for(name, root), CONFIG)
    if not os.path.isfile(config):
        return {k: "" for k in IDENTITY}
    with open(config, "rb") as f:
        raw = tomllib.load(f)
    return {k: str(raw.get(k, "") or "") for k in IDENTITY}


def save_identity(name, fields, root=None):
    """Set the header scalars, leaving the rest of the file alone.

    A line rewrite rather than a dump, because `course.toml` is mostly a
    comment explaining itself, with `[bank]` underneath. Regenerating the
    file from its values would throw both away.

    This exists because there was no way to set these at all. The
    template writes `semester = ""` and `professor = ""`, nothing ever
    filled them, and the first run built entirely through the web app --
    2026-10-19 -- printed with an empty corner. The runs before it only
    had a semester and a professor because those were typed into a
    publication by hand.
    """
    config = os.path.join(path_for(name, root), CONFIG)
    if not os.path.isfile(config):
        raise CourseError(f"{config} does not exist.")
    with open(config, encoding="utf-8") as f:
        lines = f.read().splitlines()

    wanted = {k: str(fields.get(k, "")).strip()
              for k in IDENTITY if k in fields}
    if not wanted:
        return identity(name, root)

    seen = set()
    out = []
    for line in lines:
        key = line.split("=", 1)[0].strip() if "=" in line else ""
        # Column zero only, so a key sitting inside some other table is
        # left where it is: rewriting it would un-indent it and hand it
        # to whichever table it was under.
        #
        # A `#` test used to be here too and was dead -- a mutation pass
        # showed no test could tell whether it was there. The commented
        # example in the header is `#     name   = "MAT 106"`, whose key
        # splits as `#     name` and never matches anything in IDENTITY.
        if key in wanted and not line.startswith((" ", "\t")):
            out.append(f'{key:<9} = "{_escape(wanted[key])}"')
            seen.add(key)
        else:
            out.append(line)

    missing = [k for k in IDENTITY if k in wanted and k not in seen]
    if missing:
        # Nothing to rewrite, so insert above `[bank]` -- where the
        # template puts them -- rather than at the end, underneath it,
        # where they would belong to that table instead.
        at = next((i for i, l in enumerate(out) if l.startswith("[bank]")),
                  len(out))
        for k in reversed(missing):
            out.insert(at, f'{k:<9} = "{_escape(wanted[k])}"')

    with open(config, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")
    return identity(name, root)


def _escape(value):
    return value.replace("\\", "\\\\").replace('"', '\\"')


def init(name, bank="", root=None, adopt=None):
    """Create a course. Returns (path, notes).

    `adopt` names a job folder whose roster and seating are copied in, because
    a working course already has both and nobody should retype forty-eight
    students. What it copies is reported rather than assumed: an adopted
    roster carries display names and no ids, so the class list imported next
    has to reconcile against it.
    """
    path = path_for(name, root)
    if os.path.isfile(os.path.join(path, CONFIG)):
        raise CourseError(f"{path} already exists.")
    os.makedirs(os.path.join(path, SECRETS), exist_ok=True)
    notes = []

    with open(os.path.join(path, CONFIG), "w", encoding="utf-8") as f:
        f.write(CONFIG_TEMPLATE.format(
            name=name, code=name, bank=bank.replace("\\", "/")))

    for which, source_name in (("roster", "roster.toml"),
                               ("seating", "seating.toml")):
        target = os.path.join(path, FILENAMES[which])
        source = os.path.join(adopt, source_name) if adopt else None
        if source and os.path.isfile(source):
            shutil.copy(source, target)
            notes.append(f"adopted {which} from {source}")
        elif adopt:
            notes.append(f"no {source_name} in {adopt}; left empty")

    if not os.path.exists(os.path.join(path, FILENAMES["availability"])):
        with open(os.path.join(path, FILENAMES["availability"]), "w",
                  encoding="utf-8") as f:
            f.write(AVAILABILITY_TEMPLATE)

    adopted_roster = os.path.join(path, FILENAMES["roster"])
    if adopt and os.path.isfile(adopted_roster):
        # Asked, not assumed. This said every adopted roster carries
        # display names and no ids, which is true of one built from a
        # spreadsheet and false of one a class list has been imported
        # into -- and the first real course it ran against had a
        # Banner id and an email for all forty-five, so the advice was
        # to go and fix something that was not broken. Wrong
        # instructions in a tool's own output are worse than none: the
        # import it recommends would have been against a class list
        # older than the roster, which resurrects anybody who left.
        try:
            from .roster import load as _load_roster
            people = _load_roster(adopted_roster)
        except Exception:                            # noqa: BLE001
            people = None
        if people is not None:
            thin = [s for s in people if not (s.sid or s.alt_id or s.email)]
            if thin:
                notes.append(
                    f"{len(thin)} of {len(people)} adopted students have a "
                    f"name and no id -- import a class list to match on "
                    f"those names and fill the rest in")
    return path, notes


def newest_job(root=None):
    """The most recently modified job folder, to offer as the thing to adopt."""
    base = os.path.dirname(root or default_root())
    jobs = os.path.join(base, "jobs")
    if not os.path.isdir(jobs):
        return None
    candidates = [
        os.path.join(jobs, d) for d in os.listdir(jobs)
        if os.path.isfile(os.path.join(jobs, d, "roster.toml"))
    ]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)
