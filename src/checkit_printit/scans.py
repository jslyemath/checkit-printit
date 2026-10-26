"""Reading marked papers back in.

What arrives is not a tidy stack. From the instructor: several PDFs,
because one is too large for the copier to email; both sides, but not
always in the same batch; blank pages mixed in; and the papers all
shuffled. **Page order carries no information whatsoever**, so every
page has to identify itself, and that is what the footer code and
`main.pages` are for.

This module does the placing and nothing else. It does not look at
what the student wrote -- classifying a mark is a separate job with a
separate failure mode, and the instructor has to be able to trust the
placing before any of it is worth showing him.

    batch = read_pdfs(["front.pdf", "back.pdf"], record_path)
    batch.placed          # sheets that found a student
    batch.duplicates      # the same paper scanned twice
    batch.missing(...)    # papers that never came back

The three questions at the end are the point. A scan that silently
loses a page is worse than one that fails, because the student whose
paper went missing is the one who does not complain.
"""

import dataclasses
import os

from . import pageindex
from . import record as record_mod

#: What a scanned page is rendered at before the code is looked for.
#: 200 is the low end of what the instructor's copier produces, and
#: 9mm reads 150/150 there even on a photocopy of a photocopy -- so
#: rendering higher would cost time to buy nothing. Raise it only
#: against evidence from a scanner that needs it.
DPI = 200

#: Below this fraction of dark pixels a page with no code is called
#: blank rather than unreadable. Both are "nothing to grade", but the
#: instructor should chase one and ignore the other.
#:
#: **Needs calibrating against a real scanner.** 0.005 is a guess
#: made against simulated scans; a copier that runs dark could put a
#: genuinely empty sheet above it, and then every padding page would
#: be reported as a paper that failed to read.
INK_FLOOR = 0.005


class ScanError(Exception):
    """Something stopped the read. The message is for a human."""


@dataclasses.dataclass(frozen=True)
class Sheet:
    """One side of one sheet in the stack, and what was made of it."""

    #: The PDF it came out of, and its page number *in that file*.
    #: Kept so the instructor can be told where to look, and for no
    #: other reason -- position in the stack means nothing here.
    source: str
    at: int

    #: One of:
    #:   placed      the code resolved to a run and a page in it
    #:   blank       no code and almost no ink: padding, or a separator
    #:   unreadable  ink but no code anybody could read
    #:   foreign     a code, but not one of ours
    #:   unknown-run a code of ours naming a run this course has not got
    #:   unknown-page a run we have, a page it does not have
    status: str

    run_no: int = None
    page: int = None
    #: The `main.pages` entry, when there is one.
    entry: object = None
    #: What was decoded, whatever it was. Kept for the foreign case,
    #: where the instructor is the only one who can say what it is.
    code: str = ""
    #: `{label: image}` for whatever was asked for, straightened and
    #: cut out of this page. Small on purpose: the whole page is
    #: thrown away once these are taken, because a few hundred full
    #: renders will not fit in memory and these will.
    cuts: dict = dataclasses.field(default_factory=dict)

    @property
    def placed(self):
        return self.status == "placed"

    @property
    def gradable(self):
        """Placed, and not an answer key.

        A key in the stack is an ordinary accident -- they are printed
        with the handouts and travel with them -- and recording one as
        an attempt would invent a student's work.
        """
        return self.placed and self.entry is not None and self.entry.gradable


