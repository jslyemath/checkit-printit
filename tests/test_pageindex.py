"""The table the footer code keys into.

Split between what parsing does with a malformed file and what a real
compile actually writes, because they fail differently and the second
is slow. The compiling tests are the ones that matter: the index is
produced by TeX at page-break time, and no amount of testing the
parser says whether TeX wrote the right thing.
"""

import os
import random
import shutil
import subprocess

import pytest

from checkit_printit import assemble as assemble_mod
from checkit_printit import pageindex
from checkit_printit import publication as pub_mod
from checkit_printit import roster as roster_mod
from checkit_printit import seating, theme
from checkit_printit.compile import find_pdflatex

GOOD = (
    "run*4242\n"
    "1*student*806625853*W5*803*1\n"
    "box*1*34926110*1819429*1769472*1310720*131072\n"
    "2*student*806625853*W5*803*2\n"
    "4*spare**W6*571*1\n"
    "5*key**N2*840*1\n"
)


class TestReadingTheFile:
    def test_it_reads_the_run_and_the_pages(self):
        index = pageindex.parse(GOOD)
        assert index.run_seed == 4242
        assert sorted(index.pages) == [1, 2, 4, 5]
        assert index.get(1).slug == "W5"
        assert index.get(2).sheet == 2
        assert index.get("4").kind == "spare"

    def test_a_gap_is_a_blank(self):
        """Derived from the pages, never recorded. A recorded list of
        blanks is a second copy of the same fact and can disagree."""
        assert pageindex.parse(GOOD).blanks() == [3]

    def test_a_trailing_blank_needs_the_page_count(self):
        """The index cannot see past its own last line, and a run
        almost always ends on a padding sheet -- the last thing in the
        document is a \\preparefornextstudent. Given the PDF's page
        count it reports that one too."""
        index = pageindex.parse(GOOD)
        assert index.blanks() == [3]
        assert index.blanks(total=7) == [3, 6, 7]

    def test_no_pages_means_no_blanks_rather_than_an_error(self):
        assert pageindex.parse("run*1\n").blanks() == []

    def test_a_key_is_not_gradable(self):
        index = pageindex.parse(GOOD)
        assert index.get(1).gradable
        assert not index.get(5).gradable

    def test_a_spare_is_owned_by_nobody(self):
        index = pageindex.parse(GOOD)
        assert index.get(1).owned
        assert not index.get(4).owned

    def test_without_a_run_header_it_refuses(self):
        """The header is what ties these pages to the seed in the code.
        Without it the file is a list of page numbers belonging to no
        run, and matching it to a scan would be a guess."""
        with pytest.raises(pageindex.PageIndexError, match="run header"):
            pageindex.parse("1*student*1*W5*803*1\n")

    def test_a_short_line_names_itself(self):
        with pytest.raises(pageindex.PageIndexError, match="line 2 has 5"):
            pageindex.parse("run*1\n1*student*1*W5*803\n")

    def test_an_unknown_kind_is_refused_not_assumed(self):
        """A kind this reader does not know means a theme newer than
        it. Falling back to "student" would record attempts against
        papers nobody sat."""
        with pytest.raises(pageindex.PageIndexError, match="'sample'"):
            pageindex.parse("run*1\n1*sample*1*W5*803*1\n")

    def test_a_box_is_attached_to_its_page(self):
        index = pageindex.parse(GOOD)
        assert index.get(1).box.x == 34926110
        assert index.get(1).box.width == 1769472

    def test_a_continuation_sheet_has_no_box(self):
        """Sheet 2 of a skill deliberately omits it -- one skill is
        ticked once -- so None here means "nothing to grade on this
        page", not "the record is incomplete"."""
        assert pageindex.parse(GOOD).get(2).box is None

    def test_a_box_on_a_page_that_has_no_entry_is_refused(self):
        """The two lines are written by different mechanisms, one
        immediate and one deferred. If they ever disagree about what a
        page is, cropping the box would read a mark belonging to
        nobody."""
        with pytest.raises(pageindex.PageIndexError, match=r"\[9\]"):
            pageindex.parse(GOOD + "box*9*1*2*3*4*5\n")

    def test_two_boxes_on_one_page_are_refused(self):
        with pytest.raises(pageindex.PageIndexError, match="second grading"):
            pageindex.parse(GOOD + "box*1*1*2*3*4*5\n")

    def test_a_malformed_box_line_is_refused(self):
        with pytest.raises(pageindex.PageIndexError, match="line 2"):
            pageindex.parse("run*1\nbox*1*nope*2*3*4*5\n")

    def test_the_rectangle_counts_down_from_the_top(self):
        """`\\pdfsavepos` measures up from the bottom of the page and
        an image counts down from the top, so the conversion has to
        flip -- and the page height it flips about is in PostScript
        points while the position is in TeX points. Getting that wrong
        is a 0.4% error, which at the bottom of a page is a pixel and
        a half."""
        box = pageindex.parse(GOOD).get(1).box
        left, top, right, bottom = box.rect(dpi=200, page_height_pt=792)
        assert bottom > top, "the rectangle is upside down"
        assert right > left
        # 1769472sp is 27pt, which at 200dpi over 72.27pt to the inch
        # is 74.7px. Height plus depth is 1441792sp, or 22pt, 60.9px.
        assert round(right - left) == 75
        assert round(bottom - top) == 61
        # The page is 792pt, so 2200px tall at this dpi, and the box
        # sits in the footer: its foot is 25.76pt up, which is 71px.
        assert round(2200 - bottom) == 71

    def test_a_page_listed_twice_is_refused(self):
        """Storing into a dict would hide this: the second line would
        overwrite the first and the file would read as correct."""
        with pytest.raises(pageindex.PageIndexError, match="second entry"):
            pageindex.parse(GOOD + "1*student*999*W5*803*1\n")

    def test_a_missing_file_says_how_to_get_one(self, tmp_path):
        with pytest.raises(pageindex.PageIndexError, match="install --force"):
            pageindex.load(str(tmp_path))


