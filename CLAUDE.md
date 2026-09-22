# Working in checkit-printit

Turns a CheckIt bank plus a roster into a printable class set, and manages the
course state around it. The platform is a sibling repo and **the fuller guide
lives there**: `../checkit/CLAUDE.md`. Read that too.

```bash
./.venv/Scripts/python.exe -m pytest -q          # 219 tests
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

### Do not declare something impossible without checking

"A CLI cannot sign in to Google" was said twice, was wrong both times, and
pushed the design somewhere worse. The browser loopback flow works; what was
missing was an OAuth *client*, a different problem with a different answer.

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
| `form setup` / `form connect --url` | the manual path, for when clasp is not an option |

`tools/verify_run.py <job> <out> [--against DIR]` checks a finished run
against the job that asked for it. **A check that examined nothing fails** --
that rule is the point of the file.

`tools/audit.py` checks the tool against itself: stale flags and renamed
commands, commands named in messages or docs that do not exist, options that
are not real, duplicated call sites, dead parameters, and whether all 21
commands parse. It derives the real CLI by running `--help`, so it cannot go
stale the way a hand-written table does. **Run it after any rename or any new
command.**

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

Stages 1-6c are built. **7a ran against a real Google account on
2026-09-21 and works**: attach, add-items, dry-run and push all write the
four slots. Seven bugs were found doing it, none of them the predicted ones.
Read "Stage 7a, against a real Google account" in `../checkit/CODEBASE_NOTES.md`
before touching `clasp.py` or `Code.gs`.

Four of those are worth carrying in your head:

- **clasp exits 0 when it refuses.** `run()` therefore checks the *output*
  for refusal phrases, not just the exit code. Do not undo that.
- **`clasp create-script` overwrites `appsscript.json`** in `--rootDir`,
  dropping the `webapp` block and leaving the deployment with no entry point.
  `create_form` restores the staged one; `attach` re-stages over the clone.
- **Apps Script 404s a live deployment at random**, about one call in three.
  `call()` retries 404 and timeout. It must never retry 401 or 403 -- those
  are real configuration errors and a retry only buries the message.
- **Subcommand names are pinned by tests** against `clasp --help` on 3.4.1
  (`create-script --type forms`, `push`, `create-deployment`). The old tests
  could not catch a wrong name because they assert on what the deployment
  replies, never on the argv.

**`form create` is still unfinished**: a new form needs one browser visit to
authorize the script before any call works. The editor's deploy flow does
this automatically and clasp's does not.

Next: finish that, then 7b (pull responses), 8 (the seating GUI), 9 (the
gradebook). The full plan is `../checkit/PRINT_TOOL_DESIGN.md` section 12.
