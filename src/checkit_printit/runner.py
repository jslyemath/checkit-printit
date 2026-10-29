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
from .assemble import assemble, AssemblyError, FolderInUse
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
    #: Override keys that matched nobody in the roster -- a mistyped id, or
    #: a student who has left since. Reported, never dropped.
    unmatched_overrides: tuple = ()
    #: Likewise for the "print for these students" list.
    unmatched_students: tuple = ()
    #: Named by the run and found, but dropped -- so still printed
    #: nothing. Reported separately because "matched nobody" is not
    #: what a student sitting on the roster page looks like.
    dropped_students: tuple = ()
    #: How many students this run printed for, and how many the
    #: roster holds. Equal unless the run names particular students.
    printed_for: int = 0
    roster_size: int = 0
    #: The number the print record gave this run, which is what the
    #: footer code carries. None when there is no record to key into.
    run_id: int = None
    #: True when this build was recovering a lost page index. Who
    #: held which page is sound -- it comes from the roster and the
    #: chart -- but the seeds are a fresh draw, not what was
    #: printed, and the record says so rather than looking normal.
    rebuilt: bool = False
    #: True when a run prints neither names nor an id field, so nothing
    #: on any of its papers says who sat it and Scans can never
    #: attribute one. Warned about rather than refused: an anonymous
    #: practice set is a reasonable thing to want, and this is only a
    #: mistake if somebody meant to grade it.
    anonymous: bool = False


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
        replay=None, install_theme=True, ids=None, codes=None,
        keep_record=True, only=None, replace=False, rebuilt=False):
    """Build a class set. Returns a BuildResult; raises BuildError.

    `preview` writes nothing at all -- no folder, no theme, no record -- and
    reports what would have been printed.
    """
    try:
        publication = pub_mod.load(pub_path)
    except pub_mod.PublicationError as exc:
        raise BuildError(str(exc)) from None

    # `ids` and `codes` may be overridden for one build without
    # editing the publication. None means "whatever the file says",
    # which is why they are not plain booleans: a `False` default
    # would turn the marks off for every caller that did not think
    # about them, including `--replay`.
    if ids is not None or codes is not None:
        publication = dataclasses.replace(
            publication,
            ids=publication.ids if ids is None else bool(ids),
            codes=publication.codes if codes is None else bool(codes))

    # Likewise `only`: None is "whatever the file says". An empty
    # sequence is not a way to say "nobody" here -- a command line
    # that names no students is one that forgot the argument, and
    # the deliberate empty list is a thing only the app can write.
    if only:
        publication = dataclasses.replace(
            publication, only_students=tuple(only))

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

    # Before the modes, so a student with an override but no choices of
    # their own does not also collect `default_when_missing`.
    people, unmatched_overrides = roster_mod.apply_overrides(
        people, publication.student_overrides)

    # Who the run is for, reported here so an unmatched name is seen
    # even though the filtering itself happens in `assemble`. A name
    # that matches nobody prints nothing, silently, which is the
    # failure this feature exists to prevent rather than cause.
    #
    # Against the live roster, because that is what `assemble`
    # filters -- naming a dropped student prints nothing, and
    # checking the full roster would report that as fine.
    live = people.live()
    unmatched_students, dropped_students = [], []
    printed_for = len(live)
    if publication.only_students is not None:
        chosen, unmatched_students = live.only(publication.only_students)
        printed_for = len(chosen)
        if unmatched_students:
            # "Matched nobody in the roster" is misleading for a
            # student who is visibly on the roster page and merely
            # dropped. Separated so the message can say which it is,
            # instead of sending someone hunting for a typo.
            _, truly_absent = people.only(unmatched_students)
            dropped_students = sorted(
                set(unmatched_students) - set(truly_absent))
            unmatched_students = truly_absent
        if not printed_for:
            # Before `assemble`, which would refuse this too and say
            # only "none of them is in the roster" -- true of a typo,
            # false of a student who is sitting on the roster page
            # greyed out, and the difference is the whole fix.
            why = []
            if dropped_students:
                why.append(f"{', '.join(dropped_students)} "
                           f"{'has' if len(dropped_students) == 1 else 'have'}"
                           f" been dropped")
            if unmatched_students:
                why.append(f"{', '.join(unmatched_students)} "
                           f"{'is' if len(unmatched_students) == 1 else 'are'}"
                           f" not in the roster")
            raise BuildError(
                "this run is set to print for particular students and it "
                "would print nothing: "
                + ("; ".join(why) if why
                   else "no student is named. Tick somebody, or set the "
                        "run back to the whole class.")
                + ".")

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
                         unmatched_overrides=tuple(unmatched_overrides),
                         unmatched_students=tuple(unmatched_students),
                         dropped_students=tuple(dropped_students),
                         printed_for=printed_for, roster_size=len(live),
                         rebuilt=bool(rebuilt),
                         anonymous=not publication.names
                         and not publication.ids,
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

    # And a run number, which is a different thing and is what the
    # footer code carries. Allocated before the document is written,
    # because the document has to print it -- the record is only
    # written afterwards. A folder that has been built before keeps
    # the number it already has, so a rebuild does not change what
    # the reprinted paper says.
    #
    # No course, or --no-record, means no number: there would be
    # nothing for a scanner to look the code up in.
    if publication.course_folder and keep_record and not preview:
        result.run_id = record_mod.next_run_no(
            course_mod.file_in(publication.course_folder, "record"),
            os.path.basename(os.path.normpath(out)))

    # What this folder produced last time, so `assemble` can tell a
    # rebuild from a second job wearing the first one's name. None
    # when there is nothing to compare against -- no course, no
    # record, or a folder never built before -- and None means "do
    # not check", which is how `--replace` gets through.
    #
    # A replay is exempt on purpose: reprinting a finished run into
    # its own folder is the one case where replacing what is there
    # is the whole point, and the manifest has already been checked
    # against the bank.
    already = None
    # Recovering an index is replacing a run on purpose, so it does
    # not also need `--replace`: asking for both would be asking the
    # same question twice and getting the answer wrong once.
    if (publication.course_folder and not replace and not rebuilt
            and record is None):
        already = record_mod.papers_in(
            course_mod.file_in(publication.course_folder, "record"),
            os.path.basename(os.path.normpath(out)))

    try:
        result.report = assemble(
            publication, people, chart, out, theme_source,
            rng=random.Random(result.run_seed), dry_run=preview,
            run_seed=result.run_seed, run_id=result.run_id,
            already=already)
    except FolderInUse:
        # Raised as itself, not flattened into BuildError: the web
        # app has two ways out to offer and needs to know which
        # refusal this is.
        raise
    except (AssemblyError, BankError) as exc:
        raise BuildError(str(exc)) from None

    if preview:
        return result

    # Recorded when the folder is written, not when it compiles: the papers
    # exist either way, and --no-compile is a normal way to finish.
    if keep_record:
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
            run_no=result.run_id,
            output=os.path.abspath(result.out),
            handouts=result.report.get("handouts", []),
            extras=result.report.get("extras", 0),
            rebuilt=result.rebuilt,
        )
    except Exception as exc:                 # never lose a built PDF to it
        result.record_error = str(exc)
        return
    result.recorded, result.unnamed, result.record_path = rows, unnamed, path
