"""Reading a stack of scans back in.

The fixture builds the stack the instructor described rather than a
tidy one: the pages shuffled, split across two files, blanks dropped
in, and every page rasterised and degraded the way a copier degrades
it. A test that scans the PDF printit just produced would pass
whatever the placing did, because the pages would already be in
order.
"""

import io
import os
import random
import subprocess

import pytest

from checkit_printit import assemble as assemble_mod
from checkit_printit import pageindex
from checkit_printit import publication as pub_mod
from checkit_printit import roster as roster_mod
from checkit_printit import scans, seating, theme
from checkit_printit.compile import find_pdflatex

pdflatex = find_pdflatex()
pytestmark = pytest.mark.skipif(not pdflatex, reason="no pdflatex")

RUN_NO = 4


def students():
    """Ada takes one skill, so her paper ends on an odd page and the
    run contains a padding sheet -- which must not be scanned as a
    paper that failed to read."""
    return roster_mod.Roster([
        roster_mod.Student(name="Ada", section="1", skills=["AD"],
                           sid="800000111"),
        roster_mod.Student(name="Bo", section="1", skills=["AD", "SU"],
                           sid="800000222"),
    ])


@pytest.fixture(scope="module")
def printed(bank_dir, tmp_path_factory):
    """A compiled run, and the index beside it."""
    tmp_path = tmp_path_factory.mktemp("printed")
    chart = tmp_path / "seating.toml"
    chart.write_text('[[group]]\nseats = ["Ada", "Bo"]\n', encoding="utf-8")
    publication = pub_mod.Publication(
        course="TEST 101", semester="Fall", professor="Nobody",
        title="Checkpoint", date="2026-01-01", bank_path=bank_dir,
        keys=True, key_copies=1)
    out = str(tmp_path / "out")
    source, _ = theme.load(bank_dir)
    assemble_mod.assemble(publication, students(),
                          seating.load(str(chart)), out, source,
                          rng=random.Random(1), run_seed=1, run_id=RUN_NO)
    for _ in range(2):
        subprocess.run([pdflatex, "-interaction=nonstopmode",
                        "-halt-on-error", "main.tex"],
                       cwd=out, capture_output=True, timeout=300)
    assert os.path.isfile(os.path.join(out, "main.pdf"))
    return out


