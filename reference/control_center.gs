function onOpen() {
  var ui = SpreadsheetApp.getUi();
  // Create the custom button menu at the top.
  ui.createMenu('Seating')
    .addItem('Choose Random Student', 'chooseRandomStudent')
    .addItem('Choose Multiple Students', 'chooseMultipleStudents')
    .addItem('Refresh Call List', 'refreshCallList')
    .addItem('Randomize Current Seating Chart', 'randomizeSeating')
    .addItem('Shuffle Selected Students', 'shuffleSelectedStudents')
    .addToUi();
  ui.createMenu('Printing')
    .addItem('Populate Print Preview', 'importStudentChoices')
    .addItem('Get Print Job TeX', 'generateTexFile')
    .addItem('Log in "Printed" and Reset', 'printAndReset')
    .addToUi();
  ui.createMenu('Selections Form')
    .addItem('Update Google Form', 'updateSelectionsForm')
    .addItem('Email Missing Students', 'emailMissingStudents')
    .addToUi();
}

// Wrappers for UI
function chooseRandomStudent() {
  coreCallSystem(1);
}

function chooseMultipleStudents() {
  coreCallSystem(); // Passing nothing triggers the prompt
}

function shuffleArray(array) {
  for (let i = array.length - 1; i > 0; i--) {
    // Pick a random index from 0 to i
    const j = Math.floor(Math.random() * (i + 1));
    
    // Swap elements array[i] and array[j]
    [array[i], array[j]] = [array[j], array[i]];
  }
  return array;
}

function trimArray(array) {
  let lastNonEmptyRow = 0;
  let lastNonEmptyColumn = 0;

  // Determine the last non-empty row and column
  for (let i = 0; i < array.length; i++) {
    for (let j = 0; j < array[i].length; j++) {
      if (array[i][j] !== "" && array[i][j] !== " " && array[i][j] !== null && array[i][j] !== undefined) {
        if (i > lastNonEmptyRow) lastNonEmptyRow = i;
        if (j > lastNonEmptyColumn) lastNonEmptyColumn = j;
      }
    }
  }

  // Slice the array to only include non-empty rows and columns
  const trimmedArray = array.slice(0, lastNonEmptyRow + 1).map(row => row.slice(0, lastNonEmptyColumn + 1));

  return trimmedArray;
}

function monthDay(date) {
  var dateObject = new Date(date);

  // Format the date to 'm/d
  var formattedDate = Utilities.formatDate(dateObject, Session.getScriptTimeZone(), 'M/d');
  return formattedDate;
}

function dayOfDate(date) {
  var daysOfWeek = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
  return daysOfWeek[date.getDay()]
}

function findCellR1C1(sheet, contents) {
  var data = sheet.getDataRange().getValues();
  for (var i = 0; i < data.length; i++) {
    for (var j = 0; j < data[i].length; j++) {
      if (data[i][j] === contents) {
        var row = i + 1;
        var col = j + 1;
        return { row: row, column: col };
      }
    }
  }
  return null;
}

function getColumnBelow(sheet, locationObject) {  
  // Get all data in the column starting from the row under location
  var startRow = locationObject.row + 1;
  var startColumn = locationObject.column;
  
  // Get all values in the column from the startRow down to the last row in the sheet
  var columnDataRowCount = sheet.getLastRow() - startRow + 1;
  var columnRange = sheet.getRange(startRow, startColumn, columnDataRowCount);
  var columnData = columnRange.getValues();
  
  // Find the last non-empty cell in the column
  var lastNonemptyRow = 0;
  
  for (var i = columnDataRowCount -1 ; i >= 0; i--) {
    if (columnData[i][0].length > 0 && columnData[i][0] !== " "  || columnData[i][0] !== "" || columnData[i][0] !== undefined || columnData[i][0] !== null) {
      lastNonemptyRow = i + 1;
      break;
    }
  }
  
  if (lastNonemptyRow === 0) {
    return null;
  }
  // Get the range of data
  var range = sheet.getRange(startRow, startColumn, lastNonemptyRow);
  return range;
}

const ss = SpreadsheetApp.getActiveSpreadsheet();
const mainSheet = ss.getSheetByName('Main');
const rosterSheet = ss.getSheetByName('Roster');
const missingSheet = ss.getSheetByName('Missing');
const responsesSheet = ss.getSheetByName('Responses');
const printedSheet = ss.getSheetByName('Printed');
var mainNamedRanges = mainSheet.getNamedRanges();
function rangesToDataDict (inputRanges) {
  const namedRangesDict = new Object();
  for (var i = 0; i < inputRanges.length; i++) {
    let values = inputRanges[i].getRange().getValues();
    // Check if it's a single cell
    if (values.length === 1 && values[0].length === 1) {
      namedRangesDict[inputRanges[i].getName()] = values[0][0]; // Single value
    } else if (values.length === 1) {
      namedRangesDict[inputRanges[i].getName()] = trimArray(values)[0]; // Single row
    } else if (values[0].length === 1) {
      namedRangesDict[inputRanges[i].getName()] = trimArray(values).map(row => row[0]);; // Single column
    } else {
      namedRangesDict[inputRanges[i].getName()] = trimArray(values); // 2D array
    }
  }
  return namedRangesDict;
}

var fullNamedRangesDict = rangesToDataDict(mainNamedRanges);

var rosterNamedRanges = rosterSheet.getNamedRanges();
Object.assign(fullNamedRangesDict, rangesToDataDict(rosterNamedRanges));
var missingNamedRanges = missingSheet.getNamedRanges();
Object.assign(fullNamedRangesDict, rangesToDataDict(missingNamedRanges));
var responsesNamedRanges = responsesSheet.getNamedRanges();
Object.assign(fullNamedRangesDict, rangesToDataDict(responsesNamedRanges));

const skillSheet = ss.getSheetByName(fullNamedRangesDict["GetSkillSheet"]);

