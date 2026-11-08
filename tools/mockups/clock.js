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
  function dial(gapA, gapB, r, head, cx = 12, cy = 12, cw = false) {
    // gapA..gapB is the GAP. Travel takes the long way round, from one
    // edge of the gap to the other, so the head always lands on a gap
    // edge and the arc is always the large one.
    const start = cw ? gapB : gapA;
    const end = cw ? gapA : gapB;
    const [ax, ay] = at(start, r, cx, cy);
    const [bx, by] = at(end, r, cx, cy);
    const tx = cw ? -Math.sin(end * RAD) : Math.sin(end * RAD);
    const ty = cw ? Math.cos(end * RAD) : -Math.cos(end * RAD);
    const wing = (deg) => {
      const c = Math.cos(deg * RAD), s = Math.sin(deg * RAD);
      return `${(bx - (tx * c - ty * s) * head).toFixed(2)} `
           + `${(by - (tx * s + ty * c) * head).toFixed(2)}`;
    };
    return `M${ax} ${ay}A${r} ${r} 0 1 ${cw ? 1 : 0} ${bx} ${by}`
         + `M${wing(34)}L${bx} ${by}L${wing(-34)}`;
  }

  /* A plain sheet. Written out rather than left as a <rect> because
     these get combined with partial outlines below, and one shape
     kind per family keeps the editing honest. */
  function sheet(x0, y0, x1, y1, r) {
    return `M${x0 + r} ${y0}H${x1 - r}A${r} ${r} 0 0 1 ${x1} ${y0 + r}`
         + `V${y1 - r}A${r} ${r} 0 0 1 ${x1 - r} ${y1}`
         + `H${x0 + r}A${r} ${r} 0 0 1 ${x0} ${y1 - r}`
         + `V${y0 + r}A${r} ${r} 0 0 1 ${x0 + r} ${y0}Z`;
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

    /* --- paper plus a circular arrow, after he liked the page ---

       Two objects in a 24-unit box with a 1.714-unit stroke, which
       the arithmetic says should not fit: a badge small enough to
       sit beside a page is about 9 units across, and the page's
       corner lands inside it.

       It fits anyway, because of a knockout. The page outline is
       simply **not drawn** where the badge sits -- its bottom edge
       and its right edge stop short, and the gap reads as the page
       passing behind. An overlap that would have merged becomes a
       gap drawn on purpose. That is the trick worth remembering
       from this round; it is how every badged icon in every set
       does it, and it was not obvious from the measurements. */

    { key: "7 page, arrow inside",
      note: "the arrow where the page's text lines would be. Biggest "
          + "arrow of the lot and the clearest, but it is the browser "
          + "reload icon, and that is a strong prior reading",
      parts: [sheet(4.0, 2.4, 20.0, 21.6, 1.8),
              dial(250, 290, 4.6, 2.5, 12, 12.6)] },
    { key: "8 stack, arrow inside",
      note: "two sheets, the arrow on the front one. The second "
          + "sheet is what says *runs* rather than *a run*",
      parts: ["M7.6 4.2h10.6a1.8 1.8 0 0 1 1.8 1.8v10.6",
              sheet(3.0, 7.6, 16.4, 21.4, 1.8),
              dial(250, 290, 3.9, 2.2, 9.7, 14.7)] },
    { key: "9 arrow round page",
      note: "the ring outside, the page inside. At 21px the page has "
          + "no room for anything on it, so it is a rounded rectangle "
          + "in a circle",
      parts: [dial(248, 292, 10.0, 3.2), sheet(7.6, 7.4, 16.4, 18.6, 1.4)] },
    { key: "10 arrow over stack",
      note: "drawn and failed. The sheets below the arc read as a "
          + "bowl, and the arc's ends have nothing to land on",
      parts: [dial(196, 330, 9.6, 3.0, 12, 13.6),
              "M5.8 21.4h12.4", "M4.6 17.6h14.8",
              sheet(6.2, 8.6, 17.8, 14.0, 1.3)] },
    { key: "11 page + badge",
      note: "the knockout. The page's bottom edge stops at x=11 and "
          + "its right edge at y=9.6, so the badge sits in the gap "
          + "instead of fighting the corner",
      parts: ["M11.0 17.4H4.4A1.8 1.8 0 0 1 2.6 15.6V4.4"
              + "A1.8 1.8 0 0 1 4.4 2.6H13.0A1.8 1.8 0 0 1 14.8 4.4V9.6",
              dial(250, 290, 4.6, 2.4, 17.2, 17.0)] },
    { key: "12 stack + badge",
      note: "the same with a second sheet behind. Paper and arrow "
          + "stay two separate ideas rather than one inside the "
          + "other, and the stack says there is a list of them",
      parts: ["M6.6 3.8h8.8a1.6 1.6 0 0 1 1.6 1.6v6.2",
              "M9.4 16.2H4.0A1.6 1.6 0 0 1 2.4 14.6V8.2"
              + "A1.6 1.6 0 0 1 4.0 6.6H12.2A1.6 1.6 0 0 1 13.8 8.2V11.4",
              dial(250, 290, 4.8, 2.5, 16.6, 16.8)] },

    /* The same three the other way round. Anticlockwise is history
       -- these runs already happened -- and clockwise is re-run,
       which the tab also supports: "start a new run from these
       settings". Both are defensible, so both are drawn.

       Turning one round is not a sweep-flag change. The head has to
       stay on the end of *travel*, so the two gap edges swap roles
       as start and end; flipping only the flag draws the 40-degree
       gap instead of the 320-degree arc, which is exactly what
       happened on the first attempt. */
    { key: "13 stack+inside, re-run",
      parts: ["M7.6 4.2h10.6a1.8 1.8 0 0 1 1.8 1.8v10.6",
              sheet(3.0, 7.6, 16.4, 21.4, 1.8),
              dial(250, 290, 3.9, 2.2, 9.7, 14.7, true)],
      note: "clockwise" },
    { key: "14 page+badge, re-run",
      parts: ["M11.0 17.4H4.4A1.8 1.8 0 0 1 2.6 15.6V4.4"
              + "A1.8 1.8 0 0 1 4.4 2.6H13.0A1.8 1.8 0 0 1 14.8 4.4V9.6",
              dial(250, 290, 4.6, 2.4, 17.2, 17.0, true)],
      note: "clockwise" },
    { key: "15 stack+badge, re-run",
      parts: ["M6.6 3.8h8.8a1.6 1.6 0 0 1 1.6 1.6v6.2",
              "M9.4 16.2H4.0A1.6 1.6 0 0 1 2.4 14.6V8.2"
              + "A1.6 1.6 0 0 1 4.0 6.6H12.2A1.6 1.6 0 0 1 13.8 8.2V11.4",
              dial(250, 290, 4.8, 2.5, 16.6, 16.8, true)],
      note: "clockwise" },
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
