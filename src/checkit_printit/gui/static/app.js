"use strict";

// The browser holds edits until Save. Deliberate: `roster import` already
// shows a merge before it lands, and a table that rewrote roster.toml on every
// keystroke would remove the one moment a bad edit is catchable.

const TOKEN = window.PRINTIT_TOKEN;

const VIEWS = [
  { id: "overview", label: "Overview" },
  { id: "roster", label: "Roster" },
  { id: "skills", label: "Skills", soon: "Toggle which skills are open, set the assessment's date and limit, and push the wording to the form. Today: `skills open`, `skills set`, `form push`." },
  { id: "responses", label: "Responses", soon: "Who answered and what they chose, pulled into the roster. Today: `form pull`." },
  { id: "print", label: "Print job", soon: "Skills, per-skill variants, extras and keys, then build. Today: a job folder and `build`." },
  { id: "record", label: "Record", soon: "What has been printed, to whom, at which seed. Today: `record runs`, `record student`, `record skills`." },
  { id: "seating", label: "Seating", soon: "Drag students between seats, randomise, swap two. No CLI equivalent exists yet -- this is new code, not a face on something tested." },
  { id: "callout", label: "Cold call", soon: "Pick a random student, pick several, refresh the call list. No CLI equivalent yet." },
];

// One definition per column, used to build the header AND the cells. They
// used to be two lists that could drift, and did: a rule hid the SID cell on
// a narrow window but not its heading, so every column after it read one
// place to the left.
// `min` and `max` are the column's width in pixels. Content decides the width
// between them: an <input> reports its own default width (about twenty
// characters) whatever it contains, so a column of short nicknames comes out
// as wide as a column of long emails unless the values are measured.
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
const COLUMNS = [
  { key: "name",      label: "Name",     edit: true, min: 200, max: 330,
    sortKeys: [["sort_last", "last"], ["sort_first", "first"]] },
  { key: "preferred", label: "Nickname", edit: true, min: 130, max: 210 },
  { key: "section",   label: "Section",  edit: true, min: 74,  max: 110 },
  { key: "email",     label: "Email",    edit: true, min: 215, max: 340 },
  { key: "sid",       label: "SID",      cls: "ro",  min: 86,  max: 140,
    text: s => s.sid || s.alt_id || "—",
    value: s => s.sid || s.alt_id || "" },
  { key: "_actions",  label: "",         sortable: false, min: 70, max: 70 },
];

let students = [];
let edits = new Map();          // "index:field" -> value
let showDropped = false;
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
  let payload;
  try { payload = await res.json(); }
  catch { throw new Error(`the server answered ${res.status} with no JSON`); }
  if (!res.ok || payload.error) throw new Error(payload.error || `HTTP ${res.status}`);
  return payload.data;
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

function buildNav() {
  const nav = document.getElementById("views");
  for (const view of VIEWS) {
    const b = document.createElement("button");
    b.textContent = view.label;
    if (view.soon) b.classList.add("soon");
    b.onclick = () => show(view.id);
    b.dataset.view = view.id;
    nav.appendChild(b);
  }
}

function show(id) {
  const view = VIEWS.find(v => v.id === id);
  for (const b of document.querySelectorAll("nav button")) {
    if (b.dataset.view === id) b.setAttribute("aria-current", "page");
    else b.removeAttribute("aria-current");
  }
  for (const s of document.querySelectorAll(".view")) s.hidden = true;
  if (view.soon) {
    document.getElementById("soon-title").textContent = view.label;
    document.getElementById("soon-body").textContent = view.soon;
    document.getElementById("view-soon").hidden = false;
  } else {
    document.getElementById("view-" + id).hidden = false;
  }
  location.hash = id;
}

// ------------------------------------------------------------- overview --

function renderOverview(summary) {
  document.getElementById("course-name").textContent =
    `${summary.name} — ${summary.active} active of ${summary.students}`;

  const cards = document.getElementById("overview");
  cards.textContent = "";
  const add = (n, label, missing) => {
    const d = document.createElement("div");
    d.className = "card" + (missing ? " missing" : "");
    d.innerHTML = `<div class="n"></div><div class="label"></div>`;
    d.querySelector(".n").textContent = n;
    d.querySelector(".label").textContent = label;
    cards.appendChild(d);
  };
  add(summary.active, "students");
  for (const [section, n] of Object.entries(summary.sections)) add(n, "in " + section);
  for (const [file, there] of Object.entries(summary.files)) {
    add(there ? "yes" : "—", file, !there);
  }
}

// --------------------------------------------------------------- roster --

function key(index, field) { return index + ":" + field; }

function refreshDirty() {
  const n = edits.size;
  const bar = document.getElementById("dirty");
  bar.hidden = n === 0;
  bar.textContent = n === 1 ? "1 unsaved change" : `${n} unsaved changes`;
  document.getElementById("save").disabled = n === 0;
  document.getElementById("revert").disabled = n === 0;
}

