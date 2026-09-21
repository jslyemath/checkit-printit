"""Talking to the Google Form, through a script the instructor owns.

There is no Google Cloud project here and no OAuth. The institutional account
that runs this cannot create one, and the Apps Script bound to the form can do
the whole job: it executes as the form's owner by construction, so there is no
identity to prove and no token to refresh.

What that costs is a shared secret. A web app a command line can reach has to
be deployed for "anyone", because a terminal cannot complete a Google sign-in,
so the URL is a capability and every request carries a secret the script
checks. Both live in the workspace's `secrets/` directory, never in `form.toml`
and never in a repository.

**printit renders every string.** The script formats nothing: the number
words, the three limiter modes and the phrasing all live in `availability.py`,
and one copy of them is enough. What crosses the wire is finished text plus
the item ids to put it in.
"""

import dataclasses
import json
import os
import secrets
import tomllib
import urllib.error
import urllib.request

#: The four things printit owns on the form. Everything else -- the banner,
#: the title, the grade cutoffs, the syllabus links -- belongs to whoever made
#: the form, and a push must not touch it.
SLOTS = {
    "selecting_for": "the 'What am I selecting skills for?' text",
    "confirm_date": "the date confirmation checkbox",
    "due_notice": "the 'When is this form due?' text",
    "choose_skills": "the skill selection question",
}

FILENAME = "form.toml"
SECRET_FILENAME = "form-secret.toml"


class FormError(Exception):
    pass


@dataclasses.dataclass
class Connection:
    url: str = ""
    secret: str = ""
    form_id: str = ""
    items: dict = dataclasses.field(default_factory=dict)

    @property
    def ready(self):
        return bool(self.url and self.secret)

    def missing_slots(self):
        return [k for k in SLOTS if k not in self.items]


# ------------------------------------------------------------------ files --

def new_secret():
    """Long enough that guessing is not a strategy."""
    return secrets.token_urlsafe(32)


def load(workspace_path):
    """Read the form config and its secret, which live apart on purpose."""
    conn = Connection()
    config = os.path.join(workspace_path, FILENAME)
    if os.path.isfile(config):
        with open(config, "rb") as f:
            raw = tomllib.load(f)
        block = raw.get("form", {})
        conn.form_id = str(block.get("id", "")).strip()
        conn.items = {k: str(v).strip()
                      for k, v in (raw.get("items") or {}).items()
                      if str(v).strip()}

    # The URL is as sensitive as the secret: anyone holding it can rewrite the
    # form. Both sit in secrets/, which is why neither is in form.toml.
    secret_file = os.path.join(workspace_path, "secrets", SECRET_FILENAME)
    if os.path.isfile(secret_file):
        with open(secret_file, "rb") as f:
            raw = tomllib.load(f)
        conn.url = str(raw.get("url", "")).strip()
        conn.secret = str(raw.get("secret", "")).strip()
    return conn


def _quote(value):
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def save(workspace_path, conn):
    config = os.path.join(workspace_path, FILENAME)
    lines = [
        "# Which form, and which item in it holds each thing printit writes.",
        "#",
        "# Ids, not positions: responses are stored against a question's id,",
        "# so the skill question has to keep its own while its options change",
        "# every week. Re-run `checkit-printit form adopt` if the form is",
        "# rebuilt.",
        "#",
        "# The web app URL and its secret are NOT here -- they are credentials",
        "# and live in secrets/.",
        "",
        "[form]",
        f"id = {_quote(conn.form_id)}",
        "",
        "[items]",
    ]
    for slot in SLOTS:
        if slot in conn.items:
            lines.append(f"{slot} = {_quote(conn.items[slot])}"
                         f"  # {SLOTS[slot]}")
    with open(config, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")

    secrets_dir = os.path.join(workspace_path, "secrets")
    os.makedirs(secrets_dir, exist_ok=True)
    path = os.path.join(secrets_dir, SECRET_FILENAME)
    with open(path, "w", encoding="utf-8") as f:
        f.write("# Treat both of these as passwords. Anyone holding the URL\n"
                "# and the secret can rewrite the form.\n"
                f"url    = {_quote(conn.url)}\n"
                f"secret = {_quote(conn.secret)}\n")
    try:
        os.chmod(path, 0o600)
    except OSError:                                      # pragma: no cover
        pass
    return config, path


# ----------------------------------------------------------------- talking --

def call(conn, op, payload=None, timeout=30, opener=None):
    """One request to the web app. Raises FormError with what went wrong.

    Apps Script answers a web app request with a 302 to a googleusercontent
    URL, which urllib follows on its own; the body of that second response is
    the JSON.
    """
    if not conn.ready:
        raise FormError(
            "no web app is connected. Deploy the script and run "
            "`checkit-printit form connect --url ...`.")
    body = json.dumps({"op": op, "secret": conn.secret,
                       "payload": payload or {}}).encode()
    request = urllib.request.Request(
        conn.url, data=body,
        headers={"Content-Type": "application/json"})
    try:
        open_it = opener or urllib.request.urlopen
        with open_it(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        raise FormError(
            f"the web app answered {exc.code}. A 401 or 403 usually means the "
            f"deployment is not set to 'Anyone'; a 404 means the URL is wrong "
            f"or the deployment was replaced.") from None
    except urllib.error.URLError as exc:
        raise FormError(f"could not reach the web app: {exc.reason}") from None

    try:
        answer = json.loads(text)
    except ValueError:
        raise FormError(
            "the web app did not answer with JSON. That usually means the "
            "deployment is asking for a Google sign-in, which a command line "
            "cannot do -- redeploy with access set to 'Anyone'."
        ) from None
    if not answer.get("ok"):
        raise FormError(answer.get("error", "the script reported a failure"))
    return answer


# ----------------------------------------------------------------- payload --

def describe_skill(slug, description):
    """One checkbox option, as students read it: `W1 - I can convert ...`"""
    text = (description or "").strip()
    return f"{slug} - {text}" if text else slug


NOTHING_OPEN = "(No skills are available yet. Check back later!)"


def payload_for(availability, conn, descriptions):
    """Everything the script needs, already worded.

    With nothing open the form is given a single explanatory option and a
    validation it cannot satisfy, so a student who opens it early cannot
    submit an empty choice that later reads as a real one.
    """
    nothing_open = not availability.skills
    if nothing_open:
        choices = [NOTHING_OPEN]
        validation = {"mode": "none", "count": 0, "help": ""}
    else:
        choices = [describe_skill(s, descriptions.get(s, ""))
                   for s in availability.skills]
        count = availability.choose
        if not count:
            validation = {"mode": "any", "count": 0,
                          "help": "You may choose any amount of skills."}
        else:
            from .availability import number_word
            validation = {
                "mode": availability.limit,
                "count": count,
                "help": f"Please choose {availability.limit} "
                        f"{number_word(count)} skill(s).",
            }

    day = availability.weekday()
    return {
        "items": dict(conn.items),
        "selecting_for": availability.selecting_for(),
        "confirm_date": availability.confirmation(),
        "due_notice": availability.due_notice(),
        "question_title": availability.question_title(),
        "question_help": f"You are choosing which skills you'll be redoing "
                         f"on {day}." if day else "",
        "choices": choices,
        "validation": validation,
    }
