"""Make a course, a run, and a stack of scans to read back.

Scans cannot be worked on without something to scan, and the thing
to scan has to be wrong in the ways a real stack is wrong: shuffled,
split across files, a blank in it, a page read twice, and a paper
that never came back. A tidy stack would let a broken placing look
correct.

    ./.venv/Scripts/python.exe tools/demo_scans.py
    ./.venv/Scripts/python.exe tools/demo_scans.py --home ~/scratch

By default it builds inside the real print-it home, under a course
called "Scan Demo", and says how to remove it. `--home` puts the
whole thing somewhere else, which is what a test should do -- four
junk rows went into the instructor's live record from builds that
did not.

The students are invented. The stack ends up on screen.
"""

import argparse
import os
import pathlib
import random
import shutil
import sys

TOOLS = pathlib.Path(__file__).resolve().parent
REPO = TOOLS.parent
NAME = "Scan Demo"
PEOPLE = [("Ada Lovelace", "800000111", ["W5", "W6"]),
          ("Bo Peep", "800000222", ["W5"]),
          ("Cyrus Vance", "800000333", ["W5", "W6"]),
          ("Dara Okafor", "800000444", ["W6"]),
          ("Elif Demir", "800000555", ["W5", "W6"])]


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--bank", default=str(REPO.parent /
                                              "mat-106-checkit"))
    parser.add_argument("--home", default=None,
                        help="a print-it home of its own, instead of the "
                             "real one")
    parser.add_argument("--dpi", type=int, default=150)
    parser.add_argument("--remove", action="store_true",
                        help="delete the course and stop")
    args = parser.parse_args()

    if args.home:
        os.environ["CHECKIT_PRINTIT_HOME"] = os.path.expanduser(args.home)
    sys.path.insert(0, str(REPO / "src"))
    from checkit_printit import course as course_mod
    from checkit_printit import pageindex, runner

    if args.remove:
        if course_mod.exists(NAME):
            shutil.rmtree(course_mod.path_for(NAME))
            print(f"removed {NAME}")
        else:
            print(f"no {NAME} to remove")
        return 0

    if not os.path.isdir(args.bank):
        sys.exit(f"no bank at {args.bank}")
    if course_mod.exists(NAME):
        shutil.rmtree(course_mod.path_for(NAME))
    course_mod.init(NAME, bank=args.bank)
    folder = pathlib.Path(course_mod.path_for(NAME))

    (folder / "roster.toml").write_text("".join(
        '[[student]]\n'
        f'name = "{name}"\nsection = "1"\nsid = "{sid}"\n'
        'skills = [' + ", ".join(f'"{s}"' for s in skills) + ']\n\n'
        for name, sid, skills in PEOPLE), encoding="utf-8")
    (folder / "seating.toml").write_text(
        "[[group]]\nseats = ["
        + ", ".join(f'"{n}"' for n, _, _ in PEOPLE) + "]\n", encoding="utf-8")

    job = folder / "publication.toml"
    job.write_text(
        "[course]\n"
        'name   = "DEMO 101"\n'
        'title  = "Checkpoint"\n'
        'date   = "2026-10-25"\n'
        f'folder = "{NAME}"\n'
        "\n[bank]\n"
        f"path = '{args.bank}'\n"
        "\n[roster]\npath = 'roster.toml'\n"
        "\n[print]\nkeys = true\nkey_copies = 1\n"
        # W5 has variants and the bank refuses to draw across them.
        "\n[variants]\nW5 = 'multiplication'\n", encoding="utf-8")

    out = folder / "run"
    result = runner.run(str(job), out=str(out), do_compile=True,
                        install_theme=False, seed=777)
    if not result.compiled:
        sys.exit("the run did not compile")
    index = pageindex.load(str(out))
    print(f"run {result.run_id}: {len(index.pages)} pages, "
          f"{result.recorded} papers recorded")

    stack = make_stack(out, index, folder / "scans", args.dpi)
    print(f"\n{len(stack)} files in {folder / 'scans'}")
    print("\nTo look at it:")
    print(f"  ./.venv/Scripts/python.exe -m checkit_printit gui "
          f"-c {NAME!r}")
    print("  then Scans, choose those files, Read them.")
    print("\nTo remove it:")
    print(f"  ./.venv/Scripts/python.exe tools/demo_scans.py --remove")
    return 0


#: What gets drawn in each student's box, by position in the page
#: order. Spelled out rather than randomised: a demo whose readings
#: change between runs cannot be used to check that a change to the
#: reader did what was intended.
MARKS = ["tick", "empty", "tick", "query", "tick", "empty", "tick",
         "tick", "empty", "query"]


