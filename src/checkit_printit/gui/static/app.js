"use strict";

// The browser holds edits until Save. Deliberate: `roster import` already
// shows a merge before it lands, and a table that rewrote roster.toml on every
// keystroke would remove the one moment a bad edit is catchable.

const TOKEN = window.PRINTIT_TOKEN;

/* `short` is what the tab is called when the window is narrow. Shorter
   labels rather than a menu or a scrolling strip: at 515px the full set
   wraps to two rows and costs about 35 vertical pixels, and both of the
   usual fixes hide tabs behind a gesture. Nothing here is hidden; the
   words just get smaller. */
const VIEWS = [
  // No Overview. It was eight identical boxes in which the largest word
  // on screen was "yes" -- a dashboard for a tool nobody opens to read
  // statistics. Its counts belong beside the thing they count, and
  // anything actually wrong belongs on the rail and at the top of the
  // page that owns it.
  { id: "roster", label: "Roster", short: "Roster", icon: "roster" },
  { id: "form", label: "Update form", short: "Form", icon: "form" },
  { id: "print", label: "Print job", short: "Print", icon: "print" },
  { id: "runs", label: "Runs", short: "Runs", icon: "record" },
  { id: "scans", label: "Scans", short: "Scans", icon: "scan" },
  { id: "progress", label: "Progress", short: "Progress",
    icon: "grid" },
  { id: "seating", label: "Seating", short: "Seats", icon: "seating" },
  { id: "setup", label: "Settings", short: "Settings", icon: "setup",
    foot: true },
  // No Cold call tab. It is Seating's Up Next mode: the chart is
  // already on the projector, so picking somebody should light a chair
  // rather than replace the screen with a list of names.
];

// One definition per column, used to build the header AND the cells. They
// used to be two lists that could drift, and did: a rule hid the SID cell on
// a narrow window but not its heading, so every column after it read one
// place to the left.
// `min` and `max` are the column's width in pixels. Content decides the width
// between them: an <input> reports its own default width (about twenty
// characters) whatever it contains, so a column of short values comes out as
// wide as a column of long emails unless the values are measured.
// Minimums measured against the real MAT 106 roster rather than guessed: the
// longest name there is 22 characters (~167px in this font) and the longest
// address 19. A minimum below that clips the common case, which is what the
// first pass did -- it was set from a two-row scratch roster whose longest
// name was "Test Student".
// `sortKeys` lets one column offer more than one order. Name offers surname
// and given name, because the roster holds a single full name -- splitting it
// into two editable columns would put a guessed surname in the file beside
// the name that actually prints, and the two could then disagree. The server
// derives the keys; nothing is stored. See `_sort_names`.
/* `rank` is what survives a squeeze, lowest dropped first. It is not the
 * reading order and it is not width: it is "if only one column could be
 * on screen, which".
 *
 * The thing this gets wrong by default is that **data outranks
 * controls**, because data is what a table looks like it is for. It
 * isn't: Email and SID are reference, and dropping a student is the one
 * thing this tab does. So the actions rank above everything but the
 * name, and `pin` keeps both on screen however far you scroll sideways.
 *
 * `grow` marks the columns that may take spare width when the window is
 * wider than the table needs. A fixed-width Section stretched to 300px
 * is a worse table, not a bigger one.
 */
const COLUMNS = [
  { key: "name",      label: "Name",     edit: true, min: 200, max: 360,
    floor: 150, rank: 1, pin: "left", grow: true,
    // Measured as it is shown, or the column is sized for a string the
    // table is not displaying.
    value: s => displayName(s),
    sortKeys: [["sort_last", "last"], ["sort_first", "first"]] },
  // Not "Nickname": that invites "Matt", and this replaces the whole
  // printed name. Same widths as Name, because it holds the same thing
  // -- when it holds anything; its floor is the heading, because on a
  // roster where nobody has one it was 200px of blank boxes.
  { key: "preferred", label: "Print as", edit: true, min: 200, max: 330,
    floor: 96, rank: 3, grow: true,
    placeholder: s => s.name },
  { key: "section",   label: "Section",  edit: true, min: 74,  max: 110,
    floor: 74, rank: 4 },
  { key: "email",     label: "Email",    edit: true, min: 215, max: 360,
    floor: 150, rank: 5, grow: true },
  { key: "sid",       label: "SID",      cls: "ro",  min: 86,  max: 140,
    floor: 76, rank: 6,
    text: s => s.sid || s.alt_id || "—",
    value: s => s.sid || s.alt_id || "" },
  // Wide enough for a 30px chip plus the cell's own 8px either side,
  // or the button is clipped by `td { overflow: hidden }`.
  { key: "_actions",  label: "",         sortable: false, min: 54, max: 54,
    floor: 54, rank: 2, pin: "right" },
];

let students = [];
let edits = new Map();          // "index:field" -> value
/* Drops waiting for Save, as index -> the state you asked for.
 *
 * Dropping used to write the file the moment you pressed it, which made
 * it the one control on the tab that did not wait for Save -- and the
 * one with the largest consequence, since it empties a seat. It is a
 * pending change like any other now: the student moves to the Dropped
 * band, the save bar comes up, and Discard puts them back. */
let pendingDrops = new Map();

/* What the table should show, which is not always what the file says. */
function isDropped(student) {
  return pendingDrops.has(student.index)
    ? pendingDrops.get(student.index)
    : Boolean(student.dropped);
}

function pendingCount() { return edits.size + pendingDrops.size; }
// Sorts stack, the way a spreadsheet's do: the most recent click is the
// primary key and the ones before it survive as tiebreakers. Sorting by
// surname and then by section gives 820 A-Z, then 830 A-Z.
//
// Index 0 is primary. Four is plenty; beyond that nobody can predict the
// result, and an unbounded stack would quietly keep a key you set minutes
// ago and have forgotten.
const SORT_DEPTH = 4;

// What the table opens on: grouped by section, alphabetical by surname
// within each. That is the order an instructor reads a roster in.
const DEFAULT_SORT = [
  { key: "section", desc: false },
  { key: "sort_last", desc: false },
];

let sorts = DEFAULT_SORT.map(s => ({ ...s }));

// ------------------------------------------------------------------ api --

async function api(path, body) {
  const res = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    headers: { "X-Printit-Token": TOKEN, "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  /* A restarted server has a new token, and this page is holding the
     old one. Every call then fails, the page goes on showing whatever
     it last drew, and the toast saying so fades after nine seconds --
     which is how an afternoon gets spent wondering why a new button is
     missing when the answer is that the script is yesterday's.

     So this one does not fade, and it offers the fix rather than
     describing it. */
  if (res.status === 403) { staleToken(); throw new Error("reload needed"); }
  let payload;
  try { payload = await res.json(); }
  catch { throw new Error(`the server answered ${res.status} with no JSON`); }
  if (!res.ok || payload.error) throw new Error(payload.error || `HTTP ${res.status}`);
  return payload.data;
}

function staleToken() {
  if (document.getElementById("stale")) return;
  const bar = document.createElement("div");
  bar.id = "stale";
  bar.className = "stale";
  bar.append("printit restarted, so this page is out of date — "
             + "nothing here will save until it is reloaded. ");
  const go = document.createElement("button");
  go.type = "button";
  go.className = "primary";
  go.textContent = "Reload";
  go.onclick = () => location.reload();
  bar.appendChild(go);
  document.body.appendChild(bar);
}

let toastTimer = null;
function toast(message, bad) {
  const el = document.getElementById("toast");
  el.textContent = message;
  el.classList.toggle("bad", Boolean(bad));
  el.hidden = false;
  clearTimeout(toastTimer);
  // Errors stay long enough to read; a rule saying no is the useful output.
  toastTimer = setTimeout(() => { el.hidden = true; }, bad ? 9000 : 3000);
}

/* ---- asking, and cross-tab fallout ---------------------------------
 *
 * `ask()` is the app's confirmation. `window.confirm` is browser
 * chrome and the desktop pane suppresses it, so a `<dialog>` does the
 * job instead -- it is an element on the page.
 *
 * Returns a promise for true or false, and never blocks.
 */
function askBox({ title, body, yes, no, value }) {
  /* One dialog, two questions. `value === null` is the yes/no form and
     resolves true/false; anything else shows the field and resolves to
     the text, or null if cancelled -- the same shape `window.prompt`
     had, so a caller reads the same way.

     Both exist because the pane suppresses `confirm` *and* `prompt`,
     and a suppressed one returns falsy without drawing anything. Two
     controls shipped dead that way: Push it, and the Seating tab's
     "how many versions". */
  const box = document.getElementById("ask");
  document.getElementById("ask-title").textContent = title;
  const where = document.getElementById("ask-body");
  where.textContent = "";
  for (const line of [].concat(body || [])) {
    const p = document.createElement("p");
    p.textContent = line;
    where.appendChild(p);
  }
  const field = document.getElementById("ask-input");
  const wants = value !== null;
  field.hidden = !wants;
  if (wants) field.value = String(value);
  const ok = document.getElementById("ask-yes");
  const cancel = document.getElementById("ask-no");
  ok.textContent = yes;
  cancel.textContent = no;
  return new Promise(resolve => {
    const done = (answer) => {
      ok.onclick = cancel.onclick = box.onclose = field.onkeydown = null;
      if (box.open) box.close();
      resolve(answer);
    };
    ok.onclick = () => done(wants ? field.value : true);
    cancel.onclick = () => done(wants ? null : false);
    // Escape closes it, which is a cancel.
    box.onclose = () => done(wants ? null : false);
    if (wants) {
      field.onkeydown = (e) => {
        if (e.key === "Enter") { e.preventDefault(); done(field.value); }
      };
    }
    box.showModal();
    if (wants) { field.focus(); field.select(); }
  });
}

function ask({ title, body, yes = "Go ahead", no = "Cancel" }) {
  return askBox({ title, body, yes, no, value: null });
}

function askFor({ title, body, value = "", yes = "Set", no = "Cancel" }) {
  return askBox({ title, body, yes, no, value });
}

/* Unsaved work held on a tab other than the one being saved.
 *
 * Saving one tab can invalidate another's pending work -- a seating
 * save renumbers the versions a print draft has overrides against --
 * and the only honest moment to say so is before it happens.
 *
 * `saving` is the tab doing the saving, so its own pending work is not
 * reported back to it.
 */
function pendingElsewhere(saving) {
  const held = [];
  const add = (view, label, what) => {
    if (saving !== view && what) held.push(`${label}: ${what}`);
  };
  const n = pendingCount();
  add("roster", "Roster",
      n ? `${n} unsaved change${n === 1 ? "" : "s"}` : "");
  add("print", "Print job", printDirty() ? "an unsaved print job" : "");
  add("form", "Update form",
      skills && skillsDirty() ? "unsaved assessment settings" : "");
  return held;
}

/* Ask before a save knocks over work held elsewhere -- and **only**
 * then. A warning that fires when nothing is at stake is one that gets
 * clicked through without reading. */
async function okDespitePending(saving, consequence) {
  const held = pendingElsewhere(saving);
  if (!held.length) return true;
  return ask({
    title: "Unsaved work on another tab",
    body: [consequence, ...held],
    yes: "Save anyway",
    no: "Go back",
  });
}

// ----------------------------------------------------------------- nav --

/* The rail's icons.

   Its own set, deliberately: `seating.js` has a richer one, and the
   shell must not depend on the sub-app -- Seating is written to be
   liftable out, which it would not be if the chrome imported from it.
   The direction to unify these, when they are unified, is the other
   way round: the shell owns the builder and Seating takes it. */
/* One glyph set for the shell, not one per place that wants a picture.
   It started as the rail's and grew a row action; a second table of
   paths would be the "is there a second copy" failure in picture form.

   `GLYPH`, not `ICON`: seating.js already declares a top-level `ICON`,
   and the two scripts share one global scope, so the second `const` of
   that name is a SyntaxError that stops the *other* file loading. Same
   collision as `.rail` and `.band`, in JavaScript rather than CSS. */
const GLYPH = {
  roster: "M9 11.5a3.6 3.6 0 1 1 0-7.2 3.6 3.6 0 0 1 0 7.2"
    + "M2.5 20c0-3.4 2.9-5.8 6.5-5.8s6.5 2.4 6.5 5.8"
    + "M16.2 4.7a3.6 3.6 0 0 1 0 6.6M17.4 14.6c2.5.6 4.1 2.5 4.1 5.4",
  form: "M9.2 4.2h5.6v2.6H9.2zM7.6 5.4H6.2A1.7 1.7 0 0 0 4.5 7.1v11.4"
    + "A1.7 1.7 0 0 0 6.2 20.2h11.6a1.7 1.7 0 0 0 1.7-1.7V7.1"
    + "a1.7 1.7 0 0 0-1.7-1.7h-1.4M8.4 11.2h7.2M8.4 15.1h4.3",
  print: "M7.2 9.4V4.2h9.6v5.2M7.2 17.8H5.6a1.6 1.6 0 0 1-1.6-1.6v-4.8"
    + "a1.6 1.6 0 0 1 1.6-1.6h12.8a1.6 1.6 0 0 1 1.6 1.6v4.8"
    + "a1.6 1.6 0 0 1-1.6 1.6h-1.6M7.2 14.2h9.6v5.6H7.2z",
  record: "M12 7.4v4.9l3.1 2M3.6 12a8.4 8.4 0 1 0 2.6-6.1M6.2 3.2v2.9H3.3",
  /* Seating's own chair, front on, lifted from `seating.js`. It was
     three rectangles -- the Groups glyph -- which is a picture of one
     mode inside the tab rather than of the tab, and too nondescript to
     read as anything at 21px. */
  seating: [{ r: [7.5, 2.5, 9, 7, 2] },
            { r: [4, 11, 16, 3.2, 1.6] },
            { d: "M7 21v-6.8M17 21v-6.8" }],
  /* A gear. It was two sliders, which is a picture of *adjusting*
     things and read as an equaliser; the tab is where the course is
     set up once. Eight teeth as short radial strokes plus two
     circles, because a toothed outline drawn as one path is unreadable
     at 21px. */
  setup: [{ o: [12, 12, 3.1] }, { o: [12, 12, 6.4] },
          { d: "M12 2.6v2.6M12 18.8v2.6M21.4 12h-2.6M5.2 12H2.6"
               + "M18.6 5.4l-1.8 1.8M7.2 16.8l-1.8 1.8"
               + "M18.6 18.6l-1.8-1.8M7.2 7.2L5.4 5.4" }],
  /* Corner brackets with a line across them -- the reticle every
     scanner app draws. A flatbed, which is the literal object, is a
     shallow box with a lid and reads as a drawer at 21px; this says
     *scanning* rather than *scanner*, and the tab is an action. It
     also happens to be a picture of what the tab does: find a code
     inside a rectangle.

     `record`, the clock, stays with Runs, which is about things that
     already happened. The two tabs had the same glyph. */
  scan: [{ d: "M4 9V6.2A2.2 2.2 0 0 1 6.2 4H9" },
         { d: "M15 4h2.8A2.2 2.2 0 0 1 20 6.2V9" },
         { d: "M20 15v2.8a2.2 2.2 0 0 1-2.2 2.2H15" },
         { d: "M9 20H6.2A2.2 2.2 0 0 1 4 17.8V15" },
         { d: "M3.4 12h17.2" }],
  /* A grid with a tick in the first cell. The conventional picture
     of "progress" is a rising bar chart, which would be a lie about
     what opens: this tab is a table of marks, 45 rows by 29
     columns, and nothing in it is a trend. Two dividers rather than
     a 3x3, because lines every five pixels at 21px is a smudge. */
  grid: [{ r: [3.5, 3.5, 17, 17, 2.2] },
         { d: "M12 3.5v17M3.5 12h17" },
         { d: "M5.9 8.1l1.6 1.7 3-3.3" }],
  collapse: "M14.5 7.5 9.5 12l5 4.5",
  // Points up while a group is open; CSS turns it when it closes.
  chev: "M6 14.5l6-6 6 6",
  // Two ways round, from Seating, where it already means exactly this.
  swapby: "M4 8h13l-3-3M20 16H7l3 3",

  /* A door -- a panel with a knob -- and an arrow going through it to
     drop, coming back out to restore. Only the arrow turns, so the
     pair is one idea with a direction.

     Fourth attempt, and the first chosen by looking rather than by
     reasoning about coordinates. A person with a minus loses the minus
     at 18px, and the minus is the whole meaning. Seating's chair with
     an arrow was too many strokes to read small. A frame plus a
     separate open panel was two disjoint rectangles. Four candidates
     were drawn at 56px and 18px side by side and this one was picked
     off the screen.

     Not a bin, ever: dropping deletes nobody, and it is an unkind
     picture of a person.

     The knob is a zero-length segment, not a circle: `stroke-linecap:
     round` turns it into a dot exactly one stroke-width across, so it
     thickens and thins with every other line instead of thinning away
     at 18px, which a stroked r=0.6 circle did. It sits at the far edge
     of the panel so it never crowds the arrowhead. The arrow stops
     1.4 units past the threshold -- through the doorway, not parked
     in the middle of it. */
  drop: [{ r: [9, 2.5, 12, 19, 1.6] },
         { d: "M18.4 12h0.01" },
         { d: "M2 12h8.2M7.4 8.4l3 3.6-3 3.6" }],
  restore: [{ r: [9, 2.5, 12, 19, 1.6] },
            { d: "M18.4 12h0.01" },
            { d: "M10.2 12H2M5 8.4L2 12l3 3.6" }],
  /* An arrow coming back round to where it started. */
  reset: "M19.4 12a7.4 7.4 0 1 1-2.2-5.3M19.6 4.4v4.2h-4.2",
  back: "M14.5 5.5 8 12l6.5 6.5",
  forward: "M9.5 5.5 16 12l-6.5 6.5",
};

function icon(name) {
  /* A glyph is a path string, or a list of parts. A part is either a
     path (`{d}`) or a rounded rect (`{r: [x, y, w, h, radius]}`),
     because a square drawn as path data is unreadable and a square
     with sharp corners does not belong beside the rest of these. */
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  // Carries its own class, so "these are drawn as strokes, not fills"
  // is stated once. It used to live on `.navrail button svg`, and the
  // first glyph used outside the rail came out as a solid black blob --
  // an SVG path with no `fill: none` is filled, and `currentColor` was
  // never reaching the stroke.
  svg.setAttribute("class", "glyph");
  const spec = GLYPH[name];
  for (const part of (Array.isArray(spec) ? spec : [{ d: spec || "" }])) {
    if (part.o) {
      // A circle, because one drawn as two arcs in path data is
      // unreadable to the next person editing it.
      const [cx, cy, radius] = part.o;
      const c = document.createElementNS(ns, "circle");
      c.setAttribute("cx", cx);
      c.setAttribute("cy", cy);
      c.setAttribute("r", radius);
      svg.appendChild(c);
    } else if (part.r) {
      const [x, y, w, h, radius] = part.r;
      const rect = document.createElementNS(ns, "rect");
      rect.setAttribute("x", x);
      rect.setAttribute("y", y);
      rect.setAttribute("width", w);
      rect.setAttribute("height", h);
      rect.setAttribute("rx", radius);
      svg.appendChild(rect);
    } else {
      const path = document.createElementNS(ns, "path");
      path.setAttribute("d", part.d);
      svg.appendChild(path);
    }
  }
  return svg;
}

/* How a name reads in the first column.
 *
 * A display choice, not a sort: the Name heading already cycles last
 * and first each way, which is four states, and a fifth meaning
 * something else entirely would make the one control answer two
 * questions. It sits with "show dropped" instead -- both are about how
 * this view is drawn rather than about the data.
 *
 * Remembered, like the rail: a statement about how this person reads a
 * roster, not about this visit.
 */
function filedNames() {
  try { return localStorage.getItem("filedNames") === "1"; }
  catch (err) { return false; }
}

function setFiledNames(on) {
  try { localStorage.setItem("filedNames", on ? "1" : "0"); }
  catch (err) { /* a private window still gets a working roster */ }
  renderRoster();
}

/* "Lynott, Kilah", from the server's split and never from one done here.
 *
 * **The split is a guess on most rosters, and it is sometimes wrong.**
 * `_sort_names` says so: the roster carries one full name, because that
 * is what prints; `last` and `first` are empty on every real roster
 * here. From the `First Last` form the splitter guesses, and it gets a
 * compound surname wrong by taking only its last word -- this class has
 * one such student.
 *
 * That guess was deliberately confined to *sorting*, where being wrong
 * puts a row in an odd place, which you can see. Showing it as the name
 * raises the stakes, so: the stored name stays in the cell's tooltip,
 * and the choice is off by default. Making a wrong split correctable is
 * a roster feature, not a display toggle, and is not built.
 */
function displayName(student) {
  const full = student.name || "";
  if (!filedNames()) return full;
  const last = (student.sort_last || student.last || "").trim();
  const first = (student.sort_first || student.first || "").trim();
  if (!last || !first) return full;
  // **The two parts must add up to the whole name, or they are not it.**
  // This class's one compound surname is three words, and the splitter
  // returns one word for the surname and one for the given name -- so
  // the filed form would have dropped a word of a student's name
  // without saying so. A sort put in an odd place is recoverable; a name
  // shown wrong in front of the class is not. When the parts do not
  // reconstruct the name, the name is what gets shown.
  const asWords = s => s.toLowerCase().split(/\s+/).filter(Boolean).sort();
  const parts = asWords(`${last} ${first}`);
  const whole = asWords(full);
  if (parts.length !== whole.length
      || parts.some((w, i) => w !== whole[i])) return full;
  return `${last}, ${first}`;
}

/* Collapsed is remembered, because it is a statement about this
   screen rather than about this visit. */
function railCollapsed() {
  try { return localStorage.getItem("railCollapsed") === "1"; }
  catch (err) { return false; }
}

/* The rail is narrow for two unrelated reasons -- you folded it, or the
 * window is too small for it -- and they used to be decided in two
 * places: a class for the first, a CSS media query for the second.
 * Anything keyed to only one of them was right half the time. The
 * unsaved dot was: it moved to the glyph's corner when the rail was
 * folded by hand and stayed on the row's edge when the window did it.
 *
 * So JavaScript owns the question. The media query is read here rather
 * than acted on in the stylesheet, and `tight` / `body.railtight` are
 * the one answer everything else keys to.
 */
const NARROW_RAIL = window.matchMedia("(max-width: 900px)");

function railIsTight() { return railCollapsed() || NARROW_RAIL.matches; }

function applyRail() {
  const tight = railIsTight();
  document.getElementById("navrail").classList.toggle("tight", tight);
  // The save bar is fixed and has to start where the rail ends, and it
  // is not inside the rail to read the class from there.
  document.body.classList.toggle("railtight", tight);
}

function setRailCollapsed(on) {
  try { localStorage.setItem("railCollapsed", on ? "1" : "0"); }
  catch (err) { /* a private window still gets a working rail */ }
  applyRail();
}

function buildNav() {
  const rail = document.getElementById("navrail");
  rail.textContent = "";
  applyRail();

  /* The course, where the product name used to be. A tool is opened
     to work on one course and the name of the program is the least
     useful thing on screen; the mark keeps it identifiable. */
  const brand = document.createElement("div");
  brand.className = "brand";
  const mark = document.createElement("span");
  mark.className = "mark";
  mark.title = "checkit-printit";
  const who = document.createElement("span");
  who.className = "who";
  who.id = "course-name";
  who.textContent = "loading\u2026";
  brand.append(mark, who);
  rail.appendChild(brand);

  const list = document.createElement("nav");
  list.id = "views";
  const foot = document.createElement("nav");
  foot.className = "railfoot";

  for (const view of VIEWS) {
    const b = document.createElement("button");
    b.type = "button";
    b.appendChild(icon(view.icon));
    const label = document.createElement("span");
    label.className = "label";
    label.textContent = view.label;
    b.appendChild(label);
    // The title is the whole label, so a collapsed rail is never the
    // only place a name exists.
    b.title = view.label;
    if (view.soon) b.classList.add("soon");
    b.onclick = () => show(view.id);
    b.dataset.view = view.id;
    (view.foot ? foot : list).appendChild(b);
  }

  const toggle = document.createElement("button");
  toggle.type = "button";
  toggle.className = "railtoggle";
  toggle.appendChild(icon("collapse"));
  const tlabel = document.createElement("span");
  tlabel.className = "label";
  tlabel.textContent = "Collapse";
  toggle.appendChild(tlabel);
  toggle.title = "Narrow the rail to icons";
  toggle.onclick = () => setRailCollapsed(
    !document.getElementById("navrail").classList.contains("tight"));
  foot.appendChild(toggle);

  rail.append(list, foot);
}

/* Which view `show` last drew. Only `hashchange` reads it, and only to
   ignore the hash `show` just wrote itself: setting `location.hash`
   fires `hashchange`, which called `show` again -- so **every tab
   switch ran its loader twice**. Two `/api/setup` calls for one click
   on Setup, two renders of a 45-row table for one click on Roster.
   Back and forward still work: those change the hash to something this
   is not already showing. */
let shownView = null;

function show(id) {
  const view = VIEWS.find(v => v.id === id);
  for (const b of document.querySelectorAll("nav button")) {
    if (b.dataset.view === id) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  }
  for (const s of document.querySelectorAll(".view")) s.hidden = true;
  // A tab whose job is one long table gives the table the window and
  // scrolls inside it, instead of making the page 2158px tall and
  // parking the horizontal scrollbar below the fold. Set before the
  // branch below, which returns early for a not-yet-built tab and would
  // have left the class on from the previous view.
  document.body.classList.toggle("tall", id === "roster");
  if (view.soon) {
    document.getElementById("soon-title").textContent = view.label;
    document.getElementById("soon-body").textContent = view.soon;
    document.getElementById("view-soon").hidden = false;
  } else {
    document.getElementById("view-" + id).hidden = false;
    // Column widths depend on how much room there is, and there is none
    // to measure until the tab is on screen.
    if (id === "roster" && students.length) renderRoster();
    // Fetching starts at boot; *drawing* happens the first time the tab
    // is opened. The two were one thing when the condition was `skills
    // === null`, and prefetching made that condition false before the
    // tab had ever been drawn, so it came up empty.
    if (id === "form" && !skillsDrawn) loadSkills();
    // Reloaded every time, not only the first. It used to load once, so a
    // name edited in Roster and saved never reached this table until the
    // print job itself was saved -- which read as the table being stale.
    if (id === "print") loadPrint();
    if (id === "setup") loadSetup();
    if (id === "scans") scanSetup();
    if (id === "seating") loadSeating();
    // Every visit, like Print: a build made since the last look is the
    // whole reason to open this tab.
    if (id === "runs") loadRuns();
    // Every visit: a stack saved in Scans is the reason to look.
    if (id === "progress") loadProgress();
  }
  shownView = id;
  location.hash = id;
}

// ------------------------------------------------------------- progress --

let progressData = null;
/* Kept in the browser, not the course: whether the highlight is on is
   a preference of the person looking, not a fact about the class, and
   two people reading the same course should not fight over it. */
let lightRecent = false;

async function loadProgress() {
  const out = await api("/api/progress", {});
  if (!out) return;
  progressData = out;
  renderProgress();
}

/* What one cell is, from what the record says about it.

   Returned rather than drawn, so the rules are in one readable place
   and the drawing below is only ever "put this mark in that box".
   `kind` drives the styling; `mark` and `count` are what is shown. */
function cellState(cell, threshold) {
  if (!cell || !cell.attempts) return { kind: "none" };
  const passed = cell.passes >= threshold;
  const state = {
    kind: passed ? "passed" : "open",
    // A query is still a "?" he has to come back to. It reads as not
    // passed -- which it is -- and carries a corner mark so the fact
    // that he flagged it does not vanish into the same box as an
    // ordinary blank.
    queried: Boolean(cell.queries),
    // Nothing was ever handed in. Not a seventh state -- it is still
    // not passed and still ends in "offer it again" -- but the box
    // drawn is a box on a paper, and there was no paper.
    unsat: cell.attempts > 0 && cell.absents === cell.attempts,
    attempts: cell.attempts,
    passes: cell.passes,
  };
  if (passed) {
    // Only where more than one check is needed. Where one passes a
    // skill, "1 of 1" is the word "passed" written twice.
    if (threshold > 1) state.count = `${cell.passes}/${threshold}`;
    // Passed first time needs no number.
    else if (cell.attempts > 1) state.count = String(cell.attempts);
    return state;
  }
  if (cell.passes) {
    // Part way: two needed, one so far. Its own state, because it is
    // neither "nothing yet" nor "failing".
    state.kind = "part";
    state.count = `${cell.passes}/${threshold}`;
    return state;
  }
  // Not passed. One attempt is ordinary; several is the loudest
  // thing on the page, and the count is why.
  if (cell.attempts > 1) {
    state.kind = "stuck";
    state.count = String(cell.attempts);
  }
  return state;
}

function renderProgress() {
  const data = progressData;
  const grid = document.getElementById("progress-grid");
  const any = Object.keys(data.cells).length > 0;
  document.getElementById("progress-empty").hidden = any;
  document.getElementById("progress-body").hidden = !any;
  document.getElementById("progress-count").textContent = any
    ? `${data.students.length} students, ${data.skills.length} skills`
    : "";
  if (!any) return;

  const recent = new Set(data.recent || []);
  const note = document.getElementById("progress-recent-note");
  note.textContent = recent.size
    ? (recent.size === 1 ? "the last grading set"
                         : `the last ${recent.size} grading sets`)
    : "nothing graded yet";
  document.getElementById("progress-recent").checked = lightRecent;

  grid.innerHTML = "";
  const thead = document.createElement("thead");
  const head = document.createElement("tr");
  const corner = document.createElement("th");
  corner.className = "who";
  corner.textContent = "Name";
  head.appendChild(corner);
  for (const skill of data.skills) {
    const th = document.createElement("th");
    th.className = "skillcol";
    th.textContent = skill.slug;
    // The slug is what is printed on the paper and what he says out
    // loud; the title is the sentence, and 29 sentences across the
    // top is a wall. So the slug shows and the title is the tooltip.
    th.title = skill.threshold > 1
      ? `${skill.title} \u2014 needs ${skill.threshold} passes`
      : skill.title;
    head.appendChild(th);
  }
  thead.appendChild(head);
  grid.appendChild(thead);

  const body = document.createElement("tbody");
  for (const student of data.students) {
    const tr = document.createElement("tr");
    const name = document.createElement("th");
    name.className = "who";
    name.scope = "row";
    name.textContent = student.name || student.sid;
    tr.appendChild(name);
    const mine = data.cells[student.sid] || {};
    for (const skill of data.skills) {
      tr.appendChild(progressCell(student, skill, mine[skill.slug], recent));
    }
    body.appendChild(tr);
  }
  grid.appendChild(body);
}

function progressCell(student, skill, cell, recent) {
  const td = document.createElement("td");
  const state = cellState(cell, skill.threshold);
  td.className = "cell " + state.kind;
  if (state.queried) td.classList.add("queried");
  if (state.unsat) td.classList.add("unsat");
  if (lightRecent && cell && cell.passedIn && recent.has(cell.passedIn)) {
    td.classList.add("justin");
  }
  if (state.kind !== "none") {
    const mark = document.createElement("span");
    mark.className = "cellmark";
    // A tick for passed, an outlined box for not. Drawn as text
    // rather than SVG: 1,300 inline SVGs is a slow page, and the
    // shape is carried by CSS on `.cell` anyway.
    mark.textContent = state.kind === "passed" ? "\u2713" : "";
    td.appendChild(mark);
    if (state.count) {
      const n = document.createElement("span");
      n.className = "cellcount";
      n.textContent = state.count;
      td.appendChild(n);
    }
    td.title = describeCell(student, skill, cell, state);
  }
  // Every cell opens, taken or not: a skill he never offered this
  // student still has runs it could be recorded against, and an
  // empty cell is the most likely one to need filling in by hand.
  td.tabIndex = 0;
  td.setAttribute("role", "button");
  td.onclick = () => openCell(student, skill);
  td.onkeydown = (e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      openCell(student, skill);
    }
  };
  return td;
}

