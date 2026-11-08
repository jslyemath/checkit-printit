# Mockups

Design mockups, kept in the repository rather than in a scratch
directory because a mockup that cannot be found again is a
conversation repeated.

Each one draws itself **inside the running app**, using the app's own
`style.css`, its own tokens and its own `icon()`. That is the point:
a mockup drawn anywhere else is a picture of a thing that might not
be buildable, and the last round of symbol work was only settled
because the options were the real marks under the real stylesheet.

## Running one

Start a course the usual way, then:

```bash
cp tools/mockups/drillin.js src/checkit_printit/gui/static/_mock.js
```

Open the app, and in the browser console:

```js
const s = document.createElement("script");
s.src = "/_mock.js?" + Date.now();
document.body.appendChild(s);
```

It replaces whatever view is on screen with the mockups. Reload to
get the app back. **Delete `_mock.js` afterwards** -- it is not
product, and `git status` will say so if you forget:

```bash
rm src/checkit_printit/gui/static/_mock.js
```

Each file wraps itself in an IIFE. `app.js` and `seating.js` share
one global scope and a bare `const GLYPH` in a mockup collides with
the app's own -- which is how the first one failed to draw at all.

## What is here

| file | what it shows |
|---|---|
| `drillin.js` | three fly-out panel layouts for the Progress drill-in, all timelines. **C was chosen.** See `PRINT_TOOL_DESIGN.md` 17. |
| `drillin-c.js` | C refined -- no seed, no attempt number, the Scans track one size down -- with three headers. **H3, the strip, was chosen and built.** |
| `gear.js` | five toothed gears for the Settings glyph, against the two-circles-and-sticks one in the app, at 13/18/21/32/64 and in the rail. **a8 was chosen and built.** |
| `door.js` | seven `drop`/`restore` doors, at 13 and 18 and as a pair of real buttons. **The open-frame leaning leaf was chosen and built.** |

`drillin.js` is kept rather than deleted: it is the comparison the
choice was made from, and a decision whose alternatives have been
thrown away is a decision that gets reopened. Same for the four
gears nobody picked.

## Judging a glyph at its real size

A screenshot does not settle it. The browser pane downscales, and
`zoom` crops rather than magnifies, so both hand back a blur that
argues for whichever answer you already wanted.

Rasterise it at the size it will really be drawn, then magnify
*that*. In the console, with the glyph's `innerHTML` in `inner`:

```js
const CSSPX = 21, DEV = Math.round(CSSPX * devicePixelRatio);
const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"`
  + ` width="${DEV}" height="${DEV}"><g fill="none" stroke="#e8e8e8"`
  + ` stroke-width="${(24 * 1.5 / CSSPX).toFixed(3)}"`
  + ` stroke-linecap="round" stroke-linejoin="round">${inner}</g></svg>`;
const img = new Image();
await new Promise(r => { img.onload = r;
  img.src = "data:image/svg+xml;base64," + btoa(svg); });
const c = document.createElement("canvas");
c.width = c.height = DEV;
c.getContext("2d").drawImage(img, 0, 0, DEV, DEV);
const big = document.createElement("canvas");
big.width = big.height = DEV * 8;
const g = big.getContext("2d");
g.imageSmoothingEnabled = false;          // the whole point
g.drawImage(c, 0, 0, DEV * 8, DEV * 8);
document.body.appendChild(big);
```

`stroke-width` has to be written in by hand there: `.glyph` is a
class in the page's stylesheet and a data-URL SVG is its own
document, so neither the class nor `currentColor` reaches inside
it. The formula is the one in `style.css`.

**Do it at every size the glyph is used at, and find that set
first.** The door was judged at 18px, which is what the Roster
draws, and a candidate was chosen -- and then the Runs tab turned
out to draw the same glyph at 13 through `.iconbtn.tiny`, where the
stroke is 2.77 units instead of 2.0 and the chosen one closed up.
A different arrangement of the same parts survived both. Grep for
the glyph's name before deciding anything:

```bash
grep -rn 'icon("drop")\|icon("restore")' src/checkit_printit/gui/static/
```

then look up each caller's class in `style.css`. The four sizes in
use today are 21 (the rail), 18 (`.iconbtn`), 13 (`.iconbtn.tiny`)
and 13 (the band chevron).
