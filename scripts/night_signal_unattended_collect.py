#!/usr/bin/env python3
"""Collect a reviewed NIGHT SIGNAL bundle without Codex or OpenAI API keys.

The GitHub Actions fallback fetches every configured seed source, adds a broad
news-discovery sweep per category, and asks GitHub Models to extract only facts
present in that evidence. The resulting reviewed bundle enters the same state,
quality, and publication gates as the primary collector.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

import night_signal_apply_source_review as source_review
import night_signal_models as models
import night_signal_state as state_contract


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"
SOURCE_CONFIG = ROOT / "config" / "night_signal_sources.json"
COVERAGE_CONFIG = ROOT / "config" / "night_signal_coverage.json"
JST = ZoneInfo("Asia/Tokyo")
MODELS_URL = "https://models.github.ai/inference/chat/completions"
DEFAULT_MODEL_TIMEOUT_SECONDS = 90
DEFAULT_MODEL_RETRIES = 3
DEFAULT_MODEL_MAX_TOKENS = 4000
USER_AGENT = (
    "Mozilla/5.0 (compatible; NightSignalBot/1.0; "
    "+https://dq9zt6jpc2-a11y.github.io/night-signal/)"
)
ALLOWED_TOPIC_VALUES = {
    "decision_or_policy",
    "market_or_financial_impact",
    "technical_or_product_shift",
    "operational_status_change",
    "event_result_or_outcome",
    "material_schedule_change",
    "risk_or_safety_signal",
    "cultural_or_audience_signal",
}
ALLOWED_CHANGE_CLASSES = {
    "new_event",
    "material_update",
    "routine_recurring",
    "duplicate_followup",
    "background_only",
}
MATERIAL_SIGNAL_RE = re.compile(
    r"("
    r"\d+(?:\.\d+)?\s*(?:%|％|億|兆|万|ドル|円|bps|bp)|"
    r"bond|bonds|社債|債券|debt|loan|bridge loan|借り換え|資金調達|"
    r"rating|ratings|格付|投資適格|investment grade|Baa|BBB|"
    r"market share|シェア|share falls|50%|50％|"
    r"benchmark|ベンチマーク|model|モデル|cyber|サイバー|security|脆弱性|"
    r"target price|price target|目標株価|buy rating|sell rating|"
    r"IPO|上場|Nasdaq|時価総額|valuation|"
    r"merger|合併|統合|tie-up|acquisition|買収|M&A|"
    r"hire|hiring|joins|leaves|departing|移籍|獲得|退社|人材|"
    r"契約|受注|提携|partnership|contract|"
    r"launch result|打ち上げ結果|docking|ドッキング|"
    r"policy|regulation|規制|安全|recall|リコール"
    r")",
    re.I,
)
LOW_SIGNAL_VALUE_RE = re.compile(
    r"噂|予想|予測|レンダリング|架空|ダイキャスト|ミニカー|プラモデル|"
    r"完成品|1/24|おもちゃ|グッズ|セール|値引き|クーポン",
    re.I,
)
HIGH_THROUGHPUT_CATEGORIES = {"OpenAI", "SpaceX", "SoftBank", "宇都宮ブレックス"}
MAX_CATEGORY_EVIDENCE = 18
MAX_CATEGORY_ITEMS = 3
MAX_CATEGORY_SIGNALS = 8
CATEGORY_IDENTITY_TERMS = {
    "OpenAI": ["OpenAI", "ChatGPT", "Codex", "Azure OpenAI", "生成AI", "AIモデル"],
    "SoftBank": ["SoftBank", "ソフトバンク", "SBG", "Arm"],
    "Honda": ["Honda", "ホンダ", "HRC", "Aston Martin", "Acura"],
    "F1": ["F1", "FIA", "Grand Prix", "グランプリ", "Formula 1", "ホンダ", "Honda", "ADUO", "PU", "レッドブル", "メルセデス", "フェラーリ", "マクラーレン", "Aston Martin"],
    "SpaceX": ["SpaceX", "Starship", "Starlink", "Dragon", "Falcon"],
    "日本経済": ["日本", "日銀", "財務省", "CPI", "GDP", "円", "JGB"],
    "YOASOBI / 幾田りら": ["YOASOBI", "幾田りら", "ikura"],
    "アジア経済": ["アジア", "中国", "インド", "台湾", "韓国", "ASEAN", "ベトナム"],
    "北米経済": ["米", "米国", "アメリカ", "Canada", "Fed", "FRB", "S&P", "Nasdaq"],
    "宇都宮ブレックス": ["宇都宮ブレックス", "BREX", "B.LEAGUE", "Bリーグ"],
}


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL UNATTENDED COLLECT FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        fail(f"missing file: {path}")
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON: {path}: {exc}")
    if not isinstance(value, dict):
        fail(f"expected object: {path}")
    return value


class VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag in {"script", "style", "noscript", "svg"}:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def compact_text(value: str, limit: int = 1600) -> str:
    return " ".join(html.unescape(value).split())[:limit]


def normalized_topic_key(*values: Any) -> str:
    text = " ".join(str(value or "") for value in values)
    text = re.sub(r"\s+執筆(?:\s+[-–—].*)?$", " ", text)
    text = re.sub(r"\s+[-–—]\s+[^。]{1,120}$", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"\b20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}\b", " ", text)
    text = re.sub(r"\b(?:today|yesterday|latest|breaking)\b", " ", text, flags=re.I)
    text = re.sub(r"[^\w一-龥ぁ-んァ-ンー%％$]+", " ", text.lower())
    stopwords = {
        "news",
        "latest",
        "update",
        "updates",
        "発表",
        "速報",
        "ニュース",
        "最新",
        "確認",
        "について",
    }
    tokens = [token for token in text.split() if token and token not in stopwords]
    return " ".join(tokens[:14])


def record_cluster_key(record: dict[str, Any]) -> str:
    return normalized_topic_key(record.get("title"))


def cluster_seen(seen: set[str], key: str) -> bool:
    if not key:
        return False
    return any(
        key == value
        or (len(key) >= 12 and value.startswith(key))
        or (len(value) >= 12 and key.startswith(value))
        for value in seen
    )


def cluster_priority(record: dict[str, Any], category: dict[str, Any]) -> tuple[int, str]:
    title = str(record.get("title", ""))
    excerpt = str(record.get("excerpt", ""))
    text = f"{title} {excerpt}"
    score = 0
    if record.get("source_class") != "discovered_media":
        score += 4
    if MATERIAL_SIGNAL_RE.search(text):
        score += 6
    if any(
        str(term).lower() in text.lower()
        for topic in category.get("watch_topics", [])
        if isinstance(topic, dict)
        for term in topic.get("terms", [])[:8]
    ):
        score += 3
    if record.get("published_date"):
        score += 1
    if str(record.get("publisher_url", "")).startswith(("http://", "https://")):
        score += 1
    return score, compact_text(title or excerpt, 160)


def select_clustered_evidence(
    category: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    observed = [record for record in records if record.get("observed")]
    clustered: dict[str, dict[str, Any]] = {}
    for record in observed:
        key = record_cluster_key(record)
        if not key:
            key = str(record.get("url", ""))
        current = clustered.get(key)
        if current is None or cluster_priority(record, category) > cluster_priority(current, category):
            clustered[key] = record
    records_by_score = sorted(
        clustered.values(),
        key=lambda record: cluster_priority(record, category),
        reverse=True,
    )
    seed = [record for record in records_by_score if record.get("source_class") != "discovered_media"]
    discovered = [record for record in records_by_score if record.get("source_class") == "discovered_media"]
    selected: list[dict[str, Any]] = []
    seen_routes: set[tuple[str, str]] = set()
    for record in seed:
        route = (str(record.get("source_role")), str(record.get("channel")))
        if route in seen_routes and not MATERIAL_SIGNAL_RE.search(
            f"{record.get('title', '')} {record.get('excerpt', '')}"
        ):
            continue
        seen_routes.add(route)
        selected.append(record)
    selected.extend(discovered)
    limit = MAX_CATEGORY_EVIDENCE if category.get("label") in HIGH_THROUGHPUT_CATEGORIES else 12
    return selected[:limit]


PUBLIC_COPY_REPLACEMENTS = [
    (
        r"(?:調査|探索|監視|収集)"
        r"(?:方法|経路|方針|対象|チャネル|チャンネル)",
        "関連情報",
    ),
    (
        r"(?:採用|掲載|公開)(?:判断|基準|可否|候補)",
        "重要性",
    ),
    (
        r"(?:見る|追う|確認する|収集する)必要がある",
        "今後の変化が重要となる",
    ),
]
SUMMARY_LABEL_RE = re.compile(r"(?:変更点|重要性|確認事実|未確定点)\s*[:：]")
GENERIC_IMPORTANCE_RE = re.compile(
    r"重要更新として一覧に残す|変化を広めに把握|関連テーマは|出典日付は"
)
PUBLIC_TERM_REPLACEMENTS = {
    "位置づけ": "意味",
    "競争軸": "競争の焦点",
    "更新局面": "変化",
    "IR文脈": "企業情報",
    "確認して": "確認され",
    "拾う": "捉える",
    "導線": "手段",
    "点検": "確認",
    "一次資料": "公式資料",
    "一次更新": "公式発表",
    "補助線": "背景",
}


def reader_facing_text(value: Any, limit: int = 1600) -> str:
    text = compact_text(str(value), limit)
    text = re.sub(r"<[^>]+>", " ", text)
    for pattern, replacement in PUBLIC_COPY_REPLACEMENTS:
        text = re.sub(pattern, replacement, text)
    for term in state_contract.PUBLIC_COPY_FORBIDDEN_TERMS:
        if term in text:
            text = text.replace(term, PUBLIC_TERM_REPLACEMENTS.get(term, ""))
    return compact_text(text, limit)


def useful_fact(fact: str, category_label: str) -> bool:
    text = reader_facing_text(fact, 500)
    if len(text) < 18:
        return False
    if GENERIC_IMPORTANCE_RE.search(text):
        return False
    if category_label and f"{category_label}の重要更新として確認" in text:
        return False
    return True


def useful_importance(value: str) -> bool:
    text = reader_facing_text(value, 700)
    return bool(text) and not GENERIC_IMPORTANCE_RE.search(text)


def reader_public_copy_ok(text: str, *, kind: str) -> bool:
    return not state_contract.public_copy_violations(text, kind=kind)


def category_identity_ok(category_label: str, title: str, summary: str) -> bool:
    terms = CATEGORY_IDENTITY_TERMS.get(category_label)
    if not terms:
        return True
    text = f"{title} {summary}".lower()
    return any(term.lower() in text for term in terms)


def contains_material_signal(*values: str) -> bool:
    text = " ".join(str(value or "") for value in values)
    return bool(MATERIAL_SIGNAL_RE.search(text))


def low_signal_value(*values: str) -> bool:
    text = " ".join(str(value or "") for value in values)
    return bool(LOW_SIGNAL_VALUE_RE.search(text))


def natural_detail_summary(
    *,
    summary: str,
    detail: str,
    what_changed: str,
    why_it_matters: str,
    facts: list[str],
    limits_or_unknowns: str,
    category_label: str,
) -> str:
    existing = reader_facing_text(detail, 2600)
    if len(existing) >= 280 and not SUMMARY_LABEL_RE.search(existing):
        return existing

    lead = reader_facing_text(what_changed or summary or existing, 700)
    if lead and not lead.endswith("。"):
        lead = f"{lead}。"

    useful_facts = [
        reader_facing_text(fact, 500)
        for fact in facts
        if useful_fact(fact, category_label)
    ][:3]
    fact_sentence = ""
    if useful_facts:
        joined = "、".join(fact.rstrip("。") for fact in useful_facts)
        fact_sentence = f"確認できた点は、{joined}。"

    importance_sentence = ""
    if useful_importance(why_it_matters):
        importance = reader_facing_text(why_it_matters, 700).rstrip("。")
        importance_sentence = f"{importance}。"

    limits_sentence = ""
    limits = reader_facing_text(limits_or_unknowns, 700)
    if limits:
        limits_sentence = limits if limits.endswith("。") else f"{limits}。"

    composed = compact_text(
        " ".join(
            part
            for part in (
                lead,
                fact_sentence,
                importance_sentence,
                limits_sentence,
            )
            if part
        ),
        2600,
    )
    return composed or existing


def page_text(raw: bytes, content_type: str) -> tuple[str, str]:
    charset_match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type)
    charset = charset_match.group(1) if charset_match else "utf-8"
    text = raw.decode(charset, errors="replace")
    if "<html" not in text[:1000].lower() and "<!doctype" not in text[:1000].lower():
        plain = compact_text(text)
        return plain[:180], plain
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>",
        text,
        flags=re.I | re.S,
    )
    title = compact_text(title_match.group(1), 180) if title_match else ""
    parser = VisibleTextParser()
    parser.feed(text)
    return title, compact_text(" ".join(parser.parts))


def request_bytes(url: str, timeout: int = 15) -> tuple[bytes, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml,text/plain,*/*",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(350_000)
        content_type = response.headers.get("Content-Type", "")
        return raw, content_type, response.geturl()


def jina_url(url: str) -> str:
    return "https://r.jina.ai/http://" + re.sub(r"^https?://", "", url)


def source_search_fallback(source: dict[str, Any]) -> dict[str, Any]:
    source_url = str(source["url"])
    parsed = urllib.parse.urlparse(source_url)
    account = f"{parsed.netloc}{parsed.path}".rstrip("/")
    queries = [
        f'site:{account} "{source["label"]}"',
        f'site:{parsed.netloc} "{source["label"]}"',
        f'"{source["label"]}"',
    ]
    excerpt = ""
    resolved_url = ""
    used_query = ""
    for query in queries:
        search_url = "https://www.bing.com/search?" + urllib.parse.urlencode(
            {"format": "rss", "q": query}
        )
        raw, content_type, resolved_url = request_bytes(search_url)
        try:
            root = ET.fromstring(raw)
            results = [
                " / ".join(
                    part
                    for part in (
                        compact_text(item.findtext("title") or "", 180),
                        compact_text(item.findtext("link") or "", 500),
                        compact_text(item.findtext("description") or "", 300),
                    )
                    if part
                )
                for item in root.findall(".//item")[:5]
            ]
            excerpt = compact_text(" ".join(results), 1600)
        except ET.ParseError:
            _, excerpt = page_text(raw, content_type)
        if len(excerpt) >= 80:
            used_query = query
            break
    if len(excerpt) < 80:
        raise ValueError("source-limited search returned too little evidence")
    source_kind = "Xアカウント" if source.get("channel") == "sns_x" else "登録ソース"
    return {
        **source,
        "url": source_url,
        "observed": True,
        "resolved_url": resolved_url,
        "title": f"{source['label']}限定検索",
        "excerpt": excerpt,
        "evidence": (
            f"{source['label']}の直取得とReader取得が利用できなかったため、"
            f"{source_kind}{source_url}に限定したBing RSS検索を確認した。"
            f"検索語: {used_query}。検索結果: {excerpt[:500]}"
        ),
    }


def fetch_source(source: dict[str, Any]) -> dict[str, Any]:
    url = str(source["url"])
    attempts = [url]
    if not url.startswith("https://r.jina.ai/"):
        attempts.append(jina_url(url))
    errors: list[str] = []
    for attempt in attempts:
        try:
            raw, content_type, resolved_url = request_bytes(attempt)
            title, excerpt = page_text(raw, content_type)
            if len(excerpt) < 80:
                errors.append(f"{attempt}: usable text was too short")
                continue
            via = "direct" if attempt == url else "Jina Reader mirror"
            return {
                **source,
                "url": url,
                "observed": True,
                "resolved_url": resolved_url,
                "title": title or str(source["label"]),
                "excerpt": excerpt,
                "evidence": (
                    f"{source['label']}を{via}で取得し、"
                    f"ページ「{title or source['label']}」の本文を確認した。"
                    f"抽出内容: {excerpt[:320]}"
                ),
            }
        except (OSError, TimeoutError, urllib.error.URLError, ValueError) as exc:
            errors.append(f"{attempt}: {type(exc).__name__}: {exc}")
    try:
        return source_search_fallback(source)
    except (
        OSError,
        TimeoutError,
        urllib.error.URLError,
        ValueError,
    ) as exc:
        errors.append(
            f"source-limited search: {type(exc).__name__}: {exc}"
        )
    return {
        **source,
        "url": url,
        "observed": False,
        "error": compact_text(" / ".join(errors), 700),
    }


def parse_rss_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        parsed = email.utils.parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    return parsed.astimezone(JST).date().isoformat()


def news_queries(category: dict[str, Any], issue_date: str) -> list[str]:
    label = str(category["label"])
    configured_terms: list[str] = []
    material_terms = [
        "partnership",
        "security",
        "market share",
        "benchmark",
        "funding",
        "debt",
        "rating",
        "hiring",
        "contract",
        "Japan company",
        "official",
    ]
    for axis in category.get("axes", [])[:3]:
        if isinstance(axis, dict):
            configured_terms.extend(str(term) for term in axis.get("terms", [])[:3])
    for topic in category.get("watch_topics", [])[:6]:
        if not isinstance(topic, dict):
            continue
        configured_terms.extend(str(term) for term in topic.get("terms", [])[:3])
        configured_terms.extend(str(event) for event in topic.get("event_classes", [])[:2])
    scoped = list(dict.fromkeys(configured_terms))
    groups = [
        scoped[:8],
        material_terms[:6],
        material_terms[6:],
    ]
    return [
        f"({label}) ({' OR '.join(group)}) when:3d"
        for group in groups
        if group
    ]


def news_query(category: dict[str, Any], issue_date: str) -> str:
    return news_queries(category, issue_date)[0]


def fetch_news(category: dict[str, Any], issue_date: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for query in news_queries(category, issue_date):
        rss_url = (
            "https://news.google.com/rss/search?"
            + urllib.parse.urlencode(
                {
                    "q": query,
                    "hl": "ja",
                    "gl": "JP",
                    "ceid": "JP:ja",
                }
            )
        )
        try:
            raw, _, _ = request_bytes(rss_url)
            root = ET.fromstring(raw)
        except (OSError, TimeoutError, urllib.error.URLError, ET.ParseError) as exc:
            failures.append(
                {
                    "observed": False,
                    "url": rss_url,
                    "label": "Google News RSS",
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )
            continue
        for item in root.findall(".//item")[:8]:
            title = compact_text(item.findtext("title") or "", 220)
            link = compact_text(item.findtext("link") or "", 1000)
            if not title or not link.startswith(("http://", "https://")) or link in seen_urls:
                continue
            description = compact_text(item.findtext("description") or "", 700)
            source = item.find("source")
            source_label = (
                compact_text(source.text or "", 120)
                if source is not None
                else "Google News"
            )
            publisher_url = (
                compact_text(source.get("url") or "", 1000)
                if source is not None
                else ""
            )
            if not publisher_url.startswith(("http://", "https://")):
                publisher_url = ""
            seen_urls.add(link)
            records.append(
                {
                    "label": source_label,
                    "url": link,
                    "source_role": "independent_media_or_data",
                    "channel": "web",
                    "source_class": "discovered_media",
                    "publisher_url": publisher_url,
                    "observed": True,
                    "published_date": parse_rss_date(item.findtext("pubDate")),
                    "title": title,
                    "excerpt": description or title,
                    "evidence": (
                        f"Google News RSSで「{title}」を確認した。"
                        f"配信元は{source_label}、配信日は"
                        f"{parse_rss_date(item.findtext('pubDate')) or '日付不明'}。"
                    ),
                }
            )
    return records or failures


def category_contracts() -> list[dict[str, Any]]:
    coverage = load_object(COVERAGE_CONFIG)
    return [
        category
        for category in coverage.get("categories", [])
        if isinstance(category, dict)
    ]


def current_fresh_issue(issue_date: str) -> bool:
    path = STATE_ROOT / issue_date / "coverage_manifest.json"
    if not path.exists():
        return False
    try:
        manifest = load_object(path)
        completed = datetime.fromisoformat(
            str(manifest["collection_completed_at_jst"])
        ).astimezone(JST)
    except (KeyError, TypeError, ValueError):
        return False
    now = datetime.now(JST)
    return (
        completed.date().isoformat() == issue_date
        and completed.hour >= 18
        and now - completed <= timedelta(hours=4)
    )


def collection_checked_at(issue_date: str) -> str:
    issue_day = date.fromisoformat(issue_date)
    now = datetime.now(JST)
    if issue_day > now.date():
        fail(f"issue date is in the future: {issue_date}")
    if issue_day < now.date():
        return datetime.combine(
            issue_day,
            datetime.max.time().replace(microsecond=0),
            tzinfo=JST,
        ).isoformat(timespec="seconds")
    return now.isoformat(timespec="seconds")


def model_request(
    token: str,
    messages: list[dict[str, str]],
    *,
    retries_override: Optional[int] = None,
    retry_wait_cap: int = 120,
) -> dict[str, Any]:
    errors: list[str] = []
    attempt_messages = list(messages)
    timeout = int(os.getenv("NIGHT_SIGNAL_MODEL_TIMEOUT_SECONDS", DEFAULT_MODEL_TIMEOUT_SECONDS))
    retries = (
        retries_override
        if retries_override is not None
        else int(os.getenv("NIGHT_SIGNAL_MODEL_RETRIES", DEFAULT_MODEL_RETRIES))
    )
    max_tokens = int(os.getenv("NIGHT_SIGNAL_MODEL_MAX_TOKENS", DEFAULT_MODEL_MAX_TOKENS))
    for attempt in range(retries):
        payload = {
            "model": models.model_for_route("github_unattended"),
            "messages": attempt_messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            MODELS_URL,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
                "X-GitHub-Api-Version": "2022-11-28",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                value = json.loads(response.read().decode("utf-8"))
            choice = value["choices"][0]
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("model content is not a string")
            content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
            try:
                result = json.loads(content)
            except json.JSONDecodeError as exc:
                finish_reason = str(choice.get("finish_reason", "unknown"))
                errors.append(
                    f"attempt {attempt + 1}: invalid JSON; "
                    f"finish_reason={finish_reason}; chars={len(content)}; {exc}"
                )
                if attempt < retries - 1:
                    if finish_reason == "length":
                        attempt_messages = [
                            *messages,
                            {
                                "role": "user",
                                "content": (
                                    "The previous response exceeded the output "
                                    "budget. Return smaller valid JSON: at most "
                                    "1 item and 2 signals, with all supplied "
                                    "dates and URLs preserved exactly."
                                ),
                            },
                        ]
                    time.sleep(5 * (attempt + 1))
                    continue
                break
            if not isinstance(result, dict):
                raise ValueError("model result is not an object")
            return result
        except urllib.error.HTTPError as exc:
            if exc.code != 429:
                fail(f"GitHub Models request failed with HTTP {exc.code}")
            retry_after = exc.headers.get("Retry-After")
            try:
                wait_seconds = max(1, min(retry_wait_cap, int(retry_after or "65")))
            except ValueError:
                wait_seconds = 65
            errors.append(
                f"attempt {attempt + 1}: HTTP {exc.code}; "
                f"retry_after={wait_seconds}"
            )
            if attempt < retries - 1:
                time.sleep(wait_seconds)
        except (
            KeyError,
            IndexError,
            OSError,
            TimeoutError,
            ValueError,
        ) as exc:
            errors.append(f"attempt {attempt + 1}: {type(exc).__name__}: {exc}")
            if attempt < retries - 1:
                time.sleep(5 * (attempt + 1))
    fail("GitHub Models request failed: " + " / ".join(errors))


SYSTEM_PROMPT = """You are the unattended NIGHT SIGNAL evidence extractor.

