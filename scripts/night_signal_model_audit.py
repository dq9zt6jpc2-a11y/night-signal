#!/usr/bin/env python3
"""Check current model availability without spending inference tokens."""

from __future__ import annotations

import argparse
import hashlib
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
COMPATIBLE_OPENAI_MODEL_RE = re.compile(
    r"^openai/gpt-(?P<major>\d+)(?:\.(?P<minor>\d+))?"
    r"(?:-(?P<tier>mini|nano|sol|terra|luna))?$"
)


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


def catalog_snapshot_fingerprint(value: Any) -> str:
    """Change the evaluation key when a compatible deployment changes in place."""
    if not isinstance(value, list):
        raise ValueError("GitHub Models catalog must be an array")
    snapshot = []
    for item in value:
        if not isinstance(item, dict):
            continue
        model_id = item.get("id")
        if not isinstance(model_id, str) or compatible_model_key(model_id) is None:
            continue
        snapshot.append(
            {
                "id": model_id,
                "version": item.get("version"),
                "rate_limit_tier": item.get("rate_limit_tier"),
                "capabilities": item.get("capabilities"),
                "limits": item.get("limits"),
            }
        )
    encoded = json.dumps(
        sorted(snapshot, key=lambda item: str(item["id"])),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def configured_model_ids() -> set[str]:
    config = models.load_config().get("extraction", {})
    values = [
        config.get("model"),
        config.get("quality_model"),
        *config.get("fallback_models", []),
    ]
    return {str(value) for value in values if isinstance(value, str) and value}


def compatible_model_key(model_id: str) -> tuple[int, int, int, str] | None:
    """Order compatible general-purpose OpenAI models by generation and tier."""
    match = COMPATIBLE_OPENAI_MODEL_RE.fullmatch(model_id)
    if not match:
        return None
    tier_rank = {
        "nano": 1,
        "luna": 1,
        "mini": 2,
        "terra": 2,
        None: 3,
        "sol": 3,
    }
    tier = match.group("tier")
    return (
        int(match.group("major")),
        int(match.group("minor") or 0),
        tier_rank[tier],
        model_id,
    )


def evaluation_candidates(ids: set[str], configured: set[str]) -> list[str]:
    """Find every newer compatible GitHub model, not only the official latest family."""
    configured_keys = [
        key
        for model_id in configured
        if (key := compatible_model_key(model_id)) is not None
    ]
    baseline_generation = max(
        ((key[0], key[1]) for key in configured_keys),
        default=(0, 0),
    )
    candidates = []
    for model_id in ids - configured:
        key = compatible_model_key(model_id)
        if key is None or (key[0], key[1]) < baseline_generation:
            continue
        candidates.append(model_id)
    return sorted(
        candidates,
        key=lambda model_id: compatible_model_key(model_id)
        or (0, 0, 0, model_id),
    )


def candidate_fingerprint(
    candidates: list[str],
    catalog_fingerprint: str = "",
) -> str:
    encoded = json.dumps(
        {
            "candidates": sorted(candidates),
            "catalog_fingerprint": catalog_fingerprint,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:20]


def evaluate_catalog(
    ids: set[str],
    latest: str | None,
    *,
    catalog_fingerprint: str = "",
) -> dict[str, Any]:
    configured = configured_model_ids()
    missing = sorted(configured - ids)
    latest_provider_id = f"openai/{latest}" if latest else None
    family = latest.rsplit("-", 1)[0] if latest and latest.endswith("-sol") else latest
    family_candidates = sorted(
        item
        for item in ids
        if family and item.startswith(f"openai/{family}")
    )
    compatible_models = sorted(
        (item for item in ids if compatible_model_key(item) is not None),
        key=lambda model_id: compatible_model_key(model_id) or (0, 0, 0, model_id),
    )
    candidates = evaluation_candidates(ids, configured)
    return {
        "configured_models": sorted(configured),
        "missing_configured_models": missing,
        "latest_openai_model": latest,
        "latest_openai_provider_id": latest_provider_id,
        "latest_available_in_github_models": bool(
            latest_provider_id and latest_provider_id in ids
        ),
        "available_latest_family_models": family_candidates,
        "available_compatible_openai_models": compatible_models,
        "evaluation_candidates": candidates,
        "catalog_fingerprint": catalog_fingerprint,
        "candidate_fingerprint": candidate_fingerprint(
            candidates,
            catalog_fingerprint,
        ),
        "evaluation_required": bool(candidates),
        "automatic_model_change": False,
    }


def live_audit(token: str | None) -> tuple[dict[str, Any], bool]:
    errors: list[str] = []
    latest: str | None = None
    ids: set[str] | None = None
    catalog_fingerprint = ""
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
            catalog = json.loads(fetch_text(CATALOG_URL, token=token))
            ids = catalog_ids(catalog)
            catalog_fingerprint = catalog_snapshot_fingerprint(catalog)
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
    report = evaluate_catalog(
        ids,
        latest,
        catalog_fingerprint=catalog_fingerprint,
    )
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
        "openai/gpt-5",
        "openai/gpt-5-mini",
        "openai/gpt-5.6-luna",
        "openai/gpt-5.6-sol",
        "openai/gpt-5.6-terra",
    }:
        raise SystemExit("new model family was not routed to evaluation")
    github_lags_official = evaluate_catalog(
        {
            "openai/gpt-4.1",
            "openai/gpt-4.1-mini",
            "openai/gpt-4o",
            "openai/gpt-4o-mini",
            "openai/gpt-5",
            "openai/gpt-5-mini",
            "openai/gpt-5-nano",
        },
        "gpt-5.6-sol",
    )
    if set(github_lags_official["evaluation_candidates"]) != {
        "openai/gpt-5",
        "openai/gpt-5-mini",
        "openai/gpt-5-nano",
    }:
        raise SystemExit("catalog audit missed a newer GitHub model generation")
    if github_lags_official["latest_available_in_github_models"]:
        raise SystemExit("official latest model was reported as available in GitHub Models")
    first_snapshot = [
        {
            "id": "openai/gpt-5-mini",
            "version": "2025-08-07",
            "capabilities": ["reasoning"],
            "limits": {"max_output_tokens": 100000},
        }
    ]
    second_snapshot = json.loads(json.dumps(first_snapshot))
    second_snapshot[0]["version"] = "2026-01-01"
    if catalog_snapshot_fingerprint(first_snapshot) == catalog_snapshot_fingerprint(
        second_snapshot
    ):
        raise SystemExit("in-place model deployment changes escaped the catalog key")
    if result["automatic_model_change"]:
        raise SystemExit("catalog audit must not change production models")
    print("NIGHT SIGNAL MODEL AUDIT SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--github-output", type=Path)
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
    if args.github_output:
        candidates = report.get("evaluation_candidates", [])
        if not isinstance(candidates, list):
            candidates = []
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(
                "evaluation_required="
                + ("true" if report.get("evaluation_required") else "false")
                + "\n"
            )
            output.write(
                "candidate_fingerprint="
                + str(report.get("candidate_fingerprint", "unavailable"))
                + "\n"
            )
            output.write(
                "candidate_models="
                + json.dumps(candidates, separators=(",", ":"))
                + "\n"
            )
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
