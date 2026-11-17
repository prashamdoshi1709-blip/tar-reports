"""Two-page TAR PDF and cover PNG from a validated report object.

Same engine and method as the original "TAR Renderer (Phase 3A)" tar_lib.py in Drive: WeasyPrint, the TAR base
stylesheet (810 x 1012.5 pt, Lora + Inter), inline-SVG bars that always start at zero, and a layout walk that measures
whether the body text runs into the source/footer block. The page structure follows the published reports
(masthead, meta line, headline, lede, KPI strip, optional chart, fact panel, context; page 2: why it matters,
what to watch, TAR take). Sources, attribution, disclaimer and page furniture are fixed text, never AI-written.
"""
import html, os, re, tempfile

from .common import ASSETS, GenError, long_date, run

TEAL, ORANGE, GREY, NAVY = "#2f6f6b", "#b5653a", "#b9c4c2", "#1b2733"
TONES = {"teal": "", "orange": " o", "navy": " n"}
MASTHEAD_TAG = "What happened. Why it matters. What comes next."


def e(s):
    return html.escape(s or "", quote=True)


def bars(rows, width=700, label_w=170, bar_h=22, gap=8):
    """tar_lib.bars, unchanged in behaviour: rows = [{label, values:[(value, colour, caption)]}]; bars start at zero."""
    mx = max(v for r in rows for v, _, _ in r["values"]) or 1
    plot = width - label_w - 150
    y, out = 4, []
    for r in rows:
        out.append(f'<text x="0" y="{y + bar_h * len(r["values"]) / 2 + 4}" font-size="14" font-weight="700" font-family="Lora,serif">{e(r["label"])}</text>')
        out.append(f'<line x1="{label_w}" x2="{label_w}" y1="{y}" y2="{y + (bar_h + 3) * len(r["values"])}" stroke="{NAVY}" stroke-width="1.5"/>')
        for v, col, cap in r["values"]:
            w = max(2, plot * v / mx)
            out.append(f'<rect x="{label_w}" y="{y}" width="{w:.1f}" height="{bar_h}" fill="{col}"/>')
            out.append(f'<text x="{label_w + w + 6:.1f}" y="{y + bar_h - 6}" font-size="11.5" font-weight="600">{e(cap)}</text>')
            y += bar_h + 3
        y += gap
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{y}" viewBox="0 0 {width} {y}">' + "".join(out) + "</svg>"


def kpi_class(v):
    n = len(v)
    return "" if n <= 7 else (" m" if n <= 10 else " s")


def source_lines(ident):
    d = long_date(ident.date)
    supp = (f" and the {ident.company} ASX announcement{'s' if len(ident.support) > 1 else ''} of {d} supplied with it"
            if ident.support else "")
    p1 = (f"Sources: Vitti Capital Daily Mover for {ident.company} (ASX: {ident.ticker}), {d}{supp}. "
          f"Share price moves are intraday figures as reported by Vitti, not closing prices. Company guidance and targets "
          f"are expectations, not results. TAR has summarised these sources and has not independently verified the figures.")
    p2 = (f"Sources: Vitti Capital Daily Mover, {d}{supp}. Views in the TAR take are general commentary on the "
          f"announced information. TAR has not independently verified the figures.")
    return p1, p2


def build_html(rep, ident):
    tk, d = ident.ticker, long_date(ident.date)
    src1, src2 = source_lines(ident)
    kpis = "".join(
        f'<div class="kpi"><div class="v{TONES.get(k["tone"], "")}{kpi_class(k["value"])}">{e(k["value"])}</div>'
        f'<div class="t">{e(k["label"])}</div><div class="s">{e(k["note"])}</div></div>' for k in rep["kpis"])
    chart = ""
    c = rep.get("chart") or {}
    if c.get("include") and c.get("bars"):
        rows = [{"label": b["label"], "values": [(float(b["value"]), TEAL if i == len(c["bars"]) - 1 else GREY, b["display"])]}
                for i, b in enumerate(c["bars"])]
        chart = (f'<div class="label">{e(c["label"])}</div>{bars(rows)}'
                 + (f'<div class="chartnote">{e(c["note"])}</div>' if c.get("note") else ""))
    facts = "".join(f"<p><b>{e(f['head'])}</b> {e(f['body'])}</p>" for f in rep["facts"])
    ctx_items = [f"<p><b>{e(x['head'])}</b>{e(x['body'])}</p>" for x in rep["context"]]
    half = (len(ctx_items) + 1) // 2
    ctx = f'<div class="cols two"><div>{"".join(ctx_items[:half])}</div><div>{"".join(ctx_items[half:])}</div></div>'
    why = "".join(f"<p><b>{e(x['head'])}</b>{e(x['body'])}</p>" for x in rep["why"])
    watch = "".join(f'<div class="item"><div class="n">{i}</div><div><h3>{e(x["head"])}</h3><p>{e(x["body"])}</p></div></div>'
                    for i, x in enumerate(rep["watch"], 1))
    foot = (f'<div class="foot"><div class="l"><b>{e("General information only. Not financial advice.")}</b> The Announcement Room</div>'
            f'<div class="r">{e(tk)} · PAGE {{n}} OF 2</div></div>')
    return f"""<!doctype html><html lang="en-AU"><head><meta charset="utf-8"><title>{e(rep['_clean_title'])}</title></head><body>
<div class="page"><div class="body">
<div class="topbar"><span>The Announcement Room</span><span>ASX: {e(tk)} &nbsp;|&nbsp; {e(d)}</span></div>
<div class="masthead"><div class="the">THE</div><div class="name">Announcement Room</div><div class="tag">{e(MASTHEAD_TAG)}</div></div>
<div class="meta">{e(ident.company)} (ASX: {e(tk)})<span class="d">{e(rep['topic'])}</span></div>
<h1>{e(rep['headline'])}</h1>
<p class="lede">{e(rep['lede'])}</p>
<div class="kpis">{kpis}</div>
{chart}
<div class="label">{e(rep['facts_label'])}</div>
<div class="panel facts">{facts}</div>
<div class="label">{e(rep['context_label'])}</div>
{ctx}
</div>
<div class="src">{e(src1)}</div>{foot.replace('{n}', '1')}</div>
<div class="page"><div class="body">
<div class="runhead"><div class="l">{e(ident.company)}</div><div class="r">ASX: {e(tk)}<br>{e(d)}</div></div>
<h2 class="big">Why it matters and what comes next</h2>
<div class="label">Why investors appeared to focus on it</div>
<div class="wtw">{why}</div>
<div class="label">What investors should watch</div>
{watch}
<div class="take"><div class="label">TAR take</div><p>{e(rep['take'])}</p></div>
</div>
<div class="src">{e(src2)}</div>{foot.replace('{n}', '2')}</div>
</body></html>"""


