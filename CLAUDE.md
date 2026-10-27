# Working in checkit-printit

Turns a CheckIt bank plus a roster into a printable class set, and manages the
course state around it. The platform is a sibling repo and **the fuller guide
lives there**: `../checkit/CLAUDE.md`. Read that too.

```bash
./.venv/Scripts/python.exe tools/check.py        # everything, one exit code
./.venv/Scripts/python.exe tools/docs.py         # do the docs still match?
./.venv/Scripts/python.exe -m pytest -q
./.venv/Scripts/python.exe -m checkit_printit --help
```

This venv has **both** packages installed editable: `checkit-printit` and
`checkit-dashboard` (pointing at `../checkit/dashboard`). It is therefore also
where checkit's own tests run. mat-106's venv has only checkit.

---

## READ THIS FIRST: how work goes wrong here

Every one of these has happened, most more than once. None are hypothetical.

### Write patch scripts with the Write tool. Never a heredoc.

A bash heredoc mangles backslashes, so `\n` inside a Python string arrives as
a real newline and a find-and-replace silently matches nothing. This cost time
**five separate times in one session**. `sed` is worse: it treats `\u` as an
escape, which breaks every `\usepackage`.

Always `Write` the script to the scratchpad, then run it. And put
`assert old in text` in it, so a missed match writes nothing rather than
writing the wrong thing.

### Replace by anchor, never by index

Slicing `app.js` between two `str.index` positions removed a function that
had been added between them an hour earlier, and the tab loaded with an empty
preview. The patch script was correct about both ends and wrong about what
lay in the middle.

An anchored `text.replace(old, new)` with `assert text.count(old) == 1`
cannot do this. Index slicing has no way to notice.

### Backticks in a `-m` commit message are command substitution

A commit message in double quotes is still shell text, so a word
wrapped in backticks is run as a command and replaced by its output
-- which is usually nothing. It has already silently deleted a word
from a pushed commit here.
Single-quote the message, or leave backticks out of it. Same family as
the heredoc eating backslashes and `sed` eating `\u`: **anything handed
to the shell is shell text first and prose second.**

### `command | tail` reports tail's exit code, not the command's

A failed build reads as success. Redirect to a file, check `$?` on its own
line, then read the file.

### A test that passes proves nothing until you have watched it fail

Write it, then **break the code on purpose and check the test notices.** In one
session that found, first pass every time:

- a fixture that put an unquoted name in a comment, so the guard under test
  was never reached
- an ordering test that passed by luck, because `GROUP BY` happened to sort
  the same way as the dates
- dead code: two mechanisms guarding one rule, so removing either left it green
- **nothing at all covering the thing most recently fixed** -- three times

That last is the pattern worth internalising. The test for the bug just fixed
is the likeliest to be vacuous, because it gets written while thinking about
the fix rather than about what could still be wrong.

### Run it on real data before believing it

Three bugs this session lived in code whose tests all passed and only surfaced
against the instructor's actual files: two different ID systems in class
lists, an email that differs between two same-day exports, and a preferred
name that imports as a duplicate student. Real files are in `~/Downloads` and
`~/CheckItPrintIt`.

### Verify the artifact you shipped, not the dry run

`build --preview` and `build` draw independently unless both are given the
same `--seed`. Checking the preview's seeds proves nothing about the build's.

### Operate the control; do not call what you think it calls

A reported "open the folder does nothing" was fixed and then "verified" by
POSTing to `/api/print/reveal` with a hand-picked path. It returned 200.
It also opened the wrong folder, because the button sends the run just
built and the test sent a job folder from a fortnight earlier -- and a job
folder holds one file, so it looked like the build had produced nothing.

Calling the endpoint tests the endpoint. It cannot catch a button wired to
the wrong field, which is the bug being reported. Click the thing.

### A run writes two folders, and one of them is nearly empty

| | holds |
|---|---|
| `~/CheckItPrintIt/jobs/<title> <date>/` | the **job**: `publication.toml` |
| `~/CheckItPrintIt/<course>/<title> <date>/` | the **run**: `main.pdf`, `main.tex`, `manifest.toml`, `compile.log`, a folder per skill |

### Three records, and which question each answers

A run writes three, and they are not substitutes for one another:

| | answers | written by |
|---|---|---|
| `manifest.toml` | which `(skill, version, seed)` were **drawn**, so a run can be replayed | Python, before the compile |
| the `printed` table | which **student** got which paper, so Progress can count | Python, after the folder is written |
| `main.pages` | which **page** each paper landed on, so a scan can be split | **TeX**, as it ships the pages |

The third has to be TeX's, because a skill can run to two sheets and
page numbers do not exist until the pages are broken.

### What is printed on a page, and what reads it back

**The footer code** is a QR carrying `C1-<runid>-<page>`, 9mm at
error-correction level M. That is the whole payload: run plus page is
a unique key, and everything else is a lookup in that run's
`main.pages`.

`<runid>` is the **run number**, not the draw seed, and the difference
matters. `choose_run_seed` carries a replayed run's seed on purpose,
and a replay writes to a new folder, so a reprint produces two runs
sharing one seed -- with different page-to-student mappings, because a
replay exists to fix something. Resolving a code by seed would hand
papers to the wrong students. `record.next_run_no` allocates the
number, `record.run_by_no` resolves it, and `meta.last_run_no` is the
high-water mark so a deleted run's number is never issued again.

**Sizing is one decision, not three.** A version-1 symbol is 21
modules and holds 14 bytes at level M. `C1-999-9999` is 11. Grow the
payload past 14 and the encoder moves to version 2 silently, the
modules shrink, and 9mm stops being readable --
`test_the_symbol_is_still_one_version_1` measures the module count off
a render to hold that line. 9mm itself was measured: on real pages at
200dpi, blurred, skewed and JPEGed, 9mm reads 150/150 on a photocopy
of a photocopy and 8mm reads 134/150.

**`main.pages`** has three kinds of line:

```
run*7                                       the run number
17*student*800000111*W5*803*1               page, kind, sid, skill, version, sheet
mark*17*box*34926110*1819429*1769472*...    label, then x y w h d in scaled points
```

* The page line is written **from the footer**, which is why padding
  pages need no detecting: `\preparefornextstudent` pads under
  `\pagestyle{empty}`, which has no footer, so a blank writes nothing
  and the gaps in the sequence *are* the blanks.
* `kind` is `student`, `spare` or `key`, from `\setkind`. Nothing on
  the page distinguishes them and they grade differently.
* `mark` records where something sits, from `\pdfsavepos`, for
  cropping out of a scan. Three labels: `box`, `id`, `name`. The slug
  and version are deliberately not recorded -- both are already known
  once the code is read, and if the code cannot be read there is no
  page number to look anything up by.

### The macros `main.tex` emits, and what they switch on

| macro | what it does |
|---|---|
| `\setrunid{N}` | **the gate.** Opens `main.pages`, and switches on the index, the marks and the footer code. Emitted only when the run has a record to key into |
| `\setkind{...}` | `student`, `spare` or `key` for the block that follows |
| `\setsid{...}` | the student id; empty draws the writing grid |
| `\setname` / `\setsect` / `\setvseed` | as before |

**A document that never calls `\setrunid` pays for none of it**: no
file is opened, no line is written per page, `\cipmark` measures
nothing, and no code is drawn. That is the hand-written case, and it
compiles about 11% faster than before any of this existed. A printit
run costs about 6.8% more than it did, roughly 10ms a page.

`main.tex` also carries `\providecommand{\setkind}[1]{}` so a bank
running an older `printit.sty` still compiles -- it then produces no
index, and Scans says so when asked to read the run.

### Turning the marks off

| | id field | footer code |
|---|---|---|
| hand-written document | **on** | **off** -- no run to key into |
| `\usepackage[noid]{printit}` | off | |
| `\usepackage[nocode]{printit}` | | off |
| `\cipidfalse` / `\cipcodeonfalse` in a preamble | off | off |
| `build --no-ids` / `--no-codes` | off | off |
| `[print] ids = false` / `codes = false` | off | off |
| `build --no-record` | | off -- nothing to look a code up in |

Absence means **on** everywhere, so `main_tex` writes a switch only to
turn one *off* and an older theme still compiles a newer document.

A run with `names = false` **and** `ids = false` prints papers with
nothing on them that says who sat them. That is warned about, not
refused: an anonymous practice set is a reasonable thing to want.

### A build against a real job writes to the real record

