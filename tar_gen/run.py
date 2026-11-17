#!/usr/bin/env python3
"""TAR Vitti generator: Drive package -> AI report -> two-page PDF + cover + caption -> schema 4 handoff.

    python3 -m tar_gen.run                      # what GitHub Actions runs (today, Sydney)
    python3 -m tar_gen.run --check-connections  # read-only: Drive folder visible, Anthropic key valid; no tokens spent
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
from datetime import datetime, time as dtime

from .common import CONFIG_PATH, GenError, ROOT, SYD, folder_rel, is_trading_day, load_config, parse_iso_date, today_syd
from . import notify
from .handoff import contract_check, make_handoff
from .pipeline import build
from .source import make_source
from .vitti import verify_package


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
    name = DriveSource(g["drive_root_folder_id"], key).ping()
    log(f"DRIVE OK: service account can read folder '{name}'")
    import anthropic
    if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
        raise GenError("ANTHROPIC_SECRET_MISSING", "ANTHROPIC_API_KEY secret is not set")
    m = anthropic.Anthropic().models.retrieve(g["model"])
    log(f"ANTHROPIC OK: key accepted, model {m.id} available (no tokens spent)")
    log("::notice title=CONNECTIONS OK::Drive folder readable and Anthropic key valid; nothing generated or published")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--date"); ap.add_argument("--local"); ap.add_argument("--out")
    ap.add_argument("--fixture-writer"); ap.add_argument("--mode", choices=["auto", "shadow"], default="auto")
    ap.add_argument("--check-connections", action="store_true"); ap.add_argument("--ignore-schedule", action="store_true")
    ap.add_argument("--no-notify", action="store_true"); ap.add_argument("--config", default=CONFIG_PATH)
    a = ap.parse_args(argv)
    cfg, g = load_config(a.config)
    if a.check_connections:
        check_connections(g)
        return 0
    notify_on = not a.no_notify and os.environ.get("GITHUB_ACTIONS") == "true"
    d = parse_iso_date(a.date) if a.date else today_syd()
    now = datetime.now(SYD)
    live_day = not a.date and not a.local
    out_root = a.out or os.path.join(ROOT, "generator-output")

    if not g.get("enabled") and live_day and not a.ignore_schedule:
        log("GENERATOR OFF: config vitti_generator.enabled is false; nothing to do.")
        return 0
    if not is_trading_day(d) and not a.ignore_schedule:
        log(f"NOT A TRADING DAY: {d}; nothing to do.")
        return 0
    if live_day and not a.ignore_schedule and now.time() > hhmm(g.get("latest_start", "14:40")):
        log(f"PAST START WINDOW: {now:%H:%M} is after {g.get('latest_start')} Sydney; the publisher cutoff is 3:15 PM.")
        return 0
    if live_day and existing_report(d):
        log(f"ALREADY HAVE A REPORT FOR {d}: {', '.join(os.path.basename(x) for x in existing_report(d))}. One report per trading day.")
        return 0
    if notify_on and live_day and notify.failure_open(d):
        log(f"PAUSED: a failure issue for {d} is open; close it to allow a retry.")
        return 0

    give_up = live_day and now.time() >= hhmm(g.get("give_up_after", "14:30"))
    try:
        src = make_source(g, a.local)
        pkgs = src.packages_for(d)
        if not pkgs:
            if live_day and now.time() >= hhmm(g.get("no_package_alert_after", "13:00")):
                raise GenError("NO_PACKAGE", f"no Vitti Daily Mover package in Drive for {d}")
            log(f"NO PACKAGE YET for {d}; the next scheduled run checks again.")
            return 0
        ident, errors, pkg = None, [], None
        for p in pkgs:  # newest first; the first package that passes every identity check is used
            try:
                ident, pkg = verify_package(p, d, g), p
                break
            except GenError as e:
                errors.append(f"{p.package_id}: {e.code}")
                log(f"  package {p.package_id} rejected: {e}")
        if not ident:
            raise GenError("NO_VALID_PACKAGE", "every package for the day failed verification: " + "; ".join(errors))
        log(f"PACKAGE {pkg.package_id}: {ident.company} ({ident.ticker}) {d}; sender, DKIM, hash and identity verified; "
            f"{len(ident.support)} supporting announcement(s)")
        dup = used_before(ident)
        if dup:
            raise GenError("DUPLICATE", f"this Vitti email / Daily Mover was already used by {os.path.relpath(dup, ROOT)}")

        if a.fixture_writer:
            from .writer import FixtureWriter
            writer, model = FixtureWriter(json.load(open(a.fixture_writer, encoding="utf-8"))), "fixture"
        else:
            from .writer import ClaudeWriter
            writer, model = ClaudeWriter(g["model"], g.get("effort", "high")), g["model"]
        rel = folder_rel(ident.ticker, d)
        out_dir = os.path.join(out_root, rel)
        res = build(ident, writer, out_dir, max_attempts=int(g.get("max_attempts", 3)), log=log)
        flags = dict(ident.checks, final_pdf_valid=True, visual_check_done=True, no_duplicate=True,
                     master_switch_enabled=cfg.get("enabled") is True)
        P = make_handoff(ident, res, pkg, flags, model, os.environ.get("GITHUB_RUN_ID"))
        out = contract_check(P, res["pdf"], res["png"])
        log("CONTRACT CHECK: the existing publisher (buffer_schedule.py, verify mode) accepts this handoff: "
            + next((l for l in out.splitlines() if l.startswith("FILING CONTRACT OK")), "VERIFY PASS"))
        json.dump(P, open(os.path.join(out_dir, "publish.json"), "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        open(os.path.join(out_dir, "caption.txt"), "w", encoding="utf-8").write(P["caption"])
        json.dump({"usage": writer.usage, "layout": res["layout"], "attempts": res["attempts"]},
                  open(os.path.join(out_dir, "run.json"), "w"), indent=1)

        ok, why = publish_allowed(cfg, g)
        if a.mode == "shadow" or not ok or not live_day:
            reason = "forced shadow mode" if a.mode == "shadow" else ("; ".join(why) or "historical/local run")
            log(f"SHADOW MODE ({reason}): report built and fully verified in {out_dir}; nothing committed or published.")
            summary(f"### SHADOW REPORT READY\n- {ident.ticker} {d}\n- PDF sha256 `{P['pdf_sha256']}`\n- attempts {res['attempts']}\n- not published: {reason}")
            if notify_on:
                notify.notify_log(f"{d.isoformat()} {ident.ticker}: shadow report built and verified (not published: {reason}). "
                                  f"Encrypted review copy in the run artifacts if TAR_REVIEW_PASSWORD is set. {run_url()}")
            return 0
        sha = commit_and_push([res["pdf"], res["png"], os.path.join(out_dir, "publish.json")], rel,
                              f"TAR {ident.ticker} {d.day} {d.strftime('%b %Y')}: automated report from the Vitti Daily Mover (schema 4 handoff)")
        request_pages_build()
        log(f"HANDED OFF: commit {sha} on main; the TAR Buffer Schedule workflow verifies and publishes it.")
        summary(f"### HANDED OFF TO PUBLISHER\n- {ident.ticker} {d}\n- commit `{sha}`\n- PDF sha256 `{P['pdf_sha256']}`")
        if notify_on:
            notify.notify_log(f"{d.isoformat()} {ident.ticker}: report generated and handed to the publisher (commit {sha}). {run_url()}")
        return 0
    except GenError as e:
        final = (not e.transient) or give_up or not live_day
        log(f"NO REPORT: {e}")
        if not final:
            log(f"::warning title=RETRY LATER::{e.code}: {e.msg} (the next scheduled run retries)")
            return 0
        log(f"::error title=NO REPORT::{e.code}: {e.msg}")
        summary(f"### NO REPORT\n- date {d}\n- `{e.code}`: {e.msg}")
        if notify_on and live_day:
            notify.notify_failure(d, e.code, e.msg, run_url())
        return 1


if __name__ == "__main__":
    sys.exit(main())
