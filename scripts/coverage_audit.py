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
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "site"
CONFIG_PATH = ROOT / "config" / "night_signal_coverage.json"


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
    text = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", text).strip()


def section_before_history(html: str) -> str:
    return html.split('<section class="section" id="history">', 1)[0]


def load_contract() -> dict:
    try:
        return json.loads(read(CONFIG_PATH))
    except json.JSONDecodeError as exc:
        fail(f"coverage contract JSON is invalid: {exc}")


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


def validate_card_manifest_alignment(root_html: str, category_config: dict, entry: dict) -> None:
    category = category_config["label"]
    expected_titles = card_titles_by_section(root_html, category_config["section_id"])
    if len(expected_titles) < 2:
        fail(f"{category} section has too few published cards for coverage alignment")
    manifest_titles = entry.get("published_card_titles")
    if not isinstance(manifest_titles, list) or any(not isinstance(item, str) for item in manifest_titles):
        fail(f"{category} missing published_card_titles")
    if manifest_titles != expected_titles:
        fail(
            f"{category} published_card_titles do not match page cards: "
            f"manifest={manifest_titles}, page={expected_titles}"
        )


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
        validate_card_manifest_alignment(root_html, category_config, entry)
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
