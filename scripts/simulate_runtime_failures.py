#!/usr/bin/env python3
"""Exercise the small set of runtime decisions used by production."""

from __future__ import annotations

import json

import night_signal_runtime_audit as runtime


def main() -> int:
    failure_cases = {
        "model_token_budget_exhausted": "context_length_exceeded",
        "rate_limited": "HTTP 429 rate_limit",
        "execution_timeout": "command timed out",
        "authentication_unavailable": "GITHUB_TOKEN is required",
        "network_unavailable": "Could not resolve host: example.com",
        "github_unavailable": "Could not resolve host: github.com",
        "dirty_worktree": "working tree has uncommitted changes",
        "partial_execution": '{"last_agent_message":null}',
    }
    failures = [
        name
        for name, sample in failure_cases.items()
        if runtime.classify_failure(sample) != name
    ]
    recovery_cases = {
        "fresh_final_issue": runtime.decide_recovery(
            fresh_final_issue=True,
            evidence_usable=False,
        ),
        "evidence": runtime.decide_recovery(
            fresh_final_issue=False,
            evidence_usable=True,
        ),
        "github_models_unattended": runtime.decide_recovery(
            fresh_final_issue=False,
            evidence_usable=False,
            github_models_token=True,
        ),
        "blocked_no_honest_collector": runtime.decide_recovery(
            fresh_final_issue=False,
            evidence_usable=False,
        ),
    }
    failures.extend(
        f"recovery_{expected}"
        for expected, actual in recovery_cases.items()
        if expected != actual
    )
    result = {
        "verdict": "pass" if not failures else "fail",
        "failure_classes": sorted(failure_cases),
        "recovery_paths": recovery_cases,
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
