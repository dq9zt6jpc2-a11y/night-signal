#!/usr/bin/env python3
"""Shared source and editorial primitives for the NIGHT SIGNAL pipeline."""

from __future__ import annotations

import concurrent.futures
import email.utils
import hashlib
import html
import json
import os
import re
import sys
import threading
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import night_signal_evidence as evidence_contract
import night_signal_state as state_contract


ROOT = Path(__file__).resolve().parents[1]
STATE_ROOT = ROOT / "state"
SOURCE_CONFIG = ROOT / "config" / "night_signal_sources.json"
COVERAGE_CONFIG = ROOT / "config" / "night_signal_coverage.json"
JST = ZoneInfo("Asia/Tokyo")
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
    r"契約|受注|提携|合意|協議|共同開発|標準化|partnership|contract|"
    r"発売|リリース|提供開始|開始|公開|開催|参入|撤退|建設|計画|plans?|"
    r"生産|量産|出資|損失|再任|loss|reappoint|"
    r"視察団|訪中|訪米|経済界|"
    r"アップグレード|資金流入|景気|物価|賃金|雇用|輸出|輸入|GDP|金利|"
    r"launch result|打ち上げ結果|docking|ドッキング|"
    r"policy|regulation|規制|安全|recall|リコール"
    r")",
    re.I,
)
LOW_SIGNAL_VALUE_RE = re.compile(
    r"噂|予想|予測|レンダリング|架空|ダイキャスト|ミニカー|プラモデル|"
    r"完成品|1/24|おもちゃ|グッズ|セール|値引き|クーポン|"
    r"Derivatives|価格・チャート・時価総額|体験授業|特別展示|夏休み",
    re.I,
)
PUBLICATION_EVENT_RE = re.compile(
    r"(発表|公表|決定|合意|契約|提携|買収|統合|開始|提供開始|発売|公開|更新|"
    r"就任|退任|移籍|獲得|退団|採用|建設|着工|延期|中止|承認|規制|"
    r"訪中|訪米|会談|協議|出資|資金調達|上場|申請|"
    r"上昇|下落|急落|増加|減少|改善|悪化|達成|突破|判明|結果|決算|"
    r"CPI|GDP|失業率|雇用統計|利益|売上|"
    r"announc|agree|sign|launch|release|update|acqui|merge|appoint|"
    r"resign|join|leave|delay|cancel|approve|invest|raise|filed|"
    r"rose|fell|increase|decrease)",
    re.I,
)
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
DISCOVERY_CHANGE_TERMS = [
    "partnership",
    "提携",
    "agreement",
    "合意",
    "joint",
    "共同",
    "acquisition",
    "買収",
    "investment",
    "投資",
    "security",
    "安全保障",
    "supply chain",
    "供給網",
    "regulation",
    "規制",
    "contract",
    "契約",
    "official",
    "公式",
    "market share",
    "シェア",
    "benchmark",
    "funding",
    "資金調達",
    "debt",
    "rating",
    "hiring",
    "採用",
    "construction",
    "建設",
    "appointment",
    "就任",
    "resignation",
    "退任",
]


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL CORE FAILED: {message}", file=sys.stderr)
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
    HIDDEN_TAGS = {
        "script",
        "style",
        "noscript",
        "svg",
        "nav",
        "footer",
        "aside",
        "dialog",
        "form",
        "button",
        "select",
        "option",
    }

    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []
        self.hidden_depth = 0

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag in self.HIDDEN_TAGS:
            self.hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self.HIDDEN_TAGS and self.hidden_depth:
            self.hidden_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self.hidden_depth:
            text = " ".join(data.split())
            if text:
                self.parts.append(text)


def compact_text(value: str, limit: int = 1600) -> str:
    return " ".join(html.unescape(value).split())[:limit]


def html_fragment_text(value: str, limit: int = 1600) -> str:
    parser = VisibleTextParser()
    try:
        parser.feed(html.unescape(value))
        parser.close()
    except (ValueError, TypeError):
        return compact_text(value, limit)
    return compact_text(" ".join(parser.parts), limit)


def structured_article_text(value: str) -> tuple[str, str] | None:
    articles: list[dict[str, Any]] = []

    def visit(node: Any) -> None:
        if isinstance(node, list):
            for child in node:
                visit(child)
            return
        if not isinstance(node, dict):
            return
        raw_type = node.get("@type")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if any(
            str(kind).lower() in {"article", "newsarticle", "reportagenewsarticle"}
            for kind in types
        ):
            articles.append(node)
        for child in node.values():
            if isinstance(child, (dict, list)):
                visit(child)

    for match in re.finditer(
        r"<script[^>]+type=[\"']application/ld\+json[\"'][^>]*>(.*?)</script>",
        value,
        flags=re.I | re.S,
    ):
        try:
            visit(json.loads(html.unescape(match.group(1))))
        except (json.JSONDecodeError, TypeError):
            continue
    if not articles:
        return None
    article = max(
        articles,
        key=lambda item: len(
            str(item.get("articleBody") or item.get("description") or "")
        ),
    )
    title = compact_text(str(article.get("headline") or article.get("name") or ""), 220)
    body = compact_text(
        " ".join(
            str(part)
            for part in (
                article.get("description"),
                article.get("articleBody"),
            )
            if part
        ),
        4000,
    )
    return (title, body) if title and len(body) >= 60 else None


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


def same_material_event(left: Any, right: Any) -> bool:
    return state_contract.same_material_event(left, right)


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
    return selected


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
    text = state_contract.PUBLISHER_SUFFIX_RE.sub("", text)
    text = state_contract.DOMAIN_RE.sub("", text)
    text = re.sub(r"[「『]\s*[」』]", "", text)
    text = text.strip(" -–—|｜")
    for pattern, replacement in PUBLIC_COPY_REPLACEMENTS:
        text = re.sub(pattern, replacement, text)
    for term in state_contract.PUBLIC_COPY_FORBIDDEN_TERMS:
        if term in text:
            text = text.replace(term, PUBLIC_TERM_REPLACEMENTS.get(term, ""))
    return compact_text(text, limit)


TRAILING_MEDIA_CREDIT_RE = re.compile(
    r"\s*[（(](?:フィスコ|音楽ナタリー|BASKET COUNT|共同通信|時事通信|Reuters|ロイター)[）)]$",
    re.I,
)


def record_public_title(record: dict[str, Any]) -> str:
    raw = compact_text(str(record.get("title", "")), 500)
    label = compact_text(str(record.get("label", "")), 120)
    if label:
        raw = re.sub(
            rf"\s[-–—]\s*{re.escape(label)}(?:\s[-–—].*)?$",
            "",
            raw,
            flags=re.I,
        )
    raw = re.sub(r"\s+執筆$", "", raw)
    raw = re.sub(r"\s[-–—]\s*エキスパート$", "", raw)
    raw = re.sub(r"(?:\s*[|｜]\s*)?ニュースリリース$", "", raw)
    raw = TRAILING_MEDIA_CREDIT_RE.sub("", raw)
    return reader_facing_text(raw, 180)


def useful_fact(fact: str, category_label: str) -> bool:
    text = reader_facing_text(fact, 500)
    if GENERIC_IMPORTANCE_RE.search(text) or state_contract.material_fact_violations(text):
        return False
    if category_label and f"{category_label}の重要更新として確認" in text:
        return False
    return True


def reader_public_copy_ok(text: str, *, kind: str) -> bool:
    return not state_contract.public_render_copy_violations(text, kind=kind)


def category_identity_ok(category_label: str, title: str, summary: str) -> bool:
    terms = CATEGORY_IDENTITY_TERMS.get(category_label)
    if not terms:
        return True
    text = f"{title} {summary}".lower()
    return any(term.lower() in text for term in terms)


def contains_material_signal(*values: str) -> bool:
    text = " ".join(str(value or "") for value in values)
    return bool(MATERIAL_SIGNAL_RE.search(text))


def material_event_candidate(title: str, *evidence_values: str) -> bool:
    text = " ".join([str(title), *(str(value or "") for value in evidence_values)])
    return bool(
        state_contract.analysis_headline(title)
        or PUBLICATION_EVENT_RE.search(title)
        or MATERIAL_SIGNAL_RE.search(text)
    )


def low_signal_value(*values: str) -> bool:
    text = " ".join(str(value or "") for value in values)
    return bool(LOW_SIGNAL_VALUE_RE.search(text))


def publication_item_supported(title: str, *evidence_values: str) -> bool:
    evidence = " ".join(str(value or "") for value in evidence_values)
    if state_contract.analysis_headline(title):
        supporting_sentences = [
            sentence
            for sentence in sentence_parts(evidence)
            if state_contract.title_repetition_score(title, sentence) < 0.82
        ]
        facts = state_contract.normalize_material_facts(
            title,
            supporting_sentences,
        )
        return bool(facts) and bool(state_contract.analysis_conclusion(facts))
    return material_event_candidate(title, evidence)


