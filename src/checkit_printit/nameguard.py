"""Refuse a commit or push that adds a real student. DESIGN.md section 20.

Run by the git hooks in `githooks/`, which the three repos (the
platform, printit, the mat-106 bank) point at with `core.hooksPath`;
and by hand as `checkit-printit names check`.

"Real" is anything in a roster, seating chart or vault under the print
home that does not belong to an invented course. A refusal names the file,
line and column and shows the value as its vault pseudonym, or `####` --
never the value itself, because an agent's transcript leaves the machine.

It fails closed: no roster to check against, a file that will not read, or
an allowlist that will not parse is a refusal, not a pass.
"""
import contextlib
import dataclasses
import fnmatch
import os
import pathlib
import re
import subprocess

try:
    import tomllib
except ModuleNotFoundError:                         # pragma: no cover
    import tomli as tomllib

CONFIG_NAME = "name-guard.toml"

#: A word, and anything shaped like an address. Matching is by set lookup
#: on these, so a name is only ever found as a whole word.
WORD = re.compile(r"\w+")
ADDRESS = re.compile(r"[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+")

#: Name words shorter than this are not checked: two letters match inside
#: initials and ordinary text everywhere.
MIN_NAME = 3


class GuardError(Exception):
    """The guard could not check, so it refuses. One sentence, no names."""


@dataclasses.dataclass
class Real:
    names: set        # name words, as written; capitals added below
    ids: set          # student ids, exact
    addresses: set    # lower case
    pseudonyms: dict  # real string -> its pseudonym, where a vault has one

    def __len__(self):
        return len(self.names) + len(self.ids) + len(self.addresses)


@dataclasses.dataclass
class Allow:
    invented_courses: set
    fine_words: set
    names_fine_in: list
    path: str

    def name_fine_in(self, where):
        return any(_glob(where, p) for p in self.names_fine_in)


@dataclasses.dataclass
class Hit:
    where: str        # "<repo>/<path>"
    line: int
    column: int
    kind: str         # "name", "id" or "address"
    shown: str        # pseudonym or ####
    commit: str = ""

    def __str__(self):
        at = f"{self.commit[:10]} " if self.commit else ""
        return (f"{at}{self.where}:{self.line}:{self.column}  "
                f"a real student's {self.kind} ({self.shown})")


def _glob(where, pattern):
    """gitignore-ish: `**` crosses folders, `*` does not."""
    rx = re.escape(pattern).replace(r"\*\*", "\0").replace(r"\*", "[^/]*")
    return re.fullmatch(rx.replace("\0", ".*"), where) is not None


def home_root():
    from . import record
    return pathlib.Path(record.home_root())


def load_allow(home):
    path = home / CONFIG_NAME
    if not path.is_file():
        return Allow(set(), set(), [], str(path))
    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise GuardError(f"{path} could not be read ({type(exc).__name__}), "
                         "so nothing can be checked") from None
    known = {"invented_courses", "fine_words", "names_fine_in"}
    unknown = set(raw) - known
    if unknown:
        raise GuardError(f"{path} has keys this guard does not know: "
                         f"{sorted(unknown)}; expected {sorted(known)}")
    fine = set(raw.get("fine_words", []))
    if any(any(c.isdigit() for c in w) or "@" in w for w in fine):
        raise GuardError(f"{path}: fine_words may hold names only -- an id or "
                         "an address is never fine")
    return Allow(set(raw.get("invented_courses", [])), fine,
                 list(raw.get("names_fine_in", [])), str(path))


@contextlib.contextmanager
def _unmasked_loading():
    """Load rosters without teaching a vault: with masking on,
    `roster.load` gives everyone it reads a pseudonym and saves the vault,
    and a check must not write the real home."""
    from . import privacy
    held = os.environ.pop(privacy.ENV, None)
    try:
        yield
    finally:
        if held is not None:
            os.environ[privacy.ENV] = held


def _invented(path, home, allow):
    parts = path.relative_to(home).parts
    return any(p in allow.invented_courses for p in parts[:-1]) or (
        parts[0] == "vaults" and path.stem in allow.invented_courses)


def _name_words(text):
    return {w for w in WORD.findall(text or "") if len(w) >= MIN_NAME
            and not w.isdigit()}


