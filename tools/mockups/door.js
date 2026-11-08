/* Candidates for the `drop` / `restore` door.

   The one in the app is a bare rounded rectangle with a knob dot and
   an arrow whose head lands *inside* the rectangle. He says it does
   not read, and the reason is measurable: `drop` is drawn at 18px
   and nowhere else, and at 18px the stroke is 24 * 1.5 / 18 = 2.0
   units wide in a 24-unit box. The arrowhead's tip is at x=10.4 and
   the panel's left edge at x=9, so the two overlap before the stroke
   is even counted.

   He pointed at a stock icon: a door frame with its left side open,
   a panel hinged at the right and swung toward the viewer, and an
   arrow going in through the opening -- with a single-stroke arrow,
   not that picture's outlined block one.

   **The arithmetic says the whole of that cannot fit at 18px.** The
   reference stacks five horizontal things up the middle of the box:
   leaf top, lintel, arrow, threshold, leaf bottom. Five strokes at
   2.0 is 10 units of ink, leaving 14 units for the four gaps between
   them -- 3.5 each, so 1.5 of white in each. The gear pass measured
   0.51 of white as a blob and 1.40 as comfortable, so 1.5 is only
   just past the line, and here it has to hold four times over.

   Something therefore has to give, and these candidates are the
   different things that could. `faithful` is included *because* the
   arithmetic forbids it: a prediction nobody looks at is a
   prediction nobody learns from.

   Judge at 18. The magnified panels are the real pixels -- the glyph
   rasterised at 18 CSS px times this screen's device pixel ratio and
   blown up with smoothing off. A plain screenshot cannot settle a
   glyph, because the pane downscales it; see this folder's README.

   **The door must not move when the arrow turns.** `restore` is the
   same door with the arrow reversed in the same lane, not the whole
   glyph mirrored -- a mirrored frame puts the doorway on the other
   side, which says the room moved. So a candidate here is a fixed
   `door` plus an arrow given as numbers, and the two renderings come
   from the same pair.

   **Chosen and built: `returns`, at the bottom of the list.**

   `ajar` was chosen first and rejected by him, for two reasons
   worth keeping:

   * **the frame was not suggested around the arrow.** Every
     candidate above puts the frame's opening at the left as a plain
     break in a rectangle, so the arrow arrives at a box rather than
     passing through a doorway. What you actually see beside someone
     walking through a door is the *corner returns* -- a short
     upright and a short horizontal at the head and the foot of the
     opening. Two small marks, and they sit above and below the
     arrow's lane rather than in it.
   * **a leaning line is not a leaf.** It reads as a divider. The
     leaf has to be a closed quadrilateral, and -- his words -- the
     **top and bottom** are what slant, not the sides. A leaning
     side is a door falling over; a slanted head and foot is a door
     turned toward you.

   Both notes were right, and neither is a matter of taste: a single
   stroke cannot be a panel, and the lean was on the wrong pair of
   edges. The candidates from that round are kept below the first
   set, and the paths that shipped are in `app.js`. */
