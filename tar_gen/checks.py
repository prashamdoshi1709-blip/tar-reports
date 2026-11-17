"""Content checks on an AI-written report before anything is rendered or published. Each returns readable problems; the
writer gets them back as feedback and must fix them, and a report with any remaining problem is never published.

  figures      every number in the report and caption must appear in the Vitti-supplied material (the Daily Mover or
               the company's own announcement of the day in the same package). No invented, rounded or derived figures.
  company      the only ASX code mentioned is the report's own; the company's official name comes from the Daily Mover.
  date         the report date comes from the package, never from the model.
  attribution  the caption opens by attributing the facts to the Vitti Capital Daily Mover; page sources are fixed text.
  wording      no "draft" / "not approved" (the publisher rejects them anywhere), no em dashes, no clock times, no advice.
  shape        field lengths that keep the two-page layout readable (the renderer then measures the real layout).
"""
import re

from .common import BAD, GenError, long_date
from .spell import SpellUnavailable, typos
from .vitti import NUM_RE

ADVICE = re.compile(r"\b(we recommend|you should (buy|sell|hold)|(strong )?buy rating|sell rating|investors should (buy|sell)|"
                    r"guaranteed? (return|profit)s?|risk[- ]free)\b", re.I)
CLOCK = re.compile(r"\b\d{1,2}:\d{2}\b")
ASX_CODE = re.compile(r"\bASX\s*:\s*([A-Z0-9]{2,5})\b")
DOUBLED = re.compile(r"\b([A-Za-z]{2,})\s+\1\b", re.I)
SPACE_PUNCT = re.compile(r"\s[,;:!?]|\s\.(?!\d)")
REPEAT_PUNCT = re.compile(r"[,;:]{2}|(?<!\.)\.\.(?!\.)|[!?]{2}|,\.|\.,")
LOWER_START = re.compile(r"[a-z]{3}[.!?]\s+[a-z]")
UNIT_AFTER = re.compile(r"^\s?(%|m\b|bn\b|b\b|k\b|x\b|c\b|cps\b|per ?cent|million|billion|thousand|times|cents)", re.I)

LIMITS = {"headline": (30, 120), "title": (12, 54), "topic": (4, 52), "lede": (80, 430), "facts_label": (4, 50),
          "context_label": (4, 50), "take": (60, 560)}
ITEM = {"facts": (3, 5, 70, 270), "context": (2, 4, 60, 230), "why": (3, 3, 70, 250), "watch": (3, 4, 50, 260)}
CAP = {"intro": (80, 520), "context": (60, 480), "looking_ahead": (60, 460)}


def sanitize(rep):
    """Deterministic, meaning-preserving clean-up applied before the checks: em dashes, odd spaces, stray whitespace."""
    def fix(s):
        s = s.replace(" — ", ", ").replace("—", "-").replace(" ", " ").replace(" ", " ")
        return re.sub(r"[ \t]+", " ", s).strip()

    def walk(o):
        if isinstance(o, str):
            return fix(o)
        if isinstance(o, list):
            return [walk(x) for x in o]
        if isinstance(o, dict):
            return {k: walk(v) for k, v in o.items()}
        return o
    return walk(rep)


def visible_strings(rep):
    """(field, text) for every string a reader will see, report and caption."""
    out = []
    for k in ("headline", "title", "topic", "lede", "facts_label", "context_label", "take"):
        out.append((k, rep[k]))
    for k in ("take_label", "sources_note"):
        if rep.get(k):
            out.append((k, rep[k]))
    for i, k in enumerate(rep["kpis"]):
        out += [(f"kpis[{i}].value", k["value"]), (f"kpis[{i}].label", k["label"]), (f"kpis[{i}].note", k["note"])]
    c = rep.get("chart") or {}
    if c.get("include"):
        out += [("chart.label", c.get("label", "")), ("chart.note", c.get("note", ""))]
        out += [(f"chart.bars[{i}]", f"{b['label']} {b['display']}") for i, b in enumerate(c.get("bars", []))]
    for sec in ("facts", "context", "why", "watch"):
        for i, x in enumerate(rep[sec]):
            out += [(f"{sec}[{i}].head", x["head"]), (f"{sec}[{i}].body", x["body"])]
    cap = rep["caption"]
    for k in ("intro", "context", "looking_ahead"):
        out.append((f"caption.{k}", cap[k]))
    out += [(f"caption.key_points[{i}]", s) for i, s in enumerate(cap["key_points"])]
    out += [(f"caption.we_look_at[{i}]", s) for i, s in enumerate(cap["we_look_at"])]
    return out