class TestThePayload:
    def test_it_reads_a_code(self):
        assert pageindex.read_payload("C1-4242-17") == (4242, 17)

    def test_a_foreign_code_is_not_an_error(self):
        """A scanned page may carry a library barcode or a watermark.
        Meeting one is ordinary, so it returns None rather than
        raising -- the caller is looping over a stack."""
        assert pageindex.read_payload("9781234567897") is None
        assert pageindex.read_payload("https://example.edu") is None

    def test_a_later_format_is_not_read_as_this_one(self):
        """What the `C1` tag is for. A code with different fields has
        to be distinguishable from this one, not silently misread."""
        assert pageindex.read_payload("C2-4242-17-W5") is None


class TestWhatTheDocumentDeclares:
    """`\\setkind` in main.tex, without paying for a compile.

    Spares are here and not in the compiled fixture because building
    one needs a roster with somebody unseated, and what is in question
    is only which word the document writes.
    """

    def main_tex(self, extras=(), keys=None):
        publication = pub_mod.Publication(
            course="TEST 101", semester="Fall", professor="Nobody",
            title="Checkpoint", date="2026-01-01", bank_path="")

        class Handout:
            blank_name = False
            name = "Ada"
            section = "1"
            sid = "111"
            versions = [("AD", 607)]

        return assemble_mod.main_tex(publication, [Handout()], list(extras),
                                     keys)

    def test_a_handout_is_a_student(self):
        assert r"\setkind{student}" in self.main_tex()

    def test_an_extra_is_a_spare(self):
        """A spare is printed for whoever turns up without one, so it
        is owned by nobody until somebody writes an id on it. Recorded
        as a student it would become an attempt by the person whose
        name happened to be on the handout it was copied from."""
        class Spare:
            blank_name = True
            name = ""
            section = ""
            sid = ""
            versions = [("AD", 607)]

        tex = self.main_tex(extras=[Spare()])
        assert r"\setkind{spare}" in tex

    def test_a_key_is_a_key(self):
        tex = self.main_tex(keys={"copies": 1, "versions": [("AD", 607)]})
        assert r"\setkind{key}" in tex

    def test_an_older_theme_still_compiles(self):
        """The bank's printit.sty is only replaced by `install
        --force`, which is the instructor's call, so the next build may
        well run one that has never heard of \\setkind. A bare call
        would be an undefined control sequence in the middle of a print
        job."""
        assert r"\providecommand{\setkind}[1]{}" in self.main_tex()


# --------------------------------------------------------- what TeX writes --

pdflatex = find_pdflatex()


def one_page_and_two_page_students():
    """Ada takes one skill and so ends on an odd page, which forces a
    padding sheet. That is the case the index has to step over."""
    return roster_mod.Roster([
        roster_mod.Student(name="Ada", section="1", skills=["AD"], sid="111"),
        roster_mod.Student(name="Bo", section="1", skills=["AD", "SU"],
                           sid="222"),
    ])