function findCellR1C1ByNamedRange(rangeName) {
  var namedRange = ss.getRangeByName(rangeName);
  var startRow = namedRange.getRow();
  var startColumn = namedRange.getColumn();
  var numRows = namedRange.getNumRows();
  var numColumns = namedRange.getNumColumns();
  if (numRows === 1 && numColumns === 1) {
    return { row: startRow, column: startColumn };
  }
  else {
    return { row: startRow, column: startColumn, endRow: startRow + numRows - 1, endColumn: startColumn + numColumns - 1 }
  }
}

/**
 * Unified function to call one or more students.
 * @param {number} countParam - Number of students to call. If null/undefined, prompts user.
 * @param {boolean} updateNextUp - Whether to update the dashboard cell.
 */
function coreCallSystem(countParam, updateNextUp = true) {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getActiveSheet();

  // 1. Validation & A1 Fallback
  if (!sheet.getName().toLowerCase().includes("seat")) {
    const altSheetName = sheet.getRange("A1").getValue();
    sheet = ss.getSheetByName(altSheetName);
  }
  if (!sheet || !sheet.getName().toLowerCase().includes("seat")) {
    SpreadsheetApp.getUi().alert("Please run on a seating chart sheet OR enter a valid name in A1.");
    return;
  }

  // 2. Input Handling
  let count = countParam;
  if (!count) {
    const ui = SpreadsheetApp.getUi();
    const response = ui.prompt("How many students?", "Enter a number:", ui.ButtonSet.OK_CANCEL);
    if (response.getSelectedButton() !== ui.Button.OK) return;
    count = parseInt(response.getResponseText());
  }
  if (isNaN(count) || count < 1) return;

  // 3. Data Gathering
  const fullData = sheet.getDataRange().getValues();
  const headers = findHeadersInArray(fullData);
  if (!headers.students) return;

  const startRow = headers.students.rowIndex + 1;
  const studentCol = headers.students.colIndex;
  const checkCol = studentCol + 1;

  // 4. SMART SYNC (The Refresh Logic)
  let eligibleStudents = []; 
  let blacklistedNames = new Set(); 

  for (let r = startRow; r < fullData.length; r++) {
    let name = fullData[r][studentCol];
    if (!name) continue;
    if (fullData[r][checkCol] === true) {
      blacklistedNames.add(name);
    } else {
      eligibleStudents.push(name);
    }
  }

  let callListData = [];
  let targetCol;

  if (!headers.callList) {
    // New List: Shuffle eligible students
    callListData = [...eligibleStudents];
    shuffleArray(callListData);
    targetCol = fullData[0].length + 1;
    sheet.getRange(headers.students.rowIndex + 1, targetCol).setValue("Call List");
  } else {
    // Existing List: Remove 'N' and Add Back new un-checked students
    let currentList = extractColumnData(fullData, headers.callList.colIndex, headers.callList.rowIndex)
                      .filter(name => name !== "" && name !== null);
    
    // Remove blacklisted
    let filteredList = currentList.filter(name => !blacklistedNames.has(name));
    
    // Find missing (were unchecked since last run)
    let listSet = new Set(filteredList);
    let missing = eligibleStudents.filter(name => !listSet.has(name));
    
    // Randomly insert missing students
    missing.forEach(student => {
      let randIdx = Math.floor(Math.random() * (filteredList.length + 1));
      filteredList.splice(randIdx, 0, student);
    });
    
    callListData = filteredList;
    targetCol = headers.callList.colIndex + 1;
  }

  // 5. ROTATION & SELECTION
  if (callListData.length > 0) {
    let actualCount = Math.min(count, callListData.length);
    let selectedStudents = callListData.splice(0, actualCount);
    callListData.push(...selectedStudents);

    // Write back to Call List
    const outputValues = callListData.map(name => [name]);
    sheet.getRange(headers.students.rowIndex + 2, targetCol, sheet.getMaxRows(), 1).clearContent();
    sheet.getRange(headers.students.rowIndex + 2, targetCol, outputValues.length, 1).setValues(outputValues);

    // 6. DASHBOARD UPDATE (With Name Glue)
    if (updateNextUp && headers.students.rowIndex >= 3) {
      let displayNames = selectedStudents
        .map(name => name.toString().replace(" ", "\u00A0"))
        .join(', ');
      
      let dashCell = sheet.getRange(headers.students.rowIndex - 2, headers.students.colIndex + 1);
      dashCell.setValue(displayNames);
      dashCell.setWrap(true);
      dashCell.setVerticalAlignment("middle");
    }
  }
}

/** * Helper: Find header positions in a 2D array (MUCH faster than searching the sheet)
 */
function findHeadersInArray(data) {
  let found = {};
  for (let r = 0; r < data.length; r++) {
    for (let c = 0; c < data[r].length; c++) {
      if (data[r][c] === "Students") found.students = {rowIndex: r, colIndex: c};
      if (data[r][c] === "Call List") found.callList = {rowIndex: r, colIndex: c};
    }
  }
  return found;
}

/** * Helper: Grab a specific column from the 2D array starting below the header
 */
function extractColumnData(data, colIndex, startRow) {
  let col = [];
  for (let r = startRow + 1; r < data.length; r++) {
    col.push(data[r][colIndex]);
  }
  return col;
}

