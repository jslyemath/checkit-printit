"""checkit-printit — turn a bank and a roster into a printable class set."""

import os
import random
import sys

import click

from . import __version__, publication as pub_mod, roster as roster_mod, seating, theme
from .assemble import assemble, AssemblyError
from .bank import BankError
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
def build(pub_path, out, do_compile, seed, preview):
    """Assemble the class set, and compile it."""
    try:
        publication = pub_mod.load(pub_path)
    except pub_mod.PublicationError as exc:
        raise click.ClickException(str(exc))

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

    theme_source, theme_origin = theme.load(publication.bank_path)
    rng = random.Random(seed)

    if preview:
        do_compile = False

    try:
        report = assemble(publication, roster, chart, out, theme_source,
                          rng=rng, dry_run=preview)
    except (AssemblyError, BankError) as exc:
        raise click.ClickException(str(exc))

    _report(report, out, theme_origin, publication)

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


def _report(report, out, theme_origin, publication):
    click.echo(f"bank    {publication.bank_path}")
    click.echo(f"theme   {theme_origin}")
    click.echo(f"out     {out}")
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
