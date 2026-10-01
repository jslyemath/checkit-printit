"""The print job draft, and turning it into a job folder.

The draft is written in one shape and read in another, which is where this
went wrong once already: `save_draft` put `simply_print` under `[selection]`
and `load_draft` looked for it at the root, so a draft naming two skills
built a run that printed neither.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import course as course_mod
from checkit_printit import printjob
from checkit_printit import publication as pub_mod


@pytest.fixture
def space(tmp_path, monkeypatch, bank_dir):
    # A bank, because a publication without one is refused -- which is
    # correct, and is why the view blocks Build for a course that names
    # none rather than writing a job that cannot load.
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    course_mod.init("Test", bank=str(bank_dir), adopt=None)
    return "Test"


FULL = {
    "title": "Redo", "date": "2026-10-02",
    "keys": False, "key_copies": 3, "names": False,
    "simply_print": ["W1", "W2"],
    "default_when_missing": ["D1"],
    "append_for_everyone": ["D1-E"],
    "variants": {"W4": "multiplication"},
    "overrides": {"806001": ["W3"]},
    "extras": [{"skill": "W1", "copies": 4}],
}


class TestTheDraftRoundTrips:
    """Every key, because the ones in tables were the ones that broke."""

    @pytest.mark.parametrize("key", sorted(FULL))
    def test_each_key_survives_a_save_and_a_load(self, space, key):
        printjob.save_draft(space, FULL)
        assert printjob.load_draft(space)[key] == FULL[key]

    def test_a_course_with_no_draft_still_opens(self, space):
        """A form with no saved state has to render, so every key is
        present whether or not anything was ever written."""
        draft = printjob.load_draft(space)
        assert set(draft) == set(printjob.DEFAULTS)
        assert draft["title"] and draft["simply_print"] == []

    def test_a_partial_save_keeps_what_it_did_not_mention(self, space):
        printjob.save_draft(space, FULL)
        printjob.save_draft(space, {"title": "Something else"})
        after = printjob.load_draft(space)
        assert after["title"] == "Something else"
        assert after["simply_print"] == ["W1", "W2"]

    def test_a_hand_edited_draft_of_the_wrong_shape_does_not_poison_the_view(
            self, space):
        """`variants` and `overrides` are whole tables, so a hand-edit could
        leave a string there. The view indexes them as dicts, so a wrong
        type has to be ignored rather than handed on.

        This is what the `table == key` branch is for -- removing it is
        otherwise indistinguishable from the root fallback, because a table
        named for its key is found either way."""
        bad = '\n'.join(['title = "x"',
                         'variants = "not a table"',
                         'overrides = 7',
                         'versions = []'])
        with open(printjob.draft_path(space), "w", encoding="utf-8") as f:
            f.write(bad)
        draft = printjob.load_draft(space)
        assert draft["variants"] == {}
        assert draft["overrides"] == {}
        assert draft["versions"] == {}

    def test_every_key_in_a_table_is_declared(self):
        """The pairing that stops this breaking again: a key written into a
        table must be read from the same one."""
        for key, table in printjob.IN_TABLE.items():
            assert key in printjob.DEFAULTS
            assert table in ("selection", key)


class TestWritingTheJob:
    def test_it_writes_a_publication_the_loader_accepts(self, space, tmp_path):
        printjob.save_draft(space, FULL)
        folder = printjob.write_job(space, printjob.load_draft(space),
                                    course_name="MAT 106", semester="Fall 2026",
                                    professor="Slye",
                                    root=str(tmp_path / "jobs"))
        pub = pub_mod.load(os.path.join(folder, "publication.toml"))
        assert pub.title == "Redo"
        assert pub.course == "MAT 106"
        assert pub.course_folder == space
        assert pub.simply_print == ("W1", "W2")
        assert pub.append_for_everyone == ("D1-E",)
        assert pub.variants == {"W4": "multiplication"}
        assert [e.skill for e in pub.extras] == ["W1"]
        assert pub.keys is False and pub.key_copies == 3

    def test_it_names_the_course_rather_than_copying_its_files(self, space,
                                                               tmp_path):
        """So a student who drops is fixed in one place."""
        printjob.save_draft(space, FULL)
        folder = printjob.write_job(space, printjob.load_draft(space),
                                    course_name="MAT 106",
                                    root=str(tmp_path / "jobs"))
        text = open(os.path.join(folder, "publication.toml"),
                    encoding="utf-8").read()
        assert "[roster]" not in text and "[seating]" not in text
        assert f'folder    = "{space}"' in text

    def test_no_date_is_refused(self, space, tmp_path):
        """The date names the folder, prints on the paper, and is how a
        response is matched to an assessment."""
        draft = dict(printjob.load_draft(space))
        draft["date"] = ""
        with pytest.raises(printjob.PrintJobError, match="needs a date"):
            printjob.write_job(space, draft, course_name="MAT 106",
                               root=str(tmp_path / "jobs"))

    def test_the_folder_is_named_for_the_title_and_date(self, space, tmp_path):
        draft = dict(printjob.load_draft(space))
        draft.update(title="Skill Checkpoint Redo", date="2026-10-02")
        folder = printjob.folder_for(draft, root=str(tmp_path))
        assert os.path.basename(folder) == "Skill Checkpoint Redo 2026-10-02"

    def test_a_title_with_a_slash_does_not_escape_the_folder(self, space,
                                                             tmp_path):
        draft = dict(printjob.load_draft(space))
        draft.update(title="W1/W2: redo", date="2026-10-02")
        folder = printjob.folder_for(draft, root=str(tmp_path))
        assert os.path.dirname(folder) == str(tmp_path)
        assert "/" not in os.path.basename(folder)

class TestMovingOneStudentToAnotherVersion:
    """The letter comes from a seat, which is right almost always. The
    exception is the run where it is not -- someone sitting elsewhere that
    day, two who ended up adjacent after a drop. Today that means editing
    the seating chart and putting it back."""

    def test_it_round_trips_through_the_draft(self, space):
        printjob.save_draft(space, {"versions": {"806001": "D"}})
        assert printjob.load_draft(space)["versions"] == {"806001": "D"}

    def test_it_reaches_the_publication(self, space, tmp_path):
        draft = dict(printjob.load_draft(space))
        draft.update(FULL, versions={"806001": "C"})
        folder = printjob.write_job(space, draft, course_name="MAT 106",
                                    root=str(tmp_path / "jobs"))
        pub = pub_mod.load(os.path.join(folder, "publication.toml"))
        assert pub.student_versions == {"806001": "C"}

    def test_the_seating_chart_is_not_touched(self, space, tmp_path):
        """A property of the run, not of the room: next week's print is
        unaffected, and nothing has to be put back."""
        draft = dict(printjob.load_draft(space))
        draft.update(FULL, versions={"806001": "C"})
        folder = printjob.write_job(space, draft, course_name="MAT 106",
                                    root=str(tmp_path / "jobs"))
        text = open(os.path.join(folder, "publication.toml"),
                    encoding="utf-8").read()
        assert "[versions]" in text and "[seating]" not in text

    def test_no_override_writes_no_table(self, space, tmp_path):
        folder = printjob.write_job(space, printjob.load_draft(space)
                                    | {"date": "2026-10-02"},
                                    course_name="MAT 106",
                                    root=str(tmp_path / "jobs"))
        text = open(os.path.join(folder, "publication.toml"),
                    encoding="utf-8").read()
        assert "[versions]" not in text

class TestThePinnedVersionIsUsed:
    """Reaching publication.toml is not the same as reaching the paper."""

    def _handouts(self, pinned, seat_version="A"):
        from checkit_printit.assemble import build_handouts
        from checkit_printit.roster import Student, Roster
        from checkit_printit import seating as seating_mod

        student = Student(name="Ada Lovelace", skills=["AD"], sid="806001")
        chart = seating_mod.Chart(
            seats=[seating_mod.Seat(name="Ada Lovelace", group=0,
                                    version=seat_version)],
            versions=("A", "B"))

        class Pub:
            student_versions = pinned
            names = True
        seeds = {("A", "AD"): 401, ("B", "AD"): 402}
        # build_handouts returns (handouts, unseated).
        return build_handouts(Roster([student]), chart, Pub(), seeds)[0]

    def test_with_no_override_the_seat_decides(self):
        handouts = self._handouts({}, seat_version="A")
        assert handouts[0].version == "A"
        assert handouts[0].versions == [("AD", 401)]

    def test_an_override_beats_the_seat(self):
        handouts = self._handouts({"806001": "B"}, seat_version="A")
        assert handouts[0].version == "B"
        assert handouts[0].versions == [("AD", 402)], \
            "the seed has to change too, or only the label moved"

    def test_it_is_keyed_by_id_not_name(self):
        """Like everything else that must survive a rename."""
        assert self._handouts({"Ada Lovelace": "B"})[0].version == "B"
        assert self._handouts({"someone else": "B"})[0].version == "A"
