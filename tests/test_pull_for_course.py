"""The pull, lifted out of `form pull`'s click body.

What was stuck in that body was the rule, not the reporting: which skills
count as known, what counts as trouble, the refusal to write a roster when
something could not be placed, and the write itself. The web app's card
calls this, so there is one copy rather than two that have to agree.

Nothing here talks to Google. The one call that would is stubbed, which is
the only part a test can usefully fake -- everything on either side of it
is the behaviour being checked.

No real student appears here.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import course as course_mod
from checkit_printit import form as form_mod
from checkit_printit import responses as responses_mod
from checkit_printit import roster as roster_mod
from checkit_printit.roster import Roster, Student

CONFIRM, CHOOSE = "111", "222"


class FakeConn:
    items = {"confirm_date": CONFIRM, "choose_skills": CHOOSE}


def answer(email, when="10/2", picked=("AD",), at="2026-10-01T09:00:00Z"):
    return {
        "email": email,
        "timestamp": at,
        "answers": {
            CONFIRM: [f"I understand that I am selecting skills for {when}."],
            CHOOSE: list(picked),
        },
    }


@pytest.fixture
def course(tmp_path, monkeypatch, bank_dir):
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    course_mod.init("P", bank=str(bank_dir), adopt=None)

    people = Roster([
        Student(name="Ada Lovelace", skills=[], sid="806001",
                email="ada@example.edu"),
        Student(name="Grace Hopper", skills=[], sid="806002",
                email="grace@example.edu"),
    ])
    with open(course_mod.file_in("P", "roster"), "w", encoding="utf-8") as f:
        f.write(roster_mod.to_toml(people, "test"))

    from checkit_printit import availability as availability_mod
    availability_mod.set_assessment(course_mod.file_in("P", "availability"),
                                    name="Checkpoint", date="2026-10-02")
    monkeypatch.setattr(form_mod, "load", lambda path: FakeConn())
    return "P"


def responding(monkeypatch, *answers):
    monkeypatch.setattr(form_mod, "call",
                        lambda conn, what: {"responses": list(answers)})


def skills_now(space):
    return {s.display: list(s.skills)
            for s in roster_mod.load(course_mod.file_in(space, "roster"))}


class TestItRefusesBeforeItTries:
    def test_a_course_that_does_not_exist(self, tmp_path, monkeypatch):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        with pytest.raises(responses_mod.ResponseError, match="no course"):
            responses_mod.pull_for_course("nope")

    def test_a_course_with_no_roster(self, course, monkeypatch):
        """There is nobody to match responses to, and saying so beats
        matching nothing and reporting a clean pull."""
        os.remove(course_mod.file_in(course, "roster"))
        responding(monkeypatch)
        with pytest.raises(responses_mod.ResponseError,
                           match="nobody to match"):
            responses_mod.pull_for_course(course)


class TestTheHappyPull:
    def test_it_writes_what_was_chosen(self, course, monkeypatch):
        responding(monkeypatch, answer("ada@example.edu", picked=["AD", "SU"]))
        out = responses_mod.pull_for_course(course)
        assert out.written is True
        assert skills_now(course)["Ada Lovelace"] == ["AD", "SU"]

    def test_it_leaves_the_silent_alone(self, course, monkeypatch):
        responding(monkeypatch, answer("ada@example.edu"))
        out = responses_mod.pull_for_course(course)
        assert skills_now(course)["Grace Hopper"] == []
        assert [s.display for s in out.pulled.silent] == ["Grace Hopper"]

    def test_the_counts_come_off_the_outcome(self, course, monkeypatch):
        """Every number the CLI used to compute inline, so the web app does
        not derive a second version of 'how many were out of scope'."""
        responding(monkeypatch,
                   answer("ada@example.edu"),
                   answer("grace@example.edu", when="9/18"))
        out = responses_mod.pull_for_course(course, write=False)
        assert out.total == 2
        assert out.pulled.answered == 1
        assert out.pulled.out_of_scope == 1
        assert out.assessment == "Checkpoint"
        assert out.known_from_bank is True

    def test_a_later_answer_replaces_an_earlier_one(self, course, monkeypatch):
        responding(monkeypatch,
                   answer("ada@example.edu", picked=["AD"],
                          at="2026-10-01T09:00:00Z"),
                   answer("ada@example.edu", picked=["SU"],
                          at="2026-10-01T11:00:00Z"))
        out = responses_mod.pull_for_course(course)
        assert skills_now(course)["Ada Lovelace"] == ["SU"]
        assert out.pulled.superseded == 1


class TestTheDryRun:
    def test_it_decides_everything_and_writes_nothing(self, course,
                                                      monkeypatch):
        responding(monkeypatch, answer("ada@example.edu", picked=["AD"]))
        out = responses_mod.pull_for_course(course, write=False)
        assert out.pulled.answered == 1
        assert out.written is False
        assert skills_now(course)["Ada Lovelace"] == [], "it wrote anyway"


class TestTrouble:
    """Everything here is a reason a student might not get the paper they
    asked for, so a pull that hits one does not quietly write the rest."""

    def test_an_address_nobody_has_is_trouble(self, course, monkeypatch):
        responding(monkeypatch, answer("someone.else@example.edu"))
        out = responses_mod.pull_for_course(course)
        assert out.trouble is True
        assert out.pulled.unknown_emails == ["someone.else@example.edu"]

    def test_an_answer_naming_no_real_skill_is_trouble(self, course,
                                                       monkeypatch):
        responding(monkeypatch,
                   answer("ada@example.edu", picked=["Something else"]))
        out = responses_mod.pull_for_course(course)
        assert out.trouble is True
        assert out.pulled.unrecognised == [("ada@example.edu",
                                            "Something else")]

    def test_trouble_means_nothing_is_written(self, course, monkeypatch):
        responding(monkeypatch,
                   answer("ada@example.edu", picked=["AD"]),
                   answer("nobody@example.edu", picked=["AD"]))
        out = responses_mod.pull_for_course(course)
        assert out.written is False
        assert skills_now(course)["Ada Lovelace"] == [], \
            "the good response was written despite the bad one"

    def test_it_is_returned_rather_than_raised(self, course, monkeypatch):
        """The caller is holding the detail. A refusal with none of it
        attached sends you looking for a problem it already knows about."""
        responding(monkeypatch, answer("nobody@example.edu"))
        out = responses_mod.pull_for_course(course)
        assert out.trouble and not out.written

    def test_force_writes_the_rest(self, course, monkeypatch):
        responding(monkeypatch,
                   answer("ada@example.edu", picked=["AD"]),
                   answer("nobody@example.edu", picked=["AD"]))
        out = responses_mod.pull_for_course(course, force=True)
        assert out.written is True
        assert skills_now(course)["Ada Lovelace"] == ["AD"]

    def test_a_response_for_another_day_is_not_trouble(self, course,
                                                       monkeypatch):
        """It is somebody answering early or late, not a fault, and it must
        not block the rest of the class."""
        responding(monkeypatch,
                   answer("ada@example.edu", picked=["AD"]),
                   answer("grace@example.edu", when="9/18"))
        out = responses_mod.pull_for_course(course)
        assert out.trouble is False and out.written is True
        assert out.pulled.out_of_scope == 1


class TestTheViewCallsTheSameThing:
    def test_the_endpoint_is_routed(self):
        from checkit_printit import gui as gui_mod
        assert gui_mod.ROUTES["/api/print/pull"] is gui_mod.api_print_pull

    def test_it_returns_the_pull_and_the_refreshed_table(self, course,
                                                         monkeypatch):
        """A pull rewrites the roster and the table underneath is showing
        it, so the view would otherwise draw last week's choices until
        something else happened to reload."""
        from checkit_printit import gui as gui_mod
        responding(monkeypatch, answer("ada@example.edu", picked=["AD"]))
        out = gui_mod.api_print_pull(gui_mod.Course(course), {"write": True})
        assert out["pull"]["written"] is True
        shown = {s["display"]: s["chose"] for s in out["print"]["students"]}
        assert shown["Ada Lovelace"] == ["AD"]

    def test_a_refusal_arrives_as_a_gui_error(self, course, monkeypatch):
        from checkit_printit import gui as gui_mod
        os.remove(course_mod.file_in(course, "roster"))
        responding(monkeypatch)
        with pytest.raises(gui_mod.GuiError, match="nobody to match"):
            gui_mod.api_print_pull(gui_mod.Course(course), {})

    def test_the_card_knows_whether_there_is_a_form(self, course):
        """It is hidden on a course that has never had one."""
        from checkit_printit import gui as gui_mod
        assert gui_mod.api_print(gui_mod.Course(course), {})["hasForm"] is False
