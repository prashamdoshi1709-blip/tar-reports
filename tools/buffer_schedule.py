#!/usr/bin/env python3
"""TAR Buffer scheduler (runs in GitHub Actions, stdlib only).

REV 7 (26 Oct 2026 incident: GitHub's cron started the 2:17 and 2:24 PM runs at 2:44 and 2:59 PM, so the 2:30 PM cutoff
refused a valid TUA handoff and the run still ended green). Fixes: (1) a push of reports/*/publish.json now starts this
script immediately; (2) frequent crons (every 5 min, 1:00-2:55 PM) retry until the cutoff, now 2:45 PM; (3) after
scheduling, crons every 10 min until 6 PM reconcile Buffer; (4) every report keeps reports/<date>-<TICKER>/status.json
with the states HANDOFF_COMMITTED -> BUFFER_SCHEDULED -> BUFFER_SENT -> LINKEDIN_CONFIRMED, or FAILED; (5) a final
failure makes the run RED (GitHub emails the owner) instead of a silent green warning.

Schedules ONE verified, current-day TAR report in Buffer for 3:00 PM Sydney through Buffer's official
GraphQL API (https://api.buffer.com). It never researches, edits or rebuilds anything: it only
re-verifies the committed payload and, if every check passes, makes exactly one createPost call.

MODE (env): scheduled (GitHub schedule event only: 2:17 PM and 2:24 PM Sydney) | dryrun (all checks on a named
            payload incl. Buffer reads, no createPost, time guards skipped) | verify (read-only: every file and
            public-URL check on a named payload, no Buffer call at all, time guards skipped) | selftest (secret +
            Buffer read-only connection test)
A report is scheduled ONLY from a complete verified handoff reports/<date>-<TICKER>/publish.json (schema 2) written
by the 1:58 PM routine after all research, ASX and clean-PDF checks passed. A PDF alone never publishes anything.
The routine never fetches the public URL. THIS script proves, before anything reaches Buffer, that GitHub Pages
serves exactly the verified PDF and cover (tools/public_verify.py: HTTP 200, real PDF, SHA-256, page count,
dimensions, PDF title, no DRAFT / NOT APPROVED wording, cover hash).
Idempotent: Buffer is read before every attempt; an identical existing post is success, never a second post; an
uncertain createPost is never retried in the same run (Buffer is re-read first). Fail closed: any problem in
dryrun/selftest -> exit 1; in scheduled mode -> exit 0 with a warning annotation (silent, nothing scheduled). The API key is read from the
BUFFER_API_KEY environment variable only and is never printed.
"""
import glob, hashlib, json, os, re, subprocess, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from public_verify import verify_public, PublicVerifyError  # noqa: E402

ORG_ID = "6acf0e2ceeddaaa8667d1b55"
CHANNEL_ID = "6acf0e50778b240e2f03735c"
CHANNEL_NAME = "The Announcement Room"
API = "https://api.buffer.com"
PAGES = "https://prashamdoshi1709-blip.github.io/tar-reports/reports"
SYD = ZoneInfo("Australia/Sydney")
DISCLAIMER = "General information only. Not financial advice."
CLOSURES = {"2026-12-25", "2026-12-28", "2027-01-01", "2027-01-26", "2027-03-26", "2027-03-29",
            "2027-06-14", "2027-12-27", "2027-12-28"}
EARLY_CLOSE = {"2026-12-24", "2026-12-31", "2027-12-24", "2027-12-31"}
BAD = re.compile(r"not\s*approved|approved\s*for\s*publication|draft", re.I)
MODE = os.environ.get("MODE", "scheduled").strip() or "scheduled"


CTX = {"folder": None}
STATES = ("HANDOFF_COMMITTED", "BUFFER_SCHEDULED", "BUFFER_SENT", "LINKEDIN_CONFIRMED", "FAILED")


def load_status(folder):
    p = f"{folder}/status.json"
    return json.load(open(p, encoding="utf-8")) if os.path.isfile(p) else {"state": None, "final": False, "history": []}


