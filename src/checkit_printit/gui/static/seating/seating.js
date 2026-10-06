"use strict";

/* The seating view: a canvas application that happens to be embedded in
 * checkit-printit.
 *
 * Its own file and its own stylesheet from the start, because Seating
 * and Up Next are to become an application of their own. If every
 * control already lives in here, that move is deleting the host's
 * header rather than rebuilding a UI. Specified in
 * ../../../../../checkit/PRINT_TOOL_DESIGN.md, section 12.12.
 *
 * Loaded after app.js and leans on exactly two of its globals, `api`
 * and `toast`. Keep it that way.
 */

// ---------------------------------------------------------------- state --

let seatingState = null;         // what the server last sent
let seatingRoom = null;          // the copy being edited, written on Save
let seatingSection = 0;
let seatingZoom = null;          // null means "fit"
let seatingMode = "people";

/* What is selected: `{kind: "group", id}` or `{kind: "shape", id}`, or
   null. Everything in the strip hangs off this -- it is the backbone,
   not a feature, which is why it exists before the things that read it. */
let selected = null;

/* A name in hand, for click-then-click: `{who, seat}`, with `seat` null
   when it came off the unseated rail. */
let picked = null;

/* Where everything landed, rebuilt by `drawRoom`. A drag starts from an
   element and has to reason in room coordinates. */
let drawn = { shapes: {}, cards: {}, seats: [], labels: [], box: null };

/* What is drawn, as opposed to what is true. These are the viewer's
   preferences, not the room's, so they live here and not in
   `seatingRoom` -- put in the document they would make "hide the
   version letters for a minute" an unsaved change, and the Save button
   would appear for having looked at something differently. */
let showVersions = true;
let showLabels = true;

/* Up Next. `called` is everybody who has had a turn, so nobody is
   asked twice before everybody has been asked once -- which is the
   difference between picking at random and being fair. In memory
   only: a call list is about this lesson, and one that survived a
   reload would quietly be about last week. */
let called = new Set();
let calling = null;

// ------------------------------------------------------------ constants --

const GRID = 20;        // what a dragged desk snaps to, in room units
const REACH = 90;       // how near a chair you must point to drop into it
const CARD_W = 104;     // a name card, in room units. Matches `.seatcard`
const CARD_H = 54;      //   in seating.css, and room.SHAPES is spaced for it
const PAD = 26;         // breathing room around the drawn room, same units

/* How large a first name may be drawn, largest first; the card takes the
   first that fits. Measured rather than counted -- counting put the
   ceiling at 20 when a five-letter name fits at 32, and cannot tell
   "Bartholomew" from "Christopher": same eleven letters, 13px and 17px. */
const NAME_SIZES = [32, 29, 26, 23, 20, 17, 15, 13];
const NAME_SMALLEST = 11;

/* A group owns a hue, and three shades are derived from it, each with a
   job: the table recedes, the card lifts off the table, the pill is the
   one saturated thing. These are the hues on offer -- far enough apart
   to tell at a glance, and never the only carrier of meaning, because
   the pill still says which table it is. */
const HUES = [255, 150, 35, 330, 285, 95, 195, 15];

/* The nine places a label can sit on a desk, as fractions of the
   shape's own box. Eight around the perimeter and the middle, the same
   nine for every shape -- a hexagon's corners are not where a label
   wants to be, and a rule that is the same everywhere is one a person
   can learn once.

   The pill's centre goes exactly on the point, so a perimeter anchor
   straddles the edge. That reads as deliberate, where fully outside
   reads as adrift and fully inside covers the furniture. */
const ANCHORS = {
  nw: [-0.5, -0.5], n: [0, -0.5], ne: [0.5, -0.5],
  w: [-0.5, 0], c: [0, 0], e: [0.5, 0],
  sw: [-0.5, 0.5], s: [0, 0.5], se: [0.5, 0.5],
};

const ICON = {
  view: "M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z|O12,12,3",
  people: "M5.5 20a6.5 6.5 0 0 1 13 0|O12,8,3.4",
  desks: "R3,4,18,7,1.5|R3,14,8,6,1.5|R14,14,7,6,1.5",
  chairs: "R4,8,16,9,2|O8,5,1.8|O16,5,1.8|O8,20,1.8|O16,20,1.8",
  order: "M4 6h3M4 12h3M4 18h3M11 6h9M11 12h9M11 18h9",
  upnext: "M12 3l1.9 4.6L18.5 9l-4.6 1.4L12 15l-1.9-4.6L5.5 9l4.6-1.4z"
    + "|M18 16l.8 2 2 .8-2 .8-.8 2-.8-2-2-.8 2-.8z",
};

/* Modes only. Shuffle is an action and lives in the menu: an action
   among modes is a category error, and the test that keeps the rail
   honest is whether it changes what a click on the canvas means. */
const MODES = [
  { value: "view", label: "View", icon: "view",
    why: "Nothing moves. This is the projector." },
  { value: "people", label: "People", icon: "people",
    why: "Click a name then a chair, or drag it. Landing on somebody "
      + "swaps the two; the version letters stay with the chairs, so "
      + "neighbours still differ afterwards." },
  { value: "desks", label: "Desks", icon: "desks",
    why: "Drag a desk and its people come with it. Click one and the "
      + "arrows nudge it by " + GRID + ", shift+arrows by 1." },
  { value: "chairs", label: "Chairs", icon: "chairs",
    why: "Where the chairs sit on a desk. Not built yet." },
  { value: "order", label: "Order", icon: "order",
    why: "The order papers are handed out in. Not built yet." },
  { value: "upnext", label: "Up Next", icon: "upnext",
    why: "Pick somebody: the room, with one chair lit up. Space picks "
      + "the next; nobody comes up twice until everybody has." },
];
const BUILT = new Set(["view", "people", "desks", "upnext"]);

// --------------------------------------------------------------- helpers --

function svgIcon(spec) {
  /* A tiny path language, so an icon is one string in `ICON` rather
     than six lines of createElementNS at each use. `Ox,y,r` is a
     circle, `Rx,y,w,h,r` a rounded rect, anything else a path. */
  const NS = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(NS, "svg");
  svg.setAttribute("viewBox", "0 0 24 24");
  svg.setAttribute("aria-hidden", "true");
  for (const part of spec.split("|")) {
    let node;
    if (part.startsWith("O")) {
      const [cx, cy, r] = part.slice(1).split(",");
      node = document.createElementNS(NS, "circle");
      node.setAttribute("cx", cx);
      node.setAttribute("cy", cy);
      node.setAttribute("r", r);
    } else if (part.startsWith("R")) {
      const [x, y, w, h, r] = part.slice(1).split(",");
      node = document.createElementNS(NS, "rect");
      node.setAttribute("x", x);
      node.setAttribute("y", y);
      node.setAttribute("width", w);
      node.setAttribute("height", h);
      node.setAttribute("rx", r);
    } else {
      node = document.createElementNS(NS, "path");
      node.setAttribute("d", part);
    }
    svg.appendChild(node);
  }
  return svg;
}

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function seatingCanvas() { return document.getElementById("canvas"); }
function seatingPaper() { return document.querySelector("#view-seating .paper"); }
function seatingPen() { return document.getElementById("seat-pen"); }

