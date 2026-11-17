#!/usr/bin/env python3
"""Offline tests for the TAR Vitti generator (tar_gen). No network, no API key, no Drive, no Buffer, nothing committed.

A SYNTHETIC Daily Mover for a fictional company ("Test Minerals Limited", ASX: TMZ) is generated on the fly in Vitti's
format (same PDF metadata and letter-spaced labels), so no Vitti content is stored in this public repository.

    python3 tools/test_tar_gen.py                         # synthetic suite
    python3 tools/test_tar_gen.py --historical DIR        # also replay real packages kept OUTSIDE the repo:
        DIR/<name>/daily_mover.pdf [+ SOURCE_INDEX.json] [+ reply.json = an AI reply to run the full pipeline]
"""
import copy, glob, hashlib, json, os, shutil, subprocess, sys, tempfile
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from tar_gen import checks, run as RUN  # noqa: E402
from tar_gen.caption import build_caption  # noqa: E402
from tar_gen.common import GenError, FC, BS, long_date  # noqa: E402
from tar_gen.handoff import contract_check, make_handoff  # noqa: E402
from tar_gen.pipeline import build  # noqa: E402
from tar_gen.render import render, visual_check  # noqa: E402
from tar_gen.source import LocalSource  # noqa: E402
from tar_gen.vitti import verify_package  # noqa: E402
from tar_gen.writer import FixtureWriter, SCHEMA  # noqa: E402

results = []
D = date(2026, 11, 18)
GEN = {"allowed_senders": ["reports@vitti.capital"], "dkim_domain": "vitti.capital"}


def record(name, ok, detail=""):
    results.append(bool(ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail and not ok else ""))


def expect_gen_error(name, fn, code):
    try:
        fn()
    except GenError as e:
        record(name, e.code == code, f"got {e.code}: {e.msg}")
        return
    record(name, False, "no error raised")


def spaced(s):
    return " ".join(s)


def synthetic_daily_mover(path, tk="TMZ", company="Test Minerals Limited", d=D, title_tk=None):
    from weasyprint import HTML
    body = f"""<html><body style="font-family:sans-serif;font-size:9pt">
<p>{spaced('ASX:' + tk)}</p><p>vitti.capital</p><p>{spaced('ONE-PAGE SNAPSHOT')}</p>
<h1>{company}</h1><h2>Test Minerals Rises 12.4% in Morning Trade After $85.0M Offtake Deal</h2>
<p>+12.4% {spaced('SHARE MOVE · $1.250 · AS AT 10:25')}</p><p>$85.0M {spaced('OFFTAKE VALUE')}</p>
<p>$42.5M {spaced('CASH AT 30 SEPTEMBER')}</p><p>FY27 {spaced('FIRST DELIVERIES')}</p>
<p>Revenue grew to $310.2m in FY26 from $255.0m in FY25. Chart: FY25 $255.0m, FY26 $310.2m.</p>
<p>WHAT MAY HAVE DRIVEN THE MOVE 1 Binding five-year offtake worth $85.0m with a Japanese buyer
2 Price is fixed for the first two years 3 Removes the main funding question for Stage 2</p>
<p>WHAT CHANGES NOW 1 Final investment decision on Stage 2 targeted for March 2027 2 Construction tender due in Q1 2027
3 Debt process of up to $60.0m now under way</p>
<p>HOW WE GOT HERE 26 Aug 2026 FY26 results: revenue $310.2m 30 Oct 2026 Quarterly: cash of $42.5m
18 Nov 2026 Binding offtake agreement signed</p>
<p>KEY RISKS REMAINING Funding: Stage 2 still needs up to $60.0m of debt. Execution: Construction has not started.
Customer concentration: one buyer takes 70% of output.</p>
<p>Vitti view: the offtake answers the demand question; funding and construction are now the tests.</p>
<p>Source: Offtake announcement, ASX 18 Nov 2026; FY26 Results, ASX 26 Aug 2026; exchange feed.</p>
<p>General information only. This is not personal financial advice.</p>
<p>Daily Mover Snapshot | {long_date(d)} | Analyst: Synthetic Test</p>
<p>{"padding text for a realistic text layer. " * 20}</p></body></html>"""
    doc = HTML(string=body).render()
    doc.metadata.title = f"{title_tk or tk} Daily Mover — {long_date(d)}"
    doc.metadata.description = f"Daily Mover: {company} ({tk})"
    doc.metadata.authors = ["Synthetic Test, Vitti Capital"]
    doc.write_pdf(path)


