"""The pseudonym vault and the file masker.

Every fixture here is invented. The point of the module under test is
that real student data never reaches anybody who did not already have
it, and a test suite is somewhere.

The names below are chosen to *look* like the awkward real cases --
a two-word surname, a student with two email domains, a retired
enrolment marked `-DoNotUse` -- without being anybody.
"""

import os

import pytest

from checkit_printit import mask as mask_mod
from checkit_printit.mask import MaskError
from checkit_printit.vault import Vault, VaultError


# ------------------------------------------------------------- fixtures --

CLASSLIST = """\
Student ID,Global ID,Student Last Name,Student First Name,Student MI,Email,Section
806000111,1234567890,Vanterpool Reyes,Marguerite,Q,mvanter3@institute.edu,820
806000222,1234567891,Okonkwo,Chidi,,cokonkwo@institute.edu,820
806000333,1234567892,Fairweather,Benedict,T,bfairwea@institute.edu,830
806000444,1234567893,Nakashima,Harriet,,hnakashi@alt.institute.edu,830
806000555,1234567894,Prendergast,Solomon,R,sprender@institute.edu,820
806000666,1234567895,Achterberg,Winifred,,wachterb@institute.edu,820
"""

#: Shaped after what §14.6 records about the real Brightspace export:
#: the id column first, no name column of any kind, selectbox grade
#: symbols with emoji, a `-DoNotUse` row, numeric subtotals, and an
#: end-of-line indicator that is `#` in every row.
GRADES = """\
OrgDefinedId,Fundamentals Checkpoint Grade Symbol <Selectbox MaxPoints:1>,\
F1-A Grade Symbol <Selectbox MaxPoints:1>,F2-B Grade Symbol <Selectbox \
MaxPoints:1>,Core Skills Progress Subtotal Numerator,End-of-Line Indicator
#1234567890,\U0001f3c6Pass,\U0001f4ad Not Yet,,1,#
#1234567891,\U0001f3c6Pass,\U0001f3c6Pass,,2,#
#1234567892,,\U0001f3c6Pass,\U0001f4ad Not Yet,1,#
#1234567893,\U0001f3c6Pass,,\U0001f3c6Pass,2,#
#1234567894,\U0001f4ad Not Yet,\U0001f3c6Pass,,1,#
#1234567894-DoNotUse,,,,0,#
"""


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path / "home"))
    return tmp_path


def write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return str(path)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def rows_of(path):
    return [line.split(",") for line in read(path).strip().splitlines()]


# ------------------------------------------------------- where it lives --

@pytest.mark.parametrize("set_home", [True, False])
def test_the_vault_is_a_sibling_of_courses_not_a_child(tmp_path, monkeypatch,
                                                       set_home):
    """Masking a course folder must not be able to walk into the vault.

    **Both branches.** `default_root` answers from `CHECKIT_PRINTIT_HOME`
    when it is set and from the user's home when it is not, and the
    first version of this test only ever exercised the first: breaking
    the fallback on purpose left the suite green. That is the "a fix
    applied to one path is not applied to the others" failure in its
    usual shape, and it is why this is parametrised.
    """
    from checkit_printit import course as course_mod
    from checkit_printit import vault as vault_mod

    if set_home:
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path / "home"))
    else:
        monkeypatch.delenv("CHECKIT_PRINTIT_HOME", raising=False)

    courses = os.path.abspath(course_mod.default_root())
    vaults = os.path.abspath(vault_mod.default_root())
    assert os.path.dirname(courses) == os.path.dirname(vaults)
    assert not vaults.startswith(courses + os.sep)


def test_a_course_name_with_a_slash_is_refused(home):
    from checkit_printit import vault as vault_mod
    with pytest.raises(VaultError):
        vault_mod.path_for("MAT 106/820")


# ----------------------------------------------------------- the columns --

def test_the_classlist_columns_are_recognised(home, tmp_path):
    src = write(tmp_path / "class.csv", CLASSLIST)
    rows = mask_mod.read_rows(src)
    plan = mask_mod.plan(rows)

    by_kind = {d.kind: d for d in plan.decisions if d.action == "mask"}
    assert set(by_kind) == {"sid", "alt_id", "last", "first", "middle",
                            "email"}
    section = [d for d in plan.decisions if "Section" in d.header][0]
    assert section.action == "keep"


def test_the_grades_export_columns_are_recognised(home, tmp_path):
    """No name column at all, which is what the real file looks like."""
    src = write(tmp_path / "grades.csv", GRADES)
    rows = mask_mod.read_rows(src)
    plan = mask_mod.plan(rows)

    assert plan.header_row == 0
    actions = {d.header: d.action for d in plan.decisions}
    assert actions["OrgDefinedId"] == "mask"
    # The grade vocabulary is two short values, so it reads as a category.
    assert actions["F1-A Grade Symbol <Selectbox MaxPoints:1>"] == "keep"
    assert actions["Core Skills Progress Subtotal Numerator"] == "keep"
    assert actions["End-of-Line Indicator"] == "keep"
    assert all(a != "blank" for a in actions.values())


def test_an_unrecognised_column_is_blanked_not_passed_through(home, tmp_path):
    text = CLASSLIST.replace(
        "Email,Section", "Email,Section,Advising Notes").replace(
        "820\n806000222", "820,wants to switch to the 9am section\n806000222")
    src = write(tmp_path / "class.csv", text)
    rows = mask_mod.read_rows(src)
    plan = mask_mod.plan(rows)
    notes = [d for d in plan.decisions if d.header == "Advising Notes"][0]
    assert notes.action == "blank"


