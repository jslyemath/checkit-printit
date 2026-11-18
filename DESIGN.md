# checkit-printit — design record

**Moved here from `checkit/PRINT_TOOL_DESIGN.md` on 2026-11-17**, into the
repo it describes. Its history before that date is in the checkit repo's
git log. Section numbers are unchanged, so every "DESIGN 12.6" or
"PRINT_TOOL_DESIGN.md 12.6" in the code and the notes still finds its
section. What is still to do is not here: `../checkit/ROADMAP.md`.

**Status: stages 1-5 are built** (2026-09-20). Written 2026-09-01 from reading
`pdfgenerator.py`, `skillcheckpoints.sty`, `main_template.tex` and the 30
`textemplate.tex` files in mat-106, plus the requirements given in
conversation. Sections 1-11 are that original draft, still accurate except
where **section 12** revises them; 12 covers stages 6 and 7 and the GUI, and
is the current plan.

Companion to the "The print tool" sections of `CODEBASE_NOTES.md`, which this
supersedes where they disagree.

---

## 1. What it is

A separate installable package that turns a CheckIt bank plus a roster into a
printable PDF: many versions of many skills, distributed across students,
optionally with answer keys.

It is **not** CheckIt's built-in assessment builder, which produces one
anonymous assessment. This produces a class set.

Its own repo, depending on `checkit-dashboard`. Not in the platform (rosters
and Google OAuth are not platform concerns, and it would worsen upstream
merges) and not in a bank (there are two, and the pipeline is currently copied
between them by hand).

---

## 2. The constraint that shapes everything

**`skillcheckpoints.sty` is a working by-hand system, and must remain one.**

MAT 206's skills are currently hand-written `.tex` files using that package,
with no CheckIt involved at all. That is not a temporary state to be migrated
away from — it is a supported way to use the system, and it is why the package
looks the way it does.

Three consequences, and they decide the architecture:

1. **The unit of exchange is a skill `.tex` file**, not anything CheckIt-shaped.
   A hand-written skill file and a generated one must be indistinguishable to
   the assembler, so a single document can mix them.
2. **The `.sty` vocabulary is the interface.** `\skillheader`, `\tfleft`,
   `\fillinblank`, `\minicol`, `\ans`, `ansenv`, `\setvseed`, `\setname`,
   `\setsect` are a public API. The print tool *targets* them; it does not
   replace them.
3. **The `.sty` must not require CheckIt.** No generated file it depends on, no
   import path, no assumption that `bank.xml` exists.

An earlier draft in `CODEBASE_NOTES.md` proposed making `latex.xsl` emit
semantic `\stxKnowl` / `\stxTask` commands and having a theme redefine them.
**That is now the wrong direction.** It would create a second vocabulary that
hand-authors do not use, and split the system in two. The existing commands
already are the semantic layer.

---

## 3. Architecture

```
     BANK                              PRINT TOOL                    LATEX
┌──────────────┐            ┌────────────────────────────┐      ┌────────────┐
│ seeds.json   │──seeds──▶  │ render                     │      │            │
│ (400-999)    │            │   textemplate.tex + data   │──▶   │ skill .tex │
│              │            │   or SpaTeXt → .tex        │      │  per       │
│ bank.xml     │──slug,     │                            │      │  version   │
│              │  desc      │ assemble                   │      └─────┬──────┘
│ textemplate  │──layout──▶ │   roster × seating × skills│            │
│   .tex       │            │   keys, extras, ordering   │            ▼
│ bank_helpers │            │                            │      ┌────────────┐
│   .sty       │──macros──▶ │ emit                       │──▶   │ main .tex  │
└──────────────┘            │   one folder, recompilable │      │  + .sty    │
                            └────────────────────────────┘      └─────┬──────┘
     ROSTER                                                           │
┌──────────────┐                                                      ▼
│ names,       │──────────────────────▶                          ┌────────┐
│ selections,  │                                                 │  PDF   │
│ seating      │                                                 └────────┘
└──────────────┘
```

### Layers, and what each owns

| | owns | lives in |
|---|---|---|
| **bank** | what an exercise says; the macros its content needs | the bank repo |
| **skill `.tex`** | one version of one skill, laid out | generated, or hand-written |
| **theme (`.sty`)** | how everything looks | print tool default; a bank or course may replace it |
| **publication** | what *this run* wants | a file in the course repo |
| **roster** | who gets what, and in what order | Google Sheet today; local file always possible |

---

## 4. Inputs

### 4.1 Publication file

The settings that describe a run. Plain data, versioned with the course, no
code. TOML proposed.

```toml
[course]
name       = "MAT 106"
semester   = "Fall 2026"
professor  = "J. Slye"
title      = "Skill Checkpoint 4"
date       = "2026-09-15"

[bank]
path = "../mat-106-checkit"

[print]
keys          = true      # print answer keys at the end
key_copies    = 2
names         = true      # false prints a blank rule instead
double_sided  = true
seed_override = 0         # 0 = pick per the seating chart

[[extras]]
skill  = "W1"
copies = 3                # blank name line; versions shuffled if > 1
```

Replaces the named cells currently read from the sheet.

`PDF Location:` is genuinely used and should stay: "Default Folder" or a save
dialog. An earlier draft of this document said it was ignored; that was wrong —
it drives `filedialog.asksaveasfilename` at `pdfgenerator.py:165`.

`Include Names:` is dead *in Python*, but only because the Apps Script already
applied it, writing the literal `Blank` into the name column before the CSV is
exported. That is the split-brain problem in miniature: one setting, two
implementations, and the second one looks broken when read alone.
`Submission Cutoff:` is read and unused on both sides.

### 4.2 Roster

Who exists, what each student selected, and which section they are in.

**The tool's own format is structured data it defines** — TOML or JSON with real
fields:

```toml
[[student]]
name    = "Ada Lovelace"
email   = "kstellat@oswego.edu"
sid     = "806510955"
section = "800"
skills  = ["G2-E", "G4", "A2"]
```

**Getting Google responses into that shape is an import step, not the format.**
The current pipeline treats a CSV export *as* the data model: magic headers
(`Full Name:`, `Sec:`, `Var:`, `1:`) located by string-searching a grid, in a
format never intended for structured records. Reproducing that would be
inheriting the hack rather than replacing it.

Two importers, either of which writes the structured file:

- **Forms/Sheets API** — the eventual path, and the only reason Google is
  involved at all (university-controlled accounts, no good alternative for
  polling students).
- **A CSV import step** — map columns once, interactively, eyeball the result.
  Useful as a fallback when the API is down or scopes lapse.

Either way nothing downstream ever sees a magic header.

### 4.2b Skill selection modes

Three overrides, all in the current Apps Script, all wanted:

| mode | behaviour |
|---|---|
| **Simply Print** | everyone gets the same listed skills; responses ignored entirely |
| **No Submission? Default to…** | fallback skills for students who did not respond |
| **Append for Everyone** | these skills are added on top of whatever each student chose |

They compose: Append applies on top of both of the others.

#### Who the run is for (2026-10-26)

A fourth axis, deliberately **not** a fourth mode. The three above
answer "what does this student get". This one answers "is this
student in the run at all", and they compose.

The case that asked for it: print two skills for one student who
missed the session. With only the modes, that was either a class set
thrown away, or switching to Simply Print and retyping the list for
one person -- and Simply Print would then have been left in the draft
for the next run.

| | |
|---|---|
| in the app | a second segmented row, `Printing for: the whole class / just the ones I tick`, with a tick column that appears only in the second state |
| in the job file | `[selection] only_students`, absent for the class |
| on the command line | `--only KEY`, repeatable |

Three decisions worth keeping:

- **Switching it on ticks everybody.** The switch by itself never
  changes what prints; you then untick. The alternative -- switching
  on to an empty list -- makes the control's first click destructive.
- **Switching it off clears the list.** A list left from last week is
  one click away from printing a class set as a single sheet. Same
  argument as the draft's mode keys, and worse here, because the
  wrong answer is one paper instead of forty-three.
- **Empty is refused, absent is everybody.** Which is why the key is
  written even when empty: the mistake has to be visible in the file
  to be refusable.

Still to come: a shorthand for "only the students I list", typed
rather than ticked. The filter is the half that was needed first.

### 4.3 Seating chart

Currently a set of sheets (one per section) with columns
`Group | Variant | Students | N`. Students sit in groups of four; the Variant
column alternates `A, B, A, B` within a group, typed by hand.

It determines the **order** students print in, so a stack of paper matches the
room, and which version each gets.

**The rule, stated plainly: two versions, and no two immediately adjacent
students share one.** Not "everyone at a table differs" — immediate neighbours.
That is why two versions suffice for a table of four.

Sections currently share the pool: `A`/`B` across both 800 and 810. A later
seating chart could use `E`/`F`/`G`/`H` to make a section disjoint, but nothing
needs that today.

**Long term** this becomes a GUI: drag seats into position, mark each with a
version letter, and the tool derives everything. That is the target.

**In the interim**, the smallest thing that removes the hand-typing: a seating
file listing groups in order, with the tool alternating versions along each
group and warning when two adjacent seats collide. A seat may be pinned to a
version explicitly, so the tool never overrules a deliberate choice.

```toml
[[group]]
seats = ["Ada Lovelace", "Alan Turing", "Grace Hopper", "Katherine Johnson"]

[[group]]
seats = ["Emmy Noether", "Srinivasa Ramanujan", "David Blackwell", "Mary Cartwright"]
```

The interim format should be whatever the GUI will eventually read and write,
so the GUI is a front end for it rather than a replacement.

## 5. Where versions come from

**Seeds 400–999 of the bank's `seeds.json`.** Pregenerated, reproducible, and
published nowhere — `checkit viewer` excludes `seeds.json` from `docs/`, so
those versions exist only in the bank.

This replaces the current approach of seeding `random` with a 5-digit number and
running the generator directly. Two gains: printing needs no working generator
environment, and a printed sheet can be reproduced exactly from its seed.

Do **not** use seeds 50–399: `derived.json` publishes those *with their answers*.

Variants are selected here too. An outcome declaring
`variants = ["no_repeating", "repeating"]` records the label per seed, so a
publication can ask for the case the course has reached:

```toml
[variants]
D2 = "no_repeating"
W7 = "terminating"
```

Without an entry, any variant is acceptable.

**Seed overrides** let the user choose the seeds *and* how they map onto the
seating versions — not just "use seed 509", but "version A is seed 509, version
B is seed 662". That makes a reprint exact, and it makes "give me the same quiz
as last section" a one-line change.

```toml
[seeds]
A = 509
B = 662
```

---

## 6. Output

### 6.1 The skill `.tex` file — the unit

One file per (skill, version):

```
out/
├── main.tex                  the assembled document
├── skillcheckpoints.sty      the theme, copied in
├── bank_helpers.sty          the bank's macros, copied in
├── skills/
│   ├── W1/
│   │   ├── W1 v451.tex
│   │   └── W1 v802.tex
│   └── N3/
│       └── N3 v451.tex
└── assets/                   figures the skills reference
```

**Requirement: this folder must compile with `pdflatex main.tex` and nothing
else.** No absolute paths, no reference back to the bank, no tool required. That
is what makes the output auditable, archivable, and fixable by hand at 11pm the
night before a quiz.

A hand-written skill file dropped into `skills/` is indistinguishable from a
generated one, which is the property §2 demands.

### 6.2 How a skill `.tex` is produced

Two paths, in priority order:

1. **The outcome has a `textemplate.tex`** — render it with the version's data,
   exactly as today. This is how every mat-106 outcome works, and it is how
   layout that no vocabulary will capture stays possible.
2. **It does not** — render the SpaTeXt through `latex.xsl` and wrap it in the
   theme's commands.

Path 2 means new outcomes cost one template instead of two, and path 1 means
nothing has to migrate. `textemplate.tex` is a permanent escape hatch, not a
transitional state.

### 6.3 Skill descriptions

`\skillheader{W1}` already opens a skill with its slug and description, looked
up from a `\setskilldesc` dictionary that `pdfgenerator.py` writes out of
`bank.xml`. That flow is correct and should survive unchanged.

For hand-written banks with no `bank.xml`, the descriptions file is written by
hand — which is exactly how MAT 206 works today.

---

---

## 6b. The assessment builder should converge on this

The viewer already has an assessment builder: pick outcomes, get one random
version of each as LaTeX, copy it or push it to Overleaf. **The goal is for it
to be the same thing as a print run with one student, a blank name, and one
seed.**

That is closer than it looks, because the mechanism already exists.

### What is already there

`viewer/src/templates/assessmentTemplate.tex` is a **self-contained** document —
its own `\documentclass`, its own `\usepackage` list, a Mustache loop over the
exercises. It is **already user-editable in the UI**, stored per browser, with a
reset-to-default button. It already POSTs to Overleaf.

So "carry the theme in the header" is not a new capability. It is a different
default template.

### Inlining the theme

LaTeX has a feature for exactly this, and Overleaf supports it:

```latex
\begin{filecontents*}[overwrite]{skillcheckpoints.sty}
... the whole theme ...
\end{filecontents*}

\begin{filecontents*}[overwrite]{Skill Descriptions.tex}
\setskilldesc[Blue]{G1}{I can identify lines of symmetry...}
\end{filecontents*}

\documentclass[12pt]{article}
\usepackage{skillcheckpoints}
\begin{document}
\setname{Blank}\setsect{Blank}
\skillheader{G1}
... exercise body ...
\end{document}
```

`filecontents` writes those files at compile time, so one pasteable block
carries the theme *and* the `\input{Skill Descriptions.tex}` the theme depends
on. No attachments, no folder.

**The exported assessment carries answers** — it is an instructor artefact, so
`\setboolean{anstoggle}{true}`.

### The obstacle: figures

`latex.xsl` renders `<image>` as `\includegraphics{assets/<slug>/generated/<seed>/<name>.png}`
— a **relative path**. Pasted into Overleaf there is no `assets/` folder, so the
figure is missing.

And there is a live bug behind it (found 2026-09-01, see `CODEBASE_NOTES.md`):
the assessment builder draws seeds from `[PUBLIC_SEEDS, BUNDLE_UNTIL)` = 50–399,
but `--image-seeds 50` rasterises PNGs only for seeds 0–49. **Every assessment
containing `F2` or `F2-E` currently references a PNG that was never rendered.**
Browsing looks fine because the viewer only ever shows seeds 0–49; print is fine
because it uses `textemplate.tex` with TikZ written inline and never touches the
PNGs.

Three ways to close it:

1. **Raise `--image-seeds` to `BUNDLE_UNTIL`.** Fixes the broken images. Does
   not fix copy-paste, and multiplies rasterisation time and `docs/` size by
   about eight.
2. **Publish `.tikz` and have `<image>`-style figures `\input` the source.**
   `build_viewer` currently excludes `*.tikz`. With the source published,
   `filecontents` can inline the figure too, and a pasted document draws its own
   figures with no image files at all. **This is the only option that actually
   yields one self-contained file**, and it matches what print already does.
3. **Base64 the PNGs into the document.** Works; bloats the paste enormously.

Recommended: (2), with (1) as an immediate stopgap if assessments are needed
before the tool exists.

### How close the two get

| | print | assessment builder |
|---|---|---|
| theme | `\usepackage{skillcheckpoints}` from a file | same, via `filecontents` |
| skill body | `\input{W1/W1 v451.tex}` | inlined |
| name | `\setname{Teddy Quill}` | `\setname{Blank}` |
| answers | off for students, on for keys | on |
| seeds | one per seating version | one, random from 50–399 |
| assembly | loop over students | no loop |

Everything but the last two rows is identical. **If the print tool's theme
becomes the assessment builder's default template, the two differ by a loop.**

---

## 6c. Print tracking

The tool records what was printed for whom, and lets the instructor mark what
happened afterwards.

```
printed 2026-05-06 "Skill Checkpoint" :
  Ada Lovelace  G2-E seed 509   → passed
  Ada Lovelace  G4   seed 509   → did not pass
  Ada Lovelace  A2   seed 509   → did not take
```

**For instructor record-keeping only.** It does *not* feed back into printing —
no "skip skills already passed", no "prioritise repeated failures". That keeps
the print path a pure function of its inputs.

Lives **in the tool**, not a spreadsheet. That means a table-style editor in the
eventual GUI, which is a later bridge; until then the store is a local file the
tool reads and writes.

Its shape matters more than its editor. It should answer:

- what did this student receive, on what date, at which seed?
- what happened with it?

which also makes exact reprints a lookup rather than a re-derivation. That is
why **byte-for-byte reproducibility is not a requirement**: recording the seed
is cheaper and more honest than making the whole run deterministic, and it does
not cost the freedom to reshuffle.

---

## 6d. Where output goes

A canonical location on the local machine, so the same PDF can be rebuilt later:

```
~/CheckItPrint/MAT 206/2026-05-06 Skill Checkpoint/
├── main.tex
├── skillcheckpoints.sty
├── bank_helpers.sty
├── skills/…
└── assets/…
```

`pdflatex main.tex` works there, forever, with no tool and no bank. **Not
committed to a repository** — it is a local record, not a published artefact.


## 7. Google integration

> **Revised by section 12.5 (2026-09-20)**, which settles form ownership, the
> question-id map, and how to find out whether the Google Cloud path is even
> open on a university account. The sketch below still holds in outline.


Two directions, and they are different problems.

**Reading responses** replaces the CSV export step. Google Forms API or Sheets
API; needs OAuth, a client secret, and a token cache. Contained: one adapter
behind the interface in §4.2.

**Writing the form** — updating the week's available skills so students can
select them — is the more valuable half and the harder one. It needs the Forms
API with edit scope, and it needs to know which skills are "available this
week", which is a fact the tool does not currently have anywhere.

Proposed: the publication file names them.

```toml
[form]
id     = "1FAIpQLSc..."
skills = ["W1", "W2", "N3", "F2"]
```

**Suggestion: build the CSV path first and the Forms path second.** The CSV path
is the whole pipeline minus one adapter; adding OAuth to a tool that already
works is easier than debugging both at once.

---

## 8. Feature inventory

Everything the current tool does, plus what is wanted. Marked by state.

**Swept 2026-11-05.** This table was written against the pre-port Apps
Script and not revisited after the port, so twelve rows still said
"not built" about things that had been in for weeks. Each cell now
names the call that does it, so the next sweep can check rather than
remember.

| feature | today | proposed |
|---|---|---|
| Per-student skill selection | ✅ roster columns `1:`, `2:`… | keep |
| Variant → seed mapping | ✅ **done** — `choose_seeds` draws from `bank.seeds_with_variant`, the print-only range, without replacement | |
| Seed override | ✅ | keep, in the publication file |
| Sections in header | ✅ `\setsect` | keep |
| Key packets, N copies | ✅ `Key Amount:` | keep |
| Key deduplication, bank order | ✅ | keep |
| Double-sided safety | ✅ `\preparefornextstudent` | keep |
| Course / semester / professor | ✅ four `\VAR{}`s | move to publication file |
| Skill headers with descriptions | ✅ from `bank.xml` | keep |
| Version stamp in footer | ✅ `\setvseed` | keep |
| LaTeX error log to file | ✅ | keep |
| PDF location: default folder or choose | ✅ `pdf_location_raw` drives a save dialog | keep |
| **Names on/off** | ✅ **done** — `Publication.names`, one place; false draws the ruled blank and the id grid | |
| **Submission cutoff** | ❌ **dropped** — never ported. Only in `reference/control_center.gs`; neither side reads it | |
| **Seating-chart ordering** | ✅ **done** — the chart is passed to `assemble`; `section.print_by` picks group or seat order | |
| **Version count from seating** | ✅ **done** — `versions = list(chart.versions)`, falling back to one | |
| **Extras with blank names** | ✅ **done** — `build_extras` sets `blank_name=True` | |
| **Shuffled extras** | ✅ **done** — `build_extras` shuffles the pool, so three extras of one skill are three different papers | |
| **Keys optional** | ✅ **done** — `Publication.keys`, separate from `key_copies` | |
| **Recompilable output folder** | ✅ **done** — a run folder carries `main.tex`, both `.sty` files, `Skill Descriptions.tex`, the per-skill sources and `manifest.toml` | |
| **Google Forms read** | ✅ **done** — stage 7b, `form pull`, and the Print tab's first card | |
| **Google Forms write** | ✅ **done** — stage 7a, create/attach/map/add-items/push, from the app | |
| **Selecting variants** | ✅ **done** — `[variants]` in the publication file; an unchosen variant is refused | |
| Simply Print / No-Sub default / Append | ✅ in Apps Script | keep all three |
| Available-skills list drives the Form | ✅ Apps Script | keep |
| Form validation (at most / least / exactly N) | ✅ Apps Script | keep |
| Email students who did not respond | ✅ Apps Script | **eventually**, in the tool — still not started, roadmap item 7 |
| Printed log | ✅ a sheet | becomes tracking, §6c |
| **Attempt outcomes (took / passed / failed)** | ✅ **done** — `record.save_attempts`, written by Scans, read by Progress | |
| Per-skill print counts, page estimate | ✅ Apps Script | keep as a preview |
| Reset settings after a run | ✅ `printAndReset` | keep |
| **Auto-attached explanation skills** | ✅ Apps Script | **deprecated** — explanations are standalone outcomes now |

---

## 9. Staging

Each stage ends with something that works.

**1 — Package the existing tool.** `pdfgenerator.py` cleaned up, importable,
tested, driven by a structured roster file rather than a magic-header CSV. Same
output. Establishes the repo, the theme's home, and a golden-PDF comparison to
protect everything after.

**2 — Pregenerated seeds.** Swap generator-at-print-time for seeds 400–999, with
seed overrides mapping to seating versions. First point at which printing needs
no generator environment.

**3 — Publication file.** Replace the named cells. Skill selection modes
(Simply Print / No-Submission default / Append) move here.

**4 — Seating, extras, keys.** Group-based ordering with A/B alternation and a
collision warning; extras appended at the end with blank names and shuffled
versions; keys optional.

**5 — Output guarantee.** The canonical folder compiles standalone; a test
asserts it.

**6 — Tracking.** Record what each student received; a way to mark outcomes
afterwards. Storage first, editor later.

**7 — Google.** Read responses, then write the form.

**8 — Assessment-builder convergence.** The theme becomes the viewer's default
assessment template, inlined with `filecontents`. Depends on the figure decision
in §6b.

**9 — SpaTeXt fallback.** Skills with no `textemplate.tex` render through
`latex.xsl`. Last, because nothing needs it until a bank is authored without
print templates.

**Not staged: the seating GUI.** It is the eventual target, and the interim
seating file should be the format it will read and write, so the GUI is a front
end rather than a rewrite.

## 10. Decisions taken

Settled in review, recorded so they are not relitigated.

| | |
|---|---|
| Theme location | ships in the print package; a bank may replace it, same convention as `bank_helpers.sty` |
| Versions needed | **two**, avoiding *immediate* neighbours — not everyone at a table |
| Sections | share the A/B pool today; a seating chart may use other letters later |
| One folder, one run | the folder name `{title} {date}` **is** the run's identity. A build whose papers differ from the ones that folder recorded is refused, because `main.pages` is the only record of which printed page was whose. Decided 2026-10-29, after it cost a live run of 86 papers |
| A recovered index says so | `--rebuilt` brings the page map back from the roster and the chart, which are enough. The seeds are not recoverable, so the run carries a `rebuilt` mark and nothing prints a seed from it as though it were the one handed out |
| Seed overrides | user picks the seeds **and** their mapping onto seating versions |
| Extras | appended at the end, blank name line, versions shuffled among those available |
| Roster format | the tool's own structured file; CSV is an import step, never the model |
| Skill selection modes | all three kept, and they compose |
| Assessment export | carries answers |
| Tracking | in the tool, instructor-only, does **not** feed back into printing |
| Reproducibility | not a requirement — the tracking log records seeds instead |
| Output folder | canonical local path, rebuildable, never committed |
| Auto-attach | deprecated; explanations are standalone outcomes |
| Email missing students | in the tool, but far out |

## 11. Still open

