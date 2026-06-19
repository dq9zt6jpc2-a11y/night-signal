#!/usr/bin/env python3
"""Audit NIGHT SIGNAL collection coverage against a structured contract.

This catches the class of failures where the page date is current but the
research process is not: copied manifests, missing search axes, thin evidence,
or cards that no longer match the extraction log.
"""

from __future__ import annotations

import json
import subprocess
import re
import sys
import html as html_lib
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "site"
CONFIG_PATH = ROOT / "config" / "night_signal_coverage.json"
STATE_ROOT = ROOT / "state"
URL_RE = re.compile(r"https?://[^\s\"'<>)]+")
JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u3400-\u9fff]")
SNS_HOSTS = {"x.com", "twitter.com"}
INSTAGRAM_HOSTS = {"instagram.com"}
FACEBOOK_HOSTS = {"facebook.com", "fb.com"}
SOCIAL_HOSTS = SNS_HOSTS | INSTAGRAM_HOSTS | FACEBOOK_HOSTS
YOUTUBE_HOSTS = {"youtube.com", "youtu.be"}
DEFERRED_PUBLISHING_RE = re.compile(r"(未反映|次回|次の再抽出|次の採用候補|次回の採用候補)")
SEARCH_RESULT_HOSTS = {"google.com", "bing.com", "duckduckgo.com"}
ECONOMIC_REGION_SECTION_LABELS = ["日本経済", "アジア経済", "北米経済"]
FORBIDDEN_BROAD_ECONOMIC_LABELS = {"投資"}
CLAIM_TYPE_PATTERNS = {
    "result": [r"優勝", r"制し", r"勝利", r"表彰台", r"決勝結果", r"レース結果"],
    "schedule": [r"予定", r"日程", r"開催", r"公演", r"タイムテーブル"],
    "numeric": [r"\d+(?:\.\d+)?\s?(?:%|％|台|GW|MWh|円|ユーロ|ドル|億|兆)"],
    "award": [r"受賞", r"MVP", r"AWARD", r"表彰"],
    "announcement": [r"発表", r"公表", r"公開", r"リリース", r"掲載", r"更新", r"対応"],
    "status": [r"完走", r"終了", r"未掲載", r"確認", r"開幕"],
}
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


def required_channels_for_category(contract: dict, category_config: dict) -> list[str]:
    required_channels = category_config.get(
        "required_watch_topic_channels",
        contract.get("required_watch_topic_channels", ["web", "sns_x", "youtube"]),
    )
    if (
        not isinstance(required_channels, list)
        or not required_channels
        or any(channel not in {"web", "sns_x", "instagram", "facebook", "youtube"} for channel in required_channels)
    ):
        fail(f"{category_config['label']} has invalid required_watch_topic_channels")
    return required_channels


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


def max_adopted_source_age_days(contract: dict, issue_dt) -> int:
    if effective_on_or_after(contract, "latest_three_calendar_days_effective_date", issue_dt):
        return 2
    return int(contract.get("maximum_adopted_candidate_source_age_days", 3))


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


