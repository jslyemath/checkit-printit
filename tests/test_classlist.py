"""Importing a class list, in the three shapes that actually turned up.

The fixtures are synthetic but their *shape* is copied from real exports: the
same headers in the same places, the same preamble above the Banner summary
table, the same instructor and mentor rows in the LMS export, and the same
split between two id systems. No real student appears here.
"""

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from checkit_printit import classlist
from checkit_printit.roster import Roster, Student


# Banner detail: header on row 1, three name columns, and -- uniquely -- both
# id systems, which makes it the file that ties the other two together.
BANNER_DETAIL = '''"Student ID","Student Last Name","Student First Name","Student MI","Major Code","Subject","Course","Section","Email","Global ID"
"806000001","Lovelace","Augusta","Ada"," 383","MAT","106","820","alovelace@example.edu","2000000001"
"806000002","Vantreight Pemberton","Odessa",""," 388","MAT","106","820","bvantreight@example.edu","2000000002"
"806000003","Hopper","Grace","B"," 384","MAT","106","830","ghopper@example.edu","2000000003"
'''

# LMS export: one name column as "Last, First", only the Global id, and two
# rows that are not students.
LMS_EXPORT = '''Name,Pronouns,UserName,OrgDefinedId,Email,Role,LastAccessed
"Lovelace, Augusta",,2000000001,2000000001,alovelace@example.edu,OSW - Student (Non-Cascading),"Sep 18, 2026 10:05 AM"
"Vantreight Pemberton, Odessa",,2000000002,2000000002,b.vantreight@other.edu,OSW - Student (Non-Cascading),"Sep 17, 2026 9:04 PM"
"Hopper, Grace",,2000000003,2000000003,ghopper@example.edu,OSW - Student (Non-Cascading),"Sep 14, 2026 9:18 AM"
"Jerred, Emmy",,2000000009,2000000009,mentor@example.edu,Mentor,"Sep 18, 2026 9:27 AM"
"Teacher, A",he/him,680447,680447,,OSW - Instructor (Non-Cascading),"Sep 20, 2026 5:58 PM"
'''

# Banner summary: a course-information block sits above the real header, which
# lands on row 15. No email column at all.
BANNER_SUMMARY = [
    ["Course Information", "", "", ""],
    ["Course Title", "Number Systems", "", ""],
    ["Term", "Fall 2026 - 202609", "", ""],
    ["CRN", "96126", "", ""],
    ["Duration", "08/24/2026 - 12/11/2026", "", ""],
    ["Status", "Active", "", ""],
    ["", "", "", ""],
    ["Enrollment Counts", "", "", ""],
    ["", "Maximum", "Actual", "Remaining"],
    ["Enrollment", "26", "24", "2"],
    ["Wait List", "25", "0", "25"],
    ["Cross List", "0", "0", "0"],
    ["", "", "", ""],
    ["Summary Class List", "", "", ""],
    ["Student Name", "ID", "Registration Status", "Class"],
    ["Lovelace, Augusta A.", "806000001", "**Registered**", "1st sem freshman"],
    ["Vantreight Pemberton, Odessa", "806000002", "**Registered**", "1st sem freshman"],
    ["Hopper, Grace B.", "806000003", "**Registered**", "2nd sem freshman"],
]


def write(tmp_path, name, text):
    p = tmp_path / name
    p.write_text(text, encoding="utf-8")
    return str(p)


def write_xlsx(tmp_path, name, rows):
    openpyxl = pytest.importorskip("openpyxl")
    book = openpyxl.Workbook()
    sheet = book.active
    for row in rows:
        sheet.append(row)
    p = tmp_path / name
    book.save(str(p))
    return str(p)


