"""checkit-printit — turn a bank and a roster into a printable class set."""

import os
import random
import sys

import click

from . import __version__, publication as pub_mod, roster as roster_mod, seating, theme
from . import manifest as manifest_mod
from .assemble import assemble, AssemblyError
from .bank import Bank, BankError
from .compile import compile_pdf, CompileError


def default_output_root():
    """Where builds land unless told otherwise.

    A canonical local place, so the same PDF can be rebuilt months later. Not a
    repository: this is a local record, not a published artefact.
    """
    return os.environ.get("CHECKIT_PRINTIT_HOME") or os.path.join(
        os.path.expanduser("~"), "CheckItPrintIt"
    )


@click.group()
@click.version_option(__version__)
def main():
    """Print a class set of CheckIt exercises."""


@main.command()
@click.argument("directory", default=".", type=click.Path())
@click.option("-b", "--bank", "bank_path", default=None, type=click.Path(),
              help="Path to the CheckIt bank, written into publication.toml.")
def init(directory, bank_path):
    """Set up a folder for one print job.

    Creates the directory and all three files a run needs, so the next step is
    editing rather than working out what to create.
    """
    os.makedirs(directory, exist_ok=True)

    files = {
        "publication.toml": pub_mod.TEMPLATE,
        "roster.toml": roster_mod.TEMPLATE,
        "seating.toml": seating.TEMPLATE,
    }
    existing = [n for n in files if os.path.exists(os.path.join(directory, n))]
    if existing:
        raise click.ClickException(
            f"{', '.join(existing)} already exist in {directory}. "
            "Nothing was written -- delete them, or pick another folder."
        )

    if bank_path:
        resolved = os.path.abspath(bank_path)
        if not os.path.isfile(os.path.join(resolved, "bank.xml")):
            raise click.ClickException(
                f"{resolved} has no bank.xml, so it is not a CheckIt bank."
            )
        # A relative path keeps the job folder movable alongside the bank, but
        # only while the two are near each other. Eight levels of ".." is worse
        # than an absolute path in every way.
        rel = os.path.relpath(resolved, os.path.abspath(directory))
        written = rel if rel.count("..") <= 2 else resolved
        files["publication.toml"] = files["publication.toml"].replace(
            'path = "../mat-106-checkit"',
            'path = "%s"' % written.replace("\\", "/"))

    for name, body in files.items():
        with open(os.path.join(directory, name), "w", encoding="utf-8") as f:
            f.write(body)

    click.echo(f"created {directory}/")
    for name in files:
        click.echo(f"  {name}")
    click.echo("")
    click.echo("Next: fill in the roster and seating, then")
    click.echo(f"  cd {directory} && checkit-printit build --preview")


@main.command()
@click.option("-b", "--bank", "bank_path", default=".", type=click.Path(),
              help="Path to the CheckIt bank. Defaults to the current folder.")
@click.option("--force", is_flag=True,
              help="Overwrite an existing theme with the default, discarding "
                   "any edits made to it.")
def install(bank_path, force):
    """Put this tool's theme into a bank, ready to be edited.

    Writes `printit/printit.sty`. That one file decides how printed handouts
    look AND what the viewer's Assessment tab exports, because CheckIt
    publishes it with the bank.

    `build` does this on its own the first time, so running this is only
    needed to set a bank up ahead of time, or to restore the default.
    """
    resolved = os.path.abspath(bank_path)
    if not os.path.isfile(os.path.join(resolved, "bank.xml")):
        raise click.ClickException(
            f"{resolved} has no bank.xml, so it is not a CheckIt bank."
        )
    try:
        path, action, declared = theme.install(resolved, force=force)
    except theme.ThemeError as exc:
        raise click.ClickException(str(exc))

    if action == "kept":
        click.echo(f"{path} already exists; it was left alone.")
        click.echo("Pass --force to replace it with the default.")
    else:
        click.echo(f"{action} {path}")
    if declared:
        click.echo(f"declared it in {os.path.join(resolved, 'bank.xml')}, so "
                   "`checkit generate` publishes it with the bank.")
    if action == "kept" and not declared:
        return
    click.echo("Edit it to change how this bank looks, in print and in the "
               "Assessment tab.")
    click.echo("Then run `checkit generate` so the site publishes the change.")


@main.command(name="import")
@click.argument("csv_path", type=click.Path(exists=True))
@click.option("-o", "--out", default="roster.toml", type=click.Path())
def import_csv(csv_path, out):
    """Convert a spreadsheet export into a roster file.

    A one-way import, deliberately. Run it once, read what it produced, fix
    anything it got wrong -- then nothing downstream ever depends on a column
    position again.
    """
    try:
        roster = roster_mod.from_spreadsheet_export(csv_path)
    except roster_mod.RosterError as exc:
        raise click.ClickException(str(exc))
    with open(out, "w", encoding="utf-8") as f:
        f.write(roster_mod.to_toml(roster))
    click.echo(f"wrote {out}: {len(roster)} students, "
               f"{len(roster.skills_used())} distinct skills")
    click.echo("Read it before printing from it.")


@main.command()
@click.option("-p", "--publication", "pub_path", default="publication.toml",
              type=click.Path(exists=True), help="The run's settings.")
@click.option("-o", "--out", default=None, type=click.Path(),
              help="Output folder. Defaults to a dated folder under ~/CheckItPrintIt.")
@click.option("--compile/--no-compile", "do_compile", default=True,
              help="Run pdflatex. --no-compile writes the folder and stops.")
@click.option("--seed", type=int, default=None,
              help="Seed the version chooser, to reproduce an earlier run.")