1. ~~Whether the interim seating file and the eventual GUI share a format from
   the start.~~ **Settled 2026-09-02: yes.** The GUI is a local web app that
   edits `seating.toml` in place, so there is only ever one format. Desk x/y
   positions go in the same file. See "Where we paused" in `CODEBASE_NOTES.md`
   for the full architecture.
2. Which figure route to take for self-contained assessments (§6b): raise
   `--image-seeds`, publish `.tikz`, or base64. Recommended: publish `.tikz`.
3. ~~Whether the two banks' identical `skillcheckpoints.sty` copies are deleted
   in favour of the package default.~~ **Overtaken by events 2026-09-02.** They
   are no longer identical: mat-106 and the printit package carry a color fix
   that mat-206 does not, and mat-206 is to be rebuilt from scratch rather than
   kept in step. Revisit once that rebuild happens.
4. What a hand-authored bank's `bank.xml` looks like, given the tool should keep
   `Skill Descriptions.tex` in step with it — MAT 206 has a real `bank.xml`
   already, so possibly nothing special is needed.
5. ~~Whether `Submission Cutoff:` is implemented or dropped.~~
   **Dropped by not being ported.** It survives only in
   `reference/control_center.gs`, the pre-port script kept for
   reference; neither printit nor the live Apps Script reads it. The
   "grade cutoffs" that do appear in `form.py` and `provision.py` are
   a different thing -- the banner on the form.

---

## 12. Local state, Google Forms, and the GUI (2026-09-20)

Stages 1-5 are built and in use: a real class set of 48 students printed on
2026-09-18 from form responses. This section is stages 6 and 7 plus the GUI,
and revises 7, 10 and 11 where they disagree.

### 12.1 The course

**The problem, concretely.** A job folder is self-contained: `publication.py`
resolves `[roster] path` relative to the publication file, so every job carries
its own copy of the roster and the seating chart. The 2026-09-13 run got its
seating by copying the 2026-09-10 run's file. Three copies of the same 48
students now exist on disk.

A student drops. Which file is edited? The next job is made by copying the last
one, so the fix has to be remembered and reapplied at copy time. Miss it and
they get a paper. Nothing detects the drift, because three files that disagree
are three valid files.

**A course folder is the home for state that outlives a job.**

```
~/CheckItPrintIt/
├── courses/
│   └── MAT 106/
│       ├── course.toml         name, code, semester, professor, bank path
│       ├── roster.toml         last, first, preferred, sid, email, section, dropped
│       ├── seating.toml        groups + desk x/y -- the GUI's file
│       ├── availability.toml   skills open for retake + the next assessment
│       ├── form.toml           form id, item ids, last pushed state
│       ├── record.db           SQLite: what was printed, to whom, at which seed
│       └── secrets/            OAuth client + token cache
├── jobs/<job>/                 publication.toml only
└── MAT 106/<title>/            output, unchanged
```

**One course folder need not be one course.** An instructor may run both
sections of MAT 106 from a single folder with one form and `section` as a
roster field. Another may make "MAT 106 820" and "MAT 106 830" and keep
them wholly apart, each with its own roster, seating chart, form,
availability list and print record. Both are supported and neither is the
default. The directory is named by the instructor; nothing derives it from
the course code, and `course init` will make as many as you like.

**Resolution order in `publication.load()`:**

1. an explicit `[roster] path` -- use it, so every existing job folder keeps
   working unchanged;
2. else `[course] folder` -> `~/CheckItPrintIt/courses/<name>/roster.toml`;
3. else an error naming both options.

**Not a symlink.** `viewer/public/assets/bank.json` is a git symlink that
Windows checks out as a 35-byte text file containing its own target, which is
why the viewer dev server cannot load a bank on this machine. Resolution in the
loader is explicit, cross-platform and greppable.

Once roster and seating are shared, the manifest's existing `[inputs]` hashes
start meaning "the course roster as it stood that day", which is worth more
than a hash of a copy.

### 12.2 Roster, and importing from Banner

```toml
[[student]]
last      = "Quill"
first     = "Theodore"
preferred = "Teddy Quill"   # what prints; falls back to first
sid       = "806510955"
email     = "tquill12@example.org"
section   = "830"
dropped   = false
```

**Legal and preferred names are different fields.** The seating chart says
"Teddy Quill", "John Erdos", "Sofia Cantor". A Banner export will not.
Without both, every re-import overwrites the name on the printed page.

**SID is the join key. Email is the fallback. Name is never a key.** SIDs do
not change; emails and names do. The Google Form collects email, so the roster
must carry both and a response maps email -> SID -> student.

**`dropped` is a flag, never a deletion.** The print record has to survive.
A dropped student is excluded from printing, from seating auto-fill and from
form pushes, and stays in every query.

**Importing is a merge, and absence is not deletion.** A student present in the
course but missing from a fresh Banner export is marked `dropped = true`,
not removed. A re-import must not clobber `preferred`, `section` overrides, or
anything the seating chart references.

The importer has to be forgiving, because Banner exports are not a format:

- find the header row rather than assuming row 1 -- scan for the row where the
  most known labels appear;
- map columns by matching against a synonym table, e.g. `sid` from
  `ID / Student ID / SID / Banner ID`, `last` from `Last Name / Last / Surname`,
  `email` from `Email / Email Address / E-mail`;
- print the mapping it chose and stop for confirmation before writing, with
  flags to override any column;
- accept `.csv` and `.xlsx`, because the exports that arrive are both.

Report adds, drops and field changes as three counts. Never a silent merge.

### 12.3 Availability

Which skills are open for retake, and what the next assessment is. One file,
because the form push and the print job both need exactly this:

```toml
[assessment]
name   = "Skill Checkpoint Redo"
date   = 2026-09-18
due    = 2026-09-17T23:59:00
choose = 3                       # at most N

skills = ["W1", "W1-E", "D1", "D1-E"]
```

Descriptions are **not** stored here -- they come from `bank.xml`, which is
already the single source for the printed skill headers and for
`Skill Descriptions.tex`. Copying them into a second file is how they drift.

Availability is **global, not per student**. The form shows one list to
everyone; a student who has already passed W1 still sees W1. Per-student forms
are not possible in Google Forms without one form per student.

### 12.4 The print record

**The rule: if a human is the author, TOML. If the tool is the author, SQLite.**

Roster, seating, availability, course config, form config and publication are all
hand-edited or GUI-edited, bounded in size, and read by eye. The print record
is none of those things:

- it never stops growing -- 48 students times three papers times fifteen
  assessments is about 2,000 rows a term;
