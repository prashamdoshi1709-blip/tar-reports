#!/usr/bin/env python3
"""Offline tests for the TAR Vitti generator (tar_gen). No network, no API key, no Drive, no Buffer, nothing committed.

A SYNTHETIC Daily Mover for a fictional company ("Test Minerals Limited", ASX: TMZ) is generated on the fly in Vitti's
format (same PDF metadata and letter-spaced labels), so no Vitti content is stored in this public repository.

    python3 tools/test_tar_gen.py                         # synthetic suite
    python3 tools/test_tar_gen.py --historical DIR        # also replay real packages kept OUTSIDE the repo:
        DIR/<name>/daily_mover.pdf [+ SOURCE_INDEX.json] [+ reply.json = an AI reply to run the full pipeline]
"""
import contextlib, copy, glob, hashlib, io, json, os, shutil, subprocess, sys, tempfile
from datetime import date, datetime

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
from tar_gen.template import TemplateWriter  # noqa: E402

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


def synthetic_daily_mover(path, tk="TMZ", company="Test Minerals Limited", d=D, title_tk=None, drop_risks=False):
    """Fictional company in Vitti's real Daily Mover layout (1092 x 876 pt, same section coordinates, letter-spaced
    headings, same PDF metadata), so the structured reader and MODE B are tested without any real Vitti content."""
    from weasyprint import HTML

    def at(x, y, text, size=9, ls=0, w=None, center=False, bold=False):
        style = f"left:{x}pt;top:{y}pt;font-size:{size}pt;letter-spacing:{ls}pt;" + (f"width:{w}pt;" if w else "") + \
                ("text-align:center;" if center else "") + ("font-weight:700;" if bold else "")
        return f'<div style="position:absolute;white-space:nowrap;{style}">{text}</div>'
    el = [at(46, 24, f"ASX:{tk}", ls=3), at(956, 27, "vitti.capital"), at(46, 80, "ONE-PAGE SNAPSHOT", ls=3),
          at(46, 100, company, size=20, bold=True),
          at(46, 138, "Test Minerals Rises 12.4% in Morning Trade as $85.0M Offtake Deal Signed", size=13, bold=True)]
    for x, v, lab in ((95, "+12.4%", "SHARE MOVE · $1.250 · AS AT 10:25"), (345, "$85.0M", "OFFTAKE VALUE"),
                      (595, "$42.5M", "CASH AT 30 SEPTEMBER"), (845, "FY27", "FIRST DELIVERIES")):
        el += [at(x, 189, v, size=16, bold=True), at(x, 215, lab, size=7, ls=1.5)]
    el += [at(63, 260, "REVENUE GREW STRONGLY IN FY26", ls=2), at(940, 263, "Revenue"),
           at(73, 274, "Revenue rose to $310.2m in FY26 from $255.0m in FY25"),
           at(300, 298, "$255.0m", w=90, center=True), at(741, 288, "$310.2m", w=90, center=True),
           at(105, 288, "300"), at(105, 350, "200"), at(300, 390, "FY25", w=90, center=True), at(741, 390, "FY26", w=90, center=True),
           at(63, 408, "Revenue per the FY26 Results, ASX 26 Aug 2026"),
           at(89, 458, "WHAT MAY HAVE DRIVEN THE MOVE", ls=2), at(595, 458, "WHAT CHANGES NOW", ls=2)]
    left = ["Binding five-year offtake worth $85.0m signed with a Japanese buyer", "Price is fixed for the first two years of supply",
            "Vitti says the deal removes the main funding question for Stage 2"]
    right = ["Final investment decision on Stage 2 targeted for March 2027", "Debt process of up to $60.0m is now under way",
             "Construction tender is due in Q1 2027"]
    for i, (a, b) in enumerate(zip(left, right)):
        y = 480 + 20 * i
        el += [at(65, y + 3, str(i + 1)), at(82, y, a), at(571, y + 3, str(i + 1)), at(588, y, b)]
    el += [at(46, 586, "HOW WE GOT HERE", ls=2)]
    for x, dt, t in ((46, "26 Aug 2026", "FY26 results: revenue $310.2m"), (296, "30 Oct 2026", "Quarterly report: cash of $42.5m"),
                     (546, "18 Nov 2026", "Binding offtake agreement signed")):
        el += [at(x, 615, dt, bold=True), at(x, 630, t)]
    if not drop_risks:
        el += [at(46, 676, "KEY RISKS REMAINING", ls=2)]
        for x, h, t in ((93, "Debt funding", "Stage 2 still needs up to $60.0m of debt."),
                        (430, "Construction start", "Construction has not started; the tender is due in Q1 2027."),
                        (766, "Customer concentration", "One buyer takes 70% of output under the offtake.")):
            el += [at(x, 702, h, bold=True), at(x, 718, t)]
    el += [at(46, 780, "Vitti view: The offtake answers the demand question; funding and construction are now the tests."),
           at(46, 810, "Source: Offtake announcement, ASX 18 Nov 2026; FY26 Results, ASX 26 Aug 2026; exchange feed."),
           at(61, 840, f"Daily Mover Snapshot | {long_date(d)} | Analyst: Synthetic Test", size=7),
           at(563, 834, "General information only. This is not personal financial advice.", size=7)]
    body = ('<html><head><style>@page{size:1092pt 876pt;margin:0}body{margin:0;font-family:sans-serif}</style></head>'
            '<body><div style="position:relative;width:1092pt;height:876pt">' + "".join(el) + "</div></body></html>")
    doc = HTML(string=body).render()
    doc.metadata.title = f"{title_tk or tk} Daily Mover \u2014 {long_date(d)}"
    doc.metadata.description = f"Daily Mover: {company} ({tk})"
    doc.metadata.authors = ["Synthetic Test, Vitti Capital"]
    doc.write_pdf(path)


