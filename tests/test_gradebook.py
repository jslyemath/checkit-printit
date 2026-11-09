"""The gradebook profile: the five facts, and finding a skill's column.

The headers below follow the naming Brightspace uses, which is the
exporter's doing and not anybody's data. No student appears here.
"""

import os

import pytest

from checkit_printit import gradebook as gb
from checkit_printit.gradebook import GradebookError, Profile

PASS = "\U0001f3c6Pass"
NOT_YET = "\U0001f4adNot Yet"

CORE = (["R1", "R2"] + [f"W{n}" for n in range(1, 8)]
        + [f"N{n}" for n in range(1, 5)] + [f"F{n}" for n in range(1, 6)]
        + [f"D{n}" for n in range(1, 5)])
EXPLAIN = ["W1-E", "W4-E", "N1-E", "F2-E", "F3-E", "F5-E", "D1-E"]
VIDEOS = [f"V{n}" for n in range(1, 9)]


def headers():
    out = ["OrgDefinedId",
           "Final Course Grade Grade Symbol <Selectbox MaxPoints:100>",
           "Total Core Skills Passed Formula Grade <Formula MaxPoints:22>",
           "Fundamentals Checkpoint Grade Symbol <Selectbox MaxPoints:1>",
           "My Base Project Grade Symbol <Selectbox MaxPoints:1>",
           "Participation Attendance and Homework (PAHW) Points Grade "
           "<Numeric MaxPoints:100>"]
    for slug in CORE:
        out.append(f"{slug} Grade Symbol <Selectbox MaxPoints:1 "
                   f"Category:Core Skills Progress>")
    out += ["Core Skills Progress Subtotal Numerator",
            "Core Skills Progress Subtotal Denominator"]
    for slug in EXPLAIN:
        out.append(f"{slug} Grade Symbol <Selectbox MaxPoints:1 "
                   f"Category:Explanation Skills Progress>")
    for slug in VIDEOS:
        out.append(f"{slug} Grade Symbol <Selectbox MaxPoints:1 "
                   f"Category:Modeling Math Videos Progress>")
    out.append("End-of-Line Indicator")
    return out


#: What the bank publishes: the core and explanation skills, plus `FCP`,
#: whose column is spelled out in words. The videos are not the bank's.
BANK = ["FCP"] + CORE + [s for s in EXPLAIN if s != "F5-E"]


# ----------------------------------------------------------- matching --

def test_almost_everything_matches_on_the_first_word():
    report = gb.match(headers(), BANK)
    assert len(report.found) == len(BANK) - 1
    assert report.missing == ["FCP"]
    assert set(report.how.values()) == {"the first word of the header"}


def test_a_skill_does_not_steal_another_skills_column():
    """`W1` must not take the `W1-E` column, or the other way round.

    This is the collision the pass ordering exists for. A hyphen is a
    word boundary to a regex, so a rule like "the slug appears as a word
    in the header" matches `W1` inside `W1-E Grade Symbol`. The exact
    first-word rule runs first and claims both correctly; the loose
    rules only ever see slugs it could not place.
    """
    head = headers()
    report = gb.match(head, BANK)
    for slug in ("W1", "W1-E", "W4", "W4-E", "N1", "N1-E", "D1", "D1-E",
                 "F2", "F2-E", "F3", "F3-E"):
        assert slug in report.found, slug
        assert gb.first_word(head[report.found[slug]]) == slug
    # And no two slugs share a column.
    columns = list(report.found.values())
    assert len(columns) == len(set(columns))


def test_the_looser_rules_also_avoid_the_collision():
    """A gradebook that does not put the code first.

    On his export the exact first-word rule places every skill, so the
    two fallback rules never run and nothing above tests them. Another
    LMS may well write `Skill W1 ...`, and the fallbacks have to get
    `W1` and `W1-E` right too -- the hyphen guard in their patterns is
    what does it, not the pass ordering.
    """
    head = [f"Skill {slug} Grade <Selectbox>" for slug in
            ("W1", "W1-E", "W4", "W4-E")]
    report = gb.match(head, ["W1", "W1-E", "W4", "W4-E"])
    assert report.missing == [], report.describe(head)
    assert report.ambiguous == {}
    for slug in ("W1", "W1-E", "W4", "W4-E"):
        assert head[report.found[slug]] == f"Skill {slug} Grade <Selectbox>"
    assert set(report.how.values()) == {"the slug as a word in the header"}