def load_real(home, allow):
    """Everything real under `home`, from every source that holds people."""
    from . import roster as roster_mod
    from . import seating as seating_mod
    from . import vault as vault_mod

    names, ids, addresses, pseudonyms = set(), set(), set(), {}
    files = 0
    with _unmasked_loading():
        for path in sorted(home.rglob("roster.toml")):
            if _invented(path, home, allow):
                continue
            try:
                people = roster_mod.load(str(path))
            except Exception as exc:                      # noqa: BLE001
                raise GuardError(f"{path} could not be read "
                                 f"({type(exc).__name__}), so nothing can be "
                                 "checked against it") from None
            files += 1
            for s in people:
                # `name_fields`, the one list every privacy path reads.
                for field in s.name_fields():
                    names |= _name_words(field)
                ids |= {v.strip() for v in (s.sid, s.alt_id) if v and v.strip()}
                addresses |= set(s.all_emails())
        for path in sorted(home.rglob("seating.toml")):
            if _invented(path, home, allow):
                continue
            try:
                chart = seating_mod.load(str(path))
            except Exception as exc:                      # noqa: BLE001
                raise GuardError(f"{path} could not be read "
                                 f"({type(exc).__name__})") from None
            files += 1
            # A seat is a Seat, not a string: a typed name (which need
            # not match the roster -- a misspelling is still a person) and
            # sometimes an id.
            for seat in chart:
                names |= _name_words(seat.name)
                if getattr(seat, "sid", None):
                    ids.add(str(seat.sid).strip())
        for path in sorted((home / "vaults").glob("*.json")):
            if _invented(path, home, allow):
                continue
            try:
                vault = vault_mod.Vault.load(str(path))
            except Exception as exc:                      # noqa: BLE001
                raise GuardError(f"{path} could not be read "
                                 f"({type(exc).__name__})") from None
            files += 1
            for real, fake in vault.substitutions():
                pseudonyms.setdefault(real, fake)
            # The person, field by field -- not `real_values()`, which
            # also holds the address domains ("example.edu" made "edu" a
            # real word) because a masked twin must not keep them either.
            for person in vault.people:
                for field in ("first", "last", "middle"):
                    names |= _name_words(person.real.get(field) or "")
                for field in vault_mod.ID_KINDS:
                    value = (person.real.get(field) or "").strip()
                    if value:
                        ids.add(value)
                for address in person.real.get("emails") or []:
                    addresses.add(address.strip().lower())
    if not files:
        raise GuardError(f"no roster, seating chart or vault of a real course "
                         f"under {home}, so there is nothing to check against")
    names -= allow.fine_words
    names |= {w.upper() for w in names}
    return Real(names, ids, addresses, pseudonyms)


def _shown(value, real):
    fake = real.pseudonyms.get(value)
    if fake is None and value.isupper():
        fake = next((f for r, f in real.pseudonyms.items()
                     if r.upper() == value), None)
    return f"[{fake}]" if fake else "####"


def scan_line(text, where, line, real, allow, commit=""):
    """Every real value on one line of `where` ("<repo>/<path>")."""
    hits = []
    names_ok = allow.name_fine_in(where)
    for m in ADDRESS.finditer(text):
        if m.group(0).lower() in real.addresses:
            hits.append(Hit(where, line, m.start() + 1, "address",
                            _shown(m.group(0), real), commit))
    for m in WORD.finditer(text):
        w = m.group(0)
        if w in real.ids:
            hits.append(Hit(where, line, m.start() + 1, "id", _shown(w, real), commit))
        elif not names_ok and w in real.names:
            hits.append(Hit(where, line, m.start() + 1, "name", _shown(w, real), commit))
    return hits


def _git(repo, *args, stdin=None):
    done = subprocess.run(["git", "-C", str(repo), *args], input=stdin,
                          capture_output=True)
    if done.returncode:
        raise GuardError(f"git {args[0]} failed in {repo}: "
                         f"{done.stderr.decode('utf-8', 'replace').strip()[:200]}")
    return done.stdout.decode("utf-8", "replace")


HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@")