function cellInput(student, field) {
  const input = document.createElement("input");
  input.value = student[field] || "";
  input.spellcheck = false;
  input.oninput = () => {
    const k = key(student.index, field);
    if (input.value === (student[field] || "")) edits.delete(k);
    else edits.set(k, input.value);
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

  for (const column of COLUMNS) {
    let widest = textWidth(column.label.toUpperCase(), headFont) + 18;
    for (const student of rows) {
      const value = column.value ? column.value(student)
                  : column.text ? column.text(student)
                  : (student[column.key] || "");
      widest = Math.max(widest, textWidth(value, bodyFont) + CELL_PADDING);
    }
    const col = document.createElement("col");
    col.style.width =
      Math.round(Math.min(column.max, Math.max(column.min, widest))) + "px";
    group.appendChild(col);
  }
  table.insertBefore(group, table.firstChild);
}

function renderHeader() {
  const row = document.querySelector("#roster thead tr");
  row.textContent = "";
  for (const column of COLUMNS) {
    const th = document.createElement("th");
    if (column.sortable === false) {
      th.textContent = column.label;
      row.appendChild(th);
      continue;
    }
    const cycle = cycleOf(column);
    const entry = sorts.find(s => cycle.some(([k]) => k === s.key));
    const note = entry && (cycle.find(([k]) => k === entry.key) || [])[2];
    const rank = entry ? rankOf(entry.key) : null;

    const b = document.createElement("button");
    b.className = "sort";
    // A column with two orders has to say which one it is on: "Name" alone
    // would not tell you whether it sorted by surname or given name. The
    // rank appears only when more than one key is in play, because a lone
    // "1" would be noise.
    b.textContent = column.label
      + (note ? " · " + note : "")
      + (entry ? (entry.desc ? " ↓" : " ↑") : "")
      + (entry && sorts.length > 1 ? " " + rank : "");
    if (entry) b.classList.add("sorted");
    if (rank === 1) b.classList.add("primary-sort");
    b.title = (column.sortKeys
        ? "Cycles through " + column.sortKeys.map(k => k[1]).join(" and ")
          + " name, each way. "
        : "")
      + "Sorting by another column keeps this one as a tiebreaker.";
    b.onclick = () => sortBy(column);
    th.appendChild(b);
    row.appendChild(th);
  }
}

function describeSort() {
  /* "section, then last name" -- so the order in force is legible without
     decoding four little arrows. */
  const parts = sorts.map(s => {
    const column = columnOwning(s.key);
    if (!column) return null;
    const note = (cycleOf(column).find(([k]) => k === s.key) || [])[2];
    return (note ? `${column.label.toLowerCase()} (${note})` : column.label.toLowerCase())
      + (s.desc ? ", reversed" : "");
  }).filter(Boolean);
  if (!parts.length) return "unsorted";
  return "sorted by " + parts.join(", then ");
}

function renderSortNote() {
  const isDefault =
    sorts.length === DEFAULT_SORT.length &&
    sorts.every((s, i) => s.key === DEFAULT_SORT[i].key &&
                          s.desc === DEFAULT_SORT[i].desc);
  document.getElementById("sort-note").textContent = describeSort();
  document.getElementById("reset-sort").hidden = isDefault;
}

function renderRoster() {
  renderHeader();
  renderSortNote();
  const body = document.querySelector("#roster tbody");
  body.textContent = "";

  let shown = students.filter(s => showDropped || !s.dropped);
  if (sorts.length) {
    // Sorting only reorders what is displayed. Edits are keyed to each
    // student's own index, not to a row position, so they survive it.
    const keys = sorts
      .map(s => ({ ...s, column: columnOwning(s.key) }))
      .filter(s => s.column);
    shown = [...shown].sort((a, b) => {
      for (const { key, desc, column } of keys) {
        const cmp = sortValue(key, column, a).localeCompare(
          sortValue(key, column, b), undefined, { numeric: true });
        if (cmp) return desc ? -cmp : cmp;
      }
      return 0;
    });
  }

  for (const student of shown) {
    const tr = document.createElement("tr");
    if (student.dropped) tr.className = "dropped";

    for (const column of COLUMNS) {
      const td = document.createElement("td");
      if (column.cls) td.className = column.cls;
      if (column.key === "_actions") {
        const b = document.createElement("button");
        b.className = "link";
        b.textContent = student.dropped ? "restore" : "drop";
        b.onclick = () => drop(student, !student.dropped);
        td.appendChild(b);
      } else if (column.edit) {
        td.classList.add("cell-" + column.key);
        const input = cellInput(student, column.key);
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

  const empty = document.getElementById("roster-empty");
  empty.hidden = shown.length > 0;
  empty.textContent = students.length
    ? "Every student on this roster is dropped. Tick “show dropped” to see them."
    : "This roster is empty.";
}

async function drop(student, dropped) {
  if (edits.size) {
    toast("Save or discard your edits first — dropping rewrites the file.", true);
    return;
  }
  const verb = dropped ? "Drop" : "Restore";
  const extra = dropped
    ? "\n\nThey stay on the roster (the print record refers to them) and their seat is emptied."
    : "\n\nThis does not give them a seat back.";
  if (!confirm(`${verb} ${student.name}?${extra}`)) return;
  try {
    const data = await api("/api/roster/drop",
                           { who: student.name, dropped });
    students = data.students;
    renderRoster();
    toast(data.note);
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

// ----------------------------------------------------------------- boot --

async function boot() {
  buildNav();
  document.getElementById("save").onclick = save;
  document.getElementById("revert").onclick = revert;
  document.getElementById("reset-sort").onclick = clearSort;
  document.getElementById("show-dropped").onchange = (e) => {
    showDropped = e.target.checked;
    renderRoster();
  };
  window.onbeforeunload = (e) => { if (edits.size) e.preventDefault(); };

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

  show(VIEWS.some(v => v.id === location.hash.slice(1))
       ? location.hash.slice(1) : "overview");
}

boot();
