"""Emailing students their papers (DESIGN 21).

No test here sends mail: `form.call` is replaced by a recorder, and the
quota and version it answers are the test's. The students are invented.
"""

import base64
import io
import os
import sqlite3

import pytest

from checkit_printit import fileio, form, gradebook, mailing, pageindex
from checkit_printit import record
from checkit_printit.roster import Student

RUN = "Quiz 3 2026-11-14"


def _pdf(path, widths):
    """A PDF whose page n is `widths[n-1]` points wide: a page's identity."""
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument.new()
    for w in widths:
        doc.new_page(w, 792)
    doc.save(str(path))
    doc.close()


def _widths(data):
    import pypdfium2 as pdfium
    doc = pdfium.PdfDocument(io.BytesIO(data))
    try:
        return [round(doc[i].get_size()[0]) for i in range(len(doc))]
    finally:
        doc.close()


@pytest.fixture
def course(tmp_path):
    """A graded run: three students, two skills, one scanned stack.

    Quill sat both skills (AD passed over two pages, SU queried);
    Rune failed AD and was absent for SU; Sable was absent for both.
    """
    path = str(tmp_path / "record.db")
    handouts = [
        {"sid": "901", "name": "Quill Abacus", "papers": [("AD", 1), ("SU", 2)]},
        {"sid": "902", "name": "Rune Bellows", "papers": [("AD", 3), ("SU", 4)]},
        {"sid": "903", "name": "Sable Cogwheel", "papers": [("AD", 5)]},
    ]
    record.write_run(path, run_id=RUN, title="Quiz 3", date="2026-11-14",
                     built="2026-11-14T08:00:00", seed=1, output="",
                     handouts=handouts, run_no=7)
    record.save_attempts(path, [
        {"run_id": RUN, "sid": "901", "slug": "AD", "outcome": "passed", "page": 1},
        {"run_id": RUN, "sid": "901", "slug": "SU", "outcome": "queried", "page": 3},
        {"run_id": RUN, "sid": "902", "slug": "AD", "outcome": "failed", "page": 4},
        {"run_id": RUN, "sid": "902", "slug": "SU", "outcome": "absent", "page": None},
        {"run_id": RUN, "sid": "903", "slug": "AD", "outcome": "absent", "page": None},
    ])
    scans = tmp_path / "scans"
    scans.mkdir()
    # Shuffled, as a copier returns them: scan page -> what it is.
    #   1: Quill AD sheet 2 (run page 2)   width 102
    #   2: Rune AD (run page 4)            width 104
    #   3: Quill SU (run page 3)           width 103
    #   4: Quill AD sheet 1 (run page 1)   width 101
    _pdf(scans / "stack.pdf", [102, 104, 103, 101])
    record.add_scan(path, "stack.pdf", "sha1", "copier.pdf", 4, 100)
    record.note_scan_pages(path, "stack.pdf", [
        (1, RUN, "901", "AD", 2),
        (2, RUN, "902", "AD", 4),
        (3, RUN, "901", "SU", 3),
        (4, RUN, "901", "AD", 1),
    ])
    roster = [
        Student(name="Abacus, Quill", skills=[], sid="901", email="q@example.org"),
        Student(name="Rune Bellows", skills=[], sid="902", email="r@example.org"),
        Student(name="Sable Cogwheel", skills=[], sid="903", email="s@example.org"),
    ]
    index = pageindex.Index(run_id=7, pages={
        1: pageindex.Page(1, "student", "901", "AD", "1", 1),
        2: pageindex.Page(2, "student", "901", "AD", "1", 2),
        3: pageindex.Page(3, "student", "901", "SU", "2", 1),
        4: pageindex.Page(4, "student", "902", "AD", "3", 1),
    })
    return {"path": path, "scans": str(scans), "roster": roster,
            "index": index, "tmp": tmp_path,
            "titles": {"AD": "Adding", "SU": "Subtracting"}}


def _plan(c, **kw):
    kw.setdefault("words", mailing.DEFAULT_WORDS)
    kw.setdefault("order", ["AD", "SU"])
    kw.setdefault("index", c["index"])
    return {l.sid: l for l in mailing.plan(
        c["path"], RUN, c["roster"], c["titles"], **kw)}


