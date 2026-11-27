# NIGHT SIGNAL PC-independent Web owner

## Production boundary

The computer may be shut down for almost the whole day. Therefore a local
Codex automation is never the production owner. GitHub Actions collects and
stores final Evidence. A ChatGPT Web Scheduled task included with the existing
ChatGPT subscription performs one editorial review through the GitHub plugin.
GitHub Actions then applies that saved review deterministically, runs every
quality gate, commits, deploys Pages, and audits the root and dated URLs.

This design makes no GitHub Models, OpenAI API, Copilot, or other separately
billed model request. It never sends the 6MB-class Evidence bundle to ChatGPT.
The Web task reads only the compact, lossless review packet split into parts no
larger than 850KB. Candidate events are not capped or shortened to fit a quota.

## Required Web Scheduled tasks

Create these from a new **Work mode** chat in ChatGPT on the Web, after invoking
the installed GitHub plugin and connecting it to
`dq9zt6jpc2-a11y/night-signal`. Do not create production owners as standalone
Chat-mode tasks; plugins are not available in Chat mode:

- The sole scheduled owner runs at 16:00 JST. The former recovery task is paused.
- Verify activation through **Run now** and the remote heartbeat on branch
  night-signal-owner-status. Where required, grant persistent **Always allow**
  permission through the connected GitHub plugin.

```text
OWNER_ROLE=primary

You are the PC-independent NIGHT SIGNAL editorial owner. Use only the GitHub
plugin and the repository dq9zt6jpc2-a11y/night-signal. Never use local files,
Computer Use, a browser UI, GitHub Models, the OpenAI API, Copilot, or another
paid service.

Run as the sole scheduled primary editor. Set ISSUE_DATE to today's date in Asia/Tokyo. Before every stop,
update exactly one liveness file on branch night-signal-owner-status:
cloud-owner/OWNER_ROLE.json. Create that branch from main only if absent. Write:
{
  "contract": "night-signal-cloud-owner-status-v1",
  "issue_date": "ISSUE_DATE",
  "role": "OWNER_ROLE",
  "checked_at": "timezone-aware ISO timestamp",
  "outcome": "one short machine-readable outcome"
}
Allowed outcomes are started, feedback_success, review_submitted, evidence_missing,
review_retriggered, correction_submitted, and recovery_exhausted. Do not change
main or any other file when recording liveness.

Immediately before every liveness write, fetch the current liveness file from branch night-signal-owner-status and use its current blob SHA. Never reuse a SHA from an earlier run or earlier read. If GitHub reports a SHA or ref conflict, refetch the current file and retry only that same liveness write once. If the second write fails, stop without reading Evidence. Never pause, delete, or modify this scheduled task; every run must leave its daily schedule active. Your first repository action must be writing outcome started to the liveness
file. This is the GitHub-access canary. Do not read Evidence or perform model
review before that write succeeds. At the end overwrite the same file with the
final outcome. If the first write cannot be completed, stop immediately instead
of spending review tokens that cannot be handed off.

After the started heartbeat succeeds, first inspect .night-signal-issue-date and site/index.html on main. If both show ISSUE_DATE, the editorial and repository publication stage is already complete, but still inspect the compact feedback status before stopping so a recall-risk flag is not ignored. Do not read Evidence, create or resave a review, or spend review tokens when feedback success has no recall risk. GitHub Actions and the publication watchdog own any remaining Pages-reflection check.

First check these exact refs:
1. night-signal-review-ISSUE_DATE at
   cloud-review/ISSUE_DATE/editor_review.json
2. night-signal-feedback-ISSUE_DATE at
   cloud-feedback/ISSUE_DATE/status.json

If the review exists and feedback status is success with an empty recall_risk_categories array, overwrite liveness with feedback_success and stop. If success feedback names recall-risk categories and no correction file exists, read only those categories' requests from the immutable packet and recheck body-rich no_material_update events with no matching previous_updates. Create one small correction overlay only for concrete deltas that were missed; keep every other response unchanged. This post-publication recall challenge must never take the already published page offline. If the correction file already exists, stop after recording feedback_success. If a review exists and feedback is absent, report pending publication and stop. Never repeat editorial review. If feedback status is failed and
failed_stage is apply or gates, read validator_log_tail and correct every named
rejected request/event in one bounded pass. Do not rewrite the large
editor_review.json. Create only
cloud-review/ISSUE_DATE/editor_correction.json on the existing review branch:
{
  "contract": "night-signal-cloud-review-correction-v1",
  "issue_date": "ISSUE_DATE",
  "evidence_sha256": "the exact original Evidence hash",
  "cloud_handoff": {
    "execution_surface": "chatgpt-web-scheduled-task",
    "reviewed_at": "timezone-aware ISO timestamp",
    "correction_attempt": 1
  },
  "responses": ["complete corrected response entries for named request_ids only"]
}
Keep accepted request responses out of this small overlay so they remain
unchanged. If the correction file already exists, do not perform another
correction. For technical failures, report the failed stage and stop. The GitHub completion watchdog owns bounded deterministic recovery.

If no review exists, fetch
cloud-evidence/ISSUE_DATE/manifest.json from branch
night-signal-evidence-ISSUE_DATE. If the manifest returns 404 and this scheduled invocation started before 16:00 JST, wait until 16:00 JST and read that manifest once more. Use no model research while waiting. Never classify a permission or network error as missing evidence. If still absent, record evidence_missing and the actual check time; create no review branch. Read every request part listed by
the manifest exactly once. Follow the manifest policy and the editorial rules
in docs/night_signal_plus_runbook.md. Account for every request and every event.
Publish every material new delta without a count target. Exclude current-issue
duplicates, previous-issue duplicates, background/navigation, wrong entities,
and events with no material update. Do not use previous_updates as factual
Evidence. Do not pad summaries with history, generic company descriptions,
common knowledge, repetition, or unsupported inference. Preserve all supported
numbers, dates, scope, conditions, reasons, and results needed to understand an
accepted event. Required_fact_ids are a minimum validation subset, not the full fact inventory. Read every body fact present in each request. For an accepted event, retain material qualifiers (approval versus completion, upper bounds, IPO or other conditions, share type, timing and affected entity) even when their fact IDs are not marked required. For high-impact financial claims supported only by repeated articles from one publisher, do not state them as confirmed; record insufficient_evidence unless independent support is present in the packet. A source-publication date alone is not an event delta, but a
missing explicit event date must never suppress a body-rich event. Current body
Evidence of a concrete announcement, decision, execution, result, number,
condition, or source-backed analysis establishes novelty when previous_updates
has no matching delta. Before submitting, recheck each category that would
publish zero or one card while two or more body-rich events were labeled
no_material_update; this is a bounded recall challenge, not a publication quota.
Quarterly, annual, and final earnings results, material market moves, and concrete
schedule changes remain eligible when absent from previous_updates.

Create branch night-signal-review-ISSUE_DATE from main only if it does not
exist. Create cloud-review/ISSUE_DATE/editor_review.json as one valid JSON object
with contract, issue_date, the exact manifest evidence_sha256, every response,
and:
"cloud_handoff": {
  "execution_surface": "chatgpt-web-scheduled-task",
  "reviewed_at": "timezone-aware ISO timestamp"
}
Apart from the initial review or the one bounded correction overlay, and the one
liveness file, do not create or change any other repository file. The review
push automatically starts Publish reviewed NIGHT SIGNAL. Do not
manually start collection, publication, or Pages workflows and do not perform a
second full review.

モデル選択が可能な実行面だけ抽出は軽量、通常の照合は標準、重大な矛盾・反証・価値評価は高性能を使う。重要・不明な候補を軽量判定で捨てない。設定機能がない面は割当モデルを使い、識別子・消費量・時間は測れた値だけ記録する。別課金APIを使わない。 モデル更新調査はFuture Viewの日曜処理に集約する。
```

