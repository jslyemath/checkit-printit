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
| `drillin.js` | three fly-out panel layouts for the Progress drill-in, all timelines. See `PRINT_TOOL_DESIGN.md` 17. |
