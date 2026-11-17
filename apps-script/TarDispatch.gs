/**
 * OPTIONAL add-on for the existing Vitti import Apps Script (script 5.2.x, which writes packages to "TAR Daily Sources").
 * It does not change the import. Every 5 minutes on weekday mornings it looks for today's newest package that has a
 * SOURCE_INDEX.json, and the first time it sees one it asks GitHub to start the "TAR Generate" workflow at once
 * (repository_dispatch "tar_package_ready"). Without it the workflow still runs from its own schedule every 10 minutes;
 * this only removes GitHub's cron delay.
 *
 * Setup (once): Apps Script editor > Project Settings > Script properties:
 *   GITHUB_DISPATCH_TOKEN  a fine-grained GitHub token for prashamdoshi1709-blip/tar-reports only,
 *                          permission "Contents: Read and write" (required by GitHub for repository_dispatch)
 *   TAR_ROOT_FOLDER_ID     1F9nfvK_OVBwMih6y74D1zJ94EKbW3N3C   (the "TAR Daily Sources" folder)
 * Then run installTarDispatchTrigger() once. Never put the token in this file.
 */
var TAR_REPO = 'prashamdoshi1709-blip/tar-reports';

function installTarDispatchTrigger() {
  ScriptApp.getProjectTriggers().forEach(function (t) {
    if (t.getHandlerFunction() === 'tarDispatchTick') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('tarDispatchTick').timeBased().everyMinutes(5).create();
}

function tarDispatchTick() {
  var tz = 'Australia/Sydney', now = new Date();
  var day = Utilities.formatDate(now, tz, 'u'), hhmm = Number(Utilities.formatDate(now, tz, 'HHmm'));
  if (Number(day) > 5 || hhmm < 1000 || hhmm > 1440) return;            // weekdays 10:00-14:40 Sydney only
  var props = PropertiesService.getScriptProperties();
  var token = props.getProperty('GITHUB_DISPATCH_TOKEN'), rootId = props.getProperty('TAR_ROOT_FOLDER_ID');
  if (!token || !rootId) return;
  var today = Utilities.formatDate(now, tz, 'yyyy-MM-dd');
  if (props.getProperty('TAR_DISPATCHED_' + today)) return;             // one dispatch per day is enough
  var it = DriveApp.getFolderById(rootId).searchFolders('title contains "' + today + '_"');
  while (it.hasNext()) {
    var f = it.next();
    if (!/^\d{4}-\d{2}-\d{2}_\d{4}_[0-9a-f]{8,}_a\d+$/.test(f.getName())) continue;
    if (!f.getFilesByName('SOURCE_INDEX.json').hasNext()) continue;      // import still writing
    var r = UrlFetchApp.fetch('https://api.github.com/repos/' + TAR_REPO + '/dispatches', {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      headers: { Authorization: 'Bearer ' + token, Accept: 'application/vnd.github+json' },
      payload: JSON.stringify({ event_type: 'tar_package_ready' })   // no package details: the workflow reads Drive itself
    });
    if (r.getResponseCode() === 204) props.setProperty('TAR_DISPATCHED_' + today, f.getName());
    else console.warn('TAR dispatch failed: HTTP ' + r.getResponseCode());
    return;
  }
}