def set_status(folder, state, final=None, **kw):
    """Single source of truth for where a report is. Written to the repo (committed by the workflow) and the run summary."""
    assert state in STATES
    s = load_status(folder)
    at = now_syd().isoformat()
    s.update(kw)
    changed = s.get("state") != state or any(k in kw for k in ("reason", "linkedin_url"))
    s["state"], s["updated_at"] = state, at
    s["final"] = bool(final) if final is not None else s.get("final", False)
    if changed:
        s["history"].append({"state": state, "at": at, **{k: v for k, v in kw.items() if k in ("reason", "buffer_post_id", "linkedin_url")}})
    json.dump(s, open(f"{folder}/status.json", "w", encoding="utf-8"), indent=2, ensure_ascii=False)
    line = f"STATUS {state}" + (f" (final)" if s["final"] else "") + (f": {kw['reason']}" if kw.get("reason") else "")
    print(line)
    summ = os.environ.get("GITHUB_STEP_SUMMARY")
    if summ:
        open(summ, "a").write(f"### {line}\n- report `{folder}`\n- at {at}\n" + (f"- Buffer post `{s.get('buffer_post_id')}`\n" if s.get("buffer_post_id") else "")
                              + (f"- LinkedIn {s.get('linkedin_url')}\n" if s.get("linkedin_url") else ""))
    return s


def die(msg, transient=False):
    """transient=True: may heal on the next cron (Pages not deployed yet, Buffer/API hiccup) and is retried until the
    cutoff. Anything else, or any failure at/after the cutoff, is FINAL: recorded as FAILED and the run goes RED."""
    print(f"NOT SCHEDULED: {msg}")
    if MODE in ("scheduled",):
        f = CTX.get("folder")
        final = (not transient) or CTX.get("past_cutoff", False)
        if f:
            if final:
                set_status(f, "FAILED", final=True, reason=msg)
            else:
                print(f"RETRY: transient problem, the next cron run tries again until the cutoff ({msg})")
        print(f"::{'error' if final and f else 'warning'} title=NOT SCHEDULED::{msg}")
        sys.exit(1 if (final and f) else 0)
    print(f"::error title=NOT SCHEDULED::{msg}")  # annotation: readable through the check-runs API
    sys.exit(1)


def now_syd():
    return datetime.now(SYD)