def record_has_only_headline(title: str, record: dict[str, Any]) -> bool:
    """Identify feeds whose excerpt is only the headline plus publisher credit."""
    excerpt = reader_facing_text(record.get("excerpt") or record.get("evidence") or "", 2400)
    cleaned = excerpt.rstrip("。.!！ ")
    labels = [
        str(record.get("label") or "").strip(),
        urllib.parse.urlparse(str(record.get("publisher_url") or "")).netloc
        .lower()
        .removeprefix("www."),
    ]
    for label in labels:
        if label and cleaned.lower().endswith(label.lower()):
            cleaned = cleaned[: -len(label)].rstrip(" -–—|｜。.!！ ")
    return normalized_topic_key(title) == normalized_topic_key(cleaned)


def source_material_facts(
    title: str,
    records: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> list[str]:
    records = [record for record in records if not record_has_only_headline(title, record)]
    candidates: list[str] = []
    for record in records:
        excerpt = str(record.get("excerpt") or "")
        for sentence in sentence_parts(excerpt):
            if len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", sentence)) < 8:
                continue
            if state_contract.title_repetition_score(title, sentence) >= 0.82:
                continue
            if useful_fact(sentence, ""):
                candidates.append(sentence)
    return state_contract.normalize_material_facts(title, candidates, limit=limit)


def record_has_material_body(title: str, record: dict[str, Any]) -> bool:
    """Return whether the fetched body adds usable substance beyond its headline."""
    if record_has_only_headline(title, record):
        return False
    excerpt = str(record.get("excerpt") or "")
    for sentence in sentence_parts(excerpt):
        if state_contract.title_repetition_score(title, sentence) >= 0.82:
            continue
        japanese_count = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", sentence))
        latin_words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", sentence)
        if japanese_count >= 8 and useful_fact(sentence, ""):
            return True
        if len(latin_words) >= 8 and not state_contract.navigation_shell_text(sentence):
            return True
    return False


def publication_evidence_record(
    category: dict[str, Any],
    issue_date: str,
    record: dict[str, Any],
) -> bool:
    """Return whether a coverage record can support a public update."""
    if (
        not record.get("observed")
        or not valid_date(record.get("published_date"), issue_date)
        or not record_document_is_current(record, issue_date)
    ):
        return False
    title = record_public_title(record)
    excerpt = reader_facing_text(record.get("excerpt") or record.get("evidence") or "", 2400)
    category_label = str(category.get("label", ""))
    if (
        not title
        or not excerpt
        or state_contract.navigation_shell_text(f"{title} {excerpt}")
        or state_contract.NO_UPDATE_ASSERTION_RE.search(f"{title} {excerpt}")
        or not category_identity_ok(category_label, title, excerpt)
        or low_signal_value(title, excerpt)
        or not publication_item_supported(title, excerpt)
        or not record_has_material_body(title, record)
    ):
        return False
    return True


def publication_evidence_records(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        record
        for record in select_clustered_evidence(category, records)
        if publication_evidence_record(category, issue_date, record)
    ]


def fact_supported_by_records(
    fact: str,
    source_records: list[dict[str, Any]],
) -> bool:
    fact_numbers = set(re.findall(r"\d+(?:\.\d+)?", fact))
    for record in source_records:
        title = record_public_title(record)
        evidence = reader_facing_text(
            f"{record.get('title', '')} {record.get('excerpt') or record.get('evidence') or ''}",
            3000,
        )
        evidence_numbers = set(re.findall(r"\d+(?:\.\d+)?", evidence))
        if fact_numbers and not fact_numbers <= evidence_numbers:
            continue
        evidence_japanese = len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", evidence))
        evidence_latin = len(re.findall(r"[A-Za-z]", evidence))
        if evidence_latin >= 24 and evidence_japanese < 6:
            return True
        if (
            state_contract.materially_same_fact(fact, title)
            or state_contract.text_overlap(fact, evidence) >= 2
        ):
            return True
    return False


def analysis_narrative(title: str, facts: list[str]) -> tuple[str, str, str] | None:
    if not state_contract.analysis_headline(title):
        return None
    scope = state_contract.analysis_scope_sentence(title)
    conclusion = state_contract.analysis_conclusion(facts)
    if not scope or not conclusion or not facts:
        return None
    summary = unique_sentences(" ".join([scope, *facts, conclusion]), None)
    return scope, conclusion, summary


def facts_add_information_beyond_title(title: str, facts: list[str]) -> bool:
    return bool(facts) and any(
        state_contract.fact_adds_information(title, fact) for fact in facts
    )


UNCERTAINTY_RE = re.compile(
    r"未定|未確定|未公表|明らかになっていない|公表していない|"
    r"開示していない|今後決定|調整中|検討中|"
    r"not disclosed|not announced|unknown|pending|to be decided",
    re.I,
)


def event_limits_sentence(title: str, excerpt: str) -> str:
    del title
    for sentence in sentence_parts(excerpt):
        if UNCERTAINTY_RE.search(sentence) and not state_contract.NO_UPDATE_ASSERTION_RE.search(sentence):
            return sentence.rstrip("。")
    return ""


def page_text(raw: bytes, content_type: str) -> tuple[str, str]:
    charset_match = re.search(r"charset=([A-Za-z0-9._-]+)", content_type)
    charset = charset_match.group(1) if charset_match else "utf-8"
    text = raw.decode(charset, errors="replace")
    if "<html" not in text[:1000].lower() and "<!doctype" not in text[:1000].lower():
        plain = compact_text(text, 4000)
        return plain[:180], plain
    structured = structured_article_text(text)
    if structured:
        return structured
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>",
        text,
        flags=re.I | re.S,
    )
    title = compact_text(title_match.group(1), 180) if title_match else ""
    parser = VisibleTextParser()
    parser.feed(text)
    return title, compact_text(" ".join(parser.parts), 4000)


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
            results: list[str] = []
            for item in root.findall(".//item"):
                title = compact_text(item.findtext("title") or "", 220)
                link = compact_text(item.findtext("link") or "", 1000)
                description = html_fragment_text(item.findtext("description") or "", 900)
                if not title or not link.startswith(("http://", "https://")):
                    continue
                result_host = urllib.parse.urlparse(link).netloc.lower().removeprefix("www.")
                source_host = parsed.netloc.lower().removeprefix("www.")
                if result_host != source_host and not result_host.endswith(f".{source_host}"):
                    continue
                if source.get("channel") == "sns_x":
                    source_path = parsed.path.rstrip("/").lower()
                    result_path = urllib.parse.urlparse(link).path.rstrip("/").lower()
                    if source_path and not (
                        result_path == source_path
                        or result_path.startswith(f"{source_path}/")
                    ):
                        continue
                results.append(" / ".join(part for part in (title, link, description) if part))
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
        "verification_method": "source_limited_search",
        "evidence": (
            f"{source_kind}{source_url}に限定したBing RSS検索を確認した。"
            f"検索語: {used_query}。検索結果: {excerpt[:500]}"
        ),
    }


def fetch_source(source: dict[str, Any]) -> dict[str, Any]:
    url = str(source["url"])
    if source.get("channel") in {"sns_x", "youtube", "instagram", "facebook"}:
        try:
            return source_search_fallback(source)
        except (OSError, TimeoutError, urllib.error.URLError, ValueError):
            pass
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
                "verification_method": "direct_fetch" if attempt == url else "reader_fetch",
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
        "verification_method": "unavailable",
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


def discovery_identity_query(category: dict[str, Any]) -> str:
    label = str(category["label"])
    terms = CATEGORY_IDENTITY_TERMS.get(label, [label])
    useful = list(dict.fromkeys(str(term) for term in terms if str(term).strip()))[:6]
    return " OR ".join(f'"{term}"' if " " in term else term for term in useful)


def discovery_queries(category: dict[str, Any], issue_date: str) -> list[dict[str, Any]]:
    """Build bounded searches that prove each watch topic was actually queried."""
    identity = discovery_identity_query(category)
    queries: list[dict[str, Any]] = []
    configured_topic_terms: set[str] = set()
    for topic in category.get("watch_topics", []):
        if not isinstance(topic, dict) or not topic.get("id"):
            continue
        topic_id = str(topic["id"])
        terms = list(
            dict.fromkeys(
                str(term).strip()
                for term in [*topic.get("terms", []), *topic.get("event_classes", [])]
                if str(term).strip()
            )
        )
        configured_topic_terms.update(term.lower() for term in terms)
        for index in range(0, len(terms), 20):
            group = terms[index : index + 20]
            queries.append(
                {
                    "query_id": f"topic:{topic_id}:{index // 20 + 1}",
                    "purpose": "watch_topic",
                    "watch_topic_ids": [topic_id],
                    "query": f"({identity}) ({' OR '.join(group)}) when:3d",
                    "provider": "google_news_rss",
                    "channel": "web",
                }
            )

    axis_only_terms = list(
        dict.fromkeys(
            str(term).strip()
            for axis in category.get("axes", [])
            if isinstance(axis, dict)
            for term in axis.get("terms", [])
            if str(term).strip().lower() not in configured_topic_terms
        )
    )
    horizon_terms = list(dict.fromkeys([*axis_only_terms, *DISCOVERY_CHANGE_TERMS]))
    for index in range(0, len(horizon_terms), 20):
        group = horizon_terms[index : index + 20]
        queries.append(
            {
                "query_id": f"horizon:material-change:{index // 20 + 1}",
                "purpose": "horizon",
                "watch_topic_ids": [],
                "query": f"({identity}) ({' OR '.join(group)}) when:3d",
                "provider": "google_news_rss",
                "channel": "web",
            }
        )
    return queries


