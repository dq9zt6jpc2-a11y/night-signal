# NIGHT SIGNAL Plus owner runbook

## Objective and fixed priorities

Publish the current JST issue automatically by 19:00 every evening. The priority order is:

1. coverage of every configured category and watch topic;
2. evidence grounding, novelty precision, and complete Japanese summaries;
3. token and runtime efficiency without weakening 1 or 2;
4. no charge beyond the user's existing ChatGPT Plus subscription.

GitHub Actions owns Evidence collection and deterministic publication. A
ChatGPT Web Scheduled task included with the existing subscription owns one
compact editorial review through the GitHub plugin. The local Codex automation
is emergency/manual diagnostics only and is never the production owner. See
`docs/night_signal_web_owner.md` for the PC-independent task contract. Never call
GitHub Models, the OpenAI API, Copilot credits, or another paid AI service.

## Local emergency start gate

Work only in `/Users/shimadatakashi/Documents/Codex/2026-05-10/gpt`.

1. Set `ISSUE_DATE` to today's JST date.
2. Run `git fetch origin main` and `git rebase origin/main`. Retry a network
   failure once. Stop on a dirty worktree, conflict, or unexpected tracked diff.
3. Run `python3 scripts/publication_schedule_audit.py`.
4. Run `python3 scripts/publication_audit.py "$ISSUE_DATE"`. If it passes and
   root plus dated public URLs agree, stop without collection or review.

## Obtain final Evidence without duplicate work (local emergency only)

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

## Perform one compact Web/Plus review

Read `state/$ISSUE_DATE/editor_packet.json`; do not read the full Evidence bundle
unless deterministic validation names a specific failed event. Review every
request and every event exactly once. `previous_updates` is novelty context only,
never a factual source. Each event's `novelty_context` gives explicit event dates
and the earliest known date; each Evidence entry keeps its source-publication date
and effective source class separately. A source-publication date by itself never
answers why the item is new today.

Write `state/$ISSUE_DATE/editor_review.json` with this shape:

```json
{
  "contract": "codex-plus-editor-v2",
  "issue_date": "YYYY-MM-DD",
  "evidence_sha256": "copy exactly from editor_packet.json",
  "cloud_handoff": {
    "execution_surface": "chatgpt-web-scheduled-task",
    "reviewed_at": "timezone-aware ISO timestamp"
  },
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
                "information_complete": true,
                "summary_points": [
                  {
                    "text": "source-backed Japanese fact",
                    "evidence_ids": ["e001"],
                    "source_fact_ids": ["e001:f01", "e001:f02"]
                  }
                ],
                "analysis": {
                  "inference": "labeled synthesis supported by multiple sources",
                  "counterargument": "strongest evidence-backed alternative",
                  "remaining_uncertainty": "what is still unknown",
                  "confidence": "high | medium | low",
                  "evidence_ids": ["e001", "e002"]
                },
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
`duplicate_current_issue_event`, `background_or_navigation`,
`wrong_entity_or_category`, `no_material_update`, and `insufficient_evidence`;
excluded events have an empty `items` array. A headline-only event must use
`insufficient_evidence` instead of `no_material_update` or
`background_or_navigation` unless body Evidence was resolved. Publish every
material delta without a count target. A new URL, date stamp, or background-only
rewrite is not a delta. For an already published event, publish only a concrete
new decision, execution, result, number, condition, or source-backed analysis.
Trusted media in `config/night_signal_publisher_portfolio.json` are searched in
a bounded, category- and topic-specific depth pass when body-rich Evidence from
a trusted source is missing. Open specialist media are tried before unrelated
or restricted sources; Google News and Bing remain discovery indexes rather
than source-quality substitutes.
Each weak topic gets separate single-domain official and specialist searches;
never combine several `site:` domains into one OR query. Count a targeted result
only when its article or publisher host matches that exact registered domain.
Use Google News once as a fallback when the primary Bing query is unavailable or
returns no on-domain result. Registered trusted Web seeds participate in this
depth search even when they are not duplicated in the publisher portfolio.
Restricted articles are discovery signals, not body Evidence; corroborate them
with an accessible primary source or independently readable report.
Quarterly, annual, and final earnings results and material
market moves remain eligible. Exclude only previews or routine low-impact ticks.

Breadth comes before analysis. Review every category, watch topic, and event;
never reduce the verified news set merely because an analysis cannot be formed.
Resolve important discovery results to official, regulatory, technical,
financial, specialist, or independently reported body text. Within one event,
preserve distinct facts contributed by different sources instead of selecting
one syndicated account and discarding the rest. Headline-only Evidence may stay
as an explicit insufficient-evidence candidate but cannot become a public update.

`topic_value_class` must be one of `decision_or_policy`,
`market_or_financial_impact`, `technical_or_product_shift`,
`operational_status_change`, `event_result_or_outcome`,
`material_schedule_change`, `risk_or_safety_signal`, or
`cultural_or_audience_signal`. The deterministic importer also normalizes the
documented legacy aliases; it must not request another model review only to
repair an equivalent class name.

Use all facts necessary to understand the event: subject and role, concrete
change, numbers, dates, scope, conditions, reasons, and results. Every title and
summary point must be natural Japanese. Every point must add information beyond
the title, cite all supporting Evidence ids, and list every `source_fact_id`
represented by that point. One sentence may cover several source-fact ids and
several items in one event may divide them. Do not infer facts or repeat generic
company descriptions.

Set `information_complete=true` only after accounting for every distinct,
current, article-specific supported fact needed to understand the accepted event.
Every id listed in Evidence `required_fact_ids` must be represented by at least
one accepted summary point. The importer rejects unknown ids, ids from another
event, ids whose Evidence is not cited by the point, and required ids omitted from
the whole event. `previous_updates` decide whether there is a publishable new
delta; after a publish decision, they must not remove current-source context needed
to understand the accepted event as a self-contained update.
`article_fact_count` records the complete cleaned sentence inventory and
`source_fact_overflow_count` records how many lower-ranked facts from an unusually
long single article could not enter the bounded summary inventory. This is a
quality/self-improvement signal, not permission to claim full source coverage or
to stop the daily publication. Never describe overflow as zero omission.
One summary point is valid only when the Evidence contains one such fact beyond
the title. Do not add a minimum length, historical background, common knowledge,
predictions, generic importance, or paraphrase repetition. Never omit a supported
number, date, scope, condition, reason, or result merely to shorten the summary.

`analysis` is optional and must never block an otherwise valid, information-
complete news item. Include it only when at least two independent body sources
for the same event support a useful synthesis. Keep verified facts in
`summary_points`; label the conclusion as inference and separately state the
strongest counterargument, remaining uncertainty, and confidence. If those
conditions are not met, omit `analysis` rather than padding it.

After the bounded official/specialist depth pass, keep any unresolved material
candidate in `source_gap_report.json` and the evaluation signals. Do not turn a
headline into a public update, but do not withhold other verified news or the
daily Web publication because one source body remains unavailable.

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
- Review validation failed: write one small correction overlay containing all
  rejected request/event entries; keep the large base review and all accepted
  responses unchanged.
- Render or quality gate failed: fix the exact deterministic contract mismatch;
  reuse Evidence and accepted review responses.
- Remote main changed before commit: do not rebase a generated issue. Restart
  from current main so code, Evidence, and output stay aligned.
- Push succeeded but Pages failed or live pages lag: do not recollect or re-review.
  redispatch/watch Pages once, then rerun only publication audit.
- Current issue is already committed but not public: deploy the committed issue;
  do not enter collection or review.
- The 17:50 Work-mode Web task is the cloud owner and the 18:25 Work-mode Web task is an audit-first
  recovery heartbeat. A successful earlier review/publication must not be
  repeated. The recovery task reads the compact feedback branch and patches only
  the rejected request/event entries.

CLI network or authentication commands may be retried once. Model turns, full
collection, full review, commits, and workflow dispatches must never be blindly
repeated. Browser, Computer Use, screenshots, and Web UI monitoring are forbidden.

## Continuous improvement loop

Every completed issue writes `state/$ISSUE_DATE/eval_report.json`. Compare the
current issue with up to three prior issues for source and discovery coverage,
local-language candidate yield, expanded-scope contribution, unavailable sources,
published facts, review requests, and review payload bytes. Treat the report as
diagnostic evidence, not as permission to weaken the collection contract.
Also track body-rich, trusted, and specialist Evidence, multi-source published
updates, non-body citations, unresolved source-depth gaps, facts per update, and
one-fact update ratio. Search-count growth alone is never proof of wider or
deeper coverage.

Runtime recovery may automatically reuse verified checkpoints and avoid duplicate
work. It must never auto-remove a source, locale, watch topic, quality gate, or
published fact requirement. Three consecutive zero-contribution expansion results
raise a precision-review signal; change the configuration only after checking
whether the cause is duplication, no new event, source failure, or a poor query.
After any change, require coverage and quality non-regression before accepting an
efficiency improvement.

## Model review

The configured Web task uses the evaluated `gpt-5.6-terra` quality/efficiency
route at low reasoning when that model is available in the subscribed ChatGPT
surface. On Mondays only, check official OpenAI model documentation for a newer
Codex-capable model. Do not change production automatically. Promote only after
representative NIGHT SIGNAL Evidence shows no coverage or quality regression and
lower or equal total token use. Report nothing when there is no candidate.

## Operational proof

`publication_schedule_audit.py` proves the repository architecture only.
`night_signal_operational_audit.py` separately checks the current Evidence
handoff, primary/recovery Web-owner heartbeat, review, workflow feedback, and
final root/dated publication. A current remote heartbeat or review is required
before saying the PC-independent editor is activated. `publication-watchdog.yml`
may replay only deterministic post-review work once; it never substitutes an
unreviewed issue, recollects Evidence, or calls a model.