# ----------------------------------------------------------- template --

class TestTheTemplate:
    def test_no_file_is_the_default_and_says_so(self, tmp_path):
        t = mailing.load_template(str(tmp_path))
        assert (t.subject, t.body, t.saved) == (
            mailing.DEFAULT_SUBJECT, mailing.DEFAULT_BODY, False)

    def test_the_default_uses_only_real_fields(self):
        mailing.check(mailing.DEFAULT_SUBJECT)
        mailing.check(mailing.DEFAULT_BODY)

    def test_a_save_reads_back_exactly(self, tmp_path):
        body = 'Line one\n"quoted" and \\ a backslash\n"""three"""\n\ttab\n'
        mailing.save_template("Hi {{first}}", body, str(tmp_path))
        t = mailing.load_template(str(tmp_path))
        assert (t.subject, t.body, t.saved) == ("Hi {{first}}", body, True)

    def test_a_save_keeps_his_comments(self, tmp_path):
        mailing.save_template("A", "B\n", str(tmp_path))
        path = mailing.template_path(str(tmp_path))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        with open(path, "w", encoding="utf-8") as f:
            f.write(text.replace("subject =", "# mine, keep it\nsubject =", 1)
                    + "\n# and this one\n")
        mailing.save_template("C {{name}}", "D\nE\n", str(tmp_path))
        with open(path, encoding="utf-8") as f:
            text = f.read()
        assert "# mine, keep it" in text and "# and this one" in text
        t = mailing.load_template(str(tmp_path))
        assert (t.subject, t.body) == ("C {{name}}", "D\nE\n")

    def test_the_body_is_readable_in_the_file(self, tmp_path):
        mailing.save_template("S", "first line\nsecond line\n", str(tmp_path))
        with open(mailing.template_path(str(tmp_path)), encoding="utf-8") as f:
            text = f.read()
        assert "first line\nsecond line\n" in text

    @pytest.mark.parametrize("bad, said", [
        ("Hi {{frist}}", "{{frist}}"),
        ("{{#results}}x{{/results}}", "fields only"),
        ("{{> partial}}", "fields only"),
        ("Hi {{first}", "not part of a field"),
        ("Hi {{{first}}", "mismatched"),
    ])
    def test_anything_but_a_known_field_refuses(self, bad, said):
        with pytest.raises(mailing.MailError, match=None) as caught:
            mailing.check(bad)
        assert said in str(caught.value)

    def test_a_refused_template_is_not_written(self, tmp_path):
        with pytest.raises(mailing.MailError):
            mailing.save_template("Hi {{frist}}", "x", str(tmp_path))
        assert not os.path.exists(mailing.template_path(str(tmp_path)))

    def test_nothing_is_html_escaped(self):
        assert mailing.render("{{name}}", {"name": "A & <B>"}) == "A & <B>"
        assert mailing.render("{{{ name }}}", {"name": "x"}) == "x"

    def test_a_multiline_toml_string_survives_its_own_quotes(self):
        import tomllib
        for value in ['"', '""', '"""', 'end"', 'a\\"""b', "\r\n"]:
            text = "v = " + fileio.toml_string(value, multiline=True)
            assert tomllib.loads(text)["v"] == value, value


# --------------------------------------------------------- the words --

class TestTheWords:
    def test_no_gradebook_matching_is_printits_words(self, tmp_path):
        w = mailing.words_for(str(tmp_path))
        assert (w.passed, w.failed, w.source) == ("Pass", "Not yet", "default")

    def test_his_matching_is_used_exactly(self, tmp_path):
        profile = gradebook.Profile(student_column="OrgDefinedId",
                                    passed="✅Pass",
                                    not_passed="❌Not Yet")
        gradebook.save(str(tmp_path / gradebook.FILENAME), profile)
        w = mailing.words_for(str(tmp_path))
        assert (w.passed, w.failed, w.queried, w.source) == (
            "✅Pass", "❌Not Yet", "?", "gradebook")


# ---------------------------------------------------------- the plan --