// Randomize the current Seating Arragement From Available Names on the Roster
function randomizeSeating() {
  var ss = SpreadsheetApp.getActiveSpreadsheet();
  var sheet = ss.getActiveSheet();

  // If the current sheet isn't a seating chart, try to get the name from A1
  if (!sheet.getName().toLowerCase().includes("seat")) {
    var altSheetName = sheet.getRange("A1").getValue();
    sheet = ss.getSheetByName(altSheetName);
  }

  // Final check to make sure we ended up with a valid seating chart sheet
  if (!sheet || !sheet.getName().toLowerCase().includes("seat")) {
    SpreadsheetApp.getUi().alert("Please run on a seating chart sheet OR enter a valid seating chart sheet name in A1 on this sheet.");
    return null;
  }

  var fullNamesHeader = findCellR1C1ByNamedRange ("GetFullName");
  var seatingSheetName = sheet.getName();
  var droppedHeader = findCellR1C1ByNamedRange ("GetDropped");
  var sectionHeader = findCellR1C1ByNamedRange ("GetSection");
  // The line below relies on the order of the columns. Needs to be fixed so that this can be rearranged
  var fullNamesRowData = rosterSheet.getRange(droppedHeader.row + 1, 1, rosterSheet.getLastRow() - fullNamesHeader.row, sectionHeader.column).getValues();

  Logger.log(fullNamesRowData);

  if (/\d/.test(seatingSheetName) === false) {
    fullNamesRowData = fullNamesRowData.filter(row =>
        row[droppedHeader.column - 1] === false
    );
  }
  else {
    var section = seatingSheetName.match(/\d+/)[0].trim();
    fullNamesRowData = fullNamesRowData.filter(row =>
        String(row[sectionHeader.column - 1]).trim() === section.trim() &&
        row[droppedHeader.column - 1] === false
    );
  }

  fullNames = shuffleArray(fullNamesRowData.map(row => [row[fullNamesHeader.column - 1]]));

  var studentsHeader = findCellR1C1(sheet, "Students");
  if (!studentsHeader) {
    SpreadsheetApp.getUi().alert("This function requires a column somewhere in the sheet with the header of \"Students\".");
    return null;
  }

  var startRow = studentsHeader.row + 1; // Start setting names below the "Students" header
  var totalRows = sheet.getMaxRows(); // Total number of rows in the sheet
  var totalColumns = sheet.getMaxColumns();

  // Initialize seatingArray to be the same size as the rows below "Students"
  var seatingArray = new Array(totalRows - startRow + 1).fill([""]);
  // Clear any values in the "Students" area and the potential "Call List" area
  sheet.getRange(studentsHeader.row, totalColumns, totalRows - studentsHeader.row + 1).setValue("");
  sheet.getRange(studentsHeader.row + 1, studentsHeader.column, totalRows - studentsHeader.row, 1).setValue("");
  if (studentsHeader.row < 4) {
    sheet.insertRowsBefore(studentsHeader.row, 4 - studentsHeader.row);
  }
  sheet.getRange(studentsHeader.row - 3, studentsHeader.column, 3, 1).setValue("");

  var nameIndex = 0; // Index to track position in fullNames array

  for (var i = startRow; i <= totalRows; i++) {
    if (!sheet.isRowHiddenByUser(i) && nameIndex < fullNames.length) {
      seatingArray[i - startRow] = fullNames[nameIndex];
      nameIndex++;
    }
  }

  // Use a single setValues call to update the sheet
  sheet.getRange(startRow, studentsHeader.column, seatingArray.length, 1).setValues(seatingArray);

  // // Create the call list without populating Next Up.
  // chooseRandomStudent(1, false);
}

function shuffleSelectedStudents() {
  var sheet = ss.getActiveSheet();
  if (!sheet.getName().toLowerCase().includes("seat")) {
    SpreadsheetApp.getUi().alert("This function is only allowed on seating chart sheets. The name of the sheet must contain 'seat' and the names must be in a single column.");
    return null;
  }

  var studentsHeader = findCellR1C1(sheet, "Students");
  if (!studentsHeader) {
    SpreadsheetApp.getUi().alert("This function requires a column somewhere in the sheet with the header of 'Students'.");
    return null;
  }

  var studentsSwapRange = sheet.getRange(studentsHeader.row + 1, studentsHeader.column, sheet.getLastRow() - studentsHeader.row, 2);
  var studentsSwapData = studentsSwapRange.getValues();
  var amountToSwap = studentsSwapData.filter(row => row[1] === true).length;

  if (amountToSwap === 2) {
    // Find the indices of the rows to swap
    let swapIndices = studentsSwapData.reduce((acc, row, index) => {
      if (row[1] === true) acc.push(index);
      return acc;
    }, []);
    
    // Swap the two rows
    [studentsSwapData[swapIndices[0]], studentsSwapData[swapIndices[1]]] = [studentsSwapData[swapIndices[1]], studentsSwapData[swapIndices[0]]];

  } else if (amountToSwap > 2) {
    // Shuffle the rows where the second column is true
    let swapIndices = studentsSwapData.reduce((acc, row, index) => {
      if (row[1] === true) acc.push(index);
      return acc;
    }, []);
    
    // Extract the rows to shuffle
    let rowsToShuffle = swapIndices.map(index => studentsSwapData[index]);
    rowsToShuffle = shuffleArray(rowsToShuffle);
    
    // Place the shuffled rows back into studentsSwapData
    swapIndices.forEach((index, i) => {
      studentsSwapData[index] = rowsToShuffle[i];
    });
  }

  // Set the second column to false for all rows
  studentsSwapData = studentsSwapData.map(row => {
    row[1] = false;
    return row;
  });

  // Set the updated values back to the sheet
  studentsSwapRange.setValues(studentsSwapData);
}

