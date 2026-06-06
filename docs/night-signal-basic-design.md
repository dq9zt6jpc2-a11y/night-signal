# NIGHT SIGNAL Basic Design

## 1. Mission

NIGHT SIGNAL exists to publish one current daily issue that helps the reader
notice material changes in the world before the next morning.

The mission is not to publish many cards. It is to collect broadly, decide
carefully, summarize clearly, and publish the current issue reliably.

## 2. Design Principle

Simple is best.

The system has one canonical flow:

```text
Frontier
  -> Observations
  -> Candidates
  -> Decisions
  -> Issue
  -> Publication
```

Each step owns a specific failure class. Later steps must not compensate for
missing earlier state.

| Step | Owns | Must not do |
| --- | --- | --- |
| Frontier | what to observe | write articles |
| Observations | source evidence and no-change state | decide topic value |
| Candidates | normalized change hypotheses | publish |
| Decisions | adopt/reject and reader delta | invent facts |
| Issue | render accepted decisions | add new claims |
| Publication | current public URL | fall back to old issues |

## 3. What Was Removed From The Design

The following patterns are not part of the canonical design:

- date-specific rebuild scripts;
- temporary draft-state adapters;
- phase-by-phase planning documents as operating policy;
- compatibility wrappers for old commands;
- side-channel delivery planning before daily web publication is reliable;
- model-name-first AI design;
- more checks that do not reduce the source of failure.

If any of these return, they must replace part of the canonical flow, not sit
beside it as another path.

## 4. Coverage

Coverage is defined by semantic slots, not by card count.

```text
category x watch topic x source role x channel
```

A comprehensive run follows a human editor's loop, not an additive checklist:
scan the horizon for what could have changed, form change hypotheses, verify
them across primary, independent, social, video, and data sources appropriate to
the subject, compare them with the previous state, then decide whether each
hypothesis becomes a candidate, a no-change record, or an unavailable/not
applicable slot. The loop is generic; adding a future source or category should
extend the slot contract, not create another downstream gate.

A required slot is closed only when it is:

- observed live;
- validly reused from cache;
- unavailable with a recorded reason;
- explicitly not applicable by contract.

When uncertain, keep the item as a candidate. Collection should bias toward not
missing material changes. Reader display is stricter: a public item must be an
adopted detail card inside its configured category. There is no list-only public
layer. If a fresh material item matters and has enough evidence, make it a full
detail card; if it does not, keep it in the candidate ledger with a concrete
reason.

The canonical daily state is assembled from structured files:

- `collection_plan.json`;
- `observations.jsonl`;
- `candidates.json`;
- `decisions.json`;
- `cards.json`;
- `coverage_manifest.json`.

`issue.json` is valid only when every required observation slot is closed and
every published card is backed by an adopted decision. `observations.jsonl`
alone is not a publishable state; `scripts/night_signal_synthesize.py` owns the
transition from closed observations to candidates, decisions, cards, and
coverage_manifest.

`collection_plan.json` is generated, not hand-authored. It gives each
observation slot a source role, channel, query set, reuse policy, model route,
batch group, prompt cache key, seed source targets, and acceptance rules. The
seed source targets come from `config/night_signal_sources.json`; search queries
discover additions but cannot replace official/source-target checks. This is the
handoff point for OpenAI Agents, web connectors, SNS/X, Instagram, Facebook,
YouTube checks, or manual fallback collection.

An observation is not closed merely because the task listed source targets. It
must write `source_target_results` for every seed target in the slot. This keeps
X, Instagram, Facebook, YouTube, official pages, and media/data sources from
being silently skipped inside a broad social or web check without multiplying
the number of expensive reasoning passes.

## 5. Selection

Freshness is eligibility, not value.

Publish an item only when it has:

- material facts;
- source dates;
- reference URLs;
- source authority;
- reader delta;
- adoption reason.

Routine schedules, repeated background items, and thin social reactions should
remain in observations or rejected candidates unless they change what the reader
needs to know.

Candidate volume and article volume are intentionally different. The candidate
ledger is allowed to be wider than the published card set; it is the place for
confirmed but lower-priority signals such as monthly market figures, product
minor changes, social/video operational movements, and official notices that do
not yet deserve a full detail page.

## 6. Summary

The public title and summary are rendered after the decision step.

They must be projections of accepted facts and reader delta. They must not add
new facts, process notes, internal policy language, or vague framing.

Summary quality is judged by information sufficiency, not by a target reading
time or character count. Current detail pages must expose the reader-facing
information slots needed to understand the item:

- what changed;
- why it matters;
- confirmed facts;
- limits or unknowns;
- source dates and reference URLs.

The card title should name the subject and the change in plain language. It may
be polished, but it must not become abstract editorial phrasing. The card
summary is an entry point; the detail page carries the full necessary context.
Do not publish authoring instructions, checklist language, monitoring tasks, or
selection-process notes as reader-facing copy.

The accepted candidate and the public title are separate. Cards keep
`candidate_title` for traceability to the decision, while `title` is the
reader-facing headline. This lets the issue improve wording without losing the
link back to the adopted candidate.

## 7. AI Use

Use current OpenAI technology only where it makes the canonical flow stronger:

- Responses API for tool-using workflows;
- Structured Outputs for observations, candidates, and decisions;
- Function Calling/tools for source access and cache lookup;
- Agents/tracing only for bounded workflow roles;
- Deep Research only for scheduled frontier review, not direct daily publishing;
- Batch API for asynchronous extraction/classification after source fetch;
- prompt caching and batch processing for token efficiency.

Concrete model names are not architecture. The design uses model routes:

- `small_structured_extractor`;
- `small_dedupe_or_classifier`;
- `frontier_reasoning_model`;
- `small_structured_extractor_then_frontier_reasoning_if_ambiguous`;
- `summary_contract_rewriter`;
- `deep_frontier_reviewer`.

The current concrete model for each route must be resolved from official
OpenAI docs when implementation changes.
For the current collector implementation, the verified defaults are `gpt-5-mini`
for low-cost structured source extraction and `gpt-5.2` for frontier reasoning.
They remain environment-overridable so the architecture can move with OpenAI's
model lineup without rewriting the coverage contract.

Official references checked on 2026-06-05:

- https://platform.openai.com/docs/api-reference/responses/create
- https://platform.openai.com/docs/guides/migrate-to-responses
- https://platform.openai.com/docs/guides/structured-outputs
- https://platform.openai.com/docs/models
- https://platform.openai.com/docs/guides/function-calling
- https://platform.openai.com/docs/guides/batch
- https://platform.openai.com/docs/guides/prompt-caching
- https://platform.openai.com/docs/guides/agents
- https://openai.github.io/openai-agents-python/tracing/

## 8. Efficiency

Efficiency means avoiding token waste while preserving coverage quality.

The system should not reread unchanged low-value sources with expensive models.
It should first detect updates, reuse unchanged source state, group duplicates,
and escalate only important, ambiguous, or conflicting candidates.

One daily run may take time. The unacceptable cost is repeated high-token
reasoning over unchanged or routine material.

## 9. Publication

Publication is allowed only when:

- `.night-signal-issue-date` matches the target JST issue date;
- the working sample exists;
- the dated site page exists;
- the extraction log exists in working and site locations;
- coverage and quality audits pass;
- the public root and dated URLs show the same issue date and content.

No older issue may be republished because the current issue is missing.
The stable root shows the current issue. Dated archive folders are retained for
the latest seven published issues; older dated site folders are pruned by the
site sync owner, not by article generation.

If `state/YYYY-MM-DD/issue.json` exists, preflight and publication regenerate
the working artifacts from that state before auditing. This keeps daily changes
from depending on hand-edited HTML.

## 10. Current Gap

The publication path has real safeguards. The generation owner exists in
`scripts/night_signal_state.py --generate-issue`.

The source-observation owner now exists in `scripts/night_signal_collect.py`.
It uses the Responses API web search tool and Structured Outputs to fill
`SOURCE_OBSERVATION_SCHEMA` from `collection_plan.json`. Live execution needs
`OPENAI_API_KEY`; without that credential the system can generate requests and
block readiness, but it cannot honestly claim external collection is complete.

The observation-to-publication-state owner now exists in
`scripts/night_signal_synthesize.py`. It refuses incomplete observations and
uses Structured Outputs to produce candidates, decisions, cards, and manifest
data before `issue.json` assembly.

Daily collection must still write structured observations, candidates,
decisions, cards, and coverage manifest before `issue.json` can be assembled.
Adding more documents or date-specific scripts does not solve collection.

## 11. Next Architecture Move

The next real improvement is to feed `scripts/night_signal_state.py` from
structured collection state:

1. create current frontier;
2. generate `collection_plan.json`;
3. collect source observations through `scripts/night_signal_collect.py` or a
   compatible connector that writes the same schema;
4. normalize candidates;
5. decide topic value;
6. assemble and validate `state/YYYY-MM-DD/issue.json`;
7. render the issue from accepted decisions;
8. publish only from the current issue state.

Everything else should either support that path or be deleted.
