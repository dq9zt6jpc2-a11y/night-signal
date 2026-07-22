#!/usr/bin/env python3
"""Shared source and editorial primitives for the NIGHT SIGNAL pipeline."""

from __future__ import annotations

import concurrent.futures
import email.utils
import functools
import gzip
import hashlib
import html
import json
import os
import re
import sys
import threading
import unicodedata
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
PUBLISHER_PORTFOLIO = ROOT / "config" / "night_signal_publisher_portfolio.json"
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
ENGLISH_NUMBER_WORD_VALUES = {
    "zero": 0,
    "one": 1,
    "two": 2,
    "three": 3,
    "four": 4,
    "five": 5,
    "six": 6,
    "seven": 7,
    "eight": 8,
    "nine": 9,
    "ten": 10,
    "eleven": 11,
    "twelve": 12,
    "thirteen": 13,
    "fourteen": 14,
    "fifteen": 15,
    "sixteen": 16,
    "seventeen": 17,
    "eighteen": 18,
    "nineteen": 19,
    "twenty": 20,
    "first": 1,
    "second": 2,
    "third": 3,
    "fourth": 4,
    "fifth": 5,
    "sixth": 6,
    "seventh": 7,
    "eighth": 8,
    "ninth": 9,
    "tenth": 10,
    "eleventh": 11,
    "twelfth": 12,
    "thirteenth": 13,
    "fourteenth": 14,
    "fifteenth": 15,
    "sixteenth": 16,
    "seventeenth": 17,
    "eighteenth": 18,
    "nineteenth": 19,
    "twentieth": 20,
}
ENGLISH_MONTH_VALUES = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
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
    r"アップグレード|資金流入|景気|物価|賃金|雇用|輸出|輸入|GDP|金利|"
    r"launch result|打ち上げ結果|docking|ドッキング|"
    r"policy|regulation|規制|安全|recall|リコール"
    r")",
    re.I,
)
SPORTS_RESULT_RE = re.compile(
    r"試合(?:速報|結果)|対戦結果|\d+回戦|スコア速報",
    re.I,
)
SPORTS_SCHEDULE_RE = re.compile(
    r"\b(?:schedule|timetable)\b|スケジュール|開催日程|試合日程",
    re.I,
)
SPORTS_SCHEDULE_CHANGE_RE = re.compile(
    r"変更|延期|中止|前倒し|追加|会場移転|"
    r"reschedul|postpon|cancel|moved|revised|added",
    re.I,
)
SPORTS_SCHEDULE_TIME_RE = re.compile(r"(?<!\d)\d{1,2}:\d{2}(?!\d)")
PUBLICATION_EVENT_RE = re.compile(
    r"(発表|公表|決定|合意|契約|提携|買収|統合|開始|提供開始|発売|公開|更新|"
    r"就任|退任|移籍|獲得|退団|採用|建設|着工|延期|中止|承認|規制|"
    r"会談|協議|出資|資金調達|上場|申請|"
    r"上昇|下落|急落|増加|減少|改善|悪化|達成|突破|判明|結果|決算|"
    r"CPI|GDP|失業率|雇用統計|利益|売上|"
    r"\b(?:announc|agree|sign|launch|release|update|acqui|merge|appoint|"
    r"resign|join|leave|delay|cancel|approve|invest|raise|filed|"
    r"rose|fell|increase|decrease)[A-Za-z]*\b)",
    re.I,
)
REALIZED_MATERIAL_CHANGE_RE = re.compile(
    r"(発表|公表|決定|合意|契約|提携|買収|統合|開始|提供開始|発売|公開|更新|強化|拡大|"
    r"就任|退任|移籍|獲得|退団|採用|着工|延期|中止|承認|規制|出資|資金調達|"
    r"上場|申請|成立|提訴|訴訟|結果|決算|着地|達成|突破|上方修正|下方修正|"
    r"過去最高|過去最低|最高値|最低値|急増|急減|急騰|急落|"
    r"予想(?:を|より)(?:上回|下回)|"
    r"\b(?:announc|decid|agree|sign|acquir|merge|launch|release|update|expand|strengthen|"
    r"appoint|resign|hire|delay|cancel|approve|invest|raise|filed|sues?|lawsuit|"
    r"record high|record low|"
    r"beat expectations|missed expectations)[A-Za-z]*\b)",
    re.I,
)
ROUTINE_INVESTMENT_COMMENTARY_RE = re.compile(
    r"(株価評価|株価予想|株価見通し|テクニカル(?:分析|動向)|"
    r"買い時|売り時|投資妙味|投資家にとって(?:好機|魅力)|"
    r"目標株価|投資判断|チャート分析|MACD|RSI|"
    r"\b(?:technical analysis|price target|buy rating|sell rating|"
    r"buying opportunity|stock outlook|stock rating|valuation shifts?|price attractiveness|"
    r"time to sell|stock investors?|investment will be worth)\b)",
    re.I,
)
ROUTINE_PREVIEW_RE = re.compile(
    r"(決算発表(?:を)?控え|発表を控え|開催を控え|今後の注目点|何に注目|に注目|"
    r"プレビュー|見どころ|近く発表予定|まもなく発表|"
    r"\b(?:ahead of earnings|earnings preview|event preview|what to expect|"
    r"set to report earnings)\b)",
    re.I,
)
ROUTINE_MINOR_EVENT_RE = re.compile(
    r"(ワークショップ|勉強会|セミナー|交流会|説明会を開催|"
    r"\b(?:workshop|seminar|meetup)\b)",
    re.I,
)
ROUTINE_PERIODIC_UPDATE_RE = re.compile(
    r"(月例|週次|定例|感染者.{0,12}(?:数|増加|減少|状況)|約款|"
    r"株先物|市場は.*(?:上昇|下落)|本日の値動き|"
    r"\b(?:monthly update|weekly update|market preview|stock futures)\b)",
    re.I,
)
ROUTINE_STRATEGY_OVERVIEW_RE = re.compile(
    r"(市場戦略|成長戦略|事業戦略|製品ラインアップ|価格動向|性能と価格|"
    r"企業概要|製品概要|基本情報|"
    r"\b(?:market strategy|growth strategy|product lineup|price trends|"
    r"company overview|product overview|model overview|members? profile)\b)",
    re.I,
)
ENTERTAINMENT_ARTIFACT_RE = re.compile(
    r"(アルバム|楽曲|シングル|歌手|シンガー|リイシュー|映画|ドラマ|"
    r"\b(?:album|song|singer|reissue|music video)\b)",
    re.I,
)
SPACE_CONTEXT_RE = re.compile(
    r"(SpaceX|宇宙|ロケット|衛星|打ち上げ|軌道|Starlink|Dragon|"
    r"Starship.{0,20}(?:flight|launch|test|rocket)|"
    r"\b(?:spacecraft|rocket|satellite|launch|orbit)\b)",
    re.I,
)
MATERIAL_RESULT_TITLE_RE = re.compile(
    r"((?:\d[\d,.]*|[０-９][０-９，．]*)\s*(?:%|％|億|兆|万|ドル|円|人|件)?.{0,24}"
    r"(?:増|減|上昇|下落|伸び|低下|成長|縮小|改善|悪化|黒字|赤字|突破|上回|下回|修正)|"
    r"(?:過去|史上|上場来|調査開始以来).{0,16}(?:最高|最低|最大|最小)|"
    r"(?:最高値|最安値|急騰|急落|暴落|急反発|大幅続伸|予想外))",
    re.I,
)
UNCONFIRMED_FUTURE_RE = re.compile(
    r"(見通し|予想|観測|可能性|検討|計画|予定|見込み|候補|噂|憶測|導入案|"
    r"まもなく|近く発表|発売へ$|"
    r"(?:か|のか)[？?]|[？?]$|"
    r"\b(?:rumou?r|reportedly|in talks|plans?|planning|prepping|could|may|might|"
    r"expected to|set to|to launch|eyes? an? IPO|what to expect)\b)",
    re.I,
)
CONFIRMED_FUTURE_OVERRIDE_RE = re.compile(
    r"(正式発表|決定|承認|申請|契約|合意|受注|提供開始|発売開始|"
    r"\b(?:officially announced|approved|filed|signed|launched|released)\b)",
    re.I,
)
ROUTINE_MARKET_TICK_RE = re.compile(
    r"(寄り付き|前引け|後場|大引け|概況|清算値|オプション|先物|"
    r"(?:\d{1,2}|[０-９]{1,2})時(?:点|の)|ドル[・/]?円.{0,24}推移|小動き|"
    r"\b(?:pre-market|market today|market preview|futures?|intraday|"
    r"opening bell|midday trading)\b)",
    re.I,
)
ROUTINE_MARKET_EXCEPTION_RE = re.compile(
    r"(過去最高|過去最低|史上最高|史上最低|最高値|最安値|急騰|急落|暴落|"
    r"急反発|大幅続伸|(?:1000|１[０0]{3})円超|\b(?:record high|record low|crash)\b)",
    re.I,
)
ROUTINE_PERSONAL_LIFESTYLE_RE = re.compile(
    r"(早期退職|FIRE|お小遣い|家計事情|貯蓄.*(?:平均|リアル)|"
    r"キャッシュバック|購入レビュー|買うべき|徹底解説|ランキング|ベスト\d+|"
    r"いくら必要|可能[？?]|普通なのでしょうか|やるべきこと|"
    r"\b(?:how to|should you buy|best .* to buy|personal finance)\b)",
    re.I,
)
ACTUAL_EARNINGS_EVENT_RE = re.compile(
    r"(決算(?:発表|速報|[:：])|四半期.{0,20}(?:決算|業績|実績)|"
    r"(?:通期|本決算|最終決算|[1-4１-４]Q|[1-9１-９][－ー-][0-9０-９]+月期).{0,24}"
    r"(?:決算|業績|実績|売上|利益|経常|最終|着地)|"
    r"\b(?:quarterly|annual|full-year|final|Q[1-4]|FY\d{2,4}).{0,20}"
    r"(?:earnings|results?)\b|\bearnings results?\b)",
    re.I,
)
MATERIAL_EARNINGS_EXCEPTION_RE = re.compile(
    r"(上方修正|下方修正|上場来初|初配当|増配|減配|復配|黒字転換|赤字転落|"
    r"過去最高|過去最低|最高益|最大赤字|予想(?:を|より)(?:上回|下回)|"
    r"\b(?:raises? guidance|cuts? guidance|beats? expectations|misses? expectations|"
    r"record profit|record loss|first dividend|dividend increase|dividend cut)\b)",
    re.I,
)
PHOTO_OR_MEDIA_VARIANT_RE = re.compile(
    r"^(?:\[?写真\]?|【写真(?:・画像)?】|写真・画像|動画)|(?:\s|^)\d+枚目(?:の写真・画像)?$",
    re.I,
)
ROUTINE_RECAP_OR_COMMENTARY_RE = re.compile(
    r"(ニュース\d+選|最新ハイライト|まとめ|ケーススタディ|ロードマップ|"
    r"シーズンメモリーズ|移籍市場.{0,8}契約状況|"
    r"と語る|と主張|疑問を呈|徹底分析|投資家は.*べき|協業で狙う|"
    r"\b(?:roundup|highlights?|implications|case study|what investors should|"
    r"should investors|raises doubts|signals a new|accuses|explained|says?|"
    r"history smiles|market doubt)\b)",
    re.I,
)
ROUTINE_COMMERCIAL_OR_ADJACENT_RE = re.compile(
    r"(限定発売|限定コラボ|キャンペーン|割引|円引き|サービスエリアマップ更新|チャリティ|寄付|"
    r"ボディキット|カスタム(?:車|パーツ)|興行収入|"
    r"\b(?:dealer|dealership|local charities|body kit|aftermarket|"
    r"sponsorships?|special edition label)\b)",
    re.I,
)
ROUTINE_SPACEX_LAUNCH_RE = re.compile(
    r"(launch schedule|mission details|SpaceX launches? (?:a )?Falcon 9.{0,80}Starlink|"
    r"Starlink mission.{0,40}(?:schedule|launch window))",
    re.I,
)
SPACEX_LAUNCH_EXCEPTION_RE = re.compile(
    r"(Starship|Dragon|有人|crew|初|milestone|\d+(?:st|nd|rd|th)|600th|record|"
    r"failure|anomaly|test flight|飛行試験)",
    re.I,
)
F1_COMPETITION_IDENTITY_RE = re.compile(
    r"\b(?:Ferrari|Mercedes|McLaren|Red Bull|Aston Martin|Hamilton|"
    r"Verstappen|Leclerc|Russell|Antonelli|Norris|Piastri|"
    r"FP[123]|qualifying|pit (?:lane|stop|release))\b",
    re.I,
)
ENTITY_SCOPE_NOISE_RE = {
    "SoftBank": re.compile(r"\b(?:reliance|grasim).{0,24}\barm\b", re.I),
    "Honda": re.compile(
        r"\b(?:dealer|dealership|charit|body kit|aftermarket|deserves you)\b|"
        r"(?:販売店|ディーラー|チャリティ|ボディキット)",
        re.I,
    ),
    "F1": re.compile(
        r"(Formula [23]|(?<![A-Za-z0-9])F[23](?![A-Za-z0-9])|"
        r"(?<![A-Za-z0-9])TCR(?![A-Za-z0-9])|Sクラス|限定発売|ニコチン|nicotine|"
        r"brand new website)",
        re.I,
    ),
    "SpaceX": re.compile(
        r"(^Ex-SpaceX|flight surgeon|we.re all SpaceX investors|"
        r"fantastic news for SpaceX stock|should investors be worried)",
        re.I,
    ),
}
HISTORICAL_REVIEW_RE = re.compile(
    r"((?:\d+年前|20\d{2}年.{0,8})(?:会合|政策|議事録|振り返)|"
    r"マイナス金利.{0,24}(?:元日銀|当時|議事録))",
    re.I,
)
SUSPICIOUS_MEDIA_TITLE_RE = re.compile(
    r"(?:Slide\s*)?\([A-Za-z0-9_-]{8,}\)$|\bThe Young And The Restless\b|"
    r"\bOsasuna Vs\b",
    re.I,
)
MACRO_CATEGORY_SCOPE_RE = {
    "日本経済": re.compile(
        r"(日本(?!テレビ)(?:政府|経済|企業|市場|株)?|日銀|BOJ|財務省|経産省|厚生労働省|厚労省|"
        r"総務省|内閣府|東京|東証|日経平均|JGB|円相場|ドル[・/]?円|国民生活基礎調査|"
        r"\bJapan(?:ese)?\b)",
        re.I,
    ),
    "アジア経済": re.compile(
        r"(アジア|中国|台湾|香港|韓国|インド|ベトナム|タイ|マレーシア|"
        r"シンガポール|インドネシア|フィリピン|ASEAN|RBI|PBOC|"
        r"\b(?:Asia|Asian|China|Chinese|Taiwan|Korea|Korean|India|Indian|"
        r"Vietnam|Vietnamese|Thailand|Thai|Malaysia|Singapore|Indonesia|"
        r"Philippines)\b)",
        re.I,
    ),
    "北米経済": re.compile(
        r"(米国|アメリカ|カナダ|メキシコ|FRB|連邦準備|ウォール街|"
        r"\b(?:U\.S\.|United States|American|America|Canada|Canadian|Mexico|"
        r"Mexican|Federal Reserve|Fed|Wall Street|S&P|Nasdaq|Dow Jones)\b)",
        re.I,
    ),
}
MACRO_BODY_SCOPE_RE = {
    "日本経済": re.compile(
        r"(日銀|財務省|経産省|厚生労働省|厚労省|総務省|内閣府|東証|"
        r"国民生活基礎調査|\bBOJ\b)",
        re.I,
    ),
}
MACRO_TOPIC_SCOPE_RE = {
    "日本経済": re.compile(
        r"(物価|CPI|賃金|所得|雇用|失業|消費|GDP|景気|日銀|金利|国債|JGB|"
        r"為替|円相場|ドル[・/]?円|日経平均|TOPIX|株式市場|政府方針|予算|税|"
        r"半導体.{0,30}(?:投資|助成|生産|拠点)|設備投資)",
        re.I,
    ),
    "アジア経済": re.compile(
        r"(CPI|GDP|PMI|物価|賃金|雇用|失業|消費|小売|成長率|中央銀行|金利|"
        r"輸出|輸入|貿易|関税|FDI|投資|製造業|生産|景気|為替|株式市場|"
        r"\b(?:inflation|employment|jobs|retail sales|growth|central bank|"
        r"interest rates?|exports?|imports?|trade|tariffs?|investment|manufacturing)\b)",
        re.I,
    ),
    "北米経済": re.compile(
        r"(CPI|PCE|GDP|物価|賃金|雇用|失業|消費|小売|FRB|連邦準備|金利|"
        r"米国債|Treasur|S&P|Nasdaq|Dow Jones|NYダウ|米国株式市場|"
        r"関税|貿易|産業政策|原油|エネルギー|停戦|"
        r"\b(?:inflation|employment|jobs|retail sales|Federal Reserve|Fed|"
        r"interest rates?|yields?|tariffs?|trade|industrial policy|oil|energy|ceasefire)\b)",
        re.I,
    ),
}
INVESTMENT_GUIDE_RE = state_contract.INVESTMENT_GUIDE_RE
NON_NEWS_GUIDE_RE = state_contract.NON_NEWS_GUIDE_RE
RECAP_EXPLAINER_RE = re.compile(
    r"(最新動向|見通し|まとめ|解説|基本情報|沿革|ガイド|"
    r"what\s+to\s+know|explainer|overview|history|outlook)",
    re.I,
)
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
INDEXED_CHANNEL_DOMAINS = {
    "youtube": ["youtube.com"],
    "sns_x": ["x.com", "twitter.com"],
    "instagram": ["instagram.com"],
    "facebook": ["facebook.com"],
    "tiktok": ["tiktok.com"],
}
NETWORK_SEMAPHORE = threading.BoundedSemaphore(
    max(1, int(os.getenv("NIGHT_SIGNAL_NETWORK_CONCURRENCY", "16")))
)


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


@functools.lru_cache(maxsize=1)
def configured_category_contracts() -> dict[str, dict[str, Any]]:
    coverage = load_object(COVERAGE_CONFIG)
    return {
        str(category["label"]): category
        for category in coverage.get("categories", [])
        if isinstance(category, dict) and isinstance(category.get("label"), str)
    }


PUBLISHER_ACCESS_TIER_RANK = {
    "open": 0,
    "open_or_mixed": 1,
    "mixed": 2,
    "search_or_mixed": 3,
    "restricted_or_mixed": 4,
    "restricted": 5,
}


def publisher_access_rank(publisher: dict[str, Any]) -> int:
    return PUBLISHER_ACCESS_TIER_RANK.get(
        str(publisher.get("access_tier", "")), 9
    )


@functools.lru_cache(maxsize=1)
def configured_discovery_publishers() -> dict[str, list[dict[str, Any]]]:
    """Load vetted publishers without turning every home page into a daily seed."""
    value = load_object(PUBLISHER_PORTFOLIO)
    publishers = value.get("publishers")
    if not isinstance(publishers, list):
        fail("publisher portfolio publishers must be a list")
    configured = configured_category_contracts()
    by_category: dict[str, list[dict[str, Any]]] = {
        label: [] for label in configured
    }
    seen_labels: set[str] = set()
    seen_urls: set[str] = set()
    allowed_access_tiers = {
        "open",
        "open_or_mixed",
        "mixed",
        "search_or_mixed",
        "restricted_or_mixed",
        "restricted",
    }
    for publisher in publishers:
        if not isinstance(publisher, dict):
            fail("publisher portfolio contains an invalid entry")
        label = str(publisher.get("label", "")).strip()
        url = str(publisher.get("url", "")).strip()
        source_class = str(publisher.get("source_class", "")).strip()
        access_tier = str(publisher.get("access_tier", "")).strip()
        roles = publisher.get("roles")
        categories = publisher.get("categories")
        topic_ids_by_category = publisher.get("topic_ids_by_category", {})
        try:
            priority = int(publisher.get("search_priority", 99))
        except (TypeError, ValueError):
            fail(f"publisher portfolio has invalid priority: {label or url}")
        if (
            not label
            or not normalized_source_host(url)
            or source_class not in EDITOR_TRUSTED_SOURCE_CLASSES
            or access_tier not in allowed_access_tiers
            or not isinstance(roles, list)
            or not roles
            or any(not isinstance(role, str) or not role.strip() for role in roles)
            or not isinstance(categories, list)
            or not categories
            or not isinstance(topic_ids_by_category, dict)
            or priority < 1
        ):
            fail(f"publisher portfolio has invalid entry: {label or url}")
        if label in seen_labels or url in seen_urls:
            fail(f"publisher portfolio has duplicate entry: {label or url}")
        seen_labels.add(label)
        seen_urls.add(url)
        unknown = {str(category) for category in categories} - set(configured)
        if unknown:
            fail(
                f"publisher portfolio has unknown categories for {label}: "
                + ", ".join(sorted(unknown))
            )
        for mapped_category, topic_ids in topic_ids_by_category.items():
            if mapped_category not in categories:
                fail(
                    f"publisher topic map references an unassigned category: "
                    f"{label}/{mapped_category}"
                )
            configured_topic_ids = {
                str(topic.get("id"))
                for topic in configured[str(mapped_category)].get(
                    "watch_topics", []
                )
                if isinstance(topic, dict) and topic.get("id")
            }
            if (
                not isinstance(topic_ids, list)
                or not topic_ids
                or any(
                    not isinstance(topic_id, str)
                    or topic_id not in configured_topic_ids
                    for topic_id in topic_ids
                )
            ):
                fail(
                    f"publisher topic map has invalid watch topics: "
                    f"{label}/{mapped_category}"
                )
        normalized = {
            **publisher,
            "label": label,
            "url": url,
            "source_class": source_class,
            "source_role": "independent_media_or_data",
            "search_priority": priority,
        }
        for category in categories:
            by_category[str(category)].append(normalized)
    for publishers_for_category in by_category.values():
        publishers_for_category.sort(
            key=lambda publisher: (
                int(publisher["search_priority"]),
                publisher_access_rank(publisher),
                str(publisher["label"]),
            )
        )
    for category_label, category in configured.items():
        required_roles = {
            str(role)
            for role in category.get("required_discovery_roles", [])
            if str(role).strip()
        }
        configured_roles = {
            str(role)
            for publisher in by_category[category_label]
            for role in publisher.get("roles", [])
            if str(role).strip()
        }
        missing_roles = required_roles - configured_roles
        if missing_roles:
            fail(
                f"publisher portfolio is missing required discovery roles for "
                f"{category_label}: {', '.join(sorted(missing_roles))}"
            )
    return by_category


@functools.lru_cache(maxsize=1)
def configured_depth_publishers() -> dict[str, list[dict[str, Any]]]:
    """Merge the research portfolio with trusted Web seeds for depth search.

    Seed registration already represents an explicit source decision. Reusing
    those domains here prevents a specialist such as Billboard Japan,
    SpaceNews, or Trading Economics from being checked as a home page but then
    omitted from the article-level recovery search.
    """
    portfolio = configured_discovery_publishers()
    source_categories = load_object(SOURCE_CONFIG).get("categories", {})
    merged: dict[str, list[dict[str, Any]]] = {}
    for category_label in configured_category_contracts():
        by_host: dict[str, dict[str, Any]] = {
            normalized_source_host(publisher.get("url")): dict(publisher)
            for publisher in portfolio.get(category_label, [])
            if normalized_source_host(publisher.get("url"))
        }
        seeds = (
            source_categories.get(category_label, [])
            if isinstance(source_categories, dict)
            else []
        )
        for source in seeds if isinstance(seeds, list) else []:
            if (
                not isinstance(source, dict)
                or source.get("channel") != "web"
                or source.get("source_role") != "independent_media_or_data"
                or source.get("source_class") not in EDITOR_TRUSTED_SOURCE_CLASSES
            ):
                continue
            host = normalized_source_host(source.get("url"))
            if not host or host in by_host:
                continue
            depth_topic_ids = source.get("depth_topic_ids", [])
            allowed_topic_ids = {
                str(topic.get("id"))
                for topic in configured_category_contracts()[category_label].get(
                    "watch_topics", []
                )
                if isinstance(topic, dict) and topic.get("id")
            }
            if (
                not isinstance(depth_topic_ids, list)
                or any(
                    not isinstance(topic_id, str)
                    or topic_id not in allowed_topic_ids
                    for topic_id in depth_topic_ids
                )
            ):
                fail(
                    f"registered depth publisher has invalid topics: "
                    f"{category_label}/{source.get('label', source.get('url', ''))}"
                )
            by_host[host] = {
                **source,
                "access_tier": "open_or_mixed",
                "search_priority": 1,
                "roles": ["registered_seed_depth"],
                "categories": [category_label],
                "topic_ids_by_category": (
                    {category_label: list(depth_topic_ids)}
                    if depth_topic_ids
                    else {}
                ),
            }
        merged[category_label] = sorted(
            by_host.values(),
            key=lambda publisher: (
                int(publisher.get("search_priority", 99)),
                str(publisher.get("source_class")) != "specialist_media",
                publisher_access_rank(publisher),
                str(publisher.get("label", "")),
            ),
        )
    return merged


def discovery_publishers_for_topic(
    category_label: str,
    topic_id: str,
) -> list[dict[str, Any]]:
    """Prefer specialists explicitly matched to the weak topic, with fallback."""
    publishers = configured_depth_publishers().get(category_label, [])
    matched = [
        publisher
        for publisher in publishers
        if topic_id
        in publisher.get("topic_ids_by_category", {}).get(category_label, [])
    ]
    if matched:
        return sorted(
            matched,
            key=lambda publisher: (
                str(publisher.get("source_class")) != "specialist_media",
                len(
                    publisher.get("topic_ids_by_category", {}).get(
                        category_label, []
                    )
                ),
                int(publisher.get("search_priority", 99)),
                publisher_access_rank(publisher),
                str(publisher.get("label", "")),
            ),
        )
    return sorted(
        publishers,
        key=lambda publisher: (
            int(publisher["search_priority"]),
            str(publisher.get("source_class")) != "specialist_media",
            publisher_access_rank(publisher),
            str(publisher["label"]),
        ),
    )