class TestFindingTheColumns:
    def test_banner_detail(self, tmp_path):
        students, mapping, _ = classlist.parse(
            write(tmp_path, "class-list.csv", BANNER_DETAIL))
        assert mapping.header_row == 0
        assert len(students) == 3
        s = students[0]
        assert (s.last, s.first) == ("Lovelace", "Augusta")
        assert s.sid == "806000001" and s.alt_id == "2000000001"
        assert s.section == "820"

    def test_lms_export(self, tmp_path):
        students, mapping, notes = classlist.parse(
            write(tmp_path, "lms.csv", LMS_EXPORT), section="820")
        assert len(students) == 3, "the mentor and the instructor came through"
        assert {s.last for s in students} == {"Lovelace", "Vantreight Pemberton", "Hopper"}
        assert all(s.sid == "" for s in students), "this export has no Banner id"
        assert all(s.alt_id for s in students)
        assert any("non-student" in n for n in notes)

    def test_a_header_row_that_is_not_the_first(self, tmp_path):
        students, mapping, notes = classlist.parse(
            write_xlsx(tmp_path, "summary.xlsx", BANNER_SUMMARY), section="820")
        assert mapping.header_row == 14, "the preamble should not be mistaken for it"
        assert len(students) == 3
        assert any("no email" in n for n in notes), \
            "a roster with no addresses cannot match form responses; say so"

    def test_section_comes_from_the_flag_when_the_file_lacks_one(self, tmp_path):
        students, _, _ = classlist.parse(
            write(tmp_path, "lms.csv", LMS_EXPORT), section="830")
        assert {s.section for s in students} == {"830"}

    def test_a_file_that_is_not_a_class_list_says_so(self, tmp_path):
        with pytest.raises(classlist.ClassListError, match="header row"):
            classlist.parse(write(tmp_path, "nope.csv", "a,b,c\n1,2,3\n"))


class TestNames:
    def test_a_multi_word_surname_stays_whole(self):
        assert classlist.split_full_name("Vantreight Pemberton, Odessa") == \
            ("Vantreight Pemberton", "Odessa", "")

    def test_a_middle_initial_is_separated(self):
        assert classlist.split_full_name("Lovelace, Augusta A.") == \
            ("Lovelace", "Augusta", "A.")

    def test_no_comma_falls_back_to_first_last(self):
        assert classlist.split_full_name("Grace Hopper") == ("Hopper", "Grace", "")

    def test_an_unrecognised_role_is_kept_and_reported(self):
        keep, reason = classlist.looks_like_a_student("Visiting Scholar")
        assert keep and "unrecognised" in reason

    def test_a_dropped_status_is_not_a_student(self):
        keep, _ = classlist.looks_like_a_student("**Dropped**")
        assert not keep