def make_package(root, tk="TMZ", d=D, sender="reports@vitti.capital", dkim=True, subject_tk=None, name_tk=None,
                 title_tk=None, recv=None, mode="VITTI"):
    pid = f"{d.isoformat()}_1046_1a1e000000000001_a1"
    p = os.path.join(root, pid)
    os.makedirs(p)
    pdf = os.path.join(p, "daily_mover.pdf")
    synthetic_daily_mover(pdf, tk=tk, d=d, title_tk=title_tk)
    sha = hashlib.sha256(open(pdf, "rb").read()).hexdigest()
    auth = "mx.google.com; dkim=pass header.i=@vitti.capital header.s=resend" if dkim else "mx.google.com; dkim=fail"
    idx = {"schema_version": "4.0", "package_id": pid, "import_mode": mode, "processed_at": f"{d.isoformat()}T10:51:26+11:00",
           "email": {"sender_email": sender, "subject": f"Daily Mover draft: {subject_tk or tk} +12.40% ({d.day} {d.strftime('%b %Y')})",
                     "received_at": recv or f"{d.isoformat()}T10:46:48+11:00", "gmail_message_id": "1a1e000000000001",
                     "rfc822_message_id": "<synthetic@test>", "authentication_results": auth},
           "daily_mover": {"status": "found", "name": f"{name_tk or tk}-{d.isoformat()}-draft.pdf", "sha256": sha},
           "drive": {"package_folder_id": "SYNTHETIC"}, "files": []}
    json.dump(idx, open(os.path.join(p, "SOURCE_INDEX.json"), "w"))
    return p


GOOD = {
    "title": "Test Minerals: $85.0M Offtake Deal Signed",
    "headline": "Test Minerals signs an $85.0M offtake deal and the shares rise in morning trade",
    "topic": "Binding offtake agreement",
    "lede": "Test Minerals Limited has signed a binding five-year offtake agreement worth $85.0M with a Japanese buyer. "
            "The shares rose 12.4% in morning trade to $1.250 as the deal removes the main funding question for Stage 2.",
    "kpis": [{"value": "+12.4%", "label": "Share move", "note": "Morning trade, not a closing move", "tone": "orange"},
             {"value": "$85.0M", "label": "Offtake value", "note": "Five-year binding agreement", "tone": "teal"},
             {"value": "$42.5M", "label": "Cash at 30 September", "note": "Before any Stage 2 debt", "tone": "navy"}],
    "chart": {"include": True, "label": "Revenue grew in FY26", "note": "Revenue per the FY26 results.",
              "bars": [{"label": "FY25", "value": 255.0, "display": "$255.0m FY25"}, {"label": "FY26", "value": 310.2, "display": "$310.2m FY26"}]},
    "facts_label": "What the announcement says",
    "facts": [{"head": "Binding offtake.", "body": "A five-year offtake worth $85.0m has been signed with a Japanese buyer."},
              {"head": "Fixed early pricing.", "body": "The price is fixed for the first two years of the agreement."},
              {"head": "Funding still to come.", "body": "A debt process of up to $60.0m is now under way for Stage 2."}],
    "context_label": "How we got here",
    "context": [{"head": "FY26 results, 26 Aug 2026", "body": "Revenue rose to $310.2m from $255.0m in FY25."},
                {"head": "Quarterly, 30 Oct 2026", "body": "The company reported cash of $42.5m at the end of September."}],
    "why": [{"head": "Demand is contracted.", "body": "A binding buyer for five years answers the question of who takes the output."},
            {"head": "Price certainty.", "body": "Fixed pricing for two years makes the early cash flows easier to judge."},
            {"head": "A step towards funding.", "body": "Vitti points to the offtake as removing the main funding question for Stage 2."}],
    "watch": [{"head": "Final investment decision", "body": "The Stage 2 decision is targeted for March 2027, a company target."},
              {"head": "Debt funding", "body": "Stage 2 still needs up to $60.0m of debt, and terms are not yet known."},
              {"head": "Customer concentration", "body": "One buyer takes 70% of output, which concentrates risk."}],
    "take": "The offtake gives Test Minerals a contracted buyer and fixed early pricing, which is what lenders usually want to see "
            "before funding a project. What has not changed is that Stage 2 still needs debt, construction has not started and one "
            "customer takes most of the output. The next tests are the debt terms and the March 2027 investment decision.",
    "caption": {"intro": "According to the Vitti Capital Daily Mover dated 18 November 2026, Test Minerals shares rose 12.4% in "
                         "morning trade after the company signed a binding $85.0m offtake agreement.",
                "context": "The company had cash of $42.5m at 30 September, and Stage 2 still needs up to $60.0m of debt.",
                "key_points": ["Binding five-year offtake worth $85.0m", "Pricing fixed for the first two years",
                               "Debt process of up to $60.0m under way", "One buyer takes 70% of output"],
                "looking_ahead": "Looking ahead, the final investment decision on Stage 2 is targeted for March 2027, a company target.",
                "we_look_at": ["What the offtake says", "Why the shares rose", "How the company got here", "What investors should watch"],
                "hashtags": ["TestMinerals", "Mining"]}}


