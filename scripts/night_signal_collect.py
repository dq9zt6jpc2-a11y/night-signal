#!/usr/bin/env python3
"""Collect NIGHT SIGNAL source observations with OpenAI Responses web search.

This script owns the missing transition from collection_plan.json to
observations.jsonl. It does not decide publication value and it does not render
articles. Its only job is to close observation slots with schema-valid source
evidence.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import hashlib
import json
import os
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import night_signal_models as models
import night_signal_state as state


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_ROOT = ROOT / "state"
RESPONSES_URL = os.getenv("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses")
COLLECTION_SWEEP_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "needs_extended_research",
        "extended_research_reason",
        "findings",
        "observations",
    ],
    "properties": {
        "needs_extended_research": {"type": "boolean"},
        "extended_research_reason": {"type": ["string", "null"]},
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": [
                    "title",
                    "url",
                    "published_date",
                    "summary",
                    "watch_topic_ids",
                    "finding_state",
                ],
                "properties": {
                    "title": {"type": "string"},
                    "url": {"type": "string"},
                    "published_date": {"type": ["string", "null"]},
                    "summary": {"type": "string"},
                    "watch_topic_ids": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "finding_state": {
                        "type": "string",
                        "enum": [
                            "fresh_update",
                            "near_miss",
                            "background",
                            "source_unavailable",
                        ],
                    },
                },
            },
        },
        "observations": {
            "type": "array",
            "items": state.SOURCE_OBSERVATION_SCHEMA,
        }
    },
}

SYSTEM_PROMPT = """You collect NIGHT SIGNAL category sweeps.

Return exactly one JSON object that matches the provided collection_sweep
schema. Do not write articles or decide publication value.

Rules:
- Search once across the whole category and information route, then return one
  observation for every item in watch_topics. Do not repeat the same search for
  each watch topic.
- Preserve the useful pre-summary information in findings. Record every
  distinct fresh update, near miss, relevant background result, and unavailable
  direct source that influenced the sweep. Do not collapse several URLs into
  one representative finding.
- Treat findings as the broad headline surface for the reader. Capture every
  source-backed headline candidate that could change what the reader may want
  to inspect, including cross-topic or outside-frontier material changes. The
  synthesis step will decide depth, but collection must not hide plausible
  headline topics.
- For web sweeps, return at least two distinct findings for every watch topic.
  For sns_x and youtube sweeps, return at least one finding for every watch
  topic. One finding may cover multiple topics when the source genuinely does.
- Every finding must use a direct source URL, concrete Japanese summary, source
  date when available, and all applicable watch_topic_ids.
- Inspect every seed source target exactly once during the sweep. Copy its
  closure result into every returned observation so downstream slot validation
  remains deterministic.
- Every source_target_result must contain checked_at_jst and
  verification_method. Use responses_web_search only when the URL is present in
  the web_search source trace. Use unavailable with source_unavailable when the
  source could not be verified. Never mark a seed URL observed merely because
  it was listed in the task.
- Every returned observation must include at least one observed_live target
  from this run. Cached results may supplement but cannot close the daily slot.
- Use agentic web search to discover current direct sources beyond the seed
  list. Explicitly search for important developments outside the configured
  watch topics.
- Put every outside-frontier finding in discovery_findings exactly once, on
  the observation whose suggested_watch_topic_id is the closest configured
  topic. Use an empty list on all other observations.
- Focus on the issue date and the latest three calendar days. Older material may
  be background only and must not be described as fresh.
- Routine schedules, repeated background, and extreme personal opinions should
  be recorded as evidence/no-change state, not turned into publication value.
- Use Japanese in evidence_summary and claim text. Keep facts concrete: names,
  dates, numbers, result/status, and source dates.
- If a social page is login-limited or unavailable, record source_unavailable
  for that target with a concrete Japanese evidence_summary.
- Set needs_extended_research=true only when a potentially material finding
  remains unresolved because authoritative sources conflict, all authoritative
  sources are inaccessible, or a major outside-frontier finding lacks enough
  verification. Routine no-change results do not qualify.
- When needs_extended_research=false, extended_research_reason must be null.
"""

EXTENDED_RESEARCH_PROMPT = """Resolve one ambiguous NIGHT SIGNAL category sweep.