class TestMerging:
    def banner(self, tmp_path):
        return classlist.parse(write(tmp_path, "b.csv", BANNER_DETAIL))[0]

    def lms(self, tmp_path):
        return classlist.parse(write(tmp_path, "l.csv", LMS_EXPORT), section="820")[0]

    def summary(self, tmp_path):
        return classlist.parse(
            write_xlsx(tmp_path, "s.xlsx", BANNER_SUMMARY), section="820")[0]

    def test_the_same_people_from_a_different_export_are_not_duplicated(self, tmp_path):
        roster, _ = classlist.merge(Roster([]), self.banner(tmp_path))
        roster, report = classlist.merge(roster, self.lms(tmp_path))
        assert report.added == [], "matched on the Global id"
        assert len(roster) == 3

    def test_two_exports_sharing_no_id_still_match_on_name(self, tmp_path):
        """The LMS carries only the Global id and the summary only the Banner
        id, so nothing links them but the name."""
        roster, _ = classlist.merge(Roster([]), self.lms(tmp_path))
        roster, report = classlist.merge(roster, self.summary(tmp_path))
        assert report.added == []
        assert len(roster) == 3

    def test_a_preferred_name_matches_the_legal_one(self, tmp_path):
        """An adopted roster says "Ada Lovelace"; the registrar says "Augusta
        Ada Lovelace". The display names differ and the adopted row has no id,
        so surname-plus-initial is the only thing that can join them -- and
        without it every student who goes by a short form imports as a second
        copy of themselves. Measured on a real roster: two of twenty-five."""
        roster = Roster([Student(name="Ada Lovelace", skills=["W1"])])
        roster, report = classlist.merge(roster, self.banner(tmp_path))
        assert "Augusta Lovelace" not in report.added, "imported as a duplicate"
        ada = next(s for s in roster if s.name == "Ada Lovelace")
        assert ada.sid == "806000001", "the ids should have been filled in"
        assert ada.first == "Augusta", "the legal name is recorded"
        assert ada.skills == ["W1"], "and what was authored survives"

    def test_a_second_address_is_added_not_substituted(self, tmp_path):
        """One real student had two addresses across two same-day exports, and
        the Google Form only ever saw the first. Replacing it would have
        silently stopped her responses from matching."""
        roster, _ = classlist.merge(Roster([]), self.banner(tmp_path))
        roster, _ = classlist.merge(roster, self.lms(tmp_path))
        odessa = next(s for s in roster if s.last == "Vantreight Pemberton")
        assert odessa.email == "bvantreight@example.edu", "the primary must not move"
        assert "b.vantreight@other.edu" in odessa.all_emails()

    def test_a_student_known_only_by_address_is_matched_not_duplicated(self, tmp_path):
        """A roster can be seeded from form responses, which carry an email and
        nothing else. The class list that arrives later has ids and no idea
        what it is joining to."""
        roster = Roster([Student(name="A Lovelace", skills=[],
                                 email="alovelace@example.edu")])
        roster, report = classlist.merge(roster, self.banner(tmp_path))
        assert report.added == ["Odessa Vantreight Pemberton", "Grace Hopper"],             "the one already known by address should have been matched"
        assert len(roster) == 3
        found = next(s for s in roster if s.email == "alovelace@example.edu")
        assert found.sid == "806000001", "the ids should have been filled in"

    def test_absence_marks_dropped_rather_than_deleting(self, tmp_path):
        roster, _ = classlist.merge(Roster([]), self.banner(tmp_path))
        # a 820 student leaves; 820 is still represented by the other one
        fewer = [s for s in self.banner(tmp_path) if s.last != "Lovelace"]
        roster, report = classlist.merge(roster, fewer)
        assert report.dropped == ["Augusta Lovelace"]
        assert len(roster) == 3, "the print record still refers to them"
        assert next(s for s in roster if s.last == "Lovelace").dropped

    def test_importing_one_section_leaves_the_other_alone(self, tmp_path):
        """A class list is usually one section and a course may hold
        several. Without scoping, importing 820 would drop all of 830."""
        roster, _ = classlist.merge(Roster([]), self.banner(tmp_path))
        only820 = [s for s in self.banner(tmp_path) if s.section == "820"]
        roster, report = classlist.merge(roster, only820)
        assert report.dropped == []
        assert not next(s for s in roster if s.section == "830").dropped

    def test_emptying_a_section_needs_the_coverage_stated(self, tmp_path):
        """The hole in inferring coverage from the file: when the last student
        in a section leaves, the section vanishes from the file too, so
        absence cannot be told from silence. Saying so explicitly resolves it."""
        roster, _ = classlist.merge(Roster([]), self.banner(tmp_path))
        only820 = [s for s in self.banner(tmp_path) if s.section == "820"]

        quiet, report = classlist.merge(roster, only820)
        assert report.dropped == [], "inferred coverage cannot see 830 at all"

        stated, report = classlist.merge(roster, only820, scope={"820", "830"})
        assert report.dropped == ["Grace Hopper"]

    def test_returning_after_a_drop_un_drops(self, tmp_path):
        roster, _ = classlist.merge(Roster([]), self.banner(tmp_path))
        roster, _ = classlist.merge(
            roster, [s for s in self.banner(tmp_path) if s.last != "Lovelace"])
        roster, report = classlist.merge(roster, self.banner(tmp_path))
        assert not next(s for s in roster if s.last == "Lovelace").dropped
        assert any("re-enrolled" in u for u in report.updated)

    def test_a_re_import_does_not_rename_the_printed_page(self, tmp_path):
        """The seating chart says "Matt Marrowby"; the registrar says "Matthew".
        A class list must never overwrite what prints."""
        roster = Roster([Student(name="Gus Lovelace", skills=["W1"],
                                 preferred="Gus", sid="806000001",
                                 last="Lovelace", first="Augusta")])
        roster, _ = classlist.merge(roster, self.banner(tmp_path))
        gus = next(s for s in roster if s.sid == "806000001")
        assert gus.name == "Gus Lovelace"
        assert gus.preferred == "Gus"
        assert gus.skills == ["W1"]
        assert gus.first == "Augusta", "the legal name is still recorded"


def person(first, last, sid="", email="", section="820"):
    return Student(name=f"{first} {last}", skills=[], first=first, last=last,
                   sid=sid, email=email, section=section)


