# reference/

Not part of the package. Nothing here is imported, tested, or shipped.

## `control_center.gs`

The Apps Script bound to the Google Sheet that ran MAT 106 before this tool
existed, copied here verbatim on 2026-09-20. **It is being retired**, and it is
kept because it is the only written record of how several things behaved.

Read it as a specification, not as code to port. `PRINT_TOOL_DESIGN.md` section
12.10 in the `checkit` repo says what each function did and where that
responsibility goes; the parts worth knowing before touching the Google half:

- `updateSelectionsForm` is the reference implementation of the form push --
  the number-word table, the three limiter modes, and the unsubmittable
  "no skills available yet" state.
- `importStudentChoices` shows how responses were scoped to one assessment:
  by matching the date the student confirmed, not by a timestamp window.
- It locates form items by **type and index** (`getItems(CHECKBOX)[1]`), which
  is the fragility the new design avoids by recording item ids.

It carries no student data: no names from any roster, no email addresses.
Checked before committing, not assumed.
