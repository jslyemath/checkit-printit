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
/* How far the room has been dragged from where "fit" would put it, in
   screen pixels. The other half of the camera: `seatingZoom` is how
   close you are standing and this is where you are standing. Screen
   pixels rather than room units so that a drag of 10px moves the room
   10px whatever the zoom -- the room follows the hand exactly. */
let pan = { x: 0, y: 0 };
let seatingMode = "people";
/* What to go back to when projector mode is switched off. There
   is no View mode any more -- projecting *is* the read-only
   state, and leaving it should put you back where you were
   rather than somewhere neutral. */
let modeBefore = "people";

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

/* Up Next is a way of showing the room, not a way of editing it, so
   it is a switch that sits across whatever mode you are in rather than
   a sixth mode. It was in the rail, which made the rail dishonest: the
   test for belonging there is whether it changes what a click on the
   canvas means, and this does not.

   Three things to walk through, and the walk is a *line* rather than a
   draw from a hat. Stepping back has to show who you just had, and the
   count has to say how far through you are; both of those want an
   order that exists before you start rather than one made a name at a
   time. The line is still shuffled for people, so it is not the
   seating chart read aloud. */
let upnext = false;
let upnextKind = "person";          // person | group | rep
let upnextAt = -1;                  // -1 is "not started"
let upnextLine = [];
let upnextFor = "";                 // what the line was built for

const UPNEXT_KINDS = [
  { value: "person", icon: "people", label: "One at a time",
    why: "One student at a time, in a shuffled order." },
  { value: "group", icon: "groups", label: "A group at a time",
    why: "A whole group at a time, in print order." },
  { value: "rep", icon: "letters", label: "One from each group",
    why: "One student from every group at once, by version letter: "
      + "all the As, then all the Bs. A group with fewer seats than "
      + "there are letters comes round again from its first." },
];


/* Which seat is in hand in Seats mode. Its own thing rather than part
   of `selected`, because a seat is always a seat *of* a group: the
   group stays selected while one of its seats is being moved. */
let selectedChair = null;

/* Whether the furniture column is unrolled. Shut on every other
   click, because it is a thing you reach for once and then stop
   needing. */
let paletteOpen = false;

/* Whether the furled rail is showing its list. Module state rather
   than a class read off the DOM, because every re-render rebuilds the
   buttons and a menu you opened must not close because a desk moved. */
let railOpen = false;

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
const HUES = [255, 150, 35, 330, 285, 95, 195, 15, 70];

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
  people: "M5.5 20a6.5 6.5 0 0 1 13 0|O12,8,3.4",
  groups: "R3,4,18,7,1.5|R3,14,8,6,1.5|R14,14,7,6,1.5",
  seats: "R4,8,16,9,2|O8,5,1.8|O16,5,1.8|O8,20,1.8|O16,20,1.8",
  order: "M4 6h3M4 12h3M4 18h3M11 6h9M11 12h9M11 18h9",
  upnext: "M20.5 4.5h-17A1.5 1.5 0 0 0 2 6v9a1.5 1.5 0 0 0 1.5 1.5H7v4"
    + "l5-4h8.5a1.5 1.5 0 0 0 1.5-1.5V6a1.5 1.5 0 0 0-1.5-1.5z",
  grow: "M8 3H3v5M16 3h5v5M8 21H3v-5M16 21h5v-5",
  /* One big A on a card, and a label pill: each icon is a small
     picture of the thing it turns on. A and B side by side said
     "these differ" more precisely, and looked like two bugs on a
     windscreen -- at 22px there is room for one letterform drawn
     properly or two drawn badly. */
  letters: "R3,5.5,18,13,2.5|M8.1 15.6l3.9-8.1 3.9 8.1M9.6 12.6h4.8",
  tag: "M2 12a5 5 0 0 1 5-5h10a5 5 0 0 1 0 10H7a5 5 0 0 1-5-5z"
    + "|M7.5 12h9",
  projector: "R2,7,14,10,2|M16 11l5-3v8l-5-3z|O9,12,2.4",
  shrink: "M3 8h5V3M21 8h-5V3M3 16h5v5M21 16h-5v5",
  trash: "M4 7h16|M10 11.5v6M14 11.5v6"
    + "|M6.2 7l.9 12.1A2 2 0 0 0 9.1 21h5.8a2 2 0 0 0 2-1.9L17.8 7"
    + "|M9.2 7V5.2A1.2 1.2 0 0 1 10.4 4h3.2a1.2 1.2 0 0 1 1.2 1.2V7",
  // Points the way the menu opens.
  chev: "M6 14.5l6-6 6 6",
  back: "M14.5 5l-6 7 6 7",
  fwd: "M9.5 5l6 7-6 7",
  // One card in front of another: the picture of making a second one.
  copy: "R8,8,13,13,2.5|M16 5V4.5A2.5 2.5 0 0 0 13.5 2h-9A2.5 2.5 0 0 0 2"
    + " 4.5v9A2.5 2.5 0 0 0 4.5 16H5",
};

/* Modes only. Shuffle is an action and lives in the menu: an action
   among modes is a category error, and the test that keeps the rail
   honest is whether it changes what a click on the canvas means. */
const MODES = [
  { value: "people", label: "People", icon: "people",
    why: "Click a name then a chair, or drag it. Landing on somebody "
      + "swaps the two; the version letters stay with the chairs, so "
      + "neighbours still differ afterwards." },
  { value: "groups", label: "Groups", icon: "groups",
    why: "Add, move, resize and turn the furniture. Arrows nudge the "
      + "one you click by " + GRID + ", shift+arrows by 1." },
  { value: "seats", label: "Seats", icon: "seats",
    why: "Move the seats on a group, add one, take one away — and drag "
      + "a seat onto another group to move it there." },
  { value: "order", label: "Order", icon: "order",
    why: "The order papers are handed out in. Not built yet." },
];
const BUILT = new Set(["people", "groups", "seats"]);

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

function shapeSize(shape) {
  /* A desk's own size if it has been dragged to one, otherwise the
     kind's. Stored on the shape rather than invented as a new kind,
     so "table, 3 across" and a widened 2x2 are the same thing in the
     file as they are on screen. */
  const spec = seatingState.shapes[shape.kind] || { w: 120, h: 80 };
  return [Math.round(shape.w || spec.w), Math.round(shape.h || spec.h)];
}

function spin(dx, dy, deg) {
  if (!deg) return [dx, dy];
  const r = deg * Math.PI / 180, c = Math.cos(r), s = Math.sin(r);
  return [dx * c - dy * s, dx * s + dy * c];
}

/* Rotating a desk turns its chairs with it, and the way that is stored
   is by turning the offsets themselves rather than by remembering an
   angle and applying it everywhere afterwards.

   It means `room.seats_of`, the neighbour distances, the version
   colouring and `seating.toml` need to know nothing about rotation: a
   chair is where its offset says, as it always was. `angle` is kept
   only so the silhouette stays turned, and so a second rotation knows
   where it started. The cost is a rounding each time, which is why
   the offsets are rounded to whole units and not left to drift. */
