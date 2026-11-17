"""Identity and integrity checks on a Vitti Daily Mover package, plus the source text and source-number set.

Checks (all must pass, otherwise GenError and no report):
  sender     SOURCE_INDEX email.sender_email is an allowed Vitti sender AND Gmail recorded dkim=pass for that domain
  identity   ticker and date agree across the email subject, the Daily Mover file name, the Daily Mover PDF metadata
             (Title "<TK> Daily Mover - <d Month YYYY>", Subject "Daily Mover: <Company> (<TK>)") and the PDF text;
             the date is the target date and the email arrived that day (Sydney)
  integrity  the downloaded Daily Mover has the sha256 recorded by the Apps Script, is a readable PDF with real text
"""
import re
from datetime import datetime

from .common import GenError, SYD, long_date, norm_space, run, sha256_file

MONTHS = "January February March April May June July August September October November December".split()
SUBJ_RE = re.compile(r"Daily Mover(?: draft)?:\s*([A-Z0-9]{2,5})\b.*\((\d{1,2} [A-Z][a-z]{2,8} \d{4})\)")
DM_NAME_RE = re.compile(r"^([A-Z0-9]{2,5})-(\d{4}-\d{2}-\d{2})-draft\.pdf$")
PDF_TITLE_RE = re.compile(r"^([A-Z0-9]{2,5}) Daily Mover\s*[—–-]\s*(\d{1,2} [A-Z][a-z]+ \d{4})$")
PDF_SUBJ_RE = re.compile(r"^Daily Mover:\s*(.+?)\s*\(([A-Z0-9]{2,5})\)$")
NUM_RE = re.compile(r"(?<![A-Za-z0-9.])(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?")


def _parse_day(s):
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise GenError("IDENTITY", f"unparseable date {s!r}")


def collapse_spaced(text):
    """Vitti's PDF letter-spaces labels ("$ 5 . 7 3 0 · A S AT 1 0 : 2 5"); join runs of single characters."""
    return re.sub(r"(?<!\S)(?:\S ){2,}\S(?!\S)", lambda m: m.group(0).replace(" ", ""), text)


def numbers(text):
    """Every number in a text as a normalised float (commas removed). Tokens glued to letters (FY27, H1, Q3) are labels."""
    out = set()
    for m in NUM_RE.finditer(text):
        whole = m.group(1).replace(",", "")
        v = float(whole + ("." + m.group(2) if m.group(2) else ""))
        out.add(round(v, 6))
    return out


def pdf_text(path, layout=True):
    r = run("pdftotext", *(["-layout"] if layout else []), path, "-", check=False)
    return r.stdout if r.returncode == 0 else ""


def pdf_meta(path):
    info = run("pdfinfo", path, check=False).stdout
    meta = {}
    for line in info.splitlines():
        if ":" in line:
            k, v = line.split(":", 1)
            meta[k.strip()] = v.strip()
    return meta


class Identity(dict):
    __getattr__ = dict.get


