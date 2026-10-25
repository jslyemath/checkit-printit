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
    images = []
    for n in pages:
        big = doc[n - 1].render(scale=dpi * 2 / 72).to_pil().convert("L")
        big = big.filter(ImageFilter.GaussianBlur(radius=2 * 0.55))
        big = big.rotate(rng.uniform(-1.2, 1.2), resample=Image.BICUBIC,
                         fillcolor=255)
        small = big.resize((big.width // 2, big.height // 2), Image.BOX)
        a = numpy.asarray(small, dtype=float)
        a = 35 + a * (243 - 35) / 255 + numpy.random.default_rng(
            rng.randrange(2 ** 31)).normal(0, 5, a.shape)
        images.append(Image.fromarray(
            numpy.clip(a, 0, 255).astype("uint8")).convert("L"))
    doc.close()

    paper = numpy.full((images[0].height, images[0].width), 243.0)
    paper += numpy.random.default_rng(2).normal(0, 5, paper.shape)
    images.insert(2, Image.fromarray(
        numpy.clip(paper, 0, 255).astype("uint8")).convert("L"))
    images.insert(5, images[0])                  # a double feed

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
    return written


if __name__ == "__main__":
    sys.exit(main())