def draw_mark(image, rect, kind, rng):
    """Put a pen mark in the grading box at `rect`.

    Grey 40 rather than black: a pen on a photocopy is not black,
    and a mark darker than the printed rule would make the reader's
    job easier than it is. A harness that is kinder than reality is
    a harness that passes when the real thing fails -- which is how
    a 7mm code once looked fine.
    """
    from PIL import ImageDraw

    draw = ImageDraw.Draw(image)
    left, top, right, bottom = rect
    w, h = right - left, bottom - top
    width = max(2, round(h * 0.07))
    if kind in ("tick", "query"):
        # A tick, roughly: down-right then up-right, with the ends
        # wandering the way a hand does.
        def jitter(v):
            return v + rng.uniform(-h * 0.04, h * 0.04)
        draw.line([(jitter(left + w * 0.22), jitter(top + h * 0.52)),
                   (jitter(left + w * 0.42), jitter(top + h * 0.78)),
                   (jitter(left + w * 0.80), jitter(top + h * 0.20))],
                  fill=40, width=width, joint="curve")
    if kind == "query":
        # Beside the box, not in it -- which is why the crop takes a
        # margin to the right, and why this is here to prove it does.
        size = round(h * 0.7)
        q = ImageDraw.Draw(image)
        x, y = right + w * 0.10, top + h * 0.15
        q.arc([x, y, x + size * 0.62, y + size * 0.55], 160, 20,
              fill=40, width=width)
        q.line([(x + size * 0.46, y + size * 0.40),
                (x + size * 0.34, y + size * 0.68)],
               fill=40, width=width)
        q.ellipse([x + size * 0.28, y + size * 0.80,
                   x + size * 0.40, y + size * 0.92], fill=40)


def make_stack(run, index, into, dpi):
    """Shuffled, split in two, one blank, one page twice, one short."""
    import numpy
    import pypdfium2 as pdfium
    from PIL import Image, ImageFilter

    rng = random.Random(11)
    pages = sorted(index.pages)
    # Hold one student's paper back, so "never came back" is not empty.
    held = next(n for n in reversed(pages)
                if index.get(n).kind == "student")
    pages.remove(held)
    rng.shuffle(pages)

    doc = pdfium.PdfDocument(str(run / "main.pdf"))
    # The order marks are handed out in is the page order, not the
    # shuffled order: which student got a tick should not depend on
    # how the copier happened to stack them.
    wanted = {}
    for i, n in enumerate(sorted(index.pages)):
        if index.get(n).kind == "student":
            wanted[n] = MARKS[len(wanted) % len(MARKS)]

    images, marked = [], []
    for n in pages:
        page = doc[n - 1]
        big = page.render(scale=dpi * 2 / 72).to_pil().convert("L")
        box = index.get(n).marks.get("box") if index.get(n) else None
        kind = wanted.get(n)
        if box is not None and kind:
            draw_mark(big, box.rect(dpi * 2, page.get_size()[1]), kind, rng)
            marked.append((n, kind))
        big = big.filter(ImageFilter.GaussianBlur(radius=2 * 0.55))
        big = big.rotate(rng.uniform(-1.2, 1.2), resample=Image.BICUBIC,
                         fillcolor=255)
        small = big.resize((big.width // 2, big.height // 2), Image.BOX)
        a = numpy.asarray(small, dtype=float)
        a = 35 + a * (243 - 35) / 255 + numpy.random.default_rng(
            rng.randrange(2 ** 31)).normal(0, 5, a.shape)
        images.append(Image.fromarray(
            numpy.clip(a, 0, 255).astype("uint8")).convert("L"))

    # One more copy of the first page, rendered the same way but with
    # nothing written in the box, for the double feed below.
    first = doc[pages[0] - 1]
    bare = first.render(scale=dpi * 2 / 72).to_pil().convert("L")
    bare = bare.filter(ImageFilter.GaussianBlur(radius=2 * 0.55))
    bare = bare.rotate(rng.uniform(-1.2, 1.2), resample=Image.BICUBIC,
                       fillcolor=255)
    bare = bare.resize((bare.width // 2, bare.height // 2), Image.BOX)
    a = numpy.asarray(bare, dtype=float)
    a = 35 + a * (243 - 35) / 255 + numpy.random.default_rng(
        7).normal(0, 5, a.shape)
    unmarked = [Image.fromarray(
        numpy.clip(a, 0, 255).astype("uint8")).convert("L")]
    doc.close()

    paper = numpy.full((images[0].height, images[0].width), 243.0)
    paper += numpy.random.default_rng(2).normal(0, 5, paper.shape)
    images.insert(2, Image.fromarray(
        numpy.clip(paper, 0, 255).astype("uint8")).convert("L"))
    # The double feed, and the one case worth building by hand: the
    # second pass of this sheet is taken *before* its mark, so the
    # two copies of one paper genuinely disagree. Every real stack
    # eventually has one, and it is the only thing that exercises
    # the grid's "scanned twice, and the two do not match".
    images.insert(5, unmarked[0] if unmarked else images[0])

    if into.exists():
        shutil.rmtree(into)
    into.mkdir(parents=True)
    half = len(images) // 2
    written = []
    for name, chunk in (("copier-1.pdf", images[:half]),
                        ("copier-2.pdf", images[half:])):
        chunk[0].save(into / name, save_all=True, append_images=chunk[1:],
                      resolution=float(dpi))
        written.append(name)
        print(f"  {name}: {len(chunk)} pages")
    print(f"  holding back page {held}, so one student's paper is missing")
    kinds = {}
    for _, kind in marked:
        kinds[kind] = kinds.get(kind, 0) + 1
    print(f"  marks drawn: "
          + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items())))
    print(f"  page {pages[0]} went through twice, and the second pass "
          f"has no mark on it")
    return written


if __name__ == "__main__":
    sys.exit(main())
