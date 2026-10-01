"""The per-student override, which used to stop at the staging table.

It was validated when saved, stored in `job.toml`, shown in the table, and
`willGet` in the browser composed it exactly as `apply_selection_modes`
would -- so the screen promised it. `publication_text` then wrote
`[variants]`, `[versions]` and `[[extras]]` and dropped `overrides`, and no
reader for such a table had ever existed. The paper came out with whatever
the student had chosen.

No real student appears here.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import course as course_mod
from checkit_printit import printjob
from checkit_printit import publication as pub_mod
from checkit_printit import roster as roster_mod
from checkit_printit import runner as runner_mod
from checkit_printit.roster import Roster, Student


def people(*students):
    return Roster(list(students))


class TestWhichIdsATableMayUse:
    """`keys_of` is the one list. `build_handouts` carried its own copy
    until this change, which is two places to keep agreeing."""

    def test_strongest_first(self):
        s = Student(name="Ada Lovelace", skills=[], sid="806001",
                    alt_id="2000001", email="ada@example.edu")
        assert roster_mod.keys_of(s) == ("806001", "2000001",
                                         "ada@example.edu", "Ada Lovelace")

    def test_empty_ids_are_left_out(self):
        """An empty sid must not match an empty key in a hand-edited file."""
        s = Student(name="Ada Lovelace", skills=[])
        assert roster_mod.keys_of(s) == ("Ada Lovelace",)


class TestApplyingAnOverride:
    def test_it_replaces_what_the_student_chose(self):
        s = Student(name="Ada Lovelace", skills=["AD"], sid="806001")
        out, unmatched = roster_mod.apply_overrides(people(s),
                                                    {"806001": ["SU"]})
        assert list(out)[0].skills == ["SU"]
        assert unmatched == []

    def test_everyone_else_is_untouched(self):
        a = Student(name="Ada Lovelace", skills=["AD"], sid="806001")
        b = Student(name="Grace Hopper", skills=["AD"], sid="806002")
        out, _ = roster_mod.apply_overrides(people(a, b), {"806001": ["SU"]})
        assert [s.skills for s in out] == [["SU"], ["AD"]]

    @pytest.mark.parametrize("key", ["806001", "2000001", "ada@example.edu",
                                     "Ada Lovelace"])
    def test_any_id_the_roster_carries_matches(self, key):
        s = Student(name="Ada Lovelace", skills=["AD"], sid="806001",
                    alt_id="2000001", email="ada@example.edu")
        out, unmatched = roster_mod.apply_overrides(people(s), {key: ["SU"]})
        assert list(out)[0].skills == ["SU"] and unmatched == []

    def test_one_matching_nobody_is_reported_not_dropped(self):
        """A line the instructor typed that silently does nothing is the
        whole fault being fixed here."""
        s = Student(name="Ada Lovelace", skills=["AD"], sid="806001")
        out, unmatched = roster_mod.apply_overrides(
            people(s), {"806001": ["SU"], "806999": ["AD"]})
        assert unmatched == ["806999"]
        assert list(out)[0].skills == ["SU"], "the good one still applied"

    def test_no_overrides_changes_nothing(self):
        s = Student(name="Ada Lovelace", skills=["AD"], sid="806001")
        original = people(s)
        out, unmatched = roster_mod.apply_overrides(original, {})
        assert out is original and unmatched == []


class TestItSurvivesTheJobFolder:
    @pytest.fixture
    def space(self, tmp_path, monkeypatch, bank_dir):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("T", bank=str(bank_dir), adopt=None)
        return "T"

    def _publication(self, space, tmp_path, overrides):
        draft = dict(printjob.load_draft(space))
        draft.update(title="T", date="2026-10-02", overrides=overrides)
        folder = printjob.write_job(space, draft, course_name="MAT 106",
                                    root=str(tmp_path / "jobs"))
        return pub_mod.load(os.path.join(folder, "publication.toml"))

    def test_the_table_is_written(self, space, tmp_path):
        """It was not. Everything upstream of here worked."""
        draft = dict(printjob.load_draft(space))
        draft.update(title="T", date="2026-10-02",
                     overrides={"806001": ["AD", "SU"]})
        text = printjob.publication_text(space, draft, "MAT 106")
        assert "[overrides]" in text
        assert '"806001"' in text and "AD" in text

    def test_and_read_back(self, space, tmp_path):
        pub = self._publication(space, tmp_path, {"806001": ["AD", "SU"]})
        assert pub.student_overrides == {"806001": ["AD", "SU"]}

    def test_no_overrides_writes_no_table(self, space, tmp_path):
        pub = self._publication(space, tmp_path, {})
        assert pub.student_overrides == {}


class TestTheOrderTheyCompose:
    """`willGet` in the browser says an override replaces a student's own
    choices and the modes still apply on top. The build has to agree, or
    the staging table is a promise it cannot keep."""

    @pytest.fixture
    def job(self, tmp_path, monkeypatch, bank_dir):
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("T", bank=str(bank_dir), adopt=None)
        path = os.path.join(str(tmp_path), "courses", "T", "roster.toml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(roster_mod.to_toml(Roster([
                # chose nothing, and is overridden
                Student(name="Ada Lovelace", skills=[], sid="806001"),
                # chose nothing, and is not
                Student(name="Grace Hopper", skills=[], sid="806002"),
            ]), "test"))
        seats = os.path.join(str(tmp_path), "courses", "T", "seating.toml")
        with open(seats, "w", encoding="utf-8") as f:
            f.write('\n'.join(['versions = ["A", "B"]',
                               '',
                               '[[group]]',
                               'seats = ["Ada Lovelace", "Grace Hopper"]',
                               '']))

        def build(tmp, **draft_kw):
            draft = dict(printjob.load_draft("T"))
            draft.update(title="T", date="2026-10-02", **draft_kw)
            folder = printjob.write_job("T", draft, course_name="MAT 106",
                                        root=str(tmp / "jobs"))
            return runner_mod.run(os.path.join(folder, "publication.toml"),
                                  out=str(tmp / "out"), do_compile=False)
        return build

    def _pages(self, result):
        import re
        tex = open(os.path.join(result.out, "main.tex"),
                   encoding="utf-8").read()
        out, who = {}, None
        for line in tex.splitlines():
            m = re.match(r"\\setname\{(.*)\}", line)
            if m:
                who = m.group(1)
                out[who] = []
            elif who and line.startswith(r"\skillpage{"):
                out[who].append(re.match(r"\\skillpage\{([^/]+)/",
                                         line).group(1))
        return out

    def test_an_override_beats_the_default_for_a_silent_student(self, job,
                                                                tmp_path):
        """The reason it is applied *before* the modes: a student with an
        override but no choices of their own must not also collect
        `default_when_missing`."""
        result = job(tmp_path, default_when_missing=["AD"],
                     overrides={"806001": ["SU"]})
        pages = self._pages(result)
        assert pages["Ada Lovelace"] == ["SU"]
        assert pages["Grace Hopper"] == ["AD"], "the default still applies"

    def test_append_for_everyone_still_composes_on_top(self, job, tmp_path):
        result = job(tmp_path, overrides={"806001": ["SU"]},
                     append_for_everyone=["AD"])
        assert self._pages(result)["Ada Lovelace"] == ["SU", "AD"]

    def test_simply_print_still_wins(self, job, tmp_path):
        """Everyone sitting the same thing means everyone, which is why the
        override box is hidden in that mode rather than merely ignored."""
        result = job(tmp_path, overrides={"806001": ["SU"]},
                     simply_print=["AD"])
        assert self._pages(result)["Ada Lovelace"] == ["AD"]

    def test_an_override_for_nobody_is_carried_out_of_the_build(self, job,
                                                                tmp_path):
        result = job(tmp_path, overrides={"806999": ["SU"]})
        assert result.unmatched_overrides == ("806999",)