def expected_contract_version(contract: dict, issue_date: str) -> str | None:
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    legacy_versions = contract.get("legacy_contract_versions", [])
    if not isinstance(legacy_versions, list):
        fail("coverage contract legacy_contract_versions must be a list")
    for index, legacy in enumerate(legacy_versions, start=1):
        if not isinstance(legacy, dict):
            fail(f"coverage contract legacy_contract_versions[{index}] must be an object")
        through_date = legacy.get("through_date")
        version = legacy.get("version")
        try:
            through_dt = datetime.strptime(through_date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            fail(f"coverage contract legacy_contract_versions[{index}] through_date must be YYYY-MM-DD")
        if not isinstance(version, str) or not version:
            fail(f"coverage contract legacy_contract_versions[{index}] version is invalid")
        if issue_dt <= through_dt:
            return version
    return contract.get("contract_version")


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


def has_category_identity(category: str, text: str) -> bool:
    terms = CATEGORY_IDENTITY_TERMS.get(category)
    if not terms:
        return True
    lowered = text.lower()
    return any(term.lower() in lowered for term in terms)


def inferred_claim_types(text: str) -> set[str]:
    return {
        claim_type
        for claim_type, patterns in CLAIM_TYPE_PATTERNS.items()
        if any(re.search(pattern, text, flags=re.I) for pattern in patterns)
    }


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
    if host_matches(url, SOCIAL_HOSTS) and path == "/search":
        return True
    return False


def require_channel_url(category: str, key: str, values: list[str], expected_hosts: set[str], label: str) -> None:
    if not any(host_matches(url, expected_hosts) for url in urls_in(values)):
        fail(f"{category} {key} must include {label} URL evidence")


def require_required_channel_url(category: str, key: str, channel: str, values: list[str]) -> None:
    if channel == "sns_x":
        require_channel_url(category, key, values, SNS_HOSTS, "SNS/X")
    if channel == "instagram":
        require_channel_url(category, key, values, INSTAGRAM_HOSTS, "Instagram")
    if channel == "facebook":
        require_channel_url(category, key, values, FACEBOOK_HOSTS, "Facebook")
    if channel == "youtube":
        require_channel_url(category, key, values, YOUTUBE_HOSTS, "YouTube")


def validate_channel_source(category: str, key: str, channel: str, url: str) -> None:
    if channel == "sns_x" and not host_matches(url, SNS_HOSTS):
        fail(f"{category} {key} channel/source mismatch for SNS/X")
    if channel == "instagram" and not host_matches(url, INSTAGRAM_HOSTS):
        fail(f"{category} {key} channel/source mismatch for Instagram")
    if channel == "facebook" and not host_matches(url, FACEBOOK_HOSTS):
        fail(f"{category} {key} channel/source mismatch for Facebook")
    if channel == "youtube" and not host_matches(url, YOUTUBE_HOSTS):
        fail(f"{category} {key} channel/source mismatch for YouTube")
    if channel == "web" and (host_matches(url, SOCIAL_HOSTS) or host_matches(url, YOUTUBE_HOSTS)):
        fail(f"{category} {key} channel/source mismatch for Web")


def state_issue_path(issue_date: str) -> Path:
    return STATE_ROOT / issue_date / "issue.json"


def validate_state_issue(issue_date: str) -> dict | None:
    path = state_issue_path(issue_date)
    if not path.exists():
        return None
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "night_signal_state.py"), "--validate-issue", str(path)],
        cwd=ROOT,
        text=True,
        capture_output=True,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        fail(f"state-backed coverage validation failed: {detail}")
    try:
        issue = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"state issue JSON is invalid: {exc}")
    if not isinstance(issue, dict):
        fail("state issue must be a JSON object")
    return issue


