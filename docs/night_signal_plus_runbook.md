# NIGHT SIGNAL Plus owner runbook

## Objective and fixed priorities

Publish the current JST issue automatically every evening. The priority order is:

1. coverage of every configured category and watch topic;
2. evidence grounding, novelty precision, and complete Japanese summaries;
3. token and runtime efficiency without weakening 1 or 2;
4. no charge beyond the user's existing ChatGPT Plus subscription.

GitHub Actions owns web Evidence collection only. The Codex automation included
with ChatGPT Plus owns one compact editorial review, validation, commit, and Pages
publication. Never call GitHub Models, the OpenAI API, Copilot credits, or another
paid AI service.

## Start gate

Work only in `/Users/shimadatakashi/Documents/Codex/2026-05-10/gpt`.

1. Set `ISSUE_DATE` to today's JST date.
2. Run `git fetch origin main` and `git rebase origin/main`. Retry a network
   failure once. Stop on a dirty worktree, conflict, or unexpected tracked diff.
3. Run `python3 scripts/publication_schedule_audit.py`.
4. Run `python3 scripts/publication_audit.py "$ISSUE_DATE"`. If it passes and
   root plus dated public URLs agree, stop without collection or review.

## Obtain final Evidence without duplicate work

Run the single stage-aware helper:

```text
python3 scripts/night_signal_review_artifact.py "$ISSUE_DATE"
```

It inspects `unattended-collection.yml` once, watches one queued/active owner
instead of duplicating it, restores the newest valid final artifact, and dispatches
exactly one collector only when neither exists. It validates the issue date,
16:45 JST cutoff, packet contract, and Evidence hash before installing files.
Then run:

```text
python3 scripts/night_signal_plus_editor.py "$ISSUE_DATE" --prepare
```

This command must report zero repository model requests and zero additional paid
API requests. It must retain every distinct candidate event; there is no item cap.

## Perform one compact Plus review

Read `state/$ISSUE_DATE/editor_packet.json`; do not read the full Evidence bundle
unless deterministic validation names a specific failed event. Review every
request and every event exactly once. `previous_updates` is novelty context only,
never a factual source.

Write `state/$ISSUE_DATE/editor_review.json` with this shape:

```json
{
  "contract": "codex-plus-editor-v1",
  "issue_date": "YYYY-MM-DD",
  "evidence_sha256": "copy exactly from editor_packet.json",
  "responses": [
    {
      "request_id": "copy exactly from the packet",
      "response": {
        "events": [
          {
            "event_id": "copy exactly from the packet",
            "decision": "publish",
            "items": [
              {
                "title": "natural Japanese title",
                "summary_points": [
                  {"text": "source-backed Japanese fact", "evidence_ids": ["e001"]}
                ],
                "topic_value_class": "technical_or_product_shift",
                "priority_class": "priority",
                "change_class": "new_event"
              }
            ]
          }
        ]
      }
    }
  ]
}
```

Allowed exclusion decisions are `duplicate_previous_event`,
`background_or_navigation`, `wrong_entity_or_category`, and
`no_material_update`; excluded events have an empty `items` array. Publish every
material delta without a count target. A new URL, date stamp, or background-only
rewrite is not a delta. Quarterly, annual, and final earnings results and material
market moves remain eligible. Exclude only previews or routine low-impact ticks.

Use all facts necessary to understand the event: subject and role, concrete
change, numbers, dates, scope, conditions, reasons, and results. Every title and
summary point must be natural Japanese. Every point must add information beyond
the title and cite all supporting Evidence ids. Do not infer facts or repeat
generic company descriptions.

For requests marked `quality_route=true`, check tables, multiple numbers,
attributed analysis, and cross-source consistency especially carefully. Prefer
official/primary Evidence where present, but do not discard an independent source
that supplies a distinct supported fact.

Apply and validate once:

```text
python3 scripts/night_signal_plus_editor.py "$ISSUE_DATE" \
  --apply-review "state/$ISSUE_DATE/editor_review.json"
```

If validation fails, change only the named request/event. Do not regenerate
accepted responses. Permit at most two corrections for one event; on a repeated
systemic failure, stop with the exact validator reason instead of a blind retry.

## Render, commit, and publish

After review validation passes, run:

```text
python3 scripts/night_signal_publish.py "$ISSUE_DATE" \
  --deploy-existing --deploy-edited-final-evidence --verification-profile deploy
```

Fetch `origin/main` and require local HEAD to still equal it before committing.
Stage only the normal publication surfaces:

```text
git add -A -- .night-signal-issue-date 'night-brief-web-sample-*.html' details site state
```

Commit `Publish NIGHT SIGNAL for $ISSUE_DATE`, push `HEAD:main`, dispatch
`pages.yml` once for the same date, and use one `gh run watch --exit-status`.
Finally fetch/rebase, run `publication_audit.py` again, and verify both root and
dated public URLs show the same current date.

## Stage-aware recovery

- Evidence collection failed: inspect the failed log, correct only a code/config
  cause, or retry the same network command once. Never start parallel collectors.
- Review validation failed: patch only rejected request/event entries; keep all
  accepted responses unchanged.
- Render or quality gate failed: fix the exact deterministic contract mismatch;
  reuse Evidence and accepted review responses.
- Remote main changed before commit: do not rebase a generated issue. Restart
  from current main so code, Evidence, and output stay aligned.
- Push succeeded but Pages failed or live pages lag: do not recollect or re-review.
  redispatch/watch Pages once, then rerun only publication audit.
- Current issue is already committed but not public: deploy the committed issue;
  do not enter collection or review.
- A second 18:35 run is a recovery heartbeat. It must audit first and exit with
  minimal work when the 18:05 run already succeeded.

CLI network or authentication commands may be retried once. Model turns, full
collection, full review, commits, and workflow dispatches must never be blindly
repeated. Browser, Computer Use, screenshots, and Web UI monitoring are forbidden.

## Model review

Production uses `gpt-5.6-terra` at low reasoning because it balances long
evidence review quality with Plus usage. On Mondays only, check official OpenAI
model documentation for a newer Codex-capable model. Do not change production
automatically. Promote only after representative NIGHT SIGNAL Evidence shows no
coverage or quality regression and lower or equal total token use. Report nothing
when there is no candidate.
