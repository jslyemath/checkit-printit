"use strict";

// The browser holds edits until Save. Deliberate: `roster import` already
// shows a merge before it lands, and a table that rewrote roster.toml on every
// keystroke would remove the one moment a bad edit is catchable.

const TOKEN = window.PRINTIT_TOKEN;

const VIEWS = [
  { id: "overview", label: "Overview" },
  { id: "roster", label: "Roster" },
  { id: "form", label: "Update form" },
  { id: "print", label: "Print job" },
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
const COLUMNS = [
  { key: "name",      label: "Name",     edit: true, min: 200, max: 330,
    sortKeys: [["sort_last", "last"], ["sort_first", "first"]] },
  // Not "Nickname": that invites "Matt", and this replaces the whole
  // printed name. Same widths as Name, because it holds the same thing.
  { key: "preferred", label: "Prints as", edit: true, min: 200, max: 330,
    placeholder: s => s.name },
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
    if (id === "form" && skills === null) loadSkills();
    // Reloaded every time, not only the first. It used to load once, so a
    // name edited in Roster and saved never reached this table until the
    // print job itself was saved -- which read as the table being stale.
    if (id === "print") loadPrint();
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

function cellInput(student, field, column) {
  const input = document.createElement("input");
  input.value = student[field] || "";
  input.spellcheck = false;
  // An empty "Prints as" is not missing data -- it means the roster name is
  // used -- so the box shows that name greyed rather than sitting blank.
  if (column && column.placeholder) input.placeholder = column.placeholder(student);
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

  let total = 0;
  for (const column of COLUMNS) {
    let widest = textWidth(column.label.toUpperCase(), headFont) + 18;
    for (const student of rows) {
      const value = column.value ? column.value(student)
                  : column.text ? column.text(student)
                  : (student[column.key] || "");
      widest = Math.max(widest, textWidth(value, bodyFont) + CELL_PADDING);
    }
    const col = document.createElement("col");
    const px = Math.round(Math.min(column.max, Math.max(column.min, widest)));
    col.style.width = px + "px";
    total += px;
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
  document.getElementById("skills-dirty").hidden = !dirty;
  document.getElementById("skills-dirty").textContent = "unsaved changes";
  document.getElementById("skills-save").disabled = !dirty;
  document.getElementById("skills-revert").disabled = !dirty;
  document.getElementById("open-count").textContent =
    `— ${openNow.size} of ${skills ? skills.skills.length : 0}`;
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

async function loadSkills() {
  try {
    skills = await api("/api/skills");
  } catch (err) { toast(err.message, true); return; }
  openNow = new Set(skills.open);
  fillAssessment();
  renderSkills();
  renderWording(skills.preview);
  renderPushState();
  refreshGoogle();
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
    state = await api("/api/google", { force: Boolean(force) });
  } catch { bar.hidden = true; return; }

  bar.textContent = "";
  if (state.signingIn) {
    bar.className = "banner waiting";
    bar.textContent = "Waiting for the Google sign-in in your browser… ";
    const again = document.createElement("button");
    again.className = "link";
    again.textContent = "check now";
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
  go.className = "link";
  go.textContent = "Sign in";
  go.onclick = async () => {
    try {
      await api("/api/google/login", {});
      toast("A browser window should open. Sign in there.");
      refreshGoogle(true);
    } catch (err) { toast(err.message, true); }
  };
  bar.appendChild(go);
  bar.hidden = false;
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
  const d = printDirty();
  document.getElementById("print-dirty").hidden = !d;
  document.getElementById("print-dirty").textContent = "unsaved changes";
  document.getElementById("print-save").disabled = !d;
  document.getElementById("print-revert").disabled = !d;
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
    desc.textContent = s.description;
    desc.title = s.description;
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
    rm.className = "link";
    rm.textContent = "remove";
    rm.onclick = () => { draft.extras.splice(i, 1); renderExtras(); renderVariants(); refreshPrintDirty(); };
    row.append(sel, n, document.createTextNode(" copies"), rm);
    box.appendChild(row);
  });
  document.getElementById("extras-count").textContent =
    draft.extras.length ? `— ${draft.extras.reduce((a, e) => a + Number(e.copies || 0), 0)} sheets` : "";
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
  for (const student of printState.students) {
    const gets = willGet(student);
    papers += gets.length;
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
  document.getElementById("who-count").textContent =
    `— ${printState.students.length} students, ${papers} papers`
    + (movedCount ? `, ${movedCount} moved to another version` : "");
  // One reset per column, shown on the same condition as the row ones.
  document.getElementById("reset-versions").classList.toggle("off", !movedCount);
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
    why.textContent = "This course has no Google Form connected, so there "
      + "is nothing to pull yet. `form create` makes one; `form attach` "
      + "wires up a form you already have.";
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
    line(`⚠ ${data.unknownEmails.length} response(s) came from an address `
         + `nobody on the roster has:`, "warnline");
    for (const address of data.unknownEmails) line("    " + address, "muted");
    line("Add the address to that student on the Roster tab, or check for "
         + "a typo.", "muted");
  }
  if (data.unrecognised.length) {
    line(`⚠ ${data.unrecognised.length} answer(s) name a skill the bank `
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

  for (const c of out.collisions) line("⚠ " + c, "warnline");
  if (out.unmatchedOverrides && out.unmatchedOverrides.length)
    line("⚠ override(s) for " + out.unmatchedOverrides.join(", ")
         + " matched nobody in the roster, so nothing changed for them",
         "warnline");
  if (out.unseated.length)
    line("⚠ not in the seating chart, printed last: " + out.unseated.join(", "),
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
  document.getElementById("show-dropped").onchange = (e) => {
    showDropped = e.target.checked;
    renderRoster();
  };
  window.onbeforeunload = (e) => { if (edits.size) e.preventDefault(); };

  // Back and forward change the hash without reloading, so without this
  // they appear to do nothing at all -- the URL moves and the page does
  // not, which reads as the app being stuck.
  window.addEventListener("hashchange", () => {
    const id = location.hash.slice(1);
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

  show(VIEWS.some(v => v.id === location.hash.slice(1))
       ? location.hash.slice(1) : "overview");
}

boot();
