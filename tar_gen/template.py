"""MODE B: deterministic report writer. No AI, no API, no network, no cost; nothing leaves the GitHub runner.

It arranges what Vitti wrote in the Daily Mover into the TAR two-page structure and adds no analysis of its own:

  page 1  headline (Vitti's), share move and KPI tiles (Vitti's figures and labels), Vitti's chart if it has one
          clean series, "What changes now" (Vitti's list), "How we got here" (Vitti's timeline)
  page 2  "Why investors appeared to focus on it" = Vitti's possible drivers of the move,
          "What investors should watch" = Vitti's key risks, and the Vitti view (labelled as Vitti's, not as a TAR take)

Linking sentences are fixed templates ("According to the Vitti Capital Daily Mover dated ..."). If a section the report
needs is missing or unreadable, it stops with INSUFFICIENT_SOURCE rather than filling the gap. Every report still goes
through the same figure, wording, layout and PDF checks as any other.

When the pipeline reports a problem it tries again more compactly (attempt 2: no chart, fewer list items; attempt 3:
minimum lengths) and drops any list item the checks flagged.
"""
import re

from .common import GenError, long_date, norm_space
from .dailymover import parse, sentence_case

SUFFIXES = (" Group Limited", " Holdings Limited", " Limited", " Ltd", " Group", " Holdings", " Corporation", " Inc", " plc", " NL")
CLOCK = re.compile(r"\s*·?\s*\bAS AT\b\s*\d{1,2}:\d{2}|\s*\b\d{1,2}:\d{2}\b", re.I)


def short_name(company):
    s = company
    for _ in range(3):
        for suf in SUFFIXES:
            if s.endswith(suf) and len(s) > len(suf) + 2:
                s = s[: -len(suf)]
    return s.strip()


def lower_first(s):
    s = s.strip()
    return s[:1].lower() + s[1:] if len(s) > 1 and s[1:2].islower() else s


def full_stop(s):
    s = s.strip().rstrip(";,")
    return s if s.endswith((".", "?", "!", "…")) else s + "."


def _num(s):
    m = re.search(r"\d[\d,]*(?:\.\d+)?", s)
    return float(m.group(0).replace(",", "")) if m else None


def required(dm):
    missing = [k for k, ok in (("headline", dm["headline"]), ("share move tile", dm["kpis"] and dm["kpis"][0]["label"].upper().startswith("SHARE MOVE")),
                               ("three or more KPI tiles", len(dm["kpis"]) >= 3), ("three possible drivers", len(dm["drivers"]) >= 3),
                               ("two or more 'what changes now' points", len(dm["changes"]) >= 2),
                               ("two or more timeline entries", len(dm["timeline"]) >= 2), ("three key risks", len(dm["risks"]) >= 3),
                               ("Vitti view", dm["view"])) if not ok]
    return missing


