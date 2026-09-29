"use strict";

// The browser holds edits until Save. Deliberate: `roster import` already
// shows a merge before it lands, and a table that rewrote roster.toml on every
// keystroke would remove the one moment a bad edit is catchable.

const TOKEN = window.PRINTIT_TOKEN;

const VIEWS = [
  { id: "overview", label: "Overview" },
  { id: "roster", label: "Roster" },
  { id: "skills", label: "Skills" },
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
  { key: "_actions",  label: "",         sortable: false, min: 92, max: 92 },
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
    // Loaded the first time it is opened rather than at boot: the Skills
    // view reads the bank, and a course with no bank should still show a
    // roster without waiting for one.
    if (id === "skills" && skills === null) loadSkills();
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
      // The one unsortable heading is empty, so the reset lives there --
      // over the column it belongs beside, rather than in the toolbar where
      // it sat next to controls it has nothing to do with. Right-aligned so
      // it does not read as a heading for the drop links beneath it.
      th.className = "actions-head";
      const reset = document.createElement("button");
      reset.className = "link";
      reset.id = "reset-sort";
      reset.textContent = "reset";
      reset.title = "Back to section, then surname.";
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

function renderRoster() {
  renderHeader();
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
  return {
    name: f.name.value,
    date: f.date.value,
    // The browser's datetime-local gives "2026-10-01T23:59"; the file wants
    // seconds, and as_datetime accepts either.
    due: f.due.value,
    choose: Number(f.choose.value || 0),
    limit: f.limit.value,
  };
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
  document.getElementById("skills-dirty").hidden = !dirty;
  document.getElementById("skills-dirty").textContent = "unsaved changes";
  document.getElementById("skills-save").disabled = !dirty;
  document.getElementById("skills-revert").disabled = !dirty;
  document.getElementById("open-count").textContent =
    `— ${openNow.size} of ${skills ? skills.skills.length : 0}`;
}

function renderWording(w) {
  const box = document.getElementById("wording");
  box.textContent = "";
  const line = (text, cls) => {
    const p = document.createElement("p");
    p.className = "wline " + (cls || "");
    p.textContent = text;
    box.appendChild(p);
  };
  line(w.selecting_for);
  line(w.confirm_date, "check");
  line(w.due_notice);
  line(w.question_title, "qtitle");
  if (w.question_help) line(w.question_help, "muted");
  const ul = document.createElement("ul");
  ul.className = "choices";
  for (const c of w.choices) {
    const li = document.createElement("li");
    li.textContent = c;
    ul.appendChild(li);
  }
  box.appendChild(ul);
  line(w.validation.help || "(no limit)", "muted");
}

async function refreshPreview() {
  /* Debounced: the wording comes from the server so there is exactly one
     implementation of it, and a request per keystroke would be silly. */
  clearTimeout(previewTimer);
  previewTimer = setTimeout(async () => {
    try {
      const data = await api("/api/skills/preview",
        { assessment: readAssessment(), open: [...openNow] });
      renderWording(data.wording);
    } catch (err) { toast(err.message, true); }
  }, 250);
}

function renderSkills() {
  const list = document.getElementById("skill-list");
  list.textContent = "";
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
    desc.textContent = s.inBank ? s.description
      : "not in the bank any more — untick to remove it";
    desc.title = desc.textContent;
    label.append(box, slug, desc);
    list.appendChild(label);
  }
  refreshSkillsDirty();
}

function fillAssessment() {
  const f = assessmentInputs();
  const a = skills.assessment;
  f.limit.textContent = "";
  for (const option of skills.limits) {
    const o = document.createElement("option");
    o.value = o.textContent = option;
    f.limit.appendChild(o);
  }
  f.name.value = a.name || "";
  f.date.value = (a.date || "").slice(0, 10);
  f.due.value = (a.due || "").replace(" ", "T").slice(0, 16);
  f.choose.value = a.choose || 0;
  f.limit.value = a.limit || skills.limits[0];
  assessment = readAssessment();
  for (const input of Object.values(f)) {
    input.oninput = input.onchange = () => {
      assessment = readAssessment();
      refreshSkillsDirty();
      refreshPreview();
    };
  }
}

function renderPushState() {
  const note = document.getElementById("push-state");
  const diffBtn = document.getElementById("form-diff");
  if (!skills.form.connected) {
    note.textContent = "No form is connected to this course yet. "
      + "Run `checkit-printit form create` or `form attach` first.";
    diffBtn.disabled = true;
  } else if (!skills.form.mapped.length) {
    note.textContent = "The form is connected but no items are mapped. "
      + "Run `checkit-printit form map`.";
    diffBtn.disabled = true;
  } else {
    note.textContent = "A push replaces what students see. Look at the "
      + "changes first.";
    diffBtn.disabled = false;
  }
}

