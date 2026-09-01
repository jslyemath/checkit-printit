# checkit-printit

Print a class set of [CheckIt](https://github.com/jslyemath/checkit) exercises:
many versions of many skills, distributed across a seating chart so no two
neighbours get the same paper, with answer keys.

Not CheckIt's built-in assessment builder, which produces one anonymous
assessment. This produces a stack of paper for a room full of students.

## Install

```
pip install checkit-printit
pip install "checkit-dashboard @ https://github.com/jslyemath/checkit/releases/download/v0.2.8.5/checkit_dashboard-0.2.8.5-py3-none-any.whl"
```

> `checkit-dashboard` is **not** installed from PyPI: that name belongs to the
> upstream project, which is different code. Use the fork's wheel.

You also need a LaTeX distribution with `pdflatex` on your PATH — TeX Live,
MiKTeX or MacTeX. Without one, `--no-compile` still writes a folder you can
build elsewhere.

## Use

```
checkit-printit init            # writes publication.toml
checkit-printit build           # assembles and compiles
```

`publication.toml` says what this run wants: the course, which bank, the roster
and seating files, whether to print keys.

```toml
[course]
name = "MAT 106"
semester = "Fall 2026"
professor = "Slye"
title = "Skill Checkpoint"
date = "2026-09-15"

[bank]
path = "../mat-106-checkit"

[roster]
path = "roster.toml"

[seating]
path = "seating.toml"

[print]
keys = true
names = true
```

`roster.toml` is who exists and what they chose:

```toml
[[student]]
name    = "Ada Lovelace"
section = "800"
skills  = ["W1", "N3"]
```

`seating.toml` is where they sit. Versions alternate along each group, so
immediate neighbours differ:

```toml
versions = ["A", "B"]

[[group]]
seats = ["Ada Lovelace", "Alan Turing", "Grace Hopper", "Katherine Johnson"]
```

A seat can pin its version — `{name = "Ada", version = "B"}` — and everything
else alternates around it. A pin that collides is reported, not refused: it is a
deliberate act and you may have a reason.

### Useful flags

| | |
|---|---|
| `--preview` | report what would be printed, write nothing |
| `--no-compile` | write the folder, skip `pdflatex` |
| `--seed N` | reproduce an earlier run's version choices |
| `-o DIR` | somewhere other than the default output folder |

### Coming from the spreadsheet

```
checkit-printit import "Control Center.csv" -o roster.toml
```

A one-way import. Read what it produced, fix anything it got wrong, and nothing
downstream ever depends on a column position again.

## Where versions come from

Seeds at or above `BUNDLE_UNTIL` (400) in the bank's `seeds.json`.

That range is pregenerated, so a printed sheet is reproducible from its seed,
and **published nowhere** — `checkit viewer` copies `assets/` into `docs/` while
ignoring `seeds.json`. Seeds 50–399 are *not* used: `derived.json` publishes
those with their answers, so a quiz drawn from there is a quiz whose answers are
a fetch away.

Need more versions than the bank has? Raise `--amount` when generating.

## The output folder

Builds land in `~/CheckItPrintIt/<course>/<title>/`, or wherever `-o` says.
Override the root with `CHECKIT_PRINTIT_HOME`.

```
main.tex                 the assembled document
skillcheckpoints.sty     the theme
Skill Descriptions.tex   generated from bank.xml
W1/W1 v451.tex           one file per skill per version
assets/                  figures
```

**That folder compiles with `pdflatex main.tex` and nothing else** — no tool, no
bank, no `TEXINPUTS`. It is a local record you can archive, audit, or fix by
hand the night before a quiz. It is deliberately not something to commit.

## The theme

`skillcheckpoints.sty` decides how everything looks, and **it is a working
by-hand system**. Skills can be written as plain `.tex` files against it with no
CheckIt anywhere — that is how one of the two courses using it works today.

So the tool targets the theme's commands rather than replacing them. A
hand-written skill file and a generated one are the same kind of thing, and one
document can mix them.

The package ships a default. A bank may drop its own `skillcheckpoints.sty` in
its root to replace it — the same convention `checkit`'s `tikz.py` uses for
`tikz_preamble.tex`.

## How a skill becomes a page

Two routes, and the first wins.

**Its SpaTeXt, through `latex.xsl`** — the default, and what you get for free.
Write one `template.xml` and the outcome prints. Nothing extra to maintain.

**A `textemplate.tex`** — the escape hatch, for layout no vocabulary would
capture: true/false rows, blanks in a second column, figures with the answer
marked on them. A LaTeX template using `\VAR{key}` for the generator's data.

Either way the result is a skill file in the theme's own vocabulary, so a
generated file and a hand-written one are the same kind of thing and one
document can mix them.

## Status

Early. Working today: the whole path from bank and roster to a compiled PDF,
with seating, keys, extras, selection modes, variants and pinned seeds.

Not yet: Google Forms, print tracking, the seating GUI. See
`PRINT_TOOL_DESIGN.md` in the checkit repo.

## Development

```
pip install -e .[test]
pytest
```

The tests build a real CheckIt bank on disk and print from it. One of them
copies the output folder somewhere unrelated and compiles it there, which is the
only honest way to test the self-contained promise; it skips if `pdflatex` is
missing.
