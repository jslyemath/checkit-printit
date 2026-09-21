"""Which skills are open for retake, and what the next assessment is.

One file, because the form push and the print job both need exactly this.
Descriptions are deliberately **not** here: they come from the bank's
`bank.xml`, which is already the single source for the printed skill headers
and for `Skill Descriptions.tex`. A second copy is how they drift apart.

The wording rules come from the Apps Script this replaces, kept at
`reference/control_center.gs` -- the number words, the three limiter modes,
and the unsubmittable state when nothing is open yet. They are reproduced
rather than reinvented so the form students see does not change character.
"""

import dataclasses
import datetime
import re

#: 0 to 40, where 0 means "any". Straight from the Control Center script, so
#: the sentence students read is the one they have been reading all along.
NUMBER_WORDS = [
    "any", "one", "two", "three", "four", "five", "six", "seven", "eight",
    "nine", "ten", "eleven", "twelve", "thirteen", "fourteen", "fifteen",
    "sixteen", "seventeen", "eighteen", "nineteen", "twenty", "twenty one",
    "twenty two", "twenty three", "twenty four", "twenty five", "twenty six",
    "twenty seven", "twenty eight", "twenty nine", "thirty", "thirty one",
    "thirty two", "thirty three", "thirty four", "thirty five", "thirty six",
    "thirty seven", "thirty eight", "thirty nine", "forty",
]

LIMITS = ("at most", "at least", "exactly")

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday"]


class AvailabilityError(Exception):
    pass


def number_word(count):
    """The word for a count, or the digits when it runs past the table."""
    try:
        count = int(count)
    except (TypeError, ValueError):
        return "any"
    if 0 <= count < len(NUMBER_WORDS):
        return NUMBER_WORDS[count]
    return str(count)


def as_date(value):
    """A date from a TOML date, a datetime, or an ISO-ish string."""
    if value in ("", None):
        return None
    if isinstance(value, datetime.datetime):
        return value.date()
    if isinstance(value, datetime.date):
        return value
    text = str(value).strip()
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y"):
        try:
            return datetime.datetime.strptime(text[:10], pattern).date()
        except ValueError:
            continue
    raise AvailabilityError(f"{value!r} is not a date I recognise. Use 2026-09-18.")


def as_datetime(value):
    if value in ("", None):
        return None
    if isinstance(value, datetime.datetime):
        return value
    if isinstance(value, datetime.date):
        return datetime.datetime.combine(value, datetime.time(23, 59))
    text = str(value).strip().replace(" ", "T")
    try:
        return datetime.datetime.fromisoformat(text)
    except ValueError:
        return datetime.datetime.combine(as_date(value), datetime.time(23, 59))


def spoken_date(value):
    """`Friday, 9/18` -- the form's own phrasing."""
    day = as_date(value)
    if day is None:
        return ""
    return f"{DAYS[day.weekday()]}, {day.month}/{day.day}"


def spoken_time(value):
    when = as_datetime(value)
    if when is None:
        return ""
    hour = when.hour % 12 or 12
    meridiem = "AM" if when.hour < 12 else "PM"
    return f"{hour}:{when.minute:02d} {meridiem}"


@dataclasses.dataclass
class Availability:
    name: str = ""
    date: object = None
    due: object = None
    choose: int = 0
    limit: str = "at most"
    skills: tuple = ()
    source_path: str = ""

    @property
    def unlimited(self):
        return not self.choose

    def question_title(self):
        """"Choose At Most THREE Skills", as the form shows it."""
        word = number_word(self.choose).upper()
        if self.unlimited:
            return f"Choose {word} Skills"
        return f"Choose {self.limit.title()} {word} Skills"

    def selecting_for(self):
        return (f"You are selecting {number_word(self.choose)} skill(s) you "
                f"would like to attempt on the {self.name} on "
                f"{spoken_date(self.date)}.")

    def due_notice(self):
        return (f"This form is due by {spoken_time(self.due)} on "
                f"{spoken_date(self.due)}. If you do not complete the form by "
                f"that time, then I cannot guarantee that I will have skills "
                f"printed for you to attempt.")

    def confirmation(self):
        return (f"I understand that I am selecting skills for "
                f"{spoken_date(self.date)}.")