@dataclasses.dataclass
class Batch:
    """Everything read, and the three questions worth asking of it."""

    sheets: list

    @property
    def placed(self):
        return [s for s in self.sheets if s.placed]

    @property
    def unplaced(self):
        """Everything that did not find a home, blanks included.

        One list rather than one per status: the instructor wants to
        see the pile, and the status is on each sheet.
        """
        return [s for s in self.sheets if not s.placed]

    @property
    def runs(self):
        """The run numbers this stack touches, in the order met."""
        seen = []
        for sheet in self.placed:
            if sheet.run_no not in seen:
                seen.append(sheet.run_no)
        return seen

    @property
    def duplicates(self):
        """`{(run, page): [sheets]}` for anything read more than once.

        A double-feed, a stack scanned twice, or the same sheet in two
        of the PDFs. Never resolved automatically: two scans of one
        paper are usually identical and occasionally are not, and
        which one the instructor meant is not a question this can
        answer.
        """
        seen = {}
        for sheet in self.placed:
            seen.setdefault((sheet.run_no, sheet.page), []).append(sheet)
        return {key: group for key, group in seen.items() if len(group) > 1}

    def missing(self, index_for):
        """`{run: [pages]}` handed to a student and not in this stack.

        `index_for(run_no)` gives that run's `pageindex.Index`.

        **Students' papers only.** Three kinds of page are printed and
        only one of them is expected back:

        * padding has no line in the index at all, so it cannot be
          missing;
        * an answer key never leaves the instructor's folder;
        * a spare is printed in case somebody needs one, and most
          runs end with spares nobody took.

        Counting those would bury the real answer -- the first
        version of this listed six missing pages for a stack that was
        short of two students' papers and four keys.

        The question nobody asks until it is too late. A paper that
        never came back is a student who was absent or a sheet that
        stuck to another in the feeder, and those want different
        responses, but both start here.
        """
        arrived = {(s.run_no, s.page) for s in self.placed}
        out = {}
        for run_no in self.runs:
            index = index_for(run_no)
            if index is None:
                continue
            gone = [page for page, entry in sorted(index.pages.items())
                    if entry.kind == "student"
                    and (run_no, page) not in arrived]
            if gone:
                out[run_no] = gone
        return out


# ----------------------------------------------------- where things are --
#
# `main.pages` says where the grading box, the id and the name sit
# **on the page**. A scan is that page photographed crookedly: shifted,
# turned a degree or two, and at whatever size the copier felt like.
# So a rectangle in page coordinates has to be carried across to the
# scan before anything can be cut out of it.
#
# The footer code is the thing that carries it. zxing reports the four
# corners of every symbol it reads, so the same square is visible in
# both pictures and the difference between them *is* the
# transformation -- turn, scale and shift, in one measurement, taken
# from the page itself rather than assumed about the scanner.
#
# What it needs is where the code sits on the page, and that is not in
# `main.pages`. Rather than record it -- which would mean changing the
# theme again, and the bank has only just been brought up to date --
# it is read off the run's own PDF, which is sitting in the folder
# next to the index.
#
# **Twice per run, not once per page.** The footer puts the code at
# the left margin on an odd page, and after a fixed 1.9in box on an
# even one. Neither depends on the content, so there are two answers
# per run and the rest is arithmetic.


@dataclasses.dataclass(frozen=True)
class Anchor:
    """The footer code's corners on the printed page, in page pixels."""

    corners: tuple          #: ((x, y) * 4), clockwise from top-left
    dpi: float
    page_height: float      #: the PDF's own height, in PostScript points


def _corners(found):
    p = found.position
    return ((p.top_left.x, p.top_left.y), (p.top_right.x, p.top_right.y),
            (p.bottom_right.x, p.bottom_right.y),
            (p.bottom_left.x, p.bottom_left.y))


def _centre(points):
    return (sum(x for x, _ in points) / len(points),
            sum(y for _, y in points) / len(points))


def anchors(run_folder, dpi=DPI):
    """`{parity: Anchor}` for a run, read off its own PDF.

    Parity is `page % 2`, and that is the whole index: the code's
    place in the footer depends on which side of the sheet it is and
    on nothing else.

    Returns `{}` when the folder has no PDF any more. That is a real
    case -- a run can be recorded and its folder moved -- and it means
    the pages can still be *placed*, because placing only needs the
    index, but nothing can be cut out of them.
    """
    import pypdfium2 as pdfium
    import zxingcpp

    pdf_path = os.path.join(run_folder, "main.pdf")
    if not os.path.isfile(pdf_path):
        return {}
    out = {}
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        for n in range(1, len(pdf) + 1):
            if len(out) == 2:
                break
            if n % 2 in out:
                continue
            page = pdf[n - 1]
            found = zxingcpp.read_barcodes(page.render(scale=dpi / 72).to_pil())
            ours = [f for f in found if pageindex.read_payload(f.text)]
            if ours:
                out[n % 2] = Anchor(corners=_corners(ours[0]), dpi=dpi,
                                    page_height=page.get_height())
    finally:
        pdf.close()
    return out


