#!/usr/bin/env bash
set -euo pipefail

[[ "$STATIC_REDEPLOY" == "true" && -n "$EXPECTED_SITE_TREE" ]]
[[ "$ARTIFACT_ID" =~ ^[0-9]+$ ]]
endpoint="repos/$GITHUB_REPOSITORY/pages/deployments"
oidc_token="$(curl -fsS --max-time 15 -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
  "$ACTIONS_ID_TOKEN_REQUEST_URL" | jq -er '.value | strings | select(length > 0)')"
echo "::add-mask::$oidc_token"
result="$(printf '%s' "$oidc_token" |
  jq -Rs --arg sha "$GITHUB_SHA" --argjson artifact "$ARTIFACT_ID" \
    '{artifact_id: $artifact, pages_build_version: $sha, oidc_token: .}' |
  gh api --method POST "$endpoint" --input -)"
unset oidc_token
deployment_id="$(jq -er '.id | select(type == "string" or type == "number") | tostring | select(test("^[a-zA-Z0-9_-]+$"))' <<< "$result")"
jq -r '"page_url=" + (.page_url // "")' <<< "$result" >> "$GITHUB_OUTPUT"
echo "Checking Pages deployment $deployment_id for artifact $ARTIFACT_ID"
for attempt in $(seq 1 30); do
  status="$(gh api "$endpoint/$deployment_id" --jq .status || true)"
  case "$status" in
    succeed) exit 0 ;;
    deployment_failed|deployment_content_failed|deployment_cancelled|deployment_lost|deployment_perms_error)
      echo "Pages deployment stopped: $status" >&2
      exit 1
      ;;
  esac
  sleep 5
done
echo "Pages did not confirm deployment $deployment_id." >&2
exit 1
