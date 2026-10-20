#!/usr/bin/env python3
"""TAR Buffer scheduler (runs in GitHub Actions, stdlib only).

Schedules ONE verified, current-day TAR report in Buffer for 3:00 PM Sydney through Buffer's official
GraphQL API (https://api.buffer.com). It never researches, edits or rebuilds anything: it only
re-verifies the committed payload and, if every check passes, makes exactly one createPost call.

MODE (env): live (default, push to main only) | dryrun (all checks, no createPost, time guards skipped)
            | selftest (secret + Buffer read-only connection test, no payload needed)
Fail closed: any problem -> exit 1 with a reason, nothing scheduled. The API key is read from the
BUFFER_API_KEY environment variable only and is never printed.
"""
import hashlib, json, os, re, subprocess, sys, time, urllib.request, urllib.error
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

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
MODE = os.environ.get("MODE", "live").strip() or "live"


def die(msg):
    print(f"NOT SCHEDULED: {msg}")
    print(f"::error title=NOT SCHEDULED::{msg}")  # annotation: readable through the check-runs API
    sys.exit(1)


def now_syd():
    return datetime.now(SYD)


def gql(query, variables=None):
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
        die(f"Buffer API HTTP {e.code} (401 means the API key is invalid or revoked)")
    except Exception as e:
        die(f"Buffer API request failed: {type(e).__name__}")
    if out.get("errors"):
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


def duplicate_check(date_line, slot):
    for p in all_posts():
        t = p["text"] or ""
        if t.startswith("DRY RUN DRAFT") or t.startswith("TEST ONLY"):
            continue
        if date_line in t:
            die(f"duplicate: Buffer post {p['id']} (status {p['status']}) already contains '{date_line}'")
        if p["status"] in ("scheduled", "sending", "needs_approval") and p["dueAt"]:
            due = datetime.fromisoformat(p["dueAt"].replace("Z", "+00:00"))
            if due == slot:
                die(f"a post ({p['id']}) is already scheduled for the {slot.isoformat()} slot")


def sha256(path):
    return hashlib.sha256(open(path, "rb").read()).hexdigest()


