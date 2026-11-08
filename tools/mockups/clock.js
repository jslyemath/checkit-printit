/* Options for the Runs glyph.

   Runs is the list of print runs that have already happened, and it
   has worn a clock with a history arrow round it from the start.
   Two complaints, in order:

   1. the arrowhead was a right-angle corner, `M6.2 3.2v2.9H3.3` --
      an L beside the dial rather than a point on the end of the
      arc, and not aimed along it. Fixed by placing both wings off
      the **tangent at the arc's own end point**, 34 degrees either
      side, which is what `dial()` below does.
   2. it is still "incredibly imbalanced and awkward". That one is
      not about the head. It is about where the gap sits: a
      quarter-circle bite out of the upper left, with the hands
      pointing down and right, puts every heavy thing on one
      diagonal and nothing on the other.

   So these options move the weight about rather than redraw the
   head. Only the rail draws this glyph, at 21px, so there is one
   size to satisfy -- checked with a grep before anything was
   drawn, which is the habit the door's 13px miss earned.

   Magnified panels are the real pixels; see this folder's README. */
(function () {
  const RAD = Math.PI / 180;

  function at(deg, r, cx, cy) {
    return [+(cx + r * Math.cos(deg * RAD)).toFixed(2),
            +(cy + r * Math.sin(deg * RAD)).toFixed(2)];
  }

  /* An arc travelling anticlockwise on screen from `a` to `b`, with
     an arrowhead at `b` whose wings sit 34 degrees either side of
     the tangent there. Anticlockwise because the arrow means
     backwards: these are runs that already happened.

     Note the tangent for *decreasing* angle is (sin, -cos), not
     (-sin, cos). Getting that backwards points the head the way the
     arc came from, which looks almost right and is the sort of
     thing nobody spots at 21px. */
  function dial(a, b, r, head, cx = 12, cy = 12) {
    const [ax, ay] = at(a, r, cx, cy);
    const [bx, by] = at(b, r, cx, cy);
    const travelled = ((a - b) + 360) % 360;
    const tx = Math.sin(b * RAD), ty = -Math.cos(b * RAD);
    const wing = (deg) => {
      const c = Math.cos(deg * RAD), s = Math.sin(deg * RAD);
      return `${(bx - (tx * c - ty * s) * head).toFixed(2)} `
           + `${(by - (tx * s + ty * c) * head).toFixed(2)}`;
    };
    return `M${ax} ${ay}A${r} ${r} 0 ${travelled > 180 ? 1 : 0} 0 ${bx} ${by}`
         + `M${wing(34)}L${bx} ${by}L${wing(-34)}`;
  }

  const RING = "M12 3.7a8.3 8.3 0 1 1 0 16.6 8.3 8.3 0 0 1 0-16.6";
  const HANDS = "M12 7.2v5l3.2 2.1";

  const OPTS = [
    { key: "1 as built",
      note: "the gap runs from 9 o'clock to nearly 12 -- a quarter "
          + "of the circle gone from one side, with the hands "
          + "weighted to the opposite one. This is the one he calls "
          + "imbalanced",
      parts: [dial(178, 262, 8.2, 3.6), HANDS] },
    { key: "2 gap at the top",
      note: "the gap straddles 12 o'clock, 40 degrees wide, so the "
          + "bite is symmetric about the upright and the head sits "
          + "just right of centre pointing up and left. Nothing is "
          + "missing from one side",
      parts: [dial(250, 290, 8.2, 3.3), HANDS] },
    { key: "3 small notch",
      note: "the same place as today but a 40-degree gap instead of "
          + "84, and a smaller head. Tidier, still one-sided",
      parts: [dial(206, 246, 8.3, 3.0), HANDS] },
    { key: "4 plain clock",
      note: "no arrow at all. Perfectly balanced and the calmest "
          + "thing in the rail. It says *time*, and leaves *past* to "
          + "the label beside it",
      parts: [RING, HANDS] },
    { key: "5 plain, hands up",
      note: "a closed dial with the hands at ten to twelve, so the "
          + "ink is spread rather than hanging to the lower right. "
          + "The two hands can close into a V at 21px",
      parts: [RING, "M12 12.1V7.1M12 12.1L8.3 9.6"] },
    { key: "6 a page",
      note: "a different idea entirely: a run is a printed job, so "
          + "draw the paper. It sits close to the clipboard on "
          + "Update form and the printer on Print job, which is the "
          + "reason to be careful of it",
      parts: ["M8.2 3.4h7.1l3.3 3.3v11.1a1.8 1.8 0 0 1-1.8 1.8H8.2"
              + "a1.8 1.8 0 0 1-1.8-1.8V5.2a1.8 1.8 0 0 1 1.8-1.8z",
              "M15.3 3.4v3.3h3.3",
              "M9.3 11.4h5.4M9.3 15.0h3.6"] },
  ];

  const NS = "http://www.w3.org/2000/svg";

  function draw(parts, px) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "glyph");
    svg.style.width = px + "px";
    svg.style.height = px + "px";
    svg.style.setProperty("--glyph-size", px);
    for (const d of parts) {
      const p = document.createElementNS(NS, "path");
      p.setAttribute("d", d);
      svg.appendChild(p);
    }
    return svg;
  }

  async function magnified(parts, cssPx, zoom) {
    const dev = Math.round(cssPx * devicePixelRatio);
    const ink = getComputedStyle(document.body).color;
    const svg = `<svg xmlns="http://www.w3.org/2000/svg"`
      + ` viewBox="0 0 24 24" width="${dev}" height="${dev}">`
      + `<g fill="none" stroke="${ink}"`
      + ` stroke-width="${(24 * 1.5 / cssPx).toFixed(3)}"`
      + ` stroke-linecap="round" stroke-linejoin="round">`
      + parts.map(d => `<path d="${d}"/>`).join("") + `</g></svg>`;
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
    .ck { padding: var(--s4) var(--s5) 56px; max-width: 820px; }
    .ck p.lede { color: var(--ink-2); margin: 0 0 var(--s4);
                 max-width: 62ch; font-size: var(--t-sm); }
    .ck-row { display: grid; grid-template-columns: 13rem auto;
              gap: var(--s4); padding: var(--s3) 0;
              border-top: 1px solid var(--line); align-items: center; }
    .ck-name { font: 600 var(--t-base)/1.2 var(--font); }
    .ck-note { color: var(--muted); font-size: 12px; line-height: 1.35;
               font-weight: 400; margin-top: 5px; }
    .ck-art { display: flex; align-items: center; gap: var(--s4); }
    .ck-rail { display: flex; align-items: center; gap: var(--s2);
               padding: 7px 12px; background: var(--surface-2);
               border-radius: var(--r-md);
               font: 500 var(--t-base)/1 var(--font); }
  `;

  async function render() {
    const main = document.querySelector("main");
    main.innerHTML = "";
    const style = el("style");
    style.textContent = CSS;
    main.appendChild(style);

    const wrap = el("div", "ck");
    wrap.appendChild(el("h2", null, "The Runs glyph"));
    wrap.appendChild(el("p", "lede",
      "21px is the only size this is drawn at. The big panel is the "
      + "real pixels magnified six times; then the shape at 40px, "
      + "and then the glyph where it lives, beside its label."));
    main.appendChild(wrap);

    for (const opt of OPTS) {
      const row = el("div", "ck-row");
      const name = el("div", "ck-name");
      name.appendChild(document.createTextNode(opt.key));
      name.appendChild(el("div", "ck-note", opt.note));
      row.appendChild(name);

      const art = el("div", "ck-art");
      art.appendChild(await magnified(opt.parts, 21, 6));
      art.appendChild(draw(opt.parts, 40));
      const rail = el("div", "ck-rail");
      rail.appendChild(draw(opt.parts, 21));
      rail.appendChild(el("span", null, "Runs"));
      art.appendChild(rail);
      row.appendChild(art);
      wrap.appendChild(row);
    }
  }

  render();
})();