def test_an_id_shaped_column_with_no_label_is_blanked(home, tmp_path):
    """Rule 3 before rule 4: a 9-digit number is not 'just a number'."""
    action, why = mask_mod.classify(["806000111", "806000222", "806000333"])
    assert action == "blank"
    assert "digits" in why


def test_a_points_column_is_kept(home, tmp_path):
    action, _ = mask_mod.classify(["0", "1", "0.5", "4", "2.25"])
    assert action == "keep"


def test_points_written_to_five_decimal_places_are_kept(home):
    """What Brightspace actually writes, and what it cost.

    A real export's `Participation Attendance and Homework` column holds
    `10.00000`. Those five zeros after the point are a run of five
    digits, so the "this might be a student id" test blanked the whole
    column -- an ordinary grade column emptied on his real file.
    """
    action, why = mask_mod.classify(["10.00000", "8.50000", "0.00000"])
    assert action == "keep", why


def test_a_whole_number_id_is_still_caught(home):
    """The decimal exemption must not let a real id through.

    The last case is the one that matters, and the first version of this
    test did not have it. `_whole_part` claims in its docstring that it
    only trims cells that are numbers all the way through, "so this can
    never quietly shorten an id that happens to sit next to other
    text". Breaking it to strip everything after the first dot left the
    suite green: the other two cases below do not exercise the guard at
    all, because stripping after a dot does not change either of them.

    A claim made in a comment and not tested is a claim nobody has
    checked.
    """
    action, _ = mask_mod.classify(["806000111", "806000222", "806000333"])
    assert action == "blank"

    # Still id-shaped before the point.
    action, _ = mask_mod.classify(["806000111.0", "806000222.0"])
    assert action == "blank"

    # Not a number, so not trimmed: the id after the dot must survive
    # the test and still be seen.
    action, why = mask_mod.classify(["ref.806000111", "ref.806000222",
                                     "ref.806000333", "ref.806000444",
                                     "ref.806000555"])
    assert action == "blank", why


def test_the_column_report_fits_the_terminal(home, monkeypatch):
    """Long gradebook headers wrapped, and a wrapped table is unreadable.

    On his real export the console redrew wrapped rows and whole lines
    repeated down the screen; he could not tell the report from the
    corruption.
    """
    import collections
    import shutil as shutil_mod

    header = ["OrgDefinedId",
              "Participation Attendance and Homework (PAHW) Points Grade "
              "<Numeric MaxPoints:100 Category:Other>"]
    rows = [header, ["#2041000001", "10.00000"], ["#2041000002", "8.50000"],
            ["#2041000003", "9.00000"], ["#2041000004", "7.00000"],
            ["#2041000005", "6.00000"]]

    for columns in (80, 100, 200):
        monkeypatch.setattr(
            shutil_mod, "get_terminal_size",
            lambda _default=None, c=columns: collections.namedtuple(
                "size", "columns lines")(c, 24))
        text = mask_mod.plan(rows).describe()
        longest = max(len(line) for line in text.splitlines())
        assert longest <= columns, (
            f"at {columns} columns the widest line was {longest}")


def test_a_free_text_column_is_blanked(home, tmp_path):
    action, why = mask_mod.classify([f"note number {n}" for n in range(20)])
    assert action == "blank"
    assert "free text" in why


