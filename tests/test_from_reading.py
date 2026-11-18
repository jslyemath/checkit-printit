"""Faults the 2026-11-16 review found by reading, fixed 2026-11-17.

None of these had shipped anything wrong that anyone saw. Each test was run
against the code before its fix and failed there; see "The review's smaller
items" in ../checkit/CODEBASE_NOTES.md. Every name and id is invented.
"""

import os
import pathlib
import re
import sqlite3
import tomllib
import urllib.error

import pytest

from checkit_printit import classlist, course as course_mod, digits, fileio
from checkit_printit import form, gradebook as gb, record, roster as roster_mod
from checkit_printit import scans
from checkit_printit import gui as gui_mod
from checkit_printit.vault import Vault

from test_digits import fake_reader
import test_gradebook_export as gbx


# ------------------------------------------------------------- TOML ---

class TestOneTomlString:
    """Nine copies, none escaping a newline: a title pasted with a line
    break wrote a file that could not be read back."""

    @pytest.mark.parametrize("value", [
        "plain", 'a "quoted" word', "back\\slash", "two\nlines", "cr\rlf",
        "tab\there", "bell\x07", "del\x7f", "Ünïcödé — dash",
    ])
    def test_every_value_reads_back(self, value):
        assert tomllib.loads(f"x = {fileio.toml_string(value)}")["x"] == value

    def test_a_roster_name_with_a_line_break_survives(self, tmp_path):
        path = tmp_path / "roster.toml"
        path.write_text('[[student]]\nname = "Ada"\nskills = []\n',
                        encoding="utf-8")
        people = roster_mod.load(str(path))
        people.students[0].name = "Ada\nLovelace"
        assert tomllib.loads(roster_mod.to_toml(people))["student"][0]["name"] \
            == "Ada\nLovelace"


# ----------------------------------------------------- course.toml ---

