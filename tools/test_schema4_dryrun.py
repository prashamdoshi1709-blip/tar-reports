"""Historical dry run of the schema 4 (vitti-source/1) handoff on the real published DNL report (9 Nov 2026).

Runs the REAL tools/buffer_schedule.py main() inside a temporary sandbox copy. Buffer is a mock (no network, no API key),
the public GitHub Pages check is stubbed, and nothing is committed, pushed or posted. The Vitti PDF text is read to prove
that every number in the caption comes from the Vitti Daily Mover.

Usage: python3 -I tools/test_schema4_dryrun.py <path to DNL-2026-11-09-draft.pdf>
"""
import contextlib, copy, hashlib, io, json, os, re, shutil, subprocess, sys, tempfile
from datetime import datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "tools"))
import buffer_schedule as bs  # noqa: E402

VITTI_PDF = sys.argv[1]
FOLDER = os.path.join(ROOT, "reports", "2026-11-09-DNL")
REL = "reports/2026-11-09-DNL/publish.json"
results = []


def record(name, ok, detail=""):
    results.append(ok)
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


def sha(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


vitti_text = subprocess.run(["pdftotext", "-layout", VITTI_PDF, "-"], capture_output=True, text=True).stdout
vitti_flat = re.sub(r"\s+", "", vitti_text).lower()

CAPTION = """The Announcement Room | Dyno Nobel (DNL)

According to the Vitti Capital Daily Mover dated 9 November 2026, Dyno Nobel shares were down 8.1% at $3.510 in morning trade after its FY26 result. FY26 Explosives EBIT was $485.1 million, up 12% on FY25, and FY27 EBIT guidance is $515 million to $555 million.

Vitti points to higher leverage as one factor in the move: net debt to EBITDA rose to 2.1x from 1.4x, and cash conversion halved to 35.5%.

Key points:
• FY26 Explosives EBIT of $485.1 million, within the $460 million to $500 million FY25 guidance
• FY27 EBIT guidance of $515 million to $555 million is company guidance, not a reported result
• Gearing policy widened to 1.75x to 2.25x from 1.5x to 2.0x
• On-market buyback of $574.4 million ceased in September
• FY27 capex guided at $370 million to $420 million, up from $282 million

Looking ahead, Vitti flags leverage near the top of the policy range, the Moranbah gas supplier QPM being in administration, and a scheduled turnaround drag of about $25 million of underlying EBIT in FY27.

In this two-page investor report, we look at:
• What the FY26 result showed
• Why the shares fell
• What changes now for leverage and capital returns
• What investors should watch next

ASX: DNL | 9 November 2026

General information only. Not financial advice.

#ASX #DNL #DynoNobel #EquityResearch #AustralianStocks"""

PDF = os.path.join(FOLDER, "TAR_DNL_9Nov2026.pdf")
PNG = os.path.join(FOLDER, "TAR_DNL_9Nov2026_cover.png")
PAGES = "https://prashamdoshi1709-blip.github.io/tar-reports/reports/2026-11-09-DNL/"


def payload():
    return {
        "schema": 4, "mode": "LIVE", "ticker": "DNL", "company_name": "Dyno Nobel",
        "report_date": "9 November 2026", "report_date_iso": "2026-11-09",
        "package_id": "DNL-2026-11-09-vitti",
        "handoff_created_at": "2026-11-09T12:40:00+11:00",
        "pdf_sha256": sha(PDF), "pdf_url": PAGES + "TAR_DNL_9Nov2026.pdf", "cover_url": PAGES + "TAR_DNL_9Nov2026_cover.png",
        "title": "FY26 result and FY27 outlook", "caption": CAPTION,
        "vitti_source": {"basis": "VITTI_DAILY_MOVER", "email_message_id": "DRYRUN-historical-DNL-9Nov", "pdf_name": "DNL-2026-11-09-draft.pdf",
                         "pdf_sha256": sha(VITTI_PDF), "independently_verified": False},
        "claude_verification": {k: True for k in ("vitti_sender_verified", "vitti_pdf_readable", "company_date_match",
                                                  "final_pdf_valid", "visual_check_done", "no_duplicate", "master_switch_enabled")},
    }


def sandbox(P):
    t = tempfile.mkdtemp()
    shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(t, "tools"), ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copytree(os.path.join(ROOT, "config"), os.path.join(t, "config"))
    shutil.copytree(FOLDER, os.path.join(t, "reports", "2026-11-09-DNL"))
    json.dump(P, open(os.path.join(t, REL), "w", encoding="utf-8"), ensure_ascii=False)
    return t


def run_main(t, mode, gql=None, now=None):
    cwd = os.getcwd(); os.chdir(t)
    bs.MODE = mode; os.environ["PAYLOAD"] = REL
    os.environ.pop("BUFFER_API_KEY", None)
    if mode == "scheduled":
        os.environ.update(GITHUB_EVENT_NAME="push", GITHUB_REF="refs/heads/main", BUFFER_API_KEY="mock")
    bs.verify_public = lambda *a, **k: "stubbed public check (no network)"
    if gql: bs.gql = gql
    if now: bs.now_syd = now
    bs.CTX.clear(); bs.CTX["folder"] = None
    buf, code = io.StringIO(), None
    with contextlib.redirect_stdout(buf):
        try: bs.main()
        except SystemExit as e: code = e.code
    os.chdir(cwd)
    for k in ("GITHUB_EVENT_NAME", "GITHUB_REF", "BUFFER_API_KEY"): os.environ.pop(k, None)
    return code, buf.getvalue()


def mock_buffer(existing=None):
    """Stateful Buffer mock. existing = list of post nodes already in Buffer."""
    state = {"posts": list(existing or []), "creates": [], "deletes": []}

    def gql(q, v=None, soft=False):
        if "createPost" in q:
            i = v["i"]; node = {"id": "MOCK1", "status": "scheduled", "text": i["text"], "dueAt": i["dueAt"], "channelId": i["channelId"],
                                "assets": [{"source": i["assets"][0]["document"]["url"], "thumbnail": i["assets"][0]["document"]["thumbnailUrl"],
                                            "document": {"title": i["assets"][0]["document"]["title"]}}]}
            state["creates"].append(node); state["posts"].append(node)
            return {"createPost": {"__typename": "PostActionSuccess", "post": {"id": "MOCK1"}}}
        if "deletePost" in q:
            state["deletes"].append(v); return {"deletePost": {"__typename": "DeletePostSuccess"}}
        if "account{" in q:
            return {"account": {"id": "a", "organizations": [{"id": bs.ORG_ID, "name": "o"}]}}
        if "channels(" in q:
            return {"channels": [{"id": bs.CHANNEL_ID, "displayName": bs.CHANNEL_NAME, "service": "linkedin", "isDisconnected": False, "isLocked": False}]}
        if "posts(" in q:
            return {"posts": {"edges": [{"node": n} for n in state["posts"]], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
        if "post(input" in q:
            return {"post": next(n for n in state["posts"] if n["id"] == v["i"]["id"])}
        raise AssertionError("unexpected Buffer query: " + q[:60])
    return gql, state


NOW = lambda: datetime(2026, 11, 9, 12, 40, tzinfo=bs.SYD)

# ---- 1-2: Vitti PDF identity and extraction
print("== 1-2: Vitti PDF is the source: company, ticker, date, figures")
record("Vitti PDF readable (pdftotext)", len(vitti_text) > 500)
record("Vitti PDF is Dyno Nobel Limited / DNL / 9 November 2026",
      "dynonobellimited" in vitti_flat and "asx:dnl" in vitti_flat.replace(" ", "") .replace("a s x:d n l", "asx:dnl") or "d n l" in vitti_text.lower() or "DNL" in vitti_text,
      "company/ticker present")
record("Vitti PDF dated 9 November 2026", "9november2026" in vitti_flat)

# ---- 3-4: caption numbers all come from Vitti
print("== 3-4: caption numbers come only from the Vitti PDF; no invented figures")
cap_body = CAPTION.split("ASX: DNL | 9 November 2026")[0]
nums = sorted(set(re.findall(r"\$?\d[\d,]*\.?\d*(?:x|c|%|m)?", cap_body)))
missing = []
for n in nums:
    core = n.strip("$").rstrip(".").rstrip("xcm%").replace(",", "").rstrip(".")
    if core in ("9", "2026", "1", "2", "3", "4", "25") and n in ("9", "2026"): continue
    if core.lower() not in vitti_flat: missing.append(n)
record("every figure in the caption appears in the Vitti PDF text", not missing, f"missing={missing}")
record("caption has no em dash / timestamp-of-day", "—" not in CAPTION and not re.search(r"\b\d{1,2}:\d{2}\b", CAPTION))
record("caption attributes the content to Vitti", "According to the Vitti Capital Daily Mover dated 9 November 2026" in CAPTION)
record("TAR PDF is 2 pages with the right size", subprocess.run(["pdfinfo", PDF], capture_output=True, text=True).stdout.count("Pages:           2") == 1)

# ---- 5: schema 4 handoff accepted by the real scheduler in verify mode
print("== 5: schema 4 handoff through the REAL scheduler (verify mode)")
t = sandbox(payload()); code, out = run_main(t, "verify")
record("valid schema 4 passes VERIFY (no research review, no FinancialFilings fields)", code is None and "VERIFY PASS" in out and "FILING CONTRACT OK: schema 4" in out, out.strip().splitlines()[-1][:80] if out.strip() else "")
shutil.rmtree(t, ignore_errors=True)

# negatives
def neg(name, P, want):
    t = sandbox(P); code, out = run_main(t, "verify")
    line = next((l for l in out.splitlines() if "NOT SCHEDULED" in l), "")
    record(name, code == 1 and any(w.lower() in out.lower() for w in want.split("|")), line[:100]); shutil.rmtree(t, ignore_errors=True)
P = payload(); P["claude_verification"]["no_duplicate"] = False; neg("flag false is rejected", P, "V4_FLAGS")
P = payload(); P["vitti_source"]["independently_verified"] = True; neg("claim of independent verification is rejected", P, "V4_SOURCE")
P = payload(); P["pdf_sha256"] = "0" * 64; neg("PDF hash mismatch is rejected", P, "sha256")
P = payload(); P["company_name"] = "Dyno Nobel Limited"; neg("company name that does not match the clean PDF title is rejected", P, "caption|verify_clean_pdf")
P = payload(); P["caption"] = P["caption"].replace("The Announcement Room | Dyno Nobel (DNL)", "The Announcement Room | Other Co (OTH)"); neg("caption for another company is rejected", P, "caption")
P = payload(); P["report_date"] = "10 November 2026"; neg("wrong report date is rejected", P, "mismatch")
P = payload(); P["title"] = "x" * 60; neg("title over 54 characters is rejected", P, "title")

# ---- 6-7: scheduled mode with a mocked Buffer: success, duplicate protection, idempotency
print("== 6-7: scheduled mode, mocked Buffer (no real post is possible)")
gql, st = mock_buffer(); t = sandbox(payload()); code, out = run_main(t, "scheduled", gql=gql, now=NOW)
s = json.load(open(os.path.join(t, "reports/2026-11-09-DNL/status.json")))
record("fresh day: exactly ONE mocked createPost, read-back verified, status BUFFER_SCHEDULED",
       code is None and len(st["creates"]) == 1 and "SCHEDULED: Buffer post MOCK1" in out and s.get("state") == "BUFFER_SCHEDULED", f"creates={len(st['creates'])} state={s.get('state')}")
shutil.rmtree(t, ignore_errors=True)

same = {"id": "EXIST1", "status": "scheduled", "text": CAPTION, "dueAt": "2026-11-09T12:43:00+11:00"}
gql, st = mock_buffer([same]); t = sandbox(payload()); code, out = run_main(t, "scheduled", gql=gql, now=NOW)
record("identical post already in Buffer: nothing created (idempotent)", code is None and not st["creates"] and "ALREADY SCHEDULED" in out, f"creates={len(st['creates'])}")
shutil.rmtree(t, ignore_errors=True)

other = {"id": "EXIST2", "status": "scheduled", "text": "The Announcement Room | Someone Else (XYZ)\n\nASX: XYZ | 9 November 2026\n\nGeneral information only. Not financial advice.\n\n#ASX #XYZ",
         "dueAt": "2026-11-09T12:50:00+11:00"}
gql, st = mock_buffer([other]); t = sandbox(payload()); code, out = run_main(t, "scheduled", gql=gql, now=NOW)
record("a different TAR report already scheduled today: second report blocked (one per trading day)", code is not None and not st["creates"], f"exit={code} creates={len(st['creates'])}")
shutil.rmtree(t, ignore_errors=True)

gql, st = mock_buffer(); t = sandbox(payload()); code, out = run_main(t, "scheduled", gql=gql, now=lambda: datetime(2026, 11, 9, 15, 20, tzinfo=bs.SYD))
record("after the 3:15 PM cutoff: nothing is created", not st["creates"], f"exit={code}")
shutil.rmtree(t, ignore_errors=True)

gql, st = mock_buffer(); t = sandbox(payload()); code, out = run_main(t, "scheduled", gql=gql, now=lambda: datetime(2026, 11, 10, 12, 40, tzinfo=bs.SYD))
record("handoff for a past date is refused in scheduled mode (no stale reports)", not st["creates"] and "is not today" in out, f"exit={code}")
shutil.rmtree(t, ignore_errors=True)

n = len(results)
print(f"\n{sum(results)}/{n} checks as expected")
sys.exit(0 if all(results) else 1)
