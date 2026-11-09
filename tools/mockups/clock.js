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

  /* ---- measuring, because eyeballing these was wrong three times ----

     Sample every stroke into points and ask how close two parts that
     should not touch actually get. At 21px the stroke is 1.714 units
     wide, so two strokes need about 2.55 between their centrelines
     before any white survives between them. GAP is that number. */
  const GAP = 2.55;

  function arcPts(cx, cy, r, a0, a1, cw, step = 0.12) {
    const span = cw ? ((a1 - a0) + 360) % 360 : ((a0 - a1) + 360) % 360;
    const n = Math.max(2, Math.ceil(span * RAD * r / step));
    const out = [];
    for (let i = 0; i <= n; i++) {
      const t = a0 + (cw ? 1 : -1) * span * i / n;
      out.push([cx + r * Math.cos(t * RAD), cy + r * Math.sin(t * RAD)]);
    }
    return out;
  }

  function linePts(p, q, step = 0.12) {
    const n = Math.max(1, Math.ceil(Math.hypot(q[0] - p[0], q[1] - p[1]) / step));
    const out = [];
    for (let i = 0; i <= n; i++)
      out.push([p[0] + (q[0] - p[0]) * i / n, p[1] + (q[1] - p[1]) * i / n]);
    return out;
  }

  function minDist(A, B) {
    let m = Infinity;
    for (const a of A) for (const b of B) {
      const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
      if (d < m) m = d;
    }
    return +m.toFixed(2);
  }

  /* ---- the circular arrow, with a head that clears its own arc ----

     **This is the thing that kept going wrong.** Wings splayed about
     the tangent do not work on a small circle: the arc curves into
     the inner wing. The wing's far end sits at radius

         |W - C| = hypot(r + h*sin(psi), h*cos(psi))

     from the centre, psi positive meaning away from it, so the inner
     wing ends `r - |W-C|` inside the arc -- and at r=4.8, h=2.5,
     psi=34 that is **0.82**, well under one stroke. The two merge
     into a hook. Every circular arrow drawn here before this was
     measured had a negative number there, the rail clock included.

     What works is an **asymmetric head**: the inner wing steep
     (about -70 degrees, so it dives away from the arc) and the outer
     shallow (about +45). A search over r, h and both angles, keeping
     the opening between 75 and 115 degrees so it still looks like a
     head, found nothing at all below r = 5.8. A circular arrow
     smaller than that cannot carry an arrowhead at 21px; it has to
     be a corner, or a filled triangle, or bigger. */
  function head(cx, cy, r, endDeg, h, inner, outer, cw) {
    const dir = cw ? 1 : -1;
    const beta = endDeg - dir * 90;          // backward along the tangent
    const tip = [cx + r * Math.cos(endDeg * RAD),
                 cy + r * Math.sin(endDeg * RAD)];
    const w = (psi) => {
      const a = (beta + dir * psi) * RAD;
      return [+(tip[0] + Math.cos(a) * h).toFixed(2),
              +(tip[1] + Math.sin(a) * h).toFixed(2)];
    };
    return { tip, wi: w(inner), wo: w(outer) };
  }

  function badge(cx, cy, r, gapA, gapB, h, inner, outer, cw) {
    const start = cw ? gapB : gapA, end = cw ? gapA : gapB;
    const H = head(cx, cy, r, end, h, inner, outer, cw);
    const s = [cx + r * Math.cos(start * RAD), cy + r * Math.sin(start * RAD)];
    const t = `${H.tip[0].toFixed(2)} ${H.tip[1].toFixed(2)}`;
    return {
      d: `M${s[0].toFixed(2)} ${s[1].toFixed(2)}`
       + `A${r} ${r} 0 1 ${cw ? 1 : 0} ${t}`
       + `M${H.wi[0]} ${H.wi[1]}L${t}L${H.wo[0]} ${H.wo[1]}`,
      pts: arcPts(cx, cy, r, start, end, cw)
             .concat(linePts(H.wi, H.tip), linePts(H.tip, H.wo)),
    };
  }

  /* The page, with its bottom and right edges stopped where the badge
     would crowd them -- the knockout.

     **Solve on the offset circle of radius r + GAP, not on the badge.**
     Stopping an edge where its own distance *along that edge* reaches
     GAP leaves the corner nearer than it looks, because the badge is
     round: the first version of this under-cut by nearly a unit and
     measured 0.05 of clearance where it claimed 2.55. */
  function knocked(x0, y0, x1, y1, rr, bcx, bcy, br) {
    const R = br + GAP;
    const dxr = Math.abs(x1 - bcx), dyb = Math.abs(y1 - bcy);
    const yStop = dxr < R ? bcy - Math.sqrt(R * R - dxr * dxr) : y1 - rr;
    const xStop = dyb < R ? bcx - Math.sqrt(R * R - dyb * dyb) : x1 - rr;
    return {
      d: `M${xStop.toFixed(2)} ${y1}H${(x0 + rr).toFixed(2)}`
       + `A${rr} ${rr} 0 0 1 ${x0} ${(y1 - rr).toFixed(2)}`
       + `V${(y0 + rr).toFixed(2)}A${rr} ${rr} 0 0 1 ${(x0 + rr).toFixed(2)} ${y0}`
       + `H${(x1 - rr).toFixed(2)}A${rr} ${rr} 0 0 1 ${x1} ${(y0 + rr).toFixed(2)}`
       + `V${yStop.toFixed(2)}`,
      pts: linePts([xStop, y1], [x0 + rr, y1])
        .concat(arcPts(x0 + rr, y1 - rr, rr, 90, 180, false),
                linePts([x0, y1 - rr], [x0, y0 + rr]),
                arcPts(x0 + rr, y0 + rr, rr, 180, 270, false),
                linePts([x0 + rr, y0], [x1 - rr, y0]),
                arcPts(x1 - rr, y0 + rr, rr, 270, 360, false),
                linePts([x1, y0 + rr], [x1, yStop])),
      xStop: +xStop.toFixed(2), yStop: +yStop.toFixed(2),
    };
  }

  /* The sheet behind. Offsetting it diagonally puts two rounded
     corners face to face, and **the diagonal pinch is much tighter
     than the offset**: at an offset of 3.0 with radii 1.6 and 1.7 the
     corners are 1.08 apart, not 3.0. The offset has to be about 4
     before that clears. */
  function backHint(x, y, w, down, rr) {
    return {
      d: `M${x.toFixed(2)} ${y.toFixed(2)}h${w.toFixed(2)}`
       + `a${rr} ${rr} 0 0 1 ${rr} ${rr}v${down.toFixed(2)}`,
      pts: linePts([x, y], [x + w, y])
        .concat(arcPts(x + w, y + rr, rr, 270, 360, false),
                linePts([x + w + rr, y + rr], [x + w + rr, y + rr + down])),
    };
  }

  /* One stack-and-arrow, measured.

     **Do not report the page-to-badge distance.** The knockout moves
     the stop point until that distance is exactly GAP, so it reads
     2.55 for every layout including hopeless ones -- shove the badge
     1.5 units left, or stretch the page to x=13, and it still says
     2.55. A number that cannot come out wrong is not a check. It was
     reported here for one round before that was noticed.

     The two that do move are the gap to the sheet behind -- break the
     offset to 2.6 and it drops to 1.28 -- and how much of the page's
     own right and bottom edges survive the knockout, which is what
     decides whether it still reads as a page. */
  function stackRerun(p) {
    const B = badge(p.bcx, p.bcy, p.br, 290, 340, p.h, -70, 45, true);
    const S = knocked(2.0, p.y0, p.x1, p.y1, 1.7, p.bcx, p.bcy, p.br);
    const H = backHint(2.0 + p.off, p.y0 - p.off, p.x1 - 3.6, 3.4, 1.6);
    return {
      parts: [H.d, S.d, B.d],
      toBack: minDist(B.pts, H.pts),
      behind: minDist(H.pts, S.pts),
      rightEdge: +((S.yStop - (p.y0 + 1.7)) / (p.y1 - p.y0 - 3.4)).toFixed(2),
      bottomEdge: +Math.min(1, (S.xStop - 3.7) / (p.x1 - 5.4)).toFixed(2),
    };
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

    /* ---- measured, after he picked stack-plus-clockwise ----

       Two faults in everything above, both of which he spotted and
       both of which turned out to be arithmetic:

       1. the arrowhead's inner wing merged into its own arc. The
          wings were splayed about the tangent; on a small circle the
          arc curves into them. Measured clearance was negative in
          every single one, the rail clock included.
       2. the badge and the page ran into each other at low
          resolution. The knockout was solved on the badge's own
          radius instead of the badge plus the gap, which leaves the
          corner far nearer than the number claims.

       These are built by `stackRerun`, which measures every pair and
       prints the worst. The badge is r = 5.8, which is the smallest
       the search allows: nothing below that can carry a head. */
    (() => { const r = stackRerun({ br: 5.8, bcx: 17.2, bcy: 17.2,
               y0: 6.2, x1: 10.0, y1: 16.0, off: 4.0, h: 3.4 });
      return { key: "16 measured, badge-led", parts: r.parts,
        note: `behind ${r.behind}, to back ${r.toBack} (need ${GAP}); `
            + `right edge ${r.rightEdge}, bottom ${r.bottomEdge} of the `
            + `page still drawn. The arrow is the larger object here, `
            + `because r=5.8 is the floor for a head` }; })(),
    (() => { const r = stackRerun({ br: 5.8, bcx: 17.2, bcy: 17.2,
               y0: 5.0, x1: 10.0, y1: 17.2, off: 3.8, h: 3.4 });
      return { key: "17 measured, tall page", parts: r.parts,
        note: `behind ${r.behind}, to back ${r.toBack}; right edge `
            + `${r.rightEdge}, bottom ${r.bottomEdge}. A taller page `
            + `reads more like paper at the same badge size` }; })(),
    (() => { const r = stackRerun({ br: 5.8, bcx: 17.0, bcy: 17.0,
               y0: 4.6, x1: 11.2, y1: 18.0, off: 3.6, h: 3.4 });
      return { key: "18 measured, big page", parts: r.parts,
        note: `behind ${r.behind}, to back ${r.toBack}; right edge `
            + `${r.rightEdge}, bottom ${r.bottomEdge}. The largest page `
            + `the clearances allow, so paper and arrow are even` }; })(),
    (() => { const r = stackRerun({ br: 5.8, bcx: 17.0, bcy: 17.0,
               y0: 4.6, x1: 11.8, y1: 17.2, off: 3.6, h: 3.4 });
      return { key: "19 measured, widest page", parts: r.parts,
        note: `behind ${r.behind}, to back ${r.toBack}; right edge `
            + `${r.rightEdge}, bottom ${r.bottomEdge}. Wider still, and `
            + `starting to read as a square rather than a sheet` }; })(),
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
