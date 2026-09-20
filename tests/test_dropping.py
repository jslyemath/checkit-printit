"""Dropping a student.

The model: printing works off the seating chart, so there is no filter at
print time. Dropping empties the seat, and what the chart says is what comes
out of the printer. The roster keeps the student, flagged, because the print
record refers to them.

That only holds while the two files agree, so the build checks rather than
filters -- a filter would hide a divergence, a check names it.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import classlist, seating
from checkit_printit import roster as roster_mod
from checkit_printit.assemble import AssemblyError, check_dropped_are_unseated
from checkit_printit.roster import Roster, Student


CHART = '''# Where they sit.
versions = ["A", "B", "C", "D"]

# table 6 -- move "Ada Lovelace" to the window next week
[[group]]
seats = ["Ada Lovelace", "Alan Turing", "Grace Hopper", "Katherine Johnson"]
'''


class TestBlankingASeat:
    def test_the_seat_empties(self):
        new, count = seating.blank_seat(CHART, "Alan Turing")
        assert count == 1
        assert '"Alan Turing"' not in new
        assert '""' in new

    def test_nobody_else_is_re_lettered(self, tmp_path):
        """Version letters come from position, so removing the entry instead of
        emptying it would hand this student's tablemates different papers."""
        def chart(text):
            p = tmp_path / "s.toml"
            p.write_text(text, encoding="utf-8")
            return {s.name: s.version for s in seating.load(str(p))}

        before = chart(CHART)
        after = chart(seating.blank_seat(CHART, "Alan Turing")[0])
        assert "Alan Turing" not in after
        assert all(after[n] == before[n] for n in after)

    def test_a_name_in_a_comment_is_left_alone(self):
        new, count = seating.blank_seat(CHART, "Ada Lovelace")
        assert count == 1, "only the seat counts, not the note above it"
        assert '"Ada Lovelace" to the window' in new, "the note was mangled"

    def test_the_rest_of_the_file_survives_byte_for_byte(self):
        new, _ = seating.blank_seat(CHART, "Grace Hopper")
        assert "# table 6" in new and 'versions = ["A", "B", "C", "D"]' in new

    def test_a_name_that_is_not_seated_changes_nothing(self):
        new, count = seating.blank_seat(CHART, "Nobody At All")
        assert count == 0 and new == CHART


class TestFindingAStudent:
    def roster(self):
        return Roster([
            Student(name="Ada Lovelace", skills=[], sid="806000001",
                    email="ada@example.edu"),
            Student(name="Alan Turing", skills=[], sid="806000002",
                    email="alan@example.edu"),
            Student(name="Alan Turing-Smith", skills=[], sid="806000003",
                    email="alan2@example.edu"),
        ])

    def test_by_student_id(self):
        assert roster_mod.find(self.roster(), "806000002").name == "Alan Turing"

    def test_by_email(self):
        assert roster_mod.find(self.roster(), "ada@example.edu").sid == "806000001"

    def test_an_exact_name_beats_a_partial_one(self):
        """"Alan Turing" is also a substring of "Alan Turing-Smith"; the exact
        match has to win rather than the lookup being ambiguous."""
        assert roster_mod.find(self.roster(), "Alan Turing").sid == "806000002"

    def test_an_ambiguous_partial_name_refuses_to_guess(self):
        with pytest.raises(roster_mod.Ambiguous, match="matches 2"):
            roster_mod.find(self.roster(), "alan")

    def test_an_unknown_name_says_so(self):
        with pytest.raises(roster_mod.NotFound, match="no student"):
            roster_mod.find(self.roster(), "Grace Hopper")


class TestWhoseDropItWas:
    LIST = ('"Student ID","Student Last Name","Student First Name","Email"\n'
            '"806000001","Lovelace","Ada","ada@example.edu"\n')

    def incoming(self, tmp_path):
        p = tmp_path / "c.csv"
        p.write_text(self.LIST, encoding="utf-8")
        return classlist.parse(str(p))[0]

    def test_an_import_drop_is_undone_by_a_later_import(self, tmp_path):
        roster = Roster([Student(name="Ada Lovelace", skills=[],
                                 sid="806000001", dropped=True,
                                 dropped_by="import")])
        roster, report = classlist.merge(roster, self.incoming(tmp_path))
        assert not roster.students[0].dropped
        assert any("re-enrolled" in u for u in report.updated)

    def test_an_instructor_drop_survives_a_class_list(self, tmp_path):
        """The registrar is often behind the room. Someone the instructor has
        dropped stays dropped until the instructor says otherwise."""
        roster = Roster([Student(name="Ada Lovelace", skills=[],
                                 sid="806000001", dropped=True,
                                 dropped_by="instructor")])
        roster, report = classlist.merge(roster, self.incoming(tmp_path))
        assert roster.students[0].dropped
        assert report.kept_dropped == ["Ada Lovelace"]

    def test_a_drop_inferred_from_absence_is_attributed(self, tmp_path):
        roster = Roster([Student(name="Alan Turing", skills=[], sid="806000009")])
        roster, _ = classlist.merge(roster, self.incoming(tmp_path))
        alan = next(s for s in roster if s.sid == "806000009")
        assert alan.dropped and alan.dropped_by == "import"


class TestTheBuildRefusesDisagreement:
    def chart(self, tmp_path, text=CHART):
        p = tmp_path / "s.toml"
        p.write_text(text, encoding="utf-8")
        return seating.load(str(p))

    def test_a_dropped_student_still_seated_stops_the_build(self, tmp_path):
        roster = Roster([Student(name="Ada Lovelace", skills=["W1"],
                                 dropped=True, dropped_by="instructor")])
        with pytest.raises(AssemblyError, match="still in the seating chart"):
            check_dropped_are_unseated(roster, self.chart(tmp_path))

    def test_a_dropped_student_whose_seat_is_empty_is_fine(self, tmp_path):
        emptied = seating.blank_seat(CHART, "Ada Lovelace")[0]
        roster = Roster([Student(name="Ada Lovelace", skills=["W1"],
                                 dropped=True, dropped_by="instructor")])
        check_dropped_are_unseated(roster, self.chart(tmp_path, emptied))

    def test_no_chart_at_all_is_fine(self):
        roster = Roster([Student(name="Ada Lovelace", skills=["W1"],
                                 dropped=True)])
        check_dropped_are_unseated(roster, None)
