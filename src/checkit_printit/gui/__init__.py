"""A local web front end for one course.

Stage 8a (the shell) and 8b (the roster table). The rest of the views are
planned in `../checkit/PRINT_TOOL_DESIGN.md` section 12.6.

**Every handler calls the same function the CLI calls.** Nothing here
reimplements a rule -- dropping a student goes through `roster.set_dropped`,
the same call `checkit-printit roster drop` makes. On 2026-09-21 one fix had
to be applied three times in a day because three code paths did the same job;
a GUI that duplicates a rule makes that permanent rather than occasional.

Bound to 127.0.0.1, never 0.0.0.0. This serves names, student ids and email
addresses off a laptop that sits on university wifi.

Also token-guarded. Binding to loopback stops another machine, but not another
*page*: any website open in the same browser can POST to http://127.0.0.1 in
the background. A random token is minted per run, injected into the page, and
required on every API call as a header a cross-origin form cannot set.
"""

import dataclasses
import http.server
import json
import mimetypes
import os
import secrets
import socketserver
import threading
import urllib.parse
import webbrowser

from .. import course as course_mod
from .. import availability as availability_mod
from .. import clasp as clasp_mod
from .. import boilerplate as boilerplate_mod
from .. import classlist as classlist_mod
from .. import printjob as printjob_mod
from .. import runner as runner_mod
from .. import form as form_mod
from ..bank import Bank, BankError
from .. import roster as roster_mod

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
TOKEN_HEADER = "X-Printit-Token"


class GuiError(Exception):
    pass


# ------------------------------------------------------------------- data --

def _sort_names(student):
    """Keys for sorting by surname or by given name. Never stored.

    The roster carries one full name, because that is what prints and what
    the seating chart matches on. `last` and `first` exist but are empty on
    every real roster here: those came from a single "Full Name" column.

    So the two orders are derived, on the way out, and written nowhere. The
    splitter is only reliable on the `Last, First` comma form -- from
    `First Last` it guesses, and it guesses wrong on at least one real
    student, whose compound surname comes back as its last word alone. A
    wrong guess therefore puts a row in an odd position in a sort, which you
    can see, instead of putting a wrong surname in a file, which you cannot.

    `classlist.split_full_name` does the work, so the rule has one
    implementation and the browser has none of it.
    """
    if student.last or student.first:
        return student.last, student.first        # a real import filled these
    last, first, _ = classlist_mod.split_full_name(student.name)
    return last, first


def _student_json(student, index):
    """One row of the roster table.

    `index` is the identity the browser sends back. Not the name -- a rename
    is the whole point of the nickname column -- and not the SID, which some
    class lists do not carry.
    """
    sort_last, sort_first = _sort_names(student)
    return {
        "index": index,
        "name": student.name,
        # Derived for sorting only; see _sort_names. Not editable, not saved.
        "sort_last": sort_last,
        "sort_first": sort_first,
        "last": student.last,
        "first": student.first,
        "preferred": student.preferred,
        "section": student.section,
        "email": student.email,
        "emails": [e for e in student.all_emails() if e != student.email.strip().lower()],
        "sid": student.sid,
        "alt_id": student.alt_id,
        "dropped": bool(student.dropped),
        "dropped_by": student.dropped_by,
        # Not shown in the roster table: what a student chose belongs to
        # one assessment, and the roster is the course. The assessment
        # staging view reads it. See 12.6.
        "skills": list(student.skills),
    }


#: What the table may change. Everything else -- ids, the dropped flag, the
#: accumulated addresses -- is set by an import, a drop or a pull, each of
#: which has rules of its own that a text box would quietly bypass.
EDITABLE = ("name", "preferred", "section", "email")