def scanned_images(pdf_path, pages, rng, dpi=200):
    """Render those pages the way a copier would hand them over."""
    import numpy
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter

    doc = pdfium.PdfDocument(pdf_path)
    out = []
    for n in pages:
        big = doc[n - 1].render(scale=dpi * 3 / 72).to_pil().convert("L")
        big = big.filter(ImageFilter.GaussianBlur(radius=3 * 0.55))
        big = big.rotate(rng.uniform(-1.5, 1.5), resample=Image.BICUBIC,
                         fillcolor=255)
        small = big.resize((big.width // 3, big.height // 3), Image.BOX)
        a = numpy.asarray(small, dtype=float)
        a = 35 + a * (243 - 35) / 255
        a = a + numpy.random.default_rng(rng.randrange(2 ** 31)).normal(
            0, 6, a.shape)
        out.append(Image.fromarray(
            numpy.clip(a, 0, 255).astype("uint8")).convert("RGB"))
    doc.close()
    return out


def blank_like(image, rng):
    """An empty sheet off the same scanner: paper, not pure white."""
    import numpy
    from PIL import Image
    a = numpy.full((image.height, image.width), 243.0)
    a += numpy.random.default_rng(rng.randrange(2 ** 31)).normal(
        0, 6, a.shape)
    return Image.fromarray(
        numpy.clip(a, 0, 255).astype("uint8")).convert("RGB")


def write_pdf(images, path):
    images[0].save(path, save_all=True, append_images=images[1:],
                   resolution=200.0)
    return str(path)


@pytest.fixture(scope="module")
def stack(printed, tmp_path_factory):
    """Two PDFs, shuffled, with blanks dropped in.

    Returns (paths, index, order) where `order` is the page number
    each scanned image actually came from -- so a test can check that
    placing found the right one rather than merely finding something.
    """
    pytest.importorskip("pypdfium2")
    pytest.importorskip("numpy")
    tmp_path = tmp_path_factory.mktemp("stack")
    index = pageindex.load(printed)
    rng = random.Random(99)

    pages = sorted(index.pages)
    rng.shuffle(pages)
    images = scanned_images(os.path.join(printed, "main.pdf"), pages, rng)

    # Two blanks, somewhere in the middle, as the copier would feed a
    # separator or an empty back.
    order = list(pages)
    for position in (3, len(images) - 2):
        images.insert(position, blank_like(images[0], rng))
        order.insert(position, None)

    half = len(images) // 2
    paths = [write_pdf(images[:half], tmp_path / "front.pdf"),
             write_pdf(images[half:], tmp_path / "back.pdf")]
    return paths, index, order


@pytest.fixture(scope="module")
def record_path(printed, tmp_path_factory):
    """A record holding exactly this run, under run number 4."""
    from checkit_printit import record as record_mod
    path = str(tmp_path_factory.mktemp("rec") / "record.db")
    record_mod.write_run(path, run_id="checkpoint", title="Checkpoint",
                         date="2026-01-01", built="2026-01-01T09:00",
                         seed=1, output=printed, handouts=[], run_no=RUN_NO)
    return path


@pytest.fixture(scope="module")
def batch(stack, record_path):
    paths, _, _ = stack
    return scans.read_pdfs(paths, record_path)


class TestPlacing:
    def test_the_stack_really_is_out_of_order(self, stack):
        """The premise, asserted rather than assumed.

        Everything below compares placing against where each scan
        actually came from, which is the right comparison -- but it
        adapts to whatever order the fixture produced. Take the
        shuffle out and the whole file still passes, because a
        placing that went by position would be right by luck. So the
        shuffle is checked here, once, and the rest can rely on it.
        """
        _, _, order = stack
        pages = [p for p in order if p is not None]
        assert pages != sorted(pages), "the fixture handed over a tidy stack"
        assert len(set(pages)) == len(pages)

    def test_the_two_files_split_the_stack(self, stack, batch):
        """Fronts and backs arrive in different batches, so a run's
        pages are spread across files with no relationship to what is
        in them."""
        paths, _, _ = stack
        assert len({s.source for s in batch.placed}) == len(paths) == 2

    def test_every_printed_page_is_found(self, batch, stack):
        _, index, _ = stack
        assert len(batch.placed) == len(index.pages)

    def test_each_scan_is_placed_on_the_page_it_came_from(self, batch, stack):
        """The whole claim. The scans are shuffled and split across
        two files, so a placing that went by position would be wrong
        for all but a couple of them by luck."""
        _, _, order = stack
        got = [s.page for s in batch.sheets]
        assert got == order

    def test_a_placed_student_page_names_the_right_student(self, batch):
        owners = {s.entry.sid for s in batch.placed
                  if s.entry.kind == "student"}
        assert owners == {"800000111", "800000222"}

    def test_the_run_is_identified(self, batch):
        assert batch.runs == [RUN_NO]

    def test_a_key_is_placed_but_not_gradable(self, batch):
        """Keys are printed with the handouts and travel with them,
        so one in the stack is an ordinary accident. Recording it as
        an attempt would invent a student's work."""
        keys = [s for s in batch.placed if s.entry.kind == "key"]
        assert keys, "the run printed keys and none were placed"
        assert not any(s.gradable for s in keys)
        assert all(s.gradable for s in batch.placed
                   if s.entry.kind == "student")


class TestWhatDidNotPlace:
    def test_a_blank_sheet_is_reported_blank(self, batch):
        blanks = [s for s in batch.sheets if s.status == "blank"]
        assert len(blanks) == 2

    def test_nothing_is_unreadable(self, batch):
        """Every page that carried a code was read. If this starts
        failing, the symbol or the scan has got worse -- it is the
        canary for the 9mm decision."""
        bad = [(s.source, s.at) for s in batch.sheets
               if s.status == "unreadable"]
        assert not bad, bad

    def test_a_code_from_another_system_is_not_ours(self, record_path):
        from PIL import Image
        import numpy
        pytest.importorskip("zxingcpp")
        # A page whose only code is an ISBN.
        blank = Image.fromarray(
            numpy.full((400, 400), 255, dtype="uint8")).convert("RGB")
        out = scans.read_page(blank, scans.index_reader(record_path))
        assert out["status"] == "blank"

    def test_a_run_the_record_does_not_have(self, tmp_path):
        from checkit_printit import record as record_mod
        path = str(tmp_path / "record.db")
        record_mod.connect(path).close()
        resolve = scans.index_reader(path)
        assert resolve(99) is None


class TestTheThreeQuestions:
    def test_a_clean_stack_has_no_duplicates(self, batch):
        assert batch.duplicates == {}

    def test_a_clean_stack_is_not_missing_anything(self, batch, stack):
        _, index, _ = stack
        assert batch.missing(lambda n: index) == {}

    def test_a_double_feed_is_caught(self, batch, stack):
        """Two scans of one paper are usually identical and
        occasionally are not, so this is never resolved
        automatically."""
        _, index, _ = stack
        twice = scans.Batch(sheets=batch.sheets + [batch.placed[0]])
        key = (batch.placed[0].run_no, batch.placed[0].page)
        assert list(twice.duplicates) == [key]
        assert len(twice.duplicates[key]) == 2

    def test_a_paper_that_never_came_back_is_named(self, batch, stack):
        """The question nobody asks until it is too late. A student
        whose paper went missing is the one who does not complain."""
        _, index, _ = stack
        # A student's paper specifically. `placed[0]` is whatever the
        # shuffle put first, and when that was a key this asserted
        # that a key not coming back is reported -- which it is not,
        # and should not be.
        dropped = next(s for s in batch.placed if s.entry.kind == "student")
        short = scans.Batch(sheets=[s for s in batch.sheets
                                    if s is not dropped])
        assert short.missing(lambda n: index) == {dropped.run_no:
                                                  [dropped.page]}

    def test_padding_pages_are_not_expected_back(self, batch, stack):
        """`main.pages` lists no line for a blank, so a blank cannot
        be missing. Ada takes one skill, so this run has one."""
        _, index, _ = stack
        assert index.blanks(), "no padding page, so this proves nothing"
        assert batch.missing(lambda n: index) == {}

    def test_an_answer_key_is_not_expected_back(self, stack):
        """A key never leaves the instructor's folder, so a stack
        without one is not short of anything. Counting keys buried
        the real answer: a stack missing two students' papers
        reported six missing pages, four of them keys."""
        _, index, _ = stack
        keys = [n for n, e in index.pages.items() if e.kind == "key"]
        assert keys, "the run printed no keys, so this proves nothing"
        nothing = scans.Batch(sheets=[
            scans.Sheet(source="x", at=1, status="placed", run_no=RUN_NO,
                        page=n, entry=index.get(n))
            for n in index.pages if index.get(n).kind == "student"])
        assert nothing.missing(lambda n: index) == {}

    def test_a_student_page_is_still_expected_back(self, stack):
        """The other half: without this, the test above would pass
        if `missing` had simply stopped reporting anything."""
        _, index, _ = stack
        students = [n for n, e in index.pages.items()
                    if e.kind == "student"]
        short = scans.Batch(sheets=[
            scans.Sheet(source="x", at=1, status="placed", run_no=RUN_NO,
                        page=n, entry=index.get(n))
            for n in students[1:]])
        assert short.missing(lambda n: index) == {RUN_NO: [students[0]]}

# ------------------------------------------------------ cutting it out --

def box_crop(ink_in_box=0.0, ink_beside=0.0, size=None, pen=(230, 90, 20)):
    """A crop shaped like a real one, with pen placed where asked.

    Built rather than scanned, so a test about thresholds is not
    also a test about pdfium.

    **The box is printed black and the mark is coloured**, because
    that is the difference the reading is built on: the rule, the
    skill slug and a student's pencil are grey whatever their
    darkness, and the instructor's check is not. A fixture that drew
    both in grey could not tell the two apart -- which is precisely
    how the version this replaces came to call an empty box a tick
    on fifty-five real pages.

    Nothing here is placed from `_window` any more. `measure` finds
    the box in the picture, so the fixture draws one and lets it be
    found; a fixture that told the code where to look would be
    testing the arithmetic they shared rather than the finding.
    """
    from PIL import Image, ImageDraw

    size = size or (247, 177)
    image = Image.new("RGB", size, (243, 243, 240))
    draw = ImageDraw.Draw(image)
    # A square box, as `\roundbox` draws, near the middle-left.
    side = 56
    bx, by = 60, (size[1] - side) // 2
    draw.rounded_rectangle([bx, by, bx + side, by + side], radius=7,
                           outline=(30, 30, 30), width=3)
    # `measure` divides both numbers by the area of the box's inset
    # middle, so a fixture asking for "0.3" has to draw 0.3 of
    # *that*, not of the box. Getting this wrong made a 0.3 request
    # come out at 0.63 and read as a scribble.
    middle = side * (1 - 2 * scans.INSET)
    for fraction, (ax, ay) in ((ink_in_box, (bx + 9, by + 9)),
                               (ink_beside, (bx + side + 14, by + 9))):
        if not fraction:
            continue
        span = max(3, round(middle * fraction ** 0.5))
        draw.rectangle([ax, ay, ax + span, ay + span], fill=pen)
    return image


class TestReadingAMark:
    def test_an_untouched_box_is_empty(self):
        assert scans.measure(box_crop())["call"] == "empty"

    def test_the_printed_outline_is_not_counted(self):
        """The box is on every page, so counting it would raise the
        floor under every reading by the same amount and eat the gap
        a tick has to clear."""
        assert scans.measure(box_crop())["inside"] == 0.0

    def test_pen_in_the_box_is_a_tick(self):
        out = scans.measure(box_crop(ink_in_box=0.3))
        assert out["call"] == "ticked"
        assert out["inside"] > scans.INK_MIN

    def test_a_pencil_mark_in_the_box_is_not_a_tick(self):
        """Grey, however dark. A student can tick their own box in
        pencil, and the whole reason the reading looks at colour is
        so that doing so changes nothing."""
        out = scans.measure(box_crop(ink_in_box=0.3, pen=(60, 60, 60)))
        assert out["call"] == "empty"

    def test_the_printed_box_is_not_ink_however_dark_it_is(self):
        """It is black, and black is not a colour. This is the one
        the old reading could not do: it raised `INK` to 80 to stop
        the box's own blurred outline reading as a tick, and at 80
        a faint real mark vanished too."""
        assert scans.measure(box_crop())["inside"] == 0.0

    def test_pen_only_beside_the_box_is_his_question_mark(self):
        """A `?` is written next to the box, not in it. It must
        never read as a pass -- and it is now claimed as a query
        rather than hedged, because colour can tell a drawn mark
        from the blurred corner of a printed box and darkness
        could not."""
        out = scans.measure(box_crop(ink_beside=0.3))
        assert out["call"] == "beside"
        assert out["inside"] < scans.INK_MIN

    def test_a_page_of_working_beside_the_box_is_not_a_question_mark(self):
        """One student wrote their answer in orange pen next to an
        empty box, and it measured 1.2 of the box's area where every
        real `?` measured about 0.25. A `?` is a small mark; a page
        of working is not."""
        out = scans.measure(box_crop(ink_beside=3.0))
        assert out["around"] > scans.BESIDE_MAX
        assert out["call"] == "empty"

    def test_a_tick_with_a_long_tail_is_still_a_tick(self):
        """The instructor's tick is "a check whose tail comes out
        past the box", so ink to the right is expected -- on the
        real stack a tick measured 0.14 inside and up to 0.6
        around. Ink in the box decides; ink beyond it does not
        argue."""
        out = scans.measure(box_crop(ink_in_box=0.3, ink_beside=0.2))
        assert out["call"] == "ticked"

    def test_grey_is_not_ink_at_any_darkness(self):
        """The old reading could only ask how dark a pixel was, and
        every answer was a compromise: light enough to catch a faint
        tick caught the printed box's blurred halo too. Saturation
        does not have the problem -- grey is grey at 10 and at 200."""
        for level in (200, 120, 60, 10):
            out = scans.measure(box_crop(ink_in_box=0.5,
                                         pen=(level, level, level)))
            assert out["call"] == "empty", f"grey {level} counted as ink"

    def test_the_hint_follows_the_padding(self):
        """`_window` is derived from PAD rather than written down
        again, so the two cannot drift apart. It is only the hint
        `find_box` starts from now -- it was the measurement, and
        it was wrong twice over."""
        narrow = scans._window((100, 100), (0.0, 0.0, 0.0, 0.0))
        assert narrow == (0, 0, 100, 100)
        wide = scans._window((100, 100), (1.0, 1.0, 1.0, 1.0))
        assert wide == (33, 33, 66, 66)


class TestCarryingThePageOntoTheScan:
    def test_the_same_corners_are_the_identity(self):
        corners = ((10, 20), (110, 20), (110, 120), (10, 120))
        anchor = scans.Anchor(corners=corners, dpi=200, page_height=792)
        carry = scans.placement(anchor, corners)
        for x, y in ((0, 0), (500, 700), (-30, 40)):
            got = carry(x, y)
            assert abs(got[0] - x) < 1e-6 and abs(got[1] - y) < 1e-6

    def test_a_turned_scan_turns_the_rectangle_back(self):
        """Quarter turn, which is bigger than any feeder manages and
        is the one angle whose answer can be written down by hand."""
        import math
        corners = ((100, 100), (200, 100), (200, 200), (100, 200))
        turned = tuple((300 - y, x) for x, y in corners)
        anchor = scans.Anchor(corners=corners, dpi=200, page_height=792)
        carry = scans.placement(anchor, turned)
        got = carry(100, 100)
        assert abs(got[0] - 200) < 1e-6 and abs(got[1] - 100) < 1e-6

    def test_a_bigger_scan_scales(self):
        corners = ((0, 0), (100, 0), (100, 100), (0, 100))
        twice = tuple((x * 2, y * 2) for x, y in corners)
        anchor = scans.Anchor(corners=corners, dpi=200, page_height=792)
        carry = scans.placement(anchor, twice)
        got = carry(200, 0)
        assert abs(got[0] - 400) < 1e-6 and abs(got[1] - 0) < 1e-6


@pytest.mark.skipif(not pdflatex, reason="no pdflatex")
class TestCuttingItOutOfARealPage:
    def test_the_crop_lands_on_the_box(self, printed):
        """Against the run's own PDF, used as its own scan: then the
        mapping is the identity and the crop has to land exactly,
        which separates the geometry from the skew handling."""
        pdfium = pytest.importorskip("pypdfium2")
        zxingcpp = pytest.importorskip("zxingcpp")
        numpy = pytest.importorskip("numpy")
        index = pageindex.load(printed)
        found_any = scans.anchors(printed)
        assert found_any, "no code on any page to anchor against"

        pdf = pdfium.PdfDocument(os.path.join(printed, "main.pdf"))
        checked = 0
        for n, entry in sorted(index.pages.items()):
            if entry.box is None:
                continue
            page = pdf[n - 1]
            image = page.render(scale=scans.DPI / 72).to_pil()
            codes = [c for c in zxingcpp.read_barcodes(image)
                     if pageindex.read_payload(c.text)]
            anchor = found_any[n % 2]
            carry = scans.placement(anchor, scans._corners(codes[0]))
            crop = scans.cut_out(image, entry.box, anchor, carry)
            # Nothing has been written on these, so the only ink in
            # the crop is the printed box -- and it must be where
            # `measure` looks, which is what reading zero proves.
            out = scans.measure(crop)
            assert out["call"] == "empty", (n, out)
            dark = numpy.asarray(crop, dtype=numpy.uint8) < 128
            assert dark.any(), f"page {n}: the crop is blank paper"
            checked += 1
        pdf.close()
        assert checked, "no page carried a grading box"

    def test_the_crop_keeps_room_for_a_question_mark(self, printed):
        """The `?` goes beside the box, so a crop that stops at the
        rectangle cannot contain one. The space to the right has to
        be wider than the box itself."""
        index = pageindex.load(printed)
        entry = next(e for e in index.pages.values() if e.box)
        anchor = scans.anchors(printed)[entry.page % 2]
        left, top, right, bottom = entry.box.rect(anchor.dpi,
                                                  anchor.page_height)
        assert scans.PAD[2] > 1.0, "no room beside the box for a mark"
        assert scans.PAD[2] > scans.PAD[0], "more room left than right"
