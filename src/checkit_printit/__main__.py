"""checkit-printit — turn a bank and a roster into a printable class set."""

import dataclasses
import os
import random
import sys

import click

from . import __version__, publication as pub_mod, roster as roster_mod, seating, theme
from . import availability as availability_mod
from . import clasp as clasp_mod
from . import classlist as classlist_mod
from . import form as form_mod
from . import record as record_mod
from . import responses as responses_mod
from . import course as course_mod
from . import gradebook as gradebook_mod
from . import mask as mask_mod
from . import maskcourse as maskcourse_mod
from . import vault as vault_mod
from . import manifest as manifest_mod
from . import provision as provision_mod
from . import runner
from .assemble import assemble, AssemblyError, FolderInUse
from .bank import Bank, BankError
from .compile import compile_pdf, CompileError




def _survive_a_narrow_console():
    """Print escapes rather than dying on a character the console lacks.

    A Windows console is often cp1252, and `gradebook map` prints the
    gradebook's own mark values -- which on a real export begin with an
    emoji. Writing one raised `UnicodeEncodeError` and killed the
    command **half way through its report**, after the column matching
    had been printed and before anything was saved.

    `backslashreplace` keeps the emoji on a console that can show them
    and degrades to `\U0001f3c6` on one that cannot, instead of
    stopping. Applied once here rather than at each `echo`, because
    this is not only the gradebook's problem: `vault show` and
    `vault check` print student names, and one accented letter would
    have done the same thing.
    """
    import sys as _sys
    for stream in (_sys.stdout, _sys.stderr):
        try:
            stream.reconfigure(errors="backslashreplace")
        except (AttributeError, OSError, ValueError):   # pragma: no cover
            pass


@click.group()
@click.version_option(__version__)
def main():
    """Print a class set of CheckIt exercises."""
    _survive_a_narrow_console()


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


@main.group()
def form():
    """The Google Form students choose their skills on."""


def _space_path(space):
    if not course_mod.exists(space):
        raise click.ClickException(f"no course named {space!r}.")
    return course_mod.path_for(space)


def _clasp_dir(space):
    """The local copy of the Apps Script project. See `provision`."""
    return provision_mod.clasp_dir(space)


def _stage_script(space, secret):
    """Copy the script into the course, with the secret. See `provision`."""
    return provision_mod.stage_script(space, secret)


def _ensure_login():
    try:
        if provision_mod.signed_in():
            return
    except provision_mod.ProvisionError as exc:
        raise click.ClickException(str(exc))
    click.echo("signing in to Google -- a browser window will open.")
    click.echo("  (this uses clasp's own sign-in; printit never sees your "
               "password)")
    try:
        provision_mod.sign_in()
    except provision_mod.ProvisionError as exc:
        raise click.ClickException(str(exc))


def _reach(conn):
    """Reach the script, waiting while the instructor authorizes it.

    This is the one step where the two front ends differ, and the reason
    `provision` takes it as an argument: a terminal can stop and wait for a
    keypress, a request handler cannot.
    """
    try:
        return provision_mod.reach(conn)
    except provision_mod.NeedsAuthorization as first:
        if not sys.stdin.isatty():
            raise click.ClickException(
                f"{first.cause}\n\n{provision_mod.prompt(conn.url)}\n\n"
                "Then run this command again."
            ) from None
        click.echo("")
        click.echo(provision_mod.prompt(conn.url))
        click.echo("")
        click.confirm("authorized?", default=True, abort=True)
        try:
            return provision_mod.reach(conn)
        except provision_mod.NeedsAuthorization as second:
            raise click.ClickException(
                f"still refused after authorizing: {second.cause}") from None


def _ping_authorized(conn):
    """Kept as the name the other form commands already call."""
    return _reach(conn)


def _report_identity(conn, answer):
    """Record which form we reached, and say where it is.

    `ping` is the only thing that knows: the script id cannot be turned into
    a form URL.
    """
    conn.form_id = answer.get("formId", "") or conn.form_id
    click.echo(f"  connected to {answer.get('form', '')!r}")
    if answer.get("editUrl"):
        click.echo(f"  {answer['editUrl']}")


@form.command(name="create")
@click.option("-c", "--course", "space", required=True)
@click.option("--title", default="Skill Selection Form",
              help="What the new form is called.")
@click.option("--folder", default="",
              help="A Drive folder id to put it in. Omit for the top of My "
                   "Drive.")
def form_create(space, title, folder):
    """Make a new Google Form, wire it up, and record everything.

    One command and one browser sign-in. Creates the form and its bound
    script, deploys the web app, adds the four items printit writes to, and
    records their ids -- so there is nothing to paste and nothing to map.
    """
    _space_path(space)
    _ensure_login()
    click.echo(f"creating the form {title!r}...")
    try:
        for line in provision_mod.create_form(space, title, folder,
                                              reach=_reach):
            click.echo(f"  {line}")
    except provision_mod.ProvisionError as exc:
        raise click.ClickException(str(exc))

    click.echo("")
    click.echo("done. Set the assessment and open some skills, then push:")
    click.echo(f"  checkit-printit skills set  -c {space!r} --name ... --date ...")
    click.echo(f"  checkit-printit skills open -c {space!r} W1 W1-E")
    click.echo(f"  checkit-printit form push   -c {space!r}")


@form.command(name="attach")
@click.option("-c", "--course", "space", required=True)
@click.option("--script-id", required=True,
              help="The bound script's id: on the form, three-dot menu > Apps "
                   "Script, then Project Settings.")
def form_attach(space, script_id):
    """Wire up a form you already have, without touching its content.

    For a form with a banner, grade cutoffs and syllabus links worth keeping.
    The script is pushed and deployed, but no items are created or changed --
    run `form map` afterwards to say which existing item is which.
    """
    _space_path(space)
    _ensure_login()
    click.echo("fetching the existing script...")
    try:
        for line in provision_mod.attach_form(space, script_id, reach=_reach):
            click.echo(f"  {line}")
    except provision_mod.ProvisionError as exc:
        raise click.ClickException(str(exc))
    click.echo("")
    click.echo("Next:")
    click.echo(f"  checkit-printit form map -c {space!r}")


@form.command(name="add-items")
@click.option("-c", "--course", "space", required=True)
def form_add_items(space):
    """Create any of the four items the form is missing.

    Only what is absent: an item printit already knows about is left alone,
    because recreating a question orphans every answer already given to it.
    """
    path = _space_path(space)
    conn = form_mod.load(path)
    try:
        made = form_mod.call(conn, "addItems",
                             {"items": dict(conn.items)})["items"]
    except form_mod.FormError as exc:
        raise click.ClickException(str(exc))
    added = [k for k, v in made.items() if conn.items.get(k) != v]
    conn.items = made
    form_mod.save(path, conn)
    click.echo(f"added {len(added)}: {', '.join(added) or 'nothing was missing'}")


@form.command(name="setup")
@click.option("-c", "--course", "space", required=True)
def form_setup(space):
    """Generate a secret and print what to do in the Apps Script editor."""
    path = _space_path(space)
    conn = form_mod.load(path)
    if conn.secret:
        click.echo("a secret already exists; keeping it.")
    else:
        conn.secret = form_mod.new_secret()
    _, secret_file = form_mod.save(path, conn)

    script = os.path.join(os.path.dirname(os.path.dirname(
        os.path.dirname(os.path.abspath(__file__)))), "appsscript")
    click.echo("")
    click.echo("1. Open the form, then the three-dot menu > Apps Script.")
    click.echo(f"2. Paste in the script from {script}")
    click.echo("   (or `clasp clone <scriptId>` there and `clasp push`).")
    click.echo("3. Project Settings > Script Properties > add:")
    click.echo("")
    click.echo(f"      PRINTIT_SECRET = {conn.secret}")
    click.echo("")
    click.echo("4. Deploy > New deployment > Web app")
    click.echo("      Execute as:     Me")
    click.echo("      Who has access: Anyone")
    click.echo("")
    click.echo("   'Anyone' is needed because a command line cannot sign in to")
    click.echo("   Google. The URL is unguessable and the secret is what")
    click.echo("   actually guards it, so treat the URL as a password too.")
    click.echo("")
    click.echo("5. Copy the web app URL, then run:")
    click.echo(f"      checkit-printit form connect -c {space!r} --url <URL>")
    click.echo("")
    click.echo(f"the secret is stored in {secret_file}")


@form.command(name="connect")
@click.option("-c", "--course", "space", required=True)
@click.option("--url", required=True, help="The web app deployment URL.")
def form_connect(space, url):
    """Point the course at a deployed web app, and check it answers."""
    path = _space_path(space)
    conn = form_mod.load(path)
    if not conn.secret:
        raise click.ClickException(
            "no secret yet -- run `checkit-printit form setup` first.")
    conn.url = url.strip()
    # The same path the clasp commands take: a hand-deployed web app needs
    # authorizing exactly as much as one clasp deployed, and the form id is
    # only knowable by asking the script.
    answer = _ping_authorized(conn)
    _report_identity(conn, answer)
    form_mod.save(path, conn)
    click.echo(f"next: `checkit-printit form map -c {space!r}` to say which "
               f"item is which")


@form.command(name="pull")
@click.option("-c", "--course", "space", required=True)
@click.option("--dry-run", is_flag=True,
              help="Report what was found, and write nothing.")
@click.option("--force", is_flag=True,
              help="Write the roster even when some responses could not be "
                   "placed.")
