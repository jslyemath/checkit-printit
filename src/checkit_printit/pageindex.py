"""What a page says about itself, and what that resolves to.

A scanned page carries one mark a machine can read: the footer code,
which says `C1-<runseed>-<page>` and nothing else. The case for keeping
it that short is in `printit.sty` -- run plus page is already a unique
key, and every extra field costs modules, which costs millimetres.

What that argument assumed, and what was not true until 2026-10-24, is
that the key had a table to key into. It did not. `manifest.toml`
records which (skill, version, seed) were *drawn*, with no students and
no page numbers; the print record's `printed` table has a row per
student per paper, also with no page. So the code resolved to a run and
a page number and then stopped.

The table is now written by the document itself, as `main.pages` beside
the PDF, because the document is the only party that knows: a skill may
run to two sheets, so page numbers do not exist until TeX has broken
the pages.

    run*4242
    1*student*806625853*W5*803*1
    mark*1*box*34926110*1819429*1769472*1310720*131072
    2*key**N2*840*1

One line per page that carries a footer. Padding pages have none -- they
are set under `\\pagestyle{empty}` -- so they write nothing, and the
gaps in the sequence are the blanks. Nothing detects a blank; the
absence is the detection.
"""

import dataclasses
import os
import re

#: Written by `printit.sty` next to `main.pdf`. `\jobname` is `main`.
FILENAME = "main.pages"

#: The footer code's payload. `C1` is the format tag: a later change of
#: fields has to be distinguishable from this one, because Scans will
#: meet codes printed by a theme that no longer exists.
PAYLOAD = re.compile(r"^C1-(\d+)-(\d+)$")

#: What `\setkind` can say. A key must never be recorded as an attempt,
#: and a spare belongs to nobody until somebody writes an id on it.
KINDS = ("student", "spare", "key")


class PageIndexError(Exception):
    pass


#: TeX points per inch. Not 72 -- that is the PostScript point a PDF's
#: page box is measured in, and mixing the two is a 0.4% error, which
#: at the bottom of a page is about a pixel and a half.
TEX_PT_PER_INCH = 72.27

#: Scaled points per TeX point.
SP_PER_PT = 65536


#: What `\\cipmark` can label. Not an exhaustive list of things on the
#: page -- just the ones Scans has to cut out and look at.
MARKS = ("box", "id", "name")


@dataclasses.dataclass(frozen=True)
class Mark:
    """Where something sits on the page, in the page's own coordinates.

    Scaled points, measured up from the bottom-left corner, written by
    `\\pdfsavepos` at the moment the page was shipped. Asked of the
    typesetter rather than measured off a render or computed from the
    header and footer geometry -- the first breaks silently whenever
    either is adjusted, and the second is the same constant with a
    measuring step in front of it.
    """

    x: int
    y: int
    width: int
    height: int
    depth: int

    def rect(self, dpi, page_height_pt):
        """(left, top, right, bottom) in pixels of a render at `dpi`.

        `page_height_pt` is the PDF's own page height, in PostScript
        points, because the image counts down from the top and
        `\\pdfsavepos` counts up from the bottom.
        """
        per_sp = dpi / (SP_PER_PT * TEX_PT_PER_INCH)
        tall = page_height_pt * dpi / 72.0
        return (self.x * per_sp,
                tall - (self.y + self.height) * per_sp,
                (self.x + self.width) * per_sp,
                tall - (self.y - self.depth) * per_sp)


@dataclasses.dataclass(frozen=True)
class Page:
    """One printed side, and what was on it."""

    page: int
    kind: str
    sid: str
    slug: str
    vseed: str
    sheet: int
    #: {label: Mark}. A continuation sheet has no `box`: the
    #: continuation page style omits it deliberately, because one
    #: skill is ticked once. "No box on this page" therefore means
    #: "nothing to grade here", which is a fact Scans wants rather
    #: than a gap in the record.
    marks: dict = dataclasses.field(default_factory=dict)

    @property
    def box(self):
        """The grading box, or None on a sheet that carries none."""
        return self.marks.get("box")

    @property
    def gradable(self):
        """A key is not an attempt by anybody, however it was marked."""
        return self.kind != "key"

    @property
    def owned(self):
        """False for a spare, and for any paper from a blank-name run.

        Both print an empty id grid for somebody to write in, so the
        owner is on the paper in handwriting or not at all.
        """
        return bool(self.sid)