function currentSection() {
  const sections = (seatingRoom && seatingRoom.sections) || [];
  if (!sections.length) return null;
  return sections[Math.min(seatingSection, sections.length - 1)];
}

function cardPosition(shape, seat) {
  /* A card is placed on the canvas, not inside its shape: a seat anchor
     is an offset from the shape's centre, and a dragged seat has to be
     able to leave the shape it started on. */
  return [shape.at[0] + seat.at[0], shape.at[1] + seat.at[1]];
}

function groupsOf(section) { return (section && section.groups) || []; }

function groupOfSeat(section) {
  const out = {};
  for (const g of groupsOf(section))
    for (const id of g.seats || []) out[id] = g;
  return out;
}

function hueOf(section, group) {
  /* A group's own hue if it has chosen one, otherwise one off the
     palette by position -- so a room drawn before colour existed comes
     up coloured, with nothing migrated. */
  if (!group) return null;
  if (typeof group.hue === "number") return group.hue;
  const i = groupsOf(section).indexOf(group);
  return i < 0 ? null : HUES[i % HUES.length];
}

function contentBox(section) {
  /* The smallest box holding everything drawn, in room units.

     Not the declared canvas. A section declares 1290 by 1220 while its
     furniture occupies about 932 by 648; fitting the declaration threw
     away a third of the scale across and nearly half of it down, and
     left the empty remainder on screen looking like part of the room.
     The declared size still bounds where a desk may be dragged. */
  let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
  const grow = (l, t, r, b) => {
    x0 = Math.min(x0, l); y0 = Math.min(y0, t);
    x1 = Math.max(x1, r); y1 = Math.max(y1, b);
  };
  for (const shape of (section && section.shapes) || []) {
    const spec = seatingState.shapes[shape.kind];
    if (!spec) continue;
    grow(shape.at[0] - spec.w / 2, shape.at[1] - spec.h / 2,
         shape.at[0] + spec.w / 2, shape.at[1] + spec.h / 2);
    for (const seat of shape.seats || []) {
      const [x, y] = cardPosition(shape, seat);
      grow(x - CARD_W / 2, y - CARD_H / 2, x + CARD_W / 2, y + CARD_H / 2);
    }
  }
  for (const note of (section && section.notes) || [])
    grow(note.at[0] - 70, note.at[1] - 14, note.at[0] + 70, note.at[1] + 14);

  if (x0 === Infinity) {
    const size = (section && section.canvas) || { width: 1000, height: 700 };
    return { x: 0, y: 0, w: size.width, h: size.height };
  }
  return { x: x0 - PAD, y: y0 - PAD,
           w: x1 - x0 + PAD * 2, h: y1 - y0 + PAD * 2 };
}

/* name -> the size it fits at. Measuring costs a layout, so each
   distinct name is measured once; a class has about as many first names
   as students, and every re-draw after the first is cache hits. */
const nameFits = new Map();
let nameProbe = null;

function nameSize(text) {
  if (!text) return NAME_SIZES[0];
  if (nameFits.has(text)) return nameFits.get(text);
  if (!nameProbe) {
    /* A real card, off screen, so it is measured under the rules that
       will draw it. A bare div with a hand-copied font would be a
       second copy of `.seatcard .top`, and the two would drift. */
    nameProbe = el("div", "seatcard measuring");
    nameProbe.appendChild(el("div", "top"));
    document.body.appendChild(nameProbe);
  }
  const line = nameProbe.firstChild;
  line.textContent = text;
  let chosen = NAME_SMALLEST;
  for (const size of NAME_SIZES) {
    line.style.fontSize = size + "px";
    if (line.getBoundingClientRect().width <= CARD_W - 10) {
      chosen = size;
      break;
    }
  }
  nameFits.set(text, chosen);
  return chosen;
}

function presenting() { return document.body.classList.contains("presenting"); }

function seatingDirty() {
  return seatingRoom !== null && seatingState !== null
    && JSON.stringify(seatingRoom) !== JSON.stringify(seatingState.room);
}

// ---------------------------------------------------------------- render --

function renderSeating() {
  const sections = (seatingRoom && seatingRoom.sections) || [];
  const empty = document.getElementById("seating-empty");

  drawRail();
  drawSections(sections);
  document.getElementById("seat-saving").hidden = !seatingDirty();

  if (!sections.length) {
    empty.textContent = "No room drawn for this course yet. The canvas is "
      + "where you lay the desks out; adding shapes comes next.";
    empty.hidden = false;
    seatingCanvas().textContent = "";
    seatingPen().hidden = true;
    document.getElementById("seat-strip").hidden = true;
    return;
  }
  empty.hidden = true;

  const section = currentSection();
  drawPen(section);
  drawRoom(section);
  drawStrip(section);
  drawStageBar(section, sections.length);
}

function drawRail() {
  const rail = document.getElementById("seat-modes");
  rail.textContent = "";
  for (const mode of MODES) {
    const b = el("button", "ibtn" + (mode.value === seatingMode ? " on" : ""));
    b.type = "button";
    b.title = mode.why;
    b.setAttribute("aria-pressed", String(mode.value === seatingMode));
    b.appendChild(svgIcon(ICON[mode.icon]));
    b.appendChild(el("span", "ilabel", mode.label));
    if (!BUILT.has(mode.value)) b.classList.add("soonish");
    b.onclick = () => {
      if (!BUILT.has(mode.value)) { toast(mode.why); return; }
      seatingMode = mode.value;
      picked = null;
      renderSeating();
    };
    rail.appendChild(b);
  }
}

function drawSections(sections) {
  const host = document.getElementById("seat-sections");
  host.textContent = "";
  if (sections.length < 2) return;
  const at = Math.min(seatingSection, sections.length - 1);
  sections.forEach((s, i) => {
    const b = el("button", "ibtn" + (i === at ? " on" : ""),
                 s.name || `section ${i + 1}`);
    b.type = "button";
    b.setAttribute("aria-pressed", String(i === at));
    b.onclick = () => goToSection(i);
    host.appendChild(b);
  });
}

function goToSection(i) {
  seatingSection = i;
  selected = null;
  picked = null;
  // The turn belongs to the room that is on screen. Carried across,
  // the count would be measured against a roomful of different people.
  calling = null;
  called = new Set();
  seatingZoom = null;              // each room fits on its own terms
  renderSeating();
}