// --------------------------------------------------------- the drill-in --

let cellOpen = null;

async function openCell(student, skill) {
  cellOpen = { student, skill };
  const box = document.getElementById("cell");
  document.getElementById("cell-title").textContent =
    `${student.name || student.sid} \u2014 ${skill.slug}`;
  document.getElementById("cell-sub").textContent = skill.threshold > 1
    ? `${skill.title} \u2014 needs ${skill.threshold} passes`
    : skill.title;
  document.getElementById("cell-papers").textContent = "";
  document.getElementById("cell-none").hidden = true;
  if (!box.open) box.showModal();
  await drawCell();
}

async function drawCell() {
  const { student, skill } = cellOpen;
  const out = await api("/api/progress/cell",
                        { sid: student.sid, slug: skill.slug });
  if (!out || !cellOpen) return;
  const list = document.getElementById("cell-papers");
  list.textContent = "";
  const none = document.getElementById("cell-none");
  none.hidden = out.papers.length > 0;
  if (!out.papers.length) {
    // Not "no results": there is nothing to have a result about,
    // and the fix is a print job, not this dialog.
    none.textContent = `${skill.slug} has never been printed for `
      + `${student.name || student.sid}, so there is nothing to record `
      + `yet. Put it in a print job first.`;
    return;
  }
  for (const paper of out.papers) list.appendChild(cellPaper(paper));
}

function cellPaper(paper) {
  const row = document.createElement("div");
  row.className = "cellpaper";

  const when = document.createElement("div");
  when.className = "cellwhen";
  const date = document.createElement("div");
  // The app's own date wording, which is the wording on the
  // confirmation the student ticked.
  date.textContent = spokenDay(paper.date) || paper.date;
  const what = document.createElement("div");
  what.className = "muted";
  // The seed is how this exact paper is found again -- it is what
  // `--seed` takes and what the manifest pins. Worth the room.
  what.textContent = `${paper.title}, version ${paper.version}, `
    + `seed ${paper.seed}`;
  when.append(date, what);

  const said = document.createElement("div");
  said.className = "muted cellread";
  if (paper.reading) {
    said.textContent = `scanner read it as ${paper.reading}`;
  } else if (paper.outcome) {
    said.textContent = "recorded by hand";
  } else {
    said.textContent = "never scanned";
  }

  const picks = document.createElement("div");
  picks.className = "review-picks";
  picks.setAttribute("role", "radiogroup");
  for (const outcome of OUTCOME_LIST) {
    const b = document.createElement("button");
    b.type = "button";
    b.className = "review-pick";
    b.textContent = outcome.label;
    b.title = outcome.mark;
    b.setAttribute("role", "radio");
    const on = paper.outcome === outcome.id;
    b.classList.toggle("on", on);
    b.setAttribute("aria-checked", on ? "true" : "false");
    b.onclick = () => setCellOutcome(paper.runId, outcome.id);
    picks.appendChild(b);
  }

  row.append(when, said, picks);
  return row;
}

async function setCellOutcome(runId, outcome) {
  const { student, skill } = cellOpen;
  const out = await api("/api/progress/set", {
    runId, sid: student.sid, slug: skill.slug, outcome });
  if (!out) return;
  // Saved as it is clicked. There is no draft here -- one click is
  // one decision about one paper -- and a Save button would be a
  // second state to get wrong.
  const list = document.getElementById("cell-papers");
  list.textContent = "";
  for (const paper of out.papers) list.appendChild(cellPaper(paper));
  toast("Saved.");
  // The grid behind is now wrong. Redrawn rather than patched: the
  // cell's state depends on counts, thresholds and which run the
  // pass came from, and three of those are the server's answer.
  await loadProgress();
}

/* The four outcomes, as the review grid gets them from the server.
   Held here as well so the drill-in can be opened without a scan in
   hand -- which is the whole point of it. */
const OUTCOME_LIST = [
  { id: "passed", label: "Passed", mark: "a tick" },
  { id: "queried", label: "Query", mark: "a ? beside the box" },
  { id: "failed", label: "Not passed", mark: "an empty box" },
  { id: "absent", label: "Did not sit it", mark: "no paper" },
];

/* The sentence a cell says when you point at it. Written out in full
   because the grid itself is deliberately almost wordless, and the
   one place to recover what a mark means is here. */
function describeCell(student, skill, cell, state) {
  const who = student.name || student.sid;
  const tries = cell.attempts === 1 ? "1 attempt"
                                    : `${cell.attempts} attempts`;
  // "Not passed, 1 attempt" about somebody who never saw the paper
  // is a false sentence, and the tooltip is the one place a cell
  // explains itself.
  if (state.unsat) {
    return cell.attempts === 1
      ? `${who}, ${skill.slug}: did not sit it`
      : `${who}, ${skill.slug}: did not sit it, ${cell.attempts} times`;
  }
  let said;
  if (state.kind === "passed") said = "passed";
  else if (state.kind === "part") {
    said = `${cell.passes} of ${skill.threshold} passes so far`;
  } else said = "not passed";
  const q = cell.queries ? ", one marked with a query" : "";
  const a = cell.absents ? `, ${cell.absents} not sat` : "";
  return `${who}, ${skill.slug}: ${said} \u2014 ${tries}${q}${a}`;
}

// ------------------------------------------------------------- overview --

/* The course's name, for the one or two places that need to say it in
   a sentence -- the Roster's empty state puts it in the `-c` flag of
   the command it offers. */
let courseName = "";

function renderOverview(summary) {
  /* The name alone. "MAT 106 - 45 active of 45" is three facts run
     together with a dash, which is the tic section 13.4 bans, and in a
     188px rail it truncated to "MAT 106 - 45 activ...". The counts are
     on the Roster, beside the people they count.

     Everything else this function did drew the Overview's eight cards.
     That tab went in stage 2, and the code stayed behind a
     `const cards = null; if (!cards) return;` -- thirteen unreachable
     lines, which is how a reader learns to distrust the file. */
  courseName = summary.name || "";
  document.getElementById("course-name").textContent = courseName;
}

// --------------------------------------------------------------- roster --

function key(index, field) { return index + ":" + field; }

/* One save bar per tab, and it is not on screen when there is nothing
 * to save.
 *
 * Four tabs had grown three arrangements of the same two buttons: the
 * Roster's in its toolbar, the Update form's inside one section (which
 * said they belonged to that section, and they did not -- the same save
 * writes the assessment fields above), Setup's with no Discard at all,
 * and the Print tab's in a bar that was always there, including when
 * both its buttons were disabled.
 *
 * A bar that appears only when dirty is the placement that was chosen,
 * and a disabled Save is a control that cannot say why it is disabled.
 * So the bar is absent instead.
 */
function saveBar(view, dirty, what) {
  const bar = document.getElementById(view + "-bar");
  bar.hidden = !dirty;
  bar.querySelector(".dirty").textContent = dirty ? what : "";
  /* The bar is on one tab; the fact belongs to the app. A bar that
     hides itself when clean also hides itself when you have stepped
     over to another tab, so the rail carries a dot for every
     destination holding something unsaved. */
  const tab = document.querySelector(`.navrail button[data-view="${view}"]`);
  if (tab) tab.classList.toggle("unsaved", dirty);
  // The bar is fixed to the bottom of the window, so the page has to
  // pay for the space it covers -- otherwise it sits on the last row
  // of whatever is open.
  document.body.classList.toggle(
    "hasbar", Boolean(document.querySelector(".savebar:not([hidden])")));
}

function refreshDirty() {
  const n = pendingCount();
  saveBar("roster", n > 0,
          n === 1 ? "1 unsaved change" : `${n} unsaved changes`);
}

