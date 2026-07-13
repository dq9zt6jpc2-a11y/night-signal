#!/usr/bin/env python3
"""Check current model availability without spending inference tokens."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import night_signal_models as models


CATALOG_URL = "https://models.github.ai/catalog/models"
LATEST_MODEL_URL = "https://developers.openai.com/api/docs/guides/latest-model.md"
USER_AGENT = "NightSignalModelAudit/1.0"


def fetch_text(url: str, *, token: str | None = None, timeout: int = 20) -> str:
    headers = {
        "Accept": "application/vnd.github+json" if "models.github.ai" in url else "text/markdown",
        "User-Agent": USER_AGENT,
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
        headers["X-GitHub-Api-Version"] = "2026-03-10"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read().decode("utf-8")


def latest_model_id(markdown: str) -> str | None:
    match = re.search(r"^\s*model:\s*([A-Za-z0-9._-]+)\s*$", markdown, flags=re.M)
    return match.group(1) if match else None


def catalog_ids(value: Any) -> set[str]:
    if not isinstance(value, list):
        raise ValueError("GitHub Models catalog must be an array")
    return {
        str(item["id"])
        for item in value
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }


def configured_model_ids() -> set[str]:
    config = models.load_config().get("extraction", {})
    values = [
        config.get("model"),
        config.get("quality_model"),
        *config.get("fallback_models", []),
    ]
    return {str(value) for value in values if isinstance(value, str) and value}


def evaluate_catalog(ids: set[str], latest: str | None) -> dict[str, Any]:
    configured = configured_model_ids()
    missing = sorted(configured - ids)
    latest_provider_id = f"openai/{latest}" if latest else None
    family = latest.rsplit("-", 1)[0] if latest and latest.endswith("-sol") else latest
    family_candidates = sorted(
        item
        for item in ids
        if family and item.startswith(f"openai/{family}")
    )
    evaluation_candidates = [item for item in family_candidates if item not in configured]
    return {
        "configured_models": sorted(configured),
        "missing_configured_models": missing,
        "latest_openai_model": latest,
        "latest_openai_provider_id": latest_provider_id,
        "latest_available_in_github_models": bool(
            latest_provider_id and latest_provider_id in ids
        ),
        "available_latest_family_models": family_candidates,
        "evaluation_candidates": evaluation_candidates,
        "evaluation_required": bool(evaluation_candidates),
        "automatic_model_change": False,
    }


def live_audit(token: str | None) -> tuple[dict[str, Any], bool]:
    errors: list[str] = []
    latest: str | None = None
    ids: set[str] | None = None
    try:
        latest = latest_model_id(fetch_text(LATEST_MODEL_URL))
        if not latest:
            errors.append("official latest-model document did not identify a model")
    except (OSError, TimeoutError, urllib.error.URLError) as exc:
        errors.append(f"latest-model lookup unavailable: {type(exc).__name__}")
    if not token:
        errors.append("GitHub token unavailable for model catalog lookup")
    else:
        try:
            ids = catalog_ids(json.loads(fetch_text(CATALOG_URL, token=token)))
        except (OSError, TimeoutError, urllib.error.URLError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"GitHub Models catalog unavailable: {type(exc).__name__}")
    if ids is None:
        report = {
            "status": "lookup_unavailable",
            "configured_models": sorted(configured_model_ids()),
            "latest_openai_model": latest,
            "errors": errors,
            "inference_calls": 0,
        }
        return report, False
    report = evaluate_catalog(ids, latest)
    report.update(
        {
            "status": "configured_model_missing"
            if report["missing_configured_models"]
            else "evaluation_required"
            if report["evaluation_required"]
            else "current",
            "catalog_model_count": len(ids),
            "errors": errors,
            "inference_calls": 0,
        }
    )
    return report, bool(report["missing_configured_models"])


def self_test() -> None:
    if latest_model_id("---\nlatestModelInfo:\n  model: gpt-5.6-sol\n---\n") != "gpt-5.6-sol":
        raise SystemExit("latest model parser failed")
    ids = {
        "openai/gpt-4.1",
        "openai/gpt-4.1-mini",
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "openai/gpt-5",
        "openai/gpt-5-mini",
        "openai/gpt-5.6-sol",
        "openai/gpt-5.6-terra",
        "openai/gpt-5.6-luna",
    }
    result = evaluate_catalog(ids, "gpt-5.6-sol")
    if result["missing_configured_models"]:
        raise SystemExit("configured models were not recognized")
    if set(result["evaluation_candidates"]) != {
        "openai/gpt-5.6-luna",
        "openai/gpt-5.6-sol",
        "openai/gpt-5.6-terra",
    }:
        raise SystemExit("new model family was not routed to evaluation")
    if result["automatic_model_change"]:
        raise SystemExit("catalog audit must not change production models")
    print("NIGHT SIGNAL MODEL AUDIT SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    report, blocking = live_audit(token)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    if report.get("evaluation_required"):
        print(
            "MODEL EVALUATION REQUIRED: new models are available; production remains unchanged",
            file=sys.stderr,
        )
    if blocking:
        print("MODEL AUDIT FAILED: configured production model is unavailable", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