def make_package(root, tk="TMZ", d=D, sender="reports@vitti.capital", dkim=True, subject_tk=None, name_tk=None,
                 title_tk=None, recv=None, mode="VITTI", drop_risks=False, status="AWAITING_VERIFICATION", shape=None,
                 dm_extra=None):
    pid = f"{d.isoformat()}_1046_1a1e000000000001_a1"
    p = os.path.join(root, pid)
    os.makedirs(p)
    pdf = os.path.join(p, "daily_mover.pdf")
    synthetic_daily_mover(pdf, tk=tk, d=d, title_tk=title_tk, drop_risks=drop_risks)
    sha = hashlib.sha256(open(pdf, "rb").read()).hexdigest()
    auth = "mx.google.com; dkim=pass header.i=@vitti.capital header.s=resend" if dkim else "mx.google.com; dkim=fail"
    idx = {"schema_version": "4.0", "package_id": pid, "import_mode": mode, "processed_at": f"{d.isoformat()}T10:51:26+11:00",
           "email": {"sender_email": sender, "subject": f"Daily Mover draft: {subject_tk or tk} +12.40% ({d.day} {d.strftime('%b %Y')})",
                     "received_at": recv or f"{d.isoformat()}T10:46:48+11:00", "gmail_message_id": "1a1e000000000001",
                     "rfc822_message_id": "<synthetic@test>", "authentication_results": auth},
           "daily_mover": dict({"status": "found", "name": f"{name_tk or tk}-{d.isoformat()}-draft.pdf", "sha256": sha,
                                 "drive_file_id": "SYNTHETIC_DM", "saved": True, "size_verified": True}, **(dm_extra or {})),
           "status": status, "drive": {"package_folder_id": "SYNTHETIC"}, "files": []}
    if shape:
        idx["import_shape"] = shape
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


