"""Emailing each student who sat an assessment their results and pages.

DESIGN 21. One email per student, from the Google account that owns the
course's form script, through that script's `mail` operation -- the
only Google identity printit has. Four parts, in the order a send uses
them:

    template = load_template()                  # shared by every course
    letters = plan(record, run_id, roster, ...) # who gets what, and why not
    subject, body = compose(letter, template, ...)
    report = send(...)                          # one request per student

**Nothing here decides a mark.** The outcome of each paper comes from
`attempt`, written by Scans; the pages from `scan_page`, which is what
he confirmed there. This module only reports them, and refuses rather
than guesses wherever the two do not line up.
"""

import base64
import dataclasses
import io
import os
import re
import tomllib

from . import availability as availability_mod
from . import classlist as classlist_mod
from . import fileio
from . import form as form_mod
from . import gradebook as gradebook_mod
from . import record as record_mod


class MailError(Exception):
    """Something stops the send. The message is for a human."""


# ----------------------------------------------------------- template --

#: In the home, beside `name-guard.toml`, not in a course: one template
#: for every course, his choice (2026-11-19). It holds no student data.
TEMPLATE_FILE = "email.toml"

#: What a template may use. Listed behind the `?` on Settings, and
#: never inside the default template itself: a template that documents
#: its own syntax has the documentation parsed as syntax.
FIELDS = {
    "first": "the student's first name, as the registrar has it",
    "last": "the student's last name, as the registrar has it",
    "pref_first": "the first name they go by, else the registrar's",
    "pref_last": "the last name they go by, else the registrar's",
    "name": "the name printed on their paper, first name first",
    "assessment": "the assessment's title",
    "date": "the day it was sat, as in Friday, 11/14",
    "results": "one line per skill: the skill, then the mark",
    "instructor": "the instructor, from this course's Settings",
}

DEFAULT_SUBJECT = "{{assessment}}: your results"

DEFAULT_BODY = """Hi {{pref_first}},

Here is how you did on {{assessment}} ({{date}}):

{{results}}

Your marked pages are attached.

{{instructor}}
"""

_HEADER = """\
# The email printit sends each student with their marked pages.
#
# Shared by every course. Edit it on any course's Settings tab, or here;
# the fields it can use are listed behind the ? on that card.
"""


@dataclasses.dataclass(frozen=True)
class Template:
    subject: str
    body: str
    #: False when no file exists and these are printit's defaults.
    saved: bool = False


def template_path(root=None):
    return os.path.join(root or record_mod.home_root(), TEMPLATE_FILE)


def load_template(root=None):
    """The template, or printit's default when there is no file yet.

    A file missing one of the two keys uses the default for that key --
    absence is the old behaviour, and before this file existed the
    default was all there was.
    """
    path = template_path(root)
    if not os.path.isfile(path):
        return Template(DEFAULT_SUBJECT, DEFAULT_BODY, saved=False)
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise MailError(f"{path} could not be read: {exc}") from None
    return Template(str(raw.get("subject", DEFAULT_SUBJECT)),
                    str(raw.get("body", DEFAULT_BODY)), saved=True)


def check(text):
    """Raise MailError naming the first thing the template cannot fill.

    An unknown name raises rather than becoming an empty string, which
    is the point -- a typo must not send forty emails with a hole in
    them.
    """
    render(text, {name: "" for name in FIELDS})


#: A tag: `{{name}}` or `{{{name}}}`, spaces allowed inside.
_TAG = re.compile(r"\{\{(\{?)([^{}]*?)(\}?)\}\}")


