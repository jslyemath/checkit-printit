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
  { id: "record", label: "Record", short: "Record", icon: "record", soon: "What has been printed, to whom, at which seed. Today: `record runs`, `record student`, `record skills`." },
  { id: "seating", label: "Seating", short: "Seats", icon: "seating" },
  { id: "setup", label: "Setup", short: "Setup", icon: "setup", foot: true },
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
  setup: "M4 7.4h9.2M17.2 7.4h2.8M4 16.6h3.6M11.6 16.6h8.4"
    + "M15.2 5.2v4.4M9.2 14.4v4.4",
  collapse: "M14.5 7.5 9.5 12l5 4.5",
  // Points up while a group is open; CSS turns it when it closes.
  chev: "M6 14.5l6-6 6 6",
  // Two ways round, from Seating, where it already means exactly this.
  swapby: "M4 8h13l-3-3M20 16H7l3 3",

  /* A doorway with an arrow through it: leaving the class to drop,
     coming back in to restore. The frame and the door panel stay put
     and only the arrow turns, so the pair is one idea with a
     direction.

     Two earlier attempts were worse. A person with a minus sign loses
     the minus at this size, and the minus is the whole meaning. A
     chair with an arrow -- Seating's own, so at least honest about
     emptying a seat -- was too many strokes in 18px and read as a
     shape with an arrow.

     Not a bin, ever: dropping deletes nobody, and it is an unkind
     picture of a person. */
  drop: [{ r: [13.5, 3, 7.5, 18, 1.6] },
         { d: "M10.5 3H5.2A1.2 1.2 0 0 0 4 4.2v15.6A1.2 1.2 0 0 0 5.2 21h5.3"
              + "M6.5 12h6.2M10 8.8l3.2 3.2-3.2 3.2" }],
  restore: [{ r: [13.5, 3, 7.5, 18, 1.6] },
            { d: "M10.5 3H5.2A1.2 1.2 0 0 0 4 4.2v15.6A1.2 1.2 0 0 0 5.2 21h5.3"
                 + "M12.7 12H6.5M9.7 8.8L6.5 12l3.2 3.2" }],
  /* An arrow coming back round to where it started. */
  reset: "M19.4 12a7.4 7.4 0 1 1-2.2-5.3M19.6 4.4v4.2h-4.2",
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
    if (part.r) {
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
    if (id === "seating") loadSeating();
  }
  shownView = id;
  location.hash = id;
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
  const n = edits.size;
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
      reset.className = "iconbtn undo";
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
  const active = sortRoster(students.filter(s => !s.dropped));
  const dropped = sortRoster(students.filter(s => s.dropped));

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
    if (student.dropped) tr.className = "dropped";

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
        b.className = "iconbtn" + (student.dropped ? " undo" : "");
        b.appendChild(icon(student.dropped ? "restore" : "drop"));
        b.title = student.dropped
          ? "Put this student back on the roster."
          : "Drop this student. They stay on the roster, greyed out, and "
            + "print nothing.";
        b.setAttribute("aria-label", b.title);
        b.onclick = () => drop(student, !student.dropped);
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

async function drop(student, dropped) {
  if (edits.size) {
    toast("Save or discard your edits first — dropping rewrites the file.", true);
    return;
  }
  /* **No `confirm()`.** It is a blocking native dialog, and the desktop
     app's browser pane suppresses it: the handler ran, the dialog never
     appeared, and the button looked dead. Verified by stubbing
     `window.confirm` and watching it be called with the right message
     while nothing happened on screen.

     Nothing replaced it, because the action no longer needs one. Drop
     moves the student into the Dropped band, which is on the same
     screen with a restore button in the same column -- the undo is
     visible rather than promised. The one thing restore does not give
     back is the seat, so the toast says so. */
  try {
    const data = await api("/api/roster/drop",
                           { who: student.name, dropped });
    students = data.students;
    // Opened so the student is visible where they have just gone,
    // rather than vanishing into a band that is shut by default.
    if (dropped) shutBands.delete(DROPPED_BAND);
    renderRoster();
    toast(dropped
      ? `${student.name} dropped. Their seat is now empty — restoring `
        + `them does not give it back.`
      : `${student.name} restored. They have no seat; give them one in `
        + `Seating.`);
  } catch (err) { toast(err.message, true); }
}

