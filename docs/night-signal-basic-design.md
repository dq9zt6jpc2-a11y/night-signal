# NIGHT SIGNAL basic design

## Product contract

NIGHT SIGNAL collects broadly and publishes evidence-backed important updates.
The public page keeps the established important-update format. It does not show
a candidate board, reference-information section, collection checklist, or
internal decision labels. The reader decides which published update to open.

Sparse output is a defect when supported important updates exist. Unsupported
padding is also a defect. A story must contain concrete facts from the source,
why the update matters now, and any material uncertainty supported by evidence.

## One production path

```text
coverage + sources
    -> reviewed research bundle
    -> important-update issue state
    -> HTML
    -> commit
    -> Pages
    -> public audit
```

There is one timed owner: `.github/workflows/unattended-collection.yml`.
There is one application owner: `scripts/night_signal_publish.py`.

The application owner calls these internal stages:

1. `night_signal_unattended_collect.py` fetches all configured sources and a
   broad discovery sweep for every category.
2. `night_signal_evidence.py` is the only extension boundary. It accepts
   verified or explicitly unavailable URLs and writes `research_bundle.json`.
3. `night_signal_import_research.py` is the sole story builder. It creates
   observations, important-update cards, decisions, and the coverage manifest.
4. `night_signal_state.py` validates `issue.json` and renders the issue.
5. Publication audits run before commit. `pages.yml` only deploys committed
   state, then the collection owner verifies the public root and dated URLs.

No workflow may call the collector or story builder directly. No second model
pipeline, fallback issue generator, or date-specific rebuild script is allowed.

## Schedule and retry

- 19:05 JST: collect, build, audit, commit, deploy, and verify before 20:00.
- 19:35 JST: run only when the first publication is not already verified.

The second attempt restores the latest same-date artifact. A reviewed bundle
completed at or after 19:00 JST can be reused for two hours, so a build, Git, or
Pages failure does not repeat model extraction. A bundle from an earlier date or
an earlier check window is never promoted to the current issue.

Manual runs use the same command and do not require interactive approval:

```bash
GITHUB_TOKEN=... python3 scripts/night_signal_publish.py YYYY-MM-DD
```

## State

`state/YYYY-MM-DD/` contains durable evidence and generated issue state. The
public source of truth is `issue.json`; the other records preserve evidence and
make failures diagnosable without repeating collection.

Required durable files:

- `research_bundle.json`: verified source checks and extracted updates.
- `issue.json`: complete validated issue state, including coverage provenance.
- `runtime_checkpoint.json`: stage result for retry diagnosis.

Candidate, decision, card, and manifest side files are not written. Their
validated values exist once inside `issue.json` and are never public UI sections.

## Quality boundaries

Prevent malformed stories while building them. Before commit, validate only
observable contracts:

- every configured category and topic was checked;
- every published factual claim maps to a verified source URL;
- title, summary, and detail are reader-facing and non-repetitive;
- the issue date and collection completion are current JST values;
- root, dated page, detail links, retained cards, and visible dates agree;
- no stale issue can become the latest issue.

The measurable daily targets are 100% configured-topic review, 100% seed URL
result states, 100% published-fact/source mapping, and zero invalid public links.
There is no target number of cards. Every distinct supported material cluster
is retained; a technical per-category limit exists only to bound one API call.

`simulate_quality_gate_failures.py` covers representative public breakages.
`publication_schedule_audit.py` covers the workflow boundary. There is no
inventory that merely searches code for historical complaint strings.

## Efficiency

- Fetch independent sources concurrently.
- Limit model extraction concurrency to two categories.
- Reuse only a fresh reviewed bundle after downstream failure.
- Do not run full failure simulations during daily publication.
- Do not collect after a public issue has already passed publication audit.
- Do not create chat history, daily narrative logs, or duplicate content state.
- Increase model reasoning only when a measured evaluation shows better story
  recall or factual quality.
- Use one model extraction call per category. Try a fallback model only after
  an actual request failure; do not run a separate model canary.

## Change rule

New categories extend `night_signal_coverage.json` and
`night_signal_sources.json`. They do not add a workflow, a second story builder,
or a new public section. A new search API, web agent, feed, SNS connector, image
reader, or table extractor must produce the same Evidence bundle through
`night_signal_evidence.py`; it cannot bypass the story builder. New checks
belong at the boundary where the bad state would first become possible.
