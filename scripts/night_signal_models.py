#!/usr/bin/env python3
"""Resolve the one model chain used for evidence extraction."""

from __future__ import annotations

import copy
import json
import os
import re
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "night_signal_models.json"
MODELS_URL = "https://models.github.ai/inference/chat/completions"
DEFAULT_TIMEOUT_SECONDS = 90
DEFAULT_RETRIES = 3
DEFAULT_MAX_TOKENS = 8000
USER_AGENT = (
    "Mozilla/5.0 (compatible; NightSignalBot/1.0; "
    "+https://dq9zt6jpc2-a11y.github.io/night-signal/)"
)

TOPIC_VALUE_CLASSES = [
    "decision_or_policy",
    "market_or_financial_impact",
    "technical_or_product_shift",
    "operational_status_change",
    "event_result_or_outcome",
    "material_schedule_change",
    "risk_or_safety_signal",
    "cultural_or_audience_signal",
]

EDITOR_ITEM_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "summary_points": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                },
                "required": ["text", "evidence_ids"],
                "additionalProperties": False,
            },
            "minItems": 1,
        },
        "title": {"type": "string"},
        "topic_value_class": {
            "type": "string",
            "enum": TOPIC_VALUE_CLASSES,
        },
        "priority_class": {
            "type": "string",
            "enum": ["top", "priority", "standard"],
        },
        "change_class": {
            "type": "string",
            "enum": [
                "new_event",
                "material_update",
                "new_analysis_of_existing_fact",
            ],
        },
    },
    "required": [
        "summary_points",
        "title",
        "topic_value_class",
        "priority_class",
        "change_class",
    ],
    "additionalProperties": False,
}

EXCLUDED_EVIDENCE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "evidence_id": {"type": "string"},
        "reason": {
            "type": "string",
            "enum": [
                "duplicate_or_same_event",
                "background_or_navigation",
                "wrong_entity_or_category",
                "no_material_update",
            ],
        },
    },
    "required": ["evidence_id", "reason"],
    "additionalProperties": False,
}

EDITOR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "event_id": {"type": "string"},
                    "evidence_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                        "minItems": 1,
                    },
                    "items": {
                        "type": "array",
                        "items": EDITOR_ITEM_SCHEMA,
                    },
                    "excluded_evidence": {
                        "type": "array",
                        "items": EXCLUDED_EVIDENCE_SCHEMA,
                    },
                },
                "required": [
                    "event_id",
                    "evidence_ids",
                    "items",
                    "excluded_evidence",
                ],
                "additionalProperties": False,
            },
            "minItems": 1,
        }
    },
    "required": ["events"],
    "additionalProperties": False,
}


def editor_response_schema(event_ids: list[str]) -> dict[str, Any]:
    if not event_ids or len(event_ids) != len(set(event_ids)):
        raise ValueError("editor response schema requires unique event ids")
    schema = copy.deepcopy(EDITOR_RESPONSE_SCHEMA)
    events_schema = schema["properties"]["events"]
    events_schema["minItems"] = len(event_ids)
    events_schema["maxItems"] = len(event_ids)
    events_schema["items"]["properties"]["event_id"]["enum"] = event_ids
    return schema


SYSTEM_PROMPT = """Turn supplied NIGHT SIGNAL evidence into Japanese important updates.
Return exactly one event result for every supplied event id. Within each event, every
evidence id must be either used by a summary point or listed in excluded_evidence. Event
ids are hard boundaries: never merge or move evidence across them. Reports within one event
may be split into multiple items when they state distinct changes.
Copy every supplied Evidence id for that event into event.evidence_ids exactly once, then
also account for each id in an item's summary_points or in excluded_evidence.
previous_updates are novelty context only, never Evidence: do not cite, summarize, or copy
facts from them. Use them only to exclude a report that adds no new source-backed change.

For each update, create one title and the ordered summary_points needed to understand it.
Keep all source-backed material facts even when the result becomes longer: the subject
and an unfamiliar subject's stated role, the concrete change, scope or mechanism, names,
numbers, dates, conditions, reasons, and results when they matter. Each point must add
information beyond the title. Do not target a fixed length.

For every point, cite every supporting evidence id. Exact support spans are recovered
deterministically from those evidence records after generation; do not reproduce source quotes.

Evidence marked evidence_depth=headline has no verified body beyond its source headline.
It is still usable when that headline states multiple concrete facts: make the public title
shorter and put only the remaining headline-stated facts in summary_points. Never infer a
missing detail or repeat the same fact in title and summary.
If the headline cannot support a distinct summary fact, exclude it as no_material_update.

Exclude only duplicate reports, navigation/background, wrong category/entity, or no
material update. A newly published analysis of an old fact is publishable only when the
new question, evidence, and attributed conclusion are stated; otherwise exclude it.
Do not repeat the title or a point, and do not add publisher metadata, generic importance,
common knowledge, unsupported impact or background, inferred unknowns, or follow-up
boilerplate. Use only supplied evidence."""


class ModelRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        rate_limited: bool = False,
        retry_after: int | None = None,
        status_code: int | None = None,
    ) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited
        self.retry_after = retry_after
        self.status_code = status_code


def load_config() -> dict[str, Any]:
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("extraction"), dict):
        raise ValueError("night_signal_models must define extraction")
    return value


def extraction_models() -> list[str]:
    config = load_config()["extraction"]
    override = os.getenv("NIGHT_SIGNAL_MODEL")
    primary = override or config.get("model")
    if not isinstance(primary, str) or not primary:
        raise ValueError("extraction model is missing")
    quality_model = config.get("quality_model")
    fallbacks = config.get("fallback_models", [])
    if not isinstance(fallbacks, list):
        raise ValueError("fallback_models must be a list")
    return list(
        dict.fromkeys(
            [
                primary,
                *([quality_model] if isinstance(quality_model, str) and quality_model else []),
                *[value for value in fallbacks if isinstance(value, str) and value],
            ]
        )
    )


def extraction_model() -> str:
    return extraction_models()[0]


def routed_models(*, quality_required: bool) -> list[str]:
    config = load_config()["extraction"]
    routine = extraction_model()
    quality = config.get("quality_model")
    fallbacks = [
        value
        for value in config.get("fallback_models", [])
        if isinstance(value, str) and value
    ]
    if quality_required and isinstance(quality, str) and quality:
        return list(dict.fromkeys([quality, *fallbacks]))
    return list(
        dict.fromkeys(
            [routine, *([quality] if isinstance(quality, str) and quality else []), *fallbacks]
        )
    )


