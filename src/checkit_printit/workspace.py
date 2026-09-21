"""Where a course's state lives between print jobs.

A job folder resolves its roster relative to itself, so every job used to
carry its own copy. Three copies of the same forty-eight students existed on
one machine, and a student who dropped had to be remembered and re-applied at
the next copy. Nothing detected the drift, because three files that disagree
are three valid files.

So the things that outlive a job -- who exists, where they sit, what is open
for retake, which form to talk to, what has been printed -- live in one place
and a job names it.

    ~/CheckItPrintIt/workspaces/MAT 106/
    |-- workspace.toml      course identity and the bank it prints from
    |-- roster.toml         every student, dropped ones included
    |-- seating.toml        groups and desks; the print list
    |-- availability.toml   skills open for retake, and the next assessment
    |-- form.toml           form id and item ids
    |-- record.db           what was printed, to whom, at which seed
    `-- secrets/            credentials, kept apart from configuration

**A workspace is not a course.** One instructor runs both sections of MAT 106
from a single workspace with one form and `section` as a roster field; another
wants each section separate. The directory is named by whoever makes it.

Outside every repository, always: these files carry names, student ids and
email addresses.
"""

import os
import shutil

WORKSPACES = "workspaces"
CONFIG = "workspace.toml"
SECRETS = "secrets"

#: Written by `init`, read by everything else.
FILENAMES = {
    "roster": "roster.toml",
    "seating": "seating.toml",
    "availability": "availability.toml",
    "form": "form.toml",
    "record": "record.db",
}


class WorkspaceError(Exception):
    pass


def default_root():
    """Where workspaces live.

    Beside the job folders and the printed output, under one root that is
    deliberately not a repository. `CHECKIT_PRINTIT_HOME` moves all three
    together, which is what a second machine or a test needs.
    """
    home = os.environ.get("CHECKIT_PRINTIT_HOME")
    if home:
        return os.path.join(home, WORKSPACES)
    return os.path.join(os.path.expanduser("~"), "CheckItPrintIt", WORKSPACES)


def path_for(name, root=None):
    safe = str(name).strip().rstrip(". ")
    if not safe or safe in (".", "..") or os.path.sep in safe or "/" in safe:
        raise WorkspaceError(
            f"{name!r} is not usable as a workspace name -- it becomes a "
            f"directory, so no slashes and no dots on their own."
        )
    return os.path.join(root or default_root(), safe)


def exists(name, root=None):
    return os.path.isfile(os.path.join(path_for(name, root), CONFIG))


def file_in(name, which, root=None):
    try:
        filename = FILENAMES[which]
    except KeyError:
        raise WorkspaceError(f"a workspace has no {which!r}.") from None
    return os.path.join(path_for(name, root), filename)


CONFIG_TEMPLATE = '''# This workspace. Everything here outlives a single print job.
#
# A job's publication.toml names this workspace instead of carrying copies:
#
#     [workspace]
#     name = "{name}"

name      = "{name}"
course    = "{course}"
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


def init(name, bank="", root=None, adopt=None):
    """Create a workspace. Returns (path, notes).

    `adopt` names a job folder whose roster and seating are copied in, because
    a working course already has both and nobody should retype forty-eight
    students. What it copies is reported rather than assumed: an adopted
    roster carries display names and no ids, so the class list imported next
    has to reconcile against it.
    """
    path = path_for(name, root)
    if os.path.isfile(os.path.join(path, CONFIG)):
        raise WorkspaceError(f"{path} already exists.")
    os.makedirs(os.path.join(path, SECRETS), exist_ok=True)
    notes = []

    with open(os.path.join(path, CONFIG), "w", encoding="utf-8") as f:
        f.write(CONFIG_TEMPLATE.format(
            name=name, course=name, bank=bank.replace("\\", "/")))

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

    if adopt and os.path.isfile(os.path.join(path, FILENAMES["roster"])):
        notes.append(
            "an adopted roster has display names and no student ids -- import "
            "a class list next, which will match on those names and fill the "
            "rest in"
        )
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
