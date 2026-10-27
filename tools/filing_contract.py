#!/usr/bin/env python3
"""TAR material-filings handoff contract, "material-filings/1" (publish.json schema 3). stdlib only.

WHY: schema 2 had one boolean, claude_verification.newer_asx_filings_none_material, that had to be true. A company that
publishes another material filing after (or in the same minute as) its primary announcement could therefore never be
published, even when research had already read, reconciled and incorporated it. Schema 3 replaces that single boolean
with a structured, checkable record (the `filing_verification` object) that separates four situations:

  A  outcome NONE               no newer / companion filings, feed fresh and complete
  B  outcome ROUTINE_ONLY       only routine administrative filings, each read and classified
  C  outcome MATERIAL_ASSESSED  at least one material filing, fully read, assessed, reconciled and incorporated
  D  anything else              MISSING / UNREAD / UNASSESSED / UNRESOLVED -> this module raises ContractError (STOP)

SCHEMA 2 IS UNCHANGED: still accepted exactly as before (all 8 flags true). Schema 3 is the only way to express C.
The legacy flag may never be falsely true: in schema 3 it must equal (outcome in {NONE, ROUTINE_ONLY}).

WHAT THIS MODULE CAN AND CANNOT PROVE (explicit by design):
  * It CANNOT open ASX documents. It does not independently verify that a filing was read, that the materiality
    classification is right, or that figures reconciled. Those are ATTESTATIONS by the 1:15 PM and 1:58 PM Claude stages.
  * It DOES mechanically check: schema and field presence/types; internal consistency (outcome vs classes vs flags);
    unique, well-formed announcement ids; parseable, ordered timestamps; same-minute companion flags match the
    timestamps; the review reference equals the handoff's review_record_id; every material filing is listed in the
    review's assessed ids; no unresolved issue; both stages independently attested; the freshness proof; and that each
    material filing's claimed `report_evidence` strings really appear in the committed caption or in the text of the
    committed PDF (check_report_evidence). That last check proves the report mentions the claimed implication, not that the
    implication is correct.
"""
import re
from datetime import datetime, timedelta, timezone

CONTRACT = "material-filings/1"
SCHEMA = 3
OUTCOMES = ("NONE", "ROUTINE_ONLY", "MATERIAL_ASSESSED")
CLASSES = ("ROUTINE_ADMIN", "MATERIAL")
RECONCILED_OK = ("NOT_APPLICABLE", "RECONCILED")          # anything else (UNRESOLVED, PENDING, ...) stops
FRESHNESS_MAX = timedelta(minutes=45)                       # same rule the 1:58 PM routine already applies
LEGACY_OTHER_FLAGS = ["marker_hashes_match", "review_research_ready", "source_checks_passed", "verify_clean_pdf_pass",
                      "visual_check_done", "buffer_duplicate_check_clear", "master_switch_enabled"]
LEGACY_FLAG = "newer_asx_filings_none_material"
ATTESTATION_NOTICE = ("ATTESTATION LIMIT: GitHub Actions checked the structure, internal consistency, review reference and "
                      "report text evidence of the filing record. It did NOT open or independently verify the ASX filings; "
                      "that they were read, classified and reconciled is Claude's attestation.")
ID_RE = re.compile(r"\d{6,12}")


class ContractError(Exception):
    """Case D: a precise blocker. `.code` is a stable machine-readable reason."""
    def __init__(self, code, msg):
        super().__init__(f"{code}: {msg}")
        self.code, self.msg = code, msg


def _bad(code, msg):
    raise ContractError(code, msg)


