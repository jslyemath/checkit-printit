"""Pseudonyms for real students: stable across files, and reversible.

The instructor needs help with files that carry student names, ids and
email addresses. Those files must not be shown to an assistant, pasted
into a chat, or attached to a bug report. But a file with the names
stripped out is usually useless for the thing it was needed for --
column layouts, joins between two exports, a surname the splitter gets
wrong -- so stripping is not the answer either.

So: **a masked twin.** Every real person gets one fake person, and the
fake one is substituted wherever the real one appears. The twin has the
same number of rows, the same columns in the same order, the same
*shape* of value in every cell, and none of the content.

Four things this has to get right, each learned from a way the obvious
version fails.

**It maps people, not strings.** A class list says `Clifford, Matthew
C.`, a seating chart says `Matt Clifford`, and a grades export says only
`#1234567890`. Those are one person. A string-to-string table makes them
three pseudonyms, and every cross-file join -- which is most of what
goes wrong -- becomes unreproducible in the twin. So a cell is resolved
to a *person* first, on the id order `roster.py` already uses, and the
fake person is then rendered into whatever shape that cell wanted.

**It preserves shape, because the shape is where the bugs are.** A
surname of two words masks to two words; a 9-digit id to 9 digits; a
`#`-prefixed 10-digit id keeps the `#`; a student seen under two
different email domains keeps two different fake domains. One known open
bug in this tool is a student whose surname is two words and whose
splitter returns one. Masking that to a one-word surname would delete
the bug from the twin and the twin would then prove the bug fixed.

**It never guesses that something is safe.** A column the tool does not
recognise is not passed through. See `mask.py`, which does the
classifying; this module only ever masks what it is handed.

**It checks its own output.** `real_values()` exists so a caller can
re-read what it wrote and search it for every real string in the vault.
A masker that is merely believed to be correct is not enough.

Three limits, stated here because they are easier to read than to
discover:

* **The vault is the only way back.** There is no derivation key and no
  recovery. Lose the file and the twin can never be unmasked. The
  alternative -- a key that reconstructs the mapping -- is a secret that
  would have to be trusted to whoever holds it, which is the thing being
  avoided. Back the vault up somewhere the masked files are not.
* **Files only.** This masks tabular files and text. It does nothing for
  a screenshot, a traceback, a window title or a path under
  `~/CheckItPrintIt`.
* **Results come through unmasked**, because a twin with the marks
  removed cannot be used to debug a gradebook. A pass/fail pattern in a
  class of twenty-two is close to unique, but it is not *linkable* to a
  person by anyone who does not hold the vault.

Where it lives: `~/CheckItPrintIt/vaults/<course>.json`, a **sibling** of
`courses/`, never a child. That is deliberate and structural: masking a
whole course directory, when that is built, cannot physically walk into
the vault and copy it into the output. A rule saying "skip the vault"
would be one more rule to get wrong.
"""

import dataclasses
import datetime
import json
import os
import random
import re


class VaultError(Exception):
    pass


VAULTS = "vaults"

#: Schema version of the file on disk. Read, and refused if it is from a
#: later version -- a vault half-understood is worse than one not opened,
#: because unmasking would silently leave real values in place.
VERSION = 1

#: Fake given names. Historical mathematicians and scientists, which is
#: the list `roster.TEMPLATE` already uses for its examples.
#:
#: Recognisable dead scientists are chosen **on purpose**: masked data
#: should be impossible to mistake for real data at a glance. A twin
#: populated with plausible modern names invites exactly that mistake,
#: and the mistake it invites is treating a real file as a masked one.
FIRST_NAMES = (
    "Ada", "Alan", "Emmy", "Carl", "Sofia", "Blaise", "Hypatia",
    "Leonhard", "Maryam", "Srinivasa", "Grace", "Kurt", "Amalie",
    "Pierre", "Katherine", "David", "Julia", "Henri", "Mary", "Niels",
    "Rosalind", "Felix", "Olga", "John", "Lise", "Bernhard", "Cecilia",
    "George", "Nina", "Paul", "Dorothy", "Evariste", "Ruth", "Thomas",
    "Augustin", "Vera", "Edsger", "Hanna", "Marin", "Ingrid",
    "Gottfried", "Clara", "Jakob", "Annie", "Stefan", "Hertha", "Omar",
    "Mileva", "Rene", "Sophie", "Andrey", "Esther", "Georg", "Marjorie",
    "Tullio", "Elbert", "Yuri", "Fanny", "Alicia", "Bertrand",
)