def form_pull(space, dry_run, force):
    """Read this assessment's responses into the roster.

    Scoped by the date each student confirmed, not by a time window: a form
    accumulates responses all term, and the confirmation checkbox is what
    says which assessment an answer is for. Where a student answered twice,
    the later answer wins.
    """
    try:
        out = responses_mod.pull_for_course(space, write=not dry_run,
                                            force=force)
    except responses_mod.ResponseError as exc:
        raise click.ClickException(str(exc))
    pulled = out.pulled

    click.echo(f"the form holds {out.total} response(s)")
    if not out.known_from_bank:
        click.echo("(no bank configured, so only the open skills are "
                   "recognised)")
    click.echo(f"for {out.assessment or 'this assessment'} on "
               f"{availability_mod.spoken_date(out.date) or out.date}:")
    click.echo(f"  {pulled.answered} student(s) answered")
    for key, (student, picked) in sorted(
            pulled.by_student.items(), key=lambda kv: kv[1][0].name.lower()):
        click.echo(f"    {student.display:28} {', '.join(picked) or '(nothing)'}")

    if pulled.silent:
        click.echo(f"  {len(pulled.silent)} did not answer; they will get "
                   f"[selection] default_when_missing")
    if pulled.stale:
        click.echo(f"  {len(pulled.stale)} of them still had a choice from "
                   f"an earlier assessment, which is cleared")

    # Everything below is a reason a student might not get the paper they
    # asked for, so none of it is allowed to be quiet.
    if pulled.unknown_emails:
        click.echo(f"  ! {len(pulled.unknown_emails)} response(s) from an "
                   f"address nobody on the roster has:")
        for address in pulled.unknown_emails:
            click.echo(f"      {address}")
        click.echo("    add the address to that student with "
                   "`roster import`, or check for a typo.")
    if pulled.unrecognised:
        click.echo(f"  ! {len(pulled.unrecognised)} answer(s) name a skill "
                   f"the bank does not have:")
        for address, option in pulled.unrecognised:
            click.echo(f"      {address}: {option[:60]}")
    if pulled.unconfirmed:
        click.echo(f"  {pulled.unconfirmed} response(s) confirmed no date, "
                   f"so they belong to no assessment")
    if pulled.out_of_scope:
        click.echo(f"  {pulled.out_of_scope} response(s) are for another day")
    if pulled.superseded:
        click.echo(f"  {pulled.superseded} response(s) superseded by a later "
                   f"one from the same student")

    if dry_run:
        click.echo("\ndry run -- the roster was not written.")
        return
    if not out.written:
        raise click.ClickException(
            "some responses could not be placed, so the roster was not "
            "written. Fix them, or pass --force to write the rest.")
    click.echo(f"\nwrote {out.roster_path}")
    click.echo("next: build the job that names this course.")


@form.command(name="map")
@click.option("-c", "--course", "space", required=True)
def form_map(space):
    """Record which item on the form holds each thing printit writes.

    Asked rather than guessed: only you know which section header is the due
    notice and which is the grade advice, and writing to the wrong one would
    overwrite something the tool has no way to restore.
    """
    path = _space_path(space)
    conn = form_mod.load(path)
    try:
        items = form_mod.call(conn, "describe")["items"]
    except form_mod.FormError as exc:
        raise click.ClickException(str(exc))

    click.echo("the form contains:")
    for i, item in enumerate(items, 1):
        title = item.get("title") or "(untitled)"
        help_text = (item.get("help") or "").replace("\n", " ")
        click.echo(f"  {i:2}. [{item.get('type', '?'):16}] {title[:48]}")
        if help_text:
            click.echo(f"      {help_text[:70]}")
    click.echo("")

    chosen = {}
    for slot, what in form_mod.SLOTS.items():
        current = conn.items.get(slot)
        hint = ""
        if current:
            match = next((str(n) for n, it in enumerate(items, 1)
                          if it["id"] == current), None)
            hint = f" [{match}]" if match else ""
        answer = click.prompt(f"which item is {what}?{hint}",
                              default=hint.strip(" []") or "", show_default=bool(hint))
        answer = str(answer).strip()
        if not answer:
            click.echo(f"  skipped -- {slot} will not be written")
            continue
        try:
            chosen[slot] = items[int(answer) - 1]["id"]
        except (ValueError, IndexError):
            raise click.ClickException(f"{answer!r} is not one of 1-{len(items)}.")

    conn.items = chosen
    config, _ = form_mod.save(path, conn)
    click.echo("")
    click.echo(f"wrote {config}")
    missing = conn.missing_slots()
    if missing:
        click.echo(f"not set: {', '.join(missing)} -- a push will leave those "
                   f"parts of the form alone")


@form.command(name="push")
@click.option("-c", "--course", "space", required=True)
@click.option("--dry-run", is_flag=True,
              help="Show exactly what would be sent, and send nothing.")
@click.option("--force", is_flag=True,
              help="Send even when the assessment is unset, which blanks "
                   "the wording on the form.")
def form_push(space, dry_run, force):
    """Write this week's wording and skill list onto the form."""
    path = _space_path(space)
    conn = form_mod.load(path)
    try:
        av = availability_mod.load(course_mod.file_in(space, "availability"))
    except availability_mod.AvailabilityError as exc:
        raise click.ClickException(str(exc))

    bank = _bank_for(space)
    descriptions = {}
    if bank is not None:
        for slug in av.skills:
            try:
                descriptions[slug] = bank.description(slug)
            except BankError as exc:
                raise click.ClickException(str(exc))
    elif av.skills:
        click.echo("(no bank configured, so options will carry slugs only)")

    payload = form_mod.payload_for(av, conn, descriptions)

    click.echo("what the form will say:")
    for key in ("selecting_for", "confirm_date", "due_notice",
                "question_title", "question_help"):
        if payload[key]:
            click.echo(f"  {payload[key]}")
    click.echo(f"  options ({len(payload['choices'])}):")
    for choice in payload["choices"]:
        click.echo(f"    {choice[:88]}")
    click.echo(f"  validation: {payload['validation']['mode']} "
               f"{payload['validation']['count'] or ''}".rstrip())

    if not conn.items:
        raise click.ClickException(
            "no items are mapped yet -- run `checkit-printit form map`.")
    # After the preview above, which is the thing worth seeing: the
    # refusal reads much better underneath what it is refusing to send.
    empty = av.nothing_to_say()
    if empty and not force:
        raise click.ClickException(empty + " (or --force).")
    if dry_run:
        click.echo("\ndry run -- nothing was sent.")
        return
    try:
        answer = form_mod.call(conn, "push", payload)
    except form_mod.FormError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"\nupdated: {', '.join(answer.get('changed', [])) or 'nothing'}")


@main.group()
def record():
    """What has been printed, for whom, at which seed."""


def _record_path(space):
    if not course_mod.exists(space):
        raise click.ClickException(f"no course named {space!r}.")
    return course_mod.file_in(space, "record")


@record.command(name="runs")
@click.option("-c", "--course", "space", required=True)
def record_runs(space):
    """Every print run, oldest first."""
    rows = record_mod.runs(_record_path(space))
    if not rows:
        click.echo("nothing recorded yet.")
        return
    for r in rows:
        line = (f"{r['date']:12} {r['title']:28} "
                f"{r['students']:3} students, {r['papers']:4} papers")
        if r["extras"]:
            line += f", {r['extras']} extras"
        click.echo(line)
        click.echo(f"{'':12} seed {r['seed']}   {r['run_id']}")
        if r["unnamed"]:
            click.echo(f"{'':12} {r['unnamed']} handout(s) unattributed "
                       f"(printed without names)")


@record.command(name="student")
@click.argument("who")
@click.option("-c", "--course", "space", required=True)
def record_student(who, space):
    """Every paper one student has been handed.

    Printed, not attempted -- a build cannot know who was in the room.
    """
    try:
        people = roster_mod.load(course_mod.file_in(space, "roster"))
        student = roster_mod.find(people, who)
    except roster_mod.RosterError as exc:
        raise click.ClickException(str(exc))
    if not student.sid:
        raise click.ClickException(
            f"{student.name} has no student id, so nothing can be attributed "
            f"to them. Import a class list to fill the ids in.")

    path = _record_path(space)
    rows = record_mod.for_student(path, student.sid)
    click.echo(f"{student.name}  ({student.sid})")
    if not rows:
        click.echo("  nothing printed yet.")
        return
    for r in rows:
        click.echo(f"  {r['date']:12} {r['slug']:6} v{r['seed']:<5} "
                   f"version {r['version'] or '-':2}  {r['title']}")
    click.echo("")
    counts = record_mod.times_printed(path, student.sid)
    click.echo("  times printed: "
               + ", ".join(f"{k} x{v}" for k, v in sorted(counts.items())))


@record.command(name="skills")
@click.option("-c", "--course", "space", required=True)
def record_skills(space):
    """Per skill: how many papers, to how many students."""
    rows = record_mod.skill_totals(_record_path(space))
    if not rows:
        click.echo("nothing recorded yet.")
        return
    for r in rows:
        click.echo(f"  {r['slug']:8} {r['papers']:4} papers to "
                   f"{r['students']:3} students")


@main.group()
def skills():
    """Which skills are open for retake, and what the next assessment is."""


def _availability_path(space):
    if not course_mod.exists(space):
        raise click.ClickException(
            f"no course named {space!r}. Create one with "
            f"`checkit-printit course init {space!r}`.")
    return course_mod.file_in(space, "availability")


@skills.command(name="preview")
@click.option("-c", "--course", "space", required=True)
def skills_preview(space):
    """Read the form's wording back before students see it.

    Changes nothing. `skills open` is the verb that changes what is available;
    this is the one that shows you the result.
    """
    path = _availability_path(space)
    try:
        av = availability_mod.load(path)
    except availability_mod.AvailabilityError as exc:
        raise click.ClickException(str(exc))

    descriptions = {}
    try:
        pub_bank = _bank_for(space)
        if pub_bank:
            descriptions = {s: pub_bank.description(s) for s in av.skills}
    except Exception as exc:                       # a bank problem is a note
        click.echo(f"(descriptions unavailable: {exc})")

    click.echo(availability_mod.describe(av, descriptions))
    click.echo("")
    click.echo("the form will read:")
    for line in (av.selecting_for(), av.confirmation(),
                 av.question_title(), av.due_notice()):
        click.echo(f"  {line}")


@skills.command(name="open")
@click.argument("slugs", nargs=-1, required=True)
@click.option("-c", "--course", "space", required=True)
@click.option("--add", is_flag=True, help="Add to the open list rather than "
                                          "replacing it.")
