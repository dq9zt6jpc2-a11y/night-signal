#!/usr/bin/env python3
"""Validate broad Evidence coverage and its direct projection into an Issue."""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Any

import night_signal_state as state


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "night_signal_coverage.json"
SOURCE_CONFIG_PATH = ROOT / "config" / "night_signal_sources.json"
STATE_ROOT = ROOT / "state"
SITE_ROOT = ROOT / "site"


def fail(message: str) -> None:
    print(f"COVERAGE AUDIT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        fail(f"cannot load {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}: {exc}")
    if not isinstance(value, dict):
        fail(f"expected JSON object: {path}")
    return value


def load_contract() -> dict[str, Any]:
    return load_object(CONFIG_PATH)


def effective_on_or_after(contract: dict[str, Any], key: str, issue_dt: date) -> bool:
    value = contract.get(key)
    if not isinstance(value, str):
        return False
    try:
        return issue_dt >= datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return False


def max_adopted_source_age_days(contract: dict[str, Any], issue_dt: date) -> int:
    if effective_on_or_after(contract, "strict_adopted_candidate_source_age_effective_date", issue_dt):
        return int(contract.get("maximum_adopted_candidate_source_age_days", 3))
    return 7


def visible_text(value: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", value))).strip()


def configured_categories(contract: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(category["label"]): category
        for category in contract.get("categories", [])
        if isinstance(category, dict)
    }


def source_registry() -> dict[str, list[dict[str, Any]]]:
    categories = load_object(SOURCE_CONFIG_PATH).get("categories")
    if not isinstance(categories, dict):
        fail("source registry categories must be an object")
    return {
        str(label): [source for source in sources if isinstance(source, dict)]
        for label, sources in categories.items()
        if isinstance(sources, list)
    }


def card_sources(card: dict[str, Any]) -> set[str]:
    detail = card.get("detail")
    if not isinstance(detail, dict):
        return set()
    return {
        str(source.get("url"))
        for source in detail.get("sources", [])
        if isinstance(source, dict) and isinstance(source.get("url"), str)
    }


def validate_category(
    label: str,
    config: dict[str, Any],
    entry: dict[str, Any],
    cards: list[dict[str, Any]],
    registry: dict[str, list[dict[str, Any]]],
    issue_date: str,
) -> tuple[int, int]:
    checks = entry.get("source_checks")
    if not isinstance(checks, list) or not checks:
        fail(f"{label} has no source checks")

    required_topics = {
        str(topic.get("id"))
        for topic in config.get("watch_topics", [])
        if isinstance(topic, dict)
    }
    required_channels = set(state.category_required_channels(load_contract(), config))
    checked_topics: set[str] = set()
    checked_channels: set[str] = set()
    checked_urls: set[str] = set()
    observed_urls: set[str] = set()
    for index, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            fail(f"{label} source_checks[{index}] must be an object")
        url = check.get("url")
        check_state = check.get("slot_state")
        topics = check.get("watch_topic_ids")
        channel = check.get("channel")
        if not isinstance(url, str) or not url.startswith(("http://", "https://")):
            fail(f"{label} source_checks[{index}] has an invalid URL")
        if check_state not in {"observed_live", "source_unavailable"}:
            fail(f"{label} source_checks[{index}] has an invalid state")
        if not isinstance(topics, list) or any(topic not in required_topics for topic in topics):
            fail(f"{label} source_checks[{index}] has invalid watch topics")
        if not isinstance(channel, str) or not channel:
            fail(f"{label} source_checks[{index}] has no channel")
        if not str(check.get("checked_at_jst", "")).startswith(issue_date):
            fail(f"{label} source_checks[{index}] was not checked on {issue_date}")
        if not isinstance(check.get("evidence_summary"), str) or not str(
            check.get("evidence_summary")
        ).strip():
            fail(f"{label} source_checks[{index}] has no evidence summary")
        checked_topics.update(str(topic) for topic in topics)
        checked_channels.add(channel)
        checked_urls.add(url)
        if check_state == "observed_live":
            observed_urls.add(url)

    seed_urls = {
        str(source.get("url"))
        for source in registry.get(label, [])
        if isinstance(source.get("url"), str)
    }
    if not seed_urls <= checked_urls:
        fail(f"{label} has seed URLs without result states")
    if not required_topics <= checked_topics:
        fail(f"{label} has unchecked watch topics: {', '.join(sorted(required_topics - checked_topics))}")
    if not required_channels <= checked_channels:
        fail(f"{label} has unchecked channels: {', '.join(sorted(required_channels - checked_channels))}")
    if not observed_urls:
        fail(f"{label} has no observed live evidence")

    category_cards = [card for card in cards if card.get("category") == label]
    for card in category_cards:
        sources = card_sources(card)
        if not sources or not sources <= observed_urls:
            fail(f"{label} public update cites unobserved evidence: {card.get('title')}")
    return len(checks), len(observed_urls)


def validate(issue_date: str) -> dict[str, int]:
    try:
        datetime.strptime(issue_date, "%Y-%m-%d")
    except ValueError:
        fail(f"invalid issue date: {issue_date}")
    base = STATE_ROOT / issue_date
    issue_path = base / "issue.json"
    issue = load_object(issue_path)
    bundle = load_object(base / "evidence.json")
    state.validate_issue_state(issue, issue_path)
    if bundle.get("issue_date") != issue_date:
        fail("research bundle date mismatch")

    contract = load_contract()
    configured = configured_categories(contract)
    categories = bundle.get("categories")
    if not isinstance(categories, dict) or set(categories) != set(configured):
        fail("research bundle category set does not match the coverage contract")
    cards = [card for card in issue.get("cards", []) if isinstance(card, dict)]
    registry = source_registry()
    source_checks = 0
    observed_urls = 0
    for label, config in configured.items():
        entry = categories[label]
        if not isinstance(entry, dict):
            fail(f"{label} evidence entry must be an object")
        checks, observed = validate_category(
            label, config, entry, cards, registry, issue_date
        )
        source_checks += checks
        observed_urls += observed

    dated_index = SITE_ROOT / issue_date / "index.html"
    root_index = SITE_ROOT / "index.html"
    if dated_index.exists() and root_index.exists():
        dated_text = visible_text(dated_index.read_text(encoding="utf-8"))
        root_text = visible_text(root_index.read_text(encoding="utf-8"))
        for label, config in configured.items():
            if label not in dated_text or str(config.get("section_id")) not in dated_index.read_text(
                encoding="utf-8"
            ):
                fail(f"dated page is missing category section: {label}")
        for card in cards:
            title = str(card.get("title"))
            if title not in dated_text or title not in root_text:
                fail(f"public pages are missing current update: {title}")

    return {
        "categories": len(configured),
        "cards": len(cards),
        "source_checks": source_checks,
        "observed_urls": observed_urls,
    }


def main() -> int:
    issue_date = sys.argv[1] if len(sys.argv) > 1 else datetime.now().date().isoformat()
    result = validate(issue_date)
    print(
        f"COVERAGE AUDIT PASSED: {issue_date}, categories={result['categories']}, "
        f"cards={result['cards']}, source_checks={result['source_checks']}, "
        f"observed_urls={result['observed_urls']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