#: Fake surnames, one word.
LAST_NAMES = (
    "Lovelace", "Turing", "Noether", "Gauss", "Kovalevskaya", "Pascal",
    "Euler", "Mirzakhani", "Ramanujan", "Hopper", "Godel", "Fermat",
    "Johnson", "Hilbert", "Robinson", "Poincare", "Somerville", "Abel",
    "Franklin", "Klein", "Ladyzhenskaya", "Nash", "Meitner", "Riemann",
    "Payne", "Boole", "Bari", "Erdos", "Vaughan", "Galois", "Moufang",
    "Bayes", "Cauchy", "Rubin", "Dijkstra", "Mersenne", "Daubechies",
    "Leibniz", "Immerwahr", "Bernoulli", "Cannon", "Banach", "Ayrton",
    "Khayyam", "Maric", "Descartes", "Germain", "Markov", "Lederberg",
    "Cantor", "Chern", "Rice", "Levi", "Frink", "Manin", "Mendel",
    "Agnesi", "Bassi", "Byron", "Hamilton",
)

#: Fake surnames of exactly two words, for a real surname that has two.
#:
#: Needed, not decorative: the surname splitter is known to mis-handle
#: these, and a twin that cannot reproduce that has lost the bug.
LAST_NAMES_TWO = (
    "del Ferro", "de Morgan", "von Neumann", "van Ceulen", "de Moivre",
    "da Vinci", "von Koch", "dos Santos", "al Khwarizmi", "le Verrier",
    "de Rham", "van Kampen", "di Bruno", "de Broglie", "von Mises",
)

#: Fake email domains. Every one sits under `example.org`, which RFC 2606
#: reserves, so a fake address can never be somebody's real one.
#:
#: Real domains are **mapped, not kept**. Mapping preserves the only
#: thing about a domain that matters here -- that two addresses for one
#: student may differ in domain, which is a live cause of unmatched form
#: responses -- while keeping the institution out of the twin as well.
FAKE_DOMAINS = (
    "example.org", "mail.example.org", "student.example.org",
    "alumni.example.org", "lists.example.org", "dept.example.org",
    "legacy.example.org", "sub.example.org",
)

#: Which kinds of value this module knows how to render a fake of.
#:
#: `handle` is a username or login: an opaque identifier like `sid` and
#: `alt_id`, and masked the same way. It has its own kind rather than
#: being folded into `alt_id` because a file may carry both, and because
#: a column that is blanked for want of a kind is a column that can no
#: longer be reasoned about -- the LMS class list carries `OrgDefinedId`
#: and `Username` side by side.
KINDS = ("full", "last", "first", "middle", "sid", "alt_id", "handle",
         "email")

#: The kinds that are opaque identifiers, matched and rendered alike.
ID_KINDS = ("sid", "alt_id", "handle")


def default_root():
    """Where vaults live: a sibling of `courses/`, under the same home."""
    home = os.environ.get("CHECKIT_PRINTIT_HOME")
    if home:
        return os.path.join(home, VAULTS)
    return os.path.join(os.path.expanduser("~"), "CheckItPrintIt", VAULTS)