function drawRoom(section) {
  const s = seatingState;
  const canvas = seatingCanvas();
  canvas.textContent = "";
  canvas.className = "canvas mode-" + seatingMode
    + (seatingMode === "upnext" && calling ? " hushed" : "");

  /* Everything is drawn relative to the content box, not to (0, 0) of
     the declared canvas. The model stays in room coordinates; only the
     drawing subtracts the origin, and `roomPoint` adds it back. */
  const area = contentBox(section);
  drawn = { shapes: {}, cards: {}, seats: [], labels: [], box: area };
  const ox = area.x, oy = area.y;

  canvas.style.width = area.w + "px";
  canvas.style.height = area.h + "px";

  const bySeat = groupOfSeat(section);
  const where = {};

  for (const shape of section.shapes || []) {
    const spec = s.shapes[shape.kind];
    if (!spec) continue;                   // a shape this build cannot draw
    const group = (shape.seats || []).map(x => bySeat[x.id]).find(Boolean);
    const hue = hueOf(section, group);

    const box = el("div", "shape " + spec.css);
    tint(box, hue);
    box.style.left = (shape.at[0] - spec.w / 2 - ox) + "px";
    box.style.top = (shape.at[1] - spec.h / 2 - oy) + "px";
    box.style.width = spec.w + "px";
    box.style.height = spec.h + "px";
    if (isSelected(group, shape)) box.classList.add("chosen");
    if (seatingMode === "desks") {
      box.classList.add("movable");
      box.tabIndex = 0;
      box.onkeydown = e => nudgeShape(e, section, shape);
      box.onpointerdown = e => dragShape(e, section, shape);
    } else {
      box.onpointerdown = e => { e.preventDefault(); choose(group, shape); };
    }
    canvas.appendChild(box);
    drawn.shapes[shape.id] = box;

    for (const seat of shape.seats || []) {
      const [x, y] = cardPosition(shape, seat);
      where[seat.id] = [x, y];
      const who = s.names[seat.student];
      const card = el("div", "seatcard" + (who ? "" : " empty"));
      tint(card, hue);
      card.style.left = (x - CARD_W / 2 - ox) + "px";
      card.style.top = (y - CARD_H / 2 - oy) + "px";
      fillCard(card, who, showVersions ? seat.version : "");

      if (seatingMode === "people") {
        if (who) card.classList.add("movable");
        if (picked && picked.seat === seat) card.classList.add("picked");
        card.onpointerdown = e => dragName(e, card, { seat: seat });
      } else if (seatingMode === "upnext") {
        if (seat.student && seat.student === calling)
          card.classList.add("calling");
        else if (seat.student && called.has(seat.student))
          card.classList.add("been");
      } else if (seatingMode !== "desks") {
        card.onpointerdown = e => { e.preventDefault(); choose(group, shape); };
      }
      canvas.appendChild(card);
      drawn.cards[seat.id] = card;
      drawn.seats.push({ id: seat.id, x: x, y: y, seat: seat, shape: shape });
    }
  }

  if (showLabels) {
    for (const group of groupsOf(section)) {
      const ids = (group.seats || []).filter(id => where[id]);
      if (!ids.length || !group.label) continue;
      const [x, y] = labelPoint(section, group, ids, where);
      const tag = el("div", "pill", group.label);
      tint(tag, hueOf(section, group));
      if (isSelected(group, null)) tag.classList.add("chosen");
      tag.style.left = (x - ox) + "px";
      tag.style.top = (y - oy) + "px";
      tag.onpointerdown = e => dragLabel(e, tag, section, group, ids, where);
      canvas.appendChild(tag);
      drawn.labels.push({ el: tag, seats: ids, group: group });
    }
  }

  // The nine places this group's label may sit, shown only while it is
  // selected. There is no picker control: these *are* the control.
  if (showLabels && selected && selected.kind === "group") {
    for (const spot of anchorsFor(section, selected.id)) {
      const dot = el("div", "anchor" + (spot.on ? " on" : ""));
      dot.style.left = (spot.x - ox) + "px";
      dot.style.top = (spot.y - oy) + "px";
      canvas.appendChild(dot);
    }
  }

  for (const note of section.notes || []) {
    const tag = el("div", "roomnote", note.text || "");
    tag.style.left = (note.at[0] - ox) + "px";
    tag.style.top = (note.at[1] - oy) + "px";
    canvas.appendChild(tag);
  }

  applyZoom(section);
}

function tint(node, hue) {
  // One hue in, three shades out -- see `.seatcard` and `.shape` in
  // seating.css. An ungrouped seat is the same three roles at zero
  // chroma, which is what makes the unseated rail consistent for free.
  node.style.setProperty("--h", hue === null ? 255 : hue);
  node.style.setProperty("--c", hue === null ? 0 : 1);
}

function fillCard(card, who, version) {
  if (who) {
    const size = nameSize(who.top);
    const top = el("div", "top", who.top);
    top.style.fontSize = size + "px";
    card.appendChild(top);
    if (who.bottom) {
      const bottom = el("div", "bottom", who.bottom);
      // Always clearly the lesser of the two: a long first name shrinks
      // to 13, and a surname also at 13 beside it stops reading as
      // "first name, then surname" at all.
      bottom.style.fontSize = Math.min(13, size - 3) + "px";
      card.appendChild(bottom);
    }
    card.title = who.full;
  }
  if (version) card.appendChild(el("span", "ver", version));
}

// --------------------------------------------------------- group labels --

function shapesHolding(section, group) {
  const mine = new Set(group.seats || []);
  return (section.shapes || []).filter(
    s => (s.seats || []).some(seat => mine.has(seat.id)));
}

function anchorsFor(section, groupId) {
  /* Every anchor on every desk this group sits at, with the one
     currently in use marked. A group spanning two desks gets both
     sets, because either is an honest place for its label. */
  const group = groupsOf(section).find(g => g.id === groupId);
  if (!group) return [];
  const at = group.label_at;
  const out = [];
  for (const shape of shapesHolding(section, group)) {
    const spec = seatingState.shapes[shape.kind];
    if (!spec) continue;
    for (const key of Object.keys(ANCHORS)) {
      const [fx, fy] = ANCHORS[key];
      out.push({
        shape: shape.id, anchor: key,
        x: shape.at[0] + fx * spec.w,
        y: shape.at[1] + fy * spec.h,
        on: Boolean(at) && at.shape === shape.id && at.anchor === key,
      });
    }
  }
  return out;
}

