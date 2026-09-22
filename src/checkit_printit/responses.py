"""What students chose, from the form's responses.

A form accumulates responses all term, so the first question is always *which
of these belong to today*. The retired Control Center answered it with
`filterArrayBySingleDateCriterion(responses, 0, 2, GetDate)`: match the
response's date against the assessment's. That is what the "Confirm Skill
Checkpoint Date" checkbox is **for** -- it is the scoping key, not a nudge.

Two things changed in carrying it over. The old script read column 2 of a
sheet, which is the positional fragility this design rejects everywhere else;
here the confirmation is found by its recorded item id. And the date is read
out of the student's own answer rather than a separate column, because the
answer is the thing that says which assessment they were answering for.

Everything here is decided in Python rather than in the Apps Script, so it
can be tested without a network. The script returns what the form holds and
judges nothing.
"""

import datetime
import re

from . import availability as availability_mod


class ResponseError(Exception):
    pass


#: `Friday, 9/25` inside the confirmation sentence. Month and day only: that
#: is what the retired script compared, and a form does not span a year
#: within one term. Recorded rather than silently narrowed.
_MONTH_DAY = re.compile(r"\b(\d{1,2})/(\d{1,2})\b")


def confirmed_date(answer):
    """The (month, day) a response says it is for, or None.

    `answer` is whatever the confirmation checkbox holds: a list with the one
    ticked option, a bare string, or nothing at all.
    """
    for text in _as_list(answer):
        found = _MONTH_DAY.search(str(text))
        if found:
            return int(found.group(1)), int(found.group(2))
    return None


def _as_list(answer):
    """A checkbox answers with a list, a text item with a string."""
    if answer is None:
        return []
    if isinstance(answer, (list, tuple)):
        return list(answer)
    return [answer]


def _timestamp(raw):
    text = str(raw or "").strip().replace("Z", "+00:00")
    try:
        when = datetime.datetime.fromisoformat(text)
    except ValueError:
        raise ResponseError(
            f"a response carries an unreadable timestamp: {raw!r}") from None
    # Google sends UTC; comparing aware and naive datetimes raises, and the
    # only use here is ordering, so strip the offset rather than convert.
    return when.replace(tzinfo=None)


def for_assessment(raw_responses, confirm_item_id, date):
    """Only the responses whose confirmation names this assessment's date.

    A response that ticked nothing has no date and cannot be placed, so it is
    left out and counted -- see `Pull.unconfirmed`.
    """
    day = availability_mod.as_date(date)
    if day is None:
        raise ResponseError(
            f"the assessment has no usable date ({date!r}), so responses "
            f"cannot be scoped to it. Set one with `skills set --date`.")
    want = (day.month, day.day)

    kept, unconfirmed = [], []
    for response in raw_responses:
        answers = response.get("answers") or {}
        said = confirmed_date(answers.get(str(confirm_item_id)))
        if said is None:
            unconfirmed.append(response)
        elif said == want:
            kept.append(response)
    return kept, unconfirmed


def latest_per_email(responses):
    """One response per address, the most recent.

    "Latest wins" is the existing semantics, done by hand in the 2026-09-18
    run; a student who changes their mind resubmits rather than editing.
    Returns (chosen, superseded_count).
    """
    best = {}
    superseded = 0
    for response in responses:
        email = str(response.get("email", "")).strip().lower()
        when = _timestamp(response.get("timestamp"))
        if email in best:
            superseded += 1
            if when <= best[email][0]:
                continue
        best[email] = (when, response)
    return {e: r for e, (_, r) in best.items()}, superseded


def slug_of(option, known=()):
    """`W1 - I can convert ...` -> `W1`.

    Split on the first ` - `, because a description may well contain another.
    `known` is checked when given, so a renamed or retired slug is reported
    rather than silently carried into a print run.
    """
    text = str(option).strip()
    if not text:
        return ""
    slug = text.split(" - ", 1)[0].strip()
    if known and slug not in known:
        return ""
    return slug


class Pull:
    """What a pull found, in a shape the CLI can report honestly."""

    def __init__(self):
        self.chosen = {}          # sid -> [slug, ...]
        self.by_student = {}      # sid -> (student, [slug, ...])
        self.unknown_emails = []  # responded, not on the roster
        self.unrecognised = []    # (email, option) that is not a known skill
        self.unconfirmed = 0      # ticked no date
        self.out_of_scope = 0     # confirmed a different assessment
        self.superseded = 0       # replaced by a later response
        self.silent = []          # on the roster, never responded

    @property
    def answered(self):
        return len(self.by_student)


def collect(raw_responses, roster, items, date, known_skills=()):
    """Join responses to students. Decides nothing it cannot explain.

    `items` is the recorded item id map, so the confirmation and the skill
    question are found by id and never by position -- the old script used
    `getItems(CHECKBOX)[1]`, and inserting one header above it silently
    retargeted every write.
    """
    confirm_id = (items or {}).get("confirm_date")
    choose_id = (items or {}).get("choose_skills")
    if not confirm_id or not choose_id:
        raise ResponseError(
            "this course does not know which form item is which. Run "
            "`checkit-printit form map` (or `form add-items`) first.")

    out = Pull()
    scoped, unconfirmed = for_assessment(raw_responses, confirm_id, date)
    out.unconfirmed = len(unconfirmed)
    out.out_of_scope = len(raw_responses) - len(scoped) - len(unconfirmed)

    newest, out.superseded = latest_per_email(scoped)

    # Address -> student, built from every address a student has been seen
    # under. One real student appears under two in two same-day exports, and
    # the form only ever sees one of them.
    lookup = {}
    for student in roster:
        for address in student.all_emails():
            lookup.setdefault(address, student)

    for email, response in sorted(newest.items()):
        student = lookup.get(email)
        if student is None:
            out.unknown_emails.append(email)
            continue
        picked = []
        for option in _as_list((response.get("answers") or {}).get(str(choose_id))):
            slug = slug_of(option, known_skills)
            if not slug:
                out.unrecognised.append((email, str(option)))
            elif slug not in picked:
                picked.append(slug)
        key = student.sid or student.alt_id or student.email or student.name
        out.by_student[key] = (student, picked)
        out.chosen[key] = picked

    answered = {id(s) for s, _ in out.by_student.values()}
    out.silent = [s for s in roster
                  if not s.dropped and id(s) not in answered]
    return out
