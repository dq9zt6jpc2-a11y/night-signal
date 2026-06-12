# NIGHT SIGNAL AI Collection Simulation

Checked on 2026-06-12 JST.

## Verdict

The practical collection limit for the current lightweight path has now been
reached in simulation. The system is not "perfectly exhaustive"; no automated
news collection system can prove that. But the cheap, high-signal fixes that
directly improve comprehensiveness without adding a heavier orchestration layer
are now represented in code.

It improved raw evidence auditability, forced live search, cache readiness,
task-level hypotheses, and claim/source linkage without adding a new AI call or
a parallel pipeline.

After the user's efficiency warning, the simulation target was corrected: a
separate daily `memory_snapshot -> evidence_graph` file pipeline is not treated
as required. Human-editor cognition should be compressed into existing
collection, observation, candidate, and decision state.

## Simulation Method

Added deterministic local simulation:

```text
python3 scripts/simulate_ai_collection_redesign.py 2026-06-12
```

The script does not call OpenAI or the web. It compares:

- the generated collection plan for the issue date;
- configured seed source targets;
- current collector/synthesizer/state source code;
- README, policy, and workflow structure.

The simulation asks: if the zero-base redesign is the target, which parts are
actually implemented today?

## Results

For 2026-06-12, the collection plan contains:

- 140 observation tasks;
- 316 seed source targets;
- 64 high-priority tasks;
- 76 normal-priority tasks;
- 34 reuse-candidate tasks;
- seed targets across web, SNS/X, Instagram, Facebook, and YouTube.

Potential efficiency if implemented:

- 76 of 140 tasks, or 54.29%, could be candidates for Batch execution;
- 34 of 140 tasks, or 24.29%, could be candidates for cache/reuse handling;
- prompt-cache grouping already exists as metadata in the collection plan.

Potential comprehensiveness if implemented:

- every task has seed source targets;
- every observation is required to close per-seed source target results;
- social/video source targets include SNS/X, Instagram, Facebook, and YouTube
  where configured.

Implemented capabilities found after the efficiency-constrained pass:

- seed source targets are included in generated collection tasks;
- per-seed target closure is required by the observation schema;
- the collector requests `web_search_call.action.sources`;
- live observation tasks require web search instead of leaving it optional;
- raw web-search source metadata is persisted to `source_traces.jsonl`;
- `prompt_cache_key` is sent to the Responses API;
- hypotheses are fields in `collection_plan.json`;
- material candidates must link to observed claim-bearing source URLs.

Missing capabilities found:

- raw image/search results are not requested or persisted;
- domain filters are not implemented;
- `external_web_access` is not controlled;
- `return_token_budget` is not controlled;
- image search is not enabled for visual slots;
- Batch API is not implemented.

## Re-Verification

The simulation was checked three ways:

1. `scripts/simulate_ai_collection_redesign.py` reported
   `practical_collection_limit_reached_without_heavy_orchestration`.
2. The limit assessment had no blockers.
3. Independent self-tests confirmed the production collector/state/synthesizer
   path accepts the new controls.

Supporting checks:

```text
PYTHONPYCACHEPREFIX=tmp/pycache python3 -m py_compile scripts/simulate_ai_collection_redesign.py
python3 scripts/night_signal_state.py --collection-plan --date 2026-06-12 --summary
git diff --check
```

## Weaknesses

The largest remaining weakness is token efficiency. The plan has `batch_group`,
`prompt_cache_key`, and `reuse_policy`, but they are planning metadata only.
Every live collection task still runs synchronously, one by one, without actual
Batch API execution or cache/reuse enforcement.

The second weakness is optional web-search control. Domain filters,
`external_web_access`, `return_token_budget`, and image results remain deferred
because adding them globally would increase complexity and may reduce discovery
coverage. They should be added only to targeted modes.

## Corrective Priority

Do not start with Deep Research or Agents SDK.

The first real improvement should be:

1. measure cached-token behavior from real collection responses;
2. add narrow domain-filter modes only where the source universe is known;
3. persist image `web_search_call.results` only for visual slots;
4. then evaluate Batch/prompt-cache/reuse execution.

Only after those are working should Deep Research or Agents SDK be introduced.
