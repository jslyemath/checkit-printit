/* Gear candidates for the Settings glyph.

   The one in the app is two circles and eight radial sticks: a
   picture of a gear's idea rather than a gear. He wants the real
   toothed silhouette.

   Generated geometry, not drawn by hand. Each is a closed path --
   flank, tip arc, flank, valley arc, eight (or six, or seven) times
   -- plus a hub circle. The numbers that matter are printed under
   each one: at the rail's 21px the stroke is 1.714 user units, so a
   valley narrower than that has no white left in it at all and the
   teeth merge into a plain circle. That is what the old comment in
   app.js meant, and it is why the fix is a bigger root circle rather
   than fewer teeth.

   Sizes shown are the three the app actually uses: 13 (the band
   toggle), 18 (the default) and 21 (the rail), with 32 and 64 beside
   them so the shape can be judged apart from the question of whether
   it survives. Judge at 21.

   **a8 was chosen and built.** Eight teeth, trapezoidal, hub a
   third of the diameter -- the closest of the five to the gear he
   pointed at. The others are kept because a decision whose
   alternatives have been thrown away is a decision that gets
   reopened.

   A screenshot at 21px is not the test. The pane downscales, and
   `zoom` on these tools crops rather than magnifies, so both show a
   blur that proves nothing either way. What settled it was
   rasterising each candidate into a canvas at the real device size
   -- 21 CSS px times a 1.5 device pixel ratio, so 32 real pixels --
   and then blowing *that* up with `imageSmoothingEnabled = false`.
   That shows the actual pixels the screen will light. */