def skills_open(slugs, space, add):
    """Set which skills are open for retake.

    Slugs are checked against the bank, because a typo here reaches students
    as a missing option on the form and a missing paper in the pile.
    """
    bank = _bank_for(space)
    try:
        wanted = availability_mod.set_open(
            _availability_path(space), slugs, add=add,
            known=set(bank.slugs()) if bank is not None else None)
    except availability_mod.AvailabilityError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"open for retake ({len(wanted)}): {', '.join(wanted)}")


@skills.command(name="set")
@click.option("-c", "--course", "space", required=True)
@click.option("--name", default=None, help='e.g. "Skill Checkpoint Redo"')
@click.option("--date", default=None, help="The assessment date, 2026-09-18.")
@click.option("--due", default=None, help="When the form closes, "
                                          "2026-09-17T23:59.")
@click.option("--choose", type=int, default=None,
              help="How many skills a student may pick. 0 means any number.")
@click.option("--limit", type=click.Choice(availability_mod.LIMITS),
              default=None)
def skills_set(space, name, date, due, choose, limit):
    """Set the next assessment's name, dates and selection limit."""
    try:
        av = availability_mod.set_assessment(
            _availability_path(space), name=name, date=date, due=due,
            choose=choose, limit=limit)
    except availability_mod.AvailabilityError as exc:
        raise click.ClickException(str(exc))
    click.echo(availability_mod.describe(av))


def _bank_for(space):
    """The course's bank, or None. Kept as a name the CLI already uses."""
    return course_mod.bank_for(space)


# These three moved into `runner`, which needs them with no click attached.
# Aliases rather than copies, and rather than deletions: one implementation,
# and `main._safe` still resolves for anything that reaches for it.
default_output_root = runner.default_output_root
_safe = runner.safe_name
_choose_run_seed = runner.choose_run_seed


@main.group()
def course():
    """The course state that outlives a single print job."""


@course.command(name="init")
@click.argument("name")
@click.option("-b", "--bank", "bank_path", default="", type=click.Path(),
              help="The bank this course prints from.")
# Not Path(exists=True): `--adopt=` means "start empty", and Click would
# reject the empty string before this function ever ran.
@click.option("--adopt", default=None, type=click.Path(),
              help="A job folder whose roster and seating to start from. "
                   "Defaults to the newest one; --adopt= for none.")
def course_init(name, bank_path, adopt):
    """Create a course.

    A job then names it instead of carrying its own copy of the roster and the
    seating chart, so a student who drops is fixed in one place rather than
    remembered at the next copy.
    """
    if adopt is None:
        adopt = course_mod.newest_job()
        if adopt:
            click.echo(f"adopting from the newest job: {adopt}")
            click.echo("  (pass --adopt= to start empty)")
    elif adopt and not os.path.isdir(adopt):
        raise click.ClickException(
            f"--adopt {adopt!r}: no such job folder.")
    try:
        path, notes = course_mod.init(
            name, bank=os.path.abspath(bank_path) if bank_path else "",
            adopt=adopt)
    except course_mod.CourseError as exc:
        raise click.ClickException(str(exc))

    click.echo(f"created {path}")
    for note in notes:
        click.echo(f"  {note}")
    click.echo("")
    click.echo("point a job at it by putting this in its publication.toml:")
    click.echo("")
    click.echo("    [course]")
    click.echo('    name   = "MAT 106"      # what prints in the header')
    click.echo(f'    folder = "{name}"      # this course')
    click.echo("")
    click.echo("`folder` is what resolves; `name` only prints.")


@main.command(name="gui")
@click.option("-c", "--course", "space", required=True)
@click.option("--port", default=8765, show_default=True,
              help="Which port to listen on.")
@click.option("--open/--no-open", "open_browser", default=True,
              help="Open a browser window.")
def gui(space, port, open_browser):
    """Open the local web app for a course.

    Bound to 127.0.0.1, never 0.0.0.0: it serves names, student ids and email
    addresses off a laptop that sits on university wifi. Each run mints a
    token the page must send back, because loopback stops another machine but
    not another *page* -- any site open in the same browser can quietly POST
    to localhost.

    Stop it with Ctrl-C.
    """
    from . import gui as gui_mod
    try:
        httpd, url, _ = gui_mod.serve(space, port=port,
                                      open_browser=open_browser,
                                      forever=False)
    except gui_mod.GuiError as exc:
        raise click.ClickException(str(exc))
    except OSError as exc:
        raise click.ClickException(
            f"could not listen on port {port}: {exc}. Another copy may "
            f"already be running -- try --port {port + 1}.")

    click.echo(f"serving {space!r} at {url}")
    click.echo("  Ctrl-C to stop")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        click.echo("")
    finally:
        httpd.server_close()


@main.group()
def roster():
    """Work with the list of students."""


@roster.command(name="import")
@click.argument("class_list", type=click.Path(exists=True))
@click.option("-o", "--out", default="roster.toml", type=click.Path(),
              help="Where to write. An existing file is merged into, not "
                   "replaced.")
@click.option("--section", default="",
              help="Section for every student in this file, for exports that "
                   "do not carry one.")
@click.option("--covers", multiple=True,
              help="Sections this file is authoritative for. Defaults to the "
                   "sections in the file; state it when a section has emptied, "
                   "since an empty section cannot appear in its own class list.")
@click.option("-s", "--seating", "seating_path", default=None,
              type=click.Path(),
              help="The seating chart to keep in step. Defaults to one beside "
                   "the roster.")
@click.option("--dry-run", is_flag=True,
              help="Report what would change and write nothing.")
def roster_import(class_list, out, section, covers, seating_path, dry_run):
    """Read a registrar or LMS class list into the roster.

    Merges rather than replaces: a student the file does not mention is marked
    dropped and kept, because the print record refers to them, and nothing you
    authored -- the printed name, a preferred name, chosen skills -- is ever
    overwritten by a class list.
    """
    try:
        students, mapping, notes = classlist_mod.parse(class_list, section=section)
    except classlist_mod.ClassListError as exc:
        raise click.ClickException(str(exc))

    click.echo(mapping.describe())
    click.echo(f"  read {len(students)} students")
    for note in notes:
        click.echo(f"  note: {note}")

    existing = roster_mod.Roster([])
    if os.path.isfile(out):
        try:
            existing = roster_mod.load(out)
        except roster_mod.RosterError as exc:
            raise click.ClickException(f"{out}: {exc}")
        click.echo(f"  merging into {out} ({len(existing)} already there)")

    scope = set(covers) or {s.section for s in students if s.section}
    merged, report = classlist_mod.merge(existing, students, scope=scope or None)
    click.echo("")
    if scope:
        click.echo(f"  treating this file as covering section(s) "
                   f"{', '.join(sorted(scope))}; students elsewhere are "
                   f"untouched")
    click.echo(f"  {report.describe()}")
    for label, names in (("added", report.added),
                         ("updated", report.updated),
                         ("dropped", report.dropped)):
        for name in names:
            click.echo(f"    {label:8} {name}")

    if dry_run:
        click.echo("\ndry run -- nothing was written.")
        return
    with open(out, "w", encoding="utf-8") as f:
        f.write(roster_mod.to_toml(merged, "checkit-printit roster import"))
    click.echo(f"\nwrote {out}")

    # Dropping empties the seat, whoever initiated it. Leaving that to the
    # operator would mean every import ending in a refused build, because the
    # chart is the print list and the two are checked against each other.
    if seating_path is None:
        seating_path = os.path.join(os.path.dirname(os.path.abspath(out)),
                                    "seating.toml")
    if report.dropped and os.path.isfile(seating_path):
        text = open(seating_path, encoding="utf-8").read()
        emptied = 0
        by_name = {s.name: s for s in merged}
        for name in report.dropped:
            student = by_name.get(name)
            for spelling in {name, student.display if student else ""}:
                if spelling:
                    text, count = seating.blank_seat(text, spelling)
                    emptied += count
        if emptied:
            with open(seating_path, "w", encoding="utf-8") as f:
                f.write(text)
            click.echo(f"emptied {emptied} seat(s) in {seating_path}")
        else:
            click.echo("none of the dropped students held a seat")


@roster.command(name="drop")
@click.argument("who")
@click.option("-r", "--roster", "roster_path", default="roster.toml",
              type=click.Path(exists=True))
@click.option("-s", "--seating", "seating_path", default="seating.toml",
              type=click.Path())
def roster_drop(who, roster_path, seating_path):
    """Drop a student: flag the roster, empty their seat.

    The roster keeps them, because the print record refers to them. The
    seating chart loses them, because that is what stops the printing -- the
    chart is the print list. Their seat is left empty rather than removed, so
    their tablemates keep the version letters they already had.
    """
    # The drawn room, when there is one, sits beside the chart it writes.
    # Named out of the one table of filenames rather than spelled here, so
    # the two cannot drift apart.
    room_path = os.path.join(os.path.dirname(seating_path) or ".",
                             course_mod.FILENAMES["room"])
    _set_dropped(who, roster_path, seating_path, dropped=True,
                 room_path=room_path)


@roster.command(name="restore")
@click.argument("who")
@click.option("-r", "--roster", "roster_path", default="roster.toml",
              type=click.Path(exists=True))
def roster_restore(who, roster_path):
    """Undo a drop. Does not put the student back in the seating chart --
    they need a seat choosing, which is the chart's business, not this one."""
    _set_dropped(who, roster_path, None, dropped=False)


def _set_dropped(who, roster_path, seating_path, dropped, room_path=None):
    """Render what `roster.set_dropped` did. The rule lives there, so the GUI
    can call it without going through click."""
    try:
        done = roster_mod.set_dropped(roster_path, who, dropped, seating_path,
                                      room_path)
    except roster_mod.RosterError as exc:
        raise click.ClickException(str(exc))

    if not done.changed:
        state = "already dropped" if dropped else "not dropped"
        click.echo(f"{done.student.name} is {state}; nothing to do.")
        return

    click.echo(f"{'dropped' if dropped else 'restored'} {done.student.name}"
               f"  ({roster_path})")
    if done.seating_checked:
        if done.seats_emptied:
            click.echo(f"emptied {done.seats_emptied} seat(s) in {seating_path}")
        else:
            click.echo(f"no seat found in {seating_path}; nothing to empty")
    if done.room_emptied:
        click.echo(f"emptied {done.room_emptied} chair(s) in {room_path}, "
                   f"so the next write of the chart does not seat them again")
    if not dropped:
        click.echo("give them a seat in the chart when you are ready.")


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
        f.write(roster_mod.to_toml(roster, "checkit-printit roster restore"))
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
@click.option("--ids/--no-ids", default=None,
              help="The student id field in the header. Overrides the "
                   "publication for this build only.")
