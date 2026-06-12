# NIGHT SIGNAL

NIGHT SIGNAL is a daily public web issue. The stable page is:

- `site/index.html`

The dated archive is:

- `site/YYYY-MM-DD/index.html`
- `site/YYYY-MM-DD/details/`

## Canonical Path

The operating path is intentionally small.

1. Collect current information using `config/night_signal_coverage.json`.
2. Generate the daily collection plan:
   - `state/YYYY-MM-DD/collection_plan.json`
3. Write structured collection state:
   - `state/YYYY-MM-DD/observations.jsonl`
   - `state/YYYY-MM-DD/candidates.json`
   - `state/YYYY-MM-DD/decisions.json`
   - `state/YYYY-MM-DD/cards.json`
   - `state/YYYY-MM-DD/coverage_manifest.json`
4. Assemble the canonical issue state:
   - `state/YYYY-MM-DD/issue.json`
5. Generate the working issue files:
   - `night-brief-web-sample-YYYY-MM-DD.html`
   - `details/extraction-log-YYYY-MM-DD.html`
   - linked detail pages in `details/`
6. Sync the issue to `site/`.
7. Keep only the latest seven dated site issues as readable history.
8. Audit coverage, quality, current date, and public publication.
9. Commit and push only when the current issue is ready.

## Commands

Normal publication uses one command:

```bash
python3 scripts/night_signal_publish.py YYYY-MM-DD
```

Preflight and public verification use the same owner:

```bash
python3 scripts/night_signal_publish.py YYYY-MM-DD --preflight
python3 scripts/night_signal_publish.py YYYY-MM-DD --public-audit
```

The lower-level commands remain available for debugging a failed state
transition:

```bash
python3 scripts/night_signal_state.py --write-collection-plan YYYY-MM-DD
python3 scripts/night_signal_collect.py YYYY-MM-DD
python3 scripts/night_signal_state.py --validate-observations state/YYYY-MM-DD/observations.jsonl
python3 scripts/night_signal_synthesize.py YYYY-MM-DD --replace
python3 scripts/night_signal_state.py --assemble-issue-state YYYY-MM-DD
python3 scripts/night_signal_state.py --validate-issue state/YYYY-MM-DD/issue.json
python3 scripts/night_signal_state.py --generate-issue state/YYYY-MM-DD/issue.json
python3 scripts/sync_site.py YYYY-MM-DD
python3 scripts/coverage_audit.py YYYY-MM-DD
python3 scripts/quality_gate.py YYYY-MM-DD
python3 scripts/pre22_audit.py YYYY-MM-DD
python3 scripts/publication_audit.py YYYY-MM-DD
```

Useful structural checks:

```bash
python3 scripts/night_signal_state.py --self-test
python3 scripts/night_signal_state.py --readiness --date YYYY-MM-DD
python3 scripts/pre22_audit.py YYYY-MM-DD
python3 scripts/simulate_quality_gate_failures.py
```

## Files That Matter

- `config/night_signal_coverage.json`: collection contract.
- `config/night_signal_sources.json`: canonical seed sources.
- `config/night_signal_guardrails.json`: recurrence-prevention inventory.
- `scripts/night_signal_state.py`: state model, generation owner, and readiness surface.
- `scripts/night_signal_collect.py`: source-observation collector using Responses
  API web search and structured output.
- `scripts/night_signal_synthesize.py`: source-observation synthesizer for
  candidates, decisions, cards, and coverage_manifest.
- `scripts/night_signal_publish.py`: the canonical 20:00 JST publication
  driver. It owns collection, synthesis, rendering, site sync, and local audits.
- `scripts/sync_site.py`: the only site sync path.
- `scripts/coverage_audit.py`: coverage contract audit.
- `scripts/quality_gate.py`: public issue quality audit.
- `scripts/current_issue_audit.py`: current JST issue audit.
- `scripts/pre22_audit.py`: pre-publication local audit.
- `scripts/publication_audit.py`: pushed/public URL audit.
- `.github/workflows/pages.yml`: GitHub Pages publication.
- `.github/workflows/preflight.yml`: scheduled readiness check.
- `docs/night-signal-basic-design.md`: design source of truth.

## Private Data

- Keep Safari exports, password CSVs, payment-card JSON, history JSON, and local
  `.env` files out of the repo history and out of commits.
- `.gitignore` excludes those artifacts, but they should not be treated as
  NIGHT SIGNAL inputs after `config/night_signal_sources.json` exists.

## Rules

- Do not restore date-specific rebuild scripts.
- Do not hand-edit daily HTML as the source of truth.
- If `state/YYYY-MM-DD/issue.json` exists, preflight and publication regenerate
  working artifacts from it before auditing.
- `collection_plan.json` is generated from the coverage contract. It maps each
  semantic slot to a source role, channel, query set, reuse policy, and model
  route, plus batch group, prompt cache key, and seed source targets. Search
  queries can add sources, but they do not replace the seed source checks.
  Collection may be manual or AI-backed, but it must write the same observation
  schema.
- Live AI-backed collection requires `OPENAI_API_KEY`. Without it, the system can
  generate collection requests and readiness blockers, but it cannot honestly
  claim external Web/SNS/YouTube collection is complete.
- The scheduled preflight checks `OPENAI_API_KEY` before the publication window
  when the current issue has not already been generated. Missing credentials are
  a blocking operations fault, not a content fallback condition.
- The collector keeps stable model routes in the plan. Current default concrete
  models are `gpt-5-mini` for structured source extraction and `gpt-5.5` for
  frontier reasoning. The synthesizer also defaults to `gpt-5.5`. Use the
  `NIGHT_SIGNAL_MODEL_*` and `NIGHT_SIGNAL_SYNTHESIS_MODEL` environment
  variables when official OpenAI model guidance changes.
- Each observation must include `source_target_results` for every seed target in
  its task, including X, Instagram, Facebook, YouTube, official, media, and data
  sources when configured.
- Coverage follows a reusable human-editor loop: hypothesize what could have
  changed, triangulate primary/independent/social/video/data evidence, compare
  with the previous state, then record candidate, no-change, unavailable, or not
  applicable. New sources should extend this loop, not add another late gate.
- `observations` alone are never publication-ready. The synthesis step must
  produce `candidates`, `decisions`, `cards`, and `coverage_manifest` before
  assembly and rendering.
- `issue.json` must include frontier, observations, candidates, decisions,
  cards, and coverage_manifest. Cards without adopted decisions, or decisions
  without closed observation slots, are invalid.
- The top page shows only adopted detail cards inside their configured
  categories. Broad capture belongs in candidates and coverage_manifest; reader
  display must not use list-only items as a substitute for details.
- Cards must keep `candidate_title` for traceability to the adopted decision and
  `title` for the reader-facing headline.
- Detail pages are not time-boxed summaries. Current details must carry
  `summary_basis` with what changed, why it matters, confirmed facts, limits or
  unknowns, and source dates, then render those as reader-facing context. New
  detail pages must preserve enough context to avoid deleting names, dates,
  numbers, source dates, limits, and uncertainty merely to keep the article
  short.
- Current issue publication must run through `scripts/night_signal_publish.py`.
  Workflow-local bash branches are not the source of truth.
- Do not add a new gate when a state transition should own the failure.
- Do not publish by falling back to an older issue.
- Do not treat schedule-only or routine items as topic value.
- Root publication shows the current issue only; dated history keeps the latest
  seven published issues.
- Do not use model names as architecture. Use model routes and resolve concrete
  models from official docs at implementation time.
- Keep temporary experiments out of the repo unless they become the canonical
  path.
