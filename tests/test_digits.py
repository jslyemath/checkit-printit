r"""Reading the id a student wrote into the grid.

Three kinds of test, because there are three things that can be wrong
and they fail differently.

The *presentation* of a cell is geometry, and it is tested on drawn
shapes: a recogniser trained on MNIST has only ever seen digits one
particular way, and handing it anything else fails quietly rather than
loudly.

The *choice* of a student is arithmetic over probabilities, and it is
tested with the recogniser stubbed out. What matters there is which
answers are refused, and a test that had to produce real uncertainty
in order to check what happens to it would be testing two things.

And the recogniser itself is tested on the thirty-six digits the
instructor actually wrote, which are the only handwriting any of this
has been judged against. They came off four pretend students.
"""

import pathlib

import pytest

from checkit_printit import digits

DATA = pathlib.Path(__file__).parent / "data" / "real_digits.npz"


def cell(draw=None, size=(96, 114), paper=252, pen=40, rule=None):
    """A picture shaped like a cut-out cell, with something in it.

    `draw(canvas, width, height)` puts the ink there. `rule` adds a
    line along the very top and left edges, which is what a sliver of
    the printed grid looks like when the resampler has smeared it
    across the cut.
    """
    from PIL import Image, ImageDraw

    image = Image.new("L", size, paper)
    canvas = ImageDraw.Draw(image)
    if rule is not None:
        canvas.rectangle((0, 0, size[0], 1), fill=rule)
        canvas.rectangle((0, 0, 1, size[1]), fill=rule)
    if draw:
        draw(canvas, *size, pen)
    return image


def blob(canvas, wide, high, pen):
    """A lump in the middle: not a digit, but ink to find."""
    canvas.ellipse((wide * 0.35, high * 0.35, wide * 0.65, high * 0.65),
                   fill=pen)


def tall_stroke(canvas, wide, high, pen):
    """Something much taller than it is wide, like a 1."""
    canvas.rectangle((wide * 0.45, high * 0.15, wide * 0.55, high * 0.85),
                     fill=pen)


def top_heavy(canvas, wide, high, pen):
    """Weight at the top and a thin tail below, like a 7.

    Lopsided on purpose. A shape with its ink evenly spread has its
    centre of mass in the middle of its own bounding box, so it cannot
    tell the two apart -- which is exactly how the first version of
    `test_it_is_centred_on_the_weight_not_the_box` came to pass while
    the code centred on the box.
    """
    canvas.rectangle((wide * 0.25, high * 0.18, wide * 0.75, high * 0.34),
                     fill=pen)
    canvas.rectangle((wide * 0.47, high * 0.34, wide * 0.53, high * 0.82),
                     fill=pen)