def placement(anchor, scan_corners):
    """Turn, scale and shift that carry the page onto the scan.

    A similarity, not a full perspective: a sheet on a platen is flat
    and square to the glass, so it can be turned and moved and scaled
    and nothing else. Fitting a perspective to four points that only
    differ by those three would read the noise in the corner estimates
    as keystone.
    """
    import math

    px, py = _centre(anchor.corners)
    sx, sy = _centre(scan_corners)
    # Measured across the diagonals rather than one edge: a corner
    # estimate is a pixel or two out either way, and a diagonal is the
    # longest baseline the symbol offers.
    scale, angle, n = 0.0, 0.0, 0
    for i in (0, 1):
        ax, ay = anchor.corners[i]
        bx, by = anchor.corners[i + 2]
        cx, cy = scan_corners[i]
        dx, dy = scan_corners[i + 2]
        page_len = math.hypot(bx - ax, by - ay)
        scan_len = math.hypot(dx - cx, dy - cy)
        if page_len <= 0:
            continue
        scale += scan_len / page_len
        # Wrapped into (-pi, pi] before it is added in. The two
        # diagonals of one turn can come out as +90 and -270
        # degrees, which are the same angle and average to -90 -- a
        # quarter turn the wrong way. A sheet off a feeder is never
        # more than a few degrees out, so this never bit; it was
        # waiting for the first page somebody fed in sideways.
        turn = (math.atan2(dy - cy, dx - cx)
                - math.atan2(by - ay, bx - ax))
        angle += (turn + math.pi) % (2 * math.pi) - math.pi
        n += 1
    if not n:
        return None
    scale, angle = scale / n, angle / n
    cos, sin = math.cos(angle) * scale, math.sin(angle) * scale

    def carry(x, y):
        dx, dy = x - px, y - py
        return (sx + dx * cos - dy * sin, sy + dx * sin + dy * cos)

    return carry


#: How much room to take around a mark, as a fraction of its own
#: width, going (left, top, right, bottom).
#:
#: Not the same on every side, because the two marks the instructor
#: uses do not sit in the same place. A check "whose tail comes out
#: past the box" needs room above and to the right; a `?` is written
#: **beside** the box, to its right, and a crop that stops at the
#: rectangle does not contain it at all. An empty box and a box with
#: a question mark next to it are different answers, and only one of
#: them can be read off a crop that leaves the mark outside.
#:
#: Left is the tight side: the skill slug is printed there, half an
#: em away, and there is nothing to be gained by taking more of it.
PAD = (0.22, 0.45, 1.05, 0.38)


def cut_out(image, mark, anchor, carry, pad=PAD, height=120):
    """The piece of the scan where `mark` ended up, straightened.

    Straightened by mapping the four corners through `Image.QUAD`,
    which undoes the turn in the same step as the crop. Cropping an
    upright box around a turned rectangle would bring in whatever is
    beside it, and beside the grading box is the skill name.

    The output keeps the crop's own shape rather than being forced
    square -- with a wide pad to the right, a square output would
    squash the box into an oval.
    """
    from PIL import Image

    left, top, right, bottom = mark.rect(anchor.dpi, anchor.page_height)
    unit = right - left
    left -= unit * pad[0]
    top -= unit * pad[1]
    right += unit * pad[2]
    bottom += unit * pad[3]
    size = (max(8, round(height * (right - left) / (bottom - top))), height)
    quad = []
    for x, y in ((left, top), (left, bottom), (right, bottom), (right, top)):
        quad.extend(carry(x, y))
    # Grey first, and `fillcolor` white.
    #
    # A box near the edge of a skewed sheet maps to a quad that runs
    # off the scan, and the default fill is black -- one crop came
    # back with a black wedge across its foot, which is harmless to
    # look at and enough to make any ink measure call that page the
    # most heavily marked of the lot.
    #
    # `fillcolor=255` alone did not fix it: on an RGB image that is
    # one band's worth, and the other two stay at zero, so the fill
    # came out darker than before. Everything downstream measures
    # grey anyway, and a grey crop is a third of the memory when
    # several hundred of them are being kept.
    return image.convert("L").transform(size, Image.QUAD, quad,
                                        resample=Image.BICUBIC,
                                        fillcolor=255)


#: How dark a pixel has to be to count as ink, out of 255.
#:
#: 128 -- halfway -- was the obvious choice and the wrong one. Blur
#: spreads the printed outline of the box inwards, and halfway counts
#: the grey halo as writing: an empty box measured up to 0.08 of its
#: own middle as ink, which is more than a faint tick manages.
#:
#: Swept against simulated scans. At 80 the faintest tick measures
#: 0.016 and the most inked empty box 0.003, which is the first
#: setting where the two do not overlap at all. Going darker still
#: works and leaves less of the tick to find.
#:
#: Absolute rather than relative to each crop's own paper level,
#: which was tried and is worse: the halo scales with the paper, so
#: a relative cut keeps counting it however it is set.
INK = 80