class Course:
    """One course's files, read fresh each time. No cache to go stale."""

    def __init__(self, name):
        self.name = name
        if not course_mod.exists(name):
            raise GuiError(
                f"no course named {name!r}. Make one with "
                f"`checkit-printit course init {name!r}`.")
        self.path = course_mod.path_for(name)

    def file(self, which):
        return course_mod.file_in(self.name, which)

    def roster(self):
        path = self.file("roster")
        if not os.path.isfile(path):
            return None
        return roster_mod.load(path)

    def summary(self):
        people = self.roster()
        counts = {}
        if people is not None:
            for student in people:
                if not student.dropped:
                    counts[student.section or "(none)"] = counts.get(
                        student.section or "(none)", 0) + 1
        return {
            "name": self.name,
            "path": self.path,
            "students": 0 if people is None else len(people),
            "active": 0 if people is None else
                      sum(1 for s in people if not s.dropped),
            "sections": counts,
            "files": {
                which: os.path.isfile(self.file(which))
                for which in ("roster", "seating", "availability", "form",
                              "record")
            },
        }

    def bank(self):
        """The bank this course prints from, or None.

        None is a normal state, not a failure: a course can exist before it
        is pointed at a bank, and the Skills view then shows the open list
        without descriptions rather than refusing to load.
        """
        import tomllib
        config = os.path.join(self.path, course_mod.CONFIG)
        if not os.path.isfile(config):
            return None
        with open(config, "rb") as f:
            declared = str(tomllib.load(f).get("bank", {}).get("path", "")).strip()
        if not declared:
            return None
        try:
            return Bank(os.path.normpath(os.path.join(self.path, declared)))
        except BankError:
            return None

    def availability(self):
        return availability_mod.load(self.file("availability"))

    def save_roster(self, people):
        with open(self.file("roster"), "w", encoding="utf-8") as f:
            f.write(roster_mod.to_toml(people, "checkit-printit gui"))


# --------------------------------------------------------------- handlers --

def api_course(course, _body):
    return course.summary()


def api_roster(course, _body):
    people = course.roster()
    if people is None:
        raise GuiError(
            f"{course.file('roster')} does not exist yet. Import a class list "
            f"with `checkit-printit roster import`.")
    return {"students": [_student_json(s, i) for i, s in enumerate(people)]}


def api_roster_save(course, body):
    """Apply a batch of edits. All or nothing.

    The browser holds changes until Save, so one request carries them all;
    a half-applied batch would leave the file disagreeing with the table
    still on screen.
    """
    edits = body.get("edits") or []
    people = course.roster()
    if people is None:
        raise GuiError("there is no roster to save.")
    students = list(people)

    # Validate everything, then apply. The guarantee that actually holds the
    # file together is narrower than it looks: nothing is written until every
    # edit has passed, so an early `setattr` would be equally safe and a
    # mutation test cannot tell the two apart. Kept because reading it in two
    # phases is what makes the guarantee obvious to the next person.
    staged = []
    for edit in edits:
        try:
            index = int(edit["index"])
            student = students[index]
        except (KeyError, ValueError, IndexError):
            raise GuiError(
                f"an edit names row {edit.get('index')!r}, which is not on "
                f"the roster. Reload the page -- it has changed underneath "
                f"you.") from None
        field = edit.get("field")
        if field not in EDITABLE:
            raise GuiError(
                f"{field!r} is not editable here. The table may change "
                f"{', '.join(EDITABLE)}; everything else is set by an import, "
                f"a drop or a pull, which have rules a text box would bypass.")
        value = str(edit.get("value", "")).strip()
        if field == "name" and not value:
            raise GuiError(
                "a student needs a name: it is what the seating chart matches "
                "on and what prints on the paper.")
        staged.append((student, field, value))

    if staged:
        for student, field, value in staged:
            setattr(student, field, value)
        course.save_roster(people)
    # An empty batch writes nothing at all. It used to rewrite the whole file
    # anyway, which changed its timestamp and reformatted it for no reason --
    # and made "which action last wrote this roster?" unanswerable, which is
    # the question you ask when a value is not what you expected.
    return {"saved": len(staged), "students":
            [_student_json(s, i) for i, s in enumerate(people)]}


