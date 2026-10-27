#!/usr/bin/env python3
"""Offline tests for the material-filings handoff contract (tools/filing_contract.py) and its use in buffer_schedule.py.

READ-ONLY with respect to production: no network, no Buffer call (gql is replaced by a recorder that FAILS the test if
createPost is ever called), no LinkedIn post, no live handoff is created. Fixtures live only in temp directories.

FIXTURE HONESTY: the Star Entertainment Group (SGR) scenarios use the REAL ASX announcement ids, titles and release times
of the 26/27 Oct 2026 SGR filings (as recorded from the filings feed). Every ASSESSMENT in them (class, content_read,
rationale, reconciliation, review ids, stage timestamps, report_evidence) is SYNTHETIC test data: no research review for
SGR was produced under this contract, and none is claimed. Historical schema-2 tests use the real committed handoffs.
"""
import contextlib, copy, importlib.util, io, json, os, shutil, subprocess, sys, tempfile
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
import filing_contract as fc  # noqa: E402

results = []


def record(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def blocked(P, code):
    """True if validation raises ContractError with exactly this code."""
    try:
        fc.validate(P)
    except fc.ContractError as e:
        return e.code == code, f"{e.code}: {e.msg}"[:100]
    return False, "accepted (expected " + code + ")"


def accepted(P):
    try:
        return True, str(fc.validate(P))[:100]
    except fc.ContractError as e:
        return False, f"{e.code}: {e.msg}"[:100]


CGF = os.path.join(ROOT, "reports", "2026-10-19-CGF")
BASE = json.load(open(os.path.join(CGF, "publish.json"), encoding="utf-8"))  # handoff_created_at 2026-10-19T14:05+11:00 = 03:05Z

# ---- SGR: real ids/titles/times, synthetic assessment (see module docstring)
SGR_PRIMARY = dict(announcement_id="03157578", title="Quarterly Activities/Appendix 4C Cash Flow Report",
                   release_datetime_utc="2026-10-26T22:22:00Z", content_read=True)
SGR_AGM_ADDR = dict(announcement_id="03157633", title="2026 AGM Chairman and CEO Addresses", release_datetime_utc="2026-10-26T22:48:00Z")
SGR_LAPSE = dict(announcement_id="03157659", title="Lapsing of Executive Performance Rights", release_datetime_utc="2026-10-26T23:01:00Z")
SGR_CESS = dict(announcement_id="03157660", title="Notification of cessation of securities - SGR", release_datetime_utc="2026-10-26T23:02:00Z")


def v3(outcome="NONE", filings=None, primary=None, **over):
    """Build a schema-3 payload on the CGF carrier. All times are synthetic and mutually consistent with 03:05Z handoff."""
    P = copy.deepcopy(BASE)
    filings = filings or []
    P["schema"] = 3
    cv = P["claude_verification"]
    cv["newer_asx_filings_none_material"] = outcome in ("NONE", "ROUTINE_ONLY")
    cv["material_filings_assessed_and_incorporated"] = outcome == "MATERIAL_ASSESSED"
    mat = [f["announcement_id"] for f in filings if f["class"] == "MATERIAL"]
    P["filing_verification"] = {
        "contract": fc.CONTRACT, "outcome": outcome,
        "feed": {"fresh": True, "complete": True, "checked_at_utc": "2026-10-19T02:50:00Z", "newest_item_utc": "2026-10-19T02:40:00Z"},
        "primary": primary or copy.deepcopy(SGR_PRIMARY),
        "filings": filings,
        "review": {"record_id": P["review_record_id"], "readiness": "RESEARCH-READY", "status": "COMPLETE", "revision": 3,
                   "material_filings_assessed_ids": mat, "unresolved_issues": []},
        "stage_1_15": {"checked_at_utc": "2026-10-19T02:30:00Z", "all_conditions_met": True, "marker_sha256": P["marker_sha256"]},
        "stage_1_58": {"checked_at_utc": "2026-10-19T02:58:00Z", "all_conditions_met": True},
        "verified_at_utc": "2026-10-19T03:04:00Z", "attestation_acknowledged": True,
    }
    for k, val in over.items():
        P["filing_verification"][k] = val
    return P


def routine(base, **kw):
    f = dict(base, **{"same_minute_as_primary": False, "class": "ROUTINE_ADMIN", "content_read": True,
                      "classification_rationale": "Administrative securities notice, no earnings or guidance content",
                      "assessed_at_utc": "2026-10-19T02:31:00Z"})
    f.update(kw)
    return f


def material(base, **kw):
    f = dict(base, **{"same_minute_as_primary": False, "class": "MATERIAL", "content_read": True,
                      "classification_rationale": "Management commentary on trading and outlook; could change the investor read",
                      "reconciliation": "RECONCILED", "reconciliation_notes": "Addresses repeat the quarterly figures; no conflicts found",
                      "incorporated_in_report": True, "report_evidence": ["11.80 per share"],
                      "review_ref": BASE["review_record_id"], "excluded_claims": [],
                      "assessed_at_utc": "2026-10-19T02:35:00Z"})
    f.update(kw)
    return f


def mutate(P, path, value=None, delete=False):
    cur = P
    for k in path[:-1]:
        cur = cur[k]
    if delete:
        del cur[path[-1]]
    else:
        cur[path[-1]] = value
    return P


def unit_tests():
    print("== Part 1: contract validator (in-process, no files, no network)")
    # Case A / B / C accepted
    ok, d = accepted(v3("NONE"));                                                    record("A  no later filings (NONE) accepted", ok, d)
    ok, d = accepted(v3("ROUTINE_ONLY", [routine(SGR_LAPSE), routine(SGR_CESS)]));    record("B  routine filings only, read and classified, accepted", ok, d)
    P = v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR), routine(SGR_LAPSE)])
    ok, d = accepted(P)
    record("C  SGR fixture: material filing fully assessed + routine companion accepted", ok and fc.validate(P)["material"] == ["03157633"], d)
    P = v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, excluded_claims=[{"claim": "Any FY27 EBITDA target", "reason": "Not stated in the filing; only commentary on quarter trends"}])])
    ok, d = accepted(P);                                                              record("C2 documented excluded claim accepted", ok, d)

    # Case D blockers
    cases = [
        ("D1 material filing not assessed (not incorporated)", v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, incorporated_in_report=False)]), "NOT_INCORPORATED"),
        ("D2 material filing unclassified", v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, **{"class": "UNKNOWN"})]), "UNCLASSIFIED"),
        ("D3 conflicting figures unreconciled", v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, reconciliation="UNRESOLVED")]), "UNRESOLVED"),
        ("D4 filing content unavailable / unread (material)", v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, content_read=False)]), "FILING_UNREAD"),
        ("D5 filing content unavailable / unread (routine)", v3("ROUTINE_ONLY", [routine(SGR_LAPSE, content_read=False)]), "FILING_UNREAD"),
        ("D6 primary announcement not read", v3("NONE", primary=dict(SGR_PRIMARY, content_read=False)), "PRIMARY_UNREAD"),
        ("D7 unresolved issue recorded in the review", mutate(v3("NONE"), ["filing_verification", "review", "unresolved_issues"], ["Q4 comparatives differ"]), "UNRESOLVED"),
        ("D8 review not COMPLETE", mutate(v3("NONE"), ["filing_verification", "review", "status"], "IN_PROGRESS"), "REVIEW_NOT_COMPLETE"),
        ("D9 review not RESEARCH-READY", mutate(v3("NONE"), ["filing_verification", "review", "readiness"], "NOT RESEARCH-READY"), "REVIEW_NOT_READY"),
        ("D10 undocumented excluded claim", v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, excluded_claims=[{"claim": "Guidance", "reason": "n/a"}])]), "EXCLUSION_UNDOCUMENTED"),
        ("D11 material filing without report evidence", v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, report_evidence=[])]), "NO_REPORT_EVIDENCE"),
        # stale feed
        ("E1 stale filings feed (newest item 3h old)", mutate(v3("NONE"), ["filing_verification", "feed", "newest_item_utc"], "2026-10-19T00:00:00Z"), "STALE_FEED"),
        ("E2 feed marked not fresh", mutate(v3("NONE"), ["filing_verification", "feed", "fresh"], False), "STALE_FEED"),
        ("E3 feed marked incomplete", mutate(v3("NONE"), ["filing_verification", "feed", "complete"], False), "STALE_FEED"),
        # incorrect review reference
        ("F1 filing review_ref points at another record", v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, review_ref="WRONGRECORD")]), "REVIEW_REF_MISMATCH"),
        ("F2 review.record_id != handoff review_record_id", mutate(v3("NONE"), ["filing_verification", "review", "record_id"], "OTHER"), "REVIEW_REF_MISMATCH"),
        ("F3 material filing missing from review's assessed ids", mutate(v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR)]), ["filing_verification", "review", "material_filings_assessed_ids"], []), "REVIEW_REF_MISMATCH"),
        ("F4 review lists an assessed id that is not a material filing", mutate(v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR)]), ["filing_verification", "review", "material_filings_assessed_ids"], ["03157633", "03999999"]), "REVIEW_REF_MISMATCH"),
        # falsely-true legacy flag and contradictions
        ("G1 legacy flag true although a material filing exists", mutate(v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR)]), ["claude_verification", "newer_asx_filings_none_material"], True), "CONTRADICTION"),
        ("G2 legacy flag false for outcome NONE", mutate(v3("NONE"), ["claude_verification", "newer_asx_filings_none_material"], False), "CONTRADICTION"),
        ("G3 outcome NONE but filings listed", v3("NONE", [routine(SGR_LAPSE)]), "CONTRADICTION"),
        ("G4 outcome ROUTINE_ONLY but a material filing is listed", v3("ROUTINE_ONLY", [material(SGR_AGM_ADDR)]), "CONTRADICTION"),
        ("G5 outcome MATERIAL_ASSESSED but no material filing", v3("MATERIAL_ASSESSED", [routine(SGR_LAPSE)]), "CONTRADICTION"),
        ("G6 assessed flag missing", mutate(v3("NONE"), ["claude_verification", "material_filings_assessed_and_incorporated"], delete=True), "CONTRADICTION"),
        # tampered / incomplete / unrecognised
        ("H1 filing_verification object missing", mutate(v3("NONE"), ["filing_verification"], delete=True), "MISSING_FIELD"),
        ("H2 unrecognised contract version", mutate(v3("NONE"), ["filing_verification", "contract"], "material-filings/9"), "UNRECOGNISED_CONTRACT"),
        ("H3 unrecognised schema 4", mutate(v3("NONE"), ["schema"], 4), "UNRECOGNISED_SCHEMA"),
        ("H4 unrecognised schema 1", mutate(v3("NONE"), ["schema"], 1), "UNRECOGNISED_SCHEMA"),
        ("H5 unknown outcome", mutate(v3("NONE"), ["filing_verification", "outcome"], "ALL_GOOD"), "BAD_OUTCOME"),
        ("H6 announcement id malformed", v3("MATERIAL_ASSESSED", [material(dict(SGR_AGM_ADDR, announcement_id="ABC"))]), "BAD_ANNOUNCEMENT_ID"),
        ("H7 duplicate announcement ids", v3("ROUTINE_ONLY", [routine(SGR_LAPSE), routine(SGR_LAPSE)]), "INCONSISTENT_ID"),
        ("H8 later filing repeats the primary id", v3("ROUTINE_ONLY", [routine(dict(SGR_LAPSE, announcement_id="03157578"))]), "INCONSISTENT_ID"),
        ("H9 listed filing is earlier than the primary", v3("ROUTINE_ONLY", [routine(dict(SGR_LAPSE, release_datetime_utc="2026-10-26T22:00:00Z"))]), "INCONSISTENT_ID"),
        ("H10 bad timestamp", v3("ROUTINE_ONLY", [routine(dict(SGR_LAPSE, release_datetime_utc="yesterday"))]), "BAD_TIMESTAMP"),
        ("H11 a stage did not check its conditions", mutate(v3("NONE"), ["filing_verification", "stage_1_58", "all_conditions_met"], False), "STAGE_UNCHECKED"),
        ("H12 stage 1:15 missing", mutate(v3("NONE"), ["filing_verification", "stage_1_15"], delete=True), "STAGE_UNCHECKED"),
        ("H13 stages out of order", mutate(v3("NONE"), ["filing_verification", "stage_1_15", "checked_at_utc"], "2026-10-19T02:59:00Z"), "STAGE_ORDER"),
        ("H14 marker hash differs from the handoff", mutate(v3("NONE"), ["filing_verification", "stage_1_15", "marker_sha256"], "0" * 64), "MARKER_MISMATCH"),
        ("H15 verification time after the handoff", mutate(v3("NONE"), ["filing_verification", "verified_at_utc"], "2026-10-19T03:30:00Z"), "STAGE_ORDER"),
        ("H16 attestation not acknowledged", mutate(v3("NONE"), ["filing_verification", "attestation_acknowledged"], False), "MISSING_FIELD"),
        ("H17 another claude_verification flag false", mutate(v3("NONE"), ["claude_verification", "visual_check_done"], False), "FLAGS_NOT_TRUE"),
        ("H18 classification rationale missing", v3("ROUTINE_ONLY", [routine(SGR_LAPSE, classification_rationale="")]), "MISSING_FIELD"),
    ]
    for name, P, code in cases:
        ok, d = blocked(P, code)
        record(name, ok, d)

    # Same-minute companions (included, not only strictly later filings)
    prim = dict(SGR_PRIMARY)
    same = material(dict(SGR_AGM_ADDR, announcement_id="03157600", title="Companion investor presentation (synthetic)",
                         release_datetime_utc="2026-10-26T22:22:30Z"), same_minute_as_primary=True)
    ok, d = accepted(v3("MATERIAL_ASSESSED", [same], primary=prim));                  record("I1 same-minute material companion, flagged, accepted", ok, d)
    unflagged = dict(same, same_minute_as_primary=False)
    ok, d = blocked(v3("MATERIAL_ASSESSED", [unflagged], primary=prim), "SAME_MINUTE_FLAG");  record("I2 same-minute companion not flagged is rejected", ok, d)
    ok, d = blocked(v3("MATERIAL_ASSESSED", [dict(same, content_read=False)], primary=prim), "FILING_UNREAD"); record("I3 same-minute companion unread is rejected", ok, d)
    wrongly = dict(SGR_LAPSE, same_minute_as_primary=True)
    ok, d = blocked(v3("ROUTINE_ONLY", [routine(wrongly, same_minute_as_primary=True)]), "SAME_MINUTE_FLAG"); record("I4 false same-minute flag is rejected", ok, d)

    # Valid historical schema 2 still accepted; tampered schema 2 still rejected
    for rel in ("reports/2026-10-19-CGF/publish.json", "reports/2026-10-26-TUA/publish.json"):
        H = json.load(open(os.path.join(ROOT, rel), encoding="utf-8"))
        ok, d = accepted(H);                                                          record(f"J  valid historical schema 2 accepted: {rel.split('/')[1]}", ok and H["schema"] == 2, d)
        H2 = mutate(copy.deepcopy(H), ["claude_verification", "newer_asx_filings_none_material"], False)
        ok, d = blocked(H2, "LEGACY_FLAGS");                                          record(f"J2 schema 2 with flag false still rejected: {rel.split('/')[1]}", ok, d)
    H3 = copy.deepcopy(BASE); H3["filing_verification"] = {"outcome": "NONE"}
    ok, d = accepted(H3);                                                             record("J3 schema 2 ignores/does not need filing_verification (unchanged behaviour)", ok, d)

    # Report-text evidence (mechanical)
    pdf = subprocess.run(["pdftotext", "-layout", os.path.join(CGF, "TAR_CGF_19Oct2026.pdf"), "-"], capture_output=True, text=True).stdout
    P = v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR)])
    try:
        fc.check_report_evidence(P, P["caption"], pdf); ok, d = True, "evidence found in caption and PDF"
    except fc.ContractError as e:
        ok, d = False, str(e)
    record("K1 report_evidence present in caption and PDF text accepted", ok, d)
    P = v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, report_evidence=["a sentence the report never says"])])
    try:
        fc.check_report_evidence(P, P["caption"], pdf); ok, d = False, "accepted"
    except fc.ContractError as e:
        ok, d = e.code == "EVIDENCE_NOT_IN_REPORT", str(e)[:90]
    record("K2 claimed implication absent from report is rejected", ok, d)
    P = v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, report_evidence=["TOTALLY CAPTION ONLY PHRASE"])])
    P["caption"] += "\nTOTALLY CAPTION ONLY PHRASE"
    try:
        fc.check_report_evidence(P, P["caption"], pdf); ok, d = False, "accepted"
    except fc.ContractError as e:
        ok, d = e.code == "EVIDENCE_NOT_IN_REPORT" or e.code == "EVIDENCE_NOT_IN_PDF", str(e)[:90]
    record("K3 evidence only in caption, not in the PDF, is rejected", ok, d)
    # SGR real PDF text vs synthetic caption evidence
    sgr_pdf = subprocess.run(["pdftotext", "-layout", os.path.join(ROOT, "reports", "2026-10-27-SGR", "TAR_SGR_27Oct2026.pdf"), "-"],
                             capture_output=True, text=True).stdout
    P = v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, report_evidence=["EBITDA was A$12 million"])])
    try:
        fc.check_report_evidence(P, "synthetic caption", sgr_pdf); ok, d = True, "found in the real SGR PDF text"
    except fc.ContractError as e:
        ok, d = False, str(e)[:90]
    record("K4 SGR real PDF text carries the claimed evidence (synthetic assessment)", ok, d)