class TestASparseNameColumn:
    """RV-3 of the 2026-11-16 review.

    "Few distinct short values" was taken to mean a category. A
    "Preferred Name" column where seven of thirty students have one is
    exactly that shape: it was kept, written to the twin, and the leak
    check passed, because the vault was never told those strings.
    """

    NICKS = {2: "Chichi", 5: "Fred", 9: "Jojo", 13: "Nadz", 17: "Rafa",
             21: "Vik", 27: "Bo-Bo"}
    FIRST = ["Aiko", "Bram", "Chidi", "Dara", "Elif", "Farid", "Greta",
             "Hoang", "Imani", "Jonas", "Kirra", "Lucia", "Mateo", "Nadia",
             "Oskar", "Priya", "Quinn", "Rafael", "Sanna", "Tomas", "Uma",
             "Viktor", "Wren", "Xavier", "Yara", "Zoltan", "Anouk", "Bodhi",
             "Cosima", "Dmitri"]

    def rows(self, header="Preferred Name"):
        out = [["OrgDefinedId", "Last Name", "First Name", header, "Email",
                "Section"]]
        for i, first in enumerate(self.FIRST):
            out.append([f"#80{i:07d}", f"Surname{i:02d}x", first,
                        self.NICKS.get(i, ""),
                        f"{first.lower()}{i}@school.example", "820"])
        return out

    @pytest.mark.parametrize("header", ["Preferred Name", "Preferred First Name",
                                        "Nickname", "Goes By"])
    def test_a_preferred_name_header_is_masked(self, home, header):
        plan = mask_mod.plan(self.rows(header))
        col = [d for d in plan.decisions if d.header == header][0]
        assert col.action == "mask", col.why

    def test_an_unlabelled_column_of_names_is_blanked(self, home):
        """A header nothing recognises, holding names that each occur
        once. Categories repeat; names do not."""
        plan = mask_mod.plan(self.rows("Misc"))
        col = [d for d in plan.decisions if d.header == "Misc"][0]
        assert col.action == "blank", col.why

    def test_a_value_that_is_somebody_s_first_name_is_blanked(self, home):
        """Repeating is not enough when the repeated value is a name
        the file already holds in a name column."""
        rows = self.rows("Misc")
        for row in rows[1:]:
            row[3] = ""               # nothing that occurs once
        for row in rows[1:4]:
            row[3] = "Greta"          # repeats, and is row 7's first name
        plan = mask_mod.plan(rows)
        col = [d for d in plan.decisions if d.header == "Misc"][0]
        assert col.action == "blank", col.why

    def test_no_nickname_reaches_the_twin(self, home, tmp_path):
        src = str(tmp_path / "class.csv")
        out = str(tmp_path / "class.masked.csv")
        mask_mod.write_csv(src, self.rows())
        vault = Vault(course="TEST 101")
        mask_mod.mask_file(src, out, vault)
        text = read(out)
        assert [n for n in self.NICKS.values() if n in text] == []

    def test_a_nickname_does_not_change_who_the_row_is(self, home, tmp_path):
        """Masked, but not used to identify: the same student in a file
        without the column must get the same pseudonym.

        Names only, no id or address -- with either, the row is found by
        that before any name is looked at, and this could not fail."""
        vault = Vault(course="TEST 101")
        with_nick = str(tmp_path / "a.csv")
        without = str(tmp_path / "b.csv")
        rows = [r[1:4] + r[5:] for r in self.rows()]     # last, first, nick
        mask_mod.write_csv(with_nick, rows)
        mask_mod.write_csv(without, [r[:2] + r[3:] for r in rows])
        mask_mod.mask_file(with_nick, str(tmp_path / "a.out.csv"), vault)
        before = len(vault.people)
        mask_mod.mask_file(without, str(tmp_path / "b.out.csv"), vault)
        assert len(vault.people) == before == 30

    def test_the_grade_vocabulary_is_still_a_category(self, home, tmp_path):
        """What the rule exists for. A grade value repeats across the
        whole file even where one column holds it once."""
        rows = mask_mod.read_rows(write(tmp_path / "grades.csv", GRADES))
        actions = {d.header: d.action for d in mask_mod.plan(rows).decisions}
        assert actions["Fundamentals Checkpoint Grade Symbol "
                       "<Selectbox MaxPoints:1>"] == "keep"

    def test_no_seed_makes_the_mask_refuse_itself(self, home, tmp_path):
        """A fake email built from a fake name could spell a real first
        name -- "b" + "ramanujan" contains "Bram" -- and the leak check
        then refused the twin. About one seed in thirty on this file.
        Swept, because a vault picks its seed at random."""
        src = str(tmp_path / "class.csv")
        mask_mod.write_csv(src, self.rows())
        refused = []
        for seed in range(80):
            try:
                mask_mod.mask_file(src, str(tmp_path / "o.csv"),
                                   Vault(course="T", seed=seed))
            except MaskError:
                refused.append(seed)
        assert refused == []

    def test_no_seed_breaks_the_round_trip(self, home, tmp_path):
        """A nickname masked as a shortening of one student's fake name
        could equal another student's fake, and unmasking then gave one
        student the other's name. About one seed in twenty."""
        src = str(tmp_path / "class.csv")
        mask_mod.write_csv(src, self.rows())
        wrong = []
        for seed in range(80):
            vault = Vault(course="T", seed=seed)
            out, back = str(tmp_path / "o.csv"), str(tmp_path / "b.csv")
            mask_mod.mask_file(src, out, vault)
            mask_mod.unmask_file(out, back, vault)
            if not mask_mod.unmask_bytes_identical(src, back):
                wrong.append(seed)
        assert wrong == []

    def test_a_selectbox_grade_is_kept_however_rare_its_values(self, home):
        """A letter grade can occur once in a section. A selectbox can
        only hold values the LMS scheme defines, so it is a category by
        construction; on his real exports the repeat rule alone blanked
        every midterm estimate."""
        header = "Midterm Grade Estimate Grade Symbol <Selectbox MaxPoints:100>"
        rows = [r[:3] + [g] + r[4:] for r, g in zip(
            self.rows(header), [header, "A", "B+", "C-"] + [""] * 30)]
        col = [d for d in mask_mod.plan(rows).decisions
               if d.header == header][0]
        assert col.action == "keep", col.why

    def test_the_nickname_unmasks_back(self, home, tmp_path):
        src = str(tmp_path / "class.csv")
        out = str(tmp_path / "class.masked.csv")
        back = str(tmp_path / "class.back.csv")
        mask_mod.write_csv(src, self.rows())
        vault = Vault(course="TEST 101")
        mask_mod.mask_file(src, out, vault)
        mask_mod.unmask_file(out, back, vault)
        assert mask_mod.unmask_bytes_identical(src, back)


def test_keep_promotes_a_column(home, tmp_path):
    src = write(tmp_path / "class.csv", CLASSLIST.replace(
        "Section", "Advising Notes"))
    rows = mask_mod.read_rows(src)
    plan = mask_mod.plan(rows, keep=["Advising Notes"])
    notes = [d for d in plan.decisions if d.header == "Advising Notes"][0]
    assert notes.action == "keep"
    assert "--keep" in notes.why


