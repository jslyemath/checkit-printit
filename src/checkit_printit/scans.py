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
import typing

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

    #: Where the grading box's centre sits inside its own crop on the
    #: *printed* page, as (across, down) fractions -- or None when no
    #: box could be found there.
    #:
    #: A fraction of the crop rather than a place on the page,
    #: because the crop is cut around the recorded mark and the box
    #: sits at a fixed place inside that mark whatever the page. Both
    #: parities of the 2026-10-26 run measure (0.362, 0.500) to the
    #: pixel, which is the point: it is a property of `\\roundbox`,
    #: not of the sheet, so one measurement is good for every skill.
    #:
    #: A second fiducial, and the reason for it is arithmetic. The
    #: scale is estimated from the footer code's own diagonal, which
    #: is about 100 pixels across; the grading box is 1300 pixels
    #: away from it. An error in reading those four corners is
    #: therefore multiplied thirteenfold by the time it reaches the
    #: box -- and on the stack of 2026-10-26 it was. The scale came
    #: out 1.5% high on every page of it, which pulled the box 19
    #: pixels in towards the code and the name, 1970 pixels out, by
    #: about 29: a third of the height of its own crop, which is why
    #: names came back clipped.
    #:
    #: The box can be *found*, by matching its printed outline, so it
    #: can pin the scale over that long baseline instead of the
    #: code's short one. See `_pinned`.
    box_at: tuple = None


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

    Each anchor also carries `box_at`, measured here off the same
    page: the printed sheet is the only place the box's true position
    can be read without a scanner's errors in the way, and this is
    already the one function that opens it.
    """
    import pypdfium2 as pdfium
    import zxingcpp

    pdf_path = os.path.join(run_folder, "main.pdf")
    if not os.path.isfile(pdf_path):
        return {}
    try:
        index = pageindex.load(run_folder)
    except pageindex.PageIndexError:
        # No index: the pages cannot be cut out anyway, so an anchor
        # without a reference is all there is to offer and is enough
        # for the callers that only want the corners.
        index = None
    out = {}
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        for n in range(1, len(pdf) + 1):
            if len(out) == 2:
                break
            if n % 2 in out:
                continue
            page = pdf[n - 1]
            image = page.render(scale=dpi / 72).to_pil()
            found = zxingcpp.read_barcodes(image)
            ours = [f for f in found if pageindex.read_payload(f.text)]
            if not ours:
                continue
            anchor = Anchor(corners=_corners(ours[0]), dpi=dpi,
                            page_height=page.get_height())
            out[n % 2] = dataclasses.replace(
                anchor, box_at=_reference(image, index, n, anchor))
    finally:
        pdf.close()
    return out


def _reference(image, index, page, anchor):
    """Where the box sits in its own crop, on the page as printed.

    `(across, down)` fractions, or None if there is no box on this
    page or none could be found. None is survivable: it only means
    the scale cannot be corrected and the footer code's own estimate
    stands, which is what every read did before this existed.

    The crop is taken with the identity transform, because the page
    being measured *is* the reference page -- there is no scan here
    to carry anything onto.
    """
    entry = index.get(page) if index is not None else None
    mark = entry.marks.get("box") if entry is not None else None
    if mark is None:
        return None
    crop = cut_out(image, mark, anchor, lambda x, y: (x, y), cut=BOX_CUT)
    found = scored_box(crop)
    if found is None:
        return None
    (x0, y0, x1, y1), _ = found
    return ((x0 + x1) / 2 / crop.width, (y0 + y1) / 2 / crop.height)


def placement(anchor, scan_corners):
    """Turn, scale and shift that carry the page onto the scan.

    A similarity, not a full perspective: a sheet on a platen is flat
    and square to the glass, so it can be turned and moved and scaled
    and nothing else. Fitting a perspective to four points that only
    differ by those three would read the noise in the corner estimates
    as keystone.

    The scale and the turn here are estimated from the code's own
    diagonal, which is about a hundred pixels long, and then applied
    a thousand or more pixels away. That extrapolation is the weak
    part and it is measurably weak: see `_pinned`, which replaces
    both as soon as there is a found box to replace them with. This
    is what stands when there is not.
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
    return _similarity((px, py), (sx, sy), scale / n, angle / n)