function labelPoint(section, group, ids, where) {
  /* Where the label goes. An anchor if one has been set and the desk
     it names is still there; otherwise the middle of the group's
     seats, which is the centre of a table or the gap between desks
     that belong together.

     Unless the middle is where somebody is sitting. A table of one
     puts its centre exactly on the one card and a row of three puts it
     on the middle one, so the label covered a name. When that happens
     it drops below the group instead -- a default, not a rule, and
     overridden the moment an anchor is chosen. */
  if (group.label_at) {
    const spot = anchorsFor(section, group.id).find(
      a => a.shape === group.label_at.shape
        && a.anchor === group.label_at.anchor);
    if (spot) return [spot.x, spot.y];
  }
  const xs = ids.map(id => where[id][0]);
  const ys = ids.map(id => where[id][1]);
  const x = (Math.min(...xs) + Math.max(...xs)) / 2;
  let y = (Math.min(...ys) + Math.max(...ys)) / 2;
  const onSomebody = ids.some(id =>
    Math.abs(where[id][0] - x) < CARD_W * 0.55
    && Math.abs(where[id][1] - y) < CARD_H * 0.55);
  if (onSomebody) y = Math.max(...ys) + CARD_H / 2 + 15;
  return [x, y];
}

function dragLabel(event, tag, section, group, ids, where) {
  /* Click selects; dragging moves the label to an anchor. The anchors
     are already on screen by the time a drag is possible, because
     selecting is what put them there -- which is the whole reason
     there is no anchor picker in the strip. */
  if (event.pointerType === "mouse" && event.button !== 0) return;
  event.preventDefault();
  if (seatingMode === "view") return;
  if (!isSelected(group, null)) { choose(group, null); return; }

  const spots = anchorsFor(section, group.id);
  const ox = drawn.box ? drawn.box.x : 0, oy = drawn.box ? drawn.box.y : 0;
  const start = [event.clientX, event.clientY];
  let moved = false, best = null;

  const place = e => {
    if (Math.hypot(e.clientX - start[0], e.clientY - start[1]) < 4) return;
    moved = true;
    tag.classList.add("dragging");
    const [cx, cy] = roomPoint(e);
    let near = Infinity;
    best = null;
    for (const spot of spots) {
      const d = Math.hypot(spot.x - cx, spot.y - cy);
      if (d < near) { near = d; best = spot; }
    }
    // Follows the pointer, and snaps to the nearest anchor once it is
    // close enough to be meant.
    const snap = best && near <= 110;
    tag.style.left = ((snap ? best.x : cx) - ox) + "px";
    tag.style.top = ((snap ? best.y : cy) - oy) + "px";
    for (const dot of document.querySelectorAll("#canvas .anchor"))
      dot.classList.remove("near");
    if (snap) {
      const i = spots.indexOf(best);
      const dots = document.querySelectorAll("#canvas .anchor");
      if (dots[i]) dots[i].classList.add("near");
    }
  };

  const finish = commit => {
    tag.onpointermove = tag.onpointerup = tag.onpointercancel = null;
    tag.classList.remove("dragging");
    if (!moved) { renderSeating(); return; }   // a click on a chosen label
    if (commit && best) group.label_at = { shape: best.shape,
                                           anchor: best.anchor };
    renderSeating();
  };

  tag.setPointerCapture(event.pointerId);
  tag.onpointermove = place;
  tag.onpointerup = () => finish(true);
  tag.onpointercancel = () => finish(false);
}

// ------------------------------------------------------------ selection --

function isSelected(group, shape) {
  if (!selected) return false;
  if (selected.kind === "group")
    return Boolean(group) && group.id === selected.id;
  return Boolean(shape) && shape.id === selected.id;
}

function choose(group, shape) {
  /* A table belongs to its group when it has one: what the instructor
     cares about is the group, and the shape is how it is drawn. A desk
     in no group selects itself, which is the rule the print order
     already uses -- a seat in no group is a group of one. */
  const next = group ? { kind: "group", id: group.id }
             : shape ? { kind: "shape", id: shape.id } : null;
  selected = (selected && next && selected.kind === next.kind
              && selected.id === next.id) ? null : next;
  renderSeating();
}

function drawStrip(section) {
  /* One thin strip, with no expanded state. An earlier draft was a tall
     panel with a label field, a swatch row, a nine-cell anchor picker
     and "Prints 2nd of 7"; most of it was a second way to say what the
     canvas already says.

     It holds whatever is in focus. Usually that is the selection; in
     Up Next it is the turn. Same slot, because at any moment there is
     one thing the room is about. */
  const strip = document.getElementById("seat-strip");
  strip.textContent = "";
  if (seatingMode === "upnext") { drawUpNext(strip, section); return; }
  const group = selected && selected.kind === "group"
    ? groupsOf(section).find(g => g.id === selected.id) : null;
  const shape = selected && selected.kind === "shape"
    ? (section.shapes || []).find(s => s.id === selected.id) : null;
  if (!group && !shape) { strip.hidden = true; return; }
  strip.hidden = false;

  if (!group) {
    const spec = seatingState.shapes[shape.kind];
    strip.appendChild(el("span", "sname", (spec && spec.label) || shape.kind));
    const n = (shape.seats || []).length;
    strip.appendChild(el("span", "smeta",
                         n + (n === 1 ? " chair" : " chairs")));
    return;
  }

  // One dot that opens the swatches, rather than six swatches always
  // on show: the strip has to stay one row at 515px.
  const dot = el("button", "swatch");
  dot.type = "button";
  dot.title = "Colour";
  tint(dot, hueOf(section, group));
  dot.onclick = e => { e.stopPropagation(); openHues(dot, section, group); };
  strip.appendChild(dot);

  // The heading is the label; clicking it renames. A separate text
  // field below a heading saying the same thing was the first draft.
  const name = el("span", "sname", group.label || "(no label)");
  name.title = "Click to rename";
  name.onclick = () => renameGroup(name, group);
  strip.appendChild(name);

  const n = (group.seats || []).length;
  strip.appendChild(el("span", "smeta", n + (n === 1 ? " seat" : " seats")));

  const placed = groupsOf(section)
    .filter(g => g.order !== null && g.order !== undefined)
    .sort((a, b) => a.order - b.order);
  const at = placed.indexOf(group);
  const total = groupsOf(section).length;
  const ord = el("span", "sord", (at < 0 ? "–" : at + 1) + "/" + total);
  ord.title = at < 0 ? "No place in the print order yet"
                     : `Prints ${at + 1} of ${total}`;
  strip.appendChild(ord);
}

// --------------------------------------------------------- up next --

function whoCanBeCalled() {
  // Only people in the room on screen: a chart on the projector is one
  // section, and calling on somebody from the other one is a mistake
  // nobody would understand.
  return drawn.seats.filter(s => s.seat.student);
}

function pickNext() {
  const here = whoCanBeCalled();
  if (!here.length) { toast("Nobody is seated in this room yet."); return; }
  let pool = here.filter(s => !called.has(s.seat.student));
  if (!pool.length) {
    // Round over. Start another rather than refusing, and say so,
    // because "everyone has had a turn" is worth hearing.
    called = new Set();
    pool = here;
    toast("Everybody has had a turn — starting again.");
  }
  const chair = pool[Math.floor(Math.random() * pool.length)];
  calling = chair.seat.student;
  called.add(calling);
  renderSeating();
}

