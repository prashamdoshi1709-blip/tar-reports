"""Structured reader for the Vitti Capital Daily Mover one-page snapshot (react-pdf, fixed layout).

Uses word coordinates from `pdftotext -bbox-layout` (no AI, no network) to recover each section exactly as Vitti wrote it:

    headline | 3-4 KPI tiles (value + label) | optional chart (title, subtitle, one value per period, footnote)
    WHAT MAY HAVE DRIVEN THE MOVE (numbered) | WHAT CHANGES NOW (numbered)
    HOW WE GOT HERE (dated timeline columns) | KEY RISKS REMAINING (heading + text columns)
    Vitti view | Source

Letter-spaced labels ("S H A R E  M OV E") are rebuilt into words from the gaps between glyphs. Anything the reader
cannot place with confidence is left out; the deterministic writer then decides whether enough remains for a report.
"""
import html, re, statistics

from .common import run

VALUE_RE = re.compile(r"^[+\-−]?(?:[A-Z]{0,3}\$)?\d[\d,]*(?:\.\d+)?(?:%|[mMbBkK]|bn|BN|x)?$")
DATE_RE = re.compile(r"^\d{1,2} [A-Z][a-z]{2} \d{4}$")


class W:
    __slots__ = ("x0", "y0", "x1", "y1", "t")

    def __init__(self, x0, y0, x1, y1, t):
        self.x0, self.y0, self.x1, self.y1, self.t = x0, y0, x1, y1, t


