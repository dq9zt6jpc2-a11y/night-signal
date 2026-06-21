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

Reviewed Codex live-Web research uses:

```bash
python3 scripts/night_signal_publish.py YYYY-MM-DD --import-reviewed-bundle
```

The independent no-prompt fallback uses GitHub Models plus public Web/RSS
evidence:

```bash
GITHUB_TOKEN=... python3 scripts/night_signal_unattended_collect.py YYYY-MM-DD
python3 scripts/night_signal_import_research.py YYYY-MM-DD
```

GitHub Pages is dispatch-only. It deploys only committed evening-fresh state
after `unattended-collection.yml` or `runtime-watchdog.yml` starts it and waits
for completion:

```bash
python3 scripts/night_signal_publish.py YYYY-MM-DD --deploy-existing
```

Public verification uses the same owner:

```bash
python3 scripts/night_signal_publish.py YYYY-MM-DD --public-audit
```

The lower-level commands remain available for debugging a failed state
transition:

```bash
python3 scripts/night_signal_state.py --write-collection-plan YYYY-MM-DD
python3 scripts/night_signal_collect.py YYYY-MM-DD --replace --resume
python3 scripts/night_signal_state.py --validate-observations state/YYYY-MM-DD/observations.jsonl
python3 scripts/night_signal_synthesize.py YYYY-MM-DD --replace --resume
python3 scripts/night_signal_state.py --assemble-issue-state YYYY-MM-DD
python3 scripts/night_signal_state.py --validate-issue state/YYYY-MM-DD/issue.json
python3 scripts/night_signal_state.py --generate-issue state/YYYY-MM-DD/issue.json
python3 scripts/sync_site.py YYYY-MM-DD
python3 scripts/coverage_audit.py YYYY-MM-DD
python3 scripts/quality_gate.py YYYY-MM-DD
python3 scripts/publication_audit.py YYYY-MM-DD
```

Useful structural checks:

```bash
python3 scripts/night_signal_runtime_audit.py YYYY-MM-DD --automation-id night-signal-5-21-3
python3 scripts/simulate_runtime_failures.py
python3 scripts/night_signal_state.py --self-test
python3 scripts/night_signal_state.py --readiness --date YYYY-MM-DD
python3 scripts/simulate_quality_gate_failures.py
```

## Files That Matter

- `config/night_signal_coverage.json`: collection contract.
- `config/night_signal_sources.json`: canonical seed sources.
- `config/night_signal_guardrails.json`: recurrence-prevention inventory.
- `scripts/night_signal_state.py`: state model, generation owner, and readiness surface.
- `scripts/night_signal_collect.py`: source-observation collector using Responses
  API web search and structured output. Each completed collection slot is
  atomically checkpointed under `state/YYYY-MM-DD/collection_parts/`.
- `scripts/night_signal_synthesize.py`: source-observation synthesizer for
  candidates, decisions, cards, and coverage_manifest. Each completed category
  is checkpointed under `state/YYYY-MM-DD/synthesis_parts/`.
- `scripts/night_signal_publish.py`: the canonical 20:00 JST publication
  driver. It owns collection, synthesis, rendering, site sync, and local audits.
- `scripts/night_signal_runtime_audit.py`: runtime exhaustion classifier,
  recovery-path selector, and durable stage checkpoint owner.
- `scripts/night_signal_unattended_collect.py`: GitHub Actions fallback that
  fetches every seed source, runs broad RSS discovery for all ten categories,
  and uses GitHub Models for schema-bound extraction without Codex approval,
  Codex credits, `OPENAI_API_KEY`, or the local Mac.
- `config/night_signal_resilience.json`: token/quota/network/authentication and
  partial-execution recovery contract.
- `scripts/sync_site.py`: the only site sync path.
- `scripts/coverage_audit.py`: coverage contract audit.
- `scripts/quality_gate.py`: public issue quality audit.
- `scripts/current_issue_audit.py`: current JST issue audit.
- `scripts/publication_audit.py`: pushed/public URL audit. It does not repeat
  generation quality checks; those fail before commit in the publication driver.