Any publication naming a course records the run. Four junk rows went
into the instructor's live record this way, from test builds into temp
folders. `build --no-record` is the way to avoid it, and a test that
builds should set `CHECKIT_PRINTIT_HOME` to somewhere of its own.

"Open the folder" means the second. Opening the first looks like a failed
build.

### Do not declare something impossible without checking

"A CLI cannot sign in to Google" was said twice, was wrong both times, and
pushed the design somewhere worse. The browser loopback flow works; what was
missing was an OAuth *client*, a different problem with a different answer.

### After editing gui/, restart the server before believing the page

Twice in one sitting a change was on disk and something was still running the
old copy. The browser had cached `app.js` (fixed: the server sends
`Cache-Control: no-store`), and then the running `checkit-printit gui` had
loaded `gui/__init__.py` from before the edit -- Python does not reload a
module in a live process. Sorting by surname went on producing given-name
order, which read as a bug in the sort.

The front end falls back rather than erroring when a key is missing, which is
right, and is exactly what makes a stale server hard to see.

### "Failed to fetch" means the handler died, not that the server is down

`_api` used to catch `GuiError`, `RosterError` and `OSError` and let
everything else escape, and an escaped exception closes the connection
without a response. A missing `import sys` therefore reached the browser as
`net::ERR_EMPTY_RESPONSE` -- indistinguishable from the server being down,
the token being wrong, or a typo in the URL, so the first hour goes on
three things that were never broken.

It now catches everything, prints the traceback to the terminal, and
returns a 500 naming the exception. **An error path that produces no output
is worse than one that produces a wrong message**, because a wrong message
is at least a lead.

### A fixture small enough to be convenient hides what you are measuring

The roster column widths were tuned against the two-row scratch course, whose
longest name is "Test Student", and clipped most of every real row. Use
`Scratch 48` -- forty-eight synthetic students shaped like the real roster,
same section split, same name lengths, same chart shape -- for anything whose
size or layout matters.

**It is a fixture, so it has to come back unchanged.** Seating is developed
against it through the real endpoints, which means a session of canvas work
writes to it for real. Copy the course directory aside before anything that
saves, restore it after, and check these:

```bash
cd "$HOME/CheckItPrintIt/courses/Scratch 48" && sha256sum room.json seating.toml
```

    d13caeafa670828def0a20cbefcf00ba8284ae829215354304952ac1ff28ac6e *room.json
    1bae8e12b93cca22c64ee73473ec016f95ce81bd8eba1b5c19fbc3963b23e748 *seating.toml

Unchanged as of 2026-10-11. If a deliberate change to the fixture is ever
right, change these numbers in the same commit -- a pin nobody updates is a
pin everybody learns to ignore.

### A fix applied to one path is not applied to the others

Three times in one day. The `workspace`->`course` rename replaced `"-w"` in
option definitions but not ` -w ` in message strings, nor `` `-w` `` in the
CLI table. `form attach` carries its own copy of deploy/ping/echo, so a fix
to `_deploy_and_record` left it unchanged while appearing to work. And
`form connect`, the hand-deployment path, missed every improvement the clasp
path got.

**When a change to shared behaviour does not show up, ask "is there a second
copy", not "did it deploy".** Both times that question was asked late, the
deployment was fine.

### A fake built from your own vocabulary cannot fail like the boundary

`what_the_clone_would_replace` scanned for `.gs`, `.json` and `.html`, and
clasp clones Apps Script files as **`.js`** -- so the one guard against
destroying an instructor's script was blind to every real clone. Its test
had a fake clone writing `Code.gs`: printit's spelling, not clasp's.

`.gs` and `.js` are **one file** to Apps Script. Two of them in a push
directory is what `clasp push` means by "Conflicting files found", and
re-staging cannot fix it because an overwrite cannot reach a name it does
not share. `provision.OURS` holds what printit stages, by the name Apps
Script files it under rather than by filename.

**When stubbing something at a boundary, spell the fixture the way the far
side spells it.**

A fourth, 2026-10-11: the wheel's zoom anchoring was written *inside*
`zoomTo`, so the pinch never had it and went on holding the middle of the
window still. It is now `holdPoint`, a function with a name that both call.
**Behaviour two gestures share wants a name, or only the gesture it was
written for will have it.** It was found by writing a sentence about the
feature in the docs and going to check whether the sentence was true --
which no test did, because the tests passed, and no use did, because nobody
pinches a desktop browser.

### A hand-built run is not the run he set up

When something breaks he will ask you to skip the UI and do it yourself.
Do that, but **start from `courses/<name>/job.toml`, not from what he
said in chat.** It is the live draft: selection modes, variants,
overrides, version letters, all of it, carried between visits.

The 2026-10-12 Extravaganza was built by hand from a publication
transcribed out of the conversation. The draft already said
`W5 = "multiplication"` and `W7 = "terminating"`; the transcription did
not, and ten students got a W5 with no multiplication on it. Nothing
failed. `manifest.toml` recorded `variant = "no_multiplication"` for
every one and was not read.

`printjob.publication_text(space, draft, ...)` is the function that turns
the draft into a publication, and `write_job` puts it in a job folder.
Use them. Hand-writing the TOML means hand-copying state you did not
know was there.

### An unchosen variant is now refused, and nine skills have them

`check_variants_chosen` stops a build that would print a **dealt** paper
from a variant-bearing skill with nothing in `[variants]`. Without it,
`seeds_with_variant(slug, None)` returns the whole printable tier and
the letters split evenly across variants -- half the class at the wrong
level, silently.

R1, R2, W4, W4-E, W5, W7, N3, N4 and D2 declare variants in mat-106, so
most runs now need a `[variants]` line. It is scoped so that only papers
that actually print and were actually drawn are asked about: a replay
pins every seed and passes, and a skill nobody takes is never mentioned.

`Bank.variant_labels(slug)` is the single answer to "does this skill have
variants". There were four copies of that scan; three are gone, and the
GUI keeps a 60-seed slice on purpose, documented where it lives.

### A class name in `style.css` is a claim about `seating.css` too

The two stylesheets share one document. This has shipped twice:

* **`.rail`** (stage 2). Seating has had one since its own stage A --
  the mode rail inside `.bottomstack`. `height: 100vh` landed on both,
  so `freeBand` measured 80px and the room fitted at 20%.
* **`.band`** (stage 3c). Seating's selection marquee, carrying
  `position: absolute`, which on a `<tr>` computes to `display: block`
  and drops the row out of the table -- 58px wide, no height, on top of
  the first student.

Nothing failed either time, and **the second was committed one stage
after this very section was written.** Writing it down did not work, so
`tests/test_gui_markup.py` now fails on any class defined *bare* in
both files. Bare, not shared: `.skill.on` and `.banner.waiting` share
their second word with Seating harmlessly, because a compound selector
cannot reach an element that lacks the other class.

The names are `.navrail` and `.secband`. Run the markup tests after
touching either stylesheet, and still open Seats afterwards -- the test
catches the name, not every way a rule can reach too far.

### Never hide a table column by `nth-child`

The Override column was hidden in `same` mode with
`#who.hide-override th:nth-child(5)`. On 2026-10-26 the tick column
added a new *first* cell, so with `same` mode and a ticked run at
once the fifth child became **Will get** and the wrong column
vanished -- in the one combination the tick column exists for.

The comment above that rule already warned about this: "a rule that
hid cells and left the heading once made every column after it read
one place to the left." The hazard was written down and the fix
written for it was still positional, so a new column in front
re-armed it.

Give the heading and the cells a shared class and hide that. There
is no `nth-child` anywhere in `style.css` now; keep it that way.
Neither the tests nor the screenshots caught this -- every
screenshot was in `chose` mode, where the column is not hidden at
all. When a column appears or disappears, look at the table in every
combination of the switches that govern it.

### A change with reasoning gets a dated section in the notes

`../checkit/CODEBASE_NOTES.md`, a `##` heading with today's date. The commit
message is not the record -- write what was actually wrong, how it was found,
what was ruled out, and what was verified rather than assumed.

Writing to this file does not count. Twenty-six commits went unrecorded
because the notes felt superseded by these guides; they are not, and the
design doc is a third thing again. `CLAUDE.md` is the map, the design doc is
the plan, the notes are the history.

### Student names never reach chat or a commit

They live in `~/CheckItPrintIt`, `mat-106-checkit/TeX Outputs/` and
`../FundCheck`. Mask them in anything printed. One `cat seating.toml` put 48
of them in a transcript.