def compose(ident, dm, level=1, drop=frozenset()):
    tk, d = ident.ticker, long_date(ident.date)
    short = short_name(ident.company)
    move_k = dm["kpis"][0]
    move = move_k["value"].replace("−", "-")
    up = not move.startswith("-")
    pct = move.lstrip("+-")
    pm = re.search(r"\$\s?\d[\d.,]*", move_k["label"])
    price = pm.group(0).replace(" ", "") if pm else None
    verb = "rose" if up else "fell"
    at_price = f" to {price}" if price else ""

    head = norm_space(dm["headline"])
    title = None
    for sep in (" as ", " after ", " on ", " despite "):
        if sep in head:
            cand = f"{short}: {head.split(sep, 1)[1].strip()}"
            if len(cand) <= 54:
                title = cand
                break
    if not title:
        title = f"{short}: Shares {'Up' if up else 'Down'} {pct} in Morning Trade"
    if len(title) > 54:
        title = f"{tk}: Shares {'Up' if up else 'Down'} {pct} in Morning Trade"

    def keep(sec, items):
        return [x for i, x in enumerate(items) if f"{sec}[{i}]" not in drop]

    kpis = [{"value": move, "label": "Share move", "note": f"Morning trade{', ' + price if price else ''}, not a closing price", "tone": "orange"}]
    for i, k in enumerate(dm["kpis"][1:4], 1):
        lab = sentence_case(k["label"])
        if len(k["value"]) <= 12 and len(lab) <= 30 and f"kpis[{i}]" not in drop:
            kpis.append({"value": k["value"], "label": lab, "note": "As reported by Vitti", "tone": "teal" if len(kpis) == 1 else "navy"})

    chart = {"include": False, "label": "", "note": "", "bars": []}
    c = dm.get("chart")
    if c and level == 1 and "chart" not in drop:
        bars = [{"label": cat, "value": _num(v), "display": f"{v} {cat}"} for cat, v in c["points"] if _num(v) is not None]
        if 2 <= len(bars) <= 6:
            chart = {"include": True, "label": c["title"], "note": c["footnote"].rstrip("…").strip(), "bars": bars}

    n_list = {1: 5, 2: 4, 3: 3}[level]
    changes = [{"head": f"{i}.", "body": full_stop(CLOCK.sub("", t))} for i, t in enumerate(dm["changes"][:n_list], 1)]
    timeline = [{"head": e["date"], "body": full_stop(e["text"])} for e in dm["timeline"] if len(e["text"]) >= 24][-{1: 4, 2: 4, 3: 2}[level]:]
    drivers = [{"head": f"Possible driver {i}", "body": full_stop(CLOCK.sub("", t))} for i, t in enumerate(dm["drivers"][:3], 1)]
    risks = [{"head": r["head"], "body": full_stop(r["text"])} for r in dm["risks"][:4 if level == 1 else 3]]
    view = full_stop(dm["view"])

    rep = {
        "title": title, "headline": head,
        "topic": sentence_case(dm["kpis"][1]["label"])[:52] if len(dm["kpis"]) > 1 else "Share price move",
        "lede": (f"{ident.company} shares {verb} {pct} in morning trade{at_price}, according to the Vitti Capital Daily Mover. "
                 f"The first possible driver Vitti lists is: {lower_first(full_stop(dm['drivers'][0]))}"),
        "kpis": kpis, "chart": chart,
        "facts_label": "What changes now, according to Vitti", "facts": keep("facts", changes),
        "context_label": "How we got here", "context": keep("context", timeline),
        "why": keep("why", drivers), "watch": keep("watch", risks),
        "take_label": "Vitti view", "take": view,
        "sources_note": full_stop(dm["source"]) if dm.get("source") else "",
        "caption": {
            "intro": f"According to the Vitti Capital Daily Mover dated {d}, {ident.company} shares {verb} {pct} in morning trade{at_price}.",
            "context": "Vitti points to these possible drivers: " + "; ".join(lower_first(t.rstrip('.')) for t in dm["drivers"][:3]) + ".",
            "key_points": [f"{k['label']}: {k['value']}" for k in kpis[1:]] + [x["body"] for x in changes[:2]],
            "looking_ahead": "Looking ahead, Vitti flags these key risks: " + "; ".join(lower_first(r["head"]) for r in dm["risks"][:3]) + ".",
            "we_look_at": ["What may have driven the move", "What changes now", "How we got here", "Key risks and the Vitti view"],
            "hashtags": [re.sub(r"[^A-Za-z0-9]", "", short)],
        },
    }
    if len(rep["caption"]["context"]) > 480:
        rep["caption"]["context"] = "Vitti points to this possible driver: " + lower_first(full_stop(dm["drivers"][0]))
    rep["caption"]["key_points"] = [p for p in rep["caption"]["key_points"] if len(p) <= 170][:6]
    return rep


class TemplateWriter:
    """Same interface as the AI writers (start/complete). `mode` is recorded in the handoff."""
    mode = "B-template"

    def __init__(self, ident, pdf_path):
        self.ident = ident
        self.dm = parse(pdf_path, ident.company)
        self.usage = []
        self.calls = 0
        missing = required(self.dm)
        if missing:
            raise GenError("INSUFFICIENT_SOURCE", "the Daily Mover lacks what a report needs: " + ", ".join(missing))

    def start(self, ident):
        return []

    def complete(self, messages):
        self.calls += 1
        drop = set()
        for m in messages:
            if m.get("role") == "user" and isinstance(m.get("content"), str):
                for sec, idx in re.findall(r"\b(facts|context|why|watch|kpis)\[(\d+)\]", m["content"]):
                    drop.add(f"{sec}[{idx}]")
                if "chart" in m["content"]:
                    drop.add("chart")
        rep = compose(self.ident, self.dm, level=min(self.calls, 3), drop=frozenset(drop))
        return rep, "template"
