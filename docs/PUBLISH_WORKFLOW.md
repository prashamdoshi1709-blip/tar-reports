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

## Clean-PDF verification (added 16 Oct 2026)
`tools/verify_clean_pdf.py <pdf> <expected title>` must print PASS before any file is committed to Pages or sent to Buffer.
It checks: exactly 2 pages of 810 x 1012.5 pt; no "NOT APPROVED" / "approved for publication" / "DRAFT" in page text (also with spaces removed, to catch letter-spaced banners), in the Info dictionary, in XMP, or anywhere in the decompressed raw file; no em dashes; Lora and Inter embedded; PDF Title equals the expected clean title.
`tar_lib.build()` defaults the PDF title to "TAR NOT APPROVED FOR PUBLICATION", so the clean rebuild must call it with an explicit title: `<Company> (ASX: <TICKER>) - <short headline>`. The HTML `<title>` must be replaced too.

## Scheduled GitHub Actions publishing (20 Oct 2026, replaces direct Buffer publication by the routine)
The 1:58 PM routine does all research/ASX/clean-PDF verification, pushes the PDF and cover to reports/<date>-<TICKER>/ (as before), waits for Pages, then commits ONE handoff file reports/<date>-<TICKER>/publish.json (schema 2). It never calls Buffer to publish.
The workflow "TAR Buffer Schedule" runs on GitHub's timezone-aware schedule (Australia/Sydney) at 2:17 PM and 2:24 PM on weekdays and only acts on today's publish.json.
Handoff fields (all required): schema 2, mode LIVE, ticker, company_name, report_date ("20 October 2026"), report_date_iso, package_id, review_record_id, review_status "RESEARCH-READY", marker_sha256, handoff_created_at, pdf_sha256, pdf_url, cover_url, title (<55 chars), caption, claude_verification{marker_hashes_match, review_research_ready, source_checks_passed, verify_clean_pdf_pass, visual_check_done, newer_asx_filings_none_material, buffer_duplicate_check_clear, master_switch_enabled} all true.
The script re-verifies: date is today in Sydney, ASX trading day, config/auto-publish.json enabled, committed PDF hash and tools/verify_clean_pdf.py PASS, URLs live with the same hash, title/caption rules, then reads Buffer. An identical existing post is success (no second post); any other conflict stops; an uncertain createPost is never retried (Buffer is re-read). Cutoff 2:30 PM, slot 3:00 PM +11:00/+10:00 from zoneinfo.
Manual runs (workflow_dispatch) can only do selftest or dryrun; they never create posts. Failures in scheduled mode are silent (green run, reason in a warning annotation).
