#!/usr/bin/env python3
"""Collect NIGHT SIGNAL source observations with OpenAI Responses web search.

This script owns the missing transition from collection_plan.json to
observations.jsonl. It does not decide publication value and it does not render
articles. Its only job is to close observation slots with schema-valid source
evidence.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import night_signal_state as state


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_ROOT = ROOT / "state"
RESPONSES_URL = os.getenv("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses")
DEFAULT_ROUTE_MODELS = {
    "small_structured_extractor": "gpt-5-mini",
    "small_structured_extractor_then_frontier_reasoning_if_ambiguous": "gpt-5-mini",
    "frontier_reasoning_model": "gpt-5.2",
}
ROUTE_MODEL_ENV = {
    "small_structured_extractor": "NIGHT_SIGNAL_MODEL_SMALL_STRUCTURED_EXTRACTOR",
    "small_structured_extractor_then_frontier_reasoning_if_ambiguous": "NIGHT_SIGNAL_MODEL_SMALL_THEN_FRONTIER",
    "frontier_reasoning_model": "NIGHT_SIGNAL_MODEL_FRONTIER_REASONING",
}
SYSTEM_PROMPT = """You collect NIGHT SIGNAL source observations.

Return exactly one JSON object that matches the provided source_observation
schema. Do not write an article. Do not decide whether the topic should be
published. Do not use search-result pages as source URLs.

Rules:
- Inspect every seed source target in source_targets. Every target must appear
  in source_target_results with observed_live, source_unavailable,
  reused_from_cache, or not_applicable.
- Use web search to discover additional current direct sources, but do not let
  discovered sources replace seed target checks.
- Focus on the issue date and the latest three calendar days. Older material may
  be background only and must not be described as fresh.
- Routine schedules, repeated background, and extreme personal opinions should
  be recorded as evidence/no-change state, not turned into publication value.
- Use Japanese in evidence_summary and claim text. Keep facts concrete: names,
  dates, numbers, result/status, and source dates.
- If a social page is login-limited or unavailable, record source_unavailable
  for that target with a concrete Japanese evidence_summary.
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
    env_key = ROUTE_MODEL_ENV.get(route)
    if env_key and os.getenv(env_key):
        return os.environ[env_key]
    if os.getenv("NIGHT_SIGNAL_MODEL"):
        return os.environ["NIGHT_SIGNAL_MODEL"]
    return DEFAULT_ROUTE_MODELS.get(route, DEFAULT_ROUTE_MODELS["small_structured_extractor"])


def reasoning_for_route(route: str) -> dict[str, str]:
    effort = os.getenv("NIGHT_SIGNAL_REASONING_EFFORT")
    if effort:
        return {"effort": effort}
    if route == "frontier_reasoning_model":
        return {"effort": "medium"}
    return {"effort": "low"}


def task_payload(task: dict[str, Any]) -> dict[str, Any]:
    schema = dict(state.SOURCE_OBSERVATION_SCHEMA)
    route = str(task.get("model_route", ""))
    return {
        "model": model_for_route(route),
        "reasoning": reasoning_for_route(route),
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "task": task,
                        "required_output": "one source_observation JSON object",
                        "observed_at_jst": jst_now(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ],
        "tools": [{"type": "web_search", "search_context_size": "medium"}],
        "tool_choice": "auto",
        "include": ["web_search_call.action.sources"],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "source_observation",
                "strict": True,
                "schema": schema,
            }
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


def parse_observation(response: dict[str, Any]) -> dict[str, Any]:
    text = output_text(response)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"collector output was not JSON: {exc}: {text[:500]}")
    if not isinstance(value, dict):
        fail("collector output must be a JSON object")
    return value


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


def self_test() -> None:
    fake_task = {
        "issue_date": "2099-01-01",
        "slot_id": "openai-product-social",
        "category": "OpenAI",
        "watch_topic_id": "product_release",
        "source_role": "social_or_video_signal",
        "channel": "sns_x",
        "model_route": "small_structured_extractor",
        "source_targets": [
            {"label": "OpenAI X", "url": "https://x.com/OpenAI", "channel": "sns_x"},
            {"label": "OpenAI Instagram", "url": "https://www.instagram.com/openai/", "channel": "instagram"},
        ],
        "search_queries": ["OpenAI product release latest 2099-01-01"],
        "acceptance": {"must_record": ["source_target_results_for_every_seed_target"]},
    }
    payload = task_payload(fake_task)
    text_format = payload["text"]["format"]
    if text_format["type"] != "json_schema" or text_format["schema"] != state.SOURCE_OBSERVATION_SCHEMA:
        fail("collector must use source observation structured output schema")
    if payload["model"] not in set(DEFAULT_ROUTE_MODELS.values()):
        fail("collector default model must be one of the current route defaults")
    if payload["reasoning"].get("effort") not in {"low", "medium", "high"}:
        fail("collector must set a bounded reasoning effort for web search")
    user_content = payload["input"][1]["content"]
    if "source_target_results_for_every_seed_target" not in user_content:
        fail("collector prompt must preserve source target result acceptance")
    if payload["tools"][0]["type"] != "web_search":
        fail("collector must use Responses web_search tool")
    print("NIGHT SIGNAL COLLECTOR PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=state.jst_today())
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--slot-id")
    parser.add_argument("--max-tasks", type=int)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--retries", type=int, default=3)
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

    observations: list[dict[str, Any]] = []
    for index, task in enumerate(tasks, start=1):
        print(f"collecting {index}/{len(tasks)} {task.get('slot_id')}", file=sys.stderr)
        observations.append(parse_observation(call_responses(task_payload(task), retries=args.retries)))

    output = state_dir / "observations.jsonl"
    if args.replace:
        write_jsonl(output, observations)
    else:
        append_jsonl(output, observations)
    if args.max_tasks is None and args.slot_id is None:
        frontier = state.build_frontier(state.read_json(state.CONFIG_PATH))
        state.validate_observation_records(observations, frontier)
    print(json.dumps({"issue_date": args.issue_date, "observations": len(observations), "path": str(output)}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