class TestThePlan:
    def test_only_students_who_sat_are_listed(self, course):
        assert set(_plan(course)) == {"901", "902"}       # 903 was absent

    def test_an_absent_skill_is_left_out(self, course):
        assert [s.slug for s in _plan(course)["902"].skills] == ["AD"]

    def test_leaving_queries_out_drops_the_skill_and_its_pages(self, course):
        quill = _plan(course, queried="leave out")["901"]
        assert [s.slug for s in quill.skills] == ["AD"]
        assert quill.pages == [("stack.pdf", 4), ("stack.pdf", 1)]

    def test_sending_queries_reports_them_as_a_mark(self, course):
        quill = _plan(course, queried="send")["901"]
        assert [(s.slug, s.word) for s in quill.skills] == [
            ("AD", "Pass"), ("SU", "?")]
        assert ("stack.pdf", 3) in quill.pages

    def test_pages_come_in_printed_order_not_scanned(self, course):
        quill = _plan(course, queried="send")["901"]
        assert quill.pages == [("stack.pdf", 4), ("stack.pdf", 1),
                               ("stack.pdf", 3)]

    def test_a_student_with_only_queries_is_held(self, course):
        record.save_attempts(course["path"], [
            {"run_id": RUN, "sid": "901", "slug": "AD", "outcome": "queried",
             "page": 1}])
        quill = _plan(course, queried="leave out")["901"]
        assert quill.status == mailing.HELD and not quill.skills

    def test_no_address_is_not_guessed(self, course):
        course["roster"][1].email = ""
        course["roster"][1].emails = ["other@example.org"]
        rune = _plan(course)["902"]
        assert (rune.status, rune.reason) == (mailing.NO_ADDRESS,
                                              "no email address")

    def test_someone_not_on_the_roster_is_said_so(self, course):
        del course["roster"][1]
        assert _plan(course)["902"].reason == "not on the roster"

    def test_a_student_told_everything_is_not_due(self, course):
        record.note_mailed(course["path"], RUN, "902", "r@example.org",
                           [("AD", "failed")])
        assert _plan(course)["902"].status == mailing.SENT

    def test_a_changed_mark_is_due_again(self, course):
        record.note_mailed(course["path"], RUN, "901", "q@example.org",
                           [("AD", "passed"), ("SU", "queried")])
        assert _plan(course, queried="send")["901"].status == mailing.SENT
        record.save_attempts(course["path"], [
            {"run_id": RUN, "sid": "901", "slug": "SU", "outcome": "passed",
             "page": 3}])
        assert _plan(course, queried="send")["901"].status == mailing.DUE

    def test_a_query_left_out_then_settled_is_due(self, course):
        record.note_mailed(course["path"], RUN, "901", "q@example.org",
                           [("AD", "passed")])
        assert _plan(course, queried="leave out")["901"].status == mailing.SENT
        record.save_attempts(course["path"], [
            {"run_id": RUN, "sid": "901", "slug": "SU", "outcome": "failed",
             "page": 3}])
        assert _plan(course, queried="leave out")["901"].status == mailing.DUE

    def test_resend_overrides_already_sent(self, course):
        record.note_mailed(course["path"], RUN, "902", "r@example.org",
                           [("AD", "failed")])
        assert _plan(course, resend=["902"])["902"].status == mailing.DUE

    def test_a_missing_second_page_is_said(self, course):
        db = sqlite3.connect(course["path"])
        db.execute("DELETE FROM scan_page WHERE scan_page = 1")
        db.commit()
        db.close()
        quill = _plan(course)["901"]
        assert quill.status == mailing.DUE
        assert quill.warning == "AD has 1 of 2 pages"

    def test_no_pages_at_all_is_said(self, course):
        db = sqlite3.connect(course["path"])
        db.execute("DELETE FROM scan_page WHERE sid = '902'")
        db.commit()
        db.close()
        assert "results only" in _plan(course)["902"].warning

    def test_an_unknown_queried_mode_refuses(self, course):
        with pytest.raises(mailing.MailError):
            _plan(course, queried="maybe")


