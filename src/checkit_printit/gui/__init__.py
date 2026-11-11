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

import base64
import dataclasses
import io
import datetime
import http.server
import json
import mimetypes
import os
import secrets
import shutil
import socketserver
import sys
import threading
import time
import traceback
import urllib.parse
import webbrowser

from .. import course as course_mod
from .. import availability as availability_mod
from .. import provision as provision_mod
from .. import room as room_mod
from .. import publication as pub_mod
from .. import assemble as assemble_mod
from .. import record as record_mod
from .. import scans as scans_mod
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
from .. import gradebook as gradebook_mod
from .. import mask as mask_mod

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


def _split_for_sort(full):
    """`sort_last` / `sort_first` for a name the record printed.

    The review knows a student by the name on the paper rather than by
    a roster row, so `_sort_names`, which takes a student, cannot be
    used. Same splitter underneath, and the same caveat: on a roster
    with one full-name column this is a guess and it is wrong on a
    compound surname. It decides a row's position in a sort and
    nothing else.
    """
    if not full:
        return {"sort_last": "", "sort_first": ""}
    last, first, _ = classlist_mod.split_full_name(full)
    return {"sort_last": last or "", "sort_first": first or ""}


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
    room_path = course.file("room")
    try:
        done = roster_mod.set_dropped(
            course.file("roster"), who, dropped,
            seating_path if os.path.isfile(seating_path) else None,
            room_path if os.path.isfile(room_path) else None)
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
        if done.room_emptied:
            note += " and their chair in the room"
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


#: "Not given", because `None` already means "this course has no bank".
_UNSET = object()


def _wording(course, av, bank=_UNSET):
    """Exactly what the form will say, worded by the same code that pushes it.

    `payload_for` is what `form push` sends, so a preview that used anything
    else would be a second implementation of the wording -- and the one
    place a difference would show up is on a form students are already
    looking at.

    `bank` is handed in by a caller that already built one. Building one
    costs ~130ms: it parses `bank.xml` and every outcome, and `bank_for`
    makes a fresh one each call. `api_skills` was paying that **three
    times for one request** -- once itself, once here, and once more
    because `_preview` called this again -- which was most of why opening
    the Update form tab took the better part of a second.

    Within one request, not across them: a `Bank` held between requests
    would also hold its lazily-loaded seed data, and a `checkit generate`
    mid-term would leave the app describing versions that no longer
    exist.
    """
    if bank is _UNSET:
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