@click.option("--codes/--no-codes", default=None,
              help="The scanning code in the footer. Overrides the "
                   "publication for this build only.")
@click.option("--only", multiple=True, metavar="KEY",
              help="Print for these students only, by id, alternate id or "
                   "email. Repeatable. Overrides the publication.")
@click.option("--replace", is_flag=True,
              help="Build into a folder that already holds a different "
                   "run, replacing it. Refused without this, because the "
                   "folder's page index is the only record of who held "
                   "which printed paper.")
@click.option("--rebuilt", is_flag=True,
              help="Recover a lost page index: build into the folder "
                   "again, replacing what is there, and mark the run as "
                   "rebuilt. Who held which page comes back exactly, from "
                   "the roster and the seating chart; the seeds are a "
                   "fresh draw and not what was printed, which is what "
                   "the mark is for.")
@click.option("--record/--no-record", "keep_record", default=True,
              help="Note the run in the course's print record. --no-record "
                   "is for a throwaway build: nothing is written to the "
                   "record, and the papers carry no scanning code, because "
                   "there would be nothing to look one up in.")
def build(pub_path, out, do_compile, seed, preview, replay, ids, codes,
          only, replace, rebuilt, keep_record):
    """Assemble the class set, and compile it."""
    try:
        result = runner.run(pub_path, out=out, do_compile=do_compile,
                            seed=seed, preview=preview, replay=replay,
                            ids=ids, codes=codes, keep_record=keep_record,
                            only=only, replace=replace,
                            rebuilt=rebuilt)
    except FolderInUse as exc:
        raise click.ClickException(str(exc))
    except runner.BuildError as exc:
        raise click.ClickException(str(exc))

    for note in result.replay_notes:
        click.echo(f"replay  note: {note}")
    if result.replayed:
        click.echo(f"replay  {result.replay_papers} papers pinned from "
                   f"{os.path.join(replay, manifest_mod.FILENAME)}")
    if result.theme_installed:
        click.echo(f"theme   wrote {result.theme_installed} -- edit it to "
                   f"change the look")
    if result.theme_declared:
        click.echo("theme   declared it in the bank's bank.xml, so "
                   "`checkit generate` publishes it")

    _report(result)

    if result.preview:
        click.echo("\npreview only -- nothing was written.")
        return

    if result.record_error:
        click.echo(f"\ncould not write the print record: {result.record_error}")
    elif result.record_path:
        click.echo(f"\nrecorded {result.recorded} paper(s) in "
                   f"{result.record_path}")
        if result.unnamed:
            click.echo(f"  {result.unnamed} handout(s) had no student id and "
                       f"were counted but not attributed")

    if not result.compiled:
        click.echo(f"\nnot compiled. To build it yourself:\n  "
                   f"cd {result.out} && pdflatex main.tex")
        return
    click.echo(f"\nPDF: {result.pdf}")






def _report(result):
    report, publication = result.report, result.publication
    click.echo(f"bank    {publication.bank_path}")
    click.echo(f"theme   {result.theme_origin}")
    click.echo(f"out     {result.out}")
    if result.replayed:
        # Not "repeat this draw with --seed": nothing was drawn, and the
        # versions came from the manifest rather than from this number.
        click.echo(f"seed    {result.run_seed}   (carried from the run being "
                   f"replayed; it drew nothing here)")
    else:
        click.echo(f"seed    {result.run_seed}   (repeat this draw with "
                   f"--seed {result.run_seed})")
    click.echo("")
    if result.printed_for < result.roster_size:
        click.echo(f"  students {report['students']}   (this run is for "
                   f"{result.printed_for} of {result.roster_size}; the rest "
                   f"of the class is not in it)")
    else:
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

    if report.get("header_gaps"):
        click.echo(f"  NOTE     this course has no "
                   f"{' and no '.join(report['header_gaps'])}, so the top "
                   f"right corner of every page prints blank. Set them on "
                   f"the Setup tab, or in course.toml.")

    for slug, fields in report["missing_fields"].items():
        click.echo(f"  NOTE     {slug}'s template asked for "
                   f"{', '.join(fields)}, which its generator does not set. "
                   f"Rendered as nothing -- fine if it is inside a LaTeX "
                   f"comment, a bug if it is not.")

    for a, b, version in report["collisions"]:
        click.echo(f"  WARNING  {a.name} and {b.name} are adjacent in group "
                   f"{a.group} and were both printed version {version}")
    # Short, and grammatical whether it is one name or six. "this run
    # names X, Y, who has been dropped" stops working at two, and
    # these are lists because there can be two.
    if result.dropped_students:
        click.echo(f"  WARNING  nothing printed for "
                   f"{', '.join(result.dropped_students)} -- dropped")
    if result.unmatched_students:
        click.echo(f"  WARNING  nothing printed for "
                   f"{', '.join(result.unmatched_students)} -- not in the "
                   f"roster")
    if result.unmatched_overrides:
        click.echo(f"  WARNING  override(s) for "
                   f"{', '.join(result.unmatched_overrides)} matched nobody "
                   f"in the roster, so nothing was changed for them")
    if result.rebuilt:
        click.echo("  NOTE     recorded as a rebuilt index. Who held which "
                   "page is right; the seeds are a fresh draw and not "
                   "the ones that were printed.")
    if result.anonymous:
        click.echo("  WARNING  no names and no id field, so nothing on "
                   "these papers says who sat them. Scans will read the "
                   "code and find the skill, and have no way to attribute "
                   "the paper to anybody.")
    if report["unseated"]:
        click.echo(f"  WARNING  not in the seating chart, printed last: "
                   f"{', '.join(report['unseated'])}")



# ---------------------------------------------------------------------------
# Masking
# ---------------------------------------------------------------------------

def _vault_path(course, given):
    """Where this course's vault is. `--vault` overrides the default."""
    if given:
        return given
    if not course:
        raise click.ClickException(
            "say which course this is, with -c/--course. The vault is named "
            "after the course so that every file from one course shares one "
            "set of pseudonyms -- two vaults would give one student two fake "
            "identities, which defeats the point.")
    return vault_mod.path_for(course)


def _parse_mask_as(values):
    """`--mask-as 3=sid` -> {3: "sid"}."""
    out = {}
    for item in values:
        column, _, kind = item.partition("=")
        if not kind or not column.strip().isdigit():
            raise click.ClickException(
                f"--mask-as {item!r}: expected <column number>=<kind>, "
                "such as --mask-as 1=alt_id.")
        out[column.strip()] = kind.strip()
    return out


@main.group()
def vault():
    """Make a masked twin of a file, and put the real values back.

    For sharing a file that carries student names, ids or addresses --
    with an assistant, in a bug report, in a question to a colleague --
    without sharing the students.

    Every real person gets one fake person, kept in a vault outside
    every repository, and the fake one stands in for them. The twin has
    the same rows, the same columns and the same shape of value in every
    cell; `vault unmask` turns whatever comes back into the real thing.

    Three things worth knowing before relying on it:

    \b
    * The vault is the only way back. There is no recovery key. Back it
      up somewhere the masked files are not.
    * It masks files and text. Not screenshots, not tracebacks, not
      paths, not window titles.
    * Marks and grades come through unmasked, because a twin without
      them cannot be used to debug a gradebook.
    """


@vault.command(name="columns")
@click.argument("source", type=click.Path(exists=True))
@click.option("-c", "--course", default="", help="Which course's vault.")
@click.option("--vault", "vault_path", default=None, type=click.Path(),
              help="The vault file, instead of the one named for the course.")
@click.option("--header-row", default=None, type=int,
              help="Which row holds the column names, 1-based, when it "
                   "cannot be found automatically.")
@click.option("--keep", multiple=True,
              help="A column to pass through verbatim. Repeatable. Use it "
                   "only on a column you have looked at.")
def vault_columns(source, course, vault_path, header_row, keep):
    """Say what masking would do to each column. Writes nothing.

    Run this first on an unfamiliar file. Every column is listed,
    including the ones that would pass through -- a report of only the
    exceptions makes "nothing to see here" and "I did not look" print
    the same way.
    """
    try:
        rows = mask_mod.read_rows(source)
        known = None
        path = vault_path or (vault_mod.path_for(course) if course else None)
        if path and os.path.isfile(path):
            known = vault_mod.Vault.load(path)
        plan = mask_mod.plan(rows, header_row=header_row, keep=keep,
                             vault=known)
    except (mask_mod.MaskError, vault_mod.VaultError) as exc:
        raise click.ClickException(str(exc))
    click.echo(plan.describe())
    click.echo("")
    click.echo("  masked   replaced by this student's pseudonym")
    click.echo("  blanked  emptied: not recognised, so not trusted")
    click.echo("  kept     passed through unchanged")


@vault.command(name="mask")
@click.argument("source", type=click.Path(exists=True))
@click.option("-c", "--course", default="", help="Which course's vault.")
@click.option("-o", "--out", default=None, type=click.Path(),
              help="Where to write the twin. Defaults to the source name "
                   "with `-masked.csv` on the end, beside it.")
@click.option("--vault", "vault_path", default=None, type=click.Path(),
              help="The vault file, instead of the one named for the course.")
@click.option("--header-row", default=None, type=int,
              help="Which row holds the column names, 1-based.")
@click.option("--keep", multiple=True,
              help="A column to pass through verbatim. Repeatable.")
@click.option("--mask-as", "mask_as", multiple=True,
              help="Force a column to be masked as a kind, as 3=sid. For a "
                   "column whose header the tool does not recognise. "
                   "Repeatable.")