def news_queries(category: dict[str, Any], issue_date: str) -> list[str]:
    return [str(spec["query"]) for spec in discovery_queries(category, issue_date)]


def news_query(category: dict[str, Any], issue_date: str) -> str:
    return news_queries(category, issue_date)[0]


def canonical_article_match_text(value: str) -> str:
    text = str(value).lower()
    replacements = (
        (r"総理大臣|総理|prime minister", " 首相 "),
        (r"パートナーシップ|協業|連携|mou|覚書|共同(?:展開|開発)?", " 提携 "),
        (r"announc\w*|launch\w*|発表|公表|公開|提供開始", " 発表 "),
        (r"acqui\w*|買収|取得", " 買収 "),
        (r"agreement|contract|契約|合意|締結", " 契約 "),
    )
    for pattern, replacement in replacements:
        text = re.sub(pattern, replacement, text, flags=re.I)
    return compact_text(text, 1200)


EVENT_QUERY_STOPWORDS = {
    "発表",
    "公表",
    "強化",
    "推進",
    "開始",
    "更新",
    "協力",
    "提携",
    "契約",
    "分野",
    "方針",
    "最新",
    "ニュース",
    "announced",
    "announces",
    "launch",
    "launched",
    "release",
    "released",
    "update",
    "updated",
}


def event_probe_terms(title: str) -> list[str]:
    """Extract a small, deterministic event query without domain-specific rules."""
    canonical = canonical_article_match_text(record_public_title({"title": title}))
    chunks = re.split(
        r"[、。,:：;；/／|｜・（）()【】\[\]\s]+|"
        r"(?<=[0-9A-Za-z一-龥ぁ-んァ-ンー])(?:から|より|の|と|が|を|へ|に|で)"
        r"(?=[0-9A-Za-z一-龥ぁ-んァ-ンー])",
        canonical,
    )
    chunks.extend(re.findall(r"[A-Za-z][A-Za-z0-9.+-]{2,}|\d+(?:\.\d+)?", canonical))
    ranked: list[tuple[int, int, str]] = []
    seen: set[str] = set()
    for position, raw in enumerate(chunks):
        term = raw.strip(" -–—'\"")
        term = re.sub(r"^(?:から|より|の|と|が|を|へ|に|で)+", "", term)
        key = term.casefold()
        if len(term) < 2 or key in EVENT_QUERY_STOPWORDS or key in seen:
            continue
        if not re.search(r"[0-9A-Za-z一-龥ァ-ヶー]", term):
            continue
        seen.add(key)
        score = min(len(term), 12)
        if re.search(r"(?:首相|大統領|政府|省|庁|社|銀行|大学|機構|委員会)$", term):
            score += 10
        if re.search(r"[A-Z0-9]", term):
            score += 5
        ranked.append((score, -position, term))
    return [term for _, _, term in sorted(ranked, reverse=True)[:5]]


def event_probe_query(title: str) -> str:
    terms = event_probe_terms(title)
    return " ".join(terms) if terms else compact_text(title, 180)


def article_candidate_score(original_title: str, candidate_text: str) -> int:
    original = canonical_article_match_text(original_title)
    candidate = canonical_article_match_text(candidate_text)
    matched_terms = sum(
        1 for term in event_probe_terms(original_title) if term.casefold() in candidate
    )
    return (
        round(100 * state_contract.title_repetition_score(original, candidate))
        + 12 * state_contract.text_overlap(original, candidate)
        + 18 * matched_terms
        + 25 * bool(PUBLICATION_EVENT_RE.search(candidate_text))
        + 15 * bool(MATERIAL_SIGNAL_RE.search(candidate_text))
    )


def article_result_matches(original_title: str, result_title: str) -> bool:
    canonical_original = canonical_article_match_text(original_title)
    canonical_result = canonical_article_match_text(result_title)
    return (
        state_contract.title_repetition_score(original_title, result_title) >= 0.45
        or state_contract.text_overlap(original_title, result_title) >= 2
        or state_contract.title_repetition_score(
            canonical_original,
            canonical_result,
        ) >= 0.45
        or state_contract.text_overlap(canonical_original, canonical_result) >= 2
    )


def normalized_ocr_digits(value: str) -> str:
    text = re.sub(r"(?<!\d)(20\d)\s+(\d)(?=\s*年)", r"\1\2", str(value))
    return re.sub(r"(?<=\d)\s+(?=\d\s*(?:月|日))", "", text)


def document_period_months(value: str) -> set[int]:
    normalized = normalized_ocr_digits(value)
    return {
        int(month)
        for month in re.findall(
            r"(?<!\d)(\d{1,2})\s*月\s*(?:調査|期|分|実績|結果)",
            normalized,
        )
        if 1 <= int(month) <= 12
    }


def embedded_document_date(value: str) -> date | None:
    normalized = normalized_ocr_digits(value)
    published = re.search(
        r"Published Time:\s*([^\n]{8,80}?GMT)",
        normalized,
        flags=re.I,
    )
    if published:
        try:
            return email.utils.parsedate_to_datetime(published.group(1)).date()
        except (TypeError, ValueError):
            pass
    document_header = normalized[:1600]
    japanese = (
        re.search(
            r"(?<!\d)(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
            document_header,
        )
        if re.search(
            r"経済レポート|発行日|作成日|お問い合わせ|Number of Pages|Markdown Content",
            document_header,
            flags=re.I,
        )
        else None
    )
    if japanese:
        try:
            return date(*(int(part) for part in japanese.groups()))
        except ValueError:
            pass
    return None


def url_document_month(value: str) -> tuple[int, int] | None:
    match = re.search(r"/(20\d{2})/(0?[1-9]|1[0-2])(?:/|$)", str(value))
    return (int(match.group(1)), int(match.group(2))) if match else None


def document_matches_discovery(
    record: dict[str, Any],
    candidate_url: str,
    page_title: str,
    body: str,
) -> bool:
    try:
        discovery_date = date.fromisoformat(str(record.get("published_date", "")))
    except ValueError:
        return False
    candidate_text = f"{page_title} {body}"
    document_date = embedded_document_date(candidate_text)
    if document_date and abs((discovery_date - document_date).days) > 7:
        return False
    document_month = url_document_month(candidate_url)
    if document_month:
        distance = abs(
            (discovery_date.year * 12 + discovery_date.month)
            - (document_month[0] * 12 + document_month[1])
        )
        if distance > 1:
            return False
    discovery_months = document_period_months(record_public_title(record))
    page_months = document_period_months(page_title)
    return not (
        discovery_months
        and page_months
        and discovery_months.isdisjoint(page_months)
    )


def record_document_is_current(record: dict[str, Any], issue_date: str) -> bool:
    try:
        issue_day = date.fromisoformat(issue_date)
    except ValueError:
        return False
    text = f"{record.get('title', '')} {record.get('excerpt', '')}"
    document_date = embedded_document_date(text)
    if document_date and not 0 <= (issue_day - document_date).days <= 7:
        return False
    document_month = (
        url_document_month(str(record.get("url", "")))
        if record.get("source_class") == "discovered_media"
        or record.get("original_discovery_url")
        else None
    )
    if document_month:
        distance = abs(
            (issue_day.year * 12 + issue_day.month)
            - (document_month[0] * 12 + document_month[1])
        )
        if distance > 1:
            return False
    return True


def article_search_queries(record: dict[str, Any], original_title: str) -> list[str]:
    queries = [f'"{original_title}"']
    publisher = urllib.parse.urlparse(str(record.get("publisher_url", "")))
    host = publisher.netloc.lower().removeprefix("www.")
    if host:
        queries.append(f"site:{host} {original_title}")
    probe = event_probe_query(original_title)
    if probe and probe != original_title:
        queries.append(probe)
    return list(dict.fromkeys(queries))