(function () {
  const CANDS = [
    { key: "a8", hub: 3.6, n: 8,
      note: "1.4 white between teeth, 2.4 deep",
      d: "M10.39 4.06L10.36 1.63A10.5 10.5 0 0 1 13.64 1.63L13.61 4.06A8.1 8.1 0 0 1 16.47 5.25L18.17 3.51A10.5 10.5 0 0 1 20.49 5.83L18.75 7.53A8.1 8.1 0 0 1 19.94 10.39L22.37 10.36A10.5 10.5 0 0 1 22.37 13.64L19.94 13.61A8.1 8.1 0 0 1 18.75 16.47L20.49 18.17A10.5 10.5 0 0 1 18.17 20.49L16.47 18.75A8.1 8.1 0 0 1 13.61 19.94L13.64 22.37A10.5 10.5 0 0 1 10.36 22.37L10.39 19.94A8.1 8.1 0 0 1 7.53 18.75L5.83 20.49A10.5 10.5 0 0 1 3.51 18.17L5.25 16.47A8.1 8.1 0 0 1 4.06 13.61L1.63 13.64A10.5 10.5 0 0 1 1.63 10.36L4.06 10.39A8.1 8.1 0 0 1 5.25 7.53L3.51 5.83A10.5 10.5 0 0 1 5.83 3.51L7.53 5.25A8.1 8.1 0 0 1 10.39 4.06Z" },
    { key: "b8", hub: 3.7, n: 8,
      note: "1.15 white between teeth, 2.3 deep",
      d: "M10.23 3.99L10.18 1.66A10.5 10.5 0 0 1 13.82 1.66L13.77 3.99A8.2 8.2 0 0 1 16.41 5.08L18.02 3.40A10.5 10.5 0 0 1 20.60 5.98L18.92 7.59A8.2 8.2 0 0 1 20.01 10.23L22.34 10.18A10.5 10.5 0 0 1 22.34 13.82L20.01 13.77A8.2 8.2 0 0 1 18.92 16.41L20.60 18.02A10.5 10.5 0 0 1 18.02 20.60L16.41 18.92A8.2 8.2 0 0 1 13.77 20.01L13.82 22.34A10.5 10.5 0 0 1 10.18 22.34L10.23 20.01A8.2 8.2 0 0 1 7.59 18.92L5.98 20.60A10.5 10.5 0 0 1 3.40 18.02L5.08 16.41A8.2 8.2 0 0 1 3.99 13.77L1.66 13.82A10.5 10.5 0 0 1 1.66 10.18L3.99 10.23A8.2 8.2 0 0 1 5.08 7.59L3.40 5.98A10.5 10.5 0 0 1 5.98 3.40L7.59 5.08A8.2 8.2 0 0 1 10.23 3.99Z" },
    { key: "c6", hub: 3.6, n: 6,
      note: "1.87 white between teeth, 2.6 deep",
      d: "M9.69 4.45L9.64 1.77A10.5 10.5 0 0 1 14.36 1.77L14.31 4.45A7.9 7.9 0 0 1 17.39 6.22L19.68 4.84A10.5 10.5 0 0 1 22.04 8.93L19.70 10.22A7.9 7.9 0 0 1 19.70 13.78L22.04 15.07A10.5 10.5 0 0 1 19.68 19.16L17.39 17.78A7.9 7.9 0 0 1 14.31 19.55L14.36 22.23A10.5 10.5 0 0 1 9.64 22.23L9.69 19.55A7.9 7.9 0 0 1 6.61 17.78L4.32 19.16A10.5 10.5 0 0 1 1.96 15.07L4.30 13.78A7.9 7.9 0 0 1 4.30 10.22L1.96 8.93A10.5 10.5 0 0 1 4.32 4.84L6.61 6.22A7.9 7.9 0 0 1 9.69 4.45Z" },
    { key: "d7", hub: 3.7, n: 7,
      note: "1.6 white between teeth, 2.4 deep",
      d: "M10.04 4.14L10.00 1.69A10.5 10.5 0 0 1 14.00 1.69L13.96 4.14A8.1 8.1 0 0 1 16.92 5.57L18.81 4.01A10.5 10.5 0 0 1 21.31 7.14L19.37 8.63A8.1 8.1 0 0 1 20.10 11.84L22.49 12.34A10.5 10.5 0 0 1 21.60 16.25L19.23 15.66A8.1 8.1 0 0 1 17.18 18.23L18.28 20.42A10.5 10.5 0 0 1 14.67 22.16L13.64 19.93A8.1 8.1 0 0 1 10.36 19.93L9.33 22.16A10.5 10.5 0 0 1 5.72 20.42L6.82 18.23A8.1 8.1 0 0 1 4.77 15.66L2.40 16.25A10.5 10.5 0 0 1 1.51 12.34L3.90 11.84A8.1 8.1 0 0 1 4.63 8.63L2.69 7.14A10.5 10.5 0 0 1 5.19 4.01L7.08 5.57A8.1 8.1 0 0 1 10.04 4.14Z" },
    { key: "e8", hub: 3.4, n: 8,
      note: "1.14 white between teeth, 2.8 deep",
      d: "M10.38 4.37L10.25 1.55A10.6 10.6 0 0 1 13.75 1.55L13.62 4.37A7.8 7.8 0 0 1 16.25 5.46L18.16 3.37A10.6 10.6 0 0 1 20.63 5.84L18.54 7.75A7.8 7.8 0 0 1 19.63 10.38L22.45 10.25A10.6 10.6 0 0 1 22.45 13.75L19.63 13.62A7.8 7.8 0 0 1 18.54 16.25L20.63 18.16A10.6 10.6 0 0 1 18.16 20.63L16.25 18.54A7.8 7.8 0 0 1 13.62 19.63L13.75 22.45A10.6 10.6 0 0 1 10.25 22.45L10.38 19.63A7.8 7.8 0 0 1 7.75 18.54L5.84 20.63A10.6 10.6 0 0 1 3.37 18.16L5.46 16.25A7.8 7.8 0 0 1 4.37 13.62L1.55 13.75A10.6 10.6 0 0 1 1.55 10.25L4.37 10.38A7.8 7.8 0 0 1 5.46 7.75L3.37 5.84A10.6 10.6 0 0 1 5.84 3.37L7.75 5.46A7.8 7.8 0 0 1 10.38 4.37Z" },
  ];

  const CURRENT = { key: "now", hub: 3.1, n: 8,
    note: "what is in the app today",
    parts: [{ o: [12, 12, 3.1] }, { o: [12, 12, 6.4] },
            { d: "M12 2.6v2.6M12 18.8v2.6M21.4 12h-2.6M5.2 12H2.6"
                 + "M18.6 5.4l-1.8 1.8M7.2 16.8l-1.8 1.8"
                 + "M18.6 18.6l-1.8-1.8M7.2 7.2L5.4 5.4" }] };

  const NS = "http://www.w3.org/2000/svg";

  function draw(cand, px) {
    const svg = document.createElementNS(NS, "svg");
    svg.setAttribute("viewBox", "0 0 24 24");
    svg.setAttribute("class", "glyph");
    svg.style.width = px + "px";
    svg.style.height = px + "px";
    svg.style.setProperty("--glyph-size", px);
    const parts = cand.parts
      || [{ d: cand.d }, { o: [12, 12, cand.hub] }];
    for (const p of parts) {
      if (p.o) {
        const c = document.createElementNS(NS, "circle");
        c.setAttribute("cx", p.o[0]);
        c.setAttribute("cy", p.o[1]);
        c.setAttribute("r", p.o[2]);
        svg.appendChild(c);
      } else {
        const path = document.createElementNS(NS, "path");
        path.setAttribute("d", p.d);
        svg.appendChild(path);
      }
    }
    return svg;
  }

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  }

  const CSS = `
    main { overflow-y: auto; }
    .gk { padding: var(--s5); max-width: 980px; }
    .gk h2 { margin: 0 0 var(--s2); }
    .gk p.lede { color: var(--ink-2); margin: 0 0 var(--s5);
                 max-width: 62ch; }
    .gk-row { display: flex; align-items: center; gap: var(--s5);
              padding: var(--s3) 0; border-top: 1px solid var(--line); }
    .gk-name { width: 5.5rem; flex: 0 0 auto;
               font: 600 var(--t-sm)/1.2 var(--font); }
    .gk-note { color: var(--muted); font-size: var(--t-sm);
               margin-top: 2px; font-weight: 400; }
    .gk-sizes { display: flex; align-items: center; gap: var(--s5); }
    .gk-one { display: flex; flex-direction: column; align-items: center;
              gap: 4px; }
    .gk-one span { font-size: 11px; color: var(--muted); }
    .gk-rail { margin-left: auto; display: flex; align-items: center;
               gap: var(--s2); padding: 7px 12px;
               background: var(--surface-2); border-radius: var(--r-md);
               font: 500 var(--t-base)/1 var(--font); }
  `;

  function render() {
    const main = document.querySelector("main");
    main.innerHTML = "";
    const style = el("style");
    style.textContent = CSS;
    main.appendChild(style);

    const wrap = el("div", "gk");
    wrap.appendChild(el("h2", null, "The Settings gear"));
    wrap.appendChild(el("p", "lede",
      "Judge these at 21, which is the size the rail draws. The "
      + "others are there to separate 'is this a good shape' from "
      + "'does the shape survive'. The last column puts it where it "
      + "will actually live, beside its label."));

    for (const cand of [CURRENT, ...CANDS]) {
      const row = el("div", "gk-row");
      const name = el("div", "gk-name");
      name.appendChild(document.createTextNode(cand.key));
      name.appendChild(el("div", "gk-note", cand.note));
      row.appendChild(name);

      const sizes = el("div", "gk-sizes");
      for (const px of [13, 18, 21, 32, 64]) {
        const one = el("div", "gk-one");
        one.appendChild(draw(cand, px));
        one.appendChild(el("span", null, px));
        sizes.appendChild(one);
      }
      row.appendChild(sizes);

      const rail = el("div", "gk-rail");
      rail.appendChild(draw(cand, 21));
      rail.appendChild(el("span", null, "Settings"));
      row.appendChild(rail);

      wrap.appendChild(row);
    }
    main.appendChild(wrap);
  }

  render();
})();