class TestOneCourseReader:

    @pytest.fixture
    def home(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("P")
        return tmp_path

    def test_broken_toml_names_the_file(self, home):
        path = os.path.join(course_mod.path_for("P"), course_mod.CONFIG)
        with open(path, "a", encoding="utf-8") as f:
            f.write("\nthis is = = not toml\n")
        for read in (course_mod.thresholds, course_mod.identity,
                     course_mod.bank_path):
            with pytest.raises(course_mod.CourseError, match="course.toml"):
                read("P")


# ---------------------------------------------------------- record ---

def _write(db, run_id, date, built):
    record.write_run(db, run_id=run_id, title="T", date=date, built=built,
                     seed=1, output=f"/out/{run_id}", handouts=[])


class TestTheRecordMigratesOnce:
    """connect() ran the whole schema, four ALTER probes and a sweep of
    every run on every call."""

    def test_a_current_record_is_not_migrated_again(self, tmp_path):
        db = str(tmp_path / "record.db")
        record.connect(db).close()
        raw = sqlite3.connect(db)
        assert raw.execute("PRAGMA user_version").fetchone()[0] \
            == record.SCHEMA_VERSION
        # Remove something the schema makes; a migration would put it back.
        raw.execute("DROP TRIGGER run_with_marks_is_kept")
        raw.commit()
        raw.close()
        record.connect(db).close()
        raw = sqlite3.connect(db)
        names = [r[0] for r in raw.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'")]
        raw.close()
        assert "run_with_marks_is_kept" not in names

    def test_an_old_record_is(self, tmp_path):
        db = str(tmp_path / "record.db")
        record.connect(db).close()
        raw = sqlite3.connect(db)
        raw.execute("DROP TRIGGER run_with_marks_is_kept")
        raw.execute("PRAGMA user_version = 0")
        raw.commit()
        raw.close()
        record.connect(db).close()
        raw = sqlite3.connect(db)
        names = [r[0] for r in raw.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'")]
        raw.close()
        assert "run_with_marks_is_kept" in names


class TestADateThatIsNotIsoSortsByItsBuildDay:
    """`date` is free text from the CLI; "Week 4" sorted after every year."""

    def test_runs_in_order(self, tmp_path):
        db = str(tmp_path / "record.db")
        _write(db, "early", "Week 4", "2026-10-01T09:00:00")
        _write(db, "late", "2026-10-20", "2026-10-20T09:00:00")
        assert [r["run_id"] for r in record.runs(db)] == ["early", "late"]


# ---------------------------------------------------------- roster ---

class TestADropNeedsTheWholeName:
    """`roster drop ann` dropped Joanna when she was the only match."""

    @pytest.fixture
    def path(self, tmp_path):
        path = tmp_path / "roster.toml"
        path.write_text('[[student]]\nname = "Joanna Smith"\nsid = "800000001"\n'
                        'skills = []\n', encoding="utf-8")
        return str(path)

    def test_part_of_a_name_is_refused(self, path):
        with pytest.raises(roster_mod.NotFound, match="whole name"):
            roster_mod.set_dropped(path, "ann", True)
        assert not roster_mod.load(path).students[0].dropped

    def test_the_refusal_does_not_say_the_name(self, path):
        with pytest.raises(roster_mod.NotFound) as caught:
            roster_mod.set_dropped(path, "ann", True)
        assert "Joanna" not in str(caught.value)

    def test_the_whole_name_still_works(self, path):
        roster_mod.set_dropped(path, "joanna smith", True)
        assert roster_mod.load(path).students[0].dropped

    def test_looking_up_still_takes_a_piece(self, path):
        assert roster_mod.find(roster_mod.load(path), "ann").sid == "800000001"


# ----------------------------------------------------------- scans ---

class TestAnUnknownJobSaysWhy:
    """index_reader swallowed PageIndexError, which carries the fix."""

    def test_not_in_the_record(self, tmp_path):
        db = str(tmp_path / "record.db")
        record.connect(db).close()
        resolve = scans.index_reader(db)
        assert resolve(7) is None
        assert "no job" in resolve.why[7]

    def test_its_index_will_not_load(self, tmp_path):
        db = str(tmp_path / "record.db")
        folder = tmp_path / "gone"
        record.write_run(db, run_id="r", title="T", date="2026-10-01",
                         built="2026-10-01T09:00:00", seed=1,
                         output=str(folder), handouts=[], run_no=3)
        resolve = scans.index_reader(db)
        assert resolve(3) is None
        assert resolve.why[3]       # pageindex's own message, whatever it is

    def test_the_reason_reaches_the_sheet(self, tmp_path):
        db = str(tmp_path / "record.db")
        record.connect(db).close()
        resolve = scans.index_reader(db)
        resolve(7)
        sheet = scans.Sheet(source="s.pdf", scan_page=1, status="unknown-run",
                            reason=resolve.why[7])
        assert "no job" in sheet.reason


class TestTheGridIsDescribedOnce:
    """scans.py and printit.sty each state the id grid's size. A test is
    what keeps the two copies the same, since one is TeX."""

    def test_they_agree(self):
        sty = (pathlib.Path(scans.__file__).parent / "theme" / "printit.sty"
               ).read_text(encoding="utf-8")
        grid = sty[sty.index(r"\newcommand{\cipidgrid}"):]
        grid = grid[:grid.index(r"\newcommand", 10)]
        cell = float(re.search(r"\\setlength\{\\cipcell\}\{([\d.]+)mm\}", sty)[1])
        tall = float(re.search(r"\\rule\{0pt\}\{([\d.]+)mm\}", grid)[1])
        rule = float(re.search(r"\\fboxrule\}\{([\d.]+)pt\}", grid)[1])
        dividers = re.search(r"\\@tfor\\cipdiv:=(\d+)", grid)[1]
        assert scans.ID_CELL == pytest.approx(cell * scans.MM)
        assert scans.ID_TALL == pytest.approx(tall * scans.MM)
        assert scans.ID_RULE == pytest.approx(rule)
        assert scans.ID_COUNT == len(dividers) + 1


class TestIdsTheGridCannotCarry:

    def test_are_counted_at_import(self, tmp_path):
        path = tmp_path / "list.csv"
        path.write_text("Last,First,Student ID\nSmith,Ann,800000001\n"
                        "Jones,Bo,A12345\nLee,Cy,80000000\n", encoding="utf-8")
        _, _, notes = classlist.parse(str(path))
        assert any("2 student id(s) are not 9 digits" in n for n in notes)


# ---------------------------------------------------------- digits ---

class TestTwoCloseIdsAndAnUnclearCell:
    """The best id was taken with no lead over the next. Two ids that
    differ in one place were told apart by that one cell, however
    unclear it was."""

    def test_is_left_for_the_instructor(self, monkeypatch):
        import numpy

        def probabilities(pictures):
            p = numpy.full((9, 10), 0.001)
            for i, d in enumerate("800123456"):
                p[i, int(d)] = 0.99
            p[8, 6], p[8, 7] = 0.55, 0.45       # the last cell: 6 or 7?
            return p

        monkeypatch.setattr(digits, "probabilities", probabilities)
        cells = [numpy.zeros((28, 28))] * 9
        assert digits.pick(cells, ["800123456", "800123457"]) is None

    def test_a_clear_cell_still_decides(self, monkeypatch):
        cells = fake_reader(monkeypatch, "800123456", certainty=0.99)
        assert digits.pick(cells, ["800123456", "800123457"])[0] == "800123456"


# ------------------------------------------------------------ form ---

class TestATimeoutWhileConnecting:
    """Arrives wrapped in URLError, and was not retried."""

    def test_is_retried(self, monkeypatch):
        monkeypatch.setattr(form, "RETRY_WAIT", 0)
        calls = []

        class Answer:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return b'{"ok": true}'

        def opener(request, timeout):
            calls.append(1)
            if len(calls) == 1:
                raise urllib.error.URLError(TimeoutError("timed out"))
            return Answer()

        conn = form.Connection(url="https://example.org/x", secret="s")
        assert form.call(conn, "ping", opener=opener)["ok"]
        assert len(calls) == 2


# ------------------------------------------------------- gradebook ---

class TestAProfileCanOnlyNameARealField:
    """`matches = "handle"` passed validation and matched nobody."""

    def test_every_listed_field_is_a_student_field(self):
        student = roster_mod.Student(name="x", skills=[])
        for field in gb.ID_FIELDS:
            assert hasattr(student, field), field

    def test_handle_is_refused(self):
        with pytest.raises(gb.GradebookError, match="matches"):
            gbx.profile(student_matches="handle").validate()


def _export_bytes(preamble=True):
    lines = []
    if preamble:
        lines.append("Exported from the LMS on 2026-11-17")
    # OrgDefinedId first, as Brightspace writes it: the import file keeps
    # only the identifier the LMS matches on, and that is the one.
    lines.append(",".join(["OrgDefinedId"] + gbx.head()))
    lines.append(",".join(["#806000111", "806000111", "", "", "", "0", "3", "#"]))
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


class TestTheAppsExportWithAHeaderBelowLineOne:
    """The app passed every row of the file where the rows from the
    header down were meant, so `Sheet.head` was line 1 whatever the
    header row said. It also never ran through the CLI's checks, and the
    CLI never ran through the app's: both now go through `produce`."""

    @pytest.fixture
    def course(self, tmp_path, monkeypatch, students):
        class Course:
            name = "Gb"

            def file(self, kind):
                return str(tmp_path / f"{kind}.x")

        monkeypatch.setattr(gui_mod, "_bank_slugs_for", lambda c: gbx.SKILLS)
        monkeypatch.setattr(gui_mod, "_gradebook_profile",
                            lambda c: gbx.profile())
        monkeypatch.setattr(gui_mod.roster_mod, "load", lambda p: students)
        monkeypatch.setattr(gui_mod.record_mod, "progress", lambda p: gbx.progress(
            ("806000111", "W1", 1, "passed")))
        monkeypatch.setattr(gui_mod.course_mod, "thresholds", lambda n: {})
        gui_mod.CARRIED.clear()
        gui_mod.CARRIED.put("Gb", "MAT106-820.csv", _export_bytes())
        yield Course()
        gui_mod.CARRIED.clear()

    @pytest.fixture
    def students(self, tmp_path):
        path = tmp_path / "roster.toml"
        path.write_text(gbx.ROSTER, encoding="utf-8")
        return roster_mod.load(str(path))

    def test_the_pass_is_written(self, course):
        import base64
        out = gui_mod.api_gradebook_write(course, {"headerRow": 2})
        data = base64.b64decode(out["files"][0]["data"]).decode("utf-8")
        rows = gb.rows_of(data.encode("utf-8"))
        # The line above the header survives. `drop_columns` cuts it to
        # the kept columns like any other line, so it gains two empty
        # cells; nothing reads a line above the header.
        assert rows[0][0] == "Exported from the LMS on 2026-11-17"
        header, row = rows[1], rows[2]
        assert header[0] == "OrgDefinedId"
        assert row[header.index(gbx.head()[1])] == gbx.PASS


# ----------------------------------------------------------- vault ---

class TestTwoLetterSurnames:
    """`leaks` never looks for values under three letters."""

    def test_a_whole_cell_is_a_leak(self):
        vault = Vault(course="C", seed=0)
        vault.resolve({"first": "Ann", "last": "Wu"})
        assert vault.short_cell_leaks([["x", "Wu"], ["y", "z"]]) == ["Wu"]

    def test_inside_a_cell_it_is_not(self):
        vault = Vault(course="C", seed=0)
        vault.resolve({"first": "Ann", "last": "Wu"})
        assert vault.short_cell_leaks([["would", "a wurst"]]) == []


class TestATwinWithATwoLetterSurnameInIt:
    """End to end: a column kept on request still holds a surname."""

    def test_is_deleted_not_handed_over(self, tmp_path, monkeypatch):
        from checkit_printit import mask as mask_mod
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        src, out = str(tmp_path / "in.csv"), str(tmp_path / "out.csv")
        # Two letters each, so that only the new check can see them:
        # anything of three or more the ordinary scan finds already.
        mask_mod.write_csv(src, [["Last", "First", "Partner"],
                                 ["Wu", "Ann", "Ng"], ["Ng", "Bea", "Wu"]])
        with pytest.raises(mask_mod.MaskError, match="survived"):
            mask_mod.mask_file(src, out, Vault(course="C", seed=0),
                               keep=["Partner"])
        assert not os.path.exists(out)


class TestTagsAreMatchedInTheirOwnCase:
    """`unmask` turned a "P01" anywhere into a student's real name."""

    def test(self):
        vault = Vault(course="C", seed=0)
        person, _ = vault.resolve({"first": "Ann", "last": "Smith"})
        text, _ = vault.unmask_text(f"{person.tag} and {person.tag.upper()}")
        assert text == f"Ann Smith and {person.tag.upper()}"


# ----------------------------------------------------------- build ---

class TestAnUnwrittenRecordFailsTheBuild:
    """The record is the only account of who holds which paper. A build
    that could not write it printed one quiet line and exited 0."""

    def test(self, tmp_path, monkeypatch):
        from click.testing import CliRunner
        from checkit_printit import __main__ as cli

        class Result:
            compiled, preview, replayed = True, False, False
            out, pdf = "out", "out/main.pdf"
            record_error = "the disk is full"
            record_path, recorded, unnamed = "record.db", 0, 0
            replay_notes, replay_papers = [], 0
            theme_declared, theme_installed = False, ""

        monkeypatch.setattr(cli.runner, "run", lambda *a, **k: Result())
        monkeypatch.setattr(cli, "_report", lambda result: None)
        pub = tmp_path / "publication.toml"
        pub.write_text("", encoding="utf-8")
        got = CliRunner().invoke(cli.main, ["build", "-p", str(pub)])
        assert got.exit_code != 0
        assert "NOT written" in got.output and "the disk is full" in got.output


# ------------------------------------------------------------- app ---

class TestTheAppAnswersOnlyToItsOwnName:
    """DNS rebinding: a page whose own name points at 127.0.0.1 is
    same-origin as far as the browser knows, and could read the token."""

    @pytest.fixture
    def running(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("Test")
        httpd, url, token = gui_mod.serve("Test", port=0, open_browser=False,
                                          forever=False)
        import threading
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        yield httpd.server_address[1]
        httpd.shutdown()
        httpd.server_close()

    def ask(self, port, host):
        import socket
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.sendall(f"GET / HTTP/1.1\r\nHost: {host}\r\n"
                         "Connection: close\r\n\r\n".encode())
            chunks = []
            while data := sock.recv(4096):
                chunks.append(data)
        return b"".join(chunks)

    def test_another_name_is_refused(self, running):
        reply = self.ask(running, f"evil.example:{running}")
        assert b" 403 " in reply.split(b"\r\n", 1)[0]
        assert b"__TOKEN__" not in reply and b"<title>" not in reply

    def test_its_own_name_is_served(self, running):
        for host in (f"127.0.0.1:{running}", f"localhost:{running}"):
            assert b" 200 " in self.ask(running, host).split(b"\r\n", 1)[0]

    def test_a_sibling_folder_is_not_inside(self, tmp_path):
        assert gui_mod._within(str(tmp_path / "a" / "b"), str(tmp_path / "a"))
        assert not gui_mod._within(str(tmp_path / "a-old" / "b"),
                                   str(tmp_path / "a"))
