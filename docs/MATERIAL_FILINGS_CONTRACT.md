# Material-filings handoff contract (schema 3, `material-filings/1`)

Added 27 Oct 2026. Code: `tools/filing_contract.py` (validator), used by `tools/buffer_schedule.py`; tests: `tools/test_filing_contract.py`
(also run by the `verifytest` manual mode of the TAR Buffer Schedule workflow).

## Root cause
Schema 2 had a single boolean, `claude_verification.newer_asx_filings_none_material`, which `buffer_schedule.py` required (with seven
others) to be `true`. There was no way to say "a material filing exists and was fully assessed". The 1:15 PM marker's `qa.later_filings`
and the 1:58 PM Step 4 both collapsed every material later filing into a hard stop, and Revision 7 of the 1:58 PM prompt told Claude to
stop with `BLOCKED: MATERIAL_FILING_HANDOFF_CONTRACT`. The flag was the only enforcement point (`buffer_schedule.py` payload hygiene).

## Four cases
| Case | outcome | legacy flag `newer_asx_filings_none_material` | Result |
|---|---|---|---|
| A no newer/companion filings | `NONE` | true | publish |
| B routine admin only, all read and classified | `ROUTINE_ONLY` | true | publish |
| C material filing fully assessed and incorporated | `MATERIAL_ASSESSED` | **false** (never true) | publish (schema 3 only, when the gate is open) |
| D unread / unassessed / unresolved / stale / mismatched | n/a | n/a | STOP with a coded blocker |

## Schema versions
* **Schema 2**: unchanged. All eight flags true. Historical handoffs (CGF 19 Oct, TUA 26 Oct) remain valid. Routines keep writing schema 2 for cases A and B.
* **Schema 3**: schema 2 keys, plus `claude_verification.material_filings_assessed_and_incorporated` (must equal outcome == MATERIAL_ASSESSED) and a `filing_verification` object (see `filing_contract.py` docstring and `docs/amendments/AMENDMENT_B_1_58PM.md` for the exact fields). Unknown schemas and unknown contract versions are rejected.

## What GitHub verifies, and what it does not
Verifies mechanically: schema/fields/types; outcome vs filing classes vs legacy flag (no false true); numeric unique announcement ids, the
primary not repeated; timestamps parse and order (primary <= filings; stage 1:15 <= stage 1:58 <= verified <= handoff); same-minute flags match
the timestamps; feed fresh (newest item within 45 min of the check); `review_record_id` equals the review reference everywhere and the review is
COMPLETE, RESEARCH-READY with no unresolved issues and lists exactly the material ids; marker hash equality; both stages attested; every
`report_evidence` phrase appears in the committed caption and in the text of the committed PDF. All existing checks are untouched (PDF SHA-256,
title metadata, 2 pages, public Pages check, duplicate checks, 3:00 PM slot, cutoff, master switch, fail-closed).
**Does not verify**: that the ASX filings were actually read, that the materiality classification is right, that figures reconcile, or that
the evidence phrase is a correct statement. Those are Claude's attestations (printed in the run log as `ATTESTATION LIMIT`).

## Gate
`config/auto-publish.json` -> `material_filings_contract.schema3_accepted` is **false** by default. While false a schema 3 handoff is held
(`SCHEMA3_BLOCKED`, transient: retried until the 2:45 PM cutoff, never published). Set it true only after Amendments A and B are pasted into the
1:15 PM and 1:58 PM tasks and verified. Schema 2 is unaffected by the gate.

## Blocker codes
UNRECOGNISED_SCHEMA, UNRECOGNISED_CONTRACT, MISSING_FIELD, BAD_OUTCOME, BAD_TIMESTAMP, BAD_ANNOUNCEMENT_ID, INCONSISTENT_ID, CONTRADICTION,
FLAGS_NOT_TRUE, LEGACY_FLAGS, STALE_FEED, PRIMARY_UNREAD, FILING_UNREAD, UNCLASSIFIED, SAME_MINUTE_FLAG, UNRESOLVED, NOT_INCORPORATED,
NO_REPORT_EVIDENCE, EXCLUSION_UNDOCUMENTED, REVIEW_REF_MISMATCH, REVIEW_NOT_READY, REVIEW_NOT_COMPLETE, STAGE_UNCHECKED, STAGE_ORDER,
MARKER_MISMATCH, EVIDENCE_NOT_IN_REPORT, EVIDENCE_NOT_IN_PDF.