- every question asked of it is a query ("how many times has this student
  attempted W1", "what did she get on 9/17", "which skills has nobody passed"),
  which is one line of SQL or a hand-rolled index over TOML;
- two processes write it -- the CLI at build time, the GUI when marking the
  gradebook. SQLite takes a lock; two writers rewriting a TOML file race and
  the loser's write vanishes silently;
- `sqlite3` is in the standard library.

```sql
CREATE TABLE run (
    run_id  TEXT PRIMARY KEY,      -- the output folder name
    title   TEXT NOT NULL,
    date    TEXT NOT NULL,
    built   TEXT NOT NULL,
    seed    INTEGER NOT NULL,      -- so a replay is findable from the record
    output  TEXT NOT NULL
);

CREATE TABLE printed (
    printed_id INTEGER PRIMARY KEY,
    run_id     TEXT NOT NULL REFERENCES run(run_id),
    sid        TEXT NOT NULL,      -- never the name
    slug       TEXT NOT NULL,
    seed       INTEGER NOT NULL,
    version    TEXT NOT NULL,
    variant    TEXT
);
CREATE INDEX printed_by_student ON printed(sid, slug);
```

Written at build time from the manifest, which already records seed, version
and variant per paper -- the record is a second reader of a file that exists.

**Printed is not attempted.** The build cannot know who was in the room.
`SELECT COUNT(*) FROM printed WHERE sid=? AND slug=?` counts papers handed out,
which over-counts anyone absent. The **gradebook** -- pass, no pass, absent --
is a separate table added in a later stage, and until it exists the tool must
say "printed N times", never "attempted N times".

Tracking still does **not** feed back into printing (section 10). There is no
retake cap to enforce.

### 12.5 Google Forms

**printit owns the slots it can derive, and nothing else.**

| item in the form | owner |
|---|---|
| banner image, theme, title, description | instructor |
| email collection, response receipt | instructor |
| "You are selecting *three* skill(s)... on *NAME* on *DATE*" | **printit** |
| "I understand that I am selecting skills for *DATE*" | **printit** |
| "This form is due by *DUE*" | **printit** |
| "How do I decide what to choose?" -- grade cutoffs, syllabus links | instructor |
| "Choose At Most *THREE* Skills" and its options and validation | **printit** |

The "How do I decide" block holds grade cutoffs, a link to the skill list and a
link to the syllabus. No field in printit knows any of it, and it changes on the
instructor's schedule. A push that regenerated the form would delete it every
week.

If a slot printit owns has been deleted from the form, push **stops and says
so** rather than recreating it -- because recreating changes an id.

**Responses are stored against `questionId`.** That single fact drives the rest:

- recreating the *form* changes the `formId`, so the URL dies and every response
  already collected is stranded on a form nobody can reach, along with the
  banner image and every per-form setting;
- deleting and recreating a *question* changes its `questionId`, so answers
  already given stay attached to the old question. The skills question changes
  its options every week; recreating it weekly would leave fifteen half-empty
  columns in the export by December.

So the ids are recorded once and patched forever after:

```toml
[form]
id  = "1FAIpQLSc..."
url = "https://docs.google.com/forms/d/e/.../viewform"

[items]
selecting_for = "3f8a1b2c"
confirm_date  = "7d2e4a91"
due_notice    = "1a9c3e70"
choose_skills = "5b6f8d22"   # options rewritten weekly, id never
```

A push is one `batchUpdate` of `updateItem` requests. No creates, no deletes.

**Two entry paths.** *Adopt* reads an existing form, lists its items and asks
once which is which -- that is how an instructor's banner and wording survive.
*Create* builds one when there is no form yet and records the ids it gets back.

**To verify against the API reference before implementing**, rather than guess:
the exact shape of `updateItem` and its `updateMask`; whether `forms.create`
accepts only `info.title` at creation with everything else needing a follow-up
`batchUpdate`; and how "at most N" validation on a checkbox question is
expressed.

**Whether the Google Cloud path is open at all** is a university question, and
worth answering before writing any of it. Signed in on the institutional
account: create a project at `console.cloud.google.com`; then under
APIs & Services -> OAuth consent screen, check whether **Internal** is offered
as a user type. Internal apps in a Workspace skip Google's verification review
entirely, which is the difference between an afternoon and a fortnight. Then
enable the Google Forms API in the Library, and create an OAuth client ID of
type **Desktop app**.

A Workspace admin can also restrict third-party app access domain-wide, which
only shows up at the first token request.

**Settled 2026-09-20: the institutional account cannot create Cloud projects,
so Apps Script is the primary path and the Forms API is the alternative.** The
existing Control Center is already an Apps Script that writes this form, which
is proof the permission exists and that the approach works.

A **script bound to the form**, deployed as a web app executing as the
instructor, needs no Cloud project, no OAuth client, no consent screen and no
token. printit calls it over HTTPS.

**Correcting a claim made while reaching that conclusion:** a CLI *can* do an
interactive browser login. The OAuth installed-application flow opens the
system browser and catches the redirect on `http://localhost:<port>`;
`InstalledAppFlow.run_local_server()` is a dozen lines. What a CLI cannot do
without a Cloud project is *have an OAuth client to log in with*. So the web
app authenticates with a shared secret not because interactive login is
impossible, but because the alternative needs the unavailable thing. If the
access situation ever changes, this reverses.

A web app that can rewrite the form is a capability URL. It must require a long
shared secret in the request body and reject anything without it; the secret
lives in the course's `secrets/` directory.

**Deployment is not copy-and-paste.** `clasp`, Google's Apps Script CLI, clones
a script to local files and pushes them back:

```
clasp clone <scriptId>   # once
clasp push               # after every edit
clasp deploy             # publish a new version of the web app
```

The script source then lives in the printit repository as ordinary files, in
git and reviewable in a diff. `clasp login` uses clasp's own OAuth client, so
it needs no Cloud project -- but it does need the Apps Script API switched on
at `script.google.com/home/usersettings`, a per-user toggle an admin can lock.

**The CSV fallback survives the Sheet.** Google Forms exports responses to CSV
from the form itself, so the import path in 4.2 keeps working with no
spreadsheet in the picture.

**The CSV import path stays permanently.** Scopes lapse and admins change
policy; the CSV path is the whole pipeline minus one adapter and it works
today.

### 12.6 The GUI

**Written 2026-09-02 as "the seating chart", and not revisited while the CLI
grew to 22 commands.** The instructor's question on 2026-09-21 -- why is none
of this recorded -- was fair. What follows is derived from two sources rather
than from imagination: the CLI as it now stands, and the menu the retired
Control Center actually offered.

#### It is the front end for the whole tool, not a seating widget

The Control Center was a Google Sheet an instructor sat in front of all term.
Replacing it with a CLI plus one drag-and-drop page replaces the seating menu
and nothing else. Every other thing that used to be two clicks is now a
command line with a `-c` flag.

<!-- audit-ignore -->

**Load-bearing rule: the GUI calls the same functions the CLI calls.** No
second implementation of anything -- not the roster join, not the selection
modes, not the push payload. On 2026-09-21 the same fix had to be applied
three times in one day because three code paths did the same job (`"-w"` in
option definitions vs ` -w ` in messages vs `` `-w` `` in a table;
`_deploy_and_record` vs `form attach`'s own copy; `form connect` missing both).
A GUI that reimplements any rule doubles that problem permanently. The CLI
command bodies should be thin wrappers over functions the web handlers also
call, and anything currently living inside a `@click.command` body that the
GUI will need has to move out first.

#### The views

Derived from the CLI surface and the Control Center's menu. "CLI" names the
command that already does the work.

| view | what the instructor does | CLI |
|---|---|---|
| **Roster** | an editable table: the name, what it prints as, section, email, ids; mark dropped and undo it; import a class list and see the merge before it lands | `roster import`, `roster drop`, `roster restore` |
| **Skills** | toggle which skills are open for retake; set the assessment's name, date, due time, and the choose/limit rule; see the exact wording the form will show; push it | `skills open`, `skills set`, `skills preview`, `form push` |
| **Responses** | who has answered, who has not, what they chose; the addresses that matched nobody; pull into the roster | `form pull` |
| **Seating** | drag students between seats; randomise; swap two; see version letters and empty seats | *(none -- see below)* |
| **Print job** | the staging area for one sitting: each student's choices with a manual override, skills appended for everyone, defaults for non-responders, per-skill variant, title and date, extras, keys, names; preview the draw; build; open the PDF | `build`, `build --preview` |
| **Runs** | past runs: when, which seeds, drill in, reprint, delist | `record runs` |
| **Progress** | each student against each skill: passed, passes, attempts | -- |
| **Scans** | read marked papers back in and grade them | -- |
| **Cold call** | pick a random student, pick several, refresh the call list with its skip flags | *(none)* |
| **Setup** | create or attach the form, map items, course settings, bank path | `course init`, `form create`, `form attach`, `form map`, `form add-items`, `form connect` |

The last column is the useful part of this table: most of the GUI is a face on
code that exists and is tested. The two rows with no CLI are the genuinely new
work, and **seating is one of them** -- `randomizeSeating` and
`shuffleSelectedStudents` were Control Center features that have no printit
equivalent at all. That is worth knowing before estimating.

#### One name per view

Kept in one place because it has already drifted twice. The staging table
said **Skills** after the tab became **Update form**, and **Assessment**
after the app had settled on **Print job** -- both because a view was renamed
in the plan and not in the nav, or the reverse.

`Print job` beats `Assessment` for 8d on a collision: Update form already has
a panel headed "The next assessment", and `availability.toml` an
`[assessment]` table, and those are a different thing. "Print job" names what
comes out of it.

**The nav is the authority. When a view is renamed, this table is renamed in
the same commit.**

#### Settled, and what each one cost

All three decisions are closed.

**The preferred name prints, everywhere** (2026-10-01). Above.

**Responses is not a tab** (2026-10-01, built). The pull is Print job's
first card, so the weekly flow reads top to bottom on one page: pull, see
the choices, override, build. The failure modes the pull has of its own -- an
address matching nobody, a skill no longer in the bank, a response for
another day -- are reported in that card rather than given a view. "Who has
not answered" comes back as its own thing when *email missing students*
exists, which is the part of responses that is genuinely not about
assembling a print job.

The card reports counts and every reason a student might not get the paper
they asked for, and deliberately does not list who chose what -- the table
two cards down is the view of that, and two views of one set of facts is
the reason this is not a tab.

**Simply-print is a mode** (2026-10-01). A segmented control at the top of
the tab, chosen over radios, a dropdown-in-a-sentence and a checkbox by
rendering all four in the app's stylesheet and looking at them.

Segmented wins because the app already contains that control -- the view
nav is one -- so it adds no vocabulary, and switching mode changes which
cards exist, which is what a nav-shaped control is for. It is deliberately
smaller than the real nav, with "This run:" in front of it.

The layout half was only half the problem. `simply_print` replaced each
student's choices and killed `default_when_missing`, while the job folder
carried all three keys regardless -- so a saved `publication.toml` could say
one thing and hold settings for the other. `publication_text` now writes
only the half the mode uses, and a draft written before the mode existed
says which it is by whether `simply_print` has anything in it.

#### What the Print job table has to say for itself

Settled 2026-10-01, from six reports against the first build of the view.
Each is a case of the screen having to state a rule rather than the
instructor having to hold it.

**A default is shown by being selected, not by being listed twice.** The
version dropdown had a nameless first option carrying the seat's letter and
then the letters themselves, so a student at A saw "A" twice. The outline
already says when a row is off its default. A `↺` beside the control --
`U+21BA`, the glyph in common use -- appears only when it is, with one of
the same at the head of the column. Choosing the seat's own letter clears
the pin rather than recording one that changes nothing, so "off default"
and "has a pin" cannot drift apart.

**A new version is added where versions are chosen.** Each dropdown offers
the letter after the highest in play: `+ E`, and once E is taken, `+ F`.
Next-after-highest rather than first-unused, because a chart of A, B, D
would otherwise offer C, which reads as a mistake rather than as a new
version. Both ends had to agree -- the save stopped requiring a letter the
chart already had, and `assemble.versions_for` draws seeds for whatever the
pins name.

**Reset is an edit, not a command.** "Reset this print job" fills the draft
with the server's defaults and leaves saving to Save, so Discard puts the
old job back. A button that wrote the file directly would be a way to lose
a job in one click.

**A view that caches has to say when it has stopped.** Print job loaded
once per page load, so a name saved in Roster never reached it. It reloads
on every visit now, keeps any unsaved draft, and names what changed. The
original request was for a note saying the changes would merge at the next
Save; there was never a merge to wait for -- saving was simply the only
code path that re-fetched.

#### The roster is the course; choices belong to one sitting

Decided 2026-09-22, on seeing the first roster table. It had a "Chose" column
showing each student's current selections, which was wrong twice over: what a
student picked belongs to *one assessment*, and the roster outlives every
assessment. A column that changes meaning each week does not belong in the
table that holds who is enrolled.

So the **Roster** view is the course overall -- who exists, what they are
called, which section, who has left -- and never mentions an assessment.

Choices live in the **Print job** view instead, which is a staging area for
one sitting rather than a form with a Build button on it: each student's
choices shown with a manual override, skills appended for everyone, defaults
for whoever did not respond, the per-skill variant, the title and date, the
extras. It is where an instructor assembles the paper before printing it,
which is what `importStudentChoices` did in the Control Center.

#### What the GUI needs that the CLI does not

1. **Variants, per skill, in the print job view.** Eight of mat-106's
   twenty-nine outcomes declare variants, and the labels are not guessable:

   | skill | variants |
   |---|---|
   | `R2` | `beginning`, `add_sub_frac`, `mult_div_whole`, `int_pemdas` |
   | `W4`, `W4-E`, `W5` | `multiplication`, `no_multiplication` |
   | `W7` | `terminating`, `no_terminating` |
   | `N3`, `N4` | `any_method`, `listing_only` |
   | `D2` | `repeating`, `no_repeating` |

   On the command line this is `[variants] D2 = "no_repeating"` in
   `publication.toml`, typed from memory. In a GUI it is a dropdown that has
   to be **populated from the bank**, which means enumerating
   `Bank.variant(slug, seed)` across the print tier and caching it -- there is
   no declaration to read, the label is written into each version's data by
   the generator wrapper. `Bank.seeds_with_variant` already refuses a variant
   with no printable version; the GUI should never offer one.

2. **A job is currently a folder.** `build` reads `publication.toml` from a
   directory. A GUI has no directory -- the instructor sets options in a form
   and presses Build. Either the GUI writes a job folder and calls `build`
   on it (keeping one code path and leaving a folder to inspect, which is
   also what `--replay` needs), or `build` grows a non-folder entry point.
   **The first.** The folder is the artifact that makes a run reproducible,
   and inventing a second way in is exactly the duplication the rule above
   forbids.

3. **Long operations.** `build` compiles LaTeX and `form pull` crosses the
   network. Both need progress and a readable failure, not a spinner that
   ends in "something went wrong". The CLI's own messages are already written
   for a human; they should be streamed rather than rewritten.

4. **Confirmation before anything outward-facing.** `form push` rewrites what
   students see. The CLI has `--dry-run`; the GUI needs the equivalent as a
   visible diff, not a checkbox.

#### The form's fixed wording, and who owns it

Decided 2026-09-29. printit creates the form, so **printit is the source of
truth for every word on it** -- not whatever an instructor last typed into
Google. The alternative loses the wording the first time a form is rebuilt,
silently.

`src/checkit_printit/boilerplate.py` holds it: the form's title and
description, the heading above each item, and any section that stays the same
all term. The wording that changes weekly -- which assessment, which date,
which skills -- is still derived in `form.payload_for` and rewritten on every
push.

**Two items are required and appear on every instructor's form:**

| | why it cannot be left out |
|---|---|
| `confirm_date` | the scoping key. `form pull` decides which assessment a response belongs to by reading the date a student confirmed. A form without it cannot be read back at all |
| `choose_skills` | the question itself |

Their *wording* is editable; their *presence* is not. Everything else -- the
form description, "What am I selecting skills for?", "When is this form
due?", "How do I decide what to choose?" -- is optional, and an instructor
may reword it or leave it out.

The item titles used to live in `appsscript/Code.gs`, where `addItems_`
created them. They are in `boilerplate.py` now and passed across in the
payload, because a title in two places is a title that will disagree with
itself.

**Not yet supplied:** the text of "How do I decide what to choose?". It is on
the live MAT 106 form, added by hand, and printit has never had it. The
preview shows the section with a dashed border saying so, rather than
rendering it empty, which would read as "this section is blank on the form".

#### Still to build, in this area

**A boilerplate editor.** Change the fixed wording, and choose which optional
sections to include. Touched at the start of a semester or in an emergency,
which is the whole problem with placing it -- see below.

**Creating a form from the app.** `form create` exists on the command line
and does the whole job: form, bound script, deploy, items, recorded ids. The
GUI should offer it rather than sending an instructor to a terminal, with
somewhere to say which Drive folder it goes in.

#### Where the boilerplate editor goes

The question is real: it is edited perhaps twice a year, so a tab of its own
overstates it, and a sub-tab inside Update form buries a rare thing inside a
weekly one.

**Recommendation: it lives in Setup, with a door from the preview.**

Setup already exists on this roadmap for the things done once -- `course
init`, `form create`, `form attach`, `form map`, the bank path. The
boilerplate has exactly that cadence, and grouping by *how often you touch
it* is what keeps the weekly views uncluttered.

The second half matters as much. An instructor notices the wording is wrong
**while looking at the preview**, not while thinking "I should visit Setup",
so the Form preview panel carries an `edit wording` link that opens it. Put
it where the cadence says; provide a door where the need arises.

The tempting alternative -- make the preview itself editable, click a
sentence and change it -- is worth naming and rejecting. The preview is
consulted every week before a push, and making it editable invites an
accidental edit to something meant to be stable. Worse, it erases the
distinction the design is built on: some of that text is rewritten by every
push and some is not, and a preview where everything looks equally editable
teaches the opposite.

#### Architecture, unchanged

A local web app with a Python backend, bound to `127.0.0.1` and never
`0.0.0.0`, editing the same TOML files the CLI reads. It carries names, SIDs
and email addresses, so it lives outside every repository along with
everything else in `~/CheckItPrintIt/`.

Correcting the 2026-09-02 note again: it said "everything stays in git", which
is wrong for exactly that reason.

#### Staging within 8

Ordered so that the riskiest unknown is not last, and so each slice is usable
on its own:

| | slice | why here |
|---|---|---|
| 8a | **done** -- the shell: serve a course, switch views, read-only everywhere | proves the backend reads what the CLI reads |
| 8b | **done** -- **Roster** table, editable, with drop and restore | the most-wanted, and write-round-trip is the thing to get right early |
| 8c | **done** -- **Update form**: the open skills, the assessment, the wording preview, the push | replaces the most tedious CLI sequence |
| 8d | **done** -- **Print job**: choices with overrides, defaults, variants, then build | the first view that needs the bank, not just the course |
| 8e | ~~**Record**~~ -- became Runs, Progress and Scans; **see section 14**. The response pull landed inside the Print tab instead of becoming one | |
| 8f | **Seating**, drag and drop, plus randomise and swap | genuinely new code; the interaction needs prototyping rather than specifying |
| 8g | **Cold call** | new, and the smallest |
| 8h | **Setup**: create or attach a form from the app -- **done**; the boilerplate editor still to come | both are start-of-semester work, and the editor needs somewhere the weekly views do not |

Seating is deliberately not first. It was the whole of this section for three
weeks, it is the only view whose *feel* cannot be settled in writing, and it
is the one an instructor can most easily do by hand in the meantime.

#### Open

1. **Does the roster table edit in place, or stage a diff?** Editing in place
   is nicer; `roster import` already shows a merge before it lands, and a
   table that silently rewrites `roster.toml` on every keystroke removes the
   one moment where a bad import is catchable.
2. **How is a print job's history surfaced?** `record.db` knows every run, and
   the job folders are on disk. The GUI could list past runs and offer
   `--replay` on any of them, which would make reproducibility a button
   rather than a documented procedure.
3. **Multiple courses at once**, or one at a time with a switcher. An
   instructor running 820 and 830 as separate courses will want to see both.
4. **Email missing students** was a Control Center feature with a templated
   body and `$FIRSTNAME`-style substitutions. Deferred, but it is the obvious
   home for it once Responses exists, and the variable set is recorded in
   12.10.

### 12.7 Staging

| stage | state | ends with |
|---|---|---|
| 6a course + roster | **done** | one roster, jobs resolving it, class lists merging on id |
| 6b availability | **done** | a list the form push and the print job both read |
| 6c print record | **done** | SQLite written from the manifest; queries read-only |
| 7a form write | **done, verified** | create-or-attach, then push the derived slots |
| 7b form read | **done, verified** | responses pulled to the day's skills; CSV kept |
| 8 GUI | | a front end for the whole tool: roster, skills, responses, print job, record, seating, cold call. See 12.6 |
| 9 gradebook | | pass / no pass / absent, and the table editor for it |

### 7a ran against a real account on 2026-09-21

`form attach`, `form add-items`, `form push --dry-run` and `form push` all
work end to end against a scratch form on the institutional account. Seven
bugs were found, in code that had 220 passing tests. Full account in
`CODEBASE_NOTES.md`, "Stage 7a, against a real Google account".

**The largest open risk in this design is now closed.** An anonymous POST
from a terminal holding no Google credential is accepted, so the
open-with-a-secret transport works on this domain. The 403 that suggested
otherwise was an unauthorized script, not a policy block.

Neither predicted failure happened. `_deployment_id` parsed correctly first
time, and `.clasp.json` landed where `script_id()` expects. What actually
broke was elsewhere:

- `--type form` is not a type; it is `forms`. And `push-files` is not a
  command; it is `push`. Untestable at the old seam, because the tests
  assert on what the deployment replies and never on the argv.
- **clasp exits 0 on a refusal**, so `check=True` passed an invalid `--type`
  straight through.
- **`clasp create-script` overwrites `appsscript.json` in `--rootDir`**,
  dropping the `webapp` block, so the deployment had no entry point. `attach`
  was already immune because it re-stages over the cloned files.
- **Apps Script 404s a live deployment at random** -- measured at one in
  three. `call()` retries 404 and timeout, never 401/403.
- `--title` names the script project, not the form. A `rename` op fixes it at
  creation only; a push must never touch the title.

**Still to do in 7a:** `form create` has not been run to completion, only
`form attach`. A newly created form needs **one browser visit to authorize
the script** before any call succeeds -- the manual path gets this free from
the editor's deploy flow, and the clasp path does not. `form create` should
print the URL and wait.

### 7b read a real response on 2026-09-21

Checkbox answers are arrays, `getRespondentEmail()` is populated, and the
option text round trips as `SLUG - description`. Matching, date scoping and
the refusal-to-write were all exercised against that one live response, not
only against fixtures. See "7b against a real response" in the notes --
including the submission whose three dates (submitted 9/21 Eastern, recorded
9/22 UTC, for the assessment on 9/25) make the case for confirmation-based
scoping better than this document did.

### What 7b needed

Responses are scoped to an assessment **by the date the student confirms**,
not by a timestamp window -- see 12.10. The confirmation checkbox exists for
that. Latest response per student wins. Both behaviours come from the retired
script and are already matched by hand in the 2026-09-18 run.

The script needs a `responses` op returning email, timestamp and choices;
printit maps email to a student through `Student.all_emails()`, which is why
addresses accumulate rather than replace.

### 12.11 The seating tab, specified (2026-10-04)

Four ways of *rendering* a chart were drawn and all four rejected. What is
wanted is a way of **drawing a classroom** -- a seating-chart tool that
would work for any class anywhere, not a view of `seating.toml`.

#### What it is

A canvas per section, seen from above, showing an empty classroom before
anybody is placed in it.

* **Background shapes** are dragged on to match the real room: 2x2 tables,
  1x2, 1x3, single desks, hexagons, trapezoids, circles, ovals. A single
  desk is a 1x1 rectangle with one seat.
* **Each shape carries default seat positions**, and there is a mode for
  dragging those positions around, because a real table has a side against
  a wall.
* **Name cards** drop onto seats. First name on the top line, surname
  below, so the card is squarish rather than a long strip -- which is what
  sets the spacing of the whole room.
* **Group designators** -- a table number, a color, a letter -- sit in the
  middle of a table, or float in the gap for a room of loose desks. A shape
  can carry a label and a standalone label can be dropped anywhere.
* **Version letters toggle**, because this goes on the projector.
* **Sections are separate charts**, chosen from a picker, and the
  instructor says which section's papers print first.

#### Who owns what

The division is the instructor's, and it is the whole model:

| | owns |
|---|---|
| a desk or table | the seat positions on it |
| a group | its label, the version letters of its seats, and where it comes in the print order |
| a seat in no group | behaves as a group of one, in every one of those rules |

That last line is what makes a room of loose desks in rows work without a
second code path.

#### Versions are chosen here

The seating tab decides the version letters and writes them down.
`alternate()` stays only as the fallback for a chart this tool did not
write. Within a group the letters are dealt without repeats; where a group
is larger than the bag of letters, the repeat is placed as far away as it
can be. There is **one bag of letters for the whole course**, across
sections: a group of six with six available gets one of each, a pair gets
two of the six.

This is graph coloring -- see the notes of 2026-10-04 for the algorithm
and the measurements behind each part of it.

#### Print order is a mode

A mode that brings up the print order, in which the instructor clicks the
groups one at a time in the order they will hand papers out; in an
ungrouped room, individual students. Sections are ordered too, and the
stack is all of one section and then all of the next.

A group left unplaced is a **warning, not a refusal**: the instructor may
go ahead knowing that anyone unmarked will probably be printed out of
order.

#### Two files, and why

`seating.toml` stays exactly as it is, for CLI users and for the build.
The seating tab produces it. The app's own data -- geometry, shapes, seat
anchors, groups, the canvas size -- lives beside it in `room.json`.

JSON because it is deeply nested and nothing hand-edits it. Not SQLite,
despite the rule that tool-authored state goes there: that rule is for
something unbounded, queried, and written by two processes at once, and
this is one small document read whole and written whole, worth diffing
when a room changes.

A room holds each student's **id**; names appear only in the generated
chart. `seating.toml` is the last name-keyed join in the tool, and a room
cannot be broken by a rename.

**No migration.** The live 106 charts are being redrawn by hand, which the
instructor preferred to a converter nobody would run twice.

#### Staging

| | | |
|---|---|---|
| 1 | the model, the coloring, the chart writer | **done** 2026-10-04 |
| 2 | the canvas, read-only: shapes, cards, labels, section picker, toggles, zoom | **done** 2026-10-05 |
| 3 | dragging -- cards between seats, shapes around the room | **done** 2026-10-05 |
| 3b | the sizing pass: fit to content, a projector mode, click-to-place | **done** 2026-10-05 |
| 4 | the shape palette, and dragging seat anchors | next |
| 5 | the print-order mode | |
| 6 | randomise, and swap two | |

Stage 1 was invisible and decided everything after it. Stage 2 is
projectable on its own.

Stage 3 settled two things the plan had left open.

**The tab is three modes, not one canvas with handles.** *View* moves
nothing and is what goes on the projector; *People* drags names between
chairs; *Desks* drags the furniture, with the name cards inert so a table
can be grabbed through the people sitting at it. The mode is named on the
canvas element, so "cards are not targets while desks are being moved" is
one line of CSS rather than a condition at every handler.

**Save writes the chart as well, when that is safe.** A room nothing
reads is a toy -- `seating.toml` is what the build opens. So saving the
tab rewrites it, under two conditions: somebody has to be seated, so an
untouched course cannot replace a term's chart with an empty one; and the
chart on disk has to be one this tab wrote, which `to_toml` marks and
`seating.was_generated` reads. A chart that came from an import or a text
editor is left exactly alone and the save bar says so **before** the
button is pressed. That is the 10-02 lesson made structural.

**Three modes, and a fourth that is not a mode.** View, People and
Desks are what the canvas lets you move. *Present* is not one of them:
it is the same View on the whole screen with every toolbar gone,
because the limit on how large a name can be drawn is pixels of screen
and the chrome was a third of them. Escape leaves; the arrows change
section while presenting.

Sizing is the thing that nearly sank the tab and it was three separate
faults, not one: fit scaled a declared canvas twice the size of the
furniture in it, the card's type filled under half the card, and the
banner took a quarter of a short window. All three are measured in the
notes of 2026-10-05, along with why counting characters is not the same
as measuring text.

This also opened a hole that had been harmless until now: `set_dropped`
cleared the chart and knew nothing about `room.json`, so the next save of
this tab would have walked a dropped student back onto the printed list.
A drop now empties their chair in the room too. See the notes of
2026-10-05.

### 12.12 The seating app: a shell of its own (2026-10-06)

Everything in 12.11 assumed the seating tab was a page with controls
arranged around a canvas. It is not going to be that. The instructor's
framing, which settles the whole design:

> The fullscreen version **is** the regular version, except without
> checkit-printit's header bar stuff.

So the seating tab is **an application that happens to be embedded in
checkit-printit**. Its canvas runs edge to edge, its own controls float
over that canvas, and Present does exactly one thing: hide the host's
header. Nothing else moves, nothing else changes size, nothing appears
or disappears.

That is also what makes the eventual spin-off cheap. Seating and
Up Next are to become their own application; if every control already
lives inside the seating component, extracting it is deleting the host
header rather than rebuilding a UI.

#### Where this came from

Two canvas editors were read closely, because they have solved this:

* **Excalidraw** -- tools top centre, zoom bottom left, and a
  **contextual property island** that appears only when something is
  selected. The lesson taken: properties are about the selection and
  nothing else. There is no settings panel.
* **tldraw** -- tool strip **bottom centre**, style panel to one side,
  zoom bottom left, app menu top left. The lesson taken: the overall
  placement, and that every panel is a small floating "island" over a
  full-bleed canvas rather than a region docked into a page.

**Radix Colors** supplied the color model, and the classroom tools
surveyed in the notes of 2026-10-05 supplied click-to-place.

#### The islands, and what each one is for

Five fixed positions. Each answers one question, and nothing lands in a
position because there was room for it there.

| where | question it answers | holds |
|---|---|---|
| top left | *which room am I in, and is it saved* | the section switcher, and -- only when there are unsaved changes -- **Save** and **Discard** |
| top right | *how is the room being shown* | version letters, group labels, **Up Next**, **Projector mode** |
| bottom left | *what am I looking at* | zoom out, the percentage (click to fit), zoom in, **fullscreen** |
| bottom centre | *what am I doing* | the mode rail, which furls to the current mode below ~760 |
| just above the rail | *what is selected* | one thin strip, described below |
| bottom right | *one more of these* | the plus: a group in Groups, a seat in Seats |
| the right edge | *who is not seated yet* | the unseated rail, in People mode |

Three corrections to the first draft of this table, each from using it.

**The hamburger is gone.** It hid two switches, and two switches are
cheaper to show than to hide.

**Top right is not Present alone.** Getting the chrome out of the way
and putting the room on a wall are the same question, so the display
switches live there with it -- and fullscreen does not, because that is
a question about the view and belongs with the zoom, which is where
tldraw and Miro both keep theirs.

**No unsaved-changes dot.** It announced a state that the presence of
Save and Discard already announces.

**Up Next is not a mode.** The rail's test for belonging is whether an
entry changes what a click on the canvas means; Up Next never did, it
changes what the room is *showing*. It is a switch in the top right
with the other two, and it works while projecting because that island
is the one that survives.

**The accent color means one thing: the state you are in.** Not "look
at me". A switch that is lit while unused has nothing left to say when
it is used. The plus is the one exception, because it is the only
control that makes something that was not there.

#### The camera

The canvas does not scroll. There are no scrollbars at any size: the
room is panned by taking hold of the paper, and zoomed with the zoom
island. Two numbers say where the view is -- a scale, and a pan offset
in screen pixels from where Fit would put the room -- and one function,
`freeBand`, returns the rectangle the room is both **fitted into and
centred in**. Those must be the same rectangle or the room is neither.

Fit resets both. Zoom holds the middle of the window rather than the
room's centre, so what you were looking at stays in front of you.

**Save sits with the document, not with Present.** What is saved is this
room, and the room's identity -- the menu, which section -- is top left.
Figma puts the file name and the file's own menu in the same corner for
the same reason. Save is also **absent until there is something to
save**, which is the real answer to "why is that button there": most of
the time it should not be.

**Zoom is bottom left and Present is top right, at every width.** An
earlier draft moved zoom into the top right when the window got narrow,
so the same two controls were in two different places depending on the
window. The fix is not to move the control, it is to make the rail
narrower: below 760px the rail drops its words and keeps its icons,
which leaves the bottom edge wide enough for both.

#### The mode rail

Six modes, all of them visible at once, because the point of a rail is
that the whole verb list is the rail:

| | |
|---|---|
| **View** | nothing moves. The projector |
| **People** | names between chairs |
| **Groups** | the furniture: add, move, resize, turn |
| **Seats** | where the seats sit on a group, how many, and which group they belong to |
| **Order** | the order papers are handed out in |
| **Up Next** | pick somebody |

Modes only. **Shuffle is not on the rail** -- it is an action, and an
action among modes is a category error; it moves to the menu. The same
test keeps the rail honest as features arrive: if it does not change
what a click on the canvas means, it is not a mode.

#### A desk is a frame, and rotation lives in the chairs

A desk on the canvas is a wrapper carrying its position, its size and
its angle, with its silhouette, its eight resize grips, its rotation
handle and its nine label anchors inside it. They move and turn
together because they are one element's children -- the alternative,
a list of things to also update when a desk moves, is a list that
gets missed, which is how the anchors came to stay behind.

`shape.w`, `shape.h` and `shape.angle` are all optional and all
additive, so `room.VERSION` does not move.

**Rotating rewrites the chairs' own offsets** rather than storing an
angle for everything downstream to apply. `room.seats_of`, the
neighbour distances, the coloring and `seating.toml` therefore need
to know nothing about rotation: a seat is always simply where it says
it is. `angle` is kept only for the silhouette and for the next turn.

Resizing scales the chair offsets by the same factor, so a widened
table spreads its people out. It does not add chairs; adding one is a
button, and finding two new ones after dragging for room is a
surprise.

#### Bare, which is not the same as presenting

The top right holds two buttons, not one: an eye that hides every
control, and Present. They belong together because both are about how
the room is being shown rather than what is in it -- and it means
Present is not alone in an island of one.

The two states are separate. Presenting turns bare on; turning bare
off while still presenting is how every mode stays reachable on a
projector. **The top-right island is the one thing bare does not
hide**, because a mode with no visible way out is a trap. It rests at
low opacity when nothing is happening and returns on any movement.

The stage bar shows only while bare: with the islands back it is a
second answer to the same question.

#### Up Next, which used to be Cold call

The Cold call tab is **deleted**, not moved. Folded in as a mode it
stops being a list of names beside the room and becomes what it
actually is: **the room, with one chair lit up**. The chart is already
on the projector; picking somebody should light a chair, not replace
the screen with a different view.

Renamed because the students are looking at it. "Cold call" names the
teaching technique from the instructor's side and reads, to the person
whose name is on the board, as being put on the spot. **Up Next** is
the default -- it describes a state rather than pointing at somebody,
and it is short enough for the rail. "Who's Up" is the alternative and
is a one-word change.

#### The selection strip

The contextual panel in the first mockup was a tall island on the right
with four labelled sections, and it was wrong in both sizes. Most of it
was not needed:

* **The label-position picker is deleted.** Selecting a group already
  reveals the anchor points on its shape. Dragging the label pill onto
  one is the control; a nine-cell grid that does the same thing is a
  second way to say it.
* **Six color swatches in a row are deleted.** One filled dot showing
  the group's color, which opens the swatches when clicked.
* **The label does not need a text field and a heading.** The heading
  *is* the label; click it to edit it.
* **The print position does not need the words "Prints 2nd of 7".**
  `2/7`.

What is left is one thin strip above the rail, in both sizes, with no
expanded state:

```
  ●  Table 2            4 seats    2/7
  ^  ^                  ^          ^
  |  click to rename    read-only  print position
  color
```

Nothing in it needs opening, so there is no sheet to pull up and no
panel to collapse, which is what made it awkward at 515px.

#### The unseated are students, not a status line

They were a strip along the bottom labelled "2 standing". Two faults.
The strip said in words -- in slightly odd words -- what the design
should carry; and the cards in it were a different shape from the cards
in the room, so nothing about them suggested that one could be dragged
into a chair.

The rule: **an unseated student is the same object as a seated one.**
Same card, same size, same two lines. The only difference is that it
has no group, so it is drawn in the grey of the palette -- the same
three roles at zero chroma. Being grey *is* the status; no sentence is
needed.

It moves to **the right edge**, as a vertical rail, because a class
list is a list and because the left corners are already spoken for by
the document island and the zoom. The rail **has no header**, and
**hides itself when everybody is seated** -- except while a name is
being dragged, when it reappears as a drop target, because that is
exactly when somewhere to put a person is needed.

#### Under the menu

Everything that is neither a mode nor frequent:

* **Paper** -- the canvas color
* **Show** -- version letters, group labels
* **Deal the version letters again** -- the shuffle
* **Write the chart now** -- `seating.toml`, for when Save left it alone
* **Discard changes**
* **Room size**
* **Keyboard shortcuts**

The rule for the menu is the inverse of the rule for the rail: if it
changes what the canvas *is* rather than what a click *does*, and it is
not done every few minutes, it belongs here.

#### Color: one hue, three jobs

A group owns a hue. Three shades are derived from it, and they are
derived rather than chosen so that every group is the same design in a
different color. Radix Colors' twelve-step scale gives each shade a
job; the three the room needs are:

| drawn thing | job | step |
|---|---|---|
| the table or desk | the largest area, so it must recede | **3** surface, **6** border |
| a name card | sits *on* the table, so it must lift off it | **1-2** surface, **7** border |
| the group's pill | smallest, must be found instantly | **9** solid, white text |

Generated in OKLCH with lightness and chroma fixed per role and only
the hue varying -- `oklch(0.935 0.048 var(--hue))` and so on -- which is
about ten lines of custom properties and holds up on a light or a dark
canvas. An ungrouped seat uses the same three roles at **zero chroma**,
which is what makes the unseated rail consistent for free.

Color is never the only carrier: the pill still says "Table 2".

#### The canvas is a document; the chrome is a tool

The canvas gets its own light paper -- a very pale grey by default,
with other papers in the menu -- while the islands stay dark. That is
Figma's split, and it earns itself here twice over: it separates the
thing being made from the thing making it, and a light room is what a
projector wants.

It does mean **two visual languages inside checkit-printit**: Seating is
a canvas tool, the other tabs are forms and tables. That is deliberate,
and it is also the seam the spin-off will be cut along.

#### The label pill

Its silhouette is the point. Everything else in the room is a rounded
rectangle, so the one thing that is not reads as a label rather than as
another object: a full pill radius, solid, uppercase, and about 16 room
units rather than 11. Nine anchors per shape -- eight around the
perimeter and the centre -- shown as dots when the group is selected,
set by dragging the pill onto one. A group with no anchor set keeps the
present behaviour and floats at the middle of its seats, which is what
a room of loose desks needs.

#### What is narrow, and what changes

One breakpoint, at 760px. Below it:

* the rail keeps its icons and drops its words;
* the section switcher folds into the menu;
* the unseated rail narrows to one card wide;
* **nothing moves to a different corner.**

Zoom and pan is the accepted answer for a small pane, confirmed by the
instructor: the room is worked on zoomed in and read at Present. The
canvas does not try to show twenty-five legible names in 515px, because
it cannot.

#### What has to exist first

**There is no selection model.** Nothing in the app can currently say
"this group is selected", and the selection strip, the color dot, the
label anchors and the print position all hang off it. It is the
backbone and it comes before any of the features that need it.

#### Model changes, all additive

`group.hue`, `group.chroma`, `group.label_at`, `section.canvas.paper`.
Old rooms load with sensible defaults, so `room.VERSION` does not move
-- a version bump is for a change that would make an old file read
wrongly, not for one that makes it read incompletely.

**A color is two numbers and never three.** `hue` says which color,
`chroma` says how vivid, and lightness is not stored at all. The three
shades a group draws are built at fixed lightnesses chosen so a name
is readable on the card and the card is visible against the paper, on
a screen and on a projector and in print. Let the instructor set
lightness and the first dark color anybody picks makes a table whose
names cannot be read from the back of the room. The custom-color slot
therefore opens the platform's own `input type="color"` -- a visual
field, hex, RGB and an eyedropper, none of it to maintain -- and keeps
the hue and the chroma of whatever comes back.

#### Staging

| | | leaves it working |
|---|---|---|
| **A** | the shell: islands, mode rail, Present = host header off | **done** 2026-10-06 |
| **B** | selection, and the thin strip | **done** 2026-10-06 |
| **C** | the paper: light canvas, menu | **done** 2026-10-06; the choice of papers is still to come |
| **D** | group hue, three roles, grey for ungrouped | **done** 2026-10-06 |
| **E** | the pill and its anchors | **done** 2026-10-06 |
| **F** | the unseated rail moves right and becomes cards | **done** 2026-10-06 |
| **G** | Up Next folded in, the Cold call tab deleted | **done** 2026-10-06 |
| **H** | the camera: grab-to-pan, no scrollbars, one free band | **done** 2026-10-06 |
| **I** | Duplicate a group, with its seats, letters and label | **done** 2026-10-06 |
| **J** | the rail furls; hover to open; one motion vocabulary | **done** 2026-10-07 |
| **K** | nine hues and a custom one; `group.chroma` | **done** 2026-10-07 |
| **L** | Up Next out of the rail: one, a group, or one per group | **done** 2026-10-07 |
| **M** | Printing: the mode, seat letters split from print versions | **done** 2026-10-08 |
| **N** | the strip's two states: a group, or a seat | **done** 2026-10-08 |
| **O** | order numbers on the canvas, dragged or typed | **done** 2026-10-09 |
| **P** | versions: swap, shuffle, set the count | **done** 2026-10-09 |
| **Q** | click in order, and draw the route | **done** 2026-10-09 |
| **R** | per-section save and per-section print plan | **done** 2026-10-10 |
| **S** | band-select, move and delete; pan onto space and two fingers | **done** 2026-10-10 |
| then | 12.11's stages 4-6 land into the shell rather than beside it | |

#### What is actually left, 2026-10-10

In the order they would matter:

1. ~~By-seat ordering does not reach the paper.~~ **Done 2026-10-10**,
   with a format decision rather than a patch -- see 12.14 below and the
   notes of the same day. Everything in Printing now reaches the paper,
   verified against the written text and against the real room.
2. ~~The color swatches are the last unconverted disclosure.~~
   **Done 2026-10-10.** All four are now `.isle.drop`, built once and
   opened by a class, and `closeDrawers()` is the one place that knows
   what "everything is shut" means.
3. ~~12.11's stage 6.~~ **Done 2026-10-10**, as a shuffle and a pin --
   see 12.15. Swap-two was dropped: People mode already swaps two by
   clicking one and then the other, which is the gesture it would have
   duplicated. Stages 4 and 5 were already built: the palette and seat
   dragging, and the print-order mode is Printing.
4. ~~The paper color choice.~~ **Done 2026-10-10**, as
   `section.canvas.background` -- four named light values in the
   top-right island. Not called paper: in this tool that word is the
   sheet in the printer. See the notes of the same day.

Nothing on this list is open. What is left is whatever the next round
of use turns up.

A first because everything after it needs somewhere to live, C before D
because the colors have to be designed against the paper they sit on,
and G last because it is the only one that removes a tab.

Written as a self-contained `seating/` module with its own stylesheet
from the start. That is the difference between the spin-off being a
move and being a rewrite.

### 12.13 One disclosure, one behaviour

Written down because the inconsistency keeps coming back. By the time
anybody counted, this window had **four** ways of opening a thing that
holds other things, and no two of them agreed:

| | opened by | closed by | motion |
|---|---|---|---|
| mode rail | hover | leaving | 0.28s in, 0.2s out |
| furniture drawer | click | click, or outside | 0.28s / 0.2s |
| save menu | click | outside **only** | none |
| color swatches | click | outside | none |

Three of those are defensible on their own. Together they are a window
that has to be learned four times, and the save menu's missing
press-again-to-close was a bug nobody would have written if it had
been the same code as the drawer.

**The rule.** Anything that opens to reveal more:

* **opens on a press, never on hover.** There is no hover on a touch
  screen, which is the same argument that ruled out a right-click
  menu for the Printing commands. Hover-open also fires when somebody
  is on their way somewhere else, and the usual patch for that -- an
  intent delay -- is a timer that makes the interface feel slow in
  exactly the case it was added for.
* **closes on a second press of the same control**, on a press
  outside it, and on Escape. All three, always.
* **uses `--in-time` / `--in-curve` arriving and `--out-time` /
  `--out-curve` leaving.** Those exist so that nothing has to choose
  a duration, and anything that chooses its own is wrong twice: once
  for being different, and again the next time the pair is tuned.
* **is built once and shown by a class**, not created on demand. A
  popup made at the moment it is needed has nothing to animate from,
  and -- the save menu's actual bug -- a second press builds a second
  one on top of the first instead of closing it.
* **is one at a time.** Opening any of them shuts the others.

**And the enforcement, which matters more than the rule:** these
should share an implementation, not a convention. Four places
independently deciding to behave the same way is four places that can
independently stop. The CSS is now one `.drop` / `.palette` pair of
rules over shared tokens; the open state is a boolean per surface
cleared in one place.

Where this bites next: the color swatches (`openHues`) are still the
fourth way -- created on demand, no motion, outside-press only. They
should become a `.drop` like the rest.

**A second rule, learned the hard way on 2026-10-10.** Sharing the CSS
was not enough: the rail still snapped open where the others eased,
because pressing it called `renderSeating`, which *rebuilds the rows* --
and a brand new element has no previous value to transition from.
Opening something is not a change to the document. `showOpen` sets the
three open-states on the live elements and redraws nothing. Anything
that animates must be told, not rebuilt.

### 12.8 Decisions taken

| | |
|---|---|
| Persistent state lives in a course folder outside every repo | student data must never enter a repository, and copies drift |
| A course folder is named by the instructor, not derived from the course code | one instructor wants both sections together, another wants them apart, and `course init` will make as many as they like |
| A job names a course; an explicit path still wins | one place to fix a name, and no existing job folder breaks |
| The job's pointer is `[course] folder`, a key, not a `[course]` table | a publication file already has a `[course]` table for the printed header, and TOML refuses a duplicate. `name` prints, `folder` resolves |
| TOML for human-authored state, SQLite for the print record | unbounded, machine-written, queried, and written by two processes |
| Legal name and preferred name are separate fields | the seating chart uses preferred names; Banner will not |
| SID joins, email is the fallback, name is never a key | SIDs do not change |
| `dropped` is a flag; a missing row in an import sets it | the print record has to survive |
| Availability is global, not per student | one form for everyone; per-student would mean per-student forms |
| printit owns only the form slots it can derive | the rest is pedagogy the tool cannot regenerate |
| Patch recorded item ids; never recreate form or question | responses are keyed to `questionId` |
| Printed and attempted are different facts | the build cannot know who was in the room |
| No retake cap | none exists in the course |
| Courses live in `~/CheckItPrintIt/courses/<name>/` | beside the job folders and the output, all outside every repo; configurable later if anyone needs it |
| `course init` offers to adopt the newest job's roster and seating | there are already three copies on disk and none of them should be retyped; it prints which files it read |
| `openpyxl` is added as a dependency | Banner and the seating charts both arrive as `.xlsx`, and requiring a save-as-CSV first defeats an importer whose purpose is removing manual steps |
| Responses stay scoped by the confirmed date | it is what the current system does, it survives a late submission that a timestamp window would miss, and the confirmation question already exists |
| The cold-call system waits for the seating GUI | it belongs at the top of that window, and it is far down the road |

### 12.9 Still open

0. ~~Nothing in stage 7 has run against a real Google account.~~
   **Settled 2026-09-21: 7a works.** One thing remains open --
   `form create` needs to prompt for the one-time browser authorization that
   the editor's deploy flow does automatically. See the staging table.

1. ~~Whether the Google Cloud path is open on the institutional account.~~
   **Settled 2026-09-20: it is not.** No Cloud projects on that account, so
   Apps Script is the path. See 12.5.
2. ~~The exact Banner export shape.~~ **Settled 2026-09-20 against three real
   exports**, and it changed the model. There are *two* id systems -- a Banner
   student id (`806...`) and a Global id the LMS calls OrgDefinedId (`20...`)
   -- and an export carries one, the other, or both, so a student record keeps
   both and a merge matches on whichever it has. An LMS export also contains
   an instructor and a mentor row, so role filtering is not optional. A Banner
   summary workbook puts its header on row fifteen under a course-information
   block. And **email is only a weak key**: one student appears under two
   different addresses in two exports downloaded the same day, and the Google
   Form only ever saw the first -- so addresses accumulate rather than
   replace. Implemented in `classlist.py`.
3. ~~Whether `.xlsx` support is worth a dependency.~~ **Settled 2026-09-20:
   yes, `openpyxl`.** Banner and the seating charts both arrive as `.xlsx`.
4. ~~Whether `availability.toml` should carry the "how many skills" wording, or
   derive it.~~ **Settled 2026-09-20: derive it**, reusing the Control Center's
   own number-word table (0-40, where 0 means "any"). See 12.10.
5. ~~Whether the Apps Script API toggle is available on the institutional
   account.~~ **Settled 2026-09-20: it is, and it is now on.** `clasp` is the
   deployment path; the script lives in this repo and pushes from the command
   line.

### 12.10 The Control Center, and what replaces it

The existing system is a Google Sheet with a bound Apps Script. **It is being
retired.** Going forward there is a Google Form with a script attached to it,
and printit does everything else the Sheet was doing.

The script is the specification for the half that stays with Google, and a
useful record of behaviour that exists nowhere else.

| Apps Script function | what it does | where it goes |
|---|---|---|
| `coreCallSystem`, `refreshCallList` | rotating cold-call list with a per-student skip flag, re-inserting unchecked students at random positions | **GUI** -- a feature not previously on any list here |
| `randomizeSeating` | shuffle the roster into seats, filtered by section and by dropped | GUI, writing `seating.toml` |
| `shuffleSelectedStudents` | swap two selected seats, or shuffle more than two | GUI |
| `importStudentChoices` | join seating + roster + responses + the three selection modes + extras | printit, built -- minus the response join |
| `generateTexFile` | build `main.tex` | printit, built |
| `printAndReset` | append the run to a Printed sheet, then clear the settings | printit: the manifest and `record.db`; "reset" becomes "a job is one-shot" |
| `updateSelectionsForm` | push the week's slots into the form | the form-bound script, driven by printit |
| `emailMissingStudents` | templated mail to non-responders, substituting `$FIRSTNAME`, `$ASSESSMENT`, `$DUEDATE` and friends | later; the variable set is the spec |

**What `updateSelectionsForm` establishes:**

1. **It locates items by type and index** -- `getItems(CHECKBOX)[0]` and `[1]`,
   `getItems(SECTION_HEADER)[0]` and `[1]`. Inserting one section header above
   them silently retargets every write. This is the concrete argument for
   recording ids in `form.toml`; `FormApp` items expose `getId()`.

2. **Number words 0-40, where 0 means "any"**, in both lower case (body text)
   and upper case (the question title).

3. **Three limiter modes, not one** -- "At Most", "At Least", and exactly --
   each with a matching `requireSelectAtMost` / `AtLeast` / `Exactly`
   validation and its own help text. So `availability.toml` carries a `limit`
   alongside `choose`:

   ```toml
   [assessment]
   choose = 3
   limit  = "at most"     # at most | at least | exactly
   ```

4. **The no-skills-available state is deliberate.** One option reading "(No
   skills are available yet. Check back later!)" plus
   `requireSelectAtLeast(100)`, which makes the form unsubmittable. Preserve
   it rather than rediscovering it.

5. **The auto-attached explanation suffix is dead.** The script appends
   "(X will be included on the back side automatically.)" to a skill with an
   associated explanation. Section 10 deprecated that -- explanations are
   standalone outcomes now -- so it is not carried forward.

**What `importStudentChoices` establishes:**

6. **Responses are scoped to an assessment by date, not by a time window.**
   `filterArrayBySingleDateCriterion(responses, 0, 2, GetDate)` matches the
   month and day of the response's date column against the assessment date.
   That is what the "Confirm Skill Checkpoint Date" checkbox is *for*: it is
   the scoping key, not merely a nudge. A form accumulates responses all term,
   so `form pull` has to scope the same way.

7. **Latest response wins** -- sorted by timestamp descending, first match per
   student. This is what the 2026-09-18 run did by hand, so the tool inherits
   existing semantics rather than inventing them.

8. **Extras cycle through the version letters** (`allVariants[i % length]`).
   printit shuffles instead, which is what section 10 chose. Noted so the
   difference reads as intentional.

**Two more things the script settles, which were open questions here:**

9. **Response validation is already on.** `updateSelectionsForm` builds a
   `requireSelectAtMost(n)` validation and attaches it, so students cannot
   over-select today. The push must keep setting it, since the limit and the
   skill list change together.

10. **Nothing caps a response on the way back in.** `importStudentChoices`
    takes every choice in the response, appends the "append for everyone"
    skills, de-duplicates, and prints the lot. If a response somehow carries
    more than the limit -- a stale submission from a week when the limit was
    higher, say -- the existing behaviour is to print all of it. Keep that,
    and let the preview show the count rather than silently truncating.

**The script is kept verbatim** at `reference/control_center.gs` in the
`checkit-printit` repository, with a README saying what it is. It carries no
student data; that was checked rather than assumed.

**The Sheet also held state that now belongs to the course**: the roster
with dropped flags, the seating charts, the available-skills list with its
tick boxes, the Printed log, the email templates, and the run settings
(title, date, key count, extras count, the three selection modes). Those map
onto `roster.toml`, `seating.toml`, `availability.toml`, `record.db` and the
job's `publication.toml` respectively -- which is what 12.1 through 12.4
describe.

### 12.14 What the chart says about order (2026-10-10)

`seating.toml` is a flat sequence of `[[group]]` tables, each holding a
list of seats, and that list was being asked to mean three things at
once: the order the papers print, who is sitting next to whom, and
which chair at the table a seat is. One list can only do one of those
honestly.

It did not matter until the print order could differ from the seating
order. Then it contradicted itself in both directions at once: a table
seated A B A B round its four sides is fine, but printed 1 3 2 4 the
file reads A A B B, so the check reported two clashes nobody in that
room can see -- and the real pairs, the ones along the sides, were no
longer written down anywhere to check.

**The decision.** A `[[group]]` is the *table*. Its seats are listed in
the order they sit, which is the clockwise sweep from the top left, and
that order is never touched for printing. The stack is a separate thing
each seat carries:

```toml
[[group]]
seats = [{name = "Ada Lovelace", version = "A", at = 1},
         {name = "Alan Turing", version = "B", at = 3}]

[[group]]
seats = [{name = "Grace Hopper", version = "A", at = 2},
         {name = "Katherine Johnson", version = "B", at = 4}]
```

Ada still sits with Alan; the stack still alternates tables.

Three properties were wanted and all three hold:

* **An untouched room writes the file it always did.** `at` appears only
  where the stack is not the order the file already reads in. Handing
  out table by table with nothing reordered, those are the same list.
* **Every hand-written chart still loads unchanged.** The sort is
  skipped entirely when no seat claims a place, so the key is not merely
  handled but absent from the code path.
* **`print_by = "seat"` reaches the paper.** It means one walk round the
  room, which crosses tables, and no ordering of `[[group]]` blocks can
  express that.

Rejected: flattening every seat into one `[[group]]`. It would encode
the order and destroy the meaning, since `group` is what `collisions`
reads, and one group of twenty-five would call every neighbour a clash.

Two rules fall out of it. **The numbering is one sequence for the whole
file**, because a chart has no sections in it, only a comment saying
where one begins -- and all-or-nothing, because a seat with no number
prints last and a bare section ahead of a numbered one would be dragged
behind it. And **a seat with no `at` among seats that have one prints
last**, which is the rule an unplaced group and an unspotted seat
already follow.

### 12.15 The pin, and the shuffle (2026-10-10)

Two halves of one thing. A shuffle is only usable if some people can
be exempt from it: students with accommodations sit where they sit,
and a button that threw them across the room would be a button nobody
dared press.

**The pin is on the seat, not the student.** `seat.pinned`, optional
and boolean. What it means is "whoever is in this chair stays in it",
which is the thing an accommodation is actually about -- a place, not
a person. It is not the same word as `seating.Seat.pinned` in the
chart, which says a version letter was written down rather than
worked out.

**Where it lives on screen.** The bottom-right corner of the name
card, opposite the version letter and in the same `--solid` color:
both corners are the room having decided something about that card.
Only People mode draws one, because no other mode moves people. It
shows when set, on hover, and on the card currently in hand -- the
last of those being the one a finger can reach, since a touch screen
has no hover. Twenty-five permanently visible grey pins would be
noise nobody is looking for.

**One refusal, not four.** A person can be moved by dragging a card,
dropping onto a card, clicking a name, or clicking a chair. All four
reach `movePerson`, so that is where a pinned seat is refused; the
affordances are also turned off at each gesture, so the move never
looks available in the first place. A pinned card simply does not
drag, rather than springing back -- springing back looks like a
missed drop, and the point is that the drop was never on.

**What a shuffle touches.** The people already sitting down, into the
chairs nobody has pinned. Not the unseated rail, which is somewhere a
person was put on purpose. Empty chairs shuffle like anybody, or
every gap collects at one table. The version letters stay on the
chairs, because the coloring is of the room -- so the arrangement is
still legal afterwards and nothing needs re-coloring.

It runs on the server for the same reason the coloring does: a button
calls the function a command would, and these rules are worth a test.
Nothing is written -- the room comes back changed and unsaved, so an
instructor who dislikes the result presses Discard.

**Randomising only a selection was considered and is not needed.** It
is pinning everybody else, which already exists, inverted. Swap-two
was dropped for the same kind of reason: People mode already swaps two
people by clicking one and then the other.

**Where they live.** Both are rows in the corner button's drawer,
which People mode now has like Groups and Printing -- the same
contextual surface with different contents, which is what 12.13
asked for. The wand rather than a plus, because the rule is that a
wand means "asking the room to work something out", and that is what
a shuffle is.

**That last sentence is wrong as of 2026-10-11, and the wand is
gone.** See 12.17: the corner button is a `+` where the mode has one
primary action and a `⋯` where it has a list, and People has a
list. The wand was a symbol for a category -- "the room works
something out" -- which is a thing a reader has to be taught, and the
two apps anybody compares this to teach the opposite.

### 12.16 Say it in two words (2026-10-11)

**A control is labelled with a verb and its object, and nothing
else.** "Seat all". "Unseat all". "Shuffle room". "Unpin all". Not
"Seat all 6 standing", not "Clear every chair", and never a sentence.

Written down because it has now been asked for three times, each time
after a round of new controls arrived carrying explanations in their
labels. The pull is understandable -- a label is the only place the
writer is sure the reader will look -- and it is wrong, because a
menu of five rows is read as a shape before it is read as words, and
five sentences have no shape.

The rules that follow from it:

* **No counts in a label.** "Seat all", not "Seat all 6 standing".
  The count belongs in the tooltip, where it answers "all of how
  many?" for somebody who wondered.
* **No grammatical variation on a count.** A label that is "Unpin the
  one pinned seat" at one and "Unpin all 3 seats" at three is two
  labels, and the row appears to change identity as the room does.
* **A tooltip is a fragment, not a sentence.** "3 pinned stay put".
  It is a footnote to the label, so it says the thing the label left
  out and stops.
* **The house word wins over the plain one, once there is a house
  word.** The rail "unseats"; so does the menu, and so does the drop
  target. "Clear every chair" was a third way of saying it.
* **A caption on a drop target is one word** -- "Unseat" -- because it
  is read in the half second while something is held over it.

The test: read the menu as a column with the icons covered. If any
row takes longer than a glance, it is too long.

### 12.17 The canvas obeys canvas conventions (2026-10-11)

A fortnight of use found one kind of complaint over and over: the
canvas was *nearly* like every other canvas, and the gap was where
the friction lived. These are the decisions that closed it. The
common thread is that a design canvas is a genre with conventions
already, and inventing inside it is a cost paid by the reader.

#### The canvas has no edges

It used to be fenced to a box a little larger than the content, which
could not be dragged out of. The reason was good and the effect was
not: a room could not be laid out across the width of a screen,
because the fence arrived first.

**So: coordinates may be negative, and nothing clamps.** The model
never minded. Fitting and centring measure the content's own box, so
they work the same at any offset, and `section.canvas` is a record of
how far the room reaches rather than a limit on it.

What makes that safe is that **fit is the recovery, not a wall.** A
drag that throws a table somewhere surprising is undone by the thing
the user already knows -- press fit, see everything, drag it back.
A fence prevents the surprise at the cost of making the surface feel
small all of the time, which is the worse trade, and "I can't even
place things fully from one side of the screen to the other" is what
it sounds like from the outside.

#### The wheel zooms, about the pointer

Scroll up is in, scroll down is out, and the point under the cursor
stays under the cursor. Ctrl-click (cmd on a Mac) adds to a selection.
Neither of these is a feature so much as **the absence of a defect**:
a canvas without them reads as a prototype, because every tool the
user has ever zoomed in does it this way.

Holding the point under the cursor is worth one note, because the
obvious implementation is wrong in a way that only shows up after ten
clicks. Solving for the new pan in closed form requires being right
about every rectangle in the chain, and being an eighth of a pixel
wrong each time walks the subject visibly off the cursor. **Measuring
where the point actually landed and correcting by the gap is a fixed
point**, converges in one or two passes, and does not care which of
the measurements was the inaccurate one. See the notes of 2026-10-11.

#### One grey for everything the canvas marks

`--mark`. The accent color belongs to the chrome, where it means "the
state you are in"; on the paper it is just another color, landing
beside whatever the groups happen to be. Five things were wearing it
there -- a band, the desk a dragged seat would move to, the two hover
marks in the click-in-order quasimode, the badge a version would
trade with -- and each had invented its own inset, radius and dash
along the way, so there were four selection rectangles that looked
like four different ideas.

**One geometry as well as one color**, `--pick-out` and `--pick-line`
on `.deskwrap`. A reparent target is now visibly the same gesture as
a selection, asking a question.

#### Selection color answers "which one", and only when there is one

* **A single selected group wears its own color.** That is the
  question a selection answers -- which of these have I got hold of --
  and the group's color is the only thing on screen that already
  means that group.
* **A multiselection is grey**, and the members lose their handles and
  their own selection styling entirely. With more than one there is no
  "which one", so the question changes to "what is in the set", and a
  set is one shape with one ring. `isSelected` returns false while
  more than one thing is banded, which is what makes the handles
  disappear in one place rather than eight.
* **The ring is feathered**, tapering out the same distance a seat's
  selection does, because the two now had to look like one idea.

#### Glue and unglue

A group is **a set of seats**, not a shape. That was already true and
merging is the first feature that makes it obvious: `merge_groups`
folds two seat lists together, `split_group` regroups by desk, and
**nothing moves either way**. Two tables merged while apart stay
apart; they are one group that happens to span two desks.

What follows without any new code:

* one label, one color, one strip, one set of grips
* a drag moves the whole thing; a rotation turns it about the common
  middle
* **the seat letters need no special case.** A letter is swept
  clockwise from its *group*, so a merged group sweeps its whole
  arrangement as one ring and the lettering is already right

The strip carries the merge icon when more than one group is selected
and the split icon when the selection is a merged group. Drawn as the
two inner edges of adjacent tables with a filled arrow pushing in or
pulling out, after `]  [` and `}  {` -- because the first drawing was
legible at full zoom and a smudge at arm's length, and a strip is
read at arm's length.

#### A control exists only where the thing it edits exists

The by-seat print plan made this concrete. Ordering by seat, **a group
has no place in the stack** -- the stack crosses tables, and a
group's position in it is not a number that exists -- so that control
is simply absent from the group strip in that mode. A seat gains one
instead, because by seat a single seat is exactly the thing that has
a place.

The general rule, which is cheaper than it sounds: a control that
would edit something nothing reads should not be drawn. Greying it out
says "not now"; absence says "not a thing", which is the truth.

#### A strip field is editable exactly when it is stored

* `seat.version` is stored, so it is typable, and validated against
  the room's own version list -- a letter nothing prints would put a
  version in the chart that the build has never heard of.
* The **seat letter is derived** and is therefore not editable, and
  should not become so. It is swept from where the seat sits, which is
  the whole reason "re-letter when a seat moves" needs no bookkeeping.
  Making it typable would mean storing an override, and the room would
  have two answers to the same question.

Both are regular weight now rather than bold. Two bold characters
side by side shout at each other and say nothing about which is
which; the chair and the printer icons beside them already say that.

#### The corner button is two controls in one place

A `+`, accent filled, where the mode has one primary action, which is
always adding a thing. A quiet `⋯` where it has a short list
instead. This is Material's own rule -- a floating button carries one
action, and overflow belongs in a menu -- and it resolves the thing
that looked like a conflict: People wants an "add person" *and* a
menu, so add person is the first row of the menu. In this app it
redirects to the Roster tab, because adding a person is roster work.

#### What is actually left, 2026-10-11

The four items on the 2026-10-10 list are all struck through above;
this replaces it.

1. ~~Pinch zoom does not anchor the way the wheel now does.~~
   **Done 2026-10-11**, and it was three faults rather than one. The
   guess that it needed real hardware to confirm was wrong: synthetic
   touch pointers drive the handler, and measuring first found that
   neither `panPaper` nor `bandPaper` filtered `pointermove` by
   `pointerId`, and that nothing called off the one-finger gesture
   when a second finger landed. The anchoring is now one named
   function, `holdPoint`, which both the wheel and the pinch call.
   117 pixels of drift before, 0.03 after. See the notes of the same
   day.
2. **Nothing in Seating has been used on a phone.** Two-finger pan and
   pinch are written and have never been under a thumb. The layout was
   checked at 530px in a desktop browser, which is not the same test.
3. **Record** was the one view still entirely unstarted. It is now
   three -- Runs, Progress and Scans -- and is specified in section
   14. **Setup**
   still wants its boilerplate editor.
4. **The TOMLs want a pass.** They were designed before the GUI, in
   preparation for it; now that the GUI has settled there is almost
   certainly shape in them that no longer earns its place. The
   instructor's own words: more there needs reconsidering than the one
   `at` key that 12.14 added.
5. ~~One unexplained measurement.~~ **Explained 2026-10-11, and
   there was nothing wrong with the room.** `MouseEvent.clientX` is a
   `long`, so the browser truncates wheel coordinates to whole pixels;
   the harness was measuring a point up to a pixel away from the one
   the zoom anchored on, and such a point is *supposed* to move when
   the picture scales. Rounding the measuring point gives 0.03 pixels
   over fifteen clicks. The clue was the thing recorded as the puzzle:
   **a number that does not change when you change what it measures is
   measuring something else.**

## 13. The look of the app (2026-10-13)

**Status: in force.** Stages 1 to 3 are built and every tab now shares
one structure; stage 4 is the remainder. What is marked *settled* has
been decided by the instructor and should not be relitigated. What is
marked *open* is still a judgement call and belongs to him, not to
whoever is editing this file.

Section 14 is written against these rules and assumes them.

### 13.1 The problem this exists to fix

The GUI was designed end to end by Claude, and it reads that way. The
diagnosis is not that it breaks rules -- it mostly does not. It is that
**uniform treatment was applied where a designer would have made
judgements.**

Every section is a card. Every card is the same weight. Every
explanation is the same size as every other piece of text. Nothing is
emphasised, because nothing was *chosen* to be emphasised. The giveaway
on the old Overview tab was eight identical boxes in which the largest
word on screen was "yes".

Three secondary tells, all of the same kind: native OS form controls
left unstyled in a custom dark theme; explanatory prose everywhere a
human would have trusted the reader and cut; a three-column grid
holding eight items.

**The through-line of the instructor's own reactions to a dozen
reference applications**: everything he liked was row-based with
comfortable spacing (Linear, Things 3, TrueNAS). Everything he disliked
was either boxes-with-gaps (Sonarr, Sublime Merge, Home Assistant, our
Overview) or crushed rows (TablePlus). The target is **rows with air.**

### 13.2 What we take from Material and Fluent, and what we refuse

Both frameworks were consulted. They converge on five structural
points, and those are worth having:

1. Navigation placement follows destination count and window width.
2. Layout should change *shape* at breakpoints, not merely reflow.
3. Elevation is a ladder of surfaces, not a binary.
4. One accent-filled action per view.
5. Density is a named global setting, not improvised per screen.

**We take their structure and refuse their surfaces.** Their visual
defaults are precisely what makes software look like everyone else's --
boxy and dated in Fluent's case, spartan in stock Material's. Adopting
the reasoning without the skin is the whole point.

### 13.3 Settled

**The rail.** Navigation moves from a centred top bar to a left
navigation rail, with icons, collapsible to icons only. This is not a
preference: with seven destinations at desktop width it is what both
frameworks specify, and Material 3 Expressive has since dropped the
navigation drawer in favour of exactly this collapsible rail.

**No top navigation at all.** What survives at the top of a page is the
page's own title.

**No dashboard.** The Overview tab is removed. Its contents are
redistributed by *where you would act on them*: counts go in the
relevant page's header, configuration facts go to Setup, and anything
wrong becomes a warning -- a dot on the rail, and a strip at the top of
the page that owns the problem.

**Rows, not cards.** Cards are for a group that genuinely needs a
boundary. Lists are bordered rows. Nothing gets a card merely for being
a section.

**Filled checkboxes**, not outlines. Outline checkboxes read as too
much negative space at this density.

**Save state is a bar that appears only when dirty** (option c of three
tried). Absent when there is nothing to save.

**The page title is the editable field.** The Print tab had the job's
name and date rendered twice -- once as uneditable page furniture, once
as form fields further down, with a button between them that depends on
the date. One editable title carrying name and date removes the
duplication and puts the date above the control that needs it. The
section heading "This run" dies with it: every setting on that tab is
about this run.

**A second hue, with one meaning.** Amber means *something needs your
attention* -- the rail dot, the page-top strip, the unsaved badge. It
is not used decoratively. Green stays the accent.

**No jet black in dark mode**, and more grey steps than the two the app
has now.

**The greys are warm.** Measurably: the first drafts came out violet --
`#a6a2ac` is R166 G162 B172, blue highest and green lowest, and the
whole ladder carried that cast. The light theme has always been warm
(`#fbfaf8`), so a warm dark ladder makes the two modes siblings rather
than strangers. Neutral was the alternative and is still defensible;
violet was nobody's choice, it was an accident.

**Figtree**, over Inter, Source Sans 3, Atkinson Hyperlegible and IBM
Plex Sans. It is the roundest of the candidates without being a
consumer-app face, and it is the one that answers "inviting" -- the
numerals in particular soften a dense grid at no cost to legibility.

**The gutter is for settings-shaped sections only.** Not a layout for
the whole app. See 13.5.

**Glyphs are judged at their rendered size, by rasterising and
magnifying** -- not by looking at a screenshot, which the pane
downscales. The recipe is in `checkit-printit/tools/mockups/README.md`.
The first thing it overturned was the Settings gear: the comment in
`app.js` claimed a toothed outline could not survive 21px, which was
an assumption written as a finding. Five survive. The constraint that
is real is the white left in a valley, and it is bought by moving the
root circle out rather than by cutting teeth. See `CODEBASE_NOTES.md`,
"The Settings gear, and a claim nobody had tested".

### 13.4 Writing, which is where the character is

§12.16 already governs control labels: a verb and its object, nothing
else. It extends to the whole GUI.

**Never run facts together with separators.** `45 students · 22 in 820
· 23 in 830` is the single most recognisable tic in this codebase, and
it is the writer reaching for a separator because no layout was
designed. Three facts in a row with dots between them is a sentence
pretending to be an interface.

What to reach for instead, roughly in order: **an icon with a number**,
which costs no words at all; **small grouped pills** where the facts
are peers; **colour or weight** where one of them is the one that
matters and the others are context; and **putting the fact next to the
thing it describes** rather than collecting facts into a strip at the
top. A count that belongs to a section belongs in that section's
header row, not in a run-on with two other counts.

The run-on is occasionally right -- for genuinely equal, genuinely
minor metadata, three items at most. It is not the default, and it
must never be the first thing reached for.

**Plain underlined text is not how a function looks.** The
instructor's rule, and a standing one: an underline says *this
navigates*, and every control in this app does something instead. A
column of underlined words reads as a paragraph that has been marked
up rather than as a set of controls. Quiet buttons -- no border at
rest, a surface on hover -- and for an action that repeats down every
row, an icon: grey at rest so the column stays quiet, the accent only
on the row under the pointer. `tests/test_gui_markup.py` enforces it.

**An action outranks reference data.** When a table runs out of width
the instinct is to protect the data, because data is what a table
looks like it is for. It is not: Email and SID are reference, and
dropping a student is the one thing the Roster *does*. Columns carry a
`rank` that says what survives a squeeze, and the actions sit second,
below only the name.

**Skill names come from the bank.** Each outcome in `bank.xml` carries
*two* strings: a short `<title>` ("Divisibility Statements") and a long
`<description>`, the "I can..." statement. **Titles belong in tables
and headers; descriptions belong in tooltips.** Nothing in the GUI
should invent, abbreviate or paraphrase either. `bank.description()` is
currently the only accessor printit has, which is why the long form
leaks into places that wanted the short one -- that is a gap to close,
not a style to follow.

**Explanations do not sit in the open.** The long paragraphs on the
Print tab were an AI's instinct to over-explain. An explanation belongs
behind a `?`. A short subtitle is permitted where the section genuinely
needs one; a paragraph is not.

**Say the consequence, not the event.** "17 will take the default" is
worth more than "17 did not answer", because what the reader needs is
what will print. Where two numbers are a pair, make the grammar
parallel: *28 answered / 17 didn't*.

**Empty states are the one place a utility may have a voice**, and the
cheapest source of the warmth this app lacks. "Inviting" here means
microcopy, empty states and the typeface -- not colour, not rounder
corners, not illustration scattered about. Those read as decoration,
which is the opposite of charm.

### 13.5 Structure

**Settings-shaped sections are annotated**: the section's name and its
`?` sit in a left gutter, the controls to the right. This is Polaris's
settings layout, and it works because the header is distinguished by
*position* rather than by shouting. **At narrow widths the gutter
collapses and the header moves above its controls.**

**Table-shaped tabs get no gutter.** Roster, Runs, Progress and Scans
are not settings
and must not pretend to be. The gutter costs about 120px of width
permanently, which a form does not miss and a table does: drawn both
ways, the same Roster column went from carrying a real skill name to
carrying a bare digit.

So the consistency this app keeps is **consistency of rule, not of
appearance**: a section whose content does not want horizontal space
gets a gutter; a section whose content does, does not. Two structures,
one reason, stated here so neither looks like an oversight later.

**Counters never live inside a heading.** "Open for retake — 0 to 29"
jammed three ideas into one line. The name goes in the heading, the
count sits right-aligned on the same row, the range belongs to the
control it governs.

**A long table scrolls inside the window, not the page.** With 45
rows the Roster's scroller was 2158px tall, which put its horizontal
scrollbar 1362px below the fold: sideways movement was shift-and-wheel
only, and the rightmost column -- the drop button -- could not be
reached at all. The table gets the window and scrolls within it, so
both bars are on screen and the headings stay put.

**Name and the actions are pinned**, left and right. Those are the two
a row cannot do without: which student this is, and the thing you came
to press. Everything between them scrolls.

**Spare width goes into the table.** A 1100px header above an 867px
table looked like the table had failed to load. Columns marked `grow`
take the slack up to their own maximum; Section does not, because a
300px Section is a worse table and not a bigger one.

**An empty column is sized for its heading.** `min` is what a column
wants when it holds something; `floor` is what it may be squeezed to,
and a column with no values anywhere starts there. `Prints as` is
empty on every roster here and was reserving 200px -- a fifth of the
table -- while Email was clipped.

**Slow work starts at boot, not at the click.** Measured on the real
course: `/api/skills` is ~700ms warm and 1.2s cold, `/api/google` is
**six seconds** the first time because it shells out to clasp. Both
now start when the app opens, behind the Roster, so the tab that needs
them usually finds the answer already there -- a warm switch to Update
form went from about a second to **3ms**. A request is kept as a
promise, not as data, so a second caller joins the first one instead
of making its own.

**Where a wait is unavoidable, show the shape of what is coming.**
Placeholder rows the height of real ones and as many as the list will
have, so the page has its layout before it has its content and nothing
jumps when the answer lands. Never a spinner, which says only that
something is happening somewhere.

**And they move.** 13.4's line about decoration names colour, rounder
corners and scattered illustration; a loading shimmer is none of
those, and it is not decoration, because it is carrying the one
distinction that matters here. A still grey bar is indistinguishable
from a real empty row -- "nothing is open for retake" reads exactly
like "this has not arrived yet", and on this tab the first is a
plausible state. The movement is what says which. Slow, low-contrast,
and off under `prefers-reduced-motion`.

Recorded because the opposite was briefly written here, as though the
instructor had ruled against animation. He had not: he had ruled
against underlined text for functions, and against decoration meaning
colour and corners and illustration. **Do not generalise one of his
rules into a neighbouring one he did not make.**

**A table's header row has its own surface**, so it reads as a header
without extra spacing.

**Columns collapse rather than disappear.** The variant column shows a
real editable control at full width and folds to a single icon when the
table is narrow.

**Numerals are tabular** everywhere a number sits in a column.

### 13.6 What Seats gives us, and what it does not

Seats is a canvas sandbox. The rest of the app is text and tables.
Importing its look wholesale would be a category error -- and the
instructor's own reaction proves it: Seats's floating islands are cards
with space around them, which is exactly what he disliked in Home
Assistant. They work over a canvas because the room must stay visible
underneath. In a text view there is nothing underneath.

| from Seats | verdict |
|---|---|
| two-word labels; tooltip carries the rest | **take** |
| a control exists only where the thing it edits exists | **take** |
| editable exactly when stored; derived things are not | **take** |
| an empty state is a door, not a sign | **take** |
| one neutral for what the system marks; accent reserved | **take, translated** -- accent marks the primary action and current location, never decoration |
| a ladder of surfaces | **take, translated** -- no canvas to float over, but one `--panel` is not enough |
| floating islands | **refuse** -- nothing to see through to |
| modes | **refuse** -- tabs are different data, not different verbs on one object |
| the corner plus | **refuse** -- a form has a natural home for its primary action |
| the geometric icon set | **refuse** -- those glyphs depict spatial operations; "Pull responses" has no picture |

### 13.7 The stages, and where they stopped

The work is staged so that payoff comes early and risk late. Direct
on `main`: the instructor is the only user, and asks for the usual
branch-and-merge procedure to be skipped.

| stage | what | state |
|---|---|---|
| 1 | token layer: surfaces, spacing, radius, type, font, native controls | **done** |
| 2 | the shell: left rail, no top nav, no Overview | **done** |
| 3a | a skill shows its `<title>`, not its description | **done** |
| 3b | Print tab: editable page title, `This run` dies, annotated sections, prose behind `?` | **done** |
| 3c | Roster: the counts question, and the `colgroup` arithmetic | **done**, with comments outstanding |
| 3d | Form, Setup | **done** |
| 3e | Record | **superseded by section 14** -- it became three tabs |
| 4 | save bar, warning strips, empty states, a microcopy pass | **done** |

**Settled in 3b:** an annotated section is a `.annot` grid -- a 200px
gutter holding the name and its `?`, the controls to the right, a
hairline between sections and no card. `annot-full` drops the gutter
for content that wants the width, which on this tab is the table and
nothing else; it buys the table 220px. The `?` toggles a `.hint-text`
and is wired by one delegated listener, so a section added later gets
the behaviour without being remembered. Below 860px the gutter
collapses and the header goes back above its controls.

**Settled in 3c:** the page header carries only the whole-table
total (`Roster` left, `45 students` right); the per-section counts
ride **section bands** inside the table, a thin full-width row
reading `820` with `22` right-aligned above that section's rows.
Bands are drawn only while the rows are actually grouped by section,
tested on the sorted rows rather than on `sorts[0].key`, so they
survive a descending sort and vanish when a sort interleaves the
sections. The table scrolls inside the window rather than making the
page tall, with the heading row, the Name column and the actions
column all pinned; columns carry a `rank` that decides what survives
a squeeze, and **an action outranks reference data**.

**Settled in 4:**

* **One save bar per tab, absent when there is nothing to save.** Four
  tabs had grown three arrangements of the same two buttons, one of
  them with no Discard at all, and the Print tab's bar sat there
  permanently with both buttons greyed. A disabled Save cannot say why
  it is disabled; an absent bar needs no explanation. The bar names
  its own scope -- "unsaved changes to this run", "to this course" --
  because the scope was the thing the old placements got wrong: the
  Update form's Save lived inside one section and wrote two.
* **A warning draws its own mark.** `.warnline::before`, not a `⚠`
  typed into the sentence -- two of eight had one, so warnings in the
  same report did not look alike.
* **An empty state is a door.** "This roster is empty" restated the
  blank screen. Each one now says what is missing and offers the way
  out: the import command with the course already in the `-c` flag,
  or a button that ticks "show dropped" for you.
* **Sentence case on every control.** Quiet actions were lowercase
  and prominent ones were not, which encoded the hierarchy twice --
  once in the case and once in the button style. The style keeps it.

**Settled in 3d:** Setup's "needs your attention" panel stays a card
while everything around it became an annotated section -- a boundary
is what says something is blocking you. The rule between sections is
visibility-aware, because Setup and Print both hide sections
depending on state.

**Settled during the build, beyond 13.3:** Figtree is vendored, not
linked. The greys are OKLCH 260, Seating's own hue, several steps
lifted unchanged. The rail is `.navrail` and carries the course name
at body size, matched to Seating's section toggle; its labels are
body size and its glyphs 21px. The count has left the rail.

### 13.8 Still open

* **The Roster's remaining comments.** The counts question is
  answered -- see "Settled in 3c" above -- and the instructor has
  further notes on that tab which he has parked in order to get all
  the tabs looking alike first. They are not written down here
  because they have not been given yet.
* **Section header treatment.** Six have now been tried across two
  rounds and all six were rejected. Parked deliberately: the
  instructor wants to judge it with a whole tab on screen, not in
  isolation, and it may turn out to need nothing at all.
* **Exact density**: row height and padding. `--t-base` is still 15px
  because turning it reflows every view; the midground target is
  roughly 36-40px rows, untested against 45 students.
* **The rail's collapse threshold.** It folds to icons below 900px,
  which on a narrow window means the labels are never seen. Right
  number unknown until it is used at a real window size.
* **A top strip, or none.** The top bar is gone and nothing replaced
  it. Whether the app wants a thin one for global state is open;
  three save-state placements were shown and (c), a bar that appears
  only when dirty, was chosen, which may be all that is needed.

---

## 14. Runs, Progress and Scans (2026-10-22)

Three new tabs, agreed with the instructor in a design round on
2026-10-21/22. His answers are recorded as decisions; what he did not
decide is in 14.8 and should not be guessed at.

This is the realisation of **6c**, which anticipated "a table-style
editor in the eventual GUI" and is otherwise unchanged -- including its
rule that the record **does not feed back into printing**. Progress
tells the instructor what has happened. It does not skip a skill
somebody has passed, and it does not prioritise one they keep failing.

### 14.1 Why three, and the order they depend on

They are three questions with three shapes, which is why the single
"Record" tab never got drawn:

* **Runs** -- what was printed, when, with which seeds.
* **Progress** -- where each student stands against each skill.
* **Scans** -- read the marked papers back in.

The dependency runs one way. Scans needs Runs, to know what a paper
should be. Progress needs Scans, because of the decision below.

**An attempt is logged when a paper is graded, never when it is
printed.** A printed paper for an absent student is not an attempt.
*Taken* means *present in the scan*, and it is the instructor's job to
pull absentees' and empty papers out of the stack before scanning.
That is a deliberate division: the app does not guess at attendance,
and the person holding the stack already knows.

So Progress shows nothing real until Scans works. The instructor has
his own system for this semester and is content to wait.

### 14.2 Runs

The old "Record" tab, renamed. It is about past runs.

**The data already exists.** `record.db`'s `run` table stores
`built` -- the real timestamp, which genuinely differs from the date
printed on the paper (the 10-19 run is dated the 19th and was built at
10:43:37) -- plus the run seed, the title, the date and the output
folder. Per-skill version seeds come out of the `printed` table; the
Extravaganza has 57 distinct skill/version/seed combinations. Two new
columns are needed and nothing else: **delisted** and **graded**.

**The list** is every run, newest first, showing title, date, build
time, run seed, papers, students, and whether it has been graded.

**Drilling in replaces the list with that run's page**, with a back
link, and previous/next so a run can be stepped through without going
back each time. Not an expanding row -- the detail is 50+ rows of
seeds and would push the list a screen and a half down. Not a side
panel -- the content column is about 900px and a split leaves too
little for the seed table. The same drill-in serves a single student
in Progress, so it is one pattern used twice.

The detail shows which skills were in the run, how many papers of
each, how many versions, and the version seeds per skill.

**Two actions, deliberately separate**, because merging them is how
somebody reprints last month's papers by accident:

* **Reprint exactly** -- the existing `build --replay`. Same students,
  same seeds.
* **Start a new run from these settings** -- the selection, variants
  and extras, drawn fresh against today's roster. **Warns** if the
  Print tab has unsaved work.

**Delisting** moves a run into a collapsed group at the bottom of the
list rather than hiding or deleting it. **A graded run cannot be
delisted** -- the option is not offered at all, rather than offered
and refused.

A graded run also offers **open in Scans**, to review what was read.

### 14.3 Progress

Students down the left, **all of the bank's skills** across the top --
not only the ones offered so far. Both sections together for now; an
app-wide section filter, shared with Roster, is a later job.

**Up to three facts per cell**: passed or not, how many passes, how
many attempts. 45 students by 29 skills is about 1,300 cells, so a
number in every one is a wall. Two rules cut it down:

* **A pass count only appears where the threshold is above 1.** Where
  one check passes a skill, "how many passes" says nothing that
  "passed" does not. This semester that is every skill, so the third
  fact disappears entirely -- and the design still holds next
  semester, when some skills need two.
* **An attempt count only appears when it is surprising.** Passed
  first time needs no number. Four attempts and still not passed is
  the thing worth seeing from across the room.

| state | the cell |
|---|---|
| never taken | empty |
| passed, first attempt | a tick, quiet |
| passed after several | a tick with a small count |
| not passed, one attempt | an empty box |
| **not passed, several** | **an empty box with the count, and the loudest thing on screen** |
| threshold 2, one so far | a half state and `1/2` |

**Passing is quiet.** The instructor's call, and the right one: a
gradebook is scanned for trouble, and 1,300 green cells would drown
it. **With an option to highlight recently passed skills** in the
accent, for the pass that has just come back from a grading run.
**Recent means the last two grading sets**, and the highlight can be
switched off.

**Thresholds live with the course, not the bank.** They change from
semester to semester and `bank.xml` is the shared, published file.
Default 1, overridable per skill.

**A single student drills in**, the same way a run does: their
history, when each skill was attempted, at which seed, with a link to
the scan.

#### What it became (2026-10-27)

Built as described, with four decisions that the sketch above did
not reach.

**A query is a corner dot, not a state.** The table above predates
the Query outcome. The instructor's call: it reads as not passed --
which it is -- and carries a small mark so the fact that he flagged
it for a second look does not vanish into the same box as an
ordinary blank. Offered as its own loud state and declined; a
seventh thing to learn costs more than the state is worth.

**An absence dashes the box.** Same restraint. "Did not sit it" and
"sat it and did not pass" both end in "offer it again", so they are
not separate states -- but the box drawn is the box on a paper, and
for an absence there was no paper. The tooltip says which it was,
because "not passed, 1 attempt" about somebody who never saw the
paper is simply a false sentence.

**The grid edits.** Clicking a cell opens every printing of that
skill for that student and lets him set any of them. His own
argument for it, made about scanning: "if it doesn't make it through
the scanning process for some reason, but I still have it in front
of me, I would want to be able to still input the result" -- which
is just as true in March about a run from October, when there is no
stack left to re-read. Driven off `printed`, so a run that was handed
out and never scanned is in the list with nothing against it.

**Recent is `graded`, not dates.** "The last two grading sets" is
answered by which runs have been read back, which the record already
records. Two runs sharing a date would have broken a date-based
answer, and dates are shared every time a redo is printed the same
day.

What is deliberately still missing: the section filter shared with
Roster, which 14.3 already called a later job.

### 14.4 Scans

The largest of the three and the one with real risk in it.

#### What arrives

Not a tidy stack. From the instructor:

* **Several PDFs**, because one is too large for the printer to email.
* **Both sides**, but not always -- **fronts and backs may land in
  different batches**.
* **Blank pages may be included.**
* **The papers are all mixed up.**

So page order carries no information whatsoever, and the two halves of
one sheet may not even be in the same file. **Every page has to
identify itself on its own.** That is what 14.5 is for, and it is why
the print change is on the critical path rather than being a nicety.

#### What a page already says

`printit.sty` prints, today: the student's name at the top left, `v`
and the version seed at the bottom centre, and -- **on the first page
of a skill only** -- the skill slug and the rounded box in the outer
bottom corner. The continuation style deliberately omits the box, with
a comment saying one skill should be ticked once. The box swaps
corners between left and right according to the page's side.

Two consequences:

* **Identity does not need handwriting recognition.** It needs a
  printed slug and seed read from a known corner, in a known font.
* **The mark does not need finding.** Its position is known, so the
  job is to crop a known region and classify it, which is far smaller
  than reading a page.

But a name printed at the top is not enough on its own, for two
reasons the instructor raised: a run can be printed with **blank name
lines**, and **a student can sit a skill without being in the run's
manifest** -- they pick up a spare. Both are handled in 14.5.

Blank padding pages use `\pagestyle{empty}` and so carry no footer at
all, which makes them identifiable by what they lack.

#### Reviewing

A grid of students against the skills in that sitting, which is close
enough to the Progress grid to share its parts. Each cell shows **the
cropped image of the actual box** beside the reading, so the
instructor confirms against the paper rather than against the
classifier's confidence. (This was already in the prototype; it is
recorded here because it is the thing that decides whether the tab is
trusted.)

