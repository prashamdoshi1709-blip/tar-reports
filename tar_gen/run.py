#!/usr/bin/env python3
"""TAR Vitti generator: Drive package -> report (MODE A Gemini free tier, or MODE B deterministic) -> two-page PDF +
cover + caption -> schema 4 handoff.

    python3 -m tar_gen.run                      # what GitHub Actions runs (today, Sydney)
    python3 -m tar_gen.run --check-connections  # Drive folder readable; Gemini key usable (synthetic prompt, no Vitti data)

Writer choice (config vitti_generator.writer_mode):
    "template"  MODE B only: no AI, no API, no cost, nothing sent outside the GitHub runner (default)
    "gemini"    MODE A first, ONLY if gemini_data_use_authorised is true and GEMINI_API_KEY is set; on quota exhaustion,
                outage, auth or model problems, a block, or a report that still fails the checks, fall back to MODE B.
MODE B refuses (INSUFFICIENT_SOURCE) when the Daily Mover lacks a section a report needs; then nothing is published.

Public logs: the repository is public, so in GitHub Actions the log, step summary and issues carry dates, reason codes
and hashes only, never company names, tickers before publication, figures or report text.
    python3 -m tar_gen.run --local DIR --date 2026-11-17 --fixture-writer replies.json --out /tmp/x   # offline

Publication gate (ALL required, otherwise SHADOW mode: everything is built and verified, nothing is committed):
    config/auto-publish.json  enabled == true                       (existing master switch, shared with the publisher)
    config/auto-publish.json  vitti_generator.publish == true        (this generator may hand off to the publisher)
    config/auto-publish.json  vitti_generator.rights_confirmed == true (owner confirmed the right to republish Vitti material)
    running in GitHub Actions on refs/heads/main
In publish mode the PDF, cover and publish.json are committed to main in one commit. The EXISTING workflow
"TAR Buffer Schedule" (tools/buffer_schedule.py) then re-verifies everything and is the only thing that talks to Buffer.

Exit codes: 0 = done, nothing to do, or a transient problem that the next scheduled run retries; 1 = final failure
(an issue is opened, the run turns red and GitHub emails the owner).
"""
import argparse, glob, json, os, shutil, subprocess, sys
from datetime import datetime, time as dtime, timedelta

from .common import CONFIG_PATH, GenError, ROOT, SYD, folder_rel, is_trading_day, load_config, parse_iso_date, today_syd
from . import notify
from .handoff import contract_check, make_handoff
from .pipeline import build
from .source import make_source
from .template import TemplateWriter
from .vitti import verify_package

PUBLIC = os.environ.get("GITHUB_ACTIONS") == "true"
FALLBACK_CODES = {"AI_QUOTA", "AI_UNAVAILABLE", "AI_AUTH", "AI_MODEL_UNAVAILABLE", "AI_BAD_REQUEST", "AI_BLOCKED",
                  "AI_BAD_JSON", "AI_TRUNCATED", "AI_NOT_CONFIGURED", "AI_NOT_AUTHORISED", "CHECKS_FAILED"}
REASONS = {
    "NO_PACKAGE": "no Vitti Daily Mover package in Drive for the day", "NO_VALID_PACKAGE": "packages failed verification",
    "DUPLICATE": "this Vitti email was already used", "INSUFFICIENT_SOURCE": "the Daily Mover lacks a section a report needs",
    "CHECKS_FAILED": "the report failed the content checks", "PDF_NOT_CLEAN": "the PDF failed verify_clean_pdf.py",
    "PUBLISHER_REJECTED": "the existing publisher's checks rejected the handoff",
    "MISSED_START_WINDOW": "no run reached the generator before the start deadline (GitHub schedule/dispatch too late)",
    "NOT_HANDED_TO_BUFFER": "a report exists but the publisher had not scheduled it by the cutoff",
    "PUBLISH_FAILED": "the publisher recorded a final failure for the day's report",
    "LINKEDIN_NOT_CONFIRMED": "Buffer has not confirmed a LinkedIn post for the day's report",
    "PUBLISH_BLOCKED_CREDENTIALS": "the Buffer API key is missing, expired or revoked",
}


def outcome(kind, code, detail=""):
    """One machine-readable line per run: PUBLISHED_HANDOFF / SHADOW_OK / SKIP / RETRY / FAIL plus a reason code."""
    line = f"OUTCOME: {kind} {code}" + (f" ({detail})" if detail else "")
    log(line)
    summary(f"**{line}**")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        open(out, "a").write(f"outcome={kind}\ncode={code}\n")