def main():
    if MODE == "selftest":
        c = buffer_connection_checks()
        n = len(all_posts())
        msg = (f"SELFTEST PASS: API key accepted; organisation and channel '{c['displayName']}' ({c['service']}) verified; "
               f"{n} existing posts readable; nothing created.")
        print(msg)
        print(f"::notice title=SELFTEST PASS::{msg}")
        return
    if MODE not in ("live", "dryrun"):
        die(f"unknown MODE {MODE!r}")
    if MODE == "live" and (os.environ.get("GITHUB_EVENT_NAME") != "push" or os.environ.get("GITHUB_REF") != "refs/heads/main"):
        die("live scheduling is only allowed from a push to main")

    # ---- payload selection
    path = os.environ.get("PAYLOAD", "").strip()
    if not path:
        out = subprocess.run(["git", "diff", "--name-only", "HEAD^", "HEAD", "--", "reports/*/publish.json"],
                             capture_output=True, text=True).stdout.split()
        if len(out) != 1:
            die(f"expected exactly one publish.json in this commit, found {len(out)}")
        path = out[0]
    if not re.fullmatch(r"reports/\d{4}-\d{2}-\d{2}-[A-Z0-9]{2,5}/publish\.json", path) or not os.path.isfile(path):
        die(f"bad payload path {path!r}")
    P = json.load(open(path, encoding="utf-8"))
    folder = os.path.dirname(path)
    tk, iso, company = P["ticker"], P["report_date_iso"], P["company_name"]
    d = datetime.strptime(P["report_date"], "%d %B %Y").date()
    if P.get("schema") != 1 or P.get("mode") != "LIVE" or d.isoformat() != iso or folder != f"reports/{iso}-{tk}":
        die("payload schema/mode/date/folder mismatch")
    if not re.fullmatch(r"[A-Z0-9]{2,5}", tk):
        die("bad ticker")

    # ---- current-day production guard, time guards
    today = now_syd().date()
    slot = datetime(d.year, d.month, d.day, 15, 0, tzinfo=SYD)
    if MODE == "live":
        if d != today:
            die(f"report date {d} is not today in Sydney ({today})")
        if d.weekday() >= 5 or iso in CLOSURES or iso in EARLY_CLOSE:
            die("not a full ASX trading day")
        if not json.load(open("config/auto-publish.json")).get("enabled") is True:
            die("AUTO-PUBLISH OFF (config/auto-publish.json enabled is not true)")
    cutoff = datetime(d.year, d.month, d.day, 14, 30, tzinfo=SYD)

    def time_ok():
        n = now_syd()
        return MODE == "dryrun" or (n < cutoff and slot - n >= timedelta(minutes=15))
    if not time_ok():
        die(f"past the 2:30 PM Sydney cutoff or slot too close (now {now_syd().isoformat()})")

    # ---- payload hygiene (mirrors the routine's Step 2e)
    for k in ("claude_verification", "package_id", "review_record_id", "pdf_sha256", "title", "caption", "marker_sha256"):
        if k not in P:
            die(f"payload missing {k}")
    cv = P["claude_verification"]
    need = ["marker_hashes_match", "review_research_ready", "verify_clean_pdf_pass", "visual_check_done",
            "newer_asx_filings_none_material", "buffer_duplicate_check_clear"]
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
    while True:
        try:
            body = urllib.request.urlopen(urllib.request.Request(pdf_url + f"?v={int(time.time())}",
                                          headers={"User-Agent": "tar-buffer-schedule/1.0"}), timeout=30).read()
            if hashlib.sha256(body).hexdigest() == P["pdf_sha256"]:
                urllib.request.urlopen(urllib.request.Request(png_url + f"?v={int(time.time())}",
                                       headers={"User-Agent": "tar-buffer-schedule/1.0"}), timeout=30).read()
                break
        except Exception:
            pass
        if not time_ok() or time.time() > START + 360:
            die("public PDF/cover not live with the verified hash in time")
        time.sleep(15)

    # ---- Buffer: connection, channel, duplicates
    buffer_connection_checks()
    duplicate_check(date_line, slot)
    if MODE == "dryrun":
        print("DRYRUN PASS: every check passed; createPost NOT called.")
        print("::notice title=DRYRUN PASS::every check passed; createPost NOT called.")
        return
    if not time_ok():
        die("2:30 PM cutoff reached before createPost")

    # ---- the single createPost call (never retried)
    inp = {"channelId": CHANNEL_ID, "schedulingType": "automatic", "mode": "customScheduled",
           "dueAt": slot.isoformat(), "saveToDraft": False, "text": cap,
           "assets": [{"document": {"url": pdf_url, "thumbnailUrl": png_url, "title": title}}]}
    res = gql("mutation($i:CreatePostInput!){createPost(input:$i){__typename ... on PostActionSuccess{post{id}}"
              " ... on MutationError{message}}}", {"i": inp})["createPost"]
    if res["__typename"] != "PostActionSuccess":
        die(f"createPost refused: {res.get('message')}")
    pid = res["post"]["id"]

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
    print(f"SCHEDULED: Buffer post {pid} for {slot.isoformat()} on '{CHANNEL_NAME}' (LinkedIn); PDF sha256 {P['pdf_sha256']}")
    print(f"::notice title=SCHEDULED::Buffer post {pid} dueAt {slot.isoformat()} sha256 {P['pdf_sha256']}")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        open(summary, "a").write(f"### SCHEDULED\n- ticker {tk}\n- Buffer post `{pid}`\n- dueAt {slot.isoformat()}\n- pdf sha256 `{P['pdf_sha256']}`\n")


START = time.time()
if __name__ == "__main__":
    main()