def api_roster_drop(course, body):
    """Drop or restore. Goes through the same call the CLI makes."""
    who = str(body.get("who", "")).strip()
    dropped = bool(body.get("dropped", True))
    if not who:
        raise GuiError("no student was named.")
    seating_path = course.file("seating")
    try:
        done = roster_mod.set_dropped(
            course.file("roster"), who, dropped,
            seating_path if os.path.isfile(seating_path) else None)
    except roster_mod.RosterError as exc:
        raise GuiError(str(exc)) from None

    if not done.changed:
        note = f"{done.student.name} was already " + (
            "dropped" if dropped else "on the roster")
    elif dropped:
        note = f"dropped {done.student.name}"
        if done.seating_checked:
            note += (f", emptied {done.seats_emptied} seat(s)"
                     if done.seats_emptied else ", no seat to empty")
    else:
        note = (f"restored {done.student.name} -- they have no seat until you "
                f"give them one")
    people = course.roster()
    return {"note": note, "changed": done.changed,
            "students": [_student_json(s, i) for i, s in enumerate(people)]}


# --------------------------------------------------------------- google --

class Google:
    """Whether clasp holds a usable session, and starting one that does.

    Google expires a session holding sensitive scopes after a week or two
    whether or not it is used, so "logged in once" is not a durable answer
    and the app has to keep asking.
    """

    #: Asking costs an npx invocation and several seconds, so the answer is
    #: reused briefly. Short enough that signing in shows up promptly.
    TTL = 45

    def __init__(self):
        self.checked_at = 0.0
        self.ok = None
        self.error = ""
        self.signing_in = False
        self.last_attempt = ""

    def status(self, force=False):
        import time
        stale = (time.time() - self.checked_at) > self.TTL
        if force or self.ok is None or stale:
            try:
                self.ok = clasp_mod.logged_in()
                self.error = ""
            except clasp_mod.ClaspError as exc:
                # Not the same as "signed out": something else is wrong, and
                # offering a sign-in button would send the instructor round a
                # loop that cannot fix it.
                self.ok = None
                self.error = str(exc)
            self.checked_at = time.time()
        return {"loggedIn": self.ok, "error": self.error,
                "signingIn": self.signing_in,
                "lastAttempt": self.last_attempt}

    def sign_in(self):
        """Start clasp's browser sign-in. Returns at once.

        clasp opens the browser itself. Waiting for it here would hold the
        request open for as long as someone takes to find their password,
        and the page would look hung.
        """
        if self.signing_in:
            return {"started": False, "note": "already waiting for the browser"}
        self.signing_in = True
        self.last_attempt = ""

        def run():
            try:
                clasp_mod.login()
                self.last_attempt = "done"
            except clasp_mod.ClaspError as exc:
                self.last_attempt = str(exc)
            finally:
                self.signing_in = False
                self.ok = None          # force a fresh check
                self.checked_at = 0.0

        threading.Thread(target=run, daemon=True).start()
        return {"started": True}


GOOGLE = Google()


def api_google(_course, body):
    return GOOGLE.status(force=bool(body.get("force")))


def api_google_login(_course, _body):
    return GOOGLE.sign_in()


def _wording(course, av):
    """Exactly what the form will say, worded by the same code that pushes it.

    `payload_for` is what `form push` sends, so a preview that used anything
    else would be a second implementation of the wording -- and the one
    place a difference would show up is on a form students are already
    looking at.
    """
    bank = course.bank()
    descriptions = {}
    if bank is not None:
        for slug in av.skills:
            try:
                descriptions[slug] = bank.description(slug)
            except BankError:
                descriptions[slug] = ""
    conn = form_mod.load(course.path)
    return form_mod.payload_for(av, conn, descriptions)


def _preview(course, av):
    """The whole form as a student meets it: the boilerplate parts and the
    derived ones, in order."""
    return boilerplate_mod.preview(_wording(course, av))