#### Marks

The instructor uses exactly two: **a check whose tail comes out past
the box**, and **a `?` beside the box**. `?` is its own state, not a
note on a failure.

Other instructors will use other marks, so **states are configurable
per course** and a mark maps to a state. Whatever states exist,
**only the pass mark exports as a pass** -- see 14.6. Every correction the
instructor makes during review is a labelled example, which is where
training data comes from without anyone being asked to produce any.

Starting simple is fine: a tick against an empty box, inside a known
rectangle, is close to a pixel-density question. Store the crops from
day one so a classifier can be trained later on real marks rather than
synthetic ones.

#### Saving

One action, with the rest following from it:

1. Attempts recorded for each student and skill.
2. Passes recorded, against the course's threshold.
3. The runs involved marked **graded**, which also makes them
   undeletable and gives them the "open in Scans" action.
4. *(stretch)* Per-student PDFs into their own shared Drive folder,
   set up once a semester.
5. *(stretch)* An email to each student with the results and a link.

#### Storage

The original PDFs are kept untouched. Per-student output is **PDF**,
not images, because that is what gets shared and what a student can
read; images are a working step for the classifier and belong beside
the crops, not in front of the instructor.

### 14.5 What a printed page must carry

The print-side change this all rests on, and **the one piece that must
land before the first run of next semester** -- a paper printed
without it can only be scanned by reading text.

