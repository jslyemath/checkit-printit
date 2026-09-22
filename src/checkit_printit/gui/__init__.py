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
from .. import roster as roster_mod

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
TOKEN_HEADER = "X-Printit-Token"


class GuiError(Exception):
    pass


# ------------------------------------------------------------------- data --

def _student_json(student, index):
    """One row of the roster table.

    `index` is the identity the browser sends back. Not the name -- a rename
    is the whole point of the nickname column -- and not the SID, which some
    class lists do not carry.
    """
    return {
        "index": index,
        "name": student.name,
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


ROUTES = {
    "/api/course": api_course,
    "/api/roster": api_roster,
    "/api/roster/save": api_roster_save,
    "/api/roster/drop": api_roster_drop,
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