Fixtures under `tests/` are synthetic on purpose -- shaped exactly like the
real exports, with no real person in them. Keep it that way.

---

## The CLI

`build`, `init` and `install` are the original tool. The rest manages state
that outlives one print job.

| | |
|---|---|
| `init [dir] -b BANK` | scaffold one print job |
| `install -b BANK [--force]` | put the theme into a bank |
| `build` | `-p`, `-o`, `--compile/--no-compile`, `--seed N`, `--preview`, `--replay DIR` |
| `import FILE -o OUT` | the retired Control Center CSV. Superseded by `roster import`; dead weight |
| `course init NAME` | `-b BANK`, `--adopt JOBDIR` |
| `roster import FILE` | `-o`, `--section`, `--covers`, `-s/--seating`, `--dry-run` |
| `roster drop WHO` / `roster restore WHO` | `-r`, `-s` |
| `skills open SLUGS…` | `-c`, `--add` |
| `skills set` | `-c`, `--name`, `--date`, `--due`, `--choose`, `--limit` |
| `skills preview` | `-c`. Changes nothing; `open` is the verb |
| `record runs` / `record student WHO` / `record skills` | `-c` |
| `form create` | `-c`, `--title`, `--folder`. New form, script, deploy, items, ids |
| `form attach --script-id ID` | `-c`. Same wiring for an existing form, changing nothing on it |
| `form map` | `-c`. Say which existing item is which |
| `form add-items` | `-c`. Create only the ones missing |
| `form push` | `-c`, `--dry-run` |
| `form pull` | `-c`, `--dry-run`, `--force`. Responses into the roster |
| `form setup` / `form connect --url` | the manual path, for when clasp is not an option |
| `gui` | `-c`, `--port`, `--open/--no-open`. The local web app (8a-8d) |

`tools/check.py` is the one to run before a commit: printit's tests, the
audit, and the platform's tests, with **one exit code and three lines of
output**. The short output is the point -- a page of pytest dots is what
makes people reach for `| tail`, and a pipeline reports tail's exit code,
which is how a suite with six failures in it got committed and pushed.
`--quick` skips the platform suite. A run that collected no tests fails
rather than passing quietly.

`tools/verify_run.py <job> <out> [--against DIR]` checks a finished run
against the job that asked for it. **A check that examined nothing fails** --
that rule is the point of the file.

`tools/audit.py` checks the tool against itself: stale flags and renamed
commands, commands named in messages or docs that do not exist, options that
are not real, duplicated call sites, dead parameters, and whether all 21
commands parse. It derives the real CLI by running `--help`, so it cannot go
stale the way a hand-written table does. **Run it after any rename or any new
command.**

## The local web app

`checkit-printit gui -c COURSE` serves one course at `127.0.0.1:8765`, never
`0.0.0.0`: it hands out names, student ids and email addresses from a laptop
on university wifi.

**It is also token-guarded**, which is not belt-and-braces. Loopback stops
another *machine*; it does not stop another *page*. Any site open in the same
browser can POST to `http://127.0.0.1:8765` in the background. Each run mints
a token, injects it into the page, and requires it as a header a cross-origin
form cannot set.

**Every handler calls the function the CLI calls.** Dropping goes through
`roster.set_dropped`, the same call `roster drop` makes -- which is why the
roster file it writes is headed "Written by checkit-printit roster drop". If a
rule needs to be reachable from the GUI, move it out of the `@click.command`
body rather than copying it. See the footgun above about one of two copies.

Built: **8a** the shell, **8b** Roster, **8c** Update form, **8d** Print job.
The other four views are listed in the nav and say what they will do and
which CLI command does it today. Order and rationale:
`../checkit/PRINT_TOOL_DESIGN.md` 12.6, and "Where things stand" below.

### How it looks, and where the rules are

**`../checkit/PRINT_TOOL_DESIGN.md` section 13 is the design document.**
It says what is settled, what is open, and which open questions are the
instructor's rather than yours. Read it before changing anything
visual. The short version:

* **Everything is a token.** `style.css` carries a `:root` of surfaces,
  spacing on a 4px grid, radii, and a type scale. **Nothing should
  carry a raw hex, a raw radius or a raw gap** -- a value that is not a
  token is a value nothing else agrees with.
* **One hue: OKLCH 260**, which is Seating's. `--surface-1`, `--line`,
  `--ink`, `--muted` and both accent values are lifted from
  `seating.css` unchanged, so chrome and canvas are the same material.
  Green is the accent and means "the thing to do here"; amber means
  "something needs your attention" and nothing else.
* **Figtree is vendored**, two subsets in `static/fonts`, not a CDN
  link: that would be a network request on every load from a tool that
  keeps names and emails off the network, and the app would look
  different in a classroom with no wifi.
* **Navigation is a left rail** (`.navrail`), collapsible to icons and
  remembered. There is no top bar and no Overview tab.
* **Rows with air, not boxes with gaps.** Cards are for a group that
  genuinely needs a boundary; a section does not get one for being a
  section.
* **Never run facts together with separators.** `45 students - 22 in
  820 - 23 in 830` is the most recognisable tic in this codebase and is
  banned; it is the writer reaching for a separator because no layout
  was designed.
* **Explanations live behind a `?`**, not in the open. A short subtitle
  is allowed; a paragraph is not.

### A section on the Print tab is a `.annot`, not a `.panel`

    <section class="annot">
      <div class="annot-head">
        <h3>Name</h3>
        <button class="hint" type="button" aria-expanded="false">?</button>
        <span class="sec-count"></span>
      </div>
      <div class="annot-body"> ...controls... </div>
    </section>

A 200px gutter holds the name, its `?` and its count; the controls sit
to the right; a hairline separates sections and there is no card. Add
`annot-full` to drop the gutter where the content wants the width --
on this tab that is the table and nothing else, and it is worth 220px
to it. Below 860px the gutter collapses on its own.

The `?` reveals the `.hint-text` in the same section, wired by **one
delegated listener** in `boot()`, so a new section needs no JS. A
section still built as a `.panel` can borrow `.sec-row` to get a
counter out of its heading without being restructured.

Roster, Print, Update form and Setup all use this now. Record is the
one left (3e). Setup's `attention` panel is deliberately still a card:
it is not a section, it is something blocking you, and a boundary is
what says so.

The rule between sections is `.annot:not([hidden]) ~ .annot:not([hidden])`,
not `:first-of-type` -- Setup and Print both hide sections depending on
state, and a structural selector drew a stray rule across the top of
the page whenever the first section in the markup was not the first on
screen.

### Never `confirm`, `alert` or `prompt`

The desktop app's browser pane **suppresses native modal dialogs**.
The drop button called `confirm()` and looked dead for weeks: the
handler ran, the dialog never appeared, and the code waited for an
answer nobody could give. Proved by stubbing `window.confirm` and
watching it be called while the screen did nothing.

Where an action needs a way back, give it a visible one instead of a
question. Drop acts at once and the student lands in a Dropped band on
the same screen, with restore in the same column.

### `askFor()` when the answer is text, and a test forbids the natives

`window.prompt` is suppressed here exactly as `confirm` is, and returns
null, which a caller reads as "cancelled". Two controls shipped dead
that way and nobody could tell, because a suppressed modal makes a
button do nothing *silently*:

- **Push it**, on Update form -- the one control that changes what
  students see.
- **How many versions**, on Seating.

`askBox` is the one dialog. `ask({title, body})` resolves true/false;
`askFor({title, body, value})` shows the field and resolves to the text
or null, the same shape `prompt` had. app.js loads before seating.js,
so seating can call it.

`test_no_native_modal_is_used` holds the line now. A paragraph in this
file did not: it already said never to use them, and the second one
shipped anyway. The check scans both scripts for bare calls **and** for
`window.`/`globalThis.`/`self.`-qualified ones -- the first version
checked only bare calls and let `window.prompt` straight through, which
is how the Seating one was still there after the Push one was fixed.

### `ask()` is how the app asks, and `okDespitePending` is why

`window.confirm` is suppressed here, so `ask({title, body, yes, no})`
does it instead -- a promise over a `<dialog>`, which is an element on
the page. Escape is a cancel.

`pendingElsewhere(saving)` lists unsaved work on tabs *other* than the
one saving, and `okDespitePending` asks about it and is silent when
the list is empty. Seating's save calls it, because the chart is where
the print order and every seat's version come from.