def build_and_compile(bank_dir, tmp_path, **options):
    chart = tmp_path / "seating.toml"
    chart.write_text('[[group]]\nseats = ["Ada", "Bo"]\n', encoding="utf-8")
    publication = pub_mod.Publication(
        course="TEST 101", semester="Fall", professor="Nobody",
        title="Checkpoint", date="2026-01-01", bank_path=bank_dir,
        keys=True, key_copies=1, **options)
    out = str(tmp_path / "out")
    source, _ = theme.load(bank_dir)
    assemble_mod.assemble(publication, one_page_and_two_page_students(),
                          seating.load(str(chart)), out, source,
                          rng=random.Random(1), run_seed=4242)
    for _ in range(2):
        subprocess.run([pdflatex, "-interaction=nonstopmode",
                        "-halt-on-error", "main.tex"],
                       cwd=out, capture_output=True, timeout=300)
    assert os.path.isfile(os.path.join(out, "main.pdf"))
    return out


@pytest.fixture(scope="class")
def compiled(bank_dir, tmp_path_factory):
    """One build, compiled once, shared by the tests below.

    `scope="class"` because pdflatex is seconds and these all ask
    questions about the same document.
    """
    return build_and_compile(bank_dir, tmp_path_factory.mktemp("pages"))


@pytest.fixture(scope="class")
def compiled_without_codes(bank_dir, tmp_path_factory):
    return build_and_compile(bank_dir, tmp_path_factory.mktemp("nocodes"),
                             codes=False)