def _similarity(page_at, scan_at, scale, angle):
    """The transform that carries page pixels onto scan pixels.

    Four numbers: where a known page point went, how much bigger it
    came out, and how far round. Built here rather than inside
    `placement` because two things make one of these -- the footer
    code on its own, and the code together with a box that has been
    found -- and they should not each have their own copy of the
    arithmetic.
    """
    import math

    cos, sin = math.cos(angle) * scale, math.sin(angle) * scale
    px, py = page_at
    sx, sy = scan_at

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
#: Wider than it looks like it needs to be, on every side. The crop
#: is searched now, not just shown: `find_box` has to have the whole
#: rectangle inside the picture, and the rectangle moves up to fifty
#: pixels between pages. The nine pages that still could not be read
#: after template matching were all boxes half outside the frame.
PAD = (0.70, 0.80, 1.60, 0.80)

#: The name's own padding, measured against its **height**.
#:
#: Against its height because its width is not a usable yardstick:
#: across the real roster the name mark runs from 23pt to 147pt
#: wide, a factor of six, while its height barely moves -- one line
#: of one size, give or take whether the name has a descender in it.
#: Padding by the width therefore gave a short name an inch of paper
#: on each side and a long one almost nothing, which is precisely
#: backwards, because what overruns a crop is a letter and a letter
#: is the same size either way. That one mistake is most of why so
#: many names came back cut off.
#:
#: Generous, and asked for twice: a name sitting exactly in its own
#: typeset box reads as cramped, and the whole job of the picture is
#: to be looked at beside the name the index claims.
#:
#: Asymmetric, because the page is. More below than above, since the
#: skill's coloured banner sits just under the name and a sliver of
#: it is orientation rather than clutter.
#:
#: The left is the measured one, and it is deliberately too wide.
#: `Name:` is printed immediately before the name, with 0.35 to 0.46
#: name-heights of clear paper after its colon, so 0.25 would just
#: clear the colon on a perfectly placed crop. Real crops are not
#: perfectly placed: the content sits up to 14 pixels off, because
#: the box pins the scale across the page and says nothing about the
#: scale down it -- the box is nearly due sideways from the footer
#: code, and a copier does not always reduce both ways equally.
#:
#: 0.60 covers that drift twice over. The cost is that the colon is
#: usually in shot, which is no cost at all: it marks where the name
#: starts, so a crop that is missing its first letter looks missing.
#: The other way round, a crop tight enough to drop the colon is
#: tight enough to drop a letter, and the letter is the whole reason
#: the picture is there.
NAME_PAD = (0.60, 0.50, 0.90, 0.60)

#: How many pixels one mark-unit comes out as, per mark.
#:
#: Fixing this rather than the output height is what lets the
#: padding be changed without resizing everything the reading was
#: tuned against -- and, for the name, what stops a long name being
#: typeset smaller than a short one. It used to be cut to a fixed
#: 96 pixels tall whatever the region, so a six-to-one range of
#: widths came out as a six-to-one range of *text sizes*.
PX_PER_WIDTH = 75
#: 40 puts the name's own line at 40px and its crop at about 84, for
#: a picture shown at 44. Cut larger than it is shown on purpose:
#: looking closer has to reveal something, not just enlarge pixels.
PX_PER_NAME = 40

class Cut(typing.NamedTuple):
    """How one kind of mark is framed, and how big it comes out.

    Three numbers rather than two because the second was never
    really a height: what both marks want is a *scale* -- so many
    output pixels per something the mark itself measures -- and the
    only question is which measurement. The box's crop is a multiple
    of its width, which suits a roughly square mark; the name's is a
    multiple of its height, which is the only thing about a name
    that does not depend on whose it is.
    """

    pad: tuple          #: (left, top, right, bottom), in units
    unit: str           #: "width" or "height" of the mark itself
    per_unit: float     #: output pixels one of those units becomes


BOX_CUT = Cut(PAD, "width", PX_PER_WIDTH)
NAME_CUT = Cut(NAME_PAD, "height", PX_PER_NAME)

#: Per mark, falling back to the box's. Here rather than at the call
#: site so that adding a third mark is one line in one place.
PADS = {"box": BOX_CUT, "name": NAME_CUT}