* **A machine-readable code in the footer**, carrying the run seed,
  the skill, the version seed and the page's index within that skill,
  plus the student id when the run has names. Splitting then needs no
  OCR at all, and a double-feed or a missing page is **detected**
  rather than silently filed under the wrong student.
* **The run seed, visible**, as a dashed suffix on the version in the
  bottom centre -- `v617-398621586`. The instructor's idea, and it
  means a loose sheet can be traced to its run by eye.
* **A student id field at the top**, beside the name: filled
  automatically when the run is named, and left blank to be written in
  when it is not. Printing it as one box per digit is worth doing;
  separated digits are the most reliable handwriting there is, and
  this is the only handwriting the system has to read.

That last one is what lets an unnamed spare be graded at all, and it
is why the manifest cannot be the only source of truth about who sat
what.

### 14.10 What was actually built for 14.5 (2026-10-24)

All three marks, with two deviations worth recording.

**The payload** is `C1-<runid>-<page>`, drawn 9mm square at error
correction level M. A format tag leads it, because Scans will meet
codes printed by a theme that no longer exists and a reader that
cannot tell which layout it holds has to guess.

It took three goes:

| | payload | size | level |
|---|---|---|---|
| first | `CIP1*<runseed>*<SLUG>*<vseed>*<sheet>*<page>*<sid>` | 15mm | L |
| then | `C1-<runseed>-<page>`, 17 characters | 11mm | L |
| now | `C1-<runid>-<page>`, at most 12 | **9mm** | **M** |

