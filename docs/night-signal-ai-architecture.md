# NIGHT SIGNAL AI Architecture

## Concept

NIGHT SIGNAL is a nightly signal brief, not a category quota page or a
schedule list. The system should first find candidate changes, then decide
whether each candidate changes the reader's view, and only then render HTML.

The old design failed because ownership was split: one path generated an issue,
another path selected the issue date, another path published, and later gates
tried to detect the mismatch. The optimized design has one state machine:

1. Build the discovery frontier from the coverage contract.
2. Collect source observations.
3. Normalize candidates.
4. Decide topic value.
5. Render only adopted candidates.
6. Publish only the JST-current selected issue.

If a state is missing, the system should stop at that state with a typed
blocker. It should not create filler cards, republish yesterday, or continue to
later gates hoping they catch the issue.

## Pipeline

1. Collect direct evidence from configured source classes.
2. Normalize each candidate into structured data.
3. Evaluate topic value before article generation.
4. Render cards and detail pages only from adopted structured records.
5. Keep audits small: schema, source links, date, and publication consistency.

The schema core is exported by:

```bash
python3 scripts/night_signal_state.py --schema issue_state
python3 scripts/night_signal_state.py --frontier
python3 scripts/night_signal_state.py --coverage-state
python3 scripts/night_signal_state.py --readiness
```

Completeness means every watch topic has required observation slots, not merely
that every category has some URL. The baseline slots are:

- primary or official evidence
- independent media or data evidence
- configured social/video channels such as X or YouTube

Missing slots are blockers. A later quality gate should not be responsible for
guessing whether a source class was skipped.

Efficiency is also part of the state, not an afterthought. Each observation slot
has:

- `priority`
- `reuse_policy`
- `model_route`

High-velocity or high-impact slots are checked aggressively. Low-change sources
can reuse recent observations unless the primary source changed. Cheap
structured extractors handle routine evidence extraction; frontier reasoning is
reserved for frontier planning and ambiguous/high-impact arbitration.

## OpenAI Usage

When an OpenAI API key is available, the candidate evaluator should call the
Responses API with Structured Outputs using the schemas exported by:

```bash
python3 scripts/night_signal_state.py --schema source_observation
python3 scripts/night_signal_state.py --schema candidate
python3 scripts/topic_value_engine.py --schema
```

The model should not free-write public copy at the discovery or decision stage.
It should return only schema-valid records:

- source observations with URL, source role, channel, dates, and claim atoms
- candidate records with source URLs, material facts, change class, and counter
  evidence status
- topic decisions with adoption/rejection, topic value class, reader delta, and
  materiality basis

The deterministic fallback in `scripts/topic_value_engine.py` uses the same
schema, so rendering and audits do not change when OpenAI-backed evaluation is
enabled.

Use function calling for fetching or searching external systems, and Structured
Outputs for deciding what the evidence means. Use Agents SDK tracing when the
run is split into specialist collectors so failures show which source role or
category stopped, instead of only showing a final page-quality failure.

## Model Routing

Do not spend frontier-model tokens on every repetitive task. Route work by
state:

- Frontier planning and final arbitration: latest frontier reasoning model
  such as GPT-5.5.
- Source observation extraction: cheaper structured-output capable model.
- Candidate normalization: cheaper structured-output capable model.
- Topic value arbitration for ambiguous or high-impact candidates: frontier
  reasoning model.
- HTML rendering: no model; render from accepted JSON.

This keeps quality high where judgment matters, while avoiding the old failure
mode where more checks and more prose consume tokens without improving the
daily operating state.

## Design Rule

Freshness is an eligibility filter, not an adoption reason. A fresh schedule,
calendar row, or "no result yet" confirmation is not a public topic unless it
also carries a material change: policy, market impact, technical shift,
operational status, result, risk, or audience/business signal.

Publication workflow is intentionally narrow: code, docs, and policy changes
must not republish yesterday's selected issue. Only issue artifacts and the
issue-date marker trigger Pages publication.
