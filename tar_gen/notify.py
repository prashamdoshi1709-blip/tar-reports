"""Notifications through GitHub issues (GitHub emails the repository owner about new issues and comments).

The repository is public, so notifications carry only status, reason codes, ticker, date and hashes: never report
text, captions or Vitti content. Uses the workflow's own GITHUB_TOKEN (permission issues: write); no extra secret.

  failure   opens "TAR generator: no report for <date>" (label tar-generator). While that issue is open, later runs
            for the same date do not retry (no repeated AI spend, no spam). Closing the issue allows a retry.
  success   one comment per day on the rolling issue "TAR generator: daily log", so every run leaves a trace.
"""
import json, os, urllib.request, urllib.error

API = "https://api.github.com"
LABEL = "tar-generator"


def _req(method, path, body=None):
    tok, repo = os.environ.get("GITHUB_TOKEN"), os.environ.get("GITHUB_REPOSITORY")
    if not tok or not repo:
        return None
    req = urllib.request.Request(f"{API}/repos/{repo}{path}", method=method,
                                 data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": f"Bearer {tok}", "Accept": "application/vnd.github+json",
                                          "User-Agent": "tar-generator", "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read() or b"null")
    except (urllib.error.URLError, ValueError) as e:
        print(f"::warning title=NOTIFY::GitHub API {method} {path} failed ({type(e).__name__})")
        return None


def _find(title):
    for st in ("open", "closed"):
        for i in _req("GET", f"/issues?labels={LABEL}&state={st}&per_page=100") or []:
            if i.get("title") == title and "pull_request" not in i:
                return i
    return None


def failure_title(d):
    return f"TAR generator: no report for {d.isoformat()}"


def failure_open(d):
    i = _find(failure_title(d))
    return bool(i and i.get("state") == "open")


def notify_failure(d, code, msg, run_url):
    body = (f"**Date:** {d.isoformat()}\n**Reason:** `{code}`: {msg}\n**Run:** {run_url}\n\n"
            "Nothing was published for this date by the generator. Later runs for this date are paused while this issue is "
            "open; close it to let the next scheduled run try again.\n\n---\n_Automated message from tar_gen._")
    t = failure_title(d)
    i = _find(t)
    if i and i["state"] == "open":
        _req("POST", f"/issues/{i['number']}/comments", {"body": body})
    elif i:
        _req("PATCH", f"/issues/{i['number']}", {"state": "open"})
        _req("POST", f"/issues/{i['number']}/comments", {"body": body})
    else:
        _req("POST", "/issues", {"title": t, "body": body, "labels": [LABEL]})


def notify_log(line):
    t = "TAR generator: daily log"
    i = _find(t)
    if not i:
        i = _req("POST", "/issues", {"title": t, "body": "One comment per generator outcome. No report content is posted here.",
                                      "labels": [LABEL]})
    elif i["state"] != "open":
        _req("PATCH", f"/issues/{i['number']}", {"state": "open"})
    if i:
        _req("POST", f"/issues/{i['number']}/comments", {"body": line})
