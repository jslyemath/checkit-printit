"""Wiring a course up to a Google Form.

Lifted out of `form create` and `form attach`, which between them held five
helpers and twenty-one `click.echo` calls tangled through the rules. The
web app has to do the same thing, and the app's own Responses card was
telling people to go and run a CLI command -- which is the opposite of the
point.

**The one shape that had to change.** `_ping_authorized` stopped and asked
`click.confirm("authorized?")` while the instructor went to a browser and
granted the script its permissions. A request handler cannot block like
that, so refusal is now a `NeedsAuthorization` carrying the URL and the
wording. The CLI prompts and retries exactly as before; the app shows the
link and a button that calls back in.

`attach` also carried its own copy of push/deploy/ping/record, which is why
a fix to `_deploy_and_record` once left it unchanged while appearing to
work. There is one copy here.
"""

import os
import shutil

from . import clasp as clasp_mod
from . import course as course_mod
from . import form as form_mod


class ProvisionError(Exception):
    pass


class NeedsAuthorization(ProvisionError):
    """Google has not authorized the script, so it refuses every call.

    Not a failure of the deploy: the editor's own deploy flow prompts for
    this and clasp's does not, so the first call after a create answers 403
    and looks exactly like a domain policy blocking anonymous web apps --
    which cost an hour on 2026-09-21. It is a step, and it needs the URL.
    """

    def __init__(self, url, cause=""):
        self.url = url
        self.cause = str(cause)
        super().__init__(prompt(url))


#: The two things that make the authorization page look like it failed
#: when it worked. Separate from `prompt` so a browser can show them as
#: prose next to a button, and the terminal can keep its paragraph,
#: without the two drifting into different explanations.
AUTHORIZE_NOTES = (
    "It will say 'Unverified'. That only means Google has not reviewed it; "
    "it is your script, in your own Drive.",
    "When it works you will see 'Script function not found: doGet'. This "
    "script answers POST and a browser sends GET, so that page is the "
    "success.",
)


def prompt(url):
    """What to say when Google has not authorized the script yet."""
    return (
        "Google has not authorized this script yet, so it refuses every "
        "call.\n\n"
        "Open this once, signed in as the form's owner, and grant the "
        "permissions:\n\n"
        f"    {url}\n\n"
        + "\n\n".join(AUTHORIZE_NOTES)
    )


def clasp_dir(space):
    """Where the local copy of the Apps Script project lives.

    Under secrets/, because printit writes the shared secret into the
    script source before pushing it -- clasp cannot set a Script Property,
    and the point of this path is that nothing is done by hand.
    """
    return os.path.join(course_mod.path_for(space), "secrets", "script")


def script_sources():
    here = os.path.dirname(os.path.dirname(os.path.dirname(
        os.path.abspath(__file__))))
    return os.path.join(here, "appsscript")


def stage_script(space, secret):
    """Copy the script into the course and write the secret beside it."""
    target = clasp_dir(space)
    os.makedirs(target, exist_ok=True)
    for name in ("Code.gs", "appsscript.json"):
        shutil.copy(os.path.join(script_sources(), name),
                    os.path.join(target, name))
    with open(os.path.join(target, "Secret.gs"), "w", encoding="utf-8") as f:
        f.write(form_mod.secret_source(secret))
    return target


def signed_in():
    try:
        return clasp_mod.logged_in()
    except clasp_mod.ClaspError as exc:
        raise ProvisionError(str(exc)) from None


def sign_in():
    """clasp's own browser sign-in. printit never sees a password."""
    try:
        clasp_mod.login()
    except clasp_mod.ClaspError as exc:
        raise ProvisionError(str(exc)) from None


def reach(conn):
    """Reach the deployed script, or say it needs authorizing.

    Raising rather than prompting: the two front ends want different things
    from that moment -- the CLI can wait for a keypress, a web page cannot.
    """
    try:
        return form_mod.call(conn, "ping")
    except form_mod.FormError as exc:
        raise NeedsAuthorization(conn.url, exc) from None


def deploy_and_record(space, directory, conn, rename_to="", reach=reach):
    """Push, deploy, save what exists, then finish.

    The save in the middle is not tidiness. Google may not have authorized
    the script yet, and at that point the form and the web app are already
    real -- so a course that recorded nothing would start over, make a
    second form, and leave the first one orphaned in Drive.

    Returns plain lines describing what happened, so the caller reports
    rather than re-deriving.
    """
    clasp_mod.push(directory)
    deployment = clasp_mod.deploy(directory)
    conn.url = clasp_mod.web_app_url(deployment)
    form_mod.save(course_mod.path_for(space), conn)
    return ([f"deployed: {conn.url}"]
            + finish(space, rename_to=rename_to, reach=reach))