function renderDiff(data) {
  const box = document.getElementById("diff");
  box.textContent = "";
  let changes = 0;

  const FIELD = { help: "help text", choice: "the checkbox option",
                  title: "title" };

  for (const row of data.rows) {
    const d = document.createElement("div");
    d.className = "diffrow";
    const h = document.createElement("div");
    h.className = "difflabel";
    // Say which field is being compared: a push changes a different one per
    // slot, and a row that does not say so can hold a title against an
    // option and call it a change.
    h.textContent = row.label + "  \u2014  " + (FIELD[row.field] || row.field)
      + (row.mapped ? "" : "  (not mapped)");
    d.appendChild(h);

    if (!row.known) {
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = "not on the form yet; it will be written.";
      d.appendChild(p);
      changes += 1;
    } else if ((row.before || "") === (row.after || "")) {
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = "unchanged";
      d.appendChild(p);
    } else {
      changes += 1;
      for (const [cls, sign, text] of [["was", "\u2212", row.before],
                                       ["now", "+", row.after]]) {
        const p = document.createElement("p");
        p.className = "diffline " + cls;
        p.textContent = sign + " " + (text || "(empty)");
        d.appendChild(p);
      }
    }
    box.appendChild(d);
  }

  // The options, compared as a list rather than squashed into a line.
  const before = data.choices.before;
  const after = data.choices.after;
  const d = document.createElement("div");
  d.className = "diffrow";
  const h = document.createElement("div");
  h.className = "difflabel";
  h.textContent = "The skill question's options";
  d.appendChild(h);
  const same = Array.isArray(before) && before.length === after.length
    && before.every((v, i) => v === after[i]);
  if (same) {
    const p = document.createElement("p");
    p.className = "muted";
    p.textContent = `unchanged (${after.length})`;
    d.appendChild(p);
  } else {
    changes += 1;
    const gone = (before || []).filter(v => !after.includes(v));
    const added = after.filter(v => !(before || []).includes(v));
    for (const [cls, sign, list] of [["was", "\u2212", gone],
                                     ["now", "+", added]]) {
      for (const text of list) {
        const p = document.createElement("p");
        p.className = "diffline " + cls;
        p.textContent = sign + " " + text;
        d.appendChild(p);
      }
    }
    if (!gone.length && !added.length) {
      const p = document.createElement("p");
      p.className = "muted";
      p.textContent = "same options, different order";
      d.appendChild(p);
    }
  }
  box.appendChild(d);

  const foot = document.createElement("p");
  foot.className = "muted";
  foot.textContent = "validation: " +
    (data.validation.mode + " " + (data.validation.count || "")).trim();
  box.appendChild(foot);

  document.getElementById("form-push").hidden = false;
  return changes;
}


async function loadSkills() {
  try {
    skills = await api("/api/skills");
  } catch (err) { toast(err.message, true); return; }
  openNow = new Set(skills.open);
  fillAssessment();
  renderSkills();
  renderWording(skills.wording);
  renderPushState();
}

async function saveSkills() {
  try {
    skills = await api("/api/skills/save",
      { open: [...openNow], assessment: readAssessment() });
    openNow = new Set(skills.open);
    fillAssessment();
    renderSkills();
    renderWording(skills.wording);
    renderPushState();
    toast("Saved");
  } catch (err) { toast(err.message, true); }
}

function revertSkills() {
  openNow = new Set(skills.open);
  fillAssessment();
  renderSkills();
  renderWording(skills.wording);
  toast("Discarded");
}

async function showDiff() {
  if (skillsDirty()) {
    toast("Save first — the form would be sent the saved wording, not what "
          + "is on screen.", true);
    return;
  }
  try {
    const changes = renderDiff(await api("/api/form/diff"));
    toast(changes ? `${changes} slot(s) would change` : "Nothing would change");
  } catch (err) { toast(err.message, true); }
}

async function pushForm() {
  if (!confirm("Push this to the form?\n\nStudents see the change "
               + "immediately.")) return;
  try {
    const out = await api("/api/form/push", {});
    toast("Pushed: " + (out.changed.join(", ") || "nothing"));
    document.getElementById("diff").textContent = "";
    document.getElementById("form-push").hidden = true;
  } catch (err) { toast(err.message, true); }
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
  document.getElementById("form-diff").onclick = showDiff;
  document.getElementById("form-push").onclick = pushForm;
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
