#!/usr/bin/env python3
"""Prove NIGHT SIGNAL chooses an explicit path for common runtime failures."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import night_signal_collect as collector
import night_signal_runtime_audit as runtime
import night_signal_synthesize as synthesizer


def main() -> int:
    failure_cases = {
        "codex_credit_exhausted": '{"has_credits":false,"balance":"0"}',
        "openai_quota_exhausted": "insufficient_quota",
        "model_token_budget_exhausted": "context_length_exceeded",
        "rate_limited": "HTTP 429 rate_limit",
        "execution_timeout": "background Responses request timed out",
        "authentication_unavailable": "OPENAI_API_KEY is required",
        "network_unavailable": "Could not resolve host: api.openai.com",
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
        "fresh_evening_issue": runtime.decide_recovery(
            fresh_evening_issue=True,
            reviewed_bundle_usable=False,
            openai_api_key=False,
        ),
        "reviewed_bundle": runtime.decide_recovery(
            fresh_evening_issue=False,
            reviewed_bundle_usable=True,
            openai_api_key=False,
        ),
        "responses_api": runtime.decide_recovery(
            fresh_evening_issue=False,
            reviewed_bundle_usable=False,
            openai_api_key=True,
        ),
        "blocked_no_honest_collector": runtime.decide_recovery(
            fresh_evening_issue=False,
            reviewed_bundle_usable=False,
            openai_api_key=False,
        ),
    }
    failures.extend(
        f"recovery_{expected}"
        for expected, actual in recovery_cases.items()
        if expected != actual
    )
    durable_resume = {
        "collection_slot": False,
        "synthesis_category": False,
        "changed_input_invalidates_checkpoint": False,
    }
    with tempfile.TemporaryDirectory() as temp_dir:
        state_dir = Path(temp_dir)
        task = {
            "issue_date": "2099-01-01",
            "slot_id": "openai-product-web",
            "category": "OpenAI",
            "watch_topics": [],
            "source_role": "primary_or_official",
            "channel": "web",
        }
        collector.write_collection_part(
            state_dir,
            task,
            {
                "needs_extended_research": False,
                "extended_research_reason": None,
                "findings": [],
                "observations": [],
            },
            [],
        )
        durable_resume["collection_slot"] = collector.load_collection_part(state_dir, task) is not None
        changed_task = dict(task)
        changed_task["channel"] = "sns_x"
        durable_resume["changed_input_invalidates_checkpoint"] = (
            collector.load_collection_part(state_dir, changed_task) is None
        )

        signature = synthesizer.category_signature(
            "2099-01-01",
            "OpenAI",
            [],
            [],
            [],
        )
        synthesizer.write_synthesis_part(
            state_dir,
            "2099-01-01",
            "OpenAI",
            signature,
            {
                "category": "OpenAI",
                "candidates": [],
                "decisions": [],
                "cards": [],
                "no_change_checks": [],
            },
        )
        durable_resume["synthesis_category"] = (
            synthesizer.load_synthesis_part(
                state_dir,
                "2099-01-01",
                "OpenAI",
                signature,
            )
            is not None
        )
    failures.extend(
        f"durable_resume_{name}"
        for name, passed in durable_resume.items()
        if not passed
    )
    result = {
        "verdict": "pass" if not failures else "fail",
        "failure_classes": sorted(failure_cases),
        "recovery_paths": recovery_cases,
        "durable_resume": durable_resume,
        "failures": failures,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