def render(text, values):
    """Mustache's field tags, and nothing else, with nothing escaped.

    The subset of Mustache a letter needs: `{{name}}` (or `{{{name}}}`,
    which means the same here). Not pystache, which in strict mode
    still renders an unclosed `{{#section}}` as if it were text --
    a quiet hole of exactly the kind this has to refuse. Sections,
    partials and comments are refused by name, and a `{{` that does not
    close is refused too. Plain text, so nothing is HTML-escaped: a
    student would otherwise get `&amp;`.
    """
    def literal(piece):
        if "{{" in piece or "}}" in piece:
            raise MailError("the template has a {{ or }} that is not part "
                            "of a field.")
        return piece

    out, at = [], 0
    for tag in _TAG.finditer(text):
        out.append(literal(text[at:tag.start()]))
        name = tag.group(2).strip()
        if bool(tag.group(1)) != bool(tag.group(3)):
            raise MailError(f"the template has a tag with mismatched "
                            f"braces: {tag.group(0)}")
        if name[:1] in "#^/>!&=":
            raise MailError(
                f"the template uses {tag.group(0)}; an email template "
                f"takes fields only, like {{{{first}}}}.")
        if name not in FIELDS:
            raise MailError(
                f"the template uses {{{{{name}}}}}, which is not a field. "
                f"The fields are: {', '.join(FIELDS)}.")
        out.append(str(values.get(name, "")))
        at = tag.end()
    out.append(literal(text[at:]))
    return "".join(out)


def save_template(subject, body, root=None):
    """Write the template, keeping everything else in the file.

    Edited by line, like every file a person writes (rule 6): the two
    values are replaced where they stand and any comment he added stays.
    The result is read back and compared before it is written, so a file
    this cannot edit safely is left as it was and said so.
    """
    check(subject)
    check(body)
    if "\n" in subject.strip():
        raise MailError("the subject is one line.")
    subject = subject.strip()
    path = template_path(root)
    if os.path.isfile(path):
        with open(path, encoding="utf-8", newline="") as f:
            text = f.read()
    else:
        text = _HEADER
    text = _set(text, "subject", fileio.toml_string(subject))
    text = _set(text, "body", fileio.toml_string(body, multiline=True))
    try:
        back = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise MailError(f"{path} could not be rewritten safely ({exc}); "
                        f"it is unchanged.") from None
    if back.get("subject") != subject or back.get("body") != body:
        raise MailError(f"{path} could not be rewritten safely; it is "
                        f"unchanged. Edit it by hand.")
    fileio.atomic_write(path, text, newline="")
    return path


_ASSIGN = r"^{key}[ \t]*=[ \t]*"


def _set(text, key, value):
    """`text` with `key`'s value replaced by `value`, or appended."""
    found = re.search(_ASSIGN.format(key=key), text, re.M)
    if found is None:
        sep = "" if text.endswith("\n") or not text else "\n"
        return f"{text}{sep}\n{key} = {value}\n"
    start = found.end()
    end = _value_end(text, start)
    if end is None:
        raise MailError(
            f"{TEMPLATE_FILE} has a `{key}` this cannot find the end of; "
            f"it is unchanged. Edit it by hand.")
    return text[:start] + value + text[end:]


def _value_end(text, start):
    """Where the TOML string starting at `start` ends, or None."""
    for quote, escapes in (('"""', True), ("'''", False),
                           ('"', True), ("'", False)):
        if not text.startswith(quote, start):
            continue
        at = start + len(quote)
        while at < len(text):
            if escapes and text[at] == "\\":
                at += 2
                continue
            if len(quote) == 1 and text[at] == "\n":
                return None
            if text.startswith(quote, at):
                end = at + len(quote)
                # A multi-line string may end in up to two quotes of its
                # own, written straight before the closing three.
                while len(quote) == 3 and text.startswith(quote[0], end) \
                        and end - at < 5:
                    end += 1
                return end
            at += 1
        return None
    return None


# --------------------------------------------------------- the words --

#: Until a matching for "?" exists in the gradebook profile, a query is
#: reported as itself.
QUERIED_WORD = "?"

#: What a send does with a skill he marked "?": report it as a mark like
#: any other, or leave the skill and its pages out as if it were never
#: sat. His two modes, chosen per send (2026-11-19).
QUERIED_MODES = ("send", "leave out")


@dataclasses.dataclass(frozen=True)
class Words:
    passed: str
    failed: str
    queried: str = QUERIED_WORD
    #: Where they came from, said in the dialog: `gradebook` or `default`.
    source: str = "default"

    def of(self, outcome):
        return {"passed": self.passed, "failed": self.failed,
                "queried": self.queried}[outcome]


DEFAULT_WORDS = Words(passed="Pass", failed="Not yet")