class TestOneEmail:
    def test_the_fields_are_filled(self, course):
        quill = _plan(course, queried="send")["901"]
        t = mailing.Template("{{assessment}} for {{first}}",
                             "{{name}} {{date}}\n{{results}}\n{{instructor}}")
        subject, body = mailing.compose(
            quill, t, {"title": "Quiz 3", "date": "2026-11-14"}, "Slye")
        assert subject == "Quiz 3 for Quill"
        assert body == ("Quill Abacus Saturday, 11/14\n"
                        "AD Adding: Pass\nSU Subtracting: ?\nSlye")

    def test_the_default_greeting_is_the_name_they_go_by(self):
        assert mailing.DEFAULT_BODY.startswith("Hi {{pref_first}},")


class TestTheNameFields:
    """`name_values`, the template's four name fields (DESIGN 22)."""

    def _s(self, **kw):
        return Student(name=kw.pop("name", "Quill Abacus"), skills=[], **kw)

    def test_every_one_is_a_field_the_template_may_use(self):
        values = mailing.name_values(self._s())
        assert set(values) <= set(mailing.FIELDS)
        mailing.check("{{first}} {{last}} {{pref_first}} {{pref_last}} {{name}}")

    def test_a_whole_name_roster_splits_for_both_pairs(self):
        """Every real roster until a re-import fills the parts."""
        assert mailing.name_values(self._s()) == {
            "first": "Quill", "last": "Abacus",
            "pref_first": "Quill", "pref_last": "Abacus"}

    def test_stored_parts_are_used_as_they_are(self):
        """No split once they exist: a compound surname is kept whole."""
        values = mailing.name_values(self._s(
            name="Quill Abacus Moss", first="Quill", last="Abacus Moss"))
        assert values["last"] == "Abacus Moss"

    def test_the_preferred_first_name_wins_the_greeting(self):
        """The bug this replaced: `first_name` took the registrar's first
        name ahead of the preferred one, and greeted "Quillon" whoever
        had asked to be Quill."""
        values = mailing.name_values(self._s(
            name="Quillon Abacus", first="Quillon", last="Abacus",
            pref_first="Quill"))
        assert values["pref_first"] == "Quill"
        assert values["first"] == "Quillon"

    def test_each_preferred_part_falls_back_to_the_registrar_one(self):
        values = mailing.name_values(self._s(
            first="Quill", last="Abacus", pref_last="Moss"))
        assert (values["pref_first"], values["pref_last"]) == ("Quill", "Moss")

    def test_they_reach_the_email(self, course):
        quill = _plan(course, queried="send")["901"]
        t = mailing.Template("x", "{{pref_first}}|{{pref_last}}|"
                                  "{{first}}|{{last}}")
        _, body = mailing.compose(quill, t, {"title": "Q", "date": ""}, "")
        assert body == "Quill|Abacus|Quill|Abacus"


class TestTheAttachment:
    def test_the_attachment_is_those_pages_in_that_order(self, course):
        data = mailing.attachment(course["scans"],
                                  [("stack.pdf", 4), ("stack.pdf", 1),
                                   ("stack.pdf", 3)])
        assert _widths(data) == [101, 102, 103]

    def test_a_scan_outside_the_folder_refuses(self, course):
        with pytest.raises(mailing.MailError):
            mailing.attachment(course["scans"], [("../record.db", 1)])

    def test_the_file_is_named_for_the_assessment_not_the_student(self):
        assert mailing.attachment_name(
            {"title": "Quiz 3: part/2", "date": "2026-11-14"}) == \
            "Quiz 3 part 2 2026-11-14.pdf"


# -------------------------------------------------------------- send --

class Google:
    """Answers like the deployed script, and remembers what it was sent."""

    def __init__(self, remaining=100, version=2, fail=()):
        self.remaining, self.version, self.fail = remaining, version, fail
        self.mail = []

    def __call__(self, conn, op, payload=None, **kw):
        if op == "ping":
            return {"ok": True, "version": self.version}
        if op == "quota":
            return {"ok": True, "remaining": self.remaining}
        assert op == "mail" and kw.get("retries") == 0
        if payload["to"] in self.fail:
            error = self.fail[payload["to"]]
            raise error
        self.mail.append(payload)
        return {"ok": True}