function drawUpNext(strip, section) {
  strip.hidden = false;
  const here = whoCanBeCalled();
  const who = calling ? seatingState.names[calling] : null;

  if (who) {
    const dot = el("span", "swatch");
    tint(dot, null);
    dot.style.background = "var(--isle-key)";
    strip.appendChild(dot);
    strip.appendChild(el("span", "sname", who.full));
  } else {
    strip.appendChild(el("span", "smeta",
      here.length ? "Nobody up yet" : "Nobody is seated here"));
  }

  const next = el("button", "ibtn key", calling ? "Next" : "Pick someone");
  next.type = "button";
  next.title = "Space picks the next one";
  next.onclick = pickNext;
  strip.appendChild(next);

  if (called.size) {
    strip.appendChild(el("span", "smeta",
                         called.size + "/" + here.length));
    const again = el("button", "ibtn", "Start over");
    again.type = "button";
    again.title = "Everybody back in the hat";
    again.onclick = () => { called = new Set(); calling = null; renderSeating(); };
    strip.appendChild(again);
  }
}

function openHues(near, section, group) {
  document.querySelectorAll(".hues").forEach(n => n.remove());
  const pop = el("div", "hues");
  for (const hue of HUES) {
    const b = el("button", "hue" + (hueOf(section, group) === hue
                                    ? " on" : ""));
    b.type = "button";
    b.style.setProperty("--h", hue);
    b.onclick = () => {
      group.hue = hue;
      pop.remove();
      renderSeating();
    };
    pop.appendChild(b);
  }
  document.getElementById("view-seating").appendChild(pop);
  const box = near.getBoundingClientRect();
  const app = document.getElementById("view-seating").getBoundingClientRect();
  pop.style.left = Math.round(box.left - app.left - 6) + "px";
  pop.style.bottom = Math.round(app.bottom - box.top + 8) + "px";
  const shut = e => {
    if (pop.contains(e.target)) return;
    pop.remove();
    document.removeEventListener("pointerdown", shut, true);
  };
  setTimeout(() => document.addEventListener("pointerdown", shut, true), 0);
}

function renameGroup(span, group) {
  /* Edit in place. The label is already on screen in the strip and on
     the pill, so a dialog would be a third copy of it. */
  const input = el("input", "srename");
  input.type = "text";
  input.value = group.label || "";
  span.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const settle = keep => {
    if (done) return;
    done = true;
    if (keep) group.label = input.value.trim();
    renderSeating();
  };
  input.onblur = () => settle(true);
  input.onkeydown = e => {
    if (e.key === "Enter") { e.preventDefault(); settle(true); }
    // Escape has to stop here, or the view's own handler takes it as
    // "clear the selection" and the strip vanishes mid-edit.
    if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); settle(false); }
  };
}

function drawPen(section) {
  /* Everyone with no chair, as the students they are: the same card as
     a seated one, grey because it has no group. Being grey is the
     status -- it needs no caption, and an earlier "2 standing" said in
     words what the design should carry.

     Hidden when everybody is seated, because an empty rail is a box
     around nothing; it comes back mid-drag as a drop target. */
  const pen = seatingPen();
  pen.textContent = "";
  pen.classList.remove("over");
  if (seatingMode !== "people") { pen.hidden = true; return; }

  const sitting = new Set();
  for (const sec of seatingRoom.sections || [])
    for (const shape of sec.shapes || [])
      for (const seat of shape.seats || [])
        if (seat.student) sitting.add(seat.student);

  // Filtered to this section when the roster uses that name; when it
  // does not, everybody is shown, because hiding people behind a name
  // mismatch is the worse of the two failures.
  const name = section.name || "";
  const known = Object.values(seatingState.sections).includes(name);
  const standing = Object.keys(seatingState.names)
    .filter(k => !sitting.has(k)
                 && (!known || seatingState.sections[k] === name))
    .sort((a, b) => seatingState.names[a].full
                      .localeCompare(seatingState.names[b].full));

  pen.hidden = standing.length === 0;
  for (const key of standing) {
    const card = el("div", "seatcard movable");
    tint(card, null);
    fillCard(card, seatingState.names[key], "");
    if (picked && !picked.seat && picked.who === key)
      card.classList.add("picked");
    card.onpointerdown = e => dragName(e, card, { key: key });
    pen.appendChild(card);
  }
}

function drawStageBar(section, count) {
  const stage = document.getElementById("seat-stage");
  stage.hidden = !presenting();
  document.getElementById("stage-section").textContent = section.name || "";
  /* While picking, the bar carries the count -- the islands are gone
     and the lit chair says who, but how far through the class has been
     is the one thing the room cannot show. */
  const keys = seatingMode === "upnext"
    ? (called.size ? called.size + " of " + whoCanBeCalled().length
                     + " · space for the next · esc to leave"
                   : "space to pick somebody · esc to leave")
    : (count > 1 ? "← → section · esc to leave" : "esc to leave");
  document.getElementById("stage-keys").textContent = keys;
}

// ------------------------------------------------------------------ menu --

/* The inverse of the rail's rule: if it changes what the canvas *is*
   rather than what a click *does*, and it is not done every few
   minutes, it is in here. */
function toggleMenu(force) {
  const sheet = document.getElementById("seat-sheet");
  const open = force !== undefined ? force : sheet.hidden;
  sheet.hidden = !open;
  document.getElementById("seat-menu")
    .setAttribute("aria-expanded", String(open));
  if (open) drawMenu();
}

function drawMenu() {
  const sheet = document.getElementById("seat-sheet");
  sheet.textContent = "";
  const sections = (seatingRoom && seatingRoom.sections) || [];

  if (sections.length > 1) {
    const box = el("div", "mgroup");
    box.appendChild(el("div", "mhead", "Section"));
    sections.forEach((s, i) => {
      const b = el("button", "mitem" + (i === seatingSection ? " ticked" : ""),
                   s.name || `section ${i + 1}`);
      b.type = "button";
      b.onclick = () => { toggleMenu(false); goToSection(i); };
      box.appendChild(b);
    });
    sheet.appendChild(box);
  }

  const show = el("div", "mgroup");
  show.appendChild(el("div", "mhead", "Show"));
  const toggles = [
    ["Version letters", () => showVersions, v => { showVersions = v; }],
    ["Group labels", () => showLabels, v => { showLabels = v; }],
  ];
  for (const [label, get, set] of toggles) {
    const b = el("button", "mitem" + (get() ? " ticked" : ""), label);
    b.type = "button";
    b.onclick = () => { set(!get()); drawMenu(); renderSeating(); };
    show.appendChild(b);
  }
  sheet.appendChild(show);

  const acts = el("div", "mgroup");
  acts.appendChild(el("div", "mhead", "Room"));
  const revert = el("button", "mitem", "Discard changes");
  revert.type = "button";
  revert.disabled = !seatingDirty();
  revert.onclick = () => {
    seatingRoom = JSON.parse(JSON.stringify(seatingState.room));
    selected = null;
    picked = null;
    toggleMenu(false);
    renderSeating();
  };
  acts.appendChild(revert);
  sheet.appendChild(acts);
}