def article_record_from_candidate(
    category_label: str,
    record: dict[str, Any],
    original_title: str,
    candidate_url: str,
    result_title: str,
    description: str,
) -> dict[str, Any] | None:
    for attempt in (candidate_url, jina_url(candidate_url)):
        try:
            page_raw, content_type, _ = request_bytes(attempt, timeout=12)
            page_title, body = page_text(page_raw, content_type)
        except (OSError, TimeoutError, urllib.error.URLError, ValueError):
            continue
        body = compact_text(body, 4000)
        body_record = {**record, "excerpt": body}
        combined = (
            body
            if record_has_material_body(original_title, body_record)
            else compact_text(f"{description} {body}", 2400)
        )
        candidate_record = {**record, "excerpt": combined}
        if (
            len(combined) < 80
            or state_contract.navigation_shell_text(combined)
            or not record_has_material_body(original_title, candidate_record)
            or not category_identity_ok(category_label, original_title, combined)
            or not article_result_matches(
                original_title,
                f"{page_title or result_title} {combined}",
            )
            or not document_matches_discovery(
                record,
                candidate_url,
                page_title or result_title,
                combined,
            )
        ):
            continue
        parsed = urllib.parse.urlparse(candidate_url)
        resolved_label = parsed.netloc.lower().removeprefix("www.")
        publisher_url = (
            f"{parsed.scheme}://{parsed.netloc}"
            if parsed.scheme in {"http", "https"} and parsed.netloc
            else str(record.get("publisher_url", ""))
        )
        return {
            **record,
            "label": resolved_label or str(record.get("label", "")),
            "url": candidate_url,
            "publisher_url": publisher_url,
            "original_discovery_url": str(record.get("url", "")),
            "title": original_title,
            "excerpt": combined,
            "evidence": (
                f"Google News RSSで「{original_title}」を確認し、"
                f"配信元ページ{candidate_url}を特定した。"
                f"本文抽出: {combined[:700]}"
            ),
        }
    return None