# ------------------------------------------------------ what masking does --

def test_the_twin_has_the_same_shape_and_none_of_the_content(home, tmp_path):
    src = write(tmp_path / "class.csv", CLASSLIST)
    out = str(tmp_path / "twin.csv")
    vault = Vault(course="TEST 100")
    report = mask_mod.mask_file(src, out, vault)

    before, after = rows_of(src), rows_of(out)
    assert len(before) == len(after)
    assert before[0] == after[0]                      # headers verbatim
    assert all(len(a) == len(b) for a, b in zip(before, after))
    assert report.people_seen == 6
    assert report.people_new == 6

    # And nothing real survived. This is the post-condition, asserted
    # here as well as inside mask_file, because it is the whole point.
    assert vault.leaks(read(out)) == []


def test_a_two_word_surname_stays_two_words(home, tmp_path):
    """The known splitter bug has to survive into the twin."""
    src = write(tmp_path / "class.csv", CLASSLIST)
    out = str(tmp_path / "twin.csv")
    vault = Vault(course="TEST 100")
    mask_mod.mask_file(src, out, vault)

    person = [p for p in vault.people
              if p.real["last"] == "Vanterpool Reyes"][0]
    assert len(person.fake["last"].split()) == 2
    one_word = [p for p in vault.people if p.real["last"] == "Okonkwo"][0]
    assert len(one_word.fake["last"].split()) == 1


def test_an_id_keeps_its_length_and_punctuation(home, tmp_path):
    """Shape preserved, and no masked id is any real id.

    This asserted `not startswith("#1234567")` at first, which is not a
    property the code guarantees: a prefix every row shares is kept on
    purpose, so with five digits legitimately carried over the next two
    coincide about one time in a hundred per row. The vault seeds itself
    randomly, so the suite was quietly flaky at a few percent and two
    green runs did not show it.
    """
    src = write(tmp_path / "grades.csv", GRADES)
    out = str(tmp_path / "twin.csv")
    vault = Vault(course="TEST 100")
    mask_mod.mask_file(src, out, vault)

    real = [r[0] for r in rows_of(src)[1:]]
    ids = [r[0] for r in rows_of(out)[1:]]
    assert all(i.startswith("#") for i in ids)
    assert all(len(i) == len(r) for i, r in zip(ids, real))
    assert all(i.strip("#").isdigit() for i in ids[:5])
    assert not set(ids) & set(real), "a masked id is somebody's real id"


def test_a_do_not_use_marker_survives(home, tmp_path):
    """§14.6: printit must never write to that row, so the twin needs it."""
    src = write(tmp_path / "grades.csv", GRADES)
    out = str(tmp_path / "twin.csv")
    vault = Vault(course="TEST 100")
    mask_mod.mask_file(src, out, vault)

    marked = [r[0] for r in rows_of(out) if r[0].endswith("-DoNotUse")]
    assert len(marked) == 1
    assert not marked[0].startswith("#1234567894")


def test_the_retired_row_keeps_the_base_id_of_its_live_row(home, tmp_path):
    """The fact §14.6 actually records about `-DoNotUse`.

    It is "the same base id as a live row". If masking gave the two
    rows unrelated numbers, the twin could not be used to work out the
    rule that printit must not write to the retired one -- the thing
    that makes them a pair would be gone.
    """
    src = write(tmp_path / "grades.csv", GRADES)
    out = str(tmp_path / "twin.csv")
    vault = Vault(course="TEST 100")
    mask_mod.mask_file(src, out, vault)

    ids = [r[0] for r in rows_of(out)[1:]]
    retired = [i for i in ids if i.endswith("-DoNotUse")][0]
    base = retired[:-len("-DoNotUse")]
    assert base in ids, "the retired row no longer pairs with a live one"


def test_one_id_written_two_ways_is_one_person(home):
    """`1234567890` in a class list and `#1234567890` in a gradebook."""
    vault = Vault(course="TEST 100")
    one, created = vault.resolve({"alt_id": "1234567890"})
    assert created
    two, created = vault.resolve({"alt_id": "#1234567890"})
    assert not created
    assert one.tag == two.tag
    assert vault.mask("alt_id", "#1234567890", two) == \
        "#" + vault.mask("alt_id", "1234567890", two)


def test_a_username_column_is_masked_not_blanked(home, tmp_path):
    """An LMS class list carries OrgDefinedId *and* Username.

    The first takes the `alt_id` slot, and before `handle` existed the
    second fell through to the content rules, read as free text and was
    blanked. Safe, but it threw a real identifier away.
    """
    text = ("OrgDefinedId,Username,Last Name,First Name,Email,Role\n"
            "#2041000001,tokonkwo1,Okonkwo,Chidi,c@institute.edu,Student\n"
            "#2041000002,bfairwea2,Fairweather,Benedict,b@institute.edu,"
            "Student\n")
    src = write(tmp_path / "class.csv", text)
    out = str(tmp_path / "twin.csv")
    vault = Vault(course="TEST 100")
    report = mask_mod.mask_file(src, out, vault)

    username = [d for d in report.plan.decisions
                if d.header == "Username"][0]
    assert username.action == "mask"
    assert username.kind == "handle"

    handles = [r[1] for r in rows_of(out)[1:]]
    assert all(len(h) == 9 for h in handles)
    assert all(h == h.lower() for h in handles)
    assert "okonkwo" not in read(out).lower()


