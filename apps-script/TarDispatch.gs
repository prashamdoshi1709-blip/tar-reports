/**
 * TAR dispatcher (REV 2, 23 Nov 2026). PRIMARY trigger for daily publication. Add it as a second file in the existing
 * Vitti import Apps Script project; it does not change the import.
 *
 * Why: GitHub's own schedule is best effort and on this repository fired about once a day, after the start deadline
 * (18-20 Nov were missed). Apps Script time triggers run reliably next to the Drive import, so they start the GitHub
 * workflow instead. GitHub's schedule stays as a backup.
 *
 * Every 5 minutes on weekdays (Sydney time):
 *   10:00-14:40  if today's Drive package is COMPLETE (same rule as tar_gen/source.py package_complete) and main has no
 *                report folder for today: start "TAR Generate" mode run. Repeats at most every 10 minutes and at most
 *                MAX_RUNS times a day, so a stuck day costs a handful of free runs, never a loop.
 *   15:20-17:40  start mode watchdog (one alert per day if there is no confirmed LinkedIn post; its completion also
 *                lets the publisher reconcile Buffer). At most once per 20 minutes and only until the day's
 *                status.json is final.
 * If GitHub refuses the request (expired or wrong token), it emails the script owner once per day.
 * Nothing about the package (company, ticker, figures) is sent to GitHub: the workflow reads Drive itself.
 *
 * Setup, once (browser only): Project Settings > Script properties
 *   GITHUB_DISPATCH_TOKEN  fine-grained GitHub token, repository prashamdoshi1709-blip/tar-reports only, permissions
 *                          "Actions: Read and write" and "Contents: Read-only"
 *   TAR_ROOT_FOLDER_ID     1F9nfvK_OVBwMih6y74D1zJ94EKbW3N3C   (the "TAR Daily Sources" folder)
 * then select installTarDispatchTrigger in the editor and press Run (approve the permissions it asks for).
 * Never put the token in this file.
 */
var TAR_REPO = 'prashamdoshi1709-blip/tar-reports';
var TAR_WORKFLOW = 'tar-generate.yml';
var TAR_TZ = 'Australia/Sydney';
var MAX_RUNS = 8;            // generator dispatches per day
var RUN_GAP_MIN = 10;        // minutes between generator dispatches
var WATCH_GAP_MIN = 20;      // minutes between watchdog dispatches
var READY_STATES = ['AWAITING_VERIFICATION', 'VERIFIED', 'READY'];
var NOT_READY_OK_SHAPES = ['PDF_LINKS_NO_ZIP'];

function installTarDispatchTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'tarDispatchTick') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('tarDispatchTick').timeBased().everyMinutes(5).create();
  tarDispatchTick();
}

/** Same rule as tar_gen/source.py package_complete(): never start on a package the import has not finished. */
function tarPackageComplete_(idx) {
  var st = String(idx.status || '').toUpperCase(), dm = idx.daily_mover || {};
  if (st === 'NOT_READY') { if (NOT_READY_OK_SHAPES.indexOf(idx.import_shape) < 0) return false; }
  else if (READY_STATES.indexOf(st) < 0) return false;
  if (dm.status !== 'found' || !dm.drive_file_id) return false;
  if (dm.saved === false || dm.size_verified === false) return false;
  return true;
}

function tarCompletePackageToday_(rootId, today) {
  var it = DriveApp.getFolderById(rootId).searchFolders('title contains "' + today + '_"');
  while (it.hasNext()) {
    var f = it.next();
    if (!/^\d{4}-\d{2}-\d{2}_\d{4}_[0-9a-f]{8,}_a\d+$/.test(f.getName()) || f.getName().indexOf(today) !== 0) continue;
    var files = f.getFilesByName('SOURCE_INDEX.json');
    if (!files.hasNext()) continue;                                   // import still writing
    try { if (tarPackageComplete_(JSON.parse(files.next().getBlob().getDataAsString()))) return true; }
    catch (e) { /* half-written index: try again next tick */ }
  }
  return false;
}

function tarGithub_(token, method, path, body) {
  var opt = { method: method, muteHttpExceptions: true,
              headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json',
                         'X-GitHub-Api-Version': '2022-11-28' } };
  if (body) { opt.contentType = 'application/json'; opt.payload = JSON.stringify(body); }
  return UrlFetchApp.fetch('https://api.github.com/repos/' + TAR_REPO + path, opt);
}