def gql(query, variables=None, soft=False):
    key = os.environ.get("BUFFER_API_KEY", "").strip()
    if not key:
        die("BUFFER_API_KEY secret is not set (single manual step: add it under repo Settings > Secrets > Actions)")
    req = urllib.request.Request(API, data=json.dumps({"query": query, "variables": variables or {}}).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "User-Agent": "tar-buffer-schedule/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            out = json.loads(r.read())
    except urllib.error.HTTPError as e:
        if soft:
            raise RuntimeError(f"HTTP {e.code}")
        die(f"Buffer API HTTP {e.code} (401 means the API key is invalid or revoked)", transient=e.code >= 500 or e.code == 429)
    except Exception as e:
        if soft:
            raise RuntimeError(type(e).__name__)
        die(f"Buffer API request failed: {type(e).__name__}", transient=True)
    if out.get("errors"):
        if soft:
            raise RuntimeError("API error")
        die("Buffer API error: " + "; ".join(str(x.get("message")) for x in out["errors"])[:400])
    return out["data"]


def buffer_connection_checks():
    """Read-only: account, organisation, LinkedIn channel."""
    d = gql("query{account{id organizations{id name}}}")
    if ORG_ID not in [o["id"] for o in d["account"]["organizations"]]:
        die("expected Buffer organisation not visible to this API key")
    d = gql("query($i:ChannelsInput!){channels(input:$i){id displayName service isDisconnected isLocked}}",
            {"i": {"organizationId": ORG_ID}})
    ch = [c for c in d["channels"] if c["id"] == CHANNEL_ID]
    if len(ch) != 1:
        die("LinkedIn channel id not found in organisation")
    c = ch[0]
    if c["service"] != "linkedin" or c["displayName"] != CHANNEL_NAME or c["isDisconnected"] or c["isLocked"]:
        die(f"channel check failed: {c['service']} / {c['displayName']} / disconnected={c['isDisconnected']} / locked={c['isLocked']}")
    return c


def all_posts():
    posts, after = [], None
    while True:
        d = gql("query($i:PostsInput!,$a:String){posts(first:100,after:$a,input:$i){edges{node{id status text dueAt}}"
                " pageInfo{hasNextPage endCursor}}}", {"i": {"organizationId": ORG_ID}, "a": after})
        p = d["posts"]
        posts += [e["node"] for e in (p["edges"] or [])]
        if not p["pageInfo"]["hasNextPage"]:
            return posts
        after = p["pageInfo"]["endCursor"]


def find_conflicts(date_line, slot):
    """Every real Buffer post (not DRY RUN/TEST ONLY drafts) that mentions this report or sits in the 3 PM slot."""
    out = []
    for p in all_posts():
        t = p["text"] or ""
        if t.startswith("DRY RUN DRAFT") or t.startswith("TEST ONLY"):
            continue
        due = datetime.fromisoformat(p["dueAt"].replace("Z", "+00:00")) if p["dueAt"] else None
        in_slot = p["status"] in ("scheduled", "sending", "needs_approval") and due == slot
        if date_line in t or in_slot:
            out.append(p)
    return out


def is_identical(p, cap, slot):
    """The existing post is exactly the one we would create (same text, 3 PM slot, still live or already sent)."""
    due = datetime.fromisoformat(p["dueAt"].replace("Z", "+00:00")) if p["dueAt"] else None
    return (p["text"] == cap and due == slot and p["status"] in ("scheduled", "sending", "sent"))


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def reconcile(folder, st, slot):
    """Advance BUFFER_SCHEDULED -> BUFFER_SENT -> LINKEDIN_CONFIRMED from what Buffer itself reports. Read-only on Buffer."""
    pid = st["buffer_post_id"]
    p = gql("query($i:PostInput!){post(input:$i){id status dueAt sentAt externalLink error{message}}}", {"i": {"id": pid}})["post"]
    if p["status"] == "sent":
        link = p.get("externalLink") or ""
        if "linkedin.com" in link:
            set_status(folder, "LINKEDIN_CONFIRMED", final=True, buffer_post_id=pid, sent_at=p.get("sentAt"), linkedin_url=link)
        else:
            set_status(folder, "BUFFER_SENT", buffer_post_id=pid, sent_at=p.get("sentAt"))
            print("Buffer says sent but no LinkedIn URL yet; the next reconcile run checks again.")
            if now_syd() > slot + timedelta(hours=2):
                set_status(folder, "FAILED", final=True, buffer_post_id=pid, reason="Buffer says sent but returned no LinkedIn URL after 2 hours")
                sys.exit(1)
    elif p["status"] in ("error",):
        set_status(folder, "FAILED", final=True, buffer_post_id=pid, reason=f"Buffer post error: {(p.get('error') or {}).get('message')}")
        print("::error title=BUFFER POST FAILED::see status.json")
        sys.exit(1)
    elif now_syd() > slot + timedelta(minutes=30):
        set_status(folder, "FAILED", final=True, buffer_post_id=pid, reason=f"Buffer post still '{p['status']}' 30 min after the slot")
        print("::error title=BUFFER POST STALLED::see status.json")
        sys.exit(1)
    else:
        print(f"Buffer post {pid} is '{p['status']}', due {p['dueAt']}. Waiting.")


def main():
    if MODE == "selftest":
        c = buffer_connection_checks()
        n = len(all_posts())
        msg = (f"SELFTEST PASS: API key accepted; organisation and channel '{c['displayName']}' ({c['service']}) verified; "
               f"{n} existing posts readable; nothing created.")
        print(msg)
        print(f"::notice title=SELFTEST PASS::{msg}")
        return
    if MODE not in ("scheduled", "dryrun", "verify"):
        die(f"unknown MODE {MODE!r}")
    if MODE == "scheduled" and os.environ.get("GITHUB_EVENT_NAME") not in ("schedule", "push"):
        die("scheduling a post is only allowed from the GitHub schedule or push event")
    if MODE == "scheduled" and os.environ.get("GITHUB_REF") != "refs/heads/main":
        die("scheduling a post is only allowed from main")

    # ---- payload selection: today's verified handoff only
    path = os.environ.get("PAYLOAD", "").strip()
    if not path:
        td = now_syd().date().isoformat()
        found = sorted(glob.glob(f"reports/{td}-*/publish.json"))
        if not found:
            print(f"::notice title=NO HANDOFF::No verified publish.json for {td}; nothing to do.")
            print(f"NO HANDOFF for {td}: nothing to do (a PDF without a verified handoff is never published).")
            return
        if len(found) != 1:
            die(f"expected exactly one handoff for {td}, found {len(found)}")
        path = found[0]
    if not re.fullmatch(r"reports/\d{4}-\d{2}-\d{2}-[A-Z0-9]{2,5}/publish\.json", path) or not os.path.isfile(path):
        die(f"bad payload path {path!r}")
    P = json.load(open(path, encoding="utf-8"))
    folder = os.path.dirname(path)
    if os.path.exists(f"{folder}/SHELVED.md"):
        die("report folder is marked SHELVED; it is never scheduled")
    tk, iso, company = P["ticker"], P["report_date_iso"], P["company_name"]
    d = datetime.strptime(P["report_date"], "%d %B %Y").date()
    if P.get("schema") != 2 or P.get("mode") != "LIVE" or d.isoformat() != iso or folder != f"reports/{iso}-{tk}":
        die("payload schema/mode/date/folder mismatch (schema 2 required)")
    if not re.fullmatch(r"[A-Z0-9]{2,5}", tk):
        die("bad ticker")

    # ---- current-day production guard, trading-day rules, master switch
    today = now_syd().date()
    slot = datetime(d.year, d.month, d.day, 15, 0, tzinfo=SYD)
    if MODE == "scheduled":
        if d != today:
            die(f"report date {d} is not today in Sydney ({today})")
        if d.weekday() >= 5 or iso in CLOSURES or iso in EARLY_CLOSE:
            die("not a full ASX trading day")
        if not json.load(open("config/auto-publish.json")).get("enabled") is True:
            die("AUTO-PUBLISH OFF (config/auto-publish.json enabled is not true)")
    cutoff = datetime(d.year, d.month, d.day, 14, 45, tzinfo=SYD)  # Buffer needs only seconds; slot 3:00 PM keeps 15 min margin

    def time_ok():
        n = now_syd()
        return MODE in ("dryrun", "verify") or (n < cutoff and slot - n >= timedelta(minutes=10))
    if MODE == "scheduled":
        CTX["folder"], CTX["past_cutoff"] = folder, not time_ok()
        st = load_status(folder)
        if st.get("final"):
            print(f"STATUS already final: {st.get('state')} ({st.get('reason') or st.get('linkedin_url') or ''}). Nothing to do.")
            return
        if st.get("state") is None:
            set_status(folder, "HANDOFF_COMMITTED", handoff_created_at=P.get("handoff_created_at"),
                       handoff_commit=os.environ.get("GITHUB_SHA"), pdf_sha256=P.get("pdf_sha256"))
        if st.get("state") in ("BUFFER_SCHEDULED", "BUFFER_SENT") and st.get("buffer_post_id"):
            reconcile(folder, st, slot)
            return
    if not time_ok():
        die(f"past the 2:45 PM Sydney cutoff or slot too close (now {now_syd().isoformat()})")

    # ---- payload hygiene (mirrors the routine's Step 2e)
    for k in ("claude_verification", "package_id", "review_record_id", "review_status", "pdf_sha256", "pdf_url",
              "cover_url", "title", "caption", "marker_sha256", "handoff_created_at"):
        if k not in P:
            die(f"payload missing {k}")
    cv = P["claude_verification"]
    need = ["marker_hashes_match", "review_research_ready", "source_checks_passed", "verify_clean_pdf_pass",
            "visual_check_done", "newer_asx_filings_none_material", "buffer_duplicate_check_clear",
            "master_switch_enabled"]
    if P["review_status"] != "RESEARCH-READY":
        die("handoff review_status is not RESEARCH-READY")
    if not all(cv.get(k) is True for k in need):
        die("claude_verification flags are not all true: " + ",".join(k for k in need if cv.get(k) is not True))
    title, cap = P["title"], P["caption"]
    if len(title) >= 55 or "\n" in title or "—" in title or BAD.search(title):
        die("title invalid (length, newline, em dash or forbidden wording)")
    date_line = f"ASX: {tk} | {P['report_date']}"
    if (not cap.startswith(f"The Announcement Room | {company} ({tk})") or date_line not in cap or "—" in cap
            or BAD.search(cap) or f"{DISCLAIMER}\n\n#ASX" not in cap or f"#{tk}" not in cap):
        die("caption failed consistency checks")
    if not cap.rstrip().endswith(tuple(re.findall(r"#\w+", cap)[-1:])):
        die("caption must end with hashtags")

    # ---- files: committed PDF + cover, verified again here
    fname = f"TAR_{tk}_{d.day}{d.strftime('%b')}{d.year}"
    pdf, png = f"{folder}/{fname}.pdf", f"{folder}/{fname}_cover.png"
    if not (os.path.isfile(pdf) and os.path.isfile(png)):
        die("committed PDF or cover missing")
    if sha256(pdf) != P["pdf_sha256"]:
        die("committed PDF sha256 does not match payload")
    clean_title = f"{company} (ASX: {tk}) - {title}"
    r = subprocess.run([sys.executable, "tools/verify_clean_pdf.py", pdf, clean_title], capture_output=True, text=True)
    print(r.stdout.strip())
    if r.returncode != 0 or "PASS" not in r.stdout:
        die("verify_clean_pdf.py did not PASS")

    # ---- public URLs live and identical (Pages)
    pdf_url, png_url = f"{PAGES}/{iso}-{tk}/{fname}.pdf", f"{PAGES}/{iso}-{tk}/{fname}_cover.png"
    if P["pdf_url"] != pdf_url or P["cover_url"] != png_url:
        die("handoff PDF/cover URLs do not match the expected committed locations")
    # GitHub Actions (not the Claude routine) proves what Pages serves: HTTP 200, real PDF, SHA-256 equal to the
    # handoff, page count, dimensions, PDF title, no DRAFT / NOT APPROVED wording, cover hash equal to the commit.
    if MODE == "scheduled":
        deadline = min(START + 360, cutoff.timestamp() - 60)  # never wait past the cutoff
    else:
        deadline = START + 45
    print(f"Verifying what GitHub Pages serves: {pdf_url}")
    try:
        msg = verify_public(pdf_url, png_url, P["pdf_sha256"], clean_title, sha256(png), deadline)
    except PublicVerifyError as e:
        die(f"public PDF verification failed: {e}", transient=True)
    print(f"PUBLIC URL VERIFIED: {msg}")
    if MODE == "scheduled" and not time_ok():
        die("2:45 PM cutoff reached during public verification")
    if MODE == "verify":
        print("VERIFY PASS: handoff payload, committed files and the public GitHub Pages files are all verified; "
              "no Buffer call was made, nothing created.")
        print("::notice title=VERIFY PASS::payload, committed files and public Pages files verified; read-only, no Buffer call")
        return

    # ---- Buffer: connection, channel, idempotency (Buffer is read BEFORE every attempt)
    buffer_connection_checks()
    conflicts = find_conflicts(date_line, slot)
    same = [p for p in conflicts if is_identical(p, cap, slot)]
    if MODE == "dryrun":
        if conflicts:
            print(f"DRYRUN PASS: every check passed; createPost NOT called. Duplicate protection WOULD BLOCK: "
                  f"{len(conflicts)} existing Buffer post(s) {[p['id'] for p in conflicts]} for this report/slot.")
            print(f"::notice title=DRYRUN PASS::all checks passed, createPost not called, duplicate protection would block ({len(conflicts)} existing)")
        else:
            print("DRYRUN PASS: every check passed; createPost NOT called; no existing Buffer post, so a live run would schedule.")
            print("::notice title=DRYRUN PASS::all checks passed, createPost not called, no duplicate present")
        return
    if same and len(conflicts) == len(same):
        print(f"ALREADY SCHEDULED (idempotent): Buffer post {same[0]['id']} status {same[0]['status']}. Nothing created.")
        if MODE == "scheduled":
            set_status(folder, "BUFFER_SCHEDULED", buffer_post_id=same[0]["id"], due_at=slot.isoformat())
        print(f"::notice title=ALREADY SCHEDULED::Buffer post {same[0]['id']} ({same[0]['status']}); no new post created")
        return
    if conflicts:
        die(f"duplicate/conflict: existing Buffer post(s) {[p['id'] for p in conflicts]} are not identical to this report")
    if not time_ok():
        die("2:45 PM cutoff reached before createPost")

    # ---- the single createPost call; an uncertain outcome is never retried, Buffer is re-read first
    inp = {"channelId": CHANNEL_ID, "schedulingType": "automatic", "mode": "customScheduled",
           "dueAt": slot.isoformat(), "saveToDraft": False, "text": cap,
           "assets": [{"document": {"url": pdf_url, "thumbnailUrl": png_url, "title": title}}]}
    pid = None
    try:
        res = gql("mutation($i:CreatePostInput!){createPost(input:$i){__typename ... on PostActionSuccess{post{id}}"
                  " ... on MutationError{message}}}", {"i": inp}, soft=True)["createPost"]
        if res["__typename"] != "PostActionSuccess":
            die(f"createPost refused: {res.get('message')}")  # final: Buffer rejected it
        pid = res["post"]["id"]
    except RuntimeError as e:
        time.sleep(5)  # outcome UNCERTAIN: look at Buffer, never resend
        try:
            again = [p for p in find_conflicts(date_line, slot) if is_identical(p, cap, slot)]
        except SystemExit:
            raise
        if len(again) == 1:
            print(f"UNCERTAIN createPost ({e}) but Buffer shows the post: {again[0]['id']}. Not retried.")
            pid = again[0]["id"]
        else:
            die(f"createPost outcome uncertain ({e}) and no matching post found; NOT retried now (next run checks Buffer first)", transient=True)

    # ---- read back; delete only this post if anything is off
    p = gql("query($i:PostInput!){post(input:$i){id status dueAt channelId text assets{source thumbnail ... on DocumentAsset{document{title}}}}}",
            {"i": {"id": pid}})["post"]
    a = (p["assets"] or [{}])[0]
    ok = (p["status"] == "scheduled" and datetime.fromisoformat(p["dueAt"].replace("Z", "+00:00")) == slot
          and p["channelId"] == CHANNEL_ID and p["text"] == cap and a.get("source") == pdf_url
          and a.get("thumbnail") == png_url and (a.get("document") or {}).get("title") == title)
    if not ok:
        gql("mutation($i:DeletePostInput!){deletePost(input:$i){__typename}}", {"i": {"id": pid}})
        die(f"read-back mismatch; deleted post {pid}")
    if MODE == "scheduled":
        set_status(folder, "BUFFER_SCHEDULED", buffer_post_id=pid, due_at=slot.isoformat())
    print(f"SCHEDULED: Buffer post {pid} for {slot.isoformat()} on '{CHANNEL_NAME}' (LinkedIn); PDF sha256 {P['pdf_sha256']}")
    print(f"::notice title=SCHEDULED::Buffer post {pid} dueAt {slot.isoformat()} sha256 {P['pdf_sha256']}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        open(summary, "a").write(f"### SCHEDULED\n- ticker {tk}\n- Buffer post `{pid}`\n- dueAt {slot.isoformat()}\n- pdf sha256 `{P['pdf_sha256']}`\n")


START = time.time()
if __name__ == "__main__":
    main()