def test_a_username_is_built_from_the_fake_name(home):
    """So that the twin keeps the name-to-login relationship."""
    vault = Vault(course="TEST 100")
    person, _ = vault.resolve({"last": "Okonkwo", "first": "Chidi",
                               "handle": "cokonkwo1"})
    fake = vault.mask("handle", "cokonkwo1", person)
    stem = person.fake["first"][0].lower() + person.fake["last"].lower()
    assert fake.startswith(stem[:4])


def test_an_email_local_part_is_lower_case(home):
    """A real one is, so a twin that capitalises is wrong about shape."""
    vault = Vault(course="TEST 100")
    person, _ = vault.resolve({"last": "Okonkwo", "first": "Chidi",
                               "email": "cokonkwo@institute.edu"})
    fake = vault.mask("email", "cokonkwo@institute.edu", person)
    local = fake.partition("@")[0]
    assert local == local.lower()
    assert len(local) == len("cokonkwo")


def test_two_email_domains_stay_two_different_domains(home, tmp_path):
    """One student on two domains is a live cause of unmatched responses."""
    src = write(tmp_path / "class.csv", CLASSLIST)
    out = str(tmp_path / "twin.csv")
    vault = Vault(course="TEST 100")
    mask_mod.mask_file(src, out, vault)

    addresses = [r[5] for r in rows_of(out)[1:]]
    domains = {a.rpartition("@")[2] for a in addresses}
    assert len(domains) == 2
    assert all(d.endswith("example.org") for d in domains)
    assert "institute.edu" not in read(out)


class TestTheTwinKeepsTheSourcesFormat:
    """Line endings and a byte-order-mark are carried into the twin.

    They are the shape of the container, not student data, and the
    gradebook work is about handing an LMS back **its own file** with
    some cells filled in. A file whose endings or BOM have quietly
    changed is not that file.

    The twin used to be written as UTF-8, no BOM, LF, whatever the
    source was. Reading a real export's twin to find out how the real
    export is written therefore told me only about the masker's habits.
    """

    def _write(self, path, text, bom, ending):
        import re
        body = re.sub(r"\r?\n", ending, text)
        with open(path, "w", encoding="utf-8-sig" if bom else "utf-8",
                  newline="") as f:
            f.write(body)
        return str(path)

    @pytest.mark.parametrize("bom", [False, True])
    @pytest.mark.parametrize("ending", ["\n", "\r\n"])
    def test_it_round_trips_the_format(self, home, tmp_path, bom, ending):
        src = self._write(tmp_path / "class.csv", CLASSLIST, bom, ending)
        out = str(tmp_path / "twin.csv")
        vault = Vault(course="TEST 100")
        report = mask_mod.mask_file(src, out, vault)

        assert report.fmt.bom is bom
        assert report.fmt.newline == ending

        with open(out, "rb") as f:
            raw = f.read()
        assert (raw[:3] == b"\xef\xbb\xbf") is bom
        crlf = raw.count(b"\r\n")
        bare = raw.count(b"\n") - crlf
        if ending == "\r\n":
            assert bare == 0, "a bare LF crept into a CRLF twin"
            assert crlf == len(rows_of(out))
        else:
            assert crlf == 0, "a CR crept into an LF twin"

    def test_the_format_is_reported(self, home, tmp_path):
        src = self._write(tmp_path / "class.csv", CLASSLIST, True, "\r\n")
        vault = Vault(course="TEST 100")
        report = mask_mod.mask_file(src, str(tmp_path / "twin.csv"), vault)
        said = report.describe()
        assert "with BOM" in said
        assert "CRLF" in said


def test_a_spreadsheet_has_no_physical_format_to_copy(home, tmp_path):
    """And says so by coming back as the defaults, not by guessing."""
    fmt = mask_mod.sniff(str(tmp_path / "book.xlsx"))
    assert fmt.bom is False
    assert fmt.newline == "\n"


def test_the_grade_cells_come_through_untouched(home, tmp_path):
    src = write(tmp_path / "grades.csv", GRADES)
    out = str(tmp_path / "twin.csv")
    vault = Vault(course="TEST 100")
    mask_mod.mask_file(src, out, vault)

    before, after = rows_of(src), rows_of(out)
    for b, a in zip(before[1:], after[1:]):
        assert b[1:] == a[1:]


# ------------------------------------------------------------- stability --

def test_one_student_gets_one_pseudonym_across_two_files(home, tmp_path):
    """The whole reason the vault maps people and not strings.

    The class list knows a Global ID and a name; the grades export knows
    only the id. Masked under one vault, the same student must come out
    as the same person in both -- otherwise no cross-file join can be
    reproduced in the twins.
    """
    vault = Vault(course="TEST 100")
    first = write(tmp_path / "class.csv", CLASSLIST)
    second = write(tmp_path / "grades.csv", GRADES)
    mask_mod.mask_file(first, str(tmp_path / "a.csv"), vault)
    report = mask_mod.mask_file(second, str(tmp_path / "b.csv"), vault)

    assert report.people_new == 0, "the grades export invented new students"
    assert len(vault.people) == 6

    person = [p for p in vault.people if p.real["sid"] == "806000111"][0]
    assert person.real["alt_id"] == "1234567890"
    masked_ids = [r[0] for r in rows_of(str(tmp_path / "b.csv"))[1:]]
    assert "#" + person.fake["alt_id"] in masked_ids


