# Amendment B: 1:58 PM routine "TAR Auto-Publish 3PM"

PASTE LOCATION: open the scheduled task "TAR Auto-Publish 3PM" (1:58 PM, weekdays), scroll to the VERY END of its prompt (after
the "FINAL REQUIREMENT" section of REVISION 7), add a blank line and paste everything between the two lines below. Do not edit
anything above it. This REPLACES the "BLOCKED: MATERIAL_FILING_HANDOFF_CONTRACT" instruction in Revision 7 section 2, and only that.

----- BEGIN AMENDMENT B (paste) -----
# PRIORITY UPDATE: REVISION 8 - MATERIAL FILINGS HANDOFF CONTRACT (schema 3, material-filings/1)

GitHub Actions now understands handoff schema 3. This amendment replaces the "BLOCKED: MATERIAL_FILING_HANDOFF_CONTRACT" stop in Revision 7 section 2 ONLY. All other rules stand: the 2:20 PM deadline, SILENT MODE, no Buffer writes, never fetching github.io, PDF title format, sha256 checks, master switch, duplicate checks, "no workaround if permission is denied", "never set a flag true that was not verified".

A. DECIDE THE OUTCOME in Step 4 (after the freshness proof and after reading every later AND same-minute companion filing's actual content):
 - NONE: no later or companion filings.
 - ROUTINE_ONLY: all are ROUTINE_ADMIN as defined in Step 4(d), each read.
 - MATERIAL_ASSESSED: at least one is MATERIAL AND all of the following hold, each re-checked HERE independently of the 1:15 PM task: the marker contains qa.material_filings with contract "material-filings/1" and matching outcome; every filing the feed shows after the primary (and same minute) appears in it with the same announcement_id, title and release time; you read each material filing yourself; the LATEST review revision (highest number) is COMPLETE and RESEARCH-READY, explicitly assesses each material filing and lists no unresolved issue; conflicting figures are reconciled; excluded claims have documented reasons; every report_evidence phrase appears verbatim in CAPTION_FINAL and in the pdftotext of the final PDF (you check this yourself); the PDF and caption make no claim the filings contradict.
 - Otherwise STOP silently, exactly as Revision 6 did for POTENTIALLY_MATERIAL, and record the precise blocker: MATERIAL_FILING_UNREAD, MATERIAL_FILING_UNASSESSED, MATERIAL_FILING_UNRECONCILED, MATERIAL_FILING_NOT_IN_REPORT, FEED_STALE, REVIEW_NOT_LATEST_READY or MARKER_EVIDENCE_MISSING (marker has no qa.material_filings for a material filing).

B. WHICH SCHEMA TO WRITE (Step 7). Keep EXACTLY the current schema 2 handoff for outcomes NONE and ROUTINE_ONLY (all eight flags true, no new fields) because that path is proven. Write SCHEMA 3 ONLY for outcome MATERIAL_ASSESSED.

C. SCHEMA 3 publish.json = every schema 2 key, with "schema": 3, plus:
 - claude_verification: the SEVEN other flags true as before; "newer_asx_filings_none_material": false (a material filing exists; NEVER true here); and new "material_filings_assessed_and_incorporated": true.
 - "filing_verification": {
     "contract": "material-filings/1", "outcome": "MATERIAL_ASSESSED",
     "feed": {"fresh": true, "complete": true, "checked_at_utc": <your freshness proof time, UTC, Z>, "newest_item_utc": <newest market-wide ASX item, Z>},
     "primary": {"announcement_id": <marker.primary_announcement.source_filing_id>, "title": <exact>, "release_datetime_utc": <Z>, "content_read": true},
     "filings": [ one object per later/same-minute filing, built from YOUR OWN Step 4 reading and cross-checked against the marker: announcement_id, title, release_datetime_utc, same_minute_as_primary, class, content_read true, classification_rationale, assessed_at_utc, and for MATERIAL ones reconciliation (+ reconciliation_notes when RECONCILED), incorporated_in_report true, report_evidence (verbatim phrases you verified), review_ref (= review_record_id), excluded_claims ],
     "review": {"record_id": <review_record_id>, "readiness": "RESEARCH-READY", "status": "COMPLETE", "revision": <latest>, "material_filings_assessed_ids": [<ids of every MATERIAL filing>], "unresolved_issues": []},
     "stage_1_15": {"checked_at_utc": <marker.qa.material_filings.stage_1_15_checked_at_utc>, "all_conditions_met": <marker.qa.material_filings.stage_1_15_all_conditions_met, must be true>, "marker_sha256": <same value as the handoff marker_sha256>},
     "stage_1_58": {"checked_at_utc": <now UTC, Z>, "all_conditions_met": true},
     "verified_at_utc": <now UTC, Z, not later than handoff_created_at>, "attestation_acknowledged": true }
 All timestamps in filing_verification are UTC ending in Z. announcement_id values are the ASX source_filing_id digits. Do not fabricate or approximate any value; copy from FinancialFilings, the marker and the review record. Order must hold: stage_1_15 <= stage_1_58 <= verified_at_utc <= handoff_created_at.

D. SAFETY. GitHub only checks that this record is complete, internally consistent and that the report text contains the claimed evidence; it does NOT open ASX documents, so your reading and assessment ARE the safeguard. If anything is uncertain write NO handoff. GitHub also keeps schema 3 switched off until config/auto-publish.json material_filings_contract.schema3_accepted is true (set by the repository owner after this amendment is verified); a schema 3 handoff written earlier is simply held and retried until the 2:45 PM cutoff, never published. Never edit config/auto-publish.json, the workflow or tools/ from this routine.

E. TEST HANDOFF MODE: the SGR rehearsal may build the schema 3 JSON in memory and print it, but must not commit it.
----- END AMENDMENT B -----