**Only warn when something is at stake.** The first version fired on
every seating save, because `skillsDirty()` compared the server's
assessment against an `assessment` object that is only filled when the
Update form is *drawn* -- and the prefetch loads `skills` at boot. Any
new "is this tab dirty" predicate must be false for a tab that has
never been opened.

### Nothing on the Roster writes before Save

Including drop, which used to write the file on the press. It is held
in `pendingDrops` and applied by `save()`, **before** the field edits,
because the drop call matches on name and a rename applied first would
leave it hunting for somebody who is gone.

### Test a destructive action on a throwaway course

Dropping a student from the live course empties their seat, and
restoring deliberately does not give it back. `room.json` is the
source of truth and `seating.toml` is generated from it, so fixing
only the toml is undone by the next save from Seating. Putting one
seat back took three independent signatures to identify it safely.
`Scratch 48` exists for this.

### What a new tab inherits, and must not reinvent

Stage 4 made these four shared. A tab added later uses them; it does
not grow its own.

* **`<div class="savebar" id="<view>-bar" hidden>`** with a
  `.dirty` span, then `Save` and `Discard`. Drive it with
  `saveBar(view, dirty, what)`, which hides the bar when clean. **One
  bar per tab, and nothing else in it** -- `#print-news` was in there
  and would have been hidden exactly when it mattered. A disabled Save
  is not the pattern; an absent bar is.
* **`.warnline` draws its own `⚠`.** Never type one into a message; a
  test fails on the character appearing in `app.js`.
* **`.emptystate`** -- a `.lead` line saying what is missing, then the
  way out: a button, or a `<code>` command with `-c "<course>"`
  already filled in. Not a sentence restating that the screen is
  blank.
* **Sentence case on every control label.** Prominence comes from
  `.primary` versus `.act`, not from capitalisation.

### Pushing and pulling do NOT need the Google sign-in

`form push` and `form pull` both go through `form.call`, which is an
HTTPS POST to the deployed Apps Script web app carrying the shared
secret from `secrets/form-secret.toml`. No OAuth token, no clasp, no
browser. **A course whose clasp sign-in lapsed pushes and pulls
perfectly well.**

clasp is used by `provision.py` alone -- creating the form, deploying
or redeploying the script, re-authorizing it. Those live on Settings.

The Form tab used to carry "Not signed in to Google, so pushing will
fail", driven by `clasp.logged_in()`. The check was real and the
conclusion was invented, and it was on screen on the morning of
2026-10-23 while a pull was in fact succeeding -- it sent an hour of
diagnosis down the wrong path. What actually stops a push or a pull is
`conn.ready`: a web app URL and a secret. `renderFormBar` says that,
and both working tabs call it.

### Both marks are optional, on three surfaces

`ids` and `codes` are print options beside `keys`, `key_copies` and
`names`, and travel the same road: the draft (`job.toml`), the
publication (`[print]`), the Paper row of the Print tab, and
`build --no-ids` / `--no-codes`.

**Both default on, everywhere, and absence means on.** A draft or a
publication written before these existed describes a run that had
them; reading a missing key as off would quietly change what an old
job reprints. The theme defaults them on too, so `main_tex` writes a
switch **only to turn one off** -- which is what lets a document from
a newer printit still compile against an older `printit.sty`.

The CLI flags are `None` by default, not `False`: they mean "whatever
the publication says", and they do not rewrite the file. A plain
`False` default would have turned the marks off for every caller that
did not think about them, `--replay` among them.

### The header and footer have no slack, and fancyhdr does not clip

**Every slot has an explicit width.** Without one a long name or a
long title simply runs through whatever is beside it. Both happened:
a 21-character name plus a nine-digit id ran through the course and
date, and "Skill Checkpoint Redo 2026-10-23" ran through the version.
Judge this on a real title with a real name in it -- a probe called
"Probe" shows neither.

The text block is 7in and the header's three parts very nearly fill
it. They are now three fancyhdr slots rather than two:

| slot | holds | width |
|---|---|---|
| `[L]` | `Name:` and the name | 2.5in box, name budgeted to 2.1in |
| `[C]` | `ID:` and the field | centred on the head |
| `[R]` | course, term, author | what is left |

The id is in the centre slot so that a printed id and an empty grid
land in the same place, which they did not when the id simply
followed the name. That fixes where the id starts, so the name is
**scaled to fit** past 2.1in rather than colliding with "ID:". The
longest name on either roster is 22 characters and is not touched.

The budget was set by measuring ink columns, because the gap that
matters is from the name to the word "ID:" -- and the `name` and `id`
marks do not include that label. Reading the gap between the marks
called a 27-character name clear while the render showed it touching.

### A theme change does not reach an existing bank

`theme.install` keeps a bank's own `printit.sty` unless forced --
"that file is the author's, and may be a term's worth of layout
work" -- so none of the page marks print until

```
checkit-printit install --force
```

is run against the bank. That is deliberately the instructor's call.
The first real build against `mat-106-checkit` failed on an undefined
`\setrunid` for exactly this reason; `test_the_theme_defines_what_
main_tex_calls` guards the pair for a fresh install, and nothing can
guard a bank nobody has updated.

### The Scans tab, and what places a page

`scans.py` turns PDFs into placed pages and stops there. Marking is
a separate job with a separate failure mode, and placing has to be
trustworthy before a reading of somebody's tick is worth showing.

Every page is identified by its own footer code, so **order carries
nothing**: any sequence, any number of files, blanks mixed in.

Five statuses, because "could not place" is several problems:
`placed`, `blank` (no code, almost no ink), `unreadable` (ink, no
code), `foreign` (a code, not ours), `unknown-run`.

Three questions of the batch. Which runs; what was read twice, which
is never resolved automatically because two scans of one paper are
usually identical and occasionally are not; and **what never came
back** -- the question nobody asks until it is too late.

`missing` counts **students' papers only.** Padding has no index
line, a key never leaves the instructor's folder, and a spare is
printed in case somebody needs one, so most runs end with spares
nobody took. The first version counted all three and reported six
missing for a stack short of two papers.

`INK_FLOOR` separates a blank sheet from one that failed to read. It
is a guess made against simulated scans and **needs calibrating
against the real copier**: a machine that runs dark would put an
empty sheet above it, and every padding page would then be reported
as a paper that failed.

The read runs in a thread with a polling status, like the Google
sign-in, because a few hundred pages takes minutes.

**`tools/demo_scans.py`** builds a course, a run and a stack that is
wrong in the ways a real stack is wrong -- shuffled, split in two, a
blank, a page read twice, one paper held back. `--home` keeps it out
of the real print-it home, which anything that builds should do.

### `attempt` is the only table an outcome is read from

`printed` says a paper was handed out. It cannot know who was in the
room, so nothing in it is an attempt and its wording never says so.
`attempt` is the separate table that does.

Keyed **(run, student, skill)**, not by page. A page is how a sheet
is *found*; an attempt is about the occasion. Two papers for one
skill in one run -- only reachable by hand-editing a job file, since
`append_for_everyone` dedupes -- are still one decision. The write is
an upsert, so a correction replaces rather than stacking a second
attempt and making Progress say the student sat it twice.

`page`, `reading`, `ink` and `beside` are NULL for a paper that never
reached the scanner. Not zero: "page 0, no ink" is a reading, and a
measurement nobody took is a number somebody later averages.

Four outcomes, `record.OUTCOMES`: `passed`, `queried`, `failed`,
`absent`. **`queried` is stored as itself** -- it is his "?" beside
the box, a paper still in question, and folding it into pass or fail
would throw away the only record that it was ever in doubt. Progress
counts it as an attempt and not a pass.

Writing marks every run in the batch `graded`, in the same
transaction, because a saved decision on an ungraded run could be
delisted out from under itself.

### The browser sends judgment and nothing else

`/api/scan/save` takes `{id, outcome}` and no more. Which student,
which skill, which page and what was measured all come from
`SCANNING.result`, the server's own copy of the read. A reloaded or
stale page then cannot attach a decision to a different student --
which is the one mistake here that nobody would ever notice.

The cost is that the read lives in memory: restart the server between
scanning and saving and it is gone. Refused with a message saying to
read the stack again, which is the honest trade.

### A review row is a paper, not a sheet

`batch.placed` is every placed *sheet*, and a real stack has the same
sheet in it more than once often enough that `duplicates` is one of
the three questions a batch answers. Grouped by (run, page), so one
paper is one row however many times the copier saw it.