/* "Lynott, Kilah" back into "Kilah Lynott".
 *
 * The comma is the whole specification, and it has to be exactly one:
 * without it there is no way to know where the surname stops, and with
 * two there is no way to know which half is which. A name is not
 * guessable -- that is the lesson of the one compound surname on this
 * roster -- so the rule is stated to the typist rather than inferred
 * from what they typed.
 *
 * Returns null when the text is not a filed name, which the caller
 * shows as an invalid cell rather than saving a wrong name.
 */
function unfileName(text) {
  const parts = String(text).split(",");
  if (parts.length !== 2) return null;
  const last = parts[0].trim();
  const first = parts[1].trim();
  if (!last || !first) return null;
  return `${first} ${last}`;
}

function cellInput(student, field, column) {
  const input = document.createElement("input");
  // The Name cell shows what the column is showing. It is editable in
  // either order: read-only was the first answer and the wrong one,
  // since the roster is the one place a name gets corrected.
  const filed = field === "name" && filedNames();
  input.value = filed ? displayName(student) : (student[field] || "");
  input.spellcheck = false;
  if (filed) input.title = "Surname, then given name, separated by one comma.";
  // An empty "Print as" is not missing data -- it means the roster name is
  // used -- so the box shows that name greyed rather than sitting blank.
  if (column && column.placeholder) input.placeholder = column.placeholder(student);
  input.oninput = () => {
    const k = key(student.index, field);
    const stored = filed ? unfileName(input.value) : input.value;
    input.classList.toggle("invalid", filed && stored === null);
    if (stored === null) {
      // Half-typed is not an edit to save. The cell says so and the
      // save bar does not offer to write it.
      edits.delete(k);
    } else if (stored === (student[field] || "")) {
      edits.delete(k);
    } else {
      edits.set(k, stored);
    }
    input.classList.toggle("changed", edits.has(k));
    refreshDirty();
  };
  return input;
}

function sortValue(key, column, student) {
  // `key` may be a derived one the column offers (sort_last, sort_first)
  // rather than the field the column displays.
  if (key !== column.key && key in student) return String(student[key]).toLowerCase();
  const raw = column.value ? column.value(student) : (student[column.key] || "");
  return String(raw).toLowerCase();
}

function cycleOf(column) {
  /* Every (key, direction) this heading steps through, in order. */
  const keys = column.sortKeys || [[column.key, null]];
  const out = [];
  for (const [key, note] of keys) out.push([key, false, note], [key, true, note]);
  return out;
}

function columnOwning(key) {
  return COLUMNS.find(c => c.key === key)
    || COLUMNS.find(c => (c.sortKeys || []).some(([k]) => k === key));
}

function rankOf(key) {
  const at = sorts.findIndex(s => s.key === key);
  return at < 0 ? null : at + 1;
}

function sortBy(column) {
  const cycle = cycleOf(column);
  const primary = sorts[0];
  const isPrimary = primary && cycle.some(([k]) => k === primary.key);

  let key, desc;
  if (isPrimary) {
    // Already the primary key, so step this heading's own cycle: ascending,
    // descending, and for Name on to the given-name order.
    const at = cycle.findIndex(([k, d]) => k === primary.key && d === primary.desc);
    [key, desc] = cycle[(at + 1) % cycle.length];
  } else {
    // A new primary. Everything already in the stack drops one place and
    // keeps working as a tiebreaker.
    [key, desc] = cycle[0];
  }

  // One entry per key: re-sorting by section must not leave an older section
  // entry further down, where it would do nothing but take up a slot.
  const owned = new Set(cycle.map(([k]) => k));
  sorts = [{ key, desc },
           ...sorts.filter(s => !owned.has(s.key))].slice(0, SORT_DEPTH);
  renderRoster();
}

function clearSort() {
  sorts = DEFAULT_SORT.map(s => ({ ...s }));
  renderRoster();
}

// Text measurement, for sizing columns to what is actually in them.
let ruler = null;
function textWidth(text, font) {
  if (!ruler) ruler = document.createElement("canvas").getContext("2d");
  ruler.font = font;
  return ruler.measureText(String(text)).width;
}

const CELL_PADDING = 16 + 14;   // td padding, plus the input's own border/pad

function sizeColumns(rows) {
  const table = document.getElementById("roster");
  const probe = table.querySelector("tbody td") || table.querySelector("th");
  if (!probe) return;
  const style = getComputedStyle(probe);
  const bodyFont = `${style.fontSize} ${style.fontFamily}`;
  const headStyle = getComputedStyle(table.querySelector("th"));
  // Headings are smaller but letter-spaced and upper-cased, so they are
  // measured with their own font and a little slack for the sort arrow.
  const headFont = `${headStyle.fontWeight} ${headStyle.fontSize} ${headStyle.fontFamily}`;

  let group = table.querySelector("colgroup");
  if (group) group.remove();
  group = document.createElement("colgroup");

  // A column holding nothing needs room for its heading and no more.
  // `Print as` is empty for every student on this roster and was
  // reserving 200px -- a fifth of the table -- to display nothing, while
  // Email was clipped and the drop button was off the right-hand edge.
  // So `min` is the comfortable width for a column *with* content, and
  // `floor` is what it may be squeezed to; an empty column starts at its
  // floor rather than being padded up to a width it has no use for.
  const heads = COLUMNS.map(c => textWidth(c.label.toUpperCase(), headFont) + 18);
  const floors = COLUMNS.map((c, i) => Math.max(heads[i], c.floor ?? c.min));

  const want = COLUMNS.map((column, i) => {
    let widest = heads[i];
    let anyContent = false;
    for (const student of rows) {
      const value = column.value ? column.value(student)
                  : column.text ? column.text(student)
                  : (student[column.key] || "");
      if (value) anyContent = true;
      widest = Math.max(widest, textWidth(value, bodyFont) + CELL_PADDING);
    }
    const low = anyContent ? Math.max(column.min, floors[i]) : floors[i];
    return Math.round(Math.min(column.max, Math.max(low, widest)));
  });

  // A hidden view measures zero, and zero is not a narrow window. Sized
  // at boot while the tab was still hidden, every column came out at its
  // floor and stayed there once the tab was shown -- 594px of table in a
  // 704px scroller, which is the ragged right edge this pass set out to
  // fix. `show()` re-renders on reveal; this is the belt.
  const room = table.parentElement.clientWidth;
  let gap = room > 0 ? room - want.reduce((a, b) => a + b, 0) : 0;

  if (gap > 0) {
    // **Spare room goes into the table, not beside it.** A 1100px header
    // with an 867px table under it looked like the table had failed to
    // load. Only `grow` columns take it: stretching Section to 300px
    // makes a worse table, not a bigger one.
    const growers = COLUMNS.map((c, i) => i).filter(i => COLUMNS[i].grow);
    for (let pass = 0; pass < 3 && gap > 0; pass += 1) {
      const room_left = growers.filter(i => want[i] < COLUMNS[i].max);
      if (!room_left.length) break;
      const each = Math.floor(gap / room_left.length) || 1;
      for (const i of room_left) {
        if (gap <= 0) break;
        const give = Math.min(each, COLUMNS[i].max - want[i], gap);
        want[i] += give;
        gap -= give;
      }
    }
    // Everything is at its max and there is still room. Rather than
    // leave a ragged right edge, the last growing column takes the rest,
    // so the table's edge lines up with the heading above it.
    if (gap > 0 && growers.length) want[growers[growers.length - 1]] += gap;
  } else if (gap < 0) {
    // **Shrink to fit before deciding to scroll.** The content widths
    // came to 884px in an 875px scroller, so a scrollbar ran the width
    // of the roster and moved it nine pixels -- which reads as broken
    // rather than as "there is more to the right".
    //
    // Widest slack first: nine pixels off an email is invisible, off
    // Section it is a third of the column. Down to `floor` and no
    // further; past that the table genuinely does not fit and scrolls,
    // which is survivable now that Name and the actions are pinned.
    let excess = -gap;
    const order = want
      .map((px, i) => ({ i, slack: px - floors[i] }))
      .filter(c => c.slack > 0)
      .sort((a, b) => b.slack - a.slack);
    for (const c of order) {
      if (excess <= 0) break;
      const give = Math.min(c.slack, excess);
      want[c.i] -= give;
      excess -= give;
    }
  }

  let total = 0;
  for (let i = 0; i < COLUMNS.length; i += 1) {
    const col = document.createElement("col");
    col.style.width = want[i] + "px";
    total += want[i];
    group.appendChild(col);
  }
  table.insertBefore(group, table.firstChild);
  // Without this the widths are only proportions. A `table-layout: fixed`
  // table cannot be wider than its container, so in a narrow window the
  // browser squashes every column to fit -- 814px of columns became 482 --
  // and the scroller has nothing to scroll because the table never
  // overflows. Setting the sum as a floor is what makes it overflow, and
  // therefore what makes the scrollbar appear.
  table.style.minWidth = total + "px";
}

function renderHeader() {
  const row = document.querySelector("#roster thead tr");
  row.textContent = "";
  for (const column of COLUMNS) {
    const th = document.createElement("th");
    if (column.sortable === false) {
      // The one unsortable heading is empty, so the reset lives there --
      // over the column it belongs beside, rather than in the toolbar where
      // it sat next to controls it has nothing to do with. Right-aligned so
      // it does not read as a heading for the drop links beneath it.
      th.className = "actions-head pinright";
      const reset = document.createElement("button");
      // `tiny`, matching the name-format switch in the Name heading:
      // two controls in the same header row, so they are the same size.
      reset.className = "iconbtn tiny undo";
      reset.id = "reset-sort";
      reset.appendChild(icon("reset"));
      reset.title = "Back to section, then surname.";
      reset.setAttribute("aria-label", reset.title);
      reset.hidden = isDefaultSort();
      reset.onclick = clearSort;
      th.appendChild(reset);
      row.appendChild(th);
      continue;
    }
    const cycle = cycleOf(column);
    const entry = sorts.find(s => cycle.some(([k]) => k === s.key));
    const note = entry && (cycle.find(([k]) => k === entry.key) || [])[2];
    const rank = entry ? rankOf(entry.key) : null;

    if (column.pin) th.classList.add("pin" + column.pin);
    /* The name format lives in the Name heading, not in a box above the
       table. It is a property of this column, so it belongs on it --
       and a segmented pair floating in a toolbar was, in the
       instructor's words, butt ugly.

       Seating's "two ways round" arrows, because that is exactly what
       it does and the glyph already means that elsewhere. */
    if (column.key === "name") {
      const swap = document.createElement("button");
      swap.className = "iconbtn tiny namefmt";
      swap.type = "button";
      swap.appendChild(icon("swapby"));
      swap.title = filedNames()
        ? "Showing surname first. Switch to First Last."
        : "Showing given name first. Switch to Last, First.";
      swap.setAttribute("aria-label", swap.title);
      swap.onclick = (e) => { e.stopPropagation(); setFiledNames(!filedNames()); };
      th.appendChild(swap);
    }
    const b = document.createElement("button");
    b.className = "sort";
    // A column with two orders has to say which one it is on: "Name" alone
    // would not tell you whether it sorted by surname or given name. The
    // rank appears only when more than one key is in play, because a lone
    // "1" would be noise.
    // The note names the key rather than being bolted on with a dot:
    // "LAST NAME" says the same thing as "NAME · LAST" in the same room
    // and without the separator this codebase keeps reaching for.
    b.textContent = (note ? note + " " + column.label.toLowerCase()
                          : column.label)
      + (entry ? (entry.desc ? " ↓" : " ↑") : "")
      + (entry && sorts.length > 1 ? " " + rank : "");
    if (entry) b.classList.add("sorted");
    if (rank === 1) b.classList.add("primary-sort");
    // Per state, not one string for all of them: the primary column was
    // being told it was a tiebreaker.
    b.title = (rank === 1 ? "Primary sort column."
             : rank ? `Tier ${rank} tiebreaker.`
             : "Sort by this column.")
      + (column.sortKeys ? " Cycles last and first name, each way." : "");
    b.onclick = () => sortBy(column);
    th.appendChild(b);
    row.appendChild(th);
  }
}

function isDefaultSort() {
  return sorts.length === DEFAULT_SORT.length
    && sorts.every((s, i) => s.key === DEFAULT_SORT[i].key
                          && s.desc === DEFAULT_SORT[i].desc);
}

/* The Roster with nothing in it, or nothing left after a filter.
 *
 * Three states and three different ways out, which is the point of
 * writing them separately: "this roster is empty" told the reader a
 * thing the blank screen had already said.
 *
 * Importing is still a command rather than a button, so the command is
 * what it offers -- with the course name already in it, because the
 * `-c` flag is the part people get wrong. When the class-list import
 * becomes a screen (see section 14.6 -- the LMS id arrives the same
 * way), this becomes a button and the command goes.
 */
function renderRosterEmpty(hasRows) {
  const box = document.getElementById("roster-empty");
  box.hidden = hasRows;
  box.textContent = "";
  if (hasRows) return;
  box.className = "emptystate";

  const lead = document.createElement("strong");
  lead.className = "lead";
  const say = (text) => box.appendChild(document.createTextNode(text));

  if (!students.length) {
    lead.textContent = "No students yet";
    box.append(lead);
    say("A class list from the registrar or the LMS fills this in. ");
    const cmd = document.createElement("code");
    cmd.textContent =
      `checkit-printit roster import -c "${courseName || "<course>"}" `
      + `classlist.csv`;
    box.appendChild(cmd);
    return;
  }

  lead.textContent = "Everyone here is dropped";
  box.append(lead);
  say("Nothing will print. ");
  const show = document.createElement("button");
  show.className = "act";
  show.textContent = "Open the dropped list";
  show.onclick = () => { shutBands.delete(DROPPED_BAND); renderRoster(); };
  box.appendChild(show);
}

/* Runs of one section, in the order the rows are already in.
 *
 * `45 students - 22 in 820 - 23 in 830` is the banned shape, and the
 * reason it was reached for is that no layout existed for the facts. The
 * layout is this: a section's count belongs beside that section's rows,
 * so each run of rows gets a band carrying its name and its size, and
 * only the whole-table total stays in the page header.
 *
 * Returns null when the rows are not grouped by section -- sorted by
 * email, 820 and 830 interleave, and a band every few rows would be
 * noise rather than structure. Tested on the sorted rows themselves
 * rather than on `sorts[0].key`, so it stays right for a descending
 * section sort, for one section, and for a sort that happens to group
 * them anyway.
 */
/* Sorting only reorders what is displayed. Edits are keyed to each
   student's own index, not to a row position, so they survive it.
   Applied to each group separately -- see `renderRoster`. */
function sortRoster(rows) {
  if (!sorts.length) return rows;
  const keys = sorts
    .map(s => ({ ...s, column: columnOwning(s.key) }))
    .filter(s => s.column);
  if (!keys.length) return rows;
  return [...rows].sort((a, b) => {
    for (const { key, desc, column } of keys) {
      const cmp = sortValue(key, column, a).localeCompare(
        sortValue(key, column, b), undefined, { numeric: true });
      if (cmp) return desc ? -cmp : cmp;
    }
    return 0;
  });
}

/* Which bands are shut. Dropped starts shut, because it is a list of
   people who are not in the class any more and it should not be the
   first thing the roster shows. */
const DROPPED_BAND = "\u0000dropped";
let shutBands = new Set([DROPPED_BAND]);

function bandShut(key) { return shutBands.has(key); }

function toggleBand(key) {
  if (shutBands.has(key)) shutBands.delete(key);
  else shutBands.add(key);
  renderRoster();
}

function sectionRuns(rows) {
  if (!rows.length) return null;
  const runs = [];
  for (const student of rows) {
    const name = student.section || "";
    const last = runs[runs.length - 1];
    if (last && last.section === name) last.count += 1;
    else runs.push({ section: name, key: "section:" + name, count: 1,
                     start: runs.reduce((a, r) => a + r.count, 0) });
  }
  // One run is the whole table, so the band would say what the header
  // already says. A section appearing twice means the rows are not
  // grouped, and the bands would be lying about structure.
  const names = runs.map(r => r.section);
  if (runs.length < 2 || new Set(names).size !== names.length) return null;
  return runs;
}

/* A band: the whole row is the control that opens and shuts its group.
 *
 * The count used to be a floated span, which put it above the name's
 * baseline. The row is a flex line now, so the two sit on one.
 */
function sectionBand(run) {
  const tr = document.createElement("tr");
  // `secband`, not `band`: seating.css owns `.band` for its selection
  // rectangle, and `position: absolute` on a <tr> drops it out of the table.
  tr.className = "secband";
  const td = document.createElement("td");
  td.colSpan = COLUMNS.length;

  const shut = bandShut(run.key);
  const button = document.createElement("button");
  button.className = "bandtoggle";
  button.type = "button";
  button.setAttribute("aria-expanded", String(!shut));
  button.appendChild(icon("chev"));

  const name = document.createElement("span");
  name.className = "secband-name";
  name.textContent = run.section || "no section";

  const count = document.createElement("span");
  count.className = "secband-count";
  // "22 students", not "22": the bare number was ambiguous against a
  // table whose other numbers are ids and seeds.
  count.textContent = `${run.count} student${run.count === 1 ? "" : "s"}`;

  button.append(name, count);
  button.onclick = () => toggleBand(run.key);
  if (shut) tr.classList.add("shut");
  td.appendChild(button);
  tr.appendChild(td);
  return tr;
}

