# Working in checkit-printit

Turns a CheckIt bank plus a roster into a printable class set, and manages the
course state around it. The platform is a sibling repo and **the fuller guide
lives there**: `../checkit/CLAUDE.md`. Read that too.

```bash
./.venv/Scripts/python.exe tools/check.py        # everything, one exit code
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

**Stage 8, the local web app, is four views in:**

| | | |
|---|---|---|
| 8a | shell | done |
| 8b | **Roster** | done -- editable table, drop/restore, stacked sorting |
| 8c | **Update form** | done -- open skills, the assessment, a form-shaped preview, the push |
| 8d | **Print job** | done -- selection modes, variants, extras, per-student override and version, preview, build |
| 8e | **Record** + the response pull | next |
| 8f | **Seating** | not started; genuinely new code |
| 8g | **Cold call** | not started; genuinely new code |
| 8h | **Setup** | not started -- create a form from the app, and the boilerplate editor |

**All three decisions that were blocking 8e are settled**, on
2026-10-01. See `../checkit/PRINT_TOOL_DESIGN.md` 12.6 under "Settled, and
what each one cost":

- the preferred name prints, everywhere
- Responses is **not** a tab; the pull becomes Print job's first card
- simply-print is a **mode**, a segmented control at the top of the tab

The first and third are built. **The second is the next slice**: fold
`form pull` into Print job, report its failures in place, and drop
Responses from the nav.

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

