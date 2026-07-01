#!/usr/bin/env python3
"""One-shot model-routing benchmark over one immutable Evidence bundle."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
from pathlib import Path
from typing import Any

import night_signal_core as core
import night_signal_editor as editor
import night_signal_evidence as evidence_store
import night_signal_state as state


ROOT = Path(__file__).resolve().parents[1]


def usage_from_log(value: str) -> dict[str, int]:
    for line in value.splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("phase") == "model_usage":
            return {
                key: int(item.get(key) or 0)
                for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            }
    return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def fact_matches(left: str, right: str) -> bool:
    return state.materially_same_fact(left, right) or (
        state.text_overlap(left, right) >= 2
        and set(state.content_terms(left)) <= set(state.content_terms(right))
    )


def baseline_recall(
    baseline_cards: list[dict[str, Any]],
    cards: list[dict[str, Any]],
) -> dict[str, Any]:
    matched_cards = 0
    baseline_facts = 0
    matched_facts = 0
    for baseline in baseline_cards:
        facts = [
            str(fact)
            for fact in baseline.get("detail", {}).get("summary_basis", {}).get("confirmed_facts", [])
        ]
        baseline_facts += len(facts)
        baseline_urls = {
            str(source.get("url"))
            for source in baseline.get("detail", {}).get("sources", [])
            if isinstance(source, dict)
        }
        candidates = [
            card
            for card in cards
            if card.get("category") == baseline.get("category")
            and (
                state.same_material_event(card.get("title", ""), baseline.get("title", ""))
                or bool(
                    baseline_urls
                    & {
                        str(source.get("url"))
                        for source in card.get("detail", {}).get("sources", [])
                        if isinstance(source, dict)
                    }
                )
            )
        ]
        if not candidates:
            continue
        matched_cards += 1
        candidate_facts = [
            str(fact)
            for card in candidates
            for fact in card.get("detail", {}).get("summary_basis", {}).get("confirmed_facts", [])
        ]
        matched_facts += sum(
            any(fact_matches(fact, candidate) for candidate in candidate_facts)
            for fact in facts
        )
    return {
        "baseline_cards": len(baseline_cards),
        "matched_cards": matched_cards,
        "card_recall": matched_cards / len(baseline_cards) if baseline_cards else 1.0,
        "matched_card_facts": matched_facts,
        "matched_card_fact_total": baseline_facts,
        "matched_card_fact_recall": matched_facts / baseline_facts if baseline_facts else 1.0,
    }


def benchmark_model(
    model: str,
    issue_date: str,
    evidence: dict[str, Any],
    baseline_cards: list[dict[str, Any]],
    token: str,
) -> dict[str, Any]:
    configs = editor.category_config()
    cards: list[dict[str, Any]] = []
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    category_metrics: list[dict[str, Any]] = []
    for category in core.category_contracts():
        label = str(category["label"])
        records = [
            record
            for record in evidence["categories"][label]["records"]
            if isinstance(record, dict)
        ]
        payload = core.category_prompt(category, issue_date, records)
        if not payload["evidence"]:
            category_metrics.append({"category": label, "eligible_records": 0, "model_items": 0, "cards": 0})
            continue
        messages = [
            {"role": "system", "content": core.SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            },
        ]
        captured = io.StringIO()
        with contextlib.redirect_stdout(captured):
            raw = core.model_request(token, messages, model_name=model, retry_wait_cap=90)
        model_usage = usage_from_log(captured.getvalue())
        for key in usage:
            usage[key] += model_usage[key]
        normalized = core.normalize_result(raw, category, issue_date, records)
        model_items = len(normalized["items"])
        core.backfill_items_from_evidence(normalized, category, issue_date, records)
        normalized["items"] = core.merge_related_items(normalized["items"])
        category_cards = [
            editor.item_card(label, str(configs[label]["section_id"]), item, issue_date)
            for item in normalized["items"]
        ]
        cards.extend(category_cards)
        category_metrics.append(
            {
                "category": label,
                "eligible_records": len(payload["evidence"]),
                "model_items": model_items,
                "cards": len(category_cards),
                "fallback_cards": max(0, len(category_cards) - model_items),
                **model_usage,
            }
        )
    manifest = state.build_coverage_manifest(
        issue_date,
        collection_mode=str(evidence["collection_mode"]),
        collection_completed_at_jst=str(evidence["checked_at_jst"]),
        evidence_sha256="0" * 64,
    )
    state.validate_issue_state(
        {"issue_date": issue_date, "cards": cards, "coverage_manifest": manifest},
        evidence_bundle=evidence,
    )
    facts = [
        fact
        for card in cards
        for fact in card["detail"]["summary_basis"]["confirmed_facts"]
    ]
    duplicate_pairs = sum(
        state.same_material_event(left["title"], right["title"])
        for index, left in enumerate(cards)
        for right in cards[index + 1 :]
        if left["category"] == right["category"]
    )
    return {
        "model": model,
        **usage,
        "weighted_token_units": (
            usage["prompt_tokens"] * (0.2 if model == "openai/gpt-4.1" else 0.04)
            + usage["completion_tokens"] * (0.8 if model == "openai/gpt-4.1" else 0.16)
        ),
        "cards": len(cards),
        "facts": len(facts),
        "duplicate_pairs": duplicate_pairs,
        "fallback_cards": sum(item.get("fallback_cards", 0) for item in category_metrics),
        **baseline_recall(baseline_cards, cards),
        "categories": category_metrics,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required")
    base = ROOT / "state" / args.issue_date
    evidence_path = base / "evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    baseline = json.loads((base / "issue.json").read_text(encoding="utf-8"))
    report = {
        "issue_date": args.issue_date,
        "evidence_sha256": evidence_store.bundle_sha256(evidence_path),
        "models": [
            benchmark_model(model, args.issue_date, evidence, baseline["cards"], token)
            for model in ("openai/gpt-4.1", "openai/gpt-4.1-mini")
        ],
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
