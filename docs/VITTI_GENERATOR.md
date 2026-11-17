# TAR automated generator (Vitti Daily Mover to LinkedIn)

Status: built and tested offline. **Disabled** (`config/auto-publish.json` `vitti_generator.enabled=false`). Nothing runs on
schedule and nothing can publish until the switches below are turned on.

## Flow

```
Vitti email (reports@vitti.capital, ~10:47 AM)
  -> existing Apps Script import (5.2.x)          -> Drive "TAR Daily Sources/<date>_<time>_<gmailId>_a1/"   [unchanged]
  -> GitHub Actions "TAR Generate" (tar_gen/)     every 10 min 10:00-14:50 Sydney, or at once via apps-script/TarDispatch.gs
       read package (Drive, read-only) -> verify sender, DKIM, hash, ticker/company/date
       -> Claude writes the report JSON -> figure/wording/attribution checks (fed back, up to 3 attempts)
       -> two-page PDF + cover (WeasyPrint, TAR base stylesheet, Lora/Inter) -> layout + visual check -> verify_clean_pdf.py
       -> schema 4 publish.json -> the REAL tools/buffer_schedule.py run in verify mode on the result (contract check)
       -> publish mode only: commit PDF + cover + publish.json to main
  -> existing "TAR Buffer Schedule" (started by workflow_run) re-verifies everything incl. GitHub Pages, one post per day
  -> Buffer -> LinkedIn                                                                                       [unchanged]
```

Reused unchanged: the Apps Script import and its Drive packages, `tools/filing_contract.py` (schema 4),
`tools/verify_clean_pdf.py`, `tools/public_verify.py`, the TAR base stylesheet and bar-chart method from the Drive
"TAR Renderer (Phase 3A)". `tools/buffer_schedule.py` changed by one line (it accepts the `workflow_run` event) and
`buffer-schedule.yml` gained the `workflow_run` trigger. There is still exactly one Buffer publisher.

## What is checked (fail closed: any failure means no report that day)

| Check | Where |
|---|---|
| Sender is reports@vitti.capital and Gmail recorded `dkim=pass` for vitti.capital | `tar_gen/vitti.py` |
| Daily Mover sha256 equals the Apps Script record; real text layer | `tar_gen/vitti.py` |
| Ticker, company and date agree in email subject, file name, PDF metadata and PDF text; email arrived that day | `tar_gen/vitti.py` |
| Every figure in report and caption appears in the Vitti material (Daily Mover or the company announcement Vitti attached); no rounding, conversions or own calculations | `tar_gen/checks.py` |
| No other ASX code; no "draft"/"approved"; no em dashes; no clock times; no advice wording; Vitti attribution in the caption | `tar_gen/checks.py` |
| Two pages, 810 x 1012.5 pt, nothing runs into the sources/footer, no half-empty page | `tar_gen/render.py` |
| Clean PDF (title, fonts, forbidden wording in text, metadata, raw bytes) | `tools/verify_clean_pdf.py` |
| No report already exists for the day; this email / Daily Mover not used before | `tar_gen/run.py` |
| The existing publisher accepts the handoff (schema 4, caption, title, files, hashes, PDF, cover) | `tar_gen/handoff.py` |
| Then, at publication: Pages serves the same bytes, Buffer duplicate / one-per-day rules, 3:15 PM cutoff | existing publisher |

Sources, attribution ("Vitti Capital Daily Mover ... TAR has not independently verified the figures"), the disclaimer
and the caption's first line, date line and hashtags are fixed text, never AI-written. Handoffs always carry
`vitti_source.independently_verified: false`.

## Switches (`config/auto-publish.json`)

| Setting | Effect |
|---|---|
| `vitti_generator.enabled` | false: scheduled runs exit at once. true: runs every weekday |
| `vitti_generator.publish` | false: SHADOW mode, report built and verified, never committed or posted |
| `vitti_generator.rights_confirmed` | must be true to publish; set only after the owner confirms the right to republish Vitti material |
| `enabled` (top level, existing master switch) | must also be true; shared with the existing publisher |

Retries and notifications: transient problems (Drive or Anthropic outage, package not there yet) are retried by the next
scheduled run until 2:30 PM; no package by 1:00 PM, or any final failure, opens the issue
"TAR generator: no report for <date>" (GitHub emails the owner) and the run turns red. While that issue is open the
generator does not retry that date. Each outcome is also logged on the issue "TAR generator: daily log". Issues contain
reason codes only, never report content (the repository is public).

## Secrets (repository Settings > Secrets and variables > Actions)

| Secret | Needed for |
|---|---|
| `ANTHROPIC_API_KEY` | the AI writer (Claude Opus 5.5, billed per use by Anthropic; no Claude plan limits) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | reading the Drive packages (service account with Viewer on "TAR Daily Sources") |
| `TAR_REVIEW_PASSWORD` | optional: encrypted review copy of shadow reports in the run artifacts (7z, AES) |
| `BUFFER_API_KEY` | existing, unchanged |

## Tests

`python3 tools/test_tar_gen.py` runs offline (synthetic Daily Mover for a fictional company, so no Vitti content is
stored here). `--historical DIR` replays real packages kept outside the repository. The workflow's manual run offers
`offline-tests`, `check-connections` (Drive + Anthropic key, nothing generated) and `shadow`.

## Go-live checklist

1. Secrets added; manual run `check-connections` passes.
2. `enabled=true`, `publish=false`: shadow reports for a few trading days; review the encrypted copies.
3. Owner confirms in writing the right to republish Vitti Capital Daily Mover material publicly; set `rights_confirmed=true`.
4. Set `publish=true`. Disable the Claude scheduled routines that produced reports (1:15 PM / 1:58 PM / 3 PM) so they do
   not compete; the one-report-per-day rule would block a second report anyway.
