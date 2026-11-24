#!/usr/bin/env bash
set -euo pipefail

issue_date="${1:?Missing issue date}"
phase="${2:?Missing dispatch phase}"
request_id="review-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}-$phase"
title="Publish NIGHT SIGNAL $issue_date $request_id"
site_tree="$(git rev-parse HEAD:site)"

# A failed response does not establish that GitHub rejected the dispatch.
# Reconcile the exact request before concluding it was not observed.
if ! gh workflow run pages.yml --ref main \
    -f "issue_date=$issue_date" \
    -f deploy_edited_final_evidence=true \
    -f "request_id=$request_id" \
    -f "expected_site_tree=$site_tree" >&2; then
  echo "Dispatch result uncertain for $request_id; checking for the run." >&2
fi

for attempt in $(seq 1 24); do
  if runs="$(gh run list --workflow pages.yml --branch main --event workflow_dispatch \
      --limit 30 --json databaseId,displayTitle)" &&
      matches="$(jq -r --arg title "$title" '.[] | select(.displayTitle == $title) | .databaseId' <<< "$runs")" &&
      [[ -n "$matches" ]]; then
    if [[ "$matches" =~ ^[0-9]+$ ]]; then
      printf '%s\n' "$matches"
      exit 0
    fi
    echo "Multiple Pages runs claim $request_id." >&2
    exit 1
  fi
  sleep 5
done

echo "No Pages run observed for $request_id." >&2
exit 1
