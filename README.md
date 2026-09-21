# checkit-printit

Prints a class set of [CheckIt](https://github.com/jslyemath/checkit) skill
checkpoints. Give it a bank, a roster, and a seating chart. You get a PDF where
each student has their own version of the skills they picked, ordered to match
the room so neighbours never share a paper, with answer keys at the back.

CheckIt's built-in assessment builder makes one anonymous quiz. This makes a
stack of paper for a room full of students.

## Install

Neither package is on PyPI, so both come from GitHub. One command gets both:

```bash
pipx install git+https://github.com/jslyemath/checkit-printit
```

`pipx` puts the tool in its own environment and makes `checkit-printit` a
command you can type anywhere. It asks you to run `pipx ensurepath` once, the
first time you use it, and then never again. Plain `pip install` works too, but
you have to be inside the environment you installed into every time you run it.

The name `checkit-dashboard` does exist on PyPI, but it belongs to the upstream
project and is different code, so this package names the fork's wheel by URL
rather than by name. That is why it installs from GitHub and not from PyPI.

### LaTeX

You also need `pdflatex`: TeX Live, MiKTeX, or MacTeX. That is a much larger
install than this tool, and it is the only hard requirement here.

**You can skip it.** `checkit-printit build --no-compile` writes a folder that
compiles anywhere -- upload it to Overleaf and press the button. Nothing about
the output depends on having TeX locally; only the convenience of getting a PDF
without leaving the terminal.

## A first run

Set up a folder for one quiz:

```bash
checkit-printit init ~/quizzes/2026-09-15 -b ~/Projects/mat-106-checkit
```

```
created ~/quizzes/2026-09-15/
  publication.toml
  roster.toml
  seating.toml

Next: fill in the roster and seating, then
  cd ~/quizzes/2026-09-15 && checkit-printit build --preview
```

The three files arrive with commented examples in them. Fill them in, then look
before you print:

```bash
checkit-printit build --preview
```

```
bank    /home/slye/Projects/mat-106-checkit
theme   /home/slye/Projects/mat-106-checkit/printit/printit.sty
out     /home/slye/CheckItPrintIt/MAT 106/Skill Checkpoint 2026-09-15

  students 24
  extras   6
  skills   4: W1, W1-E, N3, D2
  versions 8 distinct
  key pages 30
  seeds
    A  W1     v414
    A  N3     v407
    B  W1     v417
    B  N3     v433
```

Preview also reports the problems worth knowing about before you waste toner:
neighbours who ended up with the same version, students missing from the seating
chart, and template fields the generator never sets. When it reads right, drop
the flag:

```bash
checkit-printit build
```

That writes the folder and runs `pdflatex`.

## The three files

### `publication.toml` — this run

Where the bank is, what the header says, whether to print keys.

```toml
[course]
name      = "MAT 106"
semester  = "Fall 2026"
professor = "Slye"
title     = "Skill Checkpoint"
date      = "2026-09-15"

[bank]
path = "../mat-106-checkit"

[roster]
path = "roster.toml"

[seating]
path = "seating.toml"

[print]
keys       = true   # answer keys after the student copies
key_copies = 1
names      = true   # false prints a ruled blank instead of each name
```

Commented-out sections handle the rest: pinning a version to a known seed for an
exact reprint, choosing which variant of an outcome to ask for, the three skill
selection modes, and spare copies.

### `roster.toml` — who exists, and what they chose

```toml
[[student]]
name    = "Ada Lovelace"
section = "800"
skills  = ["W1", "N3"]
```

A `[selection]` table in `publication.toml` adjusts these choices, and its three
settings stack:

```toml
[selection]
simply_print         = []   # everyone gets exactly these; choices ignored
default_when_missing = []   # for students who chose nothing
append_for_everyone  = []   # added on top of whatever each student chose
```

Already keeping this in a spreadsheet? Import it once:

```bash
checkit-printit import "Control Center.csv" -o roster.toml
```

The import runs one way only. Read what it produced and fix anything it got
wrong, and after that nothing depends on a column staying where it is.

### `seating.toml` — where they sit

```toml
versions = ["A", "B"]

[[group]]
seats = ["Ada Lovelace", "Alan Turing", "Grace Hopper", "Katherine Johnson"]
```

One `[[group]]` per table. Versions alternate along each group so immediate
neighbours differ, and the pattern restarts at each table, since two tables
aren't adjacent. Papers print in this order, so the stack comes out matching the
room.

A seat can pin its version:

```toml
seats = [{name = "Ada Lovelace", version = "B"}, "Alan Turing"]
```

Everything else alternates around the pin. If a pin puts two neighbours on the
same version, you get a warning rather than an error, since you probably had a
reason.

## Flags

| | |
|---|---|
| `--preview` | report what would be printed, write nothing |
| `--no-compile` | write the folder, skip `pdflatex` |
| `--seed N` | reproduce an earlier run's version choices |
| `-o DIR` | write somewhere other than the default folder |
| `-p FILE` | use a publication file other than `publication.toml` |

## How a skill becomes a page

Most skills need nothing. The outcome's `template.xml` renders through CheckIt's
`latex.xsl`, the same source the website uses, and that is the page.

When a layout can't be said in SpaTeXt (true/false rows, blanks in a second
column, a figure with the answer marked on it) put a `textemplate.tex` beside the
generator. It's a LaTeX template using `\VAR{key}` for the generator's data, and
it wins over the SpaTeXt route for that outcome.