function renderRoster() {
  renderHeader();
  const body = document.querySelector("#roster tbody");
  body.textContent = "";

  /* **Two groups, and a sort never mixes them.** Dropped students are
     not part of the class any more, so they do not belong interleaved
     with it however the table is sorted -- they are their own band at
     the bottom, sorted inside itself by the same keys. That replaced
     the "show dropped students" tick, which could only hide them or
     scatter them through everyone else. */
  const active = sortRoster(students.filter(s => !isDropped(s)));
  const dropped = sortRoster(students.filter(s => isDropped(s)));

  const runs = sectionRuns(active) || [];
  let runAt = 0;
  let shutNow = false;

  const rows = [];
  for (let i = 0; i < active.length; i += 1) {
    if (runAt < runs.length && runs[runAt].start === i) {
      rows.push({ band: runs[runAt] });
      shutNow = bandShut(runs[runAt].key);
      runAt += 1;
    }
    if (!shutNow) rows.push({ student: active[i] });
  }
  if (dropped.length) {
    rows.push({ band: { section: "Dropped", count: dropped.length,
                        key: DROPPED_BAND } });
    if (!bandShut(DROPPED_BAND)) {
      for (const s of dropped) rows.push({ student: s });
    }
  }

  const shown = rows.filter(r => r.student).map(r => r.student);
  for (const row of rows) {
    if (row.band) { body.appendChild(sectionBand(row.band)); continue; }
    const student = row.student;
    const tr = document.createElement("tr");
    if (isDropped(student)) tr.className = "dropped";

    for (const column of COLUMNS) {
      const td = document.createElement("td");
      if (column.cls) td.className = column.cls;
      if (column.pin) td.classList.add("pin" + column.pin);
      if (column.key === "_actions") {
        // An icon, not the word: 45 rows of "drop" is 45 words of the
        // same instruction, and the column it needed was wider than the
        // window had to spare. Grey until you point at it, so the column
        // is quiet and the accent says which row you are on.
        const b = document.createElement("button");
        b.className = "iconbtn" + (isDropped(student) ? " undo" : "");
        b.appendChild(icon(isDropped(student) ? "restore" : "drop"));
        b.title = isDropped(student)
          ? "Put this student back on the roster."
          : "Drop this student. They stay on the roster, greyed out, and "
            + "print nothing.";
        b.setAttribute("aria-label", b.title);
        b.onclick = () => drop(student, !isDropped(student));
        td.appendChild(b);
      } else if (column.edit) {
        td.classList.add("cell-" + column.key);
        const input = cellInput(student, column.key, column);
        // Clamped columns clip. The full value is a hover away rather than
        // gone, which matters most for an email.
        input.title = student[column.key] || "";
        td.appendChild(input);
      } else {
        const value = column.text ? column.text(student)
                                  : (student[column.key] || "—");
        td.textContent = value;
        td.title = value;
      }
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }

  // After the rows exist, so the measurements use the real fonts.
  sizeColumns(shown);

  /* The class, which is the one count about the whole table. The
     per-section numbers are on their bands and the dropped count is on
     its own, each beside the rows it describes.

     Counting `active` rather than what is on screen: `shown` shrinks
     when a band is shut, and a total that changes because you folded
     something away is not a total. */
  document.getElementById("roster-count").textContent = active.length
    ? `${active.length} student${active.length === 1 ? "" : "s"}`
    : "";

  renderRosterEmpty(shown.length > 0);
}

/* Mark a student dropped or restored. Nothing is written until Save.
 *
 * Pressing it twice puts them back where they started, so the entry
 * goes rather than recording a change that is not one.
 */
function drop(student, dropped) {
  if (Boolean(student.dropped) === dropped) pendingDrops.delete(student.index);
  else pendingDrops.set(student.index, dropped);
  // Opened, so the student is visible where they have just gone rather
  // than vanishing into a band that is shut by default.
  if (dropped) shutBands.delete(DROPPED_BAND);
  renderRoster();
  refreshDirty();
}

async function applyDrops() {
  /* Drops before edits, and by the name the file still holds: the drop
     call matches on name, so a rename saved first would leave it
     looking for somebody who is no longer there. Nothing here renames
     anyone, so the names are still the stored ones. */
  let done = 0;
  for (const [index, dropped] of pendingDrops) {
    const student = students.find(s => s.index === index);
    if (!student) continue;
    const data = await api("/api/roster/drop",
                           { who: student.name, dropped });
    students = data.students;
    done += 1;
  }
  pendingDrops.clear();
  return done;
}

async function save() {
  const payload = [...edits.entries()].map(([k, value]) => {
    const [index, field] = k.split(":");
    return { index: Number(index), field, value };
  });
  const seats = [...pendingDrops.values()].filter(Boolean).length;
  try {
    const dropped = await applyDrops();
    if (payload.length) {
      const data = await api("/api/roster/save", { edits: payload });
      students = data.students;
    }
    const n = payload.length + dropped;
    edits.clear();
    renderRoster();
    refreshDirty();
    toast(`Saved ${n} change${n === 1 ? "" : "s"}`
      + (seats ? `. ${seats === 1 ? "A seat is" : seats + " seats are"} now `
                 + `empty — restoring does not give one back.` : ""));
  } catch (err) {
    // A drop may have gone through before a later one failed, so redraw
    // from whatever the server last returned rather than leave the
    // table showing a state nothing is in.
    renderRoster();
    refreshDirty();
    toast(err.message, true);
  }
}

function revert() {
  edits.clear();
  pendingDrops.clear();
  renderRoster();
  refreshDirty();
  toast("Discarded");
}

// --------------------------------------------------------------- skills --

let skills = null;            // the last state the server reported
let openNow = new Set();      // the checkboxes, before saving
let assessment = {};          // the fields, before saving
let previewTimer = null;

function assessmentInputs() {
  return {
    name: document.getElementById("a-name"),
    date: document.getElementById("a-date"),
    due: document.getElementById("a-due"),
    choose: document.getElementById("a-choose"),
    limit: document.getElementById("a-limit"),
  };
}

function readAssessment() {
  const f = assessmentInputs();
  const unlimited = f.limit.value === ANY;
  return {
    name: f.name.value,
    date: f.date.value,
    // The browser's datetime-local gives "2026-10-01T23:59"; the file wants
    // seconds, and as_datetime accepts either.
    due: f.due.value,
    // Zero is how the file says "as many as they like"; the dropdown says it
    // in words and the count disappears.
    choose: unlimited ? 0 : Number(f.choose.value || 1),
    limit: unlimited ? (skills ? skills.assessment.limit : "at most")
                     : f.limit.value,
  };
}

function syncLimitControls() {
  const f = assessmentInputs();
  const unlimited = f.limit.value === ANY;
  document.getElementById("choose-wrap").hidden = unlimited;
  if (!unlimited && Number(f.choose.value || 0) < 1) f.choose.value = 1;
}

function sameMinute(a, b) {
  /* The file says "2026-10-01 23:59:00" and a datetime-local input reads
     back "2026-10-01T23:59". Compared raw they never match, which left the
     form dirty the instant it loaded -- Save lit before anything had been
     touched, and so meaning nothing when something had. */
  const tidy = (v) => String(v || "").replace("T", " ").slice(0, 16);
  return tidy(a) === tidy(b);
}

function skillsDirty() {
  /* `skillsDrawn`, not just `skills`. The data is prefetched at boot
     and `assessment` is not filled until the tab is drawn, so a tab
     nobody has opened compared the server's values against an empty
     object and reported every field as changed. Harmless while only
     the save bar asked -- it is only drawn after `loadSkills` -- and
     not harmless once `pendingElsewhere` started asking cold, where it
     warned about unsaved work that did not exist. */
  if (!skills || !skillsDrawn) return false;
  const was = skills.assessment;
  const now = assessment;
  const sameFields = ["name", "date", "limit"].every(k => (was[k] || "") === (now[k] || ""))
    && Number(was.choose || 0) === Number(now.choose || 0)
    && sameMinute(was.due, now.due);
  const sameOpen = skills.open.length === openNow.size
    && skills.open.every(s => openNow.has(s));
  return !(sameFields && sameOpen);
}

function refreshSkillsDirty() {
  const dirty = skillsDirty();
  saveBar("form", dirty, "unsaved changes to this assessment");
  // No dash: the count is its own thing on the header row, not a
  // continuation of the heading's sentence.
  document.getElementById("open-count").textContent =
    `${openNow.size} of ${skills ? skills.skills.length : 0}`;
}

// "any number" is a choice in the dropdown rather than a zero typed into
// the count. The file still stores choose = 0 for it -- that is the format
// and the retired script's convention -- but nobody has to know that to use
// the form.
const ANY = "any number";

function fakeCheckbox() {
  /* Not a real input: it must look like the form without inviting a click
     that would do nothing. */
  const box = document.createElement("span");
  box.className = "fauxbox";
  box.setAttribute("aria-hidden", "true");
  return box;
}

function card(title) {
  const d = document.createElement("div");
  d.className = "fcard";
  if (title) {
    const h = document.createElement("div");
    h.className = "fcard-title";
    h.textContent = title;
    d.appendChild(h);
  }
  return d;
}

function renderWording(parts) {
  /* The whole form, top to bottom, from the server's `preview`: the fixed
     boilerplate and the wording a push derives, in the order a student
     meets them. */
  const box = document.getElementById("wording");
  box.textContent = "";
  box.classList.remove("loading");

  for (const part of parts) {
    if (part.kind === "form-title") {
      const head = document.createElement("div");
      head.className = "fhead";
      const h = document.createElement("div");
      h.className = "fhead-title";
      h.textContent = part.title;
      head.appendChild(h);
      box.appendChild(head);
      continue;
    }
    if (part.kind === "form-description") {
      const last = box.querySelector(".fhead");
      const d = document.createElement("div");
      d.className = "fhead-desc";
      d.textContent = part.body;
      (last || box).appendChild(d);
      continue;
    }

    const cardEl = card(part.title);
    if (part.missing) cardEl.classList.add("needs-text");

    // Required items are marked, because an instructor editing the
    // boilerplate later needs to know which two cannot be left out.
    if (part.required) {
      const tag = document.createElement("span");
      tag.className = "fkind";
      tag.textContent = "required";
      tag.title = part.note;
      cardEl.insertBefore(tag, cardEl.firstChild);
    }

    if (part.body) {
      const p = document.createElement("p");
      p.className = "fcard-text";
      p.textContent = part.body;
      cardEl.appendChild(p);
    }
    for (const option of part.options) {
      const opt = document.createElement("label");
      opt.className = "fopt";
      opt.append(fakeCheckbox(), document.createTextNode(option));
      cardEl.appendChild(opt);
    }
    if (part.footnote) {
      const p = document.createElement("p");
      p.className = "fcard-text muted rule";
      p.textContent = part.footnote;
      cardEl.appendChild(p);
    }
    if (part.missing) {
      const p = document.createElement("p");
      p.className = "fnote";
      p.textContent = "printit has no text for this section yet. It is on "
        + "the live form, added by hand; the boilerplate editor will own it.";
      cardEl.appendChild(p);
    }
    box.appendChild(cardEl);
  }
}

async function refreshPreview() {
  /* Debounced: the wording comes from the server so there is exactly one
     implementation of it, and a request per keystroke would be silly. */
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    try {
      const data = await api("/api/skills/preview",
        { assessment: readAssessment(), open: [...openNow] });
      renderWording(data.preview);
    } catch (err) { toast(err.message, true); }
  }, 250);
}

function renderSkills() {
  const list = document.getElementById("skill-list");
  list.textContent = "";
  list.classList.remove("loading");
  for (const s of skills.skills) {
    const label = document.createElement("label");
    label.className = "skill" + (s.inBank ? "" : " orphan");
    const box = document.createElement("input");
    box.type = "checkbox";
    box.checked = openNow.has(s.slug);
    box.onchange = () => {
      if (box.checked) openNow.add(s.slug); else openNow.delete(s.slug);
      label.classList.toggle("on", box.checked);
      refreshSkillsDirty();
      refreshPreview();
    };
    label.classList.toggle("on", box.checked);
    const slug = document.createElement("span");
    slug.className = "slug";
    slug.textContent = s.slug;
    const desc = document.createElement("span");
    desc.className = "desc";
    desc.textContent = s.inBank ? (s.title || s.slug)
      : "not in the bank any more — untick to remove it";
    desc.title = s.inBank ? (s.description || "") : desc.textContent;
    label.append(box, slug, desc);
    list.appendChild(label);
  }
  refreshSkillsDirty();
}

function fillAssessment() {
  const f = assessmentInputs();
  const a = skills.assessment;
  f.limit.textContent = "";
  for (const option of [...skills.limits, ANY]) {
    const o = document.createElement("option");
    o.value = o.textContent = option;
    f.limit.appendChild(o);
  }
  f.name.value = a.name || "";
  f.date.value = (a.date || "").slice(0, 10);
  f.due.value = (a.due || "").replace(" ", "T").slice(0, 16);
  f.choose.value = a.choose || 1;
  f.limit.value = a.choose ? (a.limit || skills.limits[0]) : ANY;
  syncLimitControls();
  assessment = readAssessment();
  for (const input of Object.values(f)) {
    input.oninput = input.onchange = () => {
      syncLimitControls();
      assessment = readAssessment();
      refreshSkillsDirty();
      refreshPreview();
    };
  }
}

function renderPushState() {
  // The same bar the Print tab shows, from the same field. Both tabs
  // reach Google the same way, so they say the same thing about it.
  renderFormBar("form-conn-bar",
                { hasFile: true, connected: skills.form.connected });
  const note = document.getElementById("push-state");
  const push = document.getElementById("form-push");
  if (!skills.form.connected) {
    note.textContent = "No form is connected to this course yet. Run "
      + "`checkit-printit form create` or `form attach` first.";
    push.disabled = true;
  } else if (!skills.form.mapped.length) {
    note.textContent = "The form is connected but no items are mapped. Run "
      + "`checkit-printit form map`.";
    push.disabled = true;
  } else {
    // No separate "show what would change" step: the preview above is what
    // would be there, and a push replaces the four slots wholesale. A diff
    // of a wholesale replacement is a second way of reading the same thing.
    note.textContent = "Replaces the four slots above with the preview. "
      + "Students see it immediately.";
    push.disabled = false;
  }
}

/* ---- waiting happens before the click, not after ---------------------
 *
 * Measured on this course: `/api/skills` is ~700ms warm and 1.2s cold,
 * and `/api/google` is **six seconds** the first time -- it shells out
 * to clasp. Both used to start when the Update form tab was opened, so
 * the tab was empty for about a second every time and the Google banner
 * arrived whenever it arrived.
 *
 * Both now start at boot, and the tab awaits a request that is usually
 * already finished. The promise is kept rather than the data, so a
 * second caller joins the first request instead of making another --
 * Setup and the Form banner both want the Google answer, and that was
 * two six-second calls.
 */
let skillsRequest = null;
let googleRequest = null;

function fetchSkills({ fresh = false } = {}) {
  if (fresh || !skillsRequest) {
    skillsRequest = api("/api/skills").then(data => {
      skills = data;
      openNow = new Set(data.open);
      return data;
    }, err => { skillsRequest = null; throw err; });
  }
  return skillsRequest;
}

function fetchGoogle({ force = false } = {}) {
  if (force || !googleRequest) {
    googleRequest = api("/api/google", { force: Boolean(force) })
      .catch(err => { googleRequest = null; throw err; });
  }
  return googleRequest;
}

/* Whether the tab has been drawn, which is not the same as whether the
 * data has arrived -- and once the data is prefetched at boot, `skills
 * !== null` stopped meaning "already on screen" and the tab came up
 * blank. Drawing is also once per visit on purpose: `fillAssessment`
 * refills the fields from the server, so re-running it on every visit
 * would throw away edits made before stepping over to the Roster. */
let skillsDrawn = false;

async function loadSkills() {
  // Placeholders the size of what is coming, so the tab has its shape
  // before it has its content and nothing jumps when the data lands.
  if (skills === null) showSkillsPlaceholders();
  try {
    await fetchSkills();
  } catch (err) { toast(err.message, true); clearSkillsPlaceholders(); return; }
  skillsDrawn = true;
  fillAssessment();
  renderSkills();
  renderWording(skills.preview);
  renderPushState();
  refreshGoogle();
}

/* Rows the height of real ones, and as many as this bank has, so the
   list does not grow under the pointer when the answer arrives. */
function showSkillsPlaceholders() {
  const list = document.getElementById("skill-list");
  list.textContent = "";
  list.classList.add("loading");
  for (let i = 0; i < 8; i += 1) {
    const row = document.createElement("div");
    row.className = "skill ghostrow";
    const slug = document.createElement("span");
    slug.className = "slug";
    slug.appendChild(bar(34));
    const desc = document.createElement("span");
    desc.className = "desc";
    // Uneven, because a column of identical bars reads as a pattern
    // rather than as text that has not arrived.
    desc.appendChild(bar([180, 240, 150, 210][i % 4]));
    row.append(slug, desc);
    list.appendChild(row);
  }
  const wording = document.getElementById("wording");
  wording.textContent = "";
  wording.classList.add("loading");
  for (const w of [260, 420, 340]) wording.appendChild(bar(w, true));
}

function clearSkillsPlaceholders() {
  document.getElementById("skill-list").classList.remove("loading");
  document.getElementById("wording").classList.remove("loading");
}

function bar(width, block) {
  const b = document.createElement("span");
  b.className = "ghostbar";
  b.style.width = typeof width === "number" ? width + "px" : width;
  if (block) b.style.display = "block";
  return b;
}

async function saveSkills() {
  try {
    skills = await api("/api/skills/save",
      { open: [...openNow], assessment: readAssessment() });
    openNow = new Set(skills.open);
    fillAssessment();
    renderSkills();
    renderWording(skills.preview);
    renderPushState();
    toast("Saved");
  } catch (err) { toast(err.message, true); }
}

function revertSkills() {
  openNow = new Set(skills.open);
  fillAssessment();
  renderSkills();
  renderWording(skills.preview);
  toast("Discarded");
}

async function pushForm() {
  if (skillsDirty()) {
    toast("Save first — the form would be sent the saved wording, not what "
          + "is on screen.", true);
    return;
  }
  /* `ask`, not `confirm`. The desktop pane suppresses native modals, so
     `confirm` returned falsy without ever drawing anything and this
     button did nothing at all -- silently, which is the worst way for
     the most consequential control in the app to fail. Reported as
     "I tried using the Push it button... but nothing happened."

     The same bug was found and fixed on the Roster's drop button
     earlier the same day. This copy was missed: a fix applied to one
     path is not applied to the others. */
  const go = await ask({
    title: "Push this to the form?",
    body: ["It replaces the four slots shown in the preview.",
           "Students see the change immediately."],
    yes: "Push it",
  });
  if (!go) return;
  try {
    const out = await api("/api/form/push", {});
    // What actually changed is worth saying, since a push that changed
    // nothing and a push that rewrote everything look identical otherwise.
    toast(out.changed.length
      ? "Pushed: " + out.changed.join(", ")
      : "Pushed; the form already said this.");
  } catch (err) { toast(err.message, true); }
}


/* ---- Runs ------------------------------------------------------------
 *
 * Two pages in one view and never both: `runs-list` and `runs-detail`.
 * Drilling in replaces the list rather than expanding a row, because
 * the detail is 50-odd rows of seeds -- as an expanding row it would
 * push the list a screen and a half down, and as a side panel it would
 * leave too little of the content column for the seed table.
 *
 * Nothing here is editable, so there is no save bar and no dirty
 * state. The two flags write immediately and the server hands back the
 * refreshed list, because delisting moves a run between two groups and
 * the view would otherwise have to work out where it went.
 */
let runsState = null;
let openRun = null;        // the run id being shown, or null for the list

function loadRuns() {
  api("/api/runs").then(out => {
    runsState = out;
    if (openRun) showRun(openRun);
    else renderRuns();
  }).catch(err => toast(err.message, true));
}

function runRow(run, tbody) {
  const tr = document.createElement("tr");
  const add = (text, cls) => {
    const td = document.createElement("td");
    td.textContent = text;
    if (cls) td.className = cls;
    tr.appendChild(td);
    return td;
  };
  const open = document.createElement("td");
  const link = document.createElement("button");
  link.className = "rowlink";
  link.textContent = run.title;
  link.onclick = () => showRun(run.id);
  open.appendChild(link);
  if (run.graded) {
    const chip = document.createElement("span");
    chip.className = "chip ok";
    chip.textContent = "graded";
    open.appendChild(chip);
  }
  tr.appendChild(open);

  add(spokenDay(run.date) || run.date, "ro");
  // Date and time, because two runs can share a date -- 10/19 is
  // dated the 19th and was built at 10:43:37.
  add(builtAt(run.built), "ro");
  add(String(run.papers), "ro");
  add(String(run.students), "ro");
  add(String(run.seed), "ro seedcell");

  // Last, and marked `.stretch`, so the table fills its frame and
  // the buttons end up at the right edge rather than halfway across.
  const actions = document.createElement("td");
  actions.className = "stretch";
  actions.className = "pinright";
  // A graded run offers no delist at all, rather than offering one
  // and refusing it. The record refuses it too; this is the half that
  // keeps the instructor from meeting a wall.
  if (!run.graded) {
    const flag = document.createElement("button");
    flag.className = "iconbtn tiny";
    flag.appendChild(icon(run.delisted ? "restore" : "drop"));
    flag.title = run.delisted
      ? "Put this run back in the list."
      : "Move this run to the delisted group. Nothing is deleted.";
    flag.setAttribute("aria-label", flag.title);
    flag.onclick = () => setRunFlag(run.id, { delisted: !run.delisted });
    actions.appendChild(flag);
  }
  tr.appendChild(actions);
  tbody.appendChild(tr);
}

function builtAt(stamp) {
  // "2026-10-19T10:43:37" -> "10/19, 10:43". Sliced rather than parsed:
  // the string is written by the build in local time and `new Date` on
  // an unzoned stamp is a timezone argument nobody needs here.
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})/.exec(stamp || "");
  if (!m) return stamp || "";
  return `${Number(m[2])}/${Number(m[3])}, ${m[4]}:${m[5]}`;
}

// ------------------------------------------------------------- scans ----
//
// Import a stack, place every page, report what did not place. The
// marking itself is not here yet: placing has to be trustworthy
// before a reading of someone's tick is worth showing, and placing is
// the part that can be checked without an opinion.