function refreshCallList() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const sheet = ss.getActiveSheet();
  const fullData = sheet.getDataRange().getValues();
  const headers = findHeadersInArray(fullData);
  
  if (!headers.students || !headers.callList) return;

  const startRow = headers.students.rowIndex + 1;
  const studentCol = headers.students.colIndex;
  const checkCol = studentCol + 1; // The 'N' column

  // 1. Get current list and identify who is actually eligible
  let currentCallList = extractColumnData(fullData, headers.callList.colIndex, headers.callList.rowIndex)
                        .filter(name => name !== "" && name !== null);
  
  let eligibleStudents = []; // Unchecked students from the main column
  let blacklistedNames = new Set(); // Names marked 'N'

  for (let r = startRow; r < fullData.length; r++) {
    let name = fullData[r][studentCol];
    if (!name) continue;
    
    if (fullData[r][checkCol] === true) {
      blacklistedNames.add(name);
    } else {
      eligibleStudents.push(name);
    }
  }

  // 2. Clean current list (Remove 'N' students)
  let filteredList = currentCallList.filter(name => !blacklistedNames.has(name));

  // 3. Find missing students (Eligible but not in the list)
  let listSet = new Set(filteredList);
  let missingStudents = eligibleStudents.filter(name => !listSet.has(name));

  // 4. Randomly insert missing students into the existing order
  missingStudents.forEach(student => {
    // Pick a random index from 0 to current length
    let randomIndex = Math.floor(Math.random() * (filteredList.length + 1));
    filteredList.splice(randomIndex, 0, student);
  });

  // 5. Update Sheet
  const outputValues = filteredList.map(name => [name]);
  const targetCol = headers.callList.colIndex + 1;

  sheet.getRange(headers.students.rowIndex + 2, targetCol, sheet.getMaxRows(), 1).clearContent();
  if (outputValues.length > 0) {
    sheet.getRange(headers.students.rowIndex + 2, targetCol, outputValues.length, 1).setValues(outputValues);
  }
}

function updateSelectionsForm() {
  var form = FormApp.openById(fullNamedRangesDict["GetGoogleFormID"]);
  var nextDate = fullNamedRangesDict["GetNextRedoDate"];
  var title = fullNamedRangesDict["GetNextRedoTitle"];
  var dueDate = fullNamedRangesDict["GetFormDueDate"];
  var dueTime = fullNamedRangesDict["GetFormDueTime"];
  var skillAmtLimiter = fullNamedRangesDict["GetSkillSelectionAmtLimiter"];
  var skillAmt = fullNamedRangesDict["GetSkillSelectionAmt"];

  var dateConfirmationItem = form.getItems(FormApp.ItemType.CHECKBOX)[0].asCheckboxItem();

  var skillCheckboxItem = form.getItems(FormApp.ItemType.CHECKBOX)[1].asCheckboxItem();

  var sectionHeaderItems = form.getItems(FormApp.ItemType.SECTION_HEADER);

  var nextAssessmentInfoHeader = sectionHeaderItems[0].asSectionHeaderItem();

  var nextAssessmentDueDateHeader = sectionHeaderItems[1].asSectionHeaderItem();

  Logger.log(sectionHeaderItems);

  var asManyPhrase1 = "any";

  const numberWords = [
    asManyPhrase1, "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten",
    "eleven", "twelve", "thirteen", "fourteen", "fifteen", "sixteen", "seventeen", "eighteen", "nineteen", 
    "twenty", "twenty one", "twenty two", "twenty three", "twenty four", "twenty five", 
    "twenty six", "twenty seven", "twenty eight", "twenty nine", "thirty", 
    "thirty one", "thirty two", "thirty three", "thirty four", "thirty five", 
    "thirty six", "thirty seven", "thirty eight", "thirty nine", "forty"
  ];

  const numberWordsDict = numberWords.reduce((dict, word, index) => {
    dict[index] = word;
    return dict;
  }, {});

  if (skillAmt === " " || skillAmt === "" || skillAmt === undefined || skillAmt === null) {
    skillAmt = 0;
  }

  var skillAmtLimiterSpace = " ";

  if (skillAmt == 0) {
    skillAmtLimiter = "";
    skillAmtLimiterSpace = "";
  }

  var lowercaseSkillAmt = numberWordsDict[skillAmt];
  var uppercaseSkillAmt = numberWordsDict[skillAmt].toUpperCase();


  nextAssessmentInfoHeader.setHelpText(`You are selecting ${lowercaseSkillAmt} skill(s) you would like to attempt on the ${title} on ${dayOfDate(nextDate)}, ${monthDay(nextDate)}.`);

  nextAssessmentDueDateHeader.setHelpText(`This form is due by ${dueTime} on ${dayOfDate(dueDate)}, ${monthDay(dueDate)}. If you do not complete the form by that time, then I cannot guarantee that I will have skills printed for you to attempt.`);

  var skillSelectionsData = fullNamedRangesDict["SkillSelectionAvailability"];

  var availableSkills = [];
  var numberOfAssociatedSkills = 0;
  for (var col = 0; col < skillSelectionsData[0].length; col++) {
    if (skillSelectionsData[2][col] === true) {
      availableSkills.push(skillSelectionsData[0][col]);
    }
    if (skillSelectionsData[1][col] !== " " && skillSelectionsData[1][col] !== "" && skillSelectionsData[1][col] !== null && skillSelectionsData[1][col] !== undefined) {
      numberOfAssociatedSkills++;
    }
  }

  var skillsAndDescriptions = skillSheet.getRange(1, 1, skillSheet.getLastRow(), 4).getValues(); 

  // Filter rows based on availableSkills
  var filteredSkills = skillsAndDescriptions.filter(function(row) {
    return availableSkills.includes(row[0]);
  });

  // Process filteredData into a 1D array with template strings
  var availableSkillsStringArray = filteredSkills.map(function(row) {
    if (row[2] === " " || row[2] === "" || row[2] === null || row[2] === undefined) {
      return `${row[0]} - ${row[1]}`;
    } else {
      return `${row[0]} - ${row[1]} (${row[2]} will be included on the back side automatically.)`;
    }
  });

  noSkillsAvailable = false;
  if (availableSkills.length === 0) {
    noSkillsAvailable = true;
    availableSkillsStringArray.push('(No skills are available yet. Check back later!)');
  }

  var associatedSkillsPresentString = " Certain Core Skills will always have an Explanation Skill attached. Such skills are indicated below with a parenthetical statement. Even if you've completed the Explanation Skill, it will be attached automatically.";

  if (numberOfAssociatedSkills === 0) {
    associatedSkillsPresentString = "";
  }

  skillCheckboxItem.setTitle(`Choose ${skillAmtLimiter}${skillAmtLimiterSpace}${uppercaseSkillAmt} Skills`).setHelpText(`You are choosing which skills you'll be redoing on ${dayOfDate(nextDate)}.${associatedSkillsPresentString}`);

  dateConfirmationItem.setChoiceValues([`I understand that I am selecting skills for ${dayOfDate(nextDate)}, ${monthDay(nextDate)}.`]);

  skillCheckboxItem.setChoiceValues(availableSkillsStringArray);
  
  if (noSkillsAvailable === true) {
    var checkBoxValidation = FormApp.createCheckboxValidation()
      .setHelpText(`No skills are available yet.`)
      .requireSelectAtLeast(100)
      .build();
  }
  else if (Number(skillAmt) > 0) {
    if (skillAmtLimiter == "At Most") {
      var checkBoxValidation = FormApp.createCheckboxValidation()
      .setHelpText(`Please choose at most ${lowercaseSkillAmt} skill(s).`)
      .requireSelectAtMost(Number(skillAmt))
      .build();
    }
    else if (skillAmtLimiter == "At Least") {
      var checkBoxValidation = FormApp.createCheckboxValidation()
      .setHelpText(`Please choose at least ${lowercaseSkillAmt} skill(s).`)
      .requireSelectAtLeast(Number(skillAmt))
      .build();
    }
    else {
      var checkBoxValidation = FormApp.createCheckboxValidation()
      .setHelpText(`Please choose ${lowercaseSkillAmt} skill(s).`)
      .requireSelectExactly(Number(skillAmt))
      .build();
    }
  }
  else {
    var checkBoxValidation = FormApp.createCheckboxValidation()
      .setHelpText(`You may choose any amount of skills.`)
      .requireSelectAtLeast(1)
      .build();
  }

  skillCheckboxItem.setValidation(checkBoxValidation);
}

