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

    def test_a_refused_batch_writes_nothing(self, course):
        """All or nothing: a half-applied batch leaves the file disagreeing
        with the table still on screen."""
        with pytest.raises(gui_mod.GuiError):
            gui_mod.api_roster_save(course, {"edits": [
                {"index": 0, "field": "preferred", "value": "Ada L"},
                {"index": 0, "field": "sid", "value": "999"}]})
        assert list(gui_mod.Course("Test").roster())[0].preferred == ""


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