@click.option("--preview", is_flag=True,
              help="Report what would be printed, and write nothing.")
@click.option("--replay", type=click.Path(exists=True), default=None,
              help="Reprint a finished run exactly, from the manifest in its "
                   "output folder. Draws nothing.")
def build(pub_path, out, do_compile, seed, preview, replay):
    """Assemble the class set, and compile it."""
    try:
        publication = pub_mod.load(pub_path)
    except pub_mod.PublicationError as exc:
        raise click.ClickException(str(exc))

    record = None
    if replay:
        # Checked before any work: a replay that cannot be faithful should say
        # so instead of producing a folder that looks right.
        try:
            record = manifest_mod.load(replay)
            refusals, notes = manifest_mod.check(
                record, Bank(publication.bank_path), publication)
        except (manifest_mod.ManifestError, BankError) as exc:
            raise click.ClickException(str(exc))
        for note in notes:
            click.echo(f"replay  note: {note}")
        if refusals:
            raise click.ClickException(
                "this run cannot be reproduced from its manifest:\n  "
                + "\n  ".join(refusals))
        publication = manifest_mod.apply(record, publication)
        click.echo(f"replay  {len(record['paper'])} papers pinned from "
                   f"{os.path.join(replay, manifest_mod.FILENAME)}")

    if not publication.roster_path:
        raise click.ClickException(f"{pub_path}: [roster] path is required.")
    try:
        roster = roster_mod.load(publication.roster_path)
    except (OSError, roster_mod.RosterError) as exc:
        raise click.ClickException(str(exc))

    roster = roster_mod.apply_selection_modes(
        roster,
        simply_print=publication.simply_print,
        default_when_missing=publication.default_when_missing,
        append_for_everyone=publication.append_for_everyone,
    )

    chart = None
    if publication.seating_path:
        try:
            chart = seating.load(publication.seating_path)
        except (OSError, seating.SeatingError) as exc:
            raise click.ClickException(str(exc))

    out = out or os.path.join(
        default_output_root(),
        _safe(publication.course or "bank"),
        _safe(publication.full_title or "print"),
    )

    # A bank with no theme of its own gets one, so the file it prints from is
    # a file it can edit -- and so CheckIt publishes it with the bank, which is
    # what lets the viewer's Assessment tab match these handouts. Writing into
    # someone's bank is worth saying out loud, hence the printed line rather
    # than a silent copy. A preview writes nothing, here as everywhere.
    if publication.bank_path and not preview:
        try:
            installed_at, action, declared = theme.install(publication.bank_path)
        except theme.ThemeError as exc:
            raise click.ClickException(str(exc))
        if action == "installed":
            click.echo(f"theme   wrote {installed_at} -- edit it to change the look")
        if declared:
            click.echo("theme   declared it in the bank's bank.xml, so "
                       "`checkit generate` publishes it")

    try:
        theme_source, theme_origin = theme.load(publication.bank_path)
    except theme.ThemeError as exc:
        raise click.ClickException(str(exc))
    # Every run has a seed now, generated when one is not given, so the draw
    # can be repeated afterwards. Without it a --preview can never be carried
    # into the build it previewed, and yesterday's set is unrecoverable.
    run_seed = seed if seed is not None else random.randrange(2**31)
    rng = random.Random(run_seed)

    if preview:
        do_compile = False

    try:
        report = assemble(publication, roster, chart, out, theme_source,
                          rng=rng, dry_run=preview, run_seed=run_seed)
    except (AssemblyError, BankError) as exc:
        raise click.ClickException(str(exc))

    _report(report, out, theme_origin, publication, run_seed)

    if preview:
        click.echo("\npreview only -- nothing was written.")
        return

    if not do_compile:
        click.echo(f"\nnot compiled. To build it yourself:\n  cd {out} && pdflatex main.tex")
        return

    try:
        pdf = compile_pdf(out)
    except CompileError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"\nPDF: {pdf}")


def _report(report, out, theme_origin, publication, run_seed):
    click.echo(f"bank    {publication.bank_path}")
    click.echo(f"theme   {theme_origin}")
    click.echo(f"out     {out}")
    click.echo(f"seed    {run_seed}   (repeat this draw with --seed {run_seed})")
    click.echo("")
    click.echo(f"  students {report['students']}")
    if report["extras"]:
        click.echo(f"  extras   {report['extras']}")
    click.echo(f"  skills   {len(report['skills'])}: {', '.join(report['skills'])}")
    click.echo(f"  versions {report['versions']} distinct")
    if report["keys"]:
        click.echo(f"  key pages {report['keys']}")

    # Per (version, skill): different skills have unrelated seed pools, so
    # "version A" is not one seed but one seed per skill.
    used = sorted((v, slug, s) for (v, slug), s in report["seeds"].items()
                  if slug in report["skills"])
    if used:
        click.echo("  seeds")
        for version, slug, seed in used:
            click.echo(f"    {version}  {slug:6} v{seed}")

    for slug, fields in report["missing_fields"].items():
        click.echo(f"  NOTE     {slug}'s template asked for "
                   f"{', '.join(fields)}, which its generator does not set. "
                   f"Rendered as nothing -- fine if it is inside a LaTeX "
                   f"comment, a bug if it is not.")

    for a, b in report["collisions"]:
        click.echo(f"  WARNING  {a.name} and {b.name} are adjacent in group "
                   f"{a.group} and share version {a.version}")
    if report["unseated"]:
        click.echo(f"  WARNING  not in the seating chart, printed last: "
                   f"{', '.join(report['unseated'])}")


def _safe(name):
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip().strip(".") or "print"


if __name__ == "__main__":
    sys.exit(main())
