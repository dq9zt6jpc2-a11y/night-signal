#!/usr/bin/env python3
"""Synthesize NIGHT SIGNAL observations into publication state artifacts.

This script owns the transition from completed source observations to
candidates, decisions, cards, and coverage_manifest. It refuses to run on
incomplete observations, so daily publication cannot skip collection closure.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tempfile
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import night_signal_models as models
import night_signal_state as state


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_STATE_ROOT = ROOT / "state"
RESPONSES_URL = os.getenv("OPENAI_RESPONSES_URL", "https://api.openai.com/v1/responses")
DEFAULT_SYNTHESIS_MODEL = models.model_for_route("synthesis")

NO_CHANGE_CHECK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["topic_id", "result", "evidence_urls"],
    "properties": {
        "topic_id": {"type": "string"},
        "result": {"type": "string"},
        "evidence_urls": {"type": "array", "items": {"type": "string"}},
    },
}

CATEGORY_SYNTHESIS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["category", "candidates", "decisions", "cards", "no_change_checks"],
    "properties": {
        "category": {"type": "string"},
        "candidates": {"type": "array", "items": state.CANDIDATE_SCHEMA},
        "decisions": {"type": "array", "items": state.TOPIC_DECISION_SCHEMA},
        "cards": {"type": "array", "items": state.CARD_SCHEMA},
        "no_change_checks": {"type": "array", "items": NO_CHANGE_CHECK_SCHEMA},
    },
}

SYSTEM_PROMPT = """You synthesize NIGHT SIGNAL source observations.

Return exactly one JSON object matching category_synthesis.

Mission:
- Convert closed source observations into reader-facing candidates, decisions,
  cards, and no-change evidence for one category.
- Work like a careful human editor: scan the horizon, form hypotheses about
  what could have changed, triangulate official/independent/social evidence,
  compare with the previous state, then decide what deserves a full article.
- The public issue is a broad headline board plus deeper articles. Keep the
  candidate ledger broad so the reader can decide what to inspect or request
  deeper analysis for. Do not narrow the world to only a few adopted articles.
- Do not publish routine schedules, old background, search-result pages, or
  extreme personal opinions unless a confirmed material change exists.
- Prefer including a confirmed material item over missing it, but reject weak
  items with a concrete reason.
- Do not invent a candidate merely to fill a watch topic. Every watch_topic_id
  must instead have exactly one no_change_checks entry with direct evidence
  URLs, whether the result is a material update, near miss, or no change.
- Every fresh observed claim must be represented by a candidate, even when the
  final decision is reject. The candidate ledger is broad and auditable.
- Treat the findings ledger as the uncompressed result set. Every fresh_update
  or near_miss finding must become a candidate with its direct URL, even when
  several findings belong to the same watch topic.
- Do not merge independent events into one candidate. Honda China monthly sales
  and a Civic product update, for example, must remain separate candidates.
- Every candidate must have one decision.
- No-change verification text is not a candidate. Phrases like 直近確認,
  確定差分は不足, or 単独記事にする確定差分 belong only in no_change_checks.
- Cards must correspond exactly to adopted decisions. Fresh material candidates
  that matter to the reader should be adopted broadly and made visible as
  important-update cards. Do not create a separate public candidate board; the
  reader-facing surface is the traditional important-updates list.
- Reject only when the item is duplicate, routine/no-material-change,
  insufficiently evidenced, or outside the configured category's relevance.
- Public titles must be concise Japanese news headlines. Do not include
  checklist, monitoring, collection, or authoring wording.
- Summaries may be long when needed. Do not compress away names, dates, numbers,
  source dates, status/result, limits, or relevant uncertainty.
- Detail summary_basis must explain what changed, why it matters, confirmed
  facts, limits/unknowns, and source dates.
- Detail summary_basis.fact_sources must map every confirmed fact to one or more
  URLs from detail.sources. Do not leave material facts uncited.
- Treat discovery_findings as the horizon scan for important changes outside
  the configured topic wording. Map each finding to its closest watch_topic_id,
  retain it as a candidate, and reject it only with a concrete allowed reason.
- Use only absolute direct source URLs observed in the input observations.
- Material candidates must cite at least one source URL that carries observed
  claim_atoms, not just a URL that appeared in the sweep.
