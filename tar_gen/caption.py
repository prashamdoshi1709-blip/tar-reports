"""LinkedIn caption in the house format the publisher (tools/buffer_schedule.py) checks, e.g. reports/2026-11-02-A4N.

The first line, the date line, the disclaimer and the hashtag line are fixed text built from the verified package
identity; only the paragraphs and bullets come from the writer (after tar_gen.checks has passed them)."""
import re

from .common import DISCLAIMER, GenError, long_date

MAX_LEN = 2900  # LinkedIn's limit is 3,000 characters
FIXED_TAGS = ["#EquityResearch", "#AustralianStocks"]


def hashtags(ident, extra):
    tags, seen = [], set()
    for t in ["ASX", ident.ticker] + list(extra) + [x[1:] for x in FIXED_TAGS]:
        t = re.sub(r"[^A-Za-z0-9]", "", t)
        if t and t.lower() not in seen and not t.isdigit():
            seen.add(t.lower())
            tags.append("#" + t)
    return " ".join(tags[:8])


def build_caption(rep, ident):
    c = rep["caption"]
    tk, d = ident.ticker, long_date(ident.date)
    parts = [f"The Announcement Room | {ident.company} ({tk})", c["intro"], c["context"],
             "Key points:\n" + "\n".join(f"• {s}" for s in c["key_points"]),
             c["looking_ahead"],
             "In this two-page investor report, we look at:\n" + "\n".join(f"• {s}" for s in c["we_look_at"]),
             f"ASX: {tk} | {d}", DISCLAIMER, hashtags(ident, c.get("hashtags", []))]
    cap = "\n\n".join(p.strip() for p in parts)
    # The same rules the publisher applies before it will create a Buffer post.
    if (not cap.startswith(f"The Announcement Room | {ident.company} ({tk})") or f"ASX: {tk} | {d}" not in cap
            or "—" in cap or f"{DISCLAIMER}\n\n#ASX" not in cap or f"#{tk}" not in cap):
        raise GenError("CAPTION", "caption failed the publisher's consistency rules")
    if len(cap) > MAX_LEN:
        raise GenError("CAPTION_LENGTH", f"caption is {len(cap)} characters (limit {MAX_LEN})")
    return cap
