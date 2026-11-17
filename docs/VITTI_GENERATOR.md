# TAR automated generator (Vitti Daily Mover to LinkedIn)

Status: built and tested offline. **Disabled** (`config/auto-publish.json` `vitti_generator.enabled=false`). Nothing runs on
schedule and nothing can publish until the switches below are turned on.

## Flow

```
Vitti email (reports@vitti.capital, ~10:47 AM)
  -> existing Apps Script import (5.2.x)          -> Drive "TAR Daily Sources/<date>_<time>_<gmailId>_a1/"   [unchanged]
  -> GitHub Actions "TAR Generate" (tar_gen/)     every 10 min 10:00-14:50 Sydney, or at once via apps-script/TarDispatch.gs
       read package (Drive, read-only) -> verify sender, DKIM, hash, ticker/company/date
       -> MODE B (default): deterministic report from the Daily Mover's own sections, no AI, nothing leaves GitHub
          MODE A (only if authorised): Gemini free tier writes the report JSON, falls back to MODE B on any problem
       -> figure/wording/attribution checks (fed back, up to 3 attempts)
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
| Spelling (hunspell en_AU/en_US: likely typos), repeated words, punctuation, brackets, sentence starts | `tar_gen/checks.py`, `tar_gen/spell.py` |
| Clean PDF (title, fonts, forbidden wording in text, metadata, raw bytes) | `tools/verify_clean_pdf.py` |
| No report already exists for the day; this email / Daily Mover not used before | `tar_gen/run.py` |
| The existing publisher accepts the handoff (schema 4, caption, title, files, hashes, PDF, cover) | `tar_gen/handoff.py` |
| Then, at publication: Pages serves the same bytes, Buffer duplicate / one-per-day rules, 3:15 PM cutoff | existing publisher |

Sources, attribution ("Vitti Capital Daily Mover ... TAR has not independently verified the figures"), the disclaimer
and the caption's first line, date line and hashtags are fixed text, never AI-written. Handoffs always carry
`vitti_source.independently_verified: false`.

## Writers: MODE A and MODE B ($0 either way)

| | MODE B `template` (default) | MODE A `gemini` |
|---|---|---|
| What writes the text | Fixed templates around Vitti's own sections (headline, KPI tiles, chart, drivers, what changes now, timeline, key risks, Vitti view, sources) read by `tar_gen/dailymover.py` | Google Gemini API, free tier (no billing account) |
| Cost | none | none within the free quota |
| Data sent outside GitHub | none | the Daily Mover text and attached announcements, to Google's unpaid service |
| Analysis | none added; page 2 shows Vitti's drivers, risks and the "Vitti view", labelled as Vitti's | plain-English explanation from the supplied material only |
| When it refuses | a section the report needs is missing (`INSUFFICIENT_SOURCE`) | any failure -> MODE B |

MODE A runs only when `writer_mode` is `gemini`, `gemini_data_use_authorised` is `true` and the `GEMINI_API_KEY` secret
exists. Google's Gemini API terms say content sent to unpaid services may be used to improve Google products and read by
human reviewers, and ask users not to submit confidential information; Vitti's emails say the Daily Mover is
"unreviewed and not for distribution". So keep `gemini_data_use_authorised` false unless Vitti agrees.
`gemini_models` is a preference list; the generator asks the API which models the key can call and uses the first
match, so a renamed or retired model never breaks a run (it falls back to MODE B). Quota exhaustion (429), outages,
key or model problems, safety blocks, malformed replies, or a reply that still fails the checks after 3 attempts all
fall back to MODE B. If MODE B cannot make an accurate report either, nothing is published and the reason is recorded.

## Switches (`config/auto-publish.json`)

| Setting | Effect |
|---|---|
| `vitti_generator.enabled` | false: scheduled runs exit at once. true: runs every weekday |
| `vitti_generator.publish` | false: SHADOW mode, report built and verified, never committed or posted |
| `vitti_generator.rights_confirmed` | must be true to publish; set only after the owner confirms the right to republish Vitti material |
| `enabled` (top level, existing master switch) | must also be true; shared with the existing publisher |

Retries and notifications: transient problems (Drive or Gemini outage, package not there yet) are retried by the next
scheduled run until 2:30 PM; no package by 1:00 PM, or any final failure, opens the issue
"TAR generator: no report for <date>" (GitHub emails the owner) and the run turns red. While that issue is open the
generator does not retry that date. Each outcome is also logged on the issue "TAR generator: daily log". Issues contain
reason codes only, never report content (the repository is public).

## Publishing gate in the existing publisher

`tools/buffer_schedule.py` recognises an automated handoff (it carries `generator.name = "tar_gen"`, or the Drive
package reference only the generator writes) and, in scheduled and dryrun modes, refuses it unless
`vitti_generator.enabled`, `.publish` and `.rights_confirmed` are all true, in addition to every existing check.
Manual and legacy handoffs (schemas 2, 3 and hand-made schema 4) are unaffected. Verify mode stays open because the
generator's shadow contract check uses it. `tar_gen/run.py` applies the same rule before it commits anything.

## Confidentiality (public repository)

- Shadow runs never commit, never upload artifacts or caches, and delete their output; report files never leave the
  runner. Nothing is committed to GitHub until publication is switched on and every check has passed.
- Logs, step summaries and issues carry dates, reason codes and hashes only: no company, ticker, figures or text
  before publication. Detailed check problems are logged only outside GitHub Actions. An unexpected error in a public
  run is reported by its type only (no traceback).
- Drive access is read-only (`drive.readonly`). Gemini is off and refuses to run without written authorisation.
- The optional Apps Script dispatcher sends no package details to GitHub.
- Residual risk: anyone with write access to the repository can change the workflows; keep collaborators to the owner.

## Secrets (repository Settings > Secrets and variables > Actions)

| Secret | Needed for |
|---|---|
| `GEMINI_API_KEY` | optional, MODE A only: a free Google AI Studio key (no billing account) |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | reading the Drive packages (service account with Viewer on "TAR Daily Sources") |
| `BUFFER_API_KEY` | existing, unchanged |

## Tests

`python3 tools/test_tar_gen.py` runs offline (a synthetic Daily Mover for a fictional company in Vitti's exact layout,
so no Vitti content is stored here; Gemini is tested against a local mock server: success, 429 quota, 500 outage,
unknown model, bad JSON, invented figures, safety block, bad key, no authorisation, no key). `--historical DIR` replays real packages kept outside the repository. The workflow's manual run offers
`offline-tests`, `check-connections` (Drive, plus the Gemini key with a synthetic prompt if one is set; nothing
generated) and `shadow`. In GitHub Actions the logs, step summary and issues carry dates, reason codes and hashes only.

## Go-live checklist

1. `GOOGLE_SERVICE_ACCOUNT_JSON` secret added; manual run `check-connections` passes. (MODE B needs nothing else.)
2. `enabled=true`, `publish=false`: shadow reports for a few trading days (each day's outcome is logged on the
   "TAR generator: daily log" issue; no report copies are kept on GitHub).
3. Owner confirms in writing the right to republish Vitti Capital Daily Mover material publicly; set `rights_confirmed=true`.
4. Set `publish=true`. Disable the Claude scheduled routines that produced reports (1:15 PM / 1:58 PM / 3 PM) so they do
   not compete; the one-report-per-day rule would block a second report anyway.

## Pre-merge real-data test

The "TAR Tests" workflow's `drive-shadow` job runs on pull requests once `GOOGLE_SERVICE_ACCOUNT_JSON` exists: it checks
the Drive connection, then builds the newest real Vitti package (last 10 days) in MODE B through every check and the
real publisher in verify mode, logs codes and hashes only, and deletes the output. Until the secret exists it skips.

