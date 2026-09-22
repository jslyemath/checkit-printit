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


@main.group()
def form():
    """The Google Form students choose their skills on."""


def _space_path(space):
    if not course_mod.exists(space):
        raise click.ClickException(f"no course named {space!r}.")
    return course_mod.path_for(space)


def _clasp_dir(space):
    """Where the local copy of the Apps Script project lives.

    Under secrets/, because printit writes the shared secret into the script
    source before pushing it -- clasp cannot set a Script Property, and the
    point of this path is that nothing is done by hand.
    """
    return os.path.join(course_mod.path_for(space), "secrets", "script")


def _script_sources():
    here = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    return os.path.join(here, "appsscript")


def _stage_script(space, secret):
    """Copy the script into the course and write the secret beside it."""
    import shutil
    target = _clasp_dir(space)
    os.makedirs(target, exist_ok=True)
    for name in ("Code.gs", "appsscript.json"):
        shutil.copy(os.path.join(_script_sources(), name),
                    os.path.join(target, name))
    with open(os.path.join(target, "Secret.gs"), "w", encoding="utf-8") as f:
        f.write(form_mod.secret_source(secret))
    return target


def _ensure_login():
    try:
        if clasp_mod.logged_in():
            return
    except clasp_mod.ClaspError as exc:
        raise click.ClickException(str(exc))
    click.echo("signing in to Google -- a browser window will open.")
    click.echo("  (this uses clasp's own sign-in; printit never sees your "
               "password)")
    try:
        clasp_mod.login()
    except clasp_mod.ClaspError as exc:
        raise click.ClickException(str(exc))


def _authorize_prompt(conn):
    """What to say when Google has not authorized the script yet."""
    return (
        "Google has not authorized this script yet, so it refuses every "
        "call.\n\n"
        "Open this once, signed in as the form's owner, and grant the "
        "permissions:\n\n"
        f"    {conn.url}\n\n"
        "It will say 'Unverified'. That only means Google has not reviewed "
        "it;\n"
        "it is your script, in your own Drive. When it works you will see\n"
        "'Script function not found: doGet' -- this script answers POST and "
        "a\nbrowser sends GET, so that page is the success."
    )


def _ping_authorized(conn):
    """Ping, walking the user through authorization if Google refuses.

    The editor's deploy flow prompts for this; clasp's does not. Without it
    the first call after `form create` answers 403 and looks exactly like a
    domain policy blocking anonymous web apps -- which cost an hour on
    2026-09-21.
    """
    try:
        return form_mod.call(conn, "ping")
    except form_mod.FormError as first:
        if not sys.stdin.isatty():
            raise click.ClickException(
                f"{first}\n\n{_authorize_prompt(conn)}\n\n"
                "Then run this command again."
            ) from None
        click.echo("")
        click.echo(_authorize_prompt(conn))
        click.echo("")
        click.confirm("authorized?", default=True, abort=True)
        try:
            return form_mod.call(conn, "ping")
        except form_mod.FormError as second:
            raise click.ClickException(
                f"still refused after authorizing: {second}") from None


def _report_identity(conn, answer):
    """Record which form we reached, and say where it is.

    `ping` is the only thing that knows: the script id cannot be turned into
    a form URL. This lived inline in two places, and patching one of them
    left `form attach` unchanged while appearing to fix it.
    """
    conn.form_id = answer.get("formId", "") or conn.form_id
    click.echo(f"  connected to {answer.get('form', '')!r}")
    if answer.get("editUrl"):
        click.echo(f"  {answer['editUrl']}")