function emailMissingStudents() {
  var missingStudentData = trimArray(fullNamedRangesDict["MissingStudentsData"]);
  var emailTitleTemplate = fullNamedRangesDict["GetEmailTitleTemplate"];
  var emailBodyTemplate = fullNamedRangesDict["GetEmailBodyTemplate"];
  const ourSubstitutions = {
    "$DEFAULTSKILL1": fullNamedRangesDict["GetDefaultSkill1"],
    "$DEFAULTSKILL2": fullNamedRangesDict["GetDefaultSkill2"],
    "$DEFAULTSKILL3": fullNamedRangesDict["GetDefaultSkill3"],
    "$DEFAULTSKILL4": fullNamedRangesDict["GetDefaultSkill4"],
    "$FIRSTNAME": "Student",
    "$LASTNAME": "Student",
    "$ASSESSMENT": fullNamedRangesDict["GetNextRedoTitle"],
    "$ASSESSDATE": monthDay(fullNamedRangesDict["GetNextRedoDate"]),
    "$DUETIME": fullNamedRangesDict["GetFormDueTime"],
    "$DUEDATE" : monthDay(fullNamedRangesDict["GetFormDueDate"])
  };

  function applySubstitutions(ourTemplate, ourSubstitutions) {
    // Use a regular expression to replace each key in the template with its value
    return ourTemplate.replace(/\$\w+/g, match => ourSubstitutions[match] || match);
  }

  for (let i = 0; i < missingStudentData.length; i++) {
    studentEmail = missingStudentData[i][0];
    Logger.log(studentEmail);
    ourSubstitutions["$FIRSTNAME"] = missingStudentData[i][2];
    ourSubstitutions["$LASTNAME"] = missingStudentData[i][1];
    emailTitle = applySubstitutions(emailTitleTemplate, ourSubstitutions);
    emailBody = applySubstitutions(emailBodyTemplate, ourSubstitutions);

    GmailApp.sendEmail(studentEmail, emailTitle, emailBody);
  }
}

function generateTexFile () {
  var choicesPrintData = fullNamedRangesDict["ChoicesPrintData"];
  var keyAmount = fullNamedRangesDict["GetKeyAmount"];
  var rawSeeds = fullNamedRangesDict["GetSeedOverride"];
  var seedsArray = rawSeeds.toString().split(",").map(item => item.trim()).filter(item => item !== "");
  var colOffset = findCellR1C1ByNamedRange("ChoicesPrintFullName").column;
  var secColArrayIndex = findCellR1C1ByNamedRange("ChoicesPrintSec").column - colOffset;
  var varColArrayIndex = findCellR1C1ByNamedRange("ChoicesPrintVar").column - colOffset;
  var firstChoiceColArrayIndex = findCellR1C1ByNamedRange("ChoicesPrint1").column - colOffset;

  var mainDocument = `\\documentclass[12pt,twoside]{article}
\\usepackage[utf8]{inputenc}
\\usepackage{skillcheckpoints}

\\acadclass{${fullNamedRangesDict["GetCourse"]}} % Course (no section)
\\date{${fullNamedRangesDict["GetSemester"]}} % Semester
\\author{${fullNamedRangesDict["GetProfessor"]}} % Professor

\\title{${fullNamedRangesDict["GetTitle"]} ${monthDay(fullNamedRangesDict["GetDate"])}}

\\begin{document}

% Student copies

% Keys

\\end{document}`

  // Build student versions
  let studentText = '';
  let usedVersions = new Set();

  var uniqueVariants = [];
  choicesPrintData.slice(1).forEach(row => {
    let variant = String(row[varColArrayIndex]).trim();
    if (variant && !uniqueVariants.includes(variant)) {
      uniqueVariants.push(variant);
    }
  });
  uniqueVariants.sort();

  var variantMap = {};
  uniqueVariants.forEach((variant, index) => {
    // If we have a seed for this index, map to it. Otherwise, keep the original variant name.
    variantMap[variant] = (index < seedsArray.length) ? seedsArray[index] : variant;
  });

  choicesPrintData.slice(1).forEach(row => {
      let studentName = row[0];
      let studentSection = row[secColArrayIndex];
      // Clean up the variant string just in case there are stray spaces
      let studentVariant = String(row[varColArrayIndex]).trim(); 
      
      // Look up the override in our dictionary
      let studentSeed = variantMap[studentVariant]; 
      
      let studentChoices = row.slice(firstChoiceColArrayIndex).filter(x => String(x).trim().length >= 1);

      studentText += `\\setname{${studentName}}\n`;
      studentText += `\\setsect{${studentSection}}\n`;

      studentChoices.forEach(studentChoice => {
          let choiceTexPath = `${studentChoice}/${studentChoice} v${studentSeed}`;
          studentText += `\\skillpage{${choiceTexPath}}\n`;
          usedVersions.add(choiceTexPath);
      });

      studentText += '\\preparefornextstudent\n\n';
  });

  // Build answer key versions
  let keyName = 'Key';
  let keySection = 'Blank';
  let keyText = `\\setboolean{anstoggle}{true}\n`;
  keyText += `\\setname{${keyName}}\n`;
  keyText += `\\setsect{${keySection}}\n`;

  if (parseInt(keyAmount) > 0) {
      usedVersions.forEach(usedVersion => {
          keyText += `\\skillpage{${usedVersion}}\n`;
      });
      keyText += keyText.repeat(parseInt(keyAmount) - 1);
  }

  let [beginning, ending] = mainDocument.split('% Student copies');
  mainDocument = beginning + studentText + ending;

  [beginning, ending] = mainDocument.split('% Keys');
  mainDocument = beginning + keyText + ending;

  SpreadsheetApp.getUi().alert(mainDocument);
}