The second cut rested on run plus page being a unique key, everything
else being a lookup in the run's record. The argument was sound and
the lookup table did not exist -- see 14.11. The third fixed two
further things: a seed does not identify a run (14.12), and 11mm had
been carried over from a 33-module symbol without being revisited
after the payload shrank it to 21.

**9mm was measured, not reasoned.** Real pages at 200dpi -- the low
end of the instructor's copier -- blurred, skewed, noised and JPEGed,
with the decoder given the whole sheet to search:

| size | straight | skewed 4deg | photocopy of a photocopy | upside down |
|---|---|---|---|---|
| 11mm | 36/36 | 36/36 | 36/36 | 36/36 |
| **9mm** | **36/36** | **36/36** | **36/36** | **36/36** |
| 8mm | 36/36 | 36/36 | 30/36 | 36/36 |
| 7mm | 36/36 | 36/36 | 34/36 | 36/36 |
| 6mm | 36/36 | 36/36 | 0/36 | 35/36 |

Then 150 trials on the only condition that fails: 9mm reads 150/150,
8mm 134/150. The cliff is between 9 and 8, and what finds it is a
photocopy of a photocopy -- which is how a student who needs a blank
copy gets one.

**Error correction does not buy size.** At 8mm, level L reads
134/150, M 135/150 and Q 137/150. The failure is not bit errors; the
decoder either resolves the modules or it does not. The shorter
payload therefore went into *damage tolerance* rather than
millimetres: level M at the same 9mm, 15% of the symbol recoverable
instead of 7%, which is what a staple through the corner costs.

**A version-1 symbol holds 14 bytes at level M.** Past that the
encoder moves to version 2 silently, the modules shrink, and 9mm
stops reading. `test_the_symbol_is_still_one_version_1` counts the
modules off a render to hold that line.

**Installed into `mat-106-checkit` on 2026-10-25.** `theme.install`
will not overwrite a bank's own `printit.sty` without `--force`, by
design, so this waited on the instructor. Before forcing, both files
in the bank were checked against every packaged version in printit's
history and found byte-for-byte identical to one -- nothing of his
was lost.

Verified by building his real 10/23 job from the bank's own copy:
58 pages, every code read at 200dpi and resolving to the right page.
Committed in the bank, not pushed, and `checkit generate` not run.

Runs printed before this have `run_no` NULL and cannot be scanned by
code. They were printed without codes, so there is nothing to
recover.

### 14.11 The table the code keys into (2026-10-24)

The short payload rests on one claim: that run plus page is a unique
key, and the skill, the version, the sheet and the student are "every
one of them a lookup in that run's manifest".

**They were not.** `manifest.toml` records which `(skill, version,
seed)` were *drawn* -- four `[[paper]]` blocks and a `[[skill]]`
block, no students and no page numbers anywhere in it. The print
record's `printed` table has a row per student per paper, also with no
page. So a scanned code resolved to a run and a page number and then
stopped, and Scans could not have been started on top of it.

This was found by reading `manifest.py` before writing any of Scans,
and it is the third time this project has shipped a key whose index
was assumed rather than checked.

**Who knows which page a paper landed on.** Not Python: a skill can
run to two sheets, so page numbers do not exist until TeX has broken
the pages. The document therefore writes the table itself, as
`main.pages` beside the PDF:

    run*7
    1*student*806230254*W5*803*1
    mark*1*box*34926110*1819429*1780112*963539*399609
    2*key**N2*840*1

One line per page -- page, kind, student id, skill, version seed,
sheet within the skill -- and a `mark` line for each thing on it that
Scans has to cut out and look at. `*` separates because `-` occurs in
slugs.

**The marks** are `box`, `id` and `name`, recorded by `\cipmark` from
`\pdfsavepos` in scaled points from the page's bottom-left. The id
and the name are there for the blank-copy case: on a run printed
without names the student writes both, and review shows the two crops
side by side so the instructor has two independent reads of whose
paper it is.

The skill slug and the version are deliberately **not** recorded.
Both are already known from the page index once the code has been
read, and if the code cannot be read there is no page number to look
any position up by. A position only available when it is not needed
is not worth a line in the file.

**Written from the footer, not from a shipout hook**, and that is the
whole trick for padding pages. `\preparefornextstudent` pads under
`\pagestyle{empty}`, which has no footer, so a blank page writes no
line. Nothing detects a blank; the absence *is* the detection, and the
gaps in the sequence are the padding.

**`\setkind` is new**, and says `student`, `spare` or `key`. Nothing
on a printed page distinguishes the three and they are graded
differently: a key must never become an attempt, and a spare belongs
to nobody until someone writes an id on it. `main.tex` emits
`\providecommand{\setkind}[1]{}` so a bank still running an older
`printit.sty` compiles -- it then produces no index, and Scans says so
when asked to read the run, which is a better place to find out than
halfway through a print job.

**Proved on a real build, not in the markup.** A 58-page run against
mat-106, rasterised at 200dpi -- the low end of the instructor's
copier -- and every code decoded and compared to the index: 58 of 58.
Then a student was cut to one skill to force a padding sheet, and the
index came back with a gap at page 2, that page confirmed empty, and
page 3 belonging to the next student rather than to the shifted
remains of the first.

#### What this changes about the deadline

14.5's deadline is met when the bank is updated, and the file that has
to reach it is now this one, not the version committed earlier today.
**Running `install --force` before this landed would have printed a
term's worth of codes that resolve to nothing** -- which looks exactly
like a working code until the first scan.

### 14.12 The code names a run, not a seed (2026-10-25)

Raised by the instructor: *"technically the run number is the seed
and not the actual run. We may rerun that seed with a few
corrections."* He was right, and it was worse than he framed it.

`choose_run_seed` carries a replayed run's seed **on purpose** -- a
replay draws nothing, so inventing a fresh number would be a lie
about what was chosen, and the comment in the code says so. A replay
also writes into a new folder, which is a new `run_id` and so a new
row. **Every reprint therefore produced two runs sharing one seed.**
Not hypothetical: the real record had two such pairs when this was
found.

Ambiguity is the mild reading. A replay exists to *fix* something --
a misspelt name, a dropped student -- and that can change how many
pages each student gets. Two runs, one seed, **different
page-to-student mappings**. Resolving a scanned code by seed would
not fail; it would quietly attribute papers to the wrong students.

**The decision.** The record allocates a `run_no` per course, the
code carries that, and `meta.last_run_no` is a high-water mark so a
deleted run's number is never issued again. Rebuilding into the same
folder keeps its number, because one folder is one printing event.

Two things fall out of it:

* **The code got shorter.** A run number is 1 to 3 digits where a
  seed is 10, which is what made level M affordable at 9mm.
* **No record, no code.** A build with no course, or
  `build --no-record`, allocates no number -- and then `\setrunid` is
  not written at all, which switches off the index and the symbol
  together. A code naming a run that was never recorded would be
  worse than no code, because it looks readable right up until the
  scanner.

**What is still open:** a run number is unique within a course, not
across courses, because the record is per course and Scans is
course-scoped. If Scans ever reads a stack spanning two courses it
will need the course as well.

### 14.6 Brightspace

Rewritten 2026-10-22 against a real export from the live course
(`MAT106-820`, 60 columns, 22 rows). Most of what general research
suggested was wrong for this course, so **the file is the
specification, not the documentation.**

#### What the real file looks like

* The identifying column is **`OrgDefinedId`**, first. There is **no
  `Username` column and no name column of any kind** in a grades
  export.
* Skills are **`<slug> Grade Symbol <Selectbox MaxPoints:1
  Category:...>`** -- *Grade Symbol*, not the *Points Grade* the
  guides describe, because these are selectbox items.
* The two values in use are **`🏆Pass`** and **`💭Not Yet`**, emoji
  included.
* Last column **`End-of-Line Indicator`**, `#` in every row.
* UTF-8, no BOM, LF line endings.
* Three categories: Core Skills Progress (22), Explanation Skills
  Progress (7), Modeling Math Videos Progress (8).

#### A blank cell is not missing data

**The subtotals count the cells that are filled in.** Verified on all
22 rows: `Core Skills Progress Subtotal Denominator` equals the number
of non-blank core cells, and the Numerator equals the number of
passes.

So writing `💭Not Yet` into a blank cell **raises that student's
denominator and lowers their grade.** A blank means the skill does not
count for them yet.

**The export must only write a cell where the student has actually
attempted that skill, and must leave every other cell exactly as it
found it.** This is the single most dangerous thing in the feature.

#### Rows and columns printit must not touch

* **`-DoNotUse` rows.** The export contains one: the same base id as a
  live row, a retired enrolment. More generally, **printit never adds
  or removes a row** -- it fills cells in rows that are already there.
* **Columns it does not own**: the videos `V1`-`V8`, the formula
  totals, the subtotal numerator/denominator pairs, Final Course
  Grade, Midterm Grade Estimate, Final Exam Percentage, PAHW, Tokens,
  the Calculated and Adjusted Final Grade pairs, and the grading
  scheme reminder. An unrecognised column is left alone, always.

#### The two lists do not match, and will not

Comparing the bank with this export:

* 28 slugs match exactly.
* **`FCP` is `Fundamentals Checkpoint` in Brightspace**, spelled out,
  and sits outside any category. It needs a mapping.
* **`F5-E` exists in Brightspace and not in the bank** -- the outcome
  folder is there but the slug is not published in `bank.xml`.
* The eight videos are not printit's business at all.

**Settled: match on slug, then ask.** Where a slug matches a column,
use it. Where one does not -- `FCP` against `Fundamentals Checkpoint`
-- **ask the instructor whether a column already exists, and let him
pick it from the columns that went unmatched.** The answer is
remembered.

That is better than a hardcoded table of exceptions, because the
exceptions belong to a course rather than to the tool: another
instructor's bank and another institution's gradebook will disagree
in their own way. Anything still unmatched after that is left
untouched.

#### There is no way to identify a student yet

**This is the blocker.** Brightspace uses a 10-digit `OrgDefinedId`
prefixed with `#`. The roster carries a 9-digit SID. **The overlap is
zero**, `alt_id` is empty for all 45 students, and the grades export
carries no names to fall back on.

**Settled: a classlist import.** A CSV from the LMS is imported once
a term, the id is stored on the roster, and the Roster tab shows it in
a column called **LMS ID** -- named for the job it does rather than
for Brightspace, since the next institution will call it something
else.

Matching the import's rows to the roster is the same reconciliation
problem a class list import already has, and should use it.

#### What export therefore is

Not "generate a CSV". It is: **take the file he exported, fill in the
cells we have a graded result for, change nothing else, hand it
back.** Same column order, same rows, same untouched values, UTF-8
out.

#### What counts as a pass

The instructor's rule: **the pass symbol passes, and everything else
does not.** A `?`, a blank, and any mark another instructor invents
all export as `💭Not Yet`. Nothing exports as "partial".

### 14.9 Matching a student to Brightspace (decided 2026-10-24)

The blocker that had held 14.6 since 10-21, and the answer is neither
of the two options that had been written down.

**The instructor imports a CSV with two useful columns**: the LMS id,
and something this tool already holds -- an email address or a SID.
The join is on the second, and the first is what gets stored.

Why this and not the alternatives:

* *A classlist import once a term* assumed the LMS id arrives with the
  registrar's data. It does not have to, and tying the id to a
  whole-roster import makes a fifteen-second correction into a
  re-import.
* *`Username` from the grades export* assumed one particular column of
  one particular export would always be there and would always be the
  join. Reading a real export on 10-22 is what put that in doubt.

What it needs:

* The import names its own columns. Which column is the id and which
  is the join key are **chosen by the instructor at import time**, from
  the headers actually in the file, rather than matched against a list
  of names the tool hopes to see. The same rule `form map` already
  follows: ids, not positions, and nothing guessed.
* A join on email is case-insensitive and tries every address the
  roster has seen, which is `Student.all_emails()` and already exists
  for exactly this reason.
* A row that matches nobody, and a roster student no row matches, are
  both **reported rather than dropped**. That is the `form pull`
  pattern, and the same reasoning: a silent near-miss is how a student
  goes missing from an export.
* Where it is stored: `Student.alt_id` already exists and is
  documented as "the other id system, when an export carries it". No
  new field.

Still to decide, and smaller than the thing it unblocks: whether a
second import updates ids in place or refuses when it disagrees with
one already held.

### 14.7 Build order

1. ~~**Runs.**~~ **Done 2026-10-24.** The list, the detail page,
   delist/graded, reprint and reuse.
2. ~~**The page marks (14.5).**~~ **Done 2026-10-25**; see 14.10.
   **Installed in mat-106 and pushed 2026-11-05**, so every paper
   printed from that bank from now on carries them. What Scans can
   rely on:

   * every page carries `C1-<runid>-<page>`, 9mm, level M;
   * `main.pages` in the run folder maps page -> kind, student,
     skill, version, sheet;
   * the same file gives the rectangle of the grading box, the id
     field and the name, for cropping out of a scan;
   * the run number resolves to exactly one run, even across
     reprints that share a seed;
   * `pypdfium2` renders a scanned PDF and `zxing-cpp` reads the
     codes off it; both are already dependencies.

3. ~~**Scans.**~~ **Done 2026-10-27**, and rebuilt 2026-11-02/03
   into the shape section 16 describes: two sortable tables instead
   of three stacked lists, re-matching, a mark track, and a save that
   refuses an undecided row. Cropping, classifying, the review grid
   and saving are all in. A paper printed without a name finds its
   own student from the id grid.
4. ~~**Progress.**~~ **Done 2026-10-27.** The grid, thresholds, the
   recent highlight, and a drill-in that edits. No section filter --
   that was always a later job.

### 14.8 Still open

Three of the five that were here on 10-21 are now answered and have
moved into the sections above: what "recently" means (the last two
grading sets, toggleable), how a custom mark exports (only the pass
mark passes), and what Brightspace actually wants (14.6, rewritten
against a real file).

What remains:

* ~~**How a student is matched to Brightspace.**~~ **Decided
  2026-10-24.** Neither of the two that were on the table. The
  instructor supplies a CSV holding the LMS id in one column and
  something printit already knows in another -- an email address or a
  SID -- and the import joins on that. See 14.9.
* **Where thresholds are stored** -- a new course file, or a table in
  an existing one.
* ~~**How much classifier to build.**~~ **Decided, and it fell in
  two different places for the two readings.** The grading box is
  geometric and always will be: what separates a tick from the
  printed form is that the instructor's pen is *coloured* and
  everything else in the crop is grey, which no model is needed for.
  The handwritten id is a trained one -- 372KB of numbers in
  `digits.npz`, trained by `tools/train_digits.py`, inference in
  numpy so nothing new installs. He chose that on 2026-11-03 over
  installing a model runner or writing shape rules by hand.
* **Whether Scans can place a page whose run is unknown** -- an old
  paper with no code, from before 14.5 ships. Everything printed to
  date is such a paper, so this is not a corner case for the first
  term that uses Scans.
* **Whether a run number needs its course.** It is unique within a
  course and Scans is course-scoped, so today it does not. A stack
  spanning two courses would need one. See 14.12.
* ~~**What the Scans tab does with a spare.**~~ **Read
  automatically, 2026-11-03.** The grid is found by its own top rule,
  the nine cells are read, and the result is matched against the
  roster rather than looked up as a number -- so the name lands in
  the name column the way a printed code's would, with the section
  filled in. The handwriting beside it is ringed in warning yellow,
  on those rows and no others, because they are the only ones where
  it is the sole check. A grid that cannot be read clearly enough
  leaves the row blank for him rather than guessing.

  Spares also *appear* on the tab now. `_review_rows` grouped on
  `kind == "student"`, so a spare -- printed with an empty name for
  exactly this purpose -- was dropped and could not be recorded at
  all.
* **`F5-E` is to be added to the bank.** Still open, and sharper
  than it was. `outcomes/F5-E/` exists, and `bank.xml` *does* mention
  the slug -- but inside an `<associates>` block, pointing at
  `outcomes/F5`, and **nothing reads `<associates>`**: the word does
  not appear in `dashboard/checkit/` or in printit outside a doc
  test. So it generates nothing and publishes nothing, and
  `assets/F5-E/` has never existed. It needs a real `<outcome>` entry
  with `<path>outcomes/F5-E</path>`, the way F2-E has. A
  `mat-106-checkit` job, before the export is written.

---

## 15. Roadmap (2026-10-22)

**Moved to `../checkit/ROADMAP.md` on 2026-11-17**, which is now the one
list of what is left in every repo. The section as it stood is kept
word for word in `CODEBASE_NOTES.md`, "The design document's section 15,
as it stood before 2026-11-17".

## 17. The Progress tab (2026-11-05)

Read before changing anything on that tab. What is here was settled
after driving it on a 24-student, 29-skill course built for the
purpose -- the only course with real data has real names in it, and
no demo course on the machine had a single attempt recorded.

### What was found

**The record behind it is sound.** Audited against the live MAT 106
file: no attempt without a run, no printed row without a run, no run
number used twice, `meta.last_run_no` and the highest `run_no` agree,
and no run marked ungraded while holding marks. `write_run` keys on
the output folder, so building into one twice is a single event.
`save_attempts` upserts on (run, student, skill), refuses an unknown
outcome, marks the run graded in the same transaction, and reports a
pair missing from `printed` rather than dropping the decision.

**The grid has no sorting at all.** `makeSorter` -- the stacked
machinery the Roster and both Scans tables share -- is not wired to
it; `renderProgress` builds its head and body by hand. No section
bands either, and no name-order swap, so Progress and the Roster can
show names in two different orders at once.