def unsupported_numbers(text, source_numbers, allowed_extra):
    bad = []
    for m in NUM_RE.finditer(text):
        whole, dec = m.group(1).replace(",", ""), m.group(2)
        v = round(float(whole + ("." + dec if dec else "")), 6)
        if v in source_numbers or v in allowed_extra:
            continue
        before = text[max(0, m.start() - 1):m.start()]
        after = text[m.end():m.end() + 12]
        unit = UNIT_AFTER.match(after)
        if not dec and before != "$" and not unit and (v <= 10 or 2015 <= v <= 2035):
            continue  # list counts, "two of three", years used as labels; money and percentages are never exempt
        bad.append(m.group(0) + (unit.group(1) if unit else ""))
    return bad


def check_report(rep, ident):
    p = []
    for k, (lo, hi) in LIMITS.items():
        n = len(rep.get(k) or "")
        if not lo <= n <= hi:
            p.append(f"{k} is {n} characters; it must be {lo}-{hi}")
    if not 3 <= len(rep["kpis"]) <= 4:
        p.append("kpis must have 3 or 4 entries")
    for i, k in enumerate(rep["kpis"]):
        if not 1 <= len(k["value"]) <= 12:
            p.append(f"kpis[{i}].value {k['value']!r} must be 1-12 characters (a figure, e.g. +12.4% or $1.25)")
        if len(k["label"]) > 30 or len(k["note"]) > 75:
            p.append(f"kpis[{i}] label must be <= 30 and note <= 75 characters")
    for sec, (mn, mx, hh, bb) in ITEM.items():
        items = rep[sec]
        if not mn <= len(items) <= mx:
            p.append(f"{sec} must have {mn}-{mx} entries, has {len(items)}")
        for i, x in enumerate(items):
            if len(x["head"]) > hh or len(x["body"]) > bb or len(x["body"]) < 25:
                p.append(f"{sec}[{i}] head must be <= {hh} and body 25-{bb} characters")
    c = rep.get("chart") or {}
    if c.get("include"):
        bars = c.get("bars") or []
        if not 2 <= len(bars) <= 6 or any(b["value"] < 0 for b in bars):
            p.append("chart needs 2-6 bars with non-negative values, or include=false")
    cap = rep["caption"]
    for k, (lo, hi) in CAP.items():
        if not lo <= len(cap[k]) <= hi:
            p.append(f"caption.{k} is {len(cap[k])} characters; it must be {lo}-{hi}")
    if not 3 <= len(cap["key_points"]) <= 6 or any(len(s) > 170 for s in cap["key_points"]):
        p.append("caption.key_points must have 3-6 entries of at most 170 characters")
    if len(cap["we_look_at"]) != 4 or any(len(s) > 70 for s in cap["we_look_at"]):
        p.append("caption.we_look_at must have exactly 4 entries of at most 70 characters")
    if "vitti capital daily mover" not in cap["intro"].lower():
        p.append("caption.intro must attribute the facts, e.g. 'According to the Vitti Capital Daily Mover dated "
                 f"{long_date(ident.date)}, ...'")

    allowed_extra = {round(float(ident.date.day), 6), round(float(ident.date.year), 6)}
    for field, text in visible_strings(rep):
        if BAD.search(text) or BAD.search(re.sub(r"\s+", "", text)):
            p.append(f"{field}: must not contain the words 'draft' or 'approved'")
        if "—" in text:
            p.append(f"{field}: no em dashes")
        if CLOCK.search(text):
            p.append(f"{field}: no clock times; say 'in morning trade' for the intraday move")
        if ADVICE.search(text):
            p.append(f"{field}: reads as personal financial advice; describe, do not recommend")
        if DOUBLED.search(text):
            p.append(f"{field}: repeated word '{DOUBLED.search(text).group(0)}'")
        if SPACE_PUNCT.search(text) or REPEAT_PUNCT.search(text):
            p.append(f"{field}: punctuation error")
        if text.count("(") != text.count(")"):
            p.append(f"{field}: unbalanced brackets")
        if LOWER_START.search(text):
            p.append(f"{field}: a sentence starts with a lower-case letter")
        try:
            bad_words = typos(text)
        except SpellUnavailable:
            raise GenError("SPELLCHECK_UNAVAILABLE", "hunspell is not installed; spelling cannot be checked")
        if bad_words:
            p.append(f"{field}: likely misspelling(s): {', '.join(bad_words)}")
        for code in ASX_CODE.findall(text):
            if code != ident.ticker:
                p.append(f"{field}: mentions ASX code {code}; only {ident.ticker} may appear")
        bad = unsupported_numbers(text, ident.source_numbers, allowed_extra)
        if bad:
            p.append(f"{field}: figures not found in the Vitti material: {', '.join(bad)} "
                     "(use figures exactly as Vitti wrote them; no rounding, conversions or own calculations)")
    for i, b in enumerate((c.get("bars") or []) if c.get("include") else []):
        if round(float(b["value"]), 6) not in ident.source_numbers:
            p.append(f"chart.bars[{i}].value {b['value']} is not a figure in the Vitti material")
    if ident.company.lower() not in rep["caption"]["intro"].lower() and ident.company.split()[0].lower() not in rep["caption"]["intro"].lower():
        p.append("caption.intro must name the company")
    return p