def request(
    token: str,
    messages: list[dict[str, str]],
    *,
    model_name: str | None = None,
    retry_wait_cap: int = 120,
    request_label: str = "",
    response_schema: dict[str, Any] | None = None,
    response_schema_name: str = "night_signal_editor_result",
    max_output_tokens: int | None = None,
) -> dict[str, Any]:
    """Request one schema-constrained editorial result from GitHub Models."""
    errors: list[str] = []
    rate_limit_waits: list[int] = []
    timeout = int(os.getenv("NIGHT_SIGNAL_MODEL_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    retries = int(os.getenv("NIGHT_SIGNAL_MODEL_RETRIES", DEFAULT_RETRIES))
    configured_max_tokens = int(
        os.getenv("NIGHT_SIGNAL_MODEL_MAX_TOKENS", DEFAULT_MAX_TOKENS)
    )
    max_tokens = (
        min(configured_max_tokens, max_output_tokens)
        if isinstance(max_output_tokens, int) and max_output_tokens > 0
        else configured_max_tokens
    )
    schema = response_schema or EDITOR_RESPONSE_SCHEMA
    payload = {
        "model": model_name or extraction_model(),
        "messages": messages,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": response_schema_name,
                "strict": True,
                "schema": schema,
            },
        },
    }
    if not str(payload["model"]).startswith("openai/gpt-5"):
        payload["temperature"] = 0.1
    encoded_payload = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    for attempt in range(retries):
        http_request = urllib.request.Request(
            MODELS_URL,
            data=encoded_payload,
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2026-03-10",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(http_request, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
            usage = value.get("usage", {})
            if isinstance(usage, dict):
                print(
                    json.dumps(
                        {
                            "phase": "model_usage",
                            **({"category": request_label} if request_label else {}),
                            "model": payload["model"],
                            "prompt_tokens": usage.get("prompt_tokens"),
                            "completion_tokens": usage.get("completion_tokens"),
                            "total_tokens": usage.get("total_tokens"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
            choice = value["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("model content is not a string")
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
            try:
                result = json.loads(content)
                if not isinstance(result, dict):
                    raise ValueError("model result is not an object")
            except (json.JSONDecodeError, ValueError) as exc:
                raise ModelRequestError(
                    "GitHub Models returned a response outside the strict editor schema"
                ) from exc
            return result
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise ModelRequestError(
                    f"GitHub Models request failed with HTTP {exc.code}",
                    status_code=exc.code,
                ) from exc
            retry_after = exc.headers.get("Retry-After")
            try:
                requested_wait = max(1, int(retry_after or "65"))
            except ValueError:
                requested_wait = 65
            rate_limit_waits.append(requested_wait)
            errors.append(
                f"attempt {attempt + 1}: HTTP {exc.code}; retry_after={requested_wait}"
            )
            if requested_wait > retry_wait_cap:
                raise ModelRequestError(
                    "GitHub Models rate limit exceeds the bounded retry window: "
                    + " / ".join(errors),
                    rate_limited=True,
                    retry_after=requested_wait,
                ) from exc
            if attempt < retries - 1:
                time.sleep(min(retry_wait_cap, requested_wait))
        except (KeyError, IndexError, ValueError) as exc:
            raise ModelRequestError(
                f"GitHub Models returned an invalid response envelope: {exc}"
            ) from exc
        except (OSError, TimeoutError) as exc:
            errors.append(f"attempt {attempt + 1}: {type(exc).__name__}: {exc}")
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
    raise ModelRequestError(
        "GitHub Models request failed: " + " / ".join(errors),
        rate_limited=bool(rate_limit_waits),
        retry_after=max(rate_limit_waits, default=None),
    )


def self_test() -> None:
    chain = extraction_models()
    if not chain:
        raise SystemExit("extraction model chain is empty")
    if len(chain) != len(set(chain)):
        raise SystemExit("extraction model chain contains duplicates")
    config = load_config()["extraction"]
    if (
        not os.getenv("NIGHT_SIGNAL_MODEL")
        and config.get("quality_model")
        and chain.index(str(config["quality_model"])) == 0
    ):
        raise SystemExit("quality model must be an escalation, not the routine model")
    if routed_models(quality_required=False)[0] != chain[0]:
        raise SystemExit("routine routing must use the routine model first")
    quality = config.get("quality_model")
    if quality and routed_models(quality_required=True)[0] != quality:
        raise SystemExit("quality routing must use the quality model first")
    if quality and extraction_model() in routed_models(quality_required=True)[1:]:
        raise SystemExit("quality routing must not downgrade to the routine model")
    event_schema = EDITOR_RESPONSE_SCHEMA["properties"]["events"]["items"]
    item_schema = event_schema["properties"]["items"]["items"]
    if set(event_schema["required"]) != {
        "event_id",
        "evidence_ids",
        "items",
        "excluded_evidence",
    }:
        raise SystemExit("editor schema does not account for every event result")
    required_fields = {"summary_points", "change_class"}
    if not required_fields <= set(item_schema["properties"]):
        raise SystemExit("editor response schema lacks the canonical summary contract")
    redundant_fields = {
        "summary",
        "confirmed_facts",
        "detail_summary",
        "what_changed",
        "why_it_matters",
        "sources",
    }
    if redundant_fields & set(item_schema["properties"]):
        raise SystemExit("editor response schema contains derived prose fields")
    if item_schema.get("additionalProperties") is not False:
        raise SystemExit("editor response schema must reject undeclared fields")
    point_schema = item_schema["properties"]["summary_points"]["items"]
    if "support_quotes" in point_schema.get("properties", {}):
        raise SystemExit("model schema must not duplicate source text as support quotes")
    bounded_schema = editor_response_schema(["g001", "g002"])
    bounded_events = bounded_schema["properties"]["events"]
    if (
        bounded_events["minItems"] != 2
        or bounded_events["maxItems"] != 2
        or bounded_events["items"]["properties"]["event_id"]["enum"]
        != ["g001", "g002"]
    ):
        raise SystemExit("editor response schema did not bind the input event ids")
    encoded = json.dumps(
        {"text": "日本語の本文"},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if b"\\u65e5" in encoded or "日本語".encode("utf-8") not in encoded:
        raise SystemExit("model payload expands Japanese text into JSON escapes")
    print("NIGHT SIGNAL MODELS PASSED")


if __name__ == "__main__":
    self_test()
