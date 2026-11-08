/* The chosen drill-in -- C, the work itself -- refined, with three
 * headers to choose between.
 *
 * drillin.js held the three-way comparison and stays as it is. This
 * is what was chosen, with four changes he asked for:
 *
 *   * no seed. It identifies which exercise was drawn, which is a
 *     thing to look up when a question is wrong, not a thing to read
 *     down a timeline.
 *   * no #1, #2. The position in the list already says which attempt
 *     this is -- that is what a timeline is for -- so the number was
 *     counting out loud what the layout had already said.
 *   * the marks become the track from the Scans tab, one pill with
 *     the verdict filled in place, not four separate buttons.
 *   * with the seed and the number gone, the track comes up under
 *     the date and the run with nothing between.
 *
 * On the track: the Scans table drops "did not sit it" for a paper
 * that came back, because a sheet that came back was sat whatever is
 * on it (app.js, matchedMarkCell). The same holds here, so the
 * never-scanned attempt is the only one with a fourth stop.
 *
 * The track's styling currently lives under `table.matched` in
 * style.css. Building this for real means lifting it out to a class
 * of its own -- the mockup copies it, which is the second copy this
 * file is allowed and the built version is not.
 *
 * See PRINT_TOOL_DESIGN.md 17. Run it the way tools/mockups/README.md
 * says.
 */
