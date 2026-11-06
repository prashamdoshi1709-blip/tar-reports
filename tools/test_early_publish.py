#!/usr/bin/env python3
"""Offline tests for REV 8 early publication. No network, no Buffer calls."""
import os, sys
from datetime import datetime, timedelta
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("MODE", "verify")
import buffer_schedule as bs

fails = 0
def check(name, ok):
    global fails
    print(("PASS  " if ok else "FAIL  ") + name)
    fails += 0 if ok else 1

n = datetime(2026, 11, 9, 11, 7, 42, tzinfo=bs.SYD)
s = bs.early_slot(n)
check("slot is whole minute", s.second == 0 and s.microsecond == 0)
check("slot is 3-4 min in the future", timedelta(minutes=2, seconds=1) < s - n <= timedelta(minutes=3))
today = n.date()
cap = "The Announcement Room | X (XXX)\nbody"
def post(text, status, when):
    return {"id": "p", "text": text, "status": status, "dueAt": when.isoformat(), "sentAt": None}
t = datetime(2026, 11, 9, 11, 0, tzinfo=bs.SYD)
check("other TAR post today blocks", bs.post_is_tar_report_today(post("The Announcement Room | Y (YYY)\nx", "sent", t), today))
check("draft ignored", not bs.post_is_tar_report_today(post("The Announcement Room | Y (YYY)\nx", "draft", t), today))
check("DRY RUN ignored", not bs.post_is_tar_report_today(post("DRY RUN DRAFT x", "scheduled", t), today))
check("yesterday ignored", not bs.post_is_tar_report_today(post("The Announcement Room | Y (YYY)\nx", "sent", t - timedelta(days=1)), today))
check("identical regardless of time", bs.is_identical(post(cap, "sent", t - timedelta(hours=1)), cap))
check("different text not identical", not bs.is_identical(post(cap + "z", "sent", t), cap))
check("error status not identical", not bs.is_identical(post(cap, "error", t), cap))
print(f"\n{'ALL PASS' if not fails else str(fails) + ' FAILED'}")
sys.exit(1 if fails else 0)
