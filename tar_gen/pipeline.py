"""Write -> check -> render -> verify loop for one verified Vitti package. Fails closed: GenError unless every check passes."""
import os, subprocess, sys

from .caption import build_caption
from .checks import check_report, sanitize
from .common import BAD, GenError, TOOLS, file_stem, long_date
from .render import render, visual_check


def clean_title(ident, title):
    return f"{ident.company} (ASX: {ident.ticker}) - {title}"


def _layout_feedback(layout):
    out = []
    for page, bottom, top in layout["overflow"]:
        over = round(bottom - top + 10)
        where = ("lede, facts, context or the chart" if page == 1 else "why, watch items or the TAR take")
        out.append(f"page {page} is about {over}pt too long: shorten {where} (keep every figure exact)")
    for i, c in enumerate(layout["clearance_pt"], 1):
        if c > 1012.5 - 220 - 320:
            out.append(f"page {i} has {c}pt of empty space: add useful detail from the source")
    return out


def build(ident, writer, out_dir, max_attempts=3, log=print, verbose=True):
    """Returns dict(rep, caption, title, clean_title, pdf, png, layout, attempts). Writes only into out_dir."""
    os.makedirs(out_dir, exist_ok=True)
    stem = file_stem(ident.ticker, ident.date)
    pdf, png = os.path.join(out_dir, f"{stem}.pdf"), os.path.join(out_dir, f"{stem}_cover.png")
    messages = writer.start(ident)
    last = []
    for attempt in range(1, max_attempts + 1):
        rep, content = writer.complete(messages)
        try:
            rep = sanitize(rep)
            problems = check_report(rep, ident)
        except (KeyError, TypeError, AttributeError, ValueError) as e:
            problems = [f"the JSON does not follow the schema ({type(e).__name__}: {e})"]
        cap = title = ctitle = layout = None
        if not problems:
            title = rep["title"]
            ctitle = clean_title(ident, title)
            if len(title) >= 55 or BAD.search(title):
                problems.append("title must be under 55 characters")
        if not problems:
            try:
                cap = build_caption(rep, ident)
            except GenError as e:
                problems.append(f"caption: {e.msg}; shorten caption paragraphs or bullets")
        if not problems:
            layout = render(rep, ident, pdf, png, ctitle)
            problems += _layout_feedback(layout)
            if not problems:
                problems += visual_check(pdf, layout)
        if not problems:
            r = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "verify_clean_pdf.py"), pdf, ctitle],
                               capture_output=True, text=True)
            if r.returncode != 0 or "PASS" not in r.stdout:
                raise GenError("PDF_NOT_CLEAN", "verify_clean_pdf.py rejected the rendered PDF: "
                               + "; ".join(l.strip() for l in r.stdout.splitlines() if l.strip().startswith("-")))
            log(f"  attempt {attempt}: all content, layout and PDF checks passed")
            return {"rep": rep, "caption": cap, "title": title, "clean_title": ctitle, "pdf": pdf, "png": png,
                    "layout": layout, "attempts": attempt}
        last = problems
        # Problem texts can quote figures or names from the source: only counts go to public logs (verbose=False).
        log(f"  attempt {attempt}: {len(problems)} problem(s)" + (": " + " | ".join(problems[:6]) if verbose else ""))
        feedback = ("Your report did not pass TAR's automated checks. Fix every problem below and return the complete "
                    "corrected JSON. Keep everything that was already correct.\n- " + "\n- ".join(problems))
        messages = messages + [{"role": "assistant", "content": content}, {"role": "user", "content": feedback}]
    raise GenError("CHECKS_FAILED", f"report still failed checks after {max_attempts} attempts: " + " | ".join(last[:8]))