def words(pdf):
    xml = run("pdftotext", "-f", "1", "-l", "1", "-bbox-layout", pdf, "-").stdout
    out = []
    for m in re.finditer(r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>', xml):
        out.append(W(float(m.group(1)), float(m.group(2)), float(m.group(3)), float(m.group(4)), html.unescape(m.group(5))))
    return out


def rows(ws, tol=2.5):
    """Group words into visual rows (same baseline), each sorted left to right."""
    out = []
    for w in sorted(ws, key=lambda w: (w.y0, w.x0)):
        if out and abs(out[-1][0].y0 - w.y0) <= tol:
            out[-1].append(w)
        else:
            out.append([w])
    return [sorted(r, key=lambda w: w.x0) for r in out]


def join(ws):
    """Rebuild text from glyph runs. Letter-spaced runs (most fragments 1-2 characters) get spaces only at wide gaps."""
    if not ws:
        return ""
    short = sum(1 for w in ws if len(w.t) <= 2)
    if len(ws) >= 4 and short / len(ws) >= 0.7:
        gaps = [b.x0 - a.x1 for a, b in zip(ws, ws[1:])]
        base = statistics.median(gaps) if gaps else 0
        s = ws[0].t
        for g, w in zip(gaps, ws[1:]):
            s += (" " if g > base * 1.9 + 0.8 else "") + w.t
        return s
    return " ".join(w.t for w in ws)


def segments(row, gap=24):
    """Split a row into column segments where the horizontal gap is wide."""
    segs, cur = [], [row[0]]
    for a, b in zip(row, row[1:]):
        if b.x0 - a.x1 > gap:
            segs.append(cur); cur = [b]
        else:
            cur.append(b)
    segs.append(cur)
    return segs


def key(s):
    return re.sub(r"[^A-Z]", "", s.upper())


MONTHS3 = {"jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec", "january", "february", "march",
           "april", "june", "july", "august", "september", "october", "november", "december", "monday", "tuesday",
           "wednesday", "thursday", "friday", "australia", "australian", "english"}


# Vitti's KPI labels abbreviate to fit a tile ("FY27 LIFE SCI GROWTH GUID."). Expanded before casing so the report and
# caption read as plain English. Expansions only: no figure, period or unit is ever touched.
# A tile label must stay within 30 characters (checks.py), so "LIFE SCI" becomes the proper-case "Life Sci.".
LABEL_PHRASES = [(r"\bLIFE SCI\b\.?", "Life Sci."), (r"\bLIFE SCIENCES\b", "Life Sciences"), (r"\bGUID(?:ANCE)?\b\.?", "guidance"),
                 (r"\bYOY\b", "year on year"), (r"\bQOQ\b", "quarter on quarter")]


def sentence_case(s):
    """Vitti's labels are upper case. Ordinary dictionary words become lower case, acronyms (CLS, HPC, MPI, EBITDA,
    FY26) stay upper case, month abbreviations become Sep/Oct. Mixed-case text is returned as written."""
    from .spell import known, FALLBACK_COMMON
    s = s.strip()
    if not s.isupper():
        return s[:1].upper() + s[1:]
    keep = []
    for pat, rep in LABEL_PHRASES:  # expansions are written as they must read; protected from the casing below
        s = re.sub(pat, lambda m, rep=rep: (keep.append(rep), f"\x01{len(keep) - 1}\x01")[1], s)

    def fix(m):
        w = m.group(0)
        lw = w.lower()
        if any(ch.isdigit() for ch in w):
            return w
        if lw in MONTHS3:
            return w.title()
        if len(w) <= 3:
            return lw if lw in FALLBACK_COMMON else w  # AI, HPC, CLS stay; of, in, to, new, net go lower case
        return lw if (len(w) > 5 or known(lw)) and lw not in ("ebitda", "npat", "cfius", "accc", "firb") else w
    out = re.sub(r"[A-Za-z][A-Za-z']*", fix, s)
    out = re.sub(r"\x01(\d+)\x01", lambda m: keep[int(m.group(1))], out)
    return out[:1].upper() + out[1:]


def _find(rs, k):
    for i, r in enumerate(rs):
        for seg in segments(r):
            if key(join(seg)).startswith(k):
                return i, seg[0].x0
    return None, None


def _columns(rs, starts):
    """Assign each word of rs to the column whose start is the last one at or left of it; return text per column."""
    cols = [[] for _ in starts]
    for r in rs:
        line = [[] for _ in starts]
        for w in r:
            idx = max(i for i, s in enumerate(starts) if w.x0 >= s - 3) if w.x0 >= starts[0] - 3 else 0
            line[idx].append(w)
        for i, ws in enumerate(line):
            if ws:
                cols[i].append(join(ws))
    return cols


def _numbered(ws, x_lo, x_hi, y_lo, y_hi):
    """Numbered list in one column: each item is anchored on its number glyph; its text is every word in the column
    from just above that number down to just above the next one (Vitti sets the number 3pt below its text line)."""
    col = [w for w in ws if x_lo - 3 <= w.x0 < x_hi and y_lo < w.y0 < y_hi]
    nums = sorted((w for w in col if re.fullmatch(r"[1-9]", w.t)
                   and not any(o is not w and abs(o.y0 - w.y0) < 6 and o.x1 < w.x0 for o in col)), key=lambda w: w.y0)
    items = []
    for i, n in enumerate(nums):
        top = n.y0 - 6
        bottom = nums[i + 1].y0 - 6 if i + 1 < len(nums) else y_hi
        body = [w for w in col if w is not n and top <= w.y0 < bottom and w.x0 > n.x1]
        text = " ".join(join(r) for r in rows(body))
        if text.strip():
            items.append(re.sub(r"\s+", " ", text).strip())
    return items


def parse(pdf, company):
    ws = words(pdf)
    rs = rows(ws)
    d = {"headline": None, "kpis": [], "chart": None, "drivers": [], "changes": [], "timeline": [], "risks": [],
         "view": None, "source": None}
    ci = next((i for i, r in enumerate(rs) if join(r).strip().lower() == company.lower()), None)
    i_drv, x_drv = _find(rs, "WHATMAYHAVEDRIVENTHEMOVE")
    i_chg, x_chg = _find(rs, "WHATCHANGESNOW")
    i_how, _ = _find(rs, "HOWWEGOTHERE")
    i_risk, _ = _find(rs, "KEYRISKSREMAINING")
    i_view = next((i for i, r in enumerate(rs) if join(r).startswith("Vitti view:")), None)
    i_src = next((i for i, r in enumerate(rs) if join(r).startswith("Source:")), None)
    if ci is None or i_drv is None:
        return d
    found = sorted(i for i in (i_drv, i_how, i_risk, i_view, i_src) if i is not None)

    def end_of(i):
        """A section runs to the next section heading that is present (sections can be missing)."""
        return next((j for j in found if j > i), len(rs))
    d["headline"] = join(rs[ci + 1]).strip() if ci + 1 < i_drv else None

    # KPI tiles: the first row after the headline with 3+ tiles, labels on the next row with the same tile positions
    chart_rows = []
    for k in range(ci + 2, i_drv - 1):
        vals, labels = segments(rs[k]), segments(rs[k + 1])
        if len(vals) >= 3 and len(labels) == len(vals) and all(abs(a[0].x0 - b[0].x0) < 8 for a, b in zip(vals, labels)):
            d["kpis"] = [{"value": join(v), "label": join(l)} for v, l in zip(vals, labels)]
            chart_rows = rs[k + 2:i_drv]
            break

    # Chart: single-series only; every period gets exactly one value
    if chart_rows:
        title = join(chart_rows[0])
        segs = [s for r in chart_rows for s in segments(r)]
        legend = [s for s in segs if s[0].x0 > 880]
        cats_row = next((r for r in chart_rows if r[0].x0 > 200 and all(re.fullmatch(r"(FY|H[12] ?FY|Q[1-4] ?FY|CY|1H|2H)?\d{2,4}", w.t) or w.t in ("H1", "H2") for w in r)), None)
        clean_title = len(segments(chart_rows[0])) == 1 and all(len(t) <= 22 for t in title.split()) and " " in title
        if cats_row and len(legend) == 1 and len(chart_rows) > 2 and clean_title:
            cats = segments(cats_row, gap=12)
            vals = [s for r in chart_rows for s in segments(r) if s[0].x0 > 200 and s[0].x0 < 880 and r is not cats_row
                    and re.fullmatch(r"\$?\d[\d,]*(\.\d+)?[mMbB%]?", join(s))]
            mid = lambda s: (s[0].x0 + s[-1].x1) / 2
            pairs = {}
            for v in vals:
                c = min(cats, key=lambda c: abs(mid(c) - mid(v)))
                pairs.setdefault(join(c), []).append(join(v))
            sub = join(chart_rows[1]) if len(chart_rows) > 1 else ""
            foot_i = next((i for i, r in enumerate(chart_rows) if r is cats_row), None)
            foot = join(chart_rows[foot_i + 1]) if foot_i is not None and foot_i + 1 < len(chart_rows) else ""
            if pairs and all(len(v) == 1 for v in pairs.values()) and len(pairs) == len(cats):
                d["chart"] = {"title": sentence_case(title), "subtitle": sub, "series": join(legend[0]),
                              "points": [(join(c), pairs[join(c)][0]) for c in cats], "footnote": foot}

    # Numbered lists in two columns
    y_lo = rs[i_drv][0].y1
    y_hi = rs[end_of(i_drv)][0].y0 - 2 if end_of(i_drv) < len(rs) else 10_000
    split = x_chg - 30 if x_chg else 10_000
    d["drivers"] = _numbered(ws, 0, split, y_lo, y_hi)
    d["changes"] = _numbered(ws, split, 10_000, y_lo, y_hi) if x_chg else []

    # Timeline: date row defines the columns
    tl = rs[i_how + 1:end_of(i_how)] if i_how is not None else []
    if tl:
        date_row = tl[0]
        starts, dates = [], []
        for s in segments(date_row, gap=12):
            t = join(s)
            if DATE_RE.match(t):
                starts.append(s[0].x0); dates.append(t)
        if starts:
            cols = _columns(tl[1:], starts)
            d["timeline"] = [{"date": dt, "text": " ".join(c).strip()} for dt, c in zip(dates, cols) if " ".join(c).strip()]

    # Key risks: heading row defines the columns
    rk = rs[i_risk + 1:end_of(i_risk)] if i_risk is not None else []
    if rk:
        heads = segments(rk[0])
        starts = [h[0].x0 for h in heads]
        cols = _columns(rk[1:], starts)
        d["risks"] = [{"head": join(h), "text": " ".join(c).strip()} for h, c in zip(heads, cols) if " ".join(c).strip()]

    if i_view is not None:
        end = end_of(i_view) if end_of(i_view) < len(rs) else i_view + 1
        d["view"] = " ".join(join(r) for r in rs[i_view:end]).replace("Vitti view:", "", 1).strip()
    if i_src is not None:
        lines = []
        for r in rs[i_src:]:
            t = join(r)
            if t.startswith("Daily Mover Snapshot") or t.startswith("General information"):
                break
            lines.append(t)
        d["source"] = " ".join(lines).replace("Source:", "", 1).strip()
    return d