def validate_state_backed_coverage(issue_date: str, root_html: str, manifest: dict, contract: dict, issue: dict) -> None:
    expected_version = expected_contract_version(contract, issue_date)
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
    state_cards = issue.get("cards", [])
    if not isinstance(state_cards, list):
        fail("state issue cards must be a list")
    state_titles_by_section: dict[str, list[str]] = {}
    state_candidates = issue.get("candidates", [])
    if not isinstance(state_candidates, list):
        fail("state issue candidates must be a list")
    for card in state_cards:
        if isinstance(card, dict):
            state_titles_by_section.setdefault(str(card.get("section_id")), []).append(str(card.get("title")))
    for category_config in contract["categories"]:
        label = category_config["label"]
        section_id = category_config["section_id"]
        entry = categories[label]
        if not isinstance(entry, dict):
            fail(f"{label} manifest entry must be an object")
        expected_titles = card_titles_by_section(root_html, section_id)
        if entry.get("published_card_titles") != expected_titles:
            fail(f"{label} published_card_titles do not match page cards")
        if state_titles_by_section.get(section_id, []) != expected_titles:
            fail(f"{label} state cards do not match page cards")
        category_candidates = [
            candidate
            for candidate in state_candidates
            if isinstance(candidate, dict) and candidate.get("category") == label
        ]
        required_topic_ids = {
            str(topic["id"])
            for topic in category_config.get("watch_topics", [])
            if isinstance(topic, dict) and isinstance(topic.get("id"), str)
        }
        concrete = [
            candidate
            for candidate in category_candidates
            if isinstance(candidate.get("title"), str)
            and len(candidate["title"].strip()) >= 12
            and isinstance(candidate.get("summary"), str)
            and len(re.sub(r"\s+", "", candidate["summary"])) >= 35
            and not re.search(r"(大きな更新なし|no fresh|no_new_update)", candidate["title"], re.I)
        ]
        concrete_topic_ids = {
            str(candidate.get("watch_topic_id"))
            for candidate in concrete
            if isinstance(candidate.get("watch_topic_id"), str)
        }
        visible_topic_candidates = [
            candidate
            for candidate in concrete
            if candidate.get("decision") != "adopted"
            and isinstance(candidate.get("source_urls"), list)
            and candidate.get("source_urls")
        ]
        if not expected_titles and not visible_topic_candidates:
            fail(f"{label} has no reader-facing article or candidate headline topics")
        for candidate in concrete:
            text = f"{candidate.get('title', '')} {candidate.get('summary', '')}"
            if not has_category_identity(label, text):
                fail(f"{label} candidate appears outside category scope: {candidate.get('title')}")
        topic_checks = entry.get("no_change_checks")
        if not isinstance(topic_checks, list):
            fail(f"{label} state-backed coverage missing no_change_checks")
        checked_topic_ids: set[str] = set()
        checked_urls: set[str] = set()
        for index, check in enumerate(topic_checks, start=1):
            if not isinstance(check, dict):
                fail(f"{label} no_change_checks[{index}] must be an object")
            topic_id = check.get("topic_id")
            result = check.get("result")
            evidence_urls = check.get("evidence_urls")
            if topic_id not in required_topic_ids:
                fail(f"{label} no_change_checks[{index}] uses unknown topic: {topic_id}")
            if not isinstance(result, str) or len(re.sub(r"\s+", "", result)) < 20:
                fail(f"{label} no_change_checks[{index}] result is too weak")
            if not isinstance(evidence_urls, list) or not evidence_urls:
                fail(f"{label} no_change_checks[{index}] needs evidence URLs")
            normalized = {
                normalize_url(url)
                for url in evidence_urls
                if isinstance(url, str) and normalize_url_host(url)
            }
            if not normalized:
                fail(f"{label} no_change_checks[{index}] lacks direct URL evidence")
            checked_topic_ids.add(str(topic_id))
            checked_urls.update(normalized)
        missing_topic_ids = sorted(
            required_topic_ids - concrete_topic_ids - checked_topic_ids
        )
        if missing_topic_ids:
            fail(
                f"{label} state-backed coverage needs a candidate or verified "
                "topic check for every watch topic: " + ", ".join(missing_topic_ids)
            )
        concrete_urls = {
            normalize_url(url)
            for candidate in concrete
            for url in candidate.get("source_urls", [])
            if isinstance(url, str) and normalize_url_host(url)
        }
        if len(concrete_urls | checked_urls) < min(2, len(required_topic_ids)):
            fail(f"{label} state-backed coverage lacks concrete source diversity")


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


