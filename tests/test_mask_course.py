"""A masked twin of a whole course folder.

Every name here is invented. The folder is built by hand rather than
through `course init` so these tests do not need the session's bank.
"""

import json
import os
import sqlite3

import pytest

from checkit_printit import course as course_mod
from checkit_printit import maskcourse
from checkit_printit import record
from checkit_printit.maskcourse import CourseMaskError
from checkit_printit.vault import Vault

ROSTER = '''
[[student]]
name    = "Marguerite Vanterpool Reyes"
last    = "Vanterpool Reyes"
first   = "Marguerite"
sid     = "806000111"
alt_id  = "2041000001"
email   = "mvanter3@institute.edu"
emails  = ["m.vanterpool@clasnet.institute.edu"]
section = "820"
skills  = ["AD"]

[[student]]
name      = "Chidi Okonkwo"
last      = "Okonkwo"
first     = "Chidi"
preferred = "Chi Okonkwo"
sid       = "806000222"
alt_id    = "2041000002"
email     = "cokonkwo@institute.edu"
section   = "830"
skills    = ["SU"]

[[student]]
name    = "Benedict Fairweather"
last    = "Fairweather"
first   = "Benedict"
sid     = "806000333"
email   = "bfairwea@institute.edu"
section = "820"
dropped = true
skills  = []
'''

SEATING = '''
[[group]]
desks = ["Marguerite Vanterpool Reyes", "Chi Okonkwo"]
'''

ROOM = {"seats": [{"key": "806000111", "name": "Marguerite Vanterpool Reyes"},
                  {"key": "806000222", "name": "Chidi Okonkwo"}]}

COURSE = '''
title = "Test Course"
bank  = "../bank"
'''


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    return tmp_path


@pytest.fixture
def folder(home):
    """A course folder with every kind of file in it."""
    path = course_mod.path_for("Test")
    os.makedirs(path, exist_ok=True)
    write(os.path.join(path, "course.toml"), COURSE)
    write(os.path.join(path, "roster.toml"), ROSTER)
    write(os.path.join(path, "seating.toml"), SEATING)
    with open(os.path.join(path, "room.json"), "w", encoding="utf-8") as f:
        json.dump(ROOM, f)

    os.makedirs(os.path.join(path, "secrets"), exist_ok=True)
    write(os.path.join(path, "secrets", "token.json"),
          '{"refresh_token": "1//abcdef", "client_id": "x"}')
    os.makedirs(os.path.join(path, "scans"), exist_ok=True)
    write(os.path.join(path, "scans", "stack.pdf"), "%PDF-1.4 not really")
    write(os.path.join(path, "notes.rtf"), "Marguerite needs a retake")

    db = os.path.join(path, "record.db")
    record.write_run(
        db, run_id="first", title="Checkpoint", date="2026-10-01",
        built="2026-10-01T09:00:00", seed=1, output="/out/1", run_no=1,
        handouts=[{"sid": "806000111", "name": "Marguerite Vanterpool Reyes",
                   "section": "820", "version": "A",
                   "papers": [("AD", 401)]},
                  {"sid": "806000222", "name": "Chidi Okonkwo",
                   "section": "830", "version": "B",
                   "papers": [("SU", 402)]}])
    return path