class TestPresentingACell:
    """MNIST's own recipe: 20x20 inside 28x28, centred on the weight.

    Not ours to choose -- it is what the training data looks like, and
    a cell handed over as it comes off the page is a different shape
    from anything the recogniser has seen.
    """

    def test_the_picture_is_the_size_the_training_data_was(self):
        out = digits.to_mnist(cell(blob))
        assert out.shape == (digits.FIELD, digits.FIELD)
        assert out.min() >= 0 and out.max() <= 1

    def test_an_empty_cell_gives_nothing(self):
        """A student who wrote eight digits, not a digit to guess at."""
        assert digits.to_mnist(cell()) is None

    def test_the_ink_fits_the_box_mnist_scales_to(self):
        out = digits.to_mnist(cell(blob))
        rows, cols = (out > 0.1).nonzero()
        assert rows.max() - rows.min() + 1 <= digits.FIT + 1
        assert cols.max() - cols.min() + 1 <= digits.FIT + 1

    def test_a_tall_mark_keeps_its_shape(self):
        """Scaled to fit, with the aspect ratio kept -- so something
        four times taller than it is wide stays that way rather than
        being stretched into a square."""
        out = digits.to_mnist(cell(tall_stroke))
        rows, cols = (out > 0.1).nonzero()
        tall = rows.max() - rows.min() + 1
        wide = cols.max() - cols.min() + 1
        assert tall > 2 * wide, (tall, wide)

    def test_it_is_centred_on_the_weight_not_the_box(self):
        """A 7 carries its ink high and a 6 low, and MNIST was built
        that way round -- on the centre of mass, not the middle of the
        bounding box. So the shape here is deliberately lopsided: an
        even one has its weight in the middle of its own box and
        cannot tell the two apart."""
        import numpy

        out = digits.to_mnist(cell(top_heavy))
        total = out.sum()
        cy = (out.sum(axis=1) @ numpy.arange(digits.FIELD)) / total
        cx = (out.sum(axis=0) @ numpy.arange(digits.FIELD)) / total
        # Within a pixel and a half, not within half a pixel. A 20-tall
        # patch in a 28 field can only be offset by 0 to 8, so a shape
        # whose weight sits near the top of its own box cannot quite
        # reach the middle -- it runs out of field first. MNIST has the
        # same ceiling and keeps the digit inside in the same way. A
        # tolerance that ignored it would be asserting something the
        # arithmetic cannot deliver.
        assert abs(cy - digits.FIELD / 2) < 1.5, cy
        assert abs(cx - digits.FIELD / 2) < 1.5, cx
        # And the ink is *not* evenly spread, or the test above is
        # back to proving nothing.
        half = out[:digits.FIELD // 2].sum() / total
        assert half > 0.6, f"the fixture is not lopsided enough ({half:.2f})"

    def test_a_sliver_of_printed_rule_is_ignored(self):
        """The cells are cut inside the rules, but the crop is
        resampled up from 200dpi and that smears a rule barely a pixel
        wide across several of the output's. A sliver left in a corner
        would move the bounding box into that corner, and the digit
        would come out of the far side of the picture -- which breaks
        the centring far worse than losing a little of a digit does.

        Drawn at 150, well below the ink level. On the first real
        stack the rules came back between 205 and 235 against paper at
        250 to 255, which does not reach the ink level at all, so the
        trim was doing nothing there. It is insurance against a
        scanner that runs darker than his -- which is the one thing
        about this that cannot be tested with his scanner.
        """
        import numpy

        clean = digits.to_mnist(cell(blob))
        edged = digits.to_mnist(cell(blob, rule=150))
        assert edged is not None
        assert float(numpy.abs(clean - edged).max()) < 0.2

    def test_a_pale_pencil_mark_is_still_found(self):
        """Three of the first four real pages were in pencil and one
        in a pink gel pen. Ink is measured against each cell's own
        paper for that reason, not against a fixed grey."""
        out = digits.to_mnist(cell(blob, pen=170))
        assert out is not None and out.max() > 0.5


def fake_reader(monkeypatch, wanted, certainty=0.9, blank=()):
    """Stub the recogniser: it is certain of `wanted`, digit by digit.

    Returns the pictures to hand to `pick`. `blank` names positions
    that hold no ink at all, which come back as None exactly as
    `to_mnist` returns None for an empty cell.

    Stubbed because what these tests are about is which answers get
    refused, and producing genuine uncertainty in order to check what
    happens to it would be testing the recogniser at the same time.
    """
    import numpy

    def probabilities(pictures):
        p = numpy.full((len(pictures), 10), (1 - certainty) / 9)
        for i, d in enumerate(wanted):
            p[i, int(d)] = certainty
        return p

    monkeypatch.setattr(digits, "probabilities", probabilities)
    return [None if i in blank else numpy.zeros((28, 28))
            for i in range(len(wanted))]


class TestChoosingAStudent:
    def test_the_candidate_the_cells_say_is_picked(self, monkeypatch):
        cells = fake_reader(monkeypatch, "800123456")
        got = digits.pick(cells, ["800123456", "800999999", "800123999"])
        assert got is not None and got[0] == "800123456"

    def test_one_misread_digit_does_not_lose_the_right_student(
            self, monkeypatch):
        """Which is the whole reason the candidates are scored instead
        of the digits being read and looked up. The ids in one course
        differ in at least two places, so a wrong digit costs the right
        student a little and the wrong ones a lot."""
        cells = fake_reader(monkeypatch, "800123456")
        # The pool holds the true id and one that agrees with the
        # reading in eight places out of nine.
        got = digits.pick(cells, ["800123456", "800123457"])
        assert got[0] == "800123456"

    def test_a_candidate_of_the_wrong_length_is_not_considered(
            self, monkeypatch):
        cells = fake_reader(monkeypatch, "800123456")
        assert digits.pick(cells, ["12345", "800123456"])[0] == "800123456"
        assert digits.pick(cells, ["12345"]) is None

    def test_an_empty_cell_stops_the_whole_reading(self, monkeypatch):
        """Eight digits and a gap is not an id with a digit to be
        guessed at. The row goes to him to match by hand."""
        cells = fake_reader(monkeypatch, "800123456", blank=(4,))
        assert digits.pick(cells, ["800123456"]) is None
        assert digits.rank(cells, ["800123456"]) is None

    def test_a_best_candidate_that_does_not_fit_is_refused(
            self, monkeypatch):
        """The case that matters: somebody wrote on a spare who is not
        on this list at all. The least bad candidate still beats the
        next one easily -- the margin between them says nothing --- so
        the test is the winner's own score."""
        cells = fake_reader(monkeypatch, "800123456")
        assert digits.pick(cells, ["811987654"]) is None

    def test_a_shaky_but_consistent_reading_is_still_believed(
            self, monkeypatch):
        """Three-quarters sure of every digit is a messy page, not an
        unreadable one, and nine of those multiply out to about -2.6.
        The floor is at -4.5 so that a page like that still lands."""
        cells = fake_reader(monkeypatch, "800123456", certainty=0.75)
        assert digits.pick(cells, ["800123456"])[0] == "800123456"

    def test_one_bad_cell_cannot_outweigh_two_wrong_digits(
            self, monkeypatch):
        """What the floor under each digit's probability is for.

        It is not that a cell can be *unlikely* -- a cell where every
        digit is equally hopeless costs every candidate the same and
        decides nothing. It is that the recogniser can be confidently
        **wrong**, and an unfloored probability has no bottom: a cell
        that scores the digit actually written at a billionth imposes a
        penalty of -20.7 on the one candidate who is right, which is
        more than being wrong in two other places costs anybody else.
        One smudge then picks the student.

        The floor caps what any single cell can cost at -9.2, so eight
        cells that agree still decide. Here the smudged cell reads the
        1 that was written as a billionth and prefers a 9; the rival
        differs there and in one further place.
        """
        import numpy

        wrote = "800123456"
        other = "800923450"          # differs at the smudge and at the end

        def probabilities(pictures):
            p = numpy.full((9, 10), 1e-12)
            for i, d in enumerate(wrote):
                p[i, int(d)] = 1 - 9e-12
            p[3] = 1e-30
            p[3, 1] = 1e-9           # what was written, read as hopeless
            p[3, 9] = 1e-3           # a digit nobody wrote, read as better
            p[8, 0] = 1e-5           # and the rival's other digit, unlikely
            return p

        monkeypatch.setattr(digits, "probabilities", probabilities)
        best = digits.rank([numpy.zeros((28, 28))] * 9, [wrote, other])
        assert best[0][1] == wrote, (
            f"one bad cell decided it on its own: {best}")


@pytest.mark.skipif(not DATA.exists(), reason="no real-digit fixture")
class TestTheDigitsHeActuallyWrote:
    """Thirty-six digits off four scanned pages: three in pencil and
    one in a pink gel pen, from four pretend students whose ids differ
    by a single digit in two different places on purpose.

    This is the only handwriting any of this has been judged against.
    Thirty-six is not many -- at a true accuracy of 95% a clean sweep
    would still happen one time in six -- so a failure here means
    something is broken, while a pass is encouragement and not proof.
    """

    @staticmethod
    def fixture():
        import numpy

        with numpy.load(DATA, allow_pickle=False) as data:
            return (data["pictures"].astype(float) / 255.0,
                    data["labels"], data["pages"],
                    [str(s) for s in data["ids"]],
                    [str(s) for s in data["pool"]])

    def test_every_digit_is_read_correctly(self):
        pictures, labels, _, _, _ = self.fixture()
        said = digits.probabilities(list(pictures)).argmax(axis=1)
        wrong = [(i, int(labels[i]), int(said[i]))
                 for i in range(len(labels)) if said[i] != labels[i]]
        assert not wrong, f"misread: {wrong}"

    def test_each_page_finds_its_own_student(self):
        pictures, _, pages, ids, pool = self.fixture()
        for n, want in zip(sorted(set(pages)), ids):
            cells = [p for p, page in zip(pictures, pages) if page == n]
            got = digits.pick(cells, pool)
            assert got is not None, f"page {n} was not read at all"
            assert got[0] == want, (n, got[0], want)

    def test_a_writer_who_is_not_on_the_list_is_refused(self):
        """The dangerous failure. Somebody writes on a spare and is
        not among the candidates, and the best-scoring candidate is
        then a different student -- who must not be named.

        Measured on these pages: with the writer in the pool the best
        score came out between -0.14 and -1.23, and with that student
        taken out, between -8.59 and -10.20.
        """
        pictures, _, pages, ids, pool = self.fixture()
        for n, mine in zip(sorted(set(pages)), ids):
            cells = [p for p, page in zip(pictures, pages) if page == n]
            others = [s for s in pool if s != mine]
            assert digits.pick(cells, others) is None, (
                f"page {n} was given to somebody else")

    def test_the_margin_would_not_have_caught_that(self):
        """Why the score and not the margin, written down as a test so
        that nobody swaps one for the other.

        The usual way to say how sure a classifier is, is how far the
        winner is ahead of the runner-up. Here it is no use: with the
        true student removed the winner is still far ahead, because
        the *least bad* candidate beats the next one just as easily.
        The margin measures how spread out the pool is.
        """
        pictures, _, pages, ids, pool = self.fixture()
        wide = 0
        for n, mine in zip(sorted(set(pages)), ids):
            cells = [p for p, page in zip(pictures, pages) if page == n]
            ranked = digits.rank(cells, [s for s in pool if s != mine])
            if len(ranked) > 1 and ranked[0][0] - ranked[1][0] > 5:
                wide += 1
        assert wide, ("the margin was narrow on every page with the writer "
                      "removed, so this fixture no longer shows why the "
                      "score is the test and the margin is not")
