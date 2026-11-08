/* Three fly-out panel layouts for the Progress drill-in.
 *
 * All three are timelines, because the shape of a student's attempts
 * -- cross, query, tick -- is the thing he opens this to see, and the
 * only one of the earlier three layouts that showed it.
 *
 * A panel rather than a modal: the grid stays visible behind it and
 * the cell he came from stays lit, so working down a column after a
 * scan does not mean closing and reopening. That costs width -- about
 * 400px against the dialog's 620 -- which is most of what separates
 * these three from each other.
 *
 * What is deliberately not here, because he asked for it gone:
 *
 *   * the version letter. It identifies a paper among the versions of
 *     one run, and in a list of one student's own papers there is
 *     nothing to tell apart.
 *   * what the scanner called it. The final mark is the answer; the
 *     reading is how it was arrived at, and belongs where a
 *     disagreement is being looked into, not in every row forever.
 *
 * See PRINT_TOOL_DESIGN.md 17. Run it the way tools/mockups/README.md
 * says.
 */
(function () {

const PAPERS = [
  { date: "Tue 15 Sep", run: "Checkpoint 1", no: 1, seed: 998,
    out: "failed", scan: true },
  { date: "Tue 29 Sep", run: "Redo 1", no: 2, seed: 947,
    out: "queried", scan: true },
  { date: "Tue 13 Oct", run: "Checkpoint 2", no: 3, seed: 484,
    out: "passed", scan: true },
  { date: "Tue 27 Oct", run: "Redo 2", no: 4, seed: 512,
    out: "", scan: false },
];

const MARK = { passed: "pass", failed: "fail", queried: "query",
               absent: "absent" };
const TONE = { passed: "passed", failed: "none-passed",
               queried: "query" };

function el(tag, cls, txt) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt !== undefined) n.textContent = txt;
  return n;
}

/* The four-way mark track, as the Scans tab already draws it. Same
   control in both places or they drift. */
function picks(on) {
  const d = el("div", "review-picks");
  for (const id of ["passed", "queried", "failed", "absent"]) {
    const b = el("button", "review-pick" + (id === on ? " on" : ""));
    b.type = "button";
    b.appendChild(icon(MARK[id]));
    d.appendChild(b);
  }
  return d;
}

/* A stand-in for the scanned page. The real one is a render of the
   whole sheet -- which is the point of it: he is looking for how the
   working changed, not whether a box is ticked. */
const RULED = [70, 55, 80, 40, 65, 30];

function paperThumb(has, size) {
  const t = el("div", "mk-thumb" + (size ? " mk-thumb-" + size : "")
                      + (has ? "" : " mk-thumb-none"));
  if (!has) return t;
  const rows = size === "lg" ? RULED.concat(RULED, RULED) : RULED;
  for (const w of rows) {
    const line = el("div", "mk-thumb-line");
    line.style.width = w + "%";
    t.appendChild(line);
  }
  return t;
}

/* The paper is a picture of the paper, never the words "see the
   paper". A control standing in for a thing should look like the
   thing, and a phrase where a control belongs is the tic section 13
   bans. The small one is the affordance; clicking it gives the big
   one.

   Where a run was never scanned there is nothing to click, so the
   frame is empty and dashed and is not a button. That is the layout
   saying it rather than a sentence saying it -- and it is a frame
   beside a photograph, not a glyph in a grid cell, so it does not
   collide with "never a box or a dashed box". */
function paperButton(paper, size) {
  if (!paper.scan) {
    const none = paperThumb(false, size);
    none.title = "Never scanned";
    return none;
  }
  const b = el("button", "mk-paper");
  b.type = "button";
  b.title = "See the whole page";
  b.appendChild(paperThumb(true, size));
  b.addEventListener("click", () => openPaper(paper));
  return b;
}

/* Clicking the small one gives the big one. In the built version this
   is the scan itself at a readable size; here it is the same stand-in,
   larger. */
function openPaper(paper) {
  const back = el("div", "mk-lightbox");
  const sheet = el("div", "mk-sheet");
  const bar = el("div", "mk-sheetbar");
  const shut = el("button", "iconbtn tiny");
  shut.type = "button";
  shut.appendChild(icon("collapse"));
  shut.title = "Back to the timeline";
  bar.append(el("span", "mk-sheetwho", paper.date + " · " + paper.run),
             el("span", "spacer"), shut);
  sheet.append(bar, paperThumb(true, "lg"));
  back.appendChild(sheet);
  const close = () => back.remove();
  shut.addEventListener("click", close);
  back.addEventListener("click", e => { if (e.target === back) close(); });
  document.body.appendChild(back);
}