def _send(course, google, **kw):
    letters = mailing.plan(course["path"], RUN, course["roster"],
                           course["titles"], mailing.DEFAULT_WORDS,
                           queried=kw.pop("queried", "send"),
                           order=["AD", "SU"], index=course["index"])
    return mailing.send(letters, mailing.Template("S {{first}}", "{{results}}"),
                        {"run_id": RUN, "title": "Quiz 3",
                         "date": "2026-11-14"},
                        course["path"], course["scans"], conn=None,
                        call=google, **kw)


class TestSending:
    def test_each_student_gets_their_own_email_and_pages(self, course):
        google = Google()
        report = _send(course, google)
        assert sorted(report.sent) == ["901", "902"]
        by_to = {m["to"]: m for m in google.mail}
        quill = by_to["q@example.org"]
        assert quill["subject"] == "S Quill"
        assert quill["body"] == "AD Adding: Pass\nSU Subtracting: ?"
        pdf = base64.b64decode(quill["attachments"][0]["data"])
        assert _widths(pdf) == [101, 102, 103]
        assert _widths(base64.b64decode(
            by_to["r@example.org"]["attachments"][0]["data"])) == [104]

    def test_each_email_is_recorded_and_not_sent_twice(self, course):
        _send(course, Google())
        assert record.mailed_in(course["path"], RUN) == {
            "901": {"AD": "passed", "SU": "queried"}, "902": {"AD": "failed"}}
        again = Google()
        assert _send(course, again).sent == [] and again.mail == []

    def test_too_few_left_today_sends_nothing(self, course):
        google = Google(remaining=1)
        with pytest.raises(mailing.MailError, match="Nothing was sent"):
            _send(course, google)
        assert google.mail == [] and record.mailed_in(course["path"], RUN) == {}

    def test_an_old_script_is_refused_before_anything(self, course):
        google = Google(version=1)
        with pytest.raises(mailing.MailError, match="Update it on Settings"):
            _send(course, google)
        assert google.mail == []

    def test_a_bad_address_does_not_stop_the_others(self, course):
        google = Google(fail={"q@example.org": form.FormError("Invalid email")})
        report = _send(course, google)
        assert report.sent == ["902"]
        assert report.failed == [("901", "Invalid email")]
        assert "901" not in record.mailed_in(course["path"], RUN)

    def test_a_timeout_stops_and_is_not_recorded(self, course):
        google = Google(fail={"q@example.org": form.FormTimeout("slow")})
        report = _send(course, google)
        assert report.sent == []
        assert "look in Sent" in report.failed[0][1]
        assert report.skipped == ["902"]
        assert record.mailed_in(course["path"], RUN) == {}

    def test_a_template_that_cannot_fill_sends_nothing(self, course):
        google = Google()
        letters = mailing.plan(course["path"], RUN, course["roster"],
                               course["titles"], mailing.DEFAULT_WORDS)
        with pytest.raises(mailing.MailError):
            mailing.send(letters, mailing.Template("{{nope}}", "x"),
                         {"run_id": RUN}, course["path"], course["scans"],
                         conn=None, call=google)
        assert google.mail == []


# --------------------------------------------- the record and the index --

class TestAPapersLaterPages:
    def index(self):
        P = pageindex.Page
        return pageindex.Index(run_id=1, pages={
            1: P(1, "student", "1", "AD", "", 1),
            2: P(2, "student", "1", "AD", "", 2),
            3: P(3, "student", "1", "AD", "", 3),
            4: P(4, "student", "2", "AD", "", 1),
            6: P(6, "student", "2", "SU", "", 2),     # 5 missing: a broken chain
            7: P(7, "student", "1", "SU", "", 1),
            8: P(8, "student", "9", "SU", "", 2),     # someone else's sheet 2
        })

    def test_a_sheet_two_after_another_students_paper_is_none(self):
        assert self.index().first_page_of(8) is None
        assert self.index().pages_of_paper(7) == [7]

    def test_a_later_page_finds_its_first(self):
        idx = self.index()
        assert [idx.first_page_of(p) for p in (1, 2, 3, 4)] == [1, 1, 1, 4]

    def test_a_broken_chain_is_none_not_a_guess(self):
        assert self.index().first_page_of(6) is None
        assert self.index().first_page_of(9) is None

    def test_a_paper_lists_its_pages(self):
        idx = self.index()
        assert idx.pages_of_paper(1) == [1, 2, 3]
        assert idx.pages_of_paper(4) == [4]


