"""Six things reported against the Print job view, and what they needed.

The two with teeth:

`open the folder` answered with nothing at all. `sys` was never imported, so
`sys.platform` raised NameError, the handler died before writing a response,
and the browser could only say the fetch failed. Both halves are covered
here -- the import, and a server that answers when a handler raises
something nobody expected.

A version can now be a letter the seating chart has never heard of, because
that is how one is added from the table. `assemble` has to draw seeds for
it, or the pin arrives at `build_handouts` and is reported as a skill
missing from the bank.

No real student appears here.
"""

import json
import os
import sys
import threading
import urllib.error
import urllib.request

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import assemble as assemble_mod
from checkit_printit import course as course_mod
from checkit_printit import gui as gui_mod
from checkit_printit import printjob as printjob_mod
from checkit_printit import publication as pub_mod
from checkit_printit import seating as seating_mod


def chart_of(*letters):
    return seating_mod.Chart(
        seats=[seating_mod.Seat(name=f"S{i}", group=0, version=v)
               for i, v in enumerate(letters)],
        versions=tuple(letters))


class TestEveryLetterAPinNamesGetsSeeds:
    """`versions_for` is the rule; the test that it is *used* is below."""

    def pub(self, **kw):
        return pub_mod.Publication(bank_path="x", roster_path=None,
                                   seating_path=None, **kw)

    def test_with_no_pins_it_is_the_charts_list(self):
        chart = chart_of("A", "B")
        assert assemble_mod.versions_for(chart, self.pub()) == ["A", "B"]

    def test_a_pin_beyond_the_chart_is_added(self):
        chart = chart_of("A", "B")
        pub = self.pub(student_versions={"806001": "E"})
        assert assemble_mod.versions_for(chart, pub) == ["A", "B", "E"]

    def test_a_pin_the_chart_already_has_adds_nothing(self):
        chart = chart_of("A", "B")
        pub = self.pub(student_versions={"806001": "B"})
        assert assemble_mod.versions_for(chart, pub) == ["A", "B"]

    def test_the_first_letter_does_not_move(self):
        """`versions[0]` is what an unseated student is given, so sorting
        the new letter in would reseat people who were never pinned."""
        chart = chart_of("C", "D")
        pub = self.pub(student_versions={"806001": "A"})
        assert assemble_mod.versions_for(chart, pub)[0] == "C"

    def test_without_a_chart_there_is_still_a_default(self):
        pub = self.pub(student_versions={"806001": "B"})
        assert assemble_mod.versions_for(None, pub) == ["A", "B"]

    def test_the_build_actually_draws_them(self, bank_dir, tmp_path):
        """The wiring. Reverting the call site to `list(chart.versions)`
        leaves every test above green and the bug exactly as it was."""
        from checkit_printit.roster import Roster, Student
        people = Roster([Student(name="Ada Lovelace", skills=["AD"],
                                 sid="806001")])
        chart = seating_mod.Chart(
            seats=[seating_mod.Seat(name="Ada Lovelace", group=0, version="A")],
            versions=("A", "B"))
        publication = pub_mod.Publication(
            bank_path=bank_dir, roster_path=None, seating_path=None,
            simply_print=("AD",), student_versions={"806001": "E"})
        report = assemble_mod.assemble(publication, people, chart,
                                       str(tmp_path / "out"), None,
                                       dry_run=True)
        assert ("E", "AD") in report["seeds"], \
            "no seeds for the pinned letter; the pin would read as a bad slug"
        assert report["handouts"][0]["version"] == "E"


class TestTheWrongFaultWasReported:
    def test_a_pin_with_no_paper_says_so(self):
        """It used to say the student had asked for a skill that is in the
        bank, which sends you to the wrong file."""
        from checkit_printit.roster import Roster, Student
        people = Roster([Student(name="Ada Lovelace", skills=["AD"],
                                 sid="806001")])
        chart = chart_of("A", "B")
        chart.seats[0].name = "Ada Lovelace"

        class Pub:
            student_versions = {"806001": "E"}
            names = True
        with pytest.raises(assemble_mod.AssemblyError,
                           match="pinned to version 'E'"):
            assemble_mod.build_handouts(people, chart, Pub(),
                                        {("A", "AD"): 401, ("B", "AD"): 402})


