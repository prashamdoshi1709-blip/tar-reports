#!/usr/bin/env python3
"""Caption first-line consistency check for TAR handoffs.

Rule: the first line of the (clean) caption must be exactly
    The Announcement Room | <company_name> (<TICKER>)
where company_name is the canonical full official name from the completion
marker. company_name is NEVER changed to match a caption.

Only one formatting repair is allowed: if the caption uses a shortened form S of
the company name and company_name == S + legal-form suffix (Limited, Ltd, Pty Ltd,
NL, plc, Inc, Corporation, Corp), the first line (and only that line) is
rewritten to the exact expected line. Any other difference is a FAIL.

Usage: check_caption.py <caption_file> <company_name> <TICKER> [--out <fixed_file>]
Exit 0 for OK or REPAIRED, 1 for FAIL. Prints one status line:
  CAPTION FIRST LINE OK | CAPTION FIRST LINE REPAIRED (...) | CAPTION FIRST LINE FAIL (...)
"""
import sys

PREFIX = "The Announcement Room | "
SUFFIXES = ["Limited", "Ltd", "Ltd.", "Pty Ltd", "Pty Limited", "Pty. Ltd.",
            "NL", "plc", "PLC", "Inc", "Inc.", "Corporation", "Corp", "Corp."]


def expected_line(company, ticker):
    return f"{PREFIX}{company} ({ticker})"


def check(caption, company, ticker):
    """Return (status, caption_out, message); status is OK, REPAIRED or FAIL."""
    exp = expected_line(company, ticker)
    lines = caption.split("\n")
    first = lines[0]
    if first == exp:
        return "OK", caption, exp
    tail = f" ({ticker})"
    if first.startswith(PREFIX) and first.endswith(tail):
        short = first[len(PREFIX):-len(tail)]
        if short and any(company == f"{short} {s}" for s in SUFFIXES):
            lines[0] = exp
            return "REPAIRED", "\n".join(lines), f"'{first}' -> '{exp}'"
    return "FAIL", caption, f"found '{first}', expected '{exp}'"


def main(argv):
    out = None
    if "--out" in argv:
        i = argv.index("--out")
        out = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    if len(argv) != 3:
        print(__doc__)
        return 2
    path, company, ticker = argv
    status, text, msg = check(open(path, encoding="utf-8").read(), company, ticker)
    if out and status in ("OK", "REPAIRED"):
        open(out, "w", encoding="utf-8").write(text)
    print(f"CAPTION FIRST LINE {status} ({msg})" if status != "OK" else "CAPTION FIRST LINE OK")
    return 0 if status in ("OK", "REPAIRED") else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