def validate_sources(contract: dict, category_config: dict, entry: dict) -> tuple[int, set[str]]:
    category = category_config["label"]
    optional_classes = category_config.get("optional_source_classes", [])
    if not isinstance(optional_classes, list) or any(not isinstance(item, str) for item in optional_classes):
        fail(f"{category} has invalid optional_source_classes")
    total_urls = 0
    hosts: set[str] = set()
    for source_class, rule in contract["source_classes"].items():
        if source_class in optional_classes and not entry.get(source_class):
            continue
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
    synthesis_required = effective_on_or_after(contract, "synthesis_manifest_effective_date", issue_dt)
    claim_verification_required = effective_on_or_after(contract, "claim_verification_effective_date", issue_dt)
    allowed_summary_modes = contract.get("allowed_summary_modes", [])
    minimum_material_facts = int(contract.get("minimum_material_facts_per_published_item", 0))
    allowed_claim_types = set(contract.get("allowed_claim_types", []))
    allowed_evidence_kinds = set(contract.get("allowed_claim_evidence_kinds", []))
    required_source_states = contract.get("claim_type_required_source_states", {})
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
        if not isinstance(summary, str) or not summary.strip():
            fail(f"{category} new_or_changed_items[{index}] summary is required")
        if not has_japanese(summary):
            fail(f"{category} new_or_changed_items[{index}] summary must be Japanese")
        if not synthesis_required and len(re.sub(r"\s+", "", summary)) < min_summary_chars:
            fail(f"{category} new_or_changed_items[{index}] summary is too thin")
        if not isinstance(sources, list) or not sources or any(not isinstance(source, str) for source in sources):
            fail(f"{category} new_or_changed_items[{index}] sources must be a non-empty string list")
        source_urls = [normalize_url(url) for url in urls_in(sources)]
        if not source_urls:
            fail(f"{category} new_or_changed_items[{index}] must include URL sources")
        detail_urls = source_urls_from_detail(issue_date, detail_by_title[title])
        if synthesis_required:
            summary_mode = item.get("summary_mode")
            material_facts = item.get("material_facts")
            if summary_mode not in allowed_summary_modes:
                fail(f"{category} new_or_changed_items[{index}] summary_mode is required for article synthesis")
            if (
                not isinstance(material_facts, list)
                or len(material_facts) < minimum_material_facts
                or any(not isinstance(fact, str) or len(re.sub(r"\s+", "", fact)) < 12 or not has_japanese(fact) for fact in material_facts)
            ):
                fail(f"{category} new_or_changed_items[{index}] needs concrete material_facts")
            if len(set(source_urls)) > 1 and summary_mode != "multi_source_synthesis":
                fail(f"{category} new_or_changed_items[{index}] multiple sources require multi_source_synthesis")
            if summary_mode == "multi_source_synthesis":
                basis = item.get("synthesis_basis")
                if not isinstance(basis, str) or len(re.sub(r"\s+", "", basis)) < 30 or not has_japanese(basis):
                    fail(f"{category} new_or_changed_items[{index}] multi_source_synthesis needs synthesis_basis")
            missing_detail_sources = [url for url in source_urls if url not in detail_urls]
            if missing_detail_sources:
                fail(f"{category} new_or_changed_items[{index}] all synthesis sources must appear on detail page")
        elif not any(url in detail_urls for url in source_urls):
            fail(f"{category} new_or_changed_items[{index}] sources must overlap linked detail page sources")
        if claim_verification_required:
            claims = item.get("claim_verification")
            if not isinstance(claims, list) or not claims:
                fail(f"{category} new_or_changed_items[{index}] missing claim_verification")
            verified_types: set[str] = set()
            for claim_index, claim in enumerate(claims, start=1):
                if not isinstance(claim, dict):
                    fail(f"{category} new_or_changed_items[{index}] claim_verification[{claim_index}] must be an object")
                claim_type = claim.get("claim_type")
                evidence_kind = claim.get("evidence_kind")
                source_state = claim.get("source_state")
                claim_text = claim.get("claim")
                source_url = normalize_url(str(claim.get("source_url", "")))
                if claim_type not in allowed_claim_types:
                    fail(f"{category} new_or_changed_items[{index}] claim_type is invalid: {claim_type}")
                if evidence_kind not in allowed_evidence_kinds:
                    fail(f"{category} new_or_changed_items[{index}] evidence_kind is invalid: {evidence_kind}")
                expected_states = required_source_states.get(claim_type, [])
                if source_state not in expected_states:
                    fail(
                        f"{category} new_or_changed_items[{index}] claim/source state mismatch: "
                        f"{claim_type} cannot use {source_state}"
                    )
                if not isinstance(claim_text, str) or len(re.sub(r"\s+", "", claim_text)) < 12 or not has_japanese(claim_text):
                    fail(f"{category} new_or_changed_items[{index}] claim text is too weak")
                if source_url not in set(source_urls) | detail_urls:
                    fail(f"{category} new_or_changed_items[{index}] claim source must be cited on the item/detail page")
                verified_types.add(claim_type)
            inferred = inferred_claim_types(f"{title} {summary}")
            missing_claims = sorted(inferred - verified_types)
            if missing_claims:
                fail(f"{category} new_or_changed_items[{index}] missing claim verification for: " + ", ".join(missing_claims))
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
    max_age = max_adopted_source_age_days(contract, issue_dt)
    strict_source_age_applies = effective_on_or_after(
        contract, "strict_adopted_candidate_source_age_effective_date", issue_dt
    )
    fresh_reason_applies = effective_on_or_after(
        contract, "fresh_non_adopted_reason_required_effective_date", issue_dt
    )
    screening_applies = effective_on_or_after(
        contract, "publication_screening_effective_date", issue_dt
    )
    topic_value_applies = effective_on_or_after(
        contract, "topic_value_gate_effective_date", issue_dt
    )
    allowed_change_classes = contract.get("allowed_change_classes", [])
    allowed_topic_value_classes = contract.get("allowed_topic_value_classes", [])
    weak_standalone_topic_value_classes = set(contract.get("weak_standalone_topic_value_classes", []))
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
        change_class = candidate.get("change_class")
        if screening_applies:
            assessment = candidate.get("publication_assessment")
            if change_class not in allowed_change_classes:
                fail(f"{category} latest_candidates[{index}] change_class is required for publication screening")
            if not isinstance(assessment, str) or len(re.sub(r"\s+", "", assessment)) < 30 or not has_japanese(assessment):
                fail(f"{category} latest_candidates[{index}] publication_assessment must explain the human judgment")
            if decision == "adopted" and change_class in {"routine_recurring", "duplicate_followup"}:
                materiality = candidate.get("materiality_basis")
                if not isinstance(materiality, str) or len(re.sub(r"\s+", "", materiality)) < 30 or not has_japanese(materiality):
                    fail(f"{category} adopted routine or duplicate candidate needs materiality_basis")
            if topic_value_applies and decision == "adopted":
                value_class = candidate.get("topic_value_class")
                reader_delta = candidate.get("reader_delta")
                materiality = candidate.get("materiality_basis")
                if value_class not in allowed_topic_value_classes:
                    fail(f"{category} adopted candidate missing topic_value_class: {title}")
                if not isinstance(reader_delta, str) or len(re.sub(r"\s+", "", reader_delta)) < 35 or not has_japanese(reader_delta):
                    fail(f"{category} adopted candidate must explain reader_delta: {title}")
                if not isinstance(materiality, str) or len(re.sub(r"\s+", "", materiality)) < 35 or not has_japanese(materiality):
                    fail(f"{category} adopted candidate needs materiality_basis: {title}")
                if value_class in weak_standalone_topic_value_classes and change_class not in {"new_event", "material_update"}:
                    fail(f"{category} schedule-only candidate is too weak without material change: {title}")
                if value_class in weak_standalone_topic_value_classes and not re.search(
                    r"(変更|延期|前倒し|中止|新設|追加|規制|契約|資金|結果|事故|安全|供給|収益|市場|スポンサー|技術|性能|リスク)",
                    f"{reader_delta} {materiality}",
                ):
                    fail(f"{category} schedule-only candidate lacks concrete topic value: {title}")
            if decision in {"held", "no_fresh_item"} and change_class in {"new_event", "material_update"}:
                fail(f"{category} fresh material candidate must be published or explicitly excluded: {title}")
            if decision == "excluded" and change_class in {"new_event", "material_update"}:
                if candidate.get("non_adoption_reason_class") not in {"duplicate_covered", "insufficient_evidence", "insufficient_relevance"}:
                    fail(f"{category} excluded material candidate needs a defensible exclusion reason: {title}")
            if decision != "adopted" and change_class == "routine_recurring":
                if candidate.get("non_adoption_reason_class") not in {"duplicate_covered", "no_material_change"}:
                    fail(f"{category} routine candidate must be screened as duplicate or no material change: {title}")
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