def _ts(v, what):
    if not isinstance(v, str) or not v.endswith("Z"):
        _bad("BAD_TIMESTAMP", f"{what} must be an ISO-8601 UTC string ending in Z, got {v!r}")
    try:
        return datetime.fromisoformat(v[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError:
        _bad("BAD_TIMESTAMP", f"{what} is not a valid timestamp: {v!r}")


def _s(d, k, where, minlen=1):
    v = d.get(k)
    if not isinstance(v, str) or len(v.strip()) < minlen:
        _bad("MISSING_FIELD", f"{where}.{k} missing or too short")
    return v


def _announcement(d, where):
    if not isinstance(d, dict):
        _bad("MISSING_FIELD", f"{where} must be an object")
    aid = _s(d, "announcement_id", where)
    if not ID_RE.fullmatch(aid):
        _bad("BAD_ANNOUNCEMENT_ID", f"{where}.announcement_id {aid!r} is not a numeric ASX id")
    _s(d, "title", where)
    return aid, _ts(d.get("release_datetime_utc"), f"{where}.release_datetime_utc")


def validate_legacy(P):
    """Schema 2: identical to the pre-existing behaviour (all eight flags must be true)."""
    cv = P.get("claude_verification")
    need = LEGACY_OTHER_FLAGS[:5] + [LEGACY_FLAG] + LEGACY_OTHER_FLAGS[5:]
    if not isinstance(cv, dict) or not all(cv.get(k) is True for k in need):
        _bad("LEGACY_FLAGS", "claude_verification flags are not all true: "
             + ",".join(k for k in need if not isinstance(cv, dict) or cv.get(k) is not True))
    return {"schema": 2, "outcome": "LEGACY_NONE_MATERIAL", "material": []}


def validate_v3(P):
    """Structural + consistency validation of a schema-3 handoff. Returns a summary dict or raises ContractError."""
    cv = P.get("claude_verification")
    if not isinstance(cv, dict):
        _bad("MISSING_FIELD", "claude_verification missing")
    bad = [k for k in LEGACY_OTHER_FLAGS if cv.get(k) is not True]
    if bad:
        _bad("FLAGS_NOT_TRUE", "claude_verification flags are not all true: " + ",".join(bad))
    fv = P.get("filing_verification")
    if not isinstance(fv, dict):
        _bad("MISSING_FIELD", "filing_verification object missing (schema 3 requires it)")
    if fv.get("contract") != CONTRACT:
        _bad("UNRECOGNISED_CONTRACT", f"filing_verification.contract must be {CONTRACT!r}, got {fv.get('contract')!r}")
    outcome = fv.get("outcome")
    if outcome not in OUTCOMES:
        _bad("BAD_OUTCOME", f"filing_verification.outcome must be one of {OUTCOMES}, got {outcome!r}")

    # the legacy flag may never be falsely true, and must be present and boolean in schema 3
    legacy = cv.get(LEGACY_FLAG)
    if not isinstance(legacy, bool):
        _bad("MISSING_FIELD", f"claude_verification.{LEGACY_FLAG} must be a boolean in schema 3")
    if legacy != (outcome in ("NONE", "ROUTINE_ONLY")):
        _bad("CONTRADICTION", f"{LEGACY_FLAG}={legacy} contradicts outcome {outcome} "
             "(it may be true only for NONE or ROUTINE_ONLY)")
    if cv.get("material_filings_assessed_and_incorporated") is not (outcome == "MATERIAL_ASSESSED"):
        _bad("CONTRADICTION", "claude_verification.material_filings_assessed_and_incorporated must be exactly "
             "(outcome == MATERIAL_ASSESSED)")

    # freshness proof (feed complete and current)
    fr = fv.get("feed")
    if not isinstance(fr, dict) or fr.get("fresh") is not True or fr.get("complete") is not True:
        _bad("STALE_FEED", "filing_verification.feed.fresh and .complete must both be true")
    checked, newest = _ts(fr.get("checked_at_utc"), "feed.checked_at_utc"), _ts(fr.get("newest_item_utc"), "feed.newest_item_utc")
    if checked - newest > FRESHNESS_MAX or newest > checked + timedelta(minutes=1):
        _bad("STALE_FEED", f"newest feed item {fr['newest_item_utc']} is not within 45 minutes of the check {fr['checked_at_utc']}")

    # primary announcement
    prim = fv.get("primary")
    pid, ptime = _announcement(prim, "primary")
    if prim.get("content_read") is not True:
        _bad("PRIMARY_UNREAD", "primary announcement content_read is not true")

    # review reference
    rv = fv.get("review")
    if not isinstance(rv, dict):
        _bad("MISSING_FIELD", "filing_verification.review missing")
    if rv.get("record_id") != P.get("review_record_id") or not rv.get("record_id"):
        _bad("REVIEW_REF_MISMATCH", f"review.record_id {rv.get('record_id')!r} != handoff review_record_id {P.get('review_record_id')!r}")
    if rv.get("readiness") != "RESEARCH-READY" or P.get("review_status") != "RESEARCH-READY":
        _bad("REVIEW_NOT_READY", "review.readiness and review_status must both be RESEARCH-READY")
    if rv.get("status") != "COMPLETE":
        _bad("REVIEW_NOT_COMPLETE", f"review.status must be COMPLETE, got {rv.get('status')!r}")
    if rv.get("unresolved_issues") != []:
        _bad("UNRESOLVED", f"review.unresolved_issues must be an empty list, got {rv.get('unresolved_issues')!r}")
    assessed_ids = rv.get("material_filings_assessed_ids")
    if not isinstance(assessed_ids, list) or not all(isinstance(x, str) for x in assessed_ids):
        _bad("MISSING_FIELD", "review.material_filings_assessed_ids must be a list of ids")
    if pid != (P.get("primary_announcement_id") or pid):
        _bad("INCONSISTENT_ID", "primary announcement id differs from handoff primary_announcement_id")

    # later / companion filings
    filings = fv.get("filings")
    if not isinstance(filings, list):
        _bad("MISSING_FIELD", "filing_verification.filings must be a list")
    seen, material = set(), []
    latest_assessed = None
    for i, f in enumerate(filings):
        w = f"filings[{i}]"
        fid, ftime = _announcement(f, w)
        if fid == pid:
            _bad("INCONSISTENT_ID", f"{w} repeats the primary announcement id {pid}")
        if fid in seen:
            _bad("INCONSISTENT_ID", f"{w} duplicates announcement id {fid}")
        seen.add(fid)
        if ftime < ptime:
            _bad("INCONSISTENT_ID", f"{w} ({fid}) is earlier than the primary; only newer or same-minute filings belong here")
        same_min = ftime.replace(second=0, microsecond=0) == ptime.replace(second=0, microsecond=0)
        if f.get("same_minute_as_primary") is not same_min:
            _bad("SAME_MINUTE_FLAG", f"{w} ({fid}) same_minute_as_primary={f.get('same_minute_as_primary')!r} does not match the timestamps")
        if f.get("class") not in CLASSES:
            _bad("UNCLASSIFIED", f"{w} ({fid}) class must be one of {CLASSES}, got {f.get('class')!r}")
        if f.get("content_read") is not True:
            _bad("FILING_UNREAD", f"{w} ({fid}) content_read is not true; its content was not actually read")
        _s(f, "classification_rationale", w, 12)
        at = _ts(f.get("assessed_at_utc"), f"{w}.assessed_at_utc")
        latest_assessed = at if latest_assessed is None else max(latest_assessed, at)
        if f["class"] == "MATERIAL":
            material.append(fid)
            if f.get("reconciliation") not in RECONCILED_OK:
                _bad("UNRESOLVED", f"{w} ({fid}) reconciliation is {f.get('reconciliation')!r}; figures must be RECONCILED (or NOT_APPLICABLE)")
            if f.get("reconciliation") == "RECONCILED":
                _s(f, "reconciliation_notes", w, 12)
            if f.get("incorporated_in_report") is not True:
                _bad("NOT_INCORPORATED", f"{w} ({fid}) incorporated_in_report is not true")
            ev = f.get("report_evidence")
            if not isinstance(ev, list) or not ev or not all(isinstance(x, str) and len(x.strip()) >= 6 for x in ev):
                _bad("NO_REPORT_EVIDENCE", f"{w} ({fid}) needs report_evidence: 1+ verbatim strings (6+ chars) that appear in the caption or PDF")
            if f.get("review_ref") != rv["record_id"]:
                _bad("REVIEW_REF_MISMATCH", f"{w} ({fid}) review_ref {f.get('review_ref')!r} != review.record_id {rv['record_id']!r}")
            ex = f.get("excluded_claims", [])
            if not isinstance(ex, list):
                _bad("MISSING_FIELD", f"{w}.excluded_claims must be a list")
            for j, c in enumerate(ex):
                if not isinstance(c, dict) or len(str(c.get("claim", "")).strip()) < 6 or len(str(c.get("reason", "")).strip()) < 20:
                    _bad("EXCLUSION_UNDOCUMENTED", f"{w}.excluded_claims[{j}] needs a claim and a documented reason (20+ chars)")
        else:
            if f.get("incorporated_in_report") not in (None, True, False):
                _bad("CONTRADICTION", f"{w} incorporated_in_report must be boolean or absent")

    # outcome vs contents
    if outcome == "NONE" and filings:
        _bad("CONTRADICTION", "outcome NONE but filings are listed")
    if outcome == "ROUTINE_ONLY" and (not filings or material):
        _bad("CONTRADICTION", "outcome ROUTINE_ONLY requires 1+ filings and none MATERIAL")
    if outcome == "MATERIAL_ASSESSED" and not material:
        _bad("CONTRADICTION", "outcome MATERIAL_ASSESSED requires at least one MATERIAL filing")
    if sorted(assessed_ids) != sorted(material):
        _bad("REVIEW_REF_MISMATCH", f"review.material_filings_assessed_ids {sorted(assessed_ids)} != material filings {sorted(material)}")

    # both stages independently checked
    for st in ("stage_1_15", "stage_1_58"):
        s = fv.get(st)
        if not isinstance(s, dict) or s.get("all_conditions_met") is not True:
            _bad("STAGE_UNCHECKED", f"filing_verification.{st}.all_conditions_met must be true")
        _ts(s.get("checked_at_utc"), f"{st}.checked_at_utc")
    s115, s158 = _ts(fv["stage_1_15"]["checked_at_utc"], ""), _ts(fv["stage_1_58"]["checked_at_utc"], "")
    if s158 < s115:
        _bad("STAGE_ORDER", "stage_1_58 check is earlier than stage_1_15 check")
    if fv["stage_1_15"].get("marker_sha256") != P.get("marker_sha256"):
        _bad("MARKER_MISMATCH", "stage_1_15.marker_sha256 does not equal the handoff marker_sha256")

    # verification timestamp must be after the checks and not after the handoff
    ver = _ts(fv.get("verified_at_utc"), "verified_at_utc")
    try:
        hand = datetime.fromisoformat(str(P.get("handoff_created_at")).replace("Z", "+00:00"))
        if hand.tzinfo is None:
            raise ValueError
        hand = hand.astimezone(timezone.utc)
    except ValueError:
        _bad("BAD_TIMESTAMP", f"handoff_created_at is not an ISO-8601 timestamp with offset: {P.get('handoff_created_at')!r}")
    if ver < s158 or (latest_assessed and ver < latest_assessed) or ver < checked:
        _bad("STAGE_ORDER", "verified_at_utc is earlier than the checks it summarises")
    if ver > hand + timedelta(minutes=1):
        _bad("STAGE_ORDER", "verified_at_utc is after handoff_created_at")
    if fv.get("attestation_acknowledged") is not True:
        _bad("MISSING_FIELD", "attestation_acknowledged must be true (the stages confirm this record is an attestation, not source proof)")
    return {"schema": 3, "outcome": outcome, "primary_id": pid, "material": material,
            "routine": [f["announcement_id"] for f in filings if f["class"] == "ROUTINE_ADMIN"]}


def validate(P):
    s = P.get("schema")
    if s == 2:
        return validate_legacy(P)
    if s == SCHEMA:
        return validate_v3(P)
    _bad("UNRECOGNISED_SCHEMA", f"schema {s!r} is not recognised (2 or 3 only)")


def _norm(t):
    return re.sub(r"\s+", " ", t.replace(" ", " ")).lower()


def check_report_evidence(P, caption, pdf_text):
    """Mechanical: each material filing's report_evidence string must occur in the caption or in the PDF text."""
    if P.get("schema") != SCHEMA:
        return
    hay_c, hay_p = _norm(caption), _norm(pdf_text)
    for f in P["filing_verification"]["filings"]:
        if f["class"] != "MATERIAL":
            continue
        miss = [e for e in f["report_evidence"] if _norm(e) not in hay_c and _norm(e) not in hay_p]
        if miss:
            _bad("EVIDENCE_NOT_IN_REPORT", f"filing {f['announcement_id']}: report_evidence not found in caption or PDF text: {miss}")
        if not any(_norm(e) in hay_p for e in f["report_evidence"]):
            _bad("EVIDENCE_NOT_IN_PDF", f"filing {f['announcement_id']}: none of its report_evidence appears in the PDF itself")


def gate_open(cfg):
    """Schema 3 stays blocked until config/auto-publish.json material_filings_contract.schema3_accepted is true,
    which is flipped only after the 1:15 PM and 1:58 PM routine instructions are updated AND verified."""
    g = cfg.get("material_filings_contract") if isinstance(cfg, dict) else None
    return isinstance(g, dict) and g.get("schema3_accepted") is True