def verify_package(pkg, target, gen_cfg):
    idx = pkg.index
    checks = {}
    em = idx.get("email") or {}
    dm = idx.get("daily_mover") or {}

    # ---- sender (Gmail recorded the DKIM result; the Apps Script copied it into SOURCE_INDEX)
    allowed = [s.lower() for s in gen_cfg.get("allowed_senders", [])]
    sender = (em.get("sender_email") or "").lower()
    dkim_dom = gen_cfg.get("dkim_domain", "vitti.capital")
    auth = em.get("authentication_results") or ""
    if idx.get("import_mode") != "VITTI":
        raise GenError("NOT_VITTI", f"package import_mode is {idx.get('import_mode')!r}, not VITTI")
    if sender not in allowed:
        raise GenError("SENDER", f"sender {sender!r} is not an allowed Vitti sender")
    if not re.search(rf"dkim=pass header\.i=@{re.escape(dkim_dom)}\b", auth):
        raise GenError("DKIM", f"no dkim=pass for @{dkim_dom} in the recorded authentication results")
    checks["vitti_sender_verified"] = True

    # ---- integrity of the Daily Mover file
    if dm.get("status") != "found":
        raise GenError("NO_DAILY_MOVER", "package has no Daily Mover PDF")
    got = sha256_file(pkg.daily_mover_path)
    if got != dm.get("sha256"):
        raise GenError("DM_HASH", "downloaded Daily Mover sha256 differs from SOURCE_INDEX")
    layout = pdf_text(pkg.daily_mover_path)
    raw = pdf_text(pkg.daily_mover_path, layout=False)
    meta = pdf_meta(pkg.daily_mover_path)
    if len(norm_space(layout)) < 600 or meta.get("Pages") not in ("1", "2"):
        raise GenError("DM_UNREADABLE", "Daily Mover PDF has no usable text layer or an unexpected page count")
    checks["vitti_pdf_readable"] = True

    # ---- identity: ticker, company and date must agree everywhere
    m_subj = SUBJ_RE.search(em.get("subject") or "")
    m_name = DM_NAME_RE.match(dm.get("name") or "")
    m_title = PDF_TITLE_RE.match(meta.get("Title", ""))
    m_psubj = PDF_SUBJ_RE.match(meta.get("Subject", ""))
    if not (m_subj and m_name and m_title and m_psubj):
        raise GenError("IDENTITY", "could not read ticker/date from the email subject, file name and PDF metadata "
                       f"(subject={bool(m_subj)} name={bool(m_name)} pdf_title={bool(m_title)} pdf_subject={bool(m_psubj)})")
    tickers = {m_subj.group(1), m_name.group(1), m_title.group(1), m_psubj.group(2)}
    dates = {_parse_day(m_subj.group(2)), datetime.strptime(m_name.group(2), "%Y-%m-%d").date(), _parse_day(m_title.group(2))}
    if len(tickers) != 1:
        raise GenError("IDENTITY", f"ticker disagreement {sorted(tickers)}")
    if len(dates) != 1:
        raise GenError("IDENTITY", f"date disagreement {sorted(str(x) for x in dates)}")
    tk, d = tickers.pop(), dates.pop()
    if d != target:
        raise GenError("STALE_PACKAGE", f"Daily Mover is dated {d}, not {target}")
    recv = em.get("received_at")
    if not recv or datetime.fromisoformat(recv).astimezone(SYD).date() != d:
        raise GenError("IDENTITY", "email was not received on the Daily Mover date (Sydney)")
    if "vitti capital" not in meta.get("Author", "").lower():
        raise GenError("IDENTITY", "Daily Mover PDF author is not Vitti Capital")
    company = norm_space(m_psubj.group(1))
    flat = collapse_spaced(layout)
    if f"ASX:{tk}" not in flat.replace(" ", "") or company.lower() not in norm_space(layout).lower():
        raise GenError("IDENTITY", "Daily Mover text does not carry the same ticker and company as its metadata")
    if long_date(d).lower() not in norm_space(layout).lower():
        raise GenError("IDENTITY", "Daily Mover text does not carry its own date")
    checks["company_date_match"] = True

    support = []
    for name, p in pkg.today_docs:
        t = pdf_text(p)
        if len(norm_space(t)) > 200:
            support.append((name, t))
    corpus = "\n".join([layout, flat, raw, collapse_spaced(raw)] + [collapse_spaced(t) for _, t in support])
    return Identity(ticker=tk, company=company, date=d, subject=em.get("subject"), sender=sender,
                    gmail_id=em.get("gmail_message_id"), rfc822=em.get("rfc822_message_id"), dm_sha=got,
                    dm_name=dm.get("name"), dm_text=flat, support=support, source_numbers=numbers(corpus),
                    source_text=norm_space(corpus).lower(), checks=checks)
