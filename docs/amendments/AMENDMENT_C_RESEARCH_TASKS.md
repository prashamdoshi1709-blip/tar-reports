# Amendment C (recommended, small): 11:15 AM "TAR Morning Source Review" and 12:30 PM fallback

Checked 27 Oct 2026 against the saved prompts: both already contain the newer-ASX verification (11:15 AM Revision 5; 12:30 PM Revision 6:
read every later and same-minute filing, never classify by title, NEEDS ATTENTION when unconfirmed, new review revision, no skip of a
previously reviewed package). Gaps that matter to the schema 3 handoff: (1) 11:15 AM does not require the FinancialFilings feed-freshness
proof (newest market item within 45 minutes) that the others use; (2) neither requires the review record to list each later/companion filing
with its ASX source_filing_id (digits) and UTC release time, nor a single machine-readable line the 1:15 PM and 1:58 PM stages can quote.

PASTE LOCATION: at the very end of EACH of the two prompts, after their last section. Nothing above is changed.

----- BEGIN AMENDMENT C (paste) -----
# PRIORITY UPDATE: MATERIAL FILINGS LEDGER IN THE REVIEW RECORD (contract material-filings/1)

1. FRESHNESS: before concluding anything about newer announcements run the FinancialFilings freshness proof (filings_list countries=AU ordering=-release_datetime page_size=1 release_datetime_from=<now minus 3 hours UTC>; newest market-wide item must be within 45 minutes of now). If not, write NEWER ANNOUNCEMENTS: NOT CONFIRMED and READINESS: NEEDS ATTENTION.
2. Every completed review record must contain a section "MATERIAL FILINGS LEDGER" listing the primary announcement and EVERY later or same-minute filing as: ASX source_filing_id (digits) | exact title | release time UTC (ends Z) | same minute as primary yes/no | class ROUTINE_ADMIN or MATERIAL | content actually read yes/no | for MATERIAL: reconciliation RECONCILED or NOT_APPLICABLE, what was compared, and any claim excluded with the reason.
3. Then one line exactly: "MATERIAL FILINGS ASSESSED IDS: <comma-separated ids of every MATERIAL filing, or NONE>" and one line "LATEST FILING CHECKED: <id> at <UTC time>, checked at <UTC time>".
4. If any filing in the ledger is unread, unclassified or unreconciled, READINESS must be NEEDS ATTENTION.
----- END AMENDMENT C -----
