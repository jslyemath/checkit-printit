"""Running a build, without a terminal attached.

`build` lived entirely inside its Click command: load, resolve, seed,
assemble, record, compile, with `click.echo` between every step. Nothing but
the CLI could run it, so a GUI would have had to reimplement the sequence --
and the sequence is where the rules are. Which seed. Whether a replay may
proceed. Whether to install a theme into someone's bank. What gets recorded.

So it is here, returning a `BuildResult` that says what happened. The CLI
prints it; the web app serialises it. One implementation, as with
`roster.set_dropped` and `availability.set_open`.

Nothing in this module prints.
"""

import dataclasses
import datetime
import os
import random

from . import course as course_mod
from . import manifest as manifest_mod
from . import publication as pub_mod
from . import record as record_mod
from . import roster as roster_mod
from . import seating, theme
from .assemble import assemble, AssemblyError
from .bank import Bank, BankError
from .compile import compile_pdf, CompileError


class BuildError(Exception):
    """Something stopped the run. The message is for a human."""


@dataclasses.dataclass
class BuildResult:
    """Everything a caller might want to say about a finished run."""

    publication: object
    out: str
    run_seed: int
    report: dict
    theme_origin: str = ""
    #: Where a theme was written into the bank, when one was.
    theme_installed: str = ""
    theme_declared: bool = False
    #: True when the versions came from a manifest rather than a draw.
    replayed: bool = False
    replay_notes: tuple = ()
    replay_papers: int = 0
    #: What the print record took, when the job names a course.
    recorded: int = 0
    unnamed: int = 0
    record_path: str = ""
    record_error: str = ""
    pdf: str = ""
    compiled: bool = False
    preview: bool = False


def default_output_root():
    """Where builds land unless told otherwise.

    A canonical local place, so the same PDF can be rebuilt months later. Not
    a repository: this is a local record, not a published artefact.
    """
    return os.environ.get("CHECKIT_PRINTIT_HOME") or os.path.join(
        os.path.expanduser("~"), "CheckItPrintIt"
    )


def safe_name(name):
    for ch in '<>:"/\\|?*':
        name = name.replace(ch, "_")
    return name.strip().strip(".") or "print"


def choose_run_seed(record, seed):
    """Which number goes in the manifest and the print record.

    A replay draws nothing -- every version comes from the manifest -- so it
    must not invent one. Carrying the replayed run's keeps both files honest:
    a fresh number would be written having chosen nothing, and anyone who
    later passed it to `--seed` would get different papers. `record.db`
    outlives the folder, so the lie would outlive it too.
    """
    if record is not None:
        return int(record.get("run", {}).get("seed", 0))
    if seed is not None:
        return seed
    return random.randrange(2**31)


def run(pub_path, out=None, do_compile=True, seed=None, preview=False,
        replay=None, install_theme=True):
    """Build a class set. Returns a BuildResult; raises BuildError.

    `preview` writes nothing at all -- no folder, no theme, no record -- and
    reports what would have been printed.
    """
    try:
        publication = pub_mod.load(pub_path)
    except pub_mod.PublicationError as exc:
        raise BuildError(str(exc)) from None

    record = None
    notes = ()
    if replay:
        # Checked before any work: a replay that cannot be faithful should
        # say so instead of producing a folder that looks right.
        try:
            record = manifest_mod.load(replay)
            refusals, notes = manifest_mod.check(
                record, Bank(publication.bank_path), publication)
        except (manifest_mod.ManifestError, BankError) as exc:
            raise BuildError(str(exc)) from None
        if refusals:
            raise BuildError(
                "this run cannot be reproduced from its manifest:\n  "
                + "\n  ".join(refusals))
        publication = manifest_mod.apply(record, publication)

    if not publication.roster_path:
        raise BuildError(f"{pub_path}: [roster] path is required.")
    try:
        people = roster_mod.load(publication.roster_path)
    except (OSError, roster_mod.RosterError) as exc:
        raise BuildError(str(exc)) from None

    people = roster_mod.apply_selection_modes(
        people,
        simply_print=publication.simply_print,
        default_when_missing=publication.default_when_missing,
        append_for_everyone=publication.append_for_everyone,
    )

    chart = None
    if publication.seating_path:
        try:
            chart = seating.load(publication.seating_path)
        except (OSError, seating.SeatingError) as exc:
            raise BuildError(str(exc)) from None

    out = out or os.path.join(
        default_output_root(),
        safe_name(publication.course or "bank"),
        safe_name(publication.full_title or "print"),
    )

    result = BuildResult(publication=publication, out=out, run_seed=0,
                         report={}, replayed=record is not None,
                         replay_notes=tuple(notes),
                         replay_papers=len(record["paper"]) if record else 0,
                         preview=preview)

    # A bank with no theme of its own gets one, so the file it prints from is
    # a file it can edit -- and so CheckIt publishes it with the bank, which
    # is what lets the viewer's Assessment tab match these handouts. Writing
    # into someone's bank is worth saying out loud, which is why the result
    # carries it rather than doing it silently. A preview writes nothing.
    if publication.bank_path and not preview and install_theme:
        try:
            at, action, declared = theme.install(publication.bank_path)
        except theme.ThemeError as exc:
            raise BuildError(str(exc)) from None
        result.theme_installed = at if action == "installed" else ""
        result.theme_declared = bool(declared)

    try:
        theme_source, result.theme_origin = theme.load(publication.bank_path)
    except theme.ThemeError as exc:
        raise BuildError(str(exc)) from None

    # Every run has a seed, generated when one is not given, so the draw can
    # be repeated afterwards. Without it a preview can never be carried into
    # the build it previewed, and yesterday's set is unrecoverable.
    result.run_seed = choose_run_seed(record, seed)

    try:
        result.report = assemble(
            publication, people, chart, out, theme_source,
            rng=random.Random(result.run_seed), dry_run=preview,
            run_seed=result.run_seed)
    except (AssemblyError, BankError) as exc:
        raise BuildError(str(exc)) from None

    if preview:
        return result

    # Recorded when the folder is written, not when it compiles: the papers
    # exist either way, and --no-compile is a normal way to finish.
    _record(publication, result)

    if not do_compile:
        return result
    try:
        result.pdf = compile_pdf(out)
        result.compiled = True
    except CompileError as exc:
        raise BuildError(str(exc)) from None
    return result


def _record(publication, result):
    """Note what was printed, when the job belongs to a course.

    A side effect of building, never an input to it. A failure here is
    reported and never raised: losing a built PDF to a bookkeeping error
    would be the worse trade.
    """
    if not publication.course_folder:
        return
    path = course_mod.file_in(publication.course_folder, "record")
    try:
        rows, unnamed = record_mod.write_run(
            path,
            run_id=os.path.basename(os.path.normpath(result.out)),
            title=publication.title,
            date=str(publication.date),
            built=datetime.datetime.now().isoformat(timespec="seconds"),
            seed=result.run_seed,
            output=os.path.abspath(result.out),
            handouts=result.report.get("handouts", []),
            extras=result.report.get("extras", 0),
        )
    except Exception as exc:                 # never lose a built PDF to it
        result.record_error = str(exc)
        return
    result.recorded, result.unnamed, result.record_path = rows, unnamed, path
