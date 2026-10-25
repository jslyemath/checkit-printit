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
        """`{run: [pages]}` printed in a run and not in this stack.

        `index_for(run_no)` gives that run's `pageindex.Index`. Pages
        the index does not list are padding and are not expected back.

        The question nobody asks until it is too late. A paper that
        never came back is a student who was absent, or a sheet that
        stuck to another one in the feeder, and those want different
        responses -- but both start here.
        """
        arrived = {(s.run_no, s.page) for s in self.placed}
        out = {}
        for run_no in self.runs:
            index = index_for(run_no)
            if index is None:
                continue
            gone = [page for page in sorted(index.pages)
                    if (run_no, page) not in arrived]
            if gone:
                out[run_no] = gone
        return out


def _dark_fraction(image):
    """How much of a page has ink on it, roughly."""
    import numpy
    grey = numpy.asarray(image.convert("L"), dtype=numpy.uint8)
    return float((grey < 128).mean())


def read_page(image, resolve):
    """Place one rendered page. `resolve(run_no)` gives its Index."""
    import zxingcpp

    found = [c.text for c in zxingcpp.read_barcodes(image)]
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
    return {"status": "placed", "run_no": run_no, "page": page,
            "entry": entry, "code": f"C1-{run_no}-{page}"}


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


def read_pdfs(paths, record_path, dpi=DPI, on_page=None):
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
                sheets.append(Sheet(source=path, at=n,
                                    **read_page(image, resolve)))
                done += 1
                if on_page:
                    on_page(done, total)
        return Batch(sheets=sheets)
    finally:
        for _, doc in documents:
            doc.close()