def main():
    hist = sys.argv[sys.argv.index("--historical") + 1] if "--historical" in sys.argv else None
    tmp = tempfile.mkdtemp(prefix="tar_gen_test_")
    try:
        print("== 1. package identity and integrity (synthetic Daily Mover in Vitti's format)")
        root = os.path.join(tmp, "ok"); os.makedirs(root)
        make_package(root)
        pkg = LocalSource(root).packages_for(D)[0]
        ident = verify_package(pkg, D, GEN)
        record("valid package: ticker, company, date and all three identity flags", ident.ticker == "TMZ" and
               ident.company == "Test Minerals Limited" and ident.date == D and all(ident.checks.values()) and len(ident.checks) == 3)
        record("letter-spaced figures are read ($1.250 from '$ 1 . 2 5 0')", 1.25 in ident.source_numbers)

        def bad_pkg(**kw):
            r = tempfile.mkdtemp(dir=tmp); make_package(r, **kw)
            return LocalSource(r).packages_for(kw.get("d", D))[0]
        expect_gen_error("wrong sender rejected", lambda: verify_package(bad_pkg(sender="news@other.com"), D, GEN), "SENDER")
        expect_gen_error("missing DKIM pass rejected", lambda: verify_package(bad_pkg(dkim=False), D, GEN), "DKIM")
        expect_gen_error("non-Vitti import rejected", lambda: verify_package(bad_pkg(mode="MANUAL"), D, GEN), "NOT_VITTI")
        expect_gen_error("email subject for another ticker rejected", lambda: verify_package(bad_pkg(subject_tk="ABC"), D, GEN), "IDENTITY")
        expect_gen_error("file name for another ticker rejected", lambda: verify_package(bad_pkg(name_tk="ABC"), D, GEN), "IDENTITY")
        expect_gen_error("PDF title for another ticker rejected", lambda: verify_package(bad_pkg(title_tk="ABC"), D, GEN), "IDENTITY")
        expect_gen_error("yesterday's Daily Mover rejected", lambda: verify_package(bad_pkg(), date(2026, 11, 19), GEN), "STALE_PACKAGE")
        expect_gen_error("email received on another day rejected",
                         lambda: verify_package(bad_pkg(recv="2026-11-17T10:46:48+11:00"), D, GEN), "IDENTITY")
        p2 = bad_pkg(); open(p2.daily_mover_path, "ab").write(b"tampered")
        expect_gen_error("Daily Mover hash mismatch rejected", lambda: verify_package(p2, D, GEN), "DM_HASH")

        print("== 2. content checks (figures, company, wording, attribution)")
        record("clean report has no problems", checks.check_report(checks.sanitize(GOOD), ident) == [],
               str(checks.check_report(checks.sanitize(GOOD), ident)))

        def probs(mut):
            r = copy.deepcopy(GOOD); mut(r)
            return " | ".join(checks.check_report(checks.sanitize(r), ident))
        record("invented figure is caught", "91.5m" in probs(lambda r: r["facts"][0].update(body="The offtake is worth $91.5m over five years.")))
        record("rounded figure is caught", "12%" in probs(lambda r: r.update(lede=r["lede"].replace("12.4%", "12%"))))
        record("own calculation is caught", "25.2%" in probs(lambda r: r["watch"][1].update(body="Revenue grew 25.2% in FY26, a TAR calculation.")))
        record("figure in a KPI is checked", "$99" in probs(lambda r: r["kpis"][1].update(value="$99.9M")) or "99.9" in probs(lambda r: r["kpis"][1].update(value="$99.9M")))
        record("chart value not in source is caught", "chart.bars" in probs(lambda r: r["chart"]["bars"][0].update(value=200.0)))
        record("another company's ASX code is caught", "ABC" in probs(lambda r: r["facts"][0].update(body="Peer ASX: ABC signed a similar deal.")))
        record("'draft' wording is caught", "draft" in probs(lambda r: r.update(take=r["take"] + " This draft is final.")))
        record("clock time is caught", "clock" in probs(lambda r: r.update(lede=r["lede"] + " As at 10:25 the move held.")))
        record("advice language is caught", "advice" in probs(lambda r: r.update(take=r["take"] + " We recommend investors buy now.")))
        record("missing Vitti attribution is caught", "attribute" in probs(lambda r: r["caption"].update(intro=r["caption"]["intro"].replace("According to the Vitti Capital Daily Mover dated 18 November 2026, ", ""))))
        record("over-long title is caught", "title" in probs(lambda r: r.update(title="T" * 60)))
        record("em dash is replaced, not published", "—" not in json.dumps(checks.sanitize(dict(GOOD, take=GOOD["take"] + " — x")), ensure_ascii=False))
        record("small counts and years are not treated as figures", checks.unsupported_numbers("two of 3 approvals in 2027", set(), set()) == [])
        record("money is never exempt", checks.unsupported_numbers("a $5 fee", set(), set()) == ["5"])

        print("== 3. write -> check -> render loop (fixture writer stands in for Claude)")
        out = os.path.join(tmp, "out")
        bad = copy.deepcopy(GOOD); bad["facts"][0]["body"] = "The offtake is worth $91.5m over five years."
        w = FixtureWriter([bad, GOOD])
        res = build(ident, w, out, log=lambda *_: None)
        record("problem fed back to the writer, fixed on attempt 2", res["attempts"] == 2 and w.calls == 2)
        expect_gen_error("three failing replies stop the run (fail closed)",
                         lambda: build(ident, FixtureWriter([bad, bad, bad]), os.path.join(tmp, "o3"), log=lambda *_: None), "CHECKS_FAILED")
        info = subprocess.run(["pdfinfo", res["pdf"]], capture_output=True, text=True).stdout
        fonts = subprocess.run(["pdffonts", res["pdf"]], capture_output=True, text=True).stdout
        record("PDF: 2 pages, 810 x 1012.5 pt", "Pages:           2" in info and "810 x 1012.5 pts" in info)
        record("PDF: Lora and Inter embedded", "Lora" in fonts and "Inter" in fonts)
        record("PDF: clean title metadata", f"Title:           Test Minerals Limited (ASX: TMZ) - {GOOD['title']}" in info)
        v = subprocess.run([sys.executable, "-I", os.path.join(ROOT, "tools", "verify_clean_pdf.py"), res["pdf"], res["clean_title"]], capture_output=True, text=True)
        record("tools/verify_clean_pdf.py PASS", v.returncode == 0 and "PASS" in v.stdout, v.stdout[-200:])
        sz = subprocess.run(["file", res["png"]], capture_output=True, text=True).stdout
        record("cover PNG 788 x 985 (same as published covers)", "788 x 985" in sz, sz)
        txt = subprocess.run(["pdftotext", "-layout", res["pdf"], "-"], capture_output=True, text=True).stdout
        record("page text attributes Vitti and states no independent verification",
               "Vitti Capital Daily Mover" in txt and "not independently verified" in " ".join(txt.split()))
        long_rep = copy.deepcopy(GOOD); long_rep["facts"] = [dict(f, body=f["body"] * 5) for f in GOOD["facts"]] * 2
        long_rep["context"] = [dict(c, body=c["body"] * 4) for c in GOOD["context"]] * 2
        lay = render(long_rep, ident, os.path.join(tmp, "long.pdf"), os.path.join(tmp, "long.png"), "x")
        record("overflowing page 1 is detected by the layout measurement", bool(lay["overflow"]) or lay["pages"] != 2,
               str(lay))
        record("visual check flags it", bool(visual_check(os.path.join(tmp, "long.pdf"), lay)))

        print("== 4. caption, handoff and the EXISTING publisher's checks")
        cap = res["caption"]
        record("caption: house format first line, date line, disclaimer, hashtags last",
               cap.startswith("The Announcement Room | Test Minerals Limited (TMZ)\n\nAccording to the Vitti Capital Daily Mover")
               and "\n\nASX: TMZ | 18 November 2026\n\nGeneral information only. Not financial advice.\n\n#ASX #TMZ" in cap
               and cap.rstrip().split()[-1].startswith("#"))
        flags = dict(ident.checks, final_pdf_valid=True, visual_check_done=True, no_duplicate=True, master_switch_enabled=True)
        P = make_handoff(ident, res, pkg, flags, "fixture")
        record("schema 4 handoff passes filing_contract.validate_v4", FC.validate(P)["schema"] == 4)
        record("handoff never claims independent verification", P["vitti_source"]["independently_verified"] is False)
        out_txt = contract_check(P, res["pdf"], res["png"])
        record("REAL buffer_schedule.py (verify mode) accepts the generated report", "VERIFY PASS" in out_txt)
        P2 = dict(P, pdf_sha256="0" * 64)
        expect_gen_error("publisher rejects a handoff whose hash does not match", lambda: contract_check(P2, res["pdf"], res["png"]), "PUBLISHER_REJECTED")
        P3 = dict(P, caption=P["caption"].replace("(TMZ)", "(ABC)", 1))
        expect_gen_error("publisher rejects a caption for another company", lambda: contract_check(P3, res["pdf"], res["png"]), "PUBLISHER_REJECTED")
        P4 = copy.deepcopy(P); P4["claude_verification"]["no_duplicate"] = False
        record("a false check flag is rejected by the contract", not _accepts(P4))

        print("== 5. safety gates (nothing can publish by default)")
        cfg, g = json.load(open(os.path.join(ROOT, "config", "auto-publish.json"))), None
        g = cfg["vitti_generator"]
        record("repository config: generator disabled, publish off, rights not confirmed",
               g["enabled"] is False and g["publish"] is False and g["rights_confirmed"] is False)
        os.environ.update(GITHUB_ACTIONS="true", GITHUB_REF="refs/heads/main")
        ok, why = RUN.publish_allowed(dict(cfg, enabled=True), dict(g, enabled=True, publish=True, rights_confirmed=False))
        record("publish blocked while republication rights are unconfirmed", not ok and any("rights" in w for w in why))
        ok, _ = RUN.publish_allowed(dict(cfg, enabled=False), dict(g, enabled=True, publish=True, rights_confirmed=True))
        record("publish blocked while the master switch is off", not ok)
        ok, _ = RUN.publish_allowed(dict(cfg, enabled=True), dict(g, enabled=True, publish=True, rights_confirmed=True))
        record("publish allowed only when every switch is on (on main in Actions)", ok)
        os.environ["GITHUB_REF"] = "refs/heads/claude/dev"
        ok, _ = RUN.publish_allowed(dict(cfg, enabled=True), dict(g, enabled=True, publish=True, rights_confirmed=True))
        record("publish blocked off main", not ok)
        for k in ("GITHUB_ACTIONS", "GITHUB_REF"):
            os.environ.pop(k, None)
        rc = RUN.main(["--local", root, "--date", D.isoformat(), "--fixture-writer", _dump(tmp, [GOOD]), "--out", os.path.join(tmp, "cli"), "--no-notify"])
        record("CLI end to end: exit 0, shadow output with PDF, cover, caption and publish.json, nothing in reports/",
               rc == 0 and len(glob.glob(os.path.join(tmp, "cli", "reports", "2026-11-18-TMZ", "*"))) == 5
               and not os.path.exists(os.path.join(ROOT, "reports", "2026-11-18-TMZ")))
        record("duplicate rule: an email already used by a published report is refused",
               RUN.used_before(type(ident)(gmail_id="__none__", dm_sha="__none__")) is None)
        record("publisher accepts the workflow_run event used to start it after the generator",
               '"workflow_run")' in open(os.path.join(ROOT, "tools", "buffer_schedule.py")).read())

        if hist:
            print(f"== 6. historical Vitti packages from {hist} (kept outside the repository)")
            for p in sorted(glob.glob(os.path.join(hist, "*"))):
                dm = os.path.join(p, "daily_mover.pdf")
                if not os.path.isfile(dm):
                    continue
                name = os.path.basename(p)
                meta = subprocess.run(["pdfinfo", dm], capture_output=True, text=True).stdout
                tk = meta.split("Title:")[1].split()[0]
                d = date.fromisoformat(name.split("-", 1)[1])
                if not os.path.isfile(os.path.join(p, "SOURCE_INDEX.json")):
                    _historical_index(p, dm, tk, d)
                hp = LocalSource(p).packages_for(d)[0]
                try:
                    hid = verify_package(hp, d, GEN)
                    record(f"{name}: identity verified ({hid.company}, {len(hid.source_numbers)} source figures)", True)
                except GenError as e:
                    record(f"{name}: identity verified", False, f"{e.code}: {e.msg}")
                    continue
                rj = os.path.join(p, "reply.json")
                if os.path.isfile(rj):
                    o = os.path.join(tmp, "hist", name)
                    r = build(hid, FixtureWriter(json.load(open(rj))), o, log=lambda *_: None)
                    P = make_handoff(hid, r, hp, dict(hid.checks, final_pdf_valid=True, visual_check_done=True, no_duplicate=True,
                                                     master_switch_enabled=True), "fixture")
                    record(f"{name}: full pipeline + real publisher verify", "VERIFY PASS" in contract_check(P, r["pdf"], r["png"]))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    n = len(results)
    print(f"\n{sum(results)}/{n} checks as expected")
    print("TAR GENERATOR TESTS PASS" if all(results) else "TAR GENERATOR TESTS FAILED")
    return 0 if all(results) else 1