@pytest.mark.parametrize("header", [
    "W12 Grade <Selectbox>",        # the slug is a prefix of the first word
    "Skill W12 Grade <Selectbox>",  # and of a word further in
])
def test_a_slug_that_is_a_prefix_of_a_column_word_is_not_matched(header):
    """`W1` must not match a column about `W12`.

    Both forms are needed, and the first version of this test had only
    the second. The rule that says "the header starts with the slug"
    is only reached when the header does start with it, so
    `Skill W12 ...` never exercised the guard on that rule at all --
    breaking it left the suite green. `W12 Grade ...` does reach it.
    """
    report = gb.match([header], ["W1"])
    assert report.missing == ["W1"]
    assert report.ambiguous == {}


def test_a_spelled_out_column_is_left_for_the_instructor():
    report = gb.match(headers(), BANK)
    assert "FCP" in report.missing
    spare = [headers()[i] for i in report.spare]
    assert any(h.startswith("Fundamentals Checkpoint") for h in spare), \
        "the column FCP should be paired with is not offered as spare"


def test_a_saved_pair_is_used_and_said_so():
    head = headers()
    fcp = [h for h in head if h.startswith("Fundamentals Checkpoint")][0]
    report = gb.match(head, BANK, pairs={"FCP": fcp})
    assert report.missing == []
    assert report.found["FCP"] == head.index(fcp)
    assert report.how["FCP"] == "a pair saved in the profile"


def test_an_ambiguous_slug_is_reported_not_guessed():
    head = ["AD something", "AD other thing"]
    report = gb.match(head, ["AD"])
    assert report.missing == ["AD"]
    assert report.ambiguous["AD"] == [0, 1]
    assert "left unmatched rather than guessed" in report.describe(head)


def test_the_videos_are_left_alone():
    """They are not in the bank, so nothing should claim them."""
    head = headers()
    report = gb.match(head, BANK)
    for index in report.found.values():
        assert not gb.first_word(head[index]).startswith("V") or \
            gb.first_word(head[index]) in BANK


def test_a_column_the_bank_does_not_publish_stays_spare():
    """`F5-E` has a column but the bank does not publish the skill."""
    head = headers()
    report = gb.match(head, BANK)
    spare = [head[i] for i in report.spare]
    assert any(h.startswith("F5-E") for h in spare)


# -------------------------------------------------------------- marks --

def test_the_mark_strings_are_taken_from_the_file():
    """Including the absence of a space after the emoji.

    The real export writes the trophy character immediately followed by
    `Pass`, and the balloon immediately followed by `Not Yet`. An
    invented fixture written by hand had a space in the second one, and
    only the real file showed it.
    """
    rows = [[PASS, "", NOT_YET], [NOT_YET, PASS, ""], ["", PASS, PASS]]
    passed, not_passed, others = gb.guess_marks(rows, [0, 1, 2])
    assert passed == PASS
    assert not_passed == NOT_YET
    assert others == []
    assert " " not in passed
    assert not_passed.index("Not") == 1, "a space crept in after the emoji"


def test_a_vocabulary_it_cannot_read_is_handed_back():
    rows = [["yes", "no"], ["maybe", "yes"]]
    passed, not_passed, others = gb.guess_marks(rows, [0, 1])
    assert passed == ""
    assert not_passed == ""
    assert set(others) == {"yes", "no", "maybe"}


def test_too_many_distinct_values_is_refused():
    """And refused for *that* reason, not for want of a pass value.

    The first version of this test used twenty values none of which
    contained "pass", so it came back empty either way: once because
    there were too many, and once because no pass could be identified.
    Breaking the count check left the suite green. Putting exactly one
    `Pass` among them is what makes the count the only thing standing
    between a sensible refusal and a confident wrong answer.
    """
    rows = [["Pass"]] + [[f"grade {n}"] for n in range(20)]
    passed, not_passed, others = gb.guess_marks(rows, [0])
    assert passed == "", "it picked a mark vocabulary out of 21 values"
    assert not_passed == ""
    assert len(others) > gb.guess_marks.__defaults__[0]


def test_a_third_mark_is_reported_but_the_commonest_wins():
    rows = ([[PASS]] * 5 + [[NOT_YET]] * 3 + [["?"]])
    passed, not_passed, others = gb.guess_marks(rows, [0])
    assert passed == PASS
    assert not_passed == NOT_YET
    assert others == ["?"]


# ----------------------------------------------- does a blank count? --

