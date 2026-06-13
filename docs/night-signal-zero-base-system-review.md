# NIGHT SIGNAL Zero-Base System Review

Checked on 2026-06-13 JST.

## Verdict

Yes for the current lightweight architecture, with one operational condition:
the 18:00 JST automation must complete the actual evening live collection.
Static plans and morning state no longer count as final publication evidence.

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
- reviewed research import requires explicit per-URL checks and can no longer
  mark every configured seed as observed;
- all ten categories include Web, X/SNS, and YouTube routes;
- watch-topic completeness is proved by candidates or URL-backed topic checks,
  not by fabricated near-miss candidates;
- recent verified non-adopted findings remain visible as compact confirmation
  signals;
- final deploy requires an evening-fresh manifest and GitHub Pages deploys only
  committed state;
- `scripts/simulate_ai_collection_redesign.py` reports no current lightweight
  limit blockers;
- existing self-tests still pass.

Deferred after review:

- raw image results and `search_content_types`, because visual evidence is not
  yet a cross-category publication requirement;
- split filtered/unfiltered search calls, because explicit raw-source
  verification now closes the evidence gap without doubling every sweep;
- Batch, Agents SDK, file-search memory, and broad connector orchestration,
  because the deterministic 40-sweep path is simpler and has not yet shown a
  measured recall limit.

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

## Policy Debt

`details/policy.html` is operationally heavy and historically additive. It
contains many valid guardrails, so replacing it wholesale immediately before a
publication window would create avoidable regression risk.

The current invariants are now stated explicitly:

- collect broadly before writing;
- model human editorial cognition inside existing state;
- preserve raw source traces;
- publish only evidence-backed adopted decisions;
- reject stale fallback publication;
- learn after publication.

Historical incident rules remain in `config/night_signal_guardrails.json`.
Further editorial shortening of the HTML policy is non-blocking cleanup, not a
missing runtime control.

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
6. Bounded background extended research is implemented in the collector;
   dedicated Deep Research report generation remains deferred because it is not
   needed for the daily publication path.

## Correct Next Move

Run the evening collection through the strengthened contracts, inspect a sample
of misses and source traces, then publish only after the full local gate chain.
Add heavier technology only when that real run identifies a measured recall or
latency limit.

## Verification Performed

Commands run:

```text
python3 scripts/night_signal_state.py --self-test
python3 scripts/night_signal_collect.py --self-test
python3 scripts/night_signal_synthesize.py --self-test
python3 scripts/night_signal_import_research.py --self-test
python3 scripts/night_signal_eval.py --self-test
python3 scripts/night_signal_publish.py --self-test
python3 scripts/guardrail_inventory.py
python3 scripts/publication_schedule_audit.py
python3 scripts/simulate_ai_collection_redesign.py 2026-06-13 --fail-on-weakness
python3 scripts/simulate_quality_gate_failures.py
python3 scripts/night_signal_state.py --validate-issue state/2026-06-12/issue.json
python3 scripts/night_signal_publish.py 2026-06-13 --deploy-existing
PYTHONPYCACHEPREFIX=/tmp/night-signal-pycache python3 -m py_compile scripts/*.py
git diff --check
```

Results:

- all state, collector, synthesizer, importer, evaluator, publisher, guardrail,
  schedule, and failure-injection tests passed;
- the 40-topic, 160-slot, all-category Web/X/YouTube simulation passed;
- the saved 2026-06-12 issue remains valid under its legacy contract;
- the stale pre-redesign 2026-06-13 issue is correctly rejected because it
  lacks collection completion provenance;
- `git diff --check` passed;
- no core lightweight collection blocker remains before the evening live run.