def test_masking_the_same_file_twice_gives_the_same_twin(home, tmp_path):
    vault = Vault(course="TEST 100")
    src = write(tmp_path / "class.csv", CLASSLIST)
    mask_mod.mask_file(src, str(tmp_path / "a.csv"), vault)
    mask_mod.mask_file(src, str(tmp_path / "b.csv"), vault)
    assert read(str(tmp_path / "a.csv")) == read(str(tmp_path / "b.csv"))


def test_a_name_in_either_spelling_finds_the_same_person(home):
    """`Last, First M.` and `First Last` are one student."""
    vault = Vault(course="TEST 100")
    one, created = vault.resolve({"full": "Okonkwo, Chidi"})
    assert created
    two, created = vault.resolve({"full": "Chidi Okonkwo"})
    assert not created
    assert one.tag == two.tag


def test_a_whole_name_keeps_the_shape_the_cell_wrote_it_in(home):
    vault = Vault(course="TEST 100")
    person, _ = vault.resolve({"full": "Vanterpool Reyes, Marguerite Q"})
    filed = vault.mask("full", "Vanterpool Reyes, Marguerite Q", person)
    natural = vault.mask("full", "Marguerite Vanterpool Reyes", person)
    assert "," in filed
    assert "," not in natural
    assert filed.split(",")[0] == person.fake["last"]
    assert natural.endswith(person.fake["last"])


# -------------------------------------------------------- the refusals --

def test_a_row_matching_two_people_is_refused(home):
    """Two files disagreeing about who somebody is must not be absorbed."""
    vault = Vault(course="TEST 100")
    vault.resolve({"sid": "806000111", "email": "a@institute.edu"})
    vault.resolve({"sid": "806000222", "email": "b@institute.edu"})
    with pytest.raises(VaultError, match="2 people"):
        vault.resolve({"sid": "806000111", "email": "b@institute.edu"})


def test_a_vault_from_a_later_version_is_refused(home, tmp_path):
    path = str(tmp_path / "v.json")
    with open(path, "w", encoding="utf-8") as f:
        f.write('{"version": 99, "people": []}')
    with pytest.raises(VaultError, match="version 99"):
        Vault.load(path)


def test_a_vault_for_another_course_is_refused(home, tmp_path):
    path = str(tmp_path / "v.json")
    Vault(course="MAT 106").save(path)
    with pytest.raises(VaultError, match="MAT 106"):
        Vault.open_or_create(path, "MAT 206")


# -------------------------------------------- the check on the output --

def test_a_leak_deletes_the_output_and_fails(home, tmp_path):
    """The post-condition, against the realistic way the rules miss.

    A column headed `Advisor` holding surnames, few enough and short
    enough to read as a category by rule 5. Classification keeps it,
    which is wrong -- and the scan of the written file is what catches
    that, not the classifier.
    """
    text = ("Student ID,Email,Advisor\n"
            "806000111,mvanter3@institute.edu,Okonkwo\n"
            "806000222,cokonkwo@institute.edu,Okonkwo\n"
            "806000333,bfairwea@institute.edu,Fairweather\n"
            "806000444,hnakashi@institute.edu,Fairweather\n")
    src = write(tmp_path / "class.csv", text)
    out = str(tmp_path / "twin.csv")
    vault = Vault(course="TEST 100")
    vault.resolve({"last": "Okonkwo", "first": "Chidi"})
    vault.resolve({"last": "Fairweather", "first": "Benedict"})

    with pytest.raises(MaskError, match="survived"):
        mask_mod.mask_file(src, out, vault)
    assert not os.path.exists(out), "the leaking twin was left on disk"


def test_the_failure_never_prints_the_values_that_leaked(home, tmp_path):
    # Each surname twice: since RV-3 a value occurring once is blanked by
    # the classifier, and this test needs it to miss so the scan fires.
    text = ("Student ID,Email,Advisor\n"
            "806000111,a@institute.edu,Okonkwo\n"
            "806000222,b@institute.edu,Okonkwo\n"
            "806000333,c@institute.edu,Fairweather\n"
            "806000444,d@institute.edu,Fairweather\n")
    src = write(tmp_path / "class.csv", text)
    vault = Vault(course="TEST 100")
    vault.resolve({"last": "Okonkwo", "first": "Chidi"})
    vault.resolve({"last": "Fairweather", "first": "Benedict"})

    with pytest.raises(MaskError) as caught:
        mask_mod.mask_file(src, str(tmp_path / "twin.csv"), vault)
    message = str(caught.value)
    assert "Okonkwo" not in message
    assert "Fairweather" not in message
    assert "column" in message


def test_a_header_naming_a_student_is_reported(home, tmp_path):
    src = write(tmp_path / "class.csv",
                CLASSLIST.replace("Section", "Okonkwo Project Grade"))
    vault = Vault(course="TEST 100")
    vault.resolve({"last": "Okonkwo", "first": "Chidi"})
    rows = mask_mod.read_rows(src)
    plan = mask_mod.plan(rows, vault=vault)
    assert any("header contains" in w for w in plan.warnings)


# ------------------------------------------------------------ unmasking --

