#!/usr/bin/env python3
"""Run a bounded, isolated model comparison for the NIGHT SIGNAL Editor."""

from __future__ import annotations

import argparse
import json
import os
import re
import time
from pathlib import Path
from typing import Any

import night_signal_model_audit as model_audit
import night_signal_models as models
import night_signal_core as core


EVENT_IDS = ["g001", "g002", "g003", "g004"]
EXPECTED_DECISIONS = {
    "g001": {"publish"},
    "g002": {"duplicate_previous_event", "no_material_update"},
    "g003": {"background_or_navigation", "no_material_update"},
    "g004": {"publish"},
}
REQUIRED_FACT_GROUPS = {
    "g001": [("30",), ("Enterprise", "エンタープライズ", "企業向け")],
    "g004": [("26.8",), ("70.9",)],
}


def evaluation_payload() -> dict[str, Any]:
    return {
        "category": "評価用",
        "allowed_watch_topic_ids": ["product", "earnings"],
        "events": [
            {
                "id": "g001",
                "previous_updates": [],
                "evidence": [
                    {
                        "id": "e001",
                        "watch_topic_ids": ["product"],
                        "date": "2099-01-02",
                        "source": "公式発表",
                        "title": "推論APIの高速モードを提供開始",
                        "evidence_depth": "body",
                        "body": (
                            "評価社は2099年1月2日、推論APIの高速モードを提供開始した。"
                            "標準モード比で応答遅延を30%削減し、Enterprise契約で利用できる。"
                        ),
                    }
                ],
            },
            {
                "id": "g002",
                "previous_updates": [
                    {
                        "title": "評価社、監査ログAPIを公開",
                        "summary": "管理者向けに90日分のログを取得できる。",
                    }
                ],
                "evidence": [
                    {
                        "id": "e002",
                        "watch_topic_ids": ["product"],
                        "date": "2099-01-02",
                        "source": "再掲記事",
                        "title": "評価社、監査ログAPIを公開",
                        "evidence_depth": "body",
                        "body": "管理者向けに90日分のログを取得できる。",
                    }
                ],
            },
            {
                "id": "g003",
                "previous_updates": [],
                "evidence": [
                    {
                        "id": "e003",
                        "watch_topic_ids": ["product"],
                        "date": "2099-01-02",
                        "source": "企業紹介",
                        "title": "評価社とは何か",
                        "evidence_depth": "body",
                        "body": "評価社は2015年設立の人工知能研究企業である。",
                    }
                ],
            },
            {
                "id": "g004",
                "previous_updates": [],
                "evidence": [
                    {
                        "id": "e004",
                        "watch_topic_ids": ["earnings"],
                        "date": "2099-01-02",
                        "source": "決算短信",
                        "title": "評価社、第2四半期累計経常利益は26.8億円",
                        "evidence_depth": "body",
                        "body": (
                            "第2四半期累計の経常利益は26.8億円だった。"
                            "通期計画に対する進捗率は70.9%となった。"
                        ),
                    }
                ],
            },
        ],
    }


def event_map(result: dict[str, Any]) -> dict[str, dict[str, Any]]:
    events = result.get("events")
    if not isinstance(events, list):
        return {}
    return {
        str(event.get("event_id")): event
        for event in events
        if isinstance(event, dict) and event.get("event_id")
    }


def validate_result(result: dict[str, Any]) -> list[str]:
    failures: list[str] = []
    by_id = event_map(result)
    payload_events = {
        str(event["id"]): event
        for event in evaluation_payload()["events"]
    }
    if set(by_id) != set(EVENT_IDS):
        failures.append("event_accounting")
        return failures
    for event_id, allowed in EXPECTED_DECISIONS.items():
        event = by_id[event_id]
        decision = str(event.get("decision", ""))
        if decision not in allowed:
            failures.append(f"{event_id}:decision={decision}")
        items = event.get("items")
        if not isinstance(items, list):
            failures.append(f"{event_id}:items")
            continue
        if decision == "publish" and not items:
            failures.append(f"{event_id}:missing_publish_item")
        if decision != "publish" and items:
            failures.append(f"{event_id}:excluded_event_has_items")
        allowed_evidence_id = "e" + event_id[1:]
        support_records = [
            {
                "title": evidence.get("title", ""),
                "excerpt": evidence.get("body", ""),
            }
            for evidence in payload_events[event_id]["evidence"]
        ]
        for item in items:
            if not isinstance(item, dict):
                failures.append(f"{event_id}:invalid_item")
                continue
            copy = json.dumps(item, ensure_ascii=False)
            if not re.search(r"[ぁ-んァ-ヶ一-龠]", copy):
                failures.append(f"{event_id}:not_japanese")
            for point in item.get("summary_points", []):
                if not isinstance(point, dict):
                    failures.append(f"{event_id}:invalid_point")
                    continue
                evidence_ids = point.get("evidence_ids")
                if evidence_ids != [allowed_evidence_id]:
                    failures.append(f"{event_id}:evidence_boundary")
                text = str(point.get("text", ""))
                if text and not core.fact_supported_by_records(
                    text,
                    support_records,
                ):
                    failures.append(f"{event_id}:unsupported_fact")
        item_copy = json.dumps(items, ensure_ascii=False)
        for alternatives in REQUIRED_FACT_GROUPS.get(event_id, []):
            if not any(fragment in item_copy for fragment in alternatives):
                failures.append(
                    f"{event_id}:missing_fact={'|'.join(alternatives)}"
                )
    return sorted(set(failures))