The row carries **every** crop taken of that paper, and when the
copies disagree -- a double feed that lost a tick -- it suggests
nothing and shows both. Picking one for him would pick the blank one
half the time.

### The Progress grid, and the two rules that make it readable

45 students by 29 skills is about 1,300 cells. Two rules from 14.3
keep it from being a wall:

* a **pass count** appears only where the threshold is above 1;
* an **attempt count** appears only when it is surprising -- passed
  first time needs no number, four attempts and still not passed is
  the thing worth seeing from across the room.

**Passing is quiet.** A gradebook is read for trouble. The loud cell
is `.stuck`: not passed, more than once.

A query adds a corner dot, not a state. An absence dashes the box
rather than drawing it solid -- there was no paper, so there is no
solid edge -- and neither is a seventh thing to learn.

Thresholds live in `course.toml` under `[passing]`, default 1, and
**not** in `bank.xml`: that file is shared and published, and how
many checks this semester's class needs is about this semester's
class.

Clicking a cell opens its history: every time that student was
printed that skill, with what was decided. Driven off `printed`, so a
run handed out and never scanned is in the list with nothing against
it -- that row is the paper he is holding months later with no stack
left to re-read, and recording it there goes through the same
`save_attempts` a scan does.

### The Runs tab, and what it is allowed to do

`record.db` already held everything: the `run` table plus `printed`.
Two columns were added -- `delisted` and `graded` -- with a migration
in `connect()`, because `CREATE TABLE IF NOT EXISTS` does nothing to a
table that exists and the real course had runs in it already.

* **A graded run cannot be delisted**, refused in `record.set_flags`
  and not merely hidden in the view. **Grading a delisted run
  un-delists it**: the reason a graded run may not be delisted is that
  what was read back has to be findable, and that applies equally to
  one delisted before it was scanned. Asking for both in one call is a
  contradiction and is named as one.
* **Delisting never deletes.** The `printed` rows under a run are the
  only record that a paper existed, and Scans may still have to place
  a loose sheet from it.
* **Reprint and reuse are separate**, because merging them is how
  somebody reprints last month's papers by accident. Reprint replays
  the manifest; reuse loads the old settings into the draft and
  **writes nothing** -- title and date are deliberately not carried
  over, since they are what made it that run and the date names the
  folder.
* A run's job folder is found by rebuilding its name with
  `printjob.folder_for`, not by storing a second path that could go
  stale -- `run_id` is already `"{title} {date}"`.

### Who a run is for is not one of the modes

`who` is `"all"` or `"these"`, beside `mode` rather than inside it.
The modes decide **what** a student gets; this decides **whether they
are in the run**, and the two compose -- a reprint for one student
still reads that student's own form choices, or an override typed for
them. Folded in as a third mode it would have meant retyping those
choices to print one paper, which is the thing it exists to avoid.

In the job file the key is `[selection] only_students`, and it has
**three** states, not two:

| in the file | means |
|---|---|
| absent | the whole class |
| `["806001234"]` | these students, matched on id, alternate id or email |
| `[]` | nobody -- a mistake, and `assemble` refuses it |

The third is the point of the first. If an empty list read as "the
whole class", unticking everybody would print forty-three papers.

**The filter has a deliberate second copy**, like `live()`: `assemble`
applies it and so does `build_handouts`, because `build_handouts` is
public and is called directly by tests and by the print view. Both
sites used to be written `and hasattr(roster, "only")`, copying the
`hasattr(roster, "live")` above them -- harmless there, and here it
meant a caller passing a plain list silently printed the class.
`assemble.as_roster` now normalises once and the guards are gone.

### The draft carries only what its mode uses

`save_draft` writes `simply_print` in `same` mode, and
`default_when_missing` / `append_for_everyone` in `chose` mode. Never
both. The same rule `write_job` applies to `publication.toml`, for the
reason stated there: a file carrying a setting the run does not use is
a file that will be read back later and believed.

The draft was the exception, and on 2026-10-23 it held
`mode = "chose"` beside `simply_print = ["N2"]`, four days old. One
click on the mode toggle would have printed N2 for all 43 students.

The kept keys are written **even when empty**, unlike in `write_job`:
this file is hand-edited, and a key that vanishes when you clear it is
a key you cannot find again. It is the *other* mode's keys that go.

The cost, stated so nobody treats it as a bug: set up a `same` run,
switch to `chose`, save, and the list is gone. Within one session the
page holds both in memory; it is the save that drops one.

### A seat carries the student id, and the two files are checked

`seating.toml` holds the print order and the version letters;
`room.json` holds the room itself -- shapes, positions -- and who sits
in it. They are **not** duplicates, and should not be merged: they
overlap in one fact, who sits where with which version, and the same
save writes both.

Each seat now carries `sid` beside the name, and `Chart.order` matches
on it first, falling back to the name. Before that, the chart was the
one join in the tool made on a name -- and `api_roster_save` writes the
roster and nothing else, so renaming a student in the Roster tab left
the chart naming somebody who no longer existed. They lost their seat,
their place in the stack and their version letter, silently, because an
unmatched seat is skipped. `room.json` keyed by id all along and
survived the same edit. The error message in that very handler says a
name "is what the seating chart matches on".

A chart with no ids -- hand-written, imported, or written before the
key existed -- still matches by name and is untouched.

`seating.disagrees_with_room(chart, room)` names every divergence, and
`_build` refuses on one. Only the web app can run it: the CLI build
reads `seating.toml` and knows nothing about `room.json`. It compares
by id only, so a hand-written chart produces no noise.

**The ids reach an existing course on its next Seats save.** Until
then the chart matches by name, exactly as before.

### Dropping removes a student from the whole run

`Roster.live()` is the filter, and `assemble` and `build_handouts` both
apply it. Two copies on purpose: `build_handouts` is public and decides
what prints, `assemble` also protects `check_flat_pins`. Both are pinned
by their own test -- mutation showed that with only one in place every
other test still passed.

It used to be enforced *only* by emptying the seat.
`check_dropped_are_unseated` says printing works off the chart and so
there is "deliberately no filter at print time" -- but `build_handouts`
prints `ordered + unseated`, so a correctly emptied seat moved the
student into the second group rather than out of the run. On 2026-10-23
a dropped student got a three-page packet built from the previous
week's choices. The guard passed: it looks for dropped-but-still-seated,
which is the opposite mistake.

`check_dropped_are_unseated` still runs **before** the filter, because
filtering first leaves it nothing to find.

### Only `form pull` dates a choice, and only two things write one

`form pull` writes `skills` and stamps `chose_for`. The only other
writer is `from_spreadsheet_export` (the `import_csv` command), which is
a documented one-way migration and leaves choices undated. The class
list importer creates students with `skills = []` and `merge` preserves
what is there; the GUI's roster save does not touch skills at all.

So "undated" is a migration state, not a steady one. After one pull
every active student is dated, and a date that never appears is the
point.

### availability.toml is a local copy of what the form says

`skills` there is the open-for-retake list that `form push` sends as the
question's options. It is **not** read back from the form, so it can
drift -- on 2026-10-23 it was `[]` while the live form was offering 14
options from an earlier push. Nothing silently breaks: `nothing_to_say()`
refuses a push with no skills or no date, so the blank cannot reach the
form without `--force`. `skills set` only rewrites the lines it is given
and never clears the list.

### A choice carries the day it was made for

`Student.chose_for` is a date, or None. `form pull` stamps it with the
assessment it scoped to, and clears it along with the skills when it
clears a silent student. None means "written before this field existed,
or set by hand" and is reported as **unknown**, never as agreement.

Why it exists: `skills` alone cannot be told from last week's `skills`.
On 2026-10-23 the roster still held the 10/16 answers -- verified
byte-identical against the 10/16 run in `record.db` -- because
`availability.toml` still said 10/16, so every pull re-fetched the same
responses and the Print tab showed them as current. The same failure
had happened on 10/16. Twice in eight days, silent both times.

The Print tab now reports two things separately, because they are fixed
differently: the **cause** (the job's date and the assessment's date
disagree, so a pull will keep fetching the wrong week however often you
press it) and the **symptom** (rows holding another day's answers, which
outlive the cause until the next pull lands).

### A bare class that takes an element out of flow is never a modifier

`.stale` is the page-is-older-than-the-server banner: `position: fixed`,
warn background, bottom-centre of the window. A Print tab cell was given
`class="aged stale"` and one table cell left the table and parked itself
over the page. All 805 tests passed; it took a screenshot.

