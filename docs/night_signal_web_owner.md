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

- Primary owner: every day at 17:50 JST, after the 17:17 Evidence collection
  has enough time to finish.
- Recovery heartbeat: every day at 18:25 JST.

The second task is audit-first. When the first task succeeded it reads only the
small status/review files and exits, so it does not repeat the editorial review.
These tasks run in the cloud; the Mac and the local ChatGPT app may be off.

Creation is not activation. Before treating either task as production-ready,
use **Run now** once and grant the GitHub connector persistent write permission
with **Always allow** (`常に許可`). Then verify that the matching
`cloud-owner/primary.json` or `cloud-owner/recovery.json` file was updated on
`night-signal-owner-status` for the current JST date. A visible active schedule
or a passing static repository audit is not sufficient proof: no current remote
heartbeat means the task is unproven, paused, or unable to write GitHub.

Use the following prompt for both tasks. Set `OWNER_ROLE=primary` in the 17:50
task and `OWNER_ROLE=recovery` in the 18:25 task. The small, separate heartbeat
lets the repository distinguish a missing review from a task that never ran,
was paused, or lost GitHub permission.

```text
You are the PC-independent NIGHT SIGNAL editorial owner. Use only the GitHub
plugin and the repository dq9zt6jpc2-a11y/night-signal. Never use local files,
Computer Use, a browser UI, GitHub Models, the OpenAI API, Copilot, or another
paid service.

OWNER_ROLE is primary for the 17:50 task and recovery for the 18:25 task. Reject
any other value. Set ISSUE_DATE to today's date in Asia/Tokyo. Before every stop,
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

Your first repository action must be writing outcome started to the liveness
file. This is the GitHub-access canary. Do not read Evidence or perform model
review before that write succeeds. At the end overwrite the same file with the
final outcome. If the first write cannot be completed, stop immediately instead
of spending review tokens that cannot be handed off.

First check these exact refs:
1. night-signal-review-ISSUE_DATE at
   cloud-review/ISSUE_DATE/editor_review.json
2. night-signal-feedback-ISSUE_DATE at
   cloud-feedback/ISSUE_DATE/status.json

If the review exists and feedback status is success, stop. If a review exists
and feedback is absent at the 18:25 recovery heartbeat, resave the identical
responses once with cloud_handoff.recovery_attempt=1 and a refreshed reviewed_at
to retrigger deterministic publication; if recovery_attempt is already 1, stop.
Do not perform another editorial review. If feedback status is failed and
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
  "responses": [
    {
      "request_id": "failed request id",
      "response": {"events": ["complete corrected failed event objects only"]}
    }
  ]
}
Include only the failed event objects named by validator_log_tail. The
deterministic merge preserves every other event in that request and every
accepted request unchanged. If the correction file already exists, do not perform another
correction. If failure is restore,
base_guard, commit, push, pages, pages_retry, pages_watch, or verify, do not alter
any response: resave the same review once with cloud_handoff.recovery_attempt=1
to rerun only the deterministic recovery. If the matching attempt value is
already 1, stop with the exact remaining reason. Permit at most one correction
or recovery commit in this run.

If no review exists, fetch
cloud-evidence/ISSUE_DATE/manifest.json from branch
night-signal-evidence-ISSUE_DATE. If it is absent, record the liveness outcome
without creating a review branch; the 18:25 heartbeat will check again. Read every request part listed by
the manifest exactly once. Follow the manifest policy and the editorial rules
in docs/night_signal_plus_runbook.md. Account for every request and every event.
Publish every material new delta without a count target. Exclude current-issue
duplicates, previous-issue duplicates, background/navigation, wrong entities,
and events with no material update. Do not use previous_updates as factual
Evidence. Do not pad summaries with history, generic company descriptions,
common knowledge, repetition, or unsupported inference. Preserve all supported
numbers, dates, scope, conditions, reasons, and results needed to understand an
accepted event. Quarterly, annual, and final earnings results and material
market moves remain eligible.

Breadth and source depth come before analysis. Account for every category,
watch topic, request, and event. Treat discovery indexes as leads and prefer
official, specialist, technical, financial, regulatory, and independent body
Evidence. When several sources cover one event, retain every distinct supported
fact instead of copying one account. Never publish headline-only Evidence.
Optional analysis must not suppress a verified news item: add it only when two
independent body sources support a labeled inference, counterargument, remaining
uncertainty, and confidence. Otherwise omit analysis without shortening or
discarding the verified fact summary. Never pad either layer.
An unresolved body candidate stays in the source-gap diagnostics; it is not a
headline-based public item and does not suppress other verified news or the
daily Web publication.

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
```

The repository implementation cannot create a ChatGPT Web Scheduled task from a
local checkout. Activation of these two Web tasks is therefore an explicit
deployment prerequisite, not something a successful GitHub commit can prove.

## Automatic recovery path

`NIGHT SIGNAL Evidence Collection` keeps near-window runners alive until 16:45
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
`night-signal-feedback-ISSUE_DATE`. The recovery Web task uses that feedback to
patch only rejected entries. The final acceptance condition is not a green
Pages job alone: `publication_audit.py` must prove that origin `main`, the root
URL, and the dated URL all agree on the same issue date.

`Audit and recover NIGHT SIGNAL publication` first checks owner activation at
18:00, then checks recovery/publication at 18:35, 18:50, and 19:05
JST. It can replay a completed review once after an event-trigger, restore,
commit, push, Pages, or live-reflection failure. It cannot honestly replace a
missing editorial review without another paid model path, so it reports the
exact Evidence/owner/review stage instead of publishing unreviewed copy.

ChatGPT Scheduled tasks must be created from a GitHub-plugin-enabled Work chat,
then activated from the Scheduled page on ChatGPT Web or mobile. They may
require persistent GitHub app permission. The repository
therefore treats a current remote owner heartbeat as activation evidence and
does not equate a passing static schedule audit with a live owner.
