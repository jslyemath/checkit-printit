"""What *this* print run wants.

The settings that used to be named cells in a spreadsheet. Plain data, versioned
with the course, read by the tool and never executed.
"""

import dataclasses
import os
import tomllib

from . import course as course_mod


class PublicationError(Exception):
    pass


@dataclasses.dataclass
class Extra:
    skill: str
    copies: int = 1


@dataclasses.dataclass
class Publication:
    # course identity, straight into the LaTeX header
    course: str = ""
    semester: str = ""
    professor: str = ""
    title: str = ""
    date: str = ""

    # where this was read from, so a manifest can record its fingerprint
    source_path: str = ""

    #: the course folder this job belongs to, when it names one.
    #: `course` above is the printed header string, a different thing.
    course_folder: str = ""
    bank_path: str = ""
    roster_path: str = ""
    seating_path: str = ""

    # what to print
    keys: bool = True
    key_copies: int = 1
    names: bool = True
    extras: tuple = ()

    # which versions
    #
    # `seeds` pins a letter across every skill in the run, which only means
    # something when there is one skill. `skill_seeds` pins per skill, which is
    # what naming one paper needs: two skills that went out as 755 and 821
    # cannot both be "version A is 755".
    seeds: dict = dataclasses.field(default_factory=dict)        # version -> seed
    skill_seeds: dict = dataclasses.field(default_factory=dict)  # slug -> {version: seed}
    variants: dict = dataclasses.field(default_factory=dict)     # slug -> variant

    # selection overrides
    simply_print: tuple = ()
    default_when_missing: tuple = ()
    append_for_everyone: tuple = ()

    @property
    def full_title(self):
        return " ".join(p for p in (self.title, self.date) if p).strip()


def _course_bank(name):
    """The bank a course prints from, when the job does not say."""
    if not name:
        return ""
    config = os.path.join(course_mod.path_for(name), course_mod.CONFIG)
    if not os.path.isfile(config):
        return ""
    with open(config, "rb") as f:
        raw = tomllib.load(f)
    declared = str(raw.get("bank", {}).get("path", "")).strip()
    if not declared:
        return ""
    return os.path.normpath(
        os.path.join(course_mod.path_for(name), declared))


def load(path):
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    base = os.path.dirname(os.path.abspath(path))

    def resolve(value):
        """Paths are relative to the publication file, not the shell's cwd.

        A publication file lives beside the course it describes, and is meant to
        work whichever directory it is invoked from.
        """
        if not value:
            return ""
        return os.path.normpath(os.path.join(base, value))

    course = raw.get("course", {})
    bank = raw.get("bank", {})
    print_opts = raw.get("print", {})

    # A job may name a course instead of carrying copies of the roster and
    # the seating chart. An explicit path still wins, so every job folder
    # written before courses existed keeps working untouched.
    #
    # It is a `folder` key inside [course], not a [course] table of its
    # own: this file already has one, and TOML refuses a duplicate.
    space = str(course.get("folder", "")).strip()
    if space and not course_mod.exists(space):
        raise PublicationError(
            f"{path}: [course] folder = {space!r} does not exist at "
            f"{course_mod.path_for(space)}. Create it with "
            f"`checkit-printit course init {space!r}`."
        )

    def from_course(which):
        return course_mod.file_in(space, which) if space else ""

    def either(declared, which):
        """An explicit path, else the course's, else nothing."""
        if declared:
            return resolve(declared)
        return from_course(which)

    extras = tuple(
        Extra(skill=e["skill"], copies=int(e.get("copies", 1)))
        for e in raw.get("extras", [])
    )
    for extra in extras:
        if extra.copies < 1:
            raise PublicationError(
                f"extras for {extra.skill}: copies must be at least 1, got {extra.copies}."
            )

    # [seeds] A = 451          -> {"A": 451}          values are ints
    # [seeds.W1] A = 451       -> {"W1": {"A": 451}}  values are tables
    # TOML tells the two apart for us, so both spellings read cleanly. Mixing
    # them in one file is refused rather than guessed at.
    raw_seeds = raw.get("seeds") or {}
    nested = {k: v for k, v in raw_seeds.items() if isinstance(v, dict)}
    flat = {k: v for k, v in raw_seeds.items() if not isinstance(v, dict)}
    if nested and flat:
        raise PublicationError(
            f"{path}: [seeds] mixes {sorted(flat)} pinned for every skill with "
            f"{sorted(nested)} pinned per skill. Pick one form."
        )
    flat_seeds = {str(k): int(v) for k, v in flat.items()}
    skill_seeds = {
        str(slug): {str(k): int(v) for k, v in table.items()}
        for slug, table in nested.items()
    }

    pub = Publication(
        source_path=os.path.abspath(path),
        course=course.get("name", ""),
        semester=course.get("semester", ""),
        professor=course.get("professor", ""),
        title=course.get("title", ""),
        date=str(course.get("date", "")),
        bank_path=resolve(bank.get("path", "")) or _course_bank(space),
        course_folder=space,
        roster_path=either(raw.get("roster", {}).get("path", ""), "roster"),
        seating_path=either(raw.get("seating", {}).get("path", ""), "seating"),
        keys=bool(print_opts.get("keys", True)),
        key_copies=int(print_opts.get("key_copies", 1)),
        names=bool(print_opts.get("names", True)),
        extras=extras,
        seeds=flat_seeds,
        skill_seeds=skill_seeds,
        variants={str(k): str(v) for k, v in (raw.get("variants") or {}).items()},
        simply_print=tuple(raw.get("selection", {}).get("simply_print", [])),
        default_when_missing=tuple(raw.get("selection", {}).get("default_when_missing", [])),
        append_for_everyone=tuple(raw.get("selection", {}).get("append_for_everyone", [])),
    )

    if not pub.bank_path:
        raise PublicationError(f"{path}: [bank] path is required.")
    if not os.path.isdir(pub.bank_path):
        raise PublicationError(f"{path}: bank path {pub.bank_path!r} does not exist.")
    if pub.keys and pub.key_copies < 1:
        raise PublicationError(f"{path}: key_copies must be at least 1 when keys are on.")
    return pub


TEMPLATE = '''# What this print run wants. Paths are relative to this file.

[course]
name      = "MAT 106"
semester  = "Fall 2026"
professor = "Slye"
title     = "Skill Checkpoint"
date      = "2026-09-15"

[bank]
path = "../mat-106-checkit"

[roster]
path = "roster.toml"

[seating]
path = "seating.toml"

[print]
keys       = true   # answer keys after the student copies
key_copies = 1
names      = true   # false prints a ruled blank instead of each name

# Force one version of one skill onto a chosen seed; everything unpinned is
# drawn as usual. To reproduce a whole run instead, re-run it with the seed it
# reported -- that is what the run seed is for.
# [seeds.W1]
# A = 451
# B = 802

# Ask for the case the course has reached, for outcomes declaring variants.
# [variants]
# D2 = "no_repeating"

# [selection]
# simply_print         = []   # everyone gets exactly these; choices ignored
# default_when_missing = []   # for students who chose nothing
# append_for_everyone  = []   # added on top of whatever each student chose

# Spare copies, appended at the end with a blank name line.
# [[extras]]
# skill  = "W1"
# copies = 3
'''