@pytest.mark.skipif(not pdflatex, reason="no pdflatex")
class TestWhatACompileWrites:
    def test_the_index_is_written_beside_the_pdf(self, compiled):
        assert os.path.isfile(os.path.join(compiled, pageindex.FILENAME))

    def test_the_run_seed_is_the_one_the_build_was_given(self, compiled):
        assert pageindex.load(compiled).run_seed == 4242

    def test_every_student_page_names_its_owner(self, compiled):
        index = pageindex.load(compiled)
        owners = {p.sid for p in index.pages.values() if p.kind == "student"}
        assert owners == {"111", "222"}

    def test_the_index_covers_every_page_of_the_pdf(self, compiled):
        """Between the lines and the gaps, nothing is unaccounted for.
        A page neither indexed nor blank is a page a scan could not
        place at all."""
        pdfium = pytest.importorskip("pypdfium2")
        pdf = pdfium.PdfDocument(os.path.join(compiled, "main.pdf"))
        index = pageindex.load(compiled)
        assert set(index.pages) | set(index.blanks(total=len(pdf))) == \
            set(range(1, len(pdf) + 1))

    def test_the_key_pages_are_marked_as_keys(self, compiled):
        index = pageindex.load(compiled)
        keys = [p for p in index.pages.values() if p.kind == "key"]
        assert keys, "the build asked for a key and the index has none"
        assert all(not p.sid for p in keys)
        assert all(not p.gradable for p in keys)

    def test_a_padding_page_is_a_gap_and_not_a_line(self, compiled):
        """The whole reason the index is written from the footer.
        \\preparefornextstudent pads under \\pagestyle{empty}, which has
        no footer, so a blank writes nothing. If it ever did, every
        page after it would be attributed to the wrong student.

        Ada takes one skill, so her paper ends on an odd page and the
        run is guaranteed to contain one."""
        index = pageindex.load(compiled)
        assert index.blanks(), "no padding page, so this proves nothing"

    def test_the_gaps_really_are_empty_pages(self, compiled):
        """Checked against the PDF rather than trusted: a gap proves
        the index skipped a number, not that the page is blank."""
        pdfium = pytest.importorskip("pypdfium2")
        pdf = pdfium.PdfDocument(os.path.join(compiled, "main.pdf"))
        index = pageindex.load(compiled)
        for n in index.blanks(total=len(pdf)):
            text = pdf[n - 1].get_textpage().get_text_range().strip()
            assert not text, f"page {n} is a gap but has {text[:40]!r} on it"

    def test_turning_the_codes_off_does_not_empty_the_index(
            self, compiled, compiled_without_codes):
        """Two unrelated decisions. Keeping `\\cipwriteindex` inside
        `\\ifcipcodeon` would mean a run printed without a symbol also
        recorded nothing about its pages -- and an empty index does
        not read as "no codes", it reads as a run with no pages.

        Written because a mutation that tied them together passed
        every other test here."""
        full = pageindex.load(compiled)
        bare = pageindex.load(compiled_without_codes)
        assert bare.pages, "codes off, and the index came out empty"
        assert sorted(bare.pages) == sorted(full.pages)
        assert bare.run_seed == full.run_seed

    def test_with_the_codes_off_there_is_nothing_to_scan(
            self, compiled_without_codes):
        """The other half: the index is unchanged, the symbol is gone.
        Without this the test above would also pass if `codes=False`
        quietly did nothing."""
        pdfium = pytest.importorskip("pypdfium2")
        zxingcpp = pytest.importorskip("zxingcpp")
        pdf = pdfium.PdfDocument(
            os.path.join(compiled_without_codes, "main.pdf"))
        for n in sorted(pageindex.load(compiled_without_codes).pages):
            image = pdf[n - 1].render(scale=200 / 72).to_pil()
            assert not zxingcpp.read_barcodes(image), \
                f"page {n} still carries a code"

    def test_the_recorded_rectangle_lands_on_the_grading_box(self, compiled):
        """Checked by ink, because a coordinate system can be wrong in
        a way that still produces plausible numbers -- and this one
        was: the first version measured the box inside the group the
        footer is built in, and the deferred write read a void
        register, giving the right position and a width of zero.

        The box is a thick rounded outline filled white. So inside the
        rectangle there must be dark pixels around the edge and almost
        none in the middle. A rectangle on blank paper has none at
        all; one that slid onto the skill slug beside it has them in
        the middle.
        """
        pdfium = pytest.importorskip("pypdfium2")
        numpy = pytest.importorskip("numpy")
        pdf = pdfium.PdfDocument(os.path.join(compiled, "main.pdf"))
        index = pageindex.load(compiled)
        boxed = [p for p in index.pages.values() if p.box]
        assert boxed, "no page recorded a grading box"

        for entry in boxed:
            page = pdf[entry.page - 1]
            left, top, right, bottom = entry.box.rect(200, page.get_height())
            image = page.render(scale=200 / 72).to_pil().convert("L")
            crop = numpy.asarray(
                image.crop((round(left), round(top),
                            round(right), round(bottom))), dtype=float)
            assert crop.size, f"page {entry.page}: the rectangle is off-page"
            dark = crop < 128
            inset = max(1, min(crop.shape) // 4)
            middle = dark[inset:-inset, inset:-inset]
            assert dark.sum() - middle.sum() > 20, \
                f"page {entry.page}: no box outline inside the rectangle"
            assert middle.sum() < middle.size * 0.2, \
                f"page {entry.page}: the rectangle is not on an empty box"

    def test_measuring_the_box_does_not_move_anything(self, compiled,
                                                      tmp_path):
        """Instrumenting the footer must leave the page alone.

        The first version drew the *measured copy* of the box with
        `\\usebox`, and the box and the skill slug beside it shifted
        about 0.8mm -- `\\roundbox` ends in `\\xspace`, which decides
        whether to add a space by looking at what comes next, and
        inside a save box what comes next is the end of the box.

        3,344 pixels out of 8.4 million, all in one corner. Small
        enough to miss by eye on every page of a print run, which is
        why it is a test rather than a look.
        """
        pdfium = pytest.importorskip("pypdfium2")
        numpy = pytest.importorskip("numpy")

        plain = tmp_path / "plainbox"
        shutil.copytree(compiled, plain)
        sty = plain / "printit.sty"
        text = sty.read_text(encoding="utf-8")
        marker = r"\cipcheckbox{20pt}"
        assert text.count(marker) == 1, "the footer's call moved"
        sty.write_text(text.replace(marker, r"\roundbox{20pt}"),
                       encoding="utf-8")
        for _ in range(2):
            subprocess.run([pdflatex, "-interaction=nonstopmode",
                            "-halt-on-error", "main.tex"],
                           cwd=plain, capture_output=True, timeout=300)

        was = pdfium.PdfDocument(str(plain / "main.pdf"))
        now = pdfium.PdfDocument(os.path.join(compiled, "main.pdf"))
        assert len(was) == len(now)
        for n in range(min(len(was), 4)):
            a = numpy.asarray(was[n].render(scale=150 / 72).to_pil()
                              .convert("L"), dtype=int)
            b = numpy.asarray(now[n].render(scale=150 / 72).to_pil()
                              .convert("L"), dtype=int)
            moved = int((numpy.abs(a - b) > 8).sum())
            assert moved == 0, \
                f"page {n + 1}: {moved} pixels moved when the box was measured"

    def test_the_code_on_a_page_resolves_to_that_page(self, compiled):
        """The claim the short payload rests on, read back off the
        page at 200dpi -- the low end of the instructor's copier.
        \\thepage is expanded while the footer is built inside the
        output routine, which is correct in principle and had never
        been checked against a rendered page."""
        pdfium = pytest.importorskip("pypdfium2")
        zxingcpp = pytest.importorskip("zxingcpp")
        pdf = pdfium.PdfDocument(os.path.join(compiled, "main.pdf"))
        index = pageindex.load(compiled)
        for n, entry in sorted(index.pages.items()):
            image = pdf[n - 1].render(scale=200 / 72).to_pil()
            found = [c.text for c in zxingcpp.read_barcodes(image)]
            assert found, f"page {n} carries no readable code"
            assert pageindex.read_payload(found[0]) == (index.run_seed, n)
            assert entry.page == n