def model_tier(model_id: str) -> str:
    if re.search(r"-(?:nano|luna)$", model_id):
        return "economy"
    if re.search(r"-(?:mini|terra)$", model_id):
        return "balanced"
    return "quality"


def numeric_metric(result: dict[str, Any], name: str, default: int) -> int:
    value = result.get(name)
    return value if isinstance(value, int) and value >= 0 else default


def model_generation(model_id: str) -> tuple[int, int] | None:
    key = model_audit.compatible_model_key(model_id)
    return (key[0], key[1]) if key is not None else None


def recommend_route(
    results: list[dict[str, Any]],
    *,
    routine_baseline: str,
    quality_baseline: str,
) -> dict[str, Any]:
    routine_passed = [
        result for result in results if result.get("routine_passed") is True
    ]
    quality_passed = [
        result for result in results if result.get("quality_passed") is True
    ]
    routine_by_model = {
        str(result.get("model")): result for result in routine_passed
    }
    quality_by_model = {
        str(result.get("model")): result for result in quality_passed
    }
    routine = routine_by_model.get(routine_baseline)
    if routine is not None:
        baseline_tokens = numeric_metric(routine, "total_tokens", 10**9)
        baseline_latency = numeric_metric(routine, "latency_ms", 10**9)
        routine_pool = [routine] + [
            result
            for result in routine_passed
            if str(result.get("model")) != routine_baseline
            and model_tier(str(result.get("model"))) in {"economy", "balanced"}
            and numeric_metric(result, "total_tokens", 10**9)
            <= baseline_tokens * 95 // 100
            and numeric_metric(result, "latency_ms", 10**9)
            <= baseline_latency * 3 // 2
        ]
    else:
        routine_pool = [
            result
            for result in routine_passed
            if model_tier(str(result.get("model"))) in {"economy", "balanced"}
        ]
    if routine_pool:
        routine = min(
            routine_pool,
            key=lambda result: (
                numeric_metric(result, "total_tokens", 10**9),
                numeric_metric(result, "latency_ms", 10**9),
                str(result.get("model")),
            ),
        )
    quality = quality_by_model.get(quality_baseline)
    quality_limit = (
        max(
            numeric_metric(quality, "total_tokens", 0) * 3 // 2,
            numeric_metric(quality, "total_tokens", 0) + 500,
        )
        if quality is not None
        else 10**9
    )
    baseline_generation = model_generation(quality_baseline)
    quality_pool = [quality] if quality is not None else []
    quality_pool.extend(
        result
        for result in quality_passed
        if str(result.get("model")) != quality_baseline
        and model_tier(str(result.get("model"))) == "quality"
        and numeric_metric(result, "total_tokens", 10**9) <= quality_limit
        and (
            baseline_generation is None
            or (
                model_generation(str(result.get("model"))) is not None
                and model_generation(str(result.get("model")))
                > baseline_generation
            )
        )
    )
    if quality_pool:
        quality = max(
            quality_pool,
            key=lambda result: (
                model_audit.compatible_model_key(str(result.get("model")))
                or (0, 0, 0, ""),
                -numeric_metric(result, "total_tokens", 10**9),
            ),
        )
    return {
        "routine_model": str(routine.get("model")) if routine else routine_baseline,
        "quality_model": str(quality.get("model")) if quality else quality_baseline,
        "production_change_authorized": False,
        "reason": "recommendation only; production promotion requires reviewed evidence",
    }