function importStudentChoices() {
  // Clear all data currently in the import destination range
  var choicesFullNamesHeader = findCellR1C1ByNamedRange("ChoicesPrintFullName");
  mainSheet.getRange(choicesFullNamesHeader.row + 1, choicesFullNamesHeader.column, Math.max(1, mainSheet.getLastRow() - choicesFullNamesHeader.row), mainSheet.getLastColumn() - choicesFullNamesHeader.column + 1).clearContent();

  function choiceSettingsToSelections (choiceSettingsArray) {
    choiceArray = []
    for (let i = 0; i < choiceSettingsArray[0].length; i++) {
      if (choiceSettingsArray[1][i] === true) {
        choiceArray.push(choiceSettingsArray[0][i]);
      } 
    }
    return choiceArray;
  }

  var simplyPrintData = fullNamedRangesDict["SimplyPrintSelections"];
  var simplyPrintSelections = choiceSettingsToSelections(simplyPrintData);
  var simplyPrint = false;
  if (simplyPrintSelections.length > 0) {
    simplyPrint = true
  }
  var noSubmissionsDefaultsData = fullNamedRangesDict["NoSubmissionsDefaultSelections"];
  var noSubmissionsDefaultSelections = choiceSettingsToSelections(noSubmissionsDefaultsData);
  var appendSelectionsData = fullNamedRangesDict["AppendSelections"];
  var appendSelections = choiceSettingsToSelections(appendSelectionsData);
  
  var seatingSheetsNames = fullNamedRangesDict["GetSeatingChartSheets"];
  var mergedStudentSeatingData = [];

  for (let i = 0; i < seatingSheetsNames.length; i++) {
    let seatingSheet = ss.getSheetByName(seatingSheetsNames[i]);
    let studentsHeader = findCellR1C1(seatingSheet, "Students");
    let lastRow = seatingSheet.getLastRow();
    let variantAndNameData = seatingSheet.getRange(studentsHeader.row + 1, studentsHeader.column - 1, lastRow - studentsHeader.row, 2).getValues();
    mergedStudentSeatingData.push.apply(mergedStudentSeatingData, variantAndNameData);
  }

  mergedStudentSeatingData = mergedStudentSeatingData.filter(function(row) {
    return row[1] !== " " && row[1] !== "";
  });

  var includeNamesRawLocation = findCellR1C1ByNamedRange("GetIncludeNames");
  var includeNamesRaw = mainSheet.getRange(includeNamesRawLocation.row, includeNamesRawLocation.column).getValue()[0].toLowerCase();
  var includeNames = true;
  if (includeNamesRaw === 'n') {
    includeNames = false;
  }

  var fullNamesHeader = findCellR1C1ByNamedRange("GetFullName");
  var droppedHeader = findCellR1C1ByNamedRange("GetDropped");
  var sidHeader = findCellR1C1ByNamedRange("GetSID");
  var lastNameHeader = findCellR1C1ByNamedRange("GetLast");
  var lastNameData = getColumnBelow(rosterSheet, lastNameHeader).getValues();
  var emailHeader = findCellR1C1ByNamedRange("GetEmail");
  var sectionHeader = findCellR1C1ByNamedRange("GetSection");
  var lastRosterColumn = Math.max(fullNamesHeader.column, droppedHeader.column, sidHeader.column, lastNameHeader.column, emailHeader.column, sectionHeader.column)
  var rosterData = rosterSheet.getRange(fullNamesHeader.row + 1, 1, lastNameData.length, lastRosterColumn).getValues();

  Logger.log(rosterData);

  var choicesFullNamesHeader = findCellR1C1ByNamedRange("ChoicesPrintFullName");
  var choicesEmailHeader = findCellR1C1ByNamedRange("ChoicesPrintEmail");
  var choicesSIDHeader = findCellR1C1ByNamedRange("ChoicesPrintSID");
  var choicesSectionHeader = findCellR1C1ByNamedRange("ChoicesPrintSec");
  var choicesVariantHeader = findCellR1C1ByNamedRange("ChoicesPrintVar");
  var choicesFirstChoiceHeader = findCellR1C1ByNamedRange("ChoicesPrint1");

  var responsesFirstChoiceHeader = findCellR1C1ByNamedRange("ResponsesChoice1");
  var responsesEmailHeader = findCellR1C1ByNamedRange("ResponsesEmail");

  var responsesData = responsesSheet.getRange(1, 1, responsesSheet.getLastRow(), responsesSheet.getMaxColumns()).getValues();

  // Old method for filtering
  function filterArrayByDateRange(dataArray, dateColumn, dateA, dateB) {
    let filteredArray = [];

    // Iterate over each row in the data array
    for (let i = 0; i < dataArray.length; i++) {
      let timestamp = new Date(dataArray[i][dateColumn]); // Convert the timestamp string to a Date object

      // Check if the timestamp is between dateA and dateB
      if (timestamp >= dateA && timestamp <= dateB) {
        filteredArray.push(dataArray[i]); // Keep the row if it matches the criteria
      }
    }

    filteredArray.sort(function(a, b) {
      return new Date(b[dateColumn]) - new Date(a[dateColumn]);
    });

    return filteredArray;
  }

  function filterArrayBySingleDateCriterion(dataArray, dateColumn, criterionColumn, matchCriterion) {
    let filteredArray = [];
    const targetMonth = matchCriterion.getMonth() + 1;
    const targetDay = matchCriterion.getDate();

    for (let i = 0; i < dataArray.length; i++) {
      let rawValue = dataArray[i][criterionColumn];
      if (rawValue === null || rawValue === undefined || rawValue === "") continue;

      let rowMonth, rowDay;

      // CASE 1: It's already a Date Object (Google Sheets Date format)
      if (rawValue instanceof Date) {
        rowMonth = rawValue.getMonth() + 1;
        rowDay = rawValue.getDate();
      } 
      // CASE 2: It's a String (Plain Text format)
      else if (typeof rawValue === 'string') {
        const parts = rawValue.split('/');
        if (parts.length < 2) continue;
        rowMonth = parts[0];
        rowDay = parts[1];
      } 
      else {
        continue; // Skip other types (numbers, booleans, etc.)
      }

      // High-speed comparison using loose equality (==)
      if (rowMonth == targetMonth && rowDay == targetDay) {
        filteredArray.push(dataArray[i]);
      }
    }

    // Sorting
    filteredArray.sort(function(a, b) {
      return new Date(b[dateColumn]) - new Date(a[dateColumn]);
    });

    return filteredArray;
  }

  // var leftDateCutoff = new Date(fullNamedRangesDict["GetSubmissionCutoff"]);
  var rightDateCutoff = new Date(fullNamedRangesDict["GetDate"]);
  // rightDateCutoff.setDate(rightDateCutoff.getDate() + 1); // To cut off at the end of the day, rather than the beginning

  var filteredResponsesData = filterArrayBySingleDateCriterion(responsesData, 0, 2, rightDateCutoff);


  var firstChoicesR1C1Column = Math.min(choicesFullNamesHeader.column, choicesEmailHeader.column, choicesSIDHeader.column, choicesSectionHeader.column, choicesVariantHeader.column);

  var choicesData = [];

  // Iterate over each row in mergedStudentSeatingData
  for (let i = 0; i < mergedStudentSeatingData.length; i++) {
    let searchFullNameValue = mergedStudentSeatingData[i][1]; // Get the value from the Students column from seating sheets

    // Search for the matching name in the Full Names column of rosterData
    fullNameLoop:
    for (let j = 0; j < rosterData.length; j++) {

      if (rosterData[j][fullNamesHeader.column - 1] === searchFullNameValue) { // Compare with the Full Name column (index array off 1 from sheet)

        let choicesDataRow = Array(choicesFirstChoiceHeader.column - firstChoicesR1C1Column).fill(" ");
        if (includeNames === true) {
          choicesDataRow[choicesFullNamesHeader.column - firstChoicesR1C1Column] = searchFullNameValue;
        }
        else {
          choicesDataRow[choicesFullNamesHeader.column - firstChoicesR1C1Column] = 'Blank';
        }
        choicesDataRow[choicesEmailHeader.column - firstChoicesR1C1Column] = rosterData[j][emailHeader.column - 1];
        choicesDataRow[choicesSIDHeader.column - firstChoicesR1C1Column] = String(rosterData[j][sidHeader.column - 1]);
        choicesDataRow[choicesSectionHeader.column - firstChoicesR1C1Column] = rosterData[j][sectionHeader.column - 1];
        choicesDataRow[choicesVariantHeader.column - firstChoicesR1C1Column] = mergedStudentSeatingData[i][0];
        if (simplyPrint === true) {
          choicesDataRow.push.apply(choicesDataRow, simplyPrintSelections);
          choicesData.push(choicesDataRow);
        }
        else{
          // Search for matching email in filtered Responses sheet data in order to append choices
          let studentEmail = rosterData[j][emailHeader.column - 1];
          for (let k = 0; k < filteredResponsesData.length; k++) {
            if (filteredResponsesData[k][responsesEmailHeader.column - 1] === studentEmail) { // Compare with the Student Email column
              let skillChoices = filteredResponsesData[k].slice(responsesFirstChoiceHeader.column - 1);
              // Logger.log(skillChoices);
              skillChoices.push.apply(skillChoices, appendSelections);
              skillChoices = skillChoices.filter(function(element) {
                return element !== " " && element !== "" && element !== null && element !== undefined;
              });
              skillChoices = [...new Set(skillChoices)];
              choicesDataRow.push.apply(choicesDataRow, skillChoices);
              choicesData.push(choicesDataRow);
              break fullNameLoop;
            }
          }    
          if (noSubmissionsDefaultSelections.length > 0) {
            noChoiceChoices = [];
            noChoiceChoices.push.apply(noChoiceChoices, noSubmissionsDefaultSelections);
            noChoiceChoices.push.apply(noChoiceChoices, appendSelections);
            noChoiceChoices = [...new Set(noChoiceChoices)];
            choicesDataRow.push.apply(choicesDataRow, noChoiceChoices);
            choicesData.push(choicesDataRow);
          }  
        }
        break; // Break out of the loop
      }
    }
  }

  var allVariants = mergedStudentSeatingData.map(function(row) {
    return row[0];
  });
  allVariants = [...new Set(allVariants)];
  
  for (let i = 0; i < fullNamedRangesDict["GetExtrasAmount"]; i++) {
    // HERE
    if (noSubmissionsDefaultSelections.length === 0 && simplyPrint === false) {
      SpreadsheetApp.getUi().alert('No default selections were selected in the "No Submission? Default to Printing..." area, so extras could not be created.');
    }
    else {
      let blankChoicesDataRow = Array(choicesFirstChoiceHeader.column - firstChoicesR1C1Column).fill(" ");
      blankChoicesDataRow[choicesFullNamesHeader.column - firstChoicesR1C1Column] = 'blank';
      blankChoicesDataRow[choicesSectionHeader.column - firstChoicesR1C1Column] = 'blank';
      blankChoicesDataRow[choicesVariantHeader.column - firstChoicesR1C1Column] = allVariants[i % allVariants.length];
      noChoiceChoices = [];
      var skillsToSelect = noSubmissionsDefaultSelections;
      if (simplyPrint === true) {
        skillsToSelect = simplyPrintSelections;
      }
      noChoiceChoices.push.apply(noChoiceChoices, skillsToSelect);
      noChoiceChoices.push.apply(noChoiceChoices, appendSelections);
      noChoiceChoices = [...new Set(noChoiceChoices)];
      blankChoicesDataRow.push.apply(blankChoicesDataRow, noChoiceChoices);
      choicesData.push(blankChoicesDataRow);
    }
  }

  if (choicesData.length === 0) {
    SpreadsheetApp.getUi().alert(`No relevant data found between ${monthDay(fullNamedRangesDict["GetSubmissionCutoff"])} (Print > Submission Cutoff) and ${monthDay(fullNamedRangesDict["GetDate"])} (Print > Date) using ${fullNamedRangesDict["GetSeatingChartSheets"]} (See Main > Sheet Settings > Seating Chart Sheet(s))`)
  }

  function padArray(raggedArray) {
    let maxLength = raggedArray.reduce((max, row) => Math.max(max, row.length), 0);

    // Pad the shorter rows with empty strings
    for (let i = 0; i < raggedArray.length; i++) {
      while (raggedArray[i].length < maxLength) {
        raggedArray[i].push('');
      }
    }

    return raggedArray;
  }
  choicesData = padArray(choicesData);
  mainSheet.getRange(choicesFullNamesHeader.row + 1, choicesFullNamesHeader.column, choicesData.length, choicesData[0].length).setValues(choicesData);

}