def _deploy_and_record(space, directory, conn, rename_to=""):
    click.echo("pushing the script...")
    clasp_mod.push(directory)
    click.echo("deploying it as a web app...")
    deployment = clasp_mod.deploy(directory)
    conn.url = clasp_mod.web_app_url(deployment)
    click.echo(f"  {conn.url}")

    click.echo("checking it answers...")
    answer = _ping_authorized(conn)

    if rename_to:
        # clasp's --title named the script project; the form itself is still
        # untitled. Only at creation -- a push must never touch the title.
        answer = form_mod.call(conn, "rename", {"title": rename_to})
    _report_identity(conn, answer)

    click.echo("creating the items printit writes to...")
    made = form_mod.call(conn, "addItems",
                         {"items": dict(conn.items)})["items"]
    conn.items = made

    if rename_to:
        # A form printit just made. Never for attach: an existing form's
        # settings belong to the instructor, like its banner and its title.
        click.echo("setting the form up...")
        done = form_mod.call(conn, "configure", {
            "requireLogin": True,
            "removeDefaultQuestion": True,
            "keep": dict(made),
        })
        for line in done.get("did", []):
            click.echo(f"  {line}")
        for line in done.get("skipped", []):
            click.echo(f"  ! {line}")
    form_mod.save(course_mod.path_for(space), conn)
    for slot, item_id in made.items():
        click.echo(f"  {slot:14} {item_id}")


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
    path = _space_path(space)
    conn = form_mod.load(path)
    if conn.url:
        raise click.ClickException(
            "this course is already connected to a form. Use "
            "`checkit-printit form push`, or clear secrets/form-secret.toml "
            "to start over.")
    _ensure_login()

    if not conn.secret:
        conn.secret = form_mod.new_secret()
    directory = _stage_script(space, conn.secret)

    click.echo(f"creating the form {title!r}...")
    try:
        conn.script_id = clasp_mod.create_form(title, directory, folder)
        click.echo(f"  script {conn.script_id}")
        _deploy_and_record(space, directory, conn,
                           rename_to=title)
    except (clasp_mod.ClaspError, form_mod.FormError) as exc:
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
    path = _space_path(space)
    conn = form_mod.load(path)
    _ensure_login()

    if not conn.secret:
        conn.secret = form_mod.new_secret()
    # Before the clone, so the directory exists for clasp to fetch into;
    # again afterwards, because the clone brings the remote's files down on
    # top of ours.
    directory = _stage_script(space, conn.secret)

    click.echo("fetching the existing script...")
    try:
        clasp_mod.clone(script_id, directory)
        _stage_script(space, conn.secret)      # our files, over the fetched ones
        conn.script_id = script_id
        click.echo("pushing the script...")
        clasp_mod.push(directory)
        click.echo("deploying it as a web app...")
        deployment = clasp_mod.deploy(directory)
        conn.url = clasp_mod.web_app_url(deployment)
    except (clasp_mod.ClaspError, form_mod.FormError) as exc:
        raise click.ClickException(str(exc))
    answer = _ping_authorized(conn)

    _report_identity(conn, answer)
    form_mod.save(path, conn)
    click.echo("")
    click.echo("nothing on the form was changed. Next:")
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
    path = _space_path(space)
    conn = form_mod.load(path)
    try:
        av = availability_mod.load(course_mod.file_in(space, "availability"))
    except availability_mod.AvailabilityError as exc:
        raise click.ClickException(str(exc))

    roster_path = course_mod.file_in(space, "roster")
    if not os.path.isfile(roster_path):
        raise click.ClickException(
            f"{roster_path} does not exist, so there is nobody to match "
            f"responses to. Import a class list first.")
    try:
        people = roster_mod.load(roster_path)
    except (OSError, roster_mod.RosterError) as exc:
        raise click.ClickException(str(exc))

    try:
        answer = form_mod.call(conn, "responses")
    except form_mod.FormError as exc:
        raise click.ClickException(str(exc))
    raw = answer.get("responses") or []
    click.echo(f"the form holds {len(raw)} response(s)")

    bank = _bank_for(space)
    known = tuple(bank.slugs()) if bank is not None else tuple(av.skills)
    if bank is None:
        click.echo("(no bank configured, so only the open skills are "
                   "recognised)")

    try:
        pulled = responses_mod.collect(raw, people, conn.items, av.date, known)
    except responses_mod.ResponseError as exc:
        raise click.ClickException(str(exc))

    click.echo(f"for {av.name or 'this assessment'} on "
               f"{availability_mod.spoken_date(av.date) or av.date}:")
    click.echo(f"  {pulled.answered} student(s) answered")
    for key, (student, picked) in sorted(
            pulled.by_student.items(), key=lambda kv: kv[1][0].name.lower()):
        click.echo(f"    {student.name:28} {', '.join(picked) or '(nothing)'}")

    if pulled.silent:
        click.echo(f"  {len(pulled.silent)} did not answer; they will get "
                   f"[selection] default_when_missing")

    # Everything below is a reason a student might not get the paper they
    # asked for, so none of it is allowed to be quiet.
    trouble = False
    if pulled.unknown_emails:
        trouble = True
        click.echo(f"  ! {len(pulled.unknown_emails)} response(s) from an "
                   f"address nobody on the roster has:")
        for address in pulled.unknown_emails:
            click.echo(f"      {address}")
        click.echo("    add the address to that student with "
                   "`roster import`, or check for a typo.")
    if pulled.unrecognised:
        trouble = True
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
    if trouble and not force:
        raise click.ClickException(
            "some responses could not be placed, so the roster was not "
            "written. Fix them, or pass --force to write the rest.")

    updated = []
    for student in people:
        key = student.sid or student.alt_id or student.email or student.name
        if key in pulled.chosen:
            updated.append(dataclasses.replace(
                student, skills=list(pulled.chosen[key])))
        else:
            updated.append(student)
    with open(roster_path, "w", encoding="utf-8") as f:
        f.write(roster_mod.to_toml(roster_mod.Roster(updated)))
    click.echo(f"\nwrote {roster_path}")
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
def form_push(space, dry_run):
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
    path = _availability_path(space)
    try:
        av = availability_mod.load(path)
    except availability_mod.AvailabilityError as exc:
        raise click.ClickException(str(exc))

    bank = _bank_for(space)
    if bank is not None:
        known = set(bank.slugs())
        unknown = [s for s in slugs if s not in known]
        if unknown:
            raise click.ClickException(
                f"not in the bank: {', '.join(unknown)}. It has "
                f"{', '.join(sorted(known))}.")

    wanted = list(av.skills) if add else []
    for slug in slugs:
        if slug not in wanted:
            wanted.append(slug)

    text = open(path, encoding="utf-8").read()
    with open(path, "w", encoding="utf-8") as f:
        f.write(availability_mod.set_values(text, {"skills": wanted}))
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
    path = _availability_path(space)
    values = {}
    try:
        if name is not None:
            values["name"] = name
        if date is not None:
            values["date"] = availability_mod.as_date(date)
        if due is not None:
            values["due"] = availability_mod.as_datetime(due)
        if choose is not None:
            values["choose"] = choose
        if limit is not None:
            values["limit"] = limit
    except availability_mod.AvailabilityError as exc:
        raise click.ClickException(str(exc))
    if not values:
        raise click.ClickException("nothing to set.")

    text = open(path, encoding="utf-8").read()
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(availability_mod.set_values(text, values))
    except availability_mod.AvailabilityError as exc:
        raise click.ClickException(str(exc))
    av = availability_mod.load(path)
    click.echo(availability_mod.describe(av))