def path_for(course, root=None):
    """The vault file for a named course.

    Named after the course rather than after the file being masked, so
    that every file from one course shares one set of pseudonyms. Two
    files masked under two vaults would give the same student two fake
    identities, which is the failure this whole module is shaped around.
    """
    safe = str(course).strip().rstrip(". ")
    if not safe or safe in (".", "..") or os.path.basename(safe) != safe:
        raise VaultError(
            f"{course!r} is not usable as a course name. Use a plain name "
            "with no slashes, such as \"MAT 106\"."
        )
    return os.path.join(root or default_root(), safe + ".json")


def _norm(value):
    return " ".join((value or "").split()).lower()


# --------------------------------------------------------------- shaping --

def _like(value, rng, keep=0, tries=200):
    """A different string with the same punctuation, case and classes.

    Digits become digits, upper letters upper, lower lower, and
    everything else -- `#`, `-`, spaces -- stays exactly where it was. So
    `#1234567890` masks to `#5582910473` and `806-12-3456` keeps its
    dashes. That is what makes a twin useful for a column-width or a
    parsing bug.

    `keep` is a count of leading **alphanumeric** characters to carry
    over unchanged, for a prefix the caller has established is shared by
    every row in the file. A prefix every student has cannot distinguish
    one from another, so carrying it over leaks nothing and keeps the
    value realistic. Nothing is kept unless a caller says so.
    """
    if not value:
        return value
    for _ in range(tries):
        out, seen = [], 0
        for ch in value:
            if ch.isalnum():
                seen += 1
                if seen <= keep:
                    out.append(ch)
                elif ch.isdigit():
                    out.append(str(rng.randrange(10)))
                elif ch.isupper():
                    out.append(chr(ord("A") + rng.randrange(26)))
                else:
                    out.append(chr(ord("a") + rng.randrange(26)))
            else:
                out.append(ch)
        made = "".join(out)
        if made != value:
            return made
    raise VaultError(
        f"could not invent a value unlike {value!r} after {tries} tries. "
        "It is probably too short to mask -- check the column mapping."
    )


def _split_marker(value):
    """An id, and any trailing marker with no digits in it.

    Brightspace's grades export carries a retired enrolment as the same
    id with `-DoNotUse` after it, and §14.6 settled that printit must
    never write to such a row. A marker randomised into `-WqRtPzLm`
    takes that signal out of the twin, and the twin is exactly where the
    rule has to be got right.

    A trailing run containing no digits is a system marker, not a
    person. If that is ever wrong -- an id column with a surname in it --
    the output scan catches it, because a real surname surviving in a
    masked file is precisely what that scan looks for.
    """
    match = re.search(r"\d(?=\D*$)", value)
    if not match:
        return value, ""
    return value[:match.end()], value[match.end():]


def decompose(value):
    """An id split into `(template, core, marker)`.

    `core` is just the alphanumerics. `template` is the rest of the
    value with each alphanumeric replaced by a slot, so that punctuation
    keeps its position. `marker` is a trailing run with no digits, per
    `_split_marker`.

    This exists because **the same id is written differently by
    different exports.** A class list gives a Global ID as
    `1234567890`; the grades export gives the same number as
    `#1234567890`; a retired enrolment of the same student is
    `#1234567890-DoNotUse`. All three are one person, and a key that
    includes the punctuation makes them three.

    So the *core* is what identifies, and the template and marker are
    re-applied when rendering. The twin then shows one fake number worn
    three ways, which is what the real file does and what a reader of
    the twin has to be able to see.
    """
    body, marker = _split_marker(value)
    core = re.sub(r"[^0-9A-Za-z]", "", body)
    template = re.sub(r"[0-9A-Za-z]", "\0", body)
    return template, core, marker


def recompose(template, core, marker):
    """Put a fake core back into the shape the original cell had."""
    out, index = [], 0
    for ch in template:
        if ch == "\0":
            out.append(core[index] if index < len(core) else "0")
            index += 1
        else:
            out.append(ch)
    return "".join(out) + core[index:] + marker