def scan_patch(patch, repo_name, real, allow):
    """Added lines of a `git diff` / `git log -p` with -U0. Commit headers
    (from `--format=commit %H`) and messages are read too: a name in a
    commit message is as public as one in a file."""
    hits, where, line, commit, in_message = [], None, 0, "", False
    for raw in patch.splitlines():
        if raw.startswith("commit ") and len(raw) == 47:
            commit, where, in_message = raw[7:], None, True
            continue
        if in_message:
            if raw.startswith("diff --git "):
                in_message = False
            else:
                hits += scan_line(raw, f"{repo_name} (commit message)", 0,
                                  real, allow, commit)
                continue
        if raw.startswith("+++ "):
            path = raw[4:]
            where = None if path == "/dev/null" else f"{repo_name}/{path[2:]}"
        elif raw.startswith("@@"):
            m = HUNK.match(raw)
            line = int(m.group(1)) if m else 0
        elif raw.startswith("+") and where:
            hits += scan_line(raw[1:], where, line, real, allow, commit)
            line += 1
    return hits


def repo_name(repo):
    """The name the allowlist's "<repo>/<path>" patterns use: the folder,
    without the `.git` of a bare or mirror clone."""
    name = pathlib.Path(repo).resolve().name
    return name[:-4] if name.endswith(".git") else name


DIFF = ("-U0", "--no-color", "--no-ext-diff", "--no-renames", "--src-prefix=a/",
        "--dst-prefix=b/")


def staged(repo, real, allow):
    patch = _git(repo, "diff", "--cached", *DIFF)
    return scan_patch(patch, repo_name(repo), real, allow)


def commits(repo, revs, real, allow):
    """Every commit in `revs` (rev-list arguments), message and diff."""
    patch = _git(repo, "log", "-p", "--format=commit %H%n%B", *DIFF, *revs)
    return scan_patch(patch, repo_name(repo), real, allow)


ZERO = "0" * 40


def pushed(repo, refs_text, real, allow):
    """What `pre-push` is given on stdin: `<local ref> <sha> <remote ref> <sha>`
    per line. Every commit not already on the remote is read, so a value
    added and taken out again inside the push is still caught."""
    hits = []
    for row in refs_text.splitlines():
        parts = row.split()
        if len(parts) != 4 or parts[1] == ZERO:
            continue                                    # a delete
        local, remote = parts[1], parts[3]
        if remote != ZERO and _known(repo, remote):
            revs = [f"{remote}..{local}"]
        else:
            revs = [local, "--not", "--remotes"]
        hits += commits(repo, revs, real, allow)
    return hits


def _known(repo, sha):
    return subprocess.run(["git", "-C", str(repo), "cat-file", "-e", sha + "^{commit}"],
                          capture_output=True).returncode == 0


def history(repo, revs, real, allow):
    """Every version of every file reachable from `revs`, and every commit
    message -- read as whole files, not as diffs, because `git log -p`
    does not show what a merge commit brings in."""
    root = pathlib.Path(repo).resolve()
    hits, seen = [], set()
    listing = _git(repo, "rev-list", "--objects", *revs)
    wanted = []
    for row in listing.splitlines():
        sha, _, path = row.partition(" ")
        if path and (sha, path) not in seen:
            seen.add((sha, path))
            wanted.append((sha, path))
    batch = subprocess.run(["git", "-C", str(repo), "cat-file", "--batch"],
                           input="".join(f"{s}\n" for s, _ in wanted).encode(),
                           capture_output=True)
    if batch.returncode:
        raise GuardError(f"git cat-file failed in {repo}")
    out, at = batch.stdout, 0
    for sha, path in wanted:
        header_end = out.index(b"\n", at)
        _, kind, size = out[at:header_end].split()
        size = int(size)
        body = out[header_end + 1:header_end + 1 + size]
        at = header_end + 1 + size + 1
        if kind != b"blob":
            continue
        try:
            text = body.decode("utf-8")
        except UnicodeDecodeError:
            continue                                    # binary: DESIGN 20
        for n, line in enumerate(text.splitlines(), 1):
            hits += scan_line(line, f"{repo_name(repo)}/{path}", n, real, allow,
                              commit=f"blob {sha[:8]}")
    messages = _git(repo, "log", "--format=commit %H%n%B", *revs)
    hits += scan_patch(messages, repo_name(repo), real, allow)
    return hits


def tree(repo, real, allow):
    """Every tracked file as it is now."""
    root = pathlib.Path(repo).resolve()
    hits = []
    for name in _git(repo, "ls-files", "-z").split("\0"):
        if not name:
            continue
        try:
            text = (root / name).read_bytes().decode("utf-8")
        except (OSError, UnicodeDecodeError):
            continue                                    # binary: DESIGN 20
        for n, line in enumerate(text.splitlines(), 1):
            hits += scan_line(line, f"{repo_name(repo)}/{name}", n, real, allow)
    return hits