def _bank_for(space):
    """The course's bank, or None when it names none or cannot be read."""
    import tomllib
    config = os.path.join(course_mod.path_for(space), course_mod.CONFIG)
    if not os.path.isfile(config):
        return None
    with open(config, "rb") as f:
        declared = str(tomllib.load(f).get("bank", {}).get("path", "")).strip()
    if not declared:
        return None
    try:
        return Bank(os.path.normpath(
            os.path.join(course_mod.path_for(space), declared)))
    except BankError:
        return None


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
        f.write(roster_mod.to_toml(merged))
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
        for name in report.dropped:
            text, count = seating.blank_seat(text, name)
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
    _set_dropped(who, roster_path, seating_path, dropped=True)


@roster.command(name="restore")
@click.argument("who")
@click.option("-r", "--roster", "roster_path", default="roster.toml",
              type=click.Path(exists=True))
def roster_restore(who, roster_path):
    """Undo a drop. Does not put the student back in the seating chart --
    they need a seat choosing, which is the chart's business, not this one."""
    _set_dropped(who, roster_path, None, dropped=False)


def _set_dropped(who, roster_path, seating_path, dropped):
    try:
        people = roster_mod.load(roster_path)
        student = roster_mod.find(people, who)
    except roster_mod.RosterError as exc:
        raise click.ClickException(str(exc))

    if student.dropped == dropped:
        state = "already dropped" if dropped else "not dropped"
        click.echo(f"{student.name} is {state}; nothing to do.")
        return

    student.dropped = dropped
    student.dropped_by = "instructor" if dropped else ""
    with open(roster_path, "w", encoding="utf-8") as f:
        f.write(roster_mod.to_toml(people))
    click.echo(f"{'dropped' if dropped else 'restored'} {student.name}"
               f"  ({roster_path})")

    if dropped and seating_path and os.path.isfile(seating_path):
        text = open(seating_path, encoding="utf-8").read()
        new, count = seating.blank_seat(text, student.name)
        if count:
            with open(seating_path, "w", encoding="utf-8") as f:
                f.write(new)
            click.echo(f"emptied {count} seat(s) in {seating_path}")
        else:
            click.echo(f"no seat found in {seating_path}; nothing to empty")
    elif not dropped:
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
    run_seed = _choose_run_seed(record, seed)
    rng = random.Random(run_seed)

    if preview:
        do_compile = False

    try:
        report = assemble(publication, roster, chart, out, theme_source,
                          rng=rng, dry_run=preview, run_seed=run_seed)
    except (AssemblyError, BankError) as exc:
        raise click.ClickException(str(exc))

    _report(report, out, theme_origin, publication, run_seed,
            replayed=record is not None)

    if preview:
        click.echo("\npreview only -- nothing was written.")
        return

    # Recorded when the folder is written, not when it compiles: the papers
    # exist either way, and --no-compile is a normal way to finish. A preview
    # writes nothing and records nothing, which is the honest line.
    _record_run(publication, report, out, run_seed)

    if not do_compile:
        click.echo(f"\nnot compiled. To build it yourself:\n  cd {out} && pdflatex main.tex")
        return

    try:
        pdf = compile_pdf(out)
    except CompileError as exc:
        raise click.ClickException(str(exc))
    click.echo(f"\nPDF: {pdf}")