def write(path, text):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def read(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        return f.read()


def every_text(root):
    """Everything written, as one string, databases dumped to SQL."""
    out = []
    for name in sorted(os.listdir(root)):
        path = os.path.join(root, name)
        if os.path.splitext(name)[1].lower() in maskcourse.DB_EXT:
            out.append(maskcourse.database_text(path))
        elif os.path.isfile(path):
            out.append(read(path))
    return "\n".join(out)


REAL = ["Vanterpool Reyes", "Marguerite", "Okonkwo", "Chidi", "Fairweather",
        "Benedict", "806000111", "806000222", "806000333", "2041000001",
        "mvanter3", "cokonkwo", "bfairwea", "institute.edu"]


# ------------------------------------------------------------ learning --

def test_it_learns_every_student_including_the_dropped_one(home, folder):
    """A dropped student is still in the record, so still needs a name."""
    vault = Vault(course="Test")
    count = maskcourse.learn(vault, os.path.join(folder, "roster.toml"))
    assert count == 3
    assert len(vault.people) == 3


def test_a_preferred_name_is_learned_too(home, folder):
    """`Chi Okonkwo` is what the chart says, and it is not the roster name."""
    vault = Vault(course="Test")
    maskcourse.learn(vault, os.path.join(folder, "roster.toml"))
    reals = {r for p in vault.people for r in p.strings}
    assert "Chi Okonkwo" in reals
    assert "Chidi Okonkwo" in reals
    assert "Okonkwo, Chidi" in reals


# ----------------------------------------------------------- the twin --

def test_nothing_real_survives_anywhere(home, folder, tmp_path):
    out = str(tmp_path / "twin")
    vault = Vault(course="Test")
    maskcourse.mask_course(folder, out, vault)

    text = every_text(out)
    assert vault.leaks(text) == []
    for value in REAL:
        assert value not in text, f"{value!r} survived"


def test_secrets_and_scans_are_never_copied(home, folder, tmp_path):
    out = str(tmp_path / "twin")
    vault = Vault(course="Test")
    report = maskcourse.mask_course(folder, out, vault)

    assert not os.path.exists(os.path.join(out, "secrets"))
    assert not os.path.exists(os.path.join(out, "scans"))
    skipped = dict(report.skipped)
    assert "credentials" in skipped["secrets/"]
    assert "handwriting" in skipped["scans/"]


def test_an_unrecognised_file_is_skipped_not_copied(home, folder, tmp_path):
    """`.rtf` is not a type this masks, and it holds a first name."""
    out = str(tmp_path / "twin")
    vault = Vault(course="Test")
    report = maskcourse.mask_course(folder, out, vault)

    assert not os.path.exists(os.path.join(out, "notes.rtf"))
    assert any(name == "notes.rtf" for name, _ in report.skipped)


def test_the_record_database_is_masked(home, folder, tmp_path):
    out = str(tmp_path / "twin")
    vault = Vault(course="Test")
    maskcourse.mask_course(folder, out, vault)

    with sqlite3.connect(os.path.join(out, "record.db")) as db:
        rows = db.execute("SELECT sid, name, section FROM printed").fetchall()
    assert len(rows) == 2
    for sid, name, section in rows:
        assert sid not in ("806000111", "806000222")
        assert "Okonkwo" not in name and "Vanterpool" not in name
        assert section in ("820", "830"), "a section was masked away"


def test_the_database_masking_is_schema_agnostic(home, folder, tmp_path):
    """A table nobody listed still gets masked.

    The alternative was naming `printed.name`, `printed.sid`,
    `attempt.sid` and `scan_page.sid` -- a list that goes stale the next
    time the schema grows, silently.
    """
    db_path = os.path.join(folder, "record.db")
    with sqlite3.connect(db_path) as db:
        db.execute("CREATE TABLE note (note_id INTEGER PRIMARY KEY, "
                   "who TEXT, body TEXT)")
        db.execute("INSERT INTO note (who, body) VALUES (?, ?)",
                   ("Chidi Okonkwo", "spoke to Marguerite about the retake"))
        db.commit()

    out = str(tmp_path / "twin")
    vault = Vault(course="Test")
    maskcourse.mask_course(folder, out, vault)

    with sqlite3.connect(os.path.join(out, "record.db")) as db:
        who, body = db.execute("SELECT who, body FROM note").fetchone()
    assert "Okonkwo" not in who
    assert "Marguerite" not in body
    assert "about the retake" in body, "the prose around the name was lost"


def test_a_preferred_name_gets_a_different_fake(home, folder):
    """Two real spellings of one student must not share one pseudonym.

    `name = "Chidi Okonkwo"` and `preferred = "Chi Okonkwo"` both
    rendered to the same fake name at first, because the fake given name
    does not depend on which real spelling was asked for. Unmasking then
    had to guess and put the roster spelling where the file said the
    preferred one.
    """
    vault = Vault(course="Test")
    maskcourse.learn(vault, os.path.join(folder, "roster.toml"))
    person = [p for p in vault.people if p.real["last"] == "Okonkwo"][0]
    assert person.strings["Chidi Okonkwo"] != person.strings["Chi Okonkwo"]

    # And the shortening is still visible as a shortening.
    long_one = person.strings["Chidi Okonkwo"].split()[0]
    short_one = person.strings["Chi Okonkwo"].split()[0]
    assert len(short_one) < len(long_one)
    assert long_one.startswith(short_one)


def test_the_real_to_fake_map_is_injective_for_every_person(home, folder):
    """The invariant behind unmasking, asserted rather than assumed.

    If one person's two real values share a pseudonym, unmasking cannot
    tell which was meant. Nothing checked this until it broke.
    """
    vault = Vault(course="Test")
    maskcourse.learn(vault, os.path.join(folder, "roster.toml"))
    for person in vault.people:
        fakes = list(person.strings.values())
        assert len(fakes) == len(set(fakes)), (
            f"{person.tag} has two real values sharing one pseudonym")


def test_the_twin_unmasks_back_to_the_original_roster(home, folder, tmp_path):
    out = str(tmp_path / "twin")
    vault = Vault(course="Test")
    maskcourse.mask_course(folder, out, vault)

    masked = read(os.path.join(out, "roster.toml"))
    back, hits = vault.unmask_text(masked)
    assert hits > 0
    assert back == read(os.path.join(folder, "roster.toml"))


@pytest.mark.parametrize("ending", ["\n", "\r\n"])
def test_line_endings_survive_the_round_trip(home, folder, tmp_path, ending):
    """Byte for byte, both ways.

    This was wrong, and quietly: reading with universal newlines turned
    a CRLF file into LF and the write emitted LF, so the twin differed
    from the original on every line. A diff between a twin and the file
    it came from was then worthless -- which is most of what a twin is
    for. The earlier test compared strings read back through universal
    newlines, so it could not see this at all.
    """
    import re
    from checkit_printit import mask as mask_mod

    source = os.path.join(folder, "roster.toml")
    body = re.sub(r"\r?\n", ending, ROSTER)
    with open(source, "w", encoding="utf-8", newline="") as f:
        f.write(body)

    out = str(tmp_path / "twin")
    vault = Vault(course="Test")
    maskcourse.mask_course(folder, out, vault)

    twin = os.path.join(out, "roster.toml")
    with open(twin, "rb") as f:
        raw = f.read()
    assert raw.count(ending.encode()) == body.count(ending)
    if ending == "\r\n":
        assert raw.count(b"\n") == raw.count(b"\r\n"), "a bare LF crept in"

    back = str(tmp_path / "back.toml")
    mask_mod.unmask_file(twin, back, vault)
    assert mask_mod.unmask_bytes_identical(source, back)


# -------------------------------------------------------- the refusals --

def test_it_refuses_to_write_inside_the_course_folder(home, folder):
    vault = Vault(course="Test")
    with pytest.raises(CourseMaskError, match="inside the course folder"):
        maskcourse.mask_course(folder, os.path.join(folder, "twin"), vault)


def test_it_refuses_to_write_under_the_courses_root(home, folder):
    vault = Vault(course="Test")
    target = os.path.join(course_mod.default_root(), "Twin")
    with pytest.raises(CourseMaskError, match="where the courses live"):
        maskcourse.mask_course(folder, target, vault)


def test_it_refuses_a_folder_with_no_roster(home, tmp_path):
    bare = tmp_path / "bare"
    bare.mkdir()
    write(str(bare / "course.toml"), COURSE)
    vault = Vault(course="Test")
    with pytest.raises(CourseMaskError, match="no roster.toml"):
        maskcourse.mask_course(str(bare), str(tmp_path / "twin"), vault)


def test_it_refuses_a_destination_that_is_not_empty(home, folder, tmp_path):
    out = tmp_path / "twin"
    out.mkdir()
    write(str(out / "something"), "x")
    vault = Vault(course="Test")
    with pytest.raises(CourseMaskError, match="not empty"):
        maskcourse.mask_course(folder, str(out), vault)


# ------------------------------------------------------- the sniffer --

def test_a_stray_address_fails_and_the_output_is_removed(home, folder,
                                                         tmp_path):
    """An address the roster never carried cannot be substituted.

    Substitution only replaces what `learn` learned, so this is exactly
    the hole the sniffer exists to cover.
    """
    write(os.path.join(folder, "course.toml"),
          COURSE + '\ncontact = "a.lecturer@institute.edu"\n')
    out = str(tmp_path / "twin")
    vault = Vault(course="Test")
    with pytest.raises(CourseMaskError, match="address-shaped"):
        maskcourse.mask_course(folder, out, vault)
    assert not os.path.exists(out), "a half-masked folder was left behind"


def test_a_long_number_fails_until_it_is_allowed(home, folder, tmp_path):
    write(os.path.join(folder, "course.toml"),
          COURSE + "\nseed = 1234567890123\n")
    vault = Vault(course="Test")
    with pytest.raises(CourseMaskError, match="9\\+ digit"):
        maskcourse.mask_course(folder, str(tmp_path / "a"), vault)

    vault = Vault(course="Test")
    report = maskcourse.mask_course(folder, str(tmp_path / "b"), vault,
                                    allow_digits=True)
    assert os.path.isdir(report.out_path)


def test_a_twin_that_cannot_be_deleted_is_reported(home, folder, tmp_path,
                                                   monkeypatch):
    """The clean-up used `ignore_errors=True`, and that was a lie.

    A SQLite connection left open -- `with sqlite3.connect(...)` commits
    but does not close -- locked the file on Windows, the removal failed,
    and the call returned quietly, leaving a half-masked course folder
    on disk under a message saying it had been destroyed. The
    connections are closed now; this asserts the other half, that a
    removal which still fails is not swallowed.
    """
    write(os.path.join(folder, "course.toml"),
          COURSE + '\ncontact = "a.lecturer@institute.edu"\n')

    def refuse(path):
        raise OSError("in use by another process")

    monkeypatch.setattr(maskcourse.shutil, "rmtree", refuse)
    vault = Vault(course="Test")
    with pytest.raises(CourseMaskError, match="could not be deleted"):
        maskcourse.mask_course(folder, str(tmp_path / "twin"), vault)


def test_a_fake_id_does_not_trip_the_digit_sniffer(home, folder, tmp_path):
    """The pseudonyms are 9 and 10 digits long themselves."""
    out = str(tmp_path / "twin")
    vault = Vault(course="Test")
    maskcourse.mask_course(folder, out, vault)
    addresses, digits = maskcourse.residual(every_text(out), vault)
    assert addresses == []
    assert digits == []


def test_the_failure_names_files_and_lines_but_no_values(home, folder,
                                                         tmp_path):
    write(os.path.join(folder, "course.toml"),
          COURSE + '\ncontact = "a.lecturer@institute.edu"\n')
    vault = Vault(course="Test")
    with pytest.raises(CourseMaskError) as caught:
        maskcourse.mask_course(folder, str(tmp_path / "twin"), vault)
    message = str(caught.value)
    assert "course.toml" in message
    assert "line" in message
    assert "a.lecturer" not in message
    assert "institute.edu" not in message


# --------------------------------------------------------- masking text --

def test_prose_is_masked(home, folder, tmp_path):
    vault = Vault(course="Test")
    maskcourse.learn(vault, os.path.join(folder, "roster.toml"))
    source = str(tmp_path / "trace.txt")
    write(source, "KeyError: 'Chidi Okonkwo' while seating 806000222\n")
    out = str(tmp_path / "trace-masked.txt")
    hits = maskcourse.mask_text_file(source, out, vault)

    text = read(out)
    assert hits >= 2
    assert "Okonkwo" not in text
    assert "806000222" not in text
    assert text.startswith("KeyError: '")


def test_masking_text_is_case_insensitive(home, folder):
    """A roster lower-cases an address; a log may not."""
    vault = Vault(course="Test")
    maskcourse.learn(vault, os.path.join(folder, "roster.toml"))
    out, hits = vault.mask_text("sent to COKONKWO@INSTITUTE.EDU")
    assert hits >= 1
    assert "COKONKWO" not in out.upper().replace("EXAMPLE.ORG", "")


def test_masking_text_does_not_match_inside_a_longer_word(home, folder):
    vault = Vault(course="Test")
    maskcourse.learn(vault, os.path.join(folder, "roster.toml"))
    out, hits = vault.mask_text("the Okonkwonian conjecture")
    assert hits == 0
    assert out == "the Okonkwonian conjecture"


def test_the_longest_name_is_replaced_before_its_parts(home, folder):
    """`Vanterpool Reyes` must not be masked as `Reyes` twice over."""
    vault = Vault(course="Test")
    maskcourse.learn(vault, os.path.join(folder, "roster.toml"))
    person = [p for p in vault.people
              if p.real["last"] == "Vanterpool Reyes"][0]
    out, _ = vault.mask_text("seating Marguerite Vanterpool Reyes now")
    assert person.fake["last"] in out
    assert len(person.fake["last"].split()) == 2
