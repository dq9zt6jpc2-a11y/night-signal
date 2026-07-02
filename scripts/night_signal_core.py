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
import time
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
DEFAULT_MODEL_MAX_TOKENS = 8000
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
    r"(発表|決定|合意|契約|提携|買収|統合|開始|提供開始|発売|公開|更新|"
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


def fail(message: str) -> None:
    print(f"NIGHT SIGNAL CORE FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


class ModelRequestError(RuntimeError):
    def __init__(
        self,
        message: str,
        *,
        rate_limited: bool = False,
        retry_after: int | None = None,
    ) -> None:
        super().__init__(message)
        self.rate_limited = rate_limited
        self.retry_after = retry_after


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


def useful_importance(value: str) -> bool:
    text = reader_facing_text(value, 700)
    return bool(text) and not GENERIC_IMPORTANCE_RE.search(text)


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
    return bool(PUBLICATION_EVENT_RE.search(f"{title} {evidence}"))


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


def source_material_facts(
    title: str,
    records: list[dict[str, Any]],
    *,
    limit: int | None = None,
) -> list[str]:
    candidates: list[str] = []
    for record in records:
        excerpt = str(record.get("excerpt") or "")
        for sentence in sentence_parts(excerpt):
            if len(re.findall(r"[\u3040-\u30ff\u3400-\u9fff]", sentence)) < 8:
                continue
            if state_contract.title_repetition_score(title, sentence) >= 0.95:
                continue
            if useful_fact(sentence, ""):
                candidates.append(sentence)
    return state_contract.normalize_material_facts(title, candidates, limit=limit)


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
    if (
        len(existing) >= 280
        and not SUMMARY_LABEL_RE.search(existing)
        and not state_contract.GENERIC_CONTEXT_RE.search(existing)
        and ("今回の検証" not in what_changed or "今回の検証" in existing)
    ):
        return existing

    lead = reader_facing_text(what_changed or summary or existing, 700)
    if lead and not lead.endswith("。"):
        lead = f"{lead}。"

    lead_key = sentence_key(lead)
    existing_context = ""
    if (
        existing
        and not SUMMARY_LABEL_RE.search(existing)
        and not state_contract.GENERIC_CONTEXT_RE.search(existing)
    ):
        existing_context = existing
    useful_facts = [
        reader_facing_text(fact, 500)
        for fact in facts
        if useful_fact(fact, category_label)
        and sentence_key(reader_facing_text(fact, 500)) != lead_key
    ]
    importance_sentence = ""
    if (
        useful_importance(why_it_matters)
        and not state_contract.GENERIC_CONTEXT_RE.search(why_it_matters)
    ):
        importance = reader_facing_text(why_it_matters, 700).rstrip("。")
        importance_sentence = f"{importance}。"

    limits_sentence = ""
    limits = reader_facing_text(limits_or_unknowns, 700)
    if limits:
        limits_sentence = limits if limits.endswith("。") else f"{limits}。"

    composed = unique_sentences(
        " ".join(
            part
            for part in (
                lead,
                existing_context,
                *useful_facts,
                importance_sentence,
                limits_sentence,
            )
            if part
        ),
        2600,
    )
    return composed or existing


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


def without_uncertainty_sentences(value: str) -> str:
    return unique_sentences(
        " ".join(
            sentence
            for sentence in sentence_parts(value)
            if not UNCERTAINTY_RE.search(sentence)
        ),
        1200,
    )


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
    for axis in category.get("axes", []):
        if isinstance(axis, dict):
            configured_terms.extend(str(term) for term in axis.get("terms", []))
    for topic in category.get("watch_topics", []):
        if not isinstance(topic, dict):
            continue
        configured_terms.extend(str(term) for term in topic.get("terms", []))
        configured_terms.extend(str(event) for event in topic.get("event_classes", []))
    scoped = list(dict.fromkeys(configured_terms))
    groups = [scoped[index : index + 8] for index in range(0, len(scoped), 8)][:4]
    groups.extend([material_terms[:6], material_terms[6:]])
    return [
        f"({label}) ({' OR '.join(group)}) when:3d"
        for group in groups
        if group
    ]


def news_query(category: dict[str, Any], issue_date: str) -> str:
    return news_queries(category, issue_date)[0]


def article_result_matches(original_title: str, result_title: str) -> bool:
    return (
        state_contract.title_repetition_score(original_title, result_title) >= 0.45
        or state_contract.text_overlap(original_title, result_title) >= 2
    )


def normalized_ocr_digits(value: str) -> str:
    return re.sub(r"(?<=\d)\s+(?=\d)", "", str(value))


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
    return list(dict.fromkeys(queries))


def enrich_discovered_record(
    category: dict[str, Any],
    record: dict[str, Any],
) -> dict[str, Any]:
    original_title = record_public_title(record)
    if not original_title:
        return record
    category_label = str(category.get("label", ""))
    seen_candidates: set[str] = set()
    candidate_attempts = 0
    for query in article_search_queries(record, original_title):
        search_url = "https://www.bing.com/search?" + urllib.parse.urlencode(
            {"format": "rss", "q": query}
        )
        try:
            raw, _, _ = request_bytes(search_url, timeout=12)
            root = ET.fromstring(raw)
        except (OSError, TimeoutError, urllib.error.URLError, ET.ParseError):
            continue
        for item in root.findall(".//item")[:5]:
            result_title = compact_text(item.findtext("title") or "", 220)
            candidate_url = compact_text(item.findtext("link") or "", 1000)
            description = html_fragment_text(item.findtext("description") or "", 1000)
            if (
                candidate_url in seen_candidates
                or not candidate_url.startswith(("http://", "https://"))
                or "news.google.com" in candidate_url
                or not article_result_matches(original_title, result_title)
                or not category_identity_ok(
                    category_label,
                    result_title,
                    description,
                )
            ):
                continue
            seen_candidates.add(candidate_url)
            candidate_attempts += 1
            for attempt in (candidate_url, jina_url(candidate_url)):
                try:
                    page_raw, content_type, _ = request_bytes(attempt, timeout=12)
                    page_title, body = page_text(page_raw, content_type)
                except (OSError, TimeoutError, urllib.error.URLError, ValueError):
                    continue
                combined = compact_text(f"{description} {body}", 2400)
                if (
                    len(combined) < 180
                    or not category_identity_ok(category_label, original_title, combined)
                    or not article_result_matches(
                        original_title,
                        page_title or result_title,
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
                publisher_url = (
                    f"{parsed.scheme}://{parsed.netloc}"
                    if parsed.scheme in {"http", "https"} and parsed.netloc
                    else str(record.get("publisher_url", ""))
                )
                return {
                    **record,
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
            if candidate_attempts >= 3:
                return record
    return record


def enrich_discovered_records(
    category: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    limit = 6
    ranked = sorted(
        records,
        key=lambda record: cluster_priority(record, category),
        reverse=True,
    )
    target_urls: list[str] = []
    for record in ranked:
        url = str(record.get("url", ""))
        if (
            url
            and url not in target_urls
            and contains_material_signal(
                str(record.get("title", "")),
                str(record.get("excerpt", "")),
            )
        ):
            target_urls.append(url)
        if len(target_urls) >= limit:
            break
    targets = set(target_urls)
    return [
        enrich_discovered_record(category, record)
        if str(record.get("url", "")) in targets
        else record
        for record in records
    ]


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
    return enrich_discovered_records(category, records) if records else failures


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


def model_request(
    token: str,
    messages: list[dict[str, str]],
    *,
    model_name: str | None = None,
    retry_wait_cap: int = 120,
    request_label: str = "",
) -> dict[str, Any]:
    errors: list[str] = []
    rate_limit_waits: list[int] = []
    attempt_messages = list(messages)
    timeout = int(os.getenv("NIGHT_SIGNAL_MODEL_TIMEOUT_SECONDS", DEFAULT_MODEL_TIMEOUT_SECONDS))
    retries = int(os.getenv("NIGHT_SIGNAL_MODEL_RETRIES", DEFAULT_MODEL_RETRIES))
    max_tokens = int(os.getenv("NIGHT_SIGNAL_MODEL_MAX_TOKENS", DEFAULT_MODEL_MAX_TOKENS))
    for attempt in range(retries):
        payload = {
            "model": model_name or models.extraction_model(),
            "messages": attempt_messages,
            "temperature": 0.1,
            "max_tokens": max_tokens,
            "response_format": {"type": "json_object"},
        }
        request = urllib.request.Request(
            MODELS_URL,
            data=json.dumps(payload, separators=(",", ":")).encode("utf-8"),
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
            usage = value.get("usage", {})
            if isinstance(usage, dict):
                print(
                    json.dumps(
                        {
                            "phase": "model_usage",
                            **({"category": request_label} if request_label else {}),
                            "model": payload["model"],
                            "prompt_tokens": usage.get("prompt_tokens"),
                            "completion_tokens": usage.get("completion_tokens"),
                            "total_tokens": usage.get("total_tokens"),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
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
                                    "budget. Return compact valid JSON while "
                                    "retaining every distinct item, date, fact, "
                                    "and URL. Shorten prose without reducing the "
                                    "item count."
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
                raise ModelRequestError(
                    f"GitHub Models request failed with HTTP {exc.code}"
                ) from exc
            retry_after = exc.headers.get("Retry-After")
            try:
                requested_wait = max(1, int(retry_after or "65"))
            except ValueError:
                requested_wait = 65
            wait_seconds = min(retry_wait_cap, requested_wait)
            rate_limit_waits.append(requested_wait)
            errors.append(
                f"attempt {attempt + 1}: HTTP {exc.code}; "
                f"retry_after={requested_wait}"
            )
            if requested_wait > retry_wait_cap:
                raise ModelRequestError(
                    "GitHub Models rate limit exceeds the bounded retry window: "
                    + " / ".join(errors),
                    rate_limited=True,
                    retry_after=requested_wait,
                ) from exc
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
    raise ModelRequestError(
        "GitHub Models request failed: " + " / ".join(errors),
        rate_limited=bool(rate_limit_waits),
        retry_after=max(rate_limit_waits, default=None),
    )


SYSTEM_PROMPT = """You are the unattended NIGHT SIGNAL evidence extractor.

Return one JSON object with the key items.
Use only the supplied evidence records and exact URLs. Do not use memory.
The issue window is the issue date and preceding two calendar days.
Return every distinct evidence-backed material cluster as an item. Do not drop
a supported important update to make the list shorter.

items are publication-worthy confirmed changes. Retain names, exact dates,
numbers, results, uncertainty, and context. Each item must contain:
watch_topic_id, title, summary, source_published_date, topic_value_class,
priority_class, slug, what_changed, optional why_it_matters,
confirmed_facts, limits_or_unknowns, sources.
Each source needs label and an exact supplied URL. Write clear Japanese. Let
summary depth follows the available evidence: keep thin sources
concise and preserve names, dates, numbers, conditions, and context from rich
sources.
Include every distinct confirmed fact that materially helps a reader understand
the update, and only sources that support those facts. Use available source
substance; never pad a thin source with generic prose.

Every confirmed_fact must be a distinct event fact stated in the supplied
title or body excerpt. Publisher names, publication dates, source metadata,
importance analysis, generic impact language, and remaining unknowns are not
confirmed facts. At least one confirmed fact must add concrete information
beyond merely repeating the title. Use the full body excerpt when it contains names, dates,
amounts, decisions, results, or conditions. If the evidence does not support
at least one concrete fact, omit it from items and leave it in Evidence; never
create a public or intermediate summary by padding it.
An analysis, explainer, opinion, or video commentary is not a new event merely
because its publication date is recent or its title contains a large number.
It may become an item only when the supplied body provides concrete supporting
facts and a clear analytical conclusion. For such an item,
what_changed must state what the article or video examines, why_it_matters must
state the conclusion reached, and summary must contain both the
question examined and the evidence-backed analysis. Otherwise omit it. Keep
分析, 検証, or 解説 in the public title so it cannot be mistaken
for a newly announced underlying event.

Unknown important changes may use the closest supplied watch_topic_id. Do not
silently drop potentially important recent evidence. Routine background older
than the window must not be returned. If evidence is insufficient, return an
empty items array. Never invent a date, number, source, or certainty. Public
fields must explain the event itself and must not
mention research, collection, monitoring, selection, or publication procedure.
Do not use labels such as 変更点, 重要性, 確認事実, or 未確定点, and do not say
that an item is kept in the list or monitored broadly. Include concrete facts
without repetition. Use why_it_matters only for a source-backed analytical
conclusion; otherwise omit it or return an empty string.
limits_or_unknowns must be empty unless a
supplied source explicitly states the uncertainty; never infer a generic unknown."""

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
) -> dict[str, Any] | None:
    source_date = str(signal["source_published_date"])
    source_label = str(record.get("label") or signal.get("source_label") or record.get("url"))
    source_url = str(record.get("url") or signal.get("source_url"))
    excerpt = reader_facing_text(record.get("excerpt") or record.get("evidence") or "", 900)
    summary = unique_sentences(signal_summary, 900)
    summary_sentences = sentence_parts(summary)
    what_changed = summary_sentences[0] if summary_sentences else summary
    why_it_matters = unique_sentences(" ".join(summary_sentences[1:]), 700)
    fact_values = [title, excerpt]
    facts = (
        state_contract.normalize_analysis_facts(title, fact_values)
        if state_contract.analysis_headline(title)
        else state_contract.normalize_material_facts(title, fact_values)
    )
    if not facts_add_information_beyond_title(title, facts):
        return None
    analysis = analysis_narrative(title, facts)
    if analysis is not None:
        what_changed, why_it_matters, summary = analysis
    else:
        why_it_matters = ""
        summary = unique_sentences(" ".join(facts), None)
        what_changed = facts[0]
    limits = event_limits_sentence(title, excerpt)
    detail = natural_detail_summary(
        summary=summary,
        detail="",
        what_changed=what_changed,
        why_it_matters=why_it_matters,
        facts=facts,
        limits_or_unknowns=limits,
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
        "confirmed_facts": facts,
        "limits_or_unknowns": limits,
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


def evidence_narrative(
    *,
    category_label: str,
    title: str,
    excerpt: str,
    topic_value: str,
) -> tuple[str, str, str, list[str]]:
    title_sentences = sentence_parts(title)
    event = title_sentences[0] if title_sentences else sentence_from_title(title)
    event_key = sentence_key(event)
    supporting: list[str] = []
    for sentence in sentence_parts(excerpt):
        key = sentence_key(sentence)
        if not key or key == event_key or key in {sentence_key(value) for value in supporting}:
            continue
        if state_contract.title_repetition_score(title, sentence) >= 0.95:
            continue
        supporting.append(sentence)
    del category_label, topic_value
    importance = supporting[-1] if supporting else ""
    summary = unique_sentences(" ".join([event, *supporting]), None)
    return event, importance, summary, supporting


def sentence_from_title(title: str) -> str:
    text = reader_facing_text(title, 500).rstrip("。")
    return f"{text}。" if text else ""


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
    what_changed, why_it_matters, summary, supporting = evidence_narrative(
        category_label=category_label,
        title=title,
        excerpt=excerpt,
        topic_value=topic_value,
    )
    if (
        state_contract.reader_summary_violations(title, summary)
        or not reader_public_copy_ok(summary, kind="summary")
    ):
        return None
    fact_values = [what_changed, *supporting, excerpt]
    facts = (
        state_contract.normalize_analysis_facts(title, fact_values)
        if state_contract.analysis_headline(title)
        else state_contract.normalize_material_facts(title, fact_values)
    )
    if not facts_add_information_beyond_title(title, facts):
        return None
    analysis = analysis_narrative(title, facts)
    if analysis is not None:
        what_changed, why_it_matters, summary = analysis
    else:
        why_it_matters = ""
        summary = unique_sentences(" ".join(facts), None)
        what_changed = facts[0]
    limits = event_limits_sentence(title, excerpt)
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
        summary = unique_sentences(" ".join(facts), None)
        merged[match_index] = {
            **primary,
            "summary": summary,
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
            "detail_summary": summary,
        }
    return merged


def fallback_signal_from_record(
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
        or not reader_public_copy_ok(excerpt, kind="summary")
        or not category_identity_ok(category_label, title, excerpt)
        or low_signal_value(title, excerpt)
    ):
        return None
    material = publication_item_supported(title, excerpt)
    topic_value = topic_value_from_record(record)
    _, _, summary, _ = evidence_narrative(
        category_label=category_label,
        title=title,
        excerpt=excerpt,
        topic_value=topic_value,
    )
    if state_contract.reader_summary_violations(title, summary):
        return None
    return {
        "watch_topic_id": topic,
        "title": title,
        "summary": summary,
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
        "topic_value_class": topic_value,
        "observation_source_role": str(record.get("source_role", "independent_media_or_data")),
        "observation_channel": str(record.get("channel", "web")),
    }


def backfill_signals_from_evidence(
    normalized: dict[str, Any],
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> None:
    seen = {
        normalized_topic_key(entry.get("title"))
        for collection in (normalized.get("items", []), normalized.get("signals", []))
        for entry in collection
        if isinstance(entry, dict)
    }
    for record in publication_evidence_records(category, issue_date, records):
        signal = fallback_signal_from_record(category, issue_date, record)
        if not signal:
            continue
        key = normalized_topic_key(signal.get("title"))
        if cluster_seen(seen, key):
            continue
        seen.add(key)
        if signal["change_class"] == "material_update":
            if any(
                same_material_event(signal["title"], item.get("title", ""))
                for item in normalized["items"]
                if isinstance(item, dict)
            ):
                normalized["signals"].append(signal)
                continue
            promoted = promoted_signal_item(
                topic=str(signal["watch_topic_id"]),
                title=str(signal["title"]),
                signal=signal,
                signal_summary=str(signal["summary"]),
                topic_value=str(signal["topic_value_class"]),
                issue_date=issue_date,
                record=record,
            )
            if promoted is not None:
                normalized["items"].append(promoted)
                continue
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
        summary = reader_facing_text(item.get("summary", ""), 1000)
        detail = ""
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
        sources = clean_sources(item.get("sources"), records_by_url)
        source_excerpt = " ".join(
            str(records_by_url.get(source["url"], {}).get("excerpt") or "")
            for source in sources
        )
        limits_or_unknowns = event_limits_sentence("", source_excerpt)
        summary = without_uncertainty_sentences(summary)
        what_changed = unique_sentences(what_changed, 700)
        why_it_matters = without_uncertainty_sentences(why_it_matters)
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
        summary = unique_sentences(" ".join(facts), None)
        analysis = analysis_narrative(title, facts)
        analysis_ready = not state_contract.analysis_headline(title) or analysis is not None
        if analysis is not None:
            what_changed, why_it_matters, summary = analysis
        else:
            why_it_matters = ""
        if state_contract.GENERIC_CONTEXT_RE.search(summary):
            summary = unique_sentences(" ".join(facts), None)
        detail = natural_detail_summary(
            summary=summary,
            detail="",
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
        source_dates = {
            str(source.get("published_date"))
            for source in sources
            if source.get("published_date")
        }
        rejection_checks = [
            ("unknown_topic", topic not in valid_topics),
            ("empty_title", not title),
            ("title_copy", not reader_public_copy_ok(title, kind="title")),
            ("summary_copy", not reader_public_copy_ok(summary, kind="summary")),
            ("detail_copy", not reader_public_copy_ok(detail, kind="summary")),
            ("change_copy", not reader_public_copy_ok(what_changed, kind="summary")),
            (
                "importance_copy",
                bool(why_it_matters)
                and not reader_public_copy_ok(why_it_matters, kind="summary"),
            ),
            (
                "category_identity",
                not category_identity_ok(str(category.get("label", "")), title, summary),
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
                        "summary_length": len(summary),
                        "detail_length": len(detail),
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
                "confirmed_facts": facts,
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
            or str(signal.get("source_published_date", ""))
            != str(record.get("published_date") or "")
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
        material_signal = publication_item_supported(
            title,
            signal_summary,
            str(record.get("excerpt", "")),
        )
        if material_signal and change_class in {"background_only", "duplicate_followup"}:
            change_class = "material_update"
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
            promoted = promoted_signal_item(
                topic=topic,
                title=title,
                signal=signal,
                signal_summary=signal_summary,
                topic_value=topic_value,
                issue_date=issue_date,
                record=record,
            )
        else:
            promoted = None
        if promoted is not None:
            seen_titles.add(title)
            seen_clusters.add(signal_cluster)
            items.append(promoted)
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
    no_change = compact_text(str(raw.get("no_change_summary", "")), 1500)
    if len(no_change) < 20:
        observed_count = sum(bool(record.get("observed")) for record in records)
        no_change = (
            f"{issue_date}に{category['label']}の公式、独立媒体、SNS、"
            f"YouTubeを含む{observed_count}件の証跡を確認した。"
            "直近3日の確定差分は重要更新または確認結果に記録した。"
        )
    return {
        "items": items,
        "signals": signals,
        "no_change_summary": no_change,
    }


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
        fetched = list(executor.map(fetch_source, flat_sources))
        news_lists = list(
            executor.map(
                lambda category: fetch_news(category, issue_date),
                contracts,
            )
        )
    records_by_category: dict[str, list[dict[str, Any]]] = {
        str(category["label"]): [] for category in contracts
    }
    for record in fetched:
        records_by_category[str(record["category"])].append(record)
    for category, news_records in zip(contracts, news_lists):
        label = str(category["label"])
        known_urls = {str(record.get("url")) for record in records_by_category[label]}
        records_by_category[label].extend(
            record
            for record in news_records
            if record.get("observed") and str(record.get("url")) not in known_urls
        )

    checked_at = collection_checked_at(issue_date)
    bundle = evidence_contract.build_evidence_bundle(
        issue_date,
        checked_at,
        records_by_category,
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
        "axes": [],
        "watch_topics": [
            {"id": f"topic-{index}", "terms": [f"term-{index}"], "event_classes": []}
            for index in range(9)
        ],
    }
    if "term-8" not in " ".join(news_queries(wide_category, "2099-01-01")):
        fail("discovery queries dropped later watch topics")
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
                "summary": (
                    "OpenAIが開発者向け機能を更新し、対象となる機能と提供条件を公表した。"
                    "既存サービスとの関係や利用企業への影響を判断する具体的な材料になる。"
                ),
                "source_published_date": "2099-01-02",
                "topic_value_class": "decision_or_policy",
                "priority_class": "priority",
                "detail_summary": (
                    "OpenAIが開発者向け機能を更新し、対象機能と提供条件を公表した。"
                    "公式資料では利用開始日、利用できる開発者、既存サービスとの関係が説明されている。"
                    "今回の変更により、導入企業は開発工程と運用手順の見直しを検討できる。"
                    "対象機能の性能、提供地域、料金への影響はサービス選択を判断する材料になる。"
                    "一方、長期的な運用実績、追加地域への展開時期、契約条件の細部はまだ確定していない。"
                    "今後の公式発表では、導入事例と利用条件の更新内容が焦点になる。"
                    "利用企業は、既存システムとの互換性、移行に必要な工数、運用担当者への影響も比較する必要がある。"
                    "正式な仕様と料金が示されれば、導入時期と対象業務をより具体的に判断できる。"
                ),
                "what_changed": "OpenAIが開発者向け機能を更新し、対象機能と提供条件を公表した。",
                "why_it_matters": (
                    "既存サービスとの関係や利用企業への影響を判断する具体的な材料になる。"
                ),
                "confirmed_facts": [
                    "公式資料で開発者向け機能の更新が公表された。",
                    "対象となる機能と提供条件が明示された。",
                    "更新に伴い既存サービスの移行手順も示された。",
                ],
                "limits_or_unknowns": (
                    "利用企業への長期的な影響と追加条件は今後の確認対象となる。"
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
    wrong_date_raw = json.loads(json.dumps(raw))
    wrong_date_raw["items"][0]["source_published_date"] = "2099-01-03"
    if normalize_result(wrong_date_raw, category, "2099-01-03", records)["items"]:
        fail("normalization accepted a source date absent from Evidence")
    short_raw = json.loads(json.dumps(raw))
    short_raw["items"][0]["summary"] = "OpenAIが開発者向け機能を更新した。"
    short_raw["items"][0]["detail_summary"] = (
        "OpenAIは開発者向け機能の更新対象と提供条件を公表した。"
        "公式資料では既存サービスからの移行手順と利用開始日も示している。"
    )
    short_item = normalize_result(
        short_raw,
        category,
        "2099-01-03",
        records,
    )["items"]
    if (
        len(short_item) != 1
        or len(short_item[0]["summary"]) < 80
        or not all(
            fact in short_item[0]["detail_summary"]
            for fact in short_item[0]["confirmed_facts"]
        )
    ):
        fail(
            "normalization did not expand a fact-rich short model response: "
            + json.dumps(short_item, ensure_ascii=False)
        )
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
                    "調達候補額は最大200億ドルで、複数の金融機関と協議している。"
                    "発行条件の決定前に外部格付けを取得する方針が示された。"
                    "調達資金はStarshipとStarlinkの設備投資に充てる案が検討されている。"
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
                    "SpaceXが最大200億ドルの社債発行を複数の金融機関と協議している。"
                    "発行前に外部格付けを取得し、調達資金をStarshipとStarlinkの"
                    "設備投資へ充てる案が検討されている。"
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
    promoted_facts = promoted["confirmed_facts"]
    if not promoted_facts or len(set(promoted_facts)) != len(promoted_facts):
        fail("material signal promotion did not preserve distinct facts")
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
    if state_contract.reader_summary_violations(
        fallback_item["title"], fallback_item["summary"]
    ):
        fail("evidence fallback created a title-like card summary")
    if state_contract.text_overlap(
        fallback_item["summary"], fallback_item["detail_summary"]
    ) < 2:
        fail("evidence fallback card and detail lost their shared factual core")
    if "確認できた点は" in fallback_item["detail_summary"]:
        fail("evidence fallback created label-heavy detail copy")
    if "判断する材料" in fallback_item["summary"]:
        fail("evidence fallback added unsupported importance prose")
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
    if not low_signal_value("Hondaの夏休み体験授業でF1を特別展示"):
        fail("routine promotional events must not become important updates")
    promoted_fallback: dict[str, Any] = {"items": [], "signals": []}
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
    backfill_signals_from_evidence(
        promoted_fallback,
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
        [duplicate_record],
    )
    if promoted_fallback["items"] or promoted_fallback["signals"]:
        fail("headline-only Evidence leaked beyond the Evidence layer")
    analysis_only: dict[str, Any] = {"items": [], "signals": []}
    backfill_signals_from_evidence(
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
    if analysis_only["items"] or analysis_only["signals"]:
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
            analysis_item["summary"],
            analysis_item["detail_summary"],
            analysis_item["what_changed"],
            analysis_item["why_it_matters"],
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
    japan_copy = " ".join(
        [japan_item["summary"], japan_item["detail_summary"], *japan_item["confirmed_facts"]]
    )
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