def _record_run(publication, report, out, run_seed):
    """Note what was printed, when the job belongs to a course.

    A side effect of building, never an input to it: nothing here is read back
    when choosing what to print. A job with no course records nothing and
    says nothing, because there is nowhere to put it.
    """
    if not publication.course_folder:
        return
    import datetime
    path = course_mod.file_in(publication.course_folder, "record")
    try:
        rows, unnamed = record_mod.write_run(
            path,
            run_id=os.path.basename(os.path.normpath(out)),
            title=publication.title,
            date=str(publication.date),
            built=datetime.datetime.now().isoformat(timespec="seconds"),
            seed=run_seed,
            output=os.path.abspath(out),
            handouts=report.get("handouts", []),
            extras=report.get("extras", 0),
        )
    except Exception as exc:                     # never lose a built PDF to it
        click.echo(f"\ncould not write the print record: {exc}")
        return
    click.echo(f"\nrecorded {rows} paper(s) in {path}")
    if unnamed:
        click.echo(f"  {unnamed} handout(s) had no student id and were counted "
                   f"but not attributed")


def _choose_run_seed(record, seed):
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


def _report(report, out, theme_origin, publication, run_seed, replayed=False):
    click.echo(f"bank    {publication.bank_path}")
    click.echo(f"theme   {theme_origin}")
    click.echo(f"out     {out}")
    if replayed:
        # Not "repeat this draw with --seed": nothing was drawn, and the
        # versions came from the manifest rather than from this number.
        click.echo(f"seed    {run_seed}   (carried from the run being "
                   f"replayed; it drew nothing here)")
    else:
        click.echo(f"seed    {run_seed}   (repeat this draw with "
                   f"--seed {run_seed})")
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