def _frame(mark, anchor, carry, cut=BOX_CUT):
    """Where a crop comes from and how big it comes out.

    `(quad, size, page_rect)`: the four corners in *scan* pixels that
    `Image.QUAD` samples, clockwise from the top-left; the output
    size they are resampled to; and the same region in the printed
    page's own pixels, as (left, top, right, bottom).

    Split out of `cut_out` because two things need it and a second
    copy of this arithmetic is a second thing to get wrong: the crop
    itself, and `_pinned`, which has to turn a position measured
    inside the crop into a point on the scan and the point it was
    supposed to be into a point on the page.
    """
    pad = cut.pad
    left, top, right, bottom = mark.rect(anchor.dpi, anchor.page_height)
    # Scale by the mark, never by a fixed output size: the box has to
    # come out the same number of pixels across whatever margin the
    # crop is given, because the reading is tuned to that -- and the
    # name has to come out the same size whoever it belongs to.
    unit = (right - left) if cut.unit == "width" else (bottom - top)
    left -= unit * pad[0]
    top -= unit * pad[1]
    right += unit * pad[2]
    bottom += unit * pad[3]
    scale = cut.per_unit / max(1e-6, unit)
    size = (max(8, round((right - left) * scale)),
            max(8, round((bottom - top) * scale)))
    quad = []
    for x, y in ((left, top), (left, bottom), (right, bottom), (right, top)):
        quad.extend(carry(x, y))
    return quad, size, (left, top, right, bottom)


def _on_scan(quad, across, down):
    """A point inside a crop, as a point on the scan it was cut from.

    `across` and `down` are fractions of the crop. The quad is a
    parallelogram -- the transform that made it is a similarity -- so
    interpolating along two of its edges is exact, not an
    approximation.
    """
    x0, y0 = quad[0], quad[1]            # the crop's top-left
    x1, y1 = quad[2], quad[3]            # its bottom-left, so `down`
    x3, y3 = quad[6], quad[7]            # its top-right, so `across`
    return (x0 + (x3 - x0) * across + (x1 - x0) * down,
            y0 + (y3 - y0) * across + (y1 - y0) * down)


def _on_page(page_rect, across, down):
    """The same point, on the printed page instead."""
    left, top, right, bottom = page_rect
    return (left + (right - left) * across, top + (bottom - top) * down)


def cut_out(image, mark, anchor, carry, cut=BOX_CUT):
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

    quad, size, _ = _frame(mark, anchor, carry, cut)
    # Colour, and `fillcolor` white on all three bands.
    #
    # It used to convert to grey here, for memory, because everything
    # downstream measured grey. That was the mistake underneath the
    # bad readings: the mark being looked for is **coloured pen**, and
    # the things that are not it -- the printed rule, the printed
    # text, a student's pencil -- are grey. Throwing the colour away
    # at the crop threw away the only thing that separates them.
    #
    # A box near the edge of a skewed sheet maps to a quad that runs
    # off the scan, and the default fill is black -- one crop came
    # back with a black wedge across its foot, which is harmless to
    # look at and enough to make any ink measure call that page the
    # most heavily marked of the lot. `fillcolor=255` alone did not
    # fix it: on an RGB image that is one band's worth and the other
    # two stay at zero, so the fill came out darker than before.
    return image.convert("RGB").transform(size, Image.QUAD, quad,
                                          resample=Image.BICUBIC,
                                          fillcolor=(255, 255, 255))


#: A pixel is the instructor's pen when it is **coloured** and not
#: paper-white. Saturation, out of 255.
#:
#: This is the whole of the reading. The printed box, the printed
#: question and a pencil mark are all grey -- near-zero saturation,
#: whatever their darkness -- and a pen is not. Masking on colour
#: removes in one step what two years of darkness thresholds could
#: not: the box's own blurred outline, the skill slug beside it, and
#: the student's working written across the crop.
#:
#: It costs one thing, and it is worth saying out loud: **the stack
#: has to be scanned in colour.** A greyscale scan has no pen in it
#: to find, and `read_pdfs` says so rather than reporting every page
#: as empty.
SAT_MIN = 70
VALUE_MAX = 245