def test_the_twin_unmasks_back_to_the_original(home, tmp_path):
    """Everything reverses except the middle initial, which cannot.

    One letter has no safe reversal -- see `vault._initial_like`. So the
    MI column (index 4) is asserted separately, as a placeholder, rather
    than the whole file being asserted equal and the gap going unsaid.
    """
    src = write(tmp_path / "class.csv", CLASSLIST)
    out = str(tmp_path / "twin.csv")
    back = str(tmp_path / "back.csv")
    vault = Vault(course="TEST 100")
    mask_mod.mask_file(src, out, vault)
    hits = mask_mod.unmask_file(out, back, vault)

    assert hits > 0
    MI = 4
    before, after = rows_of(src), rows_of(back)
    for b, a in zip(before, after):
        assert b[:MI] == a[:MI]
        assert b[MI + 1:] == a[MI + 1:]

    initials = [r[MI] for r in after[1:] if r[MI]]
    assert initials, "every middle initial vanished, not just its letter"
    from checkit_printit.vault import INITIAL
    assert set(initials) == {INITIAL}


def test_a_one_letter_value_never_substitutes_in_prose(home):
    """The reason the placeholder exists, asserted rather than assumed."""
    vault = Vault(course="TEST 100")
    person, _ = vault.resolve({"last": "Okonkwo", "first": "Chidi",
                               "middle": "T"})
    assert vault.mask("middle", "T", person) == "X"
    out, hits = vault.unmask_text("the X axis and the Y axis")
    assert hits == 0
    assert out == "the X axis and the Y axis"


def test_unmasking_prose_works_not_only_tables(home):
    """What comes back is usually an answer, not a file."""
    vault = Vault(course="TEST 100")
    person, _ = vault.resolve({"last": "Okonkwo", "first": "Chidi",
                               "email": "cokonkwo@institute.edu"})
    fake_mail = vault.mask("email", "cokonkwo@institute.edu", person)
    text = (f"The join fails for {person.fake['first']} "
            f"{person.fake['last']} because {fake_mail} is not the "
            "address the form saw.")
    out, hits = vault.unmask_text(text)
    assert hits >= 3
    assert "Chidi Okonkwo" in out
    assert "cokonkwo@institute.edu" in out
    assert "example.org" not in out


def test_a_tag_unmasks_to_a_name(home):
    vault = Vault(course="TEST 100")
    person, _ = vault.resolve({"last": "Okonkwo", "first": "Chidi"})
    out, hits = vault.unmask_text(f"{person.tag} has no LMS id.")
    assert hits == 1
    assert out.startswith("Chidi Okonkwo")


def test_unmasking_does_not_match_inside_a_longer_word(home):
    vault = Vault(course="TEST 100")
    person, _ = vault.resolve({"last": "Okonkwo", "first": "Chidi"})
    fake = person.fake["last"]
    out, hits = vault.unmask_text(f"the word {fake}ness is not a name")
    assert hits == 0
    assert f"{fake}ness" in out


class TestOnePassSubstitution:
    """A pseudonym must never be masked a second time.

    Found against invented data at 45 students: one student's fake
    given name was `Rosalind` and another student's *real* given name
    was `Rosalind`. Masking ran one substitution per pair, so the pass
    for the second student rewrote the first student's already-masked
    name into the second student's pseudonym. Two people became one in
    the twin, and unmasking returned the wrong student's name without
    any sign that anything was wrong.
    """

    def _collided(self):
        """A vault where one person's fake name is another's real one.

        A fixed seed. With a random one, about one run in fifty gave b
        the fake first name "Rosalind" as well, the premise collapsed,
        and the test failed for no reason (found 2026-11-17)."""
        vault = Vault(course="TEST 100", seed=0)
        a, _ = vault.resolve({"first": "Thaddeus", "last": "Thorneycroft"})
        b, _ = vault.resolve({"first": "Rosalind", "last": "Netherfield"})
        assert b.fake["first"] != "Rosalind", "the premise needs another seed"
        # Force the collision rather than wait for the name pool to
        # produce it: the bug is about what happens when it does.
        a.fake["first"] = "Rosalind"
        a.strings["Thaddeus"] = "Rosalind"
        a.strings["Thaddeus Thorneycroft"] = "Rosalind " + a.fake["last"]
        return vault, a, b

    def test_a_pseudonym_is_not_masked_again(self, home):
        vault, a, b = self._collided()
        out, _ = vault.mask_text("seating Thaddeus Thorneycroft today")
        assert "Rosalind" in out
        assert b.fake["first"] not in out, \
            "one student's pseudonym was rewritten into another's"

    def test_it_unmasks_to_the_right_student(self, home):
        vault, a, b = self._collided()
        masked, _ = vault.mask_text("seating Thaddeus Thorneycroft today")
        back, _ = vault.unmask_text(masked)
        assert "Thaddeus" in back
        assert "Rosalind" not in back

    def test_the_longest_real_value_wins_at_each_position(self, home):
        vault = Vault(course="TEST 100")
        person, _ = vault.resolve({"first": "Marguerite",
                                   "last": "Vanterpool Reyes"})
        vault.mask("full", "Marguerite Vanterpool Reyes", person)
        vault.mask("last", "Vanterpool Reyes", person)
        out, hits = vault.mask_text("desk: Marguerite Vanterpool Reyes")
        assert hits == 1, "it matched the parts instead of the whole name"
        assert person.fake["last"] in out