def safe(e):
    """Public-safe reason: code plus a fixed description. Detailed messages can contain tickers, names or figures."""
    if not PUBLIC:
        return f"{e.code}: {e.msg}"
    return f"{e.code}: {REASONS.get(e.code, 'see the reason code')}"


def log(msg):
    print(msg, flush=True)


def summary(md):
    p = os.environ.get("GITHUB_STEP_SUMMARY")
    if p:
        open(p, "a").write(md + "\n")


def run_url():
    s, r, i = os.environ.get("GITHUB_SERVER_URL"), os.environ.get("GITHUB_REPOSITORY"), os.environ.get("GITHUB_RUN_ID")
    return f"{s}/{r}/actions/runs/{i}" if s and r and i else "(local run)"


def hhmm(s):
    h, m = s.split(":")
    return dtime(int(h), int(m))


def existing_report(d):
    return sorted(glob.glob(os.path.join(ROOT, "reports", f"{d.isoformat()}-*")))


def used_before(ident):
    for p in glob.glob(os.path.join(ROOT, "reports", "*", "publish.json")):
        try:
            P = json.load(open(p, encoding="utf-8"))
        except ValueError:
            continue
        vs = P.get("vitti_source") or {}
        if vs.get("email_message_id") == ident.gmail_id or vs.get("pdf_sha256") == ident.dm_sha:
            return p
    return None


def publish_allowed(cfg, g):
    why = []
    if cfg.get("enabled") is not True:
        why.append("master switch enabled=false")
    if g.get("enabled") is not True:
        why.append("vitti_generator.enabled=false")
    if g.get("publish") is not True:
        why.append("vitti_generator.publish=false")
    if g.get("rights_confirmed") is not True:
        why.append("vitti_generator.rights_confirmed=false (republication rights not confirmed)")
    if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("GITHUB_REF") != "refs/heads/main":
        why.append("not a GitHub Actions run on main")
    return not why, why


def commit_and_push(files, rel, message):
    def git(*a):
        return subprocess.run(["git", *a], cwd=ROOT, capture_output=True, text=True)
    git("config", "user.name", "tar-generator-bot")
    git("config", "user.email", "actions@users.noreply.github.com")
    os.makedirs(os.path.join(ROOT, rel), exist_ok=True)
    for f in files:
        shutil.copy(f, os.path.join(ROOT, rel, os.path.basename(f)))
    git("add", rel)
    r = git("commit", "-q", "-m", message)
    if r.returncode != 0:
        raise GenError("GIT_COMMIT", r.stderr[-200:] or r.stdout[-200:])
    for attempt in range(4):
        if git("push", "-q", "origin", "HEAD:main").returncode == 0:
            return git("rev-parse", "HEAD").stdout.strip()
        git("pull", "-q", "--rebase", "origin", "main")
    raise GenError("GIT_PUSH", "could not push the report commit to main after 4 attempts", transient=True)


def request_pages_build():
    """Ask GitHub Pages to rebuild now (a push made with the workflow token may not trigger it). Harmless if redundant."""
    import urllib.request
    tok, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not tok or not repo:
        return
    try:
        urllib.request.urlopen(urllib.request.Request(f"https://api.github.com/repos/{repo}/pages/builds", method="POST",
                               headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                                        "User-Agent": "tar-generator"}), timeout=30)
    except Exception as e:
        log(f"::notice title=PAGES::Pages build request not accepted ({type(e).__name__}); the push itself normally deploys Pages")


def check_connections(g):
    from .source import DriveSource
    key = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
    if not key:
        raise GenError("DRIVE_SECRET_MISSING", "GOOGLE_SERVICE_ACCOUNT_JSON secret is not set")
    DriveSource(g["drive_root_folder_id"], key).ping()
    log("DRIVE OK: the service account can read the TAR Daily Sources folder")
    if not os.environ.get("GEMINI_API_KEY", "").strip():
        log("GEMINI: no GEMINI_API_KEY secret; MODE B (no AI) will be used. That is fine and costs nothing.")
    else:
        from .writer import GeminiWriter
        w = GeminiWriter(g.get("gemini_models", []), authorised=True)  # authorised here only for a synthetic, data-free prompt
        ok = w.ping()
        log(f"GEMINI OK: free-tier key works with model {w.model} (synthetic prompt only, no Vitti material sent)" if ok
            else "GEMINI: key accepted but no reply; MODE B will be used when needed")
        if g.get("gemini_data_use_authorised") is not True:
            log("GEMINI NOT USED FOR REPORTS: gemini_data_use_authorised is false, so Vitti material is never sent to it")
    log(f"WRITER MODE: {g.get('writer_mode', 'template')}")
    log("::notice title=CONNECTIONS OK::Drive readable; writer configuration checked; nothing generated or published")


