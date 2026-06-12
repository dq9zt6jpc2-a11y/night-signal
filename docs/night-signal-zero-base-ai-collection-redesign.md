# NIGHT SIGNAL Zero-Base AI Collection Redesign

Checked on 2026-06-12 JST against current official OpenAI documentation.

## 1. Conclusion

The optimal direction is not "make one bigger search prompt."

NIGHT SIGNAL should use a human-editor simulation loop, but the loop must be
compressed into the existing state path. A design that adds many daily files,
agents, or gates without reducing repeated search and review work is not an
improvement.

The cognitive loop is:

```text
Previous state
  -> collection_plan with hypotheses
  -> observations with raw source traces
  -> candidates with evidence links
  -> decisions with counter-checks
  -> issue
  -> compact learning update
```

This keeps the current canonical publication flow. Human-like editorial
cognition is represented as fields inside existing artifacts, not as a second
parallel pipeline.

The revised target is:

- add source-trace evidence to observations;
- add hypothesis and expected-source intent to collection tasks;
- add claim-to-source links to candidates and decisions;
- add compact learning metadata after publication;
- avoid adding Deep Research, Agents SDK, Batch, or extra gates until a smaller
  change proves better coverage per token and per operational branch.

## 2. Latest OpenAI Capabilities To Use

### Responses API with `web_search`

Use this as the daily observation engine.

Required usage:

- use the hosted `web_search`, not legacy `web_search_preview`;
- set `tool_choice` to required for slots that must search;
- persist `web_search_call.action.sources` for every run;
- persist `web_search_call.results` for image-capable slots;
- use `filters.allowed_domains` for seed-source verification;
- use broad search with limited `blocked_domains` for discovery;
- use `external_web_access=false` only for cache-only unchanged checks;
- use `return_token_budget=unlimited` only for high-value frontier reviews;
- use `search_content_types=["image", "text"]` for visual/event/product slots.

This directly improves both comprehensiveness and auditability. The model's
summary is no longer the only proof that a source was consulted.

### GPT-5.5

Use GPT-5.5 only for tool-heavy reasoning, ambiguity resolution, and final
editorial decision review. Official guidance says GPT-5.5 is the current model
family for complex production workflows, tool-heavy agents, and multi-step work.

Do not move every task to GPT-5.5. Low-ambiguity extraction should remain on a
cheaper structured route after evals prove accuracy is sufficient.

Model routes:

| Route | Use | Default effort |
| --- | --- | --- |
| `fast_source_probe` | seed source changed/not changed | low |
| `structured_observer` | source observation JSON | low |
| `branch_search_reasoner` | ambiguous or conflicting slot | medium |
| `frontier_editor` | what could have changed | medium/high |
| `decision_editor` | adopt/reject and reader delta | medium |
| `deep_frontier_reviewer` | periodic missed-source review | high/xhigh |

### Deep Research

Do not implement Deep Research in the current basic design. It remains a
possible later audit tool only if cheaper source-trace and evidence-link
changes fail to surface missed-source patterns.

Best uses:

- weekly or triggered missed-source discovery;
- category coverage contract redesign;
- "what are we systematically failing to notice?" reviews;
- market/science/legal-style background reports where hundreds of sources may
  be useful;
- comparing public web against private/source-registry state via file search or
  trusted MCP.

Controls:

- run in background mode;
- set `max_tool_calls`;
- log all tool calls;
- never let the final report directly become public copy;
- convert its output into proposed changes to frontier/source contracts.

### Agents SDK

Do not implement the Agents SDK in the current basic design. The current code
can own orchestration deterministically. Agents SDK is justified only if the
workflow later needs traceable handoffs that cannot be expressed in the current
state machine.

Recommended bounded roles:

- `FrontierEditor`: forms daily hypotheses from memory and category contracts;
- `SourceObserver`: executes source-plan tasks and writes observations;
- `EvidenceAuditor`: checks raw source traces and URL coverage;
- `DecisionEditor`: turns candidates into adopted/rejected decisions;
- `LearningEditor`: proposes source/frontier contract updates after publication.

Each role must write schema-bound state. Handoffs are allowed only between these
state transitions.

### Remote MCP and Connectors

Use only for trusted structured sources or private source registries.

Good fits:

- a private source registry MCP;
- a search/fetch MCP for archived source snapshots;
- calendar connectors for official schedule checks when OAuth is available;
- Google Drive/Dropbox only for user-owned private reference files.

Rules:

- prefer official or self-operated MCP servers;
- restrict tools with `allowed_tools`;
- use `defer_loading` when many tools exist;
- require approval unless the server is audited and read-only;
- never combine private MCP data and open web search in one uncontrolled step.

### File Search / Vector Stores

Do not introduce vector stores in the current basic design. Use existing prior
state JSON first. Vector stores are useful only if local state becomes too large
or too fuzzy for deterministic lookup.

Store:

- previous observations;
- prior candidates and decisions;
- known source aliases;
- stale/routine patterns;
- prior no-change reasons.

Then the daily run can ask: "what changed from the last known state?" instead
of rereading the world with no memory.

### Batch API

Do not implement Batch before source-trace persistence. Batch can lower cost,
but it also adds asynchronous failure modes and result reconciliation. It should
be adopted only after the synchronous collector can prove raw evidence capture.

Daily split:

- high-priority/current-risk slots run synchronously;
- normal slots run through Batch;
- Deep Research/frontier reviews run in background mode;
- failed or expired batch slots become explicit blockers or targeted sync
  retries.

Batch is a fit because collection is broad, repetitive, and not all results
need to be instant. It also gives lower cost and separate rate-limit headroom.

### Prompt Caching

Make caching an explicit design constraint with minimal code:

- static instructions first;
- stable schema and category contract before dynamic source content;
- dynamic issue date/source snippets last;
- use `prompt_cache_key` per slot family;
- log cached token counts;
- log cached token counts when available.

## 3. Human-Thought Simulation

The target is not human-like prose. It is human-like editorial cognition.

The efficient implementation is not one file per thought step. It is a small set
of fields attached to the existing artifacts.

### Step A: Remember

Use previous issue state directly when creating `collection_plan.json`.

Do not write `memory_snapshot.json` unless debugging an incident.

### Step B: Hypothesize

For each category, form a small set of "what might have changed" hypotheses
inside each collection task before searching.

Examples:

- "OpenAI may have shipped a model/API/product update."
- "Honda may have monthly regional production or sales updates."
- "F1/Honda may have race-week technical or schedule implications."
- "SpaceX may have launch, Starship, regulatory, or NASA mission changes."

Output: `collection_plan.json.tasks[].hypotheses`.

### Step C: Plan Sources

Convert hypotheses into existing collection tasks:

- seed official source;
- seed social/video source;
- independent/media/data source;
- broad discovery query;
- counter-query for "nothing changed" or conflicting accounts.

Output: existing `collection_plan.json`.

### Step D: Probe Cheaply

Use low-effort `web_search` or connector calls to decide whether a source
changed, is unavailable, or can be reused. This imitates a human scanning known
places before doing deep research.

Output: `observations.jsonl[].source_target_results` plus raw tool source
trace fields.

### Step E: Branch Only When Needed

Escalate only when:

- a primary source changed;
- an independent source reports a material change;
- social/video evidence suggests a new event;
- sources conflict;
- a category is unusually quiet and needs an explicit no-change proof.

Output: additional raw source traces in the same observation record, not a new
daily file.

### Step F: Build Evidence Graph

Normalize facts as claim atoms:

```text
claim -> source -> date -> authority -> confidence -> conflicts -> candidate
```

Do not let article writing happen here.

Output: claim/source link fields in candidates and decisions. A standalone
`evidence_graph.json` is useful only if this linkage becomes too large for the
existing state files.

### Step G: Decide Like An Editor

For each candidate:

- what changed;
- why it matters;
- what evidence confirms it;
- what is unknown;
- what the reader can now understand that they could not yesterday;
- adopt/reject/defer with reason.

Output: `decisions.json`.

### Step H: Learn

After publication, update:

- source reliability;
- missed-source discoveries;
- stale source patterns;
- slot requiredness;
- query patterns that found real changes;
- queries that wasted tokens.

Output: compact learning fields in `coverage_manifest.json`. A separate
`learning_update.json` is allowed only for periodic source-contract redesign,
not every daily issue.

## 4. New Minimal Architecture

Keep one canonical production flow. Do not split daily collection into many new
files.

```text
state/YYYY-MM-DD/
  collection_plan.json       # includes hypotheses and source intent
  observations.jsonl
  candidates.json
  decisions.json
  cards.json
  coverage_manifest.json
  issue.json
```

`observations.jsonl` remains the publish-blocking collection record. It should
be strengthened with raw source traces, not replaced by a wider artifact tree.

## 5. What To Remove Or Avoid

Do not build:

- one giant daily Deep Research report that becomes the issue;
- unbounded multi-agent discussion;
- a separate "AI opinion" layer;
- category quotas as a proxy for coverage;
- search-result URLs as evidence;
- model-name-first architecture;
- late gates that merely discover missing collection after the fact.

## 6. Implementation Order

1. Persist raw web-search `sources` and selected `results` alongside each
   observation.
2. Force web search only for tasks that require live observation; keep cached or
   not-applicable checks cheap.
3. Send `prompt_cache_key` and arrange request payloads for cache-friendly
   prefixes.
4. Add claim/source linkage to candidates and decisions.
5. Only after those pass simulation, evaluate Batch for normal-priority tasks.
6. Only after repeated missed-source failures, evaluate Deep Research as a
   periodic source-contract review.
7. Only after deterministic orchestration becomes unmanageable, evaluate Agents
   SDK.

## 7. Acceptance Criteria

The redesign is working only when:

- every published claim maps to source, date, and claim/source link;
- every required seed source has a raw source-trace result;
- every adopted card has a rejected/accepted candidate trail;
- no-change decisions cite checked sources;
- repeated unchanged sources consume fewer tokens than changed sources;
- Deep Research is absent from daily runs unless it has already proven net
  coverage gain per token in periodic review;
- daily publication can fail early because collection is incomplete, not
  publish stale content.

## 8. Official References Checked

- https://developers.openai.com/api/docs/guides/latest-model
- https://developers.openai.com/api/docs/guides/tools-web-search
- https://developers.openai.com/api/docs/guides/deep-research
- https://developers.openai.com/api/docs/guides/tools-connectors-mcp
- https://developers.openai.com/api/docs/guides/agents
- https://developers.openai.com/api/docs/guides/batch
- https://developers.openai.com/api/docs/guides/prompt-caching
- https://developers.openai.com/api/docs/guides/background