#: The printed rectangle: dark, and *not* coloured. Used to find the
#: box, never to measure the mark.
RULE_DARK = 140
RULE_SAT = 60

#: How much of the found box to trim before counting, so its own
#: printed outline is outside the measurement.
INSET = 0.16

#: Pen inside the box, as a fraction of the box's middle. A check
#: covers several percent of it; nothing covers none.
INK_MIN = 0.012

#: More than this inside and the box is not ticked, it is scribbled
#: over -- which is a decision for the instructor, not a pass.
HEAVY_INK = 0.35

#: And more than this *around* it is not a `?` -- it is the
#: student's own working, in pen, next to an empty box.
#:
#: The one threshold here fitted to a single stack. Every question
#: mark in the 62 pages of 2026-10-26 measured 0.23 to 0.27 of the
#: box's area and one student's orange working measured 1.20, so
#: the gap is wide; it is still one stack. If a large, loopy `?`
#: ever reads as "empty", this is the number that did it.
BESIDE_MAX = 0.60

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


def _pen(rgb):
    """True where there is coloured ink: the instructor's mark.

    Saturated and not paper-white. Opened once, so the single-pixel
    colour fringing JPEG leaves around black text does not read as a
    mark -- without it a page of dense printing scores a percent or
    two of "pen" that nobody wrote.
    """
    import numpy

    s, v = rgb.convert("HSV").split()[1:]
    m = ((numpy.asarray(s, dtype=numpy.uint8) > SAT_MIN)
         & (numpy.asarray(v, dtype=numpy.uint8) < VALUE_MAX))
    e = m.copy()
    e[1:, :] &= m[:-1, :]
    e[:-1, :] &= m[1:, :]
    e[:, 1:] &= m[:, :-1]
    e[:, :-1] &= m[:, 1:]
    d = e.copy()
    d[1:, :] |= e[:-1, :]
    d[:-1, :] |= e[1:, :]
    d[:, 1:] |= e[:, :-1]
    d[:, :-1] |= e[:, 1:]
    return d


def _integral(mask):
    """Summed-area table, so any rectangle's total is four lookups."""
    import numpy

    return numpy.pad(mask.astype(numpy.int32).cumsum(0).cumsum(1),
                     ((1, 0), (1, 0)))


def _rect_sums(table, wide, tall):
    """Every rectangle's total, as an array over its top-left corners."""
    return (table[tall:, wide:] - table[:-tall, wide:]
            - table[tall:, :-wide] + table[:-tall, :-wide])


#: How thick the printed rule is taken to be, in pixels, when
#: scoring a candidate rectangle's edge. Two is generous at 200dpi
#: and tolerant of the blur a photocopy adds.
RULE_PX = 2

#: A candidate has to have this much of its edge drawn, and this
#: little of its middle, to be the box. The first number is what
#: survives a check drawn across one side; the second is what keeps
#: a solid blot from matching.
#:
#: 0.50 sits in a gap. Across the 62 pages of 2026-10-26 the worst
#: real box scored 0.520 and nothing at all scored between 0.50 and
#: 0.52, so the cut is not balanced on the edge of the evidence. It
#: was 0.55, which lost seven boxes -- two with a check drawn
#: through one side, the rest simply printed faint.
EDGE_HIT = 0.50
MIDDLE_CLEAR = 0.30


def find_box(crop, hint=None):
    """Where the printed rectangle is, or None. See `scored_box`."""
    found = scored_box(crop, hint)
    return found[0] if found else None