def words_for(course_folder):
    """The words of his gradebook matching, as the gradebook would get them.

    His answer (2026-11-19): "whatever the instructor's chosen matching
    is" -- today an emoji and `Not Yet`, exactly as the profile holds
    them. A course with no matching uses printit's words, and the dialog
    says which it is using; that is a visible default, not a silent one.
    """
    path = os.path.join(course_folder, gradebook_mod.FILENAME)
    if not os.path.isfile(path):
        return DEFAULT_WORDS
    try:
        profile = gradebook_mod.load(path)
    except (OSError, ValueError, gradebook_mod.GradebookError) as exc:
        raise MailError(f"the gradebook matching could not be read: {exc}") \
            from None
    if not profile.passed or not profile.not_passed:
        raise MailError(
            "the gradebook matching names no word for a pass or a non-pass. "
            "Finish it, or move gradebook.toml aside to use printit's words.")
    return Words(passed=profile.passed, failed=profile.not_passed,
                 source="gradebook")


# ---------------------------------------------------------- the plan --

#: What a letter can be. Only `due` is sent.
DUE, SENT, NO_ADDRESS, HELD = "due", "sent", "no address", "held"


@dataclasses.dataclass
class Skill:
    slug: str
    title: str
    outcome: str
    word: str


@dataclasses.dataclass
class Letter:
    """One student's email, as it would go now."""

    sid: str
    name: str
    #: The four name fields -- first, last, pref_first, pref_last -- as
    #: `{field: value}`. See `name_values`.
    names: dict
    address: str
    skills: list
    #: `[(scan_id, scan_page)]`, in printed order.
    pages: list
    status: str
    reason: str = ""
    #: Something worth seeing before sending that does not stop it.
    warning: str = ""
    #: Whether an email about this run has reached them before.
    told: bool = False


def natural_name(shown):
    """`Crane, Tamsin` as `Tamsin Crane`; anything else as it is.

    Exactly one comma, the same rule the app's `displayName` states: with
    none there is nothing to turn round, and with two there is no telling
    which half is which. An email is read by the student, who does not
    file themselves surname first.
    """
    if shown.count(",") != 1:
        return shown
    last, rest = (part.strip() for part in shown.split(","))
    return f"{rest} {last}".strip() if rest and last else shown


def name_values(student):
    """The template's four name fields for one student (DESIGN 22).

    `first` and `last` are the registrar's. A roster holding only a whole
    name -- every real one until a re-import fills the parts -- has them
    split from `name`. The splitter guesses a compound surname wrong,
    never the first word, so `first` is safe from that and `last` is the
    guess it always was.

    `pref_first` and `pref_last` are the names they go by, each falling
    back to the registrar's, as printing does. **Never the other way
    round**: the email used to take the registrar's first name ahead of
    the preferred one, and greeted "Matthew" whoever had asked for Matt.
    """
    first, last = student.first, student.last
    if not (first and last):
        split_last, split_first, _ = classlist_mod.split_full_name(student.name)
        first = first or split_first or student.name
        last = last or split_last
    return {"first": first, "last": last,
            "pref_first": student.pref_first or first,
            "pref_last": student.pref_last or last}


