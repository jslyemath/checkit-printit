"""The local web app.

The handlers are ordinary functions taking (course, body), so most of this
needs no server. The few things that are genuinely about HTTP -- the token,
path traversal -- get a real one on a loopback port.
"""

import json
import os
import sys
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import course as course_mod
from checkit_printit import gui as gui_mod


ROSTER = '''[[student]]
name    = "Ada Lovelace"
sid     = "806001"
email   = "ada@example.edu"
section = "820"
skills  = ["W1"]

[[student]]
name    = "Bo Martin"
sid     = "806002"
email   = "bo@example.edu"
section = "830"
skills  = []
'''

SEATING = '''versions = ["A", "B"]

# table 1
[[group]]
seats = ["Ada Lovelace", "Bo Martin"]
'''


@pytest.fixture
def course(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    course_mod.init("Test", bank="", adopt=None)
    root = course_mod.path_for("Test")
    with open(os.path.join(root, "roster.toml"), "w", encoding="utf-8") as f:
        f.write(ROSTER)
    with open(os.path.join(root, "seating.toml"), "w", encoding="utf-8") as f:
        f.write(SEATING)
    return gui_mod.Course("Test")


class TestTheCourse:
    def test_a_course_that_does_not_exist_says_how_to_make_one(self, tmp_path,
                                                               monkeypatch):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        with pytest.raises(gui_mod.GuiError, match="course init"):
            gui_mod.Course("Nope")

    def test_the_summary_counts_only_the_undropped(self, course):
        gui_mod.api_roster_drop(course, {"who": "Bo Martin", "dropped": True})
        summary = gui_mod.api_course(course, {})
        assert summary["students"] == 2
        assert summary["active"] == 1
        assert summary["sections"] == {"820": 1}

    def test_it_reports_which_files_exist(self, course):
        files = gui_mod.api_course(course, {})["files"]
        assert files["roster"] and files["seating"]
        assert not files["record"]


class TestTheRosterTable:
    def test_it_lists_everyone_with_a_stable_index(self, course):
        rows = gui_mod.api_roster(course, {})["students"]
        assert [r["name"] for r in rows] == ["Ada Lovelace", "Bo Martin"]
        assert [r["index"] for r in rows] == [0, 1]

    def test_an_edit_reaches_the_file(self, course):
        gui_mod.api_roster_save(course, {"edits": [
            {"index": 0, "field": "preferred", "value": "Ada L"}]})
        again = gui_mod.Course("Test").roster()
        assert list(again)[0].preferred == "Ada L"

    def test_only_some_fields_are_editable(self, course):
        """Ids, the dropped flag and the accumulated addresses are set by an
        import, a drop or a pull, each of which has rules a text box would
        bypass."""
        for field in ("sid", "dropped", "emails", "alt_id", "skills"):
            with pytest.raises(gui_mod.GuiError, match="not editable"):
                gui_mod.api_roster_save(course, {"edits": [
                    {"index": 0, "field": field, "value": "x"}]})

    def test_a_blank_name_is_refused(self, course):
        """The name is what the seating chart matches on and what prints."""
        with pytest.raises(gui_mod.GuiError, match="needs a name"):
            gui_mod.api_roster_save(course, {"edits": [
                {"index": 0, "field": "name", "value": "   "}]})

    def test_a_row_that_is_not_there_says_to_reload(self, course):
        with pytest.raises(gui_mod.GuiError, match="Reload"):
            gui_mod.api_roster_save(course, {"edits": [
                {"index": 99, "field": "name", "value": "x"}]})

    def test_only_the_named_fields_move(self, course):
        """A save changes what it was asked to change and nothing else.

        Written after a scratch roster came back with a section edit that had
        been discarded in the browser. The discard turned out to be correct
        and the write came from an ad-hoc probe, but "a roster file changed
        and I cannot say which action did it" is worth making impossible to
        wonder about again.
        """
        before = {s.name: (s.section, s.email, s.sid, list(s.skills))
                  for s in course.roster()}
        gui_mod.api_roster_save(course, {"edits": [
            {"index": 0, "field": "preferred", "value": "Ada L"}]})
        after = {s.name: (s.section, s.email, s.sid, list(s.skills))
                 for s in gui_mod.Course("Test").roster()}
        assert before == after

    def test_an_empty_batch_changes_nothing(self, course):
        before = open(course.file("roster"), encoding="utf-8").read()
        gui_mod.api_roster_save(course, {"edits": []})
        assert open(course.file("roster"), encoding="utf-8").read() == before

    def test_a_refused_batch_writes_nothing(self, course):
        """All or nothing: a half-applied batch leaves the file disagreeing
        with the table still on screen."""
        with pytest.raises(gui_mod.GuiError):
            gui_mod.api_roster_save(course, {"edits": [
                {"index": 0, "field": "preferred", "value": "Ada L"},
                {"index": 0, "field": "sid", "value": "999"}]})
        assert list(gui_mod.Course("Test").roster())[0].preferred == ""


class TestSortingByName:
    """The roster holds one full name, because that is what prints and what
    the seating chart matches on. Surname and given-name order are derived
    for sorting and stored nowhere."""

    def _student(self, **kw):
        from checkit_printit.roster import Student
        kw.setdefault("skills", [])
        return Student(**kw)

    def test_a_plain_name_splits_the_obvious_way(self):
        assert gui_mod._sort_names(self._student(name="Ada Lovelace")) == \
            ("Lovelace", "Ada")

    def test_a_real_import_wins_over_the_guess(self):
        """`split_full_name` only gets a compound surname right from the
        comma form. Where an import has already filled the fields, they are
        used verbatim -- the guess is the fallback, never the override."""
        student = self._student(name="Belinda Soriano Garcia",
                                last="Soriano Garcia", first="Belinda")
        assert gui_mod._sort_names(student) == ("Soriano Garcia", "Belinda")

    def test_the_guess_is_wrong_on_a_compound_surname_and_that_is_why_it_is_not_saved(self):
        """Recorded rather than fixed. Guessing from `First Last` cannot get
        this right, so the guess is confined to sort order: a wrong guess
        puts one row in an odd place, which is visible, instead of writing a
        wrong surname into roster.toml, which is not."""
        assert gui_mod._sort_names(
            self._student(name="Belinda Soriano Garcia")) == ("Garcia", "Belinda")

    def test_a_one_word_name_does_not_crash(self):
        assert gui_mod._sort_names(self._student(name="Cher")) == ("Cher", "")

    def test_the_keys_reach_the_table(self, course):
        rows = gui_mod.api_roster(course, {})["students"]
        assert rows[0]["sort_last"] == "Lovelace"
        assert rows[0]["sort_first"] == "Ada"

    def test_they_are_not_editable(self, course):
        for field in ("sort_last", "sort_first"):
            with pytest.raises(gui_mod.GuiError, match="not editable"):
                gui_mod.api_roster_save(course, {"edits": [
                    {"index": 0, "field": field, "value": "x"}]})

    def test_nothing_derived_is_written_to_the_file(self, course):
        gui_mod.api_roster(course, {})
        gui_mod.api_roster_save(course, {"edits": [
            {"index": 0, "field": "preferred", "value": "Ada L"}]})
        text = open(course.file("roster"), encoding="utf-8").read()
        assert "sort_last" not in text and "sort_first" not in text
        # and the empty last/first stay empty rather than being filled in
        assert list(gui_mod.Course("Test").roster())[0].last == ""


class TestDropping:
    def test_it_goes_through_the_same_call_the_cli_makes(self, course):
        """Not a reimplementation: `roster.set_dropped` is the rule, and it
        empties the seat as well as flagging the roster."""
        out = gui_mod.api_roster_drop(course, {"who": "Ada Lovelace",
                                               "dropped": True})
        assert out["changed"]
        people = list(gui_mod.Course("Test").roster())
        assert people[0].dropped and people[0].dropped_by == "instructor"
        with open(course.file("seating"), encoding="utf-8") as f:
            assert "Ada Lovelace" not in f.read()

    def test_the_seat_is_emptied_not_removed(self, course):
        """Version letters come from position, so deleting the entry would
        re-letter that student's tablemates."""
        import tomllib
        gui_mod.api_roster_drop(course, {"who": "Ada Lovelace",
                                         "dropped": True})
        with open(course.file("seating"), "rb") as f:
            chart = tomllib.load(f)
        seats = chart["group"][0]["seats"]
        # Two seats still, the first now empty. One seat, or Bo in position 0,
        # would mean Bo had been re-lettered.
        assert seats == ["", "Bo Martin"]

    def test_restoring_does_not_give_a_seat_back(self, course):
        gui_mod.api_roster_drop(course, {"who": "Ada Lovelace", "dropped": True})
        out = gui_mod.api_roster_drop(course, {"who": "Ada Lovelace",
                                               "dropped": False})
        assert "no seat" in out["note"]
        with open(course.file("seating"), encoding="utf-8") as f:
            assert "Ada Lovelace" not in f.read()

    def test_dropping_someone_already_dropped_changes_nothing(self, course):
        gui_mod.api_roster_drop(course, {"who": "Ada Lovelace", "dropped": True})
        out = gui_mod.api_roster_drop(course, {"who": "Ada Lovelace",
                                               "dropped": True})
        assert not out["changed"] and "already" in out["note"]

    def test_a_name_matching_nobody_is_an_error(self, course):
        with pytest.raises(gui_mod.GuiError):
            gui_mod.api_roster_drop(course, {"who": "Nobody At All",
                                             "dropped": True})


class TestOverTheWire:
    """The parts that are genuinely about HTTP."""

    @pytest.fixture
    def running(self, course):
        httpd, url, token = gui_mod.serve(
            "Test", port=0, open_browser=False, forever=False)
        import threading
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield url, token
        httpd.shutdown()
        httpd.server_close()

    def _get(self, url, token=None):
        request = urllib.request.Request(url)
        if token is not None:
            request.add_header(gui_mod.TOKEN_HEADER, token)
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return response.status, json.loads(response.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read() or b"{}")

    def test_the_page_is_served(self, running):
        url, _ = running
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read().decode()
        assert "<title>checkit-printit</title>" in body

    def test_the_token_is_injected_into_the_page(self, running):
        url, token = running
        with urllib.request.urlopen(url, timeout=5) as response:
            body = response.read().decode()
        assert token in body and "__TOKEN__" not in body

    def test_an_api_call_without_the_token_is_refused(self, running):
        """Loopback stops another machine, not another page: any site open in
        the same browser can POST to 127.0.0.1 in the background."""
        url, _ = running
        code, payload = self._get(url + "api/roster")
        assert code == 403 and "token" in payload["error"]

    def test_a_wrong_token_is_refused(self, running):
        url, _ = running
        code, _ = self._get(url + "api/roster", "not-the-token")
        assert code == 403

    def test_the_right_token_works(self, running):
        url, token = running
        code, payload = self._get(url + "api/roster", token)
        assert code == 200 and len(payload["data"]["students"]) == 2

    @pytest.mark.parametrize("target", [
        "/../__init__.py",
        "/..%2f__init__.py",
        "/style.css/../../__init__.py",
    ])
    def test_a_path_cannot_escape_the_static_directory(self, running, target):
        """This process can read the instructor's whole home directory.

        Two things this test got wrong before, both of which made it pass with
        the guard deleted:

        1. It went through `urllib`, which normalises `../` out of a URL
           before it leaves, so the traversal was never attempted. Hence the
           raw socket.
        2. It aimed at a file that does not exist, so `os.path.isfile` refused
           it whether or not the guard was there. The target has to be a real
           file outside the static directory -- the package's own source is
           one, and always present.

        The two `../` cases fail if the guard is removed. The `%2f` case does
        not, because nothing here percent-decodes a path, so it is not a
        traversal today; it is kept as a regression guard for the day someone
        adds decoding, and is deliberately not counted as covering the guard.
        """
        import socket
        url, _ = running
        port = int(url.rstrip("/").rsplit(":", 1)[1])
        with socket.create_connection(("127.0.0.1", port), timeout=5) as sock:
            sock.sendall(
                f"GET {target} HTTP/1.1\r\nHost: 127.0.0.1\r\n"
                f"Connection: close\r\n\r\n".encode())
            chunks = []
            while True:
                data = sock.recv(4096)
                if not data:
                    break
                chunks.append(data)
        body = b"".join(chunks)
        assert b"404" in body.split(b"\r\n", 1)[0]
        assert b"GuiError" not in body       # i.e. the source did not come back

    def test_an_unknown_endpoint_says_so(self, running):
        url, token = running
        code, payload = self._get(url + "api/nope", token)
        assert code == 404 and "no such endpoint" in payload["error"]


class TestTheRunsTab:
    """Every handler is called at least once here.

    `api_run_reuse` shipped referring to a `pub_mod` that
    `gui/__init__.py` had never imported. 853 tests passed, because
    not one of them called it -- the NameError only appeared when the
    button was pressed in a browser. A handler no test calls is a
    handler nothing checks.
    """

    def runs_for(self, course):
        from checkit_printit import record
        record.write_run(
            course.file("record"), run_id="Checkpoint 2026-09-18",
            title="Checkpoint", date="2026-09-18",
            built="2026-09-18T10:00:00", seed=613,
            output=str(course.path), extras=0,
            handouts=[{"sid": "806001", "name": "Ada Lovelace",
                       "section": "820", "version": "A",
                       "papers": [("W1", 511), ("D1", 420)]},
                      {"sid": "806002", "name": "Bo Martin",
                       "section": "830", "version": "B",
                       "papers": [("W1", 802)]}])

    def test_a_course_with_no_record_lists_nothing_and_says_so(self, course):
        out = gui_mod.api_runs(course, {})
        assert out["runs"] == [] and out["delisted"] == []
        assert out["hasRecord"] is False

    def test_the_list_carries_what_the_table_shows(self, course):
        self.runs_for(course)
        row = gui_mod.api_runs(course, {})["runs"][0]
        assert row["title"] == "Checkpoint"
        assert row["papers"] == 3 and row["students"] == 2
        assert row["seed"] == 613
        assert row["delisted"] is False and row["graded"] is False

    def test_built_is_reported_separately_from_date(self, course):
        """They differ -- a run dated the 19th was built at 10:43 --
        and a list showing one could not explain two runs on a day."""
        self.runs_for(course)
        row = gui_mod.api_runs(course, {})["runs"][0]
        assert row["date"] == "2026-09-18"
        assert row["built"] == "2026-09-18T10:00:00"

    def test_a_missing_output_folder_is_flagged_not_hidden(self, course):
        """The record is the record. A run whose folder has moved is
        still listed; `onDisk` is how the view disables Reprint
        instead of offering a button that fails when pressed."""
        self.runs_for(course)
        assert gui_mod.api_runs(course, {})["runs"][0]["onDisk"] is True
        from checkit_printit import record
        import sqlite3
        db = sqlite3.connect(course.file("record"))
        db.execute("UPDATE run SET output = '/gone'")
        db.commit()
        db.close()
        assert gui_mod.api_runs(course, {})["runs"][0]["onDisk"] is False

    def test_the_detail_page(self, course):
        self.runs_for(course)
        run = gui_mod.api_run(course, {"id": "Checkpoint 2026-09-18"})["run"]
        assert {s["slug"] for s in run["skills"]} == {"W1", "D1"}
        assert len(run["seeds"]) == 3

    def test_an_unknown_run_says_so_rather_than_drawing_nothing(self, course):
        self.runs_for(course)
        with pytest.raises(gui_mod.GuiError, match="no run called"):
            gui_mod.api_run(course, {"id": "never"})

    def test_asking_for_no_run_at_all(self, course):
        with pytest.raises(gui_mod.GuiError, match="no run was named"):
            gui_mod.api_run(course, {})

    def test_delisting_moves_it_between_the_two_groups(self, course):
        self.runs_for(course)
        out = gui_mod.api_run_flag(
            course, {"id": "Checkpoint 2026-09-18", "delisted": True})
        assert out["runs"] == []
        assert [r["id"] for r in out["delisted"]] == ["Checkpoint 2026-09-18"]

    def test_delisting_a_graded_run_is_refused_through_the_view_too(
            self, course):
        self.runs_for(course)
        gui_mod.api_run_flag(course, {"id": "Checkpoint 2026-09-18",
                                      "graded": True})
        with pytest.raises(gui_mod.GuiError, match="cannot be delisted"):
            gui_mod.api_run_flag(course, {"id": "Checkpoint 2026-09-18",
                                          "delisted": True})

    def test_setting_nothing_is_refused(self, course):
        self.runs_for(course)
        with pytest.raises(gui_mod.GuiError, match="nothing to set"):
            gui_mod.api_run_flag(course, {"id": "Checkpoint 2026-09-18"})

    def name_a_bank(self, course, bank_dir):
        """Point the course at a bank. `publication.toml` requires
        one, and the shared fixture makes a course without."""
        config = os.path.join(course.path, "course.toml")
        with open(config, encoding="utf-8") as f:
            text = f.read()
        if "[bank]" in text:
            text = text.split("[bank]")[0]
        with open(config, "w", encoding="utf-8") as f:
            # A TOML *literal* string, single-quoted. In a basic string
            # a Windows path's backslashes are escapes, and this one
            # died on an invalid hex value before anything was read.
            f.write(text.rstrip("\n")
                    + "\n\n[bank]\npath = '" + str(bank_dir) + "'\n")

    def job_folder_for(self, course, **over):
        """A real job folder beside the record, as a finished run
        leaves behind. `folder_for` is what the handler uses to find
        it, so the test builds it in the same place rather than
        asserting a path it made up."""
        from checkit_printit import printjob
        draft = dict(printjob.load_draft("Test"))
        draft.update({"title": "Checkpoint", "date": "2026-09-18",
                      "mode": "same", "simply_print": ["W1"],
                      "variants": {"W1": "whole_numbers"},
                      "keys": False, "key_copies": 3})
        draft.update(over)
        return printjob.write_job("Test", draft, course_name="TEST 101")

    def test_reuse_carries_the_settings_over(self, course, bank_dir):
        """The happy path, and the only one that reads the old
        publication at all -- every refusal returns before it. That is
        why `pub_mod` could be missing from the imports while 853
        tests passed."""
        self.runs_for(course)
        self.name_a_bank(course, bank_dir)
        self.job_folder_for(course)
        out = gui_mod.api_run_reuse(course, {"id": "Checkpoint 2026-09-18"})
        draft = out["draft"]
        assert out["from"] == "Checkpoint 2026-09-18"
        assert draft["mode"] == "same"
        assert draft["simply_print"] == ["W1"]
        assert draft["variants"] == {"W1": "whole_numbers"}
        assert draft["keys"] is False and draft["key_copies"] == 3

    def test_reuse_does_not_carry_the_title_or_the_date(self, course,
                                                        bank_dir):
        """They are what made it *that* run. Copying them is how a
        fresh run comes out as a quiet duplicate of an old one -- and
        the date decides the folder name, so it would overwrite."""
        self.runs_for(course)
        self.name_a_bank(course, bank_dir)
        self.job_folder_for(course)
        before = dict(__import__("checkit_printit.printjob", fromlist=["x"])
                      .load_draft("Test"))
        draft = gui_mod.api_run_reuse(
            course, {"id": "Checkpoint 2026-09-18"})["draft"]
        assert draft["title"] == before["title"]
        assert draft["date"] == before["date"]

    def test_reuse_writes_nothing(self, course, bank_dir):
        """It fills the form and stops. The instructor saves it like
        any other edit, so there is something to discard."""
        from checkit_printit import printjob
        self.runs_for(course)
        self.name_a_bank(course, bank_dir)
        self.job_folder_for(course)
        before = printjob.load_draft("Test")
        gui_mod.api_run_reuse(course, {"id": "Checkpoint 2026-09-18"})
        assert printjob.load_draft("Test") == before

    def test_reuse_without_a_job_folder_says_where_it_looked(self, course):
        """The course here has a record but no job folder, which is
        exactly the state of a run whose folder was tidied away."""
        self.runs_for(course)
        with pytest.raises(gui_mod.GuiError, match="not on disk"):
            gui_mod.api_run_reuse(course, {"id": "Checkpoint 2026-09-18"})

    def test_replay_without_a_folder_says_so(self, course):
        self.runs_for(course)
        import sqlite3
        db = sqlite3.connect(course.file("record"))
        db.execute("UPDATE run SET output = '/gone'")
        db.commit()
        db.close()
        with pytest.raises(gui_mod.GuiError, match="not where the record"):
            gui_mod.api_run_replay(course, {"id": "Checkpoint 2026-09-18"})

    def test_reuse_and_replay_reject_an_unknown_run(self, course):
        self.runs_for(course)
        for handler in (gui_mod.api_run_reuse, gui_mod.api_run_replay):
            with pytest.raises(gui_mod.GuiError, match="no run called"):
                handler(course, {"id": "never"})