@click.option("--rows", default=None, type=int,
              help="Only the first N data rows. Fewer rows is less shared; "
                   "use it when the whole file is not needed.")
def vault_mask(source, course, out, vault_path, header_row, keep, mask_as,
               rows):
    """Write a masked twin of a file.

    The vault is created on first use and grown on every run after: a
    student seen before keeps the pseudonym they already had, which is
    what lets two files be masked and still agree about who is who.

    After writing, the twin is read back and searched for every real
    value the vault knows. If one survives, the twin is deleted and
    nothing is handed over.
    """
    path = _vault_path(course, vault_path)
    if out is None:
        stem, _ = os.path.splitext(source)
        out = stem + "-masked.csv"
    if os.path.abspath(out) == os.path.abspath(source):
        raise click.ClickException(
            "the twin would overwrite the source. Pass -o.")

    try:
        store = vault_mod.Vault.open_or_create(path, course)
        report = mask_mod.mask_file(
            source, out, store, header_row=header_row, keep=keep,
            mask_as=_parse_mask_as(mask_as), limit=rows)
        # Saved only now. A vault written before the output check passed
        # would describe a twin the check had just deleted.
        store.save(path)
    except (mask_mod.MaskError, vault_mod.VaultError) as exc:
        raise click.ClickException(str(exc))

    click.echo(report.plan.describe())
    click.echo("")
    click.echo(f"  {report.describe()}")
    click.echo(f"  checked: no real value survives in the twin")
    click.echo("")
    click.echo(f"wrote {out}")
    click.echo(f"vault {path}")
    click.echo("")
    click.echo("The vault holds real student data and is the only way to "
               "unmask. Keep it out of every repository, and do not send it "
               "anywhere with the twin.")


@vault.command(name="learn")
@click.option("-c", "--course", default="", help="Which course's vault.")
@click.option("--roster", "roster_path", default=None, type=click.Path(),
              help="The roster to learn from, instead of the course's own.")
@click.option("--vault", "vault_path", default=None, type=click.Path(),
              help="The vault file, instead of the one named for the course.")
def vault_learn(course, roster_path, vault_path):
    """Teach the vault everybody in a roster, without masking anything.

    `roster.toml` is an authoritative list of who exists, with real
    fields rather than a guess at which column is which. Once the vault
    has been through it, `mask-text` can mask a traceback or a log, and
    `mask-course` has what it needs.

    Run this first when the thing you want to share is not a table.
    """
    path = _vault_path(course, vault_path)
    if roster_path is None:
        if not course:
            raise click.ClickException(
                "say which course, with -c/--course, or name a roster with "
                "--roster.")
        roster_path = course_mod.file_in(course, "roster")
    if not os.path.isfile(roster_path):
        raise click.ClickException(f"no roster at {roster_path}.")

    try:
        store = vault_mod.Vault.open_or_create(path, course)
        before = len(store.people)
        count = maskcourse_mod.learn(store, roster_path)
        store.save(path)
    except (maskcourse_mod.CourseMaskError, vault_mod.VaultError) as exc:
        raise click.ClickException(str(exc))

    added = len(store.people) - before
    click.echo(f"read {count} students from {roster_path}")
    click.echo(f"  {added} new, {len(store.people)} in the vault now")
    click.echo(f"vault {path}")


@vault.command(name="mask-course")
@click.option("-c", "--course", default="", help="Which course.")
@click.option("-o", "--out", default=None, type=click.Path(),
              help="Where to write the twin. Defaults to "
                   "`<course>-masked` in the current directory. It may not "
                   "be inside the course folder or under the courses root.")
@click.option("--vault", "vault_path", default=None, type=click.Path(),
              help="The vault file, instead of the one named for the course.")
@click.option("--allow-digits", is_flag=True,
              help="Proceed when the twin still holds a 9+ digit run that is "
                   "not a known pseudonym. Seeds and hashes look like that; "
                   "look at the reported lines before passing this.")
def vault_mask_course(course, out, vault_path, allow_digits):
    """Write a masked twin of a whole course folder.

    For when the problem is in the course state itself rather than in a
    file you can hand over: the roster, the seating chart, the room, the
    print record.

    \b
    Two folders are never copied, and that is not an option:
      secrets/  credentials, which cannot be masked
      scans/    scanned papers -- images of handwriting, with names on

    An unrecognised file is skipped and reported, never copied.

    Everything written is checked twice: for any real value the vault
    knows, and for anything that still *looks* personal -- an address on
    an unknown domain, or a long number that is not a pseudonym. On any
    failure the whole output directory is removed, because a half-masked
    course folder is worse than none: it looks like a twin.
    """
    if not course:
        raise click.ClickException("say which course, with -c/--course.")
    path = _vault_path(course, vault_path)
    course_path = course_mod.path_for(course)
    if out is None:
        out = os.path.join(os.getcwd(), f"{course}-masked".replace(" ", "-"))

    try:
        store = vault_mod.Vault.open_or_create(path, course)
        report = maskcourse_mod.mask_course(course_path, out, store,
                                            allow_digits=allow_digits)
        # Saved last, as with `mask`: a vault written before the checks
        # passed would describe a directory that has just been removed.
        store.save(path)
    except (maskcourse_mod.CourseMaskError, vault_mod.VaultError) as exc:
        raise click.ClickException(str(exc))

    click.echo(report.describe())
    click.echo("")
    click.echo("  checked: no real value, no stray address, no unexplained "
               "long number")
    click.echo("")
    click.echo(f"wrote {report.out_path}/")
    click.echo(f"vault {path}")
    click.echo("")
    click.echo("The vault holds real student data and is the only way to "
               "unmask. Keep it out of every repository, and do not send it "
               "anywhere with the twin.")


@vault.command(name="mask-text")
@click.argument("source", type=click.Path(exists=True))
@click.option("-c", "--course", default="", help="Which course's vault.")
@click.option("-o", "--out", default=None, type=click.Path(),
              help="Where to write. Defaults to the source name with "
                   "`-masked` before the extension.")
@click.option("--vault", "vault_path", default=None, type=click.Path(),
              help="The vault file, instead of the one named for the course.")
def vault_mask_text(source, course, out, vault_path):
    """Mask a traceback, a log, or anything else that is not a table.

    Substitution only: it replaces what the vault already knows, so run
    `vault learn` first. It cannot classify columns, because there are
    none.

    The report says both how much was replaced **and** what still looks
    personal. Zero replacements on its own is ambiguous -- it reads as
    "clean" and may mean "the vault does not know these people" -- so
    the second number is what to believe.
    """
    path = _vault_path(course, vault_path)
    if out is None:
        stem, ext = os.path.splitext(source)
        out = stem + "-masked" + (ext or ".txt")

    try:
        store = vault_mod.Vault.load(path)
    except vault_mod.VaultError as exc:
        raise click.ClickException(str(exc))
    hits = maskcourse_mod.mask_text_file(source, out, store)

    with open(out, encoding="utf-8", errors="replace") as f:
        written = f.read()
    leaked = store.leaks(written)
    addresses, digits = maskcourse_mod.residual(written, store)

    click.echo(f"{hits} substitution(s) from {len(store.people)} students")
    if leaked:
        os.remove(out)
        raise click.ClickException(
            f"{len(leaked)} real value(s) still present, so nothing was "
            "written. That should not happen after a substitution pass -- "
            "run `vault check` on the source to see what the vault knows.")
    if addresses:
        click.echo(f"  ! address-shaped text remains on line(s) "
                   + ", ".join(str(n) for n in addresses[:12]))
    if digits:
        click.echo(f"  ! {len(digits)} line(s) hold a 9+ digit run that is "
                   f"not a known pseudonym, first at line {digits[0]}")
    if not addresses and not digits:
        click.echo("  nothing left that looks personal")
    else:
        click.echo("  look at those lines before sending this.")
    click.echo(f"wrote {out}")


@vault.command(name="unmask")
@click.argument("source", type=click.Path(exists=True))
@click.option("-c", "--course", default="", help="Which course's vault.")
@click.option("-o", "--out", default=None, type=click.Path(),
              help="Where to write. Defaults to the source name with "
                   "`-real` before the extension.")
@click.option("--vault", "vault_path", default=None, type=click.Path(),
              help="The vault file, instead of the one named for the course.")
def vault_unmask(source, course, out, vault_path):
    """Put the real values back into a file that came back masked.

    A plain text pass, so it works on whatever shape it is given: a
    corrected CSV, a gradebook profile, a diff, a patch, an answer
    saved to a file.

    A run that replaces nothing is an error, not a success. Zero
    replacements reads as "nothing needed changing" and nearly always
    means this vault does not describe this file.

    One known gap: a one-letter value does not come back. Middle
    initials are masked to `X` and stay that way -- see the note in
    `vault.py` for why a per-person mapping of single letters is worse
    than no mapping at all.
    """
    path = _vault_path(course, vault_path)
    if out is None:
        stem, ext = os.path.splitext(source)
        out = stem + "-real" + (ext or ".txt")

    try:
        store = vault_mod.Vault.load(path)
        hits = mask_mod.unmask_file(source, out, store)
    except (mask_mod.MaskError, vault_mod.VaultError) as exc:
        raise click.ClickException(str(exc))

    if not hits:
        os.remove(out)
        raise click.ClickException(
            f"nothing in {source} matched anything in {path}, so nothing was "
            "written. Either the file is not masked, or it was masked under a "
            "different vault. Check -c/--course.")
    click.echo(f"{hits} replacement(s)")
    click.echo(f"wrote {out}")


@vault.command(name="check")
@click.argument("source", type=click.Path(exists=True))
@click.option("-c", "--course", default="", help="Which course's vault.")
@click.option("--vault", "vault_path", default=None, type=click.Path(),
              help="The vault file, instead of the one named for the course.")