class TestBlankEvidence:
    """Judged from the file, because it is the destructive one.

    If a blank is left out of the subtotal, writing a non-pass into one
    raises that student's denominator and lowers their grade. So the
    answer is read off the file rather than configured, and the
    evidence is reported so it can be disagreed with.
    """

    def _file(self, denominator=True, numerator=True):
        head = []
        for slug in ("W1", "W2", "W3", "W4"):
            head.append(f"{slug} Grade Symbol <Selectbox MaxPoints:1 "
                        f"Category:Core Skills Progress>")
        if numerator:
            head.append("Core Skills Progress Subtotal Numerator")
        if denominator:
            head.append("Core Skills Progress Subtotal Denominator")
        rows = []
        for filled, passes in ((4, 2), (3, 3), (2, 0), (4, 4), (1, 1)):
            row = []
            for n in range(4):
                if n < passes:
                    row.append(PASS)
                elif n < filled:
                    row.append(NOT_YET)
                else:
                    row.append("")
            if numerator:
                row.append(str(passes))
            if denominator:
                row.append(str(filled))
            rows.append(row)
        return head, rows, [0, 1, 2, 3]

    def test_it_finds_the_column_that_counts_filled_cells(self):
        head, rows, skills = self._file()
        meaning, evidence = gb.blank_evidence(rows, head, skills, PASS)
        assert meaning == "not attempted"
        assert "Denominator" in evidence
        assert "all 5 rows" in evidence

    def test_it_does_not_mistake_the_numerator_for_evidence(self):
        """A column counting passes says nothing about blanks."""
        head, rows, skills = self._file(denominator=False)
        meaning, evidence = gb.blank_evidence(rows, head, skills, PASS)
        assert evidence == "", f"it accepted {evidence}"
        assert meaning == "not attempted", "the cautious default stands"

    def test_no_evidence_still_gives_the_cautious_answer(self):
        head, rows, skills = self._file(denominator=False, numerator=False)
        meaning, evidence = gb.blank_evidence(rows, head, skills, PASS)
        assert meaning == "not attempted"
        assert evidence == ""

    def test_it_groups_by_the_category_in_the_header(self):
        """A subtotal usually covers one category, not every skill."""
        head, rows, skills = self._file()
        # Add an explanation skill with no subtotal of its own. Without
        # grouping, the core denominator would stop matching.
        head.insert(4, "W1-E Grade Symbol <Selectbox MaxPoints:1 "
                       "Category:Explanation Skills Progress>")
        for row in rows:
            row.insert(4, PASS)
        meaning, evidence = gb.blank_evidence(rows, head, [0, 1, 2, 3, 4],
                                              PASS)
        assert meaning == "not attempted"
        assert "Core Skills Progress columns" in evidence

    def test_a_category_is_read_off_the_header(self):
        assert gb.category_of(
            "W1 Grade Symbol <Selectbox MaxPoints:1 "
            "Category:Core Skills Progress>") == "Core Skills Progress"
        assert gb.category_of("W1 Grade Symbol <Selectbox>") == ""

    def test_one_column_on_its_own_is_not_evidence(self):
        """A single skill column equals too many things by accident."""
        head = ["W1 Grade Symbol <Selectbox Category:Core>", "Something"]
        rows = [[PASS, "1"], ["", "0"], [NOT_YET, "1"]]
        meaning, evidence = gb.blank_evidence(rows, head, [0], PASS)
        assert evidence == ""


# ------------------------------------------------------ shared base ids --

def test_a_retired_enrolment_is_found_by_its_shared_base_id():
    rows = [["#1234567890"], ["#1234567891"], ["#1234567891-DoNotUse"]]
    shared = gb.shared_base_ids(rows, 0)
    assert list(shared) == ["#1234567891"]
    assert [v for _, v in shared["#1234567891"]] == \
        ["#1234567891", "#1234567891-DoNotUse"]


def test_rows_with_no_marker_are_not_grouped():
    rows = [["#1234567890"], ["#1234567891"], ["#1234567892"]]
    assert gb.shared_base_ids(rows, 0) == {}


# --------------------------------------------------------- the profile --

def good():
    head = headers()
    return Profile(
        name="Brightspace MAT 106",
        student_column="OrgDefinedId", student_matches="alt_id",
        passed=PASS, not_passed=NOT_YET, blank_means="not attempted",
        pairs={"FCP": [h for h in head
                       if h.startswith("Fundamentals Checkpoint")][0]})


def test_a_good_profile_validates():
    good().validate(headers())


@pytest.mark.parametrize("break_it, expect", [
    (lambda p: setattr(p, "student_column", ""), "no student column"),
    (lambda p: setattr(p, "passed", ""), "no `passed` value"),
    (lambda p: setattr(p, "not_passed", ""), "no `not_passed` value"),
    (lambda p: setattr(p, "not_passed", PASS), "are the same string"),
    (lambda p: setattr(p, "blank_means", "maybe"), "`blank_means` is"),
    (lambda p: setattr(p, "student_matches", "name"), "`matches` is"),
    (lambda p: setattr(p, "student_column", "Nope"), "no column called"),
    (lambda p: p.pairs.update({"FCP": "Nope"}), "paired with a column"),
])
def test_validation_catches_each_way_it_can_be_wrong(break_it, expect):
    profile = good()
    break_it(profile)
    with pytest.raises(GradebookError, match=expect):
        profile.validate(headers())