class MockGemini:
    """Local stand-in for the Gemini REST API (no network). Replies are consumed in order per generateContent call."""
    def __init__(self):
        import http.server, threading
        outer = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, obj):
                b = json.dumps(obj).encode()
                self.send_response(code); self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

            def do_GET(self):
                outer.log.append({"path": self.path, "key": self.headers.get("x-goog-api-key")})
                self._send(200, {"models": [{"name": f"models/{m}", "supportedGenerationMethods": ["generateContent"]} for m in outer.models]})

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0)); self.rfile.read(n)
                outer.log.append({"path": self.path, "key": self.headers.get("x-goog-api-key")})
                outer.gen_count += 1
                kind, payload = outer.replies.pop(0) if outer.replies else ("500", None)
                if kind == "ok":
                    self._send(200, {"candidates": [{"content": {"parts": [{"text": json.dumps(payload)}]}, "finishReason": "STOP"}],
                                     "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 10}})
                elif kind == "text":
                    self._send(200, {"candidates": [{"content": {"parts": [{"text": payload}]}, "finishReason": "STOP"}]})
                elif kind == "blocked":
                    self._send(200, {"promptFeedback": {"blockReason": "SAFETY"}})
                else:
                    self._send(int(kind), {"error": {"code": int(kind), "status": "RESOURCE_EXHAUSTED" if kind == "429" else "ERROR"}})
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.reset()

    def reset(self, models=(), replies=()):
        self.models, self.replies, self.log, self.gen_count = list(models), list(replies), [], 0

    @property
    def count(self):
        return len(self.log)

    def stop(self):
        self.srv.shutdown()


class MockDrive:
    """Local stand-in for the Drive v3 REST API serving one synthetic package folder."""
    def __init__(self, pkg_root, d):
        import http.server, threading, urllib.parse
        outer = self
        pdir = glob.glob(os.path.join(pkg_root, "*"))[0]
        idx = json.load(open(os.path.join(pdir, "SOURCE_INDEX.json")))
        idx["daily_mover"]["drive_file_id"] = "DM"
        self.files = {"PKG": {"id": "PKG", "name": os.path.basename(pdir), "parent": "ROOT", "mimeType": "application/vnd.google-apps.folder"},
                      "IDX": {"id": "IDX", "name": "SOURCE_INDEX.json", "parent": "PKG", "body": json.dumps(idx).encode()},
                      "DM": {"id": "DM", "name": "dm.pdf", "parent": "PKG", "body": open(os.path.join(pdir, "daily_mover.pdf"), "rb").read()}}
        self.methods, self.forbid = set(), False

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                outer.methods.add("GET")
                if outer.forbid:
                    self.send_response(403); self.end_headers(); return
                u = urllib.parse.urlparse(self.path); qs = urllib.parse.parse_qs(u.query)
                fid = u.path.rsplit("/", 1)[-1]
                if fid in outer.files and qs.get("alt") == ["media"]:
                    b = outer.files[fid]["body"]
                elif fid == "files":
                    q = qs.get("q", [""])[0]
                    par = q.split("'")[1]
                    hits = [f for f in outer.files.values() if f["parent"] == par
                            and ("name='SOURCE_INDEX.json'" not in q or f["name"] == "SOURCE_INDEX.json")]
                    b = json.dumps({"files": [{k: v for k, v in f.items() if k != "body"} for f in hits]}).encode()
                else:
                    self.send_response(404); self.end_headers(); return
                self.send_response(200); self.send_header("Content-Length", str(len(b))); self.end_headers(); self.wfile.write(b)

            def do_POST(self):
                outer.methods.add("POST"); self.send_response(405); self.end_headers()
        self.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.url = f"http://127.0.0.1:{self.srv.server_address[1]}"
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def stop(self):
        self.srv.shutdown()


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
        record("chart value not in source is caught", "chart.bars" in probs(lambda r: r["chart"]["bars"][0].update(value=233.3)))
        record("another company's ASX code is caught", "ABC" in probs(lambda r: r["facts"][0].update(body="Peer ASX: ABC signed a similar deal.")))
        record("'draft' wording is caught", "draft" in probs(lambda r: r.update(take=r["take"] + " This draft is final.")))
        record("clock time is caught", "clock" in probs(lambda r: r.update(lede=r["lede"] + " As at 10:25 the move held.")))
        record("advice language is caught", "advice" in probs(lambda r: r.update(take=r["take"] + " We recommend investors buy now.")))
        record("missing Vitti attribution is caught", "attribute" in probs(lambda r: r["caption"].update(intro=r["caption"]["intro"].replace("According to the Vitti Capital Daily Mover dated 18 November 2026, ", ""))))
        record("over-long title is caught", "title" in probs(lambda r: r.update(title="T" * 60)))
        record("em dash is replaced, not published", "—" not in json.dumps(checks.sanitize(dict(GOOD, take=GOOD["take"] + " — x")), ensure_ascii=False))
        record("small counts and years are not treated as figures", checks.unsupported_numbers("two of 3 approvals in 2027", set(), set()) == [])
        record("money is never exempt", checks.unsupported_numbers("a $5 fee", set(), set()) == ["5"])

        print("== 3. write -> check -> render loop (fixture writer stands in for the AI)")
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
        main_files = {"pdf": res["pdf"], "png": res["png"]}  # later sections reuse `res` for other reports
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
        # The owner switched publication on (rights confirmed in writing). The config must stay consistent: publish never
        # without rights, Gemini stays off, and the template writer (no AI) is used.
        record("repository config: publish only with rights confirmed; Gemini off; template writer",
               (g["publish"] is not True or (g["rights_confirmed"] is True and g["enabled"] is True))
               and g.get("gemini_data_use_authorised") is not True and g.get("writer_mode") == "template")
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

        print("== 6. MODE B: deterministic report, no AI, no API")
        from tar_gen.template import TemplateWriter
        from tar_gen.dailymover import parse as dm_parse
        dm = dm_parse(pkg.daily_mover_path, ident.company)
        record("structured reader: 4 KPI tiles, chart, 3 drivers, 3 changes, 3 timeline entries, 3 risks, view, sources",
               len(dm["kpis"]) == 4 and dm["chart"] and len(dm["drivers"]) == 3 and len(dm["changes"]) == 3
               and len(dm["timeline"]) == 3 and len(dm["risks"]) == 3 and dm["view"] and dm["source"])
        tw = TemplateWriter(ident, pkg.daily_mover_path)
        rb = build(ident, tw, os.path.join(tmp, "modeb"), log=lambda *_: None)
        rep = rb["rep"]
        record("MODE B report passes every content, layout and PDF check", rb["attempts"] >= 1 and os.path.isfile(rb["pdf"]))
        record("MODE B figures are Vitti's exactly (KPI values and chart)",
               [k["value"] for k in rep["kpis"]] == ["+12.4%", "$85.0M", "$42.5M", "FY27"]
               and [b["display"] for b in rep["chart"]["bars"]] == ["$255.0m FY25", "$310.2m FY26"])
        record("MODE B adds no analysis: page 2 is Vitti's drivers, risks and view, labelled as Vitti's",
               rep["take_label"] == "Vitti view" and rep["take"].startswith("The offtake answers")
               and [w["body"] for w in rep["watch"]][2].startswith("One buyer takes 70%"))
        record("MODE B removes the clock time from the share-move tile", not any(":" in k["note"] for k in rep["kpis"]))
        txtb = " ".join(subprocess.run(["pdftotext", "-layout", rb["pdf"], "-"], capture_output=True, text=True).stdout.split())
        record("MODE B PDF says the Vitti view is Vitti's own commentary", "Vitti view is Vitti Capital's own commentary" in txtb)
        Pb = make_handoff(ident, rb, pkg, flags, "template", writer_mode=tw.mode)
        record("MODE B handoff accepted by the REAL publisher (verify mode)", "VERIFY PASS" in contract_check(Pb, rb["pdf"], rb["png"]))
        rthin = tempfile.mkdtemp(dir=tmp); make_package(rthin, drop_risks=True)
        pthin = LocalSource(rthin).packages_for(D)[0]
        expect_gen_error("MODE B refuses a Daily Mover missing a needed section (no invented content)",
                         lambda: TemplateWriter(verify_package(pthin, D, GEN), pthin.daily_mover_path), "INSUFFICIENT_SOURCE")
        try:
            TemplateWriter(verify_package(pthin, D, GEN), pthin.daily_mover_path)
        except GenError as e:
            record("the refusal names exactly the missing section", e.msg.endswith(": three key risks"), e.msg)
        rc = RUN.main(["--local", rthin, "--date", D.isoformat(), "--out", os.path.join(tmp, "thin"), "--no-notify"])
        record("insufficient source: run stops (exit 1) and writes no handoff", rc == 1 and not glob.glob(os.path.join(tmp, "thin", "**", "publish.json"), recursive=True))
        rc = RUN.main(["--local", root, "--date", D.isoformat(), "--out", os.path.join(tmp, "cli_b"), "--no-notify"])
        Pcli = json.load(open(glob.glob(os.path.join(tmp, "cli_b", "reports", "*", "publish.json"))[0]))
        record("default configuration runs MODE B end to end (no API key anywhere)", rc == 0 and Pcli["generator"]["writer_mode"] == "B-template")

        print("== 7. MODE A: Gemini free tier against a local mock server (synthetic data only)")
        mock = MockGemini()
        os.environ.update(GEMINI_API_BASE=mock.url, GEMINI_API_KEY="test-key-not-real", TAR_GEMINI_PAUSE="0")
        from tar_gen.writer import GeminiWriter
        gcfg = dict(g, writer_mode="gemini", gemini_models=["gemini-x-lite", "gemini-y"], gemini_data_use_authorised=True)

        def run_mode(cfgv, name):
            o = os.path.join(tmp, name)
            return RUN.write_report(ident, pkg, cfgv, o, log=lambda *_: None)

        mock.reset(models=["gemini-y", "gemini-x-lite"], replies=[("ok", GOOD)])
        res, wm, model, fb = run_mode(gcfg, "ga1")
        record("authorised + quota available: MODE A used, first configured model the key offers", wm == "A-gemini" and model == "gemini-x-lite" and fb is None)
        record("API key sent in the x-goog-api-key header, never in the URL",
               all(r["key"] == "test-key-not-real" and "key=" not in r["path"] for r in mock.log))
        mock.reset(models=["gemini-x-lite"], replies=[("ok", GOOD)])
        res, wm, model, fb = run_mode(dict(gcfg, gemini_data_use_authorised=False), "ga2")
        record("NOT authorised: Gemini never contacted (0 requests), MODE B used", wm == "B-template" and mock.count == 0 and fb == "AI_NOT_AUTHORISED")
        expect_gen_error("GeminiWriter itself refuses without authorisation", lambda: GeminiWriter(["gemini-x-lite"], False), "AI_NOT_AUTHORISED")
        mock.reset(models=["gemini-x-lite"], replies=[("429", None)])
        res, wm, model, fb = run_mode(gcfg, "ga3")
        record("free quota exhausted (429): falls back to MODE B and still produces the report", wm == "B-template" and fb == "AI_QUOTA" and os.path.isfile(res["pdf"]))
        mock.reset(models=["gemini-x-lite"], replies=[("500", None)] * 6)
        res, wm, model, fb = run_mode(gcfg, "ga4")
        record("Gemini outage (repeated 500): retried, then MODE B", wm == "B-template" and fb == "AI_UNAVAILABLE" and mock.gen_count == 3)
        mock.reset(models=["gemini-other"], replies=[])
        res, wm, model, fb = run_mode(gcfg, "ga5")
        record("configured model not offered to the key: MODE B", fb == "AI_MODEL_UNAVAILABLE" and wm == "B-template")
        mock.reset(models=["gemini-x-lite"], replies=[("text", "not json")])
        res, wm, model, fb = run_mode(gcfg, "ga6")
        record("malformed AI reply: MODE B", fb == "AI_BAD_JSON" and wm == "B-template")
        mock.reset(models=["gemini-x-lite"], replies=[("ok", bad)] * 3)
        res, wm, model, fb = run_mode(gcfg, "ga7")
        record("AI keeps inventing a figure (3 attempts): its report is discarded, MODE B used", fb == "CHECKS_FAILED" and wm == "B-template")
        mock.reset(models=["gemini-x-lite"], replies=[("blocked", None)])
        res, wm, model, fb = run_mode(gcfg, "ga8")
        record("AI safety block: MODE B", fb == "AI_BLOCKED" and wm == "B-template")
        mock.reset(models=["gemini-x-lite"], replies=[("401", None)])
        res, wm, model, fb = run_mode(gcfg, "ga9")
        record("invalid key (401): MODE B", fb == "AI_AUTH" and wm == "B-template")
        mock.reset(models=["gemini-x-lite"], replies=[("429", None)])
        expect_gen_error("fallback switched off: quota error stops the run", lambda: run_mode(dict(gcfg, fallback_to_template=False), "ga10"), "AI_QUOTA")
        mock.reset(models=["gemini-x-lite"], replies=[("429", None)])
        expect_gen_error("neither mode can produce an accurate report: stop with the reason",
                         lambda: RUN.write_report(verify_package(pthin, D, GEN), pthin, gcfg, os.path.join(tmp, "ga11"), log=lambda *_: None), "INSUFFICIENT_SOURCE")
        mock.reset(models=["gemini-x-lite"], replies=[])
        os.environ.pop("GEMINI_API_KEY")
        res, wm, model, fb = run_mode(gcfg, "ga12")
        record("no GEMINI_API_KEY secret: MODE B, nothing sent", fb == "AI_NOT_CONFIGURED" and mock.count == 0)
        mock.stop()
        for k in ("GEMINI_API_BASE", "TAR_GEMINI_PAUSE"):
            os.environ.pop(k, None)

        print("== 8. public logs, summaries and artifacts carry no confidential content")
        summ = os.path.join(tmp, "summary.md")
        env = dict(os.environ, GITHUB_ACTIONS="true", GITHUB_REF="refs/heads/claude/test", GITHUB_STEP_SUMMARY=summ)
        env.pop("GITHUB_TOKEN", None)
        secret_bits = ["TMZ", "Test Minerals", "85.0", "42.5", "1.250", "Offtake", "offtake", "Japanese", "12.4"]
        for label, extra in (("successful run", []), ("failing run", ["--fixture-writer", _dump(tmp, [bad, bad, bad])])):
            cfgp = os.path.join(tmp, "cfg.json")
            c2 = json.load(open(os.path.join(ROOT, "config", "auto-publish.json")))
            json.dump(c2, open(cfgp, "w"))
            pr = subprocess.run([sys.executable, "-m", "tar_gen.run", "--local", root, "--date", D.isoformat(), "--out",
                                 os.path.join(tmp, "pub_" + label[:4]), "--config", cfgp] + extra,
                                cwd=ROOT, env=env, capture_output=True, text=True)
            seen = pr.stdout + pr.stderr + (open(summ).read() if os.path.exists(summ) else "")
            leaks = [b for b in secret_bits if b in seen]
            record(f"public log + step summary of a {label}: no ticker, company, figures or report text", not leaks and pr.stdout.strip(), f"leaked {leaks}")
        wfs = "".join(open(f).read() for f in glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")))
        record("no workflow uploads artifacts or caches (report files never leave the runner)",
               "upload-artifact" not in wfs and "actions/cache" not in wfs and "TAR_REVIEW_PASSWORD" not in wfs)
        record("the real-data CI shadow job deletes its output and runs without notifications",
               'rm -rf "$RUNNER_TEMP/tar-shadow"' in wfs and "--no-notify" in wfs)
        runsrc = open(os.path.join(ROOT, "tar_gen", "run.py")).read()
        record("failure issue body uses only the reason code and a fixed description",
               'notify.notify_failure(d, e.code, REASONS.get(e.code, "see the reason code"), run_url())' in runsrc
               and "notify.notify_failure(d, e.code, e.msg" not in runsrc)

        print("== 9. duplicate protection")
        fake = tempfile.mkdtemp(dir=tmp)
        os.makedirs(os.path.join(fake, "reports", "2026-11-10-ABC"))
        json.dump({"vitti_source": {"email_message_id": ident.gmail_id, "pdf_sha256": "x"}}, open(os.path.join(fake, "reports", "2026-11-10-ABC", "publish.json"), "w"))
        os.makedirs(os.path.join(fake, "reports", "2026-11-18-XYZ"))
        saved_root, RUN.ROOT = RUN.ROOT, fake
        try:
            record("an email already used by an earlier report is refused", RUN.used_before(ident) is not None)
            record("a second report for a day that already has one is refused", bool(RUN.existing_report(D)))
        finally:
            RUN.ROOT = saved_root

        print("== 11. publishing gates: the EXISTING publisher refuses automated handoffs unless every generator switch is on")
        def sandbox_run(Pv, cfg_over, mode):
            t = tempfile.mkdtemp(dir=tmp)
            shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(t, "tools"), ignore=shutil.ignore_patterns("__pycache__"))
            shutil.copytree(os.path.join(ROOT, "config"), os.path.join(t, "config"))
            c = json.load(open(os.path.join(t, "config", "auto-publish.json")))
            c["enabled"] = True
            c["vitti_generator"].update(cfg_over)
            json.dump(c, open(os.path.join(t, "config", "auto-publish.json"), "w"))
            rel = "reports/2026-11-18-TMZ"
            os.makedirs(os.path.join(t, rel))
            shutil.copy(main_files["pdf"], os.path.join(t, rel)); shutil.copy(main_files["png"], os.path.join(t, rel))
            json.dump(Pv, open(os.path.join(t, rel, "publish.json"), "w"))
            state = {"creates": 0}

            def gql(q, v=None, soft=False):
                if "createPost" in q:
                    state["creates"] += 1; i = v["i"]
                    state["node"] = {"id": "MOCK1", "status": "scheduled", "text": i["text"], "dueAt": i["dueAt"], "channelId": i["channelId"],
                                     "assets": [{"source": i["assets"][0]["document"]["url"], "thumbnail": i["assets"][0]["document"]["thumbnailUrl"],
                                                 "document": {"title": i["assets"][0]["document"]["title"]}}]}
                    return {"createPost": {"__typename": "PostActionSuccess", "post": {"id": "MOCK1"}}}
                if "account{" in q:
                    return {"account": {"id": "a", "organizations": [{"id": BS.ORG_ID, "name": "o"}]}}
                if "channels(" in q:
                    return {"channels": [{"id": BS.CHANNEL_ID, "displayName": BS.CHANNEL_NAME, "service": "linkedin", "isDisconnected": False, "isLocked": False}]}
                if "posts(" in q:
                    return {"posts": {"edges": [], "pageInfo": {"hasNextPage": False, "endCursor": None}}}
                if "post(input" in q:
                    return {"post": state["node"]}
                raise AssertionError(q[:50])
            saved = (BS.MODE, BS.gql, BS.now_syd, BS.verify_public, os.getcwd(), dict(BS.CTX))
            env_saved = {k: os.environ.get(k) for k in ("PAYLOAD", "GITHUB_EVENT_NAME", "GITHUB_REF", "BUFFER_API_KEY")}
            BS.MODE, BS.gql = mode, gql
            BS.now_syd = lambda: datetime(2026, 11, 18, 12, 0, tzinfo=BS.SYD)
            BS.verify_public = lambda *a, **k: "stubbed public check"
            os.environ.update(PAYLOAD=f"{rel}/publish.json", GITHUB_EVENT_NAME="workflow_run", GITHUB_REF="refs/heads/main", BUFFER_API_KEY="mock")
            BS.CTX.clear(); BS.CTX["folder"] = None
            os.chdir(t)
            buf, code = io.StringIO(), None
            try:
                with contextlib.redirect_stdout(buf):
                    try:
                        BS.main()
                    except SystemExit as e:
                        code = e.code
            finally:
                os.chdir(saved[4])
                BS.MODE, BS.gql, BS.now_syd, BS.verify_public = saved[:4]
                BS.CTX.clear(); BS.CTX.update(saved[5])
                for k, v in env_saved.items():
                    if v is None:
                        os.environ.pop(k, None)
                    else:
                        os.environ[k] = v
            return code, buf.getvalue(), state["creates"]

        auto = copy.deepcopy(P)
        off = {"enabled": False, "publish": False, "rights_confirmed": False}
        code, out, n = sandbox_run(auto, off, "scheduled")
        record("automated handoff, generator switches off: refused, no Buffer post (started by workflow_run)", n == 0 and "TAR_GEN_GATE" in out, out[-160:])
        code, out, n = sandbox_run(auto, {"enabled": True, "publish": True, "rights_confirmed": False}, "scheduled")
        record("automated handoff, rights not confirmed: refused", n == 0 and "rights_confirmed" in out)
        code, out, n = sandbox_run(auto, {"enabled": False, "publish": True, "rights_confirmed": True}, "scheduled")
        record("automated handoff, generator disabled: refused", n == 0 and "TAR_GEN_GATE" in out and "enabled" in out)
        code, out, n = sandbox_run(auto, {"enabled": True, "publish": True, "rights_confirmed": True}, "scheduled")
        record("automated handoff, every switch on: exactly one (mocked) Buffer post", n == 1 and "SCHEDULED: Buffer post MOCK1" in out, out[-200:])
        disguised = copy.deepcopy(auto); disguised.pop("generator")
        code, out, n = sandbox_run(disguised, off, "scheduled")
        record("automated handoff with its generator field removed is still recognised and refused", n == 0 and "TAR_GEN_GATE" in out)
        manual = copy.deepcopy(auto); manual.pop("generator"); manual["vitti_source"].pop("drive_package_folder_id")
        code, out, n = sandbox_run(manual, off, "scheduled")
        record("manual / legacy schema 4 handoff unaffected by the generator switches", n == 1 and "TAR_GEN_GATE" not in out, out[-200:])
        code, out, n = sandbox_run(auto, off, "dryrun")
        record("dryrun reports the gate for an automated handoff", n == 0 and "TAR_GEN_GATE" in out)
        code, out, n = sandbox_run(auto, off, "verify")
        record("verify mode (the generator's shadow contract check) stays available with switches off", "VERIFY PASS" in out and n == 0)
        os.environ.update(GITHUB_ACTIONS="true", GITHUB_REF="refs/heads/main")
        ok, why = RUN.publish_allowed(dict(cfg, enabled=True), dict(g, enabled=False, publish=True, rights_confirmed=True))
        record("generator publish gate also requires vitti_generator.enabled", not ok and any("vitti_generator.enabled" in w for w in why))
        for k in ("GITHUB_ACTIONS", "GITHUB_REF"):
            os.environ.pop(k, None)

        print("== 11b. duplicate rule in live runs vs the private --latest test")
        fake2 = tempfile.mkdtemp(dir=tmp)
        shutil.copytree(os.path.join(ROOT, "config"), os.path.join(fake2, "config"))
        os.makedirs(os.path.join(fake2, "reports", "2026-11-18-TMZ"))
        json.dump({"vitti_source": {"email_message_id": ident.gmail_id, "pdf_sha256": "x"}},
                  open(os.path.join(fake2, "reports", "2026-11-18-TMZ", "publish.json"), "w"))
        saved_root, saved_today = RUN.ROOT, RUN.today_syd
        RUN.ROOT, RUN.today_syd = fake2, (lambda: D)
        try:
            rc_dup = RUN.main(["--local", root, "--date", D.isoformat(), "--out", os.path.join(tmp, "dup1"), "--no-notify"])
            record("an already-published Vitti email stops a normal run (exit 1, no handoff)",
                   rc_dup == 1 and not glob.glob(os.path.join(tmp, "dup1", "**", "publish.json"), recursive=True))
            rc_lat = RUN.main(["--local", root, "--latest", "3", "--out", os.path.join(tmp, "dup2"), "--no-notify"])
            record("the private --latest test builds it anyway, in shadow mode only",
                   rc_lat == 0 and glob.glob(os.path.join(tmp, "dup2", "**", "publish.json"), recursive=True)
                   and not os.path.exists(os.path.join(ROOT, "reports", "2026-11-18-TMZ")))
        finally:
            RUN.ROOT, RUN.today_syd = saved_root, saved_today

        print("== 11c. production keeps one report per day; only the private shadow button builds past it")
        fake3 = tempfile.mkdtemp(dir=tmp)
        shutil.copytree(os.path.join(ROOT, "config"), os.path.join(fake3, "config"))
        c3 = json.load(open(os.path.join(fake3, "config", "auto-publish.json")))
        c3["vitti_generator"]["enabled"] = True
        json.dump(c3, open(os.path.join(fake3, "config", "auto-publish.json"), "w"))
        os.makedirs(os.path.join(fake3, "reports", "2026-11-18-ABC"))
        saved_root, saved_today = RUN.ROOT, RUN.today_syd
        RUN.ROOT, RUN.today_syd = fake3, (lambda: D)
        try:
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc_prod = RUN.main(["--config", os.path.join(fake3, "config", "auto-publish.json"), "--ignore-schedule", "--no-notify",
                                    "--out", os.path.join(tmp, "prod")])
            record("production run on a day that already has a report: stops before reading Drive or building",
                   rc_prod == 0 and "ALREADY HAVE A REPORT FOR 2026-11-18" in buf.getvalue() and not os.path.exists(os.path.join(tmp, "prod")))
        finally:
            RUN.ROOT, RUN.today_syd = saved_root, saved_today
        wfg = open(os.path.join(ROOT, ".github", "workflows", "tar-generate.yml")).read()
        record("the shadow button runs the private --latest test (no notifications, output deleted)",
               'shadow) rc=0; python3 -m tar_gen.run --latest 10 --no-notify --out "$RUNNER_TEMP/tar-shadow"' in wfg
               and 'rm -rf "$RUNNER_TEMP/tar-shadow"; exit $rc' in wfg)
        record("the scheduled production path is unchanged", "*) python3 -m tar_gen.run ;;" in wfg)

        print("== 12. Drive reader against a mock Drive API (no Google account needed)")
        from tar_gen.source import DriveSource
        mdrive = MockDrive(root, D)
        import requests
        ds = object.__new__(DriveSource)
        ds.http, ds.root, ds.workdir, ds.API = requests.Session(), "ROOT", tempfile.mkdtemp(dir=tmp), mdrive.url + "/drive/v3/files"
        pk = ds.packages_for(D)
        record("Drive: finds the day's package, downloads SOURCE_INDEX and the Daily Mover", len(pk) == 1 and os.path.isfile(pk[0].daily_mover_path))
        record("Drive: package passes the same identity checks as a local one", verify_package(pk[0], D, GEN).ticker == "TMZ")
        record("Drive: only GET requests are made (read-only)", mdrive.methods == {"GET"})
        mdrive.forbid = True
        expect_gen_error("Drive: missing folder share (403) is reported clearly", lambda: ds.packages_for(D), "DRIVE_FORBIDDEN")
        mdrive.stop()

        print("== 13. spelling and grammar checks")
        record("a likely typo stops the report", "misspelling" in probs(lambda r: r["facts"][1].update(body="The price is fixed for the frist two years of the agreement.")))
        record("a repeated word stops the report", "repeated word" in probs(lambda r: r["facts"][1].update(body="The price is fixed for the the first two years.")))
        record("broken punctuation stops the report", "punctuation" in probs(lambda r: r.update(take=r["take"].replace(".", " .", 1))))
        record("unbalanced brackets stop the report", "brackets" in probs(lambda r: r["facts"][1].update(body="The price is fixed (for the first two years.")))
        record("finance jargon and names are not flagged", checks.check_report(checks.sanitize(GOOD), ident) == [])
        from tar_gen.dailymover import sentence_case
        record("Vitti's upper-case labels keep their acronyms", sentence_case("AI HPC CANCELLATION RECOVERY") == "AI HPC cancellation recovery"
               and sentence_case("TOTAL BACKLOG (30 SEP 26)") == "Total backlog (30 Sep 26)")

        print("== 14. unexpected errors never print details in a public run")
        envc = dict(os.environ, GITHUB_ACTIONS="true", GITHUB_REF="refs/heads/claude/test")
        envc.pop("GITHUB_TOKEN", None)
        pr = subprocess.run([sys.executable, "-c", "import sys; sys.path.insert(0, '.'); from tar_gen import run as R; "
                             "R.main = lambda a=None: (_ for _ in ()).throw(ValueError('SECRET Test Minerals 85.0')); sys.exit(R.safe_main([]))"],
                            cwd=ROOT, env=envc, capture_output=True, text=True)
        record("crash in a public run: type only, no traceback or message", pr.returncode == 1 and "UNEXPECTED_ERROR: ValueError" in pr.stdout
               and "SECRET" not in pr.stdout + pr.stderr and "Traceback" not in pr.stderr)

        if hist:
            print(f"== 10. historical Vitti packages from {hist} (kept outside the repository)")
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
                try:
                    rb = build(hid, TemplateWriter(hid, hp.daily_mover_path), os.path.join(tmp, "histb", name), log=lambda *_: None)
                    Pb = make_handoff(hid, rb, hp, dict(hid.checks, final_pdf_valid=True, visual_check_done=True, no_duplicate=True,
                                                       master_switch_enabled=True), "template", writer_mode="B-template")
                    record(f"{name}: MODE B report + real publisher verify", "VERIFY PASS" in contract_check(Pb, rb["pdf"], rb["png"]))
                except GenError as e:
                    record(f"{name}: MODE B report", False, f"{e.code}: {e.msg[:200]}")
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
               "status": "AWAITING_VERIFICATION",
               "daily_mover": {"status": "found", "name": f"{tk}-{d.isoformat()}-draft.pdf", "sha256": sha,
                               "drive_file_id": "HISTORICAL", "saved": True, "size_verified": True}, "files": []},
              open(os.path.join(p, "SOURCE_INDEX.json"), "w"))


if __name__ == "__main__":
    sys.exit(main())
