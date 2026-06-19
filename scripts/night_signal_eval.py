#!/usr/bin/env python3
"""Evaluate NIGHT SIGNAL coverage, evidence depth, and collection efficiency."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import night_signal_state as state


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"
MIN_CANDIDATE_TOPIC_RECALL = 0.95
MIN_REVIEWABLE_FINDING_TOPIC_RECALL = 0.80
MIN_DISCOVERY_FINDINGS = 1

CATEGORY_IDENTITY_TERMS = {
    "OpenAI": ["OpenAI", "ChatGPT", "Codex"],
    "SoftBank": ["SoftBank", "ソフトバンク", "SBG", "Arm"],
    "Honda": ["Honda", "ホンダ", "HRC", "Aston Martin", "Acura"],
    "F1": [
        "F1",
        "FIA",
        "Grand Prix",
        "グランプリ",
        "Formula 1",
        "ホンダ",
        "Honda",
        "ADUO",
        "PU",
        "レッドブル",
        "メルセデス",
        "フェラーリ",
        "マクラーレン",
        "Aston Martin",
    ],
    "SpaceX": ["SpaceX", "Starship", "Starlink", "Dragon", "Falcon"],
    "日本経済": ["日本", "日銀", "財務省", "CPI", "GDP", "円", "JGB"],
    "YOASOBI / 幾田りら": ["YOASOBI", "幾田りら", "ikura"],
    "アジア経済": ["アジア", "中国", "インド", "台湾", "韓国", "ASEAN", "ベトナム"],
    "北米経済": ["米", "米国", "アメリカ", "Canada", "Fed", "FRB", "S&P", "Nasdaq"],
    "宇都宮ブレックス": ["宇都宮ブレックス", "BREX", "B.LEAGUE", "Bリーグ"],
}


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL EVAL FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            fail(f"invalid JSONL at {path}:{line_number}: {exc}")
        if isinstance(value, dict):
            records.append(value)
    return records


def normalized_host(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def category_identity_failures(candidates: list[dict[str, Any]]) -> list[str]:
    failures: list[str] = []
    for candidate in candidates:
        category = str(candidate.get("category"))
        terms = CATEGORY_IDENTITY_TERMS.get(category)
        if not terms:
            continue
        text = f"{candidate.get('title', '')} {candidate.get('summary', '')}"
        if not any(term.lower() in text.lower() for term in terms):
            title = str(candidate.get("title", "(no title)"))
            failures.append(f"{category}: {title}")
    return failures


def evaluate(issue_date: str, state_root: Path) -> dict[str, Any]:
    base = state_root / issue_date
    plan = state.read_json(base / "collection_plan.json")
    issue = state.read_json(base / "issue.json")
    tasks = [task for task in plan.get("tasks", []) if isinstance(task, dict)]
    observations = [item for item in issue.get("observations", []) if isinstance(item, dict)]
    candidates = [item for item in issue.get("candidates", []) if isinstance(item, dict)]
    cards = [item for item in issue.get("cards", []) if isinstance(item, dict)]
    traces = read_jsonl(base / "source_traces.jsonl")
    findings = read_jsonl(base / "findings.jsonl")

    frontier = state.build_frontier(state.read_json(state.CONFIG_PATH))
    coverage = state.coverage_state(observations)
    expected_slots = int(coverage["required_observation_slots"])
    closed_slots = int(coverage["observed_slots"])
    expected_topics = {
        (str(item["category"]), str(item["watch_topic_id"]))
        for item in frontier
    }
    candidate_topics = {
        (str(item.get("category")), str(item.get("watch_topic_id")))
        for item in candidates
    }
    concrete_candidates = [
        candidate
        for candidate in candidates
        if "大きな更新なし" not in str(candidate.get("title"))
    ]
    concrete_candidate_topics = {
        (str(item.get("category")), str(item.get("watch_topic_id")))
        for item in concrete_candidates
    }
    manifest = issue.get("coverage_manifest", {})
    manifest_categories = manifest.get("categories", {})
    reviewed_topics = set(candidate_topics)
    if isinstance(manifest_categories, dict):
        for category, entry in manifest_categories.items():
            if not isinstance(entry, dict):
                continue
            for check in entry.get("no_change_checks", []):
                if isinstance(check, dict) and isinstance(check.get("topic_id"), str):
                    reviewed_topics.add((str(category), str(check["topic_id"])))

    seed_checks = sum(
        len([target for target in task.get("source_targets", []) if isinstance(target, dict)])
        for task in tasks
    )
    unique_seed_urls = {
        str(target.get("url"))
        for task in tasks
        for target in task.get("source_targets", [])
        if isinstance(target, dict) and isinstance(target.get("url"), str)
    }
    discovery_findings = [
        finding
        for observation in observations
        for finding in observation.get("discovery_findings", [])
        if isinstance(finding, dict)
    ]
    evidence_urls = {
        str(observation.get("url"))
        for observation in observations
        if isinstance(observation.get("url"), str)
        and str(observation.get("url")).startswith(("http://", "https://"))
    }
    evidence_urls.update(
        str(result.get("url"))
        for observation in observations
        for result in observation.get("source_target_results", [])
        if isinstance(result, dict)
        and result.get("slot_state") in {"observed_live", "reused_from_cache"}
        and isinstance(result.get("url"), str)
        and str(result.get("url")).startswith(("http://", "https://"))
    )
    verified_results = [
        result
        for observation in observations
        for result in observation.get("source_target_results", [])
        if isinstance(result, dict)
        and result.get("slot_state") in {"observed_live", "reused_from_cache"}
    ]
    provenance_complete = all(
        isinstance(result.get("checked_at_jst"), str)
        and str(result.get("checked_at_jst")).startswith(issue_date)
        and result.get("verification_method")
        in {
            "responses_web_search",
            "reviewed_live_web",
            "github_models_unattended",
            "direct_fetch",
            "cached_result",
        }
        for result in verified_results
    )

    mapped_facts = 0
    confirmed_facts = 0
    uncited_facts: list[str] = []
    for card in cards:
        detail = card.get("detail")
        if not isinstance(detail, dict):
            continue
        basis = detail.get("summary_basis")
        if not isinstance(basis, dict):
            continue
        facts = [fact for fact in basis.get("confirmed_facts", []) if isinstance(fact, str)]
        mappings = {
            str(mapping.get("fact")): mapping
            for mapping in basis.get("fact_sources", [])
            if isinstance(mapping, dict)
            and isinstance(mapping.get("fact"), str)
            and isinstance(mapping.get("source_urls"), list)
            and mapping.get("source_urls")
        }
        confirmed_facts += len(facts)
        for fact in facts:
            if fact in mappings:
                mapped_facts += 1
            else:
                uncited_facts.append(fact)

    extended_traces = [
        trace for trace in traces if trace.get("stage") == "extended_research"
    ]
    findings_by_topic = {
        key: len(
            {
                str(finding.get("url"))
                for finding in findings
                if finding.get("category") == key[0]
            and key[1] in finding.get("watch_topic_ids", [])
            }
        )
        for key in expected_topics
    }
    finding_source_classes = {
        key: {
            (str(finding.get("source_role")), str(finding.get("channel")))
            for finding in findings
            if finding.get("category") == key[0]
            and key[1] in finding.get("watch_topic_ids", [])
        }
        for key in expected_topics
    }
    candidate_urls = {
        str(url)
        for candidate in candidates
        for url in candidate.get("source_urls", [])
        if isinstance(url, str)
    }
    reviewable_finding_urls = {
        str(finding.get("url"))
        for finding in findings
        if finding.get("finding_state") in {"fresh_update", "near_miss"}
        and isinstance(finding.get("url"), str)
    }
    reviewable_finding_topics = {
        (str(finding.get("category")), str(topic_id))
        for finding in findings
        if finding.get("finding_state") in {"fresh_update", "near_miss"}
        for topic_id in finding.get("watch_topic_ids", [])
    }
    checks = {
        "all_observation_slots_closed": not coverage["missing_slots"],
        "topic_review_complete": reviewed_topics >= expected_topics,
        "fact_source_mapping_complete": confirmed_facts > 0 and mapped_facts == confirmed_facts,
        "collection_calls_reduced": len(tasks) < expected_slots,
        "extended_research_bounded": len(extended_traces) <= 3,
        "direct_source_evidence_present": bool(evidence_urls),
        "source_verification_provenance_complete": bool(verified_results)
        and provenance_complete,
        "raw_finding_depth_complete": all(
            count >= 3 for count in findings_by_topic.values()
        ),
        "raw_finding_source_diversity_complete": all(
            len(classes) >= 2 for classes in finding_source_classes.values()
        ),
        "finding_candidate_retention_complete": (
            reviewable_finding_urls <= candidate_urls
        ),
    }
    metrics = {
        "collection_tasks": len(tasks),
        "expected_observation_slots": expected_slots,
        "closed_observation_slots": closed_slots,
        "slot_recall": round(closed_slots / expected_slots, 4) if expected_slots else 0,
        "candidate_topics_expected": len(expected_topics),
        "candidate_topics_covered": len(candidate_topics & expected_topics),
        "reviewed_topics_covered": len(reviewed_topics & expected_topics),
        "concrete_candidate_topics_covered": len(
            concrete_candidate_topics & expected_topics
        ),
        "candidate_topic_recall": round(
            len(candidate_topics & expected_topics) / len(expected_topics), 4
        )
        if expected_topics
        else 0,
        "seed_target_checks": seed_checks,
        "unique_seed_target_urls": len(unique_seed_urls),
        "duplicate_seed_checks_removed_by_sweeps": expected_slots - len(tasks),
        "discovery_findings": len(discovery_findings),
        "evidence_urls": len(evidence_urls),
        "evidence_hosts": len({normalized_host(url) for url in evidence_urls}),
        "verified_source_results": len(verified_results),
        "confirmed_facts": confirmed_facts,
        "facts_with_source_mapping": mapped_facts,
        "source_mapping_recall": round(mapped_facts / confirmed_facts, 4)
        if confirmed_facts
        else 0,
        "response_traces": len(traces),
        "extended_research_runs": len(extended_traces),
        "raw_findings": len(findings),
        "minimum_findings_per_topic": min(findings_by_topic.values())
        if findings_by_topic
        else 0,
        "reviewable_finding_urls": len(reviewable_finding_urls),
        "reviewable_finding_topics": len(
            reviewable_finding_topics & expected_topics
        ),
        "reviewable_findings_retained": len(
            reviewable_finding_urls & candidate_urls
        ),
        "collection_mode": manifest.get(
            "collection_mode",
            "responses_web_search" if traces else "unknown",
        ),
    }
    topic_recall = metrics["candidate_topic_recall"]
    reviewable_topic_recall = (
        len(reviewable_finding_topics & expected_topics) / len(expected_topics)
        if expected_topics
        else 0
    )
    identity_failures = category_identity_failures(candidates)
    empty_categories = sorted(
        {
            category
            for category, _topic in expected_topics
            if not any(card.get("category") == category for card in cards)
            and not any(candidate.get("category") == category for candidate in concrete_candidates)
        }
    )
    checks.update(
        {
            "candidate_topic_recall_complete": topic_recall >= MIN_CANDIDATE_TOPIC_RECALL,
            "reviewable_finding_topic_recall_complete": (
                reviewable_topic_recall >= MIN_REVIEWABLE_FINDING_TOPIC_RECALL
            ),
            "discovery_horizon_scan_present": len(discovery_findings) >= MIN_DISCOVERY_FINDINGS,
            "category_identity_complete": not identity_failures,
            "no_empty_reader_categories": not empty_categories,
        }
    )
    metrics.update(
        {
            "minimum_candidate_topic_recall": MIN_CANDIDATE_TOPIC_RECALL,
            "reviewable_finding_topic_recall": round(reviewable_topic_recall, 4),
            "minimum_reviewable_finding_topic_recall": MIN_REVIEWABLE_FINDING_TOPIC_RECALL,
            "minimum_discovery_findings": MIN_DISCOVERY_FINDINGS,
            "category_identity_failures": identity_failures,
            "empty_reader_categories": empty_categories,
        }
    )
    return {
        "issue_date": issue_date,
        "evaluated_at_jst": datetime.now(ZoneInfo("Asia/Tokyo")).isoformat(timespec="seconds"),
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": metrics,
        "failures": [name for name, passed in checks.items() if not passed],
        "uncited_facts": uncited_facts,
    }


def self_test() -> None:
    if normalized_host("https://www.openai.com/index/test") != "openai.com":
        fail("host normalization failed")
    print("NIGHT SIGNAL EVAL SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("issue_date", nargs="?", default=state.jst_today())
    parser.add_argument("--state-root", type=Path, default=STATE_ROOT)
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0

    report = evaluate(args.issue_date, args.state_root)
    output = args.state_root / args.issue_date / "eval_report.json"
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report["passed"]:
        fail(", ".join(report["failures"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