- `.github/workflows/pages.yml`: dispatch-only GitHub Pages publication
  boundary.
- `.github/workflows/runtime-watchdog.yml`: background recovery orchestrator
  that dispatches unattended collection and waits for collection and Pages.
- `.github/workflows/unattended-collection.yml`: independent 18:05-19:50 JST
  collection, audit, commit, push, Pages dispatch, and Pages completion path.
- `docs/night-signal-basic-design.md`: design source of truth.

## Private Data

- Keep Safari exports, password CSVs, payment-card JSON, history JSON, and local
  `.env` files out of the repo history and out of commits.
- `.gitignore` excludes those artifacts, but they should not be treated as
  NIGHT SIGNAL inputs after `config/night_signal_sources.json` exists.

`--resume` only reuses a part when its input hash still matches. A changed
collection task, observation set, finding ledger, or category contract
invalidates the saved part automatically. Token exhaustion therefore loses at
most the currently running slot or category, not the entire daily run.

## Rules

- Do not restore date-specific rebuild scripts.
- Do not hand-edit daily HTML as the source of truth.
- Existing `issue.json` or `research_bundle.json` never skips the current
  collection. Final publication requires a collection completed at or after
  18:00 JST.
- `collection_plan.json` is generated from the coverage contract. It maps each
  semantic slot to a source role, channel, query set, reuse policy, and model
  route, plus batch group, prompt cache key, and seed source targets. Search
  queries can add sources, but they do not replace the seed source checks.
  Collection may be manual or AI-backed, but it must write the same observation
  schema.
- Responses API collection requires `OPENAI_API_KEY`. When it is unavailable,
  the local Codex automation must perform reviewed live-Web research and write
  explicit `source_checks`; it must not convert configured URLs into evidence.
- The primary collector remains Responses web search or reviewed Codex live-Web
  research. GitHub Actions also owns an independent fallback collector using
  public Web/RSS evidence and GitHub Models. It must pass the same source,
  coverage, freshness, quality, and publication contracts before committing.
- The collector keeps stable model routes in the plan. Current default concrete
  models are `gpt-5.4-mini` for structured source extraction and `gpt-5.5` for
  frontier reasoning. The synthesizer also defaults to `gpt-5.5`. Use the
  `NIGHT_SIGNAL_MODEL_*` and `NIGHT_SIGNAL_SYNTHESIS_MODEL` environment
  variables when official OpenAI model guidance changes.
- Each observation must include `source_target_results` for every seed target in
  its task, including X, Instagram, Facebook, YouTube, official, media, and data
  sources when configured. Every result includes `checked_at_jst` and
  `verification_method`; `observed_live` requires raw search trace or an
  explicit reviewed live-Web check.
- All ten categories require Web, X/SNS, and YouTube routes. A watch topic is
  complete when it has a real candidate or a direct-URL topic result. Do not
  create a near-miss candidate only to fill a topic.
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
- The top page shows adopted detail cards plus compact confirmation signals for
  verified recent non-adopted findings. Background-only, stale, generic
  no-change, and unverified items remain hidden.
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
- A run marked `IN_PROGRESS` is not evidence that an agent started. Require a
  non-null completion or durable runtime checkpoint.
- Runtime degradation order is: deploy a fresh evening issue, import a fully
  evidenced current reviewed bundle, use the Responses API, use the independent
  GitHub Models collector, otherwise block.
- Token or credit exhaustion never permits stale publication or fabricated
  source observations.
- Do not publish by falling back to an older issue.
- Do not treat schedule-only or routine items as topic value.
- Root publication shows the current issue only; dated history keeps the latest
  seven published issues.
- Do not use model names as architecture. Use model routes and resolve concrete
  models from official docs at implementation time.
- Keep temporary experiments out of the repo unless they become the canonical
  path.
