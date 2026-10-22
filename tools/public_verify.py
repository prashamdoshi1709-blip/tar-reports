#!/usr/bin/env python3
"""Verification of what GitHub Pages actually serves for a TAR report (stdlib + poppler/qpdf).

Used by tools/buffer_schedule.py inside GitHub Actions. The Claude routine never fetches the public URL:
Actions downloads the PDF and cover from the public Pages URL itself and proves, before anything is
scheduled in Buffer, that

  * the URL answers HTTP 200 and the body is a real PDF (starts with %PDF-, qpdf --check clean),
  * the downloaded bytes have exactly the SHA-256 written in the verified handoff,
  * the downloaded PDF passes tools/verify_clean_pdf.py (exactly 2 pages, 810 x 1012.5 pt, PDF Title equal to
    the clean title, Lora/Inter embedded, no DRAFT / NOT APPROVED wording in text, metadata or raw bytes, no
    em dashes),
  * the cover PNG is a real PNG of sensible size whose SHA-256 equals the committed cover.

Pages deployment can lag a few minutes behind the push, so "not found", "not a PDF" and "different hash"
are retried until the deadline. A hash-matching file that fails structure/cleanliness checks is rejected at
once (retrying cannot fix it). Fail closed: any other outcome raises PublicVerifyError.
"""
import hashlib, os, re, struct, subprocess, sys, tempfile, time, urllib.error, urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
VERIFY_CLEAN = os.path.join(HERE, "verify_clean_pdf.py")
MAX_BYTES = 15 * 1024 * 1024
UA = "tar-buffer-schedule/1.1"


class PublicVerifyError(Exception):
    pass


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def _get(url, timeout=30):
    sep = "&" if "?" in url else "?"
    req = urllib.request.Request(f"{url}{sep}v={int(time.time() * 1000)}",
                                 headers={"User-Agent": UA, "Cache-Control": "no-cache"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        body = r.read(MAX_BYTES + 1)
        return r.status, r.headers.get("Content-Type", ""), body


def png_size(b):
    if len(b) < 24 or b[:8] != b"\x89PNG\r\n\x1a\n" or b[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", b[16:24])


def check_once(pdf_url, png_url, pdf_sha, clean_title, cover_sha):
    """Returns (ok, retryable, message)."""
    try:
        status, ctype, body = _get(pdf_url)
    except urllib.error.HTTPError as e:
        return False, True, f"public PDF URL answered HTTP {e.code}"
    except Exception as e:
        return False, True, f"public PDF URL not reachable ({type(e).__name__})"
    if status != 200:
        return False, True, f"public PDF URL answered HTTP {status}"
    if len(body) > MAX_BYTES:
        return False, False, "public PDF is larger than 15 MB"
    if len(body) < 1000 or not body.startswith(b"%PDF-"):
        return False, True, f"public URL did not return a PDF (content-type {ctype!r}, {len(body)} bytes)"
    got = sha256_bytes(body)
    if got != pdf_sha:
        return False, True, f"public PDF sha256 {got} != verified handoff sha256 {pdf_sha}"
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "public.pdf")
        open(p, "wb").write(body)
        q = subprocess.run(["qpdf", "--check", p], capture_output=True, text=True)
        if q.returncode != 0:
            return False, False, "downloaded PDF failed qpdf --check (damaged or truncated file)"
        r = subprocess.run([sys.executable, "-I", VERIFY_CLEAN, p, clean_title], capture_output=True, text=True)
        out = (r.stdout or "").strip()
        if r.returncode != 0 or "PASS" not in out or f"sha256 {pdf_sha}" not in out:
            fails = [ln.strip() for ln in out.splitlines() if ln.strip().startswith("-")]
            return False, False, "downloaded PDF failed structure/cleanliness checks: " + "; ".join(fails or [out[-200:]])
        print("  " + out.replace("\n", "\n  "))
    try:
        cstatus, cctype, cbody = _get(png_url)
    except urllib.error.HTTPError as e:
        return False, True, f"public cover URL answered HTTP {e.code}"
    except Exception as e:
        return False, True, f"public cover URL not reachable ({type(e).__name__})"
    if cstatus != 200:
        return False, True, f"public cover URL answered HTTP {cstatus}"
    size = png_size(cbody)
    if size is None or min(size) < 200 or len(cbody) < 1000 or len(cbody) > MAX_BYTES:
        return False, False, f"public cover is not a valid PNG of sensible size (size {size}, {len(cbody)} bytes)"
    if sha256_bytes(cbody) != cover_sha:
        return False, True, "public cover sha256 differs from the committed cover"
    return True, False, (f"public PDF {len(body)} bytes sha256 {got} and cover {size[0]}x{size[1]} verified "
                         f"(content-type {ctype!r})")


def verify_public(pdf_url, png_url, pdf_sha, clean_title, cover_sha, deadline_epoch, pause=15):
    """Poll until the public files verify, or raise PublicVerifyError. deadline_epoch bounds the retries."""
    last = "no attempt made"
    while True:
        ok, retryable, msg = check_once(pdf_url, png_url, pdf_sha, clean_title, cover_sha)
        if ok:
            return msg
        last = msg
        print(f"  attempt: {msg}" + (" (will retry)" if retryable else " (final)"))
        if not retryable:
            raise PublicVerifyError(msg)
        if time.time() + pause > deadline_epoch:
            raise PublicVerifyError(f"public files not verified in time: {last}")
        time.sleep(pause)
