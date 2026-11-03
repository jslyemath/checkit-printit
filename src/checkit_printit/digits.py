r"""Reading the id a student wrote into the grid.

`scans.id_cells` hands over nine pictures, one per cell. This turns
them into a student.

**Not by reading nine digits and looking the number up.** The question
is not "what are these digits" but "which of the people who could have
written this wrote it" -- and that is a choice between the forty-odd
students on the roster, whose ids differ from each other in at least
two places and usually three or four. So every candidate is scored,
and one misread digit costs the right student a little while costing
the wrong ones a lot, because the wrong ones are wrong in several
places at once.

Three things were measured rather than assumed, on the first stack of
real handwriting:

* **The presentation matters more than the model.** A recogniser
  trained on MNIST has seen digits one particular way, and the way is
  documented. Hand it a cell as it comes off the page and nothing
  works; hand it the same cell in MNIST's own form and a one-layer
  net reads all thirty-six.

* **The margin between the best candidate and the next is useless
  here**, which is unfortunate because it is the usual way to say how
  sure a classifier is. Removing the true student from the pool left
  the margin at 9.2, 9.0 and 9.2 on three pages out of four -- just as
  wide as when the answer was present -- because the *least bad*
  remaining candidate still beats the one after it easily. The margin
  measures how spread out the pool is.

* **The winner's own score is the signal.** With the true student in
  the pool it came out between -0.15 and -0.99; with that student
  removed, between -8.59 and -10.20. A factor of about three
  thousand, with nothing in between.

The recogniser itself is one hidden layer, trained by
`tools/train_digits.py` and stored in `data/digits.npz`. Reading a
digit is then a matrix multiply, which is why this needs nothing
installed that reading a scan did not already need.
"""

import functools
import os

#: How much of each side of a cell to ignore before looking for ink.
#:
#: The cells are cut inside the printed rules, but a crop is resampled
#: up from 200dpi and that smears a rule barely a pixel wide across
#: four or five of the output's, so a sliver can sit at a cell's own
#: edge. The digit is found by the bounding box of the ink, and a
#: sliver of rule in a corner moves that box across the whole cell --
#: which wrecks the centring far more than clipping a millimetre off a
#: digit does.
TRIM = 0.07

#: Ink is this much darker than the cell's own paper, out of 255.
#:
#: Relative to each cell rather than absolute, because the pages came
#: back between 250 and 255 and a pencil is far lighter than a pen.
#: The paper level is the 85th percentile of the cell: a digit covers
#: well under half of one, so most of a cell *is* paper.
#:
#: Unlike the grading box, this is a darkness and not a colour. The
#: box is read on colour because the thing being looked for there is
#: the instructor's pen and everything else in the crop is grey. Here
#: there is nothing else in the crop: the cell is cut inside its own
#: rules, and whatever is in it was written by the student, in
#: whatever they had. One of the first four pages was in pink gel pen
#: and three were in pencil.
INK_BELOW = 55

#: MNIST's own numbers: the digit is scaled to fit a 20x20 box with
#: its aspect ratio kept, then placed in a 28x28 field. Not ours to
#: choose -- they are what the training data looks like.
FIT = 20
FIELD = 28

#: How likely the whole id has to be before it is believed, as a log.
#:
#: Set between two measured groups rather than at the edge of either:
#: a right answer scored -0.15 to -0.99, and a page whose writer was
#: not in the pool scored -8.59 to -10.20. A legitimately messy page
#: can reach -3 or so -- nine cells at three-quarters certain each is
#: -2.6 -- which is why this is not tighter.
#:
#: **One stack.** Four pages, one scanner, two pens. If a genuinely
#: hard id ever comes back unread, this is the number that did it.
ACCEPT = -4.5

#: Floor under any one digit's probability.
#:
#: What this guards against is not a cell being *unlikely* -- a cell
#: where every digit is equally hopeless costs every candidate the
#: same and decides nothing. It is that the recogniser can be
#: confidently **wrong**, and a softmax has no bottom. A smudge that
#: scores the digit actually written at a billionth imposes a penalty
#: of -20.7 on the one candidate who is right, which is more than
#: being wrong in two other places costs anybody else: one cell then
#: picks the student.
#:
#: The floor caps what any single cell can cost at log(1e-4), about
#: -9.2, so eight cells that agree still outweigh one that shouts.
#: It does not rescue a pair of ids differing in that one position
#: only -- nothing could, there being nothing else to go on -- and the
#: score floor is what catches those.
FLOOR = 1e-4


@functools.lru_cache(maxsize=1)
def _weights():
    """The trained numbers, loaded once.

    Lazily, because importing this module is not the same as using it
    and the file is 372KB.
    """
    import numpy

    path = os.path.join(os.path.dirname(__file__), "data", "digits.npz")
    if not os.path.isfile(path):
        raise FileNotFoundError(
            f"the digit recogniser is missing from the install ({path}). "
            "Rebuild it with tools/train_digits.py.")
    with numpy.load(path) as data:
        return tuple(data[k] for k in ("w1", "b1", "w2", "b2"))