def scored_box(crop, hint=None):
    """Where the printed rectangle actually is, or None.

    **Found, not assumed.** The crop is placed from the position
    `main.pages` recorded, and that is good enough to put the box
    somewhere in the picture and not good enough to measure from:
    `\\cipmark{box}` wraps trailing space, so the recorded mark is
    about a third wider than the drawn rectangle, and what is left
    of the scan's skew after straightening moves it tens of pixels
    between pages.

    Matched on the rule mask -- dark **and unsaturated** -- so a
    coloured check drawn across the outline is not part of the
    shape being matched, and a box with a tick through it still
    matches on its other three sides.
    """
    import numpy

    rgb = crop if crop.mode == "RGB" else crop.convert("RGB")
    sat, val = rgb.convert("HSV").split()[1:]
    rule = ((numpy.asarray(val, dtype=numpy.uint8) < RULE_DARK)
            & (numpy.asarray(sat, dtype=numpy.uint8) < RULE_SAT))
    height, width = rule.shape
    table = _integral(rule)

    hx0, hy0, hx1, hy1 = hint or _window(rule.shape)

    guess = max(12, min(hx1 - hx0, hy1 - hy0))

    best = None
    for side in range(max(12, int(guess * 0.55)),
                      min(min(height, width), int(guess * 1.25)) + 1):
        if side + 2 * RULE_PX >= min(height, width):
            break
        inner = side - 2 * RULE_PX
        outer_sum = _rect_sums(table, side, side)
        inner_sum = _rect_sums(table, inner, inner)
        # Line up the inner rectangle with the outer one's middle.
        inner_sum = inner_sum[RULE_PX:RULE_PX + outer_sum.shape[0],
                              RULE_PX:RULE_PX + outer_sum.shape[1]]
        if inner_sum.shape != outer_sum.shape:
            continue
        edge = (outer_sum - inner_sum) / max(1, side * side - inner * inner)
        middle = inner_sum / max(1, inner * inner)
        score = numpy.where((edge >= EDGE_HIT) & (middle <= MIDDLE_CLEAR),
                            edge - middle, -1.0)
        y, x = numpy.unravel_index(int(score.argmax()), score.shape)
        if score[y, x] <= 0:
            continue
        # Nearest to where the index said, among equally good
        # matches: two boxes never share a crop, but a printed
        # letter can score respectably and the hint breaks the tie.
        away = abs(x + side / 2 - (hx0 + hx1) / 2) \
            + abs(y + side / 2 - (hy0 + hy1) / 2)
        value = float(score[y, x]) - away / 2000.0
        if best is None or value > best[0]:
            best = (value, int(x), int(y), side)
    if best is None:
        return None
    value, x, y, side = best
    # The score back out as well as the rectangle: how much of the
    # outline was actually there is the floor under every call made
    # from it, and a caller saying how sure it is needs to know.
    return (x, y, x + side, y + side), min(1.0, max(0.0, value))