def _measure(doc):
    """tar_lib.build's layout walk: bottom of the body content vs top of the source block, per page (points)."""
    report = {"pages": len(doc.pages), "overflow": [], "clearance_pt": []}
    for i, page in enumerate(doc.pages, 1):
        foot_top, maxb = [None], [0]

        def walk(b, inside=False):
            el = getattr(b, "element", None)
            names = (el.get("class") or "").split() if el is not None else []
            if "src" in names and foot_top[0] is None:
                foot_top[0] = b.border_box_y()
            ins = inside or "body" in names
            if ins and "body" not in names and hasattr(b, "content_box_y") and isinstance(getattr(b, "height", None), (int, float)):
                maxb[0] = max(maxb[0], b.content_box_y() + b.height)
            for ch in getattr(b, "children", []) or []:
                walk(ch, ins)
        walk(page._page_box)
        ft = foot_top[0] or 0
        px_to_pt = 0.75  # WeasyPrint lays out in CSS px; 1px = 0.75pt
        if ft and maxb[0] > ft - 6:
            report["overflow"].append((i, round(maxb[0] * px_to_pt, 1), round(ft * px_to_pt, 1)))
        report["clearance_pt"].append(round((ft - maxb[0]) * px_to_pt, 1))
    return report


def render(rep, ident, out_pdf, out_png, clean_title):
    try:
        from weasyprint import HTML, CSS
        from weasyprint.text.fonts import FontConfiguration
    except ImportError as ex:  # pragma: no cover
        raise GenError("DEPENDENCY", f"WeasyPrint is not installed ({ex})")
    rep = dict(rep, _clean_title=clean_title)
    fc = FontConfiguration()  # required for the bundled @font-face fonts (Lora, Inter) to be used and embedded
    doc = HTML(string=build_html(rep, ident), base_url=ASSETS).render(
        stylesheets=[CSS(filename=os.path.join(ASSETS, "tar_base.css"), font_config=fc)], font_config=fc)
    layout = _measure(doc)
    doc.metadata.title = clean_title
    doc.metadata.authors = ["The Announcement Room"]
    doc.metadata.description = None
    doc.metadata.keywords = []
    doc.metadata.generator = "The Announcement Room"
    doc.write_pdf(out_pdf)
    with tempfile.TemporaryDirectory() as t:
        run("pdftoppm", "-r", "70", "-f", "1", "-l", "1", "-png", "-singlefile", out_pdf, os.path.join(t, "c"))
        os.replace(os.path.join(t, "c.png"), out_png)
    return layout


def visual_check(pdf, layout, min_fill_pt=320):
    """Automated visual check (replaces the manual look the routines used to do). Fails closed on:
    any page not exactly 2, body text running into the source/footer block, or a page that is mostly empty."""
    problems = []
    if layout["pages"] != 2:
        problems.append(f"{layout['pages']} pages, expected 2")
    for p, bottom, top in layout["overflow"]:
        problems.append(f"page {p} body text reaches {bottom}pt, source block starts at {top}pt (overflow)")
    for i, c in enumerate(layout["clearance_pt"], 1):
        if c > 1012.5 - 220 - min_fill_pt:
            problems.append(f"page {i} is mostly empty ({c}pt of blank space above the sources)")
    txt = re.sub(r"\s+", "", run("pdftotext", "-layout", pdf, "-").stdout).lower()  # letter-spaced labels: compare without spaces
    for must in ("ANNOUNCEMENT ROOM", "Why it matters and what comes next", "General information only. Not financial advice.",
                 "Vitti Capital Daily Mover"):
        if re.sub(r"\s+", "", must).lower() not in txt:
            problems.append(f"rendered PDF text lacks {must!r}")
    return problems
