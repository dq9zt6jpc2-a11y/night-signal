# NIGHT SIGNAL AI Architecture

## Concept

NIGHT SIGNAL is a nightly signal brief, not a category quota page or a
schedule list. The system should first find candidate changes, then decide
whether each candidate changes the reader's view, and only then render HTML.

## Pipeline

1. Collect direct evidence from configured source classes.
2. Normalize each candidate into structured data.
3. Evaluate topic value before article generation.
4. Render cards and detail pages only from adopted structured records.
5. Keep audits small: schema, source links, date, and publication consistency.

## OpenAI Usage

When an OpenAI API key is available, the candidate evaluator should call the
Responses API with Structured Outputs using the schema exported by:

```bash
python3 scripts/topic_value_engine.py --schema
```

The model should not free-write public copy at this stage. It should return
only the structured topic-value decision:

- `adoption_decision`
- `topic_value_class`
- `reader_delta`
- `materiality_basis`
- `reject_reason_class`
- `reject_reason`

The deterministic fallback in `scripts/topic_value_engine.py` uses the same
schema, so rendering and audits do not change when OpenAI-backed evaluation is
enabled.

## Design Rule

Freshness is an eligibility filter, not an adoption reason. A fresh schedule,
calendar row, or "no result yet" confirmation is not a public topic unless it
also carries a material change: policy, market impact, technical shift,
operational status, result, risk, or audience/business signal.
