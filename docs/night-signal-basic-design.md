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
missing material changes. Reader display has two explicit depths:

- adopted material changes become full detail cards;
- verified recent non-adopted findings become compact confirmation signals with
  source date and direct URL.

Background-only, stale, generic no-change, and unverified items remain out of
the public page. This prevents an apparently empty category without lowering
the detail-card standard.

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

Every target result also records `checked_at_jst` and `verification_method`.
`observed_live` is valid only when the URL is present in the raw web-search
source trace or in an explicit reviewed live-Web check. A listed seed URL,
generic "checked" text, or registry membership is not evidence.

Every configured watch topic must have either a real candidate or a
topic-specific check with verified evidence URLs. Requiring a concrete
candidate for every topic is forbidden because it creates artificial near-miss
items when nothing changed.

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

Candidate volume, compact signal volume, and article volume are intentionally
different. The candidate ledger remains the complete review record. Recent
verified lower-priority signals may appear compactly on the public category,
while only adopted material changes receive detail pages.

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
- bounded background research only when a material ambiguity survives the
  normal sweep;
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
For the current collector implementation, the verified defaults are `gpt-5.4-mini`
for low-cost structured source extraction and `gpt-5.5` for frontier reasoning
and synthesis.
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

Official web-research technology review checked on 2026-06-11:

- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/docs/guides/deep-research
- https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- https://developers.openai.com/api/docs/guides/tools-tool-search
- https://developers.openai.com/api/docs/guides/tools-file-search
- https://developers.openai.com/api/docs/guides/batch
- https://developers.openai.com/api/docs/guides/prompt-caching
- https://developers.openai.com/api/docs/guides/latest-model
- https://developers.openai.com/api/docs/models

The 2026-06-12 zero-base AI collection redesign is now documented in
`docs/night-signal-zero-base-ai-collection-redesign.md`. It supersedes the
2026-06-11 review where it is more specific.

Adoption decision after the 2026-06-11 review:

- Keep Responses API web search as the daily collection owner. It is still the
  right primitive for slot-level collection because it can use hosted web search,
  structured outputs, bounded reasoning, and returned source metadata in one
  auditable request.
- Add raw web-search source capture before trusting collection completeness.
  The web search tool can return the full `sources` list through
  `include=["web_search_call.action.sources"]`; NIGHT SIGNAL should persist that
  tool evidence, not only the model-written observation summary.
- Use web search filters carefully. `allowed_domains` is useful for targeted
  seed-source verification, while open discovery should remain less constrained
  with only low-value `blocked_domains` where appropriate. A single filtered
  request must not replace the current design requirement that search can
  discover additional direct sources.
- Use image/text search only for categories where visual evidence is part of the
  source contract, such as product photos, venue/event assets, or social/video
  posts. It should not become the default for every slot.
- Keep extended research out of the normal daily path, but trigger a bounded
  GPT-5.5 background pass when authoritative sources conflict, all direct
  sources are inaccessible, or a potentially material outside-frontier finding
  remains unresolved. Limit the daily escalations to three and preserve the
  parent response, reason, sources, and tool trace.
- Remote MCP and OpenAI connectors are useful for authenticated or structured
  source systems, but they should enter only as observation connectors that
  write the same source-observation schema. They must not bypass the canonical
  Frontier -> Observations -> Candidates -> Decisions -> Issue -> Publication
  flow.
- Tool Search is not needed for the current small, explicit tool surface. It
  becomes useful only if NIGHT SIGNAL has many optional source connectors and
  the model must dynamically load the right one.
- Batch API and Prompt Caching fit the efficiency goal. The generated
  `batch_group` and `prompt_cache_key` fields should become real request
  parameters when collection is moved from synchronous one-by-one calls to a
  queued daily collection job.
- Model routes should be refreshed against official docs before implementation
  changes. As of the 2026-06-11 review, official docs position GPT-5.5 for
  complex reasoning/tool-heavy work and GPT-5.4 mini/nano for lower-cost
  workloads. Do not blindly replace model strings without a small eval over
  source-observation accuracy, URL evidence completeness, and token use.

The 2026-06-12 implementation adds a pre-summary findings ledger:

- every category sweep writes all useful direct-URL findings before producing
  one representative observation per slot;
- web sweeps require at least two distinct findings per watch topic and
  social/video sweeps require at least one;
- the complete daily issue requires at least three distinct URLs and two source
  role/channel combinations per watch topic across all sweeps;
- every watch topic requires multiple direct findings and a verified
  topic-specific result, but not an artificial candidate;
- every fresh or near-miss finding URL must survive into the candidate ledger;
- evaluation measures finding depth, source diversity, candidate retention,
  claim/source mapping, and collection-call reduction.

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

For the current JST issue, the final deploy path requires collection completion
at or after 18:00 JST. An issue generated in the morning cannot satisfy the
evening publish attempt without a new collection. `--force-collect` style
implicit bundle reuse is not part of the design.

The local Codex automation owns live collection, synthesis, commit, push, and
public verification. GitHub Pages owns only deployment of committed state that
passes the evening freshness contract. GitHub Actions must not pretend to
collect live data when the repository has no API credential.

No older issue may be republished because the current issue is missing.
The stable root shows the current issue. Dated archive folders are retained for
the latest seven published issues; older dated site folders are pruned by the
site sync owner, not by article generation.

Preflight may regenerate working artifacts from existing state for diagnosis.
Final publication either performs a fresh live collection or deploys a
committed issue whose manifest proves the evening collection time and mode.

### Runtime failure model

The collection model and the publication model have separate dependencies.
Codex background credits, model context/output token limits, OpenAI API quota
and rate limits, execution deadlines, network access, GitHub access, and the
local worktree can fail independently. A single "automation active" flag is
therefore not a readiness signal.

The runtime chooses one explicit path:

1. deploy an already verified fresh evening issue;
2. import a current reviewed bundle whose URLs have explicit live checks;
3. collect and synthesize through the Responses API;
4. block publication when no honest collector is available.

Every publication stage writes `runtime_checkpoint.json`. Independent GitHub
Actions monitoring fails when no current collection path exists, even if the
Codex automation database still says `IN_PROGRESS`. No degradation level may
republish an old issue or manufacture source evidence.

Stage checkpoints alone are insufficient for token or quota exhaustion during
a long model call sequence. Collection therefore writes one atomic part per
source slot, and synthesis writes one atomic part per category. `--resume`
reuses only parts whose input hash matches the current plan and evidence. A
changed task, observation, finding, or category input invalidates the part.
This bounds repeated work to the interrupted slot or category.

## 10. Current Status And Deferred Technology

The canonical owners now exist:

- `night_signal_collect.py`: Responses web search, raw source traces, findings,
  observations;
- `night_signal_synthesize.py`: candidates, decisions, cards, topic checks,
  manifest;
- `night_signal_state.py`: semantic validation and rendering;
- `night_signal_publish.py`: fresh collection or freshness-validated deploy.

All ten categories now require Web, X/SNS, and YouTube routes in addition to
official and independent/data evidence. Economic categories use official
central-bank or ministry social/video channels instead of being Web-only.

The following technologies remain deliberately deferred:

- Batch API, until synchronous live runs produce stable source-trace and token
  metrics;
- Agents SDK, until deterministic state transitions need handoff orchestration;
- image search, until a category-specific visual-evidence eval proves recall
  gain;
- domain-filtered split searches, until the extra call count beats the current
  open discovery plus explicit trace verification.

These are not unreviewed omissions. They are rejected for the current daily
path because they add branches without proven recall improvement.

Daily collection must still write structured observations, candidates,
decisions, cards, and coverage manifest before `issue.json` can be assembled.
Adding more documents or date-specific scripts does not solve collection.

## 11. Next Validation Move

The next required step is operational evidence from the evening run:

1. regenerate the current frontier and collection plan;
2. perform the full live Web/X/YouTube sweep after 18:00 JST;
3. inspect missed-source and unavailable-source samples;
4. assemble, render, and pass the full local gate chain;
5. publish and confirm both public URLs;
6. use measured misses, latency, and token data to decide whether any deferred
   technology has earned adoption.
8. publish only from the current issue state.

Everything else should either support that path or be deleted.