def _preview(course, av, bank=_UNSET, wording=None):
    """The whole form as a student meets it: the boilerplate parts and the
    derived ones, in order.

    `wording` is the payload when the caller has already worked it out;
    this view shows both, and deriving one from the other is cheap while
    computing it twice is not.
    """
    if wording is None:
        wording = _wording(course, av, bank)
    return boilerplate_mod.preview(wording)


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
        # Left empty on purpose: the payload below falls back to the
        # slug, and a second mechanism saying the same thing is one
        # that can rot without any test going red.
        titles = {}
    else:
        slugs = list(bank.slugs())
        descriptions = {}
        titles = {}
        for slug in slugs:
            try:
                descriptions[slug] = bank.description(slug)
                titles[slug] = bank.skill_title(slug)
            except BankError:
                descriptions[slug] = ""
                titles[slug] = slug
        # A slug that is open but no longer in the bank still has to appear,
        # or it could not be turned off from here.
        for slug in open_now:
            if slug not in descriptions:
                slugs.append(slug)
                descriptions[slug] = ""

    conn = form_mod.load(course.path)
    # The bank built at the top of this function, reused: these two used
    # to build their own, so one request parsed the bank three times.
    wording = _wording(course, av, bank)
    in_bank = set(bank.slugs()) if bank is not None else None
    return {
        "hasBank": bank is not None,
        "skills": [{"slug": s, "description": descriptions.get(s, ""),
                    "title": titles.get(s, s),
                    "open": s in open_now,
                    "inBank": in_bank is None or s in in_bank}
                   for s in slugs],
        "open": open_now,
        "assessment": {
            "name": av.name, "date": str(av.date or ""),
            "due": str(av.due or ""), "choose": av.choose, "limit": av.limit,
        },
        "limits": list(availability_mod.LIMITS),
        "wording": wording,
        "preview": _preview(course, av, bank, wording),
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
    # One bank, one wording. This endpoint fires on every keystroke in
    # the assessment fields, so it was three bank parses per character.
    bank = course.bank()
    wording = _wording(course, proposed, bank)
    return {"wording": wording,
            "preview": _preview(course, proposed, bank, wording)}


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
        # The same question the command asks. There is no dry run
        # behind a button, so this is the only thing between one click
        # and a form that has lost its wording.
        empty = av.nothing_to_say()
        if empty:
            raise GuiError(empty + ".")
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


def api_course_identity(course, body):
    """Set the four header scalars in `course.toml`.

    There was no way to set these from anywhere: the course template
    writes `semester` and `professor` empty, `init` is the only command
    that touches the file, and the web app never offered a field. They
    print in the top right corner of every page, so a course that had
    never been hand-edited printed with a blank corner and said nothing.
    """
    fields = {k: str(body.get(k, "")).strip()
              for k in course_mod.IDENTITY if k in body}
    try:
        return {"identity": course_mod.save_identity(course.name, fields)}
    except course_mod.CourseError as exc:
        raise GuiError(str(exc)) from None


def api_setup(course, _body):
    """What the Setup view draws: the Google session and the connection."""
    # Deliberately does not ask whether Google is signed in. That is an
    # `npx` invocation taking seconds, and this is a file read; behind it,
    # the view spent ten seconds showing "Make a new form" on a course
    # that already had one. The view asks `/api/google` separately.
    conn = form_mod.load(course.path)
    return {
        "connected": bool(conn.url),
        "url": conn.url,
        "scriptId": conn.script_id,
        "formId": conn.form_id,
        "items": dict(conn.items),
        "missing": conn.missing_slots(),
        "slots": dict(form_mod.SLOTS),
        # The header scalars, so the view has somewhere to set them.
        "identity": course_mod.identity(course.name),
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
        state["needsAuthorization"] = {
            "url": needs.url,
            # The notes, not the terminal's paragraph: the page puts the
            # URL on a button, so repeating it as text is noise.
            "notes": list(provision_mod.AUTHORIZE_NOTES),
            "title": title,
        }
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


def api_setup_authorize(course, _body):
    """Open this course's script in the instructor's own browser.

    Not `window.open`: the page may be running in the desktop app's
    browser pane, which has no Google session, while clasp's sign-in opens
    the operating system's default browser. Two halves of one flow landing
    in two browsers is how the authorization step became impossible to
    complete.

    The URL comes from `form.toml`, never from the request. An endpoint on
    localhost that opened whatever it was handed would let any page in any
    browser launch arbitrary URLs on this machine.
    """
    conn = form_mod.load(course.path)
    if not conn.url:
        raise GuiError("this course has no deployed script to authorize yet.")
    webbrowser.open(conn.url)
    return {"opened": conn.url}


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


def _seating_json(course):
    """Everything the canvas draws.

    The room holds student ids; the names are sent beside it rather than
    baked in, so a rename shows up on the next load without the room file
    being touched. Split into two lines here because the card is two lines
    -- squarer than one long one, and legible from the back of a room when
    this is on the projector.

    `seated` is which section each student belongs to and whether they
    already have a chair, so the tab can offer the people who are still
    standing without a second request.
    """
    people = course.roster()
    names, sections = {}, {}
    if people is not None:
        for student in people:
            if student.dropped:
                # A dropped student keeps their place in the record and
                # loses their chair; offering them one here would put them
                # back on the paper.
                continue
            shown = student.display
            cut = shown.find(" ")
            key = roster_mod.key_of(student)
            names[key] = {
                "full": shown,
                "top": shown[:cut] if cut > 0 else shown,
                "bottom": shown[cut + 1:] if cut > 0 else "",
            }
            sections[key] = student.section or ""
    room = room_mod.load(course.file("room"))
    chart = course.file("seating")
    return {
        "room": room,
        "names": names,
        "sections": sections,
        # `seats` goes too, so the canvas can build a new desk from the
        # palette without carrying its own copy of where the chairs go.
        # The definition stays in `room.SHAPES`; the browser reads it.
        "shapes": {kind: {"label": spec["label"], "w": spec["w"],
                          "h": spec["h"], "css": spec["css"],
                          "seats": [list(s) for s in spec["seats"]]}
                   for kind, spec in room_mod.SHAPES.items()},
        "hasRoster": people is not None,
        # Whether saving here will also rewrite the chart the build reads.
        # Sent so the save bar can say what the button does before it is
        # pressed, rather than reporting it afterwards.
        "chartIsOurs": (not os.path.isfile(chart)
                        or seating_mod.was_generated(chart)),
        "chartName": os.path.basename(chart),
    }


def api_seating(course, _body):
    return _seating_json(course)


def api_seating_versions(course, body):
    """Hand out version letters again, by the real coloring.

    `room.assign_versions` -- the same function the CLI uses, with the
    same graph coloring and the same heuristics about who can see
    whom. The rule in this project is that a button calls the function
    the command does, and a second implementation of the coloring
    living in JavaScript would be exactly the kind of drift that rule
    exists to stop: the browser's answer and the printed answer would
    agree until one of them was improved.

    Nothing is written. The room comes back changed and the canvas
    holds it as an unsaved edit, so an instructor who dislikes the
    shuffle presses Discard and nothing happened. Reshuffling is not a
    decision anybody should have to take permanently to look at.
    """
    incoming = body.get("room")
    if not isinstance(incoming, dict):
        raise GuiError("that request carried no room.")
    at = body.get("section")
    sections = incoming.get("sections") or []
    if not isinstance(at, int) or not 0 <= at < len(sections):
        raise GuiError("that request did not say which room.")

    letters = body.get("versions") or incoming.get("versions")
    if not isinstance(letters, list) or not letters:
        raise GuiError("no version letters to hand out.")

    section = sections[at]
    try:
        chosen, clashes = room_mod.assign_versions(
            room_mod.seats_of(section), room_mod.group_of(section), letters)
    except room_mod.RoomError as exc:
        raise GuiError(str(exc)) from None
    room_mod.apply_versions(section, chosen)
    incoming["versions"] = list(letters)

    note = f"Versions spread over {len(letters)} letters."
    if clashes:
        # Said plainly rather than hidden: with fewer letters than a
        # table has seats there is no coloring without a repeat, and
        # the instructor is the one who chose how many letters.
        note += (f" {len(clashes)} pair"
                 f"{'s' if len(clashes) != 1 else ''} of neighbours had "
                 f"to share -- there are not enough letters to keep "
                 f"every pair apart.")
    return {"room": incoming, "note": note, "clashes": len(clashes)}


def api_seating_start(course, body):
    """Draw the first room for a course that has none.

    **Server-side so `room.new_section` stays one definition.** The
    canvas could build the dict itself in four lines, and then there
    would be two answers to "what is a section" -- which is the shape
    of bug this codebase keeps finding. The rule here is that a button
    calls the function a command would.

    **One room per section the roster names.** Not one room, and not a
    name typed into a box: `standing` filters the unseated rail by
    comparing the section's name to the roster's `section` field, so a
    name that does not match a roster value silently turns the filter
    off and shows every student in both sections. The names are
    therefore taken from the roster rather than invented. A roster with
    no sections at all is one room, not none.

    Nothing is written, like the shuffle: the room comes back as an
    unsaved edit for the canvas to hold, so Discard still works and an
    empty room is not committed to disk by looking at it.
    """
    incoming = body.get("room")
    if not isinstance(incoming, dict):
        raise GuiError("that request carried no room.")
    if incoming.get("sections"):
        raise GuiError("this course already has a room drawn.")

    people = course.roster()
    names = sorted({s.section for s in people if s.section}) if people else []
    if not names:
        names = [""]
    incoming["sections"] = [room_mod.new_section(name, i + 1)
                            for i, name in enumerate(names)]

    shown = ", ".join(n or "unnamed" for n in names)
    note = (f"Started {len(names)} rooms: {shown}. Add some furniture."
            if len(names) > 1 else "Room started. Add some furniture.")
    return {"room": incoming, "note": note}


def api_seating_shuffle(course, body):
    """Deal the seated people into different chairs.

    Server-side for the same reason the coloring is: the rule in this
    project is that a button calls the function a command would, and
    the rule a shuffle has to keep -- step round the pinned, leave the
    rail alone, leave the letters on the chairs -- is the kind of thing
    that is worth a test, which a shuffle living in the canvas could
    not have.

    Nothing is written. The room comes back changed and the canvas
    holds it as an unsaved edit, so an instructor who does not like
    where everyone landed presses Discard and the morning's seating is
    still there. A reshuffle is not a decision anybody should have to
    commit to in order to look at it.
    """
    incoming = body.get("room")
    if not isinstance(incoming, dict):
        raise GuiError("that request carried no room.")
    at = body.get("section")
    sections = incoming.get("sections") or []
    if not isinstance(at, int) or not 0 <= at < len(sections):
        raise GuiError("that request did not say which room.")

    section = sections[at]
    # `live_seats`, not `seats_of`. The latter is a view that builds a
    # fresh dict per seat and carries only id, shape, student, version
    # and position -- so asking it about pins answers none, every
    # time, and the note quietly stopped mentioning them.
    held = sum(1 for seat in room_mod.live_seats(section)
               if seat.get("pinned"))
    moved = room_mod.shuffle_seats(section)

    if not moved:
        note = ("Nobody moved. There has to be more than one unpinned "
                "chair with somebody in it.")
    else:
        note = f"{moved} moved."
        if held:
            chairs = "chair" if held == 1 else "chairs"
            note += f" {held} pinned {chairs} stayed put."
    return {"room": incoming, "note": note, "moved": moved, "pinned": held}


def api_seating_fill(course, body):
    """Seat everybody who is standing, or stand everybody up.

    One handler for both, because they are the same request with the
    sign flipped and they share every rule -- pinned chairs are
    exempt, nothing is written, the room comes back for the canvas to
    hold as an unsaved edit.

    **The canvas says who is standing.** It is the only thing that
    knows: the rail is filtered by section when the roster's section
    names match the room's and shown whole when they do not, and a
    second copy of that rule living here would answer differently the
    first time somebody renamed a section.
    """
    incoming = body.get("room")
    if not isinstance(incoming, dict):
        raise GuiError("that request carried no room.")
    at = body.get("section")
    sections = incoming.get("sections") or []
    if not isinstance(at, int) or not 0 <= at < len(sections):
        raise GuiError("that request did not say which room.")

    section = sections[at]
    held = sum(1 for seat in room_mod.live_seats(section)
               if seat.get("pinned"))
    pinned_note = ""
    if held:
        chairs = "chair" if held == 1 else "chairs"
        pinned_note = f" {held} pinned {chairs} left as they were."

    if body.get("clear"):
        gone = room_mod.clear_seats(section)
        note = (f"{gone} stood up." + pinned_note) if gone \
            else "Nobody was sitting in an unpinned chair."
        return {"room": incoming, "note": note, "moved": gone}

    students = body.get("students")
    if not isinstance(students, list):
        raise GuiError("that request did not say who is standing.")
    sat = room_mod.seat_students(section, students)
    left = len(students) - sat
    if not sat:
        note = ("Nobody sat down. There are no empty chairs that are not "
                "pinned.") if students else "Everybody already has a chair."
    else:
        note = f"{sat} seated." + pinned_note
        if left:
            note += (f" {left} still standing -- the room ran out of "
                     f"chairs.")
    return {"room": incoming, "note": note, "moved": sat, "left": left}


def api_seating_save(course, body):
    """Write the room the canvas is showing, and the chart if it is ours.

    The whole document rather than a diff. A room is one small file read
    whole and written whole -- that is the reason it is JSON -- and a diff
    would need a conflict story that a single-user local app has no use
    for.

    **Checked, not trusted.** See `room.check`. This is the only door a
    room arrives by that printit did not write itself, and every rule
    there guards a failure that is silent further down.

    **The chart as well, when that is safe.** A room nothing reads is a
    toy: the file the build opens is `seating.toml`, so saving here
    rewrites it. Two conditions, because overwriting a chart is how a
    term's seating disappears:

    * somebody has to be seated, so an untouched course cannot replace a
      real chart with an empty one; and
    * the chart on disk has to be one this tab wrote, or absent. A chart
      that came from an import or a text editor is left exactly alone and
      the answer says so. That is the 10-02 mistake in different clothes:
      a file that carries an instruction is not a file to reach past.
    """
    incoming = body.get("room")
    if not isinstance(incoming, dict):
        raise GuiError("that request carried no room.")

    # Every key the roster answers to, not just the preferred one, so a
    # room written before a student gained an SID still loads.
    people = course.roster()
    known, name_of = None, {}
    if people is not None:
        known = set()
        for student in people:
            for key in roster_mod.keys_of(student):
                known.add(key)
                name_of.setdefault(key, student.name)

    try:
        room_mod.check(incoming, known)
    except room_mod.RoomError as exc:
        raise GuiError(str(exc)) from None

    room_mod.save(course.file("room"), incoming)

    seated = sum(1 for section in incoming.get("sections") or []
                 for seat in room_mod.seats_of(section) if seat["student"])
    chart = course.file("seating")
    name = os.path.basename(chart)
    if not seated:
        note = (f"Room saved. Nobody is sitting anywhere yet, so {name} is "
                f"left as it is.")
    elif os.path.isfile(chart) and not seating_mod.was_generated(chart):
        note = (f"Room saved. {name} was not written by this tab -- it was "
                f"imported or typed -- so it has been left alone, and the "
                f"build still reads it rather than this room.")
    else:
        with open(chart, "w", encoding="utf-8") as f:
            f.write(seating_mod.to_toml(
                incoming, lambda key: name_of.get(key, "")))
        note = f"Room saved, and {name} rewritten from it."
        # The one thing a saved room can be silently missing.
        #
        # With no letters on the seats the chart carries none, and a
        # build alternates A B C D along each table instead -- safe
        # within a table, and knowing nothing about who sits near whom
        # across the room. The Print view shows those invented letters
        # in a column headed "Version", which is where an instructor
        # reasonably believes their seating has been read. Said here
        # because this is the moment the file is written.
        lettered = any(
            (seat.get("version") or "").strip()
            for section in incoming.get("sections") or []
            for seat in room_mod.live_seats(section)
            if (seat.get("student") or "").strip()
        )
        if seated and not lettered:
            note += (" No seat has a version yet, so the build will "
                     "alternate them. Printing \u22ef Shuffle versions.")

    out = _seating_json(course)
    out["note"] = note
    return out


def _form_brief(course):
    """Whether this course can reach its form at all.

    **Not a Google session.** `form push` and `form pull` both go through
    `form.call`, an HTTPS POST to the deployed Apps Script web app
    carrying the shared secret from `secrets/form-secret.toml`. No OAuth
    token, no clasp, no browser. A course whose clasp sign-in has lapsed
    pushes and pulls perfectly well, which is why the Form tab's old
    banner -- "Not signed in to Google, so pushing will fail" -- was
    false, and said so on a morning when a pull was in fact succeeding.

    clasp is needed by `provision.py` alone, to deploy or redeploy the
    script. That belongs on Settings, not on either working tab.
    """
    try:
        conn = form_mod.load(course.path)
    except Exception:
        return {"connected": False, "hasFile": False}
    return {"connected": bool(conn.ready),
            "hasFile": os.path.isfile(course.file("form"))}


def _assessment_brief(course):
    """The next assessment's name and date, or empty when unreadable.

    Never raises. The Print tab has to draw on a course whose
    `availability.toml` is missing or malformed -- that is a Setup
    problem, and a blank staging view is a bad way to report it.
    """
    try:
        av = availability_mod.load(course.file("availability"))
    except Exception:
        return {"name": "", "date": "", "spoken": ""}
    day = availability_mod.as_date(av.date)
    return {
        "name": av.name or "",
        "date": day.isoformat() if day else "",
        "spoken": availability_mod.spoken_date(av.date),
    }


def api_print(course, _body):
    """Everything the staging view draws."""
    draft = printjob_mod.load_draft(course.name)
    people = course.roster()
    bank = course.bank()

    slugs = list(bank.slugs()) if bank is not None else []
    # Two endpoints need this and they are not the same loop. The
    # first attempt added titles to the payload here and built them
    # only in `api_skills`, so this one raised NameError -- caught by
    # a test, not by reading, which is the usual way round.
    descriptions = {}
    titles = {}
    if bank is not None:
        for slug in slugs:
            try:
                descriptions[slug] = bank.description(slug)
                titles[slug] = bank.skill_title(slug)
            except BankError:
                descriptions[slug] = ""
                titles[slug] = slug

    # The chart, for two things: the order the stack comes out in, and
    # the letter each seat gives. Both read from the file the build
    # reads, through the call the build makes.
    chart, versions_available, seating_note = None, [], ""
    seating_path = course.file("seating")
    if os.path.isfile(seating_path):
        try:
            chart = seating_mod.load(seating_path)
            versions_available = list(chart.versions)
        except (OSError, seating_mod.SeatingError) as exc:
            seating_note = str(exc)

    # Seating order, which is print order, with anyone unseated after
    # them -- exactly what `build_handouts` does, by the same call. A
    # chart that cannot be read leaves the roster's own order, and
    # says why rather than pretending.
    live = [s for s in (people or []) if not s.dropped]
    where = {roster_mod.key_of(s): i for i, s in enumerate(people or [])}
    if chart is not None:
        try:
            seated, unseated = chart.order(live)
            live = list(seated) + list(unseated)
        except seating_mod.SeatingError as exc:
            seating_note = str(exc)

    students = []
    if people is not None:
        for s in live:
            i = where.get(roster_mod.key_of(s), -1)
            key = roster_mod.key_of(s)
            students.append({
                "index": i, "key": key, "name": s.name,
                # What prints, and so what this view shows. One
                # definition, on the Student. See `Student.display`.
                "display": s.display,
                "section": s.section,
                "chose": list(s.skills),
                # Which assessment those choices were made for, ISO, or
                # "" when the roster does not say. "" is *unknown*, not
                # agreement -- the view must not colour it as current.
                "choseFor": (s.chose_for.isoformat() if s.chose_for else ""),
                "override": list(draft["overrides"].get(key, []))
                            if key in draft["overrides"] else None,
                # From the seat the chart gave this student, not
                # from a lookup by name: the chart matches on id
                # first *because names change*, and a renamed
                # student was keeping their seat in the build while
                # losing their letter here.
                "seatVersion": getattr(s, "version", "") or "",
                "version": draft["versions"].get(key, ""),
            })

    identity = _course_identity(course)
    return {
        "draft": draft,
        "students": students,
        "skills": [{"slug": s, "description": descriptions.get(s, ""),
                    "title": titles.get(s, s)}
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
        # The same shape `api_skills` returns, so one banner in the page
        # reads both tabs' answers. `connected` is the real precondition
        # for push and pull: a deployed web app and the shared secret.
        # It is *not* the Google sign-in -- see `_form_brief`.
        "form": _form_brief(course),
        # What the course believes the next assessment is. The job has
        # its own date, and the two being different is exactly the
        # failure this view now reports: on 2026-10-23 the job said
        # 10/23 and the assessment still said 10/16, so the pull kept
        # re-fetching last week and every row read as current.
        "assessment": _assessment_brief(course),
        "jobFolder": printjob_mod.folder_for(draft),
        "versionsAvailable": versions_available,
        # Empty when the chart was read. Anything else means the table
        # is in roster order and the paper will not be.
        "seatingNote": seating_note,
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

    # `load_draft` quietly reads an unknown value as "all", which is
    # right for a file an older version wrote and wrong for a request
    # arriving now: that is a caller bug, and the quiet reading turns
    # it into a class set nobody asked for.
    who = draft.get("who", "all")
    if who not in printjob_mod.WHO:
        raise GuiError(
            f"{who!r} is not who a run is for. It is one of "
            f"{', '.join(printjob_mod.WHO)}.")

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


def _check_chart_matches_room(course):
    """Refuse a build whose two seating files disagree.

    Only reachable from the web app, because `room.json` is its file --
    the CLI build reads `seating.toml` and knows nothing else. Both are
    written by the same save, so a divergence means one of them was
    edited alone, and what prints would not be what the Seats tab
    shows.
    """
    chart_path = course.file("seating")
    room_path = course.file("room")
    if not (os.path.isfile(chart_path) and os.path.isfile(room_path)):
        return
    try:
        chart = seating_mod.load(chart_path)
        room = room_mod.load(room_path)
    except (OSError, seating_mod.SeatingError, room_mod.RoomError):
        # Neither is this check's business to report: the build and the
        # Seats tab each say so in their own words, and a second
        # unreadable-file message here would only arrive first.
        return
    problems = seating_mod.disagrees_with_room(chart, room)
    if problems:
        raise GuiError(
            "the seating chart and seating.toml disagree, so what prints "
            "would not be what the Seats tab shows:\n\n"
            + "\n".join("  " + p for p in problems)
            + "\n\nOpen Seats and save it to rewrite seating.toml.")


def _build(course, preview, seed=None):
    _check_chart_matches_room(course)
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
    except assemble_mod.FolderInUse as exc:
        # Its own branch so the wording can be about this app, which
        # has no --replace: here the way out is the title and date
        # fields at the top of the page, and they are one click away.
        raise GuiError(
            f"{exc} The title and date at the top of this tab are what "
            f"name the folder.") from None
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
        "headerGaps": report.get("header_gaps", []),
        "collisions": [f"{a.name} and {b.name} were both printed version "
                       f"{version} at table {a.group}"
                       for a, b, version in report["collisions"]],
        "unseated": list(report["unseated"]),
        "unmatchedOverrides": list(result.unmatched_overrides),
        "anonymous": result.anonymous,
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


# ----------------------------------------------------------------- runs --

def _run_json(row):
    """One row of the Runs list.

    `built` is kept distinct from `date` on purpose: the date is what
    is printed on the paper and the one the instructor thinks in, and
    `built` is when the folder was actually written. They differ -- the
    10-19 run is dated the 19th and was built at 10:43:37 -- and a list
    that showed only one of them could not explain two runs with the
    same date.
    """
    return {
        "id": row["run_id"],
        "title": row["title"],
        "date": row["date"],
        "built": row["built"],
        "seed": row["seed"],
        "papers": row.get("papers", 0),
        "students": row.get("students", 0),
        "extras": row.get("extras", 0),
        "output": row["output"],
        "delisted": bool(row.get("delisted")),
        "graded": bool(row.get("graded")),
        # Whether the folder is still on disk. A run whose folder has
        # been moved or deleted can still be listed -- the record is
        # the record -- but Reprint cannot work, and saying so here is
        # better than a button that fails when pressed.
        "onDisk": bool(row["output"]) and os.path.isdir(row["output"]),
    }


def api_runs(course, _body):
    """Every run, newest first, with the delisted at the end.

    Sorted here rather than in SQL: `runs()` orders oldest-first
    because every other caller wants a history, and reversing a list
    of at most a few dozen rows is cheaper than a second query that
    could drift from the first.
    """
    rows = [_run_json(r) for r in record_mod.runs(course.file("record"))]
    rows.reverse()
    live = [r for r in rows if not r["delisted"]]
    gone = [r for r in rows if r["delisted"]]
    return {"runs": live, "delisted": gone,
            "hasRecord": os.path.isfile(course.file("record"))}


def api_run(course, body):
    """One run's detail page."""
    run_id = str(body.get("id") or "").strip()
    if not run_id:
        raise GuiError("no run was named.")
    detail = record_mod.run_detail(course.file("record"), run_id)
    if detail is None:
        raise GuiError(
            f"no run called {run_id!r} is in this course's record. It may "
            f"have been built before the record existed, or under another "
            f"course.")
    out = _run_json(detail)
    out["skills"] = [dict(s) for s in detail["skills"]]
    out["seeds"] = [dict(s) for s in detail["seeds"]]
    return {"run": out}


def api_run_flag(course, body):
    """Delist, relist, or mark graded. Returns the refreshed list.

    The list comes back rather than the one row, because delisting
    moves a run between two groups and the view would otherwise have
    to work out where it went.
    """
    run_id = str(body.get("id") or "").strip()
    fields = {}
    for name in ("delisted", "graded"):
        if name in body:
            fields[name] = bool(body[name])
    if not fields:
        raise GuiError("nothing to set.")
    try:
        record_mod.set_flags(course.file("record"), run_id, **fields)
    except record_mod.RecordError as exc:
        raise GuiError(str(exc)) from None
    return api_runs(course, {})


def api_run_discard(course, body):
    """Throw away a run that was never handed out.

    The papers go with it -- that is the point, since a run nobody
    sat still puts a row in every one of those students' drill-ins.
    Refused for a graded run by `record.discard_run`, which is the
    same rule that stops a graded run being delisted.

    The job folder on disk is left alone. It holds the PDF and the
    page index, it is outside every repository, and deleting a
    person's files because they tidied a list is not this button's
    business.
    """
    run_id = str(body.get("id") or "").strip()
    try:
        papers = record_mod.discard_run(course.file("record"), run_id)
    except record_mod.RecordError as exc:
        raise GuiError(str(exc)) from None
    out = api_runs(course, {})
    out["discarded"] = papers
    return out


def _job_folder_for_run(row):
    """Where the job folder of a finished run is.

    `run_id` is the output folder's name, which `folder_for` builds
    from the same title and date -- so the job folder is found by
    rebuilding the name rather than by storing a second path that
    could go stale.
    """
    return printjob_mod.folder_for({"title": row["title"],
                                    "date": row["date"]})


def api_run_replay(course, body):
    """Reprint a finished run exactly, from its manifest.

    Draws nothing: every version comes from the manifest. Separate
    from `api_run_reuse` on purpose -- merging the two is how somebody
    reprints last month's papers by accident.
    """
    run_id = str(body.get("id") or "").strip()
    detail = record_mod.run_detail(course.file("record"), run_id)
    if detail is None:
        raise GuiError(f"no run called {run_id!r}.")
    if not detail["output"] or not os.path.isdir(detail["output"]):
        raise GuiError(
            f"this run's folder is not where the record says it is "
            f"({detail['output'] or 'no path recorded'}), so there is no "
            f"manifest to reprint from. Starting a new run from its "
            f"settings still works.")
    pub = os.path.join(_job_folder_for_run(detail), "publication.toml")
    if not os.path.isfile(pub):
        raise GuiError(
            f"this run's job folder no longer has a publication.toml, so "
            f"it cannot be reprinted. Expected it beside "
            f"{_job_folder_for_run(detail)}.")
    try:
        result = runner_mod.run(pub, replay=detail["output"])
    except runner_mod.BuildError as exc:
        raise GuiError(str(exc)) from None
    return {"out": result.out, "papers": result.replay_papers,
            "notes": list(result.replay_notes)}


#: The parts of a finished run worth carrying into a new one. Not the
#: title, the date, the seeds or the per-student overrides: those are
#: what makes it *that* run, and copying them is how a fresh run comes
#: out as a quiet duplicate of an old one.
REUSED = ("mode", "simply_print", "default_when_missing",
          "append_for_everyone", "variants", "extras", "keys",
          "key_copies", "names")


def api_run_reuse(course, body):
    """Load a finished run's settings into the print draft.

    Drawn fresh against today's roster when the instructor builds; this
    only fills the form. It does **not** save -- the draft comes back
    for the Print tab to show, and the instructor saves it like any
    other edit, so there is something to discard.
    """
    run_id = str(body.get("id") or "").strip()
    detail = record_mod.run_detail(course.file("record"), run_id)
    if detail is None:
        raise GuiError(f"no run called {run_id!r}.")
    pub = os.path.join(_job_folder_for_run(detail), "publication.toml")
    if not os.path.isfile(pub):
        raise GuiError(
            f"this run's settings are not on disk any more. Expected a "
            f"publication.toml in {_job_folder_for_run(detail)}.")
    try:
        old = pub_mod.load(pub)
    except pub_mod.PublicationError as exc:
        raise GuiError(str(exc)) from None

    draft = printjob_mod.load_draft(course.name)
    for key in REUSED:
        value = getattr(old, key, None)
        if value is None:
            continue
        draft[key] = (dict(value) if isinstance(value, dict)
                      else list(value) if isinstance(value, (list, tuple))
                      else value)
    # `simply_print` decides the mode, the way `load_draft` reads it.
    draft["mode"] = "same" if draft.get("simply_print") else "chose"
    return {"draft": draft, "from": run_id}


# --------------------------------------------------------------- scans ----

class Scanning:
    """One read at a time, in a thread, because it takes minutes.

    Several hundred pages, each rendered and searched for a code. A
    request that did that inline would hold the connection open long
    enough for the page to look hung -- the same reason the Google
    sign-in runs this way.

    One at a time, and deliberately: two reads of the same stack
    would race for the same scratch folder, and there is no honest
    reason to start a second before the first has been looked at.

    One at a time, but *cumulative*. The copier mails a tray at a
    time, so a run routinely arrives as three PDFs over ten minutes,
    and a second read has to join the first rather than replace it.
    Replacing it is wrong in the worst direction: the missing list
    would name students whose papers are sitting in the file read
    first. So `sheets` is kept across reads and the batch is rebuilt
    from the whole pile, which costs nothing -- `Batch` derives runs,
    duplicates and missing from its sheet list and nothing else.

    Re-reading a file replaces that file's pages instead of adding a
    second copy of them. Dropping the same stack twice is a slip; the
    duplicates table is for paper that really did go through twice,
    and burying that signal under self-inflicted pairs would make it
    useless.
    """

    def __init__(self):
        self.running = False
        self.done = 0
        self.total = 0
        self.result = None
        self.error = ""
        self.started_at = 0.0
        #: Every sheet read since the last `clear()`, across files.
        self.sheets = []
        #: Those files' base names, in the order they were first read.
        self.files = []
        #: `{(scan file, page): (run_id, sid, slug)}` -- what he
        #: decided about these pages the last time he saved them.
        #: Kept across reads for the same reason `sheets` is: adding
        #: a second stack must not forget the first.
        self.corrections = {}

    def status(self):
        return {"running": self.running, "done": self.done,
                "total": self.total, "result": self.result,
                "error": self.error, "files": list(self.files),
                "pages": len(self.sheets)}

    def clear(self):
        """Forget the pile, so the next read starts a fresh one."""
        if self.running:
            raise GuiError("a stack is being read right now.")
        self.sheets, self.files = [], []
        self.result, self.error = None, ""

    def start(self, course, paths):
        if self.running:
            raise GuiError("a stack is already being read.")
        self.running, self.done, self.total = True, 0, 0
        self.error = ""
        self.started_at = time.time()
        record_path = course.file("record")

        def progress(done, total):
            self.done, self.total = done, total

        # Read on the way in, rather than inside `_batch_json`: the
        # section belongs to the course and the batch knows nothing
        # about rosters. No roster is not an error here -- reading a
        # stack does not need one -- so the column comes out empty.
        try:
            sections = {s.sid: (s.section or "")
                        for s in (course.roster() or []) if s.sid}
        except (OSError, ValueError):
            sections = {}

        # What he decided about these pages last time, by page. Read
        # before the thread starts, because it is a few small queries
        # and doing them here keeps the thread to one job.
        fixed = {}
        for one in paths:
            name = os.path.basename(one)
            for page, what in record_mod.scan_corrections(
                    record_path, name).items():
                fixed[(name, page)] = what

        def run():
            try:
                batch = scans_mod.read_pdfs(paths, record_path,
                                            on_page=progress,
                                            # Who could have written an
                                    # id into a grid: the roster, not
                                    # the students handed this skill.
                                    # A spare is printed with nobody
                                    # assigned to it, so the person who
                                    # picked one up need not appear in
                                    # the run at all.
                                    candidates=list(sections),
                                            # `id` as well: on a paper printed
                                    # without a name the grid is the
                                    # only thing on the sheet that says
                                    # whose it is.
                                    want=("box", "name", "id", "page"))
                self.sheets = _joined(self.sheets, batch.sheets, paths)
                self.files = _file_order(self.files, paths)
                self.corrections.update(fixed)
                self.result = _batch_json(
                    scans_mod.Batch(sheets=self.sheets),
                    record_path, sections, self.corrections)
            except (scans_mod.ScanError, OSError) as exc:
                self.error = str(exc)
            except Exception as exc:                      # noqa: BLE001
                traceback.print_exc()
                self.error = f"the read failed: {exc}"
            finally:
                self.running = False

        threading.Thread(target=run, daemon=True).start()


SCANNING = Scanning()


def _joined(kept, fresh, paths):
    """The pile after a read: what was there, plus what just arrived.

    Pages from a file in `paths` are dropped from `kept` first, so
    reading a file a second time *replaces* its pages. Compared on
    the real path rather than the base name, because two files of the
    same name in different folders are two different stacks -- though
    in practice both land in the course's own `scans/`, which is why
    re-reading is the common case and worth getting right.
    """
    again = {os.path.realpath(p) for p in paths}
    older = [s for s in kept if os.path.realpath(s.source) not in again]
    return older + list(fresh)


def _file_order(known, paths):
    """File names in the order first seen, without repeats."""
    names = list(known)
    for path in paths:
        name = os.path.basename(path)
        if name not in names:
            names.append(name)
    return names


class _Pile:
    """What the record already knows about the papers in this stack.

    One object, built once, because three separate things need the
    same answer and a second copy of a rule is how the two halves of
    this tab came to disagree before.

    **The question it exists for.** Putting a few corrected papers
    back through the copier used to bring up the whole job they came
    from. `Batch.missing` walks every run any sheet touched and lists
    every student page not in the pile, so one stray sheet from
    October produced eighty-five "missing" rows for papers graded
    weeks ago and sitting in a drawer.

    So a run's absentees are only worth asking about when that run is
    *being scanned for the first time* -- when something in this pile
    is a paper the record has no result for. A run merely being
    re-scanned contributes no absentees at all, and inside a
    first-time run a paper that already has a result is not asked
    about either: confirming "absent" for a paper already marked
    absent is asking him to agree with something nobody doubts.
    """

    def __init__(self, batch, record_path):
        self.batch = batch
        #: run number -> that run's `run_id` in the record.
        self.run_id = {}
        for sheet in batch.placed:
            if sheet.run_no not in self.run_id:
                row = record_mod.run_by_no(record_path, sheet.run_no)
                self.run_id[sheet.run_no] = (row or {}).get("run_id", "")
        self._already = record_mod.recorded_in(record_path,
                                               self.run_id.values())

        #: Runs with at least one paper in this pile the record has no
        #: result for. Those are the runs whose absentees mean
        #: something.
        self.first_time = set()
        #: Papers in this pile that already had a result -- a
        #: re-scan. Counted for the badge, and marked on the row, so a
        #: corrected "?" is visible as a correction rather than
        #: looking like a fresh read.
        self.rescanned = set()
        for sheet in batch.placed:
            entry = sheet.entry
            if entry is None or not entry.gradable:
                continue
            if self.recorded(sheet.run_no, entry.sid, entry.slug):
                self.rescanned.add((sheet.run_no, sheet.run_page))
            else:
                self.first_time.add(sheet.run_no)

    def recorded(self, run_no, sid, slug):
        """What the record holds for this paper, or ''."""
        return self._already.get(
            (self.run_id.get(run_no, ""), sid, slug), "") or ""

    def is_rescan(self, run_no, page):
        return (run_no, page) in self.rescanned

    def missing(self, resolve):
        """`{run: [pages]}`, but only the ones worth asking about.

        A filter, not a second opinion about what is absent:
        `Batch.missing` still answers "what did not arrive", and this
        drops the runs and the papers he has already answered for.
        """
        out = {}
        for run_no, pages in self.batch.missing(resolve).items():
            if run_no not in self.first_time:
                continue
            index = resolve(run_no)
            if index is None:
                continue
            keep = [page for page in pages
                    if (index.get(page) is not None
                        and not self.recorded(run_no,
                                              index.get(page).sid,
                                              index.get(page).slug))]
            if keep:
                out[run_no] = keep
        return out

    def held_back(self, resolve):
        """`{run: how many}` absentee rows the filter removed.

        Reported rather than dropped silently: a run short of two
        papers is worth knowing about even when its rows are not
        worth answering, and a number that quietly became zero is how
        a filter like this hides a real problem.
        """
        shown = self.missing(resolve)
        out = {}
        for run_no, pages in self.batch.missing(resolve).items():
            held = len(pages) - len(shown.get(run_no, ()))
            if held:
                out[run_no] = held
        return out


def _batch_json(batch, record_path, sections=None, corrections=None):
    """The batch as the page wants it.

    Names are resolved here rather than in `scans`: the reader deals
    in student ids, because an id is what a paper carries, and only
    the course knows what the id is called. `sections` is the same
    idea from the roster, for sorting the review by class.
    """
    resolve = scans_mod.index_reader(record_path)
    names = record_mod.names_printed(record_path)
    pile = _Pile(batch, record_path)
    held = pile.held_back(resolve)

    counts = {}
    for sheet in batch.sheets:
        counts[sheet.status] = counts.get(sheet.status, 0) + 1

    runs = []
    for run_no in batch.runs:
        row = record_mod.run_by_no(record_path, run_no)
        index = resolve(run_no)
        runs.append({
            "no": run_no,
            "title": (row or {}).get("title", ""),
            "date": (row or {}).get("date", ""),
            "pages": len(index.pages) if index else 0,
            # Papers of this run that came back a second time, having
            # already been graded. The badge on the job card.
            "rescanned": sum(1 for (no, _) in pile.rescanned
                             if no == run_no),
            # Whether anything of this run is being read for the first
            # time. A run with nothing new is being re-scanned, and
            # the view says so instead of listing its absentees.
            "firstTime": run_no in pile.first_time,
            # Absentees the filter held back, so a run short of papers
            # still says so without putting the rows in the table.
            "settled": held.get(run_no, 0),
        })

    sheets = []
    for sheet in batch.sheets:
        entry = sheet.entry
        sheets.append({
            "file": os.path.basename(sheet.source),
            "at": sheet.scan_page,
            "status": sheet.status,
            "run": sheet.run_no,
            "page": sheet.run_page,
            "skill": entry.slug if entry else "",
            "kind": entry.kind if entry else "",
            "sid": entry.sid if entry else "",
            "name": names.get(entry.sid, "") if entry and entry.sid else "",
            "gradable": sheet.gradable,
            "code": sheet.code,
        })

    # `pile.missing`, not `batch.missing`: the absentees worth asking
    # about, which is not every page that failed to arrive. See
    # `_Pile`. The counts the job cards draw come from this list, so
    # filtering here is what stops a re-scan reporting a job's whole
    # class as absent.
    missing = []
    for run_no, pages in pile.missing(resolve).items():
        index = resolve(run_no)
        for page in pages:
            entry = index.get(page)
            missing.append({
                "run": run_no, "page": page,
                "skill": entry.slug, "kind": entry.kind,
                "sid": entry.sid,
                "name": names.get(entry.sid, "") if entry.sid else "",
            })

    # Every page that found no home, with a picture of itself. These
    # are the rows of the second table, and a row about a page nobody
    # could read is no use without the page.
    unplaced = [{
        "file": os.path.basename(sheet.source),
        "at": sheet.scan_page,
        "status": sheet.status,
        "code": sheet.code,
        # The run and page its code claimed, when it had a readable
        # one -- `unknown-run` and `unknown-page` both do, and that is
        # the only clue to what the sheet was meant to be.
        "run": sheet.run_no,
        "page": sheet.run_page,
        "look": _as_jpeg(sheet.cuts["page"]) if "page" in sheet.cuts else "",
    } for sheet in batch.unplaced]

    duplicates = [{"run": run, "page": page,
                   "where": [f"{os.path.basename(s.source)} p{s.scan_page}"
                             for s in group]}
                  for (run, page), group in sorted(batch.duplicates.items())]

    # No wording here. What each outcome is *called* is a view
    # decision and lives in app.js; sending it over HTTP only meant
    # two places to change it.
    return {"counts": counts, "runs": runs, "sheets": sheets,
            "missing": missing, "duplicates": duplicates,
            "unplaced": unplaced,
            "outcomes": OUTCOMES,
            "review": _review_rows(batch, record_path, names,
                                   sections or {},
                                   corrections=corrections,
                                   pile=pile, titles={
                                       r["no"]: r["title"] for r in runs}),
            "gradable": sum(1 for s in batch.sheets if s.gradable)}


#: How much of the copier's own filename to keep in the stored one.
#: Long enough to recognise a stack by, short enough that the whole
#: name stays readable in a folder listing.
SCAN_STEM = 40


def scan_filename(original, blob, when=None):
    """What a stack is stored as: a date, a readable stem, a hash.

        2026-11-07 DOC110326-11032026150756 a3f9c2.pdf

    The hash is six hex of the file's own sha256 and is the part that
    matters: the same bytes always give the same name, so importing
    one stack twice writes one file instead of two, and a name can
    never come to mean a different document. The date and the stem
    are for him -- this folder gets opened by hand.

    Everything outside the safe set becomes a space, because a
    copier's name can carry anything and this becomes a filename.
    """
    import hashlib

    stamp = (when or datetime.date.today()).isoformat()
    stem = os.path.splitext(os.path.basename(original or ""))[0]
    keep = "".join(c if (c.isalnum() or c in " -_.") else " " for c in stem)
    keep = " ".join(keep.split())[:SCAN_STEM].strip()
    short = hashlib.sha256(blob).hexdigest()[:6]
    middle = f" {keep}" if keep else ""
    return f"{stamp}{middle} {short}.pdf"


def api_scan_start(course, body):
    """Take the uploaded PDFs and start reading them.

    The files arrive base64 in the request rather than as paths. A
    path would mean typing one, and the stack arrives in Downloads
    straight off the copier's email -- a file picker is the gesture
    everybody already has. They are written into the course so a read
    can be repeated without asking for them again.
    """
    files = body.get("files") or []
    if not files:
        raise GuiError("no files were chosen.")

    folder = os.path.join(course.path, "scans")
    os.makedirs(folder, exist_ok=True)
    paths = []
    for item in files:
        name = os.path.basename(str(item.get("name") or "scan.pdf"))
        if not name.lower().endswith(".pdf"):
            raise GuiError(f"{name} is not a PDF.")
        try:
            blob = base64.b64decode(item.get("data") or "", validate=True)
        except (ValueError, TypeError):
            raise GuiError(f"{name} did not arrive intact.") from None
        if not blob.startswith(b"%PDF"):
            raise GuiError(f"{name} does not look like a PDF.")
        # The sha is the identity and the filename is decoration --
        # see `scan_filename`. A stack already known comes back under
        # the name it was first given, so importing it again is the
        # same file and the same row rather than a second copy with
        # a different date on it.
        import hashlib
        sha = hashlib.sha256(blob).hexdigest()
        stored = (record_mod.scan_by_sha(course.file("record"), sha)
                  or scan_filename(name, blob))
        path = os.path.join(folder, stored)
        if not os.path.isfile(path):
            with open(path, "wb") as f:
                f.write(blob)
        record_mod.add_scan(course.file("record"), stored, sha, name,
                            _page_count(path), len(blob))
        paths.append(path)

    SCANNING.start(course, paths)
    return {"started": True, "files": [os.path.basename(p) for p in paths]}


def api_scan_list(course, _body):
    """Every stack this course has imported, newest first.

    `onDisk` is asked of the filesystem rather than assumed. The
    folder is the instructor's and outside every repository; he may
    have cleared it, and a row whose file has gone can still say what
    was in it even though it can no longer be opened.
    """
    folder = os.path.join(course.path, "scans")
    out = []
    for row in record_mod.scans(course.file("record")):
        item = dict(row)
        item["onDisk"] = os.path.isfile(os.path.join(folder, row["scan_id"]))
        out.append(item)
    return {"scans": out,
            "folder": folder,
            # What the folder costs, so clearing it is a decision
            # taken against a number rather than a feeling.
            "bytes": sum(r["bytes"] for r in out if r["onDisk"])}


def api_scan_reopen(course, body):
    """Read stored stacks again, with his corrections put back.

    Not an import: these are files already in the course, so nothing
    is uploaded and nothing is renamed. `SCANNING.start` collects
    what he decided about each page last time and the review comes
    back with it already applied -- see `_review_rows`.
    """
    want = [str(s) for s in (body.get("ids") or []) if s]
    if not want:
        raise GuiError("no stacks were chosen.")
    folder = os.path.join(course.path, "scans")
    known = {r["scan_id"] for r in record_mod.scans(course.file("record"))}
    paths = []
    for scan_id in want:
        if scan_id not in known:
            raise GuiError(f"{scan_id} is not a stack this course imported.")
        full = os.path.join(folder, os.path.basename(scan_id))
        if not os.path.isfile(full):
            raise GuiError(
                f"{scan_id} is not in the scans folder any more, so it "
                f"cannot be opened. What was decided about it is still "
                f"in the record.")
        paths.append(full)
    SCANNING.start(course, paths)
    return {"started": True, "files": [os.path.basename(p) for p in paths]}


def api_scan_forget(course, body):
    """Drop a stack from the record, and its file if asked.

    The decisions stay: they are in `attempt`, and this removes the
    working rather than the result. What goes is the stack's row and
    its page attributions -- so a later import of the same PDF is a
    fresh read with nothing remembered.
    """
    scan_id = os.path.basename(str(body.get("id") or ""))
    if not scan_id:
        raise GuiError("no stack was named.")
    delete = bool(body.get("delete"))
    record_mod.forget_scan(course.file("record"), scan_id)
    if delete:
        full = os.path.join(course.path, "scans", scan_id)
        # Resolved and checked before anything is removed. The id
        # comes from the page, and a name from the page is a name
        # that can try to be `../something`.
        folder = os.path.abspath(os.path.join(course.path, "scans"))
        if os.path.abspath(full).startswith(folder + os.sep) \
                and os.path.isfile(full):
            os.remove(full)
    return api_scan_list(course, {})


def _page_count(path):
    """How many pages a PDF has, or 0 if it cannot be opened.

    Zero rather than raising: the listing wants a number and a stack
    that will not open is a thing the read itself reports, loudly and
    with a reason. Failing here would refuse the import instead.
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:                                 # pragma: no cover
        return 0
    try:
        doc = pdfium.PdfDocument(path)
    except Exception:
        return 0
    try:
        return len(doc)
    finally:
        doc.close()


def api_scan_status(_course, _body):
    return SCANNING.status()


def api_scan_clear(_course, _body):
    """Put the pile down and start again.

    Reads accumulate, so there has to be a way to say "that was the
    wrong stack" -- otherwise the only way out is to restart the
    server. The PDFs themselves stay in the course's scans folder;
    this forgets the reading of them, not the files.
    """
    SCANNING.clear()
    return {"cleared": True}


#: What the instructor can say about one paper.
#:
#: His two marks are a tick and a `?`, and a box he has left alone is
#: the third thing. `absent` is not a mark at all -- it is the answer
#: for a paper that was printed and never came back, and it is kept
#: apart from "not passed" because **an attempt is logged when a
#: paper is graded, never when it is printed**. A student who was not
#: there did not attempt anything.
#:
#: Hard-coded for now. 14.4 says states are configurable per course,
#: because other instructors use other marks, and whatever the list
#: becomes only the pass mark will export as a pass.
OUTCOMES = [
    {"id": "passed", "label": "Passed", "mark": "a tick"},
    {"id": "queried", "label": "Query", "mark": "a ? beside the box"},
    {"id": "failed", "label": "Not passed", "mark": "an empty box"},
    {"id": "absent", "label": "Did not sit it", "mark": "no paper"},
]

#: What the reader's call suggests, before the instructor touches it.
#:
#: `beside` -- coloured ink around the box and none in it -- is his
#: `?`, and it is claimed. The reading used to hedge because it
#: measured darkness and could not tell a question mark from the
#: blurred corner of the printed box; measuring colour, it can, and
#: every `?` in the 62 pages of 2026-10-26 came back as one.
#:
#: `heavy` and `nobox` suggest nothing, and mean it: a box scribbled
#: over and a box that could not be found are both "look at this",
#: which is what an empty suggestion puts in front of him.
SUGGESTS = {"ticked": "passed", "empty": "failed", "beside": "queried",
            "heavy": "", "nobox": ""}


def _as_jpeg(image, quality=72):
    """A crop, small enough to put in the page by the hundred.

    JPEG and not PNG: 2KB against 9KB, and the whole run's crops go
    into one response. Lossy is fine because nothing is measured
    from this copy -- the reading was taken from the original, server
    side, before it was ever encoded.
    """
    buf = io.BytesIO()
    image.save(buf, format="JPEG", quality=quality)
    return "data:image/jpeg;base64," + base64.b64encode(
        buf.getvalue()).decode()


#: How much room to leave round the box in the table's own picture,
#: in box-widths, going (left, top, right, bottom).
#:
#: Measured, not chosen. Over the 62 pages of 2026-10-26 the
#: instructor's coloured pen reaches, from the box's own edge:
#:
#:   right   0.60 to 0.89 on the six `?`, worst 0.56 on a check
#:   up      median 0.89 -- the tail of a check overshoots upward
#:   left    median 0.80, but that is student working, not a mark
#:   down    median 0.09
#:
#: So the right has to clear 0.89 or a `?` is cut in half, which is
#: what a flat 0.45 on every side was doing to all six of them. The
#: left stays tight because the skill slug is printed there and it
#: is clutter, not evidence.
#:
#: Widening the right costs almost nothing on screen: the row sizes
#: the picture by its *height*, so an extra half a box-width to the
#: side adds about seven pixels.
SHOT_MARGIN = (0.35, 0.60, 0.95, 0.40)


def _tight(crop, read):
    """The crop again, cut close around the box that was found.

    The reading needs a wide picture -- `find_box` has to have the
    whole rectangle inside it, and the rectangle moves between pages
    -- but a wide picture in a table row is mostly paper. This is the
    same picture cut down to what the row is for.

    Cut here rather than windowed with `object-fit` in the
    stylesheet, because `cover` can only crop a picture, never
    enlarge it: narrowing the window shrank the box instead of
    filling the row with it. And cut from the picture already in
    hand, so it costs no second transform of the scan.

    The whole crop when no box was found. There is nothing to centre
    on, and the reading failed, which is exactly when the instructor
    should see everything there was to look at.
    """
    box = read.get("box")
    if not box:
        return crop
    x0, y0, x1, y1 = box
    unit = x1 - x0
    left, top, right, bottom = SHOT_MARGIN
    return crop.crop((max(0, round(x0 - unit * left)),
                      max(0, round(y0 - unit * top)),
                      min(crop.width, round(x1 + unit * right)),
                      min(crop.height, round(y1 + unit * bottom))))


def _review_rows(batch, record_path, names, sections=None,
                 corrections=None, pile=None, titles=None):
    """One row per paper: what it is, what was read, what to crop.

    Papers that never came back are rows too, with no crop -- but
    only the ones worth asking about. A sheet that missed the scanner
    is still a sheet he may be holding, and he should be able to put
    the result in by hand; a sheet that missed the scanner three
    weeks ago and was marked absent then is not a question, and
    eighty-five of those is how one stray paper used to bury a
    re-scan. `_Pile` draws that line.

    `pile` and `titles` come from `_batch_json`, which has already
    built them. Built here when absent so the function still stands
    on its own, and so a test can call it directly.
    """
    resolve = scans_mod.index_reader(record_path)
    if pile is None:
        pile = _Pile(batch, record_path)
    if not titles:
        titles = {}
        for run_no in pile.run_id:
            row = record_mod.run_by_no(record_path, run_no)
            titles[run_no] = (row or {}).get("title", "")

    # What the record already holds for a paper, so a stack read a
    # second time does not come up offering to save results that went
    # in the first time.
    def recorded(run_no, sid, slug):
        return pile.recorded(run_no, sid, slug)

    # By paper, not by sheet: the same sheet arrives twice often
    # enough that `duplicates` is one of the three questions the
    # batch answers, and a paper is one row however many times the
    # copier saw it.
    papers = {}
    for sheet in batch.placed:
        # `gradable`, not `kind == "student"`. A key is nobody's
        # attempt and stays out. A **spare** is a real paper somebody
        # wrote on -- it is printed with an empty name and an empty id
        # grid for exactly that -- and it used to be dropped here, so
        # a hand-written spare appeared nowhere on the tab at all and
        # could not be recorded. Same for every paper in a run printed
        # without names.
        #
        # `Page.owned` has said which is which since the index format
        # was written, and nothing read it until now.
        if not sheet.entry.gradable:
            continue
        papers.setdefault((sheet.run_no, sheet.run_page), []).append(sheet)

    rows = []
    for (run_no, page), copies in papers.items():
        entry = copies[0].entry
        # Whose paper it is. The footer code says, on a named run. On
        # a paper printed blank it says nothing, and then the student
        # is whoever wrote their id into the grid -- which `read_sid`
        # carries when the writing was clear enough to be sure of.
        #
        # The name goes in the name column, the way it does for a
        # printed code, and the section comes with the student. What
        # the instructor checks it against is the handwriting beside
        # it, which `byId` has the view ring in warning yellow: those
        # are the only rows where the handwriting is the only check
        # there is.
        by_id = next((s.read_sid for s in copies if s.read_sid), "")
        # What he said about this page last time, if it has been
        # through here before. His choice beats both readings: it is
        # the only one of the three that is a judgement rather than a
        # measurement, and a second read of the same sheet knows
        # nothing he did not know when he made it.
        kept = next(
            ((corrections or {}).get(
                (os.path.basename(s.source), s.scan_page))
             for s in copies
             if (corrections or {}).get(
                 (os.path.basename(s.source), s.scan_page))), None)
        sid = (kept[1] if kept else "") or entry.sid or by_id
        # Restored means "he chose this, and this read would not have"
        # -- so it is compared against what the read *did* work out,
        # not against the index alone. On a run printed without names
        # entry.sid is empty for every paper, so comparing to that
        # called every single row restored, including the ones where
        # the id grid agreed with him perfectly.
        restored = bool(kept and kept[1] and kept[1] != (entry.sid or by_id))
        sure_of_id = next((s.read_score for s in copies
                           if s.read_sid == sid), None)
        # Kept with the crop each was taken from: the box comes back
        # in that crop's own pixels, and turning it into the fraction
        # the view needs takes the crop's size.
        looked = [(s.cuts["box"], scans_mod.measure(s.cuts["box"]))
                  for s in copies if "box" in s.cuts]
        reads = [r for _, r in looked]
        calls = {r["call"] for r in reads}
        # One call only when the copies agree. Two scans of one sheet
        # that read differently is precisely the case a suggestion
        # must not paper over: one of them is wrong, and which one is
        # a question for somebody holding the paper.
        agreed = calls.pop() if len(calls) == 1 else ""
        first = reads[0] if reads else {}
        rows.append({
            "id": f"{run_no}-{page}",
            "run": run_no, "page": page,
            "sid": sid, "name": names.get(sid, ""),
            # Sorting by surname wants the surname, and the browser
            # has no splitter on purpose -- see `_sort_names`. The
            # same guess the roster sorts on, so the two tabs put one
            # student in the same place.
            **_split_for_sort(names.get(sid, "")),
            "section": (sections or {}).get(sid, ""),
            "byId": bool(by_id and not entry.sid and not restored),
            # He matched this one by hand before and the stack has
            # been read again. Shown so a restored choice does not
            # look like something the reader worked out -- and so the
            # view can say where the row's student came from.
            "restored": restored,
            "sureOfId": sure_of_id,
            "skill": entry.slug, "scanned": True,
            # Every square taken of this paper. One, nearly always;
            # two when it went through twice, and then both are
            # shown rather than one chosen on his behalf.
            # The wide crop, for looking closely at.
            "crops": [_as_jpeg(crop) for crop, _ in looked],
            # And the same thing cut close around the box, for the
            # row itself. Two pictures rather than one windowed by
            # the stylesheet, because where the box sits in the wide
            # crop is *measured* and differs by sheet: the window
            # was pinned at 34% while N3's boxes sat at 22% and
            # N4's at 50%, which is the cut point he reported.
            "shots": [_as_jpeg(_tight(crop, read))
                      for crop, read in looked],
            # The name as it was printed, so the row can be checked
            # against the paper instead of trusted. One is enough:
            # two scans of a sheet carry the same name, and the
            # thing being checked is the index, not the scanner.
            "nameCrop": next((_as_jpeg(s.cuts["name"]) for s in copies
                              if "name" in s.cuts), ""),
            # The id as printed. On a named run this is the number
            # itself and says nothing new; on a paper printed blank
            # it is a grid somebody wrote in, and the only thing on
            # the sheet that says whose paper it is.
            "idCrop": next((_as_jpeg(s.cuts["id"]) for s in copies
                            if "id" in s.cuts), ""),
            # Where the sheet came from, so the whole page can be
            # fetched when he asks for it. Not the page itself:
            # sixty full renders is a response nobody wants.
            # `page` here is the page in the *scanned file*, which is
            # what `/api/scan/sheet` wants. The browser-side keys have
            # not been renamed yet; see the note in `scans.Sheet`.
            # The stored name, not the path: `/api/scan/sheet`
            # resolves it against this course's own folder.
            "at": [{"file": os.path.basename(s.source),
                    "page": s.scan_page} for s in copies],
            "read": agreed,
            "reads": sorted(calls) or ([agreed] if agreed else []),
            "ink": first.get("inside", 0),
            "beside": first.get("around", 0),
            # How sure the reading is of its own call, 0 to 1. The
            # lowest of several copies: two scans of one sheet that
            # disagree are the least certain thing in the stack,
            # whatever either one measured on its own.
            "sure": min((r.get("sure", 0.0) for r in reads), default=0.0),
            # Nobody's name was printed on this one, so nobody knows
            # whose it is until he says. The row carries the id crop
            # and the name crop for him to read, and `save` refuses
            # it until a student is chosen.
            "unowned": not entry.owned,
            "outcome": SUGGESTS.get(agreed, ""),
            "recorded": recorded(run_no, sid, entry.slug),
            # Which assessment this paper came from. The run number is
            # what the footer code carries and what the record keys
            # on, but it is not what the instructor calls the thing --
            # he calls it by its title and date.
            "assessment": titles.get(run_no, ""),
            # This paper has been graded before and has come back. The
            # ordinary reason is a '?' he has since turned into a
            # tick, and that is a correction rather than a fresh read,
            # so the row says so.
            "rescan": pile.is_rescan(run_no, page),
        })

    # `pile.missing`, not `batch.missing`. See `_Pile`: a run being
    # re-scanned contributes no absentee rows, and a paper already
    # answered for is not asked about again.
    for run_no, pages in pile.missing(resolve).items():
        index = resolve(run_no)
        for page in pages:
            entry = index.get(page)
            rows.append({
                "id": f"{run_no}-{page}",
                "run": run_no, "page": page,
                "assessment": titles.get(run_no, ""),
                "rescan": False,
                "sid": entry.sid, "name": names.get(entry.sid, ""),
            # Sorting by surname wants the surname, and the browser
            # has no splitter on purpose -- see `_sort_names`. The
            # same guess the roster sorts on, so the two tabs put one
            # student in the same place.
            **_split_for_sort(names.get(entry.sid, "")),
                "section": (sections or {}).get(entry.sid, ""),
                "skill": entry.slug, "scanned": False, "crops": [],
                "shots": [], "nameCrop": "", "at": [],
                "read": "", "reads": [], "ink": 0, "beside": 0,
                # Nothing was read, so there is nothing to be sure
                # about. The row is not a guess -- the record knows
                # the paper never came back -- so it shows no dial
                # rather than a dial reading zero.
                "sure": None,
                # Not a question. The record already knows no paper
                # came back; asking him to confirm it is asking him
                # to agree with something nobody doubts. He can
                # still change it -- a sheet can turn up late, or be
                # in his hand right now.
                "outcome": "absent",
                "recorded": recorded(run_no, entry.sid, entry.slug),
            })

    # By student, then skill: a student's papers belong together, and
    # the instructor works down a class list.
    rows.sort(key=lambda r: ((r["name"] or r["sid"]).lower(), r["skill"]))
    return rows


def api_scan_sheet(course, body):
    """One scanned page, whole, rendered on demand.

    Only from this course's own scans folder. The request names a
    file, and a request that names a file is a request that can
    name any file -- so the path is resolved and checked to be
    inside the folder the read came from, rather than trusted.
    """
    import io
    import base64

    # A stored name, never a path. It used to take an absolute one
    # and check it was inside the folder, which was safe and still
    # asked the page to know where files live -- and Progress, which
    # has a name out of the record and no business knowing a path,
    # could not ask at all. `basename` is the whole check now.
    want = os.path.basename(str(body.get("file") or ""))
    page = int(body.get("page") or 0)
    # A thumbnail is for telling one page from another at 54px and
    # seeing whether the working is dense or empty -- not for reading.
    # The drill-in opens one per attempt, so a panel for a student who
    # has sat a skill four times would otherwise cost four full-page
    # renders at once, where a look used to cost one.
    thumb = bool(body.get("thumb"))
    folder = os.path.join(course.path, "scans")
    full = os.path.join(folder, want)
    if not want or not os.path.abspath(full).startswith(
            os.path.abspath(folder) + os.sep):
        raise GuiError("that is not a page from this course's scans.")
    if not os.path.isfile(full):
        raise GuiError(f"{os.path.basename(full)} is not there any more.")

    try:
        import pypdfium2 as pdfium
    except ImportError as exc:                              # pragma: no cover
        raise GuiError(f"cannot open PDFs here: {exc}") from None
    doc = pdfium.PdfDocument(full)
    try:
        if not 1 <= page <= len(doc):
            raise GuiError(f"{os.path.basename(full)} has no page {page}.")
        # Smaller than the read's own render: this is for looking at,
        # and the reading was done long ago at full resolution.
        # `scale` is against 72dpi, so 14/72 puts a letter page at
        # about 120px across -- twice the 54px it is drawn at, which
        # is what a sharp picture on a dense screen needs and no more.
        image = doc[page - 1].render(scale=(14 if thumb else 110) / 72).to_pil()
    finally:
        doc.close()
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="JPEG", quality=55 if thumb else 70)
    return {"file": os.path.basename(full), "page": page,
            "image": "data:image/jpeg;base64,"
                     + base64.b64encode(buf.getvalue()).decode()}


def api_scan_save(course, body):
    """Write the instructor's decisions into the print record.

    Takes `decisions`, a list of `{id, outcome}`. Everything else
    about the paper is read from `SCANNING.result`, the server's own
    copy of what it scanned -- see this module's note on why the
    browser is not asked for it.

    A row with no outcome is not a decision and is skipped. That is
    not the same as `absent`, which is a decision: "no paper came
    and I am recording that".
    """
    result = SCANNING.result
    if not result:
        # The read lives in memory for the life of the process, so a
        # restart between reading and saving loses it. Said plainly,
        # because the alternative -- taking the page's word for who
        # each paper belonged to -- is how a decision ends up on the
        # wrong student.
        raise GuiError(
            "there is no stack in hand to save. Read the PDFs again, "
            "then save; the decisions on screen were not kept.")

    want = {}
    for item in (body.get("decisions") or []):
        outcome = str(item.get("outcome") or "")
        if not outcome:
            continue
        if outcome not in record_mod.OUTCOMES:
            # Checked here as well as in `save_attempts`, and not as
            # a copy of it: a decision whose id matches no row in the
            # read is dropped below and never reaches the record, so
            # without this a stale page could send nonsense and be
            # told everything was fine.
            raise GuiError(
                f"{outcome!r} is not an outcome. It is one of "
                f"{', '.join(record_mod.OUTCOMES)}.")
        want[str(item.get("id"))] = {
            "outcome": outcome,
            "sid": str(item.get("sid") or ""),
            "skill": str(item.get("skill") or ""),
            "run": item.get("run"),
            "file": str(item.get("file") or ""),
            "page": item.get("page") or 0,
            "byHand": bool(item.get("byHand")),
        }
    if not want:
        raise GuiError("nothing was decided, so there is nothing to save.")

    path = course.file("record")

    # What the course actually handed out. A decision may say whose
    # paper something is -- that is what a re-match is -- but only
    # where this says the student was given that skill in that run.
    # The browser offers the same list; this is the half that cannot
    # be got round by a stale page.
    printed = record_mod.printed_pairs(path)

    def owner(said, row):
        """The student to record against, or a refusal.

        `row` is the server's own idea of the paper. When the page
        agrees, nothing is being claimed and the server's own answer
        stands. When it differs, the pair has to be one that was
        printed.
        """
        sid, slug = said["sid"], said["skill"]
        if not sid or (sid == row.get("sid") and slug == row.get("skill")):
            return row.get("sid"), row.get("skill")
        run = record_mod.run_by_no(path, said["run"] or row.get("run"))
        if run is None or (run["run_id"], sid, slug) not in printed:
            raise GuiError(
                f"this course did not print {slug or 'that skill'} for "
                f"that student in that job, so a paper cannot be "
                f"matched to them. Nothing was saved.")
        return sid, slug

    rows, no_run = [], set()
    seen_ids = set()
    for row in result.get("review", []):
        said = want.get(row["id"])
        if not said:
            continue
        seen_ids.add(row["id"])
        outcome = said["outcome"]
        row = dict(row)
        row["sid"], row["skill"] = owner(said, row)
        if not row["sid"]:
            # A paper printed without a name, still unmatched. There
            # is nobody to record it against, and a row with no
            # student would be a mark belonging to the whole class.
            raise GuiError(
                f"a {row['skill']} paper has no student yet. Match it "
                "to somebody, or set it aside. Nothing was saved.")
        run = record_mod.run_by_no(path, row["run"])
        if run is None:
            # The code named a run this course does not have. The
            # read already reports it; here it means the decision
            # has nowhere to go, so it is named rather than dropped.
            no_run.add(row["run"])
            continue
        rows.append({
            "run_id": run["run_id"], "sid": row["sid"],
            "slug": row["skill"], "outcome": outcome,
            # A paper that never came back has no page and no
            # reading. Stored as NULL rather than 0, which would
            # read as "page zero, no ink".
            "page": row["page"] if row["scanned"] else None,
            "reading": row["read"] if row["scanned"] else "",
            "ink": row["ink"] if row["scanned"] else None,
            "beside": row["beside"] if row["scanned"] else None,
        })

    # A page matched by hand is not in the read's review list -- the
    # reader never placed it, which is why it was in the other table --
    # so nothing above found it and it used to be dropped in silence.
    # It is found by where it is instead: the file it came out of and
    # the page it was in, which the server knows from its own sheets.
    for key, said in want.items():
        if key in seen_ids or not said["byHand"]:
            continue
        sheet = next((s for s in SCANNING.sheets
                      if os.path.basename(s.source) == said["file"]
                      and s.scan_page == said["page"]), None)
        if sheet is None:
            raise GuiError(
                f"{said['file']} page {said['page']} is not in the stack "
                "that was read. Nothing was saved.")
        if sheet.placed:
            # It found a home by itself, so it has a row above and
            # should have been matched by id. Something is out of step.
            raise GuiError(
                f"{said['file']} page {said['page']} was placed by its "
                "own code, so it cannot also be matched by hand. "
                "Nothing was saved.")
        run = record_mod.run_by_no(path, said["run"])
        if run is None or (run["run_id"], said["sid"],
                           said["skill"]) not in printed:
            raise GuiError(
                f"this course did not print {said['skill'] or 'that skill'} "
                "for that student in that job, so a page cannot be matched "
                "to them. Nothing was saved.")
        rows.append({
            "run_id": run["run_id"], "sid": said["sid"],
            "slug": said["skill"], "outcome": said["outcome"],
            # No page in the job and no reading: the reader never
            # placed this sheet, so there is no box it measured.
            "page": None, "reading": "", "ink": None, "beside": None,
        })

    try:
        written, unknown = record_mod.save_attempts(path, rows)
    except record_mod.RecordError as exc:
        raise GuiError(str(exc)) from None

    _note_pages(course, result, rows)

    return {
        "saved": written,
        "skipped": len(result.get("review", [])) - written,
        # Reported, not hidden: a paper the index names and the
        # record never printed means the two disagree, and that is
        # worth a line on screen even though the decision was kept.
        "unprinted": [{"sid": sid, "skill": slug}
                      for _, sid, slug in unknown],
        "noRun": sorted(no_run),
        "runs": sorted({r["run_id"] for r in rows}),
    }


def _note_pages(course, result, rows):
    """Write down what each page of each stack turned out to be.

    One row per scanned page, so a stack can be brought back as he
    left it. The attribution comes from the decisions just saved,
    matched to the page by (run, page) -- which is how a re-matched
    paper gets recorded against the student he chose rather than the
    one the index named.

    A page that was never placed and never matched still gets a row,
    with no student on it. That is not nothing: it says the page was
    seen and dismissed, so a re-read does not present it as new.
    """
    by_paper = {}
    for row in rows:
        if row.get("page") is not None:
            by_paper[(row["run_id"], row["page"])] = (row["sid"], row["slug"])

    # Which run each run number belongs to, so a sheet's `run_no` can
    # be turned into the id the decisions are keyed by.
    path = course.file("record")
    run_ids = {}
    for sheet in SCANNING.sheets:
        if sheet.run_no is not None and sheet.run_no not in run_ids:
            found = record_mod.run_by_no(path, sheet.run_no)
            run_ids[sheet.run_no] = (found or {}).get("run_id", "")

    per_scan = {}
    for sheet in SCANNING.sheets:
        scan_id = os.path.basename(sheet.source)
        run_id = run_ids.get(sheet.run_no, "")
        sid, slug = by_paper.get((run_id, sheet.run_page), ("", ""))
        per_scan.setdefault(scan_id, []).append(
            (sheet.scan_page, run_id if sid else "", sid, slug))

    for scan_id, pages in per_scan.items():
        record_mod.note_scan_pages(path, scan_id, pages)


def api_progress(course, _body):
    """The grid: students down, every skill in the bank across."""
    path = course.file("record")
    bank = course.bank()

    slugs, titles = [], {}
    if bank is not None:
        slugs = list(bank.slugs())
        for slug in slugs:
            try:
                titles[slug] = bank.skill_title(slug)
            except BankError:
                titles[slug] = slug

    try:
        needed = course_mod.thresholds(course.name)
    except course_mod.CourseError as exc:
        raise GuiError(str(exc)) from None

    cells = {}
    for row in record_mod.progress(path):
        cells.setdefault(row["sid"], {})[row["slug"]] = {
            "attempts": row["attempts"],
            "passes": row["passes"],
            "queries": row["queries"],
            "absents": row["absents"],
            "last": row["last"],
            # What happened the last time they actually sat it. The
            # glyph turns on this and not on `last`, because an
            # absence is invisible to the grid.
            "lastSat": row["last_sat"],
            "lastDate": row["last_date"],
            "passedIn": row["passed_in"],
        }

    # A skill somebody has attempted that the bank no longer lists
    # still has to appear, or the work disappears from the grid
    # without anything saying it did. Appended, so the bank's own
    # order survives.
    for by_skill in cells.values():
        for slug in by_skill:
            if slug not in titles:
                slugs.append(slug)
                titles[slug] = slug

    # Live students only, in roster order: a grid is read down a
    # class list, and somebody who has left is not on it.
    people = course.roster()
    # `_split_for_sort` as well, the same call `_review_rows` makes --
    # not a second splitter. Sorting by surname needs the surname, and
    # the browser has no splitter on purpose; without this the grid
    # could not offer the Roster's name order at all, and the two tabs
    # could show one student two ways at once.
    students = [{"sid": roster_mod.key_of(s), "name": s.display,
                 "section": s.section, **_split_for_sort(s.display)}
                for s in people.live()]

    return {
        "hasBank": bank is not None,
        "students": students,
        "skills": [{"slug": s, "title": titles.get(s, s),
                    "threshold": needed.get(s,
                                            course_mod.DEFAULT_THRESHOLD)}
                   for s in slugs],
        "cells": cells,
        # Every graded run, newest first. The view takes as many as
        # the reader asked for -- how many count as "just come back"
        # is their number, kept in their browser. Worked out from the
        # `graded` flag rather than from dates: see
        # `record.graded_runs`.
        #
        # Called `recent` until 2026-11-07, which stopped being true
        # the day the count moved into the browser and the server
        # began sending all of them.
        "graded": record_mod.graded_runs(path),
    }


def api_progress_cell(course, body):
    """One student's history of one skill, for the drill-in."""
    sid = str(body.get("sid") or "")
    slug = str(body.get("slug") or "")
    if not sid or not slug:
        raise GuiError("that request did not say which cell.")
    rows = record_mod.history(course.file("record"), sid, slug)
    return {"sid": sid, "slug": slug, "papers": [
        {"runId": r["run_id"], "title": r["title"], "date": r["date"],
         "runNo": r["run_no"], "delisted": bool(r["delisted"]),
         "rebuilt": bool(r["rebuilt"]),
         "seed": r["seed"], "version": r["version"],
         "outcome": r["outcome"] or "", "decided": r["decided"] or "",
         # Which page of the printed job. Not the page of the
         # scanned PDF -- see `scans.Sheet`.
         "runPage": r["run_page"], "reading": r["reading"] or "",
         # Where the picture is, when the stack it came out of is
         # still in the course. Absent for a paper recorded before
         # scans were kept, and for one whose stack has been
         # forgotten -- the decision stands either way.
         "scan": r["scan_id"] or "", "scanPage": r["scan_page"]}
        for r in rows]}


def api_progress_set(course, body):
    """Change or record one result by hand.

    The same table Scans writes, through the same function, so a
    decision typed here and a decision read off a stack are the same
    kind of thing and neither can produce a row the other could not.

    No `page` and no reading: this is him saying what happened, not
    a measurement of anything, and inventing a reading would put a
    number in the audit column that nothing ever measured.
    """
    run_id = str(body.get("runId") or "")
    sid = str(body.get("sid") or "")
    slug = str(body.get("slug") or "")
    outcome = str(body.get("outcome") or "")
    if not (run_id and sid and slug):
        raise GuiError("that request did not say which paper.")
    # No outcome check here. `save_attempts` owns what an outcome may
    # be -- it is the thing that writes it -- and refuses with the
    # same sentence, so a second copy of the list here was a second
    # place for it to go stale and nothing more. `api_scan_save` does
    # check, and that one is not a copy: see the note there.

    path = course.file("record")
    # Keep whatever the scanner measured, when there was a scan. He
    # is overruling the *call*, not claiming the ink was different,
    # and throwing the measurement away would lose the only evidence
    # of why the reader said what it did.
    was = next((r for r in record_mod.history(path, sid, slug)
                if r["run_id"] == run_id), None)
    if was is None:
        raise GuiError(
            f"{sid} was never printed {slug} in that run, so there is "
            f"nothing to record against it.")
    try:
        record_mod.save_attempts(path, [{
            "run_id": run_id, "sid": sid, "slug": slug,
            "outcome": outcome, "page": was["run_page"],
            "reading": was["reading"] or "", "ink": None,
            "beside": None}])
    except record_mod.RecordError as exc:
        raise GuiError(str(exc)) from None
    return api_progress_cell(course, {"sid": sid, "slug": slug})


# ------------------------------------------- getting it into the LMS --
#
# Progress *is* the gradebook; what this is for is getting what it
# holds into somebody else's. So it lives under Progress rather than in
# a tab of its own, and it is called "Export to your LMS" -- which is
# the instructor's own phrase, and worth keeping straight: he exports
# from the LMS, printit fills the file in, and he imports it back.
# Nothing here uploads anything.
#
# **The uploaded gradebooks are held in memory and never written to
# disk.** Every other file this app receives gets stored -- a scan goes
# into `scans/`, a roster into `roster.toml` -- and a gradebook export
# is the one file that should not, because it carries every student's
# name, id and marks and the tool has no reason to keep it past the
# minute it is being read. The filled copies go back to the browser as
# a download. So this adds no new place for student data to accumulate,
# and `vault mask-course` needs no new exclusion.


class _Carried:
    """The gradebook files of one visit, in memory.

    Module-level for the same reason the scan reader is: mapping,
    planning and writing are three requests about one pile of files,
    and asking for them again between steps would be asking him to
    find them three times.

    One course at a time. A second course's upload replaces the first,
    rather than the two being mixed into one plan -- which is the only
    failure worth guarding here, because the plan's whole job is to
    decide that a student appears in exactly one file.
    """

    def __init__(self):
        self.course = ""
        #: name -> the file's bytes, exactly as uploaded.
        self.files = {}

    def put(self, course, name, blob):
        if course != self.course:
            self.clear()
            self.course = course
        self.files[name] = blob

    def clear(self):
        self.course = ""
        self.files = {}

    def __bool__(self):
        return bool(self.files)


CARRIED = _Carried()


def _gradebook_profile(course):
    """The saved profile, or None. Never raises on a missing file."""
    path = gradebook_mod.path_for(course.name)
    if not os.path.isfile(path):
        return None
    try:
        return gradebook_mod.load(path)
    except gradebook_mod.GradebookError as exc:
        raise GuiError(str(exc)) from None


def _profile_json(profile):
    if profile is None:
        return None
    return {
        "name": profile.name,
        "studentColumn": profile.student_column,
        "matches": profile.student_matches,
        "passed": profile.passed,
        "notPassed": profile.not_passed,
        # The codepoints as well as the characters. On his export a pass
        # is a trophy followed *immediately* by `Pass`, and whether
        # there is a space after the emoji is invisible in the glyphs
        # and obvious here. The export writes these bytes exactly.
        "passedPoints": " ".join("U+%04X" % ord(c) for c in profile.passed),
        "notPassedPoints": " ".join("U+%04X" % ord(c)
                                    for c in profile.not_passed),
        "blankMeans": profile.blank_means,
        "pairs": dict(profile.pairs),
        "ignoreRows": list(profile.ignore_rows),
        "ignoreColumns": list(profile.ignore_columns),
    }


def api_gradebook(course, _body):
    """What is known before any file is in hand.

    The profile, the thresholds it will apply, and the bank's slugs.
    The thresholds are shown here although they are *set* in Settings:
    they belong to the course whatever you are doing, and the one bug
    this whole feature had was the export not reading them. A number
    that decides what gets written should be visible where the writing
    happens.
    """
    profile = _gradebook_profile(course)
    try:
        slugs = _bank_slugs_for(course)
    except GuiError:
        slugs = []
    return {
        "profile": _profile_json(profile),
        "profilePath": gradebook_mod.path_for(course.name),
        "slugs": slugs,
        "thresholds": course_mod.thresholds(course.name),
        "matchChoices": list(gradebook_mod.ID_FIELDS),
        "blankChoices": list(gradebook_mod.BLANK_MEANINGS),
        "carrying": sorted(CARRIED.files) if CARRIED.course == course.name
        else [],
    }


def api_gradebook_read(course, body):
    """Take the uploaded gradebook files and say what they look like.

    Reads: the header row, every skill column it can find and **how**
    it found it, the mark strings as they appear in the file, and what
    a blank cell seems to mean. Saves nothing: this is the step where
    he checks that the tool has understood his file.
    """
    files = body.get("files") or []
    if not files:
        raise GuiError("no files were chosen.")

    for item in files:
        name = os.path.basename(str(item.get("name") or "export.csv"))
        if not name.lower().endswith((".csv", ".txt")):
            raise GuiError(f"{name} is not a CSV.")
        try:
            blob = base64.b64decode(item.get("data") or "", validate=True)
        except (ValueError, TypeError):
            raise GuiError(f"{name} did not arrive intact.") from None
        if b"\0" in blob[:4096]:
            raise GuiError(f"{name} looks like a binary file, not a CSV.")
        CARRIED.put(course.name, name, blob)

    return api_gradebook_look(course, body)


def api_gradebook_look(course, body):
    """The same report, from the files already carried.

    Split from `read` so re-reading after a profile change costs
    nothing and does not ask for the files again.
    """
    if not CARRIED or CARRIED.course != course.name:
        raise GuiError("no gradebook file is in hand. Drop one first.")

    header_row = int(body.get("headerRow") or 1)
    profile = _gradebook_profile(course)
    slugs = _bank_slugs_for(course)
    out = []

    for name in sorted(CARRIED.files):
        rows = _rows_of(CARRIED.files[name])
        if not rows:
            raise GuiError(f"{name} is empty.")
        try:
            index = mask_mod.find_header(rows, header_row)
        except mask_mod.MaskError as exc:
            raise GuiError(f"{name}: {exc}") from None
        head = rows[index]
        body_rows = [r for r in rows[index + 1:]
                     if any(c.strip() for c in r)]

        found = gradebook_mod.match(
            head, slugs, pairs=(profile.pairs if profile else None))
        columns = sorted(found.found.values())
        guessed = gradebook_mod.guess_marks(body_rows, columns)
        passed = (profile.passed if profile and profile.passed
                  else guessed[0])
        meaning, evidence = gradebook_mod.blank_evidence(
            body_rows, head, columns, passed)
        sheet = gradebook_mod.sheet_from(name, rows, header_line=index + 1)

        out.append({
            "name": name,
            "headerRow": index + 1,
            "columns": len(head),
            "rows": len(body_rows),
            "section": sheet.section,
            "headers": list(head),
            # slug -> {column, header, how}. One row per skill in the
            # view, because "which column is N3" is the question he is
            # actually checking.
            "matched": {
                slug: {"column": column + 1, "header": head[column],
                       "how": found.how.get(slug, "")}
                for slug, column in sorted(found.found.items())},
            "missing": list(found.missing),
            "ambiguous": {s: [c + 1 for c in cs]
                          for s, cs in found.ambiguous.items()},
            "spare": [{"column": c + 1, "header": head[c]}
                      for c in found.spare],
            "guessedPassed": guessed[0],
            "guessedNotPassed": guessed[1],
            "otherValues": list(guessed[2]),
            "blankMeans": meaning,
            "blankEvidence": evidence,
        })
    return {"files": out, "profile": _profile_json(_gradebook_profile(course)),
            "slugs": slugs}


def api_gradebook_save(course, body):
    """Write the profile. The file on disk stays the source of truth.

    This page is a view and an editor of `gradebook.toml`, never a
    second place the answers live: the module's own note says a
    decision the tool made about a column should be greppable and
    diffable, and a web page that holds it is a page you have to open
    to find out what the tool believes.
    """
    profile = _gradebook_profile(course) or gradebook_mod.Profile()
    fields = {
        "name": ("name", str),
        "studentColumn": ("student_column", str),
        "matches": ("student_matches", str),
        "passed": ("passed", str),
        "notPassed": ("not_passed", str),
        "blankMeans": ("blank_means", str),
    }
    changes = {}
    for key, (attribute, cast) in fields.items():
        if key in body:
            changes[attribute] = cast(body[key])
    for key, attribute in (("pairs", "pairs"),
                           ("ignoreRows", "ignore_rows"),
                           ("ignoreColumns", "ignore_columns")):
        if key in body:
            changes[attribute] = (dict(body[key]) if key == "pairs"
                                  else list(body[key]))
    profile = dataclasses.replace(profile, **changes)

    # Checked against the real headers when a file is in hand, because
    # a profile naming a column the file does not have is the failure
    # that otherwise shows up as "nothing exported" with no reason.
    headers = None
    if CARRIED and CARRIED.course == course.name:
        rows = _rows_of(CARRIED.files[sorted(CARRIED.files)[0]])
        try:
            index = mask_mod.find_header(rows, int(body.get("headerRow") or 1))
            headers = rows[index]
        except mask_mod.MaskError:
            headers = None
    try:
        profile.validate(headers)
    except gradebook_mod.GradebookError as exc:
        raise GuiError(str(exc)) from None

    path = gradebook_mod.path_for(course.name)
    gradebook_mod.save(path, profile)
    return {"saved": path, "profile": _profile_json(profile)}


def _gradebook_plan(course, body):
    """`(sheets, changes, report, profile)` for the carried files."""
    if not CARRIED or CARRIED.course != course.name:
        raise GuiError("no gradebook file is in hand. Drop one first.")
    profile = _gradebook_profile(course)
    if profile is None:
        raise GuiError(
            "this course has no gradebook profile yet. Check the "
            "columns below and save it first.")
    try:
        profile.validate()
    except gradebook_mod.GradebookError as exc:
        raise GuiError(str(exc)) from None

    header_row = int(body.get("headerRow") or 1)
    slugs = _bank_slugs_for(course)
    record_path = course.file("record")
    people = roster_mod.load(course.file("roster"))
    progress = record_mod.progress(record_path)
    if not progress:
        raise GuiError(
            "nothing has been graded in this course yet, so there is no "
            "result to export. Read a stack in on the Scans tab first.")

    wanted = [s for s in (body.get("notYet") or []) if s in slugs]
    sheets = []
    for name in sorted(CARRIED.files):
        rows = _rows_of(CARRIED.files[name])
        try:
            index = mask_mod.find_header(rows, header_row)
        except mask_mod.MaskError as exc:
            raise GuiError(f"{name}: {exc}") from None
        sheets.append(gradebook_mod.sheet_from(name, rows,
                                               header_line=index + 1))

    changes, report = gradebook_mod.plan_export(
        sheets, profile, people, progress, slugs, not_yet=wanted,
        thresholds=course_mod.thresholds(course.name))
    return sheets, changes, report, profile


def api_gradebook_plan(course, body):
    """What would be written. Writes nothing.

    The default, and the only safe one for something that changes
    grades: he sees the plan, then asks for the files.
    """
    sheets, changes, report, _ = _gradebook_plan(course, body)

    per_file = []
    for sheet in sheets:
        mine = report.for_sheet(sheet.name)
        by_skill = {}
        for change in mine:
            row = by_skill.setdefault(change.slug, {"cells": 0, "blank": 0,
                                                    "over": 0})
            row["cells"] += 1
            if change.was.strip():
                row["over"] += 1
            else:
                row["blank"] += 1
        per_file.append({
            "name": sheet.name, "section": sheet.section,
            "cells": len(mine),
            "bySkill": [{"slug": slug, **counts}
                        for slug, counts in sorted(by_skill.items())],
        })

    return {
        "cells": len(report.changes),
        "alreadyRight": report.already_right,
        "notWritten": report.not_written,
        "rowsMatched": report.rows_matched,
        "files": per_file,
        "keptPasses": len(report.kept_passes()),
        # Rows and columns, never a student. This report is printed and
        # shown, and a report that can carry a name is one that cannot
        # be shown to anybody.
        "rowsIgnored": list(report.rows_ignored),
        "rowsUnmatched": list(report.rows_unmatched),
        "studentsUnmatched": len(report.students_unmatched),
        "skillsUnmatched": list(report.skills_unmatched),
        "short": dict(report.short),
        "notes": list(report.notes),
        "refused": list(report.refused),
        "thresholds": course_mod.thresholds(course.name),
    }


def api_gradebook_write(course, body):
    """Splice the files and hand them back for download.

    Not written to disk here either. The browser saves them wherever
    he keeps downloads, which is where the originals came from.
    """
    sheets, changes, report, _ = _gradebook_plan(course, body)
    if report.refused:
        raise GuiError("; ".join(report.refused))
    if not changes:
        raise GuiError("there is nothing to write.")

    out = []
    for sheet in sheets:
        if not report.for_sheet(sheet.name):
            continue
        # `splice` reads the file by path, and the file only exists in
        # memory -- so it is handed a temporary copy, written and
        # removed inside this call. The point of not storing the
        # upload is that it does not outlive the request; a scratch
        # file that does not either keeps that true.
        import tempfile
        folder = tempfile.mkdtemp(prefix="printit-gb-")
        path = os.path.join(folder, sheet.name)
        try:
            with open(path, "wb") as handle:
                handle.write(CARRIED.files[sheet.name])
            try:
                data = gradebook_mod.splice(
                    path, changes, sheet.name,
                    header_line=sheet.header_line)
            except gradebook_mod.GradebookError as exc:
                raise GuiError(str(exc)) from None
        finally:
            shutil.rmtree(folder, ignore_errors=True)

        stem, extension = os.path.splitext(sheet.name)
        out.append({
            "name": f"{stem}_UPDATED{extension}",
            "data": base64.b64encode(data).decode("ascii"),
            "cells": len(report.for_sheet(sheet.name)),
        })
    return {"files": out, "cells": len(report.changes)}


def api_gradebook_clear(course, _body):
    """Forget the carried files."""
    CARRIED.clear()
    return {"carrying": []}


def _rows_of(blob):
    """A carried file's bytes as rows, the way `mask.read_rows` reads a
    path -- same encoding handling, same BOM handling, no temporary
    file."""
    import csv
    import io
    text = blob.decode("utf-8-sig")
    return [row for row in csv.reader(io.StringIO(text, newline=""))]


def _bank_slugs_for(course):
    """The bank's slugs, or a GuiError saying why not.

    The same path the CLI's `_bank_slugs` takes, and the same reason
    for the message: without a bank there is no list of skills to
    match the gradebook's columns against, and "nothing matched" would
    be a confusing way to learn that.
    """
    bank = course_mod.bank_for(course.name)
    if bank is None:
        raise GuiError(
            "this course is not pointed at a bank, so there is no list "
            "of skills to match the gradebook's columns against. Set "
            "one in Settings, or in the course's `course.toml`.")
    try:
        return list(bank.slugs())
    except BankError as exc:
        raise GuiError(f"cannot read this course's bank: {exc}") from None


ROUTES = {
    "/api/course": api_course,
    "/api/progress": api_progress,
    "/api/progress/cell": api_progress_cell,
    "/api/progress/set": api_progress_set,
    # Under Progress, because Progress is the gradebook and this is
    # getting what it holds into somebody else's.
    "/api/gradebook": api_gradebook,
    "/api/gradebook/read": api_gradebook_read,
    "/api/gradebook/look": api_gradebook_look,
    "/api/gradebook/save": api_gradebook_save,
    "/api/gradebook/plan": api_gradebook_plan,
    "/api/gradebook/write": api_gradebook_write,
    "/api/gradebook/clear": api_gradebook_clear,
    "/api/scan/start": api_scan_start,
    "/api/scan/list": api_scan_list,
    "/api/scan/reopen": api_scan_reopen,
    "/api/scan/forget": api_scan_forget,
    "/api/scan/status": api_scan_status,
    "/api/scan/clear": api_scan_clear,
    "/api/scan/save": api_scan_save,
    "/api/scan/sheet": api_scan_sheet,
    "/api/roster": api_roster,
    "/api/roster/save": api_roster_save,
    "/api/roster/drop": api_roster_drop,
    "/api/google": api_google,
    "/api/google/login": api_google_login,
    "/api/course/identity": api_course_identity,
    "/api/setup": api_setup,
    "/api/setup/create": api_setup_create,
    "/api/setup/inspect": api_setup_inspect,
    "/api/setup/attach": api_setup_attach,
    "/api/setup/authorize": api_setup_authorize,
    "/api/setup/finish": api_setup_finish,
    "/api/seating": api_seating,
    "/api/seating/save": api_seating_save,
    "/api/seating/versions": api_seating_versions,
    "/api/seating/start": api_seating_start,
    "/api/seating/shuffle": api_seating_shuffle,
    "/api/seating/fill": api_seating_fill,
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
    "/api/runs": api_runs,
    "/api/run": api_run,
    "/api/run/flag": api_run_flag,
    "/api/run/discard": api_run_discard,
    "/api/run/replay": api_run_replay,
    "/api/run/reuse": api_run_reuse,
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