Use high-effort agentic web research to resolve only the ambiguity described in
extended_research_reason. Search broadly enough to settle conflicts and verify
important outside-frontier findings, but do not expand into a general report.
Return the complete collection_sweep object for all watch_topics so it can
replace the first pass. Set needs_extended_research=false after the bounded
research pass and preserve the complete findings ledger, source URLs, dates,
claim atoms, and no-change evidence. Do not invent certainty when sources
remain unavailable or conflict.
"""


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL COLLECT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def jst_now() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")


def load_plan(issue_date: str, state_root: Path) -> dict[str, Any]:
    path = state_root / issue_date / "collection_plan.json"
    if not path.exists():
        state.write_collection_plan(issue_date, state_root)
    try:
        plan = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid collection plan JSON: {path}: {exc}")
    if not isinstance(plan, dict) or not isinstance(plan.get("tasks"), list):
        fail(f"collection plan must contain tasks: {path}")
    return plan


def selected_tasks(plan: dict[str, Any], *, slot_id: str | None, max_tasks: int | None) -> list[dict[str, Any]]:
    tasks = [task for task in plan["tasks"] if isinstance(task, dict)]
    if slot_id:
        tasks = [task for task in tasks if task.get("slot_id") == slot_id]
        if not tasks:
            fail(f"slot_id not found in collection plan: {slot_id}")
    if max_tasks is not None:
        tasks = tasks[:max_tasks]
    return tasks


def model_for_route(route: str) -> str:
    return models.model_for_route(route)


def reasoning_for_route(route: str) -> dict[str, str]:
    return models.reasoning_for_route(route)


def compact_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def task_payload(task: dict[str, Any]) -> dict[str, Any]:
    route = str(task.get("model_route", ""))
    payload = {
        "model": model_for_route(route),
        "reasoning": reasoning_for_route(route),
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": compact_json(
                    {
                        "task": task,
                        "required_output": "one collection_sweep JSON object",
                        "observed_at_jst": jst_now(),
                    }
                ),
            },
        ],
        "tools": [
            {
                "type": "web_search",
                "search_context_size": "high",
                "external_web_access": True,
                "return_token_budget": "default",
            }
        ],
        "tool_choice": "required",
        "include": ["web_search_call.action.sources"],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "collection_sweep",
                "strict": True,
                "schema": COLLECTION_SWEEP_SCHEMA,
            }
        },
    }
    prompt_cache_key = task.get("prompt_cache_key")
    if isinstance(prompt_cache_key, str) and prompt_cache_key.strip():
        payload["prompt_cache_key"] = prompt_cache_key.strip()
    return payload


def extended_research_payload(
    task: dict[str, Any],
    first_pass: dict[str, Any],
) -> dict[str, Any]:
    return {
        "model": models.model_for_route("extended_research"),
        "reasoning": models.reasoning_for_route("extended_research"),
        "background": True,
        "store": True,
        "max_tool_calls": int(os.getenv("NIGHT_SIGNAL_EXTENDED_RESEARCH_MAX_TOOL_CALLS", "24")),
        "input": [
            {"role": "system", "content": EXTENDED_RESEARCH_PROMPT},
            {
                "role": "user",
                "content": compact_json(
                    {
                        "task": task,
                        "first_pass": first_pass,
                        "required_output": "one complete collection_sweep JSON object",
                        "observed_at_jst": jst_now(),
                    }
                ),
            },
        ],
        "tools": [
            {
                "type": "web_search",
                "search_context_size": "high",
                "external_web_access": True,
                "return_token_budget": "unlimited",
            }
        ],
        "tool_choice": "required",
        "include": ["web_search_call.action.sources"],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "collection_sweep",
                "strict": True,
                "schema": COLLECTION_SWEEP_SCHEMA,
            },
            "verbosity": "low",
        },
    }


def api_key() -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        fail("OPENAI_API_KEY is required for live collection; use --dry-run to write request payloads")
    return key


def call_responses(payload: dict[str, Any], *, retries: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "User-Agent": "night-signal-collector",
    }
    last_error = ""
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(RESPONSES_URL, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            last_error = f"HTTP {exc.code}: {detail[:1000]}"
            if exc.code not in {408, 409, 429, 500, 502, 503, 504}:
                break
        except (urllib.error.URLError, TimeoutError) as exc:
            last_error = str(exc)
        time.sleep(min(60, 2**attempt))
    fail(f"Responses API request failed after {retries} attempt(s): {last_error}")


def retrieve_response(response_id: str) -> dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "User-Agent": "night-signal-collector",
    }
    request = urllib.request.Request(
        f"{RESPONSES_URL.rstrip('/')}/{response_id}",
        headers=headers,
        method="GET",
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.loads(response.read().decode("utf-8"))


def call_background_response(
    payload: dict[str, Any],
    *,
    retries: int,
    poll_seconds: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    response = call_responses(payload, retries=retries)
    response_id = response.get("id")
    if not isinstance(response_id, str) or not response_id:
        fail("background Responses request returned no response id")
    started = time.monotonic()
    while response.get("status") in {"queued", "in_progress"}:
        if time.monotonic() - started > timeout_seconds:
            fail(f"background Responses request timed out: {response_id}")
        time.sleep(max(0.5, poll_seconds))
        try:
            response = retrieve_response(response_id)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError) as exc:
            if time.monotonic() - started > timeout_seconds:
                fail(f"background Responses polling failed: {response_id}: {exc}")
    if response.get("status") != "completed":
        fail(
            f"background Responses request ended in {response.get('status')}: "
            f"{response.get('error') or response.get('incomplete_details')}"
        )
    return response


def output_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    chunks: list[str] = []
    for item in response.get("output", []):
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if isinstance(content, dict) and content.get("type") == "output_text":
                chunks.append(str(content.get("text", "")))
    text = "\n".join(chunk for chunk in chunks if chunk).strip()
    if not text:
        fail("Responses API returned no output_text")
    return text


def parse_sweep(task: dict[str, Any], response: dict[str, Any]) -> dict[str, Any]:
    text = output_text(response)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"collector output was not JSON: {exc}: {text[:500]}")
    if (
        not isinstance(value, dict)
        or not isinstance(value.get("observations"), list)
        or not isinstance(value.get("findings"), list)
    ):
        fail("collector output must be a collection_sweep object")
    needs_extended_research = value.get("needs_extended_research")
    reason = value.get("extended_research_reason")
    if not isinstance(needs_extended_research, bool):
        fail("collector output must contain needs_extended_research boolean")
    if needs_extended_research and (not isinstance(reason, str) or not reason.strip()):
        fail("collector extended research request must contain a concrete reason")
    if not needs_extended_research and reason is not None:
        fail("collector extended_research_reason must be null when escalation is not needed")
    observations = [item for item in value["observations"] if isinstance(item, dict)]
    expected_topics = {
        str(item.get("watch_topic_id"))
        for item in task.get("watch_topics", [])
        if isinstance(item, dict)
    }
    actual_topics = {str(item.get("watch_topic_id")) for item in observations}
    if actual_topics != expected_topics or len(observations) != len(expected_topics):
        fail(
            f"{task.get('slot_id')} sweep topic mismatch: "
            f"missing={sorted(expected_topics - actual_topics)}, extra={sorted(actual_topics - expected_topics)}"
        )
    for observation in observations:
        for key in ("category", "source_role", "channel"):
            if observation.get(key) != task.get(key):
                fail(f"{task.get('slot_id')} observation {key} mismatch")
    traced_urls = web_search_source_urls(response)
    for observation in observations:
        observation_url = str(observation.get("url", ""))
        if (
            observation.get("slot_state") == "observed_live"
            and observation_url not in traced_urls
        ):
            fail(
                f"{task.get('slot_id')} observation URL missing from "
                f"web_search trace: {observation_url}"
            )
        for result in observation.get("source_target_results", []):
            if not isinstance(result, dict):
                fail(f"{task.get('slot_id')} source target result must be an object")
            method = result.get("verification_method")
            state_value = result.get("slot_state")
            url = str(result.get("url", ""))
            if state_value == "observed_live":
                if method != "responses_web_search":
                    fail(f"{task.get('slot_id')} live source must use responses_web_search")
                if url not in traced_urls:
                    fail(f"{task.get('slot_id')} observed source missing from web_search trace: {url}")
            if state_value == "source_unavailable" and method != "unavailable":
                fail(f"{task.get('slot_id')} unavailable source must use unavailable method")
        for finding in observation.get("discovery_findings", []):
            if not isinstance(finding, dict):
                fail(f"{task.get('slot_id')} discovery finding must be an object")
            source_url = str(finding.get("source_url", ""))
            if source_url not in traced_urls:
                fail(
                    f"{task.get('slot_id')} discovery URL missing from "
                    f"web_search trace: {source_url}"
                )
    findings = [item for item in value["findings"] if isinstance(item, dict)]
    required_findings = 2 if task.get("channel") == "web" else 1
    finding_counts = {
        topic_id: len(
            {
                str(finding.get("url"))
                for finding in findings
                if topic_id in finding.get("watch_topic_ids", [])
            }
        )
        for topic_id in expected_topics
    }
    thin_topics = sorted(
        topic_id
        for topic_id, count in finding_counts.items()
        if count < required_findings
    )
    if thin_topics:
        fail(
            f"{task.get('slot_id')} findings ledger lacks distinct URLs for: "
            + ", ".join(thin_topics)
        )
    for finding in findings:
        finding_url = str(finding.get("url", ""))
        if not finding_url.startswith(("http://", "https://")):
            fail(f"{task.get('slot_id')} finding must use a direct URL")
        if finding_url not in traced_urls:
            fail(
                f"{task.get('slot_id')} finding URL missing from "
                f"web_search trace: {finding_url}"
            )
        finding_topics = {
            str(topic_id) for topic_id in finding.get("watch_topic_ids", [])
        }
        if not finding_topics or not finding_topics <= expected_topics:
            fail(f"{task.get('slot_id')} finding uses an unknown watch topic")
    return {
        "needs_extended_research": needs_extended_research,
        "extended_research_reason": reason,
        "findings": findings,
        "observations": observations,
    }


def web_search_source_urls(response: dict[str, Any]) -> set[str]:
    urls: set[str] = set()
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "web_search_call":
            continue
        action = item.get("action")
        if not isinstance(action, dict):
            continue
        for source in action.get("sources", []):
            if not isinstance(source, dict):
                continue
            url = source.get("url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                urls.add(url)
    return urls


def web_search_trace(
    task: dict[str, Any],
    response: dict[str, Any],
    *,
    stage: str = "initial",
    parent_response_id: str | None = None,
    escalation_reason: str | None = None,
) -> dict[str, Any]:
    raw_web_search_sources: list[Any] = []
    web_search_calls: list[dict[str, Any]] = []
    for item in response.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "web_search_call":
            continue
        action = item.get("action")
        if not isinstance(action, dict):
            action = {}
        sources = action.get("sources")
        if isinstance(sources, list):
            raw_web_search_sources.extend(sources)
        web_search_calls.append(
            {
                "id": item.get("id"),
                "status": item.get("status"),
                "action_type": action.get("type"),
                "query": action.get("query"),
                "queries": action.get("queries"),
                "sources_count": len(sources) if isinstance(sources, list) else 0,
            }
        )
    return {
        "issue_date": task.get("issue_date"),
        "slot_id": task.get("slot_id"),
        "category": task.get("category"),
        "watch_topic_ids": [
            item.get("watch_topic_id")
            for item in task.get("watch_topics", [])
            if isinstance(item, dict)
        ],
        "source_role": task.get("source_role"),
        "channel": task.get("channel"),
        "model_route": task.get("model_route"),
        "stage": stage,
        "prompt_cache_key": task.get("prompt_cache_key"),
        "response_id": response.get("id"),
        "parent_response_id": parent_response_id,
        "escalation_reason": escalation_reason,
        "response_status": response.get("status"),
        "web_search_calls": web_search_calls,
        "raw_web_search_sources": raw_web_search_sources,
        "usage": response.get("usage"),
    }


def append_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_jsonl(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
        encoding="utf-8",
    )


def task_signature(task: dict[str, Any]) -> str:
    encoded = json.dumps(task, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def collection_part_path(state_dir: Path, task: dict[str, Any]) -> Path:
    slot_id = str(task.get("slot_id", "unknown"))
    safe_slot_id = "".join(char if char.isalnum() or char in "-_" else "_" for char in slot_id)
    return state_dir / "collection_parts" / f"{safe_slot_id}.json"


def write_collection_part(
    state_dir: Path,
    task: dict[str, Any],
    sweep: dict[str, Any],
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    value = {
        "version": 1,
        "issue_date": task.get("issue_date"),
        "slot_id": task.get("slot_id"),
        "task_signature": task_signature(task),
        "completed_at_jst": jst_now(),
        "sweep": sweep,
        "traces": traces,
    }
    path = collection_part_path(state_dir, task)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return value


def load_collection_part(state_dir: Path, task: dict[str, Any]) -> dict[str, Any] | None:
    path = collection_part_path(state_dir, task)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(value, dict)
        or value.get("issue_date") != task.get("issue_date")
        or value.get("slot_id") != task.get("slot_id")
        or value.get("task_signature") != task_signature(task)
        or not isinstance(value.get("sweep"), dict)
        or not isinstance(value.get("traces"), list)
    ):
        return None
    return value


def self_test() -> None:
    fake_task = {
        "issue_date": "2099-01-01",
        "slot_id": "openai-product-social",
        "category": "OpenAI",
        "watch_topics": [
            {
                "watch_topic_id": "product_release",
                "search_terms": ["OpenAI", "product", "release"],
                "required_channels": ["web", "sns_x", "youtube"],
            }
        ],
        "source_role": "social_or_video_signal",
        "channel": "sns_x",
        "model_route": "small_structured_extractor",
        "source_targets": [
            {"label": "OpenAI X", "url": "https://x.com/OpenAI", "channel": "sns_x"},
            {"label": "OpenAI Instagram", "url": "https://www.instagram.com/openai/", "channel": "instagram"},
        ],
        "search_queries": ["OpenAI product release latest 2099-01-01"],
        "prompt_cache_key": "night-signal-source-observation-small-structured-extractor-social-or-video-signal-sns-x",
        "acceptance": {"must_record": ["source_target_results_for_every_seed_target"]},
    }
    payload = task_payload(fake_task)
    text_format = payload["text"]["format"]
    if text_format["type"] != "json_schema" or text_format["schema"] != COLLECTION_SWEEP_SCHEMA:
        fail("collector must use collection sweep structured output schema")
    if payload["model"] != models.model_for_route("small_structured_extractor"):
        fail("collector default model must come from the configured route")
    if payload["reasoning"].get("effort") not in {"low", "medium", "high"}:
        fail("collector must set a bounded reasoning effort for web search")
    user_content = payload["input"][1]["content"]
    if "source_target_results_for_every_seed_target" not in user_content:
        fail("collector prompt must preserve source target result acceptance")
    if payload["tools"][0]["type"] != "web_search":
        fail("collector must use Responses web_search tool")
    if payload["tools"][0].get("external_web_access") is not True:
        fail("collector must use live external web access")
    if payload["tools"][0].get("return_token_budget") != "default":
        fail("collector must bound returned web-search tokens by default")
    if payload["tool_choice"] != "required":
        fail("collector must require web search for live observation tasks")
    if payload.get("prompt_cache_key") != "night-signal-source-observation-small-structured-extractor-social-or-video-signal-sns-x":
        fail("collector must pass collection plan prompt_cache_key to Responses")
    if "\n" in user_content:
        fail("collector user payload must stay compact to avoid wasting input tokens")
    extended = extended_research_payload(
        fake_task,
        {
            "needs_extended_research": True,
            "extended_research_reason": "公式資料と報道の数値が一致しない",
            "findings": [],
            "observations": [],
        },
    )
    if (
        extended.get("background") is not True
        or extended.get("store") is not True
        or extended["tools"][0].get("return_token_budget") != "unlimited"
        or extended["reasoning"].get("effort") not in {"high", "xhigh"}
    ):
        fail("extended research must use bounded background high-effort web research")
    trace = web_search_trace(fake_task, {"id": "resp_test", "output": [{"type": "web_search_call", "id": "ws_test", "status": "completed", "action": {"type": "search", "query": "OpenAI", "sources": [{"url": "https://openai.com/"}]}}]})
    if not trace["raw_web_search_sources"] or trace["web_search_calls"][0]["sources_count"] != 1:
        fail("collector must preserve raw web_search sources")
    if web_search_source_urls({"output": [{"type": "web_search_call", "action": {"sources": [{"url": "https://openai.com/"}]}}]}) != {"https://openai.com/"}:
        fail("collector must expose trace URLs for observation verification")
    with tempfile.TemporaryDirectory() as temp_dir:
        part = write_collection_part(
            Path(temp_dir),
            fake_task,
            {
                "needs_extended_research": False,
                "extended_research_reason": None,
                "findings": [],
                "observations": [],
            },
            [trace],
        )
        loaded = load_collection_part(Path(temp_dir), fake_task)
        if loaded != part:
            fail("collector must round-trip durable slot checkpoints")
        changed_task = dict(fake_task)
        changed_task["search_queries"] = ["changed"]
        if load_collection_part(Path(temp_dir), changed_task) is not None:
            fail("collector must invalidate a checkpoint when its task changes")
    print("NIGHT SIGNAL COLLECTOR PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=state.jst_today())
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--slot-id")
    parser.add_argument("--max-tasks", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--max-extended-research", type=int, default=3)
    parser.add_argument("--background-poll-seconds", type=float, default=3.0)
    parser.add_argument("--background-timeout-seconds", type=int, default=1200)
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0

    plan = load_plan(args.issue_date, args.state_root)
    tasks = selected_tasks(plan, slot_id=args.slot_id, max_tasks=args.max_tasks)
    state_dir = args.state_root / args.issue_date
    if args.dry_run:
        write_jsonl(state_dir / "collection_requests.jsonl", [task_payload(task) for task in tasks])
        print(json.dumps({"issue_date": args.issue_date, "requests": len(tasks)}, ensure_ascii=False, indent=2))
        return 0

    def collect_task(index_and_task: tuple[int, dict[str, Any]]) -> tuple[int, dict[str, Any], dict[str, Any], dict[str, Any]]:
        index, task = index_and_task
        if not args.quiet:
            print(f"collecting {index}/{len(tasks)} {task.get('slot_id')}", file=sys.stderr)
        response = call_responses(task_payload(task), retries=args.retries)
        return index, task, parse_sweep(task, response), web_search_trace(task, response)

    parts_by_slot: dict[str, dict[str, Any]] = {}
    reused_parts = 0
    pending: list[tuple[int, dict[str, Any]]] = []
    for index, task in enumerate(tasks, start=1):
        part = load_collection_part(state_dir, task) if args.resume else None
        if part is None:
            pending.append((index, task))
        else:
            parts_by_slot[str(task.get("slot_id"))] = part
            reused_parts += 1

    escalations_used = 0
    first_error: BaseException | None = None
    workers = max(1, min(args.workers, len(pending))) if pending else 1
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(collect_task, item): item
            for item in pending
        }
        for future in concurrent.futures.as_completed(futures):
            try:
                _, task, sweep, trace = future.result()
                part_traces = [trace]
                if (
                    sweep["needs_extended_research"]
                    and escalations_used < max(0, args.max_extended_research)
                ):
                    reason = str(sweep["extended_research_reason"])
                    if not args.quiet:
                        print(f"extended research {task.get('slot_id')}: {reason}", file=sys.stderr)
                    response = call_background_response(
                        extended_research_payload(task, sweep),
                        retries=args.retries,
                        poll_seconds=args.background_poll_seconds,
                        timeout_seconds=args.background_timeout_seconds,
                    )
                    parent_response_id = str(trace.get("response_id") or "")
                    sweep = parse_sweep(task, response)
                    part_traces.append(
                        web_search_trace(
                            task,
                            response,
                            stage="extended_research",
                            parent_response_id=parent_response_id or None,
                            escalation_reason=reason,
                        )
                    )
                    escalations_used += 1
                part = write_collection_part(state_dir, task, sweep, part_traces)
                parts_by_slot[str(task.get("slot_id"))] = part
            except BaseException as exc:
                if first_error is None:
                    first_error = exc
    if first_error is not None:
        raise first_error

    observations: list[dict[str, Any]] = []
    findings: list[dict[str, Any]] = []
    traces: list[dict[str, Any]] = []
    for task in tasks:
        part = parts_by_slot.get(str(task.get("slot_id")))
        if part is None:
            fail(f"collection checkpoint missing after collection: {task.get('slot_id')}")
        sweep = part["sweep"]
        traces.extend(part["traces"])
        for finding in sweep["findings"]:
            findings.append(
                {
                    **finding,
                    "issue_date": args.issue_date,
                    "slot_id": task.get("slot_id"),
                    "category": task.get("category"),
                    "source_role": task.get("source_role"),
                    "channel": task.get("channel"),
                    "observed_at_jst": part.get("completed_at_jst") or jst_now(),
                }
            )
        observations.extend(sweep["observations"])

    output = state_dir / "observations.jsonl"
    if args.replace:
        write_jsonl(output, observations)
        write_jsonl(state_dir / "findings.jsonl", findings)
        write_jsonl(state_dir / "source_traces.jsonl", traces)
    else:
        append_jsonl(output, observations)
        append_jsonl(state_dir / "findings.jsonl", findings)
        append_jsonl(state_dir / "source_traces.jsonl", traces)
    if args.max_tasks is None and args.slot_id is None:
        frontier = state.build_frontier(state.read_json(state.CONFIG_PATH))
        state.validate_observation_records(observations, frontier)
    print(
        json.dumps(
            {
                "issue_date": args.issue_date,
                "observations": len(observations),
                "findings": len(findings),
                "extended_research_runs": escalations_used,
                "reused_slot_checkpoints": reused_parts,
                "path": str(output),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