def _accepts(P):
    try:
        FC.validate(P)
        return True
    except FC.ContractError:
        return False


def _dump(tmp, obj):
    p = os.path.join(tmp, "reply.json")
    json.dump(obj, open(p, "w"))
    return p


def _historical_index(p, dm, tk, d):
    """Historical packages downloaded without their SOURCE_INDEX: rebuild the fields the generator reads, marked as such."""
    sha = hashlib.sha256(open(dm, "rb").read()).hexdigest()
    json.dump({"package_id": f"{d.isoformat()}_1046_0000000000000000_a1", "import_mode": "VITTI",
               "processed_at": f"{d.isoformat()}T10:51:00+11:00",
               "email": {"sender_email": "reports@vitti.capital", "subject": f"Daily Mover draft: {tk} +0.00% ({d.day} {d.strftime('%b %Y')})",
                         "received_at": f"{d.isoformat()}T10:46:00+11:00", "gmail_message_id": "historical-" + tk,
                         "authentication_results": "historical replay; dkim=pass header.i=@vitti.capital"},
               "daily_mover": {"status": "found", "name": f"{tk}-{d.isoformat()}-draft.pdf", "sha256": sha}, "files": []},
              open(os.path.join(p, "SOURCE_INDEX.json"), "w"))


if __name__ == "__main__":
    sys.exit(main())