class TestOpeningTheFolder:
    @pytest.fixture
    def rooted(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        return tmp_path

    def test_it_opens_one_printit_wrote(self, rooted, monkeypatch):
        opened = []
        monkeypatch.setattr(gui_mod.os, "startfile",
                            lambda p: opened.append(p), raising=False)
        monkeypatch.setattr(gui_mod.sys, "platform", "win32")
        folder = rooted / "MAT 106" / "Redo 2026-10-02"
        folder.mkdir(parents=True)
        out = gui_mod.api_print_reveal(None, {"path": str(folder)})
        assert out["opened"] == str(folder)
        assert opened == [str(folder)]

    def test_sys_is_imported(self):
        """The whole fault: `sys.platform` on a module that never imported
        `sys`. A NameError here reaches the browser as "failed to fetch",
        because the handler dies before writing anything."""
        assert gui_mod.sys is sys

    def test_somewhere_else_on_the_disk_is_refused(self, rooted):
        with pytest.raises(gui_mod.GuiError, match="not a printit output"):
            gui_mod.api_print_reveal(None, {"path": str(rooted.parent)})

    def test_a_folder_that_has_gone_is_refused(self, rooted):
        with pytest.raises(gui_mod.GuiError, match="not there any more"):
            gui_mod.api_print_reveal(None, {"path": str(rooted / "gone")})


class TestAnUnexpectedFaultStillAnswers:
    """A handler that raises something unplanned used to kill the
    connection, and the browser could only say the fetch failed -- which is
    the least useful thing it could say and is what hid a missing import.
    """

    @pytest.fixture
    def running(self, tmp_path, monkeypatch, bank_dir):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("P", bank=str(bank_dir), adopt=None)
        httpd, url, token = gui_mod.serve("P", port=0, open_browser=False,
                                          forever=False)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        yield url, token
        httpd.shutdown()
        httpd.server_close()

    def _post(self, url, token, path, body=None):
        req = urllib.request.Request(
            url.rstrip("/") + path,
            data=json.dumps(body or {}).encode(),
            headers={"Content-Type": "application/json",
                     gui_mod.TOKEN_HEADER: token})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, json.loads(r.read())
        except urllib.error.HTTPError as exc:
            return exc.code, json.loads(exc.read())

    def test_it_returns_a_message_rather_than_closing(self, running,
                                                      monkeypatch):
        url, token = running

        def explode(_course, _body):
            raise ZeroDivisionError("something nobody planned for")

        monkeypatch.setitem(gui_mod.ROUTES, "/api/print/reveal", explode)
        status, payload = self._post(url, token, "/api/print/reveal")
        assert status == 500
        assert "ZeroDivisionError" in payload["error"]
        assert "nobody planned for" in payload["error"]

    def test_a_rule_saying_no_is_still_a_400(self, running):
        """Broadening the catch must not turn every refusal into a crash."""
        url, token = running
        status, payload = self._post(url, token, "/api/print/reveal",
                                     {"path": "C:/nowhere"})
        assert status == 400
        assert "printit output folder" in payload["error"]


class TestResettingTheWholeJob:
    @pytest.fixture
    def course(self, tmp_path, monkeypatch, bank_dir):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("P", bank=str(bank_dir), adopt=None)
        return gui_mod.Course("P")

    def test_the_view_is_told_what_empty_looks_like(self, course):
        """Reset is an ordinary edit the Discard button can undo, so the
        client fills the draft with these rather than calling a second
        endpoint that writes the file behind Discard's back."""
        out = gui_mod.api_print(course, {})
        assert out["defaults"] == printjob_mod.DEFAULTS

    def test_the_defaults_are_a_copy(self, course):
        """Handing out the module's own dict would let one request's edit
        change what every later one calls empty."""
        out = gui_mod.api_print(course, {})
        out["defaults"]["title"] = "mutated"
        assert printjob_mod.DEFAULTS["title"] != "mutated"


class TestTheBuildReportNamesCollisions:
    """`printed_collisions` returns triples now. The CLI was updated and
    this path was not, so any build with a collision raised a ValueError
    inside the GUI -- a crash reachable only by the rare case the warning
    exists for."""

    @pytest.fixture
    def course(self, tmp_path, monkeypatch, bank_dir):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("P", bank=str(bank_dir), adopt=None)
        return gui_mod.Course("P")

    def test_a_collision_becomes_a_sentence(self, course, monkeypatch):
        seat = seating_mod.Seat(name="Ada Lovelace", group=2, version="A")
        other = seating_mod.Seat(name="Grace Hopper", group=2, version="B")

        class Result:
            out = "out"
            run_seed = 1
            pdf = None
            recorded = 0
            record_error = ""
            theme_installed = ""
            unmatched_overrides = ()
            report = {"students": 2, "extras": 0, "skills": [], "versions": 0,
                      "keys": 0, "seeds": {}, "unseated": [],
                      "missing_fields": {},
                      "collisions": [(seat, other, "B")]}

        monkeypatch.setattr(gui_mod.printjob_mod, "write_job",
                            lambda *a, **k: "folder")
        monkeypatch.setattr(gui_mod.runner_mod, "run", lambda *a, **k: Result())
        out = gui_mod._build(course, preview=True)
        assert out["collisions"] == [
            "Ada Lovelace and Grace Hopper were both printed version B "
            "at table 2"]