This is the fourth class collision here and the first *inside* one
stylesheet, so the cross-file check did not apply.
`test_a_class_that_escapes_the_page_is_never_a_modifier` holds it now,
narrowly on purpose: sharing a word is not by itself wrong
(`.vcircle.badge.editing` wants the bare `.badge` rule), but sharing one
with a rule that takes an element out of flow always is.

### A glyph strokes itself; the button gives it a surface

`glyph(name)` builds the SVG and puts `class="glyph"` on it, which is
where `fill: none; stroke: currentColor` lives. **Do not move that to a
context selector.** It used to be on `.navrail button svg`, and the
first glyph used anywhere else rendered as a solid black blob -- a path
with no fill rule is filled, and the colour never reaches a stroke that
is not drawn.

`.iconbtn` is the chip around it: grey surface and border at rest, the
accent on hover, which is the instructor's rule for a row action. A
glyph with no chip reads as a picture printed on the row rather than as
something to press.

### One line weight, 1.5px, everywhere

Every glyph is drawn in a 24-unit `viewBox`, and `.glyph` carries

```css
stroke-width: calc(24 * 1.5 / var(--glyph-size, 18));
```

so a glyph rendered at any size still puts 1.5 real pixels on screen.
That only holds if `--glyph-size` tells the truth. **Any rule that
gives a glyph a width must set `--glyph-size` to the same number in the
same block.** Four places do today: the rail at 21, `.iconbtn` at 18,
`.iconbtn.tiny` at 13, and the band chevron at 13.

Forgetting it is not a visible mistake on its own -- a 16px glyph
inheriting 18 draws at 1.33px, which nobody can see in isolation and
everybody can see next to a 1.5px one. That is how the rail's gear and
collapse chevron came out lighter than the five icons above them.
`test_every_glyph_size_comes_with_its_own_variable` and
`test_the_one_weight_is_stated_once` now hold the line; both were
watched failing against three deliberate breakages before being
believed.

A dot inside a glyph is a zero-length segment -- `M18.4 12h0.01` with
`stroke-linecap: round` -- not a small circle. It is then exactly one
stroke-width across and scales with everything else. The door knob was
a stroked `r=0.6` circle and thinned away to nothing at 18px.

### `app.js` and `seating.js` share one global scope

Two plain `<script>` tags, so a top-level `const` declared in both is a
SyntaxError -- and the file that fails is **the other one**. Renaming
`NAV_ICON` to `ICON` collided with seating.js's own `ICON`: the Roster
rendered perfectly and Seats did not load at all, with nothing on the
Roster to say why. The shell's set is `GLYPH`.

Same rule as the stylesheets, same remedy: the markup tests fail on any
name declared at top level in both files. And when a console error
persists after you have fixed it, check `typeof` for the globals --
`read_console_messages` returns a buffer that survives navigation, and
a stale SyntaxError reads exactly like a live one.

### How the Roster table behaves, and why

* **It scrolls inside the window, not the page** (`body.tall`, set in
  `show()`). With 45 rows the scroller was 2158px tall and its
  horizontal bar sat 1362px below the fold, so sideways movement was
  shift-and-wheel only and the drop column could not be reached.
* **Name is pinned left, the actions pinned right.** For sticky cells
  to work the table needs `border-collapse: separate` *and* no
  `overflow: hidden` on the `<table>` -- a clipping ancestor between a
  sticky cell and the scrollport is what it resolves against. The frame
  and rounding live on `.scroller` for that reason; do not move them
  back.
* **`rank` is what survives a squeeze, and an action outranks data.**
  Email and SID are reference; dropping a student is what the tab is
  for.
* **`min` is what a column wants, `floor` is what it may be squeezed
  to**, and a column empty for every row starts at its floor. `Prints
  as` was reserving 200px on a roster where nobody has one.
* **Spare width goes to the `grow` columns**, so the table's right edge
  meets the heading above it.
* **A hidden element measures zero, and zero is not "no room".** Sizing
  at boot, while the tab was hidden, pinned every column to its floor.

### What prints in the corner comes from `course.toml`

`\date` is the semester and `\author` is the instructor, both read
from `course.toml` by way of the publication. The template creates them
empty, and for a long time **nothing could set them**: `course init`
was the only writer and the web app had no field. Every run that had a
semester had it typed into a `publication.toml` by hand, so the first
run built entirely in the app printed a blank corner.

`course.save_identity` writes them now, Setup has the fields, and
`assemble.header_gaps` reports after a build which of them will print
blank -- a note, not a refusal, because a course may genuinely want an
empty corner.

`save_identity` is a **line rewrite, not a TOML dump**: that file is
mostly a comment explaining itself, with `[bank]` underneath. It
anchors on column zero so a key indented under another table is left
alone.

### What is slow, and where the waiting happens

Measured against the real course, from the page:

| call | cold | warm |
|---|---|---|
| `/api/skills` | 1194ms | 710ms |
| `/api/google` | **6072ms** | 395ms |

`/api/google` shells out to clasp. `/api/skills` reads `bank.xml` and
`availability.toml` and **makes no network call at all** -- Open for
retake has nothing to do with Google.

Its cost was that it built the bank **three times for one request**:
once itself, once in `_wording`, and once more because `_preview`
called `_wording` again. Both helpers take a `bank` now, with a
sentinel default because `None` already means "no bank", and
`_preview` takes the wording the caller already computed. 710ms to a
265ms median. `api_skills_preview` had the same shape and fires on
every keystroke.

Building a `Bank` per *request* is still right and is not the bug: one
`Course` lives for the server's lifetime, so a `Bank` held between
requests would hold stale seed data after a `checkit generate` --
which is what the variant guard reads.

Both start at boot (`fetchSkills`, `fetchGoogle` in `boot()`),
unawaited, after the Roster is drawn. They are kept as **promises, not
data**, so a second caller joins the first request: Setup and the Form
banner both want the Google answer and were making a six-second call
each.

Two traps if you touch this:

* **"Data arrived" is not "tab drawn".** `show()` used to draw the Form
  tab `if (skills === null)`, and prefetching makes that false before
  the tab is ever opened -- it came up blank. `skillsDrawn` is the
  second flag, set after a successful render, and drawing stays once
  per session because `fillAssessment` would otherwise discard edits.
* **`show()` writes `location.hash`, which fires `hashchange`, which
  called `show()` again.** Every tab switch ran its loader twice. The
  handler now ignores a hash matching `shownView`; back and forward
  still work and should be re-checked if you touch it.

### A surprising timing is the harness until proven otherwise

A warm tab switch measured 4997ms. The browser pane was hidden,
`requestAnimationFrame` is throttled in a hidden document, and the
polling loop was timing its own throttle. `document.hidden` said so;
a stamp inside the render said 3.1ms. Same family as the stale
`index.html` and the integer-truncated pointer coordinates.

### The markup has tests now, and they are the only ones that do

`tests/test_gui_markup.py`. Until 2026-10-19 **nothing in the suite
read `index.html`** -- the entire Print tab was rewritten and 768 tests
passed without noticing. A mistyped id fails silently in the browser:
`getElementById` returns null, the handler never binds, the control is
simply inert.

It checks the only contract between the two files -- that every id
`app.js` reaches for is either declared in the HTML or assigned by the
script -- plus no duplicate ids, every `?` having something behind it,
and no counter inside a heading. **Run it after any markup change**;
it is instant, and it caught a real 13.5 violation on the Update form
the first time it ran.

### A stale `index.html` will convince you Seats is broken

Seats measured 0x0 with an empty canvas after a markup change, which is
exactly the `.rail` collapse below. It was the browser serving a cached
page, and `ctrl+shift+r` and `location.reload(true)` both kept serving
it. **Append a query string -- `http://localhost:8767/?cb=1#seating` --
and compare stashed against not** before believing a regression. The
server reads the static files from disk per request, so it is never the
one that is stale.

### A skill has two names, and they are not interchangeable