/* The header all three share. Name, skill, section, and the verdict
   in the grid's own vocabulary -- a fraction when more than one pass
   is needed, a tick when it is done. */
function head(onClose) {
  const h = el("div", "mk-head");
  const top = el("div", "mk-headtop");
  const who = el("div", "mk-who");
  who.append(el("div", "mk-name", "Hal Half"),
             el("div", "mk-where", "820"));
  const shut = el("button", "iconbtn tiny");
  shut.type = "button";
  shut.appendChild(icon("forward"));
  shut.title = "Close";
  top.append(who, el("span", "spacer"), shut);

  const line = el("div", "mk-skill");
  const slug = el("span", "mk-slug", "F2");
  const verdict = el("span", "mk-verdict");
  verdict.append(el("span", "cellcount", "1/2"), el("span", "", "passed"));
  line.append(slug, el("span", "mk-title", "Fraction Models"),
              el("span", "spacer"), verdict);
  h.append(top, line);
  return h;
}

function nav() {
  const f = el("div", "mk-foot");
  const prev = el("button", "iconbtn tiny");
  prev.type = "button";
  prev.appendChild(icon("back"));
  prev.title = "The student above";
  const next = el("button", "iconbtn tiny");
  next.type = "button";
  next.appendChild(icon("forward"));
  next.title = "The student below";
  f.append(el("span", "mk-footsay", "Hal Half"),
           el("span", "spacer"), prev, next);
  return f;
}

/* ---- A: a node, and a card beside it ----------------------------- */
function optionA() {
  const p = el("div", "mk-panel");
  p.append(head());
  const line = el("div", "mk-line");
  for (const paper of PAPERS) {
    const step = el("div", "mk-step");
    const node = el("div", "mk-node " + (TONE[paper.out] || "unread"));
    if (paper.out) node.appendChild(icon(MARK[paper.out]));
    const body = el("div", "mk-body");
    body.append(el("div", "mk-date", paper.date));
    const run = el("div", "mk-run");
    run.append(el("span", "", paper.run),
               el("span", "mk-no", "#" + paper.no));
    body.append(run);
    const seed = el("div", "mk-fact");
    seed.append(el("div", "mk-key", "seed"), el("div", "mk-val", paper.seed));
    body.append(seed, picks(paper.out));
    const card = el("div", "mk-card");
    card.append(body, paperButton(paper));
    step.append(node, card);
    line.appendChild(step);
  }
  p.append(line, nav());
  return p;
}

/* ---- B: one line a paper, the tightest it goes ------------------- */
function optionB() {
  const p = el("div", "mk-panel");
  p.append(head());
  const line = el("div", "mk-line mk-tight");
  for (const paper of PAPERS) {
    const step = el("div", "mk-step");
    const node = el("div", "mk-node small " + (TONE[paper.out] || "unread"));
    if (paper.out) node.appendChild(icon(MARK[paper.out]));
    const body = el("div", "mk-body");
    const top = el("div", "mk-row1");
    top.append(el("span", "mk-date", paper.date),
               el("span", "spacer"),
               el("span", "mk-seed", String(paper.seed)));
    const bot = el("div", "mk-row2");
    const run = el("span", "mk-run");
    run.append(el("span", "", paper.run),
               el("span", "mk-no", "#" + paper.no));
    bot.append(run, el("span", "spacer"));
    bot.append(paperButton(paper, "sm"), picks(paper.out));
    body.append(top, bot);
    step.append(node, body);
    line.appendChild(step);
  }
  p.append(line, nav());
  return p;
}

/* ---- C: the work itself, down the timeline ----------------------- */
function optionC() {
  const p = el("div", "mk-panel");
  p.append(head());
  const line = el("div", "mk-line mk-withpaper");
  for (const paper of PAPERS) {
    const step = el("div", "mk-step");
    const shot = el("div", "mk-shot");
    shot.append(paperButton(paper));
    if (paper.out) {
      const badge = el("div", "mk-badge " + TONE[paper.out]);
      badge.appendChild(icon(MARK[paper.out]));
      shot.append(badge);
    }
    const body = el("div", "mk-body");
    body.append(el("div", "mk-date", paper.date));
    const run = el("div", "mk-run");
    run.append(el("span", "", paper.run),
               el("span", "mk-no", "#" + paper.no));
    body.append(run);
    const seed = el("div", "mk-fact");
    seed.append(el("div", "mk-key", "seed"), el("div", "mk-val", paper.seed));
    body.append(seed, picks(paper.out));
    step.append(shot, body);
    line.appendChild(step);
  }
  p.append(line, nav());
  return p;
}

