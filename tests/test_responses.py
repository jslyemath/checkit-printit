"""Reading the form's responses.

The Google half returns what the form holds and judges nothing, so every rule
worth getting wrong lives here and is testable without a network.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import responses as r
from checkit_printit.roster import Roster, Student

CONFIRM = "1057415225"
CHOOSE = "2133307229"
ITEMS = {"confirm_date": CONFIRM, "choose_skills": CHOOSE}
KNOWN = ("W1", "W2", "W3", "D1")


def answer(email, when, confirmed="Friday, 9/25", picked=("W1",), descr=True):
    chose = [f"{s} - I can do {s} things" if descr else s for s in picked]
    return {
        "email": email,
        "timestamp": when,
        "answers": {
            CONFIRM: [f"I understand that I am selecting skills for {confirmed}."],
            CHOOSE: list(chose),
        },
    }


def roster_of(*people):
    return Roster([
        Student(name=n, skills=[], sid=sid, email=e, emails=list(extra))
        for n, sid, e, extra in people
    ])


ADA = ("Ada L", "806001", "ada@example.edu", [])
BOB = ("Bo M", "806002", "bo@example.edu", ["bo.m@other.example.edu"])


class TestTheConfirmedDate:
    def test_it_is_read_out_of_the_student_s_own_answer(self):
        assert r.confirmed_date(
            ["I understand that I am selecting skills for Friday, 9/25."]
        ) == (9, 25)

    def test_a_bare_string_works_as_well_as_a_list(self):
        assert r.confirmed_date("for Monday, 12/1.") == (12, 1)

    def test_nothing_ticked_is_no_date(self):
        assert r.confirmed_date([]) is None
        assert r.confirmed_date(None) is None

    def test_an_answer_with_no_date_in_it_is_no_date(self):
        assert r.confirmed_date(["I understand."]) is None


class TestScoping:
    """A form accumulates responses all term. The confirmation is the key."""

    def test_only_the_matching_date_is_kept(self):
        rows = [answer("a@x", "2026-09-20T10:00:00", confirmed="Friday, 9/25"),
                answer("b@x", "2026-09-20T10:00:00", confirmed="Friday, 9/18")]
        kept, unconfirmed = r.for_assessment(rows, CONFIRM, "2026-09-25")
        assert [k["email"] for k in kept] == ["a@x"]
        assert unconfirmed == []

    def test_a_response_that_ticked_nothing_is_set_aside_not_dropped(self):
        row = answer("a@x", "2026-09-20T10:00:00")
        row["answers"][CONFIRM] = []
        kept, unconfirmed = r.for_assessment([row], CONFIRM, "2026-09-25")
        assert kept == [] and len(unconfirmed) == 1

    def test_the_year_is_not_compared(self):
        """What the retired script did: month and day. A form does not span
        a year within one term, and narrowing it silently would be worse."""
        rows = [answer("a@x", "2026-09-20T10:00:00", confirmed="Friday, 9/25")]
        kept, _ = r.for_assessment(rows, CONFIRM, "2027-09-25")
        assert len(kept) == 1

    def test_no_assessment_date_is_an_error_not_an_empty_pull(self):
        with pytest.raises(r.ResponseError, match="skills set"):
            r.for_assessment([], CONFIRM, "")

    def test_the_confirmation_is_found_by_id_not_position(self):
        """`getItems(CHECKBOX)[1]` is how the old script did it, and one
        inserted header retargeted every write."""
        row = answer("a@x", "2026-09-20T10:00:00")
        row["answers"] = {"9999": row["answers"][CONFIRM]}
        kept, unconfirmed = r.for_assessment([row], CONFIRM, "2026-09-25")
        assert kept == [] and len(unconfirmed) == 1


class TestLatestWins:
    def test_the_most_recent_response_is_the_one_kept(self):
        rows = [answer("a@x", "2026-09-20T09:00:00", picked=("W1",)),
                answer("a@x", "2026-09-20T17:00:00", picked=("W2",))]
        newest, superseded = r.latest_per_email(rows)
        assert superseded == 1
        assert newest["a@x"]["answers"][CHOOSE] == ["W2 - I can do W2 things"]

    def test_order_in_the_list_does_not_decide_it(self):
        """A test that passed by luck once before, because the input happened
        to be sorted."""
        rows = [answer("a@x", "2026-09-20T17:00:00", picked=("W2",)),
                answer("a@x", "2026-09-20T09:00:00", picked=("W1",))]
        newest, _ = r.latest_per_email(rows)
        assert newest["a@x"]["answers"][CHOOSE] == ["W2 - I can do W2 things"]

    def test_addresses_differing_only_in_case_are_one_student(self):
        rows = [answer("A@X", "2026-09-20T09:00:00", picked=("W1",)),
                answer("a@x", "2026-09-20T17:00:00", picked=("W2",))]
        newest, superseded = r.latest_per_email(rows)
        assert len(newest) == 1 and superseded == 1

    def test_an_unreadable_timestamp_is_a_sentence(self):
        rows = [answer("a@x", "not a date")]
        with pytest.raises(r.ResponseError, match="unreadable timestamp"):
            r.latest_per_email(rows)


class TestRecoveringTheSlug:
    def test_the_option_text_gives_back_the_slug(self):
        assert r.slug_of("W1 - I can convert numerals", KNOWN) == "W1"

    def test_a_description_containing_a_dash_does_not_confuse_it(self):
        assert r.slug_of("W2 - add base-b numbers - carefully", KNOWN) == "W2"

    def test_a_skill_with_no_description_still_works(self):
        assert r.slug_of("D1", KNOWN) == "D1"

    def test_an_unknown_slug_is_refused_rather_than_guessed(self):
        """A retired or renamed skill must not ride into a print run."""
        assert r.slug_of("ZZ9 - something else", KNOWN) == ""


class TestCollecting:
    def one(self, rows, roster=None, date="2026-09-25"):
        return r.collect(rows, roster or roster_of(ADA, BOB), ITEMS, date,
                         KNOWN)

    def test_a_student_is_matched_by_email_and_their_choices_recorded(self):
        out = self.one([answer("ada@example.edu", "2026-09-20T09:00:00",
                               picked=("W1", "W3"))])
        assert out.chosen == {"806001": ["W1", "W3"]}
        assert out.answered == 1

    def test_a_secondary_address_matches_too(self):
        """One real student appears under two addresses in two same-day
        exports, and the form only ever sees one of them."""
        out = self.one([answer("bo.m@other.example.edu",
                               "2026-09-20T09:00:00", picked=("W2",))])
        assert out.chosen == {"806002": ["W2"]}

    def test_an_address_nobody_on_the_roster_has_is_reported(self):
        out = self.one([answer("ghost@example.edu", "2026-09-20T09:00:00")])
        assert out.unknown_emails == ["ghost@example.edu"]
        assert out.chosen == {}

    def test_everyone_who_did_not_answer_is_listed(self):
        out = self.one([answer("ada@example.edu", "2026-09-20T09:00:00")])
        assert [s.sid for s in out.silent] == ["806002"]

    def test_a_dropped_student_is_not_counted_as_silent(self):
        people = roster_of(ADA, BOB)
        people.students[1].dropped = True
        out = self.one([answer("ada@example.edu", "2026-09-20T09:00:00")],
                       roster=people)
        assert out.silent == []

    def test_an_unrecognised_option_is_reported_not_dropped(self):
        row = answer("ada@example.edu", "2026-09-20T09:00:00")
        row["answers"][CHOOSE] = ["ZZ9 - retired last year"]
        out = self.one([row])
        assert out.unrecognised == [("ada@example.edu", "ZZ9 - retired last year")]
        assert out.chosen == {"806001": []}

    def test_a_duplicate_pick_is_recorded_once(self):
        row = answer("ada@example.edu", "2026-09-20T09:00:00")
        row["answers"][CHOOSE] = ["W1 - a", "W1 - a"]
        out = self.one([row])
        assert out.chosen == {"806001": ["W1"]}

    def test_the_counts_add_up(self):
        rows = [
            answer("ada@example.edu", "2026-09-20T09:00:00"),
            answer("ada@example.edu", "2026-09-20T10:00:00"),
            answer("bo@example.edu", "2026-09-20T09:00:00",
                   confirmed="Friday, 9/18"),
        ]
        rows.append(answer("x@y", "2026-09-20T09:00:00"))
        rows[-1]["answers"][CONFIRM] = []
        out = self.one(rows)
        assert out.superseded == 1
        assert out.out_of_scope == 1
        assert out.unconfirmed == 1

    def test_not_knowing_which_item_is_which_says_what_to_run(self):
        with pytest.raises(r.ResponseError, match="form map"):
            r.collect([], roster_of(ADA), {}, "2026-09-25", KNOWN)