def vault_check(source, course, vault_path):
    """Search a file for real values, before sending it anywhere.

    The same scan `vault mask` runs on its own output, pointed at any
    file. Use it on anything hand-edited, and on anything assembled
    from several twins.

    This one does print the values it finds, because it is meant to be
    run by the person who already has them. `vault mask` deliberately
    does not.
    """
    path = _vault_path(course, vault_path)
    try:
        store = vault_mod.Vault.load(path)
    except vault_mod.VaultError as exc:
        raise click.ClickException(str(exc))
    with open(source, encoding="utf-8", errors="replace") as f:
        text = f.read()
    found = store.leaks(text)
    if not found:
        click.echo(f"{source}: clean against {len(store.people)} students "
                   f"in {path}")
        return
    click.echo(f"{source}: {len(found)} real value(s) present")
    for value in found:
        click.echo(f"  {value}")
    raise click.ClickException("do not send this file.")


@vault.command(name="show")
@click.option("-c", "--course", default="", help="Which course's vault.")
@click.option("--vault", "vault_path", default=None, type=click.Path(),
              help="The vault file, instead of the one named for the course.")
def vault_show(course, vault_path):
    """List who is in the vault, real name beside pseudonym.

    For your eyes. It prints real student data by definition -- that is
    what it is for, when you need to know which real student a
    pseudonym in an answer refers to.
    """
    path = _vault_path(course, vault_path)
    try:
        store = vault_mod.Vault.load(path)
    except vault_mod.VaultError as exc:
        raise click.ClickException(str(exc))

    click.echo(f"{path}")
    click.echo(f"  course {store.course or '(unnamed)'}, "
               f"{len(store.people)} students, created {store.created}")
    click.echo("")
    for person in store.people:
        real = " ".join(w for w in (person.real.get("first"),
                                    person.real.get("last")) if w)
        fake = " ".join(w for w in (person.fake.get("first"),
                                    person.fake.get("last")) if w)
        click.echo(f"  {person.tag}  {fake:<28} {real}")
    if store.domains:
        click.echo("")
        for real, fake in sorted(store.domains.items()):
            click.echo(f"        {fake:<28} {real}")


# ---------------------------------------------------------------------------
# The gradebook
# ---------------------------------------------------------------------------

#: Which roster field an LMS id column most likely joins to, best first.
#: Kept as a name here because the flags and the masking code below
#: read it, but it is `gradebook.ID_FIELDS` and no longer a second copy
#: of the list.
_ID_PREFERENCE = gradebook_mod.ID_FIELDS


def _bank_slugs(course):
    bank = course_mod.bank_for(course)
    if bank is None:
        raise click.ClickException(
            f"{course} is not pointed at a bank, so there is no list of "
            "skills to match the gradebook's columns against. Set one with "
            "`course init` or by editing the course's `course.toml`.")
    return bank.slugs()


@main.group()
def gradebook():
    """Match a gradebook's columns to this course's skills.

    An LMS export is round-tripped, not generated: the file you
    exported comes back with the cells there is a result for filled in
    and nothing else touched. That needs five facts about your file,
    and `gradebook map` works out as many of them as it can and asks
    about the rest.

    The answers live in `gradebook.toml` beside the course's other
    state. It is an ordinary readable file; correct it by hand if the
    tool got something wrong.
    """


@gradebook.command(name="map")
@click.argument("source", type=click.Path(exists=True))
@click.option("-c", "--course", default="", help="Which course.")
@click.option("--pair", multiple=True, metavar="SLUG=N",
              help="Pair a skill with a column number, for one the tool "
                   "could not find -- as --pair FCP=9. Repeatable, and "
                   "remembered.")
@click.option("--student-column", default=None, type=int, metavar="N",
              help="Which column holds the LMS id, if the tool picked wrong.")
@click.option("--matches", default=None,
              type=click.Choice(_ID_PREFERENCE),
              help="Which roster field that id joins to.")
@click.option("--ignore-row", multiple=True, metavar="TEXT",
              help="Never write to a row whose id contains this, such as "
                   "-DoNotUse. Repeatable.")
@click.option("--header-row", default=None, type=int,
              help="Which row holds the column names, 1-based.")
@click.option("--passed", "passed_mark", default=None, metavar="TEXT",
              help="The exact cell contents for a pass, when the tool "
                   "cannot tell which of the values it found is which. "
                   "It decides by looking for 'pass' in the string, so "
                   "a gradebook marked 1 and 0, or with ticks, or in "
                   "another language, needs telling.")
@click.option("--not-passed", "not_passed_mark", default=None,
              metavar="TEXT", help="The exact cell contents for a "
                                   "non-pass. Goes with --passed.")
@click.option("--dry-run", is_flag=True,
              help="Report, and write nothing.")
def gradebook_map(source, course, pair, student_column, matches, ignore_row,
                  header_row, passed_mark, not_passed_mark, dry_run):
    """Work out which column is which, and save the answers.

    Run it on the file you exported from the LMS -- or on a masked twin
    of it, which gives exactly the same answers, because none of what
    gets saved is student data: column names, two mark strings, and a
    row marker.

    Nothing is guessed where guessing could be wrong. A skill that
    matches no column, or more than one, is reported and left for you
    to pair with `--pair`.
    """
    if not course:
        raise click.ClickException("say which course, with -c/--course.")
    slugs = _bank_slugs(course)
    rows = mask_mod.read_rows(source)
    if not rows:
        raise click.ClickException(f"{source} is empty.")

    try:
        index = mask_mod.find_header(rows, header_row)
    except mask_mod.MaskError as exc:
        raise click.ClickException(str(exc))
    head, body = rows[index], rows[index + 1:]
    body = [r for r in body if any(c.strip() for c in r)]
    click.echo(f"{len(head)} columns, {len(body)} rows, header row "
               f"{index + 1}")

    profile_path = gradebook_mod.path_for(course)
    existing = None
    if os.path.isfile(profile_path):
        try:
            existing = gradebook_mod.load(profile_path)
        except gradebook_mod.GradebookError as exc:
            raise click.ClickException(str(exc))
        click.echo(f"building on {profile_path}")

    # ---------------------------------------------------- the student --
    chosen = None
    if student_column is not None:
        if not 1 <= student_column <= len(head):
            raise click.ClickException(
                f"--student-column {student_column} is outside the file, "
                f"which has {len(head)} columns.")
        chosen = student_column - 1
    elif existing and existing.student_column in head:
        chosen = head.index(existing.student_column)

    # The masker's synonym table already knows what an id column is
    # called, so it is reused rather than a second list being kept.
    found = {}
    for decision in mask_mod.plan(rows, header_row=header_row).decisions:
        if decision.action == "mask" and decision.kind in _ID_PREFERENCE:
            found.setdefault(decision.kind, decision.index)
    if chosen is None:
        for kind in _ID_PREFERENCE:
            if kind in found:
                chosen = found[kind]
                break
    if chosen is None:
        raise click.ClickException(
            "no column in this file reads as a student identifier. Name it "
            "with --student-column N; the columns are numbered in "
            "`vault columns`.")
    joins = (matches
             or (existing.student_matches if existing else None)
             or next((k for k, i in found.items() if i == chosen),
                     "alt_id"))
    click.echo(f"\nstudent: column {chosen + 1}, {head[chosen]!r}, "
               f"joined on the roster's {joins}")
    others = [i for k, i in found.items() if i != chosen]
    if others:
        click.echo("  other identifier-ish columns: "
                   + ", ".join(str(i + 1) for i in sorted(others)))

    # ------------------------------------------------------ the pairs --
    pairs = dict(existing.pairs) if existing else {}
    for item in pair:
        slug, _, number = item.partition("=")
        slug = slug.strip()
        if not number.strip().isdigit():
            raise click.ClickException(
                f"--pair {item!r}: expected SLUG=<column number>, such as "
                "--pair FCP=9.")
        position = int(number) - 1
        if not 0 <= position < len(head):
            raise click.ClickException(
                f"--pair {item!r}: column {number} is outside the file.")
        if slug not in slugs:
            raise click.ClickException(
                f"--pair {item!r}: {slug!r} is not a skill in this bank. "
                f"It has {', '.join(slugs)}.")
        pairs[slug] = head[position]

    report = gradebook_mod.match(head, slugs, pairs=pairs)
    click.echo("")
    click.echo(report.describe(head))

    # ------------------------------------------------------ the marks --
    skill_columns = sorted(report.found.values())
    passed, not_passed, extra = gradebook_mod.guess_marks(body, skill_columns)
    # What he said beats what the file suggested. `guess_marks` decides
    # by looking for "pass" in the string, which settles a Brightspace
    # export and settles nothing for one marked 1 and 0, or with ticks,
    # or in another language -- and until these flags existed the only
    # way out was editing the TOML by hand.
    told = [m for m in (passed_mark, not_passed_mark) if m is not None]
    if len(told) == 1:
        raise click.ClickException(
            "--passed and --not-passed go together: naming one and "
            "guessing the other is how the wrong string gets written.")
    if passed_mark is not None:
        if passed_mark == not_passed_mark:
            raise click.ClickException(
                "--passed and --not-passed are the same string.")
        seen = set(extra) | {v for v in (passed, not_passed) if v}
        for label, value in (("--passed", passed_mark),
                             ("--not-passed", not_passed_mark)):
            # A warning, not a refusal: a column may be entirely blank
            # on the day it is mapped, and the mark still has to be
            # nameable.
            if seen and value not in seen:
                click.echo(f"note: {label} {value!r} does not appear in "
                           f"any skill column of this file")
        passed, not_passed = passed_mark, not_passed_mark
        extra = [e for e in extra if e not in (passed, not_passed)]
        click.echo("")
        click.echo("marks: given on the command line, not read from the "
                   "file")

    click.echo("")
    if passed and not_passed:
        click.echo(f"marks: a pass is {passed!r}, a non-pass is "
                   f"{not_passed!r}")
        # The codepoints as well as the characters. On the real export a
        # pass is a trophy followed *immediately* by `Pass`, and whether
        # there is a space after the emoji is invisible when the
        # characters are shown but obvious here. The export has to write
        # these bytes exactly.
        for label, value in (("pass", passed), ("non-pass", not_passed)):
            points = " ".join("U+%04X" % ord(c) for c in value)
            click.echo(f"  {label:<9} {points}")
        click.echo("  taken from the file, never retyped -- the exact "
                   "characters are what gets written back")
        if extra:
            click.echo(f"  also present, and treated as a non-pass: "
                       + ", ".join(repr(e) for e in extra))
    else:
        click.echo("marks: could not tell which value means a pass.")
        if extra:
            click.echo("  the values in those columns are: "
                       + ", ".join(repr(e) for e in extra[:12]))
        click.echo("  name them with --passed and --not-passed, or set "
                   "them by hand in " + profile_path)

    # ------------------------------------------------------ the blanks --
    meaning, evidence = gradebook_mod.blank_evidence(
        body, head, skill_columns, passed)
    click.echo("")
    click.echo(f"a blank cell means: {meaning}")
    if evidence:
        click.echo(f"  shown by {evidence}")
    else:
        click.echo("  nothing in the file settles this, so the cautious "
                   "answer stands: blanks are left alone. If your gradebook "
                   "counts a blank as a zero, set blank_means = \"zero\".")

    # -------------------------------------------------- rows to avoid --
    ignore_rows = list(existing.ignore_rows) if existing else []
    ignore_rows += [r for r in ignore_row if r not in ignore_rows]
    shared = gradebook_mod.shared_base_ids(body, chosen)
    if shared:
        click.echo("")
        click.echo(f"{len(shared)} id(s) appear on more than one row:")
        import re as _re
        suggest = {}
        for base, hits in sorted(shared.items()):
            click.echo(f"  {len(hits)} rows share a base id, on rows "
                       + ", ".join(str(n) for n, _ in hits))
            # **Every column, not just the one being matched on.**
            # Brightspace marks a retired enrolment on `OrgDefinedId`,
            # and he matches on `OSW_ID` -- so looking only at the
            # student column found nothing and reported that there was
            # nothing to tell the rows apart by, which was wrong.
            numbers = {n for n, _ in hits}
            group = [r for i, r in enumerate(body, 2) if i in numbers]
            for column in range(max(len(r) for r in group)):
                values = [r[column] if column < len(r) else ""
                          for r in group]
                marks = [_re.search(r"(?<=\d)(\D+)$", v) for v in values]
                if any(marks) and not all(marks):
                    for found in marks:
                        if found:
                            suggest.setdefault(found.group(1), column + 1)
        for marker in sorted(set(suggest) - set(ignore_rows)):
            click.echo(f"  one of them is marked {marker!r}, in column "
                       f"{suggest[marker]}. If that is a retired "
                       f"enrolment, add --ignore-row {marker!r} so nothing "
                       "is ever written to it.")
        if not suggest:
            click.echo("  none of them carries a marker, so there is nothing "
                       "to tell them apart by. Decide before exporting.")

    # ----------------------------------------------------- the profile --
    claimed = set(report.found.values()) | {chosen}
    profile = gradebook_mod.Profile(
        name=(existing.name if existing and existing.name
              else f"{course} gradebook"),
        student_column=head[chosen], student_matches=joins,
        passed=passed, not_passed=not_passed, blank_means=meaning,
        pairs={s: h for s, h in pairs.items() if s in report.found},
        ignore_rows=ignore_rows,
        ignore_columns=[h for i, h in enumerate(head) if i not in claimed])

    click.echo("")
    if report.missing:
        click.echo(f"  {len(report.missing)} skill(s) still have no column: "
                   + " ".join(report.missing))
        click.echo("  they will be skipped on export until paired. Pick from "
                   "the spare columns above, as --pair SLUG=N.")
    click.echo(f"  {len(profile.ignore_columns)} column(s) belong to nothing "
               "in the bank and will never be written to")

    if dry_run:
        click.echo("\ndry run -- nothing was written.")
        return
    try:
        profile.validate(head)
    except gradebook_mod.GradebookError as exc:
        raise click.ClickException(
            f"{exc}\n\nNothing was written. Correct it on the command line, "
            f"or write {profile_path} by hand.")
    gradebook_mod.save(profile_path, profile)
    click.echo(f"\nwrote {profile_path}")


