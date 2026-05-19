# NIGHT SIGNAL handoff for 2026-05-21 night

## Current state

- Do not push only the 2026-05-19 repair by itself after 2026-05-20 JST. The GitHub Pages workflow computes today's JST date and requires `night-brief-web-sample-YYYY-MM-DD.html` for that date.
- The 2026-05-19 repair is locally implemented and validated.
- The root prevention work now checks both presentation quality and collection evidence.
- A thread heartbeat exists for 2026-05-21 21:00 JST.
- User cannot issue PC-side Codex instructions until after 2026-05-21 22:00 JST, so the release must proceed autonomously before that.
- A standalone local cron automation exists for 2026-05-21 20:30 JST:
  - `night-signal-5-21-2`
  - Purpose: run the daily Web/SNS/X/YouTube collection, generate the current JST issue, run all gates, then commit/push only if the current issue passes.
- A backup local cron automation exists for 2026-05-21 21:45 JST:
  - `night-signal-5-21-3`
  - Purpose: check whether the 20:30 automation completed; if not, repair missing daily issue content, rerun all gates, commit/push, and verify the public URL without waiting for user input.

## Implemented prevention

- Detail pages are overview-only: `30秒概要` plus `原文確認`.
- Extra body sections after the overview fail the quality gate.
- Detail pages with too many source links fail; use at most 4 directly relevant links.
- Different topics must use different cards and different detail pages.
- Card titles and detail page title/h1/summary must align.
- Production/process wording in reader-facing copy fails.
- `coverage-manifest` now requires:
  - `published_card_titles`
  - `new_or_changed_items`
  - `no_change_checks`
  - `search_axes`
  - `search_terms`
  - source classes across Web / SNS/X / YouTube / data / schedule / counter-search
- Each `new_or_changed_items` entry must match a published card title and include Japanese summary plus URL sources.
- Those URL sources must overlap the linked detail page's `原文確認` links.

## Verified today

Run from repo root:

```bash
python3 scripts/coverage_audit.py 2026-05-19
python3 scripts/quality_gate.py 2026-05-19
python3 scripts/pre22_audit.py 2026-05-19
python3 scripts/simulate_quality_gate_failures.py
PYTHONPYCACHEPREFIX=/private/tmp/night-signal-pycache python3 -m py_compile scripts/coverage_audit.py scripts/quality_gate.py scripts/pre22_audit.py scripts/simulate_quality_gate_failures.py scripts/sync_site.py scripts/render_detail.py
git diff --check
```

All passed before this handoff was written.

## Tomorrow night workflow

1. Confirm the JST issue date.
2. Search Web, SNS/X, and YouTube for every category and every configured axis in `config/night_signal_coverage.json`.
3. For each category, decide:
   - new or changed items to publish
   - no-change checks
   - held / excluded / unresolved items
4. Create the daily issue for the current JST date, not a stale date.
5. Create one detail page per normal card.
6. Detail pages must contain only:
   - `30秒概要`
   - `原文確認`
7. Update `details/extraction-log-YYYY-MM-DD.html` with complete `coverage-manifest`.
8. Run:

```bash
python3 scripts/sync_site.py YYYY-MM-DD
python3 scripts/coverage_audit.py YYYY-MM-DD
python3 scripts/quality_gate.py YYYY-MM-DD
python3 scripts/pre22_audit.py YYYY-MM-DD
python3 scripts/simulate_quality_gate_failures.py
PYTHONPYCACHEPREFIX=/private/tmp/night-signal-pycache python3 -m py_compile scripts/coverage_audit.py scripts/quality_gate.py scripts/pre22_audit.py scripts/simulate_quality_gate_failures.py scripts/sync_site.py scripts/render_detail.py
git diff --check
```

9. Commit and push only after today's issue passes locally.
10. After push, verify GitHub Actions and public publication audit.

## Important risk

The current code can verify that evidence was recorded, but it still cannot prove that the entire internet had no missed update. The practical prevention is to require complete search axes, source-class evidence, explicit new/changed items, explicit no-change checks, and source overlap between extraction log and detail page.