class TestTwoPeopleWhoShareASurnameAndAnInitial:
    """RV-2 of the 2026-11-16 review.

    The surname-plus-initial rule joins "Matt Marrowby" to "Marrowby,
    Matthew C." when the roster row has no id. It also joined a new
    student to an existing one whenever exactly one roster student held
    the key -- Jordan Smith into Jamie Smith -- without asking whether
    the two carried different ids. One roster entry came out holding
    one student's id and the other's address, reported as "1 updated".
    """

    JAMIE = ("Jamie", "Smith", "900000001", "jamie@example.edu")
    JORDAN = ("Jordan", "Smith", "900000002", "jordan@example.edu")

    def merged(self, *incoming):
        roster = Roster([person(*self.JAMIE)])
        return classlist.merge(roster, [person(*p) for p in incoming])

    @pytest.mark.parametrize("order", ["existing first", "new one first"])
    def test_the_new_student_is_added(self, order):
        rows = ((self.JAMIE, self.JORDAN) if order == "existing first"
                else (self.JORDAN, self.JAMIE))
        roster, report = self.merged(*rows)
        assert report.added == ["Jordan Smith"]
        assert sorted(s.sid for s in roster) == ["900000001", "900000002"]

    @pytest.mark.parametrize("order", ["existing first", "new one first"])
    def test_nobody_ends_up_with_the_other_s_address(self, order):
        rows = ((self.JAMIE, self.JORDAN) if order == "existing first"
                else (self.JORDAN, self.JAMIE))
        roster, _ = self.merged(*rows)
        jamie = next(s for s in roster if s.sid == "900000001")
        assert jamie.all_emails() == ["jamie@example.edu"]

    def test_a_different_id_is_never_joined_on_the_name_alone(self):
        """Even an identical name. Two people can share one."""
        roster, report = self.merged(("Jamie", "Smith", "900000003", ""))
        assert report.added == ["Jamie Smith"]
        assert len(roster) == 2

    def test_one_roster_student_is_matched_at_most_once(self):
        """The existing row has no id, so the id rule cannot help; two
        incoming people who both reduce to (smith, j) must not both
        land on it."""
        roster = Roster([Student(name="J Smith", skills=["W1"])])
        roster, report = classlist.merge(
            roster, [person(*self.JAMIE), person(*self.JORDAN)])
        holders = [s for s in roster if s.sid]
        assert sorted(s.sid for s in holders) == ["900000001", "900000002"]
        assert len({id(s) for s in holders}) == 2

    def test_two_spellings_in_one_file_do_not_share_a_roster_row(self):
        """The case only the claimed-once rule catches: different name
        keys, no conflicting id, one roster row reachable by both. The
        second is added, so it shows up in the report as a question
        rather than being merged into somebody silently."""
        roster = Roster([Student(name="Matt Marrowby", skills=["W1"],
                                 first="Matthew", last="Marrowby")])
        roster, report = classlist.merge(roster, [
            person("Matthew", "Marrowby", "900000009"),
            Student(name="Matt Marrowby", skills=[], section="820",
                    email="other@example.edu")])
        matt = next(s for s in roster if s.sid == "900000009")
        assert "other@example.edu" not in matt.all_emails()
        assert report.added == ["Matt Marrowby"]

    def test_an_exact_name_still_matches_by_name(self):
        """Not by the weaker initial rule it would fall through to.
        A row's name and its first-plus-last are the same key, and an
        early version of the shared-key count saw that as two rows."""
        roster = Roster([Student(name="Jamie Smith", skills=["W1"]),
                         Student(name="Jo Smith", skills=["D2"])])
        roster, report = classlist.merge(
            roster, [person("Jamie", "Smith", "900000001")])
        jamie = next(s for s in roster if s.sid == "900000001")
        assert jamie.skills == ["W1"]
        assert report.added == []

    def test_the_rule_still_does_its_job(self):
        """What it is for: a roster adopted from a print job, no id,
        and the class list's legal name."""
        roster = Roster([Student(name="Matt Marrowby", skills=["W1"])])
        roster, report = classlist.merge(
            roster, [person("Matthew", "Marrowby", "900000009")])
        assert report.added == []
        assert roster.students[0].sid == "900000009"
        assert roster.students[0].skills == ["W1"]