def _window(shape, pad=None):
    """Roughly where the box sits inside a crop, in pixels.

    A hint for `find_box` and nothing more. It was the measurement
    once, and it was wrong twice over: it derives the box's size
    from the recorded mark, which is wider than the drawn
    rectangle, and `pad[1] + 1 + pad[3]` uses one box *width* as the
    box's height when the box is 0.766 of its width tall. The
    measured region was therefore both wider and taller than the
    box, clipped its printed outline, and called an empty box a
    tick.
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

    `inside` is the fraction of the found box's middle that is
    coloured pen, with its printed outline inset out of the count.
    `around` is the same for the space surrounding it -- a box's
    width to the left and above and below, two to the right, where
    the `?` goes.

    `sure` is how far the call is from being a different call,
    between 0 and 1 -- see `_confidence`. It is about the decision,
    not about the ink: a box inked twelve times over the threshold
    and one inked by a hair are both `ticked`, and only one of them
    should be believed without looking.

    `call` is one of:

        ticked   pen in the box
        beside   pen around it and none in it -- his `?`
        heavy    the box is covered; scribbled out, probably
        empty    no pen anywhere near
        nobox    no rectangle could be found to measure

    Unlike the darkness version this replaces, `beside` is claimed
    rather than hedged. A coloured mark next to the box is a thing
    somebody drew; the old reading could not distinguish one from a
    smudge because it could not distinguish ink from print at all.
    The instructor still sees every row, and he can still change it.
    """
    import numpy

    rgb = crop if crop.mode == "RGB" else crop.convert("RGB")
    # The padding has to reach `find_box`: it is what says roughly
    # where in the crop the box should be, and a caller that cut
    # the crop differently would otherwise be given a hint for a
    # crop it does not have.
    found = scored_box(rgb, hint=_window((rgb.height, rgb.width), pad))
    if found is None:
        return {"inside": 0.0, "around": 0.0, "call": "nobox",
                "box": None, "sure": 0.0}
    box, quality = found

    pen = _pen(rgb)
    x0, y0, x1, y1 = box
    wide, tall = x1 - x0, y1 - y0
    ix, iy = max(1, int(wide * INSET)), max(1, int(tall * INSET))
    inner = pen[y0 + iy:y1 - iy, x0 + ix:x1 - ix]
    area = max(1, inner.size)
    near = pen[max(0, y0 - tall):y1 + tall,
               max(0, x0 - wide):x1 + 2 * wide]

    inside = float(inner.sum()) / area
    around = (float(near.sum()) - float(inner.sum())) / area
    if inside >= HEAVY_INK:
        call = "heavy"
    elif inside >= INK_MIN:
        call = "ticked"
    elif INK_MIN <= around <= BESIDE_MAX:
        call = "beside"
    else:
        call = "empty"
    return {"inside": round(inside, 4), "around": round(around, 4),
            "call": call, "box": box,
            "sure": _confidence(call, inside, around, quality)}


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
    corners = _corners(ours)
    carry = placement(anchor, corners)
    if carry is None:
        return {}

    cuts = {}
    # The box first, and on the code's own estimate of the scale.
    #
    # The order matters and is the point. This crop is what the
    # reading is taken from, so it is cut exactly as it always was --
    # a correction derived from a box has no business moving the
    # picture that box is found in. What it does is pin the scale for
    # everything cut *after* it, which is where the error was doing
    # real damage: the name is three times further from the code than
    # the box, so it drifted three times as far.
    box_mark = entry.marks.get("box")
    if box_mark is not None:
        box_crop = cut_out(image, box_mark, anchor, carry, cut=BOX_CUT)
        if "box" in want:
            cuts["box"] = box_crop
        better = _pinned(anchor, corners, box_mark, carry, box_crop)
        if better is not None:
            carry = better

    for label in want:
        if label == "box":
            continue
        mark = entry.marks.get(label)
        if mark is not None:
            cuts[label] = cut_out(image, mark, anchor, carry,
                                  cut=PADS.get(label, BOX_CUT))
    return cuts


#: How far the box may disagree with the footer code before the
#: disagreement is read as a bad match rather than as a scale to fix:
#: a fraction of the distance between them, and radians of turn.
#:
#: 5% and 3 degrees are many times the error being corrected -- the
#: 2026-10-26 stack wanted 1.5% and 0.6 of a degree -- and still well
#: inside the range a genuine misread could sit in. Past either,
#: something other than placement is wrong: a sheet from a different
#: build, a crop with two rectangles in it, or a printed letter
#: matched as a box. Then the code's own estimate stands, because it
#: is at least wrong in a way that is understood.
PIN_SCALE_LIMIT = 0.05
PIN_TURN_LIMIT = 0.052


def _pinned(anchor, scan_corners, mark, carry, crop):
    """A transform pinned by the box that was found, or None.

    None whenever there is nothing better to say: no reference was
    measured off the printed page, no box could be found in this
    crop, or the two disagree by more than the limits above -- which
    is not a placement error but a sign that one of them is not the
    box.

    **Why one found point is enough.** A similarity has four numbers
    in it: two of shift, one of scale, one of turn. The footer code's
    centre fixes the shift, so two are left, and a single point
    somewhere else on the page carries exactly two numbers. So the
    box pins both, and it pins them over its own distance from the
    code -- 1300 pixels against the code's own 100-pixel diagonal.
    That ratio is the whole value of this: every error in reading
    those four corners was being multiplied by thirteen on its way
    across the page, and on the 2026-10-26 stack that showed up as
    1.5% of scale and 0.6 of a degree of turn, which between them
    moved the box 20 pixels and the name nearer 30.

    The code still supplies the shift, and that is on purpose. It is
    the one thing the code is *good* for: a centre averaged from four
    corners of a symbol read in place, with no long extrapolation in
    front of it.
    """
    import math

    if anchor.box_at is None:
        return None
    found = scored_box(crop)
    if found is None:
        return None
    (x0, y0, x1, y1), _ = found

    quad, _, page_rect = _frame(mark, anchor, carry, BOX_CUT)
    page_at, scan_at = _centre(anchor.corners), _centre(scan_corners)

    # Three vectors out from the footer code, all to the same corner
    # of the same box: where it is on the printed page, where this
    # crop found it on the scan, and where the code alone predicted
    # it would be. The first owes the scanner nothing.
    ux, uy = _away(_on_page(page_rect, *anchor.box_at), page_at)
    vx, vy = _away(_on_scan(quad, (x0 + x1) / 2 / crop.width,
                            (y0 + y1) / 2 / crop.height), scan_at)
    wx, wy = _away(_on_scan(quad, *anchor.box_at), scan_at)

    page_reach, said = math.hypot(ux, uy), math.hypot(wx, wy)
    if page_reach <= 0 or said <= 0:
        return None

    # Measured against what the code predicted rather than against 1
    # and 0: a sheet genuinely fed in crooked has a real turn in it,
    # and the only question here is whether this box agrees with the
    # code about roughly where the page is.
    if abs(math.hypot(vx, vy) / said - 1.0) > PIN_SCALE_LIMIT:
        return None
    off = math.atan2(vy, vx) - math.atan2(wy, wx)
    if abs((off + math.pi) % (2 * math.pi) - math.pi) > PIN_TURN_LIMIT:
        return None

    turn = math.atan2(vy, vx) - math.atan2(uy, ux)
    return _similarity(page_at, scan_at, math.hypot(vx, vy) / page_reach,
                       (turn + math.pi) % (2 * math.pi) - math.pi)