def id_core(value):
    """The part of an id that identifies somebody, lower-cased for keying."""
    return decompose(value)[1].lower()


#: What a one-letter value is masked to. Every one of them, deliberately.
INITIAL = "X"


def _initial_like(value, rng):
    """A fake middle name of the same shape: an initial for an initial.

    **A single letter is not masked per person.** It gets `INITIAL`,
    always, and so it does not unmask. That is a deliberate hole, and
    the alternative was worse: there are twenty-six letters and more
    students than that, so a per-person mapping cannot be injective, and
    a text substitution of a lone letter would rewrite every standalone
    `T` in a sentence. Reversing it wrongly is the failure mode -- it
    restored `R` where the file said `T`, silently -- and a hole that is
    written down beats a reversal that is sometimes wrong.

    What survives is the *presence* and the *shape* of a middle initial,
    which is what the name-splitting bugs need. Which letter it was does
    not identify anybody on its own.
    """
    stripped = value.strip()
    if not stripped:
        return ""
    letters = re.sub(r"[^A-Za-z]", "", stripped)
    if len(letters) <= 1:
        # "C" or "C." -- keep the punctuation, fix the letter.
        return re.sub(r"[A-Za-z]", INITIAL, stripped)
    return rng.choice(LAST_NAMES)


# ----------------------------------------------------------------- people --

@dataclasses.dataclass
class Person:
    """One real student and the fake one standing in for them.

    `real` and `fake` hold the *structured* identity, and are what new
    fake values are generated from, so that every rendering of this
    person agrees with every other one.

    `strings` is the literal record: every real cell value ever masked
    for this person, mapped to what it was masked to. It is what makes
    masking idempotent and unmasking complete -- a value that has been
    masked once always masks the same way, and every fake string that
    has ever left the machine has a way back.
    """

    tag: str
    real: dict
    fake: dict
    strings: dict = dataclasses.field(default_factory=dict)

    def real_keys(self):
        """Every exact key this person can be recognised by in a file.

        Ids first, then addresses, then the name -- the order
        `roster.keys_of` uses, and for the same reason: a name an
        instructor can retype is not a key.

        Deliberately **exact**. `classlist.merge` matches a surname plus
        an initial because a human typed one of the two spellings and
        meant the other. Masking must not do that: a wrong guess here
        merges two real students into one pseudonym, and the twin then
        silently disagrees with the file it came from.
        """
        keys = []
        for field in ID_KINDS:
            if self.real.get(field):
                keys.append((field, self.real[field].lower()))
        for address in self.real.get("emails") or []:
            keys.append(("email", _norm(address)))
        name = _norm(f"{self.real.get('first', '')} "
                     f"{self.real.get('last', '')}")
        if name.strip():
            keys.append(("name", name))
        return keys


