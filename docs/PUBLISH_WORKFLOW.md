# TAR automatic publishing workflow (prepared, NOT enabled)

Update 16 Oct 2026: re-proven. A cloud session pushed directly to main (no PR, no feature branch merge); Pages served the file in minutes; Buffer created and returned a LinkedIn PDF document draft from the Pages URLs. Master switch: config/auto-publish.json (enabled=false). Routine: TAR Auto-Publish 2:00 PM (disabled).

Status: integration proven with test files only. No real report has been scheduled.

## Proven
- Direct push to main works, so no pull request or manual merge is needed.
- GitHub Pages serves files from main at https://prashamdoshi1709-blip.github.io/tar-reports/.
- Buffer create_post with assets=[{document:{url,title,thumbnailUrl}}] and saveToDraft=true creates a LinkedIn PDF document draft; get_post reads it back (status draft, dueAt null).

## Publish steps (to run only after approval of AUTO-PUBLISH MODE)
1. Trading day check (Sydney date, ASX closures list). Stop if closed.
2. Find the latest PDF_DRAFT_COMPLETE marker and a RESEARCH-READY review for today. Stop if missing.
3. Publication QA: no NOT APPROVED text in the final PDF, title under 55 chars, disclaimer present, no em dashes, ticker/date match.
4. Newer ASX announcements check. FAIL CLOSED: if it cannot be confirmed reliably, do not schedule; alert.
5. Duplicate check: Buffer list_posts for the ticker and date (scheduled, sent, draft) plus a Drive "published" marker. Stop if found.
6. Push PDF and cover to main under reports/YYYY-MM-DD-TICKER/; wait until the Pages URL returns 200 (retry up to about 5 minutes).
7. Buffer create_post: schedulingType automatic, mode customScheduled, dueAt = 15:00 Australia/Sydney with explicit offset from zoneinfo (+11:00 until 4 Apr 2027, then +10:00; Buffer account zone is Brisbane, so never rely on it), document asset. Must be in the future; schedule by 14:30 latest.
8. Read back with get_post (status scheduled, correct dueAt, channel, title, caption). Write the Drive published marker.
9. 14:45 watchdog: confirm the post is still scheduled; alert otherwise.
Alerts: PushNotification (and Gmail if wanted).