// -------------------------------------------------------------- dragging --

function canvasScale() {
  /* The canvas is laid out at room size and CSS-scaled, so a pointer
     that moved N screen pixels moved N/scale room units. Measured off
     the DOM rather than read from `seatingZoom`, which is null while
     the zoom is "fit": one source of truth, and it cannot drift. */
  const canvas = seatingCanvas();
  return canvas.getBoundingClientRect().width / (canvas.offsetWidth || 1);
}

function roomPoint(event) {
  // The canvas is drawn from the content box's corner rather than from
  // (0, 0), so the origin goes back on here.
  const box = seatingCanvas().getBoundingClientRect();
  const scale = canvasScale();
  const area = drawn.box || { x: 0, y: 0 };
  return [(event.clientX - box.left) / scale + area.x,
          (event.clientY - box.top) / scale + area.y];
}

function liftGhost(element, event) {
  /* A copy that follows the pointer, in `document.body`.

     A copy and not the element itself, for two reasons: a transformed
     ancestor makes `position: fixed` behave like `absolute`, so
     anything left inside the scaled canvas cannot be pinned to the
     cursor; and leaving the original in place means a drag that ends
     nowhere has nothing to undo. The transform matches what was
     grabbed, so the ghost is the size of the card under the cursor. */
  const box = element.getBoundingClientRect();
  const ghost = element.cloneNode(true);
  ghost.className = element.className.replace("movable", "") + " ghost";
  ghost.style.width = element.offsetWidth + "px";
  ghost.style.height = element.offsetHeight + "px";
  ghost.style.transform = `scale(${box.width / (element.offsetWidth || 1)})`;
  document.body.appendChild(ghost);
  element.classList.add("lifted");
  return { ghost: ghost,
           hold: [event.clientX - box.left, event.clientY - box.top] };
}

function dropTarget(event, fromId) {
  /* Where a release would put this name: a chair, the unseated rail, or
     nowhere. Nearest chair to the *pointer*, so the chair you point at
     is the chair you get however you grabbed the card. Geometry rather
     than `elementFromPoint`, because the cards overhang each other and
     the ghost is under the cursor. */
  const pen = seatingPen();
  const box = pen.getBoundingClientRect();
  if (!pen.hidden && event.clientX >= box.left - 14
      && event.clientX <= box.right && event.clientY >= box.top
      && event.clientY <= box.bottom)
    return { kind: "pen" };

  const [cx, cy] = roomPoint(event);
  let best = null, near = REACH;
  for (const chair of drawn.seats) {
    if (chair.id === fromId) continue;
    const d = Math.hypot(chair.x - cx, chair.y - cy);
    if (d < near) { near = d; best = chair; }
  }
  return best ? { kind: "seat", chair: best } : null;
}

function markTarget(target, on) {
  if (!target) return;
  if (target.kind === "pen") seatingPen().classList.toggle("over", on);
  else if (drawn.cards[target.chair.id])
    drawn.cards[target.chair.id].classList.toggle("over", on);
}

function movePerson(who, fromSeat, toSeat) {
  /* The whole of what a move is, in one place, so the drag and the
     click cannot drift into meaning different things.

     `toSeat` null is the unseated rail. Otherwise whoever was there
     takes the vacated chair -- a swap from a chair, and from the rail a
     plain displacement, where `fromSeat` is null and the sitter joins
     the standing.

     The letters are untouched on purpose: a version belongs to the
     chair, because the colouring is of the room, so two people trading
     places must not trade letters or a swap could seat the same paper
     next to itself. */
  if (!toSeat) {
    if (fromSeat) fromSeat.student = "";
    return;
  }
  const sat = toSeat.student;
  toSeat.student = who;
  if (fromSeat) fromSeat.student = sat;
}

function clickOn(from) {
  /* Click a name, then click a chair. Not a fallback for dragging --
     the classroom tools lead with it, and on a trackpad it is the
     easier of the two. Shares `movePerson` with the drag.

     Clicking the held name again puts it down, which is the undo
     anybody tries first. */
  const seat = from.seat || null;
  const who = seat ? seat.student : from.key;

  if (picked) {
    const held = picked;
    picked = null;
    const sameAgain = seat ? held.seat === seat : held.who === from.key;
    if (!sameAgain) movePerson(held.who, held.seat, seat);
    renderSeating();
    return;
  }
  if (!who) return;              // an empty chair, with nothing in hand
  picked = { who: who, seat: seat };
  renderSeating();
}

function dragName(event, element, from) {
  /* Move a person. `from` is `{seat}` -- a chair in the room -- or
     `{key}` -- a card on the unseated rail. One function, because the
     two differ only at the ends. */
  if (event.pointerType === "mouse" && event.button !== 0) return;
  event.preventDefault();

  const who = from.seat ? from.seat.student : from.key;
  const fromId = from.seat ? from.seat.id : null;
  const start = [event.clientX, event.clientY];
  let target = null, lift = null;

  const place = e => {
    /* Nothing happens until the pointer has travelled. Without this a
       plain click is a drop: in a 2x2 table the chair behind is within
       reach of a pointer that never moved, so clicking somebody would
       quietly swap them with the person behind them. */
    if (!lift) {
      if (Math.hypot(e.clientX - start[0], e.clientY - start[1]) < 4) return;
      lift = liftGhost(element, event);
    }
    lift.ghost.style.left = (e.clientX - lift.hold[0]) + "px";
    lift.ghost.style.top = (e.clientY - lift.hold[1]) + "px";
    const next = dropTarget(e, fromId);
    const same = next && target && next.kind === target.kind
      && (next.kind === "pen" || next.chair.id === target.chair.id);
    if (!same) {
      markTarget(target, false);
      target = next;
      markTarget(target, true);
    }
  };

  const finish = commit => {
    element.onpointermove = element.onpointerup = null;
    element.onpointercancel = null;
    // Never travelled, so it was a click. The two gestures share this
    // handler because the pointer cannot tell them apart until it moves.
    if (!lift) { if (commit) clickOn(from); return; }
    lift.ghost.remove();
    element.classList.remove("lifted");
    markTarget(target, false);

    // Nowhere is a cancel, not an eviction. Losing somebody out of the
    // chart because a drop was a few pixels short is not a trade worth
    // making; standing them up has the rail for a target.
    if (!commit || !target) { renderSeating(); return; }
    picked = null;
    movePerson(who, from.seat || null,
               target.kind === "pen" ? null : target.chair.seat);
    renderSeating();
  };

  element.setPointerCapture(event.pointerId);
  element.onpointermove = who ? place : null;
  element.onpointerup = () => finish(true);
  // A cancel is the gesture being taken away -- a scroll starting, a
  // context menu, a pen leaving range. Not a quiet yes.
  element.onpointercancel = () => finish(false);
}