def test_a_profile_round_trips_through_disk(tmp_path):
    path = str(tmp_path / gb.FILENAME)
    gb.save(path, good())
    again = gb.load(path)
    assert again.passed == PASS
    assert again.not_passed == NOT_YET
    assert again.student_column == "OrgDefinedId"
    assert again.pairs["FCP"].startswith("Fundamentals Checkpoint")
    again.validate(headers())


def test_the_emoji_survive_the_file(tmp_path):
    """They are the cell contents, so they have to come back exactly."""
    path = str(tmp_path / gb.FILENAME)
    gb.save(path, good())
    with open(path, "rb") as f:
        raw = f.read()
    assert PASS.encode("utf-8") in raw
    assert NOT_YET.encode("utf-8") in raw
    assert gb.load(path).passed == PASS


def test_the_file_explains_what_blank_means(tmp_path):
    """Because it is the one fact that can lower somebody's grade."""
    profile = good()
    text = profile.to_toml()
    assert "lower their grade" in text

    profile.blank_means = "zero"
    assert "already a zero" in profile.to_toml()


def test_the_ignore_list_is_one_column_per_line(tmp_path):
    """A thirty-item array on one line is not something anybody checks."""
    profile = good()
    profile.ignore_columns = [f"Column {n} <Numeric>" for n in range(30)]
    text = profile.to_toml()
    longest = max(len(line) for line in text.splitlines())
    assert longest < 100, f"the widest line is {longest} characters"
    assert text.count('",\n') >= 30


def test_a_profile_carries_no_student_data(tmp_path, monkeypatch):
    """So it is safe to read out, to share, and to keep in a repo.

    Derived from a masked file and then checked against the vault that
    masked it: neither a real value nor a pseudonym may appear. If a
    profile ever captured an id -- as a student column's *contents*
    rather than its name, say -- then sharing the profile would leak,
    and the profile is the one file in this feature meant to be shared
    freely.

    **The second assertion is the one that catches it**, checked by
    injecting a masked id into a profile by hand: `vault.leaks` did
    not fire, correctly, because the injected value is a pseudonym and
    not a real value. A pseudonym is not a leak of real data, but it
    is still student-linked and has no business in a file meant to go
    anywhere. Both halves are needed and they do different jobs.
    """
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    from checkit_printit import mask as mask_mod
    from checkit_printit.vault import Vault

    source = tmp_path / "grades.csv"
    head = headers()
    lines = [",".join(head)]
    for n in range(6):
        row = [f"#204100000{n}"] + [""] * (len(head) - 1)
        for i, h in enumerate(head):
            if gb.first_word(h) in CORE[:4]:
                row[i] = PASS if n % 2 else NOT_YET
        row[head.index("Core Skills Progress Subtotal Numerator")] = \
            str(4 if n % 2 else 0)
        row[head.index("Core Skills Progress Subtotal Denominator")] = "4"
        lines.append(",".join(row))
    source.write_text("\n".join(lines) + "\n", encoding="utf-8")

    twin = str(tmp_path / "twin.csv")
    vault = Vault(course="TEST 100")
    mask_mod.mask_file(str(source), twin, vault)

    rows = mask_mod.read_rows(twin)
    report = gb.match(rows[0], BANK)
    skills = sorted(report.found.values())
    passed, not_passed, _ = gb.guess_marks(rows[1:], skills)
    meaning, _ = gb.blank_evidence(rows[1:], rows[0], skills, passed)
    profile = Profile(
        name="made from a twin", student_column=rows[0][0],
        student_matches="alt_id", passed=passed, not_passed=not_passed,
        blank_means=meaning,
        ignore_columns=[rows[0][i] for i in report.spare])

    text = profile.to_toml()
    assert vault.leaks(text) == [], "a real value reached the profile"
    for fake in vault.fake_values():
        if len(fake) >= 4:
            assert fake not in text, f"the pseudonym {fake!r} reached it"

    # And it is still a usable profile, not an empty one.
    assert profile.passed == PASS
    assert profile.blank_means == "not attempted"
    assert len(profile.ignore_columns) > 10


def test_a_missing_profile_says_how_to_make_one(tmp_path):
    with pytest.raises(GradebookError, match="gradebook map"):
        gb.load(str(tmp_path / "nothing.toml"))


def test_the_profile_lives_beside_the_courses_other_state(tmp_path,
                                                          monkeypatch):
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
    from checkit_printit import course as course_mod
    assert os.path.dirname(gb.path_for("MAT 106")) == \
        course_mod.path_for("MAT 106")