(function () {
  /* A single-stroke arrow. `h` is the head's half-height, which is
     also how far back along the shaft each head line reaches, so the
     head is a right angle whichever way it points. */
  function arrow(tail, tip, y, h) {
    const back = tip + (tail < tip ? -h : h);
    return `M${tail} ${y}H${tip}`
         + `M${back} ${y - h}L${tip} ${y}L${back} ${y + h}`;
  }

  const CANDS = [
    {
      key: "now",
      note: "what is in the app. The arrowhead ends at 10.4 and the "
          + "panel starts at 9, so the head is drawn inside the wall. "
          + "The knob touches the right edge too",
      door: [{ r: [9, 2.5, 12, 19, 1.6] }, { d: "M18.4 12h0.01" }],
      arrow: [2, 10.4, 12, 3.0],
    },
    {
      key: "faithful",
      note: "the reference, all of it: leaf, lintel, threshold, two "
          + "left stubs, arrow. Five layers. Here to be looked at, "
          + "not because the arithmetic allows it",
      door: [
        { d: "M14.9 4.2L21.0 2.4L21.0 21.6L14.9 19.8Z" },
        { d: "M7.4 9.4V8.0A1.4 1.4 0 0 1 8.8 6.6H14.9" },
        { d: "M7.4 14.6V16.0A1.4 1.4 0 0 0 8.8 17.4H14.9" },
      ],
      arrow: [2.4, 14.4, 12, 3.2],
    },
    {
      key: "bars",
      note: "the reference minus the two left stubs, the leaf pushed "
          + "taller and the bars pulled apart. Four layers: 2.0 of "
          + "white above the lintel, 3.2 between it and the arrow",
      door: [
        { d: "M14.9 2.8L21.2 1.4L21.2 22.6L14.9 21.2Z" },
        { d: "M6.8 6.8H14.9" },
        { d: "M6.8 17.2H14.9" },
      ],
      arrow: [2.4, 14.4, 12, 3.2],
    },
    {
      key: "ajar",
      note: "the frame and the leaf share the top and bottom lines, "
          + "which is what you see when the door is only slightly "
          + "open. Three layers. The leaf is the leaning line, and "
          + "the lean is the only thing saying it is a door",
      door: [
        { d: "M6.6 9.0V5.4A1.8 1.8 0 0 1 8.4 3.6H21.2V20.4H8.4"
             + "A1.8 1.8 0 0 0 6.6 18.6V15.0" },
        { d: "M15.4 3.9L13.9 20.1" },
      ],
      arrow: [1.8, 12.4, 12, 3.0],
    },
    {
      key: "doorway",
      note: "the same, with the left stubs dropped so nothing crowds "
          + "the arrow, and the leaf upright. The plainest reading: "
          + "a doorway, a door, and something going through",
      door: [
        { d: "M8.4 3.6H21.2V20.4H8.4" },
        { d: "M15.0 3.6V20.4" },
      ],
      arrow: [1.6, 12.6, 12, 3.2],
    },
    {
      key: "jamb",
      note: "the other way round: the leaf is the big thing, as in "
          + "the reference, and the frame shrinks to a left jamb "
          + "broken open for the arrow. Nothing stacks in the "
          + "arrow's lane",
      door: [
        { d: "M15.0 3.2L21.2 1.8L21.2 22.2L15.0 20.8Z" },
        { d: "M7.0 2.8V8.8" },
        { d: "M7.0 15.2V21.2" },
      ],
      arrow: [2.6, 13.4, 12, 3.0],
    },
    {
      key: "exit",
      note: "the conventional one, for comparison: a bracket open on "
          + "one side and the arrow going through it. No leaf at "
          + "all, and almost certainly the most legible thing here",
      door: [
        { d: "M13.6 3.6H7.0A2 2 0 0 0 5.0 5.6V18.4A2 2 0 0 0 7.0 20.4H13.6" },
      ],
      arrow: [10.2, 21.4, 12, 3.2],
    },
    {
      key: "cleared",
      note: "the smallest possible fix: the panel as it is, moved "
          + "right, and the arrow stopped clear of it with a proper "
          + "single-stroke head. 1.6 of white in the gap",
      door: [{ r: [14.8, 2.6, 6.6, 18.8, 1.6] }, { d: "M19.6 12h0.01" }],
      arrow: [1.6, 11.2, 12, 3.2],
    },

    /* --- second round, after the first was rejected --- */

    {
      key: "returns",
      note: "**built.** The frame is two corner returns at the left, "
          + "which is the part of a frame you see beside someone "
          + "walking through. The leaf is a closed quadrilateral: "
          + "vertical sides, slanted top and bottom, hinge edge the "
          + "taller of the two as in the icon he pointed at",
      door: [
        { d: "M6.2 8.6V4.8A1.8 1.8 0 0 1 8 3H12.2" },
        { d: "M6.2 15.4V19.2A1.8 1.8 0 0 0 8 21H12.2" },
        { d: "M14.6 5.2L21 2.4V21.6L14.6 18.8Z" },
      ],
      arrow: [1.6, 11.4, 12, 3],
    },
    {
      key: "free taller",
      note: "the same with the perspective the other way: the free "
          + "edge nearer and so taller, which is what a door opening "
          + "*toward* you really looks like. Reads fine; it is not "
          + "what the reference draws",
      door: [
        { d: "M6.2 8.6V4.8A1.8 1.8 0 0 1 8 3H12.2" },
        { d: "M6.2 15.4V19.2A1.8 1.8 0 0 0 8 21H12.2" },
        { d: "M14.4 2.6L21 5.0V19.0L14.4 21.4Z" },
      ],
      arrow: [1.5, 11.2, 12, 3],
    },
    {
      key: "parallelogram",
      note: "a true parallelogram -- both sides the same height, the "
          + "whole leaf sheared up to the right. It reads as a door "
          + "tilted rather than turned, and looks like it is floating",
      door: [
        { d: "M6.2 8.6V4.8A1.8 1.8 0 0 1 8 3H12.2" },
        { d: "M6.2 15.4V19.2A1.8 1.8 0 0 0 8 21H12.2" },
        { d: "M14.8 6.0L21.0 3.2V18.0L14.8 20.8Z" },
      ],
      arrow: [1.6, 11.6, 12, 3],
    },
    {
      key: "lintel",
      note: "corner returns replaced by a whole frame, with the "
          + "leaf's slanted edges running onto its corners. The "
          + "converging wedges fill in and the corners go solid",
      door: [
        { d: "M6.2 8.6V4.4A1.8 1.8 0 0 1 8 2.6H21.2V21.4H8"
             + "A1.8 1.8 0 0 0 6.2 19.6V15.4" },
        { d: "M14.6 6.6L21.2 2.6" },
        { d: "M14.6 6.6V17.4" },
        { d: "M14.6 17.4L21.2 21.4" },
      ],
      arrow: [1.6, 11.4, 12, 3],
    },
  ];

  const NS = "http://www.w3.org/2000/svg";

  function partsFor(cand, back) {
    const [tail, tip, y, h] = cand.arrow;
    return cand.door.concat([
      { d: back ? arrow(tip, tail, y, h) : arrow(tail, tip, y, h) },
    ]);
  }

  function draw(parts, px) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "glyph");
    svg.style.width = px + "px";
    svg.style.height = px + "px";
    svg.style.setProperty("--glyph-size", px);
    for (const p of parts) {
      if (p.o) {
        const c = document.createElementNS(NS, "circle");
        c.setAttribute("cx", p.o[0]);
        c.setAttribute("cy", p.o[1]);
        c.setAttribute("r", p.o[2]);
        svg.appendChild(c);
      } else if (p.r) {
        const rect = document.createElementNS(NS, "rect");
        rect.setAttribute("x", p.r[0]);
        rect.setAttribute("y", p.r[1]);
        rect.setAttribute("width", p.r[2]);
        rect.setAttribute("height", p.r[3]);
        rect.setAttribute("rx", p.r[4]);
        svg.appendChild(rect);
      } else {
        const path = document.createElementNS(NS, "path");
        path.setAttribute("d", p.d);
        svg.appendChild(path);
      }
    }
    return svg;
  }

  /* Rasterise at the size the screen will really draw, then magnify
     with smoothing off. `stroke-width` and the colour are written in
     by hand: `.glyph` is a class in the page's stylesheet and a
     data-URL SVG is its own document, so neither that class nor
     `currentColor` reaches inside it. */
  async function magnified(parts, cssPx, zoom) {
    const dev = Math.round(cssPx * devicePixelRatio);
    const ink = getComputedStyle(document.body).color;
    const inner = draw(parts, cssPx).innerHTML;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg"`
      + ` viewBox="0 0 24 24" width="${dev}" height="${dev}">`
      + `<g fill="none" stroke="${ink}"`
      + ` stroke-width="${(24 * 1.5 / cssPx).toFixed(3)}"`
      + ` stroke-linecap="round" stroke-linejoin="round">${inner}</g></svg>`;
    const img = new Image();
    await new Promise(res => {
      img.onload = res;
      img.src = "data:image/svg+xml;base64," + btoa(svg);
    });
    const small = document.createElement("canvas");
    small.width = small.height = dev;
    small.getContext("2d").drawImage(img, 0, 0, dev, dev);
    const big = document.createElement("canvas");
    big.width = big.height = dev * zoom;
    const g = big.getContext("2d");
    g.imageSmoothingEnabled = false;
    g.drawImage(small, 0, 0, dev * zoom, dev * zoom);
    big.style.width = (dev * zoom) + "px";
    return big;
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  const CSS = `
    main { overflow-y: auto; }
    .dk { padding: var(--s4) var(--s5) 56px; max-width: 760px; }
    .dk h2 { margin: 0 0 var(--s2); }
    .dk p.lede { color: var(--ink-2); margin: 0 0 var(--s4);
                 max-width: 64ch; font-size: var(--t-sm); }
    .dk-row { display: grid; grid-template-columns: 13rem auto;
              gap: var(--s4); padding: var(--s3) 0;
              border-top: 1px solid var(--line); align-items: center; }
    .dk-name { font: 600 var(--t-base)/1.2 var(--font); }
    .dk-note { color: var(--muted); font-size: 12px; line-height: 1.35;
               font-weight: 400; margin-top: 5px; }
    .dk-art { display: flex; align-items: center; gap: var(--s4); }
    .dk-one { display: flex; flex-direction: column; align-items: center;
              gap: 4px; }
    .dk-one span { font-size: 11px; color: var(--muted); }
    .dk-real { display: flex; align-items: center; gap: var(--s2);
               padding: 6px 10px; background: var(--surface-2);
               border-radius: var(--r-md); }
  `;

  async function render() {
    const main = document.querySelector("main");
    main.innerHTML = "";
    const style = el("style");
    style.textContent = CSS;
    main.appendChild(style);

    const wrap = el("div", "dk");
    wrap.appendChild(el("h2", null, "The door"));
    wrap.appendChild(el("p", "lede",
      "Drop then restore, at 18px, which is the only size they are "
      + "used at. The big panels are the real pixels magnified four "
      + "times; the two small buttons on the right are the pair as "
      + "they would sit in a roster row."));
    main.appendChild(wrap);

    for (const cand of CANDS) {
      const row = el("div", "dk-row");
      const name = el("div", "dk-name");
      name.appendChild(document.createTextNode(cand.key));
      name.appendChild(el("div", "dk-note", cand.note));
      row.appendChild(name);

      const art = el("div", "dk-art");
      for (const [label, back] of [["drop", false], ["restore", true]]) {
        const one = el("div", "dk-one");
        one.appendChild(await magnified(partsFor(cand, back), 18, 4));
        one.appendChild(el("span", null, label));
        art.appendChild(one);
      }
      const real = el("div", "dk-real");
      for (const back of [false, true]) {
        const b = el("button", "iconbtn");
        b.type = "button";
        b.appendChild(draw(partsFor(cand, back), 18));
        real.appendChild(b);
      }
      art.appendChild(real);
      row.appendChild(art);
      wrap.appendChild(row);
    }
  }

  render();
})();