def finish(space, rename_to="", reach=reach):
    """Everything after Google authorizes the script.

    Its own function because that is where a create or an attach stops,
    and the instructor goes to a browser. **Every step is safe to repeat**:
    `addItems` creates only what is missing, `rename` sets a title that may
    already be set, and `configure` reports what it skipped. So the way
    back from "not authorized yet" is to call this again, not to start
    over.

    `rename_to` is set only when printit made the form: clasp's --title
    names the *script project* and leaves the form itself untitled. A push
    must never touch an existing form's title.
    """
    conn = _course_conn(space)
    said = []
    answer = reach(conn)

    if rename_to:
        answer = form_mod.call(conn, "rename", {"title": rename_to})
    conn.form_id = answer.get("formId", "") or conn.form_id
    said.append(f"connected to {answer.get('form', '')!r}")
    if answer.get("editUrl"):
        said.append(answer["editUrl"])

    made = form_mod.call(conn, "addItems",
                         {"items": dict(conn.items)})["items"]
    conn.items = made

    if rename_to:
        # A form printit just made. Never for attach: an existing form's
        # settings belong to the instructor, like its banner and its title.
        done = form_mod.call(conn, "configure", {
            "requireLogin": True,
            "removeDefaultQuestion": True,
            "keep": dict(made),
        })
        said += list(done.get("did", []))
        said += [f"! {line}" for line in done.get("skipped", [])]

    form_mod.save(course_mod.path_for(space), conn)
    said += [f"{slot:14} {item_id}" for slot, item_id in made.items()]
    return said


def _course_conn(space):
    if not course_mod.exists(space):
        raise ProvisionError(f"no course named {space!r}.")
    return form_mod.load(course_mod.path_for(space))


def create_form(space, title="Skill Selection Form", folder="",
                reach=reach):
    """Make a new Google Form, wire it up, and record everything.

    One sign-in. Creates the form and its bound script, deploys the web
    app, adds the four items printit writes to, and records their ids --
    so there is nothing to paste and nothing to map afterwards.
    """
    conn = _course_conn(space)
    if conn.url:
        raise ProvisionError(
            "this course is already connected to a form. Push to it, or "
            "clear secrets/form-secret.toml to start over.")
    if not conn.secret:
        conn.secret = form_mod.new_secret()
    directory = stage_script(space, conn.secret)
    try:
        conn.script_id = clasp_mod.create_form(title, directory, folder)
        said = [f"script {conn.script_id}"]
        return said + deploy_and_record(space, directory, conn,
                                        rename_to=title, reach=reach)
    except (clasp_mod.ClaspError, form_mod.FormError) as exc:
        raise ProvisionError(str(exc)) from None


def attach_form(space, script_id, reach=reach):
    """Wire up a form that already exists, changing nothing on it.

    For a form with a banner, grade cutoffs and syllabus links worth
    keeping. No items are created or changed, so the item map has to be
    filled in afterwards.

    **It does change the bound script project.** The clone brings the
    remote's files down and printit's are written over them, so a file the
    existing script keeps under one of printit's names -- `Code.gs`,
    `appsscript.json` -- is replaced by the push. A form still driven by
    another tool is not a form to attach to without looking first.
    """
    conn = _course_conn(space)
    if not conn.secret:
        conn.secret = form_mod.new_secret()
    # Before the clone, so the directory exists for clasp to fetch into;
    # again afterwards, because the clone brings the remote's files down on
    # top of ours.
    directory = stage_script(space, conn.secret)
    try:
        clasp_mod.clone(script_id, directory)
        stage_script(space, conn.secret)       # ours, over the fetched ones
        conn.script_id = script_id
        clasp_mod.push(directory)
        deployment = clasp_mod.deploy(directory)
        conn.url = clasp_mod.web_app_url(deployment)
    except (clasp_mod.ClaspError, form_mod.FormError) as exc:
        raise ProvisionError(str(exc)) from None

    # Saved before the authorization step, for the same reason as a
    # create: the deploy has happened and starting over would leave it.
    form_mod.save(course_mod.path_for(space), conn)
    return ([f"deployed: {conn.url}"]
            + finish(space, reach=reach)
            + ["nothing on the form itself was changed"])


def what_the_clone_would_replace(space, script_id):
    """The existing script's files that attaching would overwrite.

    Asked before attaching rather than discovered after: the files printit
    stages share names with the ones most Apps Script projects already use,
    and a form can be driven by something else that is still in service.
    """
    directory = os.path.join(clasp_dir(space), "_inspect")
    os.makedirs(directory, exist_ok=True)
    try:
        clasp_mod.clone(script_id, directory)
    except clasp_mod.ClaspError as exc:
        raise ProvisionError(str(exc)) from None
    ours = {"Code.gs", "appsscript.json", "Secret.gs"}
    theirs = sorted(n for n in os.listdir(directory)
                    if n.endswith((".gs", ".json", ".html")))
    return {"files": theirs,
            "replaced": sorted(n for n in theirs if n in ours),
            "kept": sorted(n for n in theirs if n not in ours)}