def plan(record_path, run_id, roster, titles, words, queried="leave out",
         order=(), index=None, resend=()):
    """Every student who sat this run, and what an email to each would say.

    A sitting is an attempt that is not an absence (17). `roster` is the
    course's students; `titles` `{slug: title}`; `order` the run's skills
    in print order; `index` the run's page index, used to notice a paper
    with fewer pages saved than were printed. `resend` names students to
    send to again although they have been told everything.
    """
    if queried not in QUERIED_MODES:
        raise MailError(f"queried must be one of {QUERIED_MODES}, "
                        f"not {queried!r}.")
    rank = {slug: n for n, slug in enumerate(order)}
    by_sid = {s.sid: s for s in roster if s.sid}
    told_all = record_mod.mailed_in(record_path, run_id)
    pages_by_sid = {}
    for row in record_mod.scan_pages_in(record_path, run_id):
        pages_by_sid.setdefault(row["sid"], []).append(row)

    sat = {}
    for row in record_mod.attempts_in(record_path, run_id):
        if row["outcome"] != "absent":
            sat.setdefault(row["sid"], []).append(row)

    resend = set(resend)
    letters = []
    for sid, rows in sat.items():
        student = by_sid.get(sid)
        rows.sort(key=lambda r: (rank.get(r["slug"], len(rank)), r["slug"]))
        reported = [r for r in rows
                    if not (r["outcome"] == "queried" and queried == "leave out")]
        skills = [Skill(r["slug"], titles.get(r["slug"], r["slug"]),
                        r["outcome"], words.of(r["outcome"])) for r in reported]
        slugs = {s.slug for s in skills}
        mine = [p for p in pages_by_sid.get(sid, []) if p["slug"] in slugs]
        mine.sort(key=lambda p: (rank.get(p["slug"], len(rank)), p["slug"],
                                 p["run_page"] is None, p["run_page"] or 0,
                                 p["scan_id"], p["scan_page"]))
        told = told_all.get(sid, {})

        letter = Letter(
            sid=sid,
            name=natural_name(student.display) if student else "",
            names=(name_values(student) if student else
                   {f: "" for f in ("first", "last", "pref_first", "pref_last")}),
            address=(student.email.strip() if student else ""),
            skills=skills,
            pages=[(p["scan_id"], p["scan_page"]) for p in mine],
            status=DUE, told=bool(told))

        if student is None:
            letter.status, letter.reason = NO_ADDRESS, "not on the roster"
        elif not letter.address:
            letter.status, letter.reason = NO_ADDRESS, "no email address"
        elif not skills:
            letter.status = HELD
            letter.reason = "every skill is marked ?"
        elif all(told.get(s.slug) == s.outcome for s in skills) \
                and sid not in resend:
            letter.status, letter.reason = SENT, "already sent"
        letter.warning = _page_warning(reported, mine, index)
        letters.append(letter)

    letters.sort(key=lambda l: (l.name.lower(), l.sid))
    return letters


def _page_warning(reported, pages, index):
    """Say so when fewer pages were saved than the papers were printed on.

    A paper decided by hand, holding the sheet, has no scanned page at
    all; a second sheet saved before 2026-11-19 was stored with nobody on
    it. Either way the email goes with what there is, and he is told.
    """
    if not pages and reported:
        return "no scanned pages; the email has the results only"
    if index is None:
        return ""
    short = []
    for row in reported:
        if row["run_page"] is None:
            continue
        want = len(index.pages_of_paper(row["run_page"]))
        have = sum(1 for p in pages if p["slug"] == row["slug"])
        if have < want:
            short.append(f"{row['slug']} has {have} of {want} pages")
    return "; ".join(short)


# ---------------------------------------------------------- one email --

def results_text(skills):
    """`{{results}}`: one line per skill, the skill and then the mark."""
    lines = []
    for s in skills:
        named = s.slug if s.title in ("", s.slug) else f"{s.slug} {s.title}"
        lines.append(f"{named}: {s.word}")
    return "\n".join(lines)


def compose(letter, template, run, instructor=""):
    """`(subject, body)` for one letter, from `template` as it stands now."""
    values = {
        **letter.names,
        "name": letter.name,
        "assessment": run.get("title", ""),
        "date": availability_mod.spoken_date(run.get("date", ""))
        or str(run.get("date", "")),
        "results": results_text(letter.skills),
        "instructor": instructor,
    }
    subject = render(template.subject, values).strip()
    if "\n" in subject:
        raise MailError("the subject came out on more than one line.")
    return subject, render(template.body, values)


def attachment_name(run):
    """Named for the assessment, never the student: the name is on the page."""
    raw = f"{run.get('title', '')} {run.get('date', '')}".strip() or "papers"
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]+', " ", raw)
    return re.sub(r"\s+", " ", safe).strip() + ".pdf"