const CSS = `
/* Harness, not design. The app's <main> is a fixed-height clipper --
   every real view brings its own scroller -- and three panels stacked
   are taller than it, so without this the page simply cannot be
   scrolled. */
main { overflow-y: auto; }

.mk-wrap { display: flex; gap: var(--s5); align-items: flex-start;
           flex-wrap: wrap; }
.mk-col { flex: 0 0 auto; }
.mk-cap { font-size: var(--t-sm); color: var(--accent); font-weight: 600;
          margin-bottom: var(--s2); letter-spacing: .04em; }
.mk-note { font-size: var(--t-xs); color: var(--muted); max-width: 400px;
           margin-top: var(--s2); }

/* The panel itself: flush to the right edge, full height, one border
   against the grid behind it. */
.mk-panel { width: 400px; background: var(--surface-1);
            border: 1px solid var(--line); border-radius: var(--r-lg);
            display: flex; flex-direction: column; overflow: hidden; }
.mk-head { padding: var(--s3) var(--s4); border-bottom: 1px solid var(--line); }
.mk-headtop { display: flex; align-items: flex-start; gap: var(--s2); }
.mk-name { font-size: var(--t-lg); color: var(--ink); }
.mk-where { font-size: var(--t-xs); color: var(--muted); }
.mk-skill { display: flex; align-items: baseline; gap: var(--s2);
            margin-top: var(--s2); }
.mk-slug { font-size: var(--t-xs); color: var(--muted);
           border: 1px solid var(--line); border-radius: var(--r-pill);
           padding: 1px 8px; }
.mk-title { font-size: var(--t-sm); color: var(--muted);
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mk-verdict { display: flex; align-items: baseline; gap: var(--s1);
              font-size: var(--t-xs); color: var(--muted); }

.mk-line { padding: var(--s4); flex: 1; }
.mk-step { display: grid; grid-template-columns: 26px 1fr; gap: var(--s3);
           position: relative; padding-bottom: var(--s4); }
.mk-line.mk-tight .mk-step { grid-template-columns: 18px 1fr;
                             padding-bottom: var(--s3); }
.mk-line.mk-withpaper .mk-step { grid-template-columns: 58px 1fr; }
.mk-step:not(:last-child)::before { content: ""; position: absolute;
  left: 13px; top: 26px; bottom: 0; width: 2px; background: var(--line); }
.mk-line.mk-tight .mk-step:not(:last-child)::before { left: 9px; top: 18px; }
.mk-line.mk-withpaper .mk-step:not(:last-child)::before { left: 28px;
  top: 76px; }

.mk-node { width: 26px; height: 26px; border-radius: 50%; display: flex;
           align-items: center; justify-content: center;
           border: 2px solid var(--line); background: var(--surface-1);
           position: relative; z-index: 1; }
.mk-node.small { width: 18px; height: 18px; border-width: 1.5px; }
.mk-node svg { width: 14px; height: 14px; --glyph-size: 14; }
.mk-node.small svg { width: 10px; height: 10px; --glyph-size: 10; }
.mk-node.passed { border-color: var(--accent); color: var(--accent); }
.mk-node.none-passed { border-color: var(--bad); color: var(--bad); }
.mk-node.query { border-color: var(--warn); color: var(--warn); }
.mk-node.unread { border-style: dashed; }

.mk-date { font-size: var(--t-base); color: var(--ink); }
.mk-run { font-size: var(--t-sm); color: var(--muted);
          display: flex; align-items: baseline; gap: var(--s2); }
.mk-no { font-variant-numeric: tabular-nums; font-size: var(--t-xs); }
.mk-key { font-size: 10px; text-transform: uppercase; letter-spacing: .06em;
          color: var(--muted); }
.mk-val { font-size: var(--t-sm); color: var(--ink);
          font-variant-numeric: tabular-nums; }
.mk-fact { margin: var(--s2) 0; }
.mk-card { display: flex; align-items: flex-start; gap: var(--s3); }
.mk-card .mk-body { flex: 1; min-width: 0; }
.mk-row1, .mk-row2 { display: flex; align-items: center; gap: var(--s2); }
.mk-row2 { margin-top: 2px; }
.mk-seed { font-size: var(--t-xs); color: var(--muted);
           font-variant-numeric: tabular-nums; }

/* A page, small. Six ruled lines standing in for the student's
   working, which is what the real one shows. */
.mk-shot { position: relative; width: 58px; }
.mk-thumb { width: 54px; height: 70px; border: 1px solid var(--line);
            border-radius: 2px; background: var(--surface-2);
            padding: 6px 5px; display: flex; flex-direction: column;
            gap: 5px; }
.mk-thumb-line { height: 2px; background: var(--line-strong); opacity: .5; }
.mk-thumb-none { border-style: dashed; opacity: .55; }

/* The picture is the control. It gets no chrome of its own -- a
   border round a border is the thing the panel is trying to avoid --
   so hover and focus light the page's own edge instead. */
.mk-paper { background: none; border: 0; padding: 0; cursor: pointer;
            display: block; }
.mk-paper:hover .mk-thumb { border-color: var(--accent); }
.mk-paper:focus-visible { outline: 2px solid var(--accent);
                          outline-offset: 2px; border-radius: 3px; }
.mk-thumb-sm { width: 26px; height: 34px; padding: 4px 3px; gap: 2px; }
.mk-thumb-sm .mk-thumb-line { height: 1px; }
.mk-thumb-lg { width: 300px; height: 392px; padding: 22px 18px; gap: 14px;
               background: var(--surface-1); }
.mk-thumb-lg .mk-thumb-line { height: 3px; }

.mk-lightbox { position: fixed; inset: 0; z-index: 50; display: flex;
               align-items: center; justify-content: center;
               background: rgba(0, 0, 0, .45); }
.mk-sheet { background: var(--surface-2); border: 1px solid var(--line);
            border-radius: var(--r-lg); padding: var(--s3);
            display: flex; flex-direction: column; gap: var(--s2); }
.mk-sheetbar { display: flex; align-items: center; gap: var(--s2); }
.mk-sheetwho { font-size: var(--t-sm); color: var(--muted); }
.mk-badge { position: absolute; left: 40px; top: 56px; width: 20px;
            height: 20px; border-radius: 50%; display: flex;
            align-items: center; justify-content: center;
            background: var(--surface-1); border: 1.5px solid var(--line); }
.mk-badge svg { width: 11px; height: 11px; --glyph-size: 11; }
.mk-badge.passed { border-color: var(--accent); color: var(--accent); }
.mk-badge.none-passed { border-color: var(--bad); color: var(--bad); }
.mk-badge.query { border-color: var(--warn); color: var(--warn); }

.mk-foot { display: flex; align-items: center; gap: var(--s2);
           padding: var(--s2) var(--s4); border-top: 1px solid var(--line);
           background: var(--surface-2); }
.mk-footsay { font-size: var(--t-xs); color: var(--muted); }
.mk-panel .review-picks { margin-top: var(--s1); }
`;

