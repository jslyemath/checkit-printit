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
const COLUMNS = [
  { key: "name",      label: "Name",     edit: true },
  { key: "preferred", label: "Nickname", edit: true },
  { key: "section",   label: "Section",  edit: true },
  { key: "email",     label: "Email",    edit: true },
  { key: "sid",       label: "SID",      cls: "ro",
    text: s => s.sid || s.alt_id || "—",
    value: s => s.sid || s.alt_id || "" },
  { key: "_actions",  label: "",         sortable: false },
];

let students = [];
let edits = new Map();          // "index:field" -> value
let showDropped = false;
let sortKey = null;
let sortDesc = false;

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

function sortValue(column, student) {
  const raw = column.value ? column.value(student) : (student[column.key] || "");
  return String(raw).toLowerCase();
}

function sortBy(key) {
  if (sortKey === key) sortDesc = !sortDesc;
  else { sortKey = key; sortDesc = false; }
  renderRoster();
}

function renderHeader() {
  const row = document.querySelector("#roster thead tr");
  row.textContent = "";
  for (const column of COLUMNS) {
    const th = document.createElement("th");
    if (column.sortable === false) {
      th.textContent = column.label;
    } else {
      const b = document.createElement("button");
      b.className = "sort";
      b.textContent = column.label;
      if (sortKey === column.key) {
        b.classList.add("sorted");
        b.textContent += sortDesc ? " ↓" : " ↑";
      }
      b.onclick = () => sortBy(column.key);
      th.appendChild(b);
    }
    row.appendChild(th);
  }
}

function renderRoster() {
  renderHeader();
  const body = document.querySelector("#roster tbody");
  body.textContent = "";

  let shown = students.filter(s => showDropped || !s.dropped);
  if (sortKey) {
    const column = COLUMNS.find(c => c.key === sortKey);
    // Sorting only reorders what is displayed. Edits are keyed to each
    // student's own index, not to a row position, so they survive it.
    shown = [...shown].sort((a, b) => {
      const cmp = sortValue(column, a).localeCompare(
        sortValue(column, b), undefined, { numeric: true });
      return sortDesc ? -cmp : cmp;
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
        td.appendChild(cellInput(student, column.key));
      } else {
        td.textContent = column.text ? column.text(student)
                                     : (student[column.key] || "—");
      }
      tr.appendChild(td);
    }
    body.appendChild(tr);
  }

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