"""


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL SYNTHESIS FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def jst_now() -> str:
    return datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds")


def api_key() -> str:
    key = os.getenv("OPENAI_API_KEY")
    if not key:
        fail("OPENAI_API_KEY is required for live synthesis; use --dry-run to write request payloads")
    return key


def load_observations(issue_date: str, state_root: Path) -> list[dict[str, Any]]:
    state_dir = state_root / issue_date
    path = state.records_path(state_dir, "observations")
    observations = state.read_json_records(path)
    frontier = state.build_frontier(state.read_json(state.CONFIG_PATH))
    state.validate_observation_records(observations, frontier)
    return observations


def load_findings(issue_date: str, state_root: Path) -> list[dict[str, Any]]:
    path = state_root / issue_date / "findings.jsonl"
    findings = state.read_json_records(path)
    if not findings:
        fail(f"findings ledger is missing or empty: {path}")
    return findings


def by_category(records: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for record in records:
        grouped.setdefault(str(record.get("category")), []).append(record)
    return grouped


def frontier_by_category() -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for item in state.build_frontier(state.read_json(state.CONFIG_PATH)):
        grouped.setdefault(str(item["category"]), []).append(item)
    return grouped


def task_payload(
    issue_date: str,
    category: str,
    frontier_topics: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "model": DEFAULT_SYNTHESIS_MODEL,
        "reasoning": {"effort": os.getenv("NIGHT_SIGNAL_SYNTHESIS_REASONING_EFFORT", "medium")},
        "input": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "issue_date": issue_date,
                        "category": category,
                        "latest_allowed_source_dates": latest_three_dates(issue_date),
                        "frontier_topics": frontier_topics,
                        "observations": observations,
                        "findings": findings,
                        "required_output": "one category_synthesis JSON object",
                        "generated_at_jst": jst_now(),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
            },
        ],
        "text": {
            "format": {
                "type": "json_schema",
                "name": "category_synthesis",
                "strict": True,
                "schema": CATEGORY_SYNTHESIS_SCHEMA,
            }
        },
    }


def latest_three_dates(issue_date: str) -> list[str]:
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    return [
        issue_dt.isoformat(),
        (issue_dt.fromordinal(issue_dt.toordinal() - 1)).isoformat(),
        (issue_dt.fromordinal(issue_dt.toordinal() - 2)).isoformat(),
    ]


def call_responses(payload: dict[str, Any], *, retries: int) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {
        "Authorization": f"Bearer {api_key()}",
        "Content-Type": "application/json",
        "User-Agent": "night-signal-synthesizer",
    }
    last_error = ""
    for attempt in range(1, retries + 1):
        request = urllib.request.Request(RESPONSES_URL, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=240) as response:
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


def parse_category_result(response: dict[str, Any]) -> dict[str, Any]:
    text = output_text(response)
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        fail(f"synthesis output was not JSON: {exc}: {text[:500]}")
    if not isinstance(value, dict):
        fail("synthesis output must be a JSON object")
    return value


def direct_urls(observations: list[dict[str, Any]]) -> set[str]:
    urls: set[str] = set()
    for observation in observations:
        url = observation.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            urls.add(url)
        for result in observation.get("source_target_results", []):
            if isinstance(result, dict):
                result_url = result.get("url")
                if (
                    result.get("slot_state") in {"observed_live", "reused_from_cache"}
                    and isinstance(result_url, str)
                    and result_url.startswith(("http://", "https://"))
                ):
                    urls.add(result_url)
        for finding in observation.get("discovery_findings", []):
            if isinstance(finding, dict):
                finding_url = finding.get("source_url")
                if isinstance(finding_url, str) and finding_url.startswith(("http://", "https://")):
                    urls.add(finding_url)
    return urls


def claim_source_urls(issue_date: str, observations: list[dict[str, Any]]) -> set[str]:
    urls: set[str] = set()
    allowed_source_dates = set(latest_three_dates(issue_date))
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        if observation.get("slot_state") != "observed_live":
            continue
        if observation.get("published_date") not in allowed_source_dates:
            continue
        claim_atoms = observation.get("claim_atoms")
        if not isinstance(claim_atoms, list) or not claim_atoms:
            continue
        url = observation.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            urls.add(url)
        for result in observation.get("source_target_results", []):
            if not isinstance(result, dict):
                continue
            result_url = result.get("url")
            if (
                isinstance(result_url, str)
                and result_url.startswith(("http://", "https://"))
                and result.get("slot_state") == "observed_live"
                and result.get("published_date") in allowed_source_dates
            ):
                urls.add(result_url)
        for finding in observation.get("discovery_findings", []):
            if not isinstance(finding, dict) or finding.get("published_date") not in allowed_source_dates:
                continue
            finding_url = finding.get("source_url")
            if isinstance(finding_url, str) and finding_url.startswith(("http://", "https://")):
                urls.add(finding_url)
    return urls


def validate_claim_source_linkage(category: str, candidate: dict[str, Any], claim_urls: set[str]) -> None:
    change_class = candidate.get("change_class")
    if change_class not in {"new_event", "material_update"}:
        return
    source_urls = candidate.get("source_urls")
    if not isinstance(source_urls, list) or not any(url in claim_urls for url in source_urls):
        fail(f"{category} material candidate lacks claim/source linkage: {candidate.get('title')}")


def validate_candidate_is_not_placeholder(issue_date: str, category: str, candidate: dict[str, Any]) -> None:
    contract = state.read_json(state.CONFIG_PATH)
    if not state.effective_on_or_after(contract, "candidate_placeholder_ban_effective_date", issue_date):
        return
    text = " ".join([str(candidate.get("title", "")), str(candidate.get("summary", ""))])
    placeholder_patterns = [
        r"直近確認",
        r"確定差分は不足",
        r"単独記事にする確定差分",
        r"公式・媒体・SNS系の証跡で確認した",
    ]
    hits = [pattern for pattern in placeholder_patterns if re.search(pattern, text)]
    if hits:
        fail(f"{category} no-change placeholder must stay out of candidates: {candidate.get('title')}")


def validate_category_result(
    issue_date: str,
    category: str,
    frontier_topics: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    result: dict[str, Any],
    findings: list[dict[str, Any]] | None = None,
) -> None:
    if result.get("category") != category:
        fail(f"synthesis category mismatch: {result.get('category')} != {category}")
    candidates = result.get("candidates")
    decisions = result.get("decisions")
    cards = result.get("cards")
    no_change_checks = result.get("no_change_checks")
    if not isinstance(candidates, list) or not isinstance(decisions, list) or not isinstance(cards, list) or not isinstance(no_change_checks, list):
        fail(f"{category} synthesis result must contain candidates, decisions, cards, and no_change_checks lists")

    required_topics = {str(item["watch_topic_id"]) for item in frontier_topics}

    allowed_source_dates = set(latest_three_dates(issue_date))
    allowed_urls = direct_urls(observations)
    check_topics = [
        str(check.get("topic_id"))
        for check in no_change_checks
        if isinstance(check, dict)
    ]
    if sorted(check_topics) != sorted(required_topics):
        fail(f"{category} no_change_checks must cover every watch topic exactly once")
    for check in no_change_checks:
        if not isinstance(check, dict):
            fail(f"{category} no_change_check must be an object")
        evidence_urls = check.get("evidence_urls")
        if (
            not isinstance(evidence_urls, list)
            or not evidence_urls
            or any(url not in allowed_urls for url in evidence_urls)
        ):
            fail(f"{category} no_change_check must use verified observation URLs")
    claim_urls = claim_source_urls(issue_date, observations)
    fresh_claim_urls: set[str] = set()
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        if observation.get("slot_state") != "observed_live":
            continue
        if observation.get("published_date") not in allowed_source_dates:
            continue
        claim_atoms = observation.get("claim_atoms")
        if isinstance(claim_atoms, list) and claim_atoms:
            url = observation.get("url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                fresh_claim_urls.add(url)
        for finding in observation.get("discovery_findings", []):
            if not isinstance(finding, dict) or finding.get("published_date") not in allowed_source_dates:
                continue
            finding_url = finding.get("source_url")
            if isinstance(finding_url, str) and finding_url.startswith(("http://", "https://")):
                fresh_claim_urls.add(finding_url)
    for candidate in candidates:
        if not isinstance(candidate, dict):
            fail(f"{category} candidate must be an object")
        if candidate.get("source_published_date") not in allowed_source_dates and candidate.get("change_class") not in {"background_only", "routine_recurring", "duplicate_followup"}:
            fail(f"{category} candidate has stale material source date: {candidate.get('title')}")
        for url in candidate.get("source_urls", []):
            if url not in allowed_urls:
                fail(f"{category} candidate uses URL not present in observations: {url}")
            fresh_claim_urls.discard(url)
        validate_candidate_is_not_placeholder(issue_date, category, candidate)
        validate_claim_source_linkage(category, candidate, claim_urls)
    retained_finding_urls = {
        str(url)
        for candidate in candidates
        for url in candidate.get("source_urls", [])
        if isinstance(url, str)
    }
    required_finding_urls = {
        str(finding.get("url"))
        for finding in findings or []
        if finding.get("finding_state") in {"fresh_update", "near_miss"}
        and isinstance(finding.get("url"), str)
    }
    missing_finding_urls = sorted(required_finding_urls - retained_finding_urls)
    if missing_finding_urls:
        fail(
            f"{category} findings were dropped before candidate review: "
            + ", ".join(missing_finding_urls[:6])
        )
    if fresh_claim_urls:
        fail(f"{category} fresh observed claims missing from candidates: " + ", ".join(sorted(fresh_claim_urls)[:6]))

    decision_titles = [str(decision.get("candidate_title")) for decision in decisions if isinstance(decision, dict)]
    candidate_titles = [str(candidate.get("title")) for candidate in candidates if isinstance(candidate, dict)]
    if sorted(decision_titles) != sorted(candidate_titles):
        fail(f"{category} decisions must cover exactly all candidates")

    adopted = {str(decision.get("candidate_title")) for decision in decisions if isinstance(decision, dict) and decision.get("adoption_decision") == "adopt"}
    card_candidates = {str(card.get("candidate_title")) for card in cards if isinstance(card, dict)}
    if adopted != card_candidates:
        fail(f"{category} cards must cover exactly adopted decisions")

    issue = {
        "issue_date": issue_date,
        "state": "publication_ready",
        "frontier": state.build_frontier(state.read_json(state.CONFIG_PATH)),
        "observations": observations_for_issue_cache[issue_date],
        "candidates": candidates_for_validation_cache[issue_date] + candidates,
        "decisions": decisions_for_validation_cache[issue_date] + decisions,
        "cards": cards_for_validation_cache[issue_date] + cards,
        "coverage_manifest": minimal_manifest(
            issue_date,
            {category: result},
            observations=observations_for_issue_cache[issue_date],
        ),
        "blockers": [],
    }
    for card in cards:
        if isinstance(card, dict):
            state.validate_public_card_copy(card, card.get("detail", {}), issue_date=issue_date, card_index=1)


observations_for_issue_cache: dict[str, list[dict[str, Any]]] = {}
candidates_for_validation_cache: dict[str, list[dict[str, Any]]] = {}
decisions_for_validation_cache: dict[str, list[dict[str, Any]]] = {}
cards_for_validation_cache: dict[str, list[dict[str, Any]]] = {}


def minimal_manifest(
    issue_date: str,
    results_by_category: dict[str, dict[str, Any]],
    *,
    observations: list[dict[str, Any]] | None = None,
    collection_mode: str = "responses_web_search",
    collection_completed_at_jst: str | None = None,
) -> dict[str, Any]:
    contract = state.read_json(state.CONFIG_PATH)
    source_registry = state.load_source_registry()
    official_hosts = {
        urlparse(str(source["url"])).netloc.lower().removeprefix("www.")
        for sources in source_registry.values()
        for source in sources
        if source.get("source_class") in {"official", "official_dataset"}
    }
    major_hosts = {
        urlparse(str(source["url"])).netloc.lower().removeprefix("www.")
        for sources in source_registry.values()
        for source in sources
        if source.get("source_class") == "major_media"
    } | {
        "apnews.com",
        "bloomberg.com",
        "businessinsider.com",
        "ft.com",
        "theguardian.com",
        "nypost.com",
        "reuters.com",
        "wsj.com",
    }
    specialist_hosts = {
        urlparse(str(source["url"])).netloc.lower().removeprefix("www.")
        for sources in source_registry.values()
        for source in sources
        if source.get("source_class") == "specialist_media"
    }
    categories: dict[str, dict[str, Any]] = {}
    observations = observations or []
    observed_urls_by_category: dict[str, set[str]] = {}
    for observation in observations:
        if not isinstance(observation, dict):
            continue
        label = str(observation.get("category"))
        if observation.get("slot_state") in {"observed_live", "reused_from_cache"}:
            url = observation.get("url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                observed_urls_by_category.setdefault(label, set()).add(url)
        for target in observation.get("source_target_results", []):
            if not isinstance(target, dict):
                continue
            url = target.get("url")
            if (
                target.get("slot_state") in {"observed_live", "reused_from_cache"}
                and isinstance(url, str)
                and url.startswith(("http://", "https://"))
            ):
                observed_urls_by_category.setdefault(label, set()).add(url)
        for finding in observation.get("discovery_findings", []):
            if not isinstance(finding, dict):
                continue
            url = finding.get("source_url")
            if isinstance(url, str) and url.startswith(("http://", "https://")):
                observed_urls_by_category.setdefault(label, set()).add(url)
    for category in contract.get("categories", []):
        if not isinstance(category, dict):
            continue
        label = str(category.get("label"))
        result = results_by_category.get(label, {"candidates": [], "cards": [], "no_change_checks": []})
        cards = [card for card in result.get("cards", []) if isinstance(card, dict)]
        candidates = [candidate for candidate in result.get("candidates", []) if isinstance(candidate, dict)]
        decisions = [decision for decision in result.get("decisions", []) if isinstance(decision, dict)]
        adopted_titles = {str(decision.get("candidate_title")) for decision in decisions if decision.get("adoption_decision") == "adopt"}
        rejected_titles = {
            str(decision.get("candidate_title"))
            for decision in decisions
            if decision.get("adoption_decision") == "reject"
        }
        source_evidence = {
            source_class: []
            for source_class in ("official", "major_media", "specialist_media", "sns_x", "youtube_video")
        }
        candidate_urls = {
            str(url)
            for candidate in candidates
            for url in candidate.get("source_urls", [])
            if isinstance(url, str) and url.startswith(("http://", "https://"))
        }
        candidate_urls &= observed_urls_by_category.get(label, set())
        for url in observed_urls_by_category.get(label, set()) | candidate_urls:
            host = urlparse(url).netloc.lower().removeprefix("www.")
            if host in official_hosts:
                source_evidence["official"].append(url)
            elif host in major_hosts:
                source_evidence["major_media"].append(url)
            elif host in specialist_hosts:
                source_evidence["specialist_media"].append(url)
            elif host in {"x.com", "twitter.com"}:
                source_evidence["sns_x"].append(url)
            elif host in {"youtube.com", "youtu.be"}:
                source_evidence["youtube_video"].append(url)
            else:
                source_evidence["specialist_media"].append(url)
        source_evidence = {
            key: sorted(set(values))
            for key, values in source_evidence.items()
        }
        held = [
            str(decision.get("candidate_title"))
            for decision in decisions
            if decision.get("adoption_decision") == "reject"
            and decision.get("reject_reason_class") == "insufficient_evidence"
        ]
        excluded = [
            str(decision.get("candidate_title"))
            for decision in decisions
            if decision.get("adoption_decision") == "reject"
            and decision.get("reject_reason_class") != "insufficient_evidence"
        ]
        categories[label] = {
            **source_evidence,
            "data_numeric": [
                str(candidate.get("summary"))
                for candidate in candidates
                if any(char.isdigit() for char in str(candidate.get("summary")))
            ]
            or [f"{issue_date}時点で数値を伴う更新なし"],
            "schedule_calendar": [
                f"{issue_date}の公表・予定・結果を照合"
            ],
            "counter_search": [
                str(check.get("result"))
                for check in result.get("no_change_checks", [])
                if isinstance(check, dict) and isinstance(check.get("result"), str)
            ]
            or [f"{issue_date}時点の反証検索を実施"],
            "adopted": sorted(adopted_titles),
            "held": held or ["保留候補なし"],
            "excluded": excluded or ["除外候補なし"],
            "unresolved": ["未確認の重大リスクなし"],
            "critical_unresolved": [],
            "search_terms": sorted(
                {
                    str(term)
                    for topic in category.get("watch_topics", [])
                    if isinstance(topic, dict)
                    for term in topic.get("terms", [])
                    if isinstance(term, str)
                }
            ),
            "freshness_check": f"{issue_date} JSTの直近3日を基準に照合",
            "published_card_titles": [str(card.get("title")) for card in cards],
            "new_or_changed_items": [
                {
                    "title": str(card.get("title")),
                    "summary": str(card.get("summary")),
                    "sources": [str(source.get("url")) for source in card.get("detail", {}).get("sources", []) if isinstance(source, dict)],
                    "summary_mode": "multi_source_synthesis" if len(card.get("detail", {}).get("sources", [])) > 1 else "single_source_summary",
                    "material_facts": card.get("detail", {}).get("summary_basis", {}).get("confirmed_facts", []),
                }
                for card in cards
            ],
            "latest_candidates": [
                {
                    "topic_id": str(candidate.get("watch_topic_id")),
                    "title": str(candidate.get("title")),
                    "source_url": str(candidate.get("source_urls", [""])[0]),
                    "source_published_date": str(candidate.get("source_published_date")),
                    "decision": "adopted" if str(candidate.get("title")) in adopted_titles else "no_fresh_item",
                    "change_class": str(candidate.get("change_class")),
                    "rationale": str(candidate.get("summary")),
                }
                for candidate in candidates
            ],
            "no_change_checks": result.get("no_change_checks", []),
        }
    return {
        "contract_version": contract.get("contract_version"),
        "date": issue_date,
        "last_checked_jst": collection_completed_at_jst or jst_now(),
        "collection_completed_at_jst": collection_completed_at_jst or jst_now(),
        "collection_mode": collection_mode,
        "categories": categories,
    }


def write_jsonl(path: Path, records: list[dict[str, Any]], *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if replace else "a"
    with path.open(mode, encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")


def write_requests(path: Path, payloads: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n" for payload in payloads),
        encoding="utf-8",
    )


def category_signature(
    issue_date: str,
    category: str,
    topics: list[dict[str, Any]],
    observations: list[dict[str, Any]],
    findings: list[dict[str, Any]],
) -> str:
    value = {
        "issue_date": issue_date,
        "category": category,
        "topics": topics,
        "observations": observations,
        "findings": findings,
    }
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def synthesis_part_path(state_dir: Path, category: str) -> Path:
    digest = hashlib.sha256(category.encode("utf-8")).hexdigest()[:12]
    return state_dir / "synthesis_parts" / f"{digest}.json"


def write_synthesis_part(
    state_dir: Path,
    issue_date: str,
    category: str,
    signature: str,
    result: dict[str, Any],
) -> dict[str, Any]:
    value = {
        "version": 1,
        "issue_date": issue_date,
        "category": category,
        "input_signature": signature,
        "completed_at_jst": jst_now(),
        "result": result,
    }
    path = synthesis_part_path(state_dir, category)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(".json.tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temp.replace(path)
    return value


def load_synthesis_part(
    state_dir: Path,
    issue_date: str,
    category: str,
    signature: str,
) -> dict[str, Any] | None:
    path = synthesis_part_path(state_dir, category)
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if (
        not isinstance(value, dict)
        or value.get("issue_date") != issue_date
        or value.get("category") != category
        or value.get("input_signature") != signature
        or not isinstance(value.get("result"), dict)
    ):
        return None
    return value


def synthesize(
    issue_date: str,
    state_root: Path,
    *,
    dry_run: bool,
    replace: bool,
    resume: bool,
    retries: int,
) -> dict[str, Any]:
    observations = load_observations(issue_date, state_root)
    findings = load_findings(issue_date, state_root)
    observations_for_issue_cache[issue_date] = observations
    candidates_for_validation_cache[issue_date] = []
    decisions_for_validation_cache[issue_date] = []
    cards_for_validation_cache[issue_date] = []

    observations_by_category = by_category(observations)
    findings_by_category = by_category(findings)
    frontier_categories = frontier_by_category()
    payloads = [
        task_payload(
            issue_date,
            category,
            topics,
            observations_by_category.get(category, []),
            findings_by_category.get(category, []),
        )
        for category, topics in frontier_categories.items()
    ]
    state_dir = state_root / issue_date
    if dry_run:
        write_requests(state_dir / "synthesis_requests.jsonl", payloads)
        return {"issue_date": issue_date, "requests": len(payloads), "path": str(state_dir / "synthesis_requests.jsonl")}

    results_by_category: dict[str, dict[str, Any]] = {}
    reused_parts = 0
    for index, (category, topics) in enumerate(frontier_categories.items(), start=1):
        category_observations = observations_by_category.get(category, [])
        category_findings = findings_by_category.get(category, [])
        signature = category_signature(
            issue_date,
            category,
            topics,
            category_observations,
            category_findings,
        )
        part = (
            load_synthesis_part(state_dir, issue_date, category, signature)
            if resume
            else None
        )
        if part is not None:
            print(f"resuming {index}/{len(frontier_categories)} {category}", file=sys.stderr)
            result = part["result"]
            reused_parts += 1
        else:
            print(f"synthesizing {index}/{len(frontier_categories)} {category}", file=sys.stderr)
            result = parse_category_result(
                call_responses(
                    task_payload(
                        issue_date,
                        category,
                        topics,
                        category_observations,
                        category_findings,
                    ),
                    retries=retries,
                )
            )
        validate_category_result(
            issue_date,
            category,
            topics,
            category_observations,
            result,
            category_findings,
        )
        if part is None:
            write_synthesis_part(state_dir, issue_date, category, signature, result)
        results_by_category[category] = result
        candidates_for_validation_cache[issue_date].extend(result["candidates"])
        decisions_for_validation_cache[issue_date].extend(result["decisions"])
        cards_for_validation_cache[issue_date].extend(result["cards"])

    candidates = [candidate for result in results_by_category.values() for candidate in result["candidates"]]
    decisions = [decision for result in results_by_category.values() for decision in result["decisions"]]
    cards = [card for result in results_by_category.values() for card in result["cards"]]
    completed_at = jst_now()
    manifest = minimal_manifest(
        issue_date,
        results_by_category,
        observations=observations,
        collection_mode="responses_web_search",
        collection_completed_at_jst=completed_at,
    )

    write_jsonl(state_dir / "candidates.jsonl", candidates, replace=replace)
    write_jsonl(state_dir / "decisions.jsonl", decisions, replace=replace)
    write_jsonl(state_dir / "cards.jsonl", cards, replace=replace)
    (state_dir / "coverage_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    state.assemble_issue_state(issue_date, state_root)
    return {
        "issue_date": issue_date,
        "categories": len(results_by_category),
        "candidates": len(candidates),
        "decisions": len(decisions),
        "cards": len(cards),
        "reused_category_checkpoints": reused_parts,
    }


def self_test() -> None:
    payload = task_payload(
        "2099-01-01",
        "OpenAI",
        [{"category": "OpenAI", "section_id": "openai", "watch_topic_id": "product_release", "required_channels": ["web", "sns_x", "youtube"]}],
        [
            {
                "category": "OpenAI",
                "watch_topic_id": "product_release",
                "source_role": "primary_or_official",
                "channel": "web",
                "slot_state": "observed_live",
                "url": "https://openai.com/",
                "observed_at_jst": "2099-01-01T20:00:00+09:00",
                "published_date": "2099-01-01",
                "evidence_summary": "OpenAI公式で新しい発表を確認した。",
                "source_target_results": [
                    {
                        "label": "OpenAI News",
                        "url": "https://openai.com/",
                        "channel": "web",
                        "slot_state": "observed_live",
                        "published_date": "2099-01-01",
                        "evidence_summary": "OpenAI公式で発表を確認した。",
                        "checked_at_jst": "2099-01-01T20:00:00+09:00",
                        "verification_method": "responses_web_search",
                    }
                ],
                "claim_atoms": [{"claim_type": "announcement", "claim": "OpenAIが発表した。", "source_state": "confirmed_update"}],
                "discovery_findings": [],
            },
            {
                "category": "OpenAI",
                "watch_topic_id": "product_release",
                "source_role": "independent_or_media",
                "channel": "web",
                "slot_state": "observed_live",
                "url": "https://example.com/background",
                "observed_at_jst": "2099-01-01T20:01:00+09:00",
                "published_date": "2099-01-01",
                "evidence_summary": "背景情報のみで、新しい主張は確認できない。",
                "source_target_results": [
                    {
                        "label": "Background",
                        "url": "https://example.com/background",
                        "channel": "web",
                        "slot_state": "observed_live",
                        "published_date": "2099-01-01",
                        "evidence_summary": "背景情報のみ。",
                        "checked_at_jst": "2099-01-01T20:01:00+09:00",
                        "verification_method": "responses_web_search",
                    }
                ],
                "claim_atoms": [],
                "discovery_findings": [],
            }
        ],
        [
            {
                "issue_date": "2099-01-01",
                "slot_id": "openai-product-web",
                "category": "OpenAI",
                "source_role": "primary_or_official",
                "channel": "web",
                "title": "OpenAI、ChatGPTのメモリ合成を改善",
                "url": "https://openai.com/",
                "published_date": "2099-01-01",
                "summary": "OpenAIがChatGPTのメモリ合成を改善した。",
                "watch_topic_ids": ["product_release"],
                "finding_state": "fresh_update",
                "observed_at_jst": "2099-01-01T20:00:00+09:00",
            }
        ],
    )
    fmt = payload["text"]["format"]
    if fmt["type"] != "json_schema" or fmt["schema"] != CATEGORY_SYNTHESIS_SCHEMA:
        fail("synthesizer must use category synthesis structured output schema")
    content = payload["input"][1]["content"]
    for term in ("frontier_topics", "observations", "findings", "latest_allowed_source_dates"):
        if term not in content:
            fail(f"synthesis prompt missing {term}")
    frontier_topics = [
        {
            "category": "OpenAI",
            "section_id": "openai",
            "watch_topic_id": "product_release",
            "required_channels": ["web", "sns_x", "youtube"],
        }
    ]
    observations = payload["input"][1]["content"]
    observation_records = json.loads(observations)["observations"]
    observations_for_issue_cache["2099-01-01"] = observation_records
    candidates_for_validation_cache["2099-01-01"] = []
    decisions_for_validation_cache["2099-01-01"] = []
    cards_for_validation_cache["2099-01-01"] = []
    covered_result = {
        "category": "OpenAI",
        "candidates": [
            {
                "category": "OpenAI",
                "watch_topic_id": "product_release",
                "title": "OpenAI、ChatGPTのメモリ合成を改善",
                "source_published_date": "2099-01-01",
                "source_urls": ["https://openai.com/"],
                "change_class": "material_update",
                "summary": "OpenAIがChatGPTのメモリ合成を改善し、新鮮さ、継続性、関連性を高める変更を示した。",
                "material_facts": ["メモリ合成の改善が発表された。"],
                "counter_evidence_checked": True,
            }
        ],
        "decisions": [
            {
                "candidate_title": "OpenAI、ChatGPTのメモリ合成を改善",
                "adoption_decision": "reject",
                "topic_value_class": "technical_or_product_shift",
                "reader_delta": "製品改善の候補として確認したが、詳細化は他項目との優先度で見送る。",
                "materiality_basis": "公式発表の直接URLで確認した。",
                "reject_reason_class": "lower_importance",
                "reject_reason": "当日号では詳細化する他の変化を優先する。",
            }
        ],
        "cards": [],
        "no_change_checks": [
            {
                "topic_id": "product_release",
                "result": "OpenAI公式と補助資料を照合し、候補の根拠と追加の反証有無を確認した。",
                "evidence_urls": ["https://openai.com/"],
            }
        ],
    }
    validate_category_result("2099-01-01", "OpenAI", frontier_topics, observation_records, covered_result)
    missing_result = json.loads(json.dumps(covered_result, ensure_ascii=False))
    missing_result["candidates"][0]["source_urls"] = ["https://example.com/background"]
    captured_failures: list[str] = []
    original_fail = fail

    def capture_fail(message: str) -> None:
        captured_failures.append(message)
        raise RuntimeError(message)

    globals()["fail"] = capture_fail
    try:
        try:
            validate_category_result("2099-01-01", "OpenAI", frontier_topics, observation_records, missing_result)
        except RuntimeError:
            pass
    finally:
        globals()["fail"] = original_fail
    if not captured_failures or "claim/source linkage" not in captured_failures[0]:
        fail("synthesis validation must reject material candidates without claim/source linkage")
    signature = category_signature(
        "2099-01-01",
        "OpenAI",
        frontier_topics,
        observation_records,
        [],
    )
    with tempfile.TemporaryDirectory() as temp_dir:
        part = write_synthesis_part(
            Path(temp_dir),
            "2099-01-01",
            "OpenAI",
            signature,
            covered_result,
        )
        loaded = load_synthesis_part(
            Path(temp_dir),
            "2099-01-01",
            "OpenAI",
            signature,
        )
        if loaded != part:
            fail("synthesizer must round-trip durable category checkpoints")
        if load_synthesis_part(
            Path(temp_dir),
            "2099-01-01",
            "OpenAI",
            "changed",
        ) is not None:
            fail("synthesizer must invalidate a checkpoint when inputs change")
    print("NIGHT SIGNAL SYNTHESIS PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=state.jst_today())
    parser.add_argument("--state-root", type=Path, default=DEFAULT_STATE_ROOT)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--replace", action="store_true")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        self_test()
        return 0
    print(
        json.dumps(
            synthesize(
                args.issue_date,
                args.state_root,
                dry_run=args.dry_run,
                replace=args.replace,
                resume=args.resume,
                retries=args.retries,
            ),
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