def validate_zero_category_challenge(contract: dict, issue_date: str, root_html: str, category_config: dict, entry: dict) -> None:
    category = category_config["label"]
    expected_titles = card_titles_by_section(root_html, category_config["section_id"])
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    if expected_titles or not effective_on_or_after(contract, "zero_category_challenge_effective_date", issue_dt):
        return

    challenge = entry.get("zero_category_challenge")
    if not isinstance(challenge, dict):
        fail(f"{category} has zero published cards and needs zero_category_challenge")

    checked_at = challenge.get("checked_at_jst")
    if not isinstance(checked_at, str):
        fail(f"{category} zero_category_challenge missing checked_at_jst")
    try:
        checked_dt = datetime.fromisoformat(checked_at)
    except ValueError:
        fail(f"{category} zero_category_challenge checked_at_jst is not ISO-8601: {checked_at}")
    offset = checked_dt.utcoffset()
    if offset is None or offset.total_seconds() != 9 * 60 * 60:
        fail(f"{category} zero_category_challenge checked_at_jst must use JST offset: {checked_at}")
    if checked_dt.strftime("%Y-%m-%d") != issue_date:
        fail(f"{category} zero_category_challenge checked_at_jst date mismatch: {checked_at} != {issue_date}")

    candidates = challenge.get("representative_candidates")
    minimum = int(contract.get("minimum_zero_category_representative_candidates", 3))
    if not isinstance(candidates, list) or len(candidates) < minimum:
        fail(f"{category} zero_category_challenge needs at least {minimum} representative candidates")

    allowed_rejections = contract.get("allowed_zero_category_rejection_classes", [])
    if not isinstance(allowed_rejections, list) or any(not isinstance(item, str) for item in allowed_rejections):
        fail("coverage contract allowed_zero_category_rejection_classes must be a string list")
    allowed_change_classes = contract.get("allowed_change_classes", [])
    max_age = max_adopted_source_age_days(contract, issue_dt)
    generic_patterns = [
        r"直近72時間で追加掲載を要する確定差分なし",
        r"no fresh",
        r"no_new_update",
        r"掲載条件を満たす実質差分なし",
    ]

    recent_count = 0
    for index, candidate in enumerate(candidates, start=1):
        if not isinstance(candidate, dict):
            fail(f"{category} zero_category_challenge representative_candidates[{index}] must be an object")
        title = candidate.get("title")
        source_url = candidate.get("source_url")
        source_date = candidate.get("source_published_date")
        change_class = candidate.get("change_class")
        rejection_class = candidate.get("rejection_class")
        rejection_rationale = candidate.get("rejection_rationale")
        if not isinstance(title, str) or len(title.strip()) < 12 or any(re.search(pattern, title, re.I) for pattern in generic_patterns):
            fail(f"{category} zero_category_challenge representative_candidates[{index}] title must be a concrete near-miss candidate")
        if not isinstance(source_url, str) or not normalize_url_host(source_url):
            fail(f"{category} zero_category_challenge representative_candidates[{index}] source_url must be absolute")
        if is_search_result_url(source_url):
            fail(f"{category} zero_category_challenge representative_candidates[{index}] source_url cannot be a search result URL")
        if change_class not in allowed_change_classes:
            fail(f"{category} zero_category_challenge representative_candidates[{index}] change_class is invalid")
        if change_class in {"new_event", "material_update"}:
            fail(f"{category} zero category contains material candidate that must be adopted or explicitly published: {title}")
        if rejection_class not in allowed_rejections:
            fail(f"{category} zero_category_challenge representative_candidates[{index}] rejection_class is invalid")
        if (
            not isinstance(rejection_rationale, str)
            or len(re.sub(r"\s+", "", rejection_rationale)) < 35
            or not has_japanese(rejection_rationale)
            or any(re.search(pattern, rejection_rationale, re.I) for pattern in generic_patterns)
        ):
            fail(f"{category} zero_category_challenge representative_candidates[{index}] needs a specific Japanese rejection rationale")
        try:
            candidate_dt = datetime.strptime(source_date, "%Y-%m-%d").date()
        except (TypeError, ValueError):
            fail(f"{category} zero_category_challenge representative_candidates[{index}] source_published_date must be YYYY-MM-DD")
        if candidate_dt > issue_dt:
            fail(f"{category} zero_category_challenge representative_candidates[{index}] source_published_date is in the future: {source_date}")
        if (issue_dt - candidate_dt).days <= max_age:
            recent_count += 1

    if recent_count < minimum:
        fail(f"{category} zero_category_challenge needs {minimum} recent representative candidates")


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
        if channel not in {"web", "sns_x", "instagram", "facebook", "youtube"}:
            fail(f"{category} collected_items[{index}] channel is invalid: {channel}")
        validate_channel_source(category, f"collected_items[{index}]", channel, source_url)
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

    required_channels = required_channels_for_category(contract, category_config)

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
    scoped_primary_evidence_required = effective_on_or_after(
        contract, "scoped_primary_evidence_effective_date", issue_dt
    )
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
        primary_evidence_hosts: list[str] = []
        for topic in watch_topics:
            if isinstance(topic, dict) and topic.get("id") == topic_id and isinstance(topic.get("event_classes"), list):
                configured_event_classes = [item for item in topic["event_classes"] if isinstance(item, str)]
                configured_hosts = topic.get("primary_evidence_hosts", [])
                if not isinstance(configured_hosts, list) or any(not isinstance(host, str) for host in configured_hosts):
                    fail(f"{category} watch_topic {topic_id} has invalid primary_evidence_hosts")
                primary_evidence_hosts = configured_hosts
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
            if channel not in {"web", "sns_x", "instagram", "facebook", "youtube"}:
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] channel is invalid: {channel}")
            if not isinstance(evidence_url, str) or not normalize_url_host(evidence_url):
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] evidence_url must be absolute")
            if is_search_result_url(evidence_url):
                fail(f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] evidence_url cannot be a search result URL")
            validate_channel_source(
                category,
                f"watch_topic_checks[{index}].investigation_paths[{path_index}]",
                channel,
                evidence_url,
            )
            if scoped_primary_evidence_required and role == "primary_or_official" and primary_evidence_hosts and not host_matches(
                evidence_url, set(primary_evidence_hosts)
            ):
                fail(
                    f"{category} watch_topic_checks[{index}].investigation_paths[{path_index}] "
                    "primary evidence host outside configured topic scope"
                )
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
                not host_matches(url, SOCIAL_HOSTS) and not host_matches(url, YOUTUBE_HOSTS) for url in evidence_urls
            ):
                fail(f"{category} watch_topic_checks[{index}].web must include Web URL evidence")
            require_required_channel_url(category, f"watch_topic_checks[{index}].{channel}", channel, values)

    missing_topics = [topic_id for topic_id, count in sorted(by_topic.items()) if count < min_per_topic]
    if missing_topics:
        fail(f"{category} watch_topic_checks missing topics: " + ", ".join(missing_topics))