(function () {

const PAPERS = [
  { date: "Tue 15 Sep", run: "Checkpoint 1", out: "failed", scan: true },
  { date: "Tue 29 Sep", run: "Redo 1", out: "queried", scan: true },
  { date: "Tue 13 Oct", run: "Checkpoint 2", out: "passed", scan: true },
  { date: "Tue 27 Oct", run: "Redo 2", out: "", scan: false },
];

const MARK = { passed: "pass", failed: "fail", queried: "query",
               absent: "absent" };
const TONE = { passed: "passed", failed: "none-passed",
               queried: "query" };

/* The order he reads in, which is what makes a track honest here
   rather than an arbitrary row of buttons. */
const ORDER = ["passed", "queried", "failed"];

function el(tag, cls, txt) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (txt !== undefined) n.textContent = txt;
  return n;
}

/* One pill with the verdict filled in place. "Did not sit it" is only
   an offer for a paper that never came back. */
function track(paper) {
  const d = el("div", "review-picks");
  d.setAttribute("role", "radiogroup");
  const stops = paper.scan ? ORDER : ORDER.concat("absent");
  for (const id of stops) {
    const b = el("button", "review-pick" + (id === paper.out ? " on" : ""));
    b.type = "button";
    b.appendChild(icon(MARK[id]));
    b.setAttribute("role", "radio");
    b.setAttribute("aria-checked", id === paper.out ? "true" : "false");
    d.appendChild(b);
  }
  return d;
}

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

/* The page is a picture of the page, never the words "see the page".
   Where nothing was scanned there is nothing to click, and the empty
   frame says so without a sentence. */
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

function chevron(title) {
  const b = el("button", "iconbtn tiny");
  b.type = "button";
  b.appendChild(icon("forward"));
  b.title = title;
  return b;
}

function slug() {
  return el("span", "mk-slug", "F2");
}

/* ---- H1: tightened ----------------------------------------------
   The shape that was there, with the section brought up onto the
   name's line instead of orphaned under it. One line shorter and
   nothing moved. */
function headTight() {
  const h = el("div", "mk-head");
  const top = el("div", "mk-headtop");
  top.append(el("span", "mk-name", "Hal Half"),
             el("span", "mk-where", "820"),
             el("span", "spacer"), chevron("Close"));
  const line = el("div", "mk-skill");
  const verdict = el("span", "mk-verdict");
  verdict.append(el("span", "mk-vnum", "1/2"), el("span", "", "passed"));
  line.append(slug(), el("span", "mk-title", "Fraction Models"),
              el("span", "spacer"), verdict);
  h.append(top, line);
  return h;
}

/* ---- H2: the verdict as a stat ----------------------------------
   The empty right-hand side was the awkward part, so the answer goes
   in it. Identity on the left over two lines, the cell's own verdict
   on the right at the size of a thing you read first. */
function headStat() {
  const h = el("div", "mk-head mk-head-stat");
  const id = el("div", "mk-id");
  const nameline = el("div", "mk-headtop");
  nameline.append(el("span", "mk-name", "Hal Half"),
                  el("span", "mk-where", "820"));
  const line = el("div", "mk-skill");
  line.append(slug(), el("span", "mk-title", "Fraction Models"));
  id.append(nameline, line);
  const stat = el("div", "mk-stat");
  stat.append(el("div", "mk-statnum", "1/2"),
              el("div", "mk-statsay", "passed"));
  h.append(id, stat, chevron("Close"));
  return h;
}

/* ---- H3: a strip ------------------------------------------------
   Who it is, then a tinted strip carrying what the cell was. The
   strip reads as context rather than as a second title, which is the
   job the skill line is actually doing. */
function headStrip() {
  const h = el("div", "mk-head mk-head-strip");
  const top = el("div", "mk-headtop");
  top.append(el("span", "mk-name", "Hal Half"),
             el("span", "mk-where", "820"),
             el("span", "spacer"), chevron("Close"));
  const strip = el("div", "mk-strip");
  const verdict = el("span", "mk-verdict");
  verdict.append(el("span", "mk-vnum", "1/2"), el("span", "", "passed"));
  strip.append(slug(), el("span", "mk-title", "Fraction Models"),
               el("span", "spacer"), verdict);
  h.append(top, strip);
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

function panel(headFn) {
  const p = el("div", "mk-panel");
  p.append(headFn());
  const line = el("div", "mk-line");
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
    body.append(el("div", "mk-date", paper.date),
                el("div", "mk-run", paper.run),
                track(paper));
    step.append(shot, body);
    line.appendChild(step);
  }
  p.append(line, nav());
  return p;
}

const CSS = `
/* Harness, not design. The app's <main> is a fixed-height clipper --
   every real view brings its own scroller -- and three panels stacked
   are taller than it. */
main { overflow-y: auto; }

.mk-wrap { display: flex; gap: var(--s5); align-items: flex-start;
           flex-wrap: wrap; }
.mk-col { flex: 0 0 auto; }
.mk-cap { font-size: var(--t-sm); color: var(--accent); font-weight: 600;
          margin-bottom: var(--s2); letter-spacing: .04em; }
.mk-note { font-size: var(--t-xs); color: var(--muted); max-width: 400px;
           margin-top: var(--s2); }

.mk-panel { width: 400px; background: var(--surface-1);
            border: 1px solid var(--line); border-radius: var(--r-lg);
            display: flex; flex-direction: column; overflow: hidden; }

/* ---- the three headers ---- */
.mk-head { padding: var(--s3) var(--s4);
           border-bottom: 1px solid var(--line); }
.mk-headtop { display: flex; align-items: baseline; gap: var(--s2); }
.mk-name { font-size: var(--t-lg); color: var(--ink); }
.mk-where { font-size: var(--t-xs); color: var(--muted); }
.mk-skill { display: flex; align-items: baseline; gap: var(--s2);
            margin-top: var(--s1); }
.mk-slug { font-size: var(--t-xs); color: var(--muted);
           border: 1px solid var(--line); border-radius: var(--r-pill);
           padding: 1px 8px; }
.mk-title { font-size: var(--t-sm); color: var(--muted);
            overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.mk-verdict { display: flex; align-items: baseline; gap: var(--s1);
              font-size: var(--t-xs); color: var(--muted); }
.mk-vnum { font-variant-numeric: tabular-nums; color: var(--ink); }

.mk-head-stat { display: flex; align-items: flex-start; gap: var(--s3); }
.mk-head-stat .mk-id { flex: 1; min-width: 0; }
.mk-stat { text-align: right; }
.mk-statnum { font-size: var(--t-lg); color: var(--ink);
              font-variant-numeric: tabular-nums; line-height: 1.1; }
.mk-statsay { font-size: var(--t-xs); color: var(--muted); }

.mk-head-strip { padding: 0; }
.mk-head-strip .mk-headtop { padding: var(--s3) var(--s4) var(--s2); }
.mk-strip { display: flex; align-items: baseline; gap: var(--s2);
            padding: var(--s2) var(--s4); background: var(--surface-2);
            border-top: 1px solid var(--line); }

/* ---- the timeline ---- */
.mk-line { padding: var(--s4); flex: 1; }
.mk-step { display: grid; grid-template-columns: 58px 1fr; gap: var(--s3);
           position: relative; padding-bottom: var(--s4); }
/* The page now fills the row, so the rail is the stub between one
   page and the next rather than a line the pages hang off. The
   stacked pages are the spine. */
.mk-step:not(:last-child)::before { content: ""; position: absolute;
  left: 28px; top: auto; bottom: 0; height: var(--s4); width: 2px;
  background: var(--line); }

.mk-date { font-size: var(--t-base); color: var(--ink); }
.mk-run { font-size: var(--t-sm); color: var(--muted); }

/* The page, small. Six ruled lines standing in for the working.

   Its height is the row's height, not a number: a grid item stretches
   by default, so the page ends exactly where the track ends. A page
   is about 0.71 as wide as it is tall and the row comes out near
   that, so it keeps looking like a page without being told to. */
.mk-shot { position: relative; width: 58px; height: 100%; }
.mk-thumb { width: 54px; height: 100%; border: 1px solid var(--line);
            border-radius: 2px; background: var(--surface-2);
            padding: 6px 5px; display: flex; flex-direction: column;
            gap: 5px; overflow: hidden; }
.mk-thumb-line { height: 2px; background: var(--line-strong); opacity: .5; }
.mk-thumb-none { border-style: dashed; opacity: .55; }
.mk-paper { background: none; border: 0; padding: 0; cursor: pointer;
            display: block; height: 100%; }
.mk-paper:hover .mk-thumb { border-color: var(--accent); }
.mk-paper:focus-visible { outline: 2px solid var(--accent);
                          outline-offset: 2px; border-radius: 3px; }
.mk-thumb-lg { width: 300px; height: 392px; padding: 22px 18px; gap: 14px;
               background: var(--surface-1); }
.mk-thumb-lg .mk-thumb-line { height: 3px; }

.mk-badge { position: absolute; left: 38px; bottom: -8px; width: 20px;
            height: 20px; border-radius: 50%; display: flex;
            align-items: center; justify-content: center;
            background: var(--surface-1); border: 1.5px solid var(--line); }
.mk-badge svg { width: 11px; height: 11px; --glyph-size: 11; }
.mk-badge.passed { border-color: var(--accent); color: var(--accent); }
.mk-badge.none-passed { border-color: var(--bad); color: var(--bad); }
.mk-badge.query { border-color: var(--warn); color: var(--warn); }

/* ---- the mark track ----
   The shape is \`table.matched\`'s in style.css; building this for real
   lifts it out into a class both places use.

   One size down from the table's. There it is the widest thing in a
   row of plain text and carries the column; here it sits under two
   short lines next to a small page, and at the table's size it was
   the loudest thing in the panel. 28x22 against 34x26. */
.mk-panel .review-picks { display: inline-flex; align-items: center;
  gap: 0; padding: 2px; border: 1px solid var(--line);
  border-radius: var(--r-pill); background: var(--surface-2);
  line-height: 1; margin-top: var(--s2); }
.mk-panel .review-pick { display: inline-flex; align-items: center;
  justify-content: center; width: 28px; height: 22px; padding: 0;
  border: 0; border-radius: var(--r-pill); background: transparent;
  color: var(--muted); cursor: pointer; }
.mk-panel .review-pick .glyph { --glyph-size: 14; width: 14px;
  height: 14px; }
.mk-panel .review-pick:hover { background: var(--surface-3);
  color: var(--ink); }
.mk-panel .review-pick.on { background: var(--accent);
  color: var(--on-accent, #0b1f14); }
.mk-panel .review-pick.on:hover { background: var(--accent); }

.mk-foot { display: flex; align-items: center; gap: var(--s2);
           padding: var(--s2) var(--s4); border-top: 1px solid var(--line);
           background: var(--surface-2); }
.mk-footsay { font-size: var(--t-xs); color: var(--muted); }

.mk-lightbox { position: fixed; inset: 0; z-index: 50; display: flex;
               align-items: center; justify-content: center;
               background: rgba(0, 0, 0, .45); }
.mk-sheet { background: var(--surface-2); border: 1px solid var(--line);
            border-radius: var(--r-lg); padding: var(--s3);
            display: flex; flex-direction: column; gap: var(--s2); }
.mk-sheetbar { display: flex; align-items: center; gap: var(--s2); }
.mk-sheetwho { font-size: var(--t-sm); color: var(--muted); }
`;

const HEADS = [
  ["H1 · TIGHTENED", headTight,
   "The shape that was there, with the section on the name's line "
   + "instead of orphaned beneath it. One line shorter; nothing moved. "
   + "The right-hand side is still mostly empty."],
  ["H2 · VERDICT AS A STAT", headStat,
   "The empty right-hand side was the awkward part, so the cell's own "
   + "verdict goes in it at the size of a thing you read first. "
   + "Shortest of the three, and the only one that uses the width."],
  ["H3 · A STRIP", headStrip,
   "Who it is, then a tinted strip carrying what the cell was. The "
   + "strip reads as context rather than a second title. Tallest of "
   + "the three, and the clearest about which is the subject."],
];

const view = document.getElementById("view-progress")
  || document.querySelector(".view");
document.querySelectorAll(".view").forEach(v => { v.hidden = true; });
view.hidden = false;
view.innerHTML = "";
view.append(el("h2", "pagename", "Drill-in C — three headers"));
const wrap = el("div", "mk-wrap");
for (const [cap, headFn, note] of HEADS) {
  const col = el("div", "mk-col");
  col.append(el("div", "mk-cap", cap), panel(headFn),
             el("div", "mk-note", note));
  wrap.appendChild(col);
}
view.append(wrap);
const st = document.createElement("style");
st.textContent = CSS;
document.head.appendChild(st);

})();