async function save() {
  const payload = [...edits.entries()].map(([k, value]) => {
    const [index, field] = k.split(":");
    return { index: Number(index), field, value };
  });
  try {
    const data = await api("/api/roster/save", { edits: payload });
    students = data.students;
    edits.clear();
    renderRoster();
    refreshDirty();
    toast(data.saved === 1 ? "Saved 1 change" : `Saved ${data.saved} changes`);
  } catch (err) { toast(err.message, true); }
}

function revert() {
  edits.clear();
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
  if (!skills) return false;
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
  if (!confirm("Push this to the form?\n\nIt replaces the four slots shown "
               + "in the preview, and students see the change immediately."))
    return;
  try {
    const out = await api("/api/form/push", {});
    // What actually changed is worth saying, since a push that changed
    // nothing and a push that rewrote everything look identical otherwise.
    toast(out.changed.length
      ? "Pushed: " + out.changed.join(", ")
      : "Pushed; the form already said this.");
  } catch (err) { toast(err.message, true); }
}


// --------------------------------------------------------------- google --

async function refreshGoogle(force) {
  const bar = document.getElementById("google-bar");
  let state;
  try {
    state = await fetchGoogle({ force: Boolean(force) });
  } catch { bar.hidden = true; return; }

  bar.textContent = "";
  if (state.signingIn) {
    bar.className = "banner waiting";
    bar.textContent = "Waiting for the Google sign-in in your browser… ";
    const again = document.createElement("button");
    again.className = "act";
    again.textContent = "Check now";
    again.onclick = () => refreshGoogle(true);
    bar.appendChild(again);
    bar.hidden = false;
    setTimeout(() => refreshGoogle(true), 4000);
    return;
  }
  if (state.loggedIn) { bar.hidden = true; return; }

  bar.className = "banner warn";
  if (state.error) {
    // Not "signed out" -- something else is wrong, and a sign-in button
    // would send you round a loop that cannot fix it.
    bar.textContent = "Could not check the Google sign-in: " + state.error;
    bar.hidden = false;
    return;
  }
  bar.append(document.createTextNode(
    "Not signed in to Google, so pushing will fail. Sessions expire after a "
    + "week or two whether or not you use them. "));
  const go = document.createElement("button");
  go.className = "act";
  go.textContent = "Sign in";
  go.onclick = signInToGoogle;
  bar.appendChild(go);
  bar.hidden = false;
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
      + "two whether or not you use them.";
    signin.disabled = true;
    signin.textContent = "Signed in";
  } else if (g.error) {
    google.textContent = "Could not check the sign-in: " + g.error;
    signin.disabled = true;
  } else {
    google.textContent = "Not signed in, so nothing here can reach Google "
      + "yet.";
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

function badSlugs(slugs) {
  const known = new Set(printState.skills.map(s => s.slug));
  return slugs.filter(s => !known.has(s));
}

function renderWho() {
  const body = document.querySelector("#who tbody");
  body.textContent = "";
  let papers = 0;
  let getting = 0;
  for (const student of printState.students) {
    const gets = willGet(student);
    papers += gets.length;
    if (gets.length) getting += 1;
    const tr = document.createElement("tr");
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

    add(gets.join(", ") || "—");

    const td = document.createElement("td");
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
  // One fact, not three run together: what prints, and for how many.
  // The moved-version count went to the Version column's own reset,
  // which is the thing it is about.
  document.getElementById("who-count").textContent =
    papers ? `${papers} paper${papers === 1 ? "" : "s"} for ${getting} `
             + `student${getting === 1 ? "" : "s"}`
           : "nothing to print yet";
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
  };
  f.title.value = draft.title || "";
  f.date.value = draft.date || "";
  f.keys.checked = Boolean(draft.keys);
  f.key_copies.value = draft.key_copies || 1;
  f.names.checked = Boolean(draft.names);
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
  document.getElementById("print-save").onclick = savePrint;
  document.getElementById("print-revert").onclick = revertPrint;
  document.getElementById("print-reset").onclick = resetPrint;
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
