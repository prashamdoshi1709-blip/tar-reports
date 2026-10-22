#!/usr/bin/env python3
"""Offline rejection tests for the TAR publishing verifier (no network, no Buffer, creates nothing).

Part A drives tools/public_verify.py against a local HTTP server that serves one good report and many
deliberately broken ones. Part B drives tools/buffer_schedule.py in its read-only `verify` mode on doctored copies
of a historical handoff (reports/2026-10-19-CGF/publish.json) and checks that each defect is rejected for the
right reason. Exit 0 only if the good case passes AND every bad case is rejected.
"""
import copy, http.server, json, os, shutil, subprocess, sys, tempfile, threading, time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, HERE)
from public_verify import verify_public, PublicVerifyError, sha256_bytes  # noqa: E402

GOOD_DIR = os.path.join(ROOT, "reports", "2026-10-19-CGF")
GOOD_PDF = open(os.path.join(GOOD_DIR, "TAR_CGF_19Oct2026.pdf"), "rb").read()
GOOD_PNG = open(os.path.join(GOOD_DIR, "TAR_CGF_19Oct2026_cover.png"), "rb").read()
PAYLOAD = json.load(open(os.path.join(GOOD_DIR, "publish.json"), encoding="utf-8"))
TITLE = f"{PAYLOAD['company_name']} (ASX: {PAYLOAD['ticker']}) - {PAYLOAD['title']}"
results = []


def record(name, ok, detail=""):
    results.append((name, ok))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  [{detail}]" if detail else ""))


class H(http.server.BaseHTTPRequestHandler):
    routes = {}

    def do_GET(self):
        path = self.path.split("?")[0]
        status, ctype, body = self.routes.get(path, (404, "text/html", b"<html>404</html>"))
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


def sh(*cmd):
    subprocess.run(cmd, check=True, capture_output=True)