function turnShape(shape, deg) {
  for (const seat of shape.seats || []) {
    const [x, y] = spin(seat.at[0], seat.at[1], deg);
    seat.at = [Math.round(x), Math.round(y)];
  }
  shape.angle = Math.round((((shape.angle || 0) + deg) % 360 + 360) % 360);
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
    // A turned rectangle needs a bigger box than an upright one: the
    // bounding box of a w by h at angle t is w|cos t| + h|sin t| wide.
    const [w, h] = shapeSize(shape);
    const r = (shape.angle || 0) * Math.PI / 180;
    const bw = Math.abs(w * Math.cos(r)) + Math.abs(h * Math.sin(r));
    const bh = Math.abs(w * Math.sin(r)) + Math.abs(h * Math.cos(r));
    grow(shape.at[0] - bw / 2, shape.at[1] - bh / 2,
         shape.at[0] + bw / 2, shape.at[1] + bh / 2);
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

function refit() {
  /* Fit means fit: the zoom goes back to automatic and so does the
     position. A Fit that left the room dragged half off the window
     would be answering half the question. */
  seatingZoom = null;
  pan.x = 0;
  pan.y = 0;
}

function seatingDirty() {
  return seatingRoom !== null && seatingState !== null
    && JSON.stringify(seatingRoom) !== JSON.stringify(seatingState.room);
}

function projecting() {
  return document.body.classList.contains("projecting");
}

function fullscreen() { return Boolean(document.fullscreenElement); }

/* Projector mode and fullscreen are two different wishes and used to
   be one button. Projecting is "show the room and nothing else, and
   do not let me move anything by accident"; fullscreen is "use the
   whole screen". Either is useful without the other -- a projector
   mirroring a window wants the first, and drawing a big room on a
   second monitor wants the second -- so they are two controls in two
   places, the first with the display switches and the second with
   the zoom, which is the question it belongs to. */
function setProjecting(on) {
  if (on === projecting()) return;
  if (on) {
    modeBefore = seatingMode;
    selected = null;
    picked = null;
    selectedChair = null;
    paletteOpen = false;
  } else {
    seatingMode = modeBefore;      // back where you were, not somewhere neutral
  }
  document.body.classList.toggle("projecting", on);
  paintChrome();
  if (seatingRoom) { sizeSeating(); refit(); renderSeating(); }
}

async function toggleFullscreen() {
  const view = document.getElementById("view-seating");
  try {
    if (fullscreen()) await document.exitFullscreen();
    else if (view.requestFullscreen)
      await view.requestFullscreen({ navigationUI: "hide" });
    else throw new Error("not offered");
  } catch (err) {
    toast("This browser would not go fullscreen — use the window's own.");
  }
  paintChrome();
}

function paintChrome() {
  /* The buttons whose icon or state depends on something other than
     the room: the two display switches, projector mode, fullscreen.

     Accent means one thing here -- "this is the state you are in".
     It used to also mean "look at me", which is why Present was
     accented while it was off. A switch that is lit when unused has
     nothing left to say when it is used. */
  const set = (id, icon, on, title) => {
    const b = document.getElementById(id);
    if (!b) return;
    b.textContent = "";
    b.appendChild(svgIcon(ICON[icon]));
    b.classList.toggle("on", Boolean(on));
    b.setAttribute("aria-pressed", String(Boolean(on)));
    b.title = title;
  };
  set("seat-versions", "letters", showVersions, "Version letters");
  set("seat-labels", "tag", showLabels, "Group labels");
  set("seat-upnext", "upnext", upnext,
      upnext ? "Stop showing who is up"
             : "Up Next: light one student, one group, or one from "
               + "each group");
  set("seat-project", "projector", projecting(),
      projecting() ? "Back to editing — escape does it too"
                   : "Projector mode: the room and nothing else");
  set("seat-full", fullscreen() ? "shrink" : "grow", fullscreen(),
      fullscreen() ? "Leave fullscreen" : "Fill the screen");

  const plus = document.getElementById("seat-plus");
  const section = currentSection();
  const shape = selected && selected.kind === "shape"
    ? (section && (section.shapes || []).find(s => s.id === selected.id))
    : (selected && selected.kind === "group" && section
       ? shapesHolding(section,
           groupsOf(section).find(g => g.id === selected.id) || {})[0] : null);
  const wanted = !projecting() && section
    && (seatingMode === "groups" || (seatingMode === "seats" && shape));
  plus.hidden = !wanted;
  plus.classList.toggle("on", seatingMode === "groups" && paletteOpen);
  plus.title = seatingMode === "seats"
    ? "Add a seat to this group" : "Add a group";
  plus.onclick = e => {
    e.stopPropagation();
    if (seatingMode === "seats") addChair(section, shape);
    else togglePalette();
  };
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
  drawPalette(section);
  drawStrip(section);
  drawStageBar(section, sections.length);
  // The plus belongs to the mode and the selection, so it is redrawn
  // with them rather than only when a switch is flipped.
  paintChrome();
}

function drawRail() {
  /* All five modes, always, in order -- even when only one of them is
     visible. Furling is done by collapsing the other four to nothing
     rather than by leaving them out, which is what makes the current
     mode rise into its own place in the list when the menu opens: the
     rows above it grow and push it up. Nothing has to move it there,
     and there is no moment where the list is in the wrong order. */
  const rail = document.getElementById("seat-modes");
  rail.classList.toggle("open", railOpen);   // before the rows exist
  rail.textContent = "";
  const column = el("div", "railmodes");
  for (const mode of MODES) {
    const b = el("button", "ibtn" + (mode.value === seatingMode ? " on" : ""));
    b.type = "button";
    b.title = mode.why;
    b.setAttribute("aria-pressed", String(mode.value === seatingMode));
    b.appendChild(svgIcon(ICON[mode.icon]));
    b.appendChild(el("span", "ilabel", mode.label));
    /* The chevron rides inside the current mode's own button rather
       than sitting beside the column as a button of its own. A
       separate one cost forty pixels of a bottom edge that has none
       to spare, and it put two targets on screen for one question --
       "which mode" and "show me the modes" are the same question when
       only one of them is visible. Hidden unless furled. */
    if (mode.value === seatingMode) {
      const chev = svgIcon(ICON.chev);
      chev.setAttribute("class", "railchev");
      b.appendChild(chev);
    }
    if (!BUILT.has(mode.value)) b.classList.add("soonish");
    b.onclick = () => {
      if (!BUILT.has(mode.value)) { toast(mode.why); return; }
      // Furled, the current mode's button is the handle on the list:
      // it opens it, and pressing it again puts it away.
      if (rail.classList.contains("furled") && mode.value === seatingMode) {
        railOpen = !railOpen;
        renderSeating();
        return;
      }
      seatingMode = mode.value;
      picked = null;
      selectedChair = null;
      railOpen = false;              // picking one is also closing it
      renderSeating();
    };
    column.appendChild(b);
  }
  rail.appendChild(column);
  layoutRail();
}

function railWidthUnfurled(rail) {
  /* How wide the rail would be with all five modes across, measured on
     a copy.

     The first version of this measured the real thing: take `.furled`
     off, read `offsetWidth`, put it back. I wrote that it could not
     paint because nothing had yielded -- which is true of painting and
     beside the point. Reading `offsetWidth` forces a style recalc, and
     that recalc *commits* the unfurled style, which starts every
     transition on the way to it. Putting the class back a line later
     starts them all again in reverse. So the rail jumped open and
     snapped shut on every render -- every drag, every selection, every
     resize -- because measuring it was indistinguishable from opening
     it.

     A detached copy has the same ancestors and the same classes, so
     every media query that applies to the rail applies to it, and its
     transitions are turned off and it is never on screen. */
  const ghost = rail.cloneNode(true);
  ghost.classList.remove("furled", "open");
  ghost.style.cssText = "position:absolute;left:-9999px;top:0;"
    + "visibility:hidden;transform:none;transition:none";
  for (const node of ghost.querySelectorAll("*"))
    node.style.transition = "none";
  rail.parentNode.appendChild(ghost);
  const wide = ghost.offsetWidth;
  ghost.remove();
  return wide;
}

function layoutRail() {
  /* Furl when the rail, the zoom island and the plus can no longer
     share the bottom edge.

     Measured, not a breakpoint. The rail's width is five words in
     whatever font the system hands us, and the zoom island's width
     moves with the number in it -- "100%" is wider than "39%" -- so a
     number written in the stylesheet would be wrong on somebody
     else's machine and wrong here at some zoom levels.

     Measured *unfurled*, whatever state it is in: the question is
     whether the open row would fit, not whether the closed one does.
     Removing the class and reading `offsetWidth` in the same tick
     forces a layout but cannot paint, so nothing flickers. */
  const rail = document.getElementById("seat-modes");
  if (!rail || !rail.firstChild) return;
  if (projecting()) { rail.classList.remove("furled"); return; }

  const wide = railWidthUnfurled(rail);
  const zoom = document.querySelector("#view-seating .at-bl");
  const half = seatingPaper().clientWidth / 2;
  // The rail is centred, so half of it has to clear whichever corner
  // is further in: the zoom island on the left, the plus on the right.
  const need = wide / 2 + Math.max((zoom ? zoom.offsetWidth : 0) + 26, 70);
  const furl = need > half;
  rail.classList.toggle("furled", furl);
  if (!furl && railOpen) {
    railOpen = false;                // a wide window has no list to close
    rail.classList.remove("open");
  }

  /* Centred in the window, and nudged only when centred would overlap.

     Furling alone does not finish the job: at 530 the two corners take
     two thirds of the bottom edge between them, so even a 125px pill
     centred on the window sits eight pixels inside the zoom island.
     There is room -- 226px of it -- just not in the middle.

     So: want the window's centre, and clamp that into what is free.
     Above about 545 the clamp never bites and the pill is exactly
     centred, which is the behaviour to keep; below it the pill slides
     the smallest distance that clears, rather than being re-centred in
     the gap and sitting visibly off to one side at every width.

     The old version of this idea was deleted last round because the
     rail crept sideways as the zoom readout changed width -- "100%" is
     wider than "39%". That cause is gone: `.zoomnum` has a fixed width
     now, so the left bound is a constant for a given window and
     nothing moves while you zoom. The plus is reserved whether or not
     it is showing, for the same reason: a bound that changes with the
     mode would walk the pill about as you worked. */
  if (!furl) {
    rail.style.left = rail.style.transform = "";
    return;
  }
  const pill = rail.offsetWidth;
  const lo = (zoom ? zoom.offsetWidth : 0) + 12 + 10;
  const hi = half * 2 - (12 + 44 + 10) - pill;
  const mid = half - pill / 2;
  rail.style.left = Math.round(Math.max(lo, Math.min(mid, hi))) + "px";
  rail.style.transform = "none";
  const here = rail.querySelector(".railmodes .ibtn.on");
  if (here) here.title = !furl ? (MODES.find(m => m.value === seatingMode)
                                  || {}).why
    : railOpen ? "Put the list away" : "Every mode";
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
  upnextAt = -1;
  upnextFor = "";
  refit();                         // each room fits on its own terms
  renderSeating();
}

function drawRoom(section) {
  const s = seatingState;
  const canvas = seatingCanvas();
  canvas.textContent = "";
  canvas.className = "canvas mode-" + seatingMode
    + (upnext && upnextAt >= 0 ? " hushed" : "");

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
    const chroma = chromaOf(group);

    /* Two elements, not one. `.deskwrap` carries the position, the
       size and the rotation; `.shape` is only the silhouette inside
       it. Everything that belongs to the desk -- the resize handles,
       the rotation handle, the nine label anchors -- goes in the wrap,
       so it moves and turns with the desk for free.

       That is also the fix for the anchors that stayed behind when a
       desk was dragged: they were separate elements being tracked by
       hand, and the hand missed them. */
    const [sw, sh] = shapeSize(shape);
    const wrap = el("div", "deskwrap");
    wrap.style.left = (shape.at[0] - sw / 2 - ox) + "px";
    wrap.style.top = (shape.at[1] - sh / 2 - oy) + "px";
    wrap.style.width = sw + "px";
    wrap.style.height = sh + "px";
    if (shape.angle) wrap.style.transform = `rotate(${shape.angle}deg)`;
    // The hue goes on the wrap, not on the silhouette: the grips and
    // the rotation handle are the silhouette's *siblings*, so a
    // custom property set on it reaches none of them, and they came
    // out invisible -- white dots on white paper.
    tint(wrap, hue, chroma);
    canvas.appendChild(wrap);

    const box = el("div", "shape " + spec.css);
    wrap.appendChild(box);
    if (isSelected(group, shape)) wrap.classList.add("chosen");
    if (seatingMode === "groups") {
      box.classList.add("movable");
      box.tabIndex = 0;
      box.onkeydown = e => nudgeShape(e, section, shape);
      box.onpointerdown = e => dragShape(e, section, shape);
      if (isSelected(group, shape) || isSelected(null, shape))
        addHandles(wrap, section, shape);
    } else if (seatingMode === "seats") {
      // The desk itself, not its group: this mode is about the
      // furniture, and a group spanning two desks would otherwise
      // leave it ambiguous which one's chairs were being moved.
      box.classList.add("movable");
      if (isSelected(null, shape)) wrap.classList.add("chosen");
      box.onpointerdown = e => {
        e.preventDefault();
        selectedChair = null;
        choose(null, shape);
      };
    } else {
      box.onpointerdown = e => { e.preventDefault(); choose(group, shape); };
    }
    drawn.shapes[shape.id] = wrap;

    for (const seat of shape.seats || []) {
      const [x, y] = cardPosition(shape, seat);
      where[seat.id] = [x, y];
      const who = s.names[seat.student];
      const card = el("div", "seatcard" + (who ? "" : " empty"));
      tint(card, hue, chroma);
      card.style.left = (x - CARD_W / 2 - ox) + "px";
      card.style.top = (y - CARD_H / 2 - oy) + "px";
      fillCard(card, who, showVersions ? seat.version : "");

      if (upnext) {
        // Up Next is on, so nothing on the canvas is a control: the
        // room is being shown, not edited, whatever mode it is in.
      } else if (seatingMode === "people") {
        if (who) card.classList.add("movable");
        if (picked && picked.seat === seat) card.classList.add("picked");
        card.onpointerdown = e => dragName(e, card, { seat: seat });
      } else if (seatingMode === "seats") {
        card.classList.add("movable", "chairable");
        if (seat.id === selectedChair) card.classList.add("picked");
        card.onpointerdown = e => dragChair(e, card, section, shape, seat);
      } else if (seatingMode !== "groups") {
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
      tint(tag, hueOf(section, group), chromaOf(group));
      if (isSelected(group, null)) tag.classList.add("chosen");
      tag.style.left = (x - ox) + "px";
      tag.style.top = (y - oy) + "px";
      tag.title = "Drag to move it; click twice to rename";
      tag.onpointerdown = e => dragLabel(e, tag, section, group, ids, where);
      canvas.appendChild(tag);
      drawn.labels.push({ el: tag, seats: ids, group: group,
                         at: [x - ox, y - oy] });
    }
  }

  if (upnext) paintUpnext(section, where, ox, oy);

  /* The nine places this group's label may sit, shown only while it
     is selected. There is no picker control: these *are* the control.

     Drawn inside each desk's own wrap, as percentages of it, so they
     move and turn with the desk. Tracked separately they were the
     elements that stayed behind when a desk was dragged. */
  if (showLabels && selected && selected.kind === "group") {
    const group = groupsOf(section).find(g => g.id === selected.id);
    const at = group && group.label_at;
    for (const shape of group ? shapesHolding(section, group) : []) {
      const wrap = drawn.shapes[shape.id];
      if (!wrap) continue;
      for (const key of Object.keys(ANCHORS)) {
        const [fx, fy] = ANCHORS[key];
        const on = at && at.shape === shape.id && at.anchor === key;
        const dot = el("div", "anchor" + (on ? " on" : ""));
        dot.dataset.spot = shape.id + ":" + key;
        dot.style.left = (50 + fx * 100) + "%";
        dot.style.top = (50 + fy * 100) + "%";
        wrap.appendChild(dot);
      }
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

function paintUpnext(section, where, ox, oy) {
  /* Light the current step, dim the ones already done, and -- in group
     mode -- make the whole group bigger.

     Bigger about the *group's* centre, not about each piece's own
     centre. A desk and its cards are siblings on the canvas, so
     scaling each in place would grow them all while leaving the cards
     sitting where they were, creeping inward as the desk got bigger.
     Moving each piece out by `(k - 1)` of its distance from the group
     centre and then scaling it is what makes the whole thing look
     like one object being brought forward. */
  const line = upnextOrder(section);
  const here = upnextAt >= 0 && upnextAt < line.length ? line[upnextAt] : null;
  for (let i = 0; i < upnextAt; i += 1)
    for (const id of line[i].seats || [])
      if (drawn.cards[id]) drawn.cards[id].classList.add("been");
  if (!here) return;

  for (const id of here.seats || [])
    if (drawn.cards[id]) drawn.cards[id].classList.add("calling");

  if (upnextKind !== "group" || !here.group) return;
  const ids = (here.group.seats || []).filter(id => where[id]);
  if (!ids.length) return;
  const gx = ids.reduce((n, id) => n + where[id][0], 0) / ids.length - ox;
  const gy = ids.reduce((n, id) => n + where[id][1], 0) / ids.length - oy;
  const K = 1.22;
  const grow = (node, cx, cy, after) => {
    node.style.transform = `translate(${(K - 1) * (cx - gx)}px, `
      + `${(K - 1) * (cy - gy)}px) scale(${K})` + (after || "");
    node.classList.add("lifted-up");
  };
  for (const id of ids) {
    const card = drawn.cards[id];
    if (card) grow(card, where[id][0] - ox, where[id][1] - oy);
  }
  for (const shape of shapesHolding(section, here.group)) {
    const wrap = drawn.shapes[shape.id];
    if (!wrap) continue;
    // After the scale, not before: the desk's own rotation has to stay
    // the last thing that happens to it or a turned desk shears.
    grow(wrap, shape.at[0] - ox, shape.at[1] - oy,
         shape.angle ? ` rotate(${shape.angle}deg)` : "");
  }
  // And the label, which is the one part that says *which* group this
  // is -- left behind at its ordinary size it read as a sticker on
  // something that had grown around it.
  const tag = drawn.labels.find(l => l.group === here.group);
  if (tag) grow(tag.el, tag.at[0], tag.at[1]);
}

function tint(node, hue, chroma) {
  // One hue in, three shades out -- see `.seatcard` and `.shape` in
  // seating.css. An ungrouped seat is the same three roles at zero
  // chroma, which is what makes the unseated rail consistent for free.
  node.style.setProperty("--h", hue === null ? 255 : hue);
  node.style.setProperty("--c", hue === null ? 0
    : (typeof chroma === "number" ? chroma : 1));
}

function chromaOf(group) {
  // Absent means the standard strength. Only a colour chosen from the
  // picker writes one down, so every group drawn before the picker
  // existed keeps exactly the colour it had.
  return group && typeof group.chroma === "number" ? group.chroma : 1;
}

function oklchOf(hex) {
  /* sRGB hex to an OKLCH hue and a chroma, because the picker speaks
     hex and the room speaks hue.

     The lightness that comes back is thrown away on purpose. A group's
     three shades are built at fixed lightnesses chosen so that a name
     is readable on the card and the card is visible on the paper; let
     the instructor set lightness and the first dark colour anybody
     picks makes a table whose names cannot be read from the back of
     the room. So the picker chooses *which* colour and *how vivid*,
     and the design system keeps deciding how light.

     The matrices are Bjorn Ottosson's sRGB-to-Oklab, which is the same
     conversion the browser does for the `oklch()` the stylesheet
     already uses -- so a colour picked here and a colour written in
     the stylesheet mean the same thing. */
  const n = parseInt(hex.slice(1), 16);
  const to = v => {
    v /= 255;
    return v <= 0.04045 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
  };
  const R = to((n >> 16) & 255), G = to((n >> 8) & 255), B = to(n & 255);
  const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
  const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
  const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
  const a = 1.9779984951 * l - 2.4285922050 * m + 0.4505937099 * s;
  const b = 0.0259040371 * l + 0.7827717662 * m - 0.8086757660 * s;
  const c = Math.sqrt(a * a + b * b);
  let h = Math.atan2(b, a) * 180 / Math.PI;
  if (h < 0) h += 360;
  /* 0.155 is the chroma of the solid shade in the stylesheet, so a
     colour as vivid as the built-in ones comes back as 1. A grey comes
     back near 0 and stays grey, which is honest: the room already uses
     grey to mean "no group", and a group that chose it will look like
     one. */
  return { hue: h, chroma: Math.min(1.4, Math.round(c / 0.155 * 100) / 100) };
}

function hexOf(hue, chroma) {
  /* The other way, well enough to seed the picker with the colour the
     group already has. Oklab to linear sRGB, then gamma and clamp --
     an out-of-gamut colour clips, which for a seed value is fine. */
  const L = 0.585, C = 0.155 * chroma, r = hue * Math.PI / 180;
  const a = C * Math.cos(r), b = C * Math.sin(r);
  const l = (L + 0.3963377774 * a + 0.2158037573 * b) ** 3;
  const m = (L - 0.1055613458 * a - 0.0638541728 * b) ** 3;
  const s = (L - 0.0894841775 * a - 1.2914855480 * b) ** 3;
  const out = [
    +4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
    -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
    -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s,
  ].map(v => {
    const g = v <= 0.0031308 ? 12.92 * v
                             : 1.055 * Math.pow(Math.max(v, 0), 1 / 2.4) - 0.055;
    return Math.min(255, Math.max(0, Math.round(g * 255)));
  });
  return "#" + out.map(v => v.toString(16).padStart(2, "0")).join("");
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
    if (!seatingState.shapes[shape.kind]) continue;
    const [w, h] = shapeSize(shape);
    for (const key of Object.keys(ANCHORS)) {
      const [fx, fy] = ANCHORS[key];
      // Turned and sized with the desk, so an anchor stays on the
      // corner it names however the desk is standing.
      const [dx, dy] = spin(fx * w, fy * h, shape.angle || 0);
      out.push({
        shape: shape.id, anchor: key,
        x: shape.at[0] + dx,
        y: shape.at[1] + dy,
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

/* When a label was last pressed, and which one. A double click cannot
   be read off the `dblclick` event here: the first click selects the
   group, the group's pill is redrawn as a new element, and the second
   click lands on something the browser has never seen before -- so
   `dblclick` never fires. Two timestamps are what is left. */
let lastLabelTap = { id: null, at: 0 };

function dragLabel(event, tag, section, group, ids, where) {
  /* Click selects; a second click renames; dragging moves the label to
     an anchor. The anchors are on screen by the time a drag is
     possible, because selecting is what put them there -- which is
     why there is no anchor picker in the strip. */
  if (event.pointerType === "mouse" && event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  if (projecting() || seatingMode === "upnext") return;

  const now = Date.now();
  if (lastLabelTap.id === group.id && now - lastLabelTap.at < 450) {
    lastLabelTap = { id: null, at: 0 };
    renameOnCanvas(tag, group);
    return;
  }
  lastLabelTap = { id: group.id, at: now };

  if (!isSelected(group, null)) choose(group, null);

  // `choose` re-drew, so the element under the pointer is a new one.
  const live = (drawn.labels.find(l => l.group.id === group.id) || {}).el || tag;
  const spots = anchorsFor(section, group.id);
  const ox = drawn.box ? drawn.box.x : 0, oy = drawn.box ? drawn.box.y : 0;
  const start = [event.clientX, event.clientY];
  let moved = false, best = null;

  const nearest = (cx, cy) => {
    let near = Infinity, found = null;
    for (const spot of spots) {
      const d = Math.hypot(spot.x - cx, spot.y - cy);
      if (d < near) { near = d; found = spot; }
    }
    return found;
  };

  const place = e => {
    if (!moved
        && Math.hypot(e.clientX - start[0], e.clientY - start[1]) < 4) return;
    moved = true;
    live.classList.add("dragging");
    /* Under the cursor, exactly, the whole way. It used to jump to
       the nearest anchor as soon as it was near one, which made the
       label feel like it was being taken off you. It goes to the
       anchor when you let go, not before. */
    const [cx, cy] = roomPoint(e);
    live.style.left = (cx - ox) + "px";
    live.style.top = (cy - oy) + "px";
    best = nearest(cx, cy);
    for (const dot of document.querySelectorAll("#canvas .anchor"))
      dot.classList.remove("near");
    if (best) {
      // By name, not by index: the dots live inside their own desks,
      // so document order is desk order and not spot order.
      const dot = document.querySelector(
        `#canvas .anchor[data-spot="${best.shape}:${best.anchor}"]`);
      if (dot) dot.classList.add("near");
    }
  };

  const finish = commit => {
    live.onpointermove = live.onpointerup = live.onpointercancel = null;
    if (!moved) { live.classList.remove("dragging"); return; }
    if (!commit || !best) { live.classList.remove("dragging"); renderSeating(); return; }

    /* Fly home rather than appear there. The anchor it chose is a
       guess about what was meant, and watching the label travel the
       last few pixels is what tells you which guess it made. */
    group.label_at = { shape: best.shape, anchor: best.anchor };
    live.classList.remove("dragging");
    live.classList.add("homing");
    live.style.left = (best.x - ox) + "px";
    live.style.top = (best.y - oy) + "px";
    let done = false;
    const land = () => {
      if (done) return;
      done = true;
      renderSeating();
    };
    live.addEventListener("transitionend", land, { once: true });
    setTimeout(land, 260);      // in case the move was zero and nothing ran
  };

  live.setPointerCapture(event.pointerId);
  live.onpointermove = place;
  live.onpointerup = () => finish(true);
  live.onpointercancel = () => finish(false);
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
  /* Clicking a thing selects it, and clicking it again does nothing.
     It used to toggle, which read as "I clicked a desk and nothing
     happened" the moment that desk was already chosen -- most often
     straight after switching mode, when the last mode had left it
     selected. Clearing is the paper, or Escape; that is one gesture
     for one job, and the way every canvas editor does it. */
  selected = group ? { kind: "group", id: group.id }
           : shape ? { kind: "shape", id: shape.id } : null;
  renderSeating();
}

function groupFor(section, shape) {
  /* The group a desk belongs to, whatever the mode was asking about.
     Selecting in Groups and Seats yields a shape and in People a
     group, and the strip wants the same thing either way -- it used
     to show different things depending on which, which read as the
     island being inconsistent. It was. */
  if (!shape) return null;
  const mine = new Set((shape.seats || []).map(s => s.id));
  return groupsOf(section).find(
    g => (g.seats || []).some(id => mine.has(id))) || null;
}

function drawStrip(section) {
  /* One thin strip, the same in every mode: whose it is, what it is
     called, how many seats, where it prints. What changes between
     modes is one button at the right-hand end, because what changes
     between modes is what you are about to do, not what you are
     looking at.

     An earlier draft showed a group's colour and name in People and a
     desk's kind and chair-count in Desks, so the island rearranged
     itself when you changed mode and sometimes lost the controls you
     had just been using. */
  const strip = document.getElementById("seat-strip");
  strip.textContent = "";
  strip.classList.remove("upnextstrip");
  if (upnext) { drawUpNext(strip, section); return; }

  let group = selected && selected.kind === "group"
    ? groupsOf(section).find(g => g.id === selected.id) : null;
  let shape = selected && selected.kind === "shape"
    ? (section.shapes || []).find(s => s.id === selected.id) : null;
  if (!group) group = groupFor(section, shape);
  if (!shape && group) shape = shapesHolding(section, group)[0] || null;

  if (!group && !shape) {
    // Nothing chosen. Groups mode still offers the furniture, because
    // an empty room has nothing to select and still needs a desk.
    strip.hidden = true;
    return;
  }
  strip.hidden = false;

  if (group) {
    // One dot that opens the swatches, rather than six always on
    // show: the strip has to stay one row at 515px.
    const dot = el("button", "swatch");
    dot.type = "button";
    dot.title = "Colour";
    tint(dot, hueOf(section, group), chromaOf(group));
    dot.onclick = e => { e.stopPropagation(); openHues(dot, section, group); };
    strip.appendChild(dot);

    // The heading is the label; clicking it renames.
    const name = el("span", "sname", group.label || "(no label)");
    name.title = "Click to rename";
    name.onclick = () => renameGroup(name, group);
    strip.appendChild(name);

    strip.appendChild(el("span", "isep"));
    strip.appendChild(count("seats", (group.seats || []).length,
                            "Seats in this group"));

    /* Where it prints, and you can type a new one.

       Both numbers are a glyph and a value now, and both glyphs are
       ones the mode rail already taught: the Seats icon for seats, the
       Order icon for the print order. "4 seats" beside a "1/7" chip
       was a sentence beside a badge -- two ways of saying a number
       sitting next to each other, which is most of what made the strip
       look assembled rather than designed. */
    const line = printOrder(section);
    const at = line.indexOf(group) + 1;
    const ord = count("order", at + "/" + line.length,
                      group.order === null || group.order === undefined
                        ? `Prints ${at} of ${line.length}, after everything `
                          + "with a chosen place. Click to choose one."
                        : `Prints ${at} of ${line.length}. Click to change.`);
    ord.classList.add("typable");
    ord.onclick = () => editOrder(ord, section, group, at);
    strip.appendChild(ord);
  } else {
    const spec = seatingState.shapes[shape.kind];
    strip.appendChild(el("span", "sname", (spec && spec.label) || shape.kind));
    strip.appendChild(el("span", "isep"));
    strip.appendChild(count("seats", (shape.seats || []).length,
                            "Seats on this desk"));
  }

  /* The actions, after a divider. Two line-art glyphs in the same
     weight as each other: duplicate used to sit beside a typographic
     X, which is "close" from a different vocabulary standing where a
     verb should be. */
  const acts = [];
  if (seatingMode === "groups" && group && shape)
    acts.push(["copy", "Another group like this one",
               () => duplicateGroup(section, group)]);
  if (seatingMode === "groups" && shape)
    acts.push(["trash", "Remove this group",
               () => removeShape(section, shape)]);
  if (seatingMode === "seats" && shape) {
    const seat = (shape.seats || []).find(s => s.id === selectedChair);
    if (seat) acts.push(["trash", seat.student
      ? "Take this seat away; they go back on the unseated list"
      : "Take this seat away", () => removeChair(section, shape, seat)]);
  }
  if (acts.length) strip.appendChild(el("span", "isep"));
  for (const [icon, why, go] of acts) {
    const b = el("button", "ibtn tiny");
    b.type = "button";
    b.title = why;
    b.appendChild(svgIcon(ICON[icon]));
    b.onclick = go;
    strip.appendChild(b);
  }
}

function count(icon, value, why) {
  /* A glyph and a number. The one shape every fact in the strip
     takes, so two of them side by side read as two facts rather than
     as a label and a badge. */
  const box = el("span", "scount");
  box.title = why;
  box.appendChild(svgIcon(ICON[icon]));
  box.appendChild(el("span", "num", String(value)));
  return box;
}

function printOrder(section) {
  /* Every group, in the order the papers come out: the ones with a
     chosen place first, by place, then anything unplaced in the order
     it was drawn.

     That is `room.ordered_groups`' rule, written on this side so the
     strip can show a position for a group that has not chosen one.
     Such a group still prints somewhere, and saying where is more use
     than a dash saying it has no opinion. */
  const all = groupsOf(section);
  const has = g => g.order !== null && g.order !== undefined;
  return all.filter(has).sort((a, b) => a.order - b.order)
            .concat(all.filter(g => !has(g)));
}

function reorderGroup(section, group, want) {
  /* Move a group to a position, and number everything 1..N.

     One rule for both directions. Take it out of the line, put it back
     at the place asked for, renumber: moving 5 to 3 pushes the old 3
     and 4 down one, and moving 1 to 3 pulls the old 2 and 3 up one,
     with no second case to write. That is what "drag it there" means,
     and doing it by remove-and-insert rather than by arithmetic on the
     numbers is why there is no off-by-one to get wrong.

     Everything comes out numbered, including groups that had no place
     before -- they were already going to print after the placed ones,
     so writing that down changes nothing about the paper and leaves
     the sequence with no gaps for the next edit to reason about. */
  const rest = printOrder(section).filter(g => g !== group);
  const at = Math.min(Math.max(1, Math.round(want)), rest.length + 1) - 1;
  rest.splice(at, 0, group);
  rest.forEach((g, i) => { g.order = i + 1; });
  renderSeating();
}

function editOrder(node, section, group, now) {
  /* Type a position. Same shape as renaming the label: the value is
     already on screen, so a dialog would be a second copy of it. */
  const input = el("input", "srename sorder");
  input.type = "text";
  input.inputMode = "numeric";
  input.value = String(now);
  node.replaceWith(input);
  input.focus();
  input.select();
  let done = false;
  const settle = keep => {
    if (done) return;
    done = true;
    const want = parseInt(input.value, 10);
    if (keep && Number.isFinite(want)) reorderGroup(section, group, want);
    else renderSeating();
  };
  input.onblur = () => settle(true);
  input.onkeydown = e => {
    if (e.key === "Enter") { e.preventDefault(); settle(true); }
    // Escape stops here, or the view reads it as "clear the selection"
    // and the strip goes away mid-edit.
    if (e.key === "Escape") {
      e.preventDefault(); e.stopPropagation(); settle(false);
    }
  };
}

// ------------------------------------------------- desks and chairs --

function freshId(prefix, taken) {
  let n = 1;
  while (taken.has(prefix + n)) n += 1;
  return prefix + n;
}

function addShape(section, kind) {
  /* A new desk, built from the palette the server sent rather than
     from a copy of the anchors kept here. `room.SHAPES` stays the one
     definition of where chairs go on a table. */
  const spec = seatingState.shapes[kind];
  if (!spec) return;
  const shapes = section.shapes || (section.shapes = []);
  const usedShapes = new Set();
  const usedSeats = new Set();
  for (const sec of seatingRoom.sections || [])
    for (const s of sec.shapes || []) {
      usedShapes.add(s.id);
      for (const seat of s.seats || []) usedSeats.add(seat.id);
    }
  const id = freshId("d", usedShapes);

  // Dropped in the middle of what is on screen, so it arrives where
  // you are looking rather than at the room's origin.
  const area = drawn.box || { x: 0, y: 0, w: 800, h: 600 };
  const at = clampShape(section, spec, area.x + area.w / 2,
                        area.y + area.h / 2);
  const shape = { id: id, kind: kind, at: at, seats: [] };
  (spec.seats || []).forEach((offset, i) => {
    const sid = freshId(id + "-", usedSeats) + "";
    usedSeats.add(sid);
    shape.seats.push({ id: sid, at: offset.slice(), student: "",
                       version: "" });
  });
  shapes.push(shape);

  /* And a group to go with it. A desk without one has no colour, no
     label and no place in the print order, so the strip had nothing
     to show and fell back to "table, 2 by 2 — 4 chairs" — which is
     why a new desk could not be coloured or named while an old one
     could. Every desk arrives as a group of its own; merging two is
     a separate question. */
  const taken = new Set(groupsOf(section).map(g => g.id));
  const groups = section.groups || (section.groups = []);
  groups.push({
    id: freshId("g", taken),
    label: "Table " + (groups.length + 1),
    seats: shape.seats.map(s => s.id),
    order: null,
  });

  selected = { kind: "shape", id: id };
  renderSeating();
}

function freeSpotFor(section, shapes) {
  /* Where to put a copy of these shapes: beside the original if there
     is room, otherwise the first clear place on a widening ring.

     Bounding rectangles and a short search, not real packing. There
     are a few dozen desks in a classroom, the answer only has to be
     "not on top of something", and the instructor can drag it
     somewhere better in a second. Eight candidates a ring and six
     rings is forty-eight overlap tests against a few dozen boxes --
     far too small to be worth being clever about.

     The step is the group's own footprint plus a whole name card,
     because `boxOf` measures the furniture and the cards hang off its
     edges. Stepping by the table alone drops the copy's chairs on top
     of the original's while the tables themselves miss each other. */
  const mine = new Set(shapes.map(s => s.id));
  const own = shapes.map(boxOf);
  const span = {
    x0: Math.min(...own.map(b => b.x0)), x1: Math.max(...own.map(b => b.x1)),
    y0: Math.min(...own.map(b => b.y0)), y1: Math.max(...own.map(b => b.y1)),
  };
  const round = v => Math.ceil(v / GRID) * GRID;   // lands on the grid
  const stepX = round(span.x1 - span.x0 + CARD_W + GRID);
  const stepY = round(span.y1 - span.y0 + CARD_H + GRID);

  const others = (section.shapes || [])
    .filter(s => !mine.has(s.id)).map(boxOf);
  const size = section.canvas || { width: 1000, height: 700 };
  const hits = (a, b) => a.x0 < b.x1 && b.x0 < a.x1
                      && a.y0 < b.y1 && b.y0 < a.y1;
  const clear = (dx, dy, bounded) => {
    const b = { x0: span.x0 + dx, x1: span.x1 + dx,
                y0: span.y0 + dy, y1: span.y1 + dy };
    if (bounded && (b.x0 < 0 || b.y0 < 0
                    || b.x1 > size.width || b.y1 > size.height)) return false;
    return !others.some(o => hits(b, o)) && !own.some(o => hits(b, o));
  };

  // Right first, then below, then the diagonal, then back the other
  // way: reading order, so the copy turns up where the eye looks.
  const ring = [[1, 0], [0, 1], [1, 1], [-1, 0], [0, -1],
                [-1, 1], [1, -1], [-1, -1]];
  /* Twice: once insisting on staying inside the declared canvas, once
     not. Dragging a desk is clamped to the canvas, so a copy should
     prefer to respect it -- but a full room would otherwise have
     nowhere to put a copy at all, and a desk slightly outside the
     declared bounds is something you can see and drag back. */
  for (const bounded of [true, false])
    for (let r = 1; r <= 6; r += 1)
      for (const [ux, uy] of ring)
        if (clear(ux * stepX * r, uy * stepY * r, bounded))
          return [ux * stepX * r, uy * stepY * r];
  // Nowhere at all. Offset it a little anyway: a copy you can see
  // sitting on its original beats a button that silently does nothing.
  return [GRID * 2, GRID * 2];
}

function duplicateGroup(section, group) {
  /* Another group laid out exactly like this one: the same furniture
     at the same size and angle, the same seats at the same offsets,
     the same version letters, the same label in the same corner.

     Empty of people, and that is not a shortcut. A student sits in one
     seat -- `room.check` refuses a room where anyone sits in two -- so
     there is nothing else a copy could do with them.

     The letters, on the other hand, come along deliberately. They are
     most of the reason to duplicate: a second table arranged like the
     first wants the same pattern of papers around it, not a fresh
     colouring that happens to be legal. */
  const shapes = shapesHolding(section, group);
  if (!shapes.length) return;

  const usedShapes = new Set(), usedSeats = new Set(), usedGroups = new Set();
  for (const sec of seatingRoom.sections || []) {
    for (const s of sec.shapes || []) {
      usedShapes.add(s.id);
      for (const seat of s.seats || []) usedSeats.add(seat.id);
    }
    for (const g of sec.groups || []) usedGroups.add(g.id);
  }

  const [dx, dy] = freeSpotFor(section, shapes);
  const renamed = new Map();            // old shape id -> the copy's id
  const seats = [];
  for (const shape of shapes) {
    const id = freshId("d", usedShapes);
    usedShapes.add(id);
    renamed.set(shape.id, id);
    const made = { id: id, kind: shape.kind,
                   at: [shape.at[0] + dx, shape.at[1] + dy], seats: [] };
    // Only if the original carries them: a desk that has never been
    // resized stores no size, and the copy should not invent one.
    if (shape.w) made.w = shape.w;
    if (shape.h) made.h = shape.h;
    if (shape.angle) made.angle = shape.angle;
    for (const seat of shape.seats || []) {
      /* This group's seats only. One desk can hold seats belonging to
         two groups, and duplicating one of them must not quietly take
         the other's chairs along. */
      if (!(group.seats || []).includes(seat.id)) continue;
      const sid = freshId(id + "-", usedSeats);
      usedSeats.add(sid);
      made.seats.push({ id: sid, at: seat.at.slice(),
                        student: "", version: seat.version || "" });
      seats.push(sid);
    }
    (section.shapes || (section.shapes = [])).push(made);
  }

  const fresh = {
    id: freshId("g", usedGroups),
    label: (group.label || "Table") + " (copy)",
    seats: seats,
    order: null,                 // its place in the print order is a choice
  };
  // The hue is copied only when the original chose one. A group with no
  // hue takes its colour from its position in the list, and writing
  // that colour down here would freeze a copy to a shade the original
  // would abandon the moment a group before it was deleted.
  if (typeof group.hue === "number") fresh.hue = group.hue;
  if (group.label_at && renamed.has(group.label_at.shape))
    fresh.label_at = { shape: renamed.get(group.label_at.shape),
                       anchor: group.label_at.anchor };
  (section.groups || (section.groups = [])).push(fresh);

  selected = { kind: "group", id: fresh.id };
  selectedChair = null;
  renderSeating();
}

/* The eight edges and corners you can pull, as fractions of the box.
   The same nine places the label can sit, less the middle -- one set
   of positions for both, so a desk has one vocabulary of points on it
   rather than two that nearly agree. */
const GRIPS = ["nw", "n", "ne", "w", "e", "sw", "s", "se"];
const SPAN = { nw: [-1, -1], n: [0, -1], ne: [1, -1], w: [-1, 0],
               e: [1, 0], sw: [-1, 1], s: [0, 1], se: [1, 1] };
const MIN_DESK = 60;

function paintShape(shape) {
  /* Move a desk and its people on screen without redrawing anything.

     A drag cannot re-render: the handle under the pointer is one of
     the elements a re-render replaces, and the replacement does not
     hold the pointer capture. The symptom was a grip that moved a
     millimetre and then went dead, because the first pointermove
     destroyed the thing receiving the rest of them. */
  const wrap = drawn.shapes[shape.id];
  if (!wrap) return;
  const [w, h] = shapeSize(shape);
  const ox = drawn.box ? drawn.box.x : 0, oy = drawn.box ? drawn.box.y : 0;
  wrap.style.left = (shape.at[0] - w / 2 - ox) + "px";
  wrap.style.top = (shape.at[1] - h / 2 - oy) + "px";
  wrap.style.width = w + "px";
  wrap.style.height = h + "px";
  wrap.style.transform = shape.angle ? `rotate(${shape.angle}deg)` : "";
  for (const seat of shape.seats || []) {
    const card = drawn.cards[seat.id];
    if (!card) continue;
    card.style.left = (shape.at[0] + seat.at[0] - CARD_W / 2 - ox) + "px";
    card.style.top = (shape.at[1] + seat.at[1] - CARD_H / 2 - oy) + "px";
  }
}

function addHandles(wrap, section, shape) {
  for (const key of GRIPS) {
    const [fx, fy] = SPAN[key];
    const grip = el("div", "grip grip-" + key);
    grip.style.left = (50 + fx * 50) + "%";
    grip.style.top = (50 + fy * 50) + "%";
    grip.onpointerdown = e => resizeShape(e, section, shape, key);
    wrap.appendChild(grip);
  }
  const spin_ = el("div", "spinner");
  spin_.title = "Turn the desk. Hold shift for 15° steps";
  spin_.onpointerdown = e => rotateShape(e, section, shape);
  wrap.appendChild(spin_);
}

function resizeShape(event, section, shape, key) {
  /* Pull an edge or a corner. The chairs keep their places *relative*
     to the desk -- their offsets are scaled by the same factor -- so
     widening a table of four spreads the four out rather than leaving
     them huddled at the old spacing.

     The pointer's travel is un-rotated before it is used, so dragging
     the right edge of a desk turned forty degrees still widens it
     along its own length rather than along the screen's. */
  if (event.pointerType === "mouse" && event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  const scale = canvasScale();
  const start = [event.clientX, event.clientY];
  const [fx, fy] = SPAN[key];
  const [w0, h0] = shapeSize(shape);
  const at0 = shape.at.slice();
  const seats0 = (shape.seats || []).map(s => s.at.slice());
  const node = event.currentTarget;

  const place = e => {
    const [dx, dy] = spin((e.clientX - start[0]) / scale,
                          (e.clientY - start[1]) / scale,
                          -(shape.angle || 0));
    const w = Math.max(MIN_DESK, Math.round(w0 + fx * dx));
    const h = Math.max(MIN_DESK, Math.round(h0 + fy * dy));
    // The far edge stays put, so the desk grows from the side you
    // pulled rather than from its middle.
    const shift = spin(fx * (w - w0) / 2, fy * (h - h0) / 2,
                       shape.angle || 0);
    shape.w = w;
    shape.h = h;
    shape.at = [Math.round(at0[0] + shift[0]), Math.round(at0[1] + shift[1])];
    const kx = w / w0, ky = h / h0;
    (shape.seats || []).forEach((seat, i) => {
      seat.at = [Math.round(seats0[i][0] * kx), Math.round(seats0[i][1] * ky)];
    });
    paintShape(shape);
  };

  const finish = commit => {
    node.onpointermove = node.onpointerup = node.onpointercancel = null;
    if (!commit) {
      shape.w = w0; shape.h = h0; shape.at = at0;
      (shape.seats || []).forEach((s, i) => { s.at = seats0[i]; });
    }
    renderSeating();
  };
  node.setPointerCapture(event.pointerId);
  node.onpointermove = place;
  node.onpointerup = () => finish(true);
  node.onpointercancel = () => finish(false);
}

function rotateShape(event, section, shape) {
  /* Turn the desk about its own centre. The chairs turn with it --
     `turnShape` rewrites their offsets -- but the name cards do not:
     a card is read by a person standing up, not by the desk. */
  if (event.pointerType === "mouse" && event.button !== 0) return;
  event.preventDefault();
  event.stopPropagation();
  const node = event.currentTarget;
  const was = shape.angle || 0;
  const seats0 = (shape.seats || []).map(s => s.at.slice());
  const box = seatingCanvas().getBoundingClientRect();
  const k = canvasScale();
  const ox = drawn.box ? drawn.box.x : 0, oy = drawn.box ? drawn.box.y : 0;
  const centre = [box.left + (shape.at[0] - ox) * k,
                  box.top + (shape.at[1] - oy) * k];
  const angleTo = e => Math.atan2(e.clientY - centre[1],
                                  e.clientX - centre[0]) * 180 / Math.PI;
  const from = angleTo(event);

  const place = e => {
    let to = was + (angleTo(e) - from);
    if (e.shiftKey) to = Math.round(to / 15) * 15;
    // From the original offsets every time, so dragging back and
    // forth does not grind them down by rounding at each step.
    (shape.seats || []).forEach((s, i) => { s.at = seats0[i].slice(); });
    shape.angle = was;
    turnShape(shape, Math.round(to) - was);
    paintShape(shape);
  };

  const finish = commit => {
    node.onpointermove = node.onpointerup = node.onpointercancel = null;
    if (!commit) {
      (shape.seats || []).forEach((s, i) => { s.at = seats0[i]; });
      shape.angle = was;
    }
    renderSeating();
  };
  node.setPointerCapture(event.pointerId);
  node.onpointermove = place;
  node.onpointerup = () => finish(true);
  node.onpointercancel = () => finish(false);
}

function removeShape(section, shape) {
  /* Standing people up rather than refusing. A desk you cannot delete
     because somebody is at it makes you go and move four people
     first, and they all end up back on the rail anyway. */
  const sitting = (shape.seats || []).filter(s => s.student).length;
  section.shapes = (section.shapes || []).filter(s => s !== shape);
  const gone = new Set((shape.seats || []).map(s => s.id));
  for (const group of groupsOf(section))
    group.seats = (group.seats || []).filter(id => !gone.has(id));
  // A group with nothing left in it is not a group.
  section.groups = groupsOf(section).filter(g => (g.seats || []).length);
  selected = null;
  renderSeating();
  if (sitting) toast(sitting + (sitting === 1 ? " person is" : " people are")
                     + " back on the unseated list.");
}

function addChair(section, shape) {
  const used = new Set();
  for (const sec of seatingRoom.sections || [])
    for (const s of sec.shapes || [])
      for (const seat of s.seats || []) used.add(seat.id);
  const spec = seatingState.shapes[shape.kind];
  // Below the lowest chair it already has, which is somewhere a person
  // could sit and never on top of another card.
  const low = (shape.seats || []).reduce((m, s) => Math.max(m, s.at[1]),
                                         -(spec ? spec.h / 2 : 40));
  shape.seats.push({ id: freshId(shape.id + "-", used),
                     at: [0, Math.round(low + CARD_H + 10)],
                     student: "", version: "" });
  renderSeating();
}

function removeChair(section, shape, seat) {
  shape.seats = (shape.seats || []).filter(s => s !== seat);
  for (const group of groupsOf(section))
    group.seats = (group.seats || []).filter(id => id !== seat.id);
  section.groups = groupsOf(section).filter(g => (g.seats || []).length);
  if (selectedChair === seat.id) selectedChair = null;
  renderSeating();
}

function boxOf(shape) {
  /* A desk's extent in room units, as an upright rectangle. A turned
     desk gets its bounding box rather than its true corners: the
     overlap test below only has to pick a winner, and a rotated
     polygon intersection would be a lot of arithmetic to decide the
     same thing in almost every real room. */
  const [w, h] = shapeSize(shape);
  const r = (shape.angle || 0) * Math.PI / 180;
  const bw = Math.abs(w * Math.cos(r)) + Math.abs(h * Math.sin(r));
  const bh = Math.abs(w * Math.sin(r)) + Math.abs(h * Math.cos(r));
  return { x0: shape.at[0] - bw / 2, x1: shape.at[0] + bw / 2,
           y0: shape.at[1] - bh / 2, y1: shape.at[1] + bh / 2 };
}

function newParentFor(section, shape, cx, cy) {
  /* Which desk a dropped seat now belongs to: whichever covers most
     of the seat's card.

     Ties and near-ties keep the seat where it is. A seat straddling
     two desks equally has no right answer, and moving it on a
     coin-toss is worse than leaving it -- the instructor can drag it
     a little further and be explicit. */
  const card = { x0: cx - CARD_W / 2, x1: cx + CARD_W / 2,
                 y0: cy - CARD_H / 2, y1: cy + CARD_H / 2 };
  const area = other => {
    const b = boxOf(other);
    const w = Math.min(card.x1, b.x1) - Math.max(card.x0, b.x0);
    const h = Math.min(card.y1, b.y1) - Math.max(card.y0, b.y0);
    return w > 0 && h > 0 ? w * h : 0;
  };
  const scored = (section.shapes || [])
    .map(s => ({ shape: s, area: area(s) }))
    .filter(s => s.area > 0)
    .sort((a, b) => b.area - a.area);
  if (!scored.length) return null;
  if (scored[0].shape === shape) return null;          // it stayed home
  // A clear winner, or nothing happens. Within a twentieth is a tie.
  const second = scored[1] ? scored[1].area : 0;
  if (scored[0].area - second < scored[0].area * 0.05) return null;
  return scored[0].shape;
}

function reparentSeat(section, from, to, seat, cx, cy) {
  /* Move the seat between desks, keeping it exactly where it was
     dropped: its offset is recomputed against its new desk's centre.
     Offsets are stored already-turned, so there is no angle to undo. */
  from.seats = (from.seats || []).filter(s => s !== seat);
  seat.at = [Math.round(cx - to.at[0]), Math.round(cy - to.at[1])];
  to.seats.push(seat);

  // And it joins the new desk's group, because a group is a set of
  // seats and the seat has moved to a different set of furniture.
  const mine = new Set((to.seats || []).map(s => s.id));
  const host = groupsOf(section).find(
    g => (g.seats || []).some(id => mine.has(id) && id !== seat.id));
  for (const g of groupsOf(section))
    g.seats = (g.seats || []).filter(id => id !== seat.id);
  if (host) host.seats.push(seat.id);
  section.groups = groupsOf(section).filter(g => (g.seats || []).length);
  return host;
}

function dragChair(event, card, section, shape, seat) {
  /* Where a seat sits on its group. The anchor is an offset from the
     shape's centre, so this writes `seat.at` and the desk can still be
     moved afterwards without the seats coming loose.

     Snapped to the same grid as the furniture: an earlier version left
     seats free on the grounds that a real chair does not line up with
     anything, which was true and unhelpful -- what lines up is the
     drawing, and a chart of seats at arbitrary half-pixels looks
     like a mistake.

     Dropped over a different desk, the seat changes hands. Only here:
     shoving two desks together in Groups mode must not quietly
     rearrange who belongs to whom. */
  if (event.pointerType === "mouse" && event.button !== 0) return;
  event.preventDefault();
  // Touching a chair chooses its desk too, so the strip's add and
  // remove are about the thing just touched rather than about
  // whatever was chosen before.
  selectedChair = seat.id;
  selected = { kind: "shape", id: shape.id };
  const scale = canvasScale();
  const start = [event.clientX, event.clientY];
  const home = seat.at.slice();
  const spec = seatingState.shapes[shape.kind];
  const ox = drawn.box ? drawn.box.x : 0, oy = drawn.box ? drawn.box.y : 0;
  let moved = false;

  const place = e => {
    if (Math.hypot(e.clientX - start[0], e.clientY - start[1]) < 3) return;
    moved = true;
    /* Snapped in *room* coordinates, not relative ones, so a seat
       lands on the same grid the desks do however far its own desk
       happens to sit off it. */
    const snap = v => Math.round(v / GRID) * GRID;
    const wx = snap(shape.at[0] + home[0] + (e.clientX - start[0]) / scale);
    const wy = snap(shape.at[1] + home[1] + (e.clientY - start[1]) / scale);
    seat.at = [wx - shape.at[0], wy - shape.at[1]];
    card.style.left = (wx - CARD_W / 2 - ox) + "px";
    card.style.top = (wy - CARD_H / 2 - oy) + "px";

    // Say which desk would take it, before it is let go.
    const host = newParentFor(section, shape, wx, wy);
    for (const w of Object.values(drawn.shapes)) w.classList.remove("adopting");
    if (host && drawn.shapes[host.id])
      drawn.shapes[host.id].classList.add("adopting");
  };

  const finish = commit => {
    card.onpointermove = card.onpointerup = card.onpointercancel = null;
    for (const w of Object.values(drawn.shapes)) w.classList.remove("adopting");
    if (!commit) seat.at = home;
    if (!moved || !commit) { renderSeating(); return; }

    const wx = shape.at[0] + seat.at[0], wy = shape.at[1] + seat.at[1];
    const host = newParentFor(section, shape, wx, wy);
    if (host) {
      const g = reparentSeat(section, shape, host, seat, wx, wy);
      selected = { kind: "shape", id: host.id };
      toast(g && g.label ? "Moved to " + g.label : "Moved to another group");
    }
    renderSeating();
  };

  card.setPointerCapture(event.pointerId);
  card.onpointermove = place;
  card.onpointerup = () => finish(true);
  card.onpointercancel = () => finish(false);
}


// --------------------------------------------------------- up next --

function upnextOrder(section) {
  /* The line, built once and kept until the room or the kind changes.

     Kept, because stepping backwards has to show the same person you
     just saw. A fresh shuffle on every render would make the back
     arrow a second forward arrow with extra steps. */
  const made = seatingSection + "/" + upnextKind + "/"
    + drawn.seats.length + "/" + groupsOf(section).length;
  if (made === upnextFor) return upnextLine;
  upnextFor = made;
  upnextAt = -1;
  upnextLine = buildUpnext(section);
  return upnextLine;
}

function buildUpnext(section) {
  const names = (seatingState && seatingState.names) || {};
  const seated = drawn.seats.filter(s => s.seat.student);

  if (upnextKind === "person") {
    /* Shuffled once. Fisher-Yates rather than `sort(() => Math.random()
       - 0.5)`, which is not a shuffle -- it is a comparison function
       that lies, and leaves the first few in place more often than
       chance. In a classroom that is the difference between fair and
       looking fair. */
    const line = seated.map(s => ({
      label: (names[s.seat.student] || {}).full || "\u2014",
      seats: [s.id],
    }));
    for (let i = line.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      [line[i], line[j]] = [line[j], line[i]];
    }
    return line;
  }

  if (upnextKind === "group") {
    // Print order, because that is the order the room already has an
    // opinion about, and a second arbitrary order would be one more
    // thing nobody can predict.
    return printOrder(section)
      .map(g => ({ label: g.label || "(no label)", group: g,
                   seats: (g.seats || []).filter(id => drawn.cards[id]) }))
      .filter(e => e.seats.length);
  }

  /* One from each group, by version letter.

     Each group's seats are put in the room's own version order, and
     step i takes the seat at `i % however many it has`. So with
     letters A-E and a group of three, step D lands on the same seat as
     step A -- which is the instructor's rule, and is also the only
     answer that gives every seat in a small group the same number of
     turns.

     The number of steps is the longer of the two: usually the version
     list, but a group with more seats than there are letters would
     otherwise have seats that never come up at all. */
  const letters = (seatingRoom && seatingRoom.versions) || [];
  const rank = id => {
    const at = letters.indexOf(id);
    return at < 0 ? letters.length : at;
  };
  const groups = printOrder(section).map(g => (g.seats || [])
    .map(id => drawn.seats.find(s => s.id === id))
    .filter(s => s && s.seat.student)
    .sort((a, b) => rank(a.seat.version) - rank(b.seat.version)))
    .filter(seats => seats.length);
  const widest = groups.reduce((n, g) => Math.max(n, g.length), 0);
  const steps = Math.max(letters.length, widest);
  const line = [];
  for (let i = 0; i < steps; i += 1)
    line.push({
      label: letters.length ? letters[i % letters.length] : String(i + 1),
      seats: groups.map(g => g[i % g.length].id),
    });
  return line;
}

function upnextStep(by) {
  const section = currentSection();
  if (!section) return;
  const line = upnextOrder(section);
  if (!line.length) { toast("Nobody is seated in this room yet."); return; }
  if (upnextAt < 0) upnextAt = by > 0 ? 0 : line.length - 1;
  else upnextAt = (upnextAt + by + line.length) % line.length;
  renderSeating();
}

function upnextHere(section) {
  const line = upnextOrder(section);
  return upnextAt >= 0 && upnextAt < line.length ? line[upnextAt] : null;
}



function drawUpNext(strip, section) {
  /* Who is up: a back arrow, the name, how far through, a forward
     arrow -- and on the left the one control that says what "who"
     means here.

     The kind cycles on a click rather than opening a menu. There are
     three of them, the glyph says which one you are on, and a menu
     over a strip that is itself over a projected room is two layers of
     chrome to answer a question with three answers. */
  strip.hidden = false;
  strip.classList.add("upnextstrip");

  const spec = UPNEXT_KINDS.find(k => k.value === upnextKind)
    || UPNEXT_KINDS[0];
  const next = UPNEXT_KINDS[(UPNEXT_KINDS.indexOf(spec) + 1)
                            % UPNEXT_KINDS.length];
  const kind = el("button", "ibtn tiny kindbtn");
  kind.type = "button";
  kind.title = spec.why + "  (click for: " + next.label.toLowerCase() + ")";
  kind.appendChild(svgIcon(ICON[spec.icon]));
  kind.onclick = () => {
    upnextKind = next.value;
    upnextFor = "";                // a different question, a new line
    renderSeating();
  };
  strip.appendChild(kind);
  strip.appendChild(el("span", "isep"));

  const line = upnextOrder(section);
  const arrow = (dir, why) => {
    const b = el("button", "ibtn tiny steparrow");
    b.type = "button";
    b.title = why;
    b.appendChild(svgIcon(dir < 0 ? ICON.back : ICON.fwd));
    b.disabled = !line.length;
    b.onclick = () => upnextStep(dir);
    return b;
  };
  strip.appendChild(arrow(-1, "The one before"));

  const here = upnextAt >= 0 && upnextAt < line.length ? line[upnextAt] : null;
  const name = el("span", "sname upname",
    here ? here.label : (line.length ? "Ready" : "Nobody is seated here"));
  strip.appendChild(name);
  if (line.length)
    strip.appendChild(el("span", "smeta upcount",
      (upnextAt < 0 ? "\u2013" : upnextAt + 1) + "/" + line.length));

  strip.appendChild(arrow(1, "The next one"));
}

function openHues(near, section, group) {
  document.querySelectorAll(".hues").forEach(n => n.remove());
  const pop = el("div", "hues");
  const standard = chromaOf(group) === 1;
  for (const hue of HUES) {
    const b = el("button", "hue" + (standard && hueOf(section, group) === hue
                                    ? " on" : ""));
    b.type = "button";
    b.style.setProperty("--h", hue);
    b.style.setProperty("--c", 1);
    b.onclick = () => {
      group.hue = hue;
      delete group.chroma;        // back to the standard strength
      pop.remove();
      renderSeating();
    };
    pop.appendChild(b);
  }

  /* One more slot: anything else.

     `input type="color"` rather than a wheel built here. It is the
     platform's own picker, which means it already has a visual field,
     a hex box, RGB numbers and -- on every desktop -- an eyedropper,
     all of it in the conventions of whatever machine the instructor
     is sitting at, none of it to maintain. Writing a worse one would
     be the whole point of the exercise lost.

     What comes back is a full colour and what is kept is its hue and
     its vividness; `oklchOf` says why. */
  const own = el("button", "hue custom" + (standard ? "" : " on"));
  own.type = "button";
  own.title = "Any other colour";
  const pick = el("input");
  pick.type = "color";
  pick.value = hexOf(hueOf(section, group) || 255, chromaOf(group));
  // `input` rather than `change`: the picker previews live on every
  // platform that has one, and watching the room follow is most of
  // how you tell whether a colour works against the paper.
  pick.oninput = () => {
    const got = oklchOf(pick.value);
    group.hue = Math.round(got.hue * 10) / 10;
    group.chroma = got.chroma;
    renderSeating();
  };
  own.appendChild(pick);
  own.onclick = () => pick.click();
  pop.appendChild(own);
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

function renameOnCanvas(tag, group) {
  /* Edit the pill in place, at its size and in its position, so the
     name is retyped where it lives rather than in a box elsewhere
     that happens to hold the same string.

     In the group's own colour, not the accent. The accent means "the
     state you are in"; a yellow-green ring round a purple group's
     name said nothing about the purple group. */
  const section = currentSection();
  const hue = hueOf(section, group);
  const wrap = el("span", "renaming");
  wrap.style.cssText = tag.style.cssText;
  tint(wrap, hue, chromaOf(group));

  const input = el("input", "pillrename");
  input.type = "text";
  input.value = group.label || "";
  input.size = Math.max(8, (group.label || "").length + 2);
  wrap.appendChild(input);

  /* A cross, because clearing the box is not how anybody expects to
     delete a label -- emptying a field reads as "I have not typed it
     yet", not as "there should not be one". */
  const kill = el("button", "unlabel", "×");
  kill.type = "button";
  kill.title = "No label on this group";
  kill.onmousedown = e => e.preventDefault();   // keep focus off the blur
  kill.onclick = () => { done = true; group.label = ""; renderSeating(); };
  wrap.appendChild(kill);

  tag.replaceWith(wrap);
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
    e.stopPropagation();          // Escape here is "stop editing"
    if (e.key === "Enter") { e.preventDefault(); settle(true); }
    if (e.key === "Escape") { e.preventDefault(); settle(false); }
  };
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
  /* Only when the controls are away. It exists to say what the islands
     would have said; with them back it is a second answer to the same
     question, printed underneath the first. */
  const stage_wanted = projecting();
  stage.hidden = !stage_wanted;
  if (!stage_wanted) return;
  document.getElementById("stage-section").textContent = section.name || "";
  /* One instruction, and only the one you cannot guess. The count and
     the arrows are in the Up Next strip, which is on screen while they
     mean anything; the bar used to repeat them underneath, and reading
     a line of small grey text at the front of a room is work nobody
     does twice. */
  document.getElementById("stage-keys").textContent = "esc to leave";
}

// ---------------------------------------------------------------- drawer --

/* The hamburger unfolds the island it sits in rather than opening a
   menu over the room. What was in that menu was the furniture and two
   display toggles, which is a drawer with one useful thing in it and a
   lid on top; unfolded in place they are next to the room's identity,
   where they belong. */
function togglePalette(force) {
  paletteOpen = force !== undefined ? force : !paletteOpen;
  const section = currentSection();
  drawPalette(section);
  paintChrome();                  // the plus turns into a cross
}

function drawPalette(section) {
  /* The furniture, in a column that grows up out of the plus at the
     end of the strip. Closed by default: an empty room needs it once
     and then you are arranging people, so it should not sit on the
     canvas for the rest of the hour. */
  const pal = document.getElementById("seat-palette");
  pal.textContent = "";
  if (seatingMode !== "groups" || !section) {
    pal.hidden = true;
    pal.classList.remove("open");
    return;
  }
  // Kept in the layout while shut, so its height can be animated to
  // nothing rather than the island blinking out of existence.
  pal.hidden = false;
  pal.classList.toggle("open", paletteOpen);

  for (const kind of paletteKinds()) {
    const spec = seatingState.shapes[kind];
    if (!spec) continue;
    const b = el("button", "deskopt");
    b.type = "button";
    b.title = "Add a " + spec.label;
    const tile = el("span", "desktile " + spec.css);
    const k = 26 / Math.max(spec.w, spec.h);
    tile.style.width = Math.max(11, Math.round(spec.w * k)) + "px";
    tile.style.height = Math.max(11, Math.round(spec.h * k)) + "px";
    /* A single desk and a 2x2 are the same silhouette, so the one
       that holds one person says so. The 2x2 says nothing, because
       it is not "a 2x2" so much as "a table", and it stretches to
       whatever size the room wants. */
    if (spec.seats && spec.seats.length === 1) tile.textContent = "1";
    b.appendChild(tile);
    b.onclick = () => { paletteOpen = false; addShape(section, kind); };
    pal.appendChild(b);
  }
}

function paletteKinds() {
  /* One rectangle rather than four. `desk`, `table-1x2`, `table-2x2`
     and `table-1x3` are the same silhouette at four sizes; rooms that
     already use them still load, but there is no reason to choose
     between them in a palette when the thing you want is a rectangle
     of a particular size. `desk` stays because one chair and four is
     a difference in kind, not in size. */
  const all = Object.keys(seatingState.shapes);
  const drop = new Set(["table-1x2", "table-1x3"]);
  return all.filter(k => !drop.has(k));
}

function discardRoom() {
  seatingRoom = JSON.parse(JSON.stringify(seatingState.room));
  selected = null;
  picked = null;
  selectedChair = null;
  renderSeating();
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

  const box = drawn.shapes[shape.id];       // the wrap, not the silhouette
  box.focus();
  const [sw, sh] = shapeSize(shape);
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
    const to = clampShape(section, { w: sw, h: sh },
                          home[0] + (e.clientX - start[0]) / scale,
                          home[1] + (e.clientY - start[1]) / scale);
    box.style.left = (to[0] - sw / 2 - ox) + "px";
    box.style.top = (to[1] - sh / 2 - oy) + "px";
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
  if (!seatingState.shapes[shape.kind]) return;
  const [w, h] = shapeSize(shape);
  // Off-grid on purpose with shift held: snapping first would eat the
  // nudge whole, since one unit rounds back to where it started.
  const to = [shape.at[0] + by[0], shape.at[1] + by[1]];
  shape.at = event.shiftKey
    ? to : clampShape(section, { w: w, h: h }, to[0], to[1]);
  renderSeating();
  const again = drawn.shapes[shape.id];
  if (again) again.focus();
}

// ------------------------------------------------------------------ zoom --

function freeBand(paper) {
  /* The rectangle the room is fitted into, and the rectangle it is
     centred in. One function, because those have to be the same
     rectangle: a room fitted to one and centred in another is a room
     that is neither fitted nor centred, which is how the first draft
     ended up tucked under the mode rail.

     The unseated rail is a real column and takes real width. The
     islands float over the canvas by design, but they float over
     exactly the corners a fitted room would otherwise use, so the
     band stops short of them -- a name you cannot read because the
     section buttons are sitting on it is not a fitted room either.

     `offsetWidth` rather than `.hidden` for the unseated rail: the
     projector hides it with CSS and leaves the attribute alone, so
     asking the attribute would reserve a gutter for something that is
     not on screen. */
  const pen = seatingPen();
  const side = pen.offsetWidth ? pen.offsetWidth + 22 : 0;
  const top = projecting() ? 14 : 62;        // the two top islands
  const bottom = projecting() ? 46 : 130;    // the rail, and the strip
  return {
    x: 14,
    y: top,
    w: Math.max(80, paper.clientWidth - side - 28),
    h: Math.max(80, paper.clientHeight - top - bottom),
  };
}

function fitZoom(paper, area) {
  /* Both axes, not just the width -- fitting the width alone left a
     tall room scrolling, which is not what "fit" offers to do. The cap
     is 4 rather than 1: on a projector the room should be blown up past
     life size, and refusing to go over 100% was most of why a small
     class filled a quarter of the screen. */
  const band = freeBand(paper);
  return Math.min(4, Math.max(0.05,
    Math.min(band.w / area.w, band.h / area.h)));
}

function applyZoom(section) {
  const canvas = seatingCanvas();
  const box = document.getElementById("canvasbox");
  const paper = seatingPaper();
  const area = (drawn.box && drawn.box.w) ? drawn.box : contentBox(section);

  const zoom = seatingZoom === null ? fitZoom(paper, area) : seatingZoom;
  canvas.style.transform = `scale(${zoom})`;
  // The box carries the scaled size, because a scaled element's own
  // layout box is still its unscaled one and nothing downstream could
  // tell how big the room had become.
  box.style.width = Math.round(area.w * zoom) + "px";
  box.style.height = Math.round(area.h * zoom) + "px";
  document.getElementById("seat-zoom").textContent =
    Math.round(zoom * 100) + "%";
  placeBox(zoom, area);
}

function placeBox(zoom, area) {
  /* Where the room sits: the middle of the free band, plus however far
     it has been dragged.

     The same arithmetic at every window size, which is the point. The
     old layout centred with `margin: auto` and then overrode one side
     of that margin to clear the unseated rail, and an `auto` margin
     with one side pinned is not centring at all -- it is alignment
     against the pinned side. Resizing the window therefore walked the
     room to the right edge. Centre is now a number this function
     computes, so it cannot be turned into an edge by something else. */
  const paper = seatingPaper();
  const band = freeBand(paper);
  const w = area.w * zoom, h = area.h * zoom;
  clampPan(paper, band, w, h);
  const box = document.getElementById("canvasbox");
  box.style.left = Math.round(band.x + (band.w - w) / 2 + pan.x) + "px";
  box.style.top = Math.round(band.y + (band.h - h) / 2 + pan.y) + "px";
  paintPaper(zoom);
}

function clampPan(paper, band, w, h) {
  /* Pan as far as you like, until the room would leave.

     KEEP pixels of it stay on the paper in every direction. Without a
     stop there is a flick of the wrist that loses the room entirely
     and leaves a blank grid with no clue which way to drag back; with
     one you can still reach any corner, because the limit is computed
     from the room's own size rather than from a fixed box. Nothing in
     normal use touches it. */
  const KEEP = 110;
  const span = (size, at, bandSize, full) => {
    const keep = Math.min(KEEP, size);
    const home = at + (bandSize - size) / 2;
    return [keep - size - home, full - keep - home];
  };
  const [lox, hix] = span(w, band.x, band.w, paper.clientWidth);
  const [loy, hiy] = span(h, band.y, band.h, paper.clientHeight);
  pan.x = Math.min(Math.max(pan.x, lox), hix);
  pan.y = Math.min(Math.max(pan.y, loy), hiy);
}

function paintPaper(zoom) {
  /* The grid and the dots are one pattern on the paper, not two.

     They used to be separate: dots every 26 screen pixels on the
     paper, grid lines every 20 room units on the canvas. So they
     never lined up, the dots did not move with the room, and the grid
     stopped at the edge of the furniture -- which made the room look
     like it sat on a mat rather than on a floor.

     Both are on the paper now, laid out from the room's own origin at
     the room's own step, so they tile for ever and the dots land on
     the intersections because they are measured from the same corner. */
  const paper = seatingPaper();
  const canvas = seatingCanvas();
  const step = GRID * zoom;
  if (!(step > 1.5)) { paper.style.backgroundImage = "none"; return; }

  // Where room (0, 0) falls on the paper, so the pattern is pinned to
  // the room and travels with it rather than to the scrolling box.
  const pb = paper.getBoundingClientRect();
  const cb = canvas.getBoundingClientRect();
  const area = drawn.box || { x: 0, y: 0 };
  const x0 = cb.left - pb.left - area.x * zoom;
  const y0 = cb.top - pb.top - area.y * zoom;
  const at = (v, s) => (((v % s) + s) % s);
  const big = step * 5;

  const fine = "oklch(0.905 0.005 255)";
  const bold = "oklch(0.850 0.007 255)";
  const dot = "oklch(0.800 0.008 255)";
  const gridded = seatingMode === "groups" || seatingMode === "seats";

  const layers = [], sizes = [], spots = [];
  if (gridded && !projecting()) {
    layers.push(`linear-gradient(to right, ${fine} 1px, transparent 1px)`,
                `linear-gradient(to bottom, ${fine} 1px, transparent 1px)`,
                `linear-gradient(to right, ${bold} 1px, transparent 1px)`,
                `linear-gradient(to bottom, ${bold} 1px, transparent 1px)`);
    sizes.push(`${step}px ${step}px`, `${step}px ${step}px`,
               `${big}px ${big}px`, `${big}px ${big}px`);
    spots.push(`${at(x0, step)}px 0`, `0 ${at(y0, step)}px`,
               `${at(x0, big)}px 0`, `0 ${at(y0, big)}px`);
  }
  /* The dots sit on the heavy intersections, which is what makes them
     read as part of the grid rather than as a second pattern beside it.

     Half a tile back, and that is the whole fix. A linear gradient
     starts drawing at its tile's edge, so a 1px line lands on the
     background position. A radial gradient is centred in its tile, so
     the same position puts the dot half a cell away from the line it
     is meant to sit on -- which is exactly what it was doing, at the
     right spacing, in the middle of every heavy square. The extra half
     pixel aims at the middle of the 1px line rather than its left
     edge. */
  const mid = big / 2 - 0.5;
  layers.push(`radial-gradient(${dot} 1.4px, transparent 1.5px)`);
  sizes.push(`${big}px ${big}px`);
  spots.push(`${at(x0 - mid, big)}px ${at(y0 - mid, big)}px`);

  paper.style.backgroundImage = layers.join(", ");
  paper.style.backgroundSize = sizes.join(", ");
  paper.style.backgroundPosition = spots.join(", ");
}

function panPaper(event) {
  /* Take hold of the room and move it. The only way to see past the
     edge of the window now that there are no scrollbars -- and the
     reason there are none, because two ways to do one thing is one
     too many and the strips cost real room.

     A press that does not travel is still a click, and clicking bare
     paper still clears the selection. Four pixels of slack, the same
     threshold the name cards use, because a mouse drifts a little
     while a button is going down and a click that cleared nothing
     would feel broken.

     Nothing here re-renders. `applyZoom` moves and repaints, and the
     element holding the pointer capture is the paper itself, which no
     redraw replaces -- the lesson from the resize grips, which died
     after a millimetre because a `pointermove` handler rebuilt the
     node under the pointer. */
  if (event.pointerType === "mouse" && event.button !== 0) return;
  const paper = seatingPaper();
  const from = [event.clientX, event.clientY];
  const start = { x: pan.x, y: pan.y };
  let moved = false;
  try { paper.setPointerCapture(event.pointerId); } catch (err) { /* fine */ }

  const onMove = e => {
    const dx = e.clientX - from[0], dy = e.clientY - from[1];
    if (!moved && Math.abs(dx) + Math.abs(dy) < 4) return;
    moved = true;
    paper.classList.add("panning");
    pan.x = start.x + dx;
    pan.y = start.y + dy;
    const section = currentSection();
    if (section) applyZoom(section);
  };
  const done = () => {
    paper.removeEventListener("pointermove", onMove);
    paper.removeEventListener("pointerup", done);
    paper.removeEventListener("pointercancel", done);
    paper.classList.remove("panning");
    if (moved) return;                   // it was a drag, not a click
    const wasOpen = paletteOpen || railOpen;
    paletteOpen = false;                 // rolls back into the plus
    railOpen = false;                    // and the mode list rolls shut
    if (selected || selectedChair || wasOpen) {
      selected = null;
      selectedChair = null;
      renderSeating();
    }
  };
  paper.addEventListener("pointermove", onMove);
  paper.addEventListener("pointerup", done);
  paper.addEventListener("pointercancel", done);
}

function zoomBy(step) {
  const section = currentSection();
  if (!section) return;
  const area = (drawn.box && drawn.box.w) ? drawn.box : contentBox(section);
  // Proportional, not additive: a tenth of a point is a third of the
  // picture at 30% and a fortieth of it at 400%.
  const now = seatingZoom === null
    ? fitZoom(seatingPaper(), area) : seatingZoom;
  const next = Math.min(4, Math.max(0.15, now * (step > 0 ? 1.25 : 0.8)));
  /* Zoom about the middle of the window, so whatever you were looking
     at is still in front of you afterwards. Both the home position and
     the pan scale with the zoom, so holding the middle fixed works out
     to scaling the pan by the same ratio -- no screen-to-room
     conversion needed. */
  pan.x *= next / now;
  pan.y *= next / now;
  seatingZoom = next;
  applyZoom(section);
}

// ------------------------------------------------------------- projector --

function presentKeys(event) {
  if (document.getElementById("view-seating").hidden) return;
  if (event.key === "Escape" && !projecting()) {
    if (picked) { picked = null; renderSeating(); return; }

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

  /* The arrows walk the Up Next line, and space goes forward.

     They used to change section while presenting, which was the wrong
     thing for the arrow keys to do: a projected chart is one room, and
     there is no moment at the front of a class where the next thing
     you want is the other section. Switching rooms is a decision taken
     before you start, with the controls up. */
  const step = { ArrowRight: 1, ArrowDown: 1, PageDown: 1,
                 " ": 1, Enter: 1,
                 ArrowLeft: -1, ArrowUp: -1, PageUp: -1 }[event.key];
  if (upnext && step && !onControl) {
    event.preventDefault();
    upnextStep(step);
    return;
  }
  if (!projecting()) return;
  if (event.key === "Escape") { setProjecting(false); return; }
}

function onFullscreenChange() {
  // Leaving by the browser's own Escape has to leave the mode too, or
  // the chrome stays hidden with no way back.
  // Leaving fullscreen by the browser's own Escape is only about
  // fullscreen now; projector mode is a separate switch and stays
  // where it was put.
  paintChrome();
  sizeSeating();
  refit();
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
  if (fullscreen()) { view.style.height = "100vh"; }
  else {
    view.style.height = "";
    const top = view.getBoundingClientRect().top + window.scrollY;
    view.style.height = Math.max(260, window.innerHeight - top - 14) + "px";
  }
  layoutRail();
}

// --------------------------------------------------------------- wiring --

/* Its own, rather than lines inside the host's `boot`. The host calls
   `loadSeating` when the tab opens and otherwise knows nothing about
   what is in here. */
function wireSeating() {
  document.getElementById("seat-in").onclick = () => zoomBy(1);
  document.getElementById("seat-out").onclick = () => zoomBy(-1);
  document.getElementById("seat-zoom").onclick = () => {
    refit();
    const section = currentSection();
    if (section) applyZoom(section);
  };
  document.getElementById("seat-upnext").onclick = () => {
    upnext = !upnext;
    if (!upnext) { upnextAt = -1; upnextFor = ""; }
    selected = null;
    picked = null;
    selectedChair = null;
    paintChrome();
    renderSeating();
  };
  document.getElementById("seat-project").onclick =
    () => setProjecting(!projecting());
  document.getElementById("seat-full").onclick = toggleFullscreen;
  for (const [id, get, set] of [
    ["seat-versions", () => showVersions, v => { showVersions = v; }],
    ["seat-labels", () => showLabels, v => { showLabels = v; }],
  ]) document.getElementById(id).onclick = () => {
    set(!get());
    paintChrome();
    renderSeating();
  };
  paintChrome();                   // draws every icon for the first time
  document.getElementById("seat-save").onclick = saveSeating;
  document.getElementById("seat-discard").onclick = discardRoom;
  /* Pressing the paper, rather than a thing on it, either pans the
     room or -- if the pointer never travels -- clears the selection.
     `panPaper` decides which on release. */
  seatingPaper().addEventListener("pointerdown", e => {
    if (e.target.closest(".shape, .seatcard, .pill, .grip, .spinner")) return;
    panPaper(e);
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