Every outcome in `bank.xml` carries a short `<title>` ("Analyzing
Student Work") and a long `<description>`, the "I can..." statement.
**Titles belong in tables and headers; descriptions belong in
tooltips.** `Bank.skill_title(slug)` reads the first and falls back to
the slug; `Bank.description(slug)` reads the second.

`api_skills` and `api_print` each build their own `{slug: ...}` maps,
which is two copies of one loop and has already drifted once -- a patch
that added titles to one payload and built them in the other raised
NameError on the second endpoint, found by a test on its first run.

## The course

Course state that outlives a job, at `~/CheckItPrintIt/courses/<name>/`
(relocate all of it with `CHECKIT_PRINTIT_HOME`):

```
course.toml  roster.toml  seating.toml  availability.toml
form.toml       record.db    secrets/
```

**One course folder need not be one course.** An instructor may run both
sections from a single folder with one form, or make "MAT 106 820" and
"MAT 106 830" and keep them wholly apart -- separate form, seating,
availability and record. Both are supported and neither is the default.
The directory is named by whoever makes it; nothing derives it from the
course code.

A job's `publication.toml` says `[course] folder = "..."` instead of
carrying copies. **`folder`, not `name`** -- `name` in that same table is
the printed header string and always was, and it is a key rather than a
`[course]` table of its own because the file already has one and TOML
refuses a duplicate. An explicit `[roster] path` still wins, so every job
folder written before courses existed keeps working.

**Why it exists:** three job folders each held their own copy of the same 48
students, because a job resolves its roster relative to itself. A student who
dropped had to be remembered and re-applied at the next copy.

## Rules that are load-bearing

**If a human is the author, TOML. If the tool is, SQLite.** Roster, seating,
availability and form config are hand- or GUI-edited, so they stay diffable
and hand-fixable. The print record is machine-written, unbounded, queried
rather than read, and written by two processes -- the CLI at build time and
the eventual gradebook editor changing a single field.

**The seating chart is the print list.** There is deliberately no `dropped`
filter at print time. Dropping empties the seat, and the build *checks* that
the two files agree rather than filtering -- a filter hides a divergence, a
check names it. The seat is emptied, not removed: version letters come from
position, so deleting the entry re-letters that student's tablemates.

**Printed is not attempted.** The record says a paper was handed out; it
cannot know who was in the room. Do not write "attempted" anywhere until the
gradebook stage exists.

**Never rewrite these TOML files by parsing them.** They carry hand-written
comments and Python has no TOML writer that keeps them. Use the line editors:
`seating.blank_seat`, `availability.set_values`.

**Ids, never positions.** Form responses are stored against a question's id.
The roster joins on SID, then the other id, then email, and never on a name
alone. The old Apps Script used `getItems(CHECKBOX)[1]`, so inserting one
header above it silently retargeted every write.

**Email is a weak key, not a fallback key.** One real student appears under
two addresses in two same-day exports, and the Google Form only ever sees one
of them. Addresses accumulate; the primary never moves.

**`skills` sits under `[assessment]`.** A TOML table runs to the next header,
and a blank line does not unindent anything. Reading it from the root made an
open list look empty.

## Printing, unchanged and still true

- The theme is two `.sty` files because `printit.sty` cannot load inside a
  `standalone` figure -- it wants page geometry, `\acadclass` and `\title`.
- Every run writes a folder that compiles with `pdflatex main.tex` and nothing
  else. Figures are copied in by scanning the written `.tex`, which is why a
  `textemplate.tex` must choose **in Jinja** which files it names: an `\input`
  in a branch LaTeX would never run is still text, and the build hunts for it.
- `choose_seeds` draws **without replacement** per skill. Drawing
  independently collided about one run in fourteen at ten versions.
- `build --preview` writes nothing, and **the seeds it lists are not a
  prediction** -- carry its reported run seed across with `--seed N`.
- `manifest.toml` records the **result**, so `--replay` survives edits a seed
  would not. A changed input is a note; a changed variant or generator is
  refused, because then the seed is a different paper.
- `[seeds.<skill>]` pins one letter of one skill. The flat `[seeds]` form
  names no skill, so it means all of them -- refused above one skill, because
  it used to hand out three wrong papers in four with no error.

## Google, and why it is shaped this way

No Cloud project on the institutional account, so no OAuth client of our own.
An Apps Script bound to the form executes as its owner, so there is no
identity to prove -- and **clasp supplies the browser sign-in using its own
OAuth client**, which is what makes `form create` a single command. Nothing
needs installing: clasp is a Node program, so a Python venv cannot hold it,
but `npx` fetches it on demand.

The deployed web app must accept a request from a terminal holding no Google
credential, so it is open-with-a-secret. **The URL is a credential too.** Both
live in `secrets/`, never in `form.toml`; a test asserts it.

printit owns exactly four slots on the form. The banner, title, grade cutoffs
and syllabus links are the instructor's, and a push must not touch them.

`reference/control_center.gs` is the retired Apps Script, kept verbatim as the
specification for wording and behaviour. Read it before changing anything a
student sees.

## Where things stand

Stages 1-7b are done. **7a and 7b both ran against a real Google account**
and work: create, attach, map, add-items, push, and pull. Read "Stage 7a,
against a real Google account" and "7b against a real response" in
`../checkit/CODEBASE_NOTES.md` before touching `clasp.py` or `Code.gs`.

Everything Google can now be done from the app as well, which is the point:
**if the app ever tells someone to go and run a CLI command, that is a
bug.** It did, in the Responses card, and that is what prompted Setup.

**Stage 8, the local web app.** One row per slice, in the order they were
built rather than alphabetically, because several are part-done:

| | | |
|---|---|---|
| 8a | shell | done |
| 8b | **Roster** | done -- editable table, drop/restore, stacked sorting |
| 8c | **Update form** | done -- open skills, the assessment, a form-shaped preview, the push |
| 8d | **Print job** | done -- modes, variants, extras, per-student override and version, preview, build |
| 8e | the response pull | done -- it is Print job's first card, not a tab |
| 8e | **Record** | **not started.** The only view still entirely untouched |
| 8f | **Seating** | its own module under `gui/static/seating/` — ~5,900 lines of JS and ~1,600 of CSS, by far the largest thing in the app. Four modes in the rail (**People, Groups, Seats, Printing**) and two overlays that cross them (**Up Next**, **projector**). A room can be built from nothing. See the table below, and `../checkit/PRINT_TOOL_DESIGN.md` 12.11–12.17 |
| 8g | ~~Cold call~~ | **folded into Seating as the Up Next mode**, and renamed: the students see it. No tab of its own. See `../checkit/PRINT_TOOL_DESIGN.md` 12.12 |
| 8h | **Setup** | half done -- a form can be created or attached from the app. The boilerplate editor is still to come |

**A control drawn inside `.paper` must be excluded from the paper's
own `pointerdown`,** or pressing it starts a pan, pointer capture
takes the `pointerup`, and no click is ever dispatched to it. The
handler skips `button, input, select, textarea, a` for that reason.
`.plusbtn` never hit it only because it lives outside `.paper`.

**`element.click()` cannot verify a button.** It runs the handler
without hit testing, capture, or any ancestor's listeners -- so it
reports success on a button no pointer can reach. That shipped once,
over the top of two real clicks that had already failed and been
explained away.

**A course starts its rooms by itself.** `loadSeating` calls
`/api/seating/start` when the room has no sections, so a roster that
names 820 and 830 gets 820 and 830 without being asked, unsaved. A
new room opens in **Groups**, because the shape palette's plus is
only there. The empty state below is now only the retry when that
fails.

**A course starts with no room, and the empty state is where it
begins.** "Start the room" posts to `/api/seating/start`, which makes
one section per section the *roster* names. The names come from the
roster because `standing` filters the unseated rail by comparing them
to a student's `section`, and a name matching nobody turns the filter
off instead of failing. Until 2026-10-11 there was no such control and
`room.new_section` was called only by tests, so a real course could
not draw a room at all.

**`course init --adopt` can hand you a chart the tab will not
overwrite.** A `seating.toml` from a spreadsheet export is not a room,
and `save` leaves a chart it did not write alone -- so the room saves,
the build keeps reading the old chart, and nothing looks wrong. Check
`seating.was_generated` on it, and delete the adopted copy if the room
is meant to be the source. The job folder still has the original.

**Inside Seating.** The modes, and what a click means in each:

| mode | a click | a drag on bare paper | the corner button |
|---|---|---|---|
| **People** | pick a name, click a chair to seat them; the pin in a card's corner holds somebody in place | pans | ⋯ seat all, shuffle, unseat all, unpin all, add person |
| **Groups** | select furniture; grips resize, the spinner turns | bands a selection of groups | **+** the shape picker; drag a shape out, or click to drop it in the middle |
| **Seats** | select a seat; drag to move or reparent it | bands a selection of seats | **+** add a seat to this desk |
| **Printing** | select a seat; numbers and version circles are editable where they sit | pans | ⋯ what Printing can do to the room |

**The corner button is two controls in one place.** A `+`, accent
filled, where the mode has one primary action -- adding a thing. A
quiet `⋯` where it has a short list instead. That is Material's rule:
a floating button carries one action and overflow belongs in a menu.

**Ctrl-click** (cmd on a Mac) adds to the same selection a dragged
rectangle makes, in Groups and in Seats.

**Space held, the middle button, or two fingers pan**; two fingers
spreading, or the wheel, zoom -- the wheel about the pointer. Space is
taken only while the pointer is over the paper, so a keyboard user
keeps it for pressing the focused button; while it is held, the focus
is dropped, because a button fires on the space *keyup* and panning
would otherwise press whatever was last clicked.

`Up Next` and projector mode are switches in the top-right island, not
modes -- they cross whatever mode is underneath and restore it on the
way out. **While either is on, nothing drawn on the canvas is a
control**: `showing()` is the one predicate, and it takes out every
drag, handle and pin at once.

**Model fields this view owns** (all optional, all validated in
`room.check`, all absent in a room nobody has touched):

| field | means |
|---|---|
| `group.order` | where this group falls in the printed stack |
| `group.hue`, `group.chroma` | its color; lightness is the design system's and is never stored |
| `group.label_at` | which desk and which of nine anchors the label hangs on |
| `seat.version` | which paper prints for this seat |
| `seat.pinned` | this chair's occupant stays in it: no drag, no drop, no shuffle, and not filled by "seat everyone" if empty |
| `seat.spot` | its place inside its own group's run |
| `seat.order` | its place across the whole room |
| `section.print_by` | `"group"` or `"seat"` |
| `section.canvas.background` | one of `grey`, `white`, `warm`, `cool`. **Not** "paper", which here is the sheet in the printer |
| `shape.w`, `shape.h`, `shape.angle` | a desk resized or turned |

A group spans **whatever desks its seats sit on**, which is all
"merging" two groups is: `room.merge_groups` folds the seat lists,
`room.split_group` regroups by desk, and nothing moves either way. A
merged group travels whole on a drag and turns about its common
middle. Seat letters needed no case for it -- a letter is derived from
its *group*, so a merged group sweeps the whole arrangement as one
ring.

**The canvas has no edges.** Coordinates may be negative; nothing in
the model minds, and fitting and centring measure the content's own
box. `section.canvas` is a record of how far the room reaches from the
origin, not a fence. Fit, not a wall, is what makes a runaway drag
recoverable.

A **seat letter** is *not* stored: it is derived clockwise from the top
left of its group every time the room is drawn, so "recalculate when a
seat moves" needs no bookkeeping. It is not the print version; the two
start equal and diverge the moment versions are shuffled.

**How the chart says what order to print in** (settled 2026-10-10).
A `[[group]]` is a *table*: its seats are listed in the order they sit,
swept clockwise from the top left, and that order is never changed for
printing. The stack is each seat's own `at`, written **only when it is
not the order the file already reads in** -- so a room handed out table
by table with nothing reordered produces exactly the file it always did,
and every hand-written chart is untouched. A seat with no `at`, among
seats that have one, prints last.

That split is what lets `print_by = "seat"` reach the paper at all: one
walk round the room crosses tables, and no ordering of `[[group]]`
blocks can say that. It is also what keeps `Chart.collisions` honest,
since consecutive entries in a table's list are people sitting beside
each other and consecutive entries in the *stack* are not.

**Labels are a verb and its object: two words, three at a push.**
"Seat all", "Shuffle room", "Unpin all". No counts, no sentences --
those go in the tooltip, which is a fragment and not a sentence
either. See `../checkit/PRINT_TOOL_DESIGN.md` 12.16, which exists
because this was asked for three times.

**Nothing on the canvas may wear the accent.** `--isle-key` means
"the state you are in" on an island; on the paper it lands beside
whatever colours the groups happen to be. Everything the canvas marks
-- a band, a reparent target, a trade target, the paper under a
dragged shape -- uses `--mark`, one grey. The exception is a *single*
selected group, whose ring is that group's own colour, because that is
what says which group you have hold of. One ring geometry for all of
them: `--pick-out` and `--pick-line` on `.deskwrap`.

**Pointer capture does not give you the pointer to yourself.** It
redirects the captured pointer to your element; it does nothing about
any *other* pointer arriving there as well. So a `pointermove`
handler for one gesture must check `e.pointerId`, or a second finger's
position is read as the first one having travelled -- which jumped the
room by the distance between the fingers until 2026-10-11. `panPaper`
and `bandPaper` both guard it now.

And when a second finger lands, the one-finger gesture is **called
off**, not left running: both listen on the paper, so otherwise they
fight over `pan` on every move. `endGesture` holds the teardown of
whichever started, and `twoFinger` calls it. It is a bare teardown on
purpose -- ending a pan that never travelled clears the selection, and
starting a pinch is not a click on bare paper.

**`seats_of` is a view, not the seats.** It builds a fresh dict per
seat carrying id, shape, student, version and absolute position, so it
**drops `pinned`, `spot` and `order`**, and writes to what it returns
are thrown away. It cost two bugs in one hour. Reading a position asks
it; changing a seat, or reading a field it does not carry, asks
`room.live_seats`.

**The sweep exists twice on purpose.** `room.seat_sweep` and `slotsOf`
in `seating.js` are the same derivation: the canvas needs it live on
every redraw, the writer needs it with no canvas at all. They are held
together by `TestTheSweepMatchesTheCanvas`, which checks every palette
shape by the letters it is known to draw. **A change to either belongs
in both.**

**All three decisions that were blocking 8e are settled**, on
2026-10-01. See `../checkit/PRINT_TOOL_DESIGN.md` 12.6 under "Settled, and
what each one cost":

- the preferred name prints, everywhere
- Responses is **not** a tab; the pull becomes Print job's first card
- simply-print is a **mode**, a segmented control at the top of the tab

All three are built. Responses is gone from the nav; the pull is Print
job's first card. It is always on the tab: with no form connected it says
so and disables its buttons, rather than hiding and leaving no sign the
feature exists.

## Working on the web app

```bash
./.venv/Scripts/python.exe -m checkit_printit gui -c "Scratch 48"
```

`Scratch` is a two-student course wired to a **real Google Form**; use it for
anything touching Google. `Scratch 48` is forty-eight synthetic students
shaped like the real roster -- same section split, same name lengths, same
chart including the three-seat table and the lone seat -- and is what
anything about size or layout should be checked against.

The browser pane's server list comes from `.claude/launch.json` in the
**session's working directory**, which is usually `../checkit`. Both scratch
courses are registered there as `printit-gui` (8765) and `printit-gui-google`
(8766); a gui started any other way will not appear in that list.

**Restart the server after editing anything under `gui/`.** Python does not
reload a module in a live process, and the front end falls back rather than
erroring when a key is missing, so a stale server looks like a logic bug.

**Check the browser at the pane's real width**, around 530px, not only wide.
Two bugs lived in the gap: a table whose columns silently became proportions
rather than widths, and a column hidden by a rule that beat `[hidden]`.

## The rule the GUI is built on

**Every handler calls the function the CLI calls.** Not a copy of it.

| rule | lives in |
|---|---|
| what name to show a person | `Student.display` |
| which version letters a run needs | `assemble.versions_for` |
| which ids a per-run table may use | `roster.keys_of` |
| a per-student override | `roster.apply_overrides` |
| which id a student is filed under | `roster.key_of` |
| which bank a course prints from | `course.bank_for` |
| reading responses into the roster | `responses.pull_for_course` |
| connecting a course to a form | `provision.py` |
| where the desks are, and who sits at them | `room.py` |
| the chart a room produces | `seating.to_toml` |
| the desks a room can be drawn with | `room.SHAPES` |
| which spellings a seat may use | `seating.index_by_name` |
| dropping a student | `roster.set_dropped` |
| the open list, the assessment | `availability.set_open`, `set_assessment` |
| the form's wording | `form.payload_for` |
| the form's fixed text | `boilerplate.py` |
| building | `runner.run` |
| a draft becoming a job folder | `printjob.py` |

Each was lifted out of a `@click.command` body that mixed it with
`click.echo`. If the GUI needs a rule that is still inside one, **move it
out rather than reimplementing it** -- and prefer an alias to a deletion.

A GUI print job **writes a job folder and calls `build` on it**. The folder
is what makes a run reproducible and what `--replay` reads, so there is no
second way in.