def attachment(scans_folder, pages):
    """One PDF of these scanned pages, in the order given, as bytes."""
    import pypdfium2 as pdfium
    folder = os.path.abspath(scans_folder)
    out = pdfium.PdfDocument.new()
    opened = {}
    try:
        for scan_id, scan_page in pages:
            path = os.path.abspath(os.path.join(folder, scan_id))
            if os.path.dirname(path) != folder:
                raise MailError(f"a scan named {scan_id!r} is not in "
                                f"the course's scans folder.")
            if scan_id not in opened:
                if not os.path.isfile(path):
                    raise MailError(
                        f"the stored scan {scan_id} is missing from the "
                        f"course's scans folder, so its pages cannot be "
                        f"attached.")
                opened[scan_id] = pdfium.PdfDocument(path)
            source = opened[scan_id]
            if not 1 <= scan_page <= len(source):
                raise MailError(f"{scan_id} has no page {scan_page}.")
            out.import_pages(source, [scan_page - 1])
        buffer = io.BytesIO()
        out.save(buffer)
        return buffer.getvalue()
    finally:
        out.close()
        for doc in opened.values():
            doc.close()


# -------------------------------------------------------------- send --

#: The script version that has `mail` and `quota`. `ping` reports it.
MAIL_VERSION = 2

#: Google's own per-message ceiling is 25 MB; base64 adds a third.
MAX_ATTACHMENT = 18 * 1024 * 1024

#: Failures in a row after which the rest are not tried: by then it is
#: the account or the script, not one student.
STOP_AFTER = 3


def ready(conn, call=form_mod.call):
    """`{remaining}` if this course's script can send mail; MailError if not."""
    answer = call(conn, "ping")
    if int(answer.get("version") or 1) < MAIL_VERSION:
        raise MailError(
            "this course's form script was deployed before printit could "
            "send email. Update it on Settings, then grant the new "
            "permission once.")
    return {"remaining": int(call(conn, "quota").get("remaining", 0))}


@dataclasses.dataclass
class Report:
    sent: list = dataclasses.field(default_factory=list)
    #: `[(sid, reason)]`
    failed: list = dataclasses.field(default_factory=list)
    #: Not tried, because the send stopped first.
    skipped: list = dataclasses.field(default_factory=list)


def send(letters, template, run, record_path, scans_folder, conn,
         instructor="", call=form_mod.call, on_each=None):
    """Send every `due` letter, one request each, recording each as it goes.

    Refused before the first email if Google's allowance for today is
    smaller than the class. A request that times out is not retried and
    not recorded: Google may or may not have sent it, so the send stops
    and says to look in Sent before pressing again.
    """
    due = [l for l in letters if l.status == DUE]
    if not due:
        return Report()
    remaining = ready(conn, call=call)["remaining"]
    if remaining < len(due):
        raise MailError(
            f"Google allows this account {remaining} more email(s) today and "
            f"this would send {len(due)}. Nothing was sent.")
    for letter in due:
        compose(letter, template, run, instructor)     # every one, first

    report = Report()
    in_a_row = 0
    for n, letter in enumerate(due):
        if in_a_row >= STOP_AFTER:
            report.skipped = [l.sid for l in due[n:]]
            break
        try:
            subject, body = compose(letter, template, run, instructor)
            payload = {"to": letter.address, "subject": subject, "body": body,
                       "attachments": []}
            if letter.pages:
                pdf = attachment(scans_folder, letter.pages)
                if len(pdf) > MAX_ATTACHMENT:
                    raise MailError(
                        f"the pages come to {len(pdf) // (1024 * 1024)} MB, "
                        f"more than an email can carry.")
                payload["attachments"].append({
                    "name": attachment_name(run),
                    "type": "application/pdf",
                    "data": base64.b64encode(pdf).decode("ascii")})
            call(conn, "mail", payload, timeout=180, retries=0)
        except form_mod.FormTimeout as exc:
            # Reached the script, no answer: it may have gone. Not
            # recorded, so not "sent" -- and not retried, so not twice.
            report.failed.append((letter.sid, f"{exc} It may have been "
                                  f"sent: look in Sent before sending "
                                  f"again."))
            report.skipped = [l.sid for l in due[n + 1:]]
            break
        except (form_mod.FormError, MailError) as exc:
            report.failed.append((letter.sid, str(exc)))
            in_a_row += 1
            continue
        finally:
            if on_each:
                on_each(n + 1, len(due))
        record_mod.note_mailed(record_path, run["run_id"], letter.sid,
                               letter.address,
                               [(s.slug, s.outcome) for s in letter.skills])
        report.sent.append(letter.sid)
        in_a_row = 0
    return report