# ----------------------------------------------------------------------------- Part 2: scheduler integration
def load_bs():
    os.environ["MODE"] = "verify"
    spec = importlib.util.spec_from_file_location("bs", os.path.join(HERE, "buffer_schedule.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def sandbox(payload, gate=False):
    t = tempfile.mkdtemp()
    shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(t, "tools"))
    shutil.copytree(os.path.join(ROOT, "config"), os.path.join(t, "config"))
    shutil.copytree(CGF, os.path.join(t, "reports", "2026-10-19-CGF"))
    cfg = json.load(open(os.path.join(t, "config", "auto-publish.json")))
    cfg.setdefault("material_filings_contract", {})["schema3_accepted"] = gate
    json.dump(cfg, open(os.path.join(t, "config", "auto-publish.json"), "w"))
    rel = "reports/2026-10-19-CGF/publish.json"
    json.dump(payload, open(os.path.join(t, rel), "w", encoding="utf-8"), ensure_ascii=False)
    return t, rel


def run_main(bs, t, rel, mode, gql=None, now=None):
    """Run bs.main() in-process inside sandbox t. Returns (exit_code_or_None, stdout)."""
    cwd = os.getcwd()
    os.chdir(t)
    bs.MODE = mode
    os.environ["PAYLOAD"] = rel
    os.environ.pop("BUFFER_API_KEY", None)
    if mode == "scheduled":
        os.environ.update(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main", BUFFER_API_KEY="x")
    bs.verify_public = lambda *a, **k: "stubbed public check (no network)"
    if gql:
        bs.gql = gql
    if now:
        bs.now_syd = now
    bs.CTX.clear(); bs.CTX["folder"] = None
    buf, code = io.StringIO(), None
    with contextlib.redirect_stdout(buf):
        try:
            bs.main()
        except SystemExit as e:
            code = e.code
    os.chdir(cwd)
    for k in ("GITHUB_EVENT_NAME", "GITHUB_REF", "BUFFER_API_KEY"):
        os.environ.pop(k, None)
    return code, buf.getvalue()


def integration_tests():
    print("== Part 2: scheduler integration (in-process, Buffer stubbed, createPost must never be called)")
    bs = load_bs()
    good = v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR), routine(SGR_LAPSE)])

    # backward compatibility end-to-end: the real schema-2 CGF handoff still passes every non-network check
    t, rel = sandbox(BASE, gate=False)
    code, out = run_main(bs, t, rel, "verify")
    record("L1 historical schema-2 CGF handoff still passes verify end-to-end (gate off)", code is None and "VERIFY PASS" in out and "FILING CONTRACT OK: schema 2" in out, out.strip().splitlines()[-1][:90] if out.strip() else "")
    shutil.rmtree(t, ignore_errors=True)

    # gate closed: valid schema 3 is held back, with a precise blocker
    t, rel = sandbox(good, gate=False)
    code, out = run_main(bs, t, rel, "verify")
    record("L2 valid schema 3 is BLOCKED while the routine gate is closed", code == 1 and "SCHEMA3_BLOCKED" in out, next((l for l in out.splitlines() if "NOT SCHEDULED" in l), "")[:100])
    shutil.rmtree(t, ignore_errors=True)

    # gate open: valid schema 3 passes (the evidence string really is in the committed CGF caption and PDF)
    t, rel = sandbox(good, gate=True)
    code, out = run_main(bs, t, rel, "verify")
    record("L3 valid schema 3 passes verify when the gate is open", code is None and "VERIFY PASS" in out and "ATTESTATION LIMIT" in out, out.strip().splitlines()[-1][:90])
    shutil.rmtree(t, ignore_errors=True)

    # gate open, report text lacks the claimed implication
    bad_ev = v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, report_evidence=["Star Sydney licence suspension update"])])
    t, rel = sandbox(bad_ev, gate=True)
    code, out = run_main(bs, t, rel, "verify")
    record("L4 claimed implication missing from committed report is rejected", code == 1 and "EVIDENCE_NOT_IN_REPORT" in out, next((l for l in out.splitlines() if "NOT SCHEDULED" in l), "")[:100])
    shutil.rmtree(t, ignore_errors=True)

    # gate open, invalid contract content is rejected by the scheduler itself
    for name, P, code_want in (
        ("L5 scheduler rejects unreconciled material filing", v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, reconciliation="UNRESOLVED")]), "UNRESOLVED"),
        ("L6 scheduler rejects legacy flag falsely true with material filing", mutate(copy.deepcopy(good), ["claude_verification", "newer_asx_filings_none_material"], True), "CONTRADICTION"),
        ("L7 scheduler rejects schema 4", mutate(copy.deepcopy(good), ["schema"], 4), "schema"),
        ("L8 scheduler rejects wrong review reference", v3("MATERIAL_ASSESSED", [material(SGR_AGM_ADDR, review_ref="X")]), "REVIEW_REF_MISMATCH"),
        ("L9 scheduler rejects stale feed", mutate(copy.deepcopy(good), ["filing_verification", "feed", "fresh"], False), "STALE_FEED"),
    ):
        t, rel = sandbox(P, gate=True)
        code, out = run_main(bs, t, rel, "verify")
        record(name, code == 1 and code_want.lower() in out.lower(), next((l for l in out.splitlines() if "NOT SCHEDULED" in l), "")[:100])
        shutil.rmtree(t, ignore_errors=True)

    # in scheduled mode a closed gate is TRANSIENT (retried to the cutoff, status not final) and nothing is created
    syd = bs.SYD
    now = lambda: datetime(2026, 10, 19, 14, 0, tzinfo=syd)
    calls = []

    def gql_closed(q, v=None, soft=False):
        calls.append(q)
        raise AssertionError("Buffer must not be called when the gate is closed")
    t, rel = sandbox(good, gate=False)
    code, out = run_main(bs, t, rel, "scheduled", gql=gql_closed, now=now)
    st = json.load(open(os.path.join(t, "reports/2026-10-19-CGF/status.json")))
    record("M1 scheduled: closed gate = transient hold (exit 0, not final), no Buffer call", code == 0 and not st.get("final") and not calls and "RETRY" in out, f"exit={code} final={st.get('final')}")
    shutil.rmtree(t, ignore_errors=True)

    # duplicate LinkedIn/Buffer post already exists: schema 3, gate open, scheduled mode -> idempotent, createPost never called
    slot = datetime(2026, 10, 19, 15, 0, tzinfo=syd)
    creates = []

    def gql_dup(q, v=None, soft=False):
        if "createPost" in q:
            creates.append(q); raise AssertionError("createPost must not be called")
        if "account{" in q:
            return {"account": {"id": "a", "organizations": [{"id": bs.ORG_ID, "name": "o"}]}}
        if "channels(" in q:
            return {"channels": [{"id": bs.CHANNEL_ID, "displayName": bs.CHANNEL_NAME, "service": "linkedin", "isDisconnected": False, "isLocked": False}]}
        if "posts(" in q:
            return {"posts": {"edges": [{"node": {"id": "existing1", "status": "scheduled", "text": good["caption"], "dueAt": slot.isoformat()}}],
                              "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        raise AssertionError("unexpected query " + q[:40])
    t, rel = sandbox(good, gate=True)
    code, out = run_main(bs, t, rel, "scheduled", gql=gql_dup, now=now)
    record("N1 duplicate identical post exists: ALREADY SCHEDULED, createPost never called", code is None and "ALREADY SCHEDULED" in out and not creates, out.strip().splitlines()[-1][:90])
    shutil.rmtree(t, ignore_errors=True)

    def gql_conflict(q, v=None, soft=False):
        r = gql_dup(q, v, soft)
        if "posts(" in q:
            r["posts"]["edges"][0]["node"]["text"] = good["caption"] + " (edited)"
        return r
    t, rel = sandbox(good, gate=True)
    code, out = run_main(bs, t, rel, "scheduled", gql=gql_conflict, now=now)
    record("N2 non-identical conflicting post: STOP, createPost never called", code == 1 and "duplicate/conflict" in out and not creates, next((l for l in out.splitlines() if "NOT SCHEDULED" in l), "")[:100])
    shutil.rmtree(t, ignore_errors=True)

    # no-network sanity: dryrun of the same payload also never creates a post
    t, rel = sandbox(good, gate=True)
    code, out = run_main(bs, t, rel, "dryrun", gql=gql_dup, now=now)
    record("N3 dryrun with schema 3 + duplicate: reports it would block, creates nothing", code is None and "DRYRUN PASS" in out and not creates, out.strip().splitlines()[-1][:90])
    shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    unit_tests()
    integration_tests()
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks as expected")
    if bad:
        print("UNEXPECTED:", *bad, sep="\n  ")
        sys.exit(1)
    print("FILING CONTRACT TESTS PASS: schema 2 unchanged; schema 3 accepts only fully assessed filings; every Case D blocker stops.")