def api_skills(course, _body):
    """Everything the Skills view draws: the bank, the open list, the
    assessment, and the wording those produce."""
    try:
        av = course.availability()
    except availability_mod.AvailabilityError as exc:
        raise GuiError(str(exc)) from None

    bank = course.bank()
    open_now = list(av.skills)
    if bank is None:
        slugs = open_now
        descriptions = {s: "" for s in slugs}
    else:
        slugs = list(bank.slugs())
        descriptions = {}
        for slug in slugs:
            try:
                descriptions[slug] = bank.description(slug)
            except BankError:
                descriptions[slug] = ""
        # A slug that is open but no longer in the bank still has to appear,
        # or it could not be turned off from here.
        for slug in open_now:
            if slug not in descriptions:
                slugs.append(slug)
                descriptions[slug] = ""

    conn = form_mod.load(course.path)
    return {
        "hasBank": bank is not None,
        "skills": [{"slug": s, "description": descriptions.get(s, ""),
                    "open": s in open_now,
                    "inBank": bank is None or s in set(bank.slugs())}
                   for s in slugs],
        "open": open_now,
        "assessment": {
            "name": av.name, "date": str(av.date or ""),
            "due": str(av.due or ""), "choose": av.choose, "limit": av.limit,
        },
        "limits": list(availability_mod.LIMITS),
        "wording": _wording(course, av),
        "preview": _preview(course, av),
        "form": {"connected": conn.ready,
                 "mapped": sorted(conn.items),
                 "missing": conn.missing() if hasattr(conn, "missing") else []},
    }


def api_skills_preview(course, body):
    """The wording for values that have not been saved.

    Being able to see "Choose At Most TWO Skills" before committing to it is
    most of the point of the view. It builds an Availability in memory and
    hands it to the same `_wording` the push uses -- nothing is written, and
    there is still only one implementation of the wording.
    """
    try:
        saved = course.availability()
    except availability_mod.AvailabilityError as exc:
        raise GuiError(str(exc)) from None

    fields = body.get("assessment") or {}
    try:
        proposed = dataclasses.replace(
            saved,
            name=fields.get("name", saved.name),
            date=(availability_mod.as_date(fields["date"]) if fields.get("date")
                  else (None if "date" in fields else saved.date)),
            due=(availability_mod.as_datetime(fields["due"]) if fields.get("due")
                 else (None if "due" in fields else saved.due)),
            choose=int(fields.get("choose", saved.choose) or 0),
            limit=fields.get("limit", saved.limit),
            skills=tuple(body.get("open", saved.skills)),
        )
    except (availability_mod.AvailabilityError, ValueError, TypeError) as exc:
        raise GuiError(f"that is not a usable value: {exc}") from None
    return {"wording": _wording(course, proposed),
            "preview": _preview(course, proposed)}


def api_skills_save(course, body):
    """Apply the open list and the assessment fields, then report the wording.

    Both go through the functions `skills open` and `skills set` call.
    """
    path = course.file("availability")
    bank = course.bank()
    try:
        if "open" in body:
            availability_mod.set_open(
                path, list(body["open"]), add=False,
                known=set(bank.slugs()) if bank is not None else None)
        fields = body.get("assessment") or {}
        if fields:
            availability_mod.set_assessment(
                path,
                name=fields.get("name"), date=fields.get("date"),
                due=fields.get("due"), choose=fields.get("choose"),
                limit=fields.get("limit"))
    except availability_mod.AvailabilityError as exc:
        raise GuiError(str(exc)) from None
    return api_skills(course, {})


def api_form_push(course, _body):
    """Send it. The same call `form push` makes."""
    conn = form_mod.load(course.path)
    if not conn.ready:
        raise GuiError("this course is not connected to a form yet.")
    if not conn.items:
        raise GuiError("no items are mapped yet -- run "
                       "`checkit-printit form map`.")
    try:
        av = course.availability()
        answer = form_mod.call(conn, "push", _wording(course, av))
    except (availability_mod.AvailabilityError, form_mod.FormError) as exc:
        raise GuiError(str(exc)) from None
    return {"changed": answer.get("changed", [])}


# ------------------------------------------------------------ print job --

def _variants_in(bank, slugs):
    """{slug: [case, ...]} for the skills that declare any.

    There is no declaration to read: the generator wrapper writes the label
    into each version's data, so the only way to know is to look. Walking
    the whole print tier for 29 outcomes is slow, so a slice is enough to
    find every case -- a variant that appears in none of sixty versions is
    not one an instructor can be offered anyway.
    """
    out = {}
    for slug in slugs:
        seen = []
        for seed in range(400, 460):
            try:
                case = bank.variant(slug, seed)
            except Exception:
                break
            if case and case not in seen:
                seen.append(case)
        if seen:
            out[slug] = sorted(seen)
    return out


def _course_identity(course):
    import tomllib
    config = os.path.join(course.path, course_mod.CONFIG)
    if not os.path.isfile(config):
        return {}
    with open(config, "rb") as f:
        return tomllib.load(f)


