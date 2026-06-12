# NIGHT SIGNAL Zero-Base System Review

Checked on 2026-06-12 JST.

## Verdict

Partially yes. The zero-base redesign has now been applied to the core
collection/synthesis path where it matters most for comprehensiveness:
task-level hypotheses, required live web search, raw source traces, prompt-cache
keys, and claim/source linkage are in code. It has not been expanded into Batch,
Deep Research, Agents SDK, or broad policy rewrites because those would add
cost and complexity before the lightweight path is exhausted.

What has been done:

- latest OpenAI AI/web-research capabilities were reviewed;
- `docs/night-signal-zero-base-ai-collection-redesign.md` defines the desired
  human-editor simulation architecture;
- `docs/night-signal-basic-design.md` points to that redesign as the more
  specific current direction;
- `scripts/night_signal_state.py` generates compact collection hypotheses and
  validates claim/source linkage for 2026-06-12 and later;
- `scripts/night_signal_collect.py` requires live web search, sends
  `prompt_cache_key`, and writes raw web-search source traces;
- `scripts/night_signal_synthesize.py` rejects material candidates whose source
  URLs are not connected to observed claim atoms;
- `scripts/simulate_ai_collection_redesign.py` reports no current lightweight
  limit blockers;
- existing self-tests still pass.

What has not been done:

- `README-night-signal.md` still describes the older
  `collection_plan -> observations -> candidates -> decisions -> issue` flow;
- `details/policy.html` still expresses the older coverage-manifest and
  operation-time policy, not the new memory/hypothesis/evidence-graph loop;
- `scripts/night_signal_collect.py` now persists raw web-search sources to
  `source_traces.jsonl`, but it does not yet persist raw image/search results;
- `scripts/night_signal_collect.py` does not yet use latest web-search controls
  such as `filters`, `external_web_access`, `return_token_budget`, or
  `search_content_types`;
- `config/night_signal_guardrails.json` does not yet encode the new failure
  classes: missing raw source traces, missing hypothesis/source intent, missing
  claim/source linkage, unbounded Deep Research, Batch result expiry, or
  cache/reuse proof;
- Batch API, background Deep Research, file-search memory, MCP/connectors, and
  Agents SDK remain design candidates, not implemented paths.

## Current System Reality

The current production architecture is:

```text
Coverage config
  -> collection_plan.json
  -> observations.jsonl
  -> candidates/decisions/cards/coverage_manifest
  -> issue.json
  -> generated HTML
  -> site sync
  -> audits
```

The efficiency-constrained zero-base architecture is:

```text
Previous issue state
  -> collection_plan with hypotheses
  -> observations with raw source traces
  -> candidates with claim/source links
  -> decisions with counter-checks
  -> issue
  -> compact learning metadata
```

Those two are now unified in the lightweight path. The present source code does
not prove that heavier external orchestration would improve the outcome.

## Policy Gap

`details/policy.html` is operationally heavy and historically additive. It
contains many valid guardrails, but it is not the clean current policy for the
new system.

The policy should be reduced to the current invariants:

- collect broadly before writing;
- model human editorial cognition inside existing state;
- preserve raw source traces;
- publish only evidence-backed adopted decisions;
- reject stale fallback publication;
- learn after publication.

Historical incident rules should stay in `config/night_signal_guardrails.json`,
not dominate reader-facing or operator-facing policy.

## Structure Gap

The repo now has one active lightweight cognition path and one deferred
orchestration layer:

- active code path: collection plan, hypotheses, observations, raw source
  traces, claim/source validation, synthesis, rendering, audits;
- deferred layer: Batch, background Deep Research, Agents SDK, and persistent
  learning metadata.

The next implementation should still avoid a parallel pipeline. It should
measure whether the implemented lightweight path fails on real collection runs
before adding heavier orchestration.

## Source-Code Gap

The most important source-code gaps are:

1. Collector evidence is better because raw web-search tool sources are now
   persisted, but raw result/image traces are still absent.
2. Search execution is stricter because live collection now requires web
   search.
3. Claim/source linkage is now validated from claim-bearing observations to
   material candidates.
4. Reuse policy is planned but not enforced by cached source state.
5. Batch and prompt-cache fields are metadata only, except `prompt_cache_key`
   is now sent.
6. Deep Research has no controlled review command or output schema.

## Correct Next Move

Do not rewrite everything at once.

The smallest honest next move is:

1. measure cached tokens and live task outcomes from real collection runs;
2. persist selected web-search/image results only for visual slots where the
   extra bytes are justified;
3. update README, policy, workflows, and guardrails around the new
   implemented state;
4. defer Batch, Deep Research, and Agents SDK until this smaller path proves
   insufficient.

This turns the zero-base design into code without creating another decorative
document layer.

## Verification Performed

Commands run:

```text
python3 scripts/night_signal_state.py --self-test
python3 scripts/night_signal_collect.py --self-test
python3 scripts/night_signal_synthesize.py --self-test
python3 scripts/guardrail_inventory.py
python3 scripts/night_signal_state.py --readiness --date 2026-06-12
git diff --check
```

Results:

- state, collector, synthesizer, and guardrail self-tests passed;
- 2026-06-12 readiness correctly blocks because current daily state is missing;
- `git diff --check` passed;
- the review found heavier-orchestration gaps, not core lightweight collection
  blockers.
