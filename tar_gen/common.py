"""Shared constants and helpers for the TAR Vitti generator (tar_gen).

Every publication rule that the existing publisher (tools/buffer_schedule.py) enforces is imported from there, not copied,
so the generator and the publisher can never disagree about file names, URLs, caption rules or forbidden wording.
"""
import hashlib, json, os, re, subprocess, sys
from datetime import date, datetime

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
ASSETS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
if TOOLS not in sys.path:
    sys.path.insert(0, TOOLS)
os.environ.setdefault("MODE", "verify")  # importing the publisher never arms it; it only acts when its own main() runs
import buffer_schedule as BS  # noqa: E402
import filing_contract as FC  # noqa: E402

SYD = BS.SYD
PAGES = BS.PAGES
DISCLAIMER = BS.DISCLAIMER          # "General information only. Not financial advice."
BAD = BS.BAD                        # not approved / approved for publication / draft
CLOSURES, EARLY_CLOSE = BS.CLOSURES, BS.EARLY_CLOSE
GENERATOR_VERSION = "1.1.0"
CONFIG_PATH = os.path.join(ROOT, "config", "auto-publish.json")


class GenError(Exception):
    """A precise, machine-readable reason why no report is produced. `transient` problems may heal on a later run."""
    def __init__(self, code, msg, transient=False):
        super().__init__(f"{code}: {msg}")
        self.code, self.msg, self.transient = code, msg, transient


def sha256_bytes(b):
    return hashlib.sha256(b).hexdigest()


def sha256_file(p):
    with open(p, "rb") as f:
        return sha256_bytes(f.read())


def long_date(d):
    """9 November 2026 (no leading zero), the format the publisher parses with %d %B %Y."""
    return f"{d.day} {d.strftime('%B %Y')}"


def file_stem(tk, d):
    """TAR_DNL_9Nov2026, exactly as tools/buffer_schedule.py builds it."""
    return f"TAR_{tk}_{d.day}{d.strftime('%b')}{d.year}"


def folder_rel(tk, d):
    return f"reports/{d.isoformat()}-{tk}"


def public_urls(tk, d):
    stem = file_stem(tk, d)
    base = f"{PAGES}/{d.isoformat()}-{tk}"
    return f"{base}/{stem}.pdf", f"{base}/{stem}_cover.png"


def is_trading_day(d):
    iso = d.isoformat()
    return d.weekday() < 5 and iso not in CLOSURES and iso not in EARLY_CLOSE


def run(*args, check=True, **kw):
    r = subprocess.run(list(args), capture_output=True, text=True, errors="replace", **kw)
    if check and r.returncode != 0:
        raise GenError("TOOL_FAILED", f"{args[0]} exited {r.returncode}: {(r.stderr or r.stdout)[-300:]}")
    return r


def load_config(path=CONFIG_PATH):
    cfg = json.load(open(path, encoding="utf-8"))
    g = cfg.get("vitti_generator")
    if not isinstance(g, dict):
        raise GenError("CONFIG", "config/auto-publish.json has no vitti_generator section")
    return cfg, g


def today_syd():
    return datetime.now(SYD).date()


def parse_iso_date(s):
    return date.fromisoformat(s)


def norm_space(s):
    return re.sub(r"\s+", " ", (s or "").replace(" ", " ")).strip()