def write_report(ident, pkg, g, out_dir, fixture=None, log=print, verbose=True):
    """MODE A (if allowed) then MODE B. Returns (result, writer_mode, model, fallback_reason)."""
    attempts = int(g.get("max_attempts", 3))
    if fixture is not None:
        from .writer import FixtureWriter
        w = FixtureWriter(fixture)
        return build(ident, w, out_dir, max_attempts=attempts, log=log, verbose=verbose), w.mode, "fixture", None
    fallback = None
    if g.get("writer_mode") == "gemini":
        try:
            from .writer import GeminiWriter
            w = GeminiWriter(g.get("gemini_models", []), g.get("gemini_data_use_authorised"))
            log(f"MODE A: Gemini free tier, model {w.model}")
            return build(ident, w, out_dir, max_attempts=attempts, log=log, verbose=verbose), w.mode, w.model, None
        except GenError as e:
            if e.code not in FALLBACK_CODES or g.get("fallback_to_template", True) is not True:
                raise
            fallback = e.code
            log(f"MODE A not used ({e.code}); falling back to MODE B (deterministic, no AI)")
    w = TemplateWriter(ident, pkg.daily_mover_path)
    log("MODE B: deterministic report from the Daily Mover (no AI, nothing sent outside the runner)")
    return build(ident, w, out_dir, max_attempts=attempts, log=log, verbose=verbose), w.mode, "template", fallback