let scanChosen = [];
let scanPolling = null;
let scanWired = false;

function scanSetup() {
  // `show()` calls this every time the tab is opened, so it has to be
  // safe to call twice. Without the guard the second visit adds a
  // second click handler and "Read them" uploads the stack twice.
  if (scanWired) return;
  scanWired = true;
  const input = document.getElementById("scan-files");
  const go = document.getElementById("scan-go");
  input.addEventListener("change", () => {
    scanChosen = Array.from(input.files || []);
    const chosen = document.getElementById("scan-chosen");
    chosen.textContent = scanChosen.length
      ? scanChosen.map(f => f.name).join(", ")
      : "";
    go.disabled = !scanChosen.length;
  });
  go.addEventListener("click", scanStart);
}

async function scanStart() {
  const go = document.getElementById("scan-go");
  go.disabled = true;
  show_scan_error("");
  document.getElementById("scan-result").hidden = true;
  const progress = document.getElementById("scan-progress");
  progress.hidden = false;
  progress.textContent = "Reading the files\u2026";

  // Base64 rather than a path: the stack arrives in Downloads off the
  // copier's email, and a file picker is the gesture everybody has.
  const files = [];
  for (const file of scanChosen) {
    const buffer = await file.arrayBuffer();
    let binary = "";
    const bytes = new Uint8Array(buffer);
    for (let i = 0; i < bytes.length; i += 0x8000)
      binary += String.fromCharCode.apply(
        null, bytes.subarray(i, i + 0x8000));
    files.push({ name: file.name, data: btoa(binary) });
  }

  const out = await api("/api/scan/start", { files });
  if (!out) { go.disabled = false; progress.hidden = true; return; }
  scanPoll();
}

function scanPoll() {
  clearTimeout(scanPolling);
  scanPolling = setTimeout(async () => {
    const out = await api("/api/scan/status", {});
    if (!out) return;
    const progress = document.getElementById("scan-progress");
    if (out.running) {
      progress.textContent = out.total
        ? `Reading page ${out.done} of ${out.total}\u2026`
        : "Reading\u2026";
      scanPoll();
      return;
    }
    progress.hidden = true;
    document.getElementById("scan-go").disabled = !scanChosen.length;
    if (out.error) { show_scan_error(out.error); return; }
    if (out.result) renderScan(out.result);
  }, 400);
}

function show_scan_error(message) {
  const box = document.getElementById("scan-error");
  box.textContent = message;
  box.hidden = !message;
}

/* A table from a heading row and a list of rows.
 *
 * `stretch` is which column absorbs the width the others do not
 * need -- see `.stretch` in style.css. Without one the slack is
 * shared out evenly and a column of page numbers comes out as wide
 * as a column of names.
 *
 * The last column by default, which was not the first guess.
 * Stretching the column with the most variable content shoves
 * everything after it against the right edge: a two-column table
 * ends up with the name at one side and the skill at the other and
 * an inch of nothing between. Last means every column packs left and
 * the slack lands where there is nothing to misalign.
 */
function rows(table, head, body, stretch = head.length - 1) {
  table.innerHTML = "";
  const thead = document.createElement("thead");
  const hr = document.createElement("tr");
  head.forEach((cell, i) => {
    const th = document.createElement("th");
    th.textContent = cell;
    if (i === stretch) th.className = "stretch";
    hr.appendChild(th);
  });
  thead.appendChild(hr);
  table.appendChild(thead);
  const tbody = document.createElement("tbody");
  for (const line of body) {
    const tr = document.createElement("tr");
    line.forEach((cell, i) => {
      const td = document.createElement("td");
      td.textContent = cell;
      if (i === stretch) td.className = "stretch";
      tr.appendChild(td);
    });
    tbody.appendChild(tr);
  }
  table.appendChild(tbody);
}

/* What each outcome is called, and what it means for the person
 * holding the paper.
 *
 * Here and not on the server: this is wording, and wording belongs
 * with the view. `sentence` takes the count because "1 page was
 * blank" and "2 pages were blank" are different sentences, and
 * "1 pages" is the kind of thing that makes software look unfinished.
 *
 * `chase` marks the ones worth doing something about. Only those are
 * coloured -- a page of green ticks beside the ordinary outcomes
 * would make the two that matter harder to find, not easier.
 */
const SCAN_OUTCOME = {
  placed: {
    short: "Matched",
    sentence: n => `${n} ${n === 1 ? "page" : "pages"} matched to a student`,
    why: "I know whose paper this is and which skill it was for.",
  },
  blank: {
    short: "Blank",
    sentence: n => `${n} blank ${n === 1 ? "page" : "pages"}`,
    why: "Nothing printed and nothing written. A spacer sheet, or the "
       + "back of a single-sided page. Ignored.",
  },
  unreadable: {
    short: "Could not read",
    sentence: n => `${n} ${n === 1 ? "page" : "pages"} I could not read`,
    why: "There is something on these, but no code I could find. A "
       + "torn corner, a very dark scan, or a page printed before the "
       + "codes existed. You will have to place these by hand.",
    chase: true,
  },
  foreign: {
    short: "Not from here",
    sentence: n => `${n} ${n === 1 ? "page carries" : "pages carry"} `
                 + "a barcode from something else",
    why: "A code, but not one of ours. Probably a cover sheet.",
  },
  "unknown-run": {
    short: "Unknown print job",
    sentence: n => `${n} ${n === 1 ? "page names" : "pages name"} `
                 + "a print job I have no record of",
    why: "The code is one of ours and names a job this course has not "
       + "got. From another course, or a job whose folder was deleted.",
    chase: true,
  },
  "unknown-page": {
    short: "Page not in that job",
    sentence: n => `${n} ${n === 1 ? "page is" : "pages are"} `
                 + "numbered past the end of the job they name",
    why: "The job is here and does not have that page -- the folder "
       + "was built again after this was printed.",
    chase: true,
  },
};

function scanOutcome(status) {
  return SCAN_OUTCOME[status] || { short: status, sentence: n => `${n} ${status}` };
}

/* The review grid.
 *
 * One row per paper. The crop is the point of it: the instructor is
 * agreeing with a photograph of his own tick, not with a number, and
 * a cell that showed only a verdict would be asking him to trust the
 * reader rather than check it.
 *
 * Uncertain first and the rest folded away, because the reader gets
 * ticks right and flags question marks -- so the pile that needs a
 * person is small and specific, and the rest is there to be looked
 * through rather than worked through.
 */
let reviewRows = [];
let reviewOutcomes = [];

function reviewRow(row) {
  const el = document.createElement("div");
  el.className = "review-row";
  el.dataset.id = row.id;

  const who = document.createElement("div");
  who.className = "review-who";
  const name = document.createElement("div");
  name.className = "review-name";
  name.textContent = row.name || row.sid || "(no name)";
  const skill = document.createElement("div");
  skill.className = "muted";
  skill.textContent = row.skill;
  who.append(name, skill);
  // Said here rather than over the pictures: it is a fact about the
  // paper, and `.review-shot` is white because a crop of a sheet
  // belongs on something sheet-coloured.
  if ((row.crops || []).length > 1 && !row.read) {
    const note = document.createElement("div");
    note.className = "warnline review-disagree";
    note.textContent = "scanned twice, and the two do not match";
    who.appendChild(note);
  }

  const shot = document.createElement("div");
  shot.className = "review-shot";
  const crops = row.crops || [];
  if (crops.length) {
    // Usually one. Two when the sheet went through the copier
    // twice, and then both are here on purpose: if they disagree
    // the suggestion was withheld, and the two pictures are the
    // reason why.
    shot.classList.toggle("twice", crops.length > 1);
    for (const crop of crops) {
      const img = document.createElement("img");
      img.src = crop;
      img.alt = `the grading box on ${row.name || row.sid}'s ${row.skill}`;
      img.loading = "lazy";
      shot.appendChild(img);
    }
  } else {
    const gap = document.createElement("span");
    gap.className = "muted review-nocrop";
    // Said plainly, because the next thing he does depends on it:
    // this is a paper he may still be holding.
    gap.textContent = "no paper came back";
    shot.appendChild(gap);
  }

  const picks = document.createElement("div");
  picks.className = "review-picks";
  picks.setAttribute("role", "radiogroup");
  for (const outcome of reviewOutcomes) {
    // "Did not sit it" is only an answer for a paper that is not
    // here. A sheet that came back was sat, whatever is on it.
    if (outcome.id === "absent" && row.scanned) continue;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "review-pick";
    button.dataset.outcome = outcome.id;
    button.textContent = outcome.label;
    button.title = outcome.mark;
    button.setAttribute("role", "radio");
    button.onclick = () => setOutcome(row.id, outcome.id);
    picks.appendChild(button);
  }

  el.append(who, shot, picks);
  paintRow(el, row);
  return el;
}

function paintRow(el, row) {
  el.classList.toggle("undecided", !row.outcome);
  for (const button of el.querySelectorAll(".review-pick")) {
    const on = button.dataset.outcome === row.outcome;
    button.classList.toggle("on", on);
    button.setAttribute("aria-checked", on ? "true" : "false");
  }
}

function setOutcome(id, outcome) {
  const row = reviewRows.find(r => r.id === id);
  if (!row) return;
  // Clicking the one already chosen clears it, which is the only way
  // back to "I have not decided" without reloading the stack.
  row.outcome = row.outcome === outcome ? "" : outcome;
  row.touched = true;
  for (const el of document.querySelectorAll(
      `.review-row[data-id="${CSS.escape(id)}"]`)) {
    paintRow(el, row);
  }
  countReview();
}

function countReview() {
  const undecided = reviewRows.filter(r => !r.outcome).length;
  const done = reviewRows.length - undecided;
  document.getElementById("review-count").textContent =
    `${done} of ${reviewRows.length} decided`;
  const accept = document.getElementById("review-accept");
  if (accept) accept.disabled = !undecided;
  refreshScansDirty();
}

/* Decided, and not the same as what was last written for that paper.
 *
 * Per row rather than one flag for the tab, so that saving, spotting
 * one wrong and fixing it offers one paper rather than all of them --
 * and so a second Save after no change has nothing to do and says so
 * by not appearing.
 *
 * `saved` is the outcome the server has, not a boolean: changing a
 * paper from passed to failed has to count as dirty again, and a
 * boolean would call it clean. */
function unsavedReview() {
  return reviewRows.filter(r => r.outcome && r.outcome !== r.saved);
}

function refreshScansDirty() {
  const n = unsavedReview().length;
  saveBar("scans", n > 0,
          n === 1 ? "1 result not saved" : `${n} results not saved`);
}

async function saveScans() {
  const rows = unsavedReview();
  if (!rows.length) return;
  let out;
  try {
    out = await api("/api/scan/save", {
      decisions: rows.map(r => ({ id: r.id, outcome: r.outcome })) });
  } catch (err) {
    // The one failure worth spelling out: the server was restarted
    // between reading the stack and saving it, so its copy of the
    // read is gone and it will not take the page's word for whose
    // paper was whose. Nothing is lost that re-reading cannot get
    // back, and the message says so.
    toast(err.message || "could not save", true);
    return;
  }
  for (const row of rows) row.saved = row.outcome;
  reviewNote(out);
  countReview();
  toast(out.saved === 1 ? "1 result saved" : `${out.saved} results saved`);
}

/* What the save had to say, kept on the page rather than in a toast.
 *
 * A toast is right for "it worked" and wrong for "two of these name
 * a student the print record never printed" -- that is something to
 * look at, and nine seconds is not long enough to look at anything.
 */
function reviewNote(out) {
  const line = document.getElementById("review-unsaved");
  const parts = [];
  if (out.unprinted && out.unprinted.length) {
    parts.push(`${out.unprinted.length} of these name a paper the print `
      + `record has no trace of printing (`
      + out.unprinted.map(u => `${u.sid} ${u.skill}`).join(", ")
      + `). They were saved anyway -- your decision is yours -- but `
      + `the page index and the record disagree, which is worth a `
      + `look.`);
  }
  if (out.noRun && out.noRun.length) {
    parts.push(`Run ${out.noRun.join(", ")} is not in this course's `
      + `record, so nothing from it could be saved.`);
  }
  line.textContent = parts.join(" ");
  line.hidden = !parts.length;
}

function renderReview(data) {
  /* `saved` starts as whatever the record already holds for that
     paper, which the server sends. A stack read a second time then
     comes up clean instead of offering six results that went in the
     first time -- and a row the record disagrees with still shows
     as unsaved, which is exactly when it should.

     `outcome` is the suggestion, so a paper already recorded as
     something else keeps its old answer visible as "not saved"
     until he looks. */
  reviewRows = (data.review || []).map(
    r => ({ ...r,
            touched: false,
            saved: r.recorded || "",
            outcome: r.recorded || r.outcome }));
  document.getElementById("review-unsaved").hidden = true;
  reviewOutcomes = data.outcomes || [];
  const box = document.getElementById("scan-review");
  box.hidden = !reviewRows.length;
  if (!reviewRows.length) return;

  const asks = reviewRows.filter(r => !r.outcome);
  const rest = reviewRows.filter(r => r.outcome);

  const asksBox = document.getElementById("scan-review")
    .querySelector("#review-asks");
  asksBox.hidden = !asks.length;
  if (asks.length) {
    document.getElementById("review-asks-count").textContent =
      asks.length === 1 ? "1 paper needs you"
                        : `${asks.length} papers need you`;
    const accept = document.getElementById("review-accept");
    accept.textContent = rest.length === 1
      ? "Agree with the other one"
      : `Agree with the other ${rest.length}`;
    // Agreeing is not saving. It marks the readings the instructor
    // has not argued with as decided; the saving is one action at
    // the end, and it is not built yet.
    accept.onclick = () => {
      for (const row of reviewRows) if (row.outcome) row.agreed = true;
      countReview();
      accept.disabled = true;
    };
    const rows = document.getElementById("review-asks-rows");
    rows.innerHTML = "";
    for (const row of asks) rows.appendChild(reviewRow(row));
  }

  const restHead = document.getElementById("review-rest-head");
  restHead.textContent = rest.length === 1
    ? "The one I am sure about"
    : `The ${rest.length} I am sure about`;
  const restRows = document.getElementById("review-rest-rows");
  restRows.innerHTML = "";
  for (const row of rest) restRows.appendChild(reviewRow(row));
  document.getElementById("review-rest").open = !asks.length;

  countReview();
}

function renderScan(data) {
  document.getElementById("scan-result").hidden = false;
  const n = data.sheets.length;
  document.getElementById("scan-count").textContent =
    `${n} page${n === 1 ? "" : "s"} scanned`;

  // One run is the ordinary case and reads as a sentence. More than
  // one is unusual enough to be worth listing.
  const runs = document.getElementById("scan-runs");
  if (!data.runs.length) {
    runs.textContent = "None of these pages came from a print job this "
                     + "course knows about.";
  } else if (data.runs.length === 1) {
    const r = data.runs[0];
    runs.textContent = `These are from ${r.title}, printed `
      + `${spokenDay(r.date) || r.date}. That job was ${r.pages} pages.`;
  } else {
    runs.textContent = "These come from more than one print job: "
      + data.runs.map(r => `${r.title} (${spokenDay(r.date) || r.date})`)
          .join(", ") + ".";
  }

  const counts = document.getElementById("scan-counts");
  counts.innerHTML = "";
  // Said here rather than listed in a section of its own: the papers
  // themselves are rows in the review below, and a table up here
  // would be the same fact written twice.
  if (data.missing.length) {
    const li = document.createElement("li");
    li.className = "chase";
    const strong = document.createElement("strong");
    strong.textContent = data.missing.length === 1
      ? "1 paper was printed and never came back."
      : `${data.missing.length} papers were printed and never came back.`;
    const span = document.createElement("span");
    span.className = "muted";
    span.textContent = " They are at the top of the review below, "
      + "where you can mark one by hand or say the student was away.";
    li.append(strong, span);
    counts.appendChild(li);
  }
  for (const [status, count] of Object.entries(data.counts)) {
    const outcome = scanOutcome(status);
    const li = document.createElement("li");
    if (outcome.chase) li.className = "chase";
    const strong = document.createElement("strong");
    strong.textContent = outcome.sentence(count) + ".";
    li.appendChild(strong);
    if (outcome.why) {
      const span = document.createElement("span");
      span.className = "muted";
      span.textContent = " " + outcome.why;
      li.appendChild(span);
    }
    counts.appendChild(li);
  }

  const dupes = document.getElementById("scan-dupes");
  dupes.hidden = !data.duplicates.length;
  if (data.duplicates.length)
    rows(document.getElementById("scan-dupes-table"),
         ["The same paper", "Turned up in"],
         data.duplicates.map(d => [
           data.sheets.find(s => s.run === d.run && s.page === d.page)
             ?.name || `page ${d.page}`,
           d.where.join(" and "),
         ]));

  // The print job only earns a column when the stack spans more than
  // one of them, which is rare. Otherwise it is the same number on
  // every row, which is noise.
  const manyRuns = data.runs.length > 1;
  const head = ["File", "Page in it", "What it is", "Student",
                "Skill"];
  if (manyRuns) head.push("Print job");
  rows(document.getElementById("scan-sheets"), head,
       data.sheets.map(s => {
         // An answer key is not a matched anything -- it is an
         // answer key, and saying so is the whole answer. Same for
         // a spare, which belongs to nobody until it is written on.
         const what = s.kind === "key" ? "Answer key"
                    : s.kind === "spare" ? "Spare copy"
                    : scanOutcome(s.status).short;
         const line = [
           s.file, s.at, what, s.name || s.sid || "", s.skill,
         ];
         if (manyRuns) line.push(s.run ?? "");
         return line;
       }));

  renderReview(data);
}

function renderRuns() {
  openRun = null;
  document.getElementById("runs-list").hidden = false;
  document.getElementById("runs-detail").hidden = true;
  const live = runsState.runs;
  const gone = runsState.delisted;

  const body = document.querySelector("#runs tbody");
  body.textContent = "";
  for (const run of live) runRow(run, body);

  const empty = document.getElementById("runs-empty");
  empty.textContent = live.length ? "" : (
    gone.length
      ? "Every run is delisted. They are below."
      : "Nothing has been built for this course yet. Build a print job "
        + "and it appears here.");
  empty.hidden = Boolean(live.length);
  document.querySelector("#runs").hidden = !live.length;

  const count = document.getElementById("runs-count");
  count.textContent = live.length
    ? `${live.length} run${live.length === 1 ? "" : "s"}` : "";

  const wrap = document.getElementById("runs-delisted-wrap");
  wrap.hidden = !gone.length;
  document.getElementById("runs-delisted-count").textContent =
    gone.length ? String(gone.length) : "";
  const goneBody = document.querySelector("#runs-gone tbody");
  goneBody.textContent = "";
  for (const run of gone) runRow(run, goneBody);
}

function allRuns() {
  return [...runsState.runs, ...runsState.delisted];
}

