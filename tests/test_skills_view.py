"""Stage 8c: the Skills view, and the rules it was lifted out of.

`skills open` and `skills set` used to live inside their Click bodies. They
are now `availability.set_open` and `availability.set_assessment`, so the CLI
and the web app call one implementation -- these test that implementation,
not either front end.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import availability as av_mod
from checkit_printit import clasp
from checkit_printit import gui as gui_mod
from checkit_printit import course as course_mod


AVAILABILITY = '''# A comment a human wrote, which must survive every write.

[assessment]
name   = "Skill Checkpoint"
date   = 2026-10-02
due    = 2026-10-01T23:59:00
choose = 3
limit  = "at most"

# Another comment, this one below the table.
skills = ["W1", "W2"]
'''


@pytest.fixture
def path(tmp_path):
    p = tmp_path / "availability.toml"
    p.write_text(AVAILABILITY, encoding="utf-8")
    return str(p)


class TestSettingTheOpenList:
    def test_it_replaces_by_default(self, path):
        assert av_mod.set_open(path, ["D1", "D2"]) == ["D1", "D2"]
        assert list(av_mod.load(path).skills) == ["D1", "D2"]

    def test_add_keeps_what_was_there(self, path):
        assert av_mod.set_open(path, ["D1"], add=True) == ["W1", "W2", "D1"]

    def test_a_repeat_is_not_added_twice(self, path):
        assert av_mod.set_open(path, ["W1"], add=True) == ["W1", "W2"]

    def test_a_slug_the_bank_does_not_have_is_refused(self, path):
        """A typo here reaches students as a missing option on the form and
        a missing paper in the pile."""
        with pytest.raises(av_mod.AvailabilityError, match="not in the bank"):
            av_mod.set_open(path, ["W1", "ZZ9"], known={"W1", "W2"})
        assert list(av_mod.load(path).skills) == ["W1", "W2"]   # unwritten

    def test_no_bank_means_no_check(self, path):
        av_mod.set_open(path, ["ANYTHING"], known=None)
        assert list(av_mod.load(path).skills) == ["ANYTHING"]

    def test_the_comments_survive(self, path):
        av_mod.set_open(path, ["D1"])
        text = open(path, encoding="utf-8").read()
        assert "A comment a human wrote" in text
        assert "Another comment" in text

    def test_emptying_it_is_allowed(self, path):
        """With nothing open the form says so and refuses submissions, which
        is a deliberate state rather than an error."""
        assert av_mod.set_open(path, []) == []


class TestSettingTheAssessment:
    def test_one_field_at_a_time(self, path):
        av_mod.set_assessment(path, choose=1)
        after = av_mod.load(path)
        assert after.choose == 1
        assert after.name == "Skill Checkpoint"      # untouched
        assert str(after.date) == "2026-10-02"

    def test_a_bad_limit_is_refused_and_writes_nothing(self, path):
        with pytest.raises(av_mod.AvailabilityError, match="not a limit"):
            av_mod.set_assessment(path, limit="sort of")
        assert av_mod.load(path).limit == "at most"

    def test_nothing_to_set_says_so(self, path):
        with pytest.raises(av_mod.AvailabilityError, match="nothing to set"):
            av_mod.set_assessment(path)

    def test_the_comments_survive(self, path):
        av_mod.set_assessment(path, name="Redo")
        assert "A comment a human wrote" in open(path, encoding="utf-8").read()


class TestWhenClaspNeedsSigningInAgain:
    """Eight days after a successful login, Google expired the session and
    clasp passed the raw JSON through. None of the three words `logged_in`
    looked for appear in it, so it raised "could not tell" and dumped a blob
    when the answer was no."""

    REAL = ('{"error":"invalid_grant","error_description":"reauth related '
            'error (invalid_rapt)","error_uri":"https://support.google.com/'
            'a/answer/9368756","error_subtype":"invalid_rapt"}')

    def test_the_message_google_actually_sent_is_recognised(self):
        assert any(s in self.REAL.lower() for s in clasp.NEEDS_LOGIN)

    @pytest.mark.parametrize("message", [
        "You are not logged in.",
        "invalid credentials",
        "Unauthorized",
        "Token has been expired or revoked.",
    ])
    def test_the_other_ways_it_is_said(self, message):
        assert any(s in message.lower() for s in clasp.NEEDS_LOGIN)

    def test_an_unrelated_failure_still_raises(self, monkeypatch):
        """Not everything is a login problem, and swallowing the rest would
        turn a real error into a pointless browser window."""
        monkeypatch.setattr(clasp, "run", lambda *a, **k: (1, "disk full"))
        with pytest.raises(clasp.ClaspError, match="could not tell"):
            clasp.logged_in()


COURSE_AVAILABILITY = AVAILABILITY


@pytest.fixture
def course(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    course_mod.init("Test", bank="", adopt=None)
    root = course_mod.path_for("Test")
    with open(os.path.join(root, "availability.toml"), "w",
              encoding="utf-8") as f:
        f.write(COURSE_AVAILABILITY)
    return gui_mod.Course("Test")


class TestTheSkillsView:
    def test_it_lists_the_open_skills_when_there_is_no_bank(self, course):
        """A course can exist before it is pointed at a bank, and the view
        should show the open list rather than refusing to load."""
        data = gui_mod.api_skills(course, {})
        assert data["hasBank"] is False
        assert [s["slug"] for s in data["skills"]] == ["W1", "W2"]
        assert data["open"] == ["W1", "W2"]

    def test_it_reports_the_assessment_and_the_limits(self, course):
        data = gui_mod.api_skills(course, {})
        assert data["assessment"]["choose"] == 3
        assert data["assessment"]["limit"] == "at most"
        assert data["limits"] == list(av_mod.LIMITS)

    def test_the_wording_is_what_a_push_would_send(self, course):
        """Not an approximation: the preview calls `payload_for`, which is
        what `form push` sends. A second implementation would differ exactly
        where it mattered -- on a form students are reading."""
        data = gui_mod.api_skills(course, {})
        assert data["wording"]["question_title"] == "Choose At Most THREE Skills"

    def test_a_preview_writes_nothing(self, course):
        before = open(course.file("availability"), encoding="utf-8").read()
        out = gui_mod.api_skills_preview(
            course, {"assessment": {"choose": 1, "limit": "exactly"}})
        assert out["wording"]["question_title"] == "Choose Exactly ONE Skills"
        assert open(course.file("availability"), encoding="utf-8").read() == before

    def test_saving_goes_through_the_same_call_the_cli_makes(self, course):
        gui_mod.api_skills_save(course, {
            "open": ["D1"], "assessment": {"choose": 2}})
        after = course.availability()
        assert list(after.skills) == ["D1"]
        assert after.choose == 2
        assert "A comment a human wrote" in open(
            course.file("availability"), encoding="utf-8").read()

    def test_a_refused_save_leaves_the_file_alone(self, course):
        with pytest.raises(gui_mod.GuiError):
            gui_mod.api_skills_save(course, {"assessment": {"limit": "nope"}})
        assert course.availability().limit == "at most"

    def test_pushing_needs_a_form(self, course):
        with pytest.raises(gui_mod.GuiError, match="not connected"):
            gui_mod.api_form_push(course, {})


class TestTheWordingItself:
    """Anything a student reads is specified by the retired Apps Script."""

    def one(self, **kw):
        from checkit_printit import form as form_mod
        base = dict(name="Redo", date="2026-10-02", due="2026-10-01T23:59",
                    choose=3, limit="at most", skills=("W1",))
        base.update(kw)
        av = av_mod.Availability(**base)
        return form_mod.payload_for(av, form_mod.Connection(), {"W1": "do W1"})

    def test_at_most_names_its_limiter(self):
        assert self.one()["validation"]["help"] == \
            "Please choose at most three skill(s)."

    def test_at_least_names_its_limiter(self):
        assert self.one(limit="at least")["validation"]["help"] == \
            "Please choose at least three skill(s)."

    def test_exactly_does_not(self):
        """control_center.gs line 607 is `Please choose ${n} skill(s).` with
        no limiter, where 595 and 601 include theirs."""
        assert self.one(limit="exactly")["validation"]["help"] == \
            "Please choose three skill(s)."

    def test_no_limit_says_so(self):
        assert self.one(choose=0)["validation"]["help"] == \
            "You may choose any amount of skills."

class TestThePrintDraftIsChecked:
    """A slug typed into an override reaches the build as "X asked for 'W9',
    which is not in the bank" -- after a job folder has been written. Caught
    at save time instead, while the box is still on screen."""

    @pytest.fixture
    def printable(self, tmp_path, monkeypatch, bank_dir):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("P", bank=str(bank_dir), adopt=None)
        return gui_mod.Course("P")

    def test_a_slug_the_bank_does_not_have_is_refused(self, printable):
        with pytest.raises(gui_mod.GuiError, match="not in the bank"):
            gui_mod.api_print_save(printable, {"draft": {
                "overrides": {"806001": ["AD", "W9"]}}})

    def test_the_message_names_the_slug_and_the_student(self, printable):
        with pytest.raises(gui_mod.GuiError, match="806001.*W9"):
            gui_mod.api_print_save(printable, {"draft": {
                "overrides": {"806001": ["W9"]}}})

    @pytest.mark.parametrize("field", ["simply_print", "default_when_missing",
                                       "append_for_everyone"])
    def test_the_three_modes_are_checked_too(self, printable, field):
        with pytest.raises(gui_mod.GuiError, match="not in the bank"):
            gui_mod.api_print_save(printable, {"draft": {field: ["NOPE"]}})

    def test_an_extra_naming_a_missing_skill_is_refused(self, printable):
        with pytest.raises(gui_mod.GuiError, match="not in the bank"):
            gui_mod.api_print_save(printable, {"draft": {
                "extras": [{"skill": "NOPE", "copies": 1}]}})

    def test_a_good_draft_saves(self, printable):
        out = gui_mod.api_print_save(printable, {"draft": {
            "simply_print": ["AD"], "date": "2026-10-02"}})
        assert out["draft"]["simply_print"] == ["AD"]

    def test_a_letter_beyond_the_chart_is_how_a_version_is_added(self, printable):
        """It used to be refused. Adding a version from the app means
        naming a letter the chart has never heard of, and `assemble` draws
        seeds for whatever the pins name."""
        out = gui_mod.api_print_save(printable, {"draft": {
            "versions": {"806001": "E"},
            "versionsAvailable": ["A", "B"]}})
        assert out["draft"]["versions"] == {"806001": "E"}

    @pytest.mark.parametrize("letter", ["", "AA", "a", "4", "best one"])
    def test_something_that_is_not_a_version_letter_is_refused(
            self, printable, letter):
        """The value reaches a filename and a printed paper, so it has to be
        a letter even though it no longer has to be one of the chart's."""
        with pytest.raises(gui_mod.GuiError, match="not a version letter"):
            gui_mod.api_print_save(printable, {"draft": {
                "versions": {"806001": letter}}})

    def test_a_refused_draft_is_not_written(self, printable):
        from checkit_printit import printjob
        before = printjob.load_draft("P")
        with pytest.raises(gui_mod.GuiError):
            gui_mod.api_print_save(printable, {"draft": {
                "simply_print": ["NOPE"]}})
        assert printjob.load_draft("P") == before
