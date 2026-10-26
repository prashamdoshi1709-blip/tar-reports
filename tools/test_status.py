#!/usr/bin/env python3
"""Offline tests for the status machine and reconcile logic in buffer_schedule.py (no network, no secrets)."""
import importlib.util, json, os, sys, tempfile
from datetime import datetime, timedelta
os.environ["MODE"] = "scheduled"
spec = importlib.util.spec_from_file_location("bs", os.path.join(os.path.dirname(os.path.abspath(__file__)), "buffer_schedule.py"))
bs = importlib.util.module_from_spec(spec); spec.loader.exec_module(bs)
fails = []
def check(name, cond):
    print(("PASS " if cond else "FAIL ") + name)
    if not cond: fails.append(name)
def run(fn):
    try: fn(); return 0
    except SystemExit as e: return e.code
tmp = tempfile.mkdtemp()
slot = datetime.now(bs.SYD) + timedelta(minutes=30)

# 1 handoff -> scheduled -> sent (no link) -> linkedin confirmed
bs.set_status(tmp, "HANDOFF_COMMITTED"); check("handoff recorded", bs.load_status(tmp)["state"] == "HANDOFF_COMMITTED")
bs.set_status(tmp, "BUFFER_SCHEDULED", buffer_post_id="p1")
posts = {"status": "scheduled", "dueAt": slot.isoformat(), "sentAt": None, "externalLink": None, "error": None}
bs.gql = lambda q, v=None, soft=False: {"post": dict(posts, id="p1")}
st = bs.load_status(tmp)
check("scheduled stays BUFFER_SCHEDULED (waiting)", run(lambda: bs.reconcile(tmp, st, slot)) == 0 and bs.load_status(tmp)["state"] == "BUFFER_SCHEDULED")
posts.update(status="sent", sentAt="x")
bs.reconcile(tmp, bs.load_status(tmp), slot); s = bs.load_status(tmp)
check("sent without link = BUFFER_SENT, not final", s["state"] == "BUFFER_SENT" and not s["final"])
posts.update(externalLink="https://www.linkedin.com/feed/update/urn:li:share:1")
bs.reconcile(tmp, bs.load_status(tmp), slot); s = bs.load_status(tmp)
check("sent with LinkedIn URL = LINKEDIN_CONFIRMED final", s["state"] == "LINKEDIN_CONFIRMED" and s["final"] and "linkedin.com" in s["linkedin_url"])

# 2 error post -> FAILED, run red
t2 = tempfile.mkdtemp(); bs.set_status(t2, "BUFFER_SCHEDULED", buffer_post_id="p2")
posts.update(status="error", externalLink=None, error={"message": "LinkedIn rejected"})
code = run(lambda: bs.reconcile(t2, bs.load_status(t2), slot)); s = bs.load_status(t2)
check("error post = FAILED final and exit 1", code == 1 and s["state"] == "FAILED" and s["final"] and "LinkedIn rejected" in s["reason"])

# 3 stalled scheduled post long after slot
t3 = tempfile.mkdtemp(); bs.set_status(t3, "BUFFER_SCHEDULED", buffer_post_id="p3")
posts.update(status="scheduled", error=None)
code = run(lambda: bs.reconcile(t3, bs.load_status(t3), datetime.now(bs.SYD) - timedelta(minutes=45)))
check("stalled post = FAILED exit 1", code == 1 and bs.load_status(t3)["state"] == "FAILED")

# 4 die(): transient before cutoff retries (exit 0, not final); transient after cutoff or permanent is FINAL red
for name, transient, past, exp_code, exp_final in [("transient before cutoff", True, False, 0, False),
                                                   ("transient after cutoff", True, True, 1, True),
                                                   ("permanent before cutoff", False, False, 1, True)]:
    d = tempfile.mkdtemp(); bs.set_status(d, "HANDOFF_COMMITTED"); bs.CTX.update(folder=d, past_cutoff=past)
    code = run(lambda: bs.die("x", transient=transient)); s = bs.load_status(d)
    check(f"die: {name}", code == exp_code and bool(s["final"]) == exp_final and (s["state"] == "FAILED") == exp_final)
sys.exit(1 if fails else 0)