def _away(point, origin):
    return (point[0] - origin[0], point[1] - origin[1])


#: How far past the threshold a reading has to be before the call
#: is as safe as it is going to get. Four times: real ticks on the
#: 2026-10-26 stack measured 0.08 to 0.21 against a 0.012
#: threshold, so anything genuinely drawn clears this easily and
#: anything near the line does not.
SURE_AT = 4.0

#: What a *well* matched box scores, not what a perfect one would.
#:
#: `\roundbox` has rounded corners and a square template cannot
#: cover them, so no real box reaches 1.0. Over the 62 pages of
#: 2026-10-26 the best scored 0.718 and the median 0.592. Scaling
#: against 1.0 marked every page down against a number no box can
#: reach, and put the whole stack in a band three tenths wide.
EDGE_GOOD = 0.70

#: What `beside` is allowed to reach however cleanly it measures.
#: It means "a mark next to an empty box", and whether that is a
#: question mark, a correction, or the edge of somebody's working
#: is not a thing the pixels settle.
BESIDE_CEILING = 0.70


def _confidence(call, inside, around, quality):
    """How sure the call is, 0 to 1.

    Two parts. How far the measurement sits from the boundary it
    was decided on, and how well the box was found -- every call
    rests on having the right rectangle, so a rectangle that only
    just matched drags down whatever was concluded from it.
    """
    def past(value):
        """0 at the threshold, 1 at `SURE_AT` times it."""
        if value <= INK_MIN:
            return 0.0
        return min(1.0, (value / INK_MIN - 1.0) / (SURE_AT - 1.0))

    if call == "ticked":
        margin = past(inside)
    elif call == "empty":
        # What `empty` claims is that the *box* has nothing in it,
        # so `inside` is what decides how sure that is. Ink outside
        # it is a different question and is dealt with below.
        margin = 1.0 - min(1.0, inside / INK_MIN)
        if around > BESIDE_MAX:
            # There is a mark out there and the reading decided it
            # was too big to be a question mark -- which rests on
            # `BESIDE_MAX`, the one threshold here fitted to a
            # single stack. Worth saying out loud, and this is the
            # number whose job is to say it.
            margin *= 0.55
    elif call == "beside":
        margin = min(BESIDE_CEILING, past(around))
    elif call == "heavy":
        # A box buried in ink is unmistakable as a *measurement*
        # and says nothing about what was meant by it.
        margin = 0.35
    else:
        return 0.0

    # The found box's own score, against what a good box really
    # scores rather than against a perfect one. A bare match costs
    # about a third; a clean one costs nothing.
    good = min(1.0, max(0.0, (quality - EDGE_HIT)
                        / max(1e-6, EDGE_GOOD - EDGE_HIT)))
    return round(margin * (0.70 + 0.30 * good), 3)


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
