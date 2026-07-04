#!/usr/bin/env python3
"""Resolve the one model chain used for evidence extraction."""

from __future__ import annotations

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

EDITOR_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
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
                    "watch_topic_id": {"type": "string"},
                    "title": {"type": "string"},
                    "topic_value_class": {
                        "type": "string",
                        "enum": TOPIC_VALUE_CLASSES,
                    },
                    "priority_class": {
                        "type": "string",
                        "enum": ["top", "priority", "standard"],
                    },
                },
                "required": [
                    "summary_points",
                    "watch_topic_id",
                    "title",
                    "topic_value_class",
                    "priority_class",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}

SYSTEM_PROMPT = """Edit supplied NIGHT SIGNAL evidence into reader-facing Japanese updates.
Return JSON matching the supplied schema. Assign every supplied evidence id to exactly
one returned item and cite it in each summary point it supports. Merge ids only when
they report the same event; never merge different events and never omit an id.

For each item, write one concise title and ordered summary_points. Each point is one
reader-facing sentence plus the evidence ids that support it. Together the points are
the necessary-and-sufficient summary and the confirmed facts; do not create a second
prose representation. Use one point for one supported fact and add points only when they
carry additional material information. Preserve what a reader needs to understand the
update, including an unfamiliar entity's source-stated role, the concrete change,
mechanism or scope, names, quantities, timing, conditions, and results when supplied.
Do not omit a material fact merely to shorten the summary.

Do not repeat the title or a point in different words.
Do not add publisher metadata, generic importance or impact claims, common knowledge,
unsupported background, inferred unknowns, or follow-up boilerplate. For analysis or
commentary, identify it in the title and include both its concrete evidence and its
attributed conclusion. Use only the supplied evidence; never invent facts or certainty."""


class ModelRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        rate_limited: bool = False,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited
        self.retry_after = retry_after


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
) -> dict[str, Any]:
    """Request one schema-constrained editorial result from GitHub Models."""
    errors: list[str] = []
    rate_limit_waits: list[int] = []
    timeout = int(os.getenv("NIGHT_SIGNAL_MODEL_TIMEOUT_SECONDS", DEFAULT_TIMEOUT_SECONDS))
    retries = int(os.getenv("NIGHT_SIGNAL_MODEL_RETRIES", DEFAULT_RETRIES))
    max_tokens = int(os.getenv("NIGHT_SIGNAL_MODEL_MAX_TOKENS", DEFAULT_MAX_TOKENS))
    payload = {
        "model": model_name or extraction_model(),
        "messages": messages,
        "temperature": 0.1,
        "max_tokens": max_tokens,
        "response_format": {
            "type": "json_schema",
            "json_schema": {
                "name": "night_signal_editor_result",
                "strict": True,
                "schema": EDITOR_RESPONSE_SCHEMA,
            },
        },
    }
    encoded_payload = json.dumps(payload, separators=(",", ":")).encode("utf-8")
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
                if not isinstance(result, dict) or not isinstance(result.get("items"), list):
                    raise ValueError("model result does not match the editor response shape")
            except (json.JSONDecodeError, ValueError) as exc:
                raise ModelRequestError(
                    "GitHub Models returned a response outside the strict editor schema"
                ) from exc
            return result
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                raise ModelRequestError(
                    f"GitHub Models request failed with HTTP {exc.code}"
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
    item_schema = EDITOR_RESPONSE_SCHEMA["properties"]["items"]["items"]
    required_fields = {"summary_points"}
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
    print("NIGHT SIGNAL MODELS PASSED")


if __name__ == "__main__":
    self_test()