#: Ink inside the box at or above this is a tick. Set between the
#: two groups rather than at the edge of either -- three times the
#: heaviest empty box, half the faintest tick.
TICKED = 0.008

#: Below this, with nothing beside it, the box is empty. The same
#: number: with the groups cleanly apart there is no band in
#: between worth reserving, and a gap here would only manufacture
#: review for readings that are not ambiguous.
EMPTY = 0.008

#: Ink in the space to the right of the box at or above this is
#: *something* -- most likely the instructor's `?`, possibly a
#: smudge. Deliberately not called a question mark: see `measure`.
#:
#: Low, because an empty box measures exactly zero there and a
#: question mark's faintest reading is 0.001. Anything above the
#: floor is worth a look; the cost of being wrong is one glance.
BESIDE = 0.002

#: Ignored either side of the box's own outline when measuring, as a
#: fraction of the box's width. The outline is printed, not written,
#: and a measurement that counts it is measuring the form.
EDGE = 0.22


def _window(shape, pad=None):
    """Where the box sits inside a crop, in pixels.

    Derived from PAD rather than written down again, so the two
    cannot drift apart -- the crop is the rectangle grown by those
    fractions, so the rectangle is that slice of the crop.
    """
    pad = pad or PAD
    height, width = shape
    across, down = pad[0] + 1 + pad[2], pad[1] + 1 + pad[3]
    x0 = int(width * pad[0] / across)
    x1 = int(width * (pad[0] + 1) / across)
    y0 = int(height * pad[1] / down)
    y1 = int(height * (pad[1] + 1) / down)
    return x0, y0, x1, y1


def measure(crop, pad=None):
    """What a crop of the grading box shows. Numbers, then a guess.

    `inside` is the fraction of the box's middle that is dark, with
    the printed outline left out -- that is the tick.

    `beside` is the same for the space to its right, where the
    instructor writes a `?`. It starts clear of the outline, because
    a rounded corner clipped by a window boundary reads as 2% of ink
    that is not there.

    `call` is one of:

        ticked   enough ink in the box
        empty    almost nothing, in the box or beside it
        unsure   nothing in the box, but something next to it

    **`unsure` is not a failure, and there is deliberately no
    `queried`.** A `?` is small, hand-drawn and in a region where an
    empty box already shows a percent or two, so a threshold that
    caught every one of them would also catch smudges. Calling it
    unsure puts the crop in front of the instructor, which is where
    the decision between a question mark and a coffee ring belongs.
    Only the tick is claimed, and only the tick exports as a pass.
    """
    import numpy

    dark = numpy.asarray(crop.convert("L"), dtype=numpy.uint8) < INK
    x0, y0, x1, y1 = _window(dark.shape, pad)
    edge = max(1, int((x1 - x0) * EDGE))
    inside = dark[y0 + edge:y1 - edge, x0 + edge:x1 - edge]
    beside = dark[y0:y1, x1 + edge:]
    inside = float(inside.mean()) if inside.size else 0.0
    beside = float(beside.mean()) if beside.size else 0.0

    # Ink in the box decides the tick, and ink beside it does not
    # argue -- beside the box is where the tail goes. Ink out there
    # only means anything when the box itself is empty, because that
    # is the only time it could be a question mark.
    if inside >= TICKED:
        call = "ticked"
    elif beside >= BESIDE:
        call = "unsure"
    else:
        call = "empty"
    return {"inside": round(inside, 4), "beside": round(beside, 4),
            "call": call}


def _dark_fraction(image):
    """How much of a page has ink on it, roughly."""
    import numpy
    grey = numpy.asarray(image.convert("L"), dtype=numpy.uint8)
    return float((grey < 128).mean())


