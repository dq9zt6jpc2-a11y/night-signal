#!/usr/bin/env bash
set -euo pipefail

# The caller checks that this exact artifact is finalized in this run.
[[ "${ARTIFACT_ID:?}" =~ ^[0-9]+$ ]]
endpoint="repos/${GITHUB_REPOSITORY:?}/pages/deployments"
build_version="${GITHUB_SHA:?}-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}"

oidc_token="$(curl -fsS --max-time 15 -H "Authorization: bearer ${ACTIONS_ID_TOKEN_REQUEST_TOKEN:?}" \
  "${ACTIONS_ID_TOKEN_REQUEST_URL:?}" | jq -er '.value | strings | select(length > 0)')"
echo "::add-mask::$oidc_token"
deployment_id="$build_version"
if result="$(printf '%s' "$oidc_token" |
    jq -Rs --arg version "$build_version" --argjson artifact "$ARTIFACT_ID" \
      '{artifact_id: $artifact, pages_build_version: $version, oidc_token: .}' |
    gh api --method POST "$endpoint" --input -)"; then
  deployment_id="$(jq -er '.id | tostring | select(test("^[a-zA-Z0-9_-]+$"))' <<< "$result")"
  jq -r '"page_url=" + (.page_url // "")' <<< "$result" >> "${GITHUB_OUTPUT:?}"
else
  echo "Pages creation outcome uncertain; checking the build version without submitting again." >&2
fi
unset oidc_token

echo "Checking Pages deployment $deployment_id for artifact $ARTIFACT_ID"
for attempt in $(seq 1 60); do
  if status="$(gh api "$endpoint/$deployment_id" --jq .status 2>/dev/null)"; then
    case "$status" in
      succeed) exit 0 ;;
      deployment_failed|deployment_content_failed|deployment_cancelled|deployment_lost|deployment_perms_error)
        echo "Pages deployment stopped: $status" >&2
        exit 1
        ;;
    esac
  fi
  sleep 5
done
echo "Pages deployment not confirmed for $deployment_id." >&2
exit 1
