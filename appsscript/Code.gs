/**
 * checkit-printit's half of the Google Form.
 *
 * Deployed as a web app that executes as the form's owner, so it needs no
 * Cloud project, no OAuth client and no token. printit posts JSON to it.
 *
 * WHAT THIS OWNS, AND WHAT IT DOES NOT
 *
 * It rewrites four things and nothing else: the "what am I selecting for"
 * text, the date confirmation, the due notice, and the skill question with
 * its options and validation. The banner image, the title, the grade cutoffs
 * and the syllabus links are the instructor's, they change on the
 * instructor's schedule, and no field in printit knows any of them. A push
 * that regenerated the form would delete them every week.
 *
 * ITEMS ARE ADDRESSED BY ID
 *
 * Responses are stored against a question's id. Recreating the form changes
 * its URL and strands every response already collected; recreating a question
 * inside it leaves the old answers attached to the old question, so the
 * export grows a dead column every week. The skill question's options change
 * every week and its id must not. So: `describe` reports the ids once,
 * printit records them, and `push` only ever updates.
 *
 * The script this replaces addressed items by type and index --
 * getItems(CHECKBOX)[1] -- which meant inserting one section header above
 * them silently retargeted every write. See reference/control_center.gs.
 *
 * ALL WORDING COMES FROM PRINTIT
 *
 * This file formats nothing. printit sends finished strings, because the
 * number words, the three limiter modes and the phrasing live in
 * availability.py and one copy of them is enough.
 *
 * SETUP
 *
 *   clasp push
 *   Deploy > New deployment > Web app
 *     Execute as:    Me
 *     Who has access: Anyone
 *   Project Settings > Script Properties > add PRINTIT_SECRET
 *
 * "Anyone" is required because a command line cannot sign in to Google. The
 * URL is unguessable and every request must carry the secret, which is what
 * actually protects it -- so treat the URL as a credential and keep it in the
 * workspace's secrets/ directory.
 */

var SECRET_PROPERTY = 'PRINTIT_SECRET';

function doPost(e) {
  try {
    var body = JSON.parse(e.postData.contents);
    if (!secretOk_(body.secret)) {
      return json_({ok: false, error: 'the secret did not match'});
    }
    switch (body.op) {
      case 'ping':
        return json_({ok: true, form: FormApp.getActiveForm().getTitle()});
      case 'describe':
        return json_({ok: true, items: describe_()});
      case 'push':
        return json_({ok: true, changed: push_(body.payload)});
      default:
        return json_({ok: false, error: 'unknown op: ' + body.op});
    }
  } catch (err) {
    return json_({ok: false, error: String(err)});
  }
}

function secretOk_(given) {
  var want = PropertiesService.getScriptProperties()
      .getProperty(SECRET_PROPERTY);
  if (!want) {
    return false;   // unconfigured is closed, not open
  }
  if (!given || given.length !== want.length) {
    return false;
  }
  // Compared in full rather than short-circuiting, so the time taken does not
  // depend on how much of the secret was right.
  var same = 0;
  for (var i = 0; i < want.length; i++) {
    same |= (want.charCodeAt(i) ^ given.charCodeAt(i));
  }
  return same === 0;
}

/**
 * Every item, with the id printit needs to address it later.
 *
 * Reported rather than guessed at: only the instructor knows which section
 * header is the due notice and which is the grade advice, and a wrong guess
 * would overwrite the wrong one.
 */
function describe_() {
  return FormApp.getActiveForm().getItems().map(function (item) {
    return {
      id: String(item.getId()),
      type: String(item.getType()),
      title: item.getTitle(),
      help: item.getHelpText()
    };
  });
}

function byId_(form, id) {
  var item = form.getItemById(Number(id));
  if (!item) {
    throw new Error('no item with id ' + id + '. If it was deleted, run ' +
                    '`checkit-printit form adopt` again.');
  }
  return item;
}

/**
 * Apply one week's wording. Returns what changed, so a push that silently did
 * nothing is visible.
 */
function push_(payload) {
  var form = FormApp.getActiveForm();
  var ids = payload.items || {};
  var changed = [];

  if (ids.selecting_for) {
    byId_(form, ids.selecting_for).setHelpText(payload.selecting_for);
    changed.push('selecting_for');
  }
  if (ids.due_notice) {
    byId_(form, ids.due_notice).setHelpText(payload.due_notice);
    changed.push('due_notice');
  }
  if (ids.confirm_date) {
    byId_(form, ids.confirm_date).asCheckboxItem()
        .setChoiceValues([payload.confirm_date]);
    changed.push('confirm_date');
  }
  if (ids.choose_skills) {
    var question = byId_(form, ids.choose_skills).asCheckboxItem();
    question.setTitle(payload.question_title);
    if (payload.question_help) {
      question.setHelpText(payload.question_help);
    }
    question.setChoiceValues(payload.choices);
    question.setValidation(validation_(payload.validation));
    changed.push('choose_skills');
  }
  return changed;
}

/**
 * The three limiter modes, plus the state where nothing is open yet.
 *
 * With no skills available the form is made unsubmittable by requiring more
 * selections than exist -- a trick inherited deliberately, so a student who
 * opens the form early cannot submit an empty choice that later looks like a
 * real one.
 */
function validation_(spec) {
  spec = spec || {};
  var builder = FormApp.createCheckboxValidation();
  var count = Number(spec.count || 0);

  if (spec.mode === 'none') {
    return builder.setHelpText('No skills are available yet.')
        .requireSelectAtLeast(100).build();
  }
  if (!count) {
    return builder.setHelpText('You may choose any amount of skills.')
        .requireSelectAtLeast(1).build();
  }
  if (spec.mode === 'at least') {
    return builder.setHelpText(spec.help).requireSelectAtLeast(count).build();
  }
  if (spec.mode === 'exactly') {
    return builder.setHelpText(spec.help).requireSelectExactly(count).build();
  }
  return builder.setHelpText(spec.help).requireSelectAtMost(count).build();
}

function json_(value) {
  return ContentService.createTextOutput(JSON.stringify(value))
      .setMimeType(ContentService.MimeType.JSON);
}