def build_variants(tmp):
    v = {}
    src = os.path.join(tmp, "good.pdf")
    open(src, "wb").write(GOOD_PDF)
    v["truncated"] = GOOD_PDF[: len(GOOD_PDF) // 2]
    three = os.path.join(tmp, "three.pdf")
    sh("qpdf", "--empty", "--pages", src, "1-2", src, "1", "--", three)
    v["three_pages"] = open(three, "rb").read()
    v["wrong_size"] = open(os.path.join(ROOT, "test", "tar-upload-test.pdf"), "rb").read()
    v["dirty_bytes"] = GOOD_PDF + b"\n%% NOT APPROVED FOR PUBLICATION\n"
    return v


def expect(name, pdf_body, exp_sha=None, title=TITLE, cover_body=GOOD_PNG, cover_status=200, pdf_status=200,
           pdf_ctype="application/pdf", cover_sha=None, want_substr=None):
    H.routes = {"/r.pdf": (pdf_status, pdf_ctype, pdf_body), "/r_cover.png": (cover_status, "image/png", cover_body)}
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        sha = exp_sha or sha256_bytes(pdf_body)
        verify_public(f"http://127.0.0.1:{port}/r.pdf", f"http://127.0.0.1:{port}/r_cover.png", sha, title,
                      cover_sha or sha256_bytes(GOOD_PNG), time.time() + 1.0, pause=0.3)
        return True, ""
    except PublicVerifyError as e:
        return False, str(e)
    finally:
        srv.shutdown()


def part_a():
    print("== Part A: public-file verification against a local server")
    with tempfile.TemporaryDirectory() as tmp:
        var = build_variants(tmp)
        ok, msg = expect("good", GOOD_PDF)
        record("A1 good report is accepted", ok, msg)
        cases = [
            ("A2 wrong SHA-256 in handoff is rejected", dict(pdf_body=GOOD_PDF, exp_sha="0" * 64), "sha256"),
            ("A3 missing PDF (HTTP 404) is rejected", dict(pdf_body=b"x", pdf_status=404), "404"),
            ("A4 HTML page instead of a PDF is rejected", dict(pdf_body=b"<html>" + b"x" * 2000 + b"</html>",
                                                              pdf_ctype="text/html"), "did not return a PDF"),
            ("A5 truncated PDF (hash matches) is rejected", dict(pdf_body=var["truncated"]), "failed"),
            ("A6 three-page PDF is rejected", dict(pdf_body=var["three_pages"]), "pages=3"),
            ("A7 wrong page size / fonts is rejected", dict(pdf_body=var["wrong_size"]), "page size"),
            ("A8 wrong PDF title is rejected", dict(pdf_body=GOOD_PDF, title="Some Other Co (ASX: XXX) - Wrong"), "Title"),
            ("A9 NOT APPROVED wording in raw bytes is rejected", dict(pdf_body=var["dirty_bytes"]), "forbidden wording"),
            ("A10 missing cover (HTTP 404) is rejected", dict(pdf_body=GOOD_PDF, cover_status=404, cover_body=b"x"), "404"),
            ("A11 cover that is not a PNG is rejected", dict(pdf_body=GOOD_PDF, cover_body=b"not a png" * 300), "PNG"),
            ("A12 cover with a different hash is rejected", dict(pdf_body=GOOD_PDF, cover_sha="f" * 64), "cover sha256"),
        ]
        for name, kw, want in cases:
            ok, msg = expect(name, **kw)
            record(name, (not ok) and want.lower() in msg.lower(), msg[:110])


def run_verify(cwd, payload_rel):
    env = dict(os.environ, MODE="verify", PAYLOAD=payload_rel)
    env.pop("BUFFER_API_KEY", None)
    env.pop("GITHUB_EVENT_NAME", None)
    r = subprocess.run([sys.executable, "tools/buffer_schedule.py"], cwd=cwd, env=env, capture_output=True, text=True)
    return r.returncode, (r.stdout + r.stderr)


def part_b():
    print("== Part B: handoff payload and committed-file rejection (read-only verify mode)")
    def fresh():
        t = tempfile.mkdtemp()
        shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(t, "tools"))
        shutil.copytree(os.path.join(ROOT, "config"), os.path.join(t, "config"))
        shutil.copytree(GOOD_DIR, os.path.join(t, "reports", "2026-10-19-CGF"))
        return t, "reports/2026-10-19-CGF/publish.json"

    def mutate(fn):
        t, rel = fresh()
        p = copy.deepcopy(PAYLOAD)
        fn(p, t)
        json.dump(p, open(os.path.join(t, rel), "w", encoding="utf-8"), ensure_ascii=False)
        code, out = run_verify(t, rel)
        shutil.rmtree(t, ignore_errors=True)
        return code, out

    def sha_bad(p, t): p["pdf_sha256"] = "0" * 64
    def pdf_missing(p, t): os.remove(os.path.join(t, "reports/2026-10-19-CGF/TAR_CGF_19Oct2026.pdf"))
    def cover_missing(p, t): os.remove(os.path.join(t, "reports/2026-10-19-CGF/TAR_CGF_19Oct2026_cover.png"))
    def title_draft(p, t): p["title"] = "DRAFT Challenger offer"
    def title_long(p, t): p["title"] = "x" * 60
    def no_disclaimer(p, t): p["caption"] = p["caption"].replace("General information only. Not financial advice.", "")
    def flag_false(p, t): p["claude_verification"]["newer_asx_filings_none_material"] = False
    def not_ready(p, t): p["review_status"] = "NOT RESEARCH-READY"
    def url_wrong(p, t): p["pdf_url"] = p["pdf_url"].replace("CGF_19Oct2026.pdf", "OTHER.pdf")
    def schema_old(p, t): p["schema"] = 1
    def shelved(p, t): open(os.path.join(t, "reports/2026-10-19-CGF/SHELVED.md"), "w").write("shelved")
    def missing_key(p, t): del p["caption"]
    def pdf_swapped(p, t):  # a different but valid PDF committed under the right name: hash must catch it
        shutil.copy(os.path.join(ROOT, "reports", "2026-10-20-CTD", "TAR_CTD_20Oct2026.pdf"),
                    os.path.join(t, "reports/2026-10-19-CGF/TAR_CGF_19Oct2026.pdf"))
    cases = [
        ("B1 wrong committed PDF SHA-256", sha_bad, "sha256 does not match"),
        ("B2 committed PDF missing", pdf_missing, "committed PDF or cover missing"),
        ("B3 committed cover missing", cover_missing, "committed PDF or cover missing"),
        ("B4 title contains DRAFT", title_draft, "title invalid"),
        ("B5 title 55+ characters", title_long, "title invalid"),
        ("B6 caption without the disclaimer", no_disclaimer, "caption failed"),
        ("B7 a claude_verification flag is false", flag_false, "flags are not all true"),
        ("B8 review status not RESEARCH-READY", not_ready, "RESEARCH-READY"),
        ("B9 handoff URL differs from committed location", url_wrong, "URLs do not match"),
        ("B10 old schema", schema_old, "schema"),
        ("B11 report folder marked SHELVED", shelved, "SHELVED"),
        ("B12 handoff missing a required field", missing_key, "missing"),
        ("B13 a different valid PDF swapped in", pdf_swapped, "sha256 does not match"),
    ]
    for name, fn, want in cases:
        code, out = mutate(fn)
        record(name, code == 1 and "NOT SCHEDULED" in out and want.lower() in out.lower(),
               next((ln for ln in out.splitlines() if ln.startswith("NOT SCHEDULED")), out[-120:])[:110])
    # a payload path that is not a handoff folder, and no handoff at all, never schedule anything
    t, rel = fresh()
    code, out = run_verify(t, "reports/2026-10-19-CGF/TAR_CGF_19Oct2026.pdf")
    record("B14 a bare PDF path is not accepted as a handoff", code == 1 and "bad payload path" in out, out.strip()[-80:])
    shutil.rmtree(t, ignore_errors=True)


if __name__ == "__main__":
    part_a()
    part_b()
    bad = [n for n, ok in results if not ok]
    print(f"\n{len(results) - len(bad)}/{len(results)} checks as expected")
    if bad:
        print("UNEXPECTED:", *bad, sep="\n  ")
        sys.exit(1)
    print("VERIFYTEST PASS: the good report is accepted and every incorrect or missing file is rejected.")