const NOTES = {
  A: "Roomiest. The page sits to the side of the card at a size you "
     + "can tell apart but not read; click it for the big one. Four "
     + "attempts fill the panel.",
  B: "Tightest. Two lines a paper, the seed demoted to the corner, "
     + "the page shrunk to a stamp beside the marks. Fits eight or "
     + "nine attempts without scrolling.",
  C: "Shows the work. Each step carries the page itself with the mark "
     + "as a badge, so the progression is visible without opening "
     + "anything -- which is the thing he says the paper is for.",
};

const view = document.getElementById("view-progress")
  || document.querySelector(".view");
document.querySelectorAll(".view").forEach(v => { v.hidden = true; });
view.hidden = false;
view.innerHTML = "";
view.append(el("h2", "pagename", "Drill-in — three fly-out panels"));
const wrap = el("div", "mk-wrap");
for (const [cap, build] of [["A · NODE AND CARD", optionA],
                            ["B · TIGHT", optionB],
                            ["C · THE WORK ITSELF", optionC]]) {
  const col = el("div", "mk-col");
  col.append(el("div", "mk-cap", cap), build(),
             el("div", "mk-note", NOTES[cap[0]]));
  wrap.appendChild(col);
}
view.append(wrap);
const st = document.createElement("style");
st.textContent = CSS;
document.head.appendChild(st);

})();