async function showRun(id) {
  let out;
  try {
    out = await api("/api/run", { id });
  } catch (err) { toast(err.message, true); return; }
  const run = out.run;
  openRun = id;
  document.getElementById("runs-list").hidden = true;
  document.getElementById("runs-detail").hidden = false;

  for (const [id, name] of [["run-back", "back"], ["run-prev", "back"],
                            ["run-next", "forward"]]) {
    const b = document.getElementById(id);
    if (!b.firstChild) b.appendChild(icon(name));
  }
  document.getElementById("run-title").textContent = run.title;
  document.getElementById("run-sub").textContent =
    `${spokenDay(run.date) || run.date} \u00b7 built ${builtAt(run.built)}`
    + (run.delisted ? " \u00b7 delisted" : "");

  const facts = document.getElementById("run-facts");
  facts.textContent = "";
  const pairs = [
    [`${run.papers} paper${run.papers === 1 ? "" : "s"}`, ""],
    [`${run.students} student${run.students === 1 ? "" : "s"}`, ""],
    [`seed ${run.seed}`, ""],
  ];
  if (run.extras) pairs.push([`${run.extras} spare`, ""]);
  if (run.graded) pairs.push(["graded", "ok"]);
  for (const [text, cls] of pairs) {
    const chip = document.createElement("span");
    chip.className = "chip" + (cls ? " " + cls : "");
    chip.textContent = text;
    facts.appendChild(chip);
  }

  // Seeds grouped under their skill, so the table is one row per skill
  // rather than one per paper -- 14 rows instead of 29 for a real run.
  const byslug = {};
  for (const s of run.seeds) (byslug[s.slug] = byslug[s.slug] || []).push(s);
  const body = document.querySelector("#run-skills tbody");
  body.textContent = "";
  for (const skill of run.skills) {
    const tr = document.createElement("tr");
    const add = (text, cls) => {
      const td = document.createElement("td");
      td.textContent = text;
      if (cls) td.className = cls;
      tr.appendChild(td);
    };
    add(skill.slug);
    add(String(skill.papers), "ro");
    add(String(skill.versions), "ro");
    add((byslug[skill.slug] || [])
        .map(s => `${s.version} ${s.seed}`).join("   "), "ro seedcell");
    body.appendChild(tr);
  }
  document.getElementById("run-skill-count").textContent =
    `${run.skills.length} skill${run.skills.length === 1 ? "" : "s"}`;

  // Reprint needs the folder the manifest lives in. A run whose folder
  // has been moved is still a run -- the record is the record -- so it
  // is listed and the button says why it cannot act.
  const why = document.getElementById("run-again-why");
  document.getElementById("run-replay").disabled = !run.onDisk;
  why.textContent = run.onDisk ? "" :
    "This run's folder is not where the record says it is, so it cannot "
    + "be reprinted exactly. Starting a new run from its settings still "
    + "works.";

  document.getElementById("run-replay").onclick = () => replayRun(run);
  document.getElementById("run-reuse").onclick = () => reuseRun(run);

  const order = allRuns().map(r => r.id);
  const at = order.indexOf(id);
  const prev = document.getElementById("run-prev");
  const next = document.getElementById("run-next");
  prev.disabled = at <= 0;
  next.disabled = at < 0 || at >= order.length - 1;
  prev.onclick = () => showRun(order[at - 1]);
  next.onclick = () => showRun(order[at + 1]);
}

async function replayRun(run) {
  const go = await ask({
    title: "Reprint this run exactly?",
    body: [`${run.papers} paper${run.papers === 1 ? "" : "s"} for the same `
           + `${run.students} student${run.students === 1 ? "" : "s"}, at `
           + `the same seeds.`,
           "Nothing is drawn. A new folder is written beside the original."],
    yes: "Reprint it",
  });
  if (!go) return;
  try {
    const out = await api("/api/run/replay", { id: run.id });
    toast(`Reprinted ${out.papers} paper${out.papers === 1 ? "" : "s"}.`);
  } catch (err) { toast(err.message, true); }
}

async function reuseRun(run) {
  /* Fills the Print tab's form and leaves it unsaved, so it can be
     discarded. Warns about unsaved print work first, because this
     overwrites it -- the same courtesy `okDespitePending` does for
     the other direction. */
  if (printState && printDirty()) {
    const go = await ask({
      title: "Replace the print job you are building?",
      body: ["The Print job tab has unsaved changes, and these settings "
             + "would overwrite them."],
      yes: "Replace it",
    });
    if (!go) return;
  }
  let out;
  try {
    out = await api("/api/run/reuse", { id: run.id });
  } catch (err) { toast(err.message, true); return; }

  /* `draft` is null until the Print tab has been opened once, and
     Runs can be the first tab of a session -- open the app, look at
     what was printed, reuse it. Writing into null threw a TypeError
     and the button did nothing visible.

     Loading here rather than guarding the read: the settings are
     about to be merged *into* today's draft, so today's draft has to
     exist first. `loadPrint` then runs a second time under `show`,
     and leaves what is set below alone, because by then the draft
     differs from the saved file and `printDirty()` is true. */
  if (!printState) await loadPrint();
  if (!printState) return;        // the load itself failed and said so

  // The title and date are deliberately *not* carried over -- they are
  // what made it that run. Today's draft keeps its own.
  const keep = { title: draft.title, date: draft.date };
  draft = { ...out.draft, ...keep };
  show("print");
  renderPrintFields();
  renderModes();
  renderVariants();
  renderWho();
  refreshPrintDirty();
  toast("Settings loaded. Nothing is saved yet \u2014 check them, then Save.");
}

async function setRunFlag(id, fields) {
  if (fields.delisted) {
    const go = await ask({
      title: "Delist this run?",
      body: ["It moves to a group at the bottom of the list.",
             "Nothing is deleted, and you can put it back."],
      yes: "Delist it",
    });
    if (!go) return;
  }
  try {
    runsState = await api("/api/run/flag", { id, ...fields });
  } catch (err) { toast(err.message, true); return; }
  renderRuns();
}

// --------------------------------------------------------------- google --

/* ---- what actually stops a push or a pull ---------------------------
 *
 * Not the Google sign-in. `form push` and `form pull` both go through
 * `form.call`, which is an HTTPS POST to the deployed Apps Script web
 * app carrying the shared secret from `secrets/form-secret.toml`. No
 * OAuth, no clasp, no browser. clasp is used by `provision.py` alone,
 * to deploy or redeploy the script, and that lives on Settings.
 *
 * This bar used to say "Not signed in to Google, so pushing will fail"
 * and was driven by `clasp login` state. It was showing on the morning
 * of 2026-10-23 while a pull was in fact succeeding, which sent an hour
 * of diagnosis down the wrong path. The check was real; the conclusion
 * drawn from it was invented.
 *
 * One function for both tabs, because "Update form and Print job should
 * both have the same Google sign in mechanisms and warnings" -- and the
 * only honest way to make them the same is to make them both true. */
function renderFormBar(barId, form) {
  const bar = document.getElementById(barId);
  if (!bar) return;
  bar.textContent = "";
  // A course that never had a form is not missing one. The tabs that
  // need a form hide their own controls in that case.
  if (!form || !form.hasFile || form.connected) { bar.hidden = true; return; }

  bar.className = "banner warn";
  bar.append(document.createTextNode(
    "No form is connected to this course, so pushing and pulling will "
    + "fail. This is not the Google sign-in \u2014 it is the web app "
    + "address and its secret. "));
  const go = document.createElement("button");
  go.className = "act";
  go.textContent = "Open Settings";
  go.onclick = () => show("setup");
  bar.appendChild(go);
  bar.hidden = false;
}

async function refreshGoogle(force) {
  /* Settings needs the clasp answer; no working tab does. Kept as a
     plain state refresh so `loadSetup` has something to draw. */
  try {
    await fetchGoogle({ force: Boolean(force) });
  } catch { /* Settings reports it; a working tab has no use for it. */ }
}




// ---------------------------------------------------------------- setup --

let setupState = null;
/* Looking at what attaching would replace is required before attaching,
   not merely advised, so it survives a re-render rather than being read
   back off a button that `runSetup` may have disabled. */
let attachAllowed = false;
/* Kept apart from `setupState` because it arrives on a different clock:
   the connection is a file read and this is an `npx` call. A reply that
   replaces the whole of `setupState` must not take the Google answer with
   it. */
let googleState = { checking: true };

async function signInToGoogle() {
  /* One copy: the banner and the Setup view both start the same sign-in,
     and clasp opens the browser itself. */
  try {
    await api("/api/google/login", {});
    toast("A browser window should open. Sign in there.");
    refreshGoogle(true);
    if (setupState) loadSetup();
  } catch (err) { toast(err.message, true); }
}

function renderSetup() {
  const s = setupState;
  const g = googleState;
  document.getElementById("setup-checking").hidden = true;
  const google = document.getElementById("setup-google");
  const signin = document.getElementById("setup-signin");

  if (g.checking) {
    google.textContent = "Checking the Google sign-in…";
    signin.disabled = true;
  } else if (g.signingIn) {
    google.textContent = "Waiting for the Google sign-in in your browser…";
    signin.disabled = true;
    setTimeout(() => loadSetup(), 4000);
  } else if (g.loggedIn) {
    google.textContent = "Signed in. printit uses clasp's own sign-in and "
      + "never sees your password. Google expires these after a week or "
      + "two whether or not you use them \u2014 which matters only for "
      + "the steps on this page.";
    signin.disabled = true;
    signin.textContent = "Signed in";
  } else if (g.error) {
    google.textContent = "Could not check the sign-in: " + g.error;
    signin.disabled = true;
  } else {
    // Says what it actually blocks. It used to say "nothing here can
    // reach Google yet", which is false: pushing and pulling go
    // through the deployed web app and its secret, not through clasp.
    google.textContent = "Not signed in. Creating a form, deploying the "
      + "script and re-authorizing it all need this. Pushing and pulling "
      + "do not \u2014 those go through the web app address and its "
      + "secret, which do not expire.";
    signin.disabled = false;
    signin.textContent = "Sign in to Google";
  }

  /* Every button this view owns, every render. `runSetup` turns them all
     off while a call is in flight -- so that a second click cannot start a
     second form -- and if this did not turn them back on explicitly, they
     stayed off. That is how the authorization step ended up visible and
     unclickable. */
  const ready = Boolean(g.loggedIn);
  const need = Boolean(s.needsAuthorization);
  const live = {
    // Connecting needs a Google session; saying so beats failing three
    // clicks later.
    "setup-create": ready && !s.connected,
    "setup-inspect": ready && !s.connected,
    "setup-attach": ready && !s.connected && attachAllowed,
    // These two are plain HTTPS to the deployed script, so they do not
    // need clasp -- only something to authorize.
    "setup-authorize": need,
    "setup-authed": need,
    "setup-copy": need,
  };
  for (const [id, on] of Object.entries(live))
    document.getElementById(id).disabled = !on;

  document.getElementById("setup-have").hidden = !s.connected;
  document.getElementById("setup-new").hidden = s.connected;
  document.getElementById("setup-existing").hidden = s.connected;

  const auth = document.getElementById("setup-auth");
  auth.hidden = !need;
  if (need) {
    const notes = document.getElementById("setup-auth-notes");
    notes.textContent = "";
    for (const text of s.needsAuthorization.notes || []) {
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = text;
      notes.appendChild(p);
    }
    // The panel sits above Create, so pressing Create had scrolled the one
    // thing left to do off the top of the window.
    auth.scrollIntoView({ block: "center", behavior: "smooth" });
  } else {
    stopWaitingForAuth();
  }

  if (s.connected) renderConnection(s);
  renderSetupSaid(s.said);
}

function renderConnection(s) {
  const box = document.getElementById("setup-conn");
  box.textContent = "";
  const row = (label, value, mono) => {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = label + ": ";
    const v = document.createElement(mono ? "code" : "span");
    v.textContent = value || "—";
    p.appendChild(v);
    box.appendChild(p);
  };
  row("Form id", s.formId, true);
  row("Script id", s.scriptId, true);
  row("Web app", s.url, true);

  // The four slots as the same label/value rows as above, not a table: the
  // ids are long and unbroken, and a table of them set the page width.
  for (const [slot, what] of Object.entries(s.slots)) {
    const p = document.createElement("p");
    p.className = s.items[slot] ? "muted" : "warnline";
    const name = document.createElement("b");
    name.textContent = what;
    p.append(name, document.createTextNode(" — "));
    const v = document.createElement("code");
    v.textContent = s.items[slot] || "not on the form";
    p.appendChild(v);
    box.appendChild(p);
  }

  if (s.missing.length) {
    /* Not a step of its own: creating a form adds these. Seeing it means
       a create or an attach stopped part way -- almost always at Google's
       authorization -- so it is named for finishing that, not for a
       chore. */
    const p = document.createElement("p");
    p.className = "warnline";
    p.textContent = `Setup did not finish: ${s.missing.length} of the four `
      + `things printit writes to are not on the form yet, so a push and a `
      + `pull would both fail.`;
    box.appendChild(p);
    const add = document.createElement("button");
    add.className = "primary";
    add.textContent = "Finish setting up";
    add.onclick = () => runSetup("/api/setup/finish", {});
    box.appendChild(add);
  }
}

function renderSetupSaid(said) {
  const box = document.getElementById("setup-out");
  box.textContent = "";
  for (const line of said || []) {
    const p = document.createElement("p");
    p.className = line.startsWith("!") ? "warnline" : "muted";
    p.textContent = line;
    box.appendChild(p);
  }
}

let authTimer = null;

function stopWaitingForAuth() {
  if (authTimer) clearInterval(authTimer);
  authTimer = null;
  const note = document.getElementById("setup-authwait");
  if (note) note.hidden = true;
}

function waitForAuth() {
  /* Having granted the permission in another tab, there is nothing useful
     left for a person to tell us -- so the page asks for itself instead of
     making them come back and press a second button. `finish` is safe to
     repeat, which is what makes this allowed.

     Bounded: Google is being asked each time, and a page that polls for
     ever because somebody wandered off is its own small bug. */
  stopWaitingForAuth();
  const note = document.getElementById("setup-authwait");
  note.textContent = "checking…";
  note.hidden = false;
  let tries = 0;
  authTimer = setInterval(async () => {
    if (++tries > 24) {                       // two minutes
      stopWaitingForAuth();
      return;
    }
    let out;
    try {
      out = await api("/api/setup/finish",
                      { title: (setupState.needsAuthorization || {}).title
                               || "" });
    } catch { return; }                       // still refusing; keep waiting
    if (out.needsAuthorization) return;
    stopWaitingForAuth();
    setupState = out;
    renderSetup();
    toast("Connected");
  }, 5000);
}

async function openAuthorizationPage() {
  /* The server opens it, in the instructor's own default browser, where
     they are already signed in. `window.open` opens wherever the page is,
     and the page is often a pane with no Google session. */
  try {
    await api("/api/setup/authorize", {});
    toast("Opened in your browser — this page will notice when it works.");
    waitForAuth();
  } catch (err) { toast(err.message, true); }
}

/* The four scalars at the top of `course.toml`. Two of them print in the
   corner of every page and there was nowhere at all to set them, which
   is how a whole run shipped with a blank corner. */
const IDENTITY_FIELDS = ["name", "code", "semester", "professor"];

function identityInputs() {
  return IDENTITY_FIELDS.map(k => [k, document.getElementById(
    "course-" + k)]);
}

function fillIdentity(identity) {
  for (const [key, input] of identityInputs()) {
    input.value = (identity || {})[key] || "";
    input.dataset.saved = input.value;
    input.oninput = refreshIdentityDirty;
  }
  refreshIdentityDirty();
}

function refreshIdentityDirty() {
  const dirty = identityInputs().some(
    ([, i]) => i.value !== (i.dataset.saved || ""));
  saveBar("setup", dirty, "unsaved changes to this course");
}

/* Put the fields back to what is on disk. Setup had Save alone, so the
   only way out of a half-typed change was to remember what was there. */
function revertIdentity() {
  for (const [, input] of identityInputs()) input.value = input.dataset.saved || "";
  refreshIdentityDirty();
}

async function saveIdentity() {
  const body = {};
  for (const [key, input] of identityInputs()) body[key] = input.value.trim();
  try {
    const out = await api("/api/course/identity", body);
    fillIdentity(out.identity);
    toast("Saved");
  } catch (err) { toast(err.message, true); }
}

async function loadSetup() {
  try {
    setupState = await api("/api/setup", {});
  } catch (err) { toast(err.message, true); return; }
  fillIdentity(setupState.identity);
  setupState.said = setupState.said || [];
  // Drawn at once, from a file read: whether this course already has a
  // form is the thing that decides which buttons exist.
  renderSetup();

  // The same request the Form tab's banner uses. These were two calls
  // of six seconds each the first time the app was opened.
  googleState = { checking: true };
  renderSetup();
  try {
    googleState = await fetchGoogle();
  } catch (err) {
    googleState = { error: err.message };
  }
  renderSetup();
}

async function runSetup(path, body) {
  /* Every one of these talks to Google and takes a while, so the buttons
     go down for the duration rather than letting a second click start a
     second form. */
  const buttons = [...document.querySelectorAll("#view-setup button")];
  for (const b of buttons) b.disabled = true;
  try {
    setupState = await api(path, body);
    renderSetup();
    if (setupState.needsAuthorization) {
      // Straight there. The button existed because `window.open` needs a
      // click to get past a popup blocker; the server has no such
      // problem, so there is nothing for the instructor to do here.
      await openAuthorizationPage();
    } else if (setupState.connected) toast("Connected");
  } catch (err) {
    toast(err.message, true);
  } finally {
    // Whatever happened, the view decides what is live -- not the leftover
    // state of a call that may have thrown.
    renderSetup();
  }
}


async function inspectScript() {
  const box = document.getElementById("setup-inspected");
  box.textContent = "Looking…";
  try {
    const out = await api("/api/setup/inspect",
      { scriptId: document.getElementById("setup-script").value });
    box.textContent = "";
    const line = (text, cls) => {
      const p = document.createElement("p");
      p.className = cls || "muted";
      p.textContent = text;
      box.appendChild(p);
    };
    line(`That project holds ${out.files.length} file(s): `
         + out.files.join(", "));
    if (out.replaced.length)
      line("Attaching would overwrite: " + out.replaced.join(", "),
           "warnline");
    else
      line("Nothing of printit's is there yet, so nothing would be "
           + "overwritten.");
    if (out.kept.length)
      line("Left alone: " + out.kept.join(", "));
    attachAllowed = true;
    document.getElementById("setup-attach").disabled = false;
  } catch (err) {
    box.textContent = "";
    toast(err.message, true);
  }
}

// ------------------------------------------------------------ print job --

let printState = null;
let draft = null;          // the edited copy, before Save

/* The two jobs this tab can assemble. Which one is chosen decides what is
   on screen *and* what the job folder carries -- `publication_text` writes
   only the half that applies, so a saved job cannot say "everyone sits the
   same thing" and also hold per-student overrides. */
const MODE_LABELS = [
  ["chose", "Students chose",
   "Papers come from what each student asked for, with a default for "
   + "anyone who did not answer."],
  ["same", "Everyone sits the same thing",
   "One list, for the whole class. Individual choices do not apply."],
];

/* Who the run is for. A second row beside the skill modes and not a
 * third option within them: those decide *what* a student gets, this
 * decides *whether* they are in the run, and the two compose. Folded
 * together, printing for one student would have meant retyping the
 * skills they had already chosen on the form.
 */
const WHO_LABELS = [
  ["all", "the whole class",
   "Every student still enrolled."],
  ["these", "just the ones I tick",
   "A reprint for one or two. They still get whatever the mode above "
   + "says -- their own choices, or an override you type."],
];

function whoChosen() {
  return new Set(draft.only || []);
}

function isPrinting(student) {
  return draft.who !== "these" || whoChosen().has(student.key);
}

function setPrinting(student, on) {
  const chosen = whoChosen();
  if (on) chosen.add(student.key);
  else chosen.delete(student.key);
  draft.only = [...chosen];
  renderModes();
  renderWho();
  refreshPrintDirty();
}

const MODE_PICKERS = {
  chose: [
    ["default_when_missing", "Default when nobody chose",
     "What a student who chose nothing gets."],
    ["append_for_everyone", "Append for everyone",
     "Added on top of whatever each student ends with."],
  ],
  same: [
    ["simply_print", "What everyone gets",
     "Every paper is this list."],
  ],
};

/* Every version letter this run knows about: the chart's, plus any added
   from the table. A pin may name a letter the chart has never heard of --
   `assemble` draws seeds for whatever the pins name. */
function versionsInPlay() {
  const seen = new Set(printState.versionsAvailable || []);
  for (const v of Object.values(draft.versions)) if (v) seen.add(v);
  return [...seen].sort();
}

