"""Pseudonyms in place of real names, in everything the command line prints.

The standing rule is that a student's name never reaches a chat. An
assistant running printit reads what printit prints, so the rule used to
depend on the assistant remembering which commands print names -- `build`,
`roster import`, `roster drop`, `record student`, `form pull`, any error
that quotes a roster entry -- and not running them, or not looking.

With `CHECKIT_PRINTIT_MASK_NAMES=1` set, nothing has to be remembered:

* **Every person is given a pseudonym the moment printit reads them** --
  `roster.load`, `seating.load` and a class-list import call `saw` -- in
  the vault of the course the file belongs to (`vault.path_for`), the same
  vault `vault mask` uses, so a student has one pseudonym everywhere.
* **Everything written to stdout and stderr passes through every vault's
  `mask_text` on the way out** (`install`, called once by the CLI's entry
  point). One choke point rather than a mask at each `click.echo`: a name
  arrives in tracebacks and error messages from modules that never heard
  of this, and masking each print site is the "fix applied to one path"
  failure this project keeps meeting.

So the instructor can read anything an assistant quotes back by pasting it
into `checkit-printit vault unmask -c <course>`.

**It fails closed.** A vault that cannot be read or saved stops the
command with an error that names no one; output that cannot be masked is
withheld rather than printed.

Not covered: the web app's pages (they are the instructor's), and the
scripts under `tools/`, which do not go through the CLI's entry point.
"""

import os
import sys

ENV = "CHECKIT_PRINTIT_MASK_NAMES"

#: The vault for people read from a file outside any course folder. Still
#: masked; unmasked with `vault unmask -c unfiled`.
UNFILED = "unfiled"


import click


class PrivacyError(click.ClickException):
    """A ClickException, so the command line says it in one sentence
    rather than as a traceback; the web app reports it as an error like
    any other."""


def active():
    """Whether names are to be masked. Set the variable to 1 to turn it on."""
    return os.environ.get(ENV, "").strip() not in ("", "0", "false", "no")


def course_of(path):
    """The course a file belongs to, from where it sits; UNFILED if none.

    A course's state lives in `courses/<name>/`, so a file there belongs to
    `<name>`.
    """
    from . import course as course_mod
    root = os.path.normcase(os.path.abspath(course_mod.default_root()))
    folder = os.path.dirname(os.path.abspath(path))
    if os.path.normcase(os.path.dirname(folder)) == root:
        return os.path.basename(folder)
    return UNFILED


# Vaults opened in this process: {path: (vault, course, stamp)}. Shared
# with `mask`, so a person learned a moment ago is masked in the very next
# line printed.
#
# Keyed by the file, and re-read whenever the file has changed on disk.
# The web app is one long process; a vault it held from the morning and
# then saved would throw away every pseudonym `vault mask` had added since.
_open = {}


def _stamp(path):
    try:
        st = os.stat(path)
        return (st.st_mtime_ns, st.st_size)
    except OSError:
        return None


def _vault(course):
    from . import vault as vault_mod
    path = vault_mod.path_for(course)
    held = _open.get(path)
    if held is None or held[2] != _stamp(path):
        try:
            vault = vault_mod.Vault.open_or_create(path, course)
        except Exception as exc:                          # noqa: BLE001
            raise PrivacyError(
                f"names are being masked ({ENV} is set), and the vault for "
                f"{course!r} at {path} could not be opened: "
                f"{type(exc).__name__}. Nothing was printed. Fix the vault, "
                f"or unset {ENV} in a terminal of your own.") from None
        _open[path] = (vault, course, _stamp(path))
    return _open[path][0], path


def _size(vault):
    """People and spellings: what learning can add, and what needs saving."""
    return (len(vault.people), sum(len(p.strings) for p in vault.people))


def _keep(course, vault, path, before):
    if _size(vault) == before:
        return
    try:
        vault.save(path)
        _open[path] = (vault, course, _stamp(path))
    except Exception as exc:                              # noqa: BLE001
        raise PrivacyError(
            f"names are being masked ({ENV} is set), and the vault for "
            f"{course!r} could not be saved: {type(exc).__name__}. Nothing "
            f"was printed.") from None


def saw(people, where):
    """Give everybody in `people` (Students) a pseudonym, if masking is on.

    `where` is the file they were read from, or the one they are about to
    be written to, which says whose vault they belong in.
    """
    if not active():
        return
    from . import maskcourse
    course = course_of(where)
    vault, path = _vault(course)
    before = _size(vault)
    maskcourse.learn_students(vault, people)
    _keep(course, vault, path, before)


def saw_names(names, where):
    """`saw`, for bare names -- a seating chart holds nothing else."""
    if not active():
        return
    names = [n for n in names if n and str(n).strip()]
    if not names:
        return
    course = course_of(where)
    vault, path = _vault(course)
    before = _size(vault)
    vault.avoid([w for n in names for w in str(n).split()])
    for name in names:
        person, _ = vault.resolve({"full": str(name)})
        vault.mask("full", str(name), person)
    _keep(course, vault, path, before)


def mask(text):
    """`text` with every real value any vault knows replaced."""
    from . import vault as vault_mod
    root = vault_mod.default_root()
    if os.path.isdir(root):
        for name in sorted(os.listdir(root)):
            if name.endswith(".json") and \
                    os.path.join(root, name) not in _open:
                _vault(name[:-5])
    for path in list(_open):
        vault, _ = _vault(_open[path][1])         # re-read if it changed
        text, _ = vault.mask_text(text)
    return text


class _Masked:
    """A text stream that masks what is written to it.

    Deliberately no `buffer`: something that found one would write bytes
    past the mask.
    """

    def __init__(self, stream):
        self._stream = stream

    def write(self, text):
        # click writes bytes when it can, and a test runner's stream takes
        # them. Decoded to be masked -- a pattern cannot be matched in
        # bytes -- and written on as text.
        if isinstance(text, (bytes, bytearray)):
            text = bytes(text).decode(self.encoding or "utf-8", "replace")
        try:
            masked = mask(text)
        except PrivacyError as exc:
            # Its own message is written to name no one, and is the one
            # thing worth seeing: why nothing else can be shown.
            masked = f"[output withheld] {exc.message}\n"
        except Exception as exc:                          # noqa: BLE001
            masked = (f"[output withheld: it could not be masked "
                      f"({type(exc).__name__})]\n")
        self._stream.write(masked)
        return len(text)

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def flush(self):
        return self._stream.flush()

    def isatty(self):
        return self._stream.isatty()

    def fileno(self):
        raise OSError("a masked stream has no file descriptor")

    @property
    def encoding(self):
        return getattr(self._stream, "encoding", "utf-8")

    @property
    def errors(self):
        return getattr(self._stream, "errors", "strict")


def install():
    """Mask stdout and stderr for the rest of this process, if masking is on."""
    if not active():
        return
    if not isinstance(sys.stdout, _Masked):
        sys.stdout = _Masked(sys.stdout)
    if not isinstance(sys.stderr, _Masked):
        sys.stderr = _Masked(sys.stderr)
