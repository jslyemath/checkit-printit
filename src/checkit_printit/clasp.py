"""Driving Google's Apps Script CLI, so setting a form up is one command.

`clasp login` opens a browser and signs you in against **clasp's own** OAuth
client. That matters: the browser login was always possible -- what was missing
was a client to log in *with*, and creating one needs a Google Cloud project
this account cannot make. clasp brings its own, so the login works.

Nothing has to be installed. clasp is a Node program, so a Python virtual
environment cannot hold it, but `npx` fetches and runs it on demand. A global
install is used when present because it starts faster; otherwise npx, which
for a once-a-semester operation costs a few seconds and no setup.
"""

import json
import os
import shutil
import subprocess

PACKAGE = "@google/clasp@latest"

#: The file clasp overwrites on create-script. Ours declares the
#: webapp block; clasp's default does not.
MANIFEST = "appsscript.json"


class ClaspError(Exception):
    pass


def command():
    """How to invoke clasp here: installed if it is, npx if it is not."""
    found = shutil.which("clasp")
    if found:
        return [found]
    npx = shutil.which("npx")
    if not npx:
        raise ClaspError(
            "this needs Node, which does not appear to be installed. "
            "Install it from nodejs.org, or set the form up by hand -- "
            "`checkit-printit form setup` prints the steps."
        )
    return [npx, "--yes", PACKAGE]


#: clasp says these and still exits 0, so the exit code cannot be the
#: only check. `create-script --type bogus` prints the first and returns
#: success, and the real failure then surfaces as a missing .clasp.json.
REFUSALS = (
    "invalid script type",
    "unknown command",
    "unknown option",
)


def run(args, cwd=None, timeout=300, check=True):
    """One clasp invocation. Returns (exit code, combined output)."""
    try:
        done = subprocess.run(
            command() + list(args), cwd=cwd, timeout=timeout,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired:
        raise ClaspError(
            f"clasp {' '.join(args)} did not finish within {timeout}s. If it "
            f"was waiting for a browser login, run `clasp login` yourself "
            f"first and try again."
        ) from None
    output = (done.stdout or "") + (done.stderr or "")
    if check:
        lowered = output.lower()
        refused = next((r for r in REFUSALS if r in lowered), None)
        if refused:
            raise ClaspError(
                f"clasp {' '.join(args)} was refused ({refused}), though "
                f"it reported exit {done.returncode}:\n{output.strip()}"
            )
        if done.returncode != 0:
            raise ClaspError(
                f"clasp {' '.join(args)} failed:\n{output.strip()}")
    return done.returncode, output


def logged_in():
    """Whether clasp already holds credentials.

    Checked by asking rather than by looking for a file, because clasp keeps
    them in more than one place depending on version and platform.
    """
    code, output = run(["list-scripts"], check=False, timeout=120)
    if code == 0:
        return True
    lowered = output.lower()
    if "login" in lowered or "credential" in lowered or "unauthor" in lowered:
        return False
    raise ClaspError(f"could not tell whether clasp is logged in:\n{output.strip()}")


def login(timeout=300):
    """Open a browser and sign in. This is the login a CLI *can* do.

    clasp starts a local server, opens the browser, and catches the redirect
    -- the standard installed-application flow. It authenticates against
    clasp's OAuth client, so no Cloud project of the user's is involved.
    """
    run(["login"], timeout=timeout)


def create_form(title, directory, parent_id=""):
    """A new Google Form with a script bound to it. Returns the script id.

    `parent_id` is a Drive folder id, so the form lands where the instructor
    wants rather than loose at the top of My Drive.
    """
    os.makedirs(directory, exist_ok=True)

    # clasp writes its OWN appsscript.json into --rootDir, overwriting the one
    # staged there. Its default has no "webapp" block, so the deployment gets
    # no entry point and every request to /exec answers 404 -- with a
    # perfectly well-formed URL and a deployment id that parses. Keep ours and
    # put it back.
    manifest = os.path.join(directory, MANIFEST)
    staged = None
    if os.path.isfile(manifest):
        with open(manifest, encoding="utf-8") as f:
            staged = f.read()

    # "forms", plural. clasp takes standalone, webapp, api, docs, forms,
    # sheets, slides -- and answers the singular with "Invalid script
    # type" *and exit 0*, which is why run() checks the output too.
    args = ["create-script", "--type", "forms", "--title", title,
            "--rootDir", directory]
    if parent_id:
        args += ["--parentId", parent_id]
    run(args, cwd=directory)

    if staged is not None:
        with open(manifest, "w", encoding="utf-8") as f:
            f.write(staged)

    return script_id(directory)


def clone(script_id_value, directory):
    """Attach to a script that already exists, such as one bound to a form
    the instructor built themselves."""
    os.makedirs(directory, exist_ok=True)
    run(["clone-script", script_id_value, "--rootDir", directory],
        cwd=directory)


def script_id(directory):
    path = os.path.join(directory, ".clasp.json")
    if not os.path.isfile(path):
        raise ClaspError(
            f"no .clasp.json in {directory}, so clasp did not leave a project "
            f"behind. Its output above says why."
        )
    with open(path, encoding="utf-8") as f:
        return json.load(f).get("scriptId", "")


def push(directory):
    # `push`, not `push-files`: clasp answers an unknown command by
    # printing its global help, which reads a lot like success.
    run(["push", "--force"], cwd=directory)


def deploy(directory, description="checkit-printit"):
    """Publish a web app version. Returns its deployment id.

    A *new* deployment gets a new URL; updating an existing one keeps it. This
    creates a new one, so the caller has to record the URL it returns.
    """
    _, output = run(["create-deployment", "--description", description],
                    cwd=directory)
    return _deployment_id(output)


def _deployment_id(output):
    """Pull the deployment id out of clasp's chatter.

    Matched by shape -- Apps Script deployment ids are long and start with
    AKfycb -- rather than by position in the sentence, which has changed
    between clasp versions.
    """
    for token in output.replace("\n", " ").split():
        cleaned = token.strip("()[],.'\"")
        if cleaned.startswith("AKfycb") and len(cleaned) > 30:
            return cleaned
    raise ClaspError(
        "clasp deployed but did not print a deployment id that could be "
        f"recognised. Its output was:\n{output.strip()}"
    )


def web_app_url(deployment_id):
    return f"https://script.google.com/macros/s/{deployment_id}/exec"