/* The letter after the highest in play, which is the one a dropdown offers
   to add. Next-after-highest rather than first-unused: filling a gap would
   offer C for a chart of A, B, D, which reads as a mistake rather than as
   a new version. */
function nextVersionLetter() {
  const highest = versionsInPlay().reduce((m, v) => (v > m ? v : m), "@");
  return highest >= "Z" ? "" : String.fromCharCode(highest.charCodeAt(0) + 1);
}

/* The version a student gets when this run does not move them. */
function seatedVersion(student) {
  return student.seatVersion || (printState.versionsAvailable || [])[0] || "A";
}

/* U+21BA. ⟲ (U+27F2) renders as an emoji on some systems and ⭯ is absent
   from most fonts; ↺ is the glyph in common use for reset. */
const RESET_GLYPH = "\u21BA";

function resetButton(title, onClick) {
  const b = document.createElement("button");
  b.type = "button";
  b.className = "reset";
  b.textContent = RESET_GLYPH;
  b.title = title;
  b.onclick = onClick;
  return b;
}

function printDirty() {
  return printState && JSON.stringify(draft) !== JSON.stringify(printState.draft);
}

function refreshPrintDirty() {
  saveBar("print", printDirty(), "unsaved changes to this run");
}

function skillPicker(selected, onChange) {
  /* Checkboxes, matching the Update form tab's list. A multi-select was
     tried first and was wrong twice: it needs ctrl-click to pick a second
     item, which nobody discovers, and it made the same choice look like a
     different kind of control than the one two tabs away. */
  const box = document.createElement("div");
  box.className = "skill-list short";
  for (const s of printState.skills) {
    const label = document.createElement("label");
    label.className = "skill";
    const tick = document.createElement("input");
    tick.type = "checkbox";
    tick.checked = selected.includes(s.slug);
    label.classList.toggle("on", tick.checked);
    tick.onchange = () => {
      const now = [...box.querySelectorAll("input:checked")]
        .map(i => i.dataset.slug);
      label.classList.toggle("on", tick.checked);
      onChange(now);
    };
    tick.dataset.slug = s.slug;
    const slug = document.createElement("span");
    slug.className = "slug";
    slug.textContent = s.slug;
    const desc = document.createElement("span");
    desc.className = "desc";
    // The name is what a row is for; the definition is what
    // hovering it is for. See 13.4.
    desc.textContent = s.title || s.slug;
    desc.title = s.description || "";
    label.append(tick, slug, desc);
    box.appendChild(label);
  }
  return box;
}

function renderModes() {
  const box = document.getElementById("modes");
  box.textContent = "";

  const head = document.createElement("div");
  head.className = "modehead";
  const lead = document.createElement("span");
  lead.className = "muted";
  lead.textContent = "This run:";
  const seg = document.createElement("div");
  seg.className = "segmented";
  let activeNote = "";
  for (const [value, label, why] of MODE_LABELS) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.title = why;
    b.setAttribute("aria-pressed", String(draft.mode === value));
    if (draft.mode === value) activeNote = why;
    b.onclick = () => {
      if (draft.mode === value) return;
      draft.mode = value;
      // The other half's lists are kept, not cleared, so switching back
      // restores them. They simply are not written into the job.
      renderModes();
      renderPullState();
      renderVariants();
      renderWho();
      refreshPrintDirty();
    };
    seg.appendChild(b);
  }
  head.append(lead, seg);
  const why = document.createElement("p");
  why.className = "muted";
  why.textContent = activeNote;
  box.append(head, why);

  // --- who it is for
  const whoHead = document.createElement("div");
  whoHead.className = "modehead";
  const whoLead = document.createElement("span");
  whoLead.className = "muted";
  whoLead.textContent = "Printing for:";
  const whoSeg = document.createElement("div");
  whoSeg.className = "segmented";
  let whoNote = "";
  for (const [value, label, note] of WHO_LABELS) {
    const b = document.createElement("button");
    b.type = "button";
    b.textContent = label;
    b.title = note;
    b.setAttribute("aria-pressed", String(draft.who === value));
    if (draft.who === value) whoNote = note;
    b.onclick = () => {
      if (draft.who === value) return;
      draft.who = value;
      // Switching on starts with everybody ticked, so the switch by
      // itself never changes what prints -- you then untick. Turning
      // it off clears the list rather than keeping it, because a list
      // left over from last week is one radio click from printing a
      // class set as a single sheet.
      draft.only = value === "these"
        ? printState.students.map(s => s.key) : [];
      renderModes();
      renderWho();
      refreshPrintDirty();
    };
    whoSeg.appendChild(b);
  }
  whoHead.append(whoLead, whoSeg);
  if (draft.who === "these") {
    const n = whoChosen().size;
    const all = printState.students.length;
    const count = document.createElement("span");
    count.className = n ? "muted" : "warnline";
    count.textContent = n ? `${n} of ${all} ticked` : "nobody ticked yet";
    const pick = (label, keys) => {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "act chip";
      b.textContent = label;
      b.onclick = () => {
        draft.only = keys();
        renderModes();
        renderWho();
        refreshPrintDirty();
      };
      return b;
    };
    whoHead.append(count,
                   pick("Tick all",
                        () => printState.students.map(s => s.key)),
                   pick("Untick all", () => []));
  }
  const whoWhy = document.createElement("p");
  whoWhy.className = "muted";
  whoWhy.textContent = whoNote;
  box.append(whoHead, whoWhy);

  for (const [key, label, note] of MODE_PICKERS[draft.mode]) {
    const wrap = document.createElement("div");
    wrap.className = "mode";
    const h = document.createElement("div");
    h.className = "mode-label";
    h.textContent = label;
    h.title = note;
    const n = document.createElement("div");
    n.className = "muted";
    n.textContent = note;
    wrap.append(h, n, skillPicker(draft[key], (picked) => {
      draft[key] = picked;
      renderVariants();
      renderWho();
      refreshPrintDirty();
    }));
    box.appendChild(wrap);
  }
}

function skillsInPlay() {
  /* Every slug this run could print: the three modes, each student's own
     choices or their override, and the extras. A variant only matters for a
     skill actually in the run. */
  const out = new Set();
  if (draft.mode === "same") {
    for (const slug of draft.simply_print) out.add(slug);
  } else {
    for (const slug of [...draft.append_for_everyone,
                        ...draft.default_when_missing]) out.add(slug);
    for (const s of printState.students) {
      for (const slug of (draft.overrides[s.key] || s.chose)) out.add(slug);
    }
  }
  for (const e of draft.extras) if (e.skill) out.add(e.skill);
  return [...out];
}

function renderVariants() {
  const panel = document.getElementById("variants-panel");
  const box = document.getElementById("variants");
  box.textContent = "";
  const relevant = skillsInPlay().filter(s => printState.variants[s]);
  panel.hidden = relevant.length === 0;
  for (const slug of relevant.sort()) {
    const label = document.createElement("label");
    label.textContent = slug;
    const sel = document.createElement("select");
    const none = document.createElement("option");
    none.value = "";
    none.textContent = "(any)";
    sel.appendChild(none);
    for (const option of printState.variants[slug]) {
      const o = document.createElement("option");
      o.value = o.textContent = option;
      sel.appendChild(o);
    }
    sel.value = draft.variants[slug] || "";
    sel.onchange = () => {
      if (sel.value) draft.variants[slug] = sel.value;
      else delete draft.variants[slug];
      refreshPrintDirty();
    };
    label.appendChild(sel);
    box.appendChild(label);
  }
  // A variant pinned for a skill no longer in the run would be carried into
  // publication.toml and refused at build time, so drop it as it leaves.
  for (const slug of Object.keys(draft.variants)) {
    if (!relevant.includes(slug)) delete draft.variants[slug];
  }
}

function renderExtras() {
  const box = document.getElementById("extras");
  box.textContent = "";
  draft.extras.forEach((extra, i) => {
    const row = document.createElement("div");
    row.className = "extra";
    const sel = document.createElement("select");
    for (const s of printState.skills) {
      const o = document.createElement("option");
      o.value = o.textContent = s.slug;
      o.selected = s.slug === extra.skill;
      sel.appendChild(o);
    }
    sel.onchange = () => { extra.skill = sel.value; renderVariants(); refreshPrintDirty(); };
    const n = document.createElement("input");
    n.type = "number"; n.min = "1"; n.max = "99"; n.value = extra.copies;
    n.onchange = () => { extra.copies = Number(n.value || 1); refreshPrintDirty(); };
    const rm = document.createElement("button");
    rm.className = "act";
    rm.textContent = "Remove";
    rm.onclick = () => { draft.extras.splice(i, 1); renderExtras(); renderVariants(); refreshPrintDirty(); };
    row.append(sel, n, document.createTextNode(" copies"), rm);
    box.appendChild(row);
  });
  // The count rides the header row, right-aligned, with no dash joining
  // it to the name: a heading is a name, not a sentence.
  const sheets = draft.extras.reduce((a, e) => a + Number(e.copies || 0), 0);
  document.getElementById("extras-count").textContent =
    sheets ? `${sheets} sheet${sheets === 1 ? "" : "s"}` : "";
}

function willGet(student) {
  /* The same composition `roster.apply_selection_modes` does, so the table
     says what will actually print. An override replaces the student's own
     choices and nothing else -- the modes still apply on top. */
  if (draft.mode === "same") return [...draft.simply_print];
  let chosen = draft.overrides[student.key] || student.chose;
  if (!chosen.length) chosen = draft.default_when_missing;
  const out = [...chosen];
  for (const s of draft.append_for_everyone) if (!out.includes(s)) out.push(s);
  return out;
}

/* Which day a student's choices were made for, against the day this job
   prints.

   `chose` on its own cannot be told from last week's `chose`. On
   2026-10-23 the roster still held 10/16's answers -- identical to what
   had printed that day -- because the assessment date had not been moved
   on, so every pull re-fetched the same responses and this table showed
   them with complete confidence. The same thing had happened on 10/16.

   "unknown" is its own answer and is never drawn as agreement: a roster
   written before `chose_for` existed has choices and no date, and
   colouring those as current would make the whole thing decorative. */
function choiceAge(student) {
  if (!student.chose.length) return "none";
  if (!student.choseFor) return "unknown";
  return student.choseFor === (draft.date || "") ? "current" : "stale";
}

function spokenDay(iso) {
  // Matches the form's own phrasing, `Friday, 10/16`, because that is
  // the wording on the confirmation the student actually ticked.
  if (!iso) return "";
  const [y, m, d] = iso.split("-").map(Number);
  if (!y || !m || !d) return iso;
  const days = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday",
                "Friday", "Saturday"];
  return `${days[new Date(y, m - 1, d).getDay()]}, ${m}/${d}`;
}

function badSlugs(slugs) {
  const known = new Set(printState.skills.map(s => s.slug));
  return slugs.filter(s => !known.has(s));
}

function renderStale() {
  /* Two different wrongnesses, reported separately because they are
     fixed differently.

     The assessment date disagreeing with the job date is the *cause*:
     a pull scopes by the assessment, so while those differ it keeps
     fetching the wrong week however many times you press it. Fixing
     that is a Setup edit, and it comes first.

     Rows carrying another day's answers are the *symptom*, and can
     outlive the cause -- the date can be corrected and 26 people still
     hold last week's picks until the next pull lands. */
  const strip = document.getElementById("who-stale");
  strip.textContent = "";
  const lines = [];

  const av = (printState.assessment || {}).date || "";
  if (av && draft.date && av !== draft.date) {
    lines.push(`This job is for ${spokenDay(draft.date)}, but the course `
               + `says the next assessment is ${spokenDay(av)}. A pull `
               + `scopes by the assessment, so it will keep fetching `
               + `${spokenDay(av)} until that is changed on Update form.`);
  }

  const counts = { stale: 0, unknown: 0 };
  for (const student of printState.students) {
    if (draft.overrides[student.key]) continue;
    const age = choiceAge(student);
    if (age in counts) counts[age] += 1;
  }
  if (counts.stale) {
    lines.push(`${counts.stale} student${counts.stale === 1 ? "'s" : "s'"} `
               + `choices were made for another day.`);
  }
  if (counts.unknown) {
    lines.push(`${counts.unknown} student${counts.unknown === 1 ? "" : "s"} `
               + `${counts.unknown === 1 ? "has" : "have"} choices the `
               + `roster cannot date. They were written before printit `
               + `recorded this; pull again to date them.`);
  }

  // Silent when nothing is at stake -- the rule the cross-tab warning
  // had to learn. In "same" mode nobody's own choices are used at all,
  // so none of this applies.
  if (!lines.length || draft.mode === "same") { strip.hidden = true; return; }
  for (const text of lines) {
    const p = document.createElement("span");
    p.textContent = text;
    strip.appendChild(p);
  }
  strip.hidden = false;
}

function renderWho() {
  const body = document.querySelector("#who tbody");
  body.textContent = "";
  // The column only exists while the run names its students. Forty-three
  // permanently-ticked boxes would be furniture.
  const picking = draft.who === "these";
  document.getElementById("who-pick-head").hidden = !picking;
  let papers = 0;
  let getting = 0;
  for (const student of printState.students) {
    const gets = willGet(student);
    const printing = isPrinting(student);
    // A student who is not in the run contributes no paper, however
    // many skills they chose. Counting them would make the header
    // promise pages the build will not produce.
    if (printing) {
      papers += gets.length;
      if (gets.length) getting += 1;
    }
    const tr = document.createElement("tr");
    tr.classList.toggle("notprinting", !printing);
    if (picking) {
      const td = document.createElement("td");
      td.className = "pickcell";
      const box = document.createElement("input");
      box.type = "checkbox";
      box.checked = printing;
      box.setAttribute("aria-label", `print for ${student.display}`);
      box.onchange = () => setPrinting(student, box.checked);
      td.appendChild(box);
      tr.appendChild(td);
    }
    const add = (text, cls) => {
      const td = document.createElement("td");
      td.textContent = text;
      if (cls) td.className = cls;
      tr.appendChild(td);
      return td;
    };
    // `display` is the printed name; `name` is still what identifies the
    // student in the roster file, so it stays on hover.
    const nameCell = add(student.display);
    if (student.display !== student.name) nameCell.title = student.name;
    add(student.section, "ro");

    // Version. The seat's letter unless this run moves them -- and the
    // seat's letter is simply the one selected, not a second entry above
    // the list. Showing it twice said nothing the outline does not.
    const seated = seatedVersion(student);
    const moved = Boolean(student.version) && student.version !== seated;
    const vtd = document.createElement("td");
    const vwrap = document.createElement("div");
    vwrap.className = "cellwrap";
    const vsel = document.createElement("select");
    vsel.className = "vpick";
    for (const letter of versionsInPlay()) {
      const o = document.createElement("option");
      o.value = letter;
      o.textContent = letter;
      vsel.appendChild(o);
    }
    const next = nextVersionLetter();
    if (next) {
      const add = document.createElement("option");
      add.value = ADD_VERSION;
      add.textContent = "+ " + next;
      add.title = `Add version ${next} and put this student on it.`;
      vsel.appendChild(add);
    }
    vsel.value = student.version || seated;
    vsel.classList.toggle("moved", moved);
    vsel.title = moved
      ? `Moved to ${student.version} for this run; the seat gives ${seated}.`
      : `The version this seat gives. Change it for this run only.`;
    vsel.onchange = () => {
      const picked = vsel.value === ADD_VERSION ? nextVersionLetter() : vsel.value;
      // Choosing the seat's own letter is not a move, so it clears the pin
      // rather than recording one that changes nothing.
      if (picked && picked !== seated) draft.versions[student.key] = picked;
      else delete draft.versions[student.key];
      student.version = draft.versions[student.key] || "";
      renderWho();
      refreshPrintDirty();
    };
    vwrap.appendChild(vsel);
    const vreset = resetButton(`Back to ${seated}, the seat's version.`, () => {
      delete draft.versions[student.key];
      student.version = "";
      renderWho();
      refreshPrintDirty();
    });
    // Hidden rather than absent, so the column does not resize as rows
    // move on and off their default.
    vreset.classList.toggle("off", !moved);
    vwrap.appendChild(vreset);
    vtd.appendChild(vwrap);
    tr.appendChild(vtd);

    // The cell says what they get; its mark says whether that is this
    // run's answer. An override is the instructor's own decision for
    // this job, so it is never stale whatever the roster holds.
    const getsCell = add(gets.join(", ") || "—");
    const age = draft.overrides[student.key] ? "current" : choiceAge(student);
    if (age === "stale" || age === "unknown") {
      // Not `age` itself: `stale` is already the page-is-older-than-the-
      // server banner, `position: fixed` with a warn background, so
      // `td.aged.stale` lifted one table cell out of the table and
      // parked it at the bottom of the window. Fourth class collision
      // in this app and the first inside a single stylesheet.
      getsCell.classList.add("aged", age === "stale" ? "otherday" : "nodate");
      getsCell.appendChild(document.createTextNode(" "));
      const mark = document.createElement("span");
      mark.className = "agemark";
      mark.textContent = age === "stale"
        ? spokenDay(student.choseFor) : "undated";
      getsCell.appendChild(mark);
      getsCell.title = age === "stale"
        ? `Chosen for ${spokenDay(student.choseFor)}, not `
          + `${spokenDay(draft.date) || "this run"}. Pull again, or `
          + `override.`
        : `The roster does not say which assessment this was chosen `
          + `for. Pull again to date it.`;
    }

    const td = document.createElement("td");
    // Paired with the heading's class: one rule hides both, which is
    // what stops a hidden column shifting the ones after it.
    td.className = "overridecell";
    const owrap = document.createElement("div");
    owrap.className = "cellwrap";
    const input = document.createElement("input");
    input.value = (draft.overrides[student.key] || []).join(", ");
    input.placeholder = student.chose.join(", ") || "nothing chosen";
    input.spellcheck = false;
    const check = () => {
      const slugs = input.value.split(",").map(s => s.trim()).filter(Boolean);
      const bad = badSlugs(slugs);
      input.classList.toggle("bad", bad.length > 0);
      // Named as you type, because "W9" and "W4" differ by one key and the
      // build would only say so after writing a job folder.
      input.title = bad.length ? "not in the bank: " + bad.join(", ") : "";
      return slugs;
    };
    input.oninput = check;
    input.onchange = () => {
      const slugs = check();
      if (slugs.length) draft.overrides[student.key] = slugs;
      else delete draft.overrides[student.key];
      renderVariants();
      renderWho();
      refreshPrintDirty();
    };
    check();
    owrap.appendChild(input);
    // Beside the box rather than inside it: an overlay would sit on top of
    // the text it is there to clear, and the two columns read the same
    // when their controls are in the same place.
    const oreset = resetButton("Clear this override; use what they chose.",
      () => {
        delete draft.overrides[student.key];
        renderVariants();
        renderWho();
        refreshPrintDirty();
      });
    oreset.classList.toggle("off", !(draft.overrides[student.key] || []).length);
    owrap.appendChild(oreset);
    td.appendChild(owrap);
    tr.appendChild(td);
    body.appendChild(tr);
  }
  // Hidden by one rule covering the heading and the cells together: a
  // rule that hid cells and left the heading once made every column after
  // it read one place to the left.
  document.getElementById("who").classList.toggle("hide-override",
                                                  draft.mode === "same");
  const movedCount = Object.keys(draft.versions).length;
  const overrideCount = Object.keys(draft.overrides).length;
  /* Two counts as two chips, not a sentence. "44 papers for 44
     students" is grammar doing a label's job; 13.4's own answer for
     facts that are peers is small grouped pills, and this is the case
     it was written for. The moved-version count went to the Version
     column's own reset, which is the thing it is about. */
  const count = document.getElementById("who-count");
  count.textContent = "";
  if (!papers) {
    count.textContent = "nothing to print yet";
  } else {
    for (const [n, word] of [[papers, "paper"], [getting, "student"]]) {
      const chip = document.createElement("span");
      chip.className = "chip";
      chip.textContent = `${n} ${word}${n === 1 ? "" : "s"}`;
      count.appendChild(chip);
    }
  }
  renderStale();
  // One reset per column, shown on the same condition as the row ones.
  const vreset = document.getElementById("reset-versions");
  vreset.title = movedCount
    ? `${movedCount} student${movedCount === 1 ? " is" : "s are"} not on `
      + `their seat's version. Put them all back.`
    : "Put every student back on their seat's version.";
  vreset.classList.toggle("off", !movedCount);
  document.getElementById("reset-overrides").classList.toggle("off", !overrideCount);
}

