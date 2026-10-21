"""Semester and instructor: settable, and noticed when they are not set.

They print in the top right corner of every page, via `\\date` and
`\\author`. The course template creates them empty, `course init` was the
only thing that ever wrote `course.toml`, and the web app offered no
field -- so the first run built entirely in the app, 2026-10-19, printed
with a blank corner and nothing anywhere said so.
"""

import os

import pytest

from checkit_printit import assemble, course as course_mod


class Pub:
    semester = "Fall 26"
    professor = "Slye"


@pytest.fixture
def course_root(tmp_path):
    root = str(tmp_path)
    course_mod.init("TEST 101", bank="", root=root)
    return root


# ---------------------------------------------------------------- saving --

class TestTheHeaderFieldsCanBeSet:
    def test_a_new_course_starts_with_neither(self, course_root):
        """Which is the state that shipped a blank corner."""
        now = course_mod.identity("TEST 101", root=course_root)
        assert now["semester"] == ""
        assert now["professor"] == ""

    def test_setting_them_sticks(self, course_root):
        course_mod.save_identity(
            "TEST 101", {"semester": "Fall 26", "professor": "Slye"},
            root=course_root)
        now = course_mod.identity("TEST 101", root=course_root)
        assert now["semester"] == "Fall 26"
        assert now["professor"] == "Slye"

    def test_the_rest_of_the_file_survives(self, course_root):
        """A line rewrite, not a dump: the file is mostly a comment
        explaining itself, and `[bank]` lives underneath."""
        path = os.path.join(course_mod.path_for("TEST 101", course_root),
                            course_mod.CONFIG)
        before = open(path, encoding="utf-8").read()
        assert "[bank]" in before and before.count("#") > 5

        course_mod.save_identity("TEST 101", {"semester": "Fall 26"},
                                 root=course_root)
        after = open(path, encoding="utf-8").read()
        assert "[bank]" in after
        assert after.count("#") == before.count("#"), "comments were lost"
        assert 'semester  = "Fall 26"' in after

    def test_the_commented_example_is_not_rewritten(self, course_root):
        """The header comment shows a publication's own [course] table,
        with `name   = "MAT 106"` in it."""
        course_mod.save_identity("TEST 101", {"name": "Renamed"},
                                 root=course_root)
        path = os.path.join(course_mod.path_for("TEST 101", course_root),
                            course_mod.CONFIG)
        text = open(path, encoding="utf-8").read()
        assert '#     name   = "MAT 106"' in text, "the example was edited"
        assert 'name      = "Renamed"' in text

    def test_an_indented_key_under_another_table_is_left_alone(self,
                                                               course_root):
        """Only column zero is this file's own. A key indented under some
        other table belongs to that table, and rewriting it at column
        zero would quietly move it out."""
        path = os.path.join(course_mod.path_for("TEST 101", course_root),
                            course_mod.CONFIG)
        with open(path, "a", encoding="utf-8") as f:
            f.write('\n[elsewhere]\n    semester = "theirs"\n')

        course_mod.save_identity("TEST 101", {"semester": "Fall 26"},
                                 root=course_root)
        text = open(path, encoding="utf-8").read()
        assert '    semester = "theirs"' in text, "another table was edited"
        assert 'semester  = "Fall 26"' in text
        assert course_mod.identity(
            "TEST 101", root=course_root)["semester"] == "Fall 26"

    def test_a_field_not_mentioned_is_left_alone(self, course_root):
        course_mod.save_identity("TEST 101", {"semester": "Fall 26"},
                                 root=course_root)
        course_mod.save_identity("TEST 101", {"professor": "Slye"},
                                 root=course_root)
        now = course_mod.identity("TEST 101", root=course_root)
        assert now["semester"] == "Fall 26", "the first save was undone"
        assert now["professor"] == "Slye"

    def test_a_quote_in_a_name_does_not_break_the_file(self, course_root):
        course_mod.save_identity("TEST 101", {"professor": 'O"Hara'},
                                 root=course_root)
        assert course_mod.identity(
            "TEST 101", root=course_root)["professor"] == 'O"Hara'


# ---------------------------------------------------------------- noticing --

class TestABlankCornerIsReported:
    def test_both_missing_are_named(self):
        class Bare:
            semester = ""
            professor = ""
        assert assemble.header_gaps(Bare()) == ["semester", "instructor"]

    def test_one_missing_is_named_alone(self):
        class Half:
            semester = "Fall 26"
            professor = ""
        assert assemble.header_gaps(Half()) == ["instructor"]

    def test_whitespace_is_not_a_value(self):
        """`semester = " "` prints a corner that is still blank."""
        class Spaces:
            semester = "   "
            professor = "\t"
        assert assemble.header_gaps(Spaces()) == ["semester", "instructor"]

    def test_a_complete_course_is_quiet(self):
        assert assemble.header_gaps(Pub()) == []