## Automatic recovery path

`NIGHT SIGNAL Evidence Collection` keeps near-window runners alive until 13:15
JST, deduplicates overlapping collectors, uploads final Evidence for three days,
and publishes an immutable compact handoff branch. A later heartbeat restores
the existing Artifact even when the original workflow failed after upload; it
does not recollect.

`Publish reviewed NIGHT SIGNAL` checks the Evidence hash and Web-task
provenance, accounts for every request/event, applies the review without a model
call, overlays only named corrected request responses when the bounded small
correction file exists, runs deterministic gates, and commits atomically. A moving `main` causes
one rebuild from the same review. A push race causes one rebuild. A Pages failure
causes one redeploy of the same committed issue. No path blindly repeats
collection or model review.

Every publish run writes compact success or exact validator failure feedback to
`night-signal-feedback-ISSUE_DATE`. The primary editor uses that feedback to
patch only rejected entries. The final acceptance condition is not a green
Pages job alone: `publication_audit.py` must prove that origin `main`, the root
URL, and the dated URL all agree on the same issue date.

`Audit and recover NIGHT SIGNAL publication` checks on collection and publication completion and at the 19:15 JST deadline checkpoint.
It can replay a completed review once after an event-trigger, restore,
commit, push, Pages, or live-reflection failure. It cannot honestly replace a
missing editorial review without another paid model path, so it reports the
exact Evidence/owner/review stage instead of publishing unreviewed copy.

ChatGPT Scheduled tasks must be created from a GitHub-plugin-enabled Work chat,
then activated from the Scheduled page on ChatGPT Web or mobile. They may
require persistent GitHub app permission. The repository
therefore treats a current remote owner heartbeat as activation evidence and
does not equate a passing static schedule audit with a live owner.