class Vault:
    """The pseudonym table for one course.

    Load it, mask with it, save it. It grows: a student seen for the
    first time gets a fake identity invented on the spot, and a student
    seen before gets the one they already had.
    """

    def __init__(self, course, people=None, domains=None, seed=None,
                 created=None, version=VERSION):
        self.course = course
        self.people = list(people or [])
        self.domains = dict(domains or {})
        self.seed = seed if seed is not None else random.randrange(1 << 30)
        self.created = created or datetime.date.today().isoformat()
        self.version = version

        #: How many leading alphanumerics of an id are shared by every row
        #: of the file being masked, and so carry no information about any
        #: one student. Set by `mask.py` after it has looked at the whole
        #: column; empty here, because a vault on its own cannot know.
        self.prefix_keep = {}

        self._rng = random.Random(self.seed + len(self.people) * 7919)
        self._index = {}
        for person in self.people:
            for key in person.real_keys():
                self._index[key] = person

    # ------------------------------------------------------------- disk --

    @classmethod
    def load(cls, path):
        if not os.path.isfile(path):
            raise VaultError(
                f"no vault at {path}. Make one with `checkit-printit vault "
                "mask`, which creates it on first use."
            )
        with open(path, encoding="utf-8") as f:
            raw = json.load(f)
        version = raw.get("version", 0)
        if version > VERSION:
            raise VaultError(
                f"{path} is a version {version} vault and this printit reads "
                f"up to {VERSION}. Upgrade printit rather than opening it: a "
                "vault read with fields missing would unmask incompletely and "
                "leave real values in place."
            )
        people = [Person(tag=p["tag"], real=p["real"], fake=p["fake"],
                         strings=p.get("strings", {}))
                  for p in raw.get("people", [])]
        return cls(course=raw.get("course", ""), people=people,
                   domains=raw.get("domains", {}), seed=raw.get("seed"),
                   created=raw.get("created"), version=version)

    @classmethod
    def open_or_create(cls, path, course):
        if os.path.isfile(path):
            vault = cls.load(path)
            if course and vault.course and _norm(vault.course) != _norm(course):
                raise VaultError(
                    f"{path} is the vault for {vault.course!r}, not "
                    f"{course!r}. Masking two courses into one vault is "
                    "allowed but almost never meant -- pass --course "
                    f"{vault.course!r} to use it anyway."
                )
            return vault
        return cls(course=course)

    def save(self, path):
        """Write the vault, creating its directory.

        Written whole and replaced atomically, because a vault truncated
        half way through is a set of students who can no longer be
        unmasked.
        """
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        payload = {
            "version": VERSION,
            "course": self.course,
            "created": self.created,
            "seed": self.seed,
            "note": ("Real student data. Keep this file out of every "
                     "repository and away from the masked files it "
                     "explains. It is the only way to unmask them."),
            "domains": self.domains,
            "people": [{"tag": p.tag, "real": p.real, "fake": p.fake,
                        "strings": p.strings} for p in self.people],
        }
        temp = path + ".new"
        with open(temp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=1, ensure_ascii=False, sort_keys=True)
            f.write("\n")
        os.replace(temp, path)

    # ----------------------------------------------------------- lookup --

    def resolve(self, fields):
        """Find or invent the person these cells describe.

        `fields` is whatever the row offered: any of `sid`, `alt_id`,
        `email`, `first`, `last`, `middle`, `full`. Returns
        `(person, created)`.

        **A row that matches two different people is refused, not
        resolved.** It happens for real: a gradebook row carrying an id
        that belongs to one roster entry and an address that belongs to
        another means one of the two files is wrong about somebody, and
        quietly picking a winner would bake that into the twin where it
        could never be seen again.
        """
        offered = self._keys_from(fields)
        hits = {id(self._index[k]): self._index[k]
                for k in offered if k in self._index}
        if len(hits) > 1:
            names = sorted(p.tag for p in hits.values())
            raise VaultError(
                "one row matches " + str(len(hits)) + " people already in the "
                "vault (" + ", ".join(names) + "). The keys it offered were "
                + ", ".join(f"{k}={v}" for k, v in offered) + ". Two files "
                "disagree about who somebody is; fix that before masking, "
                "because the twin cannot show it to you."
            )
        if hits:
            person = next(iter(hits.values()))
            self._absorb(person, fields)
            return person, False
        return self._invent(fields), True

    def _keys_from(self, fields):
        keys = []
        for field in ID_KINDS:
            if fields.get(field):
                core = id_core(str(fields[field]))
                if core:
                    keys.append((field, core))
        for address in self._addresses(fields):
            keys.append(("email", address))
        first, last = self._name_parts(fields)
        name = _norm(f"{first} {last}")
        if name.strip():
            keys.append(("name", name))
        return keys

    @staticmethod
    def _addresses(fields):
        raw = fields.get("emails") or ([fields["email"]]
                                       if fields.get("email") else [])
        out = []
        for address in raw:
            address = _norm(address)
            if address and address not in out:
                out.append(address)
        return out

    @staticmethod
    def _name_parts(fields):
        """(first, last), splitting a single-column name when that is all.

        Uses the class list's own splitter, so the twin inherits whatever
        that splitter does -- including what it gets wrong, which is the
        point.
        """
        first = (fields.get("first") or "").strip()
        last = (fields.get("last") or "").strip()
        if first or last:
            return first, last
        from .classlist import split_full_name
        last, first, _ = split_full_name(fields.get("full") or "")
        return first, last

    def _absorb(self, person, fields):
        """Fold new facts about a known person into their entry.

        An id or an address seen for the first time becomes another way
        to recognise them next time. Nothing already recorded is
        replaced: the first file to name somebody is as good a witness as
        the second, and overwriting would make the twin depend on the
        order the files happened to be masked in.
        """
        for field in ID_KINDS:
            core = decompose(str(fields.get(field) or "").strip())[1]
            if core and not person.real.get(field):
                person.real[field] = core
                person.fake[field] = self._fake_id(field, core, person)
                self._index[(field, core.lower())] = person
        for address in self._addresses(fields):
            if address not in (person.real.get("emails") or []):
                person.real.setdefault("emails", []).append(address)
                person.fake.setdefault("emails", []).append(
                    self._fake_email(address, person))
                self._index[("email", address)] = person

    def _invent(self, fields):
        """A brand new person, with a fake identity to match their shape."""
        first, last = self._name_parts(fields)
        middle = (fields.get("middle") or "").strip()
        tag = "p%02d" % (len(self.people) + 1)

        used_first = {p.fake.get("first") for p in self.people}
        used_last = {p.fake.get("last") for p in self.people}
        words = len(last.split())
        pool = LAST_NAMES_TWO if words >= 2 else LAST_NAMES
        person = Person(
            tag=tag,
            real=dict({"first": first, "last": last, "middle": middle,
                       "emails": []},
                      **{f: "" for f in ID_KINDS}),
            fake=dict({"first": self._pick(FIRST_NAMES, used_first),
                       "last": self._pick(pool, used_last),
                       "middle": _initial_like(middle, self._rng),
                       "emails": []},
                      **{f: "" for f in ID_KINDS}),
        )
        self.people.append(person)
        for key in person.real_keys():
            self._index[key] = person
        self._absorb(person, fields)
        return person

    def _pick(self, pool, used):
        """A name not already taken, else a name with a number on it.

        Running out is possible -- sixty surnames against a large course
        -- and must not be silent, because a repeat would give two real
        students one fake identity. Numbering is ugly on purpose.
        """
        free = [w for w in pool if w not in used]
        if free:
            return self._rng.choice(free)
        for n in range(2, 1000):
            for word in pool:
                candidate = f"{word}{n}"
                if candidate not in used:
                    return candidate
        raise VaultError("ran out of fake names, which should be impossible.")

    # ----------------------------------------------------------- masking --

    def _stem(self, person, length):
        """A lower-case handle built from this person's fake name.

        Used for both a username and an email's local part, so that the
        twin keeps the *relationship* between a student's name and their
        login -- `tbayes0` next to `Bayes, Thomas`. A random string of
        the right length would hide that, and whether a username can be
        derived from a name is the sort of thing a join question turns
        on.

        Lower case throughout: a real local part is, and a twin that
        capitalises one is wrong about the shape of the thing being
        reasoned about.
        """
        made = ((person.fake.get("first") or "x")[:1]
                + re.sub(r"[^a-z]", "",
                         (person.fake.get("last") or "y").lower())).lower()
        want = length or len(made)
        made = made[:want]
        counter = 1
        while len(made) < want:
            made += str(counter % 10)
            counter += 1
        return made

    def _fake_id(self, field, core, person=None):
        """A fake *core* for an identifier: same length, same classes.

        Cores only. The punctuation an individual cell wore is re-applied
        by `_render`, so one person has one fake number however many
        shapes the real one is written in.

        A `handle` is built from the fake name instead of randomised,
        for the reason in `_stem`.
        """
        used = {p.fake.get(field) for p in self.people}
        if field == "handle" and person is not None:
            made = self._stem(person, len(core))
            bump = 1
            while made in used:
                tail = str(bump)
                made = made[:max(1, len(core) - len(tail))] + tail
                bump += 1
            return made

        keep = self.prefix_keep.get(field, 0)
        for _ in range(200):
            made = _like(core, self._rng, keep=keep)
            if made not in used:
                return made
        raise VaultError(f"could not invent an unused {field} like {core!r}.")

    def fake_domain(self, domain):
        """A stable fake for one real domain.

        Mapped rather than kept, and mapped *consistently*: two students
        on the same real domain land on the same fake one, and one
        student with two real domains keeps two different fake ones.
        """
        domain = domain.strip().lower()
        if not domain:
            return ""
        if domain not in self.domains:
            taken = set(self.domains.values())
            free = [d for d in FAKE_DOMAINS if d not in taken]
            self.domains[domain] = (
                free[0] if free
                else f"d{len(self.domains)}.example.org")
        return self.domains[domain]

    def _fake_email(self, address, person):
        """A fake address of the same length, on a mapped domain."""
        local, _, domain = address.rpartition("@")
        if not local:
            local, domain = address, ""
        want = len(local)
        made = self._stem(person, want)
        used = {a for p in self.people for a in (p.fake.get("emails") or [])}
        fake_domain = self.fake_domain(domain)
        candidate = f"{made}@{fake_domain}" if fake_domain else made
        bump = 1
        while candidate in used:
            tail = str(bump)
            base = (made[:max(1, want - len(tail))] + tail) if want else tail
            candidate = f"{base}@{fake_domain}" if fake_domain else base
            bump += 1
        return candidate

    def mask(self, kind, value, person):
        """The fake standing in for one real cell. Stable and recorded.

        Every literal that has ever been masked is kept on the person, so
        the same cell always masks the same way and every fake string
        that leaves the machine has a recorded way back.
        """
        value = "" if value is None else str(value)
        if not value.strip():
            return value
        if kind not in KINDS:
            raise VaultError(
                f"{kind!r} is not something this vault knows how to mask. "
                f"Expected one of {', '.join(KINDS)}."
            )
        if value in person.strings:
            return person.strings[value]
        made = self._render(kind, value, person)
        person.strings[value] = made
        return made

    def _render(self, kind, value, person):
        if kind in ID_KINDS:
            template, core, marker = decompose(value)
            if not person.real.get(kind):
                self._absorb(person, {kind: value})
            if (person.real.get(kind) or "").lower() == core.lower():
                fake_core = person.fake[kind]
            else:
                # A second, different id in the same field for one
                # person. Rare and probably a data error, but it is not
                # this module's job to decide that -- mask it as its own
                # number and leave the oddity visible in the twin.
                fake_core = self._fake_id(kind, core)
            return recompose(template, fake_core, marker)

        if kind == "email":
            address = _norm(value)
            reals = person.real.get("emails") or []
            if address not in reals:
                self._absorb(person, {"email": address})
                reals = person.real.get("emails") or []
            return (person.fake.get("emails") or [])[reals.index(address)]

        if kind == "first":
            return person.fake["first"]
        if kind == "last":
            return person.fake["last"]
        if kind == "middle":
            return person.fake.get("middle") or _initial_like(value, self._rng)

        return self._render_full(value, person)

    def _render_full(self, value, person):
        """A whole name, in the shape the cell wrote it.

        `Last, First M.` comes back as `Last, First M.` and `First Last`
        as `First Last`, because which form a file uses is exactly the
        sort of thing a reader of the twin needs to see.
        """
        from .classlist import split_full_name
        last, first, middle = split_full_name(value)
        fake_last = person.fake["last"]
        fake_first = person.fake["first"]
        fake_middle = (_initial_like(middle, self._rng) if middle else "")

        if "," in value:
            right = " ".join(w for w in (fake_first, fake_middle) if w)
            return f"{fake_last}, {right}".strip().rstrip(",")
        if not first and not middle:
            # A single word. Which part it is cannot be known, so the
            # surname is used -- it is the one a one-word cell usually is.
            return fake_last
        return " ".join(w for w in (fake_first, fake_middle, fake_last) if w)

    # -------------------------------------------------------- unmasking --

    def pairs(self):
        """Every reversible (fake, real) literal, longest fake first.

        Longest first so that replacing never eats a shorter string that
        is a prefix of a longer one -- an address whose local part is
        also a surname, for instance.

        A fake of one character is left out. It cannot be reversed
        safely: see `_initial_like`. Leaving it out means a middle
        initial stays masked, which is a visible gap; including it meant
        restoring the wrong letter, which was not.
        """
        out = []
        for person in self.people:
            for real, fake in person.strings.items():
                out.append((fake, real))
            for real, fake in zip(person.real.get("emails") or [],
                                  person.fake.get("emails") or []):
                out.append((fake, real))
            for field in ("first", "last") + ID_KINDS:
                if person.real.get(field) and person.fake.get(field):
                    out.append((person.fake[field], person.real[field]))
        for real, fake in self.domains.items():
            out.append((fake, real))
        seen, unique = set(), []
        for fake, real in out:
            if len(fake.strip()) < 2:
                continue
            if fake not in seen:
                seen.add(fake)
                unique.append((fake, real))
        unique.sort(key=lambda pair: len(pair[0]), reverse=True)
        return unique

    def unmask_text(self, text):
        """Put the real values back. Returns `(text, replacements)`.

        Works on any text, not only on a table: an answer, a diff, a
        patch, a column mapping. Matching is on word boundaries where
        the fake value is wordlike, so a surname cannot be replaced
        inside a longer word.

        The count is returned rather than printed so a caller can refuse
        a zero. A silent zero is the failure that matters here -- it
        reads as "nothing needed unmasking" and means "the vault does not
        describe this file".
        """
        hits = 0
        for fake, real in self.pairs():
            if not fake:
                continue
            if re.fullmatch(r"[\w.@+-]+", fake):
                pattern = r"(?<![\w.@+-])" + re.escape(fake) + r"(?![\w.@+-])"
            else:
                pattern = re.escape(fake)
            text, n = re.subn(pattern, real.replace("\\", "\\\\"), text)
            hits += n
        for person in self.people:
            pattern = r"\b" + re.escape(person.tag) + r"\b"
            name = " ".join(w for w in (person.real.get("first"),
                                        person.real.get("last")) if w)
            if name:
                text, n = re.subn(pattern, name, text)
                hits += n
        return text, hits

    # ------------------------------------------------------- the check --

    def real_values(self, min_length=3):
        """Every real string that must not appear in a masked file.

        The post-condition. A caller writes a twin, reads it back, and
        looks for any of these in it; if one is there, the twin is not a
        twin and must be destroyed rather than handed over.

        Short values are skipped because a two-letter surname or a
        one-digit section would match inside ordinary words and make the
        check useless by crying wolf. `min_length` is therefore a real
        hole in the check, and is named so it can be seen.
        """
        out = set()
        for person in self.people:
            for real in person.strings:
                out.add(real)
            for field in ("first", "last", "middle") + ID_KINDS:
                if person.real.get(field):
                    out.add(person.real[field])
            for address in person.real.get("emails") or []:
                out.add(address)
        out.update(self.domains)
        return {v for v in out if len(v.strip()) >= min_length}

    def leaks(self, text, min_length=3):
        """Which real values survive in this text. Empty is the good case."""
        low = text.lower()
        return sorted(v for v in self.real_values(min_length)
                      if v.lower() in low)
