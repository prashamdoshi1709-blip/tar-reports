# Amendment A: 1:15 PM task "TAR Daily PDF & LinkedIn Draft"

PASTE LOCATION: open the scheduled task "TAR Daily PDF & LinkedIn Draft" (1:15 PM, weekdays), scroll to the VERY END of its
prompt (after the last line of "REVISION 10"), add a blank line and paste everything between the two lines below.
Do not delete or edit anything above it. It overrides only the points it names.

----- BEGIN AMENDMENT A (paste) -----
# PRIORITY UPDATE: REVISION 11 - MATERIAL FILINGS EVIDENCE (contract material-filings/1)

This amendment overrides conflicting text in Revision 10 and earlier ONLY where it says so. Every folder id, renderer hash rule, canonical company-name rule, PDF size (810 x 1012.5 pt, 2 pages), PDF title convention and existing marker field name and meaning is UNCHANGED. Do not rename or repurpose any existing marker field.

1. CLASSIFY EVERY NEWER OR SAME-MINUTE FILING. In Step 9's qa.later_filings list include EVERY company filing released after the primary announcement AND every companion filing released in the SAME MINUTE (investor presentation, Appendix 4C, results release, etc.). Read each filing's actual content and set class to exactly one of ROUTINE_ADMIN or MATERIAL (no other values). Existing class values you already use for routine items stay valid. A filing whose content cannot be read is NOT classified: record it in qa.unread_filings and treat the draft as blocked (see 4).

2. A MATERIAL FILING IS NOT ROUTINE. Never label a MATERIAL filing ROUTINE_ADMIN or CONFIRMED_NONE_MATERIAL. qa.newer_announcements must reflect the truth: "NONE", "ROUTINE_ONLY" or "MATERIAL_PRESENT".

3. NEW ADDITIVE MARKER BLOCK. Add this object to the marker as qa.material_filings (new key; nothing else moves):
{
  "contract": "material-filings/1",
  "outcome": "NONE" | "ROUTINE_ONLY" | "MATERIAL_ASSESSED",
  "feed": {"fresh": true, "complete": true, "checked_at_utc": "<date -u ISO, ends Z>", "newest_item_utc": "<newest market-wide ASX item, ends Z>"},
  "filings": [ one object per later or same-minute filing:
    {"announcement_id": "<source_filing_id, digits>", "title": "<exact>", "release_datetime_utc": "<ends Z>",
     "same_minute_as_primary": true|false, "class": "ROUTINE_ADMIN"|"MATERIAL", "content_read": true,
     "classification_rationale": "<12+ chars, what the content showed>", "assessed_at_utc": "<ends Z>",
     and, ONLY for class MATERIAL:
     "reconciliation": "NOT_APPLICABLE"|"RECONCILED", "reconciliation_notes": "<which figures were compared and how conflicts were settled>",
     "incorporated_in_report": true, "report_evidence": ["<1+ VERBATIM phrases (6+ chars) copied from the final caption AND the PDF that carry this filing's implication>"],
     "review_ref": "<the marker's review_record id>",
     "excluded_claims": [{"claim": "...", "reason": "<documented reason, 20+ chars>"}] } ],
  "review": {"record_id": "<review_record id>", "readiness": "RESEARCH-READY", "status": "COMPLETE", "revision": <latest revision number>,
             "material_filings_assessed_ids": [<announcement_id of every MATERIAL filing>], "unresolved_issues": []},
  "stage_1_15_checked_at_utc": "<ends Z>", "stage_1_15_all_conditions_met": true
}
Rules: set outcome "MATERIAL_ASSESSED" only if (a) the LATEST review revision (highest number, even if incomplete) says RECORD STATUS: COMPLETE and READINESS: RESEARCH-READY, (b) that review explicitly assesses each material filing, (c) conflicting or updated figures were reconciled, (d) the HTML/caption you built reflect the implications and every report_evidence phrase appears verbatim in BOTH the caption and the PDF text, (e) nothing is unresolved. Never write a report_evidence phrase you have not found in the files. Never invent a filing id, time, reconciliation or review reference; copy them from FinancialFilings and the review record.

4. BLOCK, DO NOT GUESS. If any filing is unread/unclassified, any conflict is unreconciled, the review is not the latest COMPLETE RESEARCH-READY revision, the feed is stale (newest market item older than 45 min), or a material filing is not yet reflected in the report: do NOT write PDF_DRAFT_COMPLETE.json; write the usual BLOCKED diagnostic with one of: MATERIAL_FILING_UNREAD, MATERIAL_FILING_UNASSESSED, MATERIAL_FILING_UNRECONCILED, MATERIAL_FILING_NOT_IN_REPORT, FEED_STALE, REVIEW_NOT_LATEST_READY.

5. When there are no later or companion filings, still write qa.material_filings with outcome "NONE" and "filings": []. When all are routine, outcome "ROUTINE_ONLY". Existing markers without qa.material_filings remain valid for the old schema-2 path.
----- END AMENDMENT A -----