def read_page(image, resolve, anchors_for=None, want=()):
    """Place one rendered page. `resolve(run_no)` gives its Index.

    `anchors_for(run_no)` gives that run's `{parity: Anchor}`, and
    `want` names the marks to cut out. Both optional: placing a page
    needs neither, and the instructor may only want to know what came
    back.
    """
    import zxingcpp

    symbols = zxingcpp.read_barcodes(image)
    found = [c.text for c in symbols]
    ours = next((pageindex.read_payload(t) for t in found
                 if pageindex.read_payload(t)), None)

    if ours is None:
        if found:
            return {"status": "foreign", "code": found[0]}
        if _dark_fraction(image) < INK_FLOOR:
            return {"status": "blank"}
        return {"status": "unreadable"}

    run_no, page = ours
    index = resolve(run_no)
    if index is None:
        return {"status": "unknown-run", "run_no": run_no, "page": page,
                "code": f"C1-{run_no}-{page}"}
    entry = index.get(page)
    if entry is None:
        # The run exists and says nothing about this page. Either the
        # paper is from a rebuild of that folder with different
        # pagination, or the index was written by a different compile
        # than the one that printed this sheet.
        return {"status": "unknown-page", "run_no": run_no, "page": page,
                "code": f"C1-{run_no}-{page}"}
    out = {"status": "placed", "run_no": run_no, "page": page,
           "entry": entry, "code": f"C1-{run_no}-{page}"}
    if want and anchors_for:
        out["cuts"] = _cuts(image, entry, page, symbols,
                            anchors_for(run_no), want)
    return out


def _cuts(image, entry, page, symbols, anchors, want):
    """Straightened crops of the marks asked for, or nothing.

    Nothing, quietly, in three cases that are all ordinary: the run's
    folder has gone, so there is no page to compare against; the
    sheet is a continuation and carries no grading box; the corners
    came back unusable. None of them is a failure of the read -- the
    page is still placed -- so none of them raises.
    """
    anchor = (anchors or {}).get(page % 2)
    if anchor is None:
        return {}
    ours = next((s for s in symbols if pageindex.read_payload(s.text)), None)
    if ours is None:
        return {}
    carry = placement(anchor, _corners(ours))
    if carry is None:
        return {}
    cuts = {}
    for label in want:
        mark = entry.marks.get(label)
        if mark is not None:
            cuts[label] = cut_out(image, mark, anchor, carry)
    return cuts


def index_reader(record_path):
    """`run_no -> Index`, cached, from the course's print record.

    Returns None for a run the record does not have and for one whose
    folder has been moved or deleted -- both are "this page cannot be
    placed", and the difference is not worth two statuses when the
    instructor's next move is the same either way.
    """
    cache = {}

    def resolve(run_no):
        if run_no in cache:
            return cache[run_no]
        cache[run_no] = None
        row = record_mod.run_by_no(record_path, run_no)
        if row and row.get("output"):
            try:
                cache[run_no] = pageindex.load(row["output"])
            except pageindex.PageIndexError:
                pass
        return cache[run_no]

    return resolve


def anchor_reader(record_path, dpi=DPI):
    """`run_no -> {parity: Anchor}`, cached, from the run's own PDF.

    Cached hard, because this is the expensive half: it renders a
    page of the original at scanning resolution and looks for a code
    in it. Two per run, and a run's worth of scans then costs
    nothing more.
    """
    cache = {}

    def resolve(run_no):
        if run_no not in cache:
            cache[run_no] = {}
            row = record_mod.run_by_no(record_path, run_no)
            if row and row.get("output"):
                cache[run_no] = anchors(row["output"], dpi)
        return cache[run_no]

    return resolve


def read_pdfs(paths, record_path, dpi=DPI, on_page=None, want=()):
    """Read a stack. `on_page(done, total)` is called as it goes.

    The PDFs are read in the order given and pages in the order they
    appear, which matters for nothing except being able to tell the
    instructor where a sheet was.
    """
    import pypdfium2 as pdfium

    paths = [str(p) for p in paths]
    for path in paths:
        if not os.path.isfile(path):
            raise ScanError(f"{path} does not exist.")

    resolve = index_reader(record_path)
    anchors_for = anchor_reader(record_path, dpi) if want else None
    documents = []
    try:
        for path in paths:
            try:
                documents.append((path, pdfium.PdfDocument(path)))
            except Exception as exc:
                raise ScanError(f"{path} could not be opened: {exc}") from None

        total = sum(len(doc) for _, doc in documents)
        if not total:
            raise ScanError("those files hold no pages at all.")

        sheets, done = [], 0
        for path, doc in documents:
            for n in range(1, len(doc) + 1):
                image = doc[n - 1].render(scale=dpi / 72).to_pil()
                sheets.append(Sheet(
                    source=path, at=n,
                    **read_page(image, resolve, anchors_for, want)))
                done += 1
                if on_page:
                    on_page(done, total)
        return Batch(sheets=sheets)
    finally:
        for _, doc in documents:
            doc.close()