@gradebook.command(name="export")
@click.argument("sources", nargs=-1, required=True,
                type=click.Path(exists=True))
@click.option("-c", "--course", default="", help="Which course.")
@click.option("-o", "--out", "out_dir", default=None, type=click.Path(),
              help="A directory to write the filled-in copies into, named "
                   "`<original>_UPDATED.csv`. **Without this nothing is "
                   "written** -- the run only reports, which is the right "
                   "default for something that changes grades.")
@click.option("--not-yet", "not_yet", default="", metavar="SLUGS",
              help="Comma-separated skills for which a non-pass may be "
                   "written, and then only into an empty cell. Without "
                   "this, only passes are written. Entering a non-pass "
                   "raises that student's denominator where the subtotals "
                   "count filled cells, so it is named deliberately for "
                   "the skills in play.")
@click.option("--header-row", default=None, type=int,
              help="Which row holds the column names, 1-based.")
def gradebook_export(sources, course, out_dir, not_yet, header_row):
    """Fill in the cells there is a result for, and change nothing else.

    Give it every file you exported -- **one per section**, all at once.
    A student should appear in exactly one of them, and that is only
    checkable with all of them in hand.

    Each file comes back as a copy with the same columns in the same
    order, the same rows, and **every untouched line byte for byte**:
    changed lines are spliced, the rest are copied, so what you upload
    is the file you downloaded.

    \b
    A pass goes in where the cell is empty or says not-yet.
    A non-pass goes in only for a skill named in --not-yet, and
      only into an empty cell.
    A pass already in the gradebook is NEVER replaced.
    An absence writes nothing: it is not an attempt at the skill.
    A cell holding anything else stops the export.

    These are the rules `apply_to_brightspace.py` already follows.
    """
    if not course:
        raise click.ClickException("say which course, with -c/--course.")
    slugs = _bank_slugs(course)
    try:
        profile = gradebook_mod.load(gradebook_mod.path_for(course))
    except gradebook_mod.GradebookError as exc:
        raise click.ClickException(str(exc))

    wanted = {s.strip() for s in not_yet.split(",") if s.strip()}

    roster_path = course_mod.file_in(course, "roster")
    if not os.path.isfile(roster_path):
        raise click.ClickException(f"no roster at {roster_path}.")
    try:
        people = roster_mod.load(roster_path)
    except roster_mod.RosterError as exc:
        raise click.ClickException(f"{roster_path}: {exc}")

    sheets, header_lines = [], {}
    for path in sources:
        rows = mask_mod.read_rows(path)
        if not rows:
            raise click.ClickException(f"{path} is empty.")
        try:
            index = mask_mod.find_header(rows, header_row)
            profile.validate(rows[index])
        except (mask_mod.MaskError, gradebook_mod.GradebookError) as exc:
            raise click.ClickException(f"{path}: {exc}")
        sheet = gradebook_mod.sheet_from(path, rows[index:],
                                         header_line=index + 1)
        if any(s.name == sheet.name for s in sheets):
            raise click.ClickException(
                f"two of these files are called {sheet.name!r}. They are "
                "told apart by name, so rename one.")
        sheets.append(sheet)
        header_lines[sheet.name] = path

    record_path = course_mod.file_in(course, "record")
    progress = record_mod.progress(record_path)
    if not progress:
        raise click.ClickException(
            f"nothing has been graded in {record_path}, so there is no "
            "result to export. Read a stack in on the Scans tab first.")

    # The course's own thresholds, so a skill that needs two passes is
    # not exported as passed after one. Progress has always read these;
    # the export did not, and the two disagreed in the direction of
    # overstating a grade.
    needs = course_mod.thresholds(course)
    changes, report = gradebook_mod.plan_export(
        sheets, profile, people, progress, slugs, not_yet=wanted,
        thresholds=needs)
    if needs:
        click.echo("thresholds above one: "
                   + ", ".join(f"{slug} needs {n}"
                               for slug, n in sorted(needs.items())))

    click.echo(f"{len(sheets)} file(s), "
               f"{sum(len(s.body) for s in sheets)} rows, "
               f"{len(people.live())} students enrolled, "
               f"{len(progress)} graded (student, skill) pair(s)")
    for sheet in sheets:
        where = f", looks like section {sheet.section}" if sheet.section \
            else ""
        click.echo(f"  {sheet.name}  {len(sheet.body)} rows{where}")
    click.echo(f"matching on the roster's {profile.student_matches}, "
               f"against {profile.student_column!r}")
    if wanted:
        click.echo("a non-pass may be written for: "
                   + ", ".join(sorted(wanted)))
    else:
        click.echo("no --not-yet given, so only passes will be written")
    click.echo("")
    click.echo(report.describe())

    for sheet in sheets:
        mine = report.for_sheet(sheet.name)
        if not mine:
            continue
        click.echo("")
        click.echo(f"  {sheet.name}: {len(mine)} cell(s)")
        by_skill = {}
        for change in mine:
            by_skill.setdefault(change.slug, []).append(change)
        for slug in sorted(by_skill):
            group = by_skill[slug]
            blank = sum(1 for c in group if not c.was.strip())
            click.echo(f"    {slug:<8} {len(group):>3} cell(s), "
                       f"{blank} into a blank, {len(group) - blank} over a "
                       "non-pass")

    passes = report.kept_passes()
    if passes:
        click.echo("")
        click.echo("  a pass stands here although the record disagrees "
                   "-- never replaced:")
        for keep in passes:
            click.echo(f"    {keep.sheet} row {keep.row:>3}  {keep.slug}")

    if report.refused:
        raise click.ClickException(
            "nothing was written: the problems above have to be settled "
            "first.")

    if out_dir is None:
        click.echo("")
        click.echo("nothing was written -- pass -o DIR to write the "
                   "filled-in copies.")
        return

    os.makedirs(out_dir, exist_ok=True)
    written, trims = [], {}
    try:
        for sheet in sheets:
            source = header_lines[sheet.name]
            filled = gradebook_mod.apply_export(sheet, changes)
            problems = gradebook_mod.verify_export(
                sheet.rows, filled, changes, sheet.name)
            if problems:
                raise gradebook_mod.GradebookError(
                    "the filled-in rows did not match the plan:\n  "
                    + "\n  ".join(problems))

            stem, ext = os.path.splitext(os.path.basename(source))
            # `_IMPORT` when the file had to be narrowed for the LMS to
            # read it, `_UPDATED` when it comes back the same shape.
            # The name is the only thing on the file saying which of
            # the two it is.
            keep, dropped = gradebook_mod.importable_columns(sheet.head)
            suffix = "_IMPORT" if dropped else "_UPDATED"
            target = os.path.join(out_dir, f"{stem}{suffix}{ext or '.csv'}")
            if os.path.abspath(target) == os.path.abspath(source):
                raise gradebook_mod.GradebookError(
                    f"{target} is the file you exported. Choose another -o.")
            data = gradebook_mod.splice(source, changes, sheet.name,
                                        header_line=sheet.header_line)
            with open(target, "wb") as f:
                f.write(data)
            written.append((sheet, source, target))

            # And read it back, because what was checked above was the
            # rows in memory and not the file that will be uploaded.
            back = mask_mod.read_rows(target)
            problems = gradebook_mod.verify_export(
                sheet.rows, back[sheet.header_line - 1:], changes, sheet.name)
            if problems:
                raise gradebook_mod.GradebookError(
                    f"{target} did not match the plan:\n  "
                    + "\n  ".join(problems))

            # And then make it a file the LMS will take. Brightspace
            # refuses its own export over the columns it computes for
            # itself; see `importable_columns`. Trimmed after the
            # check above, which compares columns by index and should
            # be looking at the file as it was handed over.
            if dropped:
                # Nothing this export wrote to may be dropped. The
                # rule is written in terms of what the LMS computes,
                # so a skill column cannot match it -- which is
                # exactly the sort of thing to check rather than to
                # rely on.
                lost = sorted({c.slug for c in report.for_sheet(sheet.name)
                               if c.column - 1 not in keep})
                if lost:
                    raise gradebook_mod.GradebookError(
                        f"{target}: trimming for import would drop the "
                        "column(s) holding " + ", ".join(lost))
                with open(target, "wb") as f:
                    f.write(gradebook_mod.drop_columns(data, keep))
                # Read back again, for the same reason as above: what
                # matters is the file on disk, not the bytes in hand.
                problems = gradebook_mod.verify_dropped(
                    back[sheet.header_line - 1:],
                    mask_mod.read_rows(target)[sheet.header_line - 1:],
                    keep, sheet.name)
                if problems:
                    raise gradebook_mod.GradebookError(
                        f"{target} is not a faithful trim:\n  "
                        + "\n  ".join(problems))
                trims[sheet.name] = dropped
    except gradebook_mod.GradebookError as exc:
        for _, _, target in written:
            if os.path.isfile(target):
                os.remove(target)
        raise click.ClickException(
            f"{exc}\n\nNothing was left behind: any copy already written "
            "has been deleted, because a half-updated set is worse than "
            "none.")

    click.echo("")
    for sheet, source, target in written:
        mine = len(report.for_sheet(sheet.name))
        click.echo(f"wrote {mine} cell(s) into {target}")
    click.echo("  untouched lines are copied byte for byte")
    click.echo("  checked after writing: exactly the planned cells differ")

    if trims:
        click.echo("")
        click.echo("Columns removed so the LMS can read the file back. "
                   "Brightspace will not accept its own export: it holds "
                   "columns it computes for itself, and columns that are "
                   "not grade items at all, and the import refuses the "
                   "whole file over them rather than skipping them.")
        for name in sorted(trims):
            click.echo(f"  {name}: {len(trims[name])} column(s)")
            for index, header, why in trims[name]:
                click.echo(f"    {index + 1:>3}  {header}")
                click.echo(f"         {why}")
        click.echo("  nothing is lost in the LMS: these are values it "
                   "works out for itself, and it will do so again.")

    click.echo("")
    click.echo("Import these soon after exporting. A grade changed in the "
               "LMS in between would be set back to the exported value.")


