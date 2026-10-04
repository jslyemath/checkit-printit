"""Connecting a course to a form, from either front end.

Nothing here talks to Google or runs clasp. What is worth testing is the
part that is not the network: that the deploy is *saved* before the step
where Google may refuse, that refusal is a resumable state rather than a
failure, and that the view is told enough to draw itself.

The resumability is the one with teeth. Without it, a create that stops at
"not authorized yet" leaves a real form and a real web app in the
instructor's Drive with nothing recorded, and the obvious next move --
press the button again -- makes a second one.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import clasp as clasp_mod
from checkit_printit import course as course_mod
from checkit_printit import form as form_mod
from checkit_printit import gui as gui_mod
from checkit_printit import provision as provision_mod


@pytest.fixture
def space(tmp_path, monkeypatch, bank_dir):
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    course_mod.init("P", bank=str(bank_dir), adopt=None)
    return "P"


@pytest.fixture
def no_clasp(monkeypatch):
    """clasp, stubbed down to the three calls a deploy makes."""
    monkeypatch.setattr(clasp_mod, "push", lambda d: None)
    monkeypatch.setattr(clasp_mod, "deploy", lambda d, description="": "DEP1")
    monkeypatch.setattr(clasp_mod, "web_app_url",
                        lambda dep: f"https://script.example/{dep}/exec")


def answers(monkeypatch, **extra):
    """The Apps Script, stubbed. Records what it was asked."""
    asked = []

    def call(conn, what, payload=None):
        asked.append(what)
        if what in extra:
            return extra[what]
        if what == "ping":
            return {"form": "A Form", "formId": "FORM1",
                    "editUrl": "https://forms.example/edit"}
        if what == "rename":
            return {"form": "Renamed", "formId": "FORM1"}
        if what == "addItems":
            return {"items": {k: f"id-{k}" for k in form_mod.SLOTS}}
        if what == "configure":
            return {"did": ["required login"], "skipped": []}
        return {}

    monkeypatch.setattr(form_mod, "call", call)
    return asked


class TestTheDeployIsSavedBeforeGoogleCanRefuse:
    """The form and the web app are real by then. A course that recorded
    nothing would start over and make a second one."""

    def test_a_refusal_still_leaves_the_connection_on_disk(
            self, space, monkeypatch, no_clasp):
        def refuse(conn, what, payload=None):
            raise form_mod.FormError("403")
        monkeypatch.setattr(form_mod, "call", refuse)

        conn = form_mod.load(course_mod.path_for(space))
        conn.secret = "s"
        with pytest.raises(provision_mod.NeedsAuthorization):
            provision_mod.deploy_and_record(space, "dir", conn)

        again = form_mod.load(course_mod.path_for(space))
        assert again.url, "the deploy was not recorded, so a retry makes a second form"

    def test_the_refusal_carries_the_url_to_authorize(self, space,
                                                      monkeypatch, no_clasp):
        monkeypatch.setattr(form_mod, "call",
                            lambda *a, **k: (_ for _ in ()).throw(
                                form_mod.FormError("403")))
        conn = form_mod.load(course_mod.path_for(space))
        conn.secret = "s"
        try:
            provision_mod.deploy_and_record(space, "dir", conn)
        except provision_mod.NeedsAuthorization as needs:
            assert needs.url.endswith("/exec")
            assert "grant the" in provision_mod.prompt(needs.url)
        else:
            pytest.fail("it did not raise")


class TestFinishingAfterAuthorization:
    def test_it_adds_the_items_and_saves(self, space, monkeypatch):
        conn = form_mod.load(course_mod.path_for(space))
        conn.url, conn.secret = "https://script.example/x/exec", "s"
        form_mod.save(course_mod.path_for(space), conn)
        answers(monkeypatch)

        provision_mod.finish(space)
        after = form_mod.load(course_mod.path_for(space))
        assert set(after.items) == set(form_mod.SLOTS)
        assert after.form_id == "FORM1"

    def test_running_it_twice_changes_nothing(self, space, monkeypatch):
        """Which is why coming back here is the way on from "not
        authorized yet", rather than starting over."""
        conn = form_mod.load(course_mod.path_for(space))
        conn.url, conn.secret = "https://script.example/x/exec", "s"
        form_mod.save(course_mod.path_for(space), conn)
        answers(monkeypatch)

        provision_mod.finish(space)
        once = form_mod.load(course_mod.path_for(space))
        provision_mod.finish(space)
        twice = form_mod.load(course_mod.path_for(space))
        assert once.items == twice.items and once.form_id == twice.form_id

    def test_a_rename_happens_only_when_asked(self, space, monkeypatch):
        """clasp's --title names the script project, so a form printit made
        is still untitled. A push must never touch an existing one's."""
        conn = form_mod.load(course_mod.path_for(space))
        conn.url, conn.secret = "https://script.example/x/exec", "s"
        form_mod.save(course_mod.path_for(space), conn)

        asked = answers(monkeypatch)
        provision_mod.finish(space)
        assert "rename" not in asked and "configure" not in asked

        asked2 = answers(monkeypatch)
        provision_mod.finish(space, rename_to="Skill Selection Form")
        assert "rename" in asked2 and "configure" in asked2


class TestWhatAttachingWouldReplace:
    def test_it_names_the_files_printit_would_push_over(self, space,
                                                        monkeypatch):
        def clone(script_id, directory):
            os.makedirs(directory, exist_ok=True)
            for name in ("Code.gs", "ControlCenter.gs", "appsscript.json",
                         "Sidebar.html"):
                with open(os.path.join(directory, name), "w",
                          encoding="utf-8") as f:
                    f.write("x")
        monkeypatch.setattr(clasp_mod, "clone", clone)

        out = provision_mod.what_the_clone_would_replace(space, "SCRIPT1")
        assert out["replaced"] == ["Code.gs", "appsscript.json"]
        assert out["kept"] == ["ControlCenter.gs", "Sidebar.html"]