function clampShape(section, spec, x, y) {
  /* Inside the canvas, snapped to the grid. `hi` is floored at `lo` for
     a table wider than the room it is in, where the two bounds cross
     and a plain min/max flings it off the left edge. */
  const size = section.canvas || { width: 1000, height: 700 };
  const fit = (v, extent, span) => {
    const lo = span / 2, hi = Math.max(lo, extent - span / 2);
    return Math.min(Math.max(Math.round(v / GRID) * GRID, lo), hi);
  };
  return [fit(x, size.width, spec.w), fit(y, size.height, spec.h)];
}

function dragShape(event, section, shape) {
  /* Move a desk, and everyone at it. The desk itself moves rather than
     a ghost: a card is transferred and wants a ghost, but a desk is
     being positioned and watching it go is the point. */
  if (event.pointerType === "mouse" && event.button !== 0) return;
  event.preventDefault();
  const spec = seatingState.shapes[shape.kind];
  if (!spec) return;

  const box = drawn.shapes[shape.id];
  box.focus();
  const scale = canvasScale();
  const start = [event.clientX, event.clientY];
  const home = shape.at.slice();
  const mine = (shape.seats || []).map(seat => seat.id);
  const riding = mine.map(id => drawn.cards[id]).filter(Boolean);
  // A label whose group sits entirely at this desk travels with it. One
  // spanning two desks stays and snaps on release, because half of it
  // is not moving and there is no honest place to put it.
  const tags = drawn.labels
    .filter(l => l.seats.every(id => mine.includes(id)))
    .map(l => l.el);
  const held = [...riding, ...tags].map(n => [n, n.offsetLeft, n.offsetTop]);
  const ox = drawn.box ? drawn.box.x : 0, oy = drawn.box ? drawn.box.y : 0;

  box.classList.add("dragging");
  let moved = false;

  const place = e => {
    if (Math.hypot(e.clientX - start[0], e.clientY - start[1]) < 4) return;
    moved = true;
    const to = clampShape(section, spec,
                          home[0] + (e.clientX - start[0]) / scale,
                          home[1] + (e.clientY - start[1]) / scale);
    box.style.left = (to[0] - spec.w / 2 - ox) + "px";
    box.style.top = (to[1] - spec.h / 2 - oy) + "px";
    for (const [node, left, top] of held) {
      node.style.left = (left + to[0] - home[0]) + "px";
      node.style.top = (top + to[1] - home[1]) + "px";
    }
    shape.at = to;
  };

  const finish = commit => {
    box.onpointermove = box.onpointerup = box.onpointercancel = null;
    box.classList.remove("dragging");
    // `place` writes straight to the model as the desk moves, so
    // putting it back is the undo.
    if (!commit) shape.at = home;
    if (!moved) {
      // A click in Desks mode still selects, the way it does in the
      // other modes: one gesture should not mean nothing here.
      if (commit) {
        const group = (shape.seats || [])
          .map(x => groupOfSeat(section)[x.id]).find(Boolean);
        choose(group, shape);
      }
      return;
    }
    renderSeating();
    const again = drawn.shapes[shape.id];
    if (again) again.focus();               // the re-draw threw focus away
  };

  box.setPointerCapture(event.pointerId);
  box.onpointermove = place;
  box.onpointerup = () => finish(true);
  box.onpointercancel = () => finish(false);
}

function nudgeShape(event, section, shape) {
  /* Arrow keys, because a mouse is bad at the last few units and lining
     two desks up is most of drawing a room. Shift is the fine step, not
     the coarse one: the grid is the default and precision is the ask. */
  const step = event.shiftKey ? 1 : GRID;
  const by = { ArrowLeft: [-step, 0], ArrowRight: [step, 0],
               ArrowUp: [0, -step], ArrowDown: [0, step] }[event.key];
  if (!by) return;
  event.preventDefault();
  const spec = seatingState.shapes[shape.kind];
  if (!spec) return;
  // Off-grid on purpose with shift held: snapping first would eat the
  // nudge whole, since one unit rounds back to where it started.
  const to = [shape.at[0] + by[0], shape.at[1] + by[1]];
  shape.at = event.shiftKey ? to : clampShape(section, spec, to[0], to[1]);
  renderSeating();
  const again = drawn.shapes[shape.id];
  if (again) again.focus();
}

// ------------------------------------------------------------------ zoom --

function fitZoom(paper, area) {
  /* Both axes, not just the width -- fitting the width alone left a
     tall room scrolling, which is not what "fit" offers to do. The cap
     is 4 rather than 1: on a projector the room should be blown up past
     life size, and refusing to go over 100% was most of why a small
     class filled a quarter of the screen.

     The right edge is given up to the unseated rail, so fitting never
     parks a table underneath it. */
  const pen = seatingPen();
  const gutter = pen.hidden ? 44 : pen.offsetWidth + 38;
  return Math.min(4, Math.max(0.05,
    Math.min((paper.clientWidth - gutter) / area.w,
             (paper.clientHeight - 140) / area.h)));
}

function applyZoom(section) {
  const canvas = seatingCanvas();
  const box = document.getElementById("canvasbox");
  const paper = seatingPaper();
  const pen = seatingPen();
  const area = (drawn.box && drawn.box.w) ? drawn.box : contentBox(section);

  const zoom = seatingZoom === null ? fitZoom(paper, area) : seatingZoom;
  canvas.style.transform = `scale(${zoom})`;
  /* The box carries the scaled size, so the scroller measures what is
     drawn. A scaled element's *layout* box is what overflow is computed
     from, which produced scrollbars for content wholly on screen. */
  box.style.width = Math.round(area.w * zoom) + "px";
  box.style.height = Math.round(area.h * zoom) + "px";
  // Centred in the space the rail leaves, rather than in the whole
  // paper, so Fit never puts a table under it.
  box.style.marginRight = (pen.hidden ? 0 : pen.offsetWidth + 22) + "px";
  document.getElementById("seat-zoom").textContent =
    Math.round(zoom * 100) + "%";
  layoutBottom();                 // the zoom island just changed width
}

function zoomBy(step) {
  const section = currentSection();
  if (!section) return;
  const area = (drawn.box && drawn.box.w) ? drawn.box : contentBox(section);
  // Proportional, not additive: a tenth of a point is a third of the
  // picture at 30% and a fortieth of it at 400%.
  const now = seatingZoom === null
    ? fitZoom(seatingPaper(), area) : seatingZoom;
  seatingZoom = Math.min(4, Math.max(0.15, now * (step > 0 ? 1.25 : 0.8)));
  applyZoom(section);
}