def to_mnist(cell):
    """One cell as a 28x28 array, ink near 1 and paper at 0, or None.

    None when the cell holds no ink: an empty one is a student who
    wrote eight digits, not a digit to be guessed at.

    The order of the steps is MNIST's, and it is the whole of why this
    works: find the ink, cut to it, scale the longer side to 20 with
    the aspect ratio kept, and place it in a 28x28 field with its
    **centre of mass** -- not its bounding box -- at the middle. A 7
    carries its weight high and a 6 low, and the training data was
    built that way round.
    """
    import numpy
    from PIL import Image

    grey = numpy.asarray(cell.convert("L"), dtype=float)
    high, wide = grey.shape
    dy, dx = round(high * TRIM), round(wide * TRIM)
    inner = grey[dy:high - dy, dx:wide - dx]
    if inner.size == 0:
        return None

    ink = numpy.clip(numpy.percentile(inner, 85) - inner, 0, None)
    mask = ink > INK_BELOW
    if not mask.any():
        return None

    rows, cols = numpy.where(mask)
    # Cut from the ink itself, not from the mask. The threshold is for
    # finding the digit; keeping only what it caught would throw away
    # the soft edge of every stroke, which is most of what a pencil
    # line is.
    patch = ink[rows.min():rows.max() + 1, cols.min():cols.max() + 1]
    patch = patch / max(1.0, patch.max())

    tall, broad = patch.shape
    scale = FIT / max(tall, broad)
    small = numpy.clip(numpy.asarray(
        Image.fromarray((patch * 255).astype("uint8")).resize(
            (max(1, round(broad * scale)), max(1, round(tall * scale))),
            Image.LANCZOS), dtype=float) / 255.0, 0, 1)

    out = numpy.zeros((FIELD, FIELD))
    total = small.sum()
    if not total:
        return None
    cy = (small.sum(axis=1) @ numpy.arange(small.shape[0])) / total
    cx = (small.sum(axis=0) @ numpy.arange(small.shape[1])) / total
    oy = max(0, min(FIELD - small.shape[0], int(round(FIELD / 2 - cy))))
    ox = max(0, min(FIELD - small.shape[1], int(round(FIELD / 2 - cx))))
    out[oy:oy + small.shape[0], ox:ox + small.shape[1]] = small
    return out


def probabilities(pictures):
    """`(n, 10)`: how likely each digit is, for each 28x28 picture."""
    import numpy

    w1, b1, w2, b2 = _weights()
    x = numpy.stack([p.reshape(-1) for p in pictures])
    hidden = numpy.maximum(0.0, x @ w1 + b1)
    out = hidden @ w2 + b2
    out -= out.max(axis=1, keepdims=True)
    exp = numpy.exp(out)
    return exp / exp.sum(axis=1, keepdims=True)


def rank(pictures, candidates):
    """`[(score, sid)]`, best first, or None if a picture is missing.

    The score is how likely that candidate's id is, given the pictures:
    the recogniser's own probability for the digit that id has in each
    position, summed as logs because nine numbers under one multiplied
    together underflow.

    Takes prepared pictures rather than cells, because where they came
    from is not this function's business -- and because the only real
    handwriting there is to test against is kept as pictures. Keeping
    the cells would mean keeping a scan, a scanner and every constant
    in `scans` along with them, and a test that carried all of that
    would fail for reasons that had nothing to do with reading a digit.
    """
    import numpy

    if any(p is None for p in pictures):
        return None
    p = numpy.maximum(probabilities(pictures), FLOOR)
    scored = [(float(sum(numpy.log(p[i, int(d)])
                         for i, d in enumerate(sid))), sid)
              for sid in candidates
              if len(sid) == len(pictures) and sid.isdigit()]
    return sorted(scored, reverse=True)


def pick(pictures, candidates):
    """Whose paper this is: `(sid, score)`, or None.

    None whenever the answer is not clear, which covers a cell with no
    ink in it, a pool with nobody the right shape in it, and a best
    candidate that simply does not fit the writing well enough. All
    three mean the same thing to the instructor -- this row needs
    matching by hand -- and inventing a student for him to catch is
    worse than leaving the row blank, because the blank row is the one
    he looks at.
    """
    scored = rank(pictures, candidates)
    if not scored:
        return None
    score, sid = scored[0]
    if score < ACCEPT:
        return None
    return sid, score


def read_id(cells, candidates):
    """Whose paper this is, from the cells `scans.id_cells` cut."""
    return pick([to_mnist(cell) for cell in cells], candidates)