function printAndReset() {
  var dataToMove = fullNamedRangesDict["ConfirmPrintingData"];
  var assessment = fullNamedRangesDict["GetTitle"];
  var assessmentDate = monthDay(fullNamedRangesDict["GetDate"]);

  // Get all values in Column B to find the first empty cell
  var colBValues = printedSheet.getRange("B1:B" + printedSheet.getLastRow()).getValues();
  
  // Find the index of the first empty row
  // We default to the row after the last existing entry if no empty gaps are found
  var firstFreeRow = colBValues.length + 1; 
  for (var i = 0; i < colBValues.length; i++) {
    if (colBValues[i][0] === "") {
      firstFreeRow = i + 1;
      break;
    }
  }

  // Title goes in Column B (Index 2)
  var titleColumnRange = printedSheet.getRange(firstFreeRow, 2, dataToMove.length, 1);
  titleColumnRange.setValue(assessment);

  // Date goes in Column C (Index 3)
  var dateColumnRange = printedSheet.getRange(firstFreeRow, 3, dataToMove.length, 1);
  dateColumnRange.setValue(assessmentDate);

  // Data starts in Column D (Index 4)
  var destinationRange = printedSheet.getRange(firstFreeRow, 4, dataToMove.length, dataToMove[0].length);
  destinationRange.setValues(dataToMove);

  // Clear all data currently in the import destination range
  var choicesFullNamesHeader = findCellR1C1ByNamedRange("ChoicesPrintFullName");
  mainSheet.getRange(choicesFullNamesHeader.row + 1, choicesFullNamesHeader.column, Math.max(1, mainSheet.getLastRow() - choicesFullNamesHeader.row), mainSheet.getLastColumn() - choicesFullNamesHeader.column + 1).clearContent();

  // Clear some other settings
  ss.getRangeByName("GetTitle").clearContent();
  ss.getRangeByName("GetDate").clearContent();
  ss.getRangeByName("GetSubmissionCutoff").clearContent();
  ss.getRangeByName("GetExtrasAmount").setValue(0);
  ss.getRangeByName("GetKeyAmount").setValue(1);

  var simplyPrintLocation1 = findCellR1C1ByNamedRange("SimplyPrintTFStart");
  var noSubmissionsLocation1 = findCellR1C1ByNamedRange("NoSubmissionsTFStart");
  var appendLocation1 = findCellR1C1ByNamedRange("AppendTFStart");
  mainSheet.getRange(simplyPrintLocation1.row, simplyPrintLocation1.column, 1, mainSheet.getLastColumn() - simplyPrintLocation1.column + 1).setValue(false);
  mainSheet.getRange(noSubmissionsLocation1.row, noSubmissionsLocation1.column, 1, mainSheet.getLastColumn() - noSubmissionsLocation1.column + 1).setValue(false);
  mainSheet.getRange(appendLocation1.row, appendLocation1.column, 1, mainSheet.getLastColumn() - appendLocation1.column + 1).setValue(false);

}

// function testGetRow() {

// var sheet = ss.getSheets()[0];

// var range = sheet.getRange("B2");
// Logger.log(range.getRow());
// }