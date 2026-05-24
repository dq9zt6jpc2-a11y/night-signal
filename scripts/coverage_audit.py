#!/usr/bin/env python3
"""Audit NIGHT SIGNAL collection coverage against a structured contract.

This catches the class of failures where the page date is current but the
research process is not: copied manifests, missing search axes, thin evidence,
or cards that no longer match the extraction log.
"""

from __future__ import annotations

import json
import re
import sys
import html as html_lib
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "site"
CONFIG_PATH = ROOT / "config" / "night_signal_coverage.json"
URL_RE = re.compile(r"https?://[^\s\"'<>)]+")
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
SNS_HOSTS = {"x.com", "twitter.com"}
YOUTUBE_HOSTS = {"youtube.com", "youtu.be"}
DEFERRED_PUBLISHING_RE = re.compile(r"(未反映|次回|次の再抽出|次の採用候補|次回の採用候補)")
SEARCH_RESULT_HOSTS = {"google.com", "bing.com", "duckduckgo.com"}
ECONOMIC_REGION_SECTION_LABELS = ["日本経済", "アジア経済", "北米経済"]
FORBIDDEN_BROAD_ECONOMIC_LABELS = {"投資"}


def fail(message: str) -> None:
    print(f"COVERAGE AUDIT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: Path) -> str:
    if not path.exists():
        fail(f"missing file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def issue_date_from_args() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    return datetime.now().strftime("%Y-%m-%d")


def visible_text(html: str) -> str:
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<style\b.*?</style>", "", html, flags=re.S | re.I)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", text).strip()


def section_before_history(html: str) -> str:
    return html.split('<section class="section" id="history">', 1)[0]


def load_contract() -> dict:
    try:
        contract = json.loads(read(CONFIG_PATH))
    except json.JSONDecodeError as exc:
        fail(f"coverage contract JSON is invalid: {exc}")
    validate_economic_taxonomy_contract(contract)
    return contract


def validate_economic_taxonomy_contract(contract: dict) -> None:
    categories = contract.get("categories")
    if not isinstance(categories, list):
        fail("coverage contract missing categories")
    labels = [category.get("label") for category in categories if isinstance(category, dict)]
    forbidden = sorted(label for label in labels if label in FORBIDDEN_BROAD_ECONOMIC_LABELS)
    if forbidden:
        fail("coverage contract still contains broad economic sections: " + ", ".join(forbidden))
    missing = [label for label in ECONOMIC_REGION_SECTION_LABELS if label not in labels]
    if missing:
        fail("coverage contract missing regional economic sections: " + ", ".join(missing))


def effective_on_or_after(contract: dict, key: str, issue_dt) -> bool:
    value = contract.get(key)
    if value is None:
        return False
    if not isinstance(value, str):
        fail(f"coverage contract {key} must be YYYY-MM-DD")
    try:
        effective_dt = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        fail(f"coverage contract {key} must be YYYY-MM-DD")
    return issue_dt >= effective_dt


def extract_manifest(extraction_log_html: str) -> dict:
    match = re.search(
        r'<script type="application/json" id="coverage-manifest">(.*?)</script>',
        extraction_log_html,
        flags=re.S,
    )
    if not match:
        fail("extraction log missing coverage-manifest JSON")
    try:
        return json.loads(match.group(1))
    except json.JSONDecodeError as exc:
        fail(f"coverage-manifest JSON is invalid: {exc}")


def card_titles_by_section(root_html: str, section_id: str) -> list[str]:
    body = section_before_history(root_html)
    match = re.search(
        rf'<section class="section" id="{re.escape(section_id)}">(.*?)(?=<section class="section" id=|\Z)',
        body,
        flags=re.S,
    )
    if not match:
        fail(f"root page missing section for coverage contract: {section_id}")
    titles = []
    for article in re.findall(r'<article class="card[^"]*">(.*?)</article>', match.group(1), flags=re.S):
        h3 = re.search(r"<h3>(.*?)</h3>", article, flags=re.S)
        if h3:
            titles.append(visible_text(h3.group(1)))
    return titles


def normalize_url_host(url: str) -> str | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None
    return parsed.netloc.lower().removeprefix("www.")


def normalize_url(url: str) -> str:
    return url.strip().rstrip("/")


def urls_in(values: list[str]) -> list[str]:
    urls: list[str] = []
    for value in values:
        if normalize_url_host(value):
            urls.append(value)
            continue
        urls.extend(URL_RE.findall(value))
    return urls


def has_japanese(text: str) -> bool:
    return bool(JAPANESE_RE.search(text))


def host_matches(url: str, expected_hosts: set[str]) -> bool:
    host = normalize_url_host(url)
    return bool(host and any(host == expected or host.endswith("." + expected) for expected in expected_hosts))


def is_search_result_url(url: str) -> bool:
    host = normalize_url_host(url)
    path = urlparse(url).path.lower()
    if not host:
        return False
    if host in SEARCH_RESULT_HOSTS or any(host.endswith("." + expected) for expected in SEARCH_RESULT_HOSTS):
        return True
    if host_matches(url, YOUTUBE_HOSTS) and path == "/results":
        return True
    if host_matches(url, SNS_HOSTS) and path == "/search":
        return True
    return False


def require_channel_url(category: str, key: str, values: list[str], expected_hosts: set[str], label: str) -> None:
    if not any(host_matches(url, expected_hosts) for url in urls_in(values)):
        fail(f"{category} {key} must include {label} URL evidence")


def string_list(entry: dict, key: str, category: str) -> list[str]:
    value = entry.get(key)
    if not isinstance(value, list):
        fail(f"{category} {key} must be a list")
    if any(not isinstance(item, str) or len(item.strip()) < 4 for item in value):
        fail(f"{category} {key} contains weak entries")
    return value


def validate_last_checked(issue_date: str, manifest: dict) -> None:
    value = manifest.get("last_checked_jst")
    if not isinstance(value, str) or not value:
        fail("coverage-manifest missing last_checked_jst")
    try:
        checked = datetime.fromisoformat(value)
    except ValueError:
        fail(f"last_checked_jst is not ISO-8601: {value}")
    if checked.strftime("%Y-%m-%d") != issue_date:
        fail(f"last_checked_jst date mismatch: {value} != {issue_date}")


def validate_sources(contract: dict, category: str, entry: dict) -> tuple[int, set[str]]:
    total_urls = 0
    hosts: set[str] = set()
    for source_class, rule in contract["source_classes"].items():
        values = string_list(entry, source_class, category)
        if len(values) < int(rule.get("min_items", 1)):
            fail(f"{category} has too little source evidence: {source_class}")
        class_urls = 0
        for item in values:
            host = normalize_url_host(item)
            if host:
                hosts.add(host)
                total_urls += 1
                class_urls += 1
        if rule.get("url_required") and class_urls < int(rule.get("min_items", 1)):
            fail(f"{category} {source_class} must include URL evidence")
        if rule.get("must_contain_digit") and not any(re.search(r"\d", item) for item in values):
            fail(f"{category} {source_class} must include numeric evidence")
        if source_class == "sns_x":
            require_channel_url(category, source_class, values, SNS_HOSTS, "SNS/X")
        if source_class == "youtube_video":
            require_channel_url(category, source_class, values, YOUTUBE_HOSTS, "YouTube")
    return total_urls, hosts


def validate_decisions(contract: dict, category: str, entry: dict) -> None:
    for decision_class, rule in contract["decision_classes"].items():
        values = string_list(entry, decision_class, category)
        if len(values) < int(rule.get("min_items", 1)):
            fail(f"{category} has too few decision entries: {decision_class}")
    critical = entry.get("critical_unresolved")
    if not isinstance(critical, list):
        fail(f"{category} critical_unresolved must be a list")
    if critical:
        fail(f"{category} has critical unresolved risks: {critical}")


def validate_search_axes(contract: dict, category_config: dict, entry: dict) -> None:
    axes = entry.get("search_axes")
    if not isinstance(axes, dict):
        fail(f"{category_config['label']} missing search_axes")
    min_queries = int(contract.get("minimum_search_queries_per_axis", 1))
    for axis in category_config["axes"]:
        axis_id = axis["id"]
        values = axes.get(axis_id)
        if not isinstance(values, list) or len(values) < min_queries:
            fail(f"{category_config['label']} search_axis {axis_id} needs at least {min_queries} queries")
        if any(not isinstance(item, str) or len(item.strip()) < 4 for item in values):
            fail(f"{category_config['label']} search_axis {axis_id} has weak query text")
        blob = " ".join(values).lower()
        if not any(term.lower() in blob for term in axis["terms"]):
            fail(f"{category_config['label']} search_axis {axis_id} missing expected terms")


def validate_card_manifest_alignment(contract: dict, root_html: str, category_config: dict, entry: dict) -> None:
    category = category_config["label"]
    expected_titles = card_titles_by_section(root_html, category_config["section_id"])
    minimum = int(contract.get("minimum_published_cards_per_category", 0))
    if len(expected_titles) < minimum:
        fail(f"{category} section has too few published cards for coverage alignment")
    manifest_titles = entry.get("published_card_titles")
    if not isinstance(manifest_titles, list) or any(not isinstance(item, str) for item in manifest_titles):
        fail(f"{category} missing published_card_titles")
    if manifest_titles != expected_titles:
        fail(
            f"{category} published_card_titles do not match page cards: "
            f"manifest={manifest_titles}, page={expected_titles}"
        )


def card_detail_by_title(root_html: str, category_config: dict) -> dict[str, str]:
    section_id = category_config["section_id"]
    body = section_before_history(root_html)
    match = re.search(
        rf'<section class="section" id="{re.escape(section_id)}">(.*?)(?=<section class="section" id=|\Z)',
        body,
        flags=re.S,
    )
    if not match:
        fail(f"root page missing section for detail mapping: {section_id}")
    mapping: dict[str, str] = {}
    for article in re.findall(r'<article class="card[^"]*">(.*?)</article>', match.group(1), flags=re.S):
        h3 = re.search(r"<h3>(.*?)</h3>", article, flags=re.S)
        href = re.search(r'href="(?:\d{4}-\d{2}-\d{2}/)?details/([^"#?]+\.html)"', article)
        if h3 and href:
            mapping[visible_text(h3.group(1))] = href.group(1)
    return mapping


def source_urls_from_detail(issue_date: str, detail_name: str) -> set[str]:
    html = read(SITE_ROOT / issue_date / "details" / detail_name)
    source_match = re.search(r'<div class="source">(.*?)</div>', html, flags=re.S)
    if not source_match:
        fail(f"detail page missing source block for coverage item: {detail_name}")
    return {
        normalize_url(html_lib.unescape(match))
        for match in re.findall(r'href="([^"]+)"', source_match.group(1))
        if normalize_url_host(html_lib.unescape(match))
    }


def validate_new_or_changed_items(contract: dict, issue_date: str, root_html: str, category_config: dict, entry: dict) -> None:
    category = category_config["label"]
    expected_titles = card_titles_by_section(root_html, category_config["section_id"])
    detail_by_title = card_detail_by_title(root_html, category_config)
    items = entry.get("new_or_changed_items")
    minimum = int(contract.get("minimum_new_or_changed_items_per_category", 1))
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    min_summary_chars = 60
    if effective_on_or_after(contract, "summary_quality_effective_date", issue_dt):
        min_summary_chars = int(contract.get("minimum_new_or_changed_summary_chars", 120))
    if not isinstance(items, list) or len(items) < minimum:
        fail(f"{category} needs at least {minimum} new_or_changed_items")

    item_titles: list[str] = []
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            fail(f"{category} new_or_changed_items[{index}] must be an object")
        title = item.get("title")
        summary = item.get("summary")
        sources = item.get("sources")
        if not isinstance(title, str) or title not in expected_titles:
            fail(f"{category} new_or_changed_items[{index}] title must match a published card")
        if not isinstance(summary, str) or len(re.sub(r"\s+", "", summary)) < min_summary_chars:
            fail(f"{category} new_or_changed_items[{index}] summary is too thin")
        if not isinstance(summary, str) or not has_japanese(summary):
            fail(f"{category} new_or_changed_items[{index}] summary must be Japanese")
        if not isinstance(sources, list) or not sources or any(not isinstance(source, str) for source in sources):
            fail(f"{category} new_or_changed_items[{index}] sources must be a non-empty string list")
        source_urls = [normalize_url(url) for url in urls_in(sources)]
        if not source_urls:
            fail(f"{category} new_or_changed_items[{index}] must include URL sources")
        detail_urls = source_urls_from_detail(issue_date, detail_by_title[title])
        if not any(url in detail_urls for url in source_urls):
            fail(f"{category} new_or_changed_items[{index}] sources must overlap linked detail page sources")
        item_titles.append(title)

    if item_titles != expected_titles:
        fail(f"{category} new_or_changed_items must mirror published cards: items={item_titles}, page={expected_titles}")


def validate_latest_candidates(contract: dict, issue_date: str, root_html: str, category_config: dict, entry: dict) -> None:
    category = category_config["label"]
    watch_topics = category_config.get("watch_topics")
    if not isinstance(watch_topics, list) or not watch_topics:
        fail(f"{category} coverage contract missing watch_topics")

    candidates = entry.get("latest_candidates")
    if not isinstance(candidates, list):
        fail(f"{category} missing latest_candidates")

    expected_titles = card_titles_by_section(root_html, category_config["section_id"])
    detail_by_title = card_detail_by_title(root_html, category_config)
    watch_ids = {topic["id"] for topic in watch_topics if isinstance(topic, dict) and isinstance(topic.get("id"), str)}
    if len(watch_ids) != len(watch_topics):
        fail(f"{category} watch_topics are invalid")

    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    max_age = int(contract.get("maximum_adopted_candidate_source_age_days", 3))
    strict_source_age_applies = effective_on_or_after(
        contract, "strict_adopted_candidate_source_age_effective_date", issue_dt
    )
    fresh_reason_applies = effective_on_or_after(
        contract, "fresh_non_adopted_reason_required_effective_date", issue_dt
    )
    allowed_non_adoption_reasons = contract.get("allowed_non_adoption_reason_classes", [])
    if not isinstance(allowed_non_adoption_reasons, list) or any(
        not isinstance(item, str) for item in allowed_non_adoption_reasons
    ):
        fail("coverage contract allowed_non_adoption_reason_classes must be a string list")
    min_per_topic = int(contract.get("minimum_latest_candidates_per_watch_topic", 1))
    by_topic = {topic_id: 0 for topic_id in watch_ids}
    adopted_titles: list[str] = []

    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            fail(f"{category} latest_candidates[{index}] must be an object")
        topic_id = candidate.get("topic_id")
        title = candidate.get("title")
        source_url = candidate.get("source_url")
        source_date = candidate.get("source_published_date")
        decision = candidate.get("decision")
        rationale = candidate.get("rationale")
        if topic_id not in watch_ids:
            fail(f"{category} latest_candidates[{index}] topic_id is not configured: {topic_id}")
        by_topic[topic_id] += 1
        if not isinstance(title, str) or len(title.strip()) < 8:
            fail(f"{category} latest_candidates[{index}] title is too weak")
        if not isinstance(source_url, str) or not normalize_url_host(source_url):
            fail(f"{category} latest_candidates[{index}] source_url must be absolute")
        if is_search_result_url(source_url):
            fail(f"{category} latest_candidates[{index}] source_url cannot be a search result URL")
        if decision not in {"adopted", "held", "excluded", "no_fresh_item"}:
            fail(f"{category} latest_candidates[{index}] decision is invalid: {decision}")
        if not isinstance(rationale, str) or len(re.sub(r"\s+", "", rationale)) < 30 or not has_japanese(rationale):
            fail(f"{category} latest_candidates[{index}] rationale must be a concrete Japanese decision")
        if not isinstance(source_date, str):
            fail(f"{category} latest_candidates[{index}] missing source_published_date")
        try:
            candidate_dt = datetime.strptime(source_date, "%Y-%m-%d").date()
        except ValueError:
            fail(f"{category} latest_candidates[{index}] source_published_date must be YYYY-MM-DD")
        if candidate_dt > issue_dt:
            fail(f"{category} latest_candidates[{index}] source_published_date is in the future: {source_date}")
        age = (issue_dt - candidate_dt).days
        if decision == "held" and age <= max_age and DEFERRED_PUBLISHING_RE.search(rationale):
            fail(f"{category} fresh latest candidate was deferred instead of resolved: {title}")
        if decision in {"held", "excluded", "no_fresh_item"} and age <= max_age and fresh_reason_applies:
            reason_class = candidate.get("non_adoption_reason_class")
            if reason_class not in allowed_non_adoption_reasons:
                fail(
                    f"{category} fresh non-adopted latest candidate missing non_adoption_reason_class: "
                    f"{title}"
                )
        if decision == "adopted":
            if title not in expected_titles:
                fail(f"{category} adopted latest candidate is not published as a card: {title}")
            if age > max_age and strict_source_age_applies:
                fail(
                    f"{category} adopted latest candidate exceeds strict source age and must stay background-only: "
                    f"{title} ({source_date}, {age} days old)"
                )
            freshness_override = candidate.get("freshness_override")
            if age > max_age and (
                not isinstance(freshness_override, str)
                or len(re.sub(r"\s+", "", freshness_override)) < 30
                or not has_japanese(freshness_override)
            ):
                fail(f"{category} adopted latest candidate is stale: {title} ({source_date}, {age} days old)")
            detail_urls = source_urls_from_detail(issue_date, detail_by_title[title])
            if normalize_url(source_url) not in detail_urls:
                fail(f"{category} adopted latest candidate source must overlap linked detail page: {title}")
            adopted_titles.append(title)

    missing_topics = [topic_id for topic_id, count in sorted(by_topic.items()) if count < min_per_topic]
    if missing_topics:
        fail(f"{category} latest_candidates missing watch topics: " + ", ".join(missing_topics))

    missing_adopted = [title for title in expected_titles if title not in adopted_titles]
    if missing_adopted:
        fail(f"{category} published cards must come from adopted latest_candidates: " + "; ".join(missing_adopted))


def validate_collected_items(contract: dict, issue_date: str, category_config: dict, entry: dict) -> None:
    category = category_config["label"]
    watch_topics = category_config.get("watch_topics")
    if not isinstance(watch_topics, list) or not watch_topics:
        fail(f"{category} coverage contract missing watch_topics")
    watch_ids = {topic["id"] for topic in watch_topics if isinstance(topic, dict) and isinstance(topic.get("id"), str)}

    candidates = entry.get("latest_candidates")
    if not isinstance(candidates, list):
        fail(f"{category} missing latest_candidates")
    expected_keys = set()
    candidate_titles_by_topic: dict[str, set[str]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        topic_id = candidate.get("topic_id")
        title = candidate.get("title")
        source_url = candidate.get("source_url")
        if isinstance(topic_id, str) and isinstance(title, str) and isinstance(source_url, str):
            key = (topic_id, title, normalize_url(source_url))
            expected_keys.add(key)
            candidate_titles_by_topic.setdefault(topic_id, set()).add(title)

    collected = entry.get("collected_items")
    if not isinstance(collected, list):
        fail(f"{category} missing collected_items")
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    collected_keys = set()
    for index, item in enumerate(collected, start=1):
        if not isinstance(item, dict):
            fail(f"{category} collected_items[{index}] must be an object")
        topic_id = item.get("topic_id")
        title = item.get("title")
        source_url = item.get("source_url")
        source_date = item.get("source_published_date")
        observed_at = item.get("observed_at_jst")
        channel = item.get("channel")
        note = item.get("collection_note")
        if topic_id not in watch_ids:
            fail(f"{category} collected_items[{index}] topic_id is not configured: {topic_id}")
        if not isinstance(title, str) or title not in candidate_titles_by_topic.get(topic_id, set()):
            fail(f"{category} collected_items[{index}] title must match latest_candidates for same topic")
        if not isinstance(source_url, str) or not normalize_url_host(source_url):
            fail(f"{category} collected_items[{index}] source_url must be absolute")
        if is_search_result_url(source_url):
            fail(f"{category} collected_items[{index}] source_url cannot be a search result URL")
        if channel not in {"web", "sns_x", "youtube"}:
            fail(f"{category} collected_items[{index}] channel is invalid: {channel}")
        if channel == "sns_x" and not host_matches(source_url, SNS_HOSTS):
            fail(f"{category} collected_items[{index}] channel/source mismatch for SNS/X")
        if channel == "youtube" and not host_matches(source_url, YOUTUBE_HOSTS):
            fail(f"{category} collected_items[{index}] channel/source mismatch for YouTube")
        if channel == "web" and (host_matches(source_url, SNS_HOSTS) or host_matches(source_url, YOUTUBE_HOSTS)):
            fail(f"{category} collected_items[{index}] channel/source mismatch for Web")
        if not isinstance(source_date, str):
            fail(f"{category} collected_items[{index}] missing source_published_date")
        try:
            source_dt = datetime.strptime(source_date, "%Y-%m-%d").date()
        except ValueError:
            fail(f"{category} collected_items[{index}] source_published_date must be YYYY-MM-DD")
        if source_dt > issue_dt:
            fail(f"{category} collected_items[{index}] source_published_date is in the future: {source_date}")
        if not isinstance(observed_at, str):
            fail(f"{category} collected_items[{index}] missing observed_at_jst")
        try:
            observed_dt = datetime.fromisoformat(observed_at)
        except ValueError:
            fail(f"{category} collected_items[{index}] observed_at_jst is not ISO-8601: {observed_at}")
        offset = observed_dt.utcoffset()
        if offset is None or offset.total_seconds() != 9 * 60 * 60:
            fail(f"{category} collected_items[{index}] observed_at_jst must use JST offset: {observed_at}")
        if observed_dt.strftime("%Y-%m-%d") != issue_date:
            fail(f"{category} collected_items[{index}] observed_at_jst date mismatch: {observed_at} != {issue_date}")
        if not isinstance(note, str) or len(re.sub(r"\s+", "", note)) < 30 or not has_japanese(note):
            fail(f"{category} collected_items[{index}] collection_note must be concrete Japanese text")
        collected_keys.add((topic_id, title, normalize_url(source_url)))

    missing = sorted(expected_keys - collected_keys)
    if missing:
        fail(f"{category} collected_items missing latest candidate sources: " + "; ".join(title for _, title, _ in missing))


def validate_search_sweep(contract: dict, category: str, index: int, check: dict) -> None:
    sweep = check.get("search_sweep")
    if not isinstance(sweep, dict):
        fail(f"{category} watch_topic_checks[{index}] missing search_sweep")

    min_queries = int(contract.get("minimum_search_sweep_queries_per_watch_topic", 1))
    queries = sweep.get("queries")
    if not isinstance(queries, list) or len(queries) < min_queries:
        fail(f"{category} watch_topic_checks[{index}].search_sweep needs at least {min_queries} queries")
    for query_index, query in enumerate(queries, start=1):
        if not isinstance(query, str) or len(query.strip()) < 8:
            fail(f"{category} watch_topic_checks[{index}].search_sweep.queries[{query_index}] is too weak")
        if urls_in([query]):
            fail(f"{category} watch_topic_checks[{index}].search_sweep.queries[{query_index}] must be query text, not a URL")

    allowed_results = contract.get("allowed_search_sweep_results", [])
    if not isinstance(allowed_results, list) or any(not isinstance(item, str) for item in allowed_results):
        fail("coverage contract allowed_search_sweep_results must be a string list")
    result = sweep.get("result")
    if result not in allowed_results:
        fail(f"{category} watch_topic_checks[{index}].search_sweep result is invalid: {result}")

    selection_reason = sweep.get("selection_reason")
    if (
        not isinstance(selection_reason, str)
        or len(re.sub(r"\s+", "", selection_reason)) < 35
        or not has_japanese(selection_reason)
    ):
        fail(f"{category} watch_topic_checks[{index}].search_sweep selection_reason must be concrete Japanese text")


def validate_watch_topic_checks(contract: dict, issue_date: str, category_config: dict, entry: dict) -> None:
    category = category_config["label"]
    watch_topics = category_config.get("watch_topics")
    if not isinstance(watch_topics, list) or not watch_topics:
        fail(f"{category} coverage contract missing watch_topics")
    watch_ids = {topic["id"] for topic in watch_topics if isinstance(topic, dict) and isinstance(topic.get("id"), str)}
    if len(watch_ids) != len(watch_topics):
        fail(f"{category} watch_topics are invalid")

    candidates = entry.get("latest_candidates")
    if not isinstance(candidates, list):
        fail(f"{category} missing latest_candidates")
    candidate_titles_by_topic: dict[str, set[str]] = {}
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        topic_id = candidate.get("topic_id")
        title = candidate.get("title")
        if isinstance(topic_id, str) and isinstance(title, str):
            candidate_titles_by_topic.setdefault(topic_id, set()).add(title)

    required_channels = contract.get("required_watch_topic_channels", ["web", "sns_x", "youtube"])
    if (
        not isinstance(required_channels, list)
        or not required_channels
        or any(channel not in {"web", "sns_x", "youtube"} for channel in required_channels)
    ):
        fail("coverage contract has invalid required_watch_topic_channels")

    checks = entry.get("watch_topic_checks")
    if not isinstance(checks, list):
        fail(f"{category} missing watch_topic_checks")

    min_per_topic = int(contract.get("minimum_watch_topic_checks_per_topic", 1))
    allowed_event_classes = contract.get("allowed_discovery_event_classes", [])
    if not isinstance(allowed_event_classes, list) or any(not isinstance(item, str) for item in allowed_event_classes):
        fail("coverage contract has invalid allowed_discovery_event_classes")
    allowed_event_class_set = set(allowed_event_classes)
    required_source_roles = contract.get("required_investigation_source_roles", [])
    if not isinstance(required_source_roles, list) or any(not isinstance(item, str) for item in required_source_roles):
        fail("coverage contract has invalid required_investigation_source_roles")
    min_paths = int(contract.get("minimum_investigation_paths_per_watch_topic", 0))
    min_hypotheses = int(contract.get("minimum_investigation_hypotheses_per_watch_topic", 0))
    min_window_hours = int(contract.get("minimum_investigation_time_window_hours", 0))
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    search_sweep_required = effective_on_or_after(contract, "search_sweep_required_effective_date", issue_dt)
    by_topic = {topic_id: 0 for topic_id in watch_ids}
    for index, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            fail(f"{category} watch_topic_checks[{index}] must be an object")
        topic_id = check.get("topic_id")
        if not isinstance(topic_id, str) or topic_id not in watch_ids:
            fail(f"{category} watch_topic_checks[{index}] topic_id is not configured: {topic_id}")
        by_topic[topic_id] += 1

        checked_at = check.get("checked_at_jst")
        if not isinstance(checked_at, str):
            fail(f"{category} watch_topic_checks[{index}] missing checked_at_jst")
        try:
            checked_dt = datetime.fromisoformat(checked_at)
        except ValueError:
            fail(f"{category} watch_topic_checks[{index}] checked_at_jst is not ISO-8601: {checked_at}")
        offset = checked_dt.utcoffset()
        if offset is None or offset.total_seconds() != 9 * 60 * 60:
            fail(f"{category} watch_topic_checks[{index}] checked_at_jst must use JST offset: {checked_at}")
        if checked_dt.strftime("%Y-%m-%d") != issue_date:
            fail(f"{category} watch_topic_checks[{index}] checked_at_jst date mismatch: {checked_at} != {issue_date}")

        result = check.get("result")
        if not isinstance(result, str) or len(re.sub(r"\s+", "", result)) < 30:
            fail(f"{category} watch_topic_checks[{index}] result is too thin")
        if not has_japanese(result):
            fail(f"{category} watch_topic_checks[{index}] result must be Japanese")

        configured_event_classes = []
        for topic in watch_topics:
            if isinstance(topic, dict) and topic.get("id") == topic_id and isinstance(topic.get("event_classes"), list):
                configured_event_classes = [item for item in topic["event_classes"] if isinstance(item, str)]
                break
        if not configured_event_classes:
            fail(f"{category} watch_topic {topic_id} missing event_classes")
        if any(item not in allowed_event_class_set for item in configured_event_classes):
            fail(f"{category} watch_topic {topic_id} has invalid event_classes")

        check_event_classes = check.get("event_classes")
        if not isinstance(check_event_classes, list) or any(not isinstance(item, str) for item in check_event_classes):
            fail(f"{category} watch_topic_checks[{index}] event_classes must be a string list")
        missing_event_classes = sorted(set(configured_event_classes) - set(check_event_classes))
        if missing_event_classes:
            fail(f"{category} watch_topic_checks[{index}] missing event_classes: " + ", ".join(missing_event_classes))

        source_roles = check.get("source_roles_checked")
        if not isinstance(source_roles, list) or any(not isinstance(item, str) for item in source_roles):
            fail(f"{category} watch_topic_checks[{index}] source_roles_checked must be a string list")
        missing_roles = sorted(set(required_source_roles) - set(source_roles))
        if missing_roles:
            fail(f"{category} watch_topic_checks[{index}] missing source_roles_checked: " + ", ".join(missing_roles))

        paths = check.get("investigation_paths")
        if not isinstance(paths, list) or len(paths) < min_paths:
            fail(f"{category} watch_topic_checks[{index}] needs at least {min_paths} investigation_paths")
        path_roles: set[str] = set()
        for path_index, path in enumerate(paths, start=1):
            if not isinstance(path, dict):
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] must be an object")
            role = path.get("source_role")
            channel = path.get("channel")
            evidence_url = path.get("evidence_url")
            finding = path.get("finding")
            if role not in required_source_roles:
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] source_role is invalid: {role}")
            path_roles.add(role)
            if channel not in {"web", "sns_x", "youtube"}:
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] channel is invalid: {channel}")
            if not isinstance(evidence_url, str) or not normalize_url_host(evidence_url):
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] evidence_url must be absolute")
            if is_search_result_url(evidence_url):
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] evidence_url cannot be a search result URL")
            if channel == "sns_x" and not host_matches(evidence_url, SNS_HOSTS):
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] channel/source mismatch for SNS/X")
            if channel == "youtube" and not host_matches(evidence_url, YOUTUBE_HOSTS):
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] channel/source mismatch for YouTube")
            if channel == "web" and (host_matches(evidence_url, SNS_HOSTS) or host_matches(evidence_url, YOUTUBE_HOSTS)):
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] channel/source mismatch for Web")
            if not isinstance(finding, str) or len(re.sub(r"\s+", "", finding)) < 25 or not has_japanese(finding):
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] finding must be concrete Japanese text")
        missing_path_roles = sorted(set(required_source_roles) - path_roles)
        if missing_path_roles:
            fail(f"{category} watch_topic_checks[{index}] missing investigation_paths roles: " + ", ".join(missing_path_roles))

        hypotheses = check.get("investigation_hypotheses")
        if (
            min_hypotheses > 0
            and (
                not isinstance(hypotheses, list)
                or len(hypotheses) < min_hypotheses
                or any(not isinstance(item, str) or len(re.sub(r"\s+", "", item)) < 25 or not has_japanese(item) for item in hypotheses)
            )
        ):
            fail(f"{category} watch_topic_checks[{index}] needs at least {min_hypotheses} concrete Japanese investigation_hypotheses")

        window = check.get("time_window_jst")
        if not isinstance(window, dict):
            fail(f"{category} watch_topic_checks[{index}] missing time_window_jst")
        try:
            start_dt = datetime.fromisoformat(window.get("start", ""))
            end_dt = datetime.fromisoformat(window.get("end", ""))
        except (TypeError, ValueError):
            fail(f"{category} watch_topic_checks[{index}] time_window_jst must contain ISO start/end")
        if start_dt.utcoffset() is None or end_dt.utcoffset() is None:
            fail(f"{category} watch_topic_checks[{index}] time_window_jst must use timezone offsets")
        if end_dt <= start_dt:
            fail(f"{category} watch_topic_checks[{index}] time_window_jst end must be after start")
        if min_window_hours > 0 and (end_dt - start_dt).total_seconds() < min_window_hours * 3600:
            fail(f"{category} watch_topic_checks[{index}] time_window_jst is too short")
        if end_dt.strftime("%Y-%m-%d") != issue_date:
            fail(f"{category} watch_topic_checks[{index}] time_window_jst end date mismatch: {end_dt.date()} != {issue_date}")

        delta_basis = check.get("delta_basis")
        if not isinstance(delta_basis, str) or len(re.sub(r"\s+", "", delta_basis)) < 30 or not has_japanese(delta_basis):
            fail(f"{category} watch_topic_checks[{index}] delta_basis must be concrete Japanese text")

        if search_sweep_required:
            validate_search_sweep(contract, category, index, check)

        titles = check.get("candidate_titles")
        if not isinstance(titles, list) or not titles or any(not isinstance(title, str) for title in titles):
            fail(f"{category} watch_topic_checks[{index}] candidate_titles must be a non-empty string list")
        known_titles_for_topic = candidate_titles_by_topic.get(topic_id, set())
        unknown_titles = [title for title in titles if title not in known_titles_for_topic]
        if unknown_titles:
            fail(
                f"{category} watch_topic_checks[{index}] candidate_titles must match latest_candidates for same topic: "
                + "; ".join(unknown_titles)
            )

        for channel in required_channels:
            values = check.get(channel)
            if not isinstance(values, list) or not values or any(not isinstance(value, str) for value in values):
                fail(f"{category} watch_topic_checks[{index}].{channel} must be a non-empty string list")
            evidence_urls = urls_in(values)
            if not evidence_urls:
                fail(f"{category} watch_topic_checks[{index}].{channel} must include URL evidence")
            if channel == "web" and not any(
                not host_matches(url, SNS_HOSTS) and not host_matches(url, YOUTUBE_HOSTS) for url in evidence_urls
            ):
                fail(f"{category} watch_topic_checks[{index}].web must include Web URL evidence")
            if channel == "sns_x":
                require_channel_url(category, f"watch_topic_checks[{index}].sns_x", values, SNS_HOSTS, "SNS/X")
            if channel == "youtube":
                require_channel_url(category, f"watch_topic_checks[{index}].youtube", values, YOUTUBE_HOSTS, "YouTube")

    missing_topics = [topic_id for topic_id, count in sorted(by_topic.items()) if count < min_per_topic]
    if missing_topics:
        fail(f"{category} watch_topic_checks missing topics: " + ", ".join(missing_topics))


def validate_no_change_checks(contract: dict, category: str, entry: dict) -> None:
    minimum = int(contract.get("minimum_no_change_checks_per_category", 1))
    checks = entry.get("no_change_checks")
    if not isinstance(checks, list) or len(checks) < minimum:
        fail(f"{category} needs at least {minimum} no_change_checks")
    for index, check in enumerate(checks, start=1):
        if not isinstance(check, dict):
            fail(f"{category} no_change_checks[{index}] must be an object")
        axis = check.get("axis")
        result = check.get("result")
        sources = check.get("sources")
        if not isinstance(axis, str) or len(axis.strip()) < 4:
            fail(f"{category} no_change_checks[{index}] axis is too weak")
        if not isinstance(result, str) or len(re.sub(r"\s+", "", result)) < 30:
            fail(f"{category} no_change_checks[{index}] result is too thin")
        if not isinstance(result, str) or not has_japanese(result):
            fail(f"{category} no_change_checks[{index}] result must be Japanese")
        if not isinstance(sources, list) or not sources or any(not isinstance(source, str) for source in sources):
            fail(f"{category} no_change_checks[{index}] sources must be a non-empty string list")
        if not urls_in(sources):
            fail(f"{category} no_change_checks[{index}] must include URL evidence")
        require_channel_url(category, f"no_change_checks[{index}]", sources, SNS_HOSTS, "SNS/X")
        require_channel_url(category, f"no_change_checks[{index}]", sources, YOUTUBE_HOSTS, "YouTube")


def validate_coverage_contract(issue_date: str, root_html: str, extraction_log_html: str) -> None:
    contract = load_contract()
    manifest = extract_manifest(extraction_log_html)
    expected_version = contract.get("contract_version")
    if manifest.get("contract_version") != expected_version:
        fail(f"coverage contract version mismatch: {manifest.get('contract_version')} != {expected_version}")
    if manifest.get("date") != issue_date:
        fail(f"coverage-manifest date mismatch: {manifest.get('date')} != {issue_date}")
    validate_last_checked(issue_date, manifest)

    categories = manifest.get("categories")
    if not isinstance(categories, dict):
        fail("coverage-manifest missing categories object")
    forbidden_manifest_categories = sorted(set(categories).intersection(FORBIDDEN_BROAD_ECONOMIC_LABELS))
    if forbidden_manifest_categories:
        fail("coverage-manifest still contains broad economic categories: " + ", ".join(forbidden_manifest_categories))
    if re.search(r'<section class="section" id="investment">', root_html):
        fail("root page still contains broad investment section")

    configured_labels = [category["label"] for category in contract["categories"]]
    missing = [label for label in configured_labels if label not in categories]
    if missing:
        fail("coverage-manifest missing configured categories: " + ", ".join(missing))

    for category_config in contract["categories"]:
        category = category_config["label"]
        entry = categories[category]
        if not isinstance(entry, dict):
            fail(f"{category} manifest entry must be an object")
        if entry.get("collection_status") != "complete":
            fail(f"{category} collection_status must be complete")
        validate_card_manifest_alignment(contract, root_html, category_config, entry)
        validate_new_or_changed_items(contract, issue_date, root_html, category_config, entry)
        validate_latest_candidates(contract, issue_date, root_html, category_config, entry)
        validate_collected_items(contract, issue_date, category_config, entry)
        validate_watch_topic_checks(contract, issue_date, category_config, entry)
        validate_no_change_checks(contract, category, entry)
        validate_search_axes(contract, category_config, entry)
        total_urls, hosts = validate_sources(contract, category, entry)
        if total_urls < int(contract["minimum_url_evidence_per_category"]):
            fail(f"{category} has too little URL evidence: {total_urls}")
        if len(hosts) < int(contract["minimum_distinct_url_hosts_per_category"]):
            fail(f"{category} has too little source diversity: {len(hosts)} hosts")
        validate_decisions(contract, category, entry)
        freshness = entry.get("freshness_check")
        if not isinstance(freshness, str) or issue_date not in freshness:
            fail(f"{category} freshness_check must mention {issue_date}")


def main() -> int:
    issue_date = issue_date_from_args()
    root_html = read(SITE_ROOT / "index.html")
    extraction_log_html = read(ROOT / "details" / f"extraction-log-{issue_date}.html")
    validate_coverage_contract(issue_date, root_html, extraction_log_html)
    print(f"COVERAGE AUDIT PASSED: {issue_date}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