@dataclasses.dataclass(frozen=True)
class Index:
    run_seed: int
    pages: dict           #: {page number: Page}

    def get(self, page):
        return self.pages.get(int(page))

    def blanks(self, total=None):
        """Page numbers the document skipped: the padding sheets.

        Derived rather than recorded, so it cannot disagree with the
        index it is derived from.

        `total` is the document's page count, which the index does not
        know and cannot work out. The last thing in a run is a
        `\\preparefornextstudent`, so the final sheet is very often
        padding -- and without a total it sits past the last indexed
        page and goes unreported. The first version of this was a
        property with no total, and said a seven-page index over an
        eight-page PDF had one blank in it when it had two.
        """
        end = max(self.pages) if self.pages else 0
        if total is not None:
            end = max(end, int(total))
        return [n for n in range(1, end + 1) if n not in self.pages]


def parse(text):
    """Read the index out of the file's text.

    Separate from `load` so a malformed line can be tested without a
    folder, and because the error messages are about content rather
    than about where it came from.
    """
    run_seed, pages, marks = None, {}, {}
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        fields = line.split("*")
        if fields[0] == "mark":
            # Written by a *deferred* write, so it arrives after that
            # page's own line and is collected separately rather than
            # assumed to be adjacent to it.
            # fields[2] is the label, so the numbers begin at 3.
            if (len(fields) != 8 or not fields[1].isdigit()
                    or not all(f.lstrip("-").isdigit() for f in fields[3:])):
                raise PageIndexError(
                    f"line {number} is a mark this reader does not "
                    f"understand: {line!r}")
            page, label = int(fields[1]), fields[2]
            if label not in MARKS:
                # Loud, for the same reason an unknown kind is: this
                # reader is older than the theme that wrote the file,
                # and quietly dropping a mark would mean cropping
                # nothing where something was recorded.
                raise PageIndexError(
                    f"line {number} records a {label!r} mark, which this "
                    f"version does not know. Known: {', '.join(MARKS)}.")
            if label in marks.setdefault(page, {}):
                raise PageIndexError(
                    f"line {number} is a second {label!r} on page {page}. "
                    f"Each is drawn once, so two means this reader would "
                    f"crop the wrong one.")
            marks[page][label] = Mark(*(int(f) for f in fields[3:]))
            continue
        if fields[0] == "run":
            if len(fields) != 2 or not fields[1].isdigit():
                raise PageIndexError(
                    f"line {number} is a run header this reader does not "
                    f"understand: {line!r}")
            run_seed = int(fields[1])
            continue
        if len(fields) != 6:
            raise PageIndexError(
                f"line {number} has {len(fields)} fields, not 6: {line!r}")
        page, kind, sid, slug, vseed, sheet = fields
        if not page.isdigit():
            raise PageIndexError(
                f"line {number} does not start with a page number: {line!r}")
        if kind not in KINDS:
            # Loud rather than tolerant: an unknown kind is a theme this
            # reader is older than, and guessing "student" would record
            # attempts against papers nobody sat.
            raise PageIndexError(
                f"line {number} is a {kind!r} page, which this version does "
                f"not know how to grade. Known kinds: {', '.join(KINDS)}.")
        if int(page) in pages:
            # One footer per page is fancyhdr's doing, not ours: the
            # mark sits in [LO] and [RE] and exactly one fires. A
            # repeat means that stopped being true, and storing it
            # into a dict would hide it -- the second line would
            # simply overwrite the first and the file would look fine.
            raise PageIndexError(
                f"line {number} is a second entry for page {page}. One page "
                f"carries one footer, so this index was not written the way "
                f"it is read.")
        pages[int(page)] = Page(page=int(page), kind=kind, sid=sid, slug=slug,
                                vseed=vseed, sheet=int(sheet) if sheet else 0)

    if run_seed is None:
        raise PageIndexError(
            "no run header, so these pages cannot be matched to the run "
            "their codes name.")

    orphans = sorted(set(marks) - set(pages))
    if orphans:
        # Marks on a page with no entry mean the two writes disagree
        # about what a page is, and cropping them would read something
        # belonging to nobody.
        raise PageIndexError(
            f"pages {orphans} carry marks and have no entry of their own.")
    pages = {n: dataclasses.replace(p, marks=marks.get(n, {}))
             for n, p in pages.items()}
    return Index(run_seed=run_seed, pages=pages)


def load(folder):
    """Read a run folder's page index, or say why there is none."""
    path = folder
    if os.path.isdir(path):
        path = os.path.join(path, FILENAME)
    if not os.path.isfile(path):
        raise PageIndexError(
            f"{path} does not exist, so the codes on these papers cannot be "
            f"resolved to students. A run only has one if the bank's "
            f"printit.sty was recent enough to write it -- "
            f"`checkit-printit install --force <bank>` updates it, and the "
            f"run has to be built again afterwards.")
    with open(path, encoding="utf-8") as f:
        return parse(f.read())


def read_payload(text):
    """`C1-4242-17` -> (4242, 17). None for anything else.

    Anything else is the ordinary case, not an error: a scanned page may
    carry a library barcode, a watermark, or a code from some other
    system entirely.
    """
    match = PAYLOAD.match(text.strip())
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))