def watchdog(cfg, g, d, now, notify_on):
    """Missed-publication detector. Reads only the repository (reports/<date>-*/status.json written by the publisher).
    Exit 1 + one alert issue per day when a trading day did not end with a post; exit 0 otherwise."""
    if not is_trading_day(d):
        outcome("SKIP", "NOT_TRADING_DAY")
        return 0
    if not (cfg.get("enabled") is True and g.get("enabled") is True and g.get("publish") is True):
        outcome("SKIP", "PUBLISHING_OFF")
        return 0
    if now.time() < hhmm(g.get("watchdog_after", "15:20")):
        outcome("SKIP", "TOO_EARLY", f"watchdog acts after {g.get('watchdog_after', '15:20')} Sydney")
        return 0
    folders = existing_report(d)
    st = {}
    for f in folders:
        p = os.path.join(f, "status.json")
        if os.path.isfile(p):
            try:
                st = json.load(open(p, encoding="utf-8"))
            except ValueError:
                st = {}
    state = st.get("state")
    if state == "LINKEDIN_CONFIRMED":
        outcome("SKIP", "PUBLISHED_OK", st.get("linkedin_url") or "")
        return 0
    if not folders:
        code = "MISSED_START_WINDOW"
    elif st.get("blocked_reason"):
        code = "PUBLISH_BLOCKED_CREDENTIALS"
    elif state == "FAILED":
        code = "PUBLISH_FAILED"
    elif state in ("BUFFER_SCHEDULED", "BUFFER_SENT"):
        if now.time() < hhmm(g.get("confirm_alert_after", "17:00")):  # Buffer normally confirms within minutes
            outcome("SKIP", "AWAITING_CONFIRMATION", state)
            return 0
        code = "LINKEDIN_NOT_CONFIRMED"
    else:
        code = "NOT_HANDED_TO_BUFFER"
    if notify_on and notify.failure_open(d):  # one alert per day: the open issue already tells the owner
        outcome("SKIP", "ALREADY_ALERTED", code)
        return 0
    log(f"::error title=NO LINKEDIN POST::{code}: {REASONS.get(code, '')}")
    if notify_on:
        notify.notify_failure(d, code, REASONS.get(code, "see the reason code"), run_url())
    outcome("FAIL", code)
    return 1


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date"); ap.add_argument("--local"); ap.add_argument("--out")
    ap.add_argument("--fixture-writer"); ap.add_argument("--mode", choices=["auto", "shadow"], default="auto")
    ap.add_argument("--check-connections", action="store_true"); ap.add_argument("--ignore-schedule", action="store_true")
    ap.add_argument("--no-notify", action="store_true"); ap.add_argument("--config", default=CONFIG_PATH)
    ap.add_argument("--watchdog", action="store_true",
                    help="after the cutoff: alert (once per day) if the trading day has no confirmed LinkedIn post")
    ap.add_argument("--latest", type=int, metavar="DAYS",
                    help="private test: use the newest package from the last DAYS days (never publishes)")
    a = ap.parse_args(argv)
    cfg, g = load_config(a.config)
    if a.check_connections:
        check_connections(g)
        return 0
    if a.latest:
        src0 = make_source(g, a.local)
        for k in range(a.latest):
            dd = today_syd() - timedelta(days=k)
            if src0.packages_for(dd):
                a.date, a.mode, a.ignore_schedule = dd.isoformat(), "shadow", True
                log(f"LATEST PACKAGE: {dd} (private shadow test; never published)")
                break
        else:
            log(f"NO PACKAGE in the last {a.latest} days")
            return 1
    notify_on = not a.no_notify and os.environ.get("GITHUB_ACTIONS") == "true"
    d = parse_iso_date(a.date) if a.date else today_syd()
    now = datetime.now(SYD)
    live_day = not a.date and not a.local
    out_root = a.out or os.path.join(ROOT, "generator-output")

    if a.watchdog:
        return watchdog(cfg, g, d, now, notify_on)
    if not g.get("enabled") and live_day and not a.ignore_schedule:
        log("GENERATOR OFF: config vitti_generator.enabled is false; nothing to do.")
        outcome("SKIP", "GENERATOR_OFF")
        return 0
    if not is_trading_day(d) and not a.ignore_schedule:
        log(f"NOT A TRADING DAY: {d}; nothing to do.")
        outcome("SKIP", "NOT_TRADING_DAY")
        return 0
    if live_day and existing_report(d):  # idempotent: a retried or duplicate trigger never builds a second report
        log(f"ALREADY HAVE A REPORT FOR {d}: {', '.join(os.path.basename(x) for x in existing_report(d))}. One report per trading day.")
        outcome("SKIP", "REPORT_EXISTS")
        return 0
    if notify_on and live_day and notify.failure_open(d):
        log(f"PAUSED: the day's failure was already alerted (issue open); close it to allow a retry.")
        outcome("SKIP", "ALREADY_ALERTED")
        return 0
    missed = live_day and not a.ignore_schedule and now.time() > hhmm(g.get("latest_start", "14:40"))

    give_up = live_day and now.time() >= hhmm(g.get("give_up_after", "14:30"))
    try:
        if missed:
            # A trading day, no report, and the start deadline has passed: this is a MISSED day, never a green skip.
            raise GenError("MISSED_START_WINDOW", f"{now:%H:%M} is after the {g.get('latest_start')} Sydney start deadline "
                           "(publisher cutoff 3:15 PM) and no report exists")
        src = make_source(g, a.local)
        pkgs = src.packages_for(d)
        if not pkgs:
            if live_day and now.time() >= hhmm(g.get("no_package_alert_after", "13:00")):
                raise GenError("NO_PACKAGE", f"no Vitti Daily Mover package in Drive for {d}")
            log(f"NO PACKAGE YET for {d}; the next run checks again.")
            outcome("RETRY", "NO_PACKAGE_YET")
            return 0
        ident, errors, pkg = None, [], None
        for p in pkgs:  # newest first; the first package that passes every identity check is used
            try:
                ident, pkg = verify_package(p, d, g), p
                break
            except GenError as e:
                errors.append(f"{p.package_id}: {e.code}")
                log(f"  a package was rejected: {safe(e)}")
        if not ident:
            raise GenError("NO_VALID_PACKAGE", "every package for the day failed verification: " + "; ".join(errors))
        log(f"PACKAGE {d}: sender, DKIM, hash and identity verified; {len(ident.support)} supporting announcement(s)"
            + ("" if PUBLIC else f" [{ident.company} ({ident.ticker}), {pkg.package_id}]"))
        dup = used_before(ident)
        if dup and a.latest:
            # private test only (--latest forces shadow mode and can never publish): note it and keep building
            log("DUPLICATE DETECTED: this Vitti email was already used by a published report; a live run would stop here. "
                "Private test continues; nothing will be published.")
        elif dup:
            raise GenError("DUPLICATE", f"this Vitti email / Daily Mover was already used by {os.path.relpath(dup, ROOT)}")

        rel = folder_rel(ident.ticker, d)
        out_dir = os.path.join(out_root, rel)
        fixture = json.load(open(a.fixture_writer, encoding="utf-8")) if a.fixture_writer else None
        res, wmode, model, fallback = write_report(ident, pkg, g, out_dir, fixture, log=log, verbose=not PUBLIC)
        flags = dict(ident.checks, final_pdf_valid=True, visual_check_done=True, no_duplicate=True,
                     master_switch_enabled=cfg.get("enabled") is True)
        P = make_handoff(ident, res, pkg, flags, model, os.environ.get("GITHUB_RUN_ID"), writer_mode=wmode, fallback=fallback)
        out = contract_check(P, res["pdf"], res["png"])
        log("CONTRACT CHECK: the existing publisher (buffer_schedule.py, verify mode) accepts this handoff: "
            + next((l for l in out.splitlines() if l.startswith("FILING CONTRACT OK")), "VERIFY PASS"))
        json.dump(P, open(os.path.join(out_dir, "publish.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8").write(P["caption"])
        json.dump({"writer_mode": wmode, "model": model, "fallback": fallback, "layout": res["layout"], "attempts": res["attempts"]},
                  open(os.path.join(out_dir, "run.json"), "w"), indent=1)

        ok, why = publish_allowed(cfg, g)
        if a.mode == "shadow" or not ok or not live_day:
            reason = "forced shadow mode" if a.mode == "shadow" else ("; ".join(why) or "historical/local run")
            log(f"SHADOW MODE ({reason}): report built and fully verified with {wmode}; nothing committed or published."
                + ("" if PUBLIC else f" Output: {out_dir}"))
            summary(f"### SHADOW REPORT READY\n- date {d}\n- writer {wmode}" + (f" (fallback from {fallback})" if fallback else "")
                    + f"\n- PDF sha256 `{P['pdf_sha256']}`\n- attempts {res['attempts']}\n- not published: {reason}")
            if notify_on:
                notify.notify_log(f"{d.isoformat()}: shadow report built and verified with {wmode} (not published: {reason}). "
                                  f"No copy is kept on GitHub. {run_url()}")
            outcome("SHADOW_OK", "NOT_PUBLISHED", reason)
            return 0
        sha = commit_and_push([res["pdf"], res["png"], os.path.join(out_dir, "publish.json")], rel,
                              f"TAR {ident.ticker} {d.day} {d.strftime('%b %Y')}: automated report from the Vitti Daily Mover (schema 4 handoff)")
        request_pages_build()
        log(f"HANDED OFF: commit {sha} on main; the TAR Buffer Schedule workflow verifies and publishes it.")
        summary(f"### HANDED OFF TO PUBLISHER\n- {ident.ticker} {d}\n- commit `{sha}`\n- PDF sha256 `{P['pdf_sha256']}`")
        if notify_on:
            notify.notify_log(f"{d.isoformat()} {ident.ticker}: report generated and handed to the publisher (commit {sha}). {run_url()}")
        outcome("PUBLISHED_HANDOFF", "HANDED_TO_PUBLISHER", f"commit {sha[:7]}")
        return 0
    except GenError as e:
        final = (not e.transient) or give_up or not live_day
        log(f"NO REPORT: {safe(e)}")
        if not final:
            log(f"::warning title=RETRY LATER::{safe(e)} (the next run retries)")
            outcome("RETRY", e.code)
            return 0
        log(f"::error title=NO REPORT::{safe(e)}")
        summary(f"### NO REPORT\n- date {d}\n- {safe(e)}")
        if notify_on and live_day:
            notify.notify_failure(d, e.code, REASONS.get(e.code, "see the reason code"), run_url())
        outcome("FAIL", e.code)
        return 1


def safe_main(argv=None):
    """In public GitHub runs an unexpected error is reported by type only: a traceback can quote report content."""
    try:
        return main(argv)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001
        if not PUBLIC:
            raise
        log(f"::error title=NO REPORT::UNEXPECTED_ERROR: {type(e).__name__} (details withheld from the public log)")
        summary(f"### NO REPORT\n- UNEXPECTED_ERROR: {type(e).__name__}")
        if os.environ.get("GITHUB_ACTIONS") == "true":
            try:
                notify.notify_failure(today_syd(), "UNEXPECTED_ERROR", type(e).__name__, run_url())
            except Exception:  # noqa: BLE001
                pass
        return 1


if __name__ == "__main__":
    sys.exit(safe_main())