def enrich_discovered_record(
    category: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    original_title = record_public_title(record)
    if not original_title:
        return record
    category_label = str(category.get("label", ""))
    candidates: dict[str, tuple[int, str, str, str]] = {}
    for query in article_search_queries(record, original_title):
        search_url = "https://www.bing.com/search?" + urllib.parse.urlencode(
            {"format": "rss", "q": query}
        )
        try:
            raw, _, _ = request_bytes(search_url, timeout=12)
            root = ET.fromstring(raw)
        except (OSError, TimeoutError, urllib.error.URLError, ET.ParseError):
            continue
        for item in root.findall(".//item"):
            result_title = compact_text(item.findtext("title") or "", 220)
            candidate_url = compact_text(item.findtext("link") or "", 1000)
            description = html_fragment_text(item.findtext("description") or "", 1000)
            if (
                not candidate_url.startswith(("http://", "https://"))
                or "news.google.com" in candidate_url
                or not article_result_matches(
                    original_title,
                    f"{result_title} {description}",
                )
                or not category_identity_ok(
                    category_label,
                    result_title,
                    description,
                )
            ):
                continue
            candidate = (
                article_candidate_score(
                    original_title,
                    f"{result_title} {description}",
                ),
                candidate_url,
                result_title,
                description,
            )
            current = candidates.get(candidate_url)
            if current is None or candidate[0] > current[0]:
                candidates[candidate_url] = candidate

    for _, candidate_url, result_title, description in sorted(
        candidates.values(),
        reverse=True,
    )[:8]:
        parsed_candidate = urllib.parse.urlparse(candidate_url)
        snippet_record = {
            **record,
            "label": parsed_candidate.netloc.lower().removeprefix("www."),
            "url": candidate_url,
            "publisher_url": (
                f"{parsed_candidate.scheme}://{parsed_candidate.netloc}"
            ),
            "original_discovery_url": str(record.get("url", "")),
            "title": original_title,
            "excerpt": description,
            "evidence": (
                f"Google News RSSで「{original_title}」を確認し、"
                f"配信元検索で{candidate_url}と本文抜粋を特定した。"
                f"検索抜粋: {description[:700]}"
            ),
        }
        resolved = article_record_from_candidate(
            category_label,
            record,
            original_title,
            candidate_url,
            result_title,
            description,
        )
        if resolved:
            return resolved
        if (
            description
            and document_matches_discovery(
                record,
                candidate_url,
                result_title,
                description,
            )
            and record_has_material_body(original_title, snippet_record)
        ):
            return snippet_record
    return record


def enrichment_target_urls(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> set[str]:
    targets: set[str] = set()
    category_label = str(category.get("label", ""))
    for record in select_clustered_evidence(category, records):
        url = str(record.get("url", ""))
        title = record_public_title(record)
        excerpt = str(record.get("excerpt") or "")
        if (
            url
            and record.get("observed")
            and valid_date(record.get("published_date"), issue_date)
            and category_identity_ok(category_label, title, excerpt)
            and not low_signal_value(title, excerpt)
            and discovery_record_is_material(record)
            and not record_has_material_body(title, record)
        ):
            targets.add(url)
    return targets


def enrich_discovered_records(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    targets = enrichment_target_urls(category, issue_date, records)
    return [
        enrich_discovered_record(category, record)
        if str(record.get("url", "")) in targets
        else record
        for record in records
    ]


def discovery_record_is_relevant(
    category: dict[str, Any],
    issue_date: str,
    record: dict[str, Any],
) -> bool:
    title = record_public_title(record)
    excerpt = str(record.get("excerpt") or "")
    return bool(
        valid_date(record.get("published_date"), issue_date)
        and category_identity_ok(str(category.get("label", "")), title, excerpt)
        and not low_signal_value(title, excerpt)
    )


def discovery_record_is_material(record: dict[str, Any]) -> bool:
    title = record_public_title(record)
    excerpt = str(record.get("excerpt") or "")
    return material_event_candidate(title, excerpt)


def fetch_news(category: dict[str, Any], issue_date: str) -> dict[str, Any]:
    records_by_url: dict[str, dict[str, Any]] = {}
    checks: list[dict[str, Any]] = []
    for spec in discovery_queries(category, issue_date):
        query = str(spec["query"])
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
            checks.append(
                {
                    **spec,
                    "url": rss_url,
                    "label": "Google News RSS",
                    "slot_state": "search_unavailable",
                    "result_count": 0,
                    "relevant_result_count": 0,
                    "material_candidate_count": 0,
                    "resolved_candidate_count": 0,
                    "evidence_summary": f"検索に失敗した: {type(exc).__name__}: {exc}",
                }
            )
            continue
        result_count = 0
        relevant_urls: set[str] = set()
        material_urls: set[str] = set()
        for item in root.findall(".//item"):
            title = compact_text(item.findtext("title") or "", 220)
            link = compact_text(item.findtext("link") or "", 1000)
            if not title or not link.startswith(("http://", "https://")):
                continue
            result_count += 1
            description = html_fragment_text(item.findtext("description") or "", 700)
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
            record = {
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
                "discovery_query_ids": [str(spec["query_id"])],
                "watch_topic_ids": list(spec["watch_topic_ids"]),
                "evidence": (
                    f"Google News RSSで「{title}」を確認した。"
                    f"配信元は{source_label}、配信日は"
                    f"{parse_rss_date(item.findtext('pubDate')) or '日付不明'}。"
                ),
            }
            if not discovery_record_is_relevant(category, issue_date, record):
                continue
            relevant_urls.add(link)
            if discovery_record_is_material(record):
                material_urls.add(link)
            current = records_by_url.get(link)
            if current is None:
                records_by_url[link] = record
            else:
                current["discovery_query_ids"] = list(
                    dict.fromkeys(
                        [*current.get("discovery_query_ids", []), str(spec["query_id"])]
                    )
                )
                current["watch_topic_ids"] = list(
                    dict.fromkeys(
                        [*current.get("watch_topic_ids", []), *spec["watch_topic_ids"]]
                    )
                )
        checks.append(
            {
                **spec,
                "url": rss_url,
                "label": "Google News RSS",
                "slot_state": "searched",
                "result_count": result_count,
                "relevant_result_count": len(relevant_urls),
                "material_candidate_count": len(material_urls),
                "resolved_candidate_count": 0,
                "material_urls": sorted(material_urls),
                "evidence_summary": (
                    f"{result_count}件を確認し、対象期間・カテゴリに合う結果は"
                    f"{len(relevant_urls)}件、重要更新候補は{len(material_urls)}件だった。"
                ),
            }
        )

    records = enrich_discovered_records(category, issue_date, list(records_by_url.values()))
    enriched_by_url: dict[str, dict[str, Any]] = {}
    for record in records:
        enriched_by_url[str(record.get("url"))] = record
        original_url = str(record.get("original_discovery_url") or "")
        if original_url:
            enriched_by_url[original_url] = record
    for check in checks:
        if check["slot_state"] == "search_unavailable":
            continue
        material_urls = check.pop("material_urls", [])
        resolved = sum(
            bool(record and record_has_material_body(record_public_title(record), record))
            for url in material_urls
            for record in [enriched_by_url.get(str(url))]
        )
        check["resolved_candidate_count"] = resolved
        if check["relevant_result_count"] == 0:
            check["slot_state"] = "searched_no_results"
        elif check["material_candidate_count"] == 0:
            check["slot_state"] = "searched_no_material_results"
        elif resolved:
            check["slot_state"] = "searched_resolved"
        else:
            check["slot_state"] = "searched_unresolved"
        check["evidence_summary"] += f" 本文を解決できた重要更新候補は{resolved}件。"
    return {"records": records, "discovery_checks": checks}


def category_contracts() -> list[dict[str, Any]]:
    coverage = load_object(COVERAGE_CONFIG)
    return [
        category
        for category in coverage.get("categories", [])
        if isinstance(category, dict)
    ]


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


def category_prompt(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> dict[str, Any]:
    selected = publication_evidence_records(category, issue_date, records)
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
        "evidence": [
            {
                "label": record.get("label"),
                "url": record.get("url"),
                "source_role": record.get("source_role"),
                "channel": record.get("channel"),
                "published_date": record.get("published_date"),
                "title": record.get("title"),
                "excerpt": compact_text(
                    str(record.get("excerpt") or record.get("evidence") or ""),
                    1000,
                ),
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


def reader_facing_source_label(value: Any, url: str) -> str:
    label = compact_text(str(value or ""), 120)
    if re.search(r"[0-9A-Za-z\u3040-\u30ff\u3400-\u9fff]", label):
        return label
    hostname = urllib.parse.urlparse(url).hostname or ""
    return hostname.removeprefix("www.") or url


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
                "label": reader_facing_source_label(
                    record.get("label") or source.get("label"),
                    url,
                ),
                "url": url,
                "source_role": str(
                    record.get("source_role", "independent_media_or_data")
                ),
                "channel": str(record.get("channel", "web")),
                "published_date": record.get("published_date"),
                "evidence_summary": str(record.get("evidence", "")),
            }
        )
    return cleaned


def sentence_key(value: str) -> str:
    return state_contract.copy_signature(reader_facing_text(value, 1200))


def sentence_parts(value: str) -> list[str]:
    parts: list[str] = []
    for part in re.split(r"(?<=[。！？!?])", reader_facing_text(value, 2400)):
        text = part.strip()
        if text and not re.fullmatch(
            r"(?:ニュース|ファイナンス|MSN|web|オンライン)[。．.!！?？]*",
            text,
            flags=re.I,
        ):
            parts.append(text if text.endswith(("。", "！", "？", "!", "?")) else f"{text}。")
    if not parts and value:
        text = reader_facing_text(value, 700).strip()
        if text:
            parts.append(text if text.endswith("。") else f"{text}。")
    return parts


def unique_sentences(value: str, limit: int | None = 1200) -> str:
    kept: list[str] = []
    for sentence in sentence_parts(value):
        if not sentence_key(sentence):
            continue
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(kept)
                if state_contract.materially_same_fact(sentence, existing)
            ),
            None,
        )
        if duplicate_index is not None:
            if state_contract.fact_specificity(sentence) > state_contract.fact_specificity(
                kept[duplicate_index]
            ):
                kept[duplicate_index] = sentence
            continue
        kept.append(sentence)
    composed = "".join(kept)
    return compact_text(composed, limit) if limit is not None else composed


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
    if re.search(r"社債|債券|debt|rating|格付|market share|シェア|株価|price target|funding|資金調達|ipo|上場|資金流入|金利|物価|gdp|利益|売上|評価益|決算|cash flow|キャッシュフロー", text):
        return "market_or_financial_impact"
    if re.search(r"yoasobi|幾田りら|発売|ep|アルバム|展覧会|トレーラー|楽曲|ツアー", text):
        return "cultural_or_audience_signal"
    if re.search(r"model|モデル|api|release|launch|製品|技術|benchmark|ベンチマーク|ecu|標準化|アップグレード|pipeline|パイプライン", text):
        return "technical_or_product_shift"
    if re.search(r"契約|提携|合意|協議|partnership|contract|採用|移籍|退団|獲得|hiring|joins|leaves", text):
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
    title = record_public_title(record)
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
    topic_value = topic_value_from_record(record)
    fact_values = source_material_facts(title, [record])
    facts = (
        state_contract.normalize_analysis_facts(title, fact_values)
        if state_contract.analysis_headline(title)
        else state_contract.normalize_material_facts(title, fact_values)
    )
    if not facts_add_information_beyond_title(title, facts):
        return None
    analysis = analysis_narrative(title, facts)
    if analysis is not None:
        what_changed, why_it_matters, _ = analysis
    else:
        why_it_matters = ""
        what_changed = facts[0]
    limits = event_limits_sentence(title, excerpt)
    return {
        "watch_topic_id": topic,
        "title": title,
        "source_published_date": source_date,
        "topic_value_class": topic_value,
        "priority_class": "priority",
        "slug": (
            "auto-"
            + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
            + f"-{issue_date}"
        ),
        "what_changed": what_changed,
        "why_it_matters": why_it_matters,
        "confirmed_facts": facts,
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
    seen = {
        normalized_topic_key(item.get("title"))
        for item in normalized.get("items", [])
        if isinstance(item, dict)
    }
    for record in publication_evidence_records(category, issue_date, records):
        item = fallback_item_from_record(category, issue_date, record)
        if not item:
            continue
        key = normalized_topic_key(item.get("title"))
        if cluster_seen(seen, key):
            continue
        seen.add(key)
        normalized["items"].append(item)


def merge_related_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for item in items:
        match_index = next(
            (
                index
                for index, existing in enumerate(merged)
                if str(existing.get("watch_topic_id", ""))
                == str(item.get("watch_topic_id", ""))
                and same_material_event(
                    str(existing.get("title", "")),
                    str(item.get("title", "")),
                )
            ),
            None,
        )
        if match_index is None:
            merged.append(item)
            continue

        existing = merged[match_index]
        primary = min(
            (existing, item),
            key=lambda value: len(str(value.get("title", ""))) or 999,
        )
        facts = state_contract.normalize_material_facts(
            "",
            [
                *existing.get("confirmed_facts", []),
                *item.get("confirmed_facts", []),
            ],
        )
        sources: list[dict[str, Any]] = []
        seen_urls: set[str] = set()
        for source in [*existing.get("sources", []), *item.get("sources", [])]:
            if not isinstance(source, dict):
                continue
            url = str(source.get("url", ""))
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            sources.append(source)
        title = str(primary.get("title", ""))
        merged[match_index] = {
            **primary,
            "what_changed": facts[0] if facts else str(primary.get("what_changed", "")),
            "why_it_matters": (
                str(primary.get("why_it_matters", ""))
                if state_contract.analysis_headline(title)
                else ""
            ),
            "confirmed_facts": facts,
            "sources": sources,
            "source_published_date": max(
                str(existing.get("source_published_date", "")),
                str(item.get("source_published_date", "")),
            ),
        }
    return merged


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
    eligible_records = publication_evidence_records(category, issue_date, records)
    records_by_url = {
        str(record["url"]): record
        for record in eligible_records
    }
    items: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_clusters: set[str] = set()
    for item in raw.get("items", []):
        if not isinstance(item, dict):
            continue
        topic = str(item.get("watch_topic_id", ""))
        title = reader_facing_text(item.get("title", ""), 180)
        facts = [
            reader_facing_text(fact, 500)
            for fact in item.get("confirmed_facts", [])
            if isinstance(fact, str) and fact.strip()
        ]
        sources = clean_sources(item.get("sources"), records_by_url)
        source_excerpt = " ".join(
            str(records_by_url.get(source["url"], {}).get("excerpt") or "")
            for source in sources
        )
        limits_or_unknowns = event_limits_sentence("", source_excerpt)
        facts = (
            state_contract.normalize_analysis_facts(title, facts)
            if state_contract.analysis_headline(title)
            else state_contract.normalize_material_facts(title, facts)
        )
        source_records = [records_by_url[source["url"]] for source in sources]
        facts = [
            fact
            for fact in facts
            if fact_supported_by_records(fact, source_records)
        ]
        facts = state_contract.normalize_material_facts(
            title,
            [*facts, *source_material_facts(title, source_records)],
        )
        if facts:
            what_changed = facts[0]
        else:
            what_changed = ""
        why_it_matters = ""
        analysis = analysis_narrative(title, facts)
        analysis_ready = not state_contract.analysis_headline(title) or analysis is not None
        if analysis is not None:
            what_changed, why_it_matters, _ = analysis
        factual_text = " ".join(facts)
        source_cluster = record_cluster_key(records_by_url.get(sources[0]["url"], {})) if sources else ""
        item_cluster = normalized_topic_key(title, source_cluster)
        topic_value = str(item.get("topic_value_class", ""))
        source_dates = {
            str(source.get("published_date"))
            for source in sources
            if source.get("published_date")
        }
        rejection_checks = [
            ("unknown_topic", topic not in valid_topics),
            ("empty_title", not title),
            ("title_copy", not reader_public_copy_ok(title, kind="title")),
            ("change_copy", not reader_public_copy_ok(what_changed, kind="summary")),
            (
                "importance_copy",
                bool(why_it_matters)
                and not reader_public_copy_ok(why_it_matters, kind="summary"),
            ),
            (
                "category_identity",
                not category_identity_ok(str(category.get("label", "")), title, factual_text),
            ),
            ("duplicate_title", title in seen_titles),
            (
                "insufficient_facts",
                not facts_add_information_beyond_title(title, facts),
            ),
            ("incomplete_analysis", not analysis_ready),
            ("missing_source", not sources),
            ("duplicate_cluster", cluster_seen(seen_clusters, item_cluster)),
            ("unknown_topic_value", topic_value not in ALLOWED_TOPIC_VALUES),
            (
                "invalid_source_date",
                not valid_date(item.get("source_published_date"), issue_date),
            ),
            (
                "source_date_not_in_evidence",
                str(item.get("source_published_date", "")) not in source_dates,
            ),
        ]
        rejection_reasons = [reason for reason, rejected in rejection_checks if rejected]
        if rejection_reasons:
            print(
                json.dumps(
                    {
                        "phase": "normalized_item_rejected",
                        "category": category.get("label"),
                        "title": title,
                        "reasons": rejection_reasons,
                        "fact_count": len(facts),
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
            continue
        seen_titles.add(title)
        seen_clusters.add(item_cluster)
        first_source = sources[0]
        items.append(
            {
                "watch_topic_id": topic,
                "title": title,
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
                "what_changed": what_changed,
                "why_it_matters": why_it_matters,
                "confirmed_facts": facts,
                "limits_or_unknowns": limits_or_unknowns,
                "sources": sources,
                "observation_source_role": first_source["source_role"],
                "observation_channel": first_source["channel"],
            }
        )
    return {"items": items}


def collect_evidence(issue_date: str) -> dict[str, Any]:
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
        news_futures = [
            executor.submit(fetch_news, category, issue_date)
            for category in contracts
        ]
        source_futures = [executor.submit(fetch_source, source) for source in flat_sources]
        fetched = [future.result() for future in source_futures]
        news_results = [future.result() for future in news_futures]
    records_by_category: dict[str, list[dict[str, Any]]] = {
        str(category["label"]): [] for category in contracts
    }
    discovery_checks_by_category: dict[str, list[dict[str, Any]]] = {
        str(category["label"]): [] for category in contracts
    }
    for record in fetched:
        label = str(record["category"])
        records_by_category[label].append(record)
    for category, news_result in zip(contracts, news_results):
        label = str(category["label"])
        known_urls = {str(record.get("url")) for record in records_by_category[label]}
        records_by_category[label].extend(
            record
            for record in news_result["records"]
            if record.get("observed") and str(record.get("url")) not in known_urls
        )
        discovery_checks_by_category[label] = news_result["discovery_checks"]

    checked_at = collection_checked_at(issue_date)
    bundle = evidence_contract.build_evidence_bundle(
        issue_date,
        checked_at,
        records_by_category,
        discovery_checks_by_category=discovery_checks_by_category,
        collection_mode="github_models_unattended",
    )
    state_dir = STATE_ROOT / issue_date
    state_dir.mkdir(parents=True, exist_ok=True)
    evidence_path = state_dir / "evidence.json"
    evidence_contract.write_bundle(evidence_path, bundle)
    return {
        "issue_date": issue_date,
        "checked_at_jst": checked_at,
        "categories": len(records_by_category),
        "source_checks": sum(
            len(entry["source_checks"])
            for entry in bundle["categories"].values()
        ),
        "discovery_checks": sum(
            len(entry["discovery_checks"])
            for entry in bundle["categories"].values()
        ),
        "records": sum(
            len(entry["records"])
            for entry in bundle["categories"].values()
        ),
        "evidence": str(evidence_path),
        "collection_mode": "github_models_unattended",
    }


def self_test() -> None:
    wide_category = {
        "label": "CoverageTest",
        "axes": [{"id": "adjacent", "terms": ["axis-only-term"]}],
        "watch_topics": [
            {"id": f"topic-{index}", "terms": [f"term-{index}"], "event_classes": []}
            for index in range(9)
        ],
    }
    if "term-8" not in " ".join(news_queries(wide_category, "2099-01-01")):
        fail("discovery queries dropped later watch topics")
    discovery_specs = discovery_queries(wide_category, "2099-01-01")
    searched_topics = {
        topic
        for spec in discovery_specs
        if spec["purpose"] == "watch_topic"
        for topic in spec["watch_topic_ids"]
    }
    expected_topics = {topic["id"] for topic in wide_category["watch_topics"]}
    if searched_topics != expected_topics:
        fail("discovery queries did not map every watch topic")
    if not any(spec["purpose"] == "horizon" for spec in discovery_specs):
        fail("discovery queries omitted the adjacent-change horizon")
    horizon_queries = " ".join(
        str(spec["query"])
        for spec in discovery_specs
        if spec["purpose"] == "horizon"
    )
    if "axis-only-term" not in horizon_queries:
        fail("discovery queries dropped an axis-only adjacent term")
    structured_fixture = (
        '<html><script type="application/ld+json">'
        '{"@type":"NewsArticle","headline":"Hondaが新計画を発表",'
        '"datePublished":"2099-01-02T10:00:00+09:00",'
        '"description":"Hondaは新計画の投資額と開始時期を公表した。対象地域、設備、'
        '量産工程、提携先の役割も示し、来年度から段階的に実行すると説明した。"}'
        "</script></html>"
    )
    structured = structured_article_text(structured_fixture)
    if not structured or "投資額" not in structured[1]:
        fail("structured article metadata was not extracted")
    if "2099-01-02T10:00:00" in structured[1]:
        fail("structured publication metadata leaked into article facts")
    cross_domain_title = "A国首相とB国首相、経済安全保障分野での連携を強化"
    probe_terms = event_probe_terms(cross_domain_title)
    if "強化" in probe_terms or not {"a国首相", "b国首相"} <= set(probe_terms):
        fail("event probe did not preserve actors while removing generic actions")
    if article_candidate_score(
        cross_domain_title,
        "B国首相とA国首相が会談し、重要鉱物と半導体の協力を確認",
    ) <= article_candidate_score(
        cross_domain_title,
        "A国首相とB国首相が互いを愛称で呼んだ",
    ):
        fail("event enrichment preferred a side detail over the material event")
    cross_domain_category = {
        "label": "Test",
        "watch_topics": [
            {
                "id": "policy_change",
                "terms": ["政策", "安全保障"],
                "event_classes": ["decision_or_policy"],
            }
        ],
    }
    cross_domain_record = {
        "label": "Example News",
        "url": "https://example.com/cross-domain-event",
        "source_role": "independent_media_or_data",
        "channel": "web",
        "source_class": "discovered_media",
        "observed": True,
        "published_date": "2099-01-02",
        "title": cross_domain_title,
        "excerpt": (
            "両国は半導体、重要鉱物、通信基盤を優先分野とした。"
            "共同事業の工程と担当機関も公表した。"
        ),
    }
    if not publication_evidence_record(
        cross_domain_category,
        "2099-01-03",
        cross_domain_record,
    ):
        fail("a body-rich material event was lost because its action wording differed")
    headline_only_cross_domain = {
        **cross_domain_record,
        "excerpt": f"{cross_domain_title} Example News",
    }
    if enrichment_target_urls(
        cross_domain_category,
        "2099-01-03",
        [headline_only_cross_domain],
    ) != {headline_only_cross_domain["url"]}:
        fail("a material headline was not routed to evidence enrichment")
    if not article_result_matches(
        "OpenAI GPT-5.6シリーズを発表",
        "OpenAIのGPT-5.6シリーズを解説",
    ):
        fail("matching publisher article was not recognized")
    if article_result_matches(
        "OpenAI GPT-5.6シリーズを発表",
        "宇都宮ブレックスが新アリーナ計画を発表",
    ):
        fail("unrelated publisher article passed title matching")
    unreadable_source_url = "https://www.example.com/item"
    cleaned_unreadable_source = clean_sources(
        [{"url": unreadable_source_url, "label": "—"}],
        {
            unreadable_source_url: {
                "label": "—",
                "url": unreadable_source_url,
                "observed": True,
            }
        },
    )
    if cleaned_unreadable_source[0]["label"] != "example.com":
        fail("unreadable source label did not fall back to its hostname")
    music_category = {
        "label": "YOASOBI / 幾田りら",
        "watch_topics": [
            {
                "id": "music_release_chart_tieup",
                "terms": ["YOASOBI", "幾田りら", "チャート"],
                "event_classes": ["cultural_or_audience_signal"],
            }
        ],
    }
    navigation_record = {
        "label": "Music chart index",
        "url": "https://example.com/charts/",
        "source_role": "independent_media_or_data",
        "channel": "web",
        "source_class": "specialist_media",
        "observed": True,
        "published_date": "2099-01-02",
        "title": "Music CHARTS",
        "excerpt": (
            "このページをスキップ 閉じる CHART INSIGHT MUSIC CHARTS "
            "GLOBAL BOOKS JAPAN WORLD NEWS SHOPPING CART もっと見る。"
            "YOASOBIや幾田りらに関する新曲やチャート変動の具体的事実は"
            "本文に記載されていない。"
        ),
    }
    if publication_evidence_record(music_category, "2099-01-03", navigation_record):
        fail("navigation index was treated as publication Evidence")
    if category_prompt(music_category, "2099-01-03", [navigation_record])["evidence"]:
        fail("navigation index reached the Editor prompt")
    no_update_record = {
        **navigation_record,
        "url": "https://example.com/music-daily",
        "title": "音楽チャートの6月30日更新",
        "excerpt": (
            "YOASOBIや幾田りらに関する新曲やチャート変動の具体的事実は"
            "本文に記載されていない。"
        ),
    }
    if publication_evidence_record(music_category, "2099-01-03", no_update_record):
        fail("a no-update statement was treated as an important update")
    undated_record = {
        **navigation_record,
        "url": "https://example.com/yoasobi-release",
        "published_date": None,
        "title": "YOASOBIが新曲を公開",
        "excerpt": "YOASOBIが新曲を公開し、配信を開始した。",
    }
    if publication_evidence_record(music_category, "2099-01-03", undated_record):
        fail("an undated source was allowed to invent the issue date")
    english_record = {
        **navigation_record,
        "url": "https://example.com/openai-release",
        "published_date": "2099-01-02",
        "title": "OpenAI launches a new security model",
        "excerpt": (
            "OpenAI announced the model on January 2. The release adds automated "
            "vulnerability triage for enterprise customers."
        ),
    }
    openai_category = {
        "label": "OpenAI",
        "watch_topics": [
            {
                "id": "product_release",
                "terms": ["OpenAI", "security model"],
                "event_classes": ["technical_or_product_shift"],
            }
        ],
    }
    if not publication_evidence_record(openai_category, "2099-01-03", english_record):
        fail("English primary Evidence was filtered before translation")
    if not fact_supported_by_records(
        "OpenAIは企業向けに脆弱性の自動分類機能を追加した。",
        [english_record],
    ):
        fail("translated fact lost its English Evidence support")
    if fact_supported_by_records(
        "OpenAIは999社へ脆弱性の自動分類機能を提供した。",
        [english_record],
    ):
        fail("translated fact invented a number absent from English Evidence")
    _, parsed_body = page_text(
        (
            "<html><head><title>Example</title></head><body>"
            "<nav>HOME MENU NEWS SHOPPING CART</nav>"
            "<article>YOASOBIが新曲を6月30日に発売した。</article>"
            "</body></html>"
        ).encode(),
        "text/html; charset=utf-8",
    )
    if "SHOPPING CART" in parsed_body or "新曲を6月30日に発売" not in parsed_body:
        fail("HTML extraction did not separate navigation from article text")
    if event_limits_sentence("選手の新規契約", "選手の新規契約を発表した。"):
        fail("fallback invented an uncertainty absent from Evidence")
    explicit_limit = event_limits_sentence(
        "選手の新規契約",
        "選手の新規契約を発表した。契約期間は未公表である。",
    )
    if "契約期間は未公表" not in explicit_limit:
        fail("source-stated uncertainty was not retained")
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
            "title": "OpenAIが開発者向け機能を更新",
            "excerpt": (
                "OpenAIは開発者向け機能を更新し、対象機能と提供条件を公表した。"
                "既存サービスからの移行手順と利用開始日も示した。"
            ),
            "evidence": "verified",
        }
    ]
    raw = {
        "items": [
            {
                "watch_topic_id": "topic",
                "title": "OpenAIが開発者向け機能を更新",
                "source_published_date": "2099-01-02",
                "topic_value_class": "decision_or_policy",
                "priority_class": "priority",
                "confirmed_facts": [
                    "公式資料で開発者向け機能の更新が公表された。",
                    "対象となる機能と提供条件が明示された。",
                    "更新に伴い既存サービスの移行手順も示された。",
                ],
                "sources": [{"url": "https://example.com/item"}],
            }
        ]
    }
    normalized = normalize_result(raw, category, "2099-01-03", records)
    if len(normalized["items"]) != 1:
        fail("normalization self-test lost a valid item")
    normalized_item = normalized["items"][0]
    if any(
        key in normalized_item
        for key in ("summary", "detail_summary")
    ):
        fail("normalization retained redundant derived prose fields")
    wrong_date_raw = json.loads(json.dumps(raw))
    wrong_date_raw["items"][0]["source_published_date"] = "2099-01-03"
    if normalize_result(wrong_date_raw, category, "2099-01-03", records)["items"]:
        fail("normalization accepted a source date absent from Evidence")
    raw["items"][0]["sources"] = [{"url": "https://unverified.example/"}]
    if normalize_result(raw, category, "2099-01-03", records)["items"]:
        fail("normalization accepted an unverified source")
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
    fallback_item = fallback_item_from_record(
        {
            "label": "OpenAI",
            "watch_topics": [
                {
                    "id": "openai_security",
                    "terms": ["OpenAI", "Codex", "security"],
                    "event_classes": ["technical_or_product_shift"],
                }
            ],
        },
        "2099-01-03",
        {
            "label": "Technology News",
            "url": "https://example.com/openai-security",
            "source_role": "independent_media_or_data",
            "channel": "web",
            "source_class": "discovered_media",
            "observed": True,
            "published_date": "2099-01-02",
            "title": (
                "OpenAIがセキュリティー特化AIとCodex Securityの"
                "アップデートを発表"
            ),
            "excerpt": (
                "Codex Securityでは脆弱性検出後の修正支援が更新された。"
                "企業向け提供の対象範囲と利用条件は今後具体化される。"
            ),
        },
    )
    if fallback_item is None:
        fail("evidence fallback did not create a supported material item")
    if any(key in fallback_item for key in ("summary", "detail_summary")):
        fail("evidence fallback created a second prose representation")
    if not fallback_item["confirmed_facts"]:
        fail("evidence fallback lost its factual core")
    cleaned_model_title = reader_facing_text(
        "OpenAIがGPT-5.5-Cyberを更新 - MSN"
    )
    if "GPT-5.5-Cyber" not in cleaned_model_title or "MSN" in cleaned_model_title:
        fail("public cleanup confused a model version with a publisher domain")
    cleaned_yahoo_title = record_public_title(
        {
            "title": (
                "YOASOBIが『THE BOOK for,』を発売（音楽ナタリー）"
                " - Yahoo!ニュース"
            ),
            "label": "Yahoo!ニュース",
        }
    )
    if "Yahoo" in cleaned_yahoo_title or "音楽ナタリー" in cleaned_yahoo_title:
        fail("record title cleanup kept publisher credits")
    if not same_material_event(
        "ソフトバンクG株がOpenAIのIPO延期報道で急落",
        "OpenAIがIPOを延期、ソフトバンク株は反落",
    ):
        fail("semantic clustering missed a duplicate material event")
    if same_material_event(
        "ソフトバンクG株がOpenAIのIPO延期報道で急落",
        "ソフトバンクがフィジカルAIロボットの量産を開始",
    ):
        fail("semantic clustering merged distinct material events")
    merged_investment = merge_related_items(
        [
            {
                "watch_topic_id": "ai_infrastructure",
                "title": "ソフトバンクG、OpenAIに1兆6273億円を10月に追加出資",
                "source_published_date": "2099-01-02",
                "confirmed_facts": ["ソフトバンクGはOpenAIへの追加出資を10月に予定する。"],
                "sources": [{"url": "https://example.com/plan"}],
            },
            {
                "watch_topic_id": "ai_infrastructure",
                "title": "ソフトバンクG、OpenAIに1.6兆円を払い込み",
                "source_published_date": "2099-01-02",
                "confirmed_facts": ["ソフトバンクGはOpenAIに1.6兆円を払い込んだ。"],
                "sources": [{"url": "https://example.com/payment"}],
            },
        ]
    )
    if len(merged_investment) != 1 or len(merged_investment[0]["sources"]) != 2:
        fail("related publication items were not merged before card rendering")
    merged_investment_facts = " ".join(merged_investment[0]["confirmed_facts"])
    if "予定" not in merged_investment_facts or "払い込んだ" not in merged_investment_facts:
        fail("event deduplication discarded plan-to-execution progression")
    if not low_signal_value("Hondaの夏休み体験授業でF1を特別展示"):
        fail("routine promotional events must not become important updates")
    promoted_fallback: dict[str, Any] = {"items": []}
    duplicate_record = {
        "label": "Technology News",
        "url": "https://example.com/openai-codex",
        "source_role": "independent_media_or_data",
        "channel": "web",
        "source_class": "discovered_media",
        "observed": True,
        "published_date": "2099-01-02",
        "title": "OpenAIがCodex Securityのアップグレードを公開",
        "excerpt": "OpenAIがCodex Securityのアップグレードを公開。",
    }
    openai_category = {
        "label": "OpenAI",
        "watch_topics": [
            {
                "id": "openai_security",
                "terms": ["OpenAI", "Codex", "security"],
                "event_classes": ["technical_or_product_shift"],
            }
        ],
    }
    if publication_evidence_record(openai_category, "2099-01-03", duplicate_record):
        fail("headline-only record was accepted as publication Evidence")
    body_rich_record = {
        **duplicate_record,
        "excerpt": (
            "Codex Securityでは脆弱性検出後の修正支援が更新された。"
            "企業向け提供の対象範囲も拡大された。"
        ),
    }
    if not publication_evidence_record(openai_category, "2099-01-03", body_rich_record):
        fail("body-rich record was rejected as publication Evidence")
    honda_category = {
        "label": "Honda",
        "watch_topics": [
            {
                "id": "production_sales",
                "terms": ["Honda", "生産", "販売"],
                "event_classes": ["operational_status_change"],
            }
        ],
    }
    evidence_counterexamples = [
        (
            "short-official-release",
            True,
            "Hondaが5月の生産・販売実績を発表",
            "Hondaの国内販売は5万2,410台で、前年同月比8.2%減だった。",
        ),
        (
            "table-centered-release",
            True,
            "Hondaが5月の世界生産実績を公表",
            "生産実績表では世界生産が27万1,204台、中国生産が前年同月比18.4%減となった。",
        ),
        (
            "headline-only",
            False,
            "Hondaが5月の生産・販売実績を発表",
            "Hondaが5月の生産・販売実績を発表した。",
        ),
        (
            "headline-plus-publisher",
            False,
            "Hondaが5月の生産・販売実績を発表",
            "Hondaが5月の生産・販売実績を発表 Honda公式サイト。",
        ),
        (
            "wrong-category",
            False,
            "三菱自動車が5月の生産実績を発表",
            "三菱自動車の世界生産は前年同月比8.2%減となった。",
        ),
        (
            "background-profile",
            False,
            "Honda 株価履歴と過去データ",
            "Honda designs, manufactures and launches vehicles worldwide. Stock Price and News.",
        ),
    ]
    for name, expected, title, excerpt in evidence_counterexamples:
        record = {
            "label": "Official",
            "url": f"https://example.com/{name}",
            "source_role": "primary_or_official",
            "channel": "web",
            "source_class": "official",
            "observed": True,
            "published_date": "2099-01-02",
            "title": title,
            "excerpt": excerpt,
        }
        if publication_evidence_record(honda_category, "2099-01-03", record) != expected:
            fail(f"Evidence counterexample failed: {name}")
    fpt_headline = "【ベトナム】FPTと米AI教育企業、人材育成で提携"
    fpt_result = (
        "FPT、DataCampと戦略的パートナーシップを締結。"
        "日本企業向けのAI教育と人材変革を共同展開する。"
    )
    if not article_result_matches(fpt_headline, fpt_result):
        fail("article enrichment could not match a body-rich primary source")
    if event_probe_query(fpt_headline) not in article_search_queries({}, fpt_headline):
        fail("article enrichment omitted the bounded event probe query")
    backfill_items_from_evidence(
        promoted_fallback,
        openai_category,
        "2099-01-03",
        [duplicate_record],
    )
    if promoted_fallback["items"]:
        fail("headline-only Evidence leaked beyond the Evidence layer")
    analysis_only: dict[str, Any] = {"items": []}
    backfill_items_from_evidence(
        analysis_only,
        {
            "label": "SoftBank",
            "watch_topics": [
                {
                    "id": "ai_infrastructure",
                    "terms": ["SoftBank", "OpenAI", "AI"],
                    "event_classes": ["market_or_financial_impact"],
                }
            ],
        },
        "2099-01-03",
        [
            {
                "label": "YouTube",
                "url": "https://example.com/softbank-analysis",
                "source_role": "social_or_video_signal",
                "channel": "youtube",
                "source_class": "discovered_media",
                "observed": True,
                "published_date": "2099-01-02",
                "title": (
                    "【日経平均の正体】ソフトバンクG利益5兆円の裏側、"
                    "OpenAI評価益7兆円が映すAIバブルの危険"
                ),
                "excerpt": (
                    "【日経平均の正体】ソフトバンクG利益5兆円の裏側、"
                    "OpenAI評価益7兆円が映すAIバブルの危険"
                ),
            }
        ],
    )
    if analysis_only["items"]:
        fail("headline-only commentary escaped coverage-only storage")
    analysis_item = fallback_item_from_record(
        {
            "label": "SoftBank",
            "watch_topics": [
                {
                    "id": "ai_infrastructure",
                    "terms": ["SoftBank", "OpenAI", "AI", "評価益"],
                    "event_classes": ["market_or_financial_impact"],
                }
            ],
        },
        "2099-01-03",
        {
            "label": "Financial Analysis Video",
            "url": "https://example.com/softbank-analysis-full",
            "source_role": "social_or_video_signal",
            "channel": "youtube",
            "source_class": "discovered_media",
            "observed": True,
            "published_date": "2099-01-02",
            "title": (
                "【日経平均の正体】ソフトバンクG利益5兆円の裏側、"
                "OpenAI評価益7兆円が映すAIバブルの危険"
            ),
            "excerpt": (
                "ソフトバンクグループの2026年3月期純利益は5兆22億円だった。"
                "OpenAIへの出資に係る投資利益は6兆7,304億円で、純利益を上回った。"
                "投資利益は保有株式の公正価値上昇による未実現評価益が中心だった。"
                "動画は、利益が現金収支を直接増やす構造ではなく、"
                "OpenAI評価額への依存度が高いと分析している。"
            ),
        },
    )
    if analysis_item is None:
        fail("body-rich analysis did not become an evidence-backed item")
    if not publication_item_supported(
        analysis_item["title"],
        *analysis_item["confirmed_facts"],
    ):
        fail("body-rich analysis did not pass publication support checks")
    analysis_copy = " ".join(
        [
            analysis_item["what_changed"],
            analysis_item["why_it_matters"],
            *analysis_item["confirmed_facts"],
        ]
    )
    if not all(term in analysis_copy for term in ("今回の検証", "未実現評価益", "現金収支", "依存度")):
        fail("analysis summary lost its question, evidence, or conclusion")
    japan_item = fallback_item_from_record(
        {
            "label": "日本経済",
            "watch_topics": [
                {
                    "id": "trade_economic_relations",
                    "terms": ["日本経済界", "訪中", "視察団", "経済交流"],
                    "event_classes": ["decision_or_policy"],
                }
            ],
        },
        "2099-01-03",
        {
            "label": "Regional News",
            "url": "https://example.com/japan-china-delegations",
            "source_role": "independent_media_or_data",
            "channel": "web",
            "source_class": "discovered_media",
            "observed": True,
            "published_date": "2099-01-02",
            "title": "日本経済界は「改善希望」 中国、視察団の訪中巡り",
            "excerpt": (
                "中国外務省の副報道局長は2日の記者会見で、日本から複数の視察団が"
                "訪れたことは中日関係の改善を望む表れだと述べた。"
                "博覧会は北京で1日から3日まで開かれた。"
                "日本商工会議所、関西経済連合会、大阪商工会議所の幹部が訪問した。"
            ),
        },
    )
    if japan_item is None:
        fail("body-rich reference did not become an information-complete item")
    japan_copy = " ".join(japan_item["confirmed_facts"])
    if not all(term in japan_copy for term in ("副報道局長", "1日から3日", "日本商工会議所")):
        fail("body-rich reference lost concrete names, dates, or participants")
    if any(state_contract.material_fact_violations(fact) for fact in japan_item["confirmed_facts"]):
        fail("body-rich reference created non-material confirmed facts")
    stale_pdf_record = {
        "published_date": "2099-07-02",
        "title": "日銀短観（6月調査）の結果を公表",
        "url": "https://example.com/2098/12/old-report.pdf",
        "excerpt": (
            "Title: 日銀短観（2098年12月調査）結果 URL Source: https://example.com "
            "Published Time: Mon, 15 Dec 2098 08:06:30 GMT Number of Pages: 5 "
            "Markdown Content: お問い合わせ 調査部 E-mail: report@example.com TEL: 03-0000-0000"
        ),
    }
    if record_document_is_current(stale_pdf_record, "2099-07-02"):
        fail("stale embedded document date passed current Evidence validation")
    if document_matches_discovery(
        stale_pdf_record,
        stale_pdf_record["url"],
        "日銀短観（2098年12月調査）結果",
        stale_pdf_record["excerpt"],
    ):
        fail("mismatched report month passed discovered-page validation")
    fresh_pdf_record = {
        **stale_pdf_record,
        "published_date": "2099-07-02",
        "title": "日銀短観（6月調査）の結果を公表",
        "url": "https://example.com/2099/07/current-report.pdf",
        "excerpt": "2099年7月2日 経済レポート 日銀短観（6月調査）の結果を公表した。",
    }
    if not record_document_is_current(fresh_pdf_record, "2099-07-02"):
        fail("current report was rejected by document-date validation")
    print("NIGHT SIGNAL CORE SELF-TEST PASSED")
