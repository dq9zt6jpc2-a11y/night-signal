#!/usr/bin/env bash
set -euo pipefail
audit="${1:?Missing operational audit}"
decision="$(python3 scripts/night_signal_editor_recovery_decision.py "$audit")"
if [[ "$(jq -er .reason <<< "$decision")" != "eligible_for_independent_editor" ]]; then
  exit 0
fi

issue_date="$(jq -er .issue_date <<< "$decision")"
title="Independent editor watchdog probe $issue_date"
runs="$(gh run list --workflow independent-editor-trial.yml --branch main \
  --created ">=$issue_date" --limit 100 --json displayTitle,status,conclusion,databaseId)"
if jq -e --arg title "$title" \
  'length >= 100 or any(.[]; .status != "completed")' <<< "$runs" > /dev/null; then
  echo "An editor run is active, this issue was already probed, or the run query may be truncated."
  exit 0
fi

resume_args=()
previous="$(jq --arg title "$title" '[.[] | select(.displayTitle == $title)]' <<< "$runs")"
if [[ "$previous" != '[]' ]]; then
  # Only a first attempt explicitly deferred by the provider can be resumed here.
  run_id="$(jq -r 'if length == 1 and .[0].conclusion == "failure" then .[0].databaseId else empty end' <<< "$previous")"
  [[ "$run_id" =~ ^[0-9]+$ ]] || exit 0
  repo="${GITHUB_REPOSITORY:?Missing repository}"
  artifacts="$(gh api "repos/$repo/actions/runs/$run_id/artifacts")"
  jq -e 'any(.artifacts[]; .name == "independent-editor-backoff" and (.expired | not))' <<< "$artifacts" >/dev/null || exit 0
  marker_dir="$(mktemp -d)"
  gh run download "$run_id" --name independent-editor-backoff --dir "$marker_dir"
  retry_at="$(jq -er 'select(.status == 429) | .retry_at | select(type == "number" and . == floor)' "$marker_dir/provider_backoff.json")"
  (( $(date +%s) >= retry_at )) || exit 0
  resume_args=(-f "resume_run_id=$run_id")
fi

fresh_audit="$(mktemp)"
trap 'unlink "$fresh_audit"' EXIT
python3 scripts/night_signal_operational_audit.py "$issue_date" --report-only > "$fresh_audit"
decision="$(python3 scripts/night_signal_editor_recovery_decision.py "$fresh_audit")"
if [[ "$(jq -er .reason <<< "$decision")" == "eligible_for_independent_editor" ]]; then
  # The watchdog is serialized. Do not repeat a failed dispatch here, since the
  # server may have accepted the first request before the response was lost.
  gh workflow run independent-editor-trial.yml --ref main \
    -f "issue_date=$issue_date" -f watchdog_probe=true "${resume_args[@]}"
fi
