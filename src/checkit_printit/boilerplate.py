"""The parts of the form that do not change week to week.

The wording printit *derives* -- which assessment, which date, which skills --
is built in `form.payload_for` and rewritten on every push. This module holds
the other half: the form's title and description, the heading above each
item, and any section that is the same all term.

**This app is the source of truth for all of it.** printit creates the form,
so the alternative is that the authority lives in whatever an instructor last
typed into Google, and a rebuilt form silently loses it.

These are defaults. A boilerplate editor is planned (design 12.6) that will
let an instructor change the wording and leave out the optional sections; it
does not exist yet, so nothing here is editable from the app today.

### Required and optional

Two items are **required** and appear on every instructor's form, because
printit's behaviour depends on them:

- `confirm_date` -- the scoping key. `form pull` decides which assessment a
  response belongs to by reading the date a student confirmed, so a form
  without it cannot be read back at all.
- `choose_skills` -- the thing being asked.

Everything else is **optional**: an instructor may keep, reword, or omit it,
and the form still works.

### One copy, not two

The item titles used to be written into `appsscript/Code.gs`, where
`addItems_` created them. They are here now and passed across in the payload,
because a title in two places is a title that will disagree with itself --
the failure this codebase has hit repeatedly.
"""

import dataclasses


@dataclasses.dataclass(frozen=True)
class Part:
    """One piece of the form as a student meets it, top to bottom."""

    key: str
    kind: str          # form-title | form-description | section | checkbox
    #: Fixed wording, owned here.
    title: str = ""
    body: str = ""
    #: False when an instructor may leave it out.
    required: bool = False
    #: True when the body is written fresh on every push, from the
    #: assessment, rather than being boilerplate.
    derived: bool = False
    #: What the instructor should understand before changing it.
    note: str = ""


#: The form, in order. `derived` parts take their body from
#: `form.payload_for`; the rest say what they say all term.
PARTS = (
    Part("form_title", "form-title", title="Skill Selection Form",
         required=True,
         note="The form's own name, which students see at the top."),

    Part("form_description", "form-description",
         body="Use this form to select the skills that you would like "
              "printed for the next Skill Checkpoint reassessment "
              "opportunity.",
         note="The form's description, under its title."),

    Part("selecting_for", "section",
         title="What am I selecting skills for?", derived=True,
         note="The heading is yours; the sentence under it names the "
              "assessment and its date, and is rewritten on every push."),

    Part("confirm_date", "checkbox",
         title="Confirm Skill Checkpoint Date", derived=True, required=True,
         note="Required. `form pull` decides which assessment a response "
              "belongs to by reading the date confirmed here, so a form "
              "without it cannot be read back. The wording may change; the "
              "item may not go."),

    Part("due_notice", "section",
         title="When is this form due?", derived=True,
         note="The heading is yours; the sentence under it carries the "
              "closing date and is rewritten on every push."),

    Part("how_to_decide", "section",
         title="How do I decide what to choose?",
         body="",
         note="Advice that stays the same all term. Not currently on any "
              "form printit created -- it exists on the live MAT 106 form, "
              "added by hand, and its text has not been supplied yet."),

    Part("choose_skills", "checkbox",
         title="Choose Skills", derived=True, required=True,
         note="Required. The question itself. Its title and options are "
              "rewritten on every push, from the open skills and the limit."),
)


BY_KEY = {p.key: p for p in PARTS}


def titles():
    """{key: title} for the items printit creates, so `addItems` is told
    what to call them rather than deciding for itself."""
    return {p.key: p.title for p in PARTS
            if p.kind in ("section", "checkbox")}


def preview(payload, included=None):
    """The whole form, top to bottom, as the preview draws it.

    `payload` is what `form.payload_for` produced -- the derived wording.
    `included` is the set of optional keys an instructor keeps; None means
    all of them, which is the default until the editor exists.

    Returns plain dicts rather than Parts, because this crosses to the
    browser as JSON.
    """
    derived_body = {
        "selecting_for": payload.get("selecting_for", ""),
        "due_notice": payload.get("due_notice", ""),
    }
    out = []
    for part in PARTS:
        if not part.required and included is not None and part.key not in included:
            continue
        item = {
            "key": part.key,
            "kind": part.kind,
            "title": part.title,
            "body": derived_body.get(part.key, part.body),
            "required": part.required,
            "derived": part.derived,
            "note": part.note,
            "options": [],
            "footnote": "",
        }
        if part.key == "confirm_date":
            item["options"] = [payload.get("confirm_date", "")]
        elif part.key == "choose_skills":
            # The push rewrites this item's title, so the boilerplate one is
            # only what a freshly created form starts with.
            item["title"] = payload.get("question_title", part.title)
            item["body"] = payload.get("question_help", "")
            item["options"] = list(payload.get("choices", []))
            item["footnote"] = (payload.get("validation") or {}).get("help", "")
        if part.key == "how_to_decide" and not item["body"]:
            item["missing"] = True
        out.append(item)
    return out