Return one JSON object with keys items, signals, no_change_summary.
Use only the supplied evidence records and exact URLs. Do not use memory.
The issue window is the issue date and preceding two calendar days.
Return up to 3 items and up to 8 signals when distinct material clusters are
present. Do not force one item per category. Retain other relevant candidates
as signals instead of dropping them. Keep no_change_summary under 300 Japanese
characters.

items are publication-worthy confirmed changes. Retain names, exact dates,
numbers, results, uncertainty, and context. Each item must contain:
watch_topic_id, title, summary, source_published_date, topic_value_class,
priority_class, slug, detail_summary, what_changed, why_it_matters,
confirmed_facts (at least 3), limits_or_unknowns, sources (1-3).
Each source needs label and an exact supplied URL. summary should be clear
Japanese with 100-180 characters; detail_summary 280-420 characters.
what_changed and why_it_matters must each be 80-160 characters.
Use exactly 3 confirmed_facts of 40-120 characters, limits_or_unknowns up to
160 characters, and at most 2 sources.

signals are relevant recent findings that should remain visible but are not
strong enough for an article. Each signal must contain watch_topic_id, title,
summary, source_published_date, source_url, source_label, change_class,
rejection_reason_class, rejection_reason, topic_value_class.
Keep each signal summary at 60-140 Japanese characters and rejection_reason
under 100 characters.