def validate_no_change_checks(contract: dict, category_config: dict, entry: dict) -> None:
    category = category_config["label"]
    required_channels = required_channels_for_category(contract, category_config)
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
        for channel in required_channels:
            require_required_channel_url(category, f"no_change_checks[{index}]", channel, sources)


def validate_coverage_contract(issue_date: str, root_html: str, extraction_log_html: str) -> None:
    contract = load_contract()
    manifest = extract_manifest(extraction_log_html)
    state_issue = validate_state_issue(issue_date)
    if state_issue is not None:
        validate_state_backed_coverage(issue_date, root_html, manifest, contract, state_issue)
        return

    expected_version = expected_contract_version(contract, issue_date)
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
        validate_zero_category_challenge(contract, issue_date, root_html, category_config, entry)
        validate_collected_items(contract, issue_date, category_config, entry)
        validate_watch_topic_checks(contract, issue_date, category_config, entry)
        validate_no_change_checks(contract, category_config, entry)
        validate_search_axes(contract, category_config, entry)
        total_urls, hosts = validate_sources(contract, category_config, entry)
        minimum_url_evidence = int(
            category_config.get("minimum_url_evidence", contract["minimum_url_evidence_per_category"])
        )
        minimum_distinct_hosts = int(
            category_config.get("minimum_distinct_url_hosts", contract["minimum_distinct_url_hosts_per_category"])
        )
        if total_urls < minimum_url_evidence:
            fail(f"{category} has too little URL evidence: {total_urls}")
        if len(hosts) < minimum_distinct_hosts:
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
