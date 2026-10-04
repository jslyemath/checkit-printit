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
import sys
import threading
import traceback
import urllib.parse
import webbrowser

from .. import course as course_mod
from .. import availability as availability_mod
from .. import provision as provision_mod
from .. import responses as responses_mod
from .. import clasp as clasp_mod
from .. import boilerplate as boilerplate_mod
from .. import classlist as classlist_mod
from .. import printjob as printjob_mod
from .. import runner as runner_mod
from .. import form as form_mod
from ..bank import Bank, BankError
from .. import roster as roster_mod
from .. import seating as seating_mod

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

    `index` is the identity the browser sends back. Not the name -- the row
    exists to be renamed -- and not the SID, which some class lists do not
    carry.
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
        """The bank this course prints from, or None. See
        `course.bank_for` -- this used to be a second copy of it."""
        return course_mod.bank_for(self.name)

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


def api_setup(course, _body):
    """What the Setup view draws: the Google session and the connection."""
    conn = form_mod.load(course.path)
    return {
        "google": GOOGLE.status(),
        "connected": bool(conn.url),
        "url": conn.url,
        "scriptId": conn.script_id,
        "formId": conn.form_id,
        "items": dict(conn.items),
        "missing": conn.missing_slots(),
        "slots": dict(form_mod.SLOTS),
    }


def _provisioning(course, work, title=""):
    """Run a step that talks to Google, and keep "not authorized" apart.

    It is not a failure: the form and the web app exist by then, and the
    way on is for the instructor to grant permissions and come back. A 400
    would read as "that did not work", and the obvious response to that is
    to try the whole thing again -- which would make a second form.
    """
    try:
        said = work()
    except provision_mod.NeedsAuthorization as needs:
        state = api_setup(course, {})
        state["said"] = []
        state["needsAuthorization"] = {"url": needs.url,
                                       "why": provision_mod.prompt(needs.url),
                                       "title": title}
        return state
    except provision_mod.ProvisionError as exc:
        raise GuiError(str(exc)) from None
    state = api_setup(course, {})
    state["said"] = list(said)
    return state


def api_setup_create(course, body):
    """Make a new form and wire it up. The same call `form create` makes."""
    title = str(body.get("title") or "Skill Selection Form").strip()
    folder = str(body.get("folder") or "").strip()
    return _provisioning(
        course,
        lambda: provision_mod.create_form(course.name, title, folder),
        title=title)


def api_setup_inspect(course, body):
    """What attaching would overwrite in an existing script project.

    Asked before attaching, not discovered after. printit stages `Code.gs`
    and `appsscript.json`, which are the names most Apps Script projects
    already use, and the push replaces them -- so a form still driven by
    something else loses that something.
    """
    script_id = str(body.get("scriptId") or "").strip()
    if not script_id:
        raise GuiError("paste the bound script's id first.")
    try:
        return provision_mod.what_the_clone_would_replace(course.name,
                                                          script_id)
    except provision_mod.ProvisionError as exc:
        raise GuiError(str(exc)) from None


def api_setup_attach(course, body):
    """Wire up an existing form, changing nothing on the form itself."""
    script_id = str(body.get("scriptId") or "").strip()
    if not script_id:
        raise GuiError("paste the bound script's id first.")
    return _provisioning(
        course,
        lambda: provision_mod.attach_form(course.name, script_id))