function renderPullState() {
  /* The card is always on the tab. It used to hide itself when the course
     had no form and when the mode was "same", and with Responses gone from
     the nav that left no trace of the feature anywhere -- on the course
     the instructor actually had open, both were true. */
  const why = document.getElementById("pull-why");
  const connected = Boolean(printState.hasForm);
  for (const id of ["pull-run", "pull-dry"])
    document.getElementById(id).disabled = !connected;

  if (!connected) {
    why.textContent = "";
    why.append(document.createTextNode(
      "This course has no Google Form connected, so there is nothing to "
      + "pull yet. "));
    // Was two CLI commands, which is the thing this app exists to stop
    // anyone having to know.
    const go = document.createElement("button");
    go.className = "act";
    go.textContent = "Connect one in Setup";
    go.onclick = () => show("setup");
    why.appendChild(go);
    why.hidden = false;
    return;
  }
  // Worth saying, not worth hiding over: a pull writes choices into the
  // roster, which outlives this run, so it is still the right thing to do
  // on a day the whole class sits the same paper.
  why.hidden = draft.mode !== "same";
  why.textContent = "This run prints one list for everyone, so these "
    + "choices will not change today's papers. They are kept on the roster "
    + "for the next run that uses them.";
}

function renderPull(data) {
  /* What the pull found, and every reason a student might not get the
     paper they asked for. The per-student choices are deliberately not
     repeated here -- the table below is the view of those, which is why
     this is a card and not a tab. */
  const box = document.getElementById("pull-out");
  box.textContent = "";
  if (!data) return;
  const line = (text, cls) => {
    const p = document.createElement("p");
    p.className = cls || "";
    p.textContent = text;
    box.appendChild(p);
  };

  const when = data.spokenDate || data.date || "this assessment";
  line(`${data.total} response(s) on the form; `
       + `${data.answered} are for ${data.assessment || "this assessment"} `
       + `on ${when}, and are in the table below.`);
  if (!data.knownFromBank)
    line("This course names no bank, so only the open skills were "
         + "recognised.", "muted");
  if (data.silent.length)
    line(`${data.silent.length} did not answer; they get whatever `
         + `"Default when nobody chose" says.`, "muted");

  if (data.unknownEmails.length) {
    line(`${data.unknownEmails.length} response(s) came from an address `
         + `nobody on the roster has:`, "warnline");
    for (const address of data.unknownEmails) line("    " + address, "muted");
    line("Add the address to that student on the Roster tab, or check for "
         + "a typo.", "muted");
  }
  if (data.unrecognised.length) {
    line(`${data.unrecognised.length} answer(s) name a skill the bank `
         + `does not have:`, "warnline");
    for (const r of data.unrecognised)
      line(`    ${r.email}: ${r.option.slice(0, 60)}`, "muted");
  }
  for (const [n, text] of [
    [data.unconfirmed, "confirmed no date, so they belong to no assessment"],
    [data.outOfScope, "are for another day"],
    [data.superseded, "were superseded by a later answer from the same student"],
  ]) if (n) line(`${n} response(s) ${text}`, "muted");

  if (data.written) {
    line("The roster was updated.", "muted");
  } else if (data.trouble) {
    line("Nothing was written, because some responses could not be placed.",
         "warnline");
    const again = document.createElement("button");
    again.textContent = "Write the rest anyway";
    again.title = "Save the responses that did match, and leave the rest.";
    again.onclick = () => runPull({ write: true, force: true });
    box.appendChild(again);
  } else {
    line("Nothing was written -- this was a check.", "muted");
  }
}

async function runPull(body) {
  const buttons = ["pull-run", "pull-dry"].map(id => document.getElementById(id));
  for (const b of buttons) b.disabled = true;
  try {
    const out = await api("/api/print/pull", body);
    // A pull rewrites the roster, and the table below is showing it. The
    // draft is left alone: this changed what students chose, not what the
    // instructor has been assembling.
    printState.students = out.print.students;
    printState.hasForm = out.print.hasForm;
    renderPullState();
    renderPull(out.pull);
    renderVariants();
    renderWho();
    toast(out.pull.written ? "Pulled" : "Checked — nothing written");
  } catch (err) {
    renderPull(null);
    toast(err.message, true);
  } finally {
    for (const b of buttons) b.disabled = false;
  }
}

function renderPrintFields() {
  const f = {
    title: document.getElementById("p-title"),
    date: document.getElementById("p-date"),
    keys: document.getElementById("p-keys"),
    key_copies: document.getElementById("p-key-copies"),
    names: document.getElementById("p-names"),
    ids: document.getElementById("p-ids"),
    codes: document.getElementById("p-codes"),
  };
  f.title.value = draft.title || "";
  f.date.value = draft.date || "";
  f.keys.checked = Boolean(draft.keys);
  f.key_copies.value = draft.key_copies || 1;
  f.names.checked = Boolean(draft.names);
  // `!== false` rather than Boolean(): a draft written before these
  // existed has neither key, and both marks were on in every run it
  // describes. Reading absent as off would silently drop them.
  f.ids.checked = draft.ids !== false;
  f.codes.checked = draft.codes !== false;
  document.getElementById("p-keycopies-wrap").hidden = !draft.keys;
  for (const [key, input] of Object.entries(f)) {
    input.oninput = input.onchange = () => {
      draft[key] = input.type === "checkbox" ? input.checked
                 : input.type === "number" ? Number(input.value || 1)
                 : input.value;
      document.getElementById("p-keycopies-wrap").hidden = !draft.keys;
      refreshPrintDirty();
    };
  }
}

function renderBuild(out) {
  const box = document.getElementById("build-out");
  box.textContent = "";
  const line = (text, cls) => {
    const p = document.createElement("p");
    p.className = cls || "";
    p.textContent = text;
    box.appendChild(p);
  };
  line(`${out.students} students, ${out.skills.length} skill(s): `
       + out.skills.join(", "));
  line(`${out.versions} distinct papers, ${out.keys} key page(s)`
       + (out.extras ? `, ${out.extras} spare(s)` : ""));
  // Not a prediction: a build draws again unless given this number, which
  // is why it is carried across rather than shown and forgotten.
  line(out.preview
    ? `seed ${out.seed} — the build below will reuse it, so what you see is `
      + `what you get`
    : `seed ${out.seed} — pass it to --seed to reproduce this run`, "muted");

  const table = document.createElement("table");
  table.className = "seeds";
  for (const s of out.seeds) {
    const tr = document.createElement("tr");
    for (const v of [s.version, s.slug, "v" + s.seed]) {
      const td = document.createElement("td");
      td.textContent = v;
      tr.appendChild(td);
    }
    table.appendChild(tr);
  }
  box.appendChild(table);

  if (out.headerGaps && out.headerGaps.length) {
    line(`This course has no ${out.headerGaps.join(" and no ")}, so the top `
         + `right corner of every page prints blank. Set them in Setup.`,
         "warnline");
  }
  for (const c of out.collisions) line(c, "warnline");
  if (out.unmatchedOverrides && out.unmatchedOverrides.length)
    line("override(s) for " + out.unmatchedOverrides.join(", ")
         + " matched nobody in the roster, so nothing changed for them",
         "warnline");
  if (out.anonymous)
    line("Names and the ID field are both off, so nothing on these papers "
         + "says who sat them. Scans will read the code and find the skill, "
         + "and have no way to attribute the paper to anybody.", "warnline");
  if (out.unseated.length)
    line("not in the seating chart, printed last: " + out.unseated.join(", "),
         "warnline");
  for (const [slug, fields] of Object.entries(out.missingFields))
    line(`note: ${slug}'s template asked for ${fields.join(", ")}, which its `
         + `generator does not set.`, "muted");

  if (out.preview) {
    line("Nothing was written.", "muted");
  } else {
    line("PDF: " + out.pdf);
    if (out.recorded) line(`${out.recorded} paper(s) recorded`, "muted");
    if (out.recordError) line("could not write the print record: "
                              + out.recordError, "warnline");
    const reveal = document.getElementById("p-reveal");
    reveal.hidden = false;
    reveal.onclick = async () => {
      try { await api("/api/print/reveal", { path: out.out }); }
      catch (err) { toast(err.message, true); }
    };
  }
}

let lastSeed = null;
let rosterNews = null;
const ADD_VERSION = "\u0000add";

async function runPrint(which) {
  if (printDirty()) {
    toast("Save first — the build reads the file, not the screen.", true);
    return;
  }
  const btn = document.getElementById(which === "build" ? "p-build" : "p-preview");
  const was = btn.textContent;
  btn.disabled = true;
  btn.textContent = which === "build" ? "Building…" : "Drawing…";
  try {
    // A build reuses the previewed seed, so the papers are the ones just
    // shown. Without that they are drawn independently and the preview
    // proved nothing about what shipped.
    const body = which === "build" && lastSeed !== null ? { seed: lastSeed } : {};
    const out = await api("/api/print/" + which, body);
    lastSeed = out.seed;
    renderBuild(out);
    toast(which === "build" ? "Built" : "Drawn — nothing written");
  } catch (err) {
    toast(err.message, true);
  } finally {
    btn.disabled = false;
    btn.textContent = was;
  }
}

function peopleByKey(students) {
  const out = {};
  for (const s of students) out[s.key] = s;
  return out;
}

/* What the Roster changed while this tab was away. Counted rather than
   listed: the point is to explain why a row looks different, and a list of
   names on screen is a list of names on screen. */
function rosterChanges(before, after) {
  const was = peopleByKey(before), now = peopleByKey(after);
  const news = { names: 0, sections: 0, added: 0, removed: 0 };
  for (const [key, s] of Object.entries(now)) {
    if (!(key in was)) { news.added++; continue; }
    if (was[key].display !== s.display) news.names++;
    if (was[key].section !== s.section) news.sections++;
  }
  for (const key of Object.keys(was)) if (!(key in now)) news.removed++;
  news.total = news.names + news.sections + news.added + news.removed;
  return news;
}

async function loadPrint() {
  const before = printState ? printState.students : null;
  // Unsaved work survives a reload: `printDirty` compares the local draft
  // with the saved file, so replacing the file's copy and keeping the
  // local one leaves that comparison correct.
  const keepDraft = printState !== null && printDirty();
  let next;
  try {
    next = await api("/api/print");
  } catch (err) { toast(err.message, true); return; }
  printState = next;
  if (!keepDraft) draft = JSON.parse(JSON.stringify(printState.draft));
  rosterNews = before ? rosterChanges(before, printState.students) : null;

  const blocked = document.getElementById("print-blocked");
  const why = !printState.hasRoster
    ? "This course has no roster yet, so there is nobody to print for."
    : !printState.hasBank
    ? "This course names no bank, so there are no skills to print."
    : "";
  blocked.textContent = why;
  blocked.hidden = !why;
  document.getElementById("p-preview").disabled = Boolean(why);
  document.getElementById("p-build").disabled = Boolean(why);

  renderFormBar("print-conn-bar", printState.form);
  renderPrintFields();
  renderModes();
  renderPullState();
  renderPull(null);
  renderVariants();
  renderExtras();
  renderWho();
  renderRosterNews();
  refreshPrintDirty();
}

function renderRosterNews() {
  const el = document.getElementById("print-news");
  const n = rosterNews;
  if (!n || !n.total) { el.hidden = true; return; }
  const plural = (k, one, many) => `${k} ${k === 1 ? one : many}`;
  const bits = [];
  if (n.names) bits.push(plural(n.names, "name", "names"));
  if (n.sections) bits.push(plural(n.sections, "section", "sections"));
  if (n.added) bits.push(plural(n.added, "student added", "students added"));
  if (n.removed) bits.push(plural(n.removed, "no longer listed",
                                  "no longer listed"));
  el.textContent = "From Roster since this tab last opened: "
                 + bits.join(", ") + ". Already shown below.";
  el.hidden = false;
}

async function savePrint() {
  try {
    printState = await api("/api/print/save",
      { draft: { ...draft, versionsAvailable: printState.versionsAvailable } });
    draft = JSON.parse(JSON.stringify(printState.draft));
    renderPrintFields();
    renderModes();
    renderVariants();
    renderExtras();
    renderWho();
    // Saved, so there is nothing left to explain about the other tab.
    rosterNews = null;
    renderRosterNews();
    refreshPrintDirty();
    // The draw depends on the file, so a save invalidates a previewed seed.
    lastSeed = null;
    toast("Saved");
  } catch (err) { toast(err.message, true); }
}

function resetPrint() {
  /* An ordinary edit, not a second way to write the file: it fills the
     local draft with the server's defaults and leaves saving to Save, so
     Discard still undoes it. */
  draft = JSON.parse(JSON.stringify(printState.defaults));
  renderPrintFields();
  renderModes();
  renderVariants();
  renderExtras();
  renderWho();
  refreshPrintDirty();
  toast("Reset — Save to keep it, Discard to put it back.");
}

function revertPrint() {
  draft = JSON.parse(JSON.stringify(printState.draft));
  renderPrintFields();
  renderModes();
  renderVariants();
  renderExtras();
  renderWho();
  refreshPrintDirty();
  toast("Discarded");
}



// ----------------------------------------------------------------- boot --

async function boot() {
  buildNav();
  document.getElementById("save").onclick = save;
  document.getElementById("revert").onclick = revert;
  document.getElementById("skills-save").onclick = saveSkills;
  document.getElementById("skills-revert").onclick = revertSkills;
  document.getElementById("skills-none").onclick = () => {
    openNow.clear(); renderSkills(); refreshPreview();
  };
  document.getElementById("form-push").onclick = pushForm;
  document.getElementById("scans-save").onclick = saveScans;
  document.getElementById("cell-close").onclick = () => {
    cellOpen = null;
    document.getElementById("cell").close();
  };
  document.getElementById("cell").addEventListener("close", () => {
    cellOpen = null;
  });
  document.getElementById("progress-recent").onchange = (e) => {
    lightRecent = e.target.checked;
    renderProgress();
  };
  document.getElementById("print-save").onclick = savePrint;
  document.getElementById("print-revert").onclick = revertPrint;
  const preset = document.getElementById("print-reset");
  preset.appendChild(icon("reset"));
  preset.onclick = resetPrint;
  document.getElementById("setup-signin").onclick = signInToGoogle;
  document.getElementById("course-save").onclick = saveIdentity;
  document.getElementById("course-revert").onclick = revertIdentity;
  document.getElementById("setup-create").onclick = () =>
    runSetup("/api/setup/create", {
      title: document.getElementById("setup-title").value,
      folder: document.getElementById("setup-folder").value });
  document.getElementById("setup-authorize").onclick = openAuthorizationPage;
  document.getElementById("setup-copy").onclick = async () => {
    const need = setupState && setupState.needsAuthorization;
    if (!need) return;
    try {
      await navigator.clipboard.writeText(need.url);
      toast("Link copied.");
    } catch {
      // Clipboard access can be refused, and a dead button is worse than
      // a visible link.
      const box = document.getElementById("setup-auth-notes");
      const p = document.createElement("p");
      p.className = "muted";
      p.style.overflowWrap = "anywhere";
      p.textContent = need.url;
      box.prepend(p);
    }
    waitForAuth();
  };
  document.getElementById("setup-authed").onclick = () =>
    runSetup("/api/setup/finish",
             { title: (setupState.needsAuthorization || {}).title || "" });
  document.getElementById("setup-inspect").onclick = inspectScript;
  document.getElementById("setup-attach").onclick = () =>
    runSetup("/api/setup/attach",
             { scriptId: document.getElementById("setup-script").value });
  document.getElementById("setup-script").oninput = () => {
    // Looking is required before attaching, not merely advised: the push
    // replaces files in somebody else's script project.
    attachAllowed = false;
    document.getElementById("setup-attach").disabled = true;
    document.getElementById("setup-inspected").textContent = "";
  };
  document.getElementById("pull-run").onclick =
    () => runPull({ write: true });
  document.getElementById("pull-dry").onclick =
    () => runPull({ write: false });
  document.getElementById("reset-versions").onclick = () => {
    draft.versions = {};
    for (const s of printState.students) s.version = "";
    renderWho();
    refreshPrintDirty();
  };
  document.getElementById("reset-overrides").onclick = () => {
    draft.overrides = {};
    renderVariants();
    renderWho();
    refreshPrintDirty();
  };
  document.getElementById("p-preview").onclick = () => runPrint("preview");
  document.getElementById("p-build").onclick = () => runPrint("build");
  document.getElementById("extras-add").onclick = () => {
    draft.extras.push({ skill: printState.skills[0].slug, copies: 1 });
    renderExtras(); renderVariants(); refreshPrintDirty();
  };

  // The table resizes with the window, and `sizeColumns` only runs on a
  // render. Without this, widening the window left the old widths and
  // the spare room stayed spare.
  NARROW_RAIL.addEventListener("change", applyRail);

  let resizing = null;
  window.addEventListener("resize", () => {
    clearTimeout(resizing);
    resizing = setTimeout(() => {
      if (!document.getElementById("view-roster").hidden) renderRoster();
    }, 120);
  });
  // Every `?` works the same way, so one delegated listener rather than
  // one per section -- a section added later gets the behaviour for
  // free instead of needing to be remembered here.
  document.addEventListener("click", (e) => {
    const btn = e.target.closest(".hint");
    if (!btn) return;
    // An annotated section scopes its own explanation; a page header's
    // belongs to the whole view, which has only one. `.annot` is listed
    // first so the Print tab's three do not all find each other.
    const text = btn.closest(".annot, .view")?.querySelector(".hint-text");
    if (!text) return;
    const open = btn.getAttribute("aria-expanded") === "true";
    btn.setAttribute("aria-expanded", String(!open));
    text.hidden = open;
  });

  window.onbeforeunload = (e) => { if (edits.size) e.preventDefault(); };

  // Back and forward change the hash without reloading, so without this
  // they appear to do nothing at all -- the URL moves and the page does
  // not, which reads as the app being stuck.
  window.addEventListener("hashchange", () => {
    const id = location.hash.slice(1);
    if (id === shownView) return;          // our own write, echoing back
    if (VIEWS.some(v => v.id === id)) show(id);
  });

  try {
    renderOverview(await api("/api/course"));
  } catch (err) { toast(err.message, true); }

  try {
    students = (await api("/api/roster")).students;
    renderRoster();
  } catch (err) {
    document.getElementById("roster-empty").hidden = false;
    document.getElementById("roster-empty").textContent = err.message;
  }

  // **Both slow calls start now, and neither is awaited.** The Roster is
  // already on screen above, so this costs the opening view nothing, and
  // by the time Update form or Setup is clicked the answers are usually
  // in. Failures are deliberately swallowed here: the tab that needs the
  // answer reports it, and a toast at boot about a tab nobody has opened
  // is noise.
  fetchSkills().then(() => {
    // Opened via #form before the fetch finished: draw it now.
    if (!skillsDrawn && !document.getElementById("view-form").hidden) {
      loadSkills();
    }
  }).catch(() => {});
  fetchGoogle().then(() => {
    if (!document.getElementById("view-form").hidden) refreshGoogle();
  }).catch(() => {});

  show(VIEWS.some(v => v.id === location.hash.slice(1))
       ? location.hash.slice(1) : "roster");
}

boot();