def api_print(course, _body):
    """Everything the staging view draws."""
    draft = printjob_mod.load_draft(course.name)
    people = course.roster()
    bank = course.bank()

    slugs = list(bank.slugs()) if bank is not None else []
    descriptions = {}
    if bank is not None:
        for slug in slugs:
            try:
                descriptions[slug] = bank.description(slug)
            except BankError:
                descriptions[slug] = ""

    students = []
    if people is not None:
        for i, s in enumerate(people):
            if s.dropped:
                continue
            key = s.sid or s.alt_id or s.email or s.name
            students.append({
                "index": i, "key": key, "name": s.name,
                "section": s.section,
                "chose": list(s.skills),
                "override": list(draft["overrides"].get(key, []))
                            if key in draft["overrides"] else None,
            })

    identity = _course_identity(course)
    return {
        "draft": draft,
        "students": students,
        "skills": [{"slug": s, "description": descriptions.get(s, "")}
                   for s in slugs],
        "variants": _variants_in(bank, slugs) if bank is not None else {},
        "hasBank": bank is not None,
        "hasRoster": people is not None,
        "course": {"name": identity.get("code") or identity.get("name", ""),
                   "semester": identity.get("semester", ""),
                   "professor": identity.get("professor", "")},
        "jobFolder": printjob_mod.folder_for(draft),
    }


def api_print_save(course, body):
    printjob_mod.save_draft(course.name, body.get("draft") or {})
    return api_print(course, {})


def _build(course, preview, seed=None):
    draft = printjob_mod.load_draft(course.name)
    identity = _course_identity(course)
    try:
        folder = printjob_mod.write_job(
            course.name, draft,
            course_name=identity.get("code") or identity.get("name", ""),
            semester=identity.get("semester", ""),
            professor=identity.get("professor", ""))
    except printjob_mod.PrintJobError as exc:
        raise GuiError(str(exc)) from None

    try:
        result = runner_mod.run(
            os.path.join(folder, "publication.toml"),
            do_compile=not preview, seed=seed, preview=preview)
    except runner_mod.BuildError as exc:
        raise GuiError(str(exc)) from None

    report = result.report
    return {
        "folder": folder,
        "out": result.out,
        "seed": result.run_seed,
        "preview": preview,
        "students": report["students"],
        "extras": report["extras"],
        "skills": list(report["skills"]),
        "versions": report["versions"],
        "keys": report["keys"],
        # (version, skill) -> seed. Different skills have unrelated pools, so
        # "version A" is one seed per skill rather than one seed.
        "seeds": [{"version": v, "slug": s, "seed": n}
                  for (v, s), n in sorted(report["seeds"].items(),
                                          key=lambda kv: (kv[0][1], kv[0][0]))
                  if s in report["skills"]],
        "collisions": [f"{a.name} and {b.name} share version {a.version} "
                       f"at table {a.group}"
                       for a, b in report["collisions"]],
        "unseated": list(report["unseated"]),
        "missingFields": {k: list(v) for k, v in report["missing_fields"].items()},
        "pdf": result.pdf,
        "recorded": result.recorded,
        "recordError": result.record_error,
        "themeInstalled": result.theme_installed,
    }


def api_print_preview(course, body):
    """Draw and report, writing nothing.

    The seed it reports is **not** a prediction: a build draws again unless
    given the same one. The view carries it across, which is the whole
    reason every run has a seed.
    """
    return _build(course, preview=True, seed=body.get("seed"))


def api_print_build(course, body):
    return _build(course, preview=False, seed=body.get("seed"))


def api_print_reveal(_course, body):
    """Show a finished run in the file manager.

    Opening the PDF itself would hand the instructor one file; the folder
    holds the manifest and the per-skill .tex too, which is what you want
    when something looks wrong.
    """
    import subprocess
    path = str(body.get("path", ""))
    root = runner_mod.default_output_root()
    if not path or not os.path.abspath(path).startswith(os.path.abspath(root)):
        # Only ever somewhere printit wrote. This opens a window on the
        # instructor's machine, so it does not take an arbitrary path.
        raise GuiError("that is not a printit output folder.")
    if not os.path.exists(path):
        raise GuiError(f"{path} is not there any more.")
    try:
        if sys.platform == "win32":
            os.startfile(path)                      # noqa: S606
        elif sys.platform == "darwin":
            subprocess.run(["open", path], check=False)
        else:
            subprocess.run(["xdg-open", path], check=False)
    except OSError as exc:
        raise GuiError(f"could not open it: {exc}") from None
    return {"opened": path}


