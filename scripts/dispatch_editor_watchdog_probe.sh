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
  --created ">=$issue_date" --limit 100 --json displayTitle,status)"
if jq -e --arg title "$title" \
  'length >= 100 or any(.[]; .displayTitle == $title or .status != "completed")' <<< "$runs" > /dev/null; then
  echo "An editor run is active, this issue was already probed, or the run query may be truncated."
  exit 0
fi

fresh_audit="$(mktemp)"
trap 'unlink "$fresh_audit"' EXIT
python3 scripts/night_signal_operational_audit.py "$issue_date" --report-only > "$fresh_audit"
decision="$(python3 scripts/night_signal_editor_recovery_decision.py "$fresh_audit")"
if [[ "$(jq -er .reason <<< "$decision")" == "eligible_for_independent_editor" ]]; then
  # The watchdog is serialized. Do not repeat a failed dispatch here, since the
  # server may have accepted the first request before the response was lost.
  gh workflow run independent-editor-trial.yml --ref main \
    -f "issue_date=$issue_date" -f watchdog_probe=true
fi
