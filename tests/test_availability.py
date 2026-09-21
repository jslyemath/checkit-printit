"""What is open for retake, and the sentences the form will carry.

The wording is checked against the real form character for character. It is
not ours to improve: students have been reading it all term, and the Apps
Script that produced it is kept at `reference/control_center.gs`.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import availability as av


FILE = '''# a comment at the top
#   name    what it is called

[assessment]
name   = "Skill Checkpoint Redo"
date   = 2026-09-18
due    = 2026-09-17T23:59:00
choose = 3
limit  = "at most"

skills = ["W1", "W1-E"]
'''


class TestWords:
    @pytest.mark.parametrize("count,word", [
        (0, "any"), (1, "one"), (3, "three"), (20, "twenty"),
        (21, "twenty one"), (40, "forty"),
    ])
    def test_the_table_from_the_script(self, count, word):
        assert av.number_word(count) == word

    def test_past_the_table_it_falls_back_to_digits(self):
        assert av.number_word(41) == "41"

    def test_nothing_sensible_means_any(self):
        assert av.number_word(None) == "any"

    def test_a_date_is_spoken_the_way_the_form_speaks_it(self):
        assert av.spoken_date("2026-09-18") == "Friday, 9/18"

    def test_a_time_is_spoken_the_way_the_form_speaks_it(self):
        assert av.spoken_time("2026-09-17T23:59:00") == "11:59 PM"

    def test_midnight_and_noon_do_not_become_zero(self):
        assert av.spoken_time("2026-09-17T00:30:00") == "12:30 AM"
        assert av.spoken_time("2026-09-17T12:05:00") == "12:05 PM"

    def test_an_unparseable_date_says_what_it_wanted(self):
        with pytest.raises(av.AvailabilityError, match="2026-09-18"):
            av.as_date("next Tuesday")


class TestTheSentencesTheFormCarries:
    def one(self, **kw):
        base = dict(name="Skill Checkpoint Redo", date="2026-09-18",
                    due="2026-09-17T23:59:00", choose=3, limit="at most")
        base.update(kw)
        return av.Availability(**base)

    def test_selecting_for(self):
        assert self.one().selecting_for() == (
            "You are selecting three skill(s) you would like to attempt on "
            "the Skill Checkpoint Redo on Friday, 9/18.")

    def test_the_confirmation_checkbox(self):
        assert self.one().confirmation() == (
            "I understand that I am selecting skills for Friday, 9/18.")

    def test_the_question_title(self):
        assert self.one().question_title() == "Choose At Most THREE Skills"

    def test_the_due_notice(self):
        assert self.one().due_notice() == (
            "This form is due by 11:59 PM on Thursday, 9/17. If you do not "
            "complete the form by that time, then I cannot guarantee that I "
            "will have skills printed for you to attempt.")

    @pytest.mark.parametrize("limit,title", [
        ("at most", "Choose At Most THREE Skills"),
        ("at least", "Choose At Least THREE Skills"),
        ("exactly", "Choose Exactly THREE Skills"),
    ])
    def test_all_three_limiter_modes(self, limit, title):
        assert self.one(limit=limit).question_title() == title

    def test_choosing_zero_means_any_number(self):
        assert self.one(choose=0).question_title() == "Choose ANY Skills"
        assert "selecting any skill(s)" in self.one(choose=0).selecting_for()


class TestLoading:
    def write(self, tmp_path, text):
        p = tmp_path / "availability.toml"
        p.write_text(text, encoding="utf-8")
        return str(p)

    def test_it_reads_the_file(self, tmp_path):
        a = av.load(self.write(tmp_path, FILE))
        assert a.name == "Skill Checkpoint Redo"
        assert a.choose == 3 and a.limit == "at most"
        assert a.skills == ("W1", "W1-E")

    def test_skills_below_the_header_belong_to_it(self, tmp_path):
        """A TOML table runs to the next header, so a blank line does not put
        `skills` back at the root -- which is where it was first read from,
        and why an open list looked empty."""
        a = av.load(self.write(tmp_path, FILE))
        assert a.skills, "the blank line above `skills` does not unindent it"

    def test_skills_above_the_header_also_work(self, tmp_path):
        a = av.load(self.write(tmp_path, 'skills = ["D1"]\n[assessment]\n'))
        assert a.skills == ("D1",)

    def test_a_limit_that_is_not_one_of_the_three_is_refused(self, tmp_path):
        with pytest.raises(av.AvailabilityError, match="at most"):
            av.load(self.write(tmp_path, '[assessment]\nlimit = "roughly"\n'))


class TestWritingInPlace:
    def test_a_value_changes_and_the_comments_stay(self):
        out = av.set_values(FILE, {"choose": 5})
        assert "choose = 5" in out
        assert "# a comment at the top" in out
        assert "#   name    what it is called" in out

    def test_a_trailing_comment_on_that_line_survives(self):
        text = 'choose = 0   # 0 means any number\n'
        out = av.set_values(text, {"choose": 4})
        assert out.strip() == "choose = 4  # 0 means any number"

    def test_a_hash_inside_a_string_is_not_a_comment(self):
        text = 'name = "Redo #2"\n'
        out = av.set_values(text, {"name": "Redo #3"})
        assert out.strip() == 'name = "Redo #3"'

    def test_a_key_only_mentioned_in_a_comment_is_not_written(self):
        with pytest.raises(av.AvailabilityError, match="no line to change"):
            av.set_values("# choose = 3\n", {"choose": 5})

    def test_a_list_round_trips(self, tmp_path):
        out = av.set_values(FILE, {"skills": ["D1", "D1-E", "W1"]})
        p = tmp_path / "a.toml"
        p.write_text(out, encoding="utf-8")
        assert av.load(str(p)).skills == ("D1", "D1-E", "W1")

    def test_a_date_is_written_bare_and_reads_back_as_a_date(self, tmp_path):
        out = av.set_values(FILE, {"date": av.as_date("2026-10-02")})
        p = tmp_path / "a.toml"
        p.write_text(out, encoding="utf-8")
        assert av.spoken_date(av.load(str(p)).date) == "Friday, 10/2"