ROUTES = {
    "/api/course": api_course,
    "/api/roster": api_roster,
    "/api/roster/save": api_roster_save,
    "/api/roster/drop": api_roster_drop,
    "/api/google": api_google,
    "/api/google/login": api_google_login,
    "/api/print": api_print,
    "/api/print/save": api_print_save,
    "/api/print/preview": api_print_preview,
    "/api/print/build": api_print_build,
    "/api/print/reveal": api_print_reveal,
    "/api/skills": api_skills,
    "/api/skills/preview": api_skills_preview,
    "/api/skills/save": api_skills_save,
    "/api/form/push": api_form_push,
}


# ---------------------------------------------------------------- serving --

def make_handler(course, token):
    class Handler(http.server.BaseHTTPRequestHandler):
        server_version = "checkit-printit"

        def log_message(self, fmt, *args):
            pass                      # the terminal is the instructor's

        # -- helpers --
        def _send(self, code, payload, ctype="application/json"):
            body = (json.dumps(payload).encode("utf-8")
                    if ctype == "application/json" else payload)
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            # Nothing here should ever be embedded in another page.
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("X-Frame-Options", "DENY")
            # Never cached. Everything is read from disk per request, so an
            # upgraded printit takes effect on reload. Without this the
            # browser keeps running yesterday's script against today's
            # server, and the mismatch is invisible -- it cost a confused
            # minute the first time the roster table changed shape. There is
            # no network here to save.
            self.send_header("Cache-Control", "no-store, must-revalidate")
            self.end_headers()
            self.wfile.write(body)

        def _authorised(self):
            return secrets.compare_digest(
                self.headers.get(TOKEN_HEADER, ""), token)

        def _static(self, path):
            name = os.path.normpath(path.lstrip("/")).replace("\\", "/")
            if name in ("", "."):
                name = "index.html"
            full = os.path.normpath(os.path.join(STATIC, name))
            # A traversal check, not a formality: this process can read the
            # instructor's whole home directory.
            if not full.startswith(STATIC) or not os.path.isfile(full):
                self._send(404, b"not found", "text/plain; charset=utf-8")
                return
            with open(full, "rb") as f:
                body = f.read()
            if name == "index.html":
                body = body.replace(b"__TOKEN__", token.encode())
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            self._send(200, body, f"{ctype}; charset=utf-8")

        # -- routes --
        def do_GET(self):
            path = urllib.parse.urlparse(self.path).path
            if path.startswith("/api/"):
                self._api(path, {})
            else:
                self._static(path)

        def do_POST(self):
            path = urllib.parse.urlparse(self.path).path
            length = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                body = json.loads(raw or b"{}")
            except ValueError:
                self._send(400, {"error": "the request was not JSON"})
                return
            self._api(path, body)

        def _api(self, path, body):
            if not self._authorised():
                self._send(403, {"error":
                                 "wrong or missing token -- reload the page"})
                return
            handler = ROUTES.get(path)
            if handler is None:
                self._send(404, {"error": f"no such endpoint: {path}"})
                return
            try:
                self._send(200, {"ok": True, "data": handler(course, body)})
            except (GuiError, roster_mod.RosterError) as exc:
                # A rule said no. That is an answer, not a crash.
                self._send(400, {"error": str(exc)})
            except OSError as exc:
                self._send(500, {"error": f"could not read or write a file: {exc}"})

    return Handler


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def serve(course_name, port=8765, open_browser=True, forever=True):
    """Start the local app. Returns (server, url, token)."""
    course = Course(course_name)
    token = secrets.token_urlsafe(24)
    httpd = Server(("127.0.0.1", port), make_handler(course, token))
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    if open_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    if forever:
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            httpd.server_close()
    return httpd, url, token
