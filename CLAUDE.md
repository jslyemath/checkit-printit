# Working in checkit-printit

Turns a CheckIt bank plus a roster into a printable class set. The platform is
a sibling repo and **the fuller guide lives there**: `../checkit/CLAUDE.md`.

```bash
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m checkit_printit build --preview
```

## What this tool owns

`printit.sty` and `printitfigures.sty`, in `src/checkit_printit/theme/`.
`install` copies them into `<bank>/printit/` for the author to edit, and writes
a `<latex-support>` declaration into the bank's `bank.xml`.

CheckIt publishes what a bank declares and **holds no constant naming this
tool**. Keep it that way: a name in CheckIt would be a hook for something that
may never be installed.

The split between the two `.sty` files is not cosmetic. CheckIt rasterizes a
bank's `.tikz` in a `standalone` document, where `printit.sty` cannot load — it
sets up page geometry and headers and expects `\acadclass` and `\title`. The
picture half has to be loadable alone.

## The output folder is the point

Every run writes a folder that compiles with `pdflatex main.tex` and nothing
else — no bank, no tool, no `TEXINPUTS`. Figures are copied in by scanning the
written `.tex` for `\includegraphics` and `\input{...tikz}`.

That scan is why a per-outcome `textemplate.tex` must decide **in Jinja**, not
in LaTeX, which files it names: a `\input` sitting in a branch LaTeX would
never run is still text in the file, and the build fails looking for it.

## Two things worth re-reading before changing them

- `choose_seeds` draws **without replacement** per skill, so two version
  letters are never the same paper. Drawing independently looked fine and
  collided about one run in fourteen at ten versions.
- `build --preview` writes nothing. Its "versions N distinct" line is the
  check that the run is what was asked for.