def load(path):
    import tomllib
    try:
        with open(path, "rb") as f:
            raw = tomllib.load(f)
    except OSError as exc:
        raise AvailabilityError(str(exc)) from None
    block = raw.get("assessment", {})
    limit = str(block.get("limit", "at most")).strip().lower()
    if limit not in LIMITS:
        raise AvailabilityError(
            f"{path}: limit is {limit!r}; expected one of "
            + ", ".join(repr(x) for x in LIMITS)
        )
    return Availability(
        name=str(block.get("name", "")).strip(),
        date=block.get("date") or None,
        due=block.get("due") or None,
        choose=int(block.get("choose", 0) or 0),
        limit=limit,
        # `skills` sits under [assessment]: a TOML table runs to the next
        # header, so a key below one belongs to it however it is spaced. The
        # root is accepted too, for a file that puts it above.
        skills=tuple(str(s).strip()
                     for s in (block.get("skills") or raw.get("skills") or [])
                     if str(s).strip()),
        source_path=path,
    )


# ---------------------------------------------------------------- writing --

def _render(value):
    if isinstance(value, datetime.datetime):
        return value.isoformat()
    if isinstance(value, datetime.date):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join('"' + str(v).replace('"', '\\"') + '"'
                               for v in value) + "]"
    text = str(value)
    if not text:
        return '""'
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def set_values(text, values):
    """Change keys in place, keeping comments and everything else.

    A line editor rather than a parse-and-rewrite for the same reason the
    seating file gets one: this file explains itself in comments, Python has
    no TOML writer, and a round trip would throw them away. A trailing comment
    on the line being changed survives too.
    """
    remaining = dict(values)
    out = []
    for line in text.splitlines(keepends=True):
        stripped = line.lstrip()
        if not stripped.startswith("#"):
            match = re.match(r"^(\s*)([A-Za-z_][\w-]*)(\s*=\s*)(.*?)(\s*)$",
                             line.rstrip("\n").rstrip("\r"))
            if match and match.group(2) in remaining:
                indent, key, equals, value, _ = match.groups()
                comment = ""
                hash_at = _comment_start(value)
                if hash_at is not None:
                    comment = "  " + value[hash_at:].strip()
                ending = line[len(line.rstrip("\r\n")):]
                out.append(f"{indent}{key}{equals}"
                           f"{_render(remaining.pop(key))}{comment}{ending}")
                continue
        out.append(line)
    if remaining:
        raise AvailabilityError(
            "no line to change for: " + ", ".join(sorted(remaining))
        )
    return "".join(out)


def _comment_start(value):
    """Where a trailing comment begins, ignoring hashes inside quotes."""
    quote = None
    for i, ch in enumerate(value):
        if quote:
            if ch == quote:
                quote = None
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return i
    return None


def describe(av, descriptions=None):
    """What the form will say, so it can be read before it is pushed."""
    lines = [
        f"assessment  {av.name or '(unnamed)'}",
        f"date        {spoken_date(av.date) or '(not set)'}",
        f"due         {spoken_time(av.due)} {spoken_date(av.due)}".strip(),
        f"choose      {av.limit} {number_word(av.choose)}"
        if not av.unlimited else "choose      any number",
        "",
        f"open for retake ({len(av.skills)}):",
    ]
    if not av.skills:
        lines.append("  (none -- the form will say so and refuse submissions)")
    for slug in av.skills:
        text = (descriptions or {}).get(slug)
        lines.append(f"  {slug:6} {text}" if text else f"  {slug}")
    return "\n".join(lines)