class TestTheSetupView:
    @pytest.fixture
    def course(self, space):
        return gui_mod.Course(space)

    def test_an_unconnected_course_says_so(self, course):
        out = gui_mod.api_setup(course, {})
        assert out["connected"] is False
        assert set(out["slots"]) == set(form_mod.SLOTS)
        assert out["missing"] == list(form_mod.SLOTS)

    def test_a_connected_one_reports_its_ids(self, course, space):
        conn = form_mod.load(course_mod.path_for(space))
        conn.url = "https://script.example/x/exec"
        conn.script_id, conn.form_id = "SCRIPT1", "FORM1"
        conn.items = {k: f"id-{k}" for k in form_mod.SLOTS}
        form_mod.save(course_mod.path_for(space), conn)

        out = gui_mod.api_setup(course, {})
        assert out["connected"] is True
        assert out["scriptId"] == "SCRIPT1" and out["formId"] == "FORM1"
        assert out["missing"] == []

    def test_not_authorized_is_a_state_not_an_error(self, course,
                                                    monkeypatch, no_clasp):
        """A 400 would read as "that did not work", and the obvious answer
        to that is to try the whole thing again -- which makes a second
        form."""
        monkeypatch.setattr(
            provision_mod, "create_form",
            lambda *a, **k: (_ for _ in ()).throw(
                provision_mod.NeedsAuthorization("https://script.example/x/exec")))
        out = gui_mod.api_setup_create(course, {"title": "T"})
        assert out["needsAuthorization"]["url"].endswith("/exec")
        assert out["needsAuthorization"]["title"] == "T"

    def test_the_title_is_carried_so_finish_can_rename(self, course,
                                                       monkeypatch):
        monkeypatch.setattr(
            provision_mod, "create_form",
            lambda *a, **k: (_ for _ in ()).throw(
                provision_mod.NeedsAuthorization("u")))
        out = gui_mod.api_setup_create(course, {"title": "Mine"})
        assert out["needsAuthorization"]["title"] == "Mine"

    def test_it_sends_the_notes_and_not_the_terminal_paragraph(
            self, course, monkeypatch):
        """The page puts the URL on a button, so repeating it as text is
        noise -- but the explanation of 'Unverified' and the doGet message
        still has to be there, and has to be the same explanation the CLI
        gives."""
        monkeypatch.setattr(
            provision_mod, "create_form",
            lambda *a, **k: (_ for _ in ()).throw(
                provision_mod.NeedsAuthorization("https://script.example/x/exec")))
        need = gui_mod.api_setup_create(course, {})["needsAuthorization"]
        assert need["notes"] == list(provision_mod.AUTHORIZE_NOTES)
        assert "Unverified" in " ".join(need["notes"])
        assert "https://" not in " ".join(need["notes"]),             "the url belongs on the button, not in the prose"

    def test_the_two_front_ends_give_one_explanation(self):
        """`prompt` is what the terminal prints. If the notes drift out of
        it, the app and the CLI start explaining Google differently."""
        said = provision_mod.prompt("https://script.example/x/exec")
        for note in provision_mod.AUTHORIZE_NOTES:
            assert note in said
        assert "https://script.example/x/exec" in said

    def test_a_real_failure_is_still_an_error(self, course, monkeypatch):
        monkeypatch.setattr(
            provision_mod, "create_form",
            lambda *a, **k: (_ for _ in ()).throw(
                provision_mod.ProvisionError("clasp fell over")))
        with pytest.raises(gui_mod.GuiError, match="clasp fell over"):
            gui_mod.api_setup_create(course, {})

    @pytest.mark.parametrize("endpoint", ["api_setup_attach",
                                          "api_setup_inspect"])
    def test_attaching_needs_a_script_id(self, course, endpoint):
        with pytest.raises(gui_mod.GuiError, match="script's id"):
            getattr(gui_mod, endpoint)(course, {"scriptId": "  "})

    def test_authorizing_opens_the_url_printit_recorded(self, course, space,
                                                        monkeypatch):
        """Not one from the request. A localhost endpoint that opened
        whatever it was handed would let any page in any browser launch
        arbitrary URLs on this machine."""
        opened = []
        monkeypatch.setattr(gui_mod.webbrowser, "open", opened.append)
        conn = form_mod.load(course_mod.path_for(space))
        conn.url = "https://script.example/mine/exec"
        form_mod.save(course_mod.path_for(space), conn)

        out = gui_mod.api_setup_authorize(
            course, {"url": "https://somewhere.else/evil"})
        assert opened == ["https://script.example/mine/exec"]
        assert out["opened"] == "https://script.example/mine/exec"

    def test_there_is_nothing_to_authorize_before_a_deploy(self, course,
                                                           monkeypatch):
        opened = []
        monkeypatch.setattr(gui_mod.webbrowser, "open", opened.append)
        with pytest.raises(gui_mod.GuiError, match="no deployed script"):
            gui_mod.api_setup_authorize(course, {})
        assert opened == []

    def test_every_setup_route_is_wired(self):
        for path in ("/api/setup", "/api/setup/create", "/api/setup/inspect",
                     "/api/setup/attach", "/api/setup/authorize",
                     "/api/setup/finish"):
            assert path in gui_mod.ROUTES