/** The report folders on main for today (names only), or null if GitHub could not be read. */
function tarReportsToday_(token, today) {
  var r = tarGithub_(token, 'get', '/contents/reports?ref=main');
  if (r.getResponseCode() !== 200) return null;
  return JSON.parse(r.getContentText()).filter(function (e) { return e.type === 'dir' && e.name.indexOf(today + '-') === 0; })
    .map(function (e) { return e.name; });
}

function tarStatusFinal_(token, folder) {
  var r = tarGithub_(token, 'get', '/contents/reports/' + folder + '/status.json?ref=main');
  if (r.getResponseCode() !== 200) return false;
  try { return JSON.parse(Utilities.newBlob(Utilities.base64Decode(JSON.parse(r.getContentText()).content)).getDataAsString()).final === true; }
  catch (e) { return false; }
}

function tarDispatch_(token, mode, props, today) {
  var r = tarGithub_(token, 'post', '/actions/workflows/' + TAR_WORKFLOW + '/dispatches', { ref: 'main', inputs: { mode: mode } });
  if (r.getResponseCode() === 204) return true;
  console.warn('TAR dispatch (' + mode + ') failed: HTTP ' + r.getResponseCode());
  tarAlertOnce_(props, today, 'GitHub refused the TAR dispatch (HTTP ' + r.getResponseCode() + '). If this is 401 or 403, '
    + 'the GITHUB_DISPATCH_TOKEN script property has expired or lacks "Actions: Read and write": create a new fine-grained '
    + 'token and replace the property. GitHub\'s own backup schedule still runs meanwhile.');
  return false;
}

function tarAlertOnce_(props, today, msg) {
  if (props.getProperty('TAR_ALERTED_' + today)) return;
  props.setProperty('TAR_ALERTED_' + today, '1');
  try { MailApp.sendEmail(Session.getEffectiveUser().getEmail(), 'TAR dispatcher problem ' + today, msg); } catch (e) { console.warn(e); }
}

function tarDispatchTick() {
  var now = new Date(), props = PropertiesService.getScriptProperties();
  var dow = Number(Utilities.formatDate(now, TAR_TZ, 'u')), hhmm = Number(Utilities.formatDate(now, TAR_TZ, 'HHmm'));
  if (dow > 5 || hhmm < 1000 || hhmm > 1740) return;                 // weekdays only; holidays are skipped by the workflow
  var token = props.getProperty('GITHUB_DISPATCH_TOKEN'), rootId = props.getProperty('TAR_ROOT_FOLDER_ID');
  if (!token || !rootId) return;
  var today = Utilities.formatDate(now, TAR_TZ, 'yyyy-MM-dd'), mins = now.getTime() / 60000;

  if (hhmm <= 1440) {
    var n = Number(props.getProperty('TAR_RUNS_' + today) || 0), last = Number(props.getProperty('TAR_LAST_RUN_' + today) || 0);
    if (n >= MAX_RUNS || mins - last < RUN_GAP_MIN) return;
    if (!tarCompletePackageToday_(rootId, today)) return;             // incomplete packages never start anything
    var have = tarReportsToday_(token, today);
    if (have === null || have.length) return;                         // a report exists (or GitHub unreadable): nothing to do
    if (tarDispatch_(token, 'run', props, today)) {
      props.setProperty('TAR_RUNS_' + today, String(n + 1));
      props.setProperty('TAR_LAST_RUN_' + today, String(mins));
    }
    return;
  }
  if (hhmm >= 1520) {
    var lastW = Number(props.getProperty('TAR_LAST_WATCH_' + today) || 0);
    if (mins - lastW < WATCH_GAP_MIN) return;
    var rep = tarReportsToday_(token, today);
    if (rep && rep.length && tarStatusFinal_(token, rep[0])) return;  // published (or finally failed and alerted)
    if (tarDispatch_(token, 'watchdog', props, today)) props.setProperty('TAR_LAST_WATCH_' + today, String(mins));
  }
}

/** Optional housekeeping: delete per-day properties older than a week. Safe to run any time. */
function tarCleanupProperties() {
  var props = PropertiesService.getScriptProperties(), keys = props.getKeys(), cutoff = new Date(Date.now() - 7 * 864e5);
  keys.forEach(function (k) {
    var m = /^TAR_[A-Z_]+_(\d{4}-\d{2}-\d{2})$/.exec(k);
    if (m && new Date(m[1]) < cutoff) props.deleteProperty(k);
  });
}