def api_setup_finish(course, body):
    """Carry on after Google authorizes the script.

    Every step inside is safe to repeat, which is why coming back here is
    the way on rather than starting over.
    """
    title = str(body.get("title") or "").strip()
    return _provisioning(
        course,
        lambda: provision_mod.finish(course.name, rename_to=title),
        title=title)


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

    # The letter each seat gives, so the table can show what a student will
    # get before anything is drawn. Read from the chart rather than guessed:
    # it comes from a seat's position within its table, and a lone seat or a
    # table of three is not the same arithmetic as a table of four.
    seat_version, versions_available = {}, []
    seating_path = course.file("seating")
    if os.path.isfile(seating_path):
        try:
            chart = seating_mod.load(seating_path)
            versions_available = list(chart.versions)
            for seat in chart.seats:
                if str(seat.name).strip():
                    seat_version[seat.name] = seat.version
        except (OSError, seating_mod.SeatingError):
            pass

    students = []
    if people is not None:
        for i, s in enumerate(people):
            if s.dropped:
                continue
            key = roster_mod.key_of(s)
            students.append({
                "index": i, "key": key, "name": s.name,
                # What prints, and so what this view shows. One
                # definition, on the Student. See `Student.display`.
                "display": s.display,
                "section": s.section,
                "chose": list(s.skills),
                "override": list(draft["overrides"].get(key, []))
                            if key in draft["overrides"] else None,
                "seatVersion": seat_version.get(s.name, ""),
                "version": draft["versions"].get(key, ""),
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
        # Whether to offer the pull at all. A course can print happily
        # without ever having had a form.
        "hasForm": os.path.isfile(course.file("form")),
        "jobFolder": printjob_mod.folder_for(draft),
        "versionsAvailable": versions_available,
        # So "Reset this print job" is an ordinary edit that Discard can
        # undo, rather than a second way to write the file.
        "defaults": dict(printjob_mod.DEFAULTS),
    }


def api_print_save(course, body):
    """Save the draft, refusing anything the build would refuse later.

    A slug typed into an override reaches the build as
    "X asked for 'W9', which is not in the bank" -- after the job folder has
    been written. Caught here instead, while the box is still on screen.
    """
    draft = body.get("draft") or {}
    bank = course.bank()
    if bank is not None:
        known = set(bank.slugs())
        bad = {}
        for key, slugs in (draft.get("overrides") or {}).items():
            missing = [s for s in slugs if s not in known]
            if missing:
                bad[key] = missing
        for field in ("simply_print", "default_when_missing",
                      "append_for_everyone"):
            missing = [s for s in (draft.get(field) or []) if s not in known]
            if missing:
                bad[field] = missing
        for extra in (draft.get("extras") or []):
            if extra.get("skill") and extra["skill"] not in known:
                bad.setdefault("extras", []).append(extra["skill"])
        if bad:
            named = "; ".join(f"{k}: {', '.join(v)}" for k, v in bad.items())
            raise GuiError(f"not in the bank -- {named}")

    mode = draft.get("mode", "chose")
    if mode not in printjob_mod.MODES:
        raise GuiError(
            f"{mode!r} is not a mode. It is one of "
            f"{', '.join(printjob_mod.MODES)}.")

    # A letter beyond the chart's is allowed: that is how a version is
    # added from the app, and `assemble` draws seeds for whatever the pins
    # name. It still has to be a version letter and not prose, because the
    # value ends up in a filename and on a paper.
    for key, letter in (draft.get("versions") or {}).items():
        if not (isinstance(letter, str) and len(letter) == 1
                and "A" <= letter <= "Z"):
            raise GuiError(
                f"{letter!r} is not a version letter. Versions are a single "
                f"capital, A to Z.")

    printjob_mod.save_draft(course.name, draft)
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
        # Triples since the collision check started reading the paper
        # rather than the chart: the letter printed is not the seat's.
        "collisions": [f"{a.name} and {b.name} were both printed version "
                       f"{version} at table {a.group}"
                       for a, b, version in report["collisions"]],
        "unseated": list(report["unseated"]),
        "unmatchedOverrides": list(result.unmatched_overrides),
        "missingFields": {k: list(v) for k, v in report["missing_fields"].items()},
        "pdf": result.pdf,
        "recorded": result.recorded,
        "recordError": result.record_error,
        "themeInstalled": result.theme_installed,
    }


def _pull_json(outcome):
    """One shape for both the dry run and the real thing.

    Every count comes off `PullOutcome` rather than being re-derived here;
    a second derivation of "how many were out of scope" is a second thing
    to get wrong.
    """
    pulled = outcome.pulled
    return {
        "total": outcome.total,
        "assessment": outcome.assessment,
        "date": str(outcome.date or ""),
        "spokenDate": (availability_mod.spoken_date(outcome.date)
                       or str(outcome.date or "")),
        "knownFromBank": outcome.known_from_bank,
        "written": outcome.written,
        "trouble": outcome.trouble,
        "answered": pulled.answered,
        "silent": sorted(s.display for s in pulled.silent),
        "unknownEmails": list(pulled.unknown_emails),
        "unrecognised": [{"email": e, "option": o}
                         for e, o in pulled.unrecognised],
        "unconfirmed": pulled.unconfirmed,
        "outOfScope": pulled.out_of_scope,
        "superseded": pulled.superseded,
    }


def api_print_pull(course, body):
    """Read this assessment's responses, from the Print job view.

    `write` false is the dry run. `force` is the instructor saying "write
    the rest anyway" after seeing what could not be placed -- which is why
    the card shows the detail first and offers that button second.

    Returns the refreshed Print job payload alongside, because a pull
    rewrites the roster and the table underneath is showing it.
    """
    try:
        outcome = responses_mod.pull_for_course(
            course.name,
            write=bool(body.get("write", True)),
            force=bool(body.get("force")))
    except responses_mod.ResponseError as exc:
        raise GuiError(str(exc)) from None
    return {"pull": _pull_json(outcome), "print": api_print(course, {})}


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
    "/api/setup": api_setup,
    "/api/setup/create": api_setup_create,
    "/api/setup/inspect": api_setup_inspect,
    "/api/setup/attach": api_setup_attach,
    "/api/setup/finish": api_setup_finish,
    "/api/print": api_print,
    "/api/print/save": api_print_save,
    "/api/print/pull": api_print_pull,
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
            except Exception as exc:                      # noqa: BLE001
                # Anything else is a bug, and a bug must still answer. Left
                # uncaught, the handler dies without writing a response and
                # the browser can only say "failed to fetch" -- which is
                # what a missing `import sys` looked like for a week. The
                # traceback goes to the terminal, where it is useful.
                traceback.print_exc()
                self._send(500, {"error": f"{type(exc).__name__}: {exc}"})

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