def evaluate_model(token: str, model_id: str) -> dict[str, Any]:
    usage: dict[str, Any] = {}
    started = time.monotonic()
    try:
        result = models.request(
            token,
            [
                {"role": "system", "content": models.SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": json.dumps(
                        evaluation_payload(),
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            ],
            model_name=model_id,
            retry_wait_cap=0,
            request_label=f"model-eval:{model_id}",
            response_schema=models.editor_response_schema(EVENT_IDS),
            response_schema_name="night_signal_model_eval",
            max_output_tokens=4000,
            usage_metrics=usage,
        )
        failures = validate_result(result)
        routine_failures = [
            failure
            for failure in failures
            if failure == "event_accounting" or not failure.startswith("g004:")
        ]
        return {
            "model": model_id,
            "request_succeeded": True,
            "routine_passed": not routine_failures,
            "quality_passed": not failures,
            "passed": not failures,
            "failures": failures,
            "latency_ms": round((time.monotonic() - started) * 1000),
            **usage,
        }
    except models.ModelRequestError as exc:
        return {
            "model": model_id,
            "request_succeeded": False,
            "routine_passed": False,
            "quality_passed": False,
            "passed": False,
            "failures": [f"request:{exc}"],
            "latency_ms": round((time.monotonic() - started) * 1000),
        }


def self_test() -> None:
    valid = {
        "events": [
            {
                "event_id": "g001",
                "decision": "publish",
                "items": [
                    {
                        "title": "評価社が高速モードを開始",
                        "summary_points": [
                            {
                                "text": "応答遅延を30%削減し、Enterprise契約で利用できる。",
                                "evidence_ids": ["e001"],
                            }
                        ],
                    }
                ],
            },
            {"event_id": "g002", "decision": "duplicate_previous_event", "items": []},
            {"event_id": "g003", "decision": "background_or_navigation", "items": []},
            {
                "event_id": "g004",
                "decision": "publish",
                "items": [
                    {
                        "title": "評価社の経常利益は26.8億円",
                        "summary_points": [
                            {"text": "進捗率は70.9%。", "evidence_ids": ["e004"]}
                        ],
                    }
                ],
            },
        ]
    }
    if validate_result(valid):
        raise SystemExit("valid model evaluation fixture was rejected")
    invalid = json.loads(json.dumps(valid, ensure_ascii=False))
    invalid["events"][0]["items"][0]["summary_points"][0]["evidence_ids"] = ["e004"]
    if "g001:evidence_boundary" not in validate_result(invalid):
        raise SystemExit("cross-event evidence escaped model evaluation")
    route = recommend_route(
        [
            {
                "model": "openai/gpt-4o-mini",
                "routine_passed": True,
                "quality_passed": True,
                "total_tokens": 1000,
                "latency_ms": 900,
            },
            {
                "model": "openai/gpt-5-mini",
                "routine_passed": True,
                "quality_passed": False,
                "total_tokens": 800,
                "latency_ms": 800,
            },
            {
                "model": "openai/gpt-4.1-mini",
                "routine_passed": True,
                "quality_passed": True,
                "total_tokens": 900,
                "latency_ms": 700,
            },
            {
                "model": "openai/gpt-5",
                "routine_passed": True,
                "quality_passed": True,
                "total_tokens": 1200,
                "latency_ms": 1000,
            },
        ],
        routine_baseline="openai/gpt-4o-mini",
        quality_baseline="openai/gpt-4.1-mini",
    )
    if route["routine_model"] != "openai/gpt-5-mini":
        raise SystemExit("efficient passing routine model was not recommended")
    if route["quality_model"] != "openai/gpt-5":
        raise SystemExit("newer passing quality model was not recommended")
    conservative_route = recommend_route(
        [
            {
                "model": "openai/gpt-4.1-mini",
                "routine_passed": True,
                "quality_passed": True,
                "total_tokens": 900,
                "latency_ms": 700,
            },
            {
                "model": "openai/gpt-4o",
                "routine_passed": True,
                "quality_passed": True,
                "total_tokens": 800,
                "latency_ms": 600,
            },
        ],
        routine_baseline="openai/gpt-4o-mini",
        quality_baseline="openai/gpt-4.1-mini",
    )
    if conservative_route["quality_model"] != "openai/gpt-4.1-mini":
        raise SystemExit("legacy model replaced the newer quality baseline")
    if route["production_change_authorized"]:
        raise SystemExit("model evaluation authorized an automatic production change")
    print("NIGHT SIGNAL MODEL EVALUATION SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-models", default="[]")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    try:
        candidates = json.loads(args.candidate_models)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"candidate model JSON is invalid: {exc}") from exc
    if not isinstance(candidates, list) or not all(
        isinstance(value, str) for value in candidates
    ):
        raise SystemExit("candidate models must be a JSON array of strings")
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        raise SystemExit("GITHUB_TOKEN is required for isolated model evaluation")
    config = models.load_config()["extraction"]
    routine_baseline = str(config["model"])
    quality_baseline = str(config["quality_model"])
    evaluated_models = list(dict.fromkeys([*models.extraction_models(), *candidates]))
    results = [evaluate_model(token, model_id) for model_id in evaluated_models]
    report = {
        "candidate_models": candidates,
        "evaluated_models": evaluated_models,
        "maximum_model_requests": len(evaluated_models),
        "results": results,
        "recommended_route": recommend_route(
            results,
            routine_baseline=routine_baseline,
            quality_baseline=quality_baseline,
        ),
    }
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    successful_responses = sum(
        1
        for result in results
        if result.get("request_succeeded") is True
    )
    return 0 if successful_responses else 1


if __name__ == "__main__":
    raise SystemExit(main())