Either way you end up with a skill file written in the theme's commands, so a
generated skill and a hand-written one are interchangeable and one document can
hold both.

## The output folder

Builds land in `~/CheckItPrintIt/<course>/<title>/`, or wherever `-o` says. Set
`CHECKIT_PRINTIT_HOME` to move the root.

```
main.tex                 the assembled document
printit.sty              the theme
Skill Descriptions.tex   generated from bank.xml
W1/W1 v451.tex           one file per skill per version
assets/                  figures
```

Everything the document needs is in there. `pdflatex main.tex` builds it with no
tool, no bank, and no `TEXINPUTS`, which means you can archive it, audit it, or
fix a typo by hand the night before a quiz. It's a local record, not repository
content, so don't commit it.

## The theme

`printit.sty` decides how the pages look, and it works on its own: you can write
skills as plain `.tex` files against it with no CheckIt involved, which is how
one of the two courses using it works today. So this tool targets the theme's
commands instead of replacing them.

It lives in your bank, at `printit/printit.sty`, and it is yours to edit. The
first `build` puts the default there, or you can do it yourself:

```bash
checkit-printit install -b path/to/bank
```

That one file decides two things: how these handouts look, and how the CheckIt
viewer's Assessment tab exports LaTeX. Edit it, run `checkit generate`, and both
change together.

Installing also adds a line to the bank's `bank.xml`:

```xml
<latex-support>
    <file path="printit/printit.sty" role="theme"/>
</latex-support>
```

CheckIt publishes LaTeX files a bank declares there. It has no idea this tool
exists -- a constant in CheckIt naming `printit.sty` would be a hook for
something that may never be installed -- so writing the declaration is this
tool's job.

A bank without one still prints -- it falls back to the copy shipped inside this
package, and the Assessment tab falls back to CheckIt's plain template.

The file used to sit at the bank root as `skillcheckpoints.sty`. A bank still
arranged that way stops with move instructions rather than quietly reverting to
the default.

## Where versions come from

Seeds at or above `BUNDLE_UNTIL` (400) in the bank's `seeds.json`.

Those seeds are pregenerated, so a printed sheet can be traced back from its
seed, and they're published nowhere: `checkit viewer` copies `assets/` into
`docs/` and leaves `seeds.json` behind. Seeds 50 to 399 are off limits for
printing because `derived.json` publishes them together with their answers, so a
quiz drawn from that range is a quiz whose answers are one fetch away.

If you need more versions than the bank has, raise `--amount` when generating.

## Status

Early, but the whole path works: bank and roster in, compiled PDF out, with
seating, keys, extras, selection modes, variants, and pinned seeds.

Still to come: Google Forms, print tracking, and a seating GUI. Design notes live
in `PRINT_TOOL_DESIGN.md` in the checkit repo.

## Development

```bash
pip install -e ".[test]" && pytest
```

The tests build a real CheckIt bank on disk and print from it, rather than
mocking one. One test copies the finished output folder somewhere unrelated and
compiles it there, which is the only honest check of the self-contained promise
above; it skips itself if `pdflatex` is missing.
