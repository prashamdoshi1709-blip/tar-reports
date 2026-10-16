#!/usr/bin/env python3
"""Fail-closed check that a TAR PDF is publication-clean.
Usage: verify_clean_pdf.py <pdf> <expected_title_or_-> [--expect-dirty]
Exit 0 only if the PDF has exactly 2 pages of 810 x 1012.5 pt and no NOT APPROVED / DRAFT wording
in page text (any page, also with spaces removed, so letter-spaced banners are caught),
Info dictionary, XMP metadata, or raw/decompressed file bytes. Prints sha256."""
import subprocess, sys, re, hashlib, os, tempfile
pdf = sys.argv[1]; expect_dirty = '--expect-dirty' in sys.argv
BAD = re.compile(r'not\s*approved|approved\s*for\s*publication|draft', re.I)
def run(*a):
    return subprocess.run(a, capture_output=True, text=True, errors='replace').stdout
fails = []
info = run('pdfinfo', pdf) + '\n' + run('pdfinfo', '-meta', pdf)
m = re.search(r'Pages:\s+(\d+)', info); pages = int(m.group(1)) if m else 0
if pages != 2: fails.append(f'pages={pages}, expected 2')
m = re.search(r'Page size:\s+([\d.]+) x ([\d.]+) pts', info)
if not m or abs(float(m.group(1))-810) > 0.6 or abs(float(m.group(2))-1012.5) > 0.6:
    fails.append(f'page size {m.groups() if m else None}, expected 810 x 1012.5')
for p in (1, 2):
    t = run('pdftotext', '-f', str(p), '-l', str(p), '-layout', pdf, '-')
    if BAD.search(t) or BAD.search(re.sub(r'\s+', '', t)): fails.append(f'page {p} text contains forbidden wording')
    if '—' in t: fails.append(f'page {p} contains an em dash')
if BAD.search(info): fails.append('Info/XMP metadata contains forbidden wording (title/subject/keywords/author/XMP)')
with tempfile.TemporaryDirectory() as d:
    q = os.path.join(d, 'q.pdf')
    subprocess.run(['qpdf', '--qdf', '--object-streams=disable', '--stream-data=uncompress', pdf, q], capture_output=True)
    raw = open(q, 'rb').read() if os.path.exists(q) else open(pdf, 'rb').read()
    text_raw = raw.decode('latin-1')
    for s in (text_raw, open(pdf, 'rb').read().decode('latin-1')):
        if BAD.search(s): fails.append('raw file bytes contain forbidden wording (hidden text, annotations, bookmarks or metadata)'); break
fonts = run('pdffonts', pdf)
for f in ('Lora', 'Inter'):
    if f not in fonts: fails.append(f'font {f} not embedded')
if len(sys.argv) > 2 and sys.argv[2] != '-':
    m = re.search(r'^Title:\s*(.*)$', info, re.M)
    if not m or m.group(1).strip() != sys.argv[2].strip(): fails.append(f'PDF Title metadata {m.group(1) if m else None!r} != expected {sys.argv[2]!r}')
print('sha256', hashlib.sha256(open(pdf, 'rb').read()).hexdigest())
if expect_dirty:
    print('EXPECTED-DIRTY CHECK:', 'detector works (found problems)' if fails else 'DETECTOR FAILED (no problems found)'); sys.exit(0 if fails else 1)
if fails: print('FAIL'); [print(' -', f) for f in fails]; sys.exit(1)
print('PASS clean: 2 pages, 810x1012.5, no NOT APPROVED/DRAFT wording in text, metadata or raw bytes')