// ------------------------------------------------------------- projector --

async function present() {
  /* The room on the whole screen, with nothing else on it.

     Real fullscreen is asked for first, because the limit on how large
     a name can be is pixels of screen. If the host refuses it -- an
     embedded browser pane does, with "Permissions check failed" -- we
     still present, inside the window. That is the case to get right
     rather than to report: somebody is standing in front of a class. */
  const view = document.getElementById("view-seating");
  // Up Next survives: it is a mode for presenting, not one for
  // editing, and the whole reason Cold call stopped being a tab was
  // that it belongs on the projector with the room.
  if (seatingMode !== "upnext") seatingMode = "view";
  selected = null;
  picked = null;
  toggleMenu(false);
  document.body.classList.add("presenting");
  sizeSeating();
  seatingZoom = null;
  renderSeating();
  try {
    if (view.requestFullscreen)
      await view.requestFullscreen({ navigationUI: "hide" });
  } catch (err) {
    toast("Showing it in the window — this browser would not go fullscreen.");
  }
  sizeSeating();
  seatingZoom = null;
  renderSeating();                     // the screen just changed size
}

function leavePresenting() {
  document.body.classList.remove("presenting");
  if (document.fullscreenElement) document.exitFullscreen();
  sizeSeating();
  seatingZoom = null;
  renderSeating();
}

function presentKeys(event) {
  if (document.getElementById("view-seating").hidden) return;
  if (event.key === "Escape" && !presenting()) {
    if (picked) { picked = null; renderSeating(); return; }
    if (!document.getElementById("seat-sheet").hidden) {
      toggleMenu(false);
      return;
    }
    if (selected) { selected = null; renderSeating(); }
    return;
  }
  // Space picks the next one. The one key a person has a free hand for
  // while standing at the front, and it works whether or not the room
  // is on the projector.
  /* `event.target` is the document itself when nothing has focus, and
     a document has no `closest` -- which threw, and silently took the
     whole handler with it. Guarded rather than assumed: a keydown's
     target is not always an element. */
  const onControl = event.target instanceof Element
    && event.target.closest("input, button");
  if (seatingMode === "upnext" && (event.key === " " || event.key === "Enter")
      && !onControl) {
    event.preventDefault();
    pickNext();
    return;
  }
  if (!presenting()) return;
  if (event.key === "Escape") { leavePresenting(); return; }
  const sections = (seatingRoom && seatingRoom.sections) || [];
  const step = { ArrowRight: 1, ArrowDown: 1, PageDown: 1, " ": 1,
                 ArrowLeft: -1, ArrowUp: -1, PageUp: -1 }[event.key];
  if (!step || sections.length < 2) return;
  event.preventDefault();
  seatingSection = (seatingSection + step + sections.length) % sections.length;
  seatingZoom = null;
  renderSeating();
}

function onFullscreenChange() {
  // Leaving by the browser's own Escape has to leave the mode too, or
  // the chrome stays hidden with no way back.
  if (!document.fullscreenElement && presenting()) {
    leavePresenting();
    return;
  }
  sizeSeating();
  seatingZoom = null;
  if (seatingRoom) renderSeating();
}

// -------------------------------------------------------- load and save --

async function loadSeating() {
  // Unsaved work survives switching tabs and coming back: this runs on
  // every visit, not only the first.
  const keep = seatingDirty() ? seatingRoom : null;
  try {
    seatingState = await api("/api/seating", {});
  } catch (err) { toast(err.message, true); return; }
  seatingRoom = keep || JSON.parse(JSON.stringify(seatingState.room));
  sizeSeating();
  renderSeating();
}

async function saveSeating() {
  try {
    const out = await api("/api/seating/save", { room: seatingRoom });
    seatingState = out;
    seatingRoom = JSON.parse(JSON.stringify(out.room));
    renderSeating();
    toast(out.note);
  } catch (err) { toast(err.message, true); }
}

function sizeSeating() {
  /* The app fills what is left of the window. Measured rather than a
     constant: a flat allowance is right at one window width and wrong
     by two hundred pixels at another, where the host's nav wraps. */
  const view = document.getElementById("view-seating");
  if (view.hidden) return;
  if (presenting()) { view.style.height = "100vh"; }
  else {
    view.style.height = "";
    const top = view.getBoundingClientRect().top + window.scrollY;
    view.style.height = Math.max(260, window.innerHeight - top - 14) + "px";
  }
  layoutBottom();
}

function layoutBottom() {
  /* The rail is centred in the space the other islands leave, not in
     the whole width. Centred in the whole width it overlapped the zoom
     by twenty-one pixels at 515px -- and the answer to that is not to
     move zoom out of its corner, which was the fault in the first
     draft, but to centre the rail in what is actually free.

     Measured, because the zoom island is wider at some zoom levels
     than others -- "100%" is wider than "39%". */
  const rail = document.querySelector("#view-seating .at-bc");
  const zoom = document.querySelector("#view-seating .at-bl");
  if (!rail || !zoom) return;
  if (window.innerWidth > 760 || presenting()) {
    rail.style.left = rail.style.right = rail.style.transform = "";
    return;
  }
  const paper = seatingPaper().getBoundingClientRect();
  rail.style.left =
    Math.round(zoom.getBoundingClientRect().right - paper.left + 14) + "px";
  rail.style.right = "12px";
  rail.style.transform = "none";
}

// --------------------------------------------------------------- wiring --

/* Its own, rather than lines inside the host's `boot`. The host calls
   `loadSeating` when the tab opens and otherwise knows nothing about
   what is in here. */
function wireSeating() {
  document.getElementById("seat-in").onclick = () => zoomBy(1);
  document.getElementById("seat-out").onclick = () => zoomBy(-1);
  document.getElementById("seat-zoom").onclick = () => {
    seatingZoom = null;
    const section = currentSection();
    if (section) applyZoom(section);
  };
  document.getElementById("seat-present").onclick = present;
  document.getElementById("seat-save").onclick = saveSeating;
  document.getElementById("seat-menu").onclick = e => {
    e.stopPropagation();
    toggleMenu();
  };
  // Clicking the paper, rather than a thing on it, clears the selection
  // and shuts the menu: the gesture everybody tries.
  seatingPaper().addEventListener("pointerdown", e => {
    if (e.target.closest(".shape, .seatcard, .pill")) return;
    toggleMenu(false);
    if (selected) { selected = null; renderSeating(); }
  });
  document.addEventListener("fullscreenchange", onFullscreenChange);
  document.addEventListener("keydown", presentKeys);
  window.addEventListener("resize", () => {
    if (!seatingRoom || document.getElementById("view-seating").hidden) return;
    sizeSeating();
    const section = currentSection();
    if (section) applyZoom(section);
  });
}

wireSeating();
