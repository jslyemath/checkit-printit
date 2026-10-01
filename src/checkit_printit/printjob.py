"""The draft of one print run, and turning it into a job folder.

The CLI's unit of work is a folder holding `publication.toml`. A GUI has no
folder: an instructor sets options in a form and presses Build. Rather than
giving `build` a second way in, the app **writes the folder and builds it**
-- so there is one entry point, one set of rules, and a folder left behind
that `--replay` can reproduce months later.

Two files, deliberately:

- `<course>/job.toml` is the **draft**. Edited freely, carried between
  visits, meaningless to anyone else.
- `<job folder>/publication.toml` is the **run**. Written at build time and
  never edited, because it is what the manifest's fingerprints refer to.

Copying the first into the second is the moment a draft becomes a record.
"""

import os
import tomllib

from . import course as course_mod

DRAFT = "job.toml"


class PrintJobError(Exception):
    pass


#: What the draft carries. Anything absent falls back to these, so a course
#: that has never had a print job still opens with a usable form.
DEFAULTS = {
    "title": "Skill Checkpoint",
    "date": "",
    "keys": True,
    "key_copies": 1,
    "names": True,
    "simply_print": [],
    "default_when_missing": [],
    "append_for_everyone": [],
    "variants": {},
    "extras": [],
    "overrides": {},
}


def draft_path(space):
    return os.path.join(course_mod.path_for(space), DRAFT)


#: Which table each key is written into, so reading and writing cannot
#: disagree about where something lives. Keys absent here are at the root.
#:
#: Paired deliberately: the first version of this had `save_draft` writing
#: `simply_print` under `[selection]` and `load_draft` looking for it at the
#: root, so a draft naming two skills built a run that printed neither.
IN_TABLE = {
    "simply_print": "selection",
    "default_when_missing": "selection",
    "append_for_everyone": "selection",
    "variants": "variants",
    "overrides": "overrides",
}


def load_draft(space):
    """The draft, with every key present and every table looked in."""
    out = dict(DEFAULTS)
    out["variants"] = {}
    out["extras"] = []
    out["overrides"] = {}
    path = draft_path(space)
    if not os.path.isfile(path):
        return out
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    for key in DEFAULTS:
        table = IN_TABLE.get(key)
        if table is None:
            if key in raw:
                out[key] = raw[key]
        elif table == key:
            # A whole table is the value: [variants], [overrides].
            if isinstance(raw.get(key), dict):
                out[key] = dict(raw[key])
        else:
            block = raw.get(table) or {}
            if key in block:
                out[key] = block[key]
    return out


def _quote(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _list(values):
    return "[" + ", ".join(_quote(v) for v in values) + "]"


def save_draft(space, draft):
    """Write the draft. Its own format; nothing else reads it."""
    merged = dict(load_draft(space))
    merged.update(draft)
    lines = [
        "# The print job being put together for this course.",
        "#",
        "# A draft, not a record: it is edited freely and carried between",
        "# visits. Building copies it into a job folder as publication.toml,",
        "# and that copy is what the manifest's fingerprints refer to.",
        "",
        f"title      = {_quote(merged['title'])}",
        f"date       = {_quote(merged['date'])}",
        f"keys       = {'true' if merged['keys'] else 'false'}",
        f"key_copies = {int(merged['key_copies'])}",
        f"names      = {'true' if merged['names'] else 'false'}",
        "",
        "[selection]",
        f"simply_print         = {_list(merged['simply_print'])}",
        f"default_when_missing = {_list(merged['default_when_missing'])}",
        f"append_for_everyone  = {_list(merged['append_for_everyone'])}",
        "",
    ]
    if merged["variants"]:
        lines.append("[variants]")
        for slug, case in sorted(merged["variants"].items()):
            lines.append(f"{slug} = {_quote(case)}")
        lines.append("")
    if merged["overrides"]:
        lines += [
            "# One student's choices, set by hand, replacing whatever the",
            "# form recorded. Keyed by student id.",
            "[overrides]",
        ]
        for sid, slugs in sorted(merged["overrides"].items()):
            lines.append(f"{_quote(sid)} = {_list(slugs)}")
        lines.append("")
    for extra in merged["extras"]:
        lines += ["[[extras]]",
                  f"skill  = {_quote(extra['skill'])}",
                  f"copies = {int(extra['copies'])}", ""]

    path = draft_path(space)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    return path


def publication_text(space, draft, course_name, semester="", professor=""):
    """The `publication.toml` a job folder gets.

    It names the course rather than carrying copies of the roster and the
    seating chart, so a student who drops is fixed in one place.
    """
    lines = [
        "# Written by printit's web app. One run, as it was built.",
        "#",
        "# Names the course rather than carrying its own roster and seating,",
        "# so a drop is fixed in one place rather than remembered at the",
        "# next copy.",
        "",
        "[course]",
        f"name      = {_quote(course_name)}",
        f"folder    = {_quote(space)}",
    ]
    if semester:
        lines.append(f"semester  = {_quote(semester)}")
    if professor:
        lines.append(f"professor = {_quote(professor)}")
    lines += [
        f"title     = {_quote(draft['title'])}",
        f"date      = {_quote(draft['date'])}",
        "",
        "[print]",
        f"keys       = {'true' if draft['keys'] else 'false'}",
        f"key_copies = {int(draft['key_copies'])}",
        f"names      = {'true' if draft['names'] else 'false'}",
        "",
    ]
    selection = {k: draft[k] for k in
                 ("simply_print", "default_when_missing", "append_for_everyone")
                 if draft[k]}
    if selection:
        lines.append("[selection]")
        for key, values in selection.items():
            lines.append(f"{key} = {_list(values)}")
        lines.append("")
    if draft["variants"]:
        lines.append("[variants]")
        for slug, case in sorted(draft["variants"].items()):
            lines.append(f"{slug} = {_quote(case)}")
        lines.append("")
    for extra in draft["extras"]:
        lines += ["[[extras]]",
                  f"skill  = {_quote(extra['skill'])}",
                  f"copies = {int(extra['copies'])}", ""]
    return "\n".join(lines)


def folder_for(draft, root=None):
    """Where this run's job folder goes.

    Named for the title and date, so two runs on one day with different
    titles do not overwrite each other, and so a folder can be found again
    by what it was.
    """
    from .runner import default_output_root, safe_name
    stem = safe_name(f"{draft['title']} {draft['date']}".strip())
    return os.path.join(root or os.path.join(default_output_root(), "jobs"),
                        stem)


def write_job(space, draft, course_name, semester="", professor="",
              root=None):
    """Create the job folder and its publication.toml. Returns the folder."""
    if not str(draft.get("date", "")).strip():
        raise PrintJobError(
            "the run needs a date: it names the folder, prints on the paper, "
            "and is how a response is matched to an assessment.")
    folder = folder_for(draft, root)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "publication.toml"), "w",
              encoding="utf-8") as f:
        f.write(publication_text(space, draft, course_name, semester,
                                 professor))
    return folder