class TestScansSavesEveryPageOfAPaper:
    """A paper's second sheet carries no box, so no decision names it.

    Saving a stack used to store that page with nobody on it, and an
    email would then have attached only the first sheet. It now finds
    its paper through the run's own index (DESIGN 21).
    """

    @pytest.fixture
    def course(self, tmp_path, monkeypatch):
        from checkit_printit import course as course_mod
        from checkit_printit import gui as gui_mod
        monkeypatch.setenv("CHECKIT_PRINTIT_HOME", str(tmp_path))
        course_mod.init("Test", bank="", adopt=None)
        folder = tmp_path / "Quiz 2026-11-14"
        folder.mkdir()
        (folder / pageindex.FILENAME).write_text(
            "run*1\n"
            "1*student*001*W1*401*1\n"
            "2*student*001*W1*401*2\n"
            "3*student*002*W1*403*1\n", encoding="utf-8")
        path = course_mod.file_in("Test", "record")
        record.write_run(
            path, run_id="first", title="Quiz", date="2026-11-14",
            built="2026-11-14T09:00:00", seed=1, output=str(folder),
            run_no=1, handouts=[
                {"sid": "001", "name": "Quill", "papers": [("W1", 401)]},
                {"sid": "002", "name": "Rune", "papers": [("W1", 403)]}])
        record.add_scan(path, "stack.pdf", "sha", "copier.pdf", 3, 1)
        return gui_mod.Course("Test")

    @staticmethod
    def sheet(scan_page, run_page, sid, sheet):
        from checkit_printit import scans as scans_mod
        entry = pageindex.Page(page=run_page, kind="student", sid=sid,
                               slug="W1", vseed="401", sheet=sheet)
        return scans_mod.Sheet(
            source="/scans/stack.pdf", scan_page=scan_page, status="placed",
            run_no=1, run_page=run_page, entry=entry)

    def test_the_second_sheet_goes_to_whoever_the_paper_was_decided_to_be(
            self, course, monkeypatch):
        from checkit_printit import gui as gui_mod
        # Shuffled: the second sheet came out of the copier first. And
        # re-matched: he decided Quill's paper was Rune's, so the second
        # sheet follows the decision, not the name the index printed.
        monkeypatch.setattr(gui_mod.SCANNING, "sheets", [
            self.sheet(1, 2, "001", 2),
            self.sheet(2, 1, "001", 1),
        ])
        gui_mod._note_pages(course, {}, [
            {"run_id": "first", "page": 1, "sid": "002", "slug": "W1"}])
        rows = record.scan_pages_in(course.file("record"), "first")
        assert [(r["scan_page"], r["sid"], r["run_page"]) for r in rows] == [
            (2, "002", 1), (1, "002", 2)]


def test_an_old_record_gains_the_run_page_column(tmp_path):
    path = str(tmp_path / "old.db")
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE scan (scan_id TEXT PRIMARY KEY, sha TEXT NOT NULL UNIQUE,
            added TEXT NOT NULL, original TEXT NOT NULL,
            pages INTEGER NOT NULL, bytes INTEGER NOT NULL);
        CREATE TABLE scan_page (scan_id TEXT NOT NULL, scan_page INTEGER NOT NULL,
            run_id TEXT, sid TEXT, slug TEXT, PRIMARY KEY (scan_id, scan_page));
        INSERT INTO scan VALUES ('s.pdf', 'x', '2026-11-01', 'c.pdf', 1, 1);
        INSERT INTO scan_page VALUES ('s.pdf', 1, 'r', '001', 'AD');
    """)
    db.commit()
    db.close()
    assert record.scan_pages_in(path, "r") == [
        {"scan_id": "s.pdf", "scan_page": 1, "sid": "001", "slug": "AD",
         "run_page": None}]
