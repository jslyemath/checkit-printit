"""What *this* print run wants.

The settings that used to be named cells in a spreadsheet. Plain data, versioned
with the course, read by the tool and never executed.
"""

import dataclasses
import os
import tomllib


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

    bank_path: str = ""
    roster_path: str = ""
    seating_path: str = ""

    # what to print
    keys: bool = True
    key_copies: int = 1
    names: bool = True
    extras: tuple = ()

    # which versions
    seeds: dict = dataclasses.field(default_factory=dict)   # version -> seed
    variants: dict = dataclasses.field(default_factory=dict)  # slug -> variant

    # selection overrides
    simply_print: tuple = ()
    default_when_missing: tuple = ()
    append_for_everyone: tuple = ()

    @property
    def full_title(self):
        return " ".join(p for p in (self.title, self.date) if p).strip()


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

    extras = tuple(
        Extra(skill=e["skill"], copies=int(e.get("copies", 1)))
        for e in raw.get("extras", [])
    )
    for extra in extras:
        if extra.copies < 1:
            raise PublicationError(
                f"extras for {extra.skill}: copies must be at least 1, got {extra.copies}."
            )

    pub = Publication(
        course=course.get("name", ""),
        semester=course.get("semester", ""),
        professor=course.get("professor", ""),
        title=course.get("title", ""),
        date=str(course.get("date", "")),
        bank_path=resolve(bank.get("path", "")),
        roster_path=resolve(raw.get("roster", {}).get("path", "")),
        seating_path=resolve(raw.get("seating", {}).get("path", "")),
        keys=bool(print_opts.get("keys", True)),
        key_copies=int(print_opts.get("key_copies", 1)),
        names=bool(print_opts.get("names", True)),
        extras=extras,
        seeds={str(k): int(v) for k, v in (raw.get("seeds") or {}).items()},
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

# Pin a version to a seed, so a reprint is exact. Omit to choose at random
# from the printable range.
# [seeds]
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
