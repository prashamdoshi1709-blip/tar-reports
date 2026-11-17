"""Schema 4 (vitti-source/1) handoff for the EXISTING publisher, and a contract check that runs that publisher on it.

publish.json follows tools/filing_contract.validate_v4 exactly. claude_verification is the publisher's historical field
name for "the producer's attestations"; here every flag is set only from a check this pipeline actually ran:

  vitti_sender_verified  allowed sender + dkim=pass recorded by Gmail                (tar_gen.vitti)
  vitti_pdf_readable     Daily Mover sha256 matches SOURCE_INDEX, real text layer       (tar_gen.vitti)
  company_date_match     ticker, company and date agree in subject, file, metadata, text (tar_gen.vitti)
  final_pdf_valid        tools/verify_clean_pdf.py PASS + the publisher's own checks    (contract_check below)
  visual_check_done      automated layout and page-fill check                           (tar_gen.render.visual_check)
  no_duplicate           no report, manual marker or handoff for this date / email      (tar_gen.run)
  master_switch_enabled  config/auto-publish.json enabled is true                       (tar_gen.run)
"""
import contextlib, io, json, os, shutil, tempfile
from datetime import datetime

from .common import FC, GenError, ROOT, SYD, GENERATOR_VERSION, folder_rel, long_date, public_urls, sha256_file


def make_handoff(ident, result, pkg, flags, model, run_id=None):
    pdf_url, cover_url = public_urls(ident.ticker, ident.date)
    P = {
        "schema": 4, "mode": "LIVE", "ticker": ident.ticker, "company_name": ident.company,
        "report_date": long_date(ident.date), "report_date_iso": ident.date.isoformat(),
        "package_id": pkg.package_id, "handoff_created_at": datetime.now(SYD).isoformat(timespec="seconds"),
        "pdf_sha256": sha256_file(result["pdf"]), "pdf_url": pdf_url, "cover_url": cover_url,
        "title": result["title"], "caption": result["caption"],
        "vitti_source": {"basis": "VITTI_DAILY_MOVER", "email_message_id": ident.gmail_id, "pdf_name": ident.dm_name,
                         "pdf_sha256": ident.dm_sha, "independently_verified": False,
                         "rfc822_message_id": ident.rfc822, "drive_package_folder_id": pkg.folder_id,
                         "supporting_announcements": [n for n, _ in ident.support]},
        "claude_verification": {k: bool(flags.get(k)) for k in FC.V4_FLAGS},
        "generator": {"name": "tar_gen", "version": GENERATOR_VERSION, "model": model, "attempts": result["attempts"],
                      "run_id": run_id, "cover_sha256": sha256_file(result["png"])},
    }
    FC.validate_v4(P)  # same validator the publisher uses; raises ContractError
    return P


def contract_check(P, pdf, png):
    """Run the REAL tools/buffer_schedule.py main() in MODE=verify on a sandbox copy containing this report. Pages is
    simulated by serving the local files to tools/public_verify.py, so every publisher check (schema 4 contract, title,
    caption, file names, sha256, verify_clean_pdf, qpdf, cover PNG) runs for real. No network, no Buffer, nothing committed.
    Returns the publisher's output; raises GenError unless it ends in VERIFY PASS."""
    from .common import BS
    import public_verify as PV
    rel = folder_rel(P["ticker"], datetime.strptime(P["report_date_iso"], "%Y-%m-%d").date())
    t = tempfile.mkdtemp(prefix="tar_contract_")
    try:
        shutil.copytree(os.path.join(ROOT, "tools"), os.path.join(t, "tools"), ignore=shutil.ignore_patterns("__pycache__"))
        shutil.copytree(os.path.join(ROOT, "config"), os.path.join(t, "config"))
        os.makedirs(os.path.join(t, rel))
        shutil.copy(pdf, os.path.join(t, rel, os.path.basename(pdf)))
        shutil.copy(png, os.path.join(t, rel, os.path.basename(png)))
        json.dump(P, open(os.path.join(t, rel, "publish.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        served = {P["pdf_url"]: os.path.join(t, rel, os.path.basename(pdf)), P["cover_url"]: os.path.join(t, rel, os.path.basename(png))}

        def local_get(url, timeout=30):
            base = url.split("?v=")[0]
            if base not in served:
                raise PV.urllib.error.HTTPError(url, 404, "not served", {}, None)
            body = open(served[base], "rb").read()
            return 200, "application/pdf" if base.endswith(".pdf") else "image/png", body

        saved = (PV._get, BS.MODE, os.environ.get("PAYLOAD"), os.getcwd(), dict(BS.CTX))
        PV._get, BS.MODE = local_get, "verify"
        os.environ["PAYLOAD"] = f"{rel}/publish.json"
        os.chdir(t)
        buf, code = io.StringIO(), None
        try:
            with contextlib.redirect_stdout(buf):
                try:
                    BS.main()
                except SystemExit as e:
                    code = e.code
        finally:
            PV._get, BS.MODE = saved[0], saved[1]
            if saved[2] is None:
                os.environ.pop("PAYLOAD", None)
            else:
                os.environ["PAYLOAD"] = saved[2]
            os.chdir(saved[3])
            BS.CTX.clear(); BS.CTX.update(saved[4])
        out = buf.getvalue()
        if code not in (None, 0) or "VERIFY PASS" not in out:
            reason = next((l for l in out.splitlines() if "NOT SCHEDULED" in l), out.strip()[-300:])
            raise GenError("PUBLISHER_REJECTED", f"the existing publisher rejected the handoff: {reason}")
        return out
    finally:
        shutil.rmtree(t, ignore_errors=True)