> **Closed.** `progressSort` is a `makeSorter` over
> `progressColumns`, which now holds the name column (with the
> Roster's `swapby` control in its heading), the section column and
> one column per skill, each sorting worst-first by `cellSortKey`.
> Checked on 2026-11-08 by clicking the Section heading **with a
> real pointer**: the headings came back `Sec` with priority 1 and
> `last name` with priority 2, and two section bands appeared.
>
> `element.click()` reported the opposite -- nothing moved -- which
> is the footgun this repository already has written down: it runs
> a handler without hit testing or any ancestor's listeners, so it
> can report either answer regardless of the truth. It was believed
> for one round here before the real click was tried.

**Six of the seven cell states draw no glyph.** Only `passed` has
one, a tick. The rest are told apart by CSS: a 13px outlined box, a
dashed one for "never sat", an amber border and background for
"stuck", a 5px corner dot for a query. Two consequences worth fixing:
"never printed" and "printed, not passed" differ only by whether that
box is drawn at all; and **the number beside a tick means two
different things** -- `2` is "passed on the second attempt", `2/2` is
"two of the two passes needed", same place, same styling.

**The name column and the header already stick** while the grid
scrolls, both measured. Nothing to do there.

### Decided: columns stay as they are, for now

At 29 skills the grid is mostly blank -- in the demo, 596 of 696 cells
are `none`. The obvious answers are hiding skills nobody has been
printed, or a skill picker in the toolbar.

**Neither, yet.** Which skills are live is moving out of the Update
form tab to somewhere of its own, and the grid's columns will come
from that when it does. Building a second way to choose them now
would be the thing this codebase keeps doing: two mechanisms for one
decision, and the one nobody looks at drifts.

### The drill-in: what it has to lay out (2026-11-07)

Blocked until now on content that was not settled. It is settled.

Per paper, oldest first, for one student and one skill:

| | |
|---|---|
| when | the run's date |
| which job | title, and the run number |
| which paper | version and seed, so the sheet can be found |
| what the reader said | `reading` -- beside what he decided |
| what he decided | the outcome, set here and saved on the click |
| the picture | `scan` and `scanPage`, when the stack is still here |
| flags | `rebuilt` (the seed is not what was printed), `delisted` |

Papers printed and never scanned are in the list -- `history` is
driven off `printed` -- which is the point: that is a sheet he may
be holding.

**What it must not do**, from section 13 and from the current one
breaking all three: run facts together with separators
(`Checkpoint 1, version A, seed 998` is the banned tic verbatim);
say with a sentence what a layout can say (`scanner read it as
empty`); or put an explanation in the open rather than behind a `?`.

Three layouts were drawn against the real stylesheet -- rows with
air, a table, and a timeline -- and the timeline is the one to
build: it is the only one that shows the *shape* of a student's
attempts, which is what he opens this to see. Still open: whether it
stays a modal or becomes a side panel with next/previous, which
changes the width the layout gets.

### Three fly-out timelines, drawn (2026-11-07)

A panel, not a modal. The grid stays visible behind it and the cell
it came from stays lit, so working down a column after a scan does
not mean closing and reopening one dialog per student. That costs
width -- about 400px against the dialog's 620 -- and the width is
most of what separates the three.

Two fields were dropped before drawing:

* the **version letter**. It tells one paper from the other versions
  of a run. In a list of one student's own papers there is nothing
  to tell apart.
* **what the scanner read**. The final mark is the answer; the
  reading is how it was arrived at, and belongs where a disagreement
  is being looked into, not in every row for ever.

The code is `tools/mockups/drillin.js` in checkit-printit, and it
draws inside the running app with the app's own stylesheet, so these
are the real marks at the real sizes. All three share a header
(name, section, skill pill, the grid's own verdict) and a footer
that steps to the student above or below.

| | shape | per paper | holds |
|---|---|---|---|
| **A** node and card | dot on a rail, card beside it | date / run and number / a labelled `SEED` row with *see the paper* beside it / the mark track | 4 attempts |
| **B** tight | same rail, two lines a paper | date and seed on line one, run and the mark track on line two; the paper is an icon | 8-9 attempts |
| **C** the work itself | the scanned page is the node | thumbnail with the mark as a corner badge, then date / run / seed / mark track | 4 attempts |

**A** is the most legible and the least dense. Nothing is run
together with commas, which is the tic section 13 bans, and the seed
gets a key above a value rather than a `seed: 998`.

**B** fits a whole term without scrolling, which matters for a skill
a student has attempted eight times. It is also the one with no
slack: at 400px the right-hand group (paper icon plus four marks)
wants about 210px and leaves 190 for the date and the run, so a
longer run title will crowd it.

**C** is the only one that answers what he said the paper is *for* --
seeing how the working changed -- without opening anything. It costs
the most vertical room per attempt and needs a real page render
behind it, not a cutout.

### Built: the drill-in is a panel (2026-11-08)

C, with the header of H3. Drawn in `tools/mockups/drillin-c.js`
before it was built, which is why the sizes below are measured
rather than guessed.

Four things came out of the panel after it was drawn:

* **the seed.** It is how an exercise is found again, which is a
  thing to look up when a question is wrong, not a thing to read
  down a list of four attempts.
* **the version letter.** It tells one paper from the other versions
  of a run. Among one student's own papers there is nothing to tell
  apart.
* **the attempt number.** `#1`, `#2` counted out loud what the
  timeline had already said by putting them in order.
* **the scanner's own reading.** The final mark is the answer; the
  reading is how it was arrived at, and belongs where a disagreement
  is being looked into.

What is left per attempt is the page, the date, the run, and the
mark -- and with the seed and the number gone the mark track comes
up directly under the run with nothing between.

**The page is the control.** Not the words "see the paper": a
control standing in for a thing should look like the thing, and a
phrase where a control belongs is the tic section 13 bans. Clicking
one opens the whole page in the viewer the Scans tab already uses.
Where nothing was scanned there is no picture to click, and the
empty dashed frame says so without a sentence.

**The page has no height of its own.** It is a grid item, so it
stretches to the row, which means it ends exactly where the track
ends -- the bottoms line up without a number being chosen. The row
comes out 76px for a 54px-wide page, a ratio of 0.71, which is about
what a letter page is, so it keeps looking like a page without being
told to.

**The track is one size down from the Scans table's**, 28x22 against
34x26. In the table it is the widest thing in a row of plain text
and carries the column; in the panel it sits under two short lines
beside a small page, and at the table's size it was the loudest
thing there.

**Headers considered.** The awkwardness of the first draft was two
separate things: the name and section were stacked, making a tall
row with little in it, and the right-hand half was empty. H1
(tightened) fixed only the first. H2 put the cell's verdict in the
empty half as a stat -- shortest, but it made the verdict compete
with the name for what the panel is about, and the verdict is
already visible in the cell that was clicked to get here. H3 won:
the name on its own line, then a tinted strip carrying slug, title
and verdict. It is the tallest, and the only one where the student
is plainly the subject and the skill is plainly context. Said with
the layout, not with a label.

**It takes width rather than floating over.** The first build fixed
the panel to the right edge, over the grid. That was wrong, and the
reason it was wrong is the reason the drill-in is a panel at all:
the cell it came from stays lit so you can work down a column, and
an overlay hides exactly the right-hand columns. Measured on a 24 by
29 grid at 1400px: a cell at x 1015 sat under a panel starting at
1000, and the grid lost about two columns across every visible row
with no way to reach them but to close the panel.

`body` was already a flex row -- nav rail, then `main` at
`flex: 1 1 auto; min-width: 0` -- so the panel became a third item
beside them. No margin on `main`, no JavaScript. `main` is capped at
`max-width: 1100px`, so above about 1690px of window the panel costs
the grid nothing at all; below that the grid narrows and keeps every
column reachable by scrolling sideways, which it already did.

Below 900px there is no width to share, so the panel goes back to
covering. Material's side sheets and Liferay's sidebar both switch
at about there, for the same reason.

What the field does is split, but split by purpose rather than
fashion. Overlay is the default for a temporary, focused, mostly-read
task -- Material's modal side sheet, Carbon's shell right panel.
Push is what gets recommended where both halves are worked at once,
and Workday says the case almost exactly: where the panel edits
content within the page, keeping it open and resizing the page
content may be ideal. That is this panel -- it sets a mark, and the
grid behind it is what shows the mark.

**One thing push brought with it.** Narrowing the grid can scroll
the lit cell off the right edge -- losing sight of it by scrolling
rather than by covering, which is the same failure wearing a
different hat. The panel scrolls it back into view on open, and
again after the grid is redrawn by a saved mark.

**240px.** It was 400 from the mockup, where the panel was drawn
against a 620px dialog to show what the narrower shape cost, then
320, and both were read off the wrong thing.

The width should come from whatever cannot give way, and only one
thing here cannot: the mark track is 117 when it carries four
stops. The page beside it is 58, the gap 12 and the padding 32, so
219 is the floor and 240 is that with a little air. Measured across
fourteen students, the widest date is 99 and the widest student
name 93, both inside it, and a run title wraps.

320 came from the strip, which wanted 295 at the time. But the
strip holds the skill's title, which wants 434 for a long one and
has an ellipsis -- so it would have asked for any width it was
given. A part that can give way should not set the width. Both the
title and the student's name ellipsize now, with tooltips, so the
grid never pays for a long one.

**The header shows the cell, not a sentence about it.** It said
"1/2 passed" or "passed" or "no passes yet". It now draws the same
glyph or the same bare fraction the grid drew, wearing the same
state and tone classes, so an amber cell is amber in the header and
a red one red. A cell with nothing recorded shows nothing, which is
what the grid does too. The words moved to the tooltip, which is
`describeCell` -- the same sentence the cell itself says when
pointed at.

That is one declaration per colour, not two: the drill-in's class is
named beside each `td` in the grid's own rules rather than given a
copy of the values.

### Decided: the cell vocabulary (2026-11-07)

Seven states drawn as outlined boxes became five marks, agreed cell
by cell. **No box, plain or dashed, anywhere.** The two glyphs that
are not a tick come from the app's existing icon set -- `fail` and
`query`, the same ones the drill-in's mark track uses -- so a cell and
the control that sets it show the same shape.

**A sitting is an attempt that is not an absence.** "Did not sit" is
still recorded and still shown in the drill-in and the tooltip, and is
invisible to everything else: it changes no glyph, no highlight and no
sort. A cell whose only attempts were absences is a blank cell.

The glyph, first match wins:

| | |
|---|---|
| no sittings | nothing at all |
| `passes >= threshold` | a tick, and no number |
| `passes > 0` | the fraction `passes/threshold`, and no glyph |
| the most recent sitting was a query | `?` |
| otherwise | `✗` |

**A tick never carries a number.** `✓2` meaning "passed at the second
go" and `✓2/2` meaning "two of the two passes needed" were the same
shape in the same place saying different things. With counts gone from
the tick, a fraction is the only number on the grid and can only mean
one thing. How many goes it took is in the drill-in.

**A query only replaces what there was nothing else to say.** It takes
the place of the `✗`, never of a fraction and never of a tick: a cell
part way through has a number worth more than the fact that the last
paper is in question, and a skill already passed is settled. The amber
background is what carries an open question in those two cases.

The background, at most one:

| | |
|---|---|
| green | passed, and passed in one of the last **N** graded runs |
| amber | not fully passed, and some sitting was a query |
| red | no passes at all, and **R** sittings or more |

**Amber beats red** where both apply. A query means the cell is not
decided yet, and "this student is stuck" is a judgement the query may
overturn. One line to flip if that reads wrong in use.

Green cannot collide with either: it needs a pass, and both the others
need the skill unpassed.

**N and R are the person's, not the course's.** Kept in
`localStorage` beside `filedNames`, for the reason already written
against the old "light up what just came back" switch: how the grid is
lit is a preference of whoever is reading it, and two people looking
at one course should not fight over it. Nothing is written to the
record, so the tab stays read-only and needs no save bar.

`N = 0` is off, which is what the switch it replaces did by default.

**The toolbar is the legend and the legend is the control.** A tick
box, a sentence explaining it, and a muted note saying "the last 2
grading sets" were three things saying one thing -- and `#progress-key`
was an empty span that nothing ever filled. One strip now: each mark
beside its own short label, with the two numbers editable where they
are read.

### Decided: the grid stays about results

`record.progress()` reads `FROM attempt`, so a student-and-skill that
was printed and never graded has no cell and reads exactly like a
skill never offered. On the live record that is **456 of 542 pairs**.

The data is there -- `printed` holds it, and `history()` already uses
it, which is why the drill-in knows and the grid does not.

**It stays out of the grid.** The grid is about results; the drill-in
is where a paper printed and never marked is visible. Making it a
cell state would put a mark on 84% of the grid, and a mark on 84% of
anything is a background.

## 16. What the Scans tab shows after a read (2026-11-02)

**Written down because it was lost.** This was agreed from three
mockups over a couple of messages, built a day later from a one-line
description of it, and came out wrong in four ways at once -- no
glyphs, chips in the page header instead of on the job, a card that
was not a card, and wordier than what it replaced. The design lived
only in the conversation, and a conversation is not a place to keep a
decision. It lives here now.

**The rule this leaves behind: a mockup that is agreed gets written
into this document before it is built.** Not into the commit, not into
the notes -- here, where the next piece of work reads it.

### The job header

One card per print job the stack came from.

    +---------------------------------------------------------------+
    |  Skill Checkpoint   10/26                                      |
    |                                                                |
    |  62 matched   1 blank        [(x) 24 missing]  [(?) 2 unmatched]|
    +---------------------------------------------------------------+

* **A card**: panel background, hairline border, `--r-md`.
* **Title** at `--t-lg`, then the date **`m/d`** in `--muted`. Not the
  long spoken form -- that belongs on Update form, where it matches
  the wording a student ticked.
* **Settled facts, plain text, left**: `62 matched`, then `1 blank` in
  `--muted`. Matched counts **papers, not sheets**: a double feed puts
  one paper through twice.
* **Work, as chips, right**: `--warn` on `--warn-soft`, filled rather
  than outlined, because the outlined `.chip` is how the app says "a
  small fact" and this is the opposite. Each carries the mark he would
  make on the paper himself -- the struck-through sheet (`absent`) for
  one that never came back, the `?` (`query`) for one that could not
  be placed. **Absent at zero**, never "0 missing".
* **A chip never wraps.** A card two rows tall with one word on the
  end of it is the thing this layout exists to avoid. When the words
  stop fitting, the chips drop to **glyph and number** -- the number
  stays, because a glyph alone says which problem and not how much of
  it -- and the words come back when the room does.
* **All the cards change together.** If one card's line is short of
  room, every chip on the tab collapses, so two cards side by side
  never disagree about how a count is written. `fitChips()` always
  measures in the roomy state and a `ResizeObserver` on the container
  re-runs it; measuring in whichever state happens to be current is
  how a fitter ends up flapping between two answers.
* **No totals, no bar, no run badge.** The page total is on the drop
  strip already; `matched + missing` is the job.

`unmatched` is the three statuses marked `chase` -- no code, a code
naming a job this course has not got, a page past the end of the job
it names. **Not `foreign`**: a barcode from something else is a cover
sheet, and chasing it is chasing the copier.

Blank and unmatched belong to the *pile*, not to a job -- the pages
carrying them name no job. With one job, which is the ordinary case
and what the mockup shows, they go on its card. With several they
would be a guess, so they get a card of their own.

### The drop area

Built, and still as agreed: one control, three states. Idle is a
dashed rectangle with the seating app's filled accent `+` circle.
Dropping reads straight away -- there is no second decision to
confirm, and no button beside it, ever. While reading it folds to a
one-line strip that **is its own progress bar**, filling left to right
in `--accent-soft` as the pages are read, with `n / total` as the only
words. When it finishes the fill goes grey over 700ms and the strip
reads `13 pages . 2 files`.

### Still to build

The collapsible **"Everything in the stack"** goes. Two tables stand
in its place: the matched papers, then the pages that could not be
placed. The duplicates section goes with it -- it still reads in the
old voice, a five-word heading over a three-line muted paragraph.

#### The matched table

Not sure / unsure / the rest. **One table of every matched paper**,
sortable. Taken from the mockup, left to right:

| column | what is in it |
|---|---|
| Last name | `Lovelace, Ada`. Carries the roster's own last/first swap control |
| Paper name | **the cropped name image** off the paper |
| Section | `820` |
| Skill | `N3` |
| Confidence | the dial: a ring with a number in it |
| Paper mark | **the cropped box area** -- the photograph of his own tick |
| Mark | the four marks, the current one filled |

One row height, everything side by side.

The last two are **Paper mark** then **Mark**: the picture of what is on
the paper, then the decision. The mockup labelled them `Paper box` and
`Paper mark`, which was the older naming.

`Confidence`, not `Sure`. It is the longer word by about 30px beside a
34px dial -- measured, not guessed -- and that is cheap on a table this
wide. If it reads fat in place, `Sure` is a one-word revert.

* **Sortable on every column**, with the header showing direction and
  **priority number**: the default is `Sure` descending (1), then
  `Section` ascending (2), then `Last name` ascending (3).
* **Nothing-scanned rows sink to the bottom** when sorting by
  confidence: muted name, `--` for the paper name and the paper box,
  `n/a` in a grey dial, and `absent` already chosen in Paper mark.
* **Paper mark** uses the app's existing `GLYPH` marks -- `pass`,
  `query`, `fail`, `absent` -- and colours the **background** of the
  chosen one, never the glyph alone.
* **The dial already exists** -- `sureDial()` in `app.js`, `.suredial`
  in the stylesheet, built for the old review grid and lifted as it
  is. Out of ten, `Math.round(sure * 10)`, never a percent, because a
  percent reads as a measurement and this is a judgement about a
  judgement. The ring is a conic gradient drawn from the **rounded**
  tenth so the ring and the number can never disagree. `>= 8` is
  `--accent`, `>= 6` is `--midway`, below that `--warn`; a paper that
  never came back gets `n/a` in `--dim` and no ring at all.

The sort machinery is the roster's and must be **lifted, not copied**
-- `sorts`, `SORT_DEPTH`, `DEFAULT_SORT`, `cycleOf`, `columnOwning`,
`rankOf`, `sortBy`, `clearSort`, `sortRoster`, `renderHeader` are
welded to the `COLUMNS` global and to `renderRoster()`. All the name
options come too, last/first swap included.

Its student dropdown guesses from the box slug and the name crop, but
**not exclusively**: guesses at the top, then every other name in
roster order, by surname within section.

#### The unplaceable table

| column | what is in it |
|---|---|
| Preview | a thumbnail of the page |
| File | `copier-2.pdf` |
| Page | `7` |
| Description | `Blank`, `No code found` |
| Match | `--`, or a **"Match to..."** control |

The action is **"Match to..."**, not "Assign to". A blank page gets
`--`: there is nothing to match it to. Pick the skill first, then the
student -- from anyone in that job who took that skill, read from the
`printed` table, because not everyone takes the same skills in a run.

#### Built, and what it came out as

All of section 16 is built. What changed on the way, so the next
reader is not working from the sketch:

**The columns** are `Name`, `Paper name`, `Sec`, `Skill`, `Conf`,
`Box`, `Mark`. `Name` rather than `Last name`, because the heading is
rendered as `<note> <label>` and follows the name-order switch beside
it -- `Last name` produced "last last name". `Sec` and `Conf` because
`Section` and `Confidence` were wider than the things under them, and
`Box` then `Mark` is the crop of his tick followed by the decision.

**One row height**, 36px, set by the line box rather than by the
content: a cell's `height` is only a floor, so a row of dashes came
out shorter than a row holding a crop. The crops are the row's height
too, which is also what made the marks readable without squinting.

**The Mark column is a track** -- one pill with the verdict filled in
place -- chosen over three squares and over a segmented box because
the filled spot then sits somewhere different in each row, so the
column's shape says the shape of the marking before any of it is
read. Honest here only because the three marks are an order he reads
in; it would be a lie for an unordered set.

**Re-matching** is option B: click the name, a `rematch` button
appears, click that for the picker. The glyph is his -- a person, an
arrow, a person -- drawn at **21px**, not the 18 the rest of
`.iconbtn` uses, because two figures and an arrow is more ink than
the rest of the set and at 18 the arrow closes up. The button is
pinned to the right edge of the name column rather than following the
end of the name, which landed it somewhere different on every row.

**Two papers can claim one student for one skill**, and both a
re-match and a hand match can cause it. Every row in such a pair wears
a `warn` triangle at its left -- at the left so that a different sort
can throw the pair apart and both ends still carry it. Computed on
every draw, so it travels with a row and clears itself the moment the
clash is resolved; a flag stored on the row would outlive the clash
that earned it.

**The unplaceable table** is `Preview | File | Page | Description |
Match`, and the preview is the point of it. The thumbnail is cut in
`read_page` while the page is still in hand, at 150px, and **only for
the pages that failed** -- `Sheet.cuts` exists because the full render
is thrown away immediately, and a thumbnail of every page would walk
back into the memory problem it was built to avoid. A blank page gets
no Match control, there being nobody to match it to.

**Match to...** asks the skill first and the student second, because
the skill narrows the field: on a redo each student takes one or two
of fourteen skills, so "who took N3" is a far shorter question than
the other way round. A hand-matched page joins the matched table with
no box crop and no confidence -- the reader found no anchor, which is
why it was unplaceable -- so Box shows a dash, the dial says `n/a`,
and the mark is made from the preview.

**Gone with it**: the fold-away listing of the whole stack, which was
94 rows to find 4 in, and the duplicates table, which said what the
matched table already says as two crops in one row.

#### Still open

* **Saving is built**, and this list said twice that it was not --
  from a stale comment in the old review code, `"the saving is one
  action at the end, and it is not built yet"`, which predates the
  implementation and was repeated without being checked.

  What it does: Save posts the decisions to `/api/scan/save`, which
  matches each one against `SCANNING.result` -- the server's own copy
  of the read, never the page's -- and calls
  `record.save_attempts()`. That writes one attempt row per paper
  into the course's `record.db` and marks the run graded. The
  Progress tab has no storage of its own; `api_progress` reads
  `record.progress()` out of the same file, so saving a stack is what
  puts marks on that grid.

  The one real limit: `SCANNING.result` lives in memory for the life
  of the process, so a restart between reading and saving loses the
  stack. The handler says so rather than taking the page's word for
  whose paper was whose.

* **A re-match or a hand match does not reach the record.** Found by
  asking what Save actually writes, and it is a real fault in the work
  above rather than something left for later.

  The browser sends `{id, outcome}` and nothing else. The server
  builds its rows from `SCANNING.result`, taking `sid` from its own
  copy of the read -- so a paper re-matched on screen **saves against
  the student the code originally named**. A hand-matched page is
  worse: its id is `hand-<file>-<at>`, which matches no row in the
  server's review list, so it is skipped and nothing is written at
  all. In both cases `saveScans` then sets `row.saved`, so the page
  reports success.

  The server is right not to take the page's word for whose paper is
  whose -- that rule is why a restart refuses rather than guesses.
  The fix is to widen the contract rather than drop it: send `sid`
  and `skill` with the decision, and have the server accept them only
  when the `printed` table says that student was handed that skill in
  that run. That is the same test `rematchPool` applies in the
  browser, enforced where it counts.

  **Fixed, that same day.** `owner()` in `api_scan_save` does exactly
  that, and a hand-matched page is now found by the file and page it
  came out of rather than by an id the server has never seen.
* **A clash is warned about and not prevented.** Two papers may still
  be saved against one student and one skill if he ignores the flag.
  Whether the Save should refuse that is undecided.

### The handwritten id (2026-11-03)

On a run printed with `names = false` the header draws a ruled blank
for a name and a grid of nine cells for the student's id. Nothing on
such a sheet says whose paper it is: `assemble` writes no student into
the index for a blank-name handout, so the footer code places the page
and says nothing about its owner.

The grid exists so the program can work that out. It reads the nine
digits, finds the student, and puts the **name** in the name column --
the same column a printed code fills. The check is the handwritten
name in the column beside it, which is ringed in warning yellow on
these rows and only on these rows: every other row has a printed name
to agree with, and a highlight that is always on is not a highlight.

#### Finding the cells

The grid's position is arithmetic off `\cipidgrid`'s own lengths --
nine 4.4mm cells with a 0.4pt rule between each pair -- and
`\cipmark{id}` records the framebox exactly, to within a pixel at
200dpi on the original PDF.

On a *scan* that rectangle lands about a millimetre out. The transform
is fitted from the footer code and its scale pinned by the footer's
grading box, and the header is nine inches from both, so a fraction of
a degree down there is a millimetre up here. A millimetre is nothing to
a padded name crop and a quarter of a 4.4mm cell.

So the grid is found rather than predicted, by its own top rule: 40mm
of straight line in a header that holds no other. Its ends give the
left and right edges and so a width, which is checked against the
prediction -- past 3% the find is thrown away and the grid is reported
as unplaceable rather than cut from the wrong place. That check is also
what answers "does this work on another scanner": a differently scaled
scan either works or says it could not place the grid.

The nine *vertical* rules are the obvious landmark and the wrong one.
They print at 0.4pt in 30% black, paler than anybody's pen, so a comb
fitted to them locks onto a digit's downstroke -- which it did, on two
of the first four real pages, half a cell out and confident about it.

#### Reading them

Not by reading nine digits and looking the number up. The question is
which of the students on the roster wrote them, and in MAT 106 that is
forty-five people whose ids differ in at least two places and usually
three or four, with the first three digits the same on every one. So
each candidate is scored on how likely its own digits are, and one
misread digit costs the right student a little and the wrong ones a
lot.

The recogniser is one hidden layer, 372KB of numbers in
`data/digits.npz`, trained by `tools/train_digits.py` on MNIST with the
strokes thickened and thinned. Inference is a matrix multiply, so this
adds no dependency: numpy was already needed to read a scan at all --
indeed it was needed and undeclared, and is now declared along with
Pillow.

The effort went into *presenting* a cell, not into the model. MNIST's
digits are scaled to a 20x20 box and centred on their centre of mass in
a 28x28 field, and a cell handed over as it comes off the page is a
different shape from anything the recogniser has seen. Same recipe, and
a one-layer net then reads all thirty-six real digits.

#### How it knows it is unsure

The usual signal is how far the winner leads the runner-up, and here it
is useless. With the true student removed from the pool the lead stayed
at 9.2, 9.0 and 9.2 on three pages out of four -- as wide as when the
answer was there -- because the *least bad* candidate still beats the
next one easily. The lead measures how spread out the pool is.

The winner's own score is the signal: between -0.15 and -1.23 with the
writer in the pool, and between -8.59 and -10.20 with that student
taken out. The threshold sits at -4.5, between the two groups rather
than at the edge of either, and a page that cannot clear it is left
blank for him to match by hand. An invented student he has to catch is
worse than a blank row, because the blank row is the one he looks at.

**This is one stack**: four pages, one scanner, two pens, thirty-six
digits. A clean sweep of thirty-six would still happen one time in six
at a true accuracy of 95%, so it is encouragement and not proof. The
thirty-six are kept as a fixture in `tests/data/real_digits.npz`.

#### Still open there

* **No second scanner has been tried.** The rules came back at 205 to
  235 against paper at 250 to 255 on his copier. A machine that runs
  darker or lighter would move both the rule-finding and the ink level,
  and the 3% width check is the only thing standing behind it.
* **A spare still has to be matched by hand** unless its writer filled
  the grid in, which is the same situation as before for anybody who
  leaves it blank.


## 18. Sharing a file without sharing the students (2026-11-08)

The instructor's requirement, in his words: *"I need you to come up
with a way, such as some sort of script, that will mask the student
data before you see it, then unmask it before I use it."* Not a
preference -- real student data must not reach an assistant at all.

That is also the thing standing in front of the gradebook work, since
§14.6 settled that export means round-tripping **his own exported
file** and nobody can write that round-trip against a file they are not
allowed to look at. So this came first, and it unblocks rather than
delays.

### Built: `checkit-printit vault`

One fake person per real person, in a vault outside every repository,
substituted wherever the real one appears. `vault mask` writes the
twin, `vault unmask` turns whatever comes back into the real thing,
`vault columns` shows what would happen without writing, `vault check`
scans any file, `vault show` lists who is in there.

### Four things the obvious version gets wrong

**It must map people, not strings.** A class list says `Quill,
Theodore J.`, a seating chart says `Teddy Quill`, and a grades export
says only `#1234567890`. One person. A string-to-string table makes
them three pseudonyms, and every cross-file join -- which is most of
what goes wrong -- stops being reproducible in the twins. So a row is
resolved to a *person* on the id order `roster.py` already uses, and
the fake person is then rendered into whatever shape the cell wanted.

Matching is **exact**, unlike `classlist.merge`, which pairs a surname
with an initial because a human typed one spelling and meant the other.
A wrong guess here merges two real students into one pseudonym and the
twin then silently disagrees with the file it came from. A row matching
two different people is **refused**, because that means two files
disagree about who somebody is and quietly picking a winner would bake
it in where it could never be seen.

**It must preserve shape, because the shape is where the bugs are.** A
two-word surname masks to a two-word surname; a 9-digit id to 9 digits;
a `#`-prefixed 10-digit id keeps the `#`; a student on two email
domains keeps two *different* fake domains. One open bug in the Roster
list is a student whose surname is two words and whose splitter returns
one. Masking that to one word would delete the bug from the twin, and
the twin would then prove it fixed.

**It must fail closed.** A column that is recognised is masked; a
column positively shown to be harmless is kept; **anything else is
blanked** -- header and column kept, cells emptied. Blanking rather
than dropping keeps the file's shape, which is what makes a twin usable
for working out a round-trip. `--keep` promotes a column once a human
has looked at it, and there is no option that promotes one silently.

How a column is shown harmless, in order, and the order is the point:
a known label; anything holding an `@`; **anything holding a run of
five or more digits**, which is blanked as a possible id; all values
numeric, which is a points column; at most twelve distinct values none
longer than 24 characters, which is a grade vocabulary. Low cardinality
is the test that separates a category from prose. The digit rule runs
*before* the numeric rule, which is the whole reason a 9-digit student
number in an unlabelled column does not sail through as "just a
number".

**It must check its own output.** After writing, the twin is read back
and searched for every real string the vault knows; if one survives the
twin is **deleted**. A masker believed to be correct is not the
standard. This earned its place immediately: a column headed `Advisor`
holding surnames is few enough and short enough to read as a category
by the cardinality rule, the classifier keeps it, and only the scan
catches it. That is a test in the suite.

The failure message carries counts and column numbers, never the values
-- the point of the exercise is that they do not travel, and a terminal
is somewhere they would.

### Decided: where the vault lives, and why it is a sibling

`~/CheckItPrintIt/vaults/<course>.json`, beside `courses/` and never
inside it. Structural, not a rule: masking a whole course folder --
`roster.toml` and `record.db`, when that is built -- physically cannot
walk into the vault. A rule saying "skip the vault" is one more rule to
get wrong.

Named after the **course**, not the file, so every file from one course
shares one set of pseudonyms. Two vaults would give one student two
fake identities, which is the failure the whole module is shaped
around.

### Decided: no recovery key

The vault is the only way back. The alternative is a key that
reconstructs the mapping, and that key is a secret somebody would have
to be trusted with -- which is the thing being avoided. So: back it up,
and the CLI says so on every mask.

### Two deliberate holes

* **A one-letter value does not unmask.** A middle initial is masked to
  `X`, always. There are twenty-six letters and more students than
  that, so a per-person mapping cannot be injective, and substituting a
  lone letter in text would rewrite every standalone `T` in a sentence.
  The first version did map them per person and restored `R` where the
  file said `T`. A hole that is written down beats a reversal that is
  sometimes wrong. What survives is the *presence* and shape of an
  initial, which is what the name-splitting bugs need.
* **A blanked column cannot be restored.** It never left the machine.

Everything else round-trips exactly. Measured on three invented
exports: the LMS class list came back **identical**, 24 rows by 6
columns; the registrar's list differed only in its 17 middle initials;
the 55-column grades export differed only in the 5 cells of its
blanked `Instructor comment` column -- which, in the sample, held a
student's first name, and was blanked by the cardinality rule with no
help from any label.

### How the gradebook work now goes

1. He runs `vault columns` on his real export and reads the table.
2. He runs `vault mask` and sends the twin.
3. The round-trip is built against the twin.
4. He runs it on the real file. Nothing of his ever moved.

### Built, 2026-11-08: a whole course folder

`vault mask-course`, plus `vault learn` and `vault mask-text`. The
strategy **inverts** from the file masker, and for a good reason:
`mask.py` has to work out which columns of an unfamiliar file are a
person, whereas a course folder contains `roster.toml`, which is an
authoritative structured list of everybody in it.

So: learn the people properly from the roster through `roster.load`;
substitute those known values through every other file; then check
everything written, twice. A seating chart, a room, an availability
list and the record database all name the same people, and none of them
has to be understood in order to be masked.

**The record database is masked schema-agnostically** -- every text
column of every table goes through the same substitution, rather than a
list naming `printed.name`, `printed.sid`, `attempt.sid` and
`scan_page.sid`. A column holding a slug matches nothing; a column
added next term is covered without anybody remembering. The named list
is the thing that goes stale silently.

**`secrets/` and `scans/` are never copied, and it is not an option.**
Credentials cannot be masked. Scans are images of handwriting with
names written on them, and no text substitution touches an image.

**The second check is the point.** Substitution can only replace what
the roster taught, so every written file is sniffed for anything that
still looks personal: an address whose domain is not one of the vault's
fakes (a hard failure), and a run of nine or more digits that is not a
known pseudonym (a failure `--allow-digits` overrides, since a seed or
a hash can look like that and only he can tell). On any failure **the
whole output directory is removed** -- a half-masked course folder is
worse than none, because it looks like a twin.

Measured against an invented 45-student course at the real one's scale,
two sections and two print runs: 45 students learned, 650
substitutions across five files, `secrets/` and `scans/` absent, and
`roster.toml`, `seating.toml` and `room.json` each unmasking **byte for
byte** back to the original. Checked a second time by a script that
reads the original roster with `tomllib` and searches the twin for all
276 of its distinct strings, so the verification does not go through
the vault whose correctness is in question.

### What his real export turned out to hold (2026-11-08)

He ran `vault columns` on the live MAT 106 gradebook. 60 columns, and
the structure is worth writing down because the profile has to be
written against it.

**Only one column identifies a student**: `OrgDefinedId`. No name
column, no email column, no username -- which confirms what 14.6
recorded from the 10-22 export and means masking this file changes
exactly one column out of sixty. It also means the twin cannot be tied
to a student by itself; the class list has to be masked into the same
vault for the ids to join up.

**The skills, as the gradebook names them:**

* **22 core**: `R1`, `R2`, `W1`-`W7`, `N1`-`N4`, `F1`-`F5`, `D1`-`D4`
* **7 explanation**, with an `-E` suffix: `W1-E`, `W4-E`, `N1-E`,
  `F2-E`, `F3-E`, `F5-E`, `D1-E`
* **8 videos**, `V1`-`V8`, which are not printit's business
* **`Fundamentals Checkpoint`** and **`My Base Project`**, spelled out
  with no slug, which are the two that will need pairing by hand

So the skill code is the **first whitespace-separated word** of the
header, and everything after it is `Grade Symbol <Selectbox
MaxPoints:1 Category:...>`. That is what the profile's column rule can
key on.

**`F5-E` is in the gradebook**, which is the other half of the item
already on the list: the slug is in mat-106's `<associates>` and not
published as a real `<outcome>`, so the bank generates nothing for it
while Brightspace has a column waiting.

### Two things the real file broke that the invented ones did not

**A points column was blanked.** Brightspace writes points to five
decimal places, so `Participation Attendance and Homework` holds
`10.00000`. The rule that treats a run of five or more digits as
possibly a student id fired on the five zeros *after the decimal
point*, and emptied an ordinary grade column. The test now looks only
at the part before the point, because a student id is a whole number.
Every invented fixture had used `1`, `0.5` and `2.25`, none of which
has a long run anywhere.

**The report was unreadable at his terminal width.** The header column
was a fixed 46 characters and his column names run to seventy, so every
row wrapped and the console redrew the halves on top of each other --
whole rows repeating down the screen. He could not tell the report from
the corruption, and said so. It now measures the terminal and sizes the
header field to fit.

### Built: the gradebook profile and `gradebook map` (2026-11-09)

The five facts, as a readable file per course, and a command that works
out as many of them as it can from the file in front of it.

**What is in it, and what is deliberately not.** Which column holds the
student and which roster field it joins to; the two mark strings;
whether a blank cell counts; the slugs that needed pairing by hand; the
rows and columns never to write to. **Not** the file's byte-order-mark
or line endings -- those are read off whatever file is handed over on
the day, by `mask.sniff`, because storing them would give them a chance
to go stale.

**The profile carries no student data**, which is a property worth
naming because it is what makes the whole arrangement work: the profile
derived from a masked twin is identical to the one derived from the
real export, so the mapping can be worked out by somebody who may not
see the file. There is a test asserting it against a vault, checking
for pseudonyms as well as real values.

**Matching needed almost no configuration.** The rule that works is
"the skill's code is the first word of the header", which places 28 of
the 29 published slugs on the real export. Two looser rules follow for
anything it misses, and all three refuse to resolve an ambiguity:
a slug matching more than one free column is reported and left. `FCP`
is the only hand pairing, and only hand pairings are saved -- the rest
is re-matched every run so a renamed column is noticed.

The `W1` against `W1-E` collision is handled by a hyphen guard in the
looser rules' patterns rather than by the pass ordering, and there is a
test with headers like `Skill W1 ...` that actually reaches those
rules. The first version of that test did not, because the exact rule
placed everything on the real file and the fallbacks never ran.

**The mark strings are read from the file.** `guess_marks` takes the
distinct values in the matched columns, refuses if there are more than
six of them, and picks the pass by looking for `pass` in it. If that
does not settle it, both come back and the instructor is asked. On the
real export it found `U+1F3C6 Pass` and `U+1F4AD Not Yet` -- with no
space after either emoji, which an invented fixture had got wrong.

**Whether a blank counts is proved, not configured.** `blank_evidence`
groups the matched columns by the `Category:` the exporter writes into
the header, then looks for a numeric column equal to the number of
*filled* cells in a group across every row. On the real export that is
column 36, the Core Skills denominator, and it holds for all 20 rows. A
column equal to the *passes* is rejected: that is a numerator. With no
evidence the cautious answer stands, because filling a blank is the
destructive direction.

**The retired enrolment is found by grouping ids that differ only by a
trailing marker**, and reported rather than acted on -- and only the
*marker* is suggested as an ignore rule, never the id, so nothing
student-shaped reaches the profile.

### Built: `gradebook export` (2026-11-09)

Not "generate a CSV": take the file the instructor exported, fill in
the cells there is a recorded result for, change nothing else, hand it
back -- same columns, same rows, same untouched values, and the same
line endings and byte-order-mark, which is what `mask.sniff` was built
for.

**The three rules**, and the third is the one that matters: ever passed
takes the profile's pass value; attempted and not passed takes its
non-pass value; **never attempted, or only ever absent, is left exactly
as found**. An absence is not an attempt at the skill, and where the
subtotals count filled cells, writing a non-pass into that blank raises
the student's denominator for a paper they never sat. A query counts as
an attempt that did not pass, which is his own rule.

**Two guards.** Nothing is written without `-o`, so the dry run is the
default. And a cell that already says passed is **not** replaced unless
`--allow-downgrades` is given: a pass in the gradebook may have come
from outside printit, and destroying it is the one irreversible thing
this does. Those cells are counted apart and listed individually.

**Ambiguity is refused, never resolved.** A row whose id matches two
roster entries, or a second row for a student already matched on an
earlier row, stops the export rather than picking one. The second is
exactly the `-DoNotUse` case with its ignore rule missing.

Measured against the masked twin of the real export, with an invented
roster built around its pseudonyms and 57 invented decisions: 19 of 20
rows matched, 1 skipped by the ignore rule, 16 cells to fill, 19
already right, 508 left alone for want of a result, and 8 downgrades
held back. The written file was then compared cell by cell against the
input: **16 cells changed, in the 6 columns the report named, and
nothing else** across 21 rows and 60 columns.

### Decided, 2026-11-09: no new command for the LMS ids

Checked before building one. `roster import` already reads
`OrgDefinedId` as `alt_id`, and `classlist.merge` already matches an
incoming row on any identifier a student answers to, including an
email address -- which all 45 MAT 106 students have and none of whose
`alt_id` is set. So the prerequisite is a `roster import` away.

**With `--covers`.** A Brightspace class list carries no section
column, and a file naming no section is taken to cover everybody, so
importing one section's list marks the other section dropped and their
papers stop printing. The option exists; it has to be passed, because
the file cannot say. `test_lms_ids.py` pins both the protection and the
danger.

### What the real export settled (2026-11-09)

Run against the masked twin of the live MAT 106 gradebook, 60 columns
and 20 rows:

* **29 of 29 skills matched** once `FCP` was paired with column 9.
* **30 columns belong to nothing in the bank** and are listed as never
  to write to -- the formula totals, the final and midterm grades, the
  eight videos, PAHW, Tokens, the subtotal pairs, `My Base Project`,
  the grading-scheme reminder, the end-of-line indicator, and `F5-E`,
  whose column exists while the bank does not publish the skill.
* **A blank is not counted**, shown by the denominator column in all 20
  rows.
* **One retired enrolment**, `-DoNotUse`, sharing its base id with a
  live row -- and it holds six real marks and its own subtotals, so it
  is a record with history and not an empty husk.

### Rewritten against his own script (2026-11-09)

He mentioned, in passing, that there are two sections and so two
files. Looking at the folder to see what shape they were in turned up
`apply_to_brightspace.py` -- **his own Brightspace writer, in
production since October** -- and its `README.txt`.

The export had been built without knowing it existed, and it disagreed
with it in five places, every one in the direction of writing more than
he wanted:

1. **A non-pass was written for any attempted-and-not-passed skill.**
   His rule: only for skills named on the command line, and only into
   an empty cell. Writing one raises the denominator, so it is a
   deliberate act for the skills in play.
2. **Replacing a pass was a flag.** His rule, confirmed in his own
   words: never. So the flag is gone -- a default can be overridden and
   a rule that takes no argument cannot -- and a test asserts the flag
   does not exist.
3. **A cell holding something unrecognised was overwritten.** His rule:
   stop. Overwriting a value the tool does not understand is guessing.
4. **A student on two rows was refused.** His rule: the row with more
   grades wins, and only a tie is refused.
5. **One file at a time.** A course exports one per section, and the
   check that a student appears in exactly one of them cannot be made
   by a tool holding one file.

And one thing his script does that is simply better: **untouched lines
are copied byte for byte.** It splices the changed lines rather than
re-serialising, because a CSV writer normalises quoting -- so a cell
the LMS quoted unnecessarily would come back bare and the uploaded file
would no longer be the downloaded one. `splice` now does the same, and
refuses a line with a quote character rather than splitting it on
commas.

Two further checks adopted from it: a cell that has changed since the
plan was made stops the export, and a student in the file for the wrong
section is noted (the section being guessed from a three-digit group in
the file name, so a wrong guess is a false note and never a wrong
write).

**What his script does that this still does not** is build a second,
independent plan and compare the two. `verify_export` and the re-read
of the written file are the cheaper half of the same idea -- they catch
a write that strayed from a correct plan, not a plan that was wrong.
Worth doing if this is ever trusted unattended.

### The first run on the real files (2026-11-09)

He gave the two paths rather than keep copying output back, having
checked that the commands would not open the files. He was nearly
right: `gradebook map` prints only structure, but the export's report
had two lines that identified a student by id. Those were fixed first,
and the fix was watched failing, before anything was run.

**Both files, 62 columns each, identical headers.** `OSW_ID` is column
61, `Fundamentals Checkpoint` column 10, and there is **no `Last Name`
column** -- which his own script requires, so these were exported with
different options than it expects.

**The result is the quiet one: nothing to do.** 43 students, 86 graded
(student, skill) pairs, and with every skill named for non-passes --
the most it could possibly write -- **0 cells to write, 61 already
right**. Brightspace is already current with everything printit has
recorded.

Two things the run surfaced that are worth keeping:

* **One real disagreement**: the 830 file, row 12, skill `N3`.
  Brightspace says passed, the record does not. Not written, per his
  rule, and reported so he can look at it.
* **The `-DoNotUse` row was skipped** -- but only after a bug was
  fixed. See below.

### Two bugs only the real files could find (2026-11-09)

**The ignore marker is on the wrong column.** Brightspace appends
`-DoNotUse` to `OrgDefinedId`; he matches on `OSW_ID`. The rule was
checked against the student column alone, so the moment the match moved
to the other id it **silently stopped firing**. Both rows then looked
clean, became a duplicate pair, and were separated by their grade
counts -- which picks the live row here only because the retired one
holds fewer marks. `ignored_by` now scans every cell and says which
column it matched in.

**The section inference read the course code.** `(?<!\d)(\d{3})(?!\d)`
takes `106` out of `MAT106-820`, so all 42 rows looked misfiled: 42
near-identical notes, burying everything else. Now `[-_](\d{3})(?!\d)`,
the general form of the `MAT\d+-(\d{3})` his script anchors on, and the
note is one line per file.

Neither could have been found on the masked twin: the first needs the
marker and the matched id to be in different columns, which only
happened once he said to match on `OSW_ID`, and the second needs a real
file name.

### Decided, 2026-11-09: match on the student id, not an email

His reason, and it is specific rather than general: **an email that
reaches Brightspace from another institution is often stale**, so the
address in the LMS can disagree with the roster's for a student who is
perfectly well enrolled. Matching on the address reports them as
missing while their paper is on the desk.

So `OSW_ID` -- Oswego's own 9-digit id, which he has included in the
export -- is the column, and `osw_id` is now in
`classlist.SYNONYMS["sid"]` beside the vendor-specific `banner id`.
Without it the column was unrecognised, which meant the masker blanked
it and the importer ignored it: safe but useless.

**This closes 1a entirely.** The export matches the gradebook to a
student on the student id, which every one of the 45 MAT 106 students
already has, so no LMS id has to be imported at all.

### Decided, 2026-11-08: three answers, and the order

The general gradebook system is the other half of the request: *"The
grades import/export needs to work for a variety of LMSs, not just
mine."* Three questions were put to him, and all three are answered.

**Import means marks as well, one way.** Not only the LMS-id import of
§14.9. A gradebook can be read to seed printit's record -- for a skill
passed outside printit, or for a term that began before printit did --
and it stays one-way. Nothing reconciles in both directions, because
two systems that both claim authority over a mark need a rule for which
wins, and he did not ask for that rule. **What still needs deciding is
what a mark with no scanned paper behind it looks like in Progress**,
since every mark there currently traces to a printed page and a run.

**Masking extends to a whole course folder, and that is next.**
`roster.toml` and `record.db`, not only the files handed over -- which
is what makes the live 106 state safe to debug rather than just the
CSVs chosen for a question. The vault core already supports it; it
needs a TOML adapter and a SQLite one. Taken before the gradebook,
which is his sequencing, not a technical constraint.

**The column-to-skill pairing is a CLI command first.** A `gradebook
map`, shaped like `form map`: ids not positions, nothing guessed, the
answer written to the profile. The GUI reads that profile afterwards.
Fastest to build and to test against fifty columns, and it keeps the
profile as the single truth rather than something a screen holds.

### What §19 therefore has to settle

* The **profile**: the five facts that are Brightspace-specific in
  §14.6 -- the id column, the skill-column pattern, the two mark
  strings, whether blank means "not attempted", and which rows and
  columns are untouchable -- written as data per course.
* **What a seeded mark looks like** where Progress expects a paper.

## 20. No real student in a commit (2026-11-17)

On 2026-11-17 a check of what was about to be pushed found real students
in all three public repos -- names, a student id, an address -- written
into docstrings, comments, test fixtures and the notes as worked
examples, over two months. The house rules said "never commit them";
nothing enforced it (principle 3). The history was rewritten that day;
this section is what stops it happening again.

### The rule

A commit or push that **adds** a real student's name word, id or address
to any of the three repos is refused, before it lands. "Real" means: in
any roster, seating chart or vault under `~/CheckItPrintIt` that does not
belong to an invented course.

### Where it runs

* **git hooks**, `pre-commit` (the staged lines) and `pre-push` (every
  commit being pushed, so a value added and then removed inside the push
  is still caught). git runs them whoever commits -- the instructor, an
  agent, a script. They live in `checkit-printit/githooks/`, and each
  repo points at them with `core.hooksPath` (local config, not
  committed). mat-206 is frozen and is not touched.
* **The agent's shell hook** refuses `--no-verify` and any change to
  `core.hooksPath`, which are the two ways past a git hook.
* `checkit-printit names check --all` reads the whole history, and
  `--tree` the current files, for an audit.

### What counts, and what does not

Matching is on whole words, a set lookup per word -- never a substring,
so a four-letter name inside a longer word is not a hit.

* **Ids and addresses always count.** Nothing makes them fine.
* **A name word counts** when it is 3+ letters, written as the roster
  writes it or in capitals. Lower case is ordinary English.
* **The allowlist** is `~/CheckItPrintIt/name-guard.toml`, next to the
  data and never committed, since its entries are real roster words:
  * `invented_courses` -- courses whose rosters are made up (`Demo`).
    Every other course counts, so a new real course is guarded the day
    it appears; forgetting to list a *real* one cannot happen.
  * `fine_words` -- words a student happens to share that are fine
    anywhere: a month, an algorithm's name, a common nickname. Which
    words they are is itself about real students, which is one more
    reason the file stays out of every repo.
  * `names_fine_in` -- files where a name word is fine because the file
    is a list of common names (the word problems' name list and the
    exercises drawn from it). Ids and addresses still count there.

### What a refusal says

The file, line and column, the kind (name, id, address), and the value
as its vault pseudonym, or `####` when the vault has none -- never the
value. The person at the keyboard opens the line to see it. The output
is read by agents, whose transcripts leave the machine.

### Fails closed

No roster found, a roster or vault that cannot be read, or a guard that
cannot start (the hook's Python missing) all refuse the commit. A guard
that quietly passes because it had nothing to check against is the
failure this section exists to prevent.

### Not covered

Images and PDFs are not read. Real data can only enter them through a
scan or a printed paper, and none is tracked; if one ever is, this
section needs a rule for binary files.