@functools.lru_cache(maxsize=1)
def configured_official_depth_sources() -> dict[str, dict[str, list[dict[str, Any]]]]:
    """Index official seed domains that should join topic-specific depth search."""
    configured = configured_category_contracts()
    categories = load_object(SOURCE_CONFIG).get("categories", {})
    indexed: dict[str, dict[str, list[dict[str, Any]]]] = {
        label: {} for label in configured
    }
    if not isinstance(categories, dict):
        fail("source config categories must be an object")
    for category_label, sources in categories.items():
        if category_label not in configured or not isinstance(sources, list):
            continue
        allowed_topics = {
            str(topic.get("id"))
            for topic in configured[category_label].get("watch_topics", [])
            if isinstance(topic, dict) and topic.get("id")
        }
        for source in sources:
            if not isinstance(source, dict):
                continue
            topic_ids = source.get("depth_topic_ids", [])
            if not topic_ids:
                continue
            if source.get("source_role") != "primary_or_official":
                continue
            if (
                source.get("channel") != "web"
                or not isinstance(topic_ids, list)
                or any(
                    not isinstance(topic_id, str)
                    or topic_id not in allowed_topics
                    for topic_id in topic_ids
                )
                or not normalized_source_host(source.get("url"))
            ):
                fail(
                    f"official depth source has invalid topics: "
                    f"{category_label}/{source.get('label', source.get('url', ''))}"
                )
            for topic_id in topic_ids:
                indexed[category_label].setdefault(str(topic_id), []).append(source)
    return indexed


SOURCE_AUTHORITY_RANK = {
    "official": 5,
    "official_dataset": 5,
    "major_media": 4,
    "specialist_media": 3,
    "sns_x": 2,
    "youtube_video": 2,
    "social": 1,
    "discovered_media": 0,
}
EDITOR_TRUSTED_SOURCE_CLASSES = {
    "official",
    "official_dataset",
    "major_media",
    "specialist_media",
}


def normalized_source_host(value: Any) -> str:
    parsed = urllib.parse.urlparse(str(value or ""))
    host = (parsed.hostname or "").casefold().removeprefix("www.")
    return host.rstrip(".")


def source_host_matches(candidate: str, allowed: str) -> bool:
    return bool(
        candidate
        and allowed
        and (
            candidate == allowed
            or candidate.endswith(f".{allowed}")
            or allowed.endswith(f".{candidate}")
        )
    )


def record_matches_allowed_hosts(
    record: dict[str, Any],
    allowed_hosts: list[str],
) -> bool:
    """Enforce targeted search domains after the search provider responds."""
    normalized_allowed = [
        normalized_source_host(f"https://{host}")
        for host in allowed_hosts
        if normalized_source_host(f"https://{host}")
    ]
    if not normalized_allowed:
        return True
    candidates = {
        normalized_source_host(record.get("url")),
        normalized_source_host(record.get("publisher_url")),
    } - {""}
    return any(
        source_host_matches(candidate, allowed)
        for candidate in candidates
        for allowed in normalized_allowed
    )


@functools.lru_cache(maxsize=1)
def configured_source_profiles() -> dict[str, tuple[str, str]]:
    """Index configured publishers so RSS discoveries inherit source authority."""
    categories = load_object(SOURCE_CONFIG).get("categories")
    if not isinstance(categories, dict):
        fail("source config categories must be an object")
    profiles: dict[str, tuple[str, str]] = {}
    source_groups = list(categories.values()) + [
        [
            publisher
            for publishers in configured_discovery_publishers().values()
            for publisher in publishers
        ]
    ]
    for sources in source_groups:
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            host = normalized_source_host(source.get("url"))
            source_class = str(source.get("source_class", ""))
            source_role = str(source.get("source_role", ""))
            if not host or not source_class:
                continue
            existing = profiles.get(host)
            if (
                existing is None
                or SOURCE_AUTHORITY_RANK.get(source_class, 0)
                > SOURCE_AUTHORITY_RANK.get(existing[0], 0)
            ):
                profiles[host] = (source_class, source_role)
    return profiles


@functools.lru_cache(maxsize=2048)
def configured_source_profile_for_hosts(
    candidates: tuple[str, ...],
) -> tuple[str, str] | None:
    for candidate in candidates:
        matches = [
            profile
            for host, profile in configured_source_profiles().items()
            if candidate == host
            or candidate.endswith(f".{host}")
            or host.endswith(f".{candidate}")
        ]
        if matches:
            return max(
                matches,
                key=lambda profile: SOURCE_AUTHORITY_RANK.get(profile[0], 0),
            )
    return None


def configured_source_profile(record: dict[str, Any]) -> tuple[str, str] | None:
    candidates = tuple(
        sorted(
            {
                host
                for host in (
                    normalized_source_host(record.get("url")),
                    normalized_source_host(record.get("publisher_url")),
                )
                if host
            }
        )
    )
    return configured_source_profile_for_hosts(candidates)


def effective_source_class(record: dict[str, Any]) -> str:
    source_class = str(record.get("source_class", ""))
    if source_class and source_class != "discovered_media":
        return source_class
    configured = configured_source_profile(record)
    return configured[0] if configured is not None else source_class


def effective_source_role(record: dict[str, Any]) -> str:
    configured = configured_source_profile(record)
    if configured is not None:
        return configured[1]
    return str(record.get("source_role", ""))


def record_has_trusted_editor_source(record: dict[str, Any]) -> bool:
    return effective_source_class(record) in EDITOR_TRUSTED_SOURCE_CLASSES


@functools.lru_cache(maxsize=1)
def configured_category_identity_terms() -> dict[str, tuple[str, ...]]:
    configured: dict[str, tuple[str, ...]] = {}
    for label, category in configured_category_contracts().items():
        try:
            terms = evidence_contract.category_identity_terms(category)
        except evidence_contract.EvidenceContractError as exc:
            fail(str(exc))
        configured[label] = terms
    return configured


def category_identity_terms(category_label: str) -> tuple[str, ...]:
    return configured_category_identity_terms().get(category_label, ())


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


class ArticleContainerParser(HTMLParser):
    HIDDEN_TAGS = VisibleTextParser.HIDDEN_TAGS
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
    CONTAINER_RE = re.compile(
        r"(?:article|entry|post|story|news)[_-]?(?:body|content)|"
        r"(?:body|content)[_-]?(?:article|entry|post|story|news)",
        re.I,
    )

    def __init__(self) -> None:
        super().__init__()
        self.depth = 0
        self.hidden_depth = 0
        self.current: list[str] = []
        self.candidates: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if self.depth:
            if tag not in self.VOID_TAGS:
                self.depth += 1
            if tag in self.HIDDEN_TAGS:
                self.hidden_depth += 1
            return
        values = dict(attrs)
        identity = " ".join(
            str(values.get(name) or "") for name in ("id", "class")
        )
        if tag == "article" or self.CONTAINER_RE.search(identity):
            self.depth = 1
            self.hidden_depth = 0
            self.current = []

    def handle_endtag(self, tag: str) -> None:
        if not self.depth:
            return
        if tag in self.HIDDEN_TAGS and self.hidden_depth:
            self.hidden_depth -= 1
        self.depth -= 1
        if self.depth == 0:
            text = compact_text(" ".join(self.current), 8000)
            if text:
                self.candidates.append(text)
            self.current = []

    def handle_startendtag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag not in self.VOID_TAGS:
            self.handle_starttag(tag, attrs)
            self.handle_endtag(tag)

    def handle_data(self, data: str) -> None:
        if self.depth and not self.hidden_depth:
            text = " ".join(data.split())
            if text:
                self.current.append(text)

    def text(self) -> str:
        return max(self.candidates, key=len, default="")


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
        8000,
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
    def normalize_number_words(value: Any) -> str:
        return re.sub(
            r"\b(?:" + "|".join(ENGLISH_NUMBER_WORD_VALUES) + r")\b",
            lambda match: str(
                ENGLISH_NUMBER_WORD_VALUES[match.group(0).lower()]
            ),
            str(value),
            flags=re.I,
        )

    normalized_left = unicodedata.normalize("NFKC", normalize_number_words(left))
    normalized_right = unicodedata.normalize("NFKC", normalize_number_words(right))
    explainer_pattern = re.compile(
        r"(?:とは|使い方|料金|違い|徹底解説|\bwhat is\b|\bhow to\b|"
        r"\bexplained\b|\bguide\b)",
        re.I,
    )
    left_explainer = explainer_pattern.search(normalized_left)
    right_explainer = explainer_pattern.search(normalized_right)
    if left_explainer and right_explainer:
        left_subject = normalized_left[: left_explainer.start()]
        right_subject = normalized_right[: right_explainer.start()]
        if (
            left_subject.strip()
            and right_subject.strip()
            and not state_contract.materially_same_fact(
                left_subject,
                right_subject,
            )
            and state_contract.text_overlap(left_subject, right_subject) == 0
        ):
            return False
    left_signature = state_contract.copy_signature(normalized_left)
    right_signature = state_contract.copy_signature(normalized_right)
    if not left_signature or not right_signature:
        return False
    shorter, longer = sorted(
        (left_signature, right_signature),
        key=len,
    )
    if shorter != longer and len(shorter) < 12 and len(longer) >= len(shorter) * 2:
        return False
    left_ngrams = {
        left_signature[index : index + 3]
        for index in range(max(0, len(left_signature) - 2))
    }
    right_ngrams = {
        right_signature[index : index + 3]
        for index in range(max(0, len(right_signature) - 2))
    }
    similarity = (
        len(left_ngrams & right_ngrams) / min(len(left_ngrams), len(right_ngrams))
        if left_ngrams and right_ngrams
        else 0.0
    )
    shared_ngrams = left_ngrams & right_ngrams
    shared_numbers = {
        value
        for value in numeric_claims(normalized_left) & numeric_claims(normalized_right)
        if not 1900 <= value <= 2100
    }
    left_ascii_terms = {
        term.casefold()
        for term in re.findall(r"[A-Za-z][A-Za-z0-9.-]{2,}", normalized_left)
    }
    right_ascii_terms = {
        term.casefold()
        for term in re.findall(r"[A-Za-z][A-Za-z0-9.-]{2,}", normalized_right)
    }
    shared_ascii_terms = left_ascii_terms & right_ascii_terms
    shared_version_terms = {
        term
        for term in shared_ascii_terms
        if re.search(r"\d", term) and ("." in term or "-" in term)
    }
    ascii_event_stopwords = {
        "announce",
        "announced",
        "announcement",
        "launch",
        "launched",
        "release",
        "released",
        "releases",
        "update",
        "updated",
        "model",
        "models",
        "series",
        "official",
        "formally",
        "new",
        "the",
        "and",
        "for",
        "from",
        "with",
    }
    left_unique_subjects = {
        term
        for term in left_ascii_terms - shared_ascii_terms
        if term not in ascii_event_stopwords and not re.search(r"\d", term)
    }
    right_unique_subjects = {
        term
        for term in right_ascii_terms - shared_ascii_terms
        if term not in ascii_event_stopwords and not re.search(r"\d", term)
    }
    if (
        shared_version_terms
        and min(len(left_unique_subjects), len(right_unique_subjects)) >= 1
        and max(len(left_unique_subjects), len(right_unique_subjects)) >= 3
    ):
        return False
    return (
        state_contract.materially_same_fact(normalized_left, normalized_right)
        or (
            state_contract.text_overlap(normalized_left, normalized_right) >= 2
            and similarity >= 0.4
        )
        or (bool(shared_numbers) and len(shared_ngrams) >= 4)
        or (
            len(shared_ascii_terms) >= 3
            and bool(PUBLICATION_EVENT_RE.search(normalized_left))
            and bool(PUBLICATION_EVENT_RE.search(normalized_right))
        )
        or (
            similarity >= 0.62
            and len(shared_ngrams) >= 8
            and bool(PUBLICATION_EVENT_RE.search(normalized_left))
            and bool(PUBLICATION_EVENT_RE.search(normalized_right))
        )
    )


def cluster_priority(
    record: dict[str, Any],
    category: dict[str, Any],
) -> tuple[int, int, str]:
    title = str(record.get("title", ""))
    excerpt = str(record.get("excerpt", ""))
    text = f"{title} {excerpt}"
    score = SOURCE_AUTHORITY_RANK.get(effective_source_class(record), 0) * 4
    score += 5 * record_has_material_body(record_public_title(record), record)
    score += 2 * (effective_source_role(record) == "primary_or_official")
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
    return score, min(len(excerpt), 8000), compact_text(title or excerpt, 160)