@gradebook.command(name="audit")
@click.argument("before", type=click.Path(exists=True))
@click.argument("after", type=click.Path(exists=True))
@click.option("-c", "--course", default="", help="Which course.")
@click.option("--not-yet", "not_yet", default="", metavar="SLUGS",
              help="The same list the export was run with. Without it, a "
                   "non-pass in the file is reported as written for a "
                   "skill nobody asked for -- the right answer when the "
                   "flag genuinely was not passed, and a false alarm when "
                   "it was.")
@click.option("--header-row", default=None, type=int,
              help="Which row holds the column names, 1-based.")
def gradebook_audit(before, after, course, not_yet, header_row):
    """Check a filled-in gradebook against the record, cell by cell.

    BEFORE is the file as the LMS exported it; AFTER is the copy you
    are about to upload. Reads both, writes nothing.

    **A different question from the one `export` already answers.**
    Every write is checked against the plan that produced it -- but a
    plan that is wrong and a write that is faithful to it both pass
    that check, because the plan is the question and the answer. This
    asks instead whether every cell in the finished file agrees with
    what the record says, and it takes a file from anywhere: this
    tool, the old script, or one edited by hand.

    What it reports, worst first:

    \b
      regression  a cell held a pass and no longer does
      unbacked    a cell changed that the record does not account for
      stray       a cell changed outside any skill's column
      shape       a row, a row's width, or the header row moved
      mismapped   a column mapped to a slug its header never names
      missed      the record says passed and the file does not

    The first four mean the file is not what it should be, and the
    command exits non-zero. `missed` is the inverse check and the one
    that matters most on a quiet run: a file that was never written to
    at all passes every other test here.
    """
    if not course:
        raise click.ClickException("say which course, with -c/--course.")
    slugs = _bank_slugs(course)
    try:
        profile = gradebook_mod.load(gradebook_mod.path_for(course))
    except gradebook_mod.GradebookError as exc:
        raise click.ClickException(str(exc))

    roster_path = course_mod.file_in(course, "roster")
    if not os.path.isfile(roster_path):
        raise click.ClickException(f"no roster at {roster_path}.")
    try:
        people = roster_mod.load(roster_path)
    except roster_mod.RosterError as exc:
        raise click.ClickException(f"{roster_path}: {exc}")

    old_rows = mask_mod.read_rows(before)
    new_rows = mask_mod.read_rows(after)
    if not old_rows:
        raise click.ClickException(f"{before} is empty.")
    try:
        index = mask_mod.find_header(old_rows, header_row)
        profile.validate(old_rows[index])
    except (mask_mod.MaskError, gradebook_mod.GradebookError) as exc:
        raise click.ClickException(f"{before}: {exc}")

    progress = record_mod.progress(course_mod.file_in(course, "record"))
    if not progress:
        raise click.ClickException(
            "nothing has been graded in this course, so there is nothing "
            "to check this file against.")
    wanted = {s.strip() for s in not_yet.split(",") if s.strip()}

    report = gradebook_mod.audit_export(
        old_rows[index:], new_rows[index:], os.path.basename(after), profile,
        people, progress, slugs, not_yet=wanted,
        thresholds=course_mod.thresholds(course))

    # And the bytes, which the rows cannot speak for: a cell whose
    # value is unchanged and whose quoting is not reads as identical
    # through a CSV parser and is a different file to the LMS.
    with open(before, "rb") as handle:
        old_bytes = handle.read()
    with open(after, "rb") as handle:
        new_bytes = handle.read()
    moved, same = gradebook_mod.changed_lines(old_bytes, new_bytes)
    report.lines_identical = same

    click.echo(before)
    click.echo(after)
    click.echo("")
    click.echo(report.describe())
    click.echo("")
    if report.columns_dropped:
        # Every line legitimately differs once whole columns have gone,
        # so "21 of 21 lines differ" would be alarming and would mean
        # nothing. The byte comparison catches a cell silently
        # requoted, and a file narrowed for import is not the file to
        # ask that of.
        click.echo("Not comparing bytes: whole columns were removed for "
                   "import, so every line differs by design. The cell by "
                   "cell check above is the one that counts here.")
    else:
        click.echo(f"{same} line(s) came through byte for byte; "
                   f"{len(moved)} differ")
        if moved:
            click.echo("  lines: " + ", ".join(str(n) for n in moved[:20])
                       + (" ..." if len(moved) > 20 else ""))

    stops = [f for f in report.findings
             if f.kind in ("regression", "unbacked", "stray", "shape")]
    click.echo("")
    if stops:
        raise click.ClickException(
            f"{len(stops)} problem(s) mean this file should not be "
            "uploaded as it stands.")
    if report.findings:
        click.echo("Nothing here says the file is wrong, but read the "
                   "findings above before uploading.")
    else:
        click.echo("Every cell in this file agrees with the record.")


@gradebook.command(name="show")
@click.option("-c", "--course", default="", help="Which course.")
def gradebook_show(course):
    """Print this course's gradebook profile.

    Nothing in it is student data -- column names, two mark strings and
    a row marker -- so it is safe to read out and to share.
    """
    if not course:
        raise click.ClickException("say which course, with -c/--course.")
    path = gradebook_mod.path_for(course)
    try:
        profile = gradebook_mod.load(path)
    except gradebook_mod.GradebookError as exc:
        raise click.ClickException(str(exc))
    click.echo(path)
    click.echo("")
    click.echo(f"  name            {profile.name}")
    click.echo(f"  student column  {profile.student_column!r}")
    click.echo(f"  joined on       the roster's {profile.student_matches}")
    click.echo(f"  a pass is       {profile.passed!r}")
    click.echo(f"  a non-pass is   {profile.not_passed!r}")
    click.echo(f"  a blank means   {profile.blank_means}")
    if profile.pairs:
        click.echo("")
        click.echo("  paired by hand:")
        for slug in sorted(profile.pairs):
            click.echo(f"    {slug:<8} {profile.pairs[slug]!r}")
    if profile.ignore_rows:
        click.echo("")
        click.echo("  never write to a row whose id contains: "
                   + ", ".join(repr(r) for r in profile.ignore_rows))
    click.echo("")
    click.echo(f"  {len(profile.ignore_columns)} column(s) are never "
               "written to")



if __name__ == "__main__":
    sys.exit(main())