Unknown important changes may use the closest supplied watch_topic_id. Do not
silently drop potentially important recent evidence. Routine background older
than the window belongs only in no_change_summary. If evidence is insufficient,
return empty arrays and explain what was checked. Never invent a date, number,
source, or certainty. Public fields must explain the event itself and must not
mention research, collection, monitoring, selection, or publication procedure.
detail_summary must be one natural Japanese paragraph. Do not use labels such
as 変更点, 重要性, 確認事実, or 未確定点, and do not say that an item is kept in
the list or monitored broadly. Include concrete facts, why the change matters,
and remaining uncertainty without repeating the same sentence."""

def category_prompt(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    selected = select_clustered_evidence(category, records)
    return {
        "issue_date": issue_date,
        "category": category["label"],
        "watch_topics": [
            {
                "id": topic["id"],
                "terms": topic.get("terms", []),
                "event_classes": topic.get("event_classes", []),
            }
            for topic in category.get("watch_topics", [])
            if isinstance(topic, dict)
        ],
        "allowed_topic_value_classes": sorted(ALLOWED_TOPIC_VALUES),
        "allowed_change_classes": sorted(ALLOWED_CHANGE_CLASSES),
        "evidence": [
            {
                "label": record.get("label"),
                "url": record.get("url"),
                "source_role": record.get("source_role"),
                "channel": record.get("channel"),
                "published_date": record.get("published_date"),
                "title": record.get("title"),
                "excerpt": compact_text(str(record.get("excerpt", "")), 240),
                "cluster_key": record_cluster_key(record),
                "material_signal": bool(
                    MATERIAL_SIGNAL_RE.search(
                        f"{record.get('title', '')} {record.get('excerpt', '')}"
                    )
                ),
            }
            for record in selected
        ],
    }


def valid_date(value: Any, issue_date: str) -> bool:
    try:
        parsed = date.fromisoformat(str(value))
        end = date.fromisoformat(issue_date)
    except ValueError:
        return False
    return end - timedelta(days=2) <= parsed <= end


def clean_sources(
    raw_sources: Any,
    records_by_url: dict[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    if not isinstance(raw_sources, list):
        return []
    cleaned: list[dict[str, Any]] = []
    seen: set[str] = set()
    for source in raw_sources:
        if not isinstance(source, dict):
            continue
        url = str(source.get("url", ""))
        record = records_by_url.get(url)
        if not record or not record.get("observed") or url in seen:
            continue
        seen.add(url)
        cleaned.append(
            {
                "label": str(record.get("label") or source.get("label") or url),
                "url": url,
                "source_role": str(
                    record.get("source_role", "independent_media_or_data")
                ),
                "channel": str(record.get("channel", "web")),
                "published_date": record.get("published_date"),
                "evidence_summary": str(record.get("evidence", "")),
            }
        )
        if len(cleaned) == 3:
            break
    return cleaned


def sentence_key(value: str) -> str:
    return re.sub(r"[、。．.!！?？\s「」『』（）()]", "", value).lower()


def sentence_parts(value: str) -> list[str]:
    parts: list[str] = []
    for part in re.split(r"(?<=[。！？!?])", reader_facing_text(value, 2400)):
        text = part.strip()
        if text:
            parts.append(text if text.endswith(("。", "！", "？", "!", "?")) else f"{text}。")
    if not parts and value:
        text = reader_facing_text(value, 700).strip()
        if text:
            parts.append(text if text.endswith("。") else f"{text}。")
    return parts


def unique_sentences(value: str, limit: int = 1200) -> str:
    seen: set[str] = set()
    kept: list[str] = []
    for sentence in sentence_parts(value):
        key = sentence_key(sentence)
        if not key or key in seen:
            continue
        seen.add(key)
        kept.append(sentence)
    return compact_text("".join(kept), limit)


def unique_nonempty(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    kept: list[str] = []
    for value in values:
        text = unique_sentences(value, limit)
        key = sentence_key(text)
        if not text or not key or key in seen:
            continue
        seen.add(key)
        kept.append(text)
    return kept


def promoted_signal_item(
    *,
    topic: str,
    title: str,
    signal: dict[str, Any],
    signal_summary: str,
    topic_value: str,
    issue_date: str,
    record: dict[str, Any],
) -> dict[str, Any]:
    source_date = str(signal["source_published_date"])
    source_label = str(record.get("label") or signal.get("source_label") or record.get("url"))
    source_url = str(record.get("url") or signal.get("source_url"))
    excerpt = reader_facing_text(record.get("excerpt") or record.get("evidence") or "", 900)
    summary = unique_sentences(signal_summary, 900)
    summary_sentences = sentence_parts(summary)
    what_changed = summary_sentences[0] if summary_sentences else summary
    why_it_matters = unique_sentences(
        " ".join(summary_sentences[1:]) or (
            f"{title}は、{category_hint_from_title(title)}に関わる新しい材料として、"
            "投資判断、事業運営、予定確認のいずれかに影響しうる。"
        ),
        700,
    )
    facts = unique_nonempty(
        [
            title,
            what_changed,
            summary,
            f"{source_label}が{source_date}付の情報として配信した。",
            excerpt,
        ],
        500,
    )[:4]
    if len(facts) < 3:
        facts.append(f"{source_date}を出典日として扱う。")
    detail = natural_detail_summary(
        summary=summary,
        detail="",
        what_changed=what_changed,
        why_it_matters=why_it_matters,
        facts=facts,
        limits_or_unknowns="追加の公式発表、条件、数値の内訳は今後の確認対象となる。",
        category_label="",
    )
    return {
        "watch_topic_id": topic,
        "title": title,
        "summary": summary,
        "source_published_date": source_date,
        "topic_value_class": topic_value,
        "priority_class": "priority",
        "slug": (
            "auto-"
            + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
            + f"-{issue_date}"
        ),
        "detail_summary": detail,
        "what_changed": what_changed,
        "why_it_matters": why_it_matters,
        "confirmed_facts": facts[:4],
        "limits_or_unknowns": "追加の公式発表、条件、数値の内訳は今後の確認対象となる。",
        "sources": [
            {
                "label": source_label,
                "url": source_url,
                "source_role": str(record.get("source_role", "independent_media_or_data")),
                "channel": str(record.get("channel", "web")),
            }
        ],
        "observation_source_role": str(record.get("source_role", "independent_media_or_data")),
        "observation_channel": str(record.get("channel", "web")),
    }


def category_hint_from_title(title: str) -> str:
    for category, terms in CATEGORY_IDENTITY_TERMS.items():
        if any(term.lower() in title.lower() for term in terms):
            return category
    return "当該テーマ"


def best_topic_for_record(category: dict[str, Any], record: dict[str, Any]) -> str:
    text = f"{record.get('title', '')} {record.get('excerpt', '')}".lower()
    best_topic = ""
    best_score = -1
    for topic in category.get("watch_topics", []):
        if not isinstance(topic, dict):
            continue
        score = sum(
            1
            for term in topic.get("terms", [])
            if isinstance(term, str) and term.lower() in text
        )
        if score > best_score:
            best_score = score
            best_topic = str(topic.get("id", ""))
    return best_topic


def topic_value_from_record(record: dict[str, Any]) -> str:
    text = f"{record.get('title', '')} {record.get('excerpt', '')}".lower()
    if re.search(r"security|cyber|サイバー|安全|脆弱性|regulation|規制", text):
        return "risk_or_safety_signal"
    if re.search(r"社債|debt|rating|格付|market share|シェア|株価|price target|funding|資金調達", text):
        return "market_or_financial_impact"
    if re.search(r"model|モデル|api|release|launch|製品|技術|benchmark|ベンチマーク", text):
        return "technical_or_product_shift"
    if re.search(r"契約|提携|partnership|contract|採用|移籍|退団|hiring|joins|leaves", text):
        return "decision_or_policy"
    if re.search(r"result|結果|score|勝|敗|打ち上げ|docking|ドッキング", text):
        return "event_result_or_outcome"
    return "operational_status_change"


def fallback_item_from_record(
    category: dict[str, Any],
    issue_date: str,
    record: dict[str, Any],
) -> dict[str, Any] | None:
    source_date = str(record.get("published_date") or "")
    title = reader_facing_text(record.get("title", ""), 180)
    excerpt = reader_facing_text(record.get("excerpt") or record.get("evidence") or "", 1200)
    category_label = str(category.get("label", ""))
    topic = best_topic_for_record(category, record)
    if (
        not topic
        or not title
        or not excerpt
        or not valid_date(source_date, issue_date)
        or not reader_public_copy_ok(title, kind="title")
        or not category_identity_ok(category_label, title, excerpt)
        or not contains_material_signal(title, excerpt)
        or low_signal_value(title, excerpt)
    ):
        return None
    summary = unique_sentences(f"{title}。{excerpt}", 1000)
    if len(summary) < 80:
        return None
    what_changed = sentence_parts(summary)[0] if sentence_parts(summary) else summary
    why_it_matters = unique_sentences(
        f"{title}は、{category_label}の直近3日内の具体的な変化として、"
        "事業、競争環境、予定、または市場評価に影響しうる材料になる。",
        700,
    )
    facts = unique_nonempty(
        [
            title,
            excerpt,
            f"{record.get('label') or '確認元'}が{source_date}付の情報として配信した。",
        ],
        500,
    )
    if len(facts) < 3:
        return None
    limits = "詳細条件、正式な続報、数値の内訳は追加確認の対象となる。"
    detail = natural_detail_summary(
        summary=summary,
        detail="",
        what_changed=what_changed,
        why_it_matters=why_it_matters,
        facts=facts,
        limits_or_unknowns=limits,
        category_label=category_label,
    )
    return {
        "watch_topic_id": topic,
        "title": title,
        "summary": summary,
        "source_published_date": source_date,
        "topic_value_class": topic_value_from_record(record),
        "priority_class": "priority",
        "slug": (
            "auto-"
            + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
            + f"-{issue_date}"
        ),
        "detail_summary": detail,
        "what_changed": what_changed,
        "why_it_matters": why_it_matters,
        "confirmed_facts": facts[:4],
        "limits_or_unknowns": limits,
        "sources": [
            {
                "label": str(record.get("label") or record.get("url")),
                "url": str(record.get("url")),
                "source_role": str(record.get("source_role", "independent_media_or_data")),
                "channel": str(record.get("channel", "web")),
            }
        ],
        "observation_source_role": str(record.get("source_role", "independent_media_or_data")),
        "observation_channel": str(record.get("channel", "web")),
    }


def backfill_items_from_evidence(
    normalized: dict[str, Any],
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> None:
    target = 3 if category.get("label") in HIGH_THROUGHPUT_CATEGORIES else 1
    seen = {
        normalized_topic_key(item.get("title"))
        for item in normalized.get("items", [])
        if isinstance(item, dict)
    }
    for record in select_clustered_evidence(category, records):
        if len(normalized["items"]) >= min(MAX_CATEGORY_ITEMS, target):
            break
        item = fallback_item_from_record(category, issue_date, record)
        if not item:
            continue
        key = normalized_topic_key(item.get("title"))
        if cluster_seen(seen, key):
            continue
        seen.add(key)
        normalized["items"].append(item)


def fallback_signal_from_record(
    category: dict[str, Any],
    issue_date: str,
    record: dict[str, Any],
) -> dict[str, Any] | None:
    source_date = str(record.get("published_date") or "")
    title = reader_facing_text(record.get("title", ""), 180)
    excerpt = reader_facing_text(record.get("excerpt") or record.get("evidence") or "", 1200)
    category_label = str(category.get("label", ""))
    topic = best_topic_for_record(category, record)
    if (
        not topic
        or not title
        or not excerpt
        or not valid_date(source_date, issue_date)
        or not reader_public_copy_ok(title, kind="title")
        or not reader_public_copy_ok(excerpt, kind="summary")
        or not category_identity_ok(category_label, title, excerpt)
        or low_signal_value(title, excerpt)
    ):
        return None
    material = contains_material_signal(title, excerpt)
    return {
        "watch_topic_id": topic,
        "title": title,
        "summary": unique_sentences(f"{title}。{excerpt}", 1200),
        "source_published_date": source_date,
        "source_url": str(record.get("url")),
        "source_label": str(record.get("label") or record.get("url")),
        "change_class": "material_update" if material else "background_only",
        "rejection_reason_class": "duplicate_covered" if material else "no_material_change",
        "rejection_reason": (
            "確定情報は確認できたが、同カテゴリ内の上位カードまたは候補群と重なるため候補として保持する。"
            if material
            else "関連情報として確認したが、記事化に必要な具体的な変化は限定的なため候補として保持する。"
        ),
        "topic_value_class": topic_value_from_record(record),
        "observation_source_role": str(record.get("source_role", "independent_media_or_data")),
        "observation_channel": str(record.get("channel", "web")),
    }


def backfill_signals_from_evidence(
    normalized: dict[str, Any],
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> None:
    target = MAX_CATEGORY_SIGNALS if category.get("label") in HIGH_THROUGHPUT_CATEGORIES else 4
    seen = {
        normalized_topic_key(entry.get("title"))
        for collection in (normalized.get("items", []), normalized.get("signals", []))
        for entry in collection
        if isinstance(entry, dict)
    }
    for record in select_clustered_evidence(category, records):
        if len(normalized["signals"]) >= target:
            break
        signal = fallback_signal_from_record(category, issue_date, record)
        if not signal:
            continue
        key = normalized_topic_key(signal.get("title"))
        if cluster_seen(seen, key):
            continue
        seen.add(key)
        normalized["signals"].append(signal)


def normalize_result(
    raw: dict[str, Any],
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    valid_topics = {
        str(topic["id"])
        for topic in category.get("watch_topics", [])
        if isinstance(topic, dict)
    }
    topic_terms = {
        str(topic["id"]): " / ".join(str(term) for term in topic.get("terms", [])[:2])
        for topic in category.get("watch_topics", [])
        if isinstance(topic, dict)
    }
    records_by_url = {
        str(record["url"]): record
        for record in records
        if record.get("observed")
    }
    items: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_clusters: set[str] = set()
    for item in raw.get("items", []):
        if not isinstance(item, dict):
            continue
        topic = str(item.get("watch_topic_id", ""))
        title = reader_facing_text(item.get("title", ""), 180)
        summary = reader_facing_text(item.get("summary", ""), 1000)
        detail = reader_facing_text(item.get("detail_summary", ""), 2600)
        what_changed = reader_facing_text(item.get("what_changed", ""), 700)
        why_it_matters = reader_facing_text(
            item.get("why_it_matters", ""),
            700,
        )
        facts = [
            reader_facing_text(fact, 500)
            for fact in item.get("confirmed_facts", [])
            if isinstance(fact, str) and fact.strip()
        ]
        limits_or_unknowns = reader_facing_text(
            item.get("limits_or_unknowns", ""),
            900,
        )
        if len(summary) < 100:
            summary = compact_text(
                "。".join(
                    value
                    for value in (summary, what_changed, why_it_matters)
                    if value
                ),
                1000,
            )
        summary = unique_sentences(summary, 1000)
        what_changed = unique_sentences(what_changed, 700)
        why_it_matters = unique_sentences(why_it_matters, 700)
        facts = unique_nonempty(facts, 500)
        if len(detail) < 280 or SUMMARY_LABEL_RE.search(detail):
            detail = natural_detail_summary(
                summary=summary,
                detail=detail,
                what_changed=what_changed,
                why_it_matters=why_it_matters,
                facts=facts,
                limits_or_unknowns=limits_or_unknowns,
                category_label=str(category.get("label", "")),
            )
        detail = unique_sentences(detail, 2600)
        sources = clean_sources(item.get("sources"), records_by_url)
        first_record = records_by_url.get(sources[0]["url"], {}) if sources else {}
        if sources and len(summary) < 80:
            summary = unique_sentences(
                " ".join(
                    value
                    for value in (
                        summary,
                        what_changed,
                        why_it_matters,
                        str(first_record.get("excerpt") or first_record.get("evidence") or ""),
                    )
                    if value
                ),
                1000,
            )
        if sources and len(facts) < 3:
            facts = unique_nonempty(
                [
                    *facts,
                    title,
                    summary,
                    f"{sources[0]['label']}が{item.get('source_published_date')}付の情報として配信した。",
                ],
                500,
            )
        if len(detail) < 280 or SUMMARY_LABEL_RE.search(detail):
            detail = natural_detail_summary(
                summary=summary,
                detail=detail,
                what_changed=what_changed,
                why_it_matters=why_it_matters,
                facts=facts,
                limits_or_unknowns=limits_or_unknowns,
                category_label=str(category.get("label", "")),
            )
            detail = unique_sentences(detail, 2600)
        source_cluster = record_cluster_key(records_by_url.get(sources[0]["url"], {})) if sources else ""
        item_cluster = normalized_topic_key(title, source_cluster)
        topic_value = str(item.get("topic_value_class", ""))
        if (
            topic not in valid_topics
            or not title
            or not reader_public_copy_ok(title, kind="title")
            or not reader_public_copy_ok(summary, kind="summary")
            or not reader_public_copy_ok(detail, kind="summary")
            or not reader_public_copy_ok(what_changed, kind="summary")
            or not reader_public_copy_ok(why_it_matters, kind="summary")
            or not category_identity_ok(str(category.get("label", "")), title, summary)
            or title in seen_titles
            or len(summary) < 80
            or len(detail) < 220
            or len(facts) < 3
            or not sources
            or cluster_seen(seen_clusters, item_cluster)
            or topic_value not in ALLOWED_TOPIC_VALUES
            or not valid_date(item.get("source_published_date"), issue_date)
        ):
            continue
        seen_titles.add(title)
        seen_clusters.add(item_cluster)
        first_source = sources[0]
        items.append(
            {
                "watch_topic_id": topic,
                "title": title,
                "summary": summary,
                "source_published_date": str(item["source_published_date"]),
                "topic_value_class": topic_value,
                "priority_class": (
                    str(item.get("priority_class"))
                    if item.get("priority_class") in {"top", "priority", "standard"}
                    else "standard"
                ),
                "slug": (
                    "auto-"
                    + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
                    + f"-{issue_date}"
                ),
                "detail_summary": detail,
                "what_changed": what_changed,
                "why_it_matters": why_it_matters,
                "confirmed_facts": facts[:8],
                "limits_or_unknowns": limits_or_unknowns,
                "sources": sources,
                "observation_source_role": first_source["source_role"],
                "observation_channel": first_source["channel"],
            }
        )
    signals: list[dict[str, Any]] = []
    for signal in raw.get("signals", []):
        if not isinstance(signal, dict):
            continue
        topic = str(signal.get("watch_topic_id", ""))
        title = reader_facing_text(signal.get("title", ""), 180)
        url = str(signal.get("source_url", ""))
        record = records_by_url.get(url)
        signal_cluster = normalized_topic_key(title, record_cluster_key(record or {}))
        if (
            topic not in valid_topics
            or not title
            or not reader_public_copy_ok(title, kind="title")
            or title in seen_titles
            or cluster_seen(seen_clusters, signal_cluster)
            or not record
            or not valid_date(signal.get("source_published_date"), issue_date)
        ):
            continue
        change_class = str(signal.get("change_class", "background_only"))
        topic_value = str(
            signal.get("topic_value_class", "operational_status_change")
        )
        if change_class not in ALLOWED_CHANGE_CLASSES:
            change_class = "background_only"
        if topic_value not in ALLOWED_TOPIC_VALUES:
            topic_value = "operational_status_change"
        signal_summary = reader_facing_text(
            signal.get("summary", ""),
            1200,
        )
        if not signal_summary:
            signal_summary = reader_facing_text(
                record.get("excerpt") or record.get("evidence") or title,
                1200,
            )
        elif len(signal_summary) < 100:
            signal_summary = unique_sentences(
                f"{signal_summary} {record.get('excerpt') or record.get('evidence') or ''}",
                1200,
            )
        if not reader_public_copy_ok(signal_summary, kind="summary"):
            continue
        if not category_identity_ok(str(category.get("label", "")), title, signal_summary):
            continue
        material_signal = contains_material_signal(title, signal_summary, str(record.get("excerpt", "")))
        if material_signal and change_class in {"background_only", "duplicate_followup"}:
            change_class = "material_update"
        if material_signal and topic_value == "operational_status_change":
            topic_value = "market_or_financial_impact"
        rejection_class = (
            str(signal.get("rejection_reason_class"))
            if signal.get("rejection_reason_class")
            in {
                "duplicate_covered",
                "lower_importance",
                "no_material_change",
                "insufficient_evidence",
                "insufficient_relevance",
            }
            else "insufficient_evidence"
        )
        if material_signal and rejection_class in {"no_material_change", "lower_importance"}:
            rejection_class = "duplicate_covered"
        if material_signal and len(signal_summary) >= 80 and url:
            seen_titles.add(title)
            seen_clusters.add(signal_cluster)
            items.append(
                promoted_signal_item(
                    topic=topic,
                    title=title,
                    signal=signal,
                    signal_summary=signal_summary,
                    topic_value=topic_value,
                    issue_date=issue_date,
                    record=record,
                )
            )
            continue
        rejection_reason = reader_facing_text(
            signal.get("rejection_reason", ""),
            600,
        )
        if not rejection_reason:
            rejection_reason = "記事化に必要な確定情報が不足している。"
        seen_titles.add(title)
        seen_clusters.add(signal_cluster)
        signals.append(
            {
                "watch_topic_id": topic,
                "title": title,
                "summary": signal_summary,
                "source_published_date": str(signal["source_published_date"]),
                "source_url": url,
                "source_label": str(record.get("label", url)),
                "change_class": change_class,
                "rejection_reason_class": rejection_class,
                "rejection_reason": rejection_reason,
                "topic_value_class": topic_value,
                "observation_source_role": str(
                    record.get("source_role", "independent_media_or_data")
                ),
                "observation_channel": str(record.get("channel", "web")),
            }
        )
    items = items[:MAX_CATEGORY_ITEMS]
    signals = signals[:MAX_CATEGORY_SIGNALS]
    no_change = compact_text(str(raw.get("no_change_summary", "")), 1500)
    if len(no_change) < 20:
        observed_count = sum(bool(record.get("observed")) for record in records)
        no_change = (
            f"{issue_date}に{category['label']}の公式、独立媒体、SNS、"
            f"YouTubeを含む{observed_count}件の証跡を確認した。"
            "直近3日の確定差分は掲載記事または候補台帳に記録した。"
        )
    return {
        "items": items,
        "signals": signals,
        "no_change_summary": no_change,
    }


def collect(issue_date: str, token: str) -> dict[str, Any]:
    sources = load_object(SOURCE_CONFIG).get("categories")
    if not isinstance(sources, dict):
        fail("source config categories must be an object")
    contracts = category_contracts()
    flat_sources = [
        {**source, "category": category}
        for category, category_sources in sources.items()
        for source in category_sources
        if isinstance(source, dict)
    ]
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
        fetched = list(executor.map(fetch_source, flat_sources))
        news_lists = list(
            executor.map(
                lambda category: fetch_news(category, issue_date),
                contracts,
            )
        )
    fetched_by_category: dict[str, list[dict[str, Any]]] = {
        str(category["label"]): []
        for category in contracts
    }
    for record in fetched:
        fetched_by_category[str(record["category"])].append(record)
    checked_at = collection_checked_at(issue_date)
    unavailable: dict[str, str] = {}
    evidence: dict[str, str] = {}
    reviewed_categories: dict[str, dict[str, Any]] = {}
    records_by_category: dict[str, list[dict[str, Any]]] = {}
    for category, news_records in zip(contracts, news_lists):
        label = str(category["label"])
        seed_records = fetched_by_category[label]
        for record in seed_records:
            if record.get("observed"):
                evidence[str(record["url"])] = str(record["evidence"])
            else:
                unavailable[str(record["url"])] = (
                    f"{checked_at}に直接取得とJina Reader経由取得を試したが、"
                    f"本文を確認できなかった。理由: {record.get('error', '不明')}"
                )
        for record in news_records:
            if record.get("observed"):
                evidence[str(record["url"])] = str(record["evidence"])
        records_by_category[label] = seed_records + [
            record
            for record in news_records
            if record.get("observed")
        ]
    def review_category(category: dict[str, Any]) -> tuple[str, dict[str, Any], dict[str, Any]]:
        label = str(category["label"])
        print(
            json.dumps(
                {
                    "phase": "category_review_start",
                    "category": label,
                    "records": len(records_by_category[label]),
                },
                ensure_ascii=False,
            ),
            flush=True,
        )
        try:
            raw = model_request(
                token,
                [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": json.dumps(
                            category_prompt(
                                category,
                                issue_date,
                                records_by_category[label],
                            ),
                            ensure_ascii=False,
                        ),
                    },
                ],
                retry_wait_cap=90,
            )
        except SystemExit as exc:
            print(
                json.dumps(
                    {
                        "phase": "category_model_fallback",
                        "category": label,
                        "error": str(exc),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            raw = {
                "items": [],
                "signals": [],
                "no_change_summary": (
                    f"{label}はモデル抽出が一時失敗したため、"
                    "取得済み証拠から重要クラスタを補完した。"
                ),
                "model_error": str(exc),
            }
        normalized = normalize_result(
            raw,
            category,
            issue_date,
            records_by_category[label],
        )
        backfill_items_from_evidence(
            normalized,
            category,
            issue_date,
            records_by_category[label],
        )
        backfill_signals_from_evidence(
            normalized,
            category,
            issue_date,
            records_by_category[label],
        )
        normalized["discovery_sources"] = [
            {
                "label": str(record.get("label") or "Google News"),
                "url": str(record["url"]),
                "source_role": "independent_media_or_data",
                "channel": "web",
                "published_date": record.get("published_date"),
                "evidence_summary": str(record.get("evidence", "")),
            }
            for record in records_by_category[label]
            if record.get("observed")
            and record.get("source_class") == "discovered_media"
        ]
        normalized["discovery_sources"].extend(
            {
                "label": f"{record.get('label') or '配信元'} 媒体ページ",
                "url": str(record["publisher_url"]),
                "source_role": "independent_media_or_data",
                "channel": "web",
                "published_date": record.get("published_date"),
                "evidence_summary": (
                    f"Google News RSSのsource属性から、"
                    f"{record.get('label') or '配信元'}の媒体URL"
                    f"{record['publisher_url']}を確認した。"
                ),
            }
            for record in records_by_category[label]
            if record.get("observed")
            and record.get("source_class") == "discovered_media"
            and record.get("publisher_url")
        )
        raw_items = [
            {
                "title": item.get("title"),
                "watch_topic_id": item.get("watch_topic_id"),
                "source_published_date": item.get("source_published_date"),
                "topic_value_class": item.get("topic_value_class"),
                "summary_length": len(str(item.get("summary", ""))),
                "detail_length": len(str(item.get("detail_summary", ""))),
                "fact_count": len(item.get("confirmed_facts", []))
                if isinstance(item.get("confirmed_facts"), list)
                else 0,
                "source_urls": [
                    source.get("url")
                    for source in item.get("sources", [])
                    if isinstance(source, dict)
                ],
            }
            for item in raw.get("items", [])
            if isinstance(item, dict)
        ]
        report = {
            "phase": "category_review_complete",
            "category": label,
            "raw_items": raw_items,
            "raw_signals": len(raw.get("signals", []))
            if isinstance(raw.get("signals"), list)
            else 0,
            "model_fallback": bool(raw.get("model_error")),
            "normalized_items": len(normalized["items"]),
            "normalized_signals": len(normalized["signals"]),
        }
        return label, normalized, report

    model_workers = max(1, int(os.getenv("NIGHT_SIGNAL_MODEL_CONCURRENCY", "1")))
    print(
        json.dumps(
            {
                "phase": "category_review_pool",
                "categories": len(contracts),
                "model_workers": model_workers,
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    with concurrent.futures.ThreadPoolExecutor(max_workers=model_workers) as executor:
        futures = {
            executor.submit(review_category, category): str(category["label"])
            for category in contracts
        }
        for future in concurrent.futures.as_completed(futures):
            label, normalized, report = future.result()
            reviewed_categories[label] = normalized
            print(json.dumps(report, ensure_ascii=False), flush=True)
    total_items = sum(
        len(entry["items"])
        for entry in reviewed_categories.values()
    )
    if total_items == 0:
        fail("GitHub Models produced no evidence-backed publication item")
    state_dir = STATE_ROOT / issue_date
    state_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = state_dir / "research_bundle.json"
    review_path = state_dir / "source_review.json"
    bundle_path.write_text(
        json.dumps(
            {
                "issue_date": issue_date,
                "checked_at_jst": checked_at,
                "collection_mode": "github_models_unattended",
                "categories": {},
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    review_path.write_text(
        json.dumps(
            {
                "issue_date": issue_date,
                "checked_at_jst": checked_at,
                "unavailable_urls": unavailable,
                "evidence_by_url": evidence,
                "categories": reviewed_categories,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    applied = source_review.apply_review(
        issue_date,
        bundle_path,
        review_path,
    )
    return {
        **applied,
        "collection_mode": "github_models_unattended",
        "unavailable_sources": len(unavailable),
    }


def canary(token: str) -> None:
    try:
        result = model_request(
            token,
            [
                {
                    "role": "user",
                    "content": 'Return exactly this JSON object: {"ok":true}',
                }
            ],
            retries_override=1,
            retry_wait_cap=5,
        )
    except SystemExit as exc:
        print(
            "NIGHT SIGNAL GITHUB MODELS CANARY DEGRADED: "
            f"{exc}. Collection will continue with evidence-backed fallback."
        )
        return
    if result.get("ok") is not True:
        fail(f"GitHub Models canary returned unexpected data: {result}")
    print("NIGHT SIGNAL GITHUB MODELS CANARY PASSED")


def self_test() -> None:
    category = {
        "label": "Test",
        "watch_topics": [
            {"id": "topic", "terms": [], "event_classes": []},
            {"id": "quiet_topic", "terms": [], "event_classes": []},
        ],
    }
    records = [
        {
            "label": "Official",
            "url": "https://example.com/item",
            "source_role": "primary_or_official",
            "channel": "web",
            "observed": True,
            "published_date": "2099-01-02",
            "evidence": "verified",
        }
    ]
    raw = {
        "items": [
            {
                "watch_topic_id": "topic",
                "title": "Concrete update",
                "summary": "A short model summary.",
                "source_published_date": "2099-01-02",
                "topic_value_class": "decision_or_policy",
                "priority_class": "priority",
                "detail_summary": "A short model detail.",
                "what_changed": "The confirmed operating condition changed.",
                "why_it_matters": (
                    "The change affects a monitored decision and its timing."
                ),
                "confirmed_facts": [
                    "The official source published the update.",
                    "The update falls inside the issue window.",
                    "The named subject and result are explicit.",
                ],
                "limits_or_unknowns": (
                    "Later effects remain unconfirmed and are stated separately."
                ),
                "sources": [{"url": "https://example.com/item"}],
            }
        ],
        "signals": [],
        "no_change_summary": "All configured source roles were checked.",
    }
    normalized = normalize_result(raw, category, "2099-01-03", records)
    if len(normalized["items"]) != 1:
        fail("normalization self-test lost a valid item")
    detail_summary = normalized["items"][0]["detail_summary"]
    if SUMMARY_LABEL_RE.search(detail_summary) or GENERIC_IMPORTANCE_RE.search(detail_summary):
        fail("normalization created label-heavy or internal detail copy")
    raw["items"][0]["sources"] = [{"url": "https://unverified.example/"}]
    if normalize_result(raw, category, "2099-01-03", records)["items"]:
        fail("normalization accepted an unverified source")
    signal_raw = {
        "items": [],
        "signals": [
            {
                "watch_topic_id": "topic",
                "title": "Retained candidate",
                "summary": "",
                "source_published_date": "2099-01-02",
                "source_url": "https://example.com/item",
                "change_class": "",
                "rejection_reason_class": "",
                "rejection_reason": "",
                "topic_value_class": "",
            }
        ],
        "no_change_summary": "All configured source roles were checked.",
    }
    normalized_signal = normalize_result(
        signal_raw,
        category,
        "2099-01-03",
        records,
    )["signals"]
    if (
        len(normalized_signal) != 1
        or not normalized_signal[0]["summary"]
        or not normalized_signal[0]["rejection_reason"]
    ):
        fail("normalization lost a concise retained signal")
    material_signal_raw = {
        "items": [],
        "signals": [
            {
                "watch_topic_id": "topic",
                "title": "SpaceXが200億ドル規模の社債を検討",
                "summary": (
                    "SpaceXが200億ドル規模の社債発行を検討していると報じられた。"
                    "格付や資金使途、テスラとの関係を含む資本政策の見方に影響する。"
                    "大型資金調達は宇宙事業の投資余力と市場評価を読む材料になる。"
                    "Starship、Starlink、打ち上げインフラへの資本配分もあわせて注目される。"
                ),
                "source_published_date": "2099-01-02",
                "source_url": "https://example.com/item",
                "change_class": "background_only",
                "rejection_reason_class": "",
                "rejection_reason": "",
                "topic_value_class": "operational_status_change",
            }
        ],
        "no_change_summary": "All configured source roles were checked.",
    }
    promoted_items = normalize_result(
        material_signal_raw,
        category,
        "2099-01-03",
        [
            {
                **records[0],
                "label": "Financial Times",
                "excerpt": (
                    "SpaceXが200億ドル規模の社債発行を検討し、"
                    "格付、資金調達条件、テスラとの関係が市場で注目されている。"
                ),
            }
        ],
    )["items"]
    if len(promoted_items) != 1:
        fail("material signal was not promoted into a publication item")
    promoted = promoted_items[0]
    copied_fields = {
        promoted["summary"],
        promoted["detail_summary"],
        promoted["what_changed"],
        promoted["why_it_matters"],
    }
    if len(copied_fields) < 3:
        fail("material signal promotion copied one sentence into public fields")
    if len(set(promoted["confirmed_facts"])) < 3:
        fail("material signal promotion did not create distinct facts")
    quiet_result = normalize_result(
        {"items": [], "signals": [], "no_change_summary": "All configured source roles were checked."},
        category,
        "2099-01-03",
        records,
    )
    if quiet_result["signals"]:
        fail("normalization turned no-change coverage into candidate signals")
    if reader_facing_text("収集方針を説明する。") != "関連情報を説明する。":
        fail("public-copy normalization kept research procedure wording")
    if state_contract.public_copy_violations(
        reader_facing_text("この発表の位置づけと競争軸を確認して説明する。"),
        kind="summary",
    ):
        fail("public-copy normalization kept a forbidden reader-facing term")
    fallback_name = source_search_fallback.__name__
    if fallback_name != "source_search_fallback":
        fail("source-search fallback is unavailable")
    past_checked_at = collection_checked_at("2000-01-01")
    if not past_checked_at.startswith("2000-01-01T23:59:59+09:00"):
        fail("past-date recovery timestamp escaped the requested issue date")
    print("NIGHT SIGNAL UNATTENDED COLLECT SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "issue_date",
        nargs="?",
        default=datetime.now(JST).date().isoformat(),
    )
    parser.add_argument("--skip-if-fresh", action="store_true")
    parser.add_argument("--canary", action="store_true")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    token = os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN")
    if not token:
        fail("GITHUB_TOKEN or GH_TOKEN is required")
    if args.canary:
        canary(token)
        return 0
    if args.skip_if_fresh and current_fresh_issue(args.issue_date):
        print(f"NIGHT SIGNAL UNATTENDED COLLECT SKIPPED: fresh issue {args.issue_date}")
        return 0
    print(json.dumps(collect(args.issue_date, token), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