def test_a_pseudonym_is_never_another_students_real_name(home):
    """`avoid` keeps the collision from arising at all.

    Written first as "forbid six of the sixty names, then draw six" --
    which passes about half the time with `avoid` disabled, because six
    random draws from fifty-four remaining names usually miss the
    forbidden six. The breakage harness caught that; the suite had gone
    green on it once already.

    Both assertions here are deterministic instead: forbidding the
    whole pool leaves `_pick` no choice but its numbered fallback, and
    forbidding all but six makes a wrong draw a one-in-ten-million
    coincidence rather than a coin toss.
    """
    from checkit_printit.vault import FIRST_NAMES

    vault = Vault(course="TEST 100")
    vault.avoid(FIRST_NAMES)
    person, _ = vault.resolve({"first": "Real", "last": "Surname"})
    assert person.fake["first"] not in FIRST_NAMES

    vault = Vault(course="TEST 100")
    free = set(FIRST_NAMES[:6])
    vault.avoid([n for n in FIRST_NAMES if n not in free])
    for n in range(6):
        vault.resolve({"first": f"Real{n}", "last": f"Surname{n}"})
    picked = {p.fake["first"] for p in vault.people}
    assert picked <= free, f"picked a forbidden name: {picked - free}"


def test_the_scan_does_not_cry_wolf_over_a_pseudonym(home):
    """A value that is also a pseudonym cannot be evidence of a leak."""
    vault = Vault(course="TEST 100")
    a, _ = vault.resolve({"first": "Thaddeus", "last": "Thorneycroft"})
    b, _ = vault.resolve({"first": "Rosalind", "last": "Netherfield"})
    a.fake["first"] = "Rosalind"
    assert "Rosalind" not in vault.real_values()
    # The longer values are still looked for.
    assert "Thorneycroft" in vault.real_values()
    assert "Netherfield" in vault.real_values()


class TestTheScanReadsWordsNotLetters:
    """Found masking his real course folder, 2026-11-17: `vault
    mask-course` refused every attempt, and every value it complained of
    was a false alarm. The masker replaces whole words; the scan matched
    letters, so it refused two things the masker can never write:

    * a real surname in the middle of an ordinary word the original
      file already held -- the course's own wording, not a student
    * a real first name at the start of a pseudonym the vault invented

    The exemptions are narrow on purpose. A real name at either *end*
    of a word still counts, because that is how a username leaks.
    """

    def vault(self):
        v = Vault(course="TEST 100", seed=3)
        v.resolve({"first": "Kat", "last": "Ness"})
        return v

    def test_inside_an_ordinary_word_of_the_original_is_not_a_leak(self, home):
        text = "Businesses due Friday."
        assert self.vault().leaks(text, original=text) == []

    def test_without_the_original_it_still_counts(self, home):
        """`vault check` has no original to compare with, so it stays
        as strict as it was."""
        assert self.vault().leaks("Businesses due Friday.") == ["Ness"]

    def test_at_the_end_of_a_word_it_still_counts(self, home):
        """`jness` is a username, whatever the original held."""
        text = "login: jness"
        assert self.vault().leaks(text, original=text) == ["Ness"]

    def test_at_the_start_of_a_word_it_still_counts(self, home):
        text = "login: ness42"
        assert self.vault().leaks(text, original=text) == ["Ness"]

    def test_a_word_the_original_did_not_have_still_counts(self, home):
        assert self.vault().leaks("Unessential", original="nothing") \
            == ["Ness"]

    def test_inside_a_pseudonym_is_not_a_leak(self, home):
        vault = self.vault()
        person = vault.people[0]
        person.fake["first"] = "Katherine"
        assert vault.leaks("Katherine Byron") == []

    def test_a_whole_word_always_counts(self, home):
        text = "Kat sat here"
        assert self.vault().leaks(text, original=text) == ["Kat"]

    def test_no_pseudonym_is_picked_that_contains_a_real_name(self, home):
        """The cause of the second class, fixed where it starts."""
        from checkit_printit.vault import FIRST_NAMES
        vault = Vault(course="TEST 100", seed=1)
        vault.avoid(["Kat", "Ada", "Mar", "Ann", "Eli", "Car", "Jul"])
        for n in range(40):
            vault.resolve({"first": f"Q{n}", "last": f"Zz{n}"})
        for person in vault.people:
            low = person.fake["first"].lower()
            assert not any(name in low for name in
                           ("kat", "ada", "mar", "ann", "eli", "car", "jul")), \
                person.fake["first"]


def test_a_vault_round_trips_through_disk(home, tmp_path):
    path = str(tmp_path / "v.json")
    vault = Vault(course="TEST 100")
    person, _ = vault.resolve({"sid": "806000111", "last": "Okonkwo",
                               "first": "Chidi",
                               "email": "cokonkwo@institute.edu"})
    masked = vault.mask("sid", "806000111", person)
    vault.save(path)

    again = Vault.load(path)
    assert again.course == "TEST 100"
    assert len(again.people) == 1
    out, hits = again.unmask_text(masked)
    assert hits == 1
    assert out == "806000111"


# -------------------------------------------------------- shared prefix --

def test_a_prefix_every_row_shares_is_kept(home):
    values = ["806000111", "806000222", "806000333", "806000444",
              "806000555", "806000666"]
    assert mask_mod.common_prefix(values) == 4


def test_a_prefix_is_not_trusted_from_too_few_rows(home):
    assert mask_mod.common_prefix(["806000111", "806000222"]) == 0
