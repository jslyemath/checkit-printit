"""What a finished run actually drew, written beside the papers.

A run seed reproduces the *process*: give it back and the lottery runs the
same way. That only lands on the same papers if nothing else moved. This file
records the *result* instead, so a reprint survives edits the seed would not --
fixing a misspelt name should not redraw forty-eight students' exercises.

Two of the three sections are checks rather than inputs:

- `[[paper]]` is the input. Replay pins these and draws nothing.
- `variant` on each paper is a checksum. The seed already implies a variant,
  because the bank stores one per seed -- but only for a fixed variants list.
  Adding a case to a generator re-deals about two thirds of the seeds and
  reordering the list re-deals all of them, so a recorded variant is how
  replay notices that the bank no longer means what it meant.
- `[inputs]` hashes say which file moved. They never block a replay: the
  papers come from `[[paper]]`, so a changed roster is worth reporting and
  not worth refusing.
"""

import dataclasses
import datetime
import hashlib
import os
import tomllib

from . import __version__

FILENAME = "manifest.toml"


class ManifestError(Exception):
    pass


def _quote(value):
    out = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{out}"'


def file_digest(path):
    if not path or not os.path.isfile(path):
        return ""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def write(out_dir, publication, run_seed, seeds, bank, slugs):
    """Record the run. `seeds` is {(version, slug): seed}; `slugs` what printed."""
    now = datetime.datetime.now().isoformat(timespec="seconds")
    lines = [
        "# Written by checkit-printit. What this run drew, so it can be",
        "# reprinted exactly: checkit-printit build --replay <this folder>",
        "",
        "[run]",
        f"tool  = {_quote('checkit-printit ' + __version__)}",
        f"built = {_quote(now)}",
        f"seed  = {int(run_seed)}",
        f"title = {_quote(publication.title)}",
        f"date  = {_quote(publication.date)}",
        "",
        "[inputs]",
        f"bank        = {_quote(publication.bank_path)}",
        f"publication = {_quote(file_digest(getattr(publication, 'source_path', '')))}",
        f"roster      = {_quote(file_digest(publication.roster_path))}",
        f"seating     = {_quote(file_digest(publication.seating_path))}",
    ]

    for (version, slug), seed in sorted(seeds.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        if slug not in slugs:
            continue
        lines += [
            "",
            "[[paper]]",
            f"skill   = {_quote(slug)}",
            f"version = {_quote(version)}",
            f"seed    = {int(seed)}",
            f"variant = {_quote(bank.variant(slug, seed) or '')}",
        ]

    # Enough of the bank to notice it moved under a replay.
    for slug in sorted(slugs):
        labels = sorted({bank.variant(slug, s) or ""
                         for s in bank.printable_seeds(slug)})
        labels = [x for x in labels if x]
        try:
            generator = file_digest(bank.outcome(slug).generator_path())
        except Exception:
            generator = ""
        lines += [
            "",
            "[[skill]]",
            f"slug      = {_quote(slug)}",
            "variants  = [" + ", ".join(_quote(x) for x in labels) + "]",
            f"printable = {len(bank.printable_seeds(slug))}",
            f"generator = {_quote(generator)}",
        ]

    path = os.path.join(out_dir, FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def load(folder):
    """Read a manifest from a run folder, or from the file itself."""
    path = folder
    if os.path.isdir(path):
        path = os.path.join(path, FILENAME)
    if not os.path.isfile(path):
        raise ManifestError(
            f"{path} does not exist. A run only has one if it was built by a "
            f"version of this tool that writes them."
        )
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    if not raw.get("paper"):
        raise ManifestError(f"{path} records no papers, so there is nothing to replay.")
    return raw


def pins(raw):
    """{slug: {version: seed}}, ready to hand to the publication."""
    out = {}
    for paper in raw["paper"]:
        out.setdefault(paper["skill"], {})[paper["version"]] = int(paper["seed"])
    return out


def check(raw, bank, publication):
    """Returns (refusals, notes). A refusal means the papers would differ."""
    refusals, notes = [], []

    for paper in raw["paper"]:
        slug, seed = paper["skill"], int(paper["seed"])
        recorded = paper.get("variant", "")
        try:
            current = bank.variant(slug, seed) or ""
        except Exception as exc:                     # slug or seed gone
            refusals.append(f"{slug} v{seed}: {exc}")
            continue
        if current != recorded:
            refusals.append(
                f"{slug} v{seed} was {recorded or '(no variant)'} when this run "
                f"was built and is {current or '(no variant)'} now -- the "
                f"generator's variants list has changed, so this seed is a "
                f"different paper."
            )

    for entry in raw.get("skill", []):
        slug = entry["slug"]
        try:
            labels = sorted({bank.variant(slug, s) or ""
                             for s in bank.printable_seeds(slug)})
        except Exception as exc:
            refusals.append(f"{slug}: {exc}")
            continue
        labels = [x for x in labels if x]
        if labels != list(entry.get("variants", [])):
            notes.append(f"{slug} declared {entry.get('variants')} and now "
                         f"declares {labels}")
        if len(bank.printable_seeds(slug)) != entry.get("printable"):
            notes.append(f"{slug} had {entry.get('printable')} printable seeds "
                         f"and now has {len(bank.printable_seeds(slug))}")

        # A seed is only a paper for as long as the generator is the one that
        # produced it. Absent on manifests written before this was recorded,
        # which replay cannot check and does not pretend to.
        was = entry.get("generator", "")
        if was:
            try:
                now = file_digest(bank.outcome(slug).generator_path())
            except Exception as exc:
                refusals.append(f"{slug}: {exc}")
                continue
            if now and now != was:
                refusals.append(
                    f"{slug}'s generator has changed since this run was "
                    f"built, so its seeds may no longer produce the same "
                    f"exercises. An edit that changed nothing about the "
                    f"output trips this too; build fresh if that is all "
                    f"it was."
                )

    inputs = raw.get("inputs", {})
    for label, path in [("roster", publication.roster_path),
                        ("seating", publication.seating_path),
                        ("publication", getattr(publication, "source_path", ""))]:
        was = inputs.get(label, "")
        now = file_digest(path)
        if was and now and was != now:
            notes.append(f"{label} has changed since this run was built")

    return refusals, notes


def apply(raw, publication):
    """A publication that draws nothing: every paper comes from the record."""
    return dataclasses.replace(publication, seeds={}, skill_seeds=pins(raw))