def select_clustered_evidence(
    category: dict[str, Any],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    observed = [record for record in records if record.get("observed")]
    clustered: dict[str, list[dict[str, Any]]] = {}
    for record in observed:
        key = record_cluster_key(record)
        if not key:
            key = str(record.get("url", ""))
        clustered.setdefault(key, []).append(record)
    selected: list[dict[str, Any]] = []
    for group in clustered.values():
        ranked = sorted(
            group,
            key=lambda record: cluster_priority(record, category),
            reverse=True,
        )
        hosts: set[str] = set()
        source_classes: set[str] = set()
        for record in ranked:
            host = normalized_source_host(
                record.get("publisher_url") or record.get("url")
            )
            source_class = effective_source_class(record)
            if any(
                state_contract.materially_same_fact(
                    editor_source_text(record, 2400),
                    editor_source_text(existing, 2400),
                )
                for existing in selected
                if (record_cluster_key(existing) or str(existing.get("url", "")))
                == (record_cluster_key(record) or str(record.get("url", "")))
            ):
                continue
            if (
                hosts
                and source_class in source_classes
                and not record_has_material_body(record_public_title(record), record)
            ):
                continue
            selected.append(record)
            if host:
                hosts.add(host)
            source_classes.add(source_class)
    records_by_score = sorted(
        selected,
        key=lambda record: cluster_priority(record, category),
        reverse=True,
    )
    return records_by_score


def record_from_expanded_scope(record: dict[str, Any]) -> bool:
    """Identify Evidence introduced by an explicit scope expansion."""
    return bool(record.get("official_scope")) or any(
        str(query_id).startswith("horizon:local-language:")
        for query_id in record.get("discovery_query_ids", [])
    )


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
    category = configured_category_contracts().get(category_label, {})
    if not category.get("allow_sports_results", False) and SPORTS_RESULT_RE.search(title):
        return False
    terms = category_identity_terms(category_label)
    if not terms:
        return True
    text = f"{title} {summary}".lower()
    if category_label == "F1" and F1_COMPETITION_IDENTITY_RE.search(text):
        return True
    return any(term.lower() in text for term in terms)


def editor_candidate_boundary(
    category_label: str,
    title: str,
    excerpt: str,
    *,
    source_label: str = "",
) -> bool:
    """Apply the shared material-event boundary before model review."""
    text = f"{title} {excerpt}"
    return bool(
        title
        and excerpt
        and not state_contract.navigation_shell_text(text)
        and not state_contract.NO_UPDATE_ASSERTION_RE.search(text)
        and material_event_candidate(title, excerpt)
        and category_identity_ok(category_label, f"{source_label} {title}", excerpt)
    )


def material_event_candidate(title: str, excerpt: str) -> bool:
    """Reject generic descriptions while preserving concrete changes and analysis."""
    title_text = reader_facing_text(title, 500)
    body_text = reader_facing_text(excerpt, 2400)
    if state_contract.GENERIC_ENTITY_OVERVIEW_RE.search(title_text):
        return False
    combined = f"{title_text} {body_text}"
    if INVESTMENT_GUIDE_RE.search(combined) or NON_NEWS_GUIDE_RE.search(combined):
        return False
    return bool(
        PUBLICATION_EVENT_RE.search(combined)
        or MATERIAL_SIGNAL_RE.search(combined)
        or SPORTS_RESULT_RE.search(combined)
        or (
            state_contract.ANALYSIS_HEADLINE_RE.search(title_text)
            and state_contract.ANALYSIS_REASONING_RE.search(body_text)
        )
    )


ARTICLE_CONTENT_END_RE = re.compile(
    r"AI・生成AIのおすすめコンテンツ|おすすめコンテンツ|"
    r"Googleで見つけやすく|(?:^|\s)関連記事(?:一覧|はこちら)?|"
    r"関連コンテンツ|もっと読むにはこちら|"
    r"Daily Debrief Newsletter|Sign up for (?:our|the) newsletter|"
    r"(?:^|\s)共有する(?:\s|$)|(?:^|\s)Related Stories(?:\s|$)",
    re.I,
)
ARTICLE_REQUIRED_FACT_TAIL_RE = re.compile(
    r"(?:^|\s)(?:Recent(?:ly)? Published|Latest (?:News|Articles|Stories)|"
    r"TOP STORIES|Related Articles|Recommended (?:Articles|Stories)|"
    r"You May Also Like|Read Next|More (?:News|Stories|From))(?=\s|[:：]|$)|"
    r"Download (?:the )?[^。.!?]{0,80}?(?:App|Articles)(?=[\s:：。.!?]|$)|"
    r"Complete profile|Before downloading the whitepaper|"
    r"(?:Follow|Connect with) [^。.!?]{0,80}? on LinkedIn|"
    r"商品ページ|TV放送[＆&]タイムスケジュール|"
    r"コメントを読む|本記事はニュース提供社|"
    r"すべてのコンテンツの著作権|"
    r"(?:株式会社|有限公司)\s*概要|"
    r"(?:氏|さん)[（(][^）)]{0,60}[）)]\s*19\d{2}年|"
    r"まずは一度、?ぜひ|"
    r"What to do before the window closes|"
    r"Reference\s*[:：]",
    re.I,
)
ARTICLE_OPTIONAL_REQUIRED_FACT_RE = re.compile(
    r"^実験的な機能のため、?記事本文と併せてご確認ください|"
    r"^(?:本記事|この記事)では.{0,180}(?:(?:紹介|解説|確認)(?:します|する)|"
    r"紐解(?:きます|く))|"
    r"^[A-Z][A-Za-z.'’-]+ last (?:Monday|Tuesday|Wednesday|Thursday|Friday|"
    r"Saturday|Sunday|week|month)[。.!?]?$|"
    r"^Must Read\b",
    re.I,
)
ARTICLE_CHROME_SENTENCE_RE = re.compile(
    r"印刷機能|会員登録|無料登録|ログイン|マイページ|"
    r"トップページ|タグをフォロー|著者を応援|"
    r"コメントを投稿|通報|ブロック解除|"
    r"(?:^|\s)(?:Home|Menu|Share|Subscribe|Sign up|Log in)(?:\s|$)|"
    r"cookies?|privacy policy|already a subscriber|read more",
    re.I,
)
ARTICLE_LEADING_CHROME_RE = re.compile(
    r"^.*?(?:タグをもっとみる|Tags?\s*[:：])\s*",
    re.I,
)
FIGURE_LINK_PREFIX_RE = re.compile(
    r"^【(?:図版付き記事はこちら|関連記事)】[^。！？!?]{0,280}?[）)]\s*"
)
ARTICLE_GENERIC_PURPOSE_RE = re.compile(
    r"企業ミッションとして掲げ|"
    r"(?:環境|体制|AIシステムの構築)を推進する[。．.!！?？]*$|"
    r"(?:可能性がある|期待される|見通しだ|注目される)[。．.!！?？]*$"
)
ARTICLE_EMBEDDED_ENTITY_HISTORY_RE = re.compile(
    r"20\d{2}年\d{1,2}月に(?:設立|創業)した.{0,160}"
    r"20\d{2}年\d{1,2}月\d{1,2}日.{0,120}(?:発表|公開)"
)


def article_source_window(record: dict[str, Any]) -> str:
    """Keep the article body while dropping deterministic page chrome."""
    raw = reader_facing_text(
        str(record.get("excerpt") or record.get("evidence") or ""),
        12_000,
    )
    if not raw:
        return ""
    title = record_public_title(record)
    start = 0
    leading_markers = list(
        re.finditer(r"タグをもっとみる|Tags?\s*[:：]", raw[:3000], re.I)
    )
    if leading_markers:
        start = leading_markers[-1].end()
    elif title:
        title_positions = [
            match.start()
            for match in re.finditer(re.escape(title), raw[:3000], re.I)
        ]
        if title_positions:
            start = title_positions[-1]
    author_expander = raw.find("もっと見る", start, min(len(raw), start + 1200))
    author_close = raw.find("閉じる", author_expander, min(len(raw), start + 3000))
    if author_expander >= 0 and author_close > author_expander:
        start = author_close + len("閉じる")
    end = len(raw)
    for match in ARTICLE_CONTENT_END_RE.finditer(raw, max(0, start + 120)):
        end = match.start()
        break
    return raw[start:end].strip(" -–—|｜")


def clean_article_sentence(value: str) -> str:
    sentence = ARTICLE_LEADING_CHROME_RE.sub("", value).strip()
    sentence = FIGURE_LINK_PREFIX_RE.sub("", sentence).strip()
    sentence = re.sub(r"^[（(]Photo\s*:[^）)]*[）)]\s*", "", sentence, flags=re.I)
    return sentence.strip(" -–—|｜")


def editor_article_facts(record: dict[str, Any]) -> list[str]:
    """Return the complete, article-specific confirmed-fact inventory."""
    title = record_public_title(record)
    window = article_source_window(record)
    facts: list[str] = []
    for raw_sentence in sentence_parts(window, limit=12_000):
        sentence = clean_article_sentence(raw_sentence)
        visible_count = len(re.findall(r"\S", sentence))
        letter_count = len(
            re.findall(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]", sentence)
        )
        if (
            not sentence
            or not visible_count
            or letter_count / visible_count < 0.45
            or ARTICLE_CONTENT_END_RE.search(sentence)
            or ARTICLE_CHROME_SENTENCE_RE.search(sentence)
            or state_contract.DOCUMENT_EXTRACTION_NOISE_RE.search(sentence)
            or state_contract.navigation_shell_text(sentence)
            or state_contract.source_material_fact_violations(sentence)
            or state_contract.GENERIC_ENTITY_OVERVIEW_RE.search(sentence)
            or INVESTMENT_GUIDE_RE.search(sentence)
            or NON_NEWS_GUIDE_RE.search(sentence)
            or ARTICLE_GENERIC_PURPOSE_RE.search(sentence)
            or state_contract.materially_same_fact(title, sentence)
        ):
            continue
        if not state_contract.fact_adds_information(title, sentence):
            continue
        if (
            ARTICLE_EMBEDDED_ENTITY_HISTORY_RE.search(sentence)
            and any(
                state_contract.text_overlap(existing, sentence) >= 6
                for existing in facts
            )
        ):
            continue
        duplicate_index = next(
            (
                index
                for index, existing in enumerate(facts)
                if state_contract.materially_same_fact(existing, sentence)
            ),
            None,
        )
        if duplicate_index is not None:
            if state_contract.fact_specificity(sentence) > state_contract.fact_specificity(
                facts[duplicate_index]
            ):
                facts[duplicate_index] = sentence
            continue
        facts.append(sentence)
    if facts:
        return facts
    return []


MAX_EDITOR_SOURCE_FACTS = 16


def editor_source_fact_inventory(
    evidence_id: str,
    record: dict[str, Any],
) -> list[dict[str, str]]:
    facts = editor_article_facts(record)
    if len(facts) > MAX_EDITOR_SOURCE_FACTS:
        title = record_public_title(record)

        def fact_rank(indexed: tuple[int, str]) -> tuple[int, int, int, int]:
            index, fact = indexed
            return (
                6 * bool(PUBLICATION_EVENT_RE.search(fact))
                + 5 * bool(MATERIAL_SIGNAL_RE.search(fact))
                + 4 * bool(SPORTS_RESULT_RE.search(fact))
                + 3 * min(3, state_contract.text_overlap(title, fact))
                + 2 * bool(
                    re.search(
                        r"理由|要因|背景|ため|結果|影響|条件|対象|範囲|"
                        r"because|reason|result|impact|condition|scope",
                        fact,
                        re.I,
                    )
                )
                + min(3, len(numeric_claims(fact)))
                + max(0, 6 - index),
                len(numeric_claims(fact)),
                state_contract.text_overlap(title, fact),
                -index,
            )

        selected_indexes = {
            index
            for index, _ in sorted(
                enumerate(facts),
                key=fact_rank,
                reverse=True,
            )[:MAX_EDITOR_SOURCE_FACTS]
        }
        facts = [
            fact for index, fact in enumerate(facts) if index in selected_indexes
        ]
    return [
        {"id": f"{evidence_id}:f{index:02d}", "text": fact}
        for index, fact in enumerate(facts, start=1)
    ]


def editor_required_source_facts(
    evidence_entries: list[tuple[str, dict[str, Any]]],
) -> dict[str, list[dict[str, str]]]:
    """Deduplicate repeated source facts without discarding distinct additions."""
    required: dict[str, list[dict[str, str]]] = {}
    for evidence_id, record in evidence_entries:
        event_id = str(record.get("_editor_event_id") or evidence_id)
        event_facts = required.setdefault(event_id, [])
        for fact in editor_source_fact_inventory(evidence_id, record):
            # Keep stable fact ids in the packet inventory, but never make a
            # publisher's related-story/navigation tail mandatory summary
            # content.  Once a tail marker appears, all later extracted
            # sentences belong to the page shell rather than the article.
            if ARTICLE_REQUIRED_FACT_TAIL_RE.search(fact["text"]):
                break
            # A publisher can inject an isolated promo, article-description,
            # extraction warning, or sentence fragment between real body
            # paragraphs.  Skip that one fact without truncating later body
            # facts, and keep packet fact ids immutable.
            if ARTICLE_OPTIONAL_REQUIRED_FACT_RE.search(fact["text"]):
                continue
            if any(
                state_contract.materially_same_fact(fact["text"], existing["text"])
                for existing in event_facts
            ):
                continue
            event_facts.append({**fact, "evidence_id": evidence_id})
    return required


def editor_source_text(record: dict[str, Any], limit: int) -> str:
    """Select a bounded relevance view for deterministic grouping only."""
    text = reader_facing_text(
        str(record.get("excerpt") or record.get("evidence") or ""),
        8000,
    )
    text = compact_text(
        state_contract.GENERIC_ENTITY_OVERVIEW_RE.sub(" ", text).strip(
            " 。.!?！？"
        ),
        8000,
    )
    if len(text) <= limit:
        return text
    title = record_public_title(record)
    sentences = [
        sentence.strip()
        for sentence in sentence_parts(text, split_latin_sentences=False)
        if sentence.strip()
        and not state_contract.navigation_shell_text(sentence)
    ]
    if not sentences:
        return compact_text(text, limit)

    def sentence_score(indexed: tuple[int, str]) -> tuple[int, int]:
        index, sentence = indexed
        score = (
            5 * bool(PUBLICATION_EVENT_RE.search(sentence))
            + 4 * bool(MATERIAL_SIGNAL_RE.search(sentence))
            + 3 * bool(SPORTS_RESULT_RE.search(sentence))
            + 2 * bool(state_contract.ANALYSIS_REASONING_RE.search(sentence))
            + 2 * min(2, state_contract.text_overlap(title, sentence))
            + min(3, len(re.findall(r"\d+(?:\.\d+)?", sentence)))
            + int(index < 2)
        )
        return score, -index

    chosen: dict[int, str] = {}
    used = 0
    for index, sentence in sorted(
        enumerate(sentences),
        key=sentence_score,
        reverse=True,
    ):
        remaining = limit - used - int(bool(chosen))
        if remaining < 80:
            break
        if len(sentence) > remaining:
            head = max(1, remaining * 2 // 3)
            sentence = f"{sentence[:head]} {sentence[-(remaining - head):]}"
        chosen[index] = compact_text(sentence, remaining)
        used += len(chosen[index])
    return compact_text(" ".join(chosen[index] for index in sorted(chosen)), limit)


def record_has_only_headline(title: str, record: dict[str, Any]) -> bool:
    """Identify feeds whose excerpt is only the headline plus publisher credit."""
    excerpt = reader_facing_text(record.get("excerpt") or record.get("evidence") or "", 2400)
    canonical_title = canonical_article_match_text(title)
    canonical_excerpt = canonical_article_match_text(excerpt)
    residual = canonical_excerpt.replace(canonical_title, " ")
    labels = [
        str(record.get("label") or "").strip(),
        urllib.parse.urlparse(str(record.get("publisher_url") or "")).netloc
        .lower()
        .removeprefix("www."),
    ]
    for label in labels:
        canonical_label = canonical_article_match_text(label)
        if canonical_label:
            residual = residual.replace(canonical_label, " ")
    if canonical_title and not re.sub(r"[^a-z0-9\u3040-\u30ff\u3400-\u9fff]+", "", residual):
        return True
    cleaned = excerpt.rstrip("。.!！ ")
    for label in labels:
        if label and cleaned.lower().endswith(label.lower()):
            cleaned = cleaned[: -len(label)].rstrip(" -–—|｜。.!！ ")
    return normalized_topic_key(title) == normalized_topic_key(cleaned)


def record_has_material_body(title: str, record: dict[str, Any]) -> bool:
    """Return whether the fetched body adds usable substance beyond its headline."""
    if record_has_only_headline(title, record):
        return False
    excerpt = str(record.get("excerpt") or "")
    canonical_title = canonical_article_match_text(title)
    headline_core = re.sub(
        r"\s*[（(][^()（）]{2,60}[）)]$",
        "",
        canonical_title,
    ).strip()
    title_for_anchor = headline_core or canonical_title
    title_japanese = "".join(
        re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", title_for_anchor)
    )
    title_ngrams = {
        title_japanese[index : index + 4]
        for index in range(max(0, len(title_japanese) - 3))
    }
    for raw_sentence in sentence_parts(excerpt):
        sentence = raw_sentence
        markdown_marker = re.search(r"markdown content\s*:\s*", sentence, re.I)
        if markdown_marker:
            sentence = sentence[markdown_marker.end() :].strip()
        if not sentence:
            continue
        if (
            state_contract.DOCUMENT_EXTRACTION_NOISE_RE.search(sentence)
            or state_contract.SOURCE_CHROME_RE.search(sentence)
            or re.search(
                r"(?:cookie|privacy policy|terms of use|sign up|log in|"
                r"subscribe|newsletter|advertisement|accept all|consent|"
                r"already a subscriber|skip to main content|"
                r"クッキー|プライバシー|会員登録|ログイン|購読|広告)",
                sentence,
                re.I,
            )
        ):
            continue
        added_terms = (
            state_contract.content_terms(sentence)
            - state_contract.content_terms(title)
        )
        added_numbers = numeric_claims(sentence) - numeric_claims(title)
        repetition_score = state_contract.title_repetition_score(title, sentence)
        if repetition_score >= 0.82:
            canonical_sentence = canonical_article_match_text(sentence)
            adds_substance = bool(
                len(added_terms) >= 2
                or added_numbers
                or PUBLICATION_EVENT_RE.search(" ".join(added_terms))
            )
            if (
                not adds_substance
                or (
                    headline_core
                    and canonical_sentence.count(headline_core) >= 2
                )
            ):
                continue
        sentence_japanese = "".join(
            re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", sentence)
        )
        sentence_ngrams = {
            sentence_japanese[index : index + 4]
            for index in range(max(0, len(sentence_japanese) - 3))
        }
        anchored = (
            state_contract.text_overlap(
                title_for_anchor,
                canonical_article_match_text(sentence),
            )
            >= 1
            or len(title_ngrams & sentence_ngrams) >= 2
        )
        if state_contract.navigation_shell_text(sentence) or not anchored:
            continue
        visible_count = len(re.findall(r"\S", sentence))
        letter_count = len(
            re.findall(r"[A-Za-z\u3040-\u30ff\u3400-\u9fff]", sentence)
        )
        if not visible_count or letter_count / visible_count < 0.45:
            continue
        japanese_count = len(
            re.findall(r"[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af]", sentence)
        )
        latin_words = re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", sentence)
        if (
            japanese_count >= 8
            and useful_fact(sentence, "")
            and (len(added_terms) >= 2 or bool(added_numbers))
        ):
            return True
        if (
            len(latin_words) >= 8
            and (len(added_terms) >= 4 or bool(added_numbers))
            and not state_contract.navigation_shell_text(sentence)
        ):
            return True
    article_text = " ".join(editor_article_facts(record))
    if source_requires_japanese_translation(article_text):
        article_terms = (
            state_contract.content_terms(article_text)
            - state_contract.content_terms(title)
        )
        article_numbers = numeric_claims(article_text) - numeric_claims(title)
        if (
            state_contract.text_overlap(title_for_anchor, article_text) >= 1
            and len(re.findall(r"[A-Za-z][A-Za-z0-9'-]{2,}", article_text)) >= 8
            and (len(article_terms) >= 4 or bool(article_numbers))
        ):
            return True
    return False


def record_is_aggregate_digest(title: str, record: dict[str, Any]) -> bool:
    """Reject navigation-led pages that combine several linked events as one item."""
    excerpt = reader_facing_text(
        record.get("excerpt") or record.get("evidence") or "",
        8000,
    )
    source_markers = sum(
        excerpt.lower().count(marker)
        for marker in (
            "情報源を見る",
            "ニュース -",
            "view source",
            "read source",
            "source:",
        )
    )
    digest_title = bool(
        re.search(
            r"(?:AI.{0,12}解説|値動きの背景|今の株価の理由|"
            r"news roundup|latest news|all the news|market summary)",
            title,
            flags=re.I,
        )
    )
    return source_markers >= 3 and digest_title


def record_is_routine_sports_schedule(
    category: dict[str, Any],
    title: str,
    record: dict[str, Any],
) -> bool:
    """Reject timetable-only sports pages while retaining material schedule changes."""
    if not category.get("allow_sports_results", False):
        return False
    excerpt = str(record.get("excerpt") or record.get("evidence") or "")
    text = f"{title} {excerpt[:5000]}"
    return bool(
        SPORTS_SCHEDULE_RE.search(text)
        and len(SPORTS_SCHEDULE_TIME_RE.findall(text)) >= 3
        and not SPORTS_SCHEDULE_CHANGE_RE.search(text)
    )


def record_is_low_importance_routine(
    category: dict[str, Any],
    title: str,
    record: dict[str, Any],
    issue_date: str,
) -> bool:
    """Reject clear recurring or low-value items before any model request."""
    excerpt = reader_facing_text(
        record.get("excerpt") or record.get("evidence") or "",
        2400,
    )
    text = f"{title} {excerpt}"
    if PHOTO_OR_MEDIA_VARIANT_RE.search(title) or SUSPICIOUS_MEDIA_TITLE_RE.search(
        title
    ):
        return True
    if (
        UNCONFIRMED_FUTURE_RE.search(title)
        and not CONFIRMED_FUTURE_OVERRIDE_RE.search(title)
    ):
        return True
    if ROUTINE_INVESTMENT_COMMENTARY_RE.search(text):
        return True
    if ROUTINE_RECAP_OR_COMMENTARY_RE.search(title):
        return True
    if ROUTINE_COMMERCIAL_OR_ADJACENT_RE.search(title):
        return True
    if HISTORICAL_REVIEW_RE.search(title):
        return True
    if ROUTINE_PREVIEW_RE.search(title):
        return True
    if (
        ROUTINE_MINOR_EVENT_RE.search(title)
        and not REALIZED_MATERIAL_CHANGE_RE.search(title)
    ):
        return True
    if ROUTINE_PERIODIC_UPDATE_RE.search(title):
        if re.search(r"約款|感染者", title) or not REALIZED_MATERIAL_CHANGE_RE.search(
            title
        ):
            return True
    if (
        ROUTINE_STRATEGY_OVERVIEW_RE.search(title)
        and not REALIZED_MATERIAL_CHANGE_RE.search(title)
    ):
        return True
    if re.search(r"\bmembers? profile\b|メンバー紹介", title, re.I):
        return True
    if ROUTINE_PERSONAL_LIFESTYLE_RE.search(title):
        return True
    if (
        ROUTINE_MARKET_TICK_RE.search(title)
        and not ROUTINE_MARKET_EXCEPTION_RE.search(title)
    ):
        return True
    category_label = str(category.get("label", ""))
    if (
        category_label == "SpaceX"
        and ROUTINE_SPACEX_LAUNCH_RE.search(title)
        and not SPACEX_LAUNCH_EXCEPTION_RE.search(title)
    ):
        return True
    entity_noise = ENTITY_SCOPE_NOISE_RE.get(category_label)
    if entity_noise is not None and entity_noise.search(title):
        return True
    if (
        category_label == "SoftBank"
        and record.get("source_class") == "discovered_media"
        and not re.search(
            r"(SoftBank|ソフトバンク|SBG|孫正義|Masayoshi Son|"
            r"\bArm (?:Holdings|CEO|chips?|shares?|stock|earnings|processors?)\b)",
            title,
            re.I,
        )
    ):
        return True
    try:
        issue_year = date.fromisoformat(issue_date).year
    except ValueError:
        issue_year = 0
    stale_years = {
        int(value)
        for value in re.findall(r"(?<!\d)(20\d{2})(?!\d)", title)
        if issue_year and int(value) < issue_year - 1
    }
    if stale_years and not REALIZED_MATERIAL_CHANGE_RE.search(title):
        return True
    if (
        str(category.get("label", "")) == "SpaceX"
        and ENTERTAINMENT_ARTIFACT_RE.search(text)
        and not SPACE_CONTEXT_RE.search(text)
    ):
        return True
    return False


def record_title_has_material_change(
    category: dict[str, Any],
    title: str,
    record: dict[str, Any],
) -> bool:
    """Require the headline itself to identify a realized update or result."""
    excerpt = reader_facing_text(
        record.get("excerpt") or record.get("evidence") or "",
        2400,
    )
    return bool(
        REALIZED_MATERIAL_CHANGE_RE.search(title)
        or MATERIAL_RESULT_TITLE_RE.search(title)
        or ACTUAL_EARNINGS_EVENT_RE.search(title)
        or (
            category.get("allow_sports_results", False)
            and SPORTS_RESULT_RE.search(title)
        )
        or (
            state_contract.ANALYSIS_HEADLINE_RE.search(title)
            and state_contract.ANALYSIS_REASONING_RE.search(excerpt)
        )
    )


def record_matches_macro_scope(
    category: dict[str, Any],
    title: str,
    record: dict[str, Any],
) -> bool:
    """Keep geographic macro items inside their configured region."""
    scope_re = MACRO_CATEGORY_SCOPE_RE.get(str(category.get("label", "")))
    if scope_re is None:
        return True
    material_text = editor_source_text(record, 1600)
    body_scope_re = MACRO_BODY_SCOPE_RE.get(str(category.get("label", "")))
    region_match = bool(
        scope_re.search(title)
        or (body_scope_re is not None and body_scope_re.search(material_text))
    )
    topic_re = MACRO_TOPIC_SCOPE_RE.get(str(category.get("label", "")))
    if ACTUAL_EARNINGS_EVENT_RE.search(title):
        return True
    if (
        str(category.get("label", "")) == "日本経済"
        and MATERIAL_EARNINGS_EXCEPTION_RE.search(title)
        and re.search(r"[一-龯ぁ-んァ-ヶ]", title)
    ):
        return True
    return bool(
        region_match
        and topic_re is not None
        and topic_re.search(f"{title} {material_text}")
    )


def headline_supports_distinct_summary(title: str) -> bool:
    """Return whether a headline states detail that can sit outside a shorter title."""
    text = canonical_article_match_text(title)
    numbers = re.findall(r"(?<![a-z])\d+(?:\.\d+)?(?![a-z])", text)
    material_numbers = [
        value
        for value in numbers
        if not re.fullmatch(r"(?:19|20)\d{2}", value)
    ]
    if material_numbers:
        return bool(PUBLICATION_EVENT_RE.search(text))
    if re.search(
        r"[、;；]|(?:ため|目的|向け|分野|領域|対象|条件|理由|背景|結果|"
        r"が続く|に続く|へ展開|まで拡大|を通じて)",
        text,
    ):
        return True
    connectors = re.findall(
        r"\b(?:with|to|for|after|while|across|using)\b",
        text,
    )
    return len(connectors) >= 2 and bool(
        {"with", "for", "while", "across", "using"} & set(connectors)
    )


def record_evidence_depth(title: str, record: dict[str, Any]) -> str:
    """Describe the strongest source-backed text available to the editor."""
    if record_has_material_body(title, record):
        return "body"
    excerpt = str(record.get("excerpt") or record.get("evidence") or "")
    if (
        record.get("source_class") == "discovered_media"
        and record.get("observed")
        and headline_supports_distinct_summary(title)
        and not state_contract.navigation_shell_text(f"{title} {excerpt}")
    ):
        return "headline"
    return "none"


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
        or record_is_delayed_untrusted_recap(record, issue_date)
    ):
        return False
    title = record_public_title(record)
    excerpt = reader_facing_text(record.get("excerpt") or record.get("evidence") or "", 2400)
    category_label = str(category.get("label", ""))
    if (
        not title
        or not excerpt
        or not editor_candidate_boundary(
            category_label,
            title,
            excerpt,
            source_label=str(record.get("label", "")),
        )
        or record_is_aggregate_digest(title, record)
        or record_is_routine_sports_schedule(category, title, record)
        or record_is_low_importance_routine(category, title, record, issue_date)
        or not record_title_has_material_change(category, title, record)
        or not record_matches_macro_scope(category, title, record)
        or record_evidence_depth(title, record) == "none"
    ):
        return False
    return True


def publication_evidence_records(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    for record in select_clustered_evidence(category, records):
        url = str(record.get("url", ""))
        if (
            url in seen_urls
            or not publication_evidence_record(category, issue_date, record)
        ):
            continue
        seen_urls.add(url)
        selected.append(record)
    return selected


def editor_evidence_records(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> list[tuple[str, dict[str, Any]]]:
    """Assign stable request-local ids to every publishable evidence record."""
    return [
        (f"e{index:03d}", record)
        for index, record in enumerate(
            publication_evidence_records(category, issue_date, records),
            start=1,
        )
    ]


def normalized_financial_amounts(value: str) -> tuple[list[tuple[str, float]], str]:
    amounts: list[tuple[str, float]] = []
    spans: list[tuple[int, int]] = []
    japanese_number = (
        r"(?:\d[\d,]*(?:\.\d+)?\s*(?:兆|億|万|千)\s*)+"
        r"(?:\d[\d,]*(?:\.\d+)?)?"
    )
    japanese = re.compile(
        rf"(?P<number>{japanese_number})\s*(?P<currency>ドル|円|ユーロ|ポンド)"
    )
    japanese_range = re.compile(
        rf"(?P<left>{japanese_number})\s*[～〜–—-]\s*"
        rf"(?P<right>{japanese_number})\s*(?P<currency>ドル|円|ユーロ|ポンド)"
    )
    unit_scale = {"兆": 1e12, "億": 1e8, "万": 1e4, "千": 1e3}
    currency_map = {"ドル": "USD", "円": "JPY", "ユーロ": "EUR", "ポンド": "GBP"}

    def japanese_amount(raw: str) -> float:
        total = sum(
            float(number.replace(",", "")) * unit_scale[unit]
            for number, unit in re.findall(
                r"(\d[\d,]*(?:\.\d+)?)\s*(兆|億|万|千)", raw
            )
        )
        trailing = re.search(r"(?:兆|億|万|千)\s*(\d[\d,]*(?:\.\d+)?)\s*$", raw)
        return total + (
            float(trailing.group(1).replace(",", "")) if trailing else 0.0
        )

    for match in japanese_range.finditer(value):
        currency = currency_map[match.group("currency")]
        amounts.extend(
            [
                (currency, japanese_amount(match.group("left"))),
                (currency, japanese_amount(match.group("right"))),
            ]
        )
        spans.append(match.span())
    for match in japanese.finditer(value):
        if any(match.start() < end and match.end() > start for start, end in spans):
            continue
        amounts.append(
            (
                currency_map[match.group("currency")],
                japanese_amount(match.group("number")),
            )
        )
        spans.append(match.span())
    plain_japanese = re.compile(
        r"(?P<number>\d[\d,]*(?:[.．]\d+)?)\s*"
        r"(?P<currency>ドル|円|ユーロ|ポンド)"
    )
    for match in plain_japanese.finditer(value):
        if any(match.start() < end and match.end() > start for start, end in spans):
            continue
        amounts.append(
            (
                currency_map[match.group("currency")],
                float(match.group("number").replace(",", "").replace("．", ".")),
            )
        )
        spans.append(match.span())
    english = re.compile(
        r"(?:(?P<symbol>[$€£])\s*)?"
        r"(?P<number>\d[\d,]*(?:\.\d+)?)\s*"
        r"(?P<unit>trillion|billion|million)"
        r"(?:\s*(?P<word>dollars?|euros?|pounds?))?",
        re.I,
    )
    english_scale = {"trillion": 1e12, "billion": 1e9, "million": 1e6}
    english_currency = {
        "$": "USD",
        "€": "EUR",
        "£": "GBP",
        "dollar": "USD",
        "dollars": "USD",
        "euro": "EUR",
        "euros": "EUR",
        "pound": "GBP",
        "pounds": "GBP",
    }
    for match in english.finditer(value):
        marker = (match.group("symbol") or match.group("word") or "").lower()
        if not marker:
            continue
        amounts.append(
            (
                english_currency.get(marker, "UNSPECIFIED"),
                float(match.group("number").replace(",", ""))
                * english_scale[match.group("unit").lower()],
            )
        )
        spans.append(match.span())
    plain_english = re.compile(
        r"(?:(?P<symbol>[$€£])\s*(?P<symbol_number>\d[\d,]*(?:\.\d+)?)|"
        r"(?P<word_number>\d[\d,]*(?:\.\d+)?)\s*"
        r"(?P<word>dollars?|euros?|pounds?))",
        re.I,
    )
    for match in plain_english.finditer(value):
        if any(match.start() < end and match.end() > start for start, end in spans):
            continue
        marker = (match.group("symbol") or match.group("word") or "").lower()
        number = match.group("symbol_number") or match.group("word_number") or "0"
        amounts.append(
            (
                english_currency[marker],
                float(number.replace(",", "")),
            )
        )
        spans.append(match.span())
    stripped = list(value)
    for start, end in spans:
        stripped[start:end] = " " * (end - start)
    return amounts, "".join(stripped)


def numeric_literals(value: str) -> set[float]:
    value = value.replace("．", ".").replace("，", ",")
    value = re.sub(
        r"(?<!\d)(\d+)分(\d{1,2})秒(\d{1,3})(?!\d)",
        lambda match: f"{match.group(1)} {match.group(2)}.{match.group(3)}",
        value,
    )
    value = re.sub(
        r"(?<![\d,])(\d{1,3}),(\d{1,2})(?![\d,])",
        lambda match: f"{match.group(1)}.{match.group(2)}",
        value,
    )
    return {
        float(number.replace(",", ""))
        for number in re.findall(r"\d[\d,]*(?:\.\d+)?", value)
    }


def normalized_scaled_numbers(value: str) -> tuple[set[float], str]:
    pattern = re.compile(
        r"(?<![\d.])((?:\d[\d,]*(?:\.\d+)?\s*(?:兆|億|万|千)\s*)+)"
    )
    scale = {"兆": 1e12, "億": 1e8, "万": 1e4, "千": 1e3}
    numbers: set[float] = set()
    stripped = list(value)
    for match in pattern.finditer(value):
        numbers.add(
            sum(
                float(number.replace(",", "")) * scale[unit]
                for number, unit in re.findall(
                    r"(\d[\d,]*(?:\.\d+)?)\s*(兆|億|万|千)",
                    match.group(1),
                )
            )
        )
        stripped[match.start() : match.end()] = " " * (match.end() - match.start())
    english_pattern = re.compile(
        r"(?<![\d.])(\d[\d,]*(?:\.\d+)?)\s*[-–—]?\s*"
        r"(trillion|billion|million|thousand)\b",
        re.I,
    )
    english_scale = {
        "trillion": 1e12,
        "billion": 1e9,
        "million": 1e6,
        "thousand": 1e3,
    }
    for match in english_pattern.finditer(value):
        numbers.add(
            float(match.group(1).replace(",", ""))
            * english_scale[match.group(2).lower()]
        )
        stripped[match.start() : match.end()] = " " * (match.end() - match.start())
    return numbers, "".join(stripped)


def numeric_claims(value: str) -> set[float]:
    scaled, remainder = normalized_scaled_numbers(value)
    short_years: set[float] = set()
    short_year_spans: list[tuple[int, int]] = []
    for match in re.finditer(r"(?<!\d)(\d{2})年(?!間)", remainder):
        year = int(match.group(1))
        short_years.add(float((2000 if year <= 49 else 1900) + year))
        short_year_spans.append(match.span())
    if short_year_spans:
        stripped = list(remainder)
        for start, end in short_year_spans:
            stripped[start:end] = " " * (end - start)
        remainder = "".join(stripped)
    period_components = {
        float(component)
        for match in re.finditer(
            r"(?<!\d)((?:19|20)\d{2})[./-](0?[1-9]|1[0-2])(?=$|[./\-\s])",
            remainder,
        )
        for component in match.groups()
    }
    word_numbers = {
        float(ENGLISH_NUMBER_WORD_VALUES[match.group(0).lower()])
        for match in re.finditer(
            r"\b(?:" + "|".join(ENGLISH_NUMBER_WORD_VALUES) + r")\b",
            remainder,
            flags=re.I,
        )
    }
    month_numbers = {
        float(ENGLISH_MONTH_VALUES[match.group(0).lower()])
        for match in re.finditer(
            r"\b(?:" + "|".join(ENGLISH_MONTH_VALUES) + r")\b",
            remainder,
            flags=re.I,
        )
    }
    return (
        scaled
        | short_years
        | numeric_literals(remainder)
        | word_numbers
        | month_numbers
        | period_components
    )


def numeric_claim_supported(
    claimed: float,
    evidence_numbers: set[float],
    *,
    approximate: bool,
) -> bool:
    if claimed in evidence_numbers:
        return True
    if not approximate or claimed == 0:
        return False
    return any(
        abs(claimed - observed) <= max(1.0, abs(observed) * 0.01)
        for observed in evidence_numbers
    )


def source_requires_japanese_translation(value: str) -> bool:
    """Recognize source prose that cannot be lexically compared with Japanese copy."""
    kana = len(re.findall(r"[\u3040-\u30ff]", value))
    if kana >= 6:
        return False
    latin = len(re.findall(r"[A-Za-z]", value))
    hangul = len(re.findall(r"[\uac00-\ud7af]", value))
    han = len(re.findall(r"[\u3400-\u9fff]", value))
    return latin >= 24 or hangul >= 12 or (kana == 0 and han >= 18)


def fact_supported_by_records(
    fact: str,
    source_records: list[dict[str, Any]],
) -> bool:
    fact_amounts, fact_without_amounts = normalized_financial_amounts(fact)
    fact_numbers = numeric_claims(fact_without_amounts)
    approximate_numbers = bool(re.search(r"(?:約|およそ|ほぼ|程度|以上|超)", fact))
    for record in source_records:
        title = record_public_title(record)
        body = reader_facing_text(
            str(record.get("excerpt") or record.get("evidence") or ""),
            8500,
        )
        evidence = reader_facing_text(
            f"{record.get('title', '')} {body}",
            8500,
        )
        evidence_amounts, evidence_without_amounts = normalized_financial_amounts(
            evidence
        )
        evidence_numbers = numeric_claims(evidence_without_amounts)
        if any(
            not numeric_claim_supported(
                number,
                evidence_numbers,
                approximate=approximate_numbers,
            )
            for number in fact_numbers
        ):
            continue
        if any(
            not any(
                (fact_currency == evidence_currency or "UNSPECIFIED" in {fact_currency, evidence_currency})
                and abs(fact_amount - evidence_amount)
                <= max(1.0, abs(fact_amount) * 1e-9)
                for evidence_currency, evidence_amount in evidence_amounts
            )
            for fact_currency, fact_amount in fact_amounts
        ):
            continue
        if source_requires_japanese_translation(evidence):
            fact_anchors = {
                value.casefold()
                for value in re.findall(r"[A-Za-z][A-Za-z0-9.+-]{1,}", fact)
                if value.casefold()
                not in {"ai", "the", "and", "for", "with", "from"}
            }
            evidence_anchors = {
                value.casefold()
                for value in re.findall(
                    r"[A-Za-z][A-Za-z0-9.+-]{1,}", evidence
                )
            }
            if (
                bool(fact_numbers)
                or bool(fact_amounts)
                or (
                    record_has_material_body(title, record)
                    and bool(fact_anchors & evidence_anchors)
                )
            ):
                return True
            continue
        if (
            state_contract.materially_same_fact(fact, title)
            or state_contract.text_overlap(fact, evidence) >= 1
        ):
            return True
    return False


def facts_add_information_beyond_title(title: str, facts: list[str]) -> bool:
    return bool(facts) and any(
        state_contract.fact_adds_information(title, fact) for fact in facts
    )


def support_quote_from_record(fact: str, record: dict[str, Any]) -> str:
    """Select a deterministic source span for an editor fact."""
    raw_title = compact_text(str(record.get("title", "")), 320)
    raw_body = compact_text(
        str(record.get("excerpt") or record.get("evidence") or ""),
        8500,
    )
    candidates = list(
        dict.fromkeys(
            value
            for value in [raw_title, *sentence_parts(raw_body)]
            if 8 <= len(value) <= 320
        )
    )
    if not candidates:
        return compact_text(raw_title or raw_body, 320)
    fact_numbers = set(re.findall(r"\d+(?:\.\d+)?", fact))

    def relevance(value: str) -> tuple[int, int, int, int]:
        value_numbers = set(re.findall(r"\d+(?:\.\d+)?", value))
        return (
            len(fact_numbers & value_numbers),
            state_contract.text_overlap(fact, value),
            int(state_contract.materially_same_fact(fact, value)),
            min(len(value), 180),
        )

    return max(candidates, key=relevance)


HTTP_CHARSET_ALIASES = {
    # Microsoft/IANA aliases that are emitted by Japanese publisher servers
    # but are not registered codec names in every Python runtime.
    "cp51932": "euc_jp",
    "windows-31j": "cp932",
    "x-euc-jp": "euc_jp",
    "x-sjis": "cp932",
}


def decode_http_text(raw: bytes, content_type: str) -> str:
    """Decode a response without letting one vendor charset abort collection."""
    charset_match = re.search(
        r"charset\s*=\s*[\"']?([A-Za-z0-9._-]+)",
        content_type,
        re.I,
    )
    declared = charset_match.group(1) if charset_match else "utf-8"
    normalized = declared.casefold().replace("_", "-")
    charset = HTTP_CHARSET_ALIASES.get(normalized, declared)
    try:
        return raw.decode(charset, errors="replace")
    except LookupError:
        # Unknown names are external metadata failures, not a reason to lose
        # all categories.  Prefer lossless decoding; replacement is the final
        # bounded fallback only when no common Web encoding fits.
        for fallback in ("utf-8", "cp932", "euc_jp", "iso2022_jp"):
            try:
                return raw.decode(fallback)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")


def page_text(raw: bytes, content_type: str) -> tuple[str, str]:
    text = decode_http_text(raw, content_type)
    if "<html" not in text[:1000].lower() and "<!doctype" not in text[:1000].lower():
        plain = compact_text(text, 8000)
        return plain[:180], plain
    structured = structured_article_text(text)
    if structured:
        title, body = structured
        if len(body) < 600:
            parser = ArticleContainerParser()
            parser.feed(text)
            container_body = parser.text()
            if len(container_body) > len(body):
                body = (
                    container_body
                    if len(body) < 120
                    else compact_text(f"{body} {container_body}", 8000)
                )
        return title, body
    title_match = re.search(
        r"<title[^>]*>(.*?)</title>",
        text,
        flags=re.I | re.S,
    )
    title = compact_text(title_match.group(1), 180) if title_match else ""
    parser = VisibleTextParser()
    parser.feed(text)
    return title, compact_text(" ".join(parser.parts), 8000)


def request_bytes(url: str, timeout: int = 15) -> tuple[bytes, str, str]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml,application/xml,text/plain,*/*",
            "User-Agent": USER_AGENT,
        },
    )
    with NETWORK_SEMAPHORE:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(350_000)
            content_type = response.headers.get("Content-Type", "")
            return raw, content_type, response.geturl()


def post_form_bytes(
    url: str,
    values: dict[str, str],
    timeout: int = 15,
) -> tuple[bytes, str, str]:
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode("utf-8"),
        headers={
            "Accept": "*/*",
            "Content-Type": "application/x-www-form-urlencoded;charset=UTF-8",
            "User-Agent": USER_AGENT,
        },
        method="POST",
    )
    with NETWORK_SEMAPHORE:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(100_000)
            content_type = response.headers.get("Content-Type", "")
            return raw, content_type, response.geturl()


def jina_url(url: str) -> str:
    return "https://r.jina.ai/http://" + re.sub(r"^https?://", "", url)


class GoogleNewsArticleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.params: tuple[str, str, str] | None = None

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag != "div" or self.params is not None:
            return
        values = dict(attrs)
        article_id = values.get("data-n-a-id")
        timestamp = values.get("data-n-a-ts")
        signature = values.get("data-n-a-sg")
        if article_id and timestamp and signature:
            self.params = (article_id, timestamp, signature)


def google_news_decoding_params(params_url: str) -> tuple[str, str, str] | None:
    request = urllib.request.Request(
        params_url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Encoding": "gzip",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=12) as response:
        content_type = response.headers.get("Content-Type", "")
        raw = response.read(500_000)
        if response.headers.get("Content-Encoding", "").lower() == "gzip":
            raw = gzip.decompress(raw)
        parser = GoogleNewsArticleParser()
        parser.feed(decode_http_text(raw, content_type))
        return parser.params


def _google_news_publisher_url_once(source_url: str) -> str | None:
    parsed = urllib.parse.urlparse(source_url)
    parts = [part for part in parsed.path.split("/") if part]
    if parsed.netloc.lower() != "news.google.com" or len(parts) < 2:
        return None
    if parts[-2] not in {"articles", "read"}:
        return None
    query = urllib.parse.parse_qs(parsed.query)
    query.update({"hl": ["en-US"], "gl": ["US"], "ceid": ["US:en"]})
    params_url = urllib.parse.urlunparse(
        parsed._replace(query=urllib.parse.urlencode(query, doseq=True))
    )
    try:
        params = google_news_decoding_params(params_url)
        if params is None:
            return None
        resolved_id, timestamp, signature = params
        inner = [
            "garturlreq",
            [
                [
                    "X",
                    "X",
                    ["X", "X"],
                    None,
                    None,
                    1,
                    1,
                    "US:en",
                    None,
                    1,
                    None,
                    None,
                    None,
                    None,
                    None,
                    0,
                    1,
                ],
                "X",
                "X",
                1,
                [1, 1, 1],
                1,
                1,
                None,
                0,
                0,
                None,
                0,
            ],
            resolved_id,
            int(timestamp),
            signature,
        ]
        envelope = [
            [
                [
                    "Fbv4je",
                    json.dumps(inner, ensure_ascii=False, separators=(",", ":")),
                    None,
                    "generic",
                ]
            ]
        ]
        raw, _, _ = post_form_bytes(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            {"f.req": json.dumps(envelope, ensure_ascii=False, separators=(",", ":"))},
            timeout=12,
        )
        response_text = raw.decode("utf-8", errors="replace")
        for line in response_text.splitlines():
            line = line.strip()
            if not line.startswith("["):
                continue
            response = json.loads(line)
            for entry in response:
                if (
                    isinstance(entry, list)
                    and len(entry) >= 3
                    and entry[0] == "wrb.fr"
                    and entry[1] == "Fbv4je"
                    and isinstance(entry[2], str)
                ):
                    decoded = json.loads(entry[2])
                    publisher_url = decoded[1] if len(decoded) > 1 else None
                    if isinstance(publisher_url, str) and publisher_url.startswith(
                        ("http://", "https://")
                    ):
                        return publisher_url
    except (
        OSError,
        TimeoutError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
        urllib.error.URLError,
    ):
        return None
    return None


def google_news_publisher_url(source_url: str) -> str | None:
    """Resolve a Google News article id, retrying only a failed signed request."""
    for _ in range(2):
        resolved = _google_news_publisher_url_once(source_url)
        if resolved:
            return resolved
    return None


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


def discovery_identity_queries(
    category: dict[str, Any],
    extra_terms: list[str] | None = None,
    *,
    replace_with_extra: bool = False,
) -> list[str]:
    label = str(category["label"])
    terms = (
        list(extra_terms or [])
        if replace_with_extra and extra_terms
        else [*(category_identity_terms(label) or (label,)), *(extra_terms or [])]
    )
    useful = list(dict.fromkeys(str(term) for term in terms if str(term).strip()))
    return [
        " OR ".join(f'"{term}"' if " " in term else term for term in group)
        for index in range(0, len(useful), 10)
        for group in [useful[index : index + 10]]
        if group
    ]


def configured_discovery_locales() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    config = load_object(COVERAGE_CONFIG).get("discovery_locales", {})
    if not isinstance(config, dict):
        return ([{"id": "ja-JP", "hl": "ja", "gl": "JP", "ceid": "JP:ja"}], {})
    defaults = [value for value in config.get("default", []) if isinstance(value, dict)]
    category_horizon = config.get("category_horizon", {})
    return defaults, category_horizon if isinstance(category_horizon, dict) else {}


def discovery_queries(category: dict[str, Any], issue_date: str) -> list[dict[str, Any]]:
    """Build bounded searches that prove each watch topic was actually queried."""
    identities = discovery_identity_queries(category)
    default_locales, local_horizon = configured_discovery_locales()
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
            for identity_index, identity in enumerate(identities, start=1):
                for locale in default_locales:
                    locale_id = str(locale.get("id") or "default")
                    queries.append(
                        {
                            "query_id": (
                                f"topic:{topic_id}:{index // 20 + 1}:"
                                f"identity-{identity_index}:{locale_id}"
                            ),
                            "purpose": "watch_topic",
                            "watch_topic_ids": [topic_id],
                            "query": f"({identity}) ({' OR '.join(group)}) when:3d",
                            "provider": "google_news_rss",
                            "channel": "web",
                            "locale": locale,
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
        for identity_index, identity in enumerate(identities, start=1):
            for locale in default_locales:
                locale_id = str(locale.get("id") or "default")
                queries.append(
                    {
                        "query_id": (
                            f"horizon:material-change:{index // 20 + 1}:"
                            f"identity-{identity_index}:{locale_id}"
                        ),
                        "purpose": "horizon",
                        "watch_topic_ids": [],
                        "query": f"({identity}) ({' OR '.join(group)}) when:3d",
                        "provider": "google_news_rss",
                        "channel": "web",
                        "locale": locale,
                    }
                )

    category_locales = [
        value
        for value in local_horizon.get(str(category.get("label")), [])
        if isinstance(value, dict)
    ]
    configured_locales = {
        str(value.get("id")) for value in category_locales if value.get("id")
    }
    required_locales = {
        str(value)
        for value in category.get("required_local_horizon_locales", [])
        if str(value).strip()
    }
    missing_locales = required_locales - configured_locales
    if missing_locales:
        raise ValueError(
            f"{category.get('label')} has unconfigured required local horizons: "
            + ", ".join(sorted(missing_locales))
        )
    for locale in category_locales:
        locale_id = str(locale.get("id") or "local")
        local_identities = discovery_identity_queries(
            category,
            [str(value) for value in locale.get("identity_terms", [])],
            replace_with_extra=True,
        )
        changes = [str(value) for value in locale.get("change_terms", []) if str(value).strip()]
        if changes:
            for identity_index, identity in enumerate(local_identities, start=1):
                queries.append(
                    {
                        "query_id": (
                            f"horizon:local-language:{locale_id}:"
                            f"identity-{identity_index}"
                        ),
                        "purpose": "horizon",
                        "watch_topic_ids": [],
                        "query": f"({identity}) ({' OR '.join(changes)}) when:3d",
                        "provider": "google_news_rss",
                        "channel": "web",
                        "locale": locale,
                    }
                )

    for channel, domains in INDEXED_CHANNEL_DOMAINS.items():
        sites = " OR ".join(f"site:{domain}" for domain in domains)
        for change_index in range(0, len(DISCOVERY_CHANGE_TERMS), 16):
            indexed_terms = " OR ".join(
                DISCOVERY_CHANGE_TERMS[change_index : change_index + 16]
            )
            for identity_index, identity in enumerate(identities, start=1):
                queries.append(
                    {
                        "query_id": (
                            f"horizon:indexed:{channel}:"
                            f"change-{change_index // 16 + 1}:identity-{identity_index}"
                        ),
                        "purpose": "horizon",
                        "watch_topic_ids": [],
                        "query": f"({sites}) ({identity}) ({indexed_terms})",
                        "provider": "bing_rss",
                        "channel": channel,
                    }
                )
    return queries


def depth_recovery_queries(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build a small second search pass only for evidence-thin watch topics."""
    topics = [
        topic
        for topic in category.get("watch_topics", [])
        if isinstance(topic, dict) and topic.get("id")
    ]
    if not topics:
        return []
    eligible = [
        record
        for record in records
        if publication_evidence_record(category, issue_date, record)
    ]
    body_records = [
        record
        for record in eligible
        if record_evidence_depth(record_public_title(record), record) == "body"
        and record_has_trusted_editor_source(record)
    ]
    body_topics = {
        str(topic_id)
        for record in body_records
        for topic_id in record.get("watch_topic_ids", [])
        if str(topic_id)
    }
    body_events = {
        record_cluster_key(record) or str(record.get("url", ""))
        for record in body_records
    }
    headline_topics = {
        str(topic_id)
        for record in eligible
        if record_evidence_depth(record_public_title(record), record) == "headline"
        for topic_id in record.get("watch_topic_ids", [])
        if str(topic_id)
    }
    weak_topics = [topic for topic in topics if str(topic["id"]) not in body_topics]
    if not weak_topics:
        return []
    weak_threshold = max(1, (len(topics) + 1) // 2)
    if (
        len(body_events) >= 2
        and len(weak_topics) < weak_threshold
        and not headline_topics
    ):
        return []

    configured_max_queries = os.getenv("NIGHT_SIGNAL_DEPTH_RECOVERY_MAX_QUERIES")
    try:
        max_queries = (
            max(0, int(configured_max_queries))
            if configured_max_queries is not None
            else len(weak_topics) * 2
        )
    except ValueError:
        max_queries = len(weak_topics) * 2
    if max_queries == 0:
        return []
    identities = discovery_identity_queries(category)
    if not identities:
        return []
    prioritized = sorted(
        weak_topics,
        key=lambda topic: (
            str(topic["id"]) not in headline_topics,
            str(topic["id"]),
        ),
    )
    candidates: list[list[dict[str, Any]]] = []
    for topic_index, topic in enumerate(prioritized):
        topic_id = str(topic["id"])
        official_hosts = list(
            dict.fromkeys(
                normalized_source_host(source.get("url"))
                for source in configured_official_depth_sources()
                .get(str(category.get("label", "")), {})
                .get(topic_id, [])
                if normalized_source_host(source.get("url"))
            )
        )
        publishers = discovery_publishers_for_topic(
            str(category.get("label", "")), topic_id
        )
        specialist_hosts = list(
            dict.fromkeys(
                normalized_source_host(publisher.get("url"))
                for publisher in publishers
                if publisher.get("source_class") == "specialist_media"
                and normalized_source_host(publisher.get("url"))
            )
        )
        major_hosts = list(
            dict.fromkeys(
                normalized_source_host(publisher.get("url"))
                for publisher in publishers
                if publisher.get("source_class") == "major_media"
                and normalized_source_host(publisher.get("url"))
            )
        )
        terms = list(
            dict.fromkeys(
                str(term).strip()
                for term in [*topic.get("terms", []), *topic.get("event_classes", [])]
                if str(term).strip()
            )
        )
        topic_specs: list[dict[str, Any]] = []
        identity = identities[topic_index % len(identities)]

        def targeted_spec(kind: str, host: str) -> dict[str, Any]:
            return {
                "query_id": f"depth:{kind}:{topic_id}:bing",
                "purpose": "watch_topic",
                "watch_topic_ids": [topic_id],
                "query": (
                    f"site:{host} ({identity}) "
                    f"({' OR '.join(terms[:6])}) when:3d"
                ),
                "provider": "bing_rss",
                "fallback_provider": "google_news_rss",
                "channel": "web",
                "allowed_hosts": [host],
                "target_source_class": kind,
            }

        if terms and official_hosts:
            topic_specs.append(
                targeted_spec(
                    "official",
                    official_hosts[0],
                )
            )
        if terms and specialist_hosts:
            topic_specs.append(
                targeted_spec(
                    "specialist_media",
                    specialist_hosts[0],
                )
            )
        if terms and len(topic_specs) < 2 and major_hosts:
            topic_specs.append(
                targeted_spec(
                    "major_media",
                    major_hosts[0],
                )
            )
        if terms and len(topic_specs) < 2:
            topic_specs.append(
                {
                    "query_id": f"depth:open-web:{topic_id}:bing",
                    "purpose": "watch_topic",
                    "watch_topic_ids": [topic_id],
                    "query": f"({identity}) ({' OR '.join(terms[:6])}) when:3d",
                    "provider": "bing_rss",
                    "channel": "web",
                }
            )
        candidates.append(topic_specs)
    # Round-robin gives every weak watch topic one diverse query before a
    # second query is spent on any one topic.
    selected: list[dict[str, Any]] = []
    for round_index in range(2):
        for topic_specs in candidates:
            if round_index < len(topic_specs):
                selected.append(topic_specs[round_index])
            if len(selected) >= max_queries:
                return selected
    return selected


def news_queries(category: dict[str, Any], issue_date: str) -> list[str]:
    return [str(spec["query"]) for spec in discovery_queries(category, issue_date)]


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


def candidate_matches_publisher(record: dict[str, Any], candidate_url: str) -> bool:
    expected = urllib.parse.urlparse(str(record.get("publisher_url", ""))).netloc.lower()
    candidate = urllib.parse.urlparse(candidate_url).netloc.lower()
    expected = expected.removeprefix("www.")
    candidate = candidate.removeprefix("www.")
    if not expected:
        return True
    return candidate == expected or candidate.endswith(f".{expected}")


def reader_resolved_discovery_url(candidate_url: str, resolved_url: str) -> bool:
    candidate_host = urllib.parse.urlparse(candidate_url).netloc.lower()
    resolved_host = urllib.parse.urlparse(resolved_url).netloc.lower()
    return (
        candidate_host == "news.google.com"
        or candidate_host.endswith(".news.google.com")
    ) and resolved_host == "r.jina.ai"


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


def url_document_date(value: str) -> date | None:
    match = re.search(
        r"/(20\d{2})/(0?[1-9]|1[0-2])/(0?[1-9]|[12]\d|3[01])(?:/|$)",
        str(value),
    )
    if not match:
        return None
    try:
        return date(*(int(part) for part in match.groups()))
    except ValueError:
        return None


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
    url_date = url_document_date(candidate_url)
    if document_date and abs((discovery_date - document_date).days) > 7:
        return False
    if url_date and abs((discovery_date - url_date).days) > 7:
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


def explicit_title_event_dates(value: str, reference: date) -> set[date]:
    """Extract explicit event dates from a headline without treating data periods as dates."""
    text = normalized_ocr_digits(value)
    found: set[date] = set()
    covered: list[tuple[int, int]] = []
    full_patterns = (
        r"(?<!\d)(20\d{2})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        r"(?<!\d)(20\d{2})[-/.](\d{1,2})[-/.](\d{1,2})(?!\d)",
    )
    for pattern in full_patterns:
        for match in re.finditer(pattern, text):
            try:
                found.add(date(*(int(part) for part in match.groups())))
                covered.append(match.span())
            except ValueError:
                continue

    def overlaps_full_date(span: tuple[int, int]) -> bool:
        return any(start <= span[0] and span[1] <= end for start, end in covered)

    month_days: set[tuple[int, int]] = set()
    short_patterns = (
        r"(?<!\d)(\d{1,2})\s*月\s*(\d{1,2})\s*日",
        r"(?<!\d)(\d{1,2})/(\d{1,2})\s*(?:付|公開|発表|時点|号|開催|配信|発売|開始)",
    )
    for pattern in short_patterns:
        for match in re.finditer(pattern, text):
            if overlaps_full_date(match.span()):
                continue
            month_days.add((int(match.group(1)), int(match.group(2))))

    english_months = {
        name.casefold(): number
        for number, names in enumerate(
            (
                (),
                ("January", "Jan"),
                ("February", "Feb"),
                ("March", "Mar"),
                ("April", "Apr"),
                ("May",),
                ("June", "Jun"),
                ("July", "Jul"),
                ("August", "Aug"),
                ("September", "Sep", "Sept"),
                ("October", "Oct"),
                ("November", "Nov"),
                ("December", "Dec"),
            )
        )
        for name in names
    }
    english_pattern = re.compile(
        r"\b(" + "|".join(re.escape(name) for name in english_months) + r")\.?\s+"
        r"(\d{1,2})(?:st|nd|rd|th)?\b",
        re.I,
    )
    for match in english_pattern.finditer(text):
        month_days.add((english_months[match.group(1).casefold()], int(match.group(2))))

    for month, day in month_days:
        candidates: list[date] = []
        for year in (reference.year - 1, reference.year, reference.year + 1):
            try:
                candidates.append(date(year, month, day))
            except ValueError:
                pass
        if candidates:
            found.add(min(candidates, key=lambda candidate: abs(candidate - reference)))
    return found


def record_explicit_event_dates(
    record: dict[str, Any],
    issue_day: date,
) -> set[date]:
    """Extract dates that the article itself ties to the reported event."""
    lead = reader_facing_text(
        str(record.get("excerpt") or record.get("evidence") or ""),
        620,
    )
    return explicit_title_event_dates(
        f"{record_public_title(record)} {lead}",
        issue_day,
    )


def record_is_delayed_untrusted_recap(
    record: dict[str, Any],
    issue_date: str,
) -> bool:
    """Reject a late secondary retelling while preserving primary and material data."""
    if (
        str(record.get("source_class", "")) != "discovered_media"
        or record_has_trusted_editor_source(record)
    ):
        return False
    try:
        issue_day = date.fromisoformat(issue_date)
    except ValueError:
        return True
    title = record_public_title(record)
    excerpt = reader_facing_text(
        str(record.get("excerpt") or record.get("evidence") or ""),
        1200,
    )
    if (
        not PUBLICATION_EVENT_RE.search(title)
        or ACTUAL_EARNINGS_EVENT_RE.search(title)
        or MATERIAL_EARNINGS_EXCEPTION_RE.search(title)
        or ROUTINE_MARKET_EXCEPTION_RE.search(title)
        or (
            state_contract.ANALYSIS_HEADLINE_RE.search(title)
            and state_contract.ANALYSIS_REASONING_RE.search(excerpt)
        )
    ):
        return False
    event_dates = record_explicit_event_dates(record, issue_day)
    past_dates = {
        event_day
        for event_day in event_dates
        if event_day <= issue_day
    }
    return bool(
        past_dates
        and all((issue_day - event_day).days > 2 for event_day in past_dates)
    )


def record_document_is_current(record: dict[str, Any], issue_date: str) -> bool:
    try:
        issue_day = date.fromisoformat(issue_date)
    except ValueError:
        return False
    text = f"{record.get('title', '')} {record.get('excerpt', '')}"
    title_dates = explicit_title_event_dates(str(record.get("title", "")), issue_day)
    if title_dates and all(
        event_date <= issue_day and (issue_day - event_date).days > 7
        for event_date in title_dates
    ):
        return False
    lead = reader_facing_text(str(record.get("excerpt", "")), 520)
    lead_dates = explicit_title_event_dates(lead, issue_day)
    if (
        not title_dates
        and RECAP_EXPLAINER_RE.search(str(record.get("title", "")))
        and lead_dates
        and all(
            event_date <= issue_day and (issue_day - event_date).days > 7
            for event_date in lead_dates
        )
    ):
        return False
    document_date = embedded_document_date(text)
    url_date = url_document_date(str(record.get("url", "")))
    if document_date and not 0 <= (issue_day - document_date).days <= 7:
        return False
    if url_date and not 0 <= (issue_day - url_date).days <= 7:
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
    candidate_host = urllib.parse.urlparse(candidate_url).netloc.lower()
    discovery_redirect = candidate_host == "news.google.com" or candidate_host.endswith(
        ".news.google.com"
    )
    if not discovery_redirect and not candidate_matches_publisher(record, candidate_url):
        return None
    publisher_candidate = (
        google_news_publisher_url(candidate_url)
        if discovery_redirect
        else candidate_url
    )
    source_candidates = list(
        dict.fromkeys(
            [
                *([publisher_candidate] if publisher_candidate else []),
                candidate_url,
            ]
        )
    )
    attempts = [
        (source_candidate, attempt)
        for source_candidate in source_candidates
        for attempt in (source_candidate, jina_url(source_candidate))
    ]
    for source_candidate, attempt in attempts:
        try:
            page_raw, content_type, resolved_url = request_bytes(attempt, timeout=12)
            page_title, body = page_text(page_raw, content_type)
        except (OSError, TimeoutError, urllib.error.URLError, ValueError):
            continue
        reader_fetch = (
            urllib.parse.urlparse(resolved_url).netloc.lower() == "r.jina.ai"
        )
        reader_resolved_discovery = (
            source_candidate == candidate_url
            and reader_resolved_discovery_url(candidate_url, resolved_url)
        )
        effective_url = (
            source_candidate
            if reader_fetch
            else resolved_url
        )
        if not reader_resolved_discovery and not candidate_matches_publisher(
            record, effective_url
        ):
            continue
        body = compact_text(body, 8000)
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
                page_title or result_title,
            )
            or not document_matches_discovery(
                record,
                effective_url,
                page_title or result_title,
                combined,
            )
        ):
            continue
        parsed = urllib.parse.urlparse(effective_url)
        page_date = embedded_document_date(page_raw.decode("utf-8", errors="ignore"))
        resolved_label = (
            str(record.get("label", ""))
            if reader_resolved_discovery
            else parsed.netloc.lower().removeprefix("www.")
        )
        publisher_url = str(record.get("publisher_url", ""))
        if not reader_resolved_discovery and parsed.scheme in {"http", "https"} and parsed.netloc:
            publisher_url = f"{parsed.scheme}://{parsed.netloc}"
        return {
            **record,
            "label": resolved_label or str(record.get("label", "")),
            "url": effective_url,
            "publisher_url": publisher_url,
            "published_date": page_date.isoformat() if page_date else record.get("published_date"),
            "original_discovery_url": str(record.get("url", "")),
            "title": original_title,
            "excerpt": combined,
            "evidence": (
                f"Google News RSSで「{original_title}」を確認し、"
                f"配信元ページ{effective_url}を特定した。"
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
    direct = article_record_from_candidate(
        category_label,
        record,
        original_title,
        str(record.get("url", "")),
        original_title,
        str(record.get("excerpt", "")),
    )
    if direct:
        return direct

    def resolve_candidates(
        values: list[tuple[int, str, str, str]],
    ) -> dict[str, Any] | None:
        for _, candidate_url, result_title, description in values[:8]:
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
                    f"配信元ページ候補{candidate_url}と本文抜粋を特定した。"
                    f"本文抜粋: {description[:700]}"
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
                and category_identity_ok(
                    category_label,
                    original_title,
                    description,
                )
                and document_matches_discovery(
                    record,
                    candidate_url,
                    result_title,
                    description,
                )
                and record_has_material_body(original_title, snippet_record)
            ):
                return snippet_record
        return None

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
                or not candidate_matches_publisher(record, candidate_url)
                or not article_result_matches(
                    original_title,
                    result_title,
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
    return resolve_candidates(sorted(candidates.values(), reverse=True)) or record


def enrichment_target_urls(
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
) -> set[str]:
    targets: set[str] = set()
    category_label = str(category.get("label", ""))
    # Every URL counted as a material candidate must get the same enrichment
    # opportunity. Clustering is an editorial deduplication step and must not
    # shrink the collector's resolution set.
    for record in records:
        url = str(record.get("url", ""))
        title = record_public_title(record)
        excerpt = str(record.get("excerpt") or "")
        if (
            url
            and record.get("observed")
            and valid_date(record.get("published_date"), issue_date)
            and record_document_is_current(record, issue_date)
            and editor_candidate_boundary(
                category_label,
                title,
                excerpt,
                source_label=str(record.get("label", "")),
            )
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
        and record_document_is_current(record, issue_date)
        and editor_candidate_boundary(
            str(category.get("label", "")),
            title,
            excerpt,
            source_label=str(record.get("label", "")),
        )
    )


def discovery_record_is_material(record: dict[str, Any]) -> bool:
    title = record_public_title(record)
    excerpt = str(record.get("excerpt") or "")
    text = f"{title} {excerpt}"
    return bool(
        title
        and excerpt
        and not record_has_only_headline(title, record)
        and not state_contract.navigation_shell_text(text)
        and not state_contract.NO_UPDATE_ASSERTION_RE.search(text)
        and material_event_candidate(title, excerpt)
    )


def discovery_record_needs_resolution(record: dict[str, Any]) -> bool:
    """Keep concrete headline-only changes visible until enrichment finishes."""
    title = record_public_title(record)
    excerpt = str(record.get("excerpt") or "")
    return bool(
        discovery_record_is_material(record)
        or (
            title
            and excerpt
            and record_evidence_depth(title, record) == "headline"
            and material_event_candidate(title, excerpt)
        )
    )


def material_candidate_has_resolved_peer(
    candidate: dict[str, Any],
    records: list[dict[str, Any]],
) -> bool:
    """Resolve one search candidate by event, not only by its discovery URL."""
    candidate_title = record_public_title(candidate)
    if not candidate_title:
        return False
    return any(
        record.get("observed")
        and record_evidence_depth(record_public_title(record), record) != "none"
        and same_material_event(candidate_title, record_public_title(record))
        for record in records
    )


def remaining_editor_coverage_gaps(
    bundle: dict[str, Any],
    report: dict[str, Any],
) -> list[str]:
    """Keep only material topic gaps that lack a body-rich peer for every event."""
    remaining: list[str] = []
    categories = bundle.get("categories", {})
    issue_date = str(bundle.get("issue_date", ""))
    for gap in report.get("editor_coverage_gaps", []):
        label, separator, topic = str(gap).partition("/")
        entry = categories.get(label) if isinstance(categories, dict) else None
        if not separator or not isinstance(entry, dict):
            remaining.append(str(gap))
            continue
        records = [
            record
            for record in entry.get("records", [])
            if isinstance(record, dict)
        ]
        unresolved_query_ids = {
            str(check.get("query_id"))
            for check in entry.get("discovery_checks", [])
            if isinstance(check, dict)
            and topic in check.get("watch_topic_ids", [])
            and int(check.get("material_candidate_count", 0)) > 0
            and int(check.get("resolved_candidate_count", 0)) == 0
        }
        bounded_depth_attempted = any(
            isinstance(check, dict)
            and str(check.get("query_id", "")).startswith("depth:")
            and topic in check.get("watch_topic_ids", [])
            for check in entry.get("discovery_checks", [])
        )
        candidates = [
            record
            for record in records
            if unresolved_query_ids
            & {
                str(query_id)
                for query_id in record.get("discovery_query_ids", [])
            }
            and discovery_record_is_material(record)
            and bool(issue_date)
            and valid_date(record.get("published_date"), issue_date)
            and record_document_is_current(record, issue_date)
            and editor_candidate_boundary(
                label,
                record_public_title(record),
                str(record.get("excerpt") or ""),
                source_label=str(record.get("label", "")),
            )
        ]
        # Discovery counters are historical collection metadata. If every URL
        # they counted now fails the current material boundary, the Editor has
        # no honest coverage obligation and should not trigger recollection.
        if candidates and not all(
            material_candidate_has_resolved_peer(candidate, records)
            for candidate in candidates
        ) and not bounded_depth_attempted:
            remaining.append(str(gap))
    return remaining


def discovery_fallback_spec(spec: dict[str, Any]) -> dict[str, Any] | None:
    fallback_provider = str(spec.get("fallback_provider", ""))
    primary_provider = str(spec.get("provider", ""))
    if (
        not fallback_provider
        or fallback_provider == primary_provider
        or spec.get("fallback_attempted")
    ):
        return None
    return {
        **spec,
        "provider": fallback_provider,
        "fallback_provider": "",
        "fallback_attempted": True,
        "fallback_from_provider": primary_provider,
    }


def fetch_discovery_spec(
    category: dict[str, Any],
    issue_date: str,
    spec: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    query = str(spec["query"])
    provider = str(spec.get("provider"))
    locale = spec.get("locale") if isinstance(spec.get("locale"), dict) else {}
    if provider == "google_news_rss":
        rss_url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
            {
                "q": query,
                "hl": str(locale.get("hl") or "ja"),
                "gl": str(locale.get("gl") or "JP"),
                "ceid": str(locale.get("ceid") or "JP:ja"),
            }
        )
        provider_label = "Google News RSS"
    elif provider == "bing_rss":
        rss_url = "https://www.bing.com/search?" + urllib.parse.urlencode(
            {"format": "rss", "q": query}
        )
        provider_label = "Bing indexed search"
    else:
        raise ValueError(f"unsupported discovery provider: {provider}")

    try:
        raw, _, _ = request_bytes(rss_url)
        root = ET.fromstring(raw)
    except (OSError, TimeoutError, urllib.error.URLError, ET.ParseError) as exc:
        fallback = discovery_fallback_spec(spec)
        if fallback is not None:
            records, check = fetch_discovery_spec(
                category,
                issue_date,
                fallback,
            )
            check["evidence_summary"] = (
                f"{provider_label}失敗後に代替検索を実行した。"
                f"{check['evidence_summary']}"
            )
            return records, check
        return [], {
            **spec,
            "url": rss_url,
            "label": provider_label,
            "slot_state": "search_unavailable",
            "result_count": 0,
            "relevant_result_count": 0,
            "material_candidate_count": 0,
            "resolved_candidate_count": 0,
            "evidence_summary": f"検索に失敗した: {type(exc).__name__}: {exc}",
        }

    result_count = 0
    relevant_urls: set[str] = set()
    material_urls: set[str] = set()
    records: list[dict[str, Any]] = []
    for item in root.findall(".//item"):
        title = compact_text(item.findtext("title") or "", 220)
        link = compact_text(item.findtext("link") or "", 1000)
        if not title or not link.startswith(("http://", "https://")):
            continue
        result_count += 1
        description = html_fragment_text(item.findtext("description") or "", 1200)
        published_date = parse_rss_date(item.findtext("pubDate"))
        source = item.find("source") if provider == "google_news_rss" else None
        parsed = urllib.parse.urlparse(link)
        source_label = (
            compact_text(source.text or "", 120)
            if source is not None
            else parsed.netloc.lower().removeprefix("www.")
        )
        publisher_url = (
            compact_text(source.get("url") or "", 1000)
            if source is not None
            else f"{parsed.scheme}://{parsed.netloc}"
        )
        if not publisher_url.startswith(("http://", "https://")):
            publisher_url = ""
        channel = str(spec.get("channel") or "web")
        record = {
            "label": source_label or provider_label,
            "url": link,
            "source_role": (
                "independent_media_or_data"
                if channel == "web"
                else "social_or_video_signal"
            ),
            "channel": channel,
            "source_class": "discovered_media",
            "publisher_url": publisher_url,
            "observed": True,
            "published_date": published_date,
            "title": title,
            "excerpt": description or title,
            "discovery_query_ids": [str(spec["query_id"])],
            "watch_topic_ids": list(spec["watch_topic_ids"]),
            "evidence": (
                f"{provider_label}で「{title}」を確認した。"
                f"配信元は{source_label or parsed.netloc}、配信日は"
                f"{published_date or '日付不明'}。"
            ),
        }
        allowed_hosts = [
            str(host)
            for host in spec.get("allowed_hosts", [])
            if isinstance(host, str) and host.strip()
        ]
        if allowed_hosts and not record_matches_allowed_hosts(record, allowed_hosts):
            continue
        if not discovery_record_is_relevant(category, issue_date, record):
            continue
        relevant_urls.add(link)
        if discovery_record_needs_resolution(record):
            material_urls.add(link)
        records.append(record)

    if spec.get("allowed_hosts") and not relevant_urls:
        fallback = discovery_fallback_spec(spec)
        if fallback is not None:
            fallback_records, fallback_check = fetch_discovery_spec(
                category,
                issue_date,
                fallback,
            )
            fallback_check["evidence_summary"] = (
                f"{provider_label}の対象ドメイン結果が0件だったため"
                f"代替検索を実行した。{fallback_check['evidence_summary']}"
            )
            return fallback_records, fallback_check

    return records, {
        **spec,
        "url": rss_url,
        "label": provider_label,
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


def execute_discovery_specs(
    category: dict[str, Any],
    issue_date: str,
    specs: list[dict[str, Any]],
) -> list[tuple[int, list[dict[str, Any]], dict[str, Any]]]:
    """Fetch one bounded discovery pass while preserving configured order."""
    search_results: list[tuple[int, list[dict[str, Any]], dict[str, Any]]] = []
    if not specs:
        return search_results
    workers = max(1, int(os.getenv("NIGHT_SIGNAL_SEARCH_CONCURRENCY", "8")))
    with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {
            executor.submit(fetch_discovery_spec, category, issue_date, spec): index
            for index, spec in enumerate(specs)
        }
        for future in concurrent.futures.as_completed(futures):
            index = futures[future]
            try:
                records, check = future.result()
            except (OSError, TimeoutError, ValueError) as exc:
                spec = specs[index]
                records = []
                check = {
                    **spec,
                    "url": (
                        "https://news.google.com/"
                        if spec.get("provider") == "google_news_rss"
                        else "https://www.bing.com/"
                    ),
                    "label": str(spec.get("provider") or "search"),
                    "slot_state": "search_unavailable",
                    "result_count": 0,
                    "relevant_result_count": 0,
                    "material_candidate_count": 0,
                    "resolved_candidate_count": 0,
                    "evidence_summary": f"検索に失敗した: {type(exc).__name__}: {exc}",
                }
            search_results.append((index, records, check))
    return sorted(search_results, key=lambda value: value[0])


def merge_discovery_results(
    records_by_url: dict[str, dict[str, Any]],
    search_results: list[tuple[int, list[dict[str, Any]], dict[str, Any]]],
) -> list[dict[str, Any]]:
    """Merge query provenance without dropping a richer duplicate result."""
    checks: list[dict[str, Any]] = []
    for _, records, check in search_results:
        checks.append(check)
        for record in records:
            link = str(record.get("url", ""))
            current = records_by_url.get(link)
            if current is None:
                records_by_url[link] = record
                continue
            query_ids = list(
                dict.fromkeys(
                    [
                        *current.get("discovery_query_ids", []),
                        *record.get("discovery_query_ids", []),
                    ]
                )
            )
            topic_ids = list(
                dict.fromkeys(
                    [
                        *current.get("watch_topic_ids", []),
                        *record.get("watch_topic_ids", []),
                    ]
                )
            )
            if len(str(record.get("excerpt", ""))) > len(
                str(current.get("excerpt", ""))
            ):
                records_by_url[link] = {
                    **record,
                    "discovery_query_ids": query_ids,
                    "watch_topic_ids": topic_ids,
                }
            else:
                current["discovery_query_ids"] = query_ids
                current["watch_topic_ids"] = topic_ids
    return checks


def finalize_discovery_checks(
    checks: list[dict[str, Any]],
    records: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Bind search counters to the strongest Evidence obtained after enrichment."""
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
            bool(
                record
                and record_evidence_depth(record_public_title(record), record) != "none"
            )
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
        check["evidence_summary"] += (
            f" 編集可能な根拠を確保した重要更新候補は{resolved}件。"
        )
    return checks


def fetch_news(category: dict[str, Any], issue_date: str) -> dict[str, Any]:
    records_by_url: dict[str, dict[str, Any]] = {}
    checks = merge_discovery_results(
        records_by_url,
        execute_discovery_specs(
            category,
            issue_date,
            discovery_queries(category, issue_date),
        ),
    )
    records = enrich_discovered_records(
        category, issue_date, list(records_by_url.values())
    )
    depth_specs = depth_recovery_queries(category, issue_date, records)
    if depth_specs:
        checks.extend(
            merge_discovery_results(
                records_by_url,
                execute_discovery_specs(category, issue_date, depth_specs),
            )
        )
        records = enrich_discovered_records(
            category, issue_date, list(records_by_url.values())
        )
    return {
        "records": records,
        "discovery_checks": finalize_discovery_checks(checks, records),
    }


def category_contracts() -> list[dict[str, Any]]:
    return list(configured_category_contracts().values())


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
    selected = editor_evidence_records(category, issue_date, records)
    required_facts_by_event = editor_required_source_facts(selected)

    def build_payload() -> dict[str, Any]:
        events: list[dict[str, Any]] = []
        events_by_id: dict[str, dict[str, Any]] = {}
        for evidence_id, record in selected:
            title = record_public_title(record)
            evidence_depth = record_evidence_depth(title, record)
            event_id = str(record.get("_editor_event_id") or evidence_id)
            required_fact_ids = {
                fact["id"]
                for fact in required_facts_by_event.get(event_id, [])
                if fact["evidence_id"] == evidence_id
            }
            event = events_by_id.get(event_id)
            if event is None:
                event = {
                    "id": event_id,
                    "previous_updates": record.get("_editor_previous_updates", []),
                    "evidence": [],
                    "_records": [],
                }
                events_by_id[event_id] = event
                events.append(event)
            event["_records"].append(record)
            article_fact_count = (
                len(editor_article_facts(record))
                if evidence_depth == "body"
                else 0
            )
            fact_inventory = (
                editor_source_fact_inventory(evidence_id, record)
                if evidence_depth == "body"
                else []
            )
            event["evidence"].append(
                {
                    "id": evidence_id,
                    "watch_topic_ids": list(
                        dict.fromkeys(
                            str(value)
                            for value in record.get("watch_topic_ids", [])
                            if str(value)
                        )
                    ),
                    "date": record.get("published_date"),
                    "source": record.get("label"),
                    "source_class": effective_source_class(record),
                    "title": title,
                    "evidence_depth": evidence_depth,
                    "body": " ".join(
                        f"[{fact['id']}] {fact['text']}"
                        for fact in fact_inventory
                    ),
                    "required_fact_ids": [
                        fact["id"]
                        for fact in fact_inventory
                        if fact["id"] in required_fact_ids
                    ],
                    "article_fact_count": article_fact_count,
                    "source_fact_overflow_count": max(
                        0,
                        article_fact_count - len(fact_inventory),
                    ),
                }
            )
        issue_day = date.fromisoformat(issue_date)
        for event in events:
            event_records = event.pop("_records")
            previous_dates = {
                str(update.get("date"))
                for update in event.get("previous_updates", [])
                if re.fullmatch(
                    r"20\d{2}-\d{2}-\d{2}",
                    str(update.get("date", "")),
                )
            }
            explicit_dates = sorted(
                {
                    event_day.isoformat()
                    for record in event_records
                    for event_day in record_explicit_event_dates(record, issue_day)
                    if event_day <= issue_day
                }
            )
            known_dates = sorted(previous_dates | set(explicit_dates))
            event["novelty_context"] = {
                "known_since": known_dates[0] if known_dates else None,
                "explicit_event_dates": explicit_dates,
            }
        return {
            "category": category["label"],
            "allowed_watch_topic_ids": [
                str(topic["id"])
                for topic in category.get("watch_topics", [])
                if isinstance(topic, dict) and topic.get("id")
            ],
            "events": events,
        }

    return build_payload()


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


def sentence_parts(
    value: str,
    *,
    limit: int = 2400,
    split_latin_sentences: bool = True,
) -> list[str]:
    parts: list[str] = []
    splitter = (
        r"(?<=[。！？!?])\s*|(?<=\.)\s+(?=[A-Z0-9“\"'])"
        if split_latin_sentences
        else r"(?<=[。！？!?])"
    )
    for part in re.split(
        splitter,
        reader_facing_text(value, limit),
    ):
        text = part.strip()
        if text and not re.fullmatch(
            r"(?:ニュース|ファイナンス|MSN|web|オンライン)[。．.!！?？]*",
            text,
            flags=re.I,
        ):
            parts.append(
                text
                if text.endswith(("。", "．", ".", "！", "？", "!", "?"))
                else f"{text}。"
            )
    if not parts and value:
        text = reader_facing_text(value, min(limit, 700)).strip()
        if text:
            parts.append(text if text.endswith("。") else f"{text}。")
    return parts


def sources_from_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    sources: list[dict[str, Any]] = []
    seen: set[str] = set()
    for record in records:
        url = str(record.get("url", ""))
        host = urllib.parse.urlparse(url).netloc.lower()
        title = record_public_title(record)
        if (
            (host == "news.google.com" or host.endswith(".news.google.com"))
            and record_evidence_depth(title, record) != "headline"
        ):
            continue
        if not url or url in seen:
            continue
        seen.add(url)
        sources.append(
            {
                "label": reader_facing_source_label(record.get("label"), url),
                "url": url,
                "source_role": str(
                    record.get("source_role", "independent_media_or_data")
                ),
                "channel": str(record.get("channel", "web")),
                "published_date": str(record.get("published_date", "")),
            }
        )
    return sources


def derived_watch_topic(
    category: dict[str, Any],
    records: list[dict[str, Any]],
    *texts: str,
) -> str:
    topics = [
        topic
        for topic in category.get("watch_topics", [])
        if isinstance(topic, dict) and topic.get("id")
    ]
    valid_topic_ids = {str(topic["id"]) for topic in topics}
    evidence_topics = [
        str(topic_id)
        for record in records
        for topic_id in record.get("watch_topic_ids", [])
        if str(topic_id) in valid_topic_ids
    ]
    if evidence_topics:
        return min(
            valid_topic_ids,
            key=lambda topic_id: (
                -evidence_topics.count(topic_id),
                next(
                    index
                    for index, topic in enumerate(topics)
                    if str(topic["id"]) == topic_id
                ),
            ),
        )
    haystack = " ".join(texts).lower()
    ranked = [
        (
            sum(
                1
                for term in topic.get("terms", [])
                if str(term).strip() and str(term).lower() in haystack
            ),
            -index,
            str(topic["id"]),
        )
        for index, topic in enumerate(topics)
    ]
    return max(ranked, default=(0, 0, ""))[2]


ANALYSIS_INFERENCE_RE = re.compile(
    r"(?:示唆|兆し|可能性|とみられ|考えられ|整合|一方|反面|"
    r"suggest|indicat|signal|could|may\b)",
    re.I,
)


def normalize_analysis_block(
    raw: Any,
    records_by_id: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Validate optional multi-source analysis separately from confirmed facts."""
    if raw is None:
        return None, []
    if not isinstance(raw, dict):
        return None, ["analysis_shape"]
    inference = reader_facing_text(raw.get("inference", ""), 900)
    counterargument = reader_facing_text(raw.get("counterargument", ""), 700)
    uncertainty = reader_facing_text(raw.get("remaining_uncertainty", ""), 700)
    confidence = str(raw.get("confidence", ""))
    evidence_ids = list(
        dict.fromkeys(
            str(value)
            for value in raw.get("evidence_ids", [])
            if isinstance(value, str) and value
        )
    )
    unknown_ids = [value for value in evidence_ids if value not in records_by_id]
    records = [records_by_id[value] for value in evidence_ids if value in records_by_id]
    hosts = {
        normalized_source_host(record.get("publisher_url") or record.get("url"))
        for record in records
        if normalized_source_host(record.get("publisher_url") or record.get("url"))
    }
    reasons: list[str] = []
    if not inference or not counterargument or not uncertainty:
        reasons.append("analysis_layers_incomplete")
    if confidence not in {"high", "medium", "low"}:
        reasons.append("analysis_confidence")
    if unknown_ids:
        reasons.append("analysis_unknown_evidence_id")
    if len(evidence_ids) < 2 or len(hosts) < 2:
        reasons.append("analysis_requires_two_independent_sources")
    if records and any(
        record_evidence_depth(record_public_title(record), record) != "body"
        for record in records
    ):
        reasons.append("analysis_requires_body_evidence")
    if records and not any(record_has_trusted_editor_source(record) for record in records):
        reasons.append("analysis_requires_trusted_source")
    if inference and not ANALYSIS_INFERENCE_RE.search(inference):
        reasons.append("analysis_not_labeled_as_inference")
    if any(
        not reader_public_copy_ok(text, kind="summary")
        for text in (inference, counterargument, uncertainty)
        if text
    ):
        reasons.append("analysis_copy")
    analysis_text = " ".join((inference, counterargument, uncertainty))
    analysis_amounts, analysis_without_amounts = normalized_financial_amounts(
        analysis_text
    )
    evidence_text = " ".join(
        f"{record.get('title', '')} {record.get('excerpt') or record.get('evidence') or ''}"
        for record in records
    )
    evidence_amounts, evidence_without_amounts = normalized_financial_amounts(
        evidence_text
    )
    evidence_numbers = numeric_claims(evidence_without_amounts)
    if any(
        not numeric_claim_supported(number, evidence_numbers, approximate=True)
        for number in numeric_claims(analysis_without_amounts)
    ):
        reasons.append("analysis_unsupported_number")
    if any(
        not any(
            (currency == observed_currency or "UNSPECIFIED" in {currency, observed_currency})
            and abs(amount - observed_amount) <= max(1.0, abs(amount) * 1e-9)
            for observed_currency, observed_amount in evidence_amounts
        )
        for currency, amount in analysis_amounts
    ):
        reasons.append("analysis_unsupported_amount")
    if reasons:
        return None, list(dict.fromkeys(reasons))
    return (
        {
            "inference": inference,
            "counterargument": counterargument,
            "remaining_uncertainty": uncertainty,
            "confidence": confidence,
            "evidence_ids": evidence_ids,
            "source_urls": list(
                dict.fromkeys(str(record.get("url")) for record in records)
            ),
        },
        [],
    )


def source_fact_covered_by_summary(source_fact: str, summary_point: str) -> bool:
    """Verify that a cited source-fact id is actually represented in the copy."""
    source_numbers = numeric_claims(source_fact)
    summary_numbers = numeric_claims(summary_point)
    if source_requires_japanese_translation(source_fact):
        source_anchors = {
            re.sub(r"[^a-z0-9]", "", value.casefold())
            for value in re.findall(r"[A-Za-z][A-Za-z0-9.+-]{1,}", source_fact)
            if value.casefold() not in {"ai", "the", "and", "for", "with", "from"}
        }
        summary_anchors = {
            re.sub(r"[^a-z0-9]", "", value.casefold())
            for value in re.findall(r"[A-Za-z][A-Za-z0-9.+-]{1,}", summary_point)
        }
        # Source sentences often contain publication times or other incidental
        # numbers beside the material claim.  Require one numeric bridge for a
        # translated numeric fact, not every number in the source sentence.
        # The opposite direction is still strict below:
        # summary_claims_supported_by_source_facts rejects every number added
        # by the summary unless it exists in the cited source facts.
        numeric_anchor = not source_numbers or any(
            numeric_claim_supported(number, summary_numbers, approximate=True)
            for number in source_numbers
        )
        return numeric_anchor and bool(source_anchors & summary_anchors)
    if state_contract.materially_same_fact(source_fact, summary_point):
        return True
    required_overlap = min(2, max(1, len(state_contract.content_terms(source_fact))))
    return state_contract.text_overlap(source_fact, summary_point) >= required_overlap


def summary_claims_supported_by_source_facts(
    summary_point: str,
    source_facts: list[dict[str, str]],
) -> bool:
    """Reject translated copy that adds a number or amount absent from its facts."""
    if not source_facts:
        return False
    source_text = " ".join(fact["text"] for fact in source_facts)
    source_amounts, source_without_amounts = normalized_financial_amounts(source_text)
    summary_amounts, summary_without_amounts = normalized_financial_amounts(
        summary_point
    )
    source_numbers = numeric_claims(source_without_amounts)
    summary_numbers = numeric_claims(summary_without_amounts)
    if any(
        not numeric_claim_supported(number, source_numbers, approximate=True)
        for number in summary_numbers
    ):
        return False
    return not any(
        not any(
            (currency == observed_currency or "UNSPECIFIED" in {currency, observed_currency})
            and abs(amount - observed_amount) <= max(1.0, abs(amount) * 1e-9)
            for observed_currency, observed_amount in source_amounts
        )
        for currency, amount in summary_amounts
    )


def normalize_result(
    raw: dict[str, Any],
    category: dict[str, Any],
    issue_date: str,
    records: list[dict[str, Any]],
    *,
    require_source_fact_coverage: bool = False,
) -> dict[str, Any]:
    valid_topic_order = [
        str(topic["id"])
        for topic in category.get("watch_topics", [])
        if isinstance(topic, dict)
    ]
    valid_topics = set(valid_topic_order)
    evidence_entries = editor_evidence_records(category, issue_date, records)
    records_by_id = dict(evidence_entries)
    required_facts_by_event = editor_required_source_facts(evidence_entries)
    source_facts_by_id = {
        fact["id"]: {**fact, "evidence_id": evidence_id}
        for evidence_id, record in evidence_entries
        for fact in editor_source_fact_inventory(evidence_id, record)
    }
    expected_event_ids = {
        str(record.get("_editor_event_id") or evidence_id)
        for evidence_id, record in evidence_entries
    }
    items: list[dict[str, Any]] = []
    rejected_items: list[dict[str, Any]] = []
    seen_titles: set[str] = set()
    seen_clusters: set[str] = set()
    published_event_ids: set[str] = set()
    covered_source_fact_ids_by_event: dict[str, set[str]] = {}
    excluded_event_ids = {
        str(value.get("event_id"))
        for value in raw.get("excluded_events", [])
        if isinstance(value, dict)
        and str(value.get("event_id", "")) in expected_event_ids
    }
    unknown_excluded_event_ids = {
        str(value.get("event_id"))
        for value in raw.get("excluded_events", [])
        if isinstance(value, dict)
        and str(value.get("event_id", "")) not in expected_event_ids
    }
    for item in raw.get("items", []):
        if not isinstance(item, dict):
            continue
        title = compact_text(str(item.get("title", "")), 180)
        point_values: list[
            tuple[str, list[str], list[str], list[dict[str, str]]]
        ] = []
        seen_point_texts: set[str] = set()
        invalid_point_shape = False
        for raw_point in item.get("summary_points", []):
            if not isinstance(raw_point, dict):
                invalid_point_shape = True
                continue
            text = compact_text(str(raw_point.get("text", "")), 500)
            point_ids = list(
                dict.fromkeys(
                    str(value)
                    for value in raw_point.get("evidence_ids", [])
                    if isinstance(value, str) and value
                )
            )
            source_fact_ids = list(
                dict.fromkeys(
                    str(value)
                    for value in raw_point.get("source_fact_ids", [])
                    if isinstance(value, str) and value
                )
            )
            if (
                not text
                or not point_ids
                or (require_source_fact_coverage and not source_fact_ids)
            ):
                invalid_point_shape = True
                continue
            normalized_texts = state_contract.normalize_material_facts(title, [text])
            if not normalized_texts:
                invalid_point_shape = True
                continue
            for normalized_text in normalized_texts:
                if normalized_text in seen_point_texts:
                    continue
                seen_point_texts.add(normalized_text)
                support_quotes = [
                    {
                        "evidence_id": evidence_id,
                        "quote": support_quote_from_record(
                            normalized_text,
                            records_by_id[evidence_id],
                        ),
                    }
                    for evidence_id in point_ids
                    if evidence_id in records_by_id
                ]
                point_values.append(
                    (normalized_text, point_ids, source_fact_ids, support_quotes)
                )
        unsupported_facts: list[str] = []
        supported_point_values: list[
            tuple[str, list[str], list[str], list[dict[str, str]]]
        ] = []
        invalid_source_fact_ids: set[str] = set()
        uncovered_source_fact_ids: set[str] = set()
        covered_source_fact_ids: set[str] = set()
        for text, point_ids, source_fact_ids, support_quotes in point_values:
            if any(evidence_id not in records_by_id for evidence_id in point_ids):
                supported_point_values.append(
                    (text, point_ids, source_fact_ids, support_quotes)
                )
                continue
            for source_fact_id in source_fact_ids:
                source_fact = source_facts_by_id.get(source_fact_id)
                if (
                    source_fact is None
                    or source_fact["evidence_id"] not in point_ids
                ):
                    invalid_source_fact_ids.add(source_fact_id)
                    continue
                if not source_fact_covered_by_summary(source_fact["text"], text):
                    uncovered_source_fact_ids.add(source_fact_id)
                else:
                    covered_source_fact_ids.add(source_fact_id)
            cited_source_facts = [
                source_facts_by_id[source_fact_id]
                for source_fact_id in source_fact_ids
                if source_fact_id in source_facts_by_id
                and source_facts_by_id[source_fact_id]["evidence_id"] in point_ids
            ]
            claims_supported = summary_claims_supported_by_source_facts(
                text, cited_source_facts
            )
            if claims_supported:
                # Exact source-fact ids are the semantic bridge for natural
                # Japanese translations.  Deterministic validation still owns
                # id existence, Evidence boundaries, and every numeric claim.
                covered_source_fact_ids.update(
                    source_fact["id"]
                    for source_fact in cited_source_facts
                    if source_requires_japanese_translation(source_fact["text"])
                )
            explicitly_supported = claims_supported and bool(
                covered_source_fact_ids
                & {source_fact["id"] for source_fact in cited_source_facts}
            )
            if fact_supported_by_records(
                text,
                [records_by_id[evidence_id] for evidence_id in point_ids],
            ) or explicitly_supported:
                supported_point_values.append(
                    (text, point_ids, source_fact_ids, support_quotes)
                )
            else:
                unsupported_facts.append(text)
        uncovered_source_fact_ids -= covered_source_fact_ids
        point_values = supported_point_values
        if unsupported_facts:
            print(
                json.dumps(
                    {
                        "phase": "unsupported_summary_points_rejected",
                        "category": category.get("label"),
                        "facts": unsupported_facts,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        evidence_ids = list(
            dict.fromkeys(
                evidence_id
                for _, point_ids, _, _ in point_values
                for evidence_id in point_ids
            )
        )
        if invalid_point_shape:
            print(
                json.dumps(
                    {
                        "phase": "invalid_summary_points_rejected",
                        "category": category.get("label"),
                        "title": title,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        unknown_evidence_ids = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_id not in records_by_id
        ]
        source_records = [
            records_by_id[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in records_by_id
        ]
        analysis, analysis_reasons = normalize_analysis_block(
            item.get("analysis"),
            records_by_id,
        )
        if analysis_reasons:
            print(
                json.dumps(
                    {
                        "phase": "analysis_not_published",
                        "category": category.get("label"),
                        "title": title,
                        "reasons": analysis_reasons,
                    },
                    ensure_ascii=False,
                ),
                flush=True,
            )
        analysis_evidence_ids = analysis.get("evidence_ids", []) if analysis else []
        evidence_ids = list(dict.fromkeys([*evidence_ids, *analysis_evidence_ids]))
        unknown_evidence_ids = [
            evidence_id
            for evidence_id in evidence_ids
            if evidence_id not in records_by_id
        ]
        source_records = [
            records_by_id[evidence_id]
            for evidence_id in evidence_ids
            if evidence_id in records_by_id
        ]
        sources = sources_from_records(source_records)
        item_event_id = compact_text(item.get("event_id", ""), 40)
        source_event_ids = {
            str(record.get("_editor_event_id"))
            for record in source_records
            if record.get("_editor_event_id")
        }
        available_event_ids = {
            str(record.get("_editor_event_id"))
            for record in records_by_id.values()
            if record.get("_editor_event_id")
        }
        topic = derived_watch_topic(
            category,
            source_records,
            title,
            *[text for text, _, _, _ in point_values],
        )
        point_texts = [text for text, _, _, _ in point_values]
        # The model-provided id-to-sentence mapping is useful grounding but is
        # not itself the completeness boundary.  Credit every required fact
        # that the accepted title or summary actually represents.  This avoids
        # rejecting a complete review merely because an id was attached to the
        # wrong point, while the event-wide missing-fact gate still rejects a
        # real omission.
        represented_texts = [title, *point_texts]
        covered_source_fact_ids.update(
            fact["id"]
            for fact in required_facts_by_event.get(item_event_id, [])
            if fact["evidence_id"] in evidence_ids
            and any(
                source_fact_covered_by_summary(fact["text"], represented)
                for represented in represented_texts
            )
        )
        facts = point_texts
        summary = " ".join(facts)
        invalid_support_quotes = [
            quote
            for _, point_ids, _, quotes in point_values
            for quote in quotes
            if quote["evidence_id"] not in point_ids
            or quote["evidence_id"] not in records_by_id
            or len(compact_text(quote["quote"], 320)) < 8
        ]
        missing_quote_ids = [
            evidence_id
            for _, point_ids, _, quotes in point_values
            for evidence_id in point_ids
            if evidence_id
            not in {str(quote.get("evidence_id")) for quote in quotes}
        ]
        factual_text = " ".join([summary, *facts])
        item_cluster = normalized_topic_key(title)
        topic_value = str(item.get("topic_value_class", ""))
        change_class = str(item.get("change_class", ""))
        source_dates = {
            str(record.get("published_date"))
            for record in source_records
            if record.get("published_date")
        }
        source_date = max(source_dates, default="")
        fact_source_urls = [
            {
                "fact": fact,
                "source_urls": [
                    str(records_by_id[evidence_id].get("url"))
                    for evidence_id in point_ids
                    if evidence_id in records_by_id
                ],
            }
            for fact, (_, point_ids, _, _) in zip(facts, point_values)
        ]
        rejection_checks = [
            ("invalid_summary_point", invalid_point_shape),
            ("unsupported_summary_point", bool(unsupported_facts)),
            (
                "invalid_source_fact_id",
                require_source_fact_coverage and bool(invalid_source_fact_ids),
            ),
            ("missing_evidence_id", not evidence_ids),
            ("unknown_evidence_id", bool(unknown_evidence_ids)),
            (
                "insufficient_body_evidence",
                bool(source_records)
                and not any(
                    record_evidence_depth(record_public_title(record), record)
                    == "body"
                    for record in source_records
                ),
            ),
            ("unknown_topic", topic not in valid_topics),
            (
                "missing_event_id",
                bool(available_event_ids) and not item_event_id,
            ),
            (
                "unknown_event_id",
                bool(available_event_ids) and item_event_id not in available_event_ids,
            ),
            (
                "event_evidence_mismatch",
                bool(source_event_ids)
                and bool(item_event_id)
                and source_event_ids != {item_event_id},
            ),
            ("mixed_event_boundary", len(source_event_ids) > 1),
            ("empty_title", not title),
            ("title_copy", not reader_public_copy_ok(title, kind="title")),
            ("empty_summary", not facts),
            ("information_incomplete", item.get("information_complete") is not True),
            ("summary_copy", not reader_public_copy_ok(summary, kind="summary")),
            (
                "unsupported_title",
                bool(source_records)
                and not fact_supported_by_records(title, source_records),
            ),
            (
                "summary_repetition",
                bool(state_contract.reader_summary_violations(title, summary)),
            ),
            (
                "category_identity",
                not (
                    category_identity_ok(
                        str(category.get("label", "")), title, factual_text
                    )
                    or any(
                        category_identity_ok(
                            str(category.get("label", "")),
                            f"{record.get('label', '')} {record_public_title(record)}",
                            "",
                        )
                        for record in source_records
                    )
                ),
            ),
            ("duplicate_title", title in seen_titles),
            (
                "insufficient_facts",
                not facts_add_information_beyond_title(title, facts),
            ),
            (
                "generic_padding",
                any(not useful_fact(fact, str(category.get("label", ""))) for fact in facts),
            ),
            ("unsupported_quote", bool(invalid_support_quotes)),
            ("missing_support_quote", bool(missing_quote_ids)),
            ("missing_source", not sources),
            ("duplicate_cluster", cluster_seen(seen_clusters, item_cluster)),
            ("unknown_topic_value", topic_value not in ALLOWED_TOPIC_VALUES),
            (
                "unknown_change_class",
                change_class
                not in {"new_event", "material_update", "new_analysis_of_existing_fact"},
            ),
            ("invalid_source_date", not valid_date(source_date, issue_date)),
            (
                "unmapped_fact_source",
                any(not mapping["source_urls"] for mapping in fact_source_urls),
            ),
        ]
        rejection_reasons = [reason for reason, rejected in rejection_checks if rejected]
        if rejection_reasons:
            rejected_items.append(
                {
                    "event_id": item_event_id,
                    "title": title,
                    "reasons": rejection_reasons,
                    "unsupported_facts": unsupported_facts,
                    "invalid_source_fact_ids": sorted(invalid_source_fact_ids),
                    "uncovered_source_fact_ids": sorted(uncovered_source_fact_ids),
                }
            )
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
        published_event_ids.add(item_event_id)
        covered_source_fact_ids_by_event.setdefault(item_event_id, set()).update(
            covered_source_fact_ids
        )
        first_source = sources[0]
        items.append(
            {
                "event_id": item_event_id,
                "evidence_ids": evidence_ids,
                "watch_topic_id": topic,
                "title": title,
                "summary": summary,
                "source_published_date": source_date,
                "topic_value_class": topic_value,
                "priority_class": (
                    str(item.get("priority_class"))
                    if item.get("priority_class") in {"top", "priority", "standard"}
                    else "standard"
                ),
                "change_class": change_class,
                "slug": (
                    "auto-"
                    + hashlib.sha1(title.encode("utf-8")).hexdigest()[:12]
                    + f"-{issue_date}"
                ),
                "confirmed_facts": facts,
                "source_fact_ids": sorted(covered_source_fact_ids),
                "fact_sources": fact_source_urls,
                "analysis": analysis,
                "sources": sources,
                "observation_source_role": first_source["source_role"],
                "observation_channel": first_source["channel"],
            }
        )
    rejected_by_event: dict[str, list[dict[str, Any]]] = {}
    for rejected in rejected_items:
        event_id = str(rejected.get("event_id", ""))
        if event_id in expected_event_ids:
            rejected_by_event.setdefault(event_id, []).append(rejected)
    # A publish decision must never disappear merely because a deterministic
    # identity heuristic disagrees with the reviewed, source-bound event.  Keep
    # the rejection visible so only this event is corrected/reviewed.
    deterministic_wrong_category_ids: set[str] = set()
    conflicting_event_ids = sorted(published_event_ids & excluded_event_ids)
    accounted_event_ids = published_event_ids | excluded_event_ids
    missing_event_ids = sorted(expected_event_ids - accounted_event_ids)
    missing_source_fact_ids_by_event = {
        event_id: sorted(
            {fact["id"] for fact in required_facts_by_event.get(event_id, [])}
            - covered_source_fact_ids_by_event.get(event_id, set())
        )
        for event_id in sorted(published_event_ids)
        if {
            fact["id"] for fact in required_facts_by_event.get(event_id, [])
        }
        - covered_source_fact_ids_by_event.get(event_id, set())
    }
    return {
        "items": items,
        "coverage_complete": not (
            missing_event_ids
            or conflicting_event_ids
            or unknown_excluded_event_ids
            or (
                require_source_fact_coverage
                and missing_source_fact_ids_by_event
            )
        ),
        "missing_event_ids": missing_event_ids,
        "conflicting_event_ids": conflicting_event_ids,
        "unknown_excluded_event_ids": sorted(unknown_excluded_event_ids),
        "missing_source_fact_ids_by_event": missing_source_fact_ids_by_event,
        "deterministic_wrong_category_ids": sorted(
            deterministic_wrong_category_ids
        ),
        "expected_event_ids": sorted(expected_event_ids),
        "rejected_items": rejected_items,
    }


def collect_evidence(issue_date: str) -> dict[str, Any]:
    source_config = load_object(SOURCE_CONFIG)
    sources = source_config.get("categories")
    if not isinstance(sources, dict):
        fail("source config categories must be an object")
    contracts = category_contracts()
    try:
        evidence_contract.validate_source_configuration(
            load_object(COVERAGE_CONFIG),
            source_config,
        )
        # Generate every query once before starting network work so a missing
        # required locale fails fast instead of wasting a partial collection.
        for category in contracts:
            discovery_queries(category, issue_date)
    except (evidence_contract.EvidenceContractError, ValueError) as exc:
        fail(str(exc))
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
        collection_mode="web_evidence_plus_review",
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
        "coverage_proof": {
            "source_registry_version": source_config.get("version"),
            "source_registry_sha256": bundle["source_registry_contract"]["sha256"],
            "publisher_portfolio_version": bundle[
                "publisher_portfolio_contract"
            ]["portfolio_version"],
            "publisher_portfolio_sha256": bundle[
                "publisher_portfolio_contract"
            ]["sha256"],
            "required_official_scopes": sum(
                len(category.get("required_official_scopes", []))
                for category in contracts
            ),
            "required_local_horizons": sum(
                len(category.get("required_local_horizon_locales", []))
                for category in contracts
            ),
            "completed_local_horizon_queries": sum(
                1
                for entry in bundle["categories"].values()
                for check in entry["discovery_checks"]
                if str(check.get("query_id", "")).startswith(
                    "horizon:local-language:"
                )
            ),
            "local_horizon_relevant_results": sum(
                int(check.get("relevant_result_count", 0))
                for entry in bundle["categories"].values()
                for check in entry["discovery_checks"]
                if str(check.get("query_id", "")).startswith(
                    "horizon:local-language:"
                )
            ),
            "local_horizon_material_candidates": sum(
                int(check.get("material_candidate_count", 0))
                for entry in bundle["categories"].values()
                for check in entry["discovery_checks"]
                if str(check.get("query_id", "")).startswith(
                    "horizon:local-language:"
                )
            ),
            "local_horizon_resolved_candidates": sum(
                int(check.get("resolved_candidate_count", 0))
                for entry in bundle["categories"].values()
                for check in entry["discovery_checks"]
                if str(check.get("query_id", "")).startswith(
                    "horizon:local-language:"
                )
            ),
            "scoped_official_sources_configured": sum(
                bool(source.get("official_scope"))
                for category_sources in sources.values()
                for source in category_sources
                if isinstance(source, dict)
            ),
            "scoped_official_sources_observed": sum(
                check.get("slot_state") == "observed_live"
                and bool(
                    next(
                        (
                            source.get("official_scope")
                            for source in sources.get(label, [])
                            if isinstance(source, dict)
                            and source.get("url") == check.get("url")
                        ),
                        None,
                    )
                )
                for label, entry in bundle["categories"].items()
                for check in entry["source_checks"]
            ),
        },
        "evidence": str(evidence_path),
        "collection_mode": "web_evidence_plus_review",
    }


def self_test() -> None:
    if PUBLICATION_EVENT_RE.search("Emergency Alert Today"):
        fail("English event matching treated Emergency as a merger")
    if not PUBLICATION_EVENT_RE.search("SpaceX launches a new vehicle"):
        fail("English event matching lost a real launch")
    routine_category = {"label": "Honda"}
    if not record_is_low_importance_routine(
        routine_category,
        "Honda株のテクニカル分析、RSIから買い時を検討",
        {"excerpt": "株価チャートと目標株価を解説する。"},
        "2099-01-02",
    ):
        fail("routine investment commentary reached the Editor")
    if not record_is_low_importance_routine(
        routine_category,
        "Honda 2097年モデルの性能と価格",
        {"excerpt": "過去モデルの製品概要を紹介する。"},
        "2099-01-02",
    ):
        fail("stale product overview reached the Editor")
    if record_is_low_importance_routine(
        routine_category,
        "Hondaが新工場建設を決定、2097年計画を更新",
        {"excerpt": "投資額と稼働時期を正式決定した。"},
        "2099-01-02",
    ):
        fail("a realized material change was rejected as stale background")
    if not record_is_low_importance_routine(
        {"label": "SpaceX"},
        "STARSHIPが新アルバムを発売",
        {"excerpt": "ロックバンドが楽曲を公開した。"},
        "2099-01-02",
    ):
        fail("SpaceX entertainment-name collision reached the Editor")
    if record_is_low_importance_routine(
        {"label": "SpaceX"},
        "SpaceXがStarshipの飛行試験を開始",
        {"excerpt": "大型ロケットを打ち上げ、軌道投入手順を確認した。"},
        "2099-01-02",
    ):
        fail("a SpaceX flight update was rejected as entertainment")
    macro_category = {"label": "日本経済"}
    if record_is_low_importance_routine(
        macro_category,
        "Example社、4〜6月期の四半期決算を発表",
        {"excerpt": "売上高と営業利益の実績を公表した。"},
        "2099-01-02",
    ):
        fail("an actual quarterly result was rejected as routine")
    for earnings_title in (
        "Example社、2098年12月期の通期決算を発表",
        "Example社、本決算を発表",
        "Example社、最終決算を発表",
    ):
        earnings_record = {
            "excerpt": "売上高、営業利益、最終利益の実績を公表した。"
        }
        if record_is_low_importance_routine(
            macro_category,
            earnings_title,
            earnings_record,
            "2099-01-02",
        ):
            fail(f"an actual annual or final result was rejected: {earnings_title}")
        if not record_title_has_material_change(
            macro_category,
            earnings_title,
            earnings_record,
        ):
            fail(f"an actual annual or final result lost materiality: {earnings_title}")
    if not record_is_low_importance_routine(
        macro_category,
        "Example社、四半期決算発表を控え今後の注目点",
        {"excerpt": "発表前に市場予想と注目点を整理した。"},
        "2099-01-02",
    ):
        fail("an earnings preview reached the Editor")
    if record_is_low_importance_routine(
        macro_category,
        "Example社、今期経常を30%上方修正",
        {"excerpt": "需要増を受けて通期業績予想を引き上げた。"},
        "2099-01-02",
    ):
        fail("a material earnings revision was rejected as routine")
    if not record_is_low_importance_routine(
        macro_category,
        "13時の日経平均は20円高",
        {"excerpt": "前場から小幅な値動きが続いた。"},
        "2099-01-02",
    ):
        fail("routine intraday market tick reached the Editor")
    if record_is_low_importance_routine(
        macro_category,
        "日経平均が急反発、一時1000円超高",
        {"excerpt": "半導体株主導で大幅に反発した。"},
        "2099-01-02",
    ):
        fail("a material market move was rejected as routine")
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
    discovered_channels = {str(spec.get("channel")) for spec in discovery_specs}
    if {"web", *INDEXED_CHANNEL_DOMAINS} - discovered_channels:
        fail("discovery queries omitted a required public information channel")
    web_locales = {
        str(spec.get("locale", {}).get("id"))
        for spec in discovery_specs
        if spec.get("channel") == "web" and isinstance(spec.get("locale"), dict)
    }
    if not {"ja-JP", "en-US"} <= web_locales:
        fail("discovery queries did not search both Japanese and English")
    missing_locale_category = {
        **wide_category,
        "required_local_horizon_locales": ["missing-locale"],
    }
    try:
        discovery_queries(missing_locale_category, "2099-01-01")
    except ValueError:
        pass
    else:
        fail("discovery configuration accepted a missing required local horizon")
    if discovery_identity_queries(
        {"label": "F1"},
        ["Formula Uno"],
        replace_with_extra=True,
    ) != ['"Formula Uno"']:
        fail("local-language horizon retained unrelated default identity terms")
    horizon_queries = " ".join(
        str(spec["query"])
        for spec in discovery_specs
        if spec["purpose"] == "horizon"
    )
    if "axis-only-term" not in horizon_queries:
        fail("discovery queries dropped an axis-only adjacent term")
    split_identity_specs = discovery_queries(
        {"label": "F1", "axes": [], "watch_topics": []},
        "2099-01-01",
    )
    split_identity_queries = " ".join(
        str(spec["query"]) for spec in split_identity_specs
    )
    if any(
        term not in split_identity_queries
        for term in category_identity_terms("F1")
    ):
        fail("bounded discovery queries dropped a later category identity")
    if not category_identity_ok(
        "F1",
        "Ferrari penalised for unsafe pit release involving Hamilton",
        "",
    ):
        fail("F1 competition entities failed the category identity boundary")
    indexed_queries = " ".join(
        str(spec["query"])
        for spec in split_identity_specs
        if spec.get("channel") in INDEXED_CHANNEL_DOMAINS
    )
    if any(term not in indexed_queries for term in DISCOVERY_CHANGE_TERMS):
        fail("indexed public-channel queries dropped a material change term")
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
    short_metadata_fixture = (
        '<html><script type="application/ld+json">'
        '{"@type":"NewsArticle","headline":"YOASOBIが新MVを公開",'
        '"description":"YOASOBIが新しいMVを公開した。公開日は7月4日。"}'
        '</script><div id="entrybody"><p>新MVは短編小説を原作とし、3人の登場人物が'
        'それぞれの記憶と向き合う姿を描いた。ゲーム内コラボは7月21日まで開催され、'
        '全6種の限定スキンと楽曲を使ったダンス演出も提供される。</p></div></html>'
    )
    _, enriched_body = page_text(
        short_metadata_fixture.encode(),
        "text/html; charset=utf-8",
    )
    if "全6種の限定スキン" not in enriched_body:
        fail("short structured metadata was not supplemented by the article body")
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
    clustered_headline = {
        **headline_only_cross_domain,
        "url": "https://example.com/cross-domain-event-copy",
    }
    if enrichment_target_urls(
        cross_domain_category,
        "2099-01-03",
        [headline_only_cross_domain, clustered_headline],
    ) != {headline_only_cross_domain["url"], clustered_headline["url"]}:
        fail("candidate clustering skipped a material URL before enrichment")
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
    for original_title, wrong_page_title in (
        (
            "ホンダF1、ADUOで得た2回の権利をどう使う？",
            "Layer 2 solutions in blockchain",
        ),
        (
            "ドル円、161.47円までじり高 米雇用統計後の動き",
            "東京 - Wikipedia",
        ),
        (
            "全国12万本の消火栓標識でStarlink活用探る技術デモ",
            "Starlink - Wikipedia",
        ),
    ):
        if article_result_matches(original_title, wrong_page_title):
            fail("generic entity overlap passed discovered article title matching")
    unreadable_source_url = "https://www.example.com/item"
    cleaned_unreadable_source = sources_from_records(
        [
            {
                "label": "—",
                "url": unreadable_source_url,
                "observed": True,
            }
        ]
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
    sports_category = {
        "label": "F1",
        "allow_sports_results": True,
        "watch_topics": [],
    }
    routine_schedule_record = {
        "label": "Racing News",
        "url": "https://example.com/f1-race-schedule",
        "source_role": "independent_media_or_data",
        "channel": "web",
        "source_class": "discovered_media",
        "observed": True,
        "published_date": "2099-01-02",
        "title": "2099 F1 Belgian Grand Prix",
        "excerpt": (
            "The 2099 F1 Belgian Grand Prix timetable lists practice at 13:30, "
            "qualifying at 16:00, and the race at 15:00 local time."
        ),
    }
    if not record_is_routine_sports_schedule(
        sports_category,
        routine_schedule_record["title"],
        routine_schedule_record,
    ):
        fail("routine sports timetable was not recognized before editing")
    if publication_evidence_record(
        sports_category, "2099-01-03", routine_schedule_record
    ):
        fail("routine sports timetable reached the Editor")
    changed_schedule_record = {
        **routine_schedule_record,
        "url": "https://example.com/f1-race-postponed",
        "title": "F1 Belgian Grand Prix timetable postponed",
        "excerpt": (
            "The F1 Belgian Grand Prix timetable was postponed after a safety review; "
            "practice had been set for 13:30, qualifying for 16:00, and the race for 15:00."
        ),
    }
    if record_is_routine_sports_schedule(
        sports_category,
        changed_schedule_record["title"],
        changed_schedule_record,
    ):
        fail("material sports schedule change was treated as a routine timetable")
    if record_is_routine_sports_schedule(
        music_category,
        routine_schedule_record["title"],
        routine_schedule_record,
    ):
        fail("sports timetable filter leaked into a non-sports category")
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
    navigation_prompt = category_prompt(
        music_category,
        "2099-01-03",
        [navigation_record],
    )
    if any(event["evidence"] for event in navigation_prompt["events"]):
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
    openai_category = configured_category_contracts()["OpenAI"]
    generic_overview_record = {
        **navigation_record,
        "label": "OpenAI Guide",
        "url": "https://example.com/openai-overview",
        "source_class": "discovered_media",
        "title": "OpenAIの基本情報と提供サービス",
        "excerpt": (
            "OpenAIは人工知能研究会社であり、"
            "ChatGPTなどのサービスを提供している。"
        ),
    }
    if publication_evidence_record(
        openai_category,
        "2099-01-03",
        generic_overview_record,
    ):
        fail("a generic entity overview reached publication Evidence")
    ipo_investment_guide = {
        **generic_overview_record,
        "url": "https://example.com/how-to-invest-openai-ipo",
        "title": "OpenAI IPOへの参加方法と上場見通し",
        "excerpt": (
            "OpenAIは2098年12月8日にIPO申請を行った。"
            "プレIPOのセカンダリーマーケット、AIテーマ型ETF、"
            "IPO後の直接買い付けを解説する。"
        ),
    }
    if publication_evidence_record(
        openai_category,
        "2099-01-03",
        ipo_investment_guide,
    ):
        fail("an IPO investment guide reached publication Evidence")
    viewing_guide = {
        **generic_overview_record,
        "url": "https://example.com/how-to-watch-launch",
        "title": "SpaceX launch: how to watch live",
        "excerpt": "SpaceX will livestream its next launch; here is where to watch.",
    }
    if discovery_record_is_material(viewing_guide):
        fail("a viewing guide was treated as a material discovery event")
    headline_only_discovery = {
        **generic_overview_record,
        "label": "Top Gear Philippines",
        "publisher_url": "https://www.topgear.com.ph",
        "source_class": "discovered_media",
        "observed": True,
        "published_date": "2099-01-03",
        "title": "Is this a sign that we could soon get an S+ Shift-equipped Honda Civic?",
        "excerpt": (
            "Is this a sign that we could soon get an S+ Shift-equipped Honda Civic? "
            "Top Gear Philippines"
        ),
    }
    if discovery_record_is_material(headline_only_discovery):
        fail("headline-only RSS discovery was treated as material coverage")
    long_update = {
        **generic_overview_record,
        "title": "OpenAIが監査機能を提供開始",
        "excerpt": (
            "一般的な背景説明が続く。" * 120
            + "OpenAIは監査機能を提供開始し、対象を42社に拡大した。"
        ),
    }
    bounded_update = editor_source_text(long_update, 420)
    if "監査機能" not in bounded_update or "42社" not in bounded_update:
        fail("bounded Editor input lost a material sentence near the end")
    headline_record = {
        **navigation_record,
        "label": "音楽情報サイト",
        "url": "https://news.google.com/rss/articles/chart-update?oc=5",
        "publisher_url": "https://music.example.jp",
        "source_class": "discovered_media",
        "title": (
            "Billboard JAPAN Download Albums（1/2公開）、"
            "YOASOBI「THE BOOK for.」2週連続DLアルバム首位 "
            "長渕剛／NiziUが続く"
        ),
        "excerpt": (
            "Billboard JAPAN Download Albums（1/2公開）、"
            "YOASOBI「THE BOOK for.」2週連続DLアルバム首位 "
            "長渕剛／NiziUが続く 音楽情報サイト"
        ),
    }
    if record_evidence_depth(record_public_title(headline_record), headline_record) != "headline":
        fail("fact-rich discovery headline was not retained as headline Evidence")
    if not publication_evidence_record(
        music_category,
        "2099-01-03",
        headline_record,
    ):
        fail("fact-rich discovery headline was filtered before the Editor")
    headline_payload = category_prompt(
        music_category,
        "2099-01-03",
        [headline_record],
    )
    if headline_payload["events"][0]["evidence"][0].get("evidence_depth") != "headline":
        fail("Editor prompt lost headline Evidence depth")
    if headline_payload["events"][0]["evidence"][0].get("body"):
        fail("Editor prompt leaked unverified body text into headline Evidence")
    if not sources_from_records([headline_record]):
        fail("headline Evidence lost its clickable Google News source")
    headline_record["_editor_event_id"] = "g001"
    headline_normalized = normalize_result(
        {
            "items": [
                {
                    "information_complete": True,
                    "summary_points": [
                        {
                            "text": (
                                "1月2日公開のチャートで2週連続首位となり、"
                                "長渕剛／NiziUが続いた。"
                            ),
                            "evidence_ids": ["e001"],
                            "support_quotes": [
                                {
                                    "evidence_id": "e001",
                                    "quote": (
                                        "YOASOBI「THE BOOK for.」2週連続DLアルバム首位 "
                                        "長渕剛／NiziUが続く"
                                    ),
                                }
                            ],
                        }
                    ],
                    "watch_topic_id": "music_release_chart_tieup",
                    "event_id": "g001",
                    "title": "YOASOBI「THE BOOK for.」がDLアルバム首位を維持",
                    "topic_value_class": "cultural_or_audience_signal",
                    "priority_class": "standard",
                    "change_class": "material_update",
                }
            ],
            "excluded_events": [],
        },
        music_category,
        "2099-01-03",
        [headline_record],
    )
    if headline_normalized["coverage_complete"] or headline_normalized["items"]:
        fail("headline-only Evidence was allowed to become a public update")
    if not any(
        "insufficient_body_evidence" in rejection.get("reasons", [])
        for rejection in headline_normalized.get("rejected_items", [])
        if isinstance(rejection, dict)
    ):
        fail("headline-only rejection did not identify the missing body Evidence")
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
    topic_derivation_category = {
        "label": "OpenAI",
        "watch_topics": [
            {"id": "ipo_financing", "terms": ["IPO", "上場"]},
            {"id": "product_release", "terms": ["ChatGPT", "API"]},
        ],
    }
    if derived_watch_topic(
        topic_derivation_category,
        [{**english_record, "watch_topic_ids": []}],
        "ChatGPT広告への対応を開始",
    ) != "product_release":
        fail("horizon Evidence was not assigned to a deterministic watch topic")
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
    chinese_record = {
        **english_record,
        "title": "中国新能源汽车出口量大幅增加",
        "excerpt": "中国新能源汽车出口量同比增长40%，海外市场需求持续扩大。",
    }
    if not fact_supported_by_records(
        "中国の新エネルギー車輸出は前年比40%増加し、海外需要も拡大した。",
        [chinese_record],
    ):
        fail("translated fact lost its Chinese Evidence support")
    if fact_supported_by_records(
        "中国の新エネルギー車輸出は前年比50%増加した。",
        [chinese_record],
    ):
        fail("translated fact invented a number absent from Chinese Evidence")
    korean_record = {
        **english_record,
        "title": "한국 반도체 기업이 신규 공장을 발표",
        "excerpt": "한국 반도체 기업은 부산에 신규 공장을 건설하고 2028년에 가동할 계획이다.",
    }
    if not fact_supported_by_records(
        "韓国の半導体企業は釜山に新工場を建設し、2028年の稼働を計画する。",
        [korean_record],
    ):
        fail("translated fact lost its Korean Evidence support")
    if fact_supported_by_records(
        "韓国の半導体企業は釜山に新工場を建設し、2029年の稼働を計画する。",
        [korean_record],
    ):
        fail("translated fact invented a number absent from Korean Evidence")
    localized_decimal_record = {
        **english_record,
        "title": "IMF nâng dự báo GDP Việt Nam năm 2026 lên 7,5%",
        "excerpt": "Dự báo tăng từ 7,1% thêm 0,4 điểm phần trăm.",
    }
    if not fact_supported_by_records(
        "IMFはベトナムの2026年GDP成長率予測を7.1%から0.4ポイント引き上げ、7.5%とした。",
        [localized_decimal_record],
    ):
        fail("localized decimal commas lost translated numeric support")
    if fact_supported_by_records(
        "IMFはベトナムの2026年GDP成長率予測を7.6%とした。",
        [localized_decimal_record],
    ):
        fail("localized decimal commas accepted a different number")
    if numeric_claims("7,5%と1,491,932件") != {7.5, 1491932.0}:
        fail("decimal-comma normalization altered a thousands separator")
    short_year_record = {
        **english_record,
        "title": "世帯平均所得は25年調査で増加",
        "excerpt": (
            "厚生労働省が公表した2025年調査によると、24年の世帯平均所得は"
            "前年比7.3%増の575万2000円だった。額は94年のピークを下回る。"
        ),
    }
    if not fact_supported_by_records(
        "2024年の世帯平均所得は前年比7.3%増の575万2000円だった。",
        [short_year_record],
    ):
        fail("two-digit Japanese source years lost full-year fact support")
    if fact_supported_by_records(
        "2023年の世帯平均所得は前年比7.3%増の575万2000円だった。",
        [short_year_record],
    ):
        fail("two-digit Japanese source years supported a different year")
    bilingual_record = {
        **english_record,
        "title": "SpaceXがIPOを計画",
        "excerpt": "SpaceX is preparing for a potential $75 billion IPO.",
    }
    if not fact_supported_by_records(
        "SpaceXは約750億ドル規模のIPOを計画している。",
        [bilingual_record],
    ):
        fail("translated billion-to-億 amount lost source support")
    million_record = {
        **english_record,
        "title": "Bank of America provides OpenAI a $520 million credit line",
        "excerpt": "The bank provided OpenAI with a $520 million credit facility.",
    }
    if not fact_supported_by_records(
        "バンク・オブ・アメリカはOpenAIに5億2,000万ドルの信用枠を提供した。",
        [million_record],
    ):
        fail("translated million-to-億万 amount lost source support")
    if fact_supported_by_records(
        "バンク・オブ・アメリカはOpenAIに5億3,000万ドルの信用枠を提供した。",
        [million_record],
    ):
        fail("financial amount normalization accepted a different amount")
    plain_currency_record = {
        **english_record,
        "title": "America stopped selling new cars under $20,000",
        "excerpt": "Every new vehicle sold in the US now starts above $20,000.",
    }
    if not fact_supported_by_records(
        "米国では2万ドル未満の新車がなくなった。",
        [plain_currency_record],
    ):
        fail("plain dollar amount lost Japanese ten-thousand support")
    if fact_supported_by_records(
        "米国では2万1,000ドル未満の新車がなくなった。",
        [plain_currency_record],
    ):
        fail("plain currency normalization accepted a different amount")
    if normalized_financial_amounts("株価は68.95ドルだった。")[0] != [
        ("USD", 68.95)
    ]:
        fail("plain Japanese decimal currency amount was not normalized")
    population_record = {
        **english_record,
        "title": "Sichuan economy ranks sixth in China",
        "excerpt": (
            "Sichuan has the sixth-largest provincial economy in China "
            "and a population of more than 80 million."
        ),
    }
    if not fact_supported_by_records(
        "Sichuan（四川省）は人口8000万人超で、中国第6位の省経済規模を持つ。",
        [population_record],
    ):
        fail("non-financial English million quantity lost Japanese support")
    if not {4.3, 5.9}.issubset(numeric_claims("GDPは4．3％から5．9％へ上昇")):
        fail("full-width decimal points lost numeric support")
    if not {1.0, 44.361}.issubset(numeric_claims("首位タイムは1分44秒361")):
        fail("Japanese lap time lost source-compatible numeric support")
    fiscal_period_record = {
        **english_record,
        "title": "Ｓａｎｓａｎ、今期経常は125億～145億円、2.5円増配へ",
        "excerpt": "今期予想 2027.05 経常利益125億～145億円、年間配当5円。",
    }
    if not fact_supported_by_records(
        "Ｓａｎｓａｎ、2027年5月期に経常利益125億～145億円、配当を2.5円増配へ",
        [fiscal_period_record],
    ):
        fail("numeric period notation lost Japanese fiscal-year support")
    if fact_supported_by_records(
        "Ｓａｎｓａｎ、2028年5月期に経常利益125億～145億円、配当を2.5円増配へ",
        [fiscal_period_record],
    ):
        fail("numeric period notation accepted a different fiscal year")
    localized_count_record = {
        **english_record,
        "title": "Honda Pakistan offers Rs 200,000 off the HR-V VTI-S",
        "excerpt": (
            "Honda Pakistan launched a limited promotion with Rs 200,000 off "
            "the HR-V VTI-S and free registration."
        ),
    }
    if not fact_supported_by_records(
        "ホンダパキスタンはHR-V VTI-Sを20万ルピー割り引き、無料登録も付ける。",
        [localized_count_record],
    ):
        fail("Japanese ten-thousand notation lost source numeric support")
    if fact_supported_by_records(
        "ホンダパキスタンはHR-V VTI-Sを21万ルピー割り引く。",
        [localized_count_record],
    ):
        fail("Japanese ten-thousand notation accepted a different amount")
    rounded_count_record = {
        **english_record,
        "title": "Honda recalls 325,588 Odyssey minivans",
        "excerpt": "Honda recalled 325,588 Odyssey minivans over a rear-camera fault.",
    }
    if not fact_supported_by_records(
        "ホンダはオデッセイ約32万5千台を後方カメラ不具合でリコールした。",
        [rounded_count_record],
    ):
        fail("Explicitly approximate Japanese count lost rounded source support")
    if fact_supported_by_records(
        "ホンダはオデッセイ30万台を後方カメラ不具合でリコールした。",
        [rounded_count_record],
    ):
        fail("Exact Japanese count accepted a different source number")
    number_word_record = {
        **english_record,
        "title": "How an eight-year-old became Formula 1's tiniest team principal",
        "excerpt": "Eight-year-old George won the Formula 1 fan competition.",
    }
    if not fact_supported_by_records(
        "8歳のジョージがF1ファン向けコンテストで選出された。",
        [number_word_record],
    ):
        fail("English number word lost Japanese numeric support")
    if fact_supported_by_records(
        "9歳のジョージがF1ファン向けコンテストで選出された。",
        [number_word_record],
    ):
        fail("English number word accepted a different Japanese number")
    ordinal_record = {
        **english_record,
        "title": "Genesis leads at the fourth FIA WEC race weekend",
        "excerpt": "Genesis set the pace during the fourth race weekend.",
    }
    if not fact_supported_by_records(
        "ジェネシスがFIA WEC第4戦で先頭に立った。",
        [ordinal_record],
    ):
        fail("English ordinal lost Japanese numeric support")
    if fact_supported_by_records(
        "ジェネシスがFIA WEC第5戦で先頭に立った。",
        [ordinal_record],
    ):
        fail("English ordinal accepted a different Japanese number")
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
    _, cp51932_body = page_text(
        (
            "<html><head><title>文字コード検証</title></head><body>"
            "<article>ホンダが新技術の提供条件を公表した。</article>"
            "</body></html>"
        ).encode("euc_jp"),
        "text/html; charset=cp51932",
    )
    if "ホンダが新技術の提供条件を公表" not in cp51932_body:
        fail("cp51932 publisher response was not decoded as Japanese EUC")
    unknown_charset_text = decode_http_text(
        "OpenAIが新機能を公表した。".encode("utf-8"),
        'text/plain; charset="x-unknown-publisher-codec"',
    )
    if "OpenAIが新機能を公表" not in unknown_charset_text:
        fail("unknown publisher charset did not use a safe text fallback")
    corrupted_visual_record = {
        **english_record,
        "title": "Previewing a next-generation model",
        "excerpt": (
            "Title: Previewing a next-generation model URL Source: http://example.com "
            "Markdown Content: Skip to main content Research Products Business "
            + "0 . 5 6 . 55 0 . " * 180
        ),
    }
    if record_has_material_body(
        corrupted_visual_record["title"], corrupted_visual_record
    ):
        fail("numeric rendering noise was accepted as a material article body")
    metadata_only_record = {
        **english_record,
        "title": "Publishers seek sanctions over OpenAI evidence dispute",
        "excerpt": (
            "Title: Publishers seek sanctions over OpenAI evidence dispute "
            "URL Source: http:// Published Time: 2099-01-02 "
            "Warning: This page may not yet be fully loaded. Markdown Content:"
        ),
    }
    if record_has_material_body(
        metadata_only_record["title"], metadata_only_record
    ):
        fail("extraction metadata was accepted as a material article body")
    newsletter_shell_record = {
        **english_record,
        "title": "OpenAI CFO proposes useful intelligence per dollar metric",
        "excerpt": (
            "OpenAI CFO proposes useful intelligence per dollar metric. "
            "Sign up for our newsletter. Accept all cookies. Subscribe to read "
            "more. Privacy policy. Already a subscriber? Log in."
        ),
    }
    if record_has_material_body(
        newsletter_shell_record["title"], newsletter_shell_record
    ):
        fail("headline plus newsletter shell was accepted as article body")
    rich_article_record = {
        **english_record,
        "title": "Thinking MachinesがAIモデルInklingを公開",
        "excerpt": (
            "印刷機能のご利用には会員登録が必要です。ログイン。トップページ。"
            "AI・生成AI | タグをもっとみる "
            "Thinking Machinesは2099年1月2日、AIモデルInklingを公開した。"
            "Apache 2.0でHugging Faceから重みを提供する。"
            "テキスト、画像、音声、動画の45兆トークンで事前学習した。"
            "MoE方式で総9750億、推論時は410億パラメータを使う。"
            "最大100万トークンのコンテキストを備える。"
            "軽量版Inkling-Smallは総2760億、稼働120億である。"
            "Tinkerで独自データによる微調整に対応する。"
            "TogetherAI、Fireworks、Databricks、NVIDIA NIM、Unslothと連携する。"
            "人間の判断を拡張するAIを企業ミッションとして掲げている。"
            "AI・生成AIのおすすめコンテンツ OpenAIの関連記事を読む。"
        ),
    }
    rich_article_facts = editor_article_facts(rich_article_record)
    rich_article_text = " ".join(rich_article_facts)
    for anchor in (
        "Apache 2.0",
        "45兆トークン",
        "9750億",
        "410億",
        "100万トークン",
        "Inkling-Small",
        "Tinker",
        "NVIDIA NIM",
        "Unsloth",
    ):
        if anchor not in rich_article_text:
            fail(f"article fact inventory omitted a material source fact: {anchor}")
    if any(
        marker in rich_article_text
        for marker in ("会員登録", "おすすめコンテンツ", "企業ミッション")
    ):
        fail("article fact inventory retained page chrome or generic padding")
    salary_record = {
        **english_record,
        "title": "OpenAI hires an applied AI banking specialist",
        "excerpt": (
            "OpenAI is hiring an applied AI banking specialist in San Francisco. "
            "The role pays $185,000-$205,000 plus equity and requires at least "
            "two years of live transaction experience."
        ),
    }
    if not fact_supported_by_records(
        "基本給は18万5,000～20万5,000ドルで、株式報酬も付く。",
        [salary_record],
    ):
        fail("localized Japanese currency range lost valid source support")
    if fact_supported_by_records(
        "基本給は18万5,000～21万5,000ドルで、株式報酬も付く。",
        [salary_record],
    ):
        fail("localized Japanese currency range accepted a different amount")
    multi_source_records = [
        {
            **english_record,
            "label": "Official",
            "source_class": "official",
            "source_role": "primary_or_official",
            "url": "https://official.example/event",
            "publisher_url": "https://official.example/",
            "title": "OpenAI launches a new security model",
        },
        {
            **english_record,
            "label": "Security Specialist",
            "source_class": "specialist_media",
            "url": "https://specialist.example/event-analysis",
            "publisher_url": "https://specialist.example/",
            "title": "OpenAI launches a new security model",
            "excerpt": (
                "OpenAI launched the security model for enterprise customers. "
                "Independent testing found faster vulnerability triage and "
                "documented the deployment conditions."
            ),
        },
    ]
    retained_sources = select_clustered_evidence(openai_category, multi_source_records)
    if len(retained_sources) != 2:
        fail("event clustering discarded a distinct official or specialist source")
    analysis_fixture = {
        "inference": (
            "公式発表と専門媒体の検証結果は、企業向け脆弱性対応の"
            "自動化が実運用へ進む兆しを示唆する。"
        ),
        "counterargument": (
            "単一製品の導入結果だけでは市場全体への波及を確認できない。"
        ),
        "remaining_uncertainty": (
            "他社環境での再現性と長期運用時の誤検知率は未確認である。"
        ),
        "confidence": "medium",
        "evidence_ids": ["e001", "e002"],
    }
    normalized_analysis, analysis_errors = normalize_analysis_block(
        analysis_fixture,
        {"e001": multi_source_records[0], "e002": multi_source_records[1]},
    )
    if analysis_errors or not normalized_analysis:
        fail("valid multi-source analysis did not pass the separate analysis contract")
    _, thin_analysis_errors = normalize_analysis_block(
        {**analysis_fixture, "evidence_ids": ["e001"]},
        {"e001": multi_source_records[0]},
    )
    if "analysis_requires_two_independent_sources" not in thin_analysis_errors:
        fail("single-source text was accepted as multi-source analysis")
    category = {
        "label": "Test",
        "watch_topics": [
            {"id": "topic", "terms": [], "event_classes": []},
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
            "_editor_event_id": "g001",
        }
    ]
    facts = [
        "更新対象となる機能と提供条件が公表された。",
        "既存サービスからの移行手順と利用開始日が示された。",
    ]
    raw = {
        "items": [
            {
                "watch_topic_id": "topic",
                "event_id": "g001",
                "title": "OpenAIが開発者向け機能を更新",
                "topic_value_class": "decision_or_policy",
                "priority_class": "priority",
                "change_class": "material_update",
                "information_complete": True,
                "summary_points": [
                    {
                        "text": fact,
                        "evidence_ids": ["e001"],
                        "support_quotes": [
                            {"evidence_id": "e001", "quote": records[0]["excerpt"]}
                        ],
                    }
                    for fact in facts
                ],
            }
        ]
    }
    normalized = normalize_result(raw, category, "2099-01-03", records)
    if len(normalized["items"]) != 1 or not normalized["coverage_complete"]:
        fail("canonical normalization lost a valid evidence-backed summary")
    strict_raw = json.loads(json.dumps(raw, ensure_ascii=False))
    required_fixture_facts = editor_required_source_facts(
        editor_evidence_records(category, "2099-01-03", records)
    )["g001"]
    if len(required_fixture_facts) != 2:
        fail("source fact inventory did not preserve both fixture facts")
    for point, source_fact in zip(
        strict_raw["items"][0]["summary_points"],
        required_fixture_facts,
    ):
        point["source_fact_ids"] = [source_fact["id"]]
    strict_normalized = normalize_result(
        strict_raw,
        category,
        "2099-01-03",
        records,
        require_source_fact_coverage=True,
    )
    if len(strict_normalized["items"]) != 1 or not strict_normalized["coverage_complete"]:
        fail("source-to-summary fact recall rejected complete coverage")
    translated_source_facts = [
        {
            "id": "e001:f01",
            "text": (
                "The 3-trillion-parameter model is scheduled for release on July 27."
            ),
            "evidence_id": "e001",
        }
    ]
    if not summary_claims_supported_by_source_facts(
        "3兆パラメータのモデルは7月27日に公開予定だ。",
        translated_source_facts,
    ):
        fail("translated source-fact validation rejected supported numbers")
    if summary_claims_supported_by_source_facts(
        "4兆パラメータのモデルは7月27日に公開予定だ。",
        translated_source_facts,
    ):
        fail("translated source-fact validation accepted an invented number")
    misassigned_fact_raw = json.loads(json.dumps(strict_raw, ensure_ascii=False))
    misassigned_fact_raw["items"][0]["summary_points"][0]["source_fact_ids"] = [
        required_fixture_facts[1]["id"]
    ]
    misassigned_fact_raw["items"][0]["summary_points"][1]["source_fact_ids"] = [
        required_fixture_facts[0]["id"]
    ]
    misassigned_fact = normalize_result(
        misassigned_fact_raw,
        category,
        "2099-01-03",
        records,
        require_source_fact_coverage=True,
    )
    if len(misassigned_fact["items"]) != 1 or not misassigned_fact[
        "coverage_complete"
    ]:
        fail("event-wide fact recall rejected complete copy with misassigned ids")
    omitted_fact_raw = json.loads(json.dumps(strict_raw, ensure_ascii=False))
    omitted_fact_raw["items"][0]["summary_points"] = omitted_fact_raw["items"][0][
        "summary_points"
    ][:1]
    omitted_fact = normalize_result(
        omitted_fact_raw,
        category,
        "2099-01-03",
        records,
        require_source_fact_coverage=True,
    )
    if omitted_fact["coverage_complete"] or omitted_fact[
        "missing_source_fact_ids_by_event"
    ] != {"g001": [required_fixture_facts[1]["id"]]}:
        fail("source-to-summary fact recall accepted an omitted source fact")
    incomplete_raw = json.loads(json.dumps(raw, ensure_ascii=False))
    incomplete_raw["items"][0]["information_complete"] = False
    incomplete = normalize_result(
        incomplete_raw,
        category,
        "2099-01-03",
        records,
    )
    if incomplete["items"] or not any(
        "information_incomplete" in rejection.get("reasons", [])
        for rejection in incomplete.get("rejected_items", [])
        if isinstance(rejection, dict)
    ):
        fail("normalization accepted an item without information completeness")
    normalized_item = normalized["items"][0]
    if normalized_item["event_id"] != "g001":
        fail("normalization lost the event boundary needed for checkpointing")
    if normalized_item["summary"] != " ".join(facts):
        fail("normalization did not reuse the canonical summary points")
    if normalized_item["source_published_date"] != "2099-01-02":
        fail("normalization did not derive the source date from Evidence")
    if normalized_item["sources"][0]["url"] != "https://example.com/item":
        fail("normalization did not derive the source URL from Evidence")
    separate_event_records = [
        {**records[0], "_editor_event_id": "g001"},
        {
            **records[0],
            "_editor_event_id": "g002",
            "url": "https://example.com/pricing",
            "title": "OpenAIがAPI価格を改定",
            "excerpt": (
                "OpenAIはAPI価格を改定し、新料金の適用日を公表した。"
                "企業向けプランの対象範囲と移行手順も示した。"
            ),
            "watch_topic_ids": ["topic"],
        },
    ]
    mixed_event_raw = json.loads(json.dumps(raw))
    mixed_event_raw["items"][0]["event_id"] = "g001"
    mixed_event_raw["items"][0]["summary_points"] = [
        {
            "text": "対象機能と提供条件に加え、APIの新料金と適用日が公表された。",
            "evidence_ids": ["e001", "e002"],
            "support_quotes": [
                {"evidence_id": "e001", "quote": separate_event_records[0]["excerpt"]},
                {"evidence_id": "e002", "quote": separate_event_records[1]["excerpt"]},
            ],
        }
    ]
    if normalize_result(
        mixed_event_raw,
        category,
        "2099-01-03",
        separate_event_records,
    )["items"]:
        fail("normalization accepted a summary spanning separate event boundaries")
    omitted = normalize_result({"items": []}, category, "2099-01-03", records)
    if omitted["coverage_complete"] or omitted["missing_event_ids"] != ["g001"]:
        fail("normalization accepted an omitted publishable event")
    excluded = normalize_result(
        {
            "items": [],
            "excluded_events": [
                {"event_id": "g001", "reason": "wrong_entity_or_category"}
            ],
        },
        category,
        "2099-01-03",
        records,
    )
    if not excluded["coverage_complete"]:
        fail("normalization rejected an explicitly reviewed event exclusion")
    wrong_category_record = {
        **records[0],
        "title": "NBCC子会社が教育インフラ契約を獲得",
        "excerpt": (
            "NBCC子会社が教育インフラの管理契約4件を獲得した。"
            "契約総額は約159億ルピーとなる。"
            "関連記事一覧にはSoftBank Groupの株価情報も掲載されている。"
        ),
    }
    wrong_category_raw = json.loads(json.dumps(raw))
    wrong_category_raw["items"][0]["title"] = wrong_category_record["title"]
    wrong_category_raw["items"][0]["summary_points"] = [
        {
            "text": "契約は4件で、総額は約159億ルピーとなる。",
            "evidence_ids": ["e001"],
        }
    ]
    wrong_category = normalize_result(
        wrong_category_raw,
        {**category, "label": "SoftBank"},
        "2099-01-03",
        [wrong_category_record],
    )
    if (
        wrong_category["coverage_complete"]
        or wrong_category["items"]
        or not any(
            "category_identity" in rejection.get("reasons", [])
            for rejection in wrong_category["rejected_items"]
        )
        or wrong_category["deterministic_wrong_category_ids"]
    ):
        fail("normalization silently discarded a reviewed category disagreement")
    padded_raw = json.loads(json.dumps(raw))
    padded_raw["items"][0]["summary_points"].append(
        {
            "text": "市場全体の競争が激化するとみられる。",
            "evidence_ids": ["e001"],
            "support_quotes": [
                {"evidence_id": "e001", "quote": records[0]["excerpt"]}
            ],
        }
    )
    padded_result = normalize_result(padded_raw, category, "2099-01-03", records)
    if padded_result["items"] or not any(
        "unsupported_summary_point" in rejection.get("reasons", [])
        for rejection in padded_result.get("rejected_items", [])
        if isinstance(rejection, dict)
    ):
        fail("normalization silently removed an unsupported padding claim")
    repeated_raw = json.loads(json.dumps(raw))
    repeated_raw["items"][0]["summary_points"].append(
        repeated_raw["items"][0]["summary_points"][0]
    )
    repeated_result = normalize_result(
        repeated_raw, category, "2099-01-03", records
    )
    if len(repeated_result["items"]) != 1 or len(
        repeated_result["items"][0]["confirmed_facts"]
    ) != len(facts):
        fail("normalization did not remove repeated summary points")
    long_record = {
        **records[0],
        "url": "https://example.com/long-item",
        "excerpt": records[0]["excerpt"]
        + " ".join(
            f"追加条件{index}では対象機能{index}の適用範囲と開始手順を定めた。"
            for index in range(1, 41)
        ),
    }
    prompt = category_prompt(category, "2099-01-03", [long_record])
    prompt_evidence = prompt["events"][0]["evidence"][0]
    if (
        len(prompt_evidence["required_fact_ids"]) != MAX_EDITOR_SOURCE_FACTS
        or prompt_evidence["source_fact_overflow_count"]
        != prompt_evidence["article_fact_count"] - MAX_EDITOR_SOURCE_FACTS
    ):
        fail("editor prompt did not expose its bounded long-source fact selection")
    tail_record = {
        **records[0],
        "url": "https://example.com/article-with-related-links",
        "title": "OpenAIが開発者向け機能の提供条件を公表",
        "excerpt": (
            "OpenAIは対象機能の提供条件と利用開始日を公表した。"
            "Recent Published TOP STORIES Another company announced an unrelated merger. "
            "A separate unrelated market article followed."
        ),
    }
    tail_required = editor_required_source_facts(
        editor_evidence_records(category, "2099-01-03", [tail_record])
    )["g001"]
    if len(tail_required) != 1 or "unrelated" in tail_required[0]["text"]:
        fail("publisher related-story tail was made mandatory summary content")
    embedded_chrome_record = {
        **records[0],
        "url": "https://example.com/article-with-embedded-chrome",
        "title": "OpenAIが開発者向け機能の提供条件を公表",
        "excerpt": (
            "OpenAIは対象機能の提供条件と利用開始日を公表した。"
            "実験的な機能のため、記事本文と併せてご確認ください。"
            "指標は完了した重要業務と総費用を比較する。"
            "Download the Example App."
            "Related Articles: An unrelated company changed its strategy."
        ),
    }
    embedded_required_by_event = editor_required_source_facts(
        editor_evidence_records(category, "2099-01-03", [embedded_chrome_record])
    )
    embedded_required = next(iter(embedded_required_by_event.values()))
    embedded_text = " ".join(fact["text"] for fact in embedded_required)
    if (
        "重要業務" not in embedded_text
        or "実験的な機能" in embedded_text
        or "Download" in embedded_text
        or "unrelated" in embedded_text
    ):
        fail(
            "embedded publisher chrome changed the mandatory article facts: "
            + embedded_text
        )
    if set(prompt_evidence) != {
        "id",
        "watch_topic_ids",
        "date",
        "source",
        "source_class",
        "title",
        "evidence_depth",
        "body",
        "required_fact_ids",
        "article_fact_count",
        "source_fact_overflow_count",
    }:
        fail("editor prompt retained redundant evidence metadata")
    if set(prompt["events"][0]["novelty_context"]) != {
        "known_since",
        "explicit_event_dates",
    }:
        fail("editor prompt omitted compact event novelty context")
    large_prompt_records = [
        {
            **long_record,
            "url": f"https://example.com/large-item-{index}",
            "title": f"OpenAIが開発者向け機能{index}を更新",
        }
        for index in range(80)
    ]
    large_prompt = category_prompt(category, "2099-01-03", large_prompt_records)
    large_prompt_size = len(
        json.dumps(large_prompt, ensure_ascii=False, separators=(",", ":")).encode(
            "utf-8"
        )
    )
    large_prompt_evidence = [
        item
        for event in large_prompt["events"]
        for item in event["evidence"]
    ]
    if large_prompt_size <= 64_000 or len(large_prompt_evidence) != 80:
        fail("editor prompt silently shortened rich Evidence instead of leaving chunking to Editor")
    if (
        not any(item["required_fact_ids"] for item in large_prompt_evidence)
        or any(not item["body"] for item in large_prompt_evidence)
        or any(
            any(
            f"[{source_fact_id}]" not in item["body"]
            for source_fact_id in item["required_fact_ids"]
            )
            for item in large_prompt_evidence
        )
    ):
        fail("editor prompt lost required source facts before request chunking")
    summary_cases = [
        (
            "ジグザグ台湾とW2、越境EC支援で業務提携を発表",
            (
                "ジグザグ台湾は、越境EC支援サービスWorldShopping BIZを展開する"
                "ジグザグの台湾子会社である。国内事業者はWorldShopping BIZを1行の"
                "JavaScriptタグで導入し、海外販売を始められる。W2 Commerce Asiaが"
                "テスト販売、現地PR、台湾向けECとCRMを担い、両社は共同提案と"
                "セミナーを行う。"
            ),
            [
                "ジグザグ台湾は、越境EC支援サービスWorldShopping BIZを展開するジグザグの台湾子会社である。",
                "国内事業者はWorldShopping BIZを1行のJavaScriptタグで導入し、海外販売を始められる。",
                "W2 Commerce Asiaがテスト販売、現地PR、台湾向けECとCRMを担い、両社は共同提案とセミナーを行う。",
            ],
            ("台湾子会社", "1行", "CRM", "共同提案"),
        ),
        (
            "Hondaが2026年5月の生産・販売・輸出実績を公表",
            (
                "Hondaの2026年5月の世界生産は27万1,204台だった。"
                "中国生産は前年同月比18.4%減、国内販売は5万2,410台で同8.2%減となった。"
            ),
            [
                "Hondaの2026年5月の世界生産は27万1,204台だった。",
                "中国生産は前年同月比18.4%減、国内販売は5万2,410台で同8.2%減となった。",
            ],
            ("27万1,204台", "18.4%減", "5万2,410台", "8.2%減"),
        ),
        (
            "FPTとDataCamp、AI人材育成で戦略提携を発表",
            (
                "ベトナムIT大手FPTは米国のAI教育企業DataCampと戦略提携した。"
                "両社は日本企業向けにAI研修、スキル評価、人材変革プログラムを共同提供する。"
            ),
            [
                "ベトナムIT大手FPTは米国のAI教育企業DataCampと戦略提携した。",
                "両社は日本企業向けにAI研修、スキル評価、人材変革プログラムを共同提供する。",
            ],
            ("ベトナムIT大手", "米国のAI教育企業", "スキル評価", "日本企業向け"),
        ),
    ]
    for case_index, (case_title, case_body, case_points, required_terms) in enumerate(
        summary_cases,
        start=1,
    ):
        case_record = {
            **records[0],
            "_editor_event_id": "g001",
            "url": f"https://example.com/summary-case-{case_index}",
            "title": case_title,
            "excerpt": case_body,
        }
        case_raw = {
            "items": [
                {
                    "watch_topic_id": "topic",
                    "event_id": "g001",
                    "title": case_title,
                    "topic_value_class": "decision_or_policy",
                    "priority_class": "priority",
                    "change_class": "new_event",
                    "information_complete": True,
                    "summary_points": [
                        {
                            "text": point,
                            "evidence_ids": ["e001"],
                            "support_quotes": [
                                {"evidence_id": "e001", "quote": case_body}
                            ],
                        }
                        for point in case_points
                    ],
                }
            ]
        }
        case_result = normalize_result(
            case_raw,
            category,
            "2099-01-03",
            [case_record],
        )
        if len(case_result["items"]) != 1 or not case_result["coverage_complete"]:
            fail(f"cross-category summary case {case_index} was rejected")
        case_summary = case_result["items"][0]["summary"]
        if not all(term in case_summary for term in required_terms):
            fail(f"cross-category summary case {case_index} lost material information")
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
    discovered_reuters = {
        "url": "https://www.reuters.com/technology/example",
        "publisher_url": "https://www.reuters.com",
        "source_class": "discovered_media",
        "source_role": "independent_media_or_data",
    }
    if effective_source_class(discovered_reuters) != "major_media":
        fail("configured publisher authority was lost on a discovered article")
    delayed_recap = {
        "url": "https://unregistered.example/openai-release",
        "publisher_url": "https://unregistered.example",
        "source_class": "discovered_media",
        "source_role": "independent_media_or_data",
        "title": "OpenAIが新しい業務機能を発表",
        "excerpt": "OpenAIは2099年1月5日、新しい業務機能を発表した。",
    }
    if not record_is_delayed_untrusted_recap(delayed_recap, "2099-01-10"):
        fail("late untrusted retelling passed as a current event")
    if record_is_delayed_untrusted_recap(
        {**delayed_recap, "url": "https://openai.com/news/example"},
        "2099-01-10",
    ):
        fail("official event evidence was removed as a secondary recap")
    if record_is_delayed_untrusted_recap(
        {**delayed_recap, "title": "OpenAIが2099年度通期決算を発表"},
        "2099-01-10",
    ):
        fail("a final earnings event was removed as a routine recap")
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
    if same_material_event(
        "OpenAI",
        "New York Times-led group asks court to sanction OpenAI in copyright dispute",
    ):
        fail("generic entity title bridged a distinct material event")
    if same_material_event(
        "Claude（クロード）とは？料金や使い方、ChatGPTとの違いを徹底解説",
        "ChatGPT Workとは？機能・料金・使い方、Codexとの違いを徹底解説",
    ):
        fail("shared explainer boilerplate merged different subjects")
    if same_material_event(
        "OpenAIがGPT-5.6搭載のChatGPT WorkとCodex統合アプリを発表",
        "GPT-5.6正式発表、OpenAIとAnthropicのモデル競争が激化",
    ):
        fail("shared model version merged distinct product announcements")
    if not same_material_event(
        "Starship's Thirteenth Flight Test",
        "SpaceX targets July 16 for Starship Flight 13",
    ):
        fail("English ordinal and numeric event titles did not cluster")
    title_only_candidate = {
        "observed": True,
        "source_class": "discovered_media",
        "title": "Starship's Thirteenth Flight Test",
        "excerpt": "Starship's Thirteenth Flight Test",
    }
    body_peer = {
        "observed": True,
        "source_class": "discovered_media",
        "title": "SpaceX targets July 16 for Starship Flight 13",
        "excerpt": (
            "SpaceX set July 16 as the target and plans to deploy "
            "20 Starlink V3 satellites during the test."
        ),
    }
    if not material_candidate_has_resolved_peer(
        title_only_candidate,
        [title_only_candidate, body_peer],
    ):
        fail("body-rich peer did not resolve a title-only discovery URL")
    unrelated_peer = {
        **body_peer,
        "title": "SpaceX expands a ground-station network in South Africa",
    }
    if material_candidate_has_resolved_peer(
        title_only_candidate,
        [title_only_candidate, unrelated_peer],
    ):
        fail("unrelated body source resolved a distinct discovery event")
    if category_identity_ok(
        "SoftBank",
        "ソフトバンク×阪神の試合速報・結果",
        "福岡ソフトバンクホークスが阪神と対戦した。",
    ):
        fail("non-sports category accepted an ambiguous sports result")
    if category_identity_ok(
        "OpenAI",
        "国産生成AIモデルを企業向けに提供開始",
        "日本語対応の生成AI基盤を公開した。",
    ):
        fail("OpenAI category accepted a generic AI update")
    if category_identity_ok(
        "宇都宮ブレックス",
        "川崎ブレイブサンダースが新アリーナ施策を発表",
        "Bリーグでの取り組みを開始する。",
    ):
        fail("Brex category accepted another B.LEAGUE club")
    if editor_candidate_boundary(
        "Honda",
        "Hondaの夏休み体験授業でF1を特別展示",
        "Hondaは夏休み体験授業でF1を特別展示する。",
    ):
        fail("a non-material activity announcement reached the Editor")
    if not editor_candidate_boundary(
        "Honda",
        "2026年5月の生産・販売・輸出実績",
        "世界生産と国内販売の地域別実績を公表した。",
        source_label="Honda News",
    ):
        fail("configured official source identity did not preserve a generic title")
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
    duplicated_feed_headline = {
        **duplicate_record,
        "label": "Example News",
        "publisher_url": "https://example.com",
        "excerpt": (
            "OpenAIがCodex Securityのアップグレードを公開 Example News "
            "OpenAIがCodex Securityのアップグレードを公開"
        ),
    }
    if not record_has_only_headline(
        duplicated_feed_headline["title"],
        duplicated_feed_headline,
    ):
        fail("duplicated feed headline was mistaken for article body")
    listing_shell_record = {
        **duplicate_record,
        "label": "Finance News",
        "title": "225オプション・プット（期近・7月13日・権利行使価格6万6500円）",
        "excerpt": (
            "225オプション・プット（期近・7月13日・権利行使価格6万6500円）。"
            "ニューストップ ヘッドライン 新着 市況・概況 関連ニュース。"
            "情報提供会社のリンクは外部サイトへ移動します。"
            "投資判断はご自身の判断で行ってください。"
        ),
    }
    if publication_evidence_record(
        {"label": "日本経済", "watch_topics": []},
        "2099-01-03",
        listing_shell_record,
    ):
        fail("headline plus page shell was accepted as substantive Evidence")
    aggregate_digest = {
        **duplicate_record,
        "title": "Example社：今の株価の理由は？値動きの背景をAIが解説",
        "excerpt": (
            "株価動向をまとめる。情報源を見る ニュース - 製品更新。"
            "情報源を見る ニュース - 人事変更。情報源を見る ニュース - 決算発表。"
        ),
    }
    if not record_is_aggregate_digest(
        aggregate_digest["title"],
        aggregate_digest,
    ):
        fail("multi-event digest page was accepted as one publication event")
    body_rich_record = {
        **duplicate_record,
        "excerpt": (
            "Codex Securityでは脆弱性検出後の修正支援が更新された。"
            "企業向け提供の対象範囲も拡大された。"
        ),
    }
    if not publication_evidence_record(openai_category, "2099-01-03", body_rich_record):
        fail("body-rich record was rejected as publication Evidence")
    year_only_headline = {
        **duplicate_record,
        "title": "OpenAI explains strategy after tough start to 2026 campaign",
        "excerpt": "OpenAI explains strategy after tough start to 2026 campaign",
    }
    if headline_supports_distinct_summary(year_only_headline["title"]):
        fail("calendar year alone made a headline look summary-rich")
    if publication_evidence_record(openai_category, "2099-01-03", year_only_headline):
        fail("year-only headline repetition was accepted as publication Evidence")
    relational_headline = "OpenAI partners with Example Corp to launch a service"
    if not headline_supports_distinct_summary(relational_headline):
        fail("multi-party headline lost its distinct summary detail")
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
            "semantic-background-for-editor",
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
    if candidate_matches_publisher(
        {"publisher_url": "https://example.jp"},
        "https://unrelated.example.com/article",
    ):
        fail("article enrichment crossed publisher domains")
    if not candidate_matches_publisher(
        {"publisher_url": "https://example.jp"},
        "https://news.example.jp/article",
    ):
        fail("article enrichment rejected a publisher subdomain")
    if not reader_resolved_discovery_url(
        "https://news.google.com/rss/articles/example?oc=5",
        "https://r.jina.ai/http://news.google.com/rss/articles/example?oc=5",
    ):
        fail("Google News Reader resolution was not recognized")
    original_request_bytes = request_bytes
    original_post_form_bytes = post_form_bytes
    original_google_news_decoding_params = google_news_decoding_params
    decoded_headline = "OpenAIが米政府への5％株式譲渡案を協議"
    encoded_google_url = "https://news.google.com/rss/articles/decode-example?oc=5"

    def fake_decode_request(url: str, timeout: int = 15) -> tuple[bytes, str, str]:
        if url.startswith("https://news.google.com/articles/decode-example"):
            page = (
                '<c-wiz><div jscontroller="article" '
                'data-n-a-id="decode-example" data-n-a-ts="123" '
                'data-n-a-sg="signature"></div></c-wiz>'
            )
            return page.encode(), "text/html; charset=utf-8", url
        if url == "https://example.com/openai-government-stake":
            body = (
                f"Title: {decoded_headline}\n"
                "Published Time: 2099-01-02T12:00:00+09:00\n"
                "Markdown Content: OpenAIは米政府に株式5％を譲渡する案を協議した。"
                "評価額に基づく持分額と議会承認の可能性も報じられた。"
            )
            return body.encode(), "text/plain; charset=utf-8", url
        raise urllib.error.URLError(f"unexpected URL: {url}")

    def fake_decode_post(
        url: str,
        values: dict[str, str],
        timeout: int = 15,
    ) -> tuple[bytes, str, str]:
        if "decode-example" not in values.get("f.req", ""):
            raise urllib.error.URLError("article id missing from decode request")
        inner = json.dumps(
            ["garturlres", "https://example.com/openai-government-stake", 1],
            separators=(",", ":"),
        )
        response = [["wrb.fr", "Fbv4je", inner, None, None, None, ""]]
        return (
            (")]}'\n\n" + json.dumps(response, separators=(",", ":"))).encode(),
            "application/json; charset=utf-8",
            url,
        )

    globals()["request_bytes"] = fake_decode_request
    globals()["post_form_bytes"] = fake_decode_post
    globals()["google_news_decoding_params"] = lambda _: (
        "decode-example",
        "123",
        "signature",
    )
    try:
        decoded_record = article_record_from_candidate(
            "OpenAI",
            {
                "label": "Example News",
                "url": encoded_google_url,
                "publisher_url": "https://example.com",
                "source_class": "discovered_media",
                "observed": True,
                "published_date": "2099-01-02",
                "title": decoded_headline,
                "excerpt": decoded_headline,
            },
            decoded_headline,
            encoded_google_url,
            decoded_headline,
            decoded_headline,
        )
    finally:
        globals()["request_bytes"] = original_request_bytes
        globals()["post_form_bytes"] = original_post_form_bytes
        globals()["google_news_decoding_params"] = original_google_news_decoding_params
    if (
        not decoded_record
        or decoded_record.get("url")
        != "https://example.com/openai-government-stake"
        or not record_has_material_body(decoded_headline, decoded_record)
    ):
        fail("Google News URL was not resolved to body-rich publisher Evidence")
    original_decode_once = _google_news_publisher_url_once
    retry_results = iter([None, "https://example.com/retried-article"])
    globals()["_google_news_publisher_url_once"] = lambda _: next(retry_results)
    try:
        retried_url = google_news_publisher_url(encoded_google_url)
    finally:
        globals()["_google_news_publisher_url_once"] = original_decode_once
    if retried_url != "https://example.com/retried-article":
        fail("Google News URL resolution did not retry a transient failure once")
    original_request_bytes = request_bytes
    original_google_news_decoding_params = google_news_decoding_params
    reader_headline = "OpenAIが米政府への5％株式譲渡案を協議"
    reader_google_url = "https://news.google.com/rss/articles/example?oc=5"

    def fake_reader_request(url: str, timeout: int = 15) -> tuple[bytes, str, str]:
        if "r.jina.ai" not in url:
            raise urllib.error.URLError("direct Google News fetch unavailable")
        body = (
            f"Title: {reader_headline}\n"
            "URL Source: http://news.google.com/rss/articles/example?oc=5\n"
            "Published Time: 2099-01-02T12:00:00+09:00\n"
            "Markdown Content: OpenAIは米政府に株式5％を譲渡する案を協議した。"
            "評価額に基づく持分額と議会承認の可能性も報じられた。"
        )
        return body.encode(), "text/plain; charset=utf-8", jina_url(reader_google_url)

    globals()["request_bytes"] = fake_reader_request
    globals()["google_news_decoding_params"] = lambda _: None
    try:
        reader_record = article_record_from_candidate(
            "OpenAI",
            {
                "label": "Example News",
                "url": reader_google_url,
                "publisher_url": "https://example.com",
                "source_class": "discovered_media",
                "observed": True,
                "published_date": "2099-01-02",
                "title": reader_headline,
                "excerpt": reader_headline,
            },
            reader_headline,
            reader_google_url,
            reader_headline,
            reader_headline,
        )
    finally:
        globals()["request_bytes"] = original_request_bytes
        globals()["google_news_decoding_params"] = original_google_news_decoding_params
    if not reader_record or not record_has_material_body(reader_headline, reader_record):
        fail("Google News Reader body was not retained as publication Evidence")
    if event_probe_query(fpt_headline) not in article_search_queries({}, fpt_headline):
        fail("article enrichment omitted the bounded event probe query")
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
    stale_rebroadcast = {
        "published_date": "2099-07-08",
        "title": "【リーグ情報】選手契約継続ほか 6月18日号 ライブ配信",
        "url": "https://example.com/rebroadcast",
        "excerpt": "【リーグ情報】選手契約継続ほか 6月18日号 ライブ配信",
    }
    if record_document_is_current(stale_rebroadcast, "2099-07-10"):
        fail("stale rebroadcast event date passed current Evidence validation")
    for current_title in (
        "チャート（7/8公開）で2週連続首位",
        "展覧会を7月24日から開催",
        "Event announced July 8",
    ):
        if not record_document_is_current(
            {**stale_rebroadcast, "title": current_title},
            "2099-07-10",
        ):
            fail(f"current or upcoming title date was rejected: {current_title}")
    if record_document_is_current(
        {
            "source_class": "discovered_media",
            "url": "https://example.com/2099/06/09/old-story/",
            "title": "企業が新計画を発表",
            "excerpt": "企業は新計画の詳細を発表した。",
        },
        "2099-07-02",
    ):
        fail("stale URL date passed current Evidence validation")
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
    if discovery_record_is_material(headline_only_cross_domain):
        fail("headline-only discovery was treated as resolved body Evidence")
    if not discovery_record_needs_resolution(headline_only_cross_domain):
        fail("headline-only material discovery was discarded before enrichment")
    publisher_portfolio = configured_discovery_publishers()
    required_publishers = {
        "Reuters",
        "Kyodo News",
        "NHK News",
        "Financial Times",
        "Bloomberg",
        "The Wall Street Journal",
        "Nikkei",
        "The Information",
        "MIT Technology Review",
        "IEEE Spectrum",
        "Semafor",
        "TechCrunch",
        "The Register",
    }
    configured_publishers = {
        str(publisher.get("label"))
        for publishers in publisher_portfolio.values()
        for publisher in publishers
    }
    if not required_publishers <= configured_publishers:
        fail("publisher portfolio omitted a required broad or technology source")
    softbank_domestic_publishers = {
        str(publisher.get("label"))
        for publisher in discovery_publishers_for_topic(
            "SoftBank", "domestic_services"
        )
    }
    if not {"Business Network", "ITmedia Mobile", "K-tai Watch"} <= (
        softbank_domestic_publishers
    ):
        fail("topic-specific recovery omitted Japanese telecom specialists")
    if "Financial Times" in softbank_domestic_publishers:
        fail("topic-specific recovery fell back to unrelated broad publishers")
    yoasobi_depth_publishers = {
        str(publisher.get("label"))
        for publisher in discovery_publishers_for_topic(
            "YOASOBI / 幾田りら", "music_release_chart_tieup"
        )
    }
    if not {"Billboard Japan", "Natalie Music", "ORICON NEWS"} <= (
        yoasobi_depth_publishers
    ):
        fail("registered music specialists were omitted from depth discovery")
    asia_depth_publishers = discovery_publishers_for_topic(
        "アジア経済", "china_macro_policy"
    )
    if not asia_depth_publishers or asia_depth_publishers[0].get(
        "source_class"
    ) != "specialist_media":
        fail("regional macro depth discovery did not prioritize specialists")
    f1_depth_specs = depth_recovery_queries(
        configured_category_contracts()["F1"],
        "2099-07-02",
        [],
    )
    if not f1_depth_specs or not any(
        spec.get("target_source_class") == "specialist_media"
        and spec.get("allowed_hosts")
        for spec in f1_depth_specs
    ):
        fail("depth recovery did not target a vetted category specialist")
    if len(f1_depth_specs) > 6:
        fail("depth recovery exceeded its bounded query budget")
    if any(
        len(spec.get("allowed_hosts", [])) != 1
        or str(spec.get("query", "")).count("site:") != 1
        for spec in f1_depth_specs
        if spec.get("allowed_hosts")
    ):
        fail("targeted depth recovery did not isolate one publisher domain")
    if any(
        spec.get("fallback_provider") != "google_news_rss"
        for spec in f1_depth_specs
    ):
        fail("targeted depth recovery omitted its bounded search fallback")
    original_request_bytes = request_bytes

    def unavailable_search(
        url: str,
        timeout: int = 15,
    ) -> tuple[bytes, str, str]:
        raise urllib.error.URLError("self-test search outage")

    globals()["request_bytes"] = unavailable_search
    try:
        _, fallback_check = fetch_discovery_spec(
            configured_category_contracts()["F1"],
            "2099-07-02",
            f1_depth_specs[0],
        )
    finally:
        globals()["request_bytes"] = original_request_bytes
    if (
        not fallback_check.get("fallback_attempted")
        or fallback_check.get("fallback_from_provider") != "bing_rss"
        or fallback_check.get("provider") != "google_news_rss"
    ):
        fail("targeted depth recovery did not execute its one bounded fallback")
    if record_matches_allowed_hosts(
        {
            "url": "https://en.wikipedia.org/wiki/Formula_One",
            "publisher_url": "https://en.wikipedia.org/",
        },
        ["racefans.net"],
    ):
        fail("off-domain search noise passed a targeted publisher boundary")
    if not record_matches_allowed_hosts(
        {
            "url": "https://www.racefans.net/2099/07/report/",
            "publisher_url": "https://www.racefans.net/",
        },
        ["racefans.net"],
    ):
        fail("a valid targeted publisher result failed its domain boundary")
    print("NIGHT SIGNAL CORE SELF-TEST PASSED")
