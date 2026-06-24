#!/usr/bin/env python3
"""Fail publication when NIGHT SIGNAL is stale or structurally incomplete."""

from __future__ import annotations

import re
import sys
import json
import difflib
import html as html_lib
from urllib.parse import unquote
from datetime import datetime
from pathlib import Path

from coverage_audit import effective_on_or_after, load_contract, max_adopted_source_age_days, validate_coverage_contract


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "site"
COVERAGE_CONTRACT = load_contract()
MIN_CHANGED_CARDS_VS_PREVIOUS = int(COVERAGE_CONTRACT.get("minimum_changed_cards_vs_previous_issue", 1))
MAX_UNCHANGED_CARD_RATIO_VS_PREVIOUS = 0.70
MAX_ISSUE_SIMILARITY_VS_PREVIOUS = 0.94
MAX_DETAIL_SIMILARITY_VS_PREVIOUS = 0.95
EXPECTED_HERO_TITLE = "NIGHT SIGNAL"
EXPECTED_HERO_CONCEPT_TERMS = ["眠りにつく前に", "世界の輪郭", "次の朝"]
LEGACY_HERO_CONCEPT_TERMS = ["一次情報", "変化点", "判断"]
HERO_COPY_EFFECTIVE_DATE = "2026-05-25"
PUBLIC_SELECTION_RATIONALE_BAN_EFFECTIVE_DATE = "2026-05-25"
PUBLIC_ABSTRACT_FRAMING_BAN_EFFECTIVE_DATE = "2026-06-01"
LATEST_THREE_DAY_LABELS = {0: "今日", 1: "昨日", 2: "一昨日"}
HERO_DAILY_TOPIC_TERMS = [
    "OpenAI",
    "SoftBank",
    "Honda",
    "SpaceX",
    "TanStack",
    "CRS-34",
    "Starship",
    "Dragon",
    "Codex",
    "ホンダ",
    "ソフトバンク",
]

REQUIRED_CATEGORIES = [category["label"] for category in COVERAGE_CONTRACT["categories"]]
CATEGORY_CONFIG_BY_LABEL = {
    category["label"]: category for category in COVERAGE_CONTRACT["categories"]
}
REQUIRED_SECTIONS = {
    category["section_id"]: category["label"] for category in COVERAGE_CONTRACT["categories"]
}

MIN_CARDS_PER_SECTION = int(COVERAGE_CONTRACT.get("minimum_published_cards_per_category", 0))
MIN_DETAIL_TEXT_CHARS = 300
MAX_SOURCE_LINKS_PER_DETAIL = 3

REQUIRED_COVERAGE_TERMS = [
    "公式",
    "主要報道",
    "専門媒体",
    "SNS/X",
    "YouTube",
    "データ",
    "予定",
    "反証",
    "保留",
    "除外",
    "未確認",
]

REQUIRED_SOURCE_CLASSES = list(COVERAGE_CONTRACT["source_classes"])
REQUIRED_DECISION_CLASSES = list(COVERAGE_CONTRACT["decision_classes"])

TITLE_POLICY_LEAK_TERMS = [
    "一次で固定",
    "一次資料",
    "一次更新",
    "数字を固定",
    "完了扱い",
    "補助線",
    "採用は一次",
    "採用前",
    "保留に落と",
    "直検索",
    "カバレッジ",
    "品質ゲート",
    "最新採用",
]

DETAIL_POLICY_LEAK_TERMS = TITLE_POLICY_LEAK_TERMS + [
    "今夜やること",
    "今夜のチェックリスト",
    "今夜の運用ルール",
    "機械的",
    "監査メモ",
    "復旧版",
    "当日版が未生成",
]

HEADLINE_ABSTRACT_LEAK_TERMS = [
    "個人の文脈",
    "安全の文脈",
    "同じ地図",
    "CPUの現場",
    "投資枠とインフラ",
    "ロスター更新",
    "打ち上げ結果",
    "製品”と“資本",
    "扱い始める",
    "温度感",
    "前に出す",
    "同じ線",
    "現物",
    "足回り",
    "見る日",
    "読む日",
    "意味",
    "更新導線",
    "進捗",
    "再確認",
    "上書き",
    "落とし込",
    "固定する",
    "確認する",
    "読む",
    "見る",
]

PUBLIC_ABSTRACT_FRAMING_TERMS = [
    "説明軸",
    "IR文脈",
    "読み筋",
    "読める状態",
    "見せる材料",
    "更新局面",
    "並行管理",
    "競争軸",
    "発表局面",
    "材料になっている",
]

HEADLINE_FORBIDDEN_CHARS = ["→", "“", "”"]
GENERIC_HEADLINE_STARTS = ["何が", "なぜ", "どう見る", "読み方", "ポイント"]
DETAIL_ALIGNMENT_KEYWORDS = [
    "ChatGPT",
    "OpenAI",
    "Dell",
    "Codex",
    "TanStack",
    "証明書",
    "家計",
    "口座",
    "安全",
    "リスク",
    "SoftBank",
    "Arm",
    "データセンター",
    "バッテリー",
    "電源",
    "災害",
    "Honda",
    "EV",
    "HV",
    "赤字",
    "関税",
    "中国",
    "販売",
    "生産",
    "ADUO",
    "FIA",
    "カナダ",
    "Aston",
    "PU",
    "CRS-34",
    "Falcon",
    "Dragon",
    "ISS",
    "Starship",
    "Flight 12",
    "Starlink",
    "ベトナム",
    "IIP",
    "インド",
    "CPI",
    "RBI",
    "外貨準備",
    "名古屋",
    "ジェレット",
    "ニュービル",
    "D.J.",
    "コロネル",
    "スタッフ",
    "米株",
    "S&P",
    "Nasdaq",
    "Dow",
    "ファンド",
    "ETF",
    "ICI",
    "フロー",
]
DETAIL_FORBIDDEN_SECTION_HEADINGS = [
    "チェック観点",
    "次の確認",
    "次の予定",
    "読むポイント",
    "今回の要点",
    "一次で押さえる点",
]
LEGACY_MIN_SUMMARY_LEAD_CHARS = 180
LEGACY_DETAIL_SUMMARY_HEADING = "30秒概要"
DEFAULT_DETAIL_SUMMARY_HEADING = "要点と背景"

READER_PROCESS_LEAK_TERMS = [
    "今日の再抽出",
    "今日の更新",
    "本日の更新",
    "本日の修正",
    "前日コピー",
    "日付だけ",
    "主軸に切り替え",
    "本線に更新",
    "差し替え",
    "品質ゲート",
    "監査メモ",
    "作業を書",
    "修正しました",
    "再公開",
    "復旧版",
    "カードを",
    "5/19版では",
    "版では",
    "導線",
    "点検",
    "拾う",
    "一次ソースで",
    "確認して",
    "公式/主要報道",
    "位置づけ",
    "チェックリスト",
    "読むポイント",
    "次の確認",
    "上書きする",
    "混ぜない",
    "落とし込",
    "固定し",
    "確認として",
    "最新採用",
]
READER_PROCESS_LEAK_PATTERNS = [
    (r"作業(?:指示|説明|メモ|語|上|として|を書)", "authoring work wording"),
]

FORBIDDEN_PUBLIC_CONFIRMATION_LAYER_TERMS = [
    "確認情報",
    "直近3日で追加表示する確認情報はありません",
    "候補題目",
]

PUBLIC_SUMMARY_PROCESS_PATTERNS = [
    (r"(?:採用|掲載|公開)(?:判断|基準|可否|候補)", "selection/publication decision"),
    (r"(?:調査|探索|監視|収集)(?:方法|経路|方針|対象|チャネル|チャンネル)", "research procedure"),
    (r"(?:見る|追う|確認する|収集する)必要がある", "research instruction"),
    (r"(?:本人|スタッフ|公式|SNS|X|Instagram|YouTube).{0,24}(?:毎回|必ず|継続して)(?:見る|確認|追う)", "monitoring instruction"),
    (r"(?:原文確認先|参照経路|参照先).{0,24}(?:併記|揃え|区別)", "source-handling commentary"),
    (r"(?:本項目|本記事).{0,24}(?:区別して掲載|掲載する)", "publication commentary"),
    (r"(?:水準|差分|構成比).{0,24}(?:確認したい|見たい|読むべき)", "reader instruction"),
]


def issue_date_from_args() -> str:
    if len(sys.argv) > 1:
        return sys.argv[1]
    return datetime.now().strftime("%Y-%m-%d")


def fail(message: str) -> None:
    print(f"QUALITY GATE FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def read(path: Path) -> str:
    if not path.exists():
        fail(f"missing file: {path.relative_to(ROOT)}")
    return path.read_text(encoding="utf-8")


def section_before_history(html: str) -> str:
    return html.split('<section class="section" id="history">', 1)[0]


def card_blocks(html: str) -> list[str]:
    body = section_before_history(html)
    return re.findall(r"<article class=\"(?:card|priority-card)[^\"]*\">.*?</article>", body, flags=re.S)


def normal_card_blocks(html: str) -> list[str]:
    return [card for card in card_blocks(html) if "priority-card" not in card]


def retained_card(card: str) -> bool:
    match = re.search(r'<article class="([^"]*)"', card)
    return bool(match and "retained" in match.group(1).split())


def current_card_blocks(html: str) -> list[str]:
    return [card for card in card_blocks(html) if not retained_card(card)]


def without_retained_cards(html: str) -> str:
    return re.sub(r'<article class="[^"]*\bretained\b[^"]*">.*?</article>', "", html, flags=re.S)


def card_dates(card: str) -> list[str]:
    # Only visible metadata dates count. Links such as
    # href="2026-05-13/details/..." are publication paths, not item dates.
    return re.findall(r"<span class=\"pill[^\"]*\">(?:今日|昨日|一昨日)?\s*(20\d{2}-\d{2}-\d{2})</span>", card)


def card_title(card: str) -> str:
    match = re.search(r"<h3>(.*?)</h3>", card, flags=re.S)
    if not match:
        return "(no title)"
    text = html_lib.unescape(re.sub(r"<.*?>", "", match.group(1)))
    return re.sub(r"\s+", " ", text).strip()


def card_cluster_key(card: str) -> str:
    text = card_title(card)
    text = re.sub(r"\s+執筆(?:\s+[-–—].*)?$", " ", text)
    text = re.sub(r"\s+[-–—]\s+[^。]{1,120}$", " ", text)
    text = re.sub(r"https?://\S+", " ", text)
    text = re.sub(r"20\d{2}[-/.]\d{1,2}[-/.]\d{1,2}", " ", text)
    text = re.sub(r"[^\w一-龥ぁ-んァ-ンー%％$]+", " ", text.lower())
    stopwords = {"news", "latest", "update", "updates", "発表", "速報", "ニュース", "最新", "今日", "昨日", "一昨日"}
    tokens = [token for token in text.split() if token and token not in stopwords]
    return " ".join(tokens[:14])


def seen_card_cluster(seen: dict[str, str], key: str) -> str | None:
    if not key:
        return None
    for seen_key, title in seen.items():
        if (
            key == seen_key
            or (len(key) >= 12 and seen_key.startswith(key))
            or (len(seen_key) >= 12 and key.startswith(seen_key))
        ):
            return title
    return None


def card_detail_href(card: str) -> str | None:
    match = re.search(r'href="([^"]*details/([^"#?]+\.html))', card)
    if not match:
        return None
    return match.group(2)


def card_detail_target(issue_date: str, card: str) -> tuple[str, str] | None:
    match = re.search(r'href="([^"]*details/([^"#?]+\.html))', card)
    if not match:
        return None
    href = match.group(1)
    dated = re.search(r'(?:^|\.\./)(20\d{2}-\d{2}-\d{2})/details/', href)
    return (dated.group(1) if dated else issue_date, match.group(2))


def page_titles(html: str) -> list[str]:
    titles = []
    for match in re.finditer(r"<h3>(.*?)</h3>", section_before_history(html), flags=re.S):
        text = html_lib.unescape(re.sub(r"<.*?>", "", match.group(1)))
        titles.append(re.sub(r"\s+", " ", text).strip())
    return titles


def heading_texts(html: str, tags: tuple[str, ...]) -> list[str]:
    tag_pattern = "|".join(tags)
    texts = []
    for match in re.finditer(rf"<({tag_pattern})[^>]*>(.*?)</\1>", html, flags=re.S):
        text = html_lib.unescape(re.sub(r"<.*?>", "", match.group(2)))
        texts.append(re.sub(r"\s+", " ", text).strip())
    return texts


def visible_text(html: str) -> str:
    html = re.sub(r"<script\b.*?</script>", "", html, flags=re.S | re.I)
    html = re.sub(r"<style\b.*?</style>", "", html, flags=re.S | re.I)
    text = html_lib.unescape(re.sub(r"<[^>]+>", " ", html))
    return re.sub(r"\s+", " ", text).strip()


def normalize_for_similarity(text: str) -> str:
    text = visible_text(text)
    text = re.sub(r"20\d{2}[-/.]\d{2}[-/.]\d{2}", "<date>", text)
    text = re.sub(r"20\d{2}年\d{1,2}月\d{1,2}日", "<date>", text)
    text = re.sub(r"night-brief-web-sample-<date>\.html", "night-brief-web-sample-<date>.html", text)
    text = re.sub(r"\b\d{4,}\b", "<num>", text)
    return text.lower()


def card_signature(card: str) -> str:
    title = card_title(card)
    paragraphs = []
    for match in re.finditer(r"<p[^>]*>(.*?)</p>", card, flags=re.S):
        paragraphs.append(visible_text(match.group(1)))
    return normalize_for_similarity(title + " " + " ".join(paragraphs))


def previous_issue_sample(issue_date: str) -> Path | None:
    candidates = []
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    for path in ROOT.glob("night-brief-web-sample-*.html"):
        match = re.fullmatch(r"night-brief-web-sample-(\d{4}-\d{2}-\d{2})\.html", path.name)
        if not match:
            continue
        candidate_dt = datetime.strptime(match.group(1), "%Y-%m-%d").date()
        if candidate_dt < issue_dt:
            candidates.append((candidate_dt, path))
    if not candidates:
        return None
    return sorted(candidates)[-1][1]


def previous_issue_date(issue_date: str) -> str | None:
    previous_path = previous_issue_sample(issue_date)
    if not previous_path:
        return None
    match = re.fullmatch(r"night-brief-web-sample-(\d{4}-\d{2}-\d{2})\.html", previous_path.name)
    if not match:
        return None
    return match.group(1)


def validate_reader_process_language(context: str, html: str) -> None:
    text = visible_text(html)
    leaks = [term for term in READER_PROCESS_LEAK_TERMS if term in text]
    pattern_leaks = [label for pattern, label in READER_PROCESS_LEAK_PATTERNS if re.search(pattern, text)]
    if leaks or pattern_leaks:
        fail(f"{context} contains production/process wording: " + ", ".join((leaks + pattern_leaks)[:8]))


def validate_no_confirmation_layer(context: str, html: str) -> None:
    text = visible_text(section_before_history(html))
    leaks = [term for term in FORBIDDEN_PUBLIC_CONFIRMATION_LAYER_TERMS if term in text]
    if leaks:
        fail(f"{context} still exposes deprecated confirmation information: " + ", ".join(leaks))


def validate_public_summary_language(context: str, text: str, issue_date: str) -> None:
    if re.search(r"[。．.]{2,}|[！？!?]{2,}", text):
        fail(f"{context} contains repeated punctuation")
    sentences = [part.strip() for part in re.split(r"(?<=[。！？!?])", text) if part.strip()]
    seen_sentences: set[str] = set()
    for sentence in sentences:
        key = re.sub(r"[、。．.!！?？\s「」『』（）()]", "", sentence).lower()
        if key and key in seen_sentences:
            fail(f"{context} repeats the same sentence")
        seen_sentences.add(key)
    violations = [
        label
        for pattern, label in PUBLIC_SUMMARY_PROCESS_PATTERNS
        if re.search(pattern, text)
    ]
    if violations:
        fail(f"{context} contains editorial/research procedure wording: " + ", ".join(violations))
    if issue_date >= PUBLIC_ABSTRACT_FRAMING_BAN_EFFECTIVE_DATE:
        abstract_terms = [term for term in PUBLIC_ABSTRACT_FRAMING_TERMS if term in text]
        if abstract_terms:
            fail(f"{context} contains abstract/editorial framing wording: " + ", ".join(abstract_terms[:8]))


def detail_summary_heading(issue_dt) -> str:
    if effective_on_or_after(COVERAGE_CONTRACT, "detail_summary_heading_effective_date", issue_dt):
        heading = COVERAGE_CONTRACT.get("detail_summary_heading", DEFAULT_DETAIL_SUMMARY_HEADING)
        if isinstance(heading, str) and heading.strip():
            return heading.strip()
        return DEFAULT_DETAIL_SUMMARY_HEADING
    return LEGACY_DETAIL_SUMMARY_HEADING


def detail_min_summary_chars(issue_dt) -> int:
    if effective_on_or_after(COVERAGE_CONTRACT, "detail_depth_effective_date", issue_dt):
        return int(COVERAGE_CONTRACT.get("minimum_current_detail_summary_chars", 240))
    if effective_on_or_after(COVERAGE_CONTRACT, "summary_quality_effective_date", issue_dt):
        return int(COVERAGE_CONTRACT.get("minimum_detail_summary_chars", 240))
    return LEGACY_MIN_SUMMARY_LEAD_CHARS


def detail_information_required(issue_dt) -> bool:
    return effective_on_or_after(COVERAGE_CONTRACT, "detail_information_contract_effective_date", issue_dt)


def validate_stable_hero(context: str, html: str, issue_date: str) -> None:
    hero_match = re.search(r'<section class="hero">(.*?)</section>', html, flags=re.S)
    if not hero_match:
        fail(f"{context} missing hero section")
    hero = hero_match.group(1)
    h1_match = re.search(r"<h1>(.*?)</h1>", hero, flags=re.S)
    if not h1_match:
        fail(f"{context} missing hero h1")
    hero_title = visible_text(h1_match.group(1))
    if hero_title != EXPECTED_HERO_TITLE:
        fail(f"{context} hero h1 must be stable concept title '{EXPECTED_HERO_TITLE}', not daily news: {hero_title}")
    hero_text = visible_text(hero)
    concept_terms = (
        EXPECTED_HERO_CONCEPT_TERMS
        if issue_date >= HERO_COPY_EFFECTIVE_DATE
        else LEGACY_HERO_CONCEPT_TERMS
    )
    missing = [term for term in concept_terms if term not in hero_text]
    if missing:
        fail(f"{context} hero concept copy missing terms: " + ", ".join(missing))
    daily_terms = [term for term in HERO_DAILY_TOPIC_TERMS if term in hero_text]
    if daily_terms:
        fail(f"{context} hero must describe the product concept, not daily topics: " + ", ".join(daily_terms[:8]))


def validate_priority_has_no_selection_process(context: str, html: str, issue_date: str) -> None:
    if issue_date < PUBLIC_SELECTION_RATIONALE_BAN_EFFECTIVE_DATE:
        return
    match = re.search(
        r'<section class="section" id="priority">(.*?)(?=<section class="section" id=|\Z)',
        section_before_history(html),
        flags=re.S,
    )
    if not match:
        fail(f"{context} missing priority section")
    priority_text = visible_text(match.group(1))
    if "選定理由" in priority_text or "priority-rationale" in match.group(1):
        fail(f"{context} priority section exposes selection rationale")


def validate_daily_delta(issue_date: str, sample_html: str) -> None:
    previous_path = previous_issue_sample(issue_date)
    if not previous_path:
        return
    previous_html = read(previous_path)
    current_cards = [card_signature(card) for card in current_card_blocks(sample_html)]
    previous_cards = set(card_signature(card) for card in current_card_blocks(previous_html))
    if not current_cards or not previous_cards:
        return
    unchanged = sum(1 for signature in current_cards if signature in previous_cards)
    changed = len(current_cards) - unchanged
    unchanged_ratio = unchanged / len(current_cards)
    required_changed = min(MIN_CHANGED_CARDS_VS_PREVIOUS, len(current_cards))
    if changed < required_changed or unchanged_ratio > MAX_UNCHANGED_CARD_RATIO_VS_PREVIOUS:
        fail(
            "issue appears copied from previous day: "
            f"changed cards {changed}/{len(current_cards)}, unchanged ratio {unchanged_ratio:.0%} "
            f"against {previous_path.name}"
        )

    current_body = normalize_for_similarity(without_retained_cards(section_before_history(sample_html)))
    previous_body = normalize_for_similarity(without_retained_cards(section_before_history(previous_html)))
    similarity = difflib.SequenceMatcher(None, current_body, previous_body).ratio()
    if similarity > MAX_ISSUE_SIMILARITY_VS_PREVIOUS:
        fail(f"issue body too similar to previous day ({similarity:.1%}) against {previous_path.name}")


def validate_detail_daily_delta(issue_date: str, root_html: str, dated_html: str) -> None:
    previous_date = previous_issue_date(issue_date)
    if not previous_date:
        return
    linked = set(re.findall(rf'href="{issue_date}/details/([^"#?]+\.html)', root_html))
    linked.update(re.findall(r'href="details/([^"#?]+\.html)', dated_html))
    excluded = {"policy.html", f"extraction-log-{issue_date}.html"}
    copied = []
    for name in sorted(linked - excluded):
        previous_name = name.replace(issue_date, previous_date)
        if previous_name == name:
            continue
        current_path = SITE_ROOT / issue_date / "details" / name
        previous_path = SITE_ROOT / previous_date / "details" / previous_name
        if not previous_path.exists():
            previous_path = ROOT / "details" / previous_name
        if not previous_path.exists():
            continue
        current_text = normalize_for_similarity(read(current_path))
        previous_text = normalize_for_similarity(read(previous_path))
        similarity = difflib.SequenceMatcher(None, current_text, previous_text).ratio()
        if similarity > MAX_DETAIL_SIMILARITY_VS_PREVIOUS:
            copied.append(f"{name} vs {previous_name}: {similarity:.1%}")
    if copied:
        fail("detail page appears copied from previous day: " + "; ".join(copied[:8]))


def validate_reader_facing_headlines(context: str, headings: list[str]) -> None:
    failures = []
    for heading in headings:
        if any(term in heading for term in HEADLINE_ABSTRACT_LEAK_TERMS + PUBLIC_ABSTRACT_FRAMING_TERMS):
            failures.append(f"{heading} [abstract phrase]")
            continue
        if any(char in heading for char in HEADLINE_FORBIDDEN_CHARS):
            failures.append(f"{heading} [quote/arrow shorthand]")
            continue
        if any(heading.startswith(prefix) for prefix in GENERIC_HEADLINE_STARTS):
            failures.append(f"{heading} [generic start]")
    if failures:
        fail(f"{context} headings are not reader-facing: " + "; ".join(failures[:8]))


def alignment_keywords(title: str) -> list[str]:
    return [keyword for keyword in DETAIL_ALIGNMENT_KEYWORDS if keyword in title]


def validate_card_detail_alignment(issue_date: str, root_html: str, dated_html: str) -> None:
    cards = card_blocks(root_html) + card_blocks(dated_html)
    by_detail: dict[tuple[str, str], set[str]] = {}
    for card in cards:
        target = card_detail_target(issue_date, card)
        if not target:
            continue
        by_detail.setdefault(target, set()).add(card_title(card))

    failures = []
    for (detail_issue_date, name), titles in sorted(by_detail.items()):
        if name in {"policy.html", f"extraction-log-{issue_date}.html"}:
            continue
        path = SITE_ROOT / detail_issue_date / "details" / name
        html = read(path)
        primary = " ".join(heading_texts(html, ("title", "h1")))
        body = " ".join(heading_texts(html, ("title", "h1", "h2")))
        summary_match = re.search(r'<div class="(?:summary-lead|article-summary)">(.*?)</div>', html, flags=re.S)
        if summary_match:
            body += " " + re.sub(r"<.*?>", "", summary_match.group(1))
        for title in sorted(titles):
            keywords = alignment_keywords(title)
            if not keywords:
                continue
            primary_hits = [keyword for keyword in keywords if keyword in primary]
            body_hits = [keyword for keyword in keywords if keyword in body]
            required_primary_hits = min(2, len(keywords))
            if len(primary_hits) < required_primary_hits or len(body_hits) < required_primary_hits:
                failures.append(
                    f"{title} -> {name} (primary hits: {primary_hits or '-'}, expected: {keywords})"
                )
    if failures:
        fail("card/detail title mismatch: " + "; ".join(failures[:8]))


def linked_detail_names(issue_date: str, root_html: str, dated_html: str) -> set[str]:
    linked = set(re.findall(rf'href="{issue_date}/details/([^"#?]+\.html)', root_html))
    linked.update(re.findall(r'href="details/([^"#?]+\.html)', dated_html))
    return linked


def validate_unique_detail_links(context: str, html: str) -> None:
    by_detail: dict[str, set[str]] = {}
    for card in normal_card_blocks(html):
        name = card_detail_href(card)
        if not name:
            continue
        by_detail.setdefault(name, set()).add(card_title(card))
    duplicates = [
        f"{name}: " + " / ".join(sorted(titles))
        for name, titles in sorted(by_detail.items())
        if len(titles) > 1
    ]
    if duplicates:
        fail(f"{context} duplicate detail links; split unrelated topics into separate detail pages: " + "; ".join(duplicates[:8]))


def validate_unique_display_clusters(context: str, html: str) -> None:
    seen: dict[str, str] = {}
    duplicates: list[str] = []
    for card in normal_card_blocks(html):
        key = card_cluster_key(card)
        title = card_title(card)
        if not key:
            continue
        duplicate_title = seen_card_cluster(seen, key)
        if duplicate_title:
            duplicates.append(f"{duplicate_title} / {title}")
        else:
            seen[key] = title
    if duplicates:
        fail(f"{context} duplicate displayed news clusters: " + "; ".join(duplicates[:8]))


def local_href_targets(html: str, base: Path) -> list[Path]:
    targets = []
    for href in re.findall(r'href="([^"]+)"', html):
        if href.startswith(("#", "http://", "https://", "mailto:", "tel:")):
            continue
        path = unquote(href.split("#", 1)[0].split("?", 1)[0])
        if not path:
            continue
        targets.append((base / path).resolve())
    return targets


def validate_local_links(issue_date: str) -> None:
    html_files = [SITE_ROOT / "index.html", SITE_ROOT / issue_date / "index.html"]
    html_files.extend(sorted((SITE_ROOT / issue_date / "details").glob("*.html")))
    missing = []
    for html_file in html_files:
        html = read(html_file)
        for target in local_href_targets(html, html_file.parent):
            try:
                target.relative_to(ROOT)
            except ValueError:
                continue
            if not target.exists():
                missing.append(f"{html_file.relative_to(ROOT)} -> {target.relative_to(ROOT)}")
    if missing:
        fail("broken local links: " + "; ".join(missing[:12]))


def validate_detail_scope(issue_date: str, root_html: str, dated_html: str) -> None:
    linked = linked_detail_names(issue_date, root_html, dated_html)
    linked.add("policy.html")
    linked.add(f"extraction-log-{issue_date}.html")
    actual = {path.name for path in (SITE_ROOT / issue_date / "details").glob("*.html")}
    extra = actual - linked
    missing = linked - actual
    if missing:
        fail("published issue missing linked detail pages: " + ", ".join(sorted(missing)))
    if extra:
        fail("published issue contains unlinked stale detail pages: " + ", ".join(sorted(extra)[:12]))


def validate_detail_quality(issue_date: str, root_html: str, dated_html: str) -> None:
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    filename_date_required = effective_on_or_after(COVERAGE_CONTRACT, "article_summary_effective_date", issue_dt)
    # Legacy details use one overview block. Current details use a compact,
    # reader-facing structure: summary, confirmed facts, limits, and sources.
    article_summary_required = filename_date_required
    information_required = detail_information_required(issue_dt)
    min_summary_chars = detail_min_summary_chars(issue_dt)
    linked = linked_detail_names(issue_date, root_html, dated_html)
    excluded = {"policy.html", f"extraction-log-{issue_date}.html"}
    if filename_date_required:
        wrong_issue_details = [
            name for name in sorted(linked - excluded) if not name.endswith(f"-{issue_date}.html")
        ]
        if wrong_issue_details:
            fail(
                "current issue detail filenames must include issue date: "
                + ", ".join(wrong_issue_details[:8])
            )
    weak = []
    leaked = []
    checklist_headings = []
    article_structure_failures = []
    weak_summaries = []
    missing_source = []
    too_many_sources = []
    missing_back = []
    for name in sorted(linked - excluded):
        path = SITE_ROOT / issue_date / "details" / name
        html = read(path)
        plain = re.sub(r"<[^>]+>", "", html)
        plain = re.sub(r"\s+", "", plain)
        if not information_required and len(plain) < MIN_DETAIL_TEXT_CHARS:
            weak.append(f"{name}: {len(plain)} chars")
        headings = " ".join(re.findall(r"<(?:title|h1|h2)[^>]*>(.*?)</(?:title|h1|h2)>", html, flags=re.S))
        heading_text = re.sub(r"<[^>]+>", "", headings)
        if any(term in heading_text for term in DETAIL_POLICY_LEAK_TERMS):
            leaked.append(name)
        h2_texts = heading_texts(html, ("h2",))
        if any(any(term in heading for term in DETAIL_FORBIDDEN_SECTION_HEADINGS) for heading in h2_texts):
            checklist_headings.append(name)
        if information_required:
            required_h2 = [detail_summary_heading(issue_dt), "確認した事実", "未確定点"]
        else:
            required_h2 = [detail_summary_heading(issue_dt)]
        if h2_texts != required_h2:
            article_structure_failures.append(f"{name}: h2={h2_texts or '-'}")
        summary_class = "article-summary" if article_summary_required else "summary-lead"
        summary_match = re.search(rf'<div class="{summary_class}">(.*?)</div>', html, flags=re.S)
        if not summary_match:
            weak_summaries.append(f"{name}: missing summary")
        else:
            summary_text = visible_text(summary_match.group(1))
            validate_public_summary_language(f"detail page {name} summary", summary_text, issue_date)
            summary_text = re.sub(r"\s+", "", summary_text)
            if not information_required and len(summary_text) < min_summary_chars:
                weak_summaries.append(f"{name}: {len(summary_text)} chars")
        if information_required:
            fact_match = re.search(r'<ul class="fact-list">(.*?)</ul>', html, flags=re.S)
            if not fact_match:
                article_structure_failures.append(f"{name}: missing confirmed facts")
            else:
                facts = [visible_text(item) for item in re.findall(r"<li[^>]*>(.*?)</li>", fact_match.group(1), flags=re.S)]
                min_facts = int(COVERAGE_CONTRACT.get("minimum_material_facts_per_published_item", 2))
                if len([fact for fact in facts if fact]) < min_facts:
                    article_structure_failures.append(f"{name}: not enough confirmed facts")
                for fact in facts:
                    validate_public_summary_language(f"detail page {name} fact", fact, issue_date)
            limits_match = re.search(r'<p class="limits">(.*?)</p>', html, flags=re.S)
            if not limits_match or not visible_text(limits_match.group(1)):
                article_structure_failures.append(f"{name}: missing limits/unknowns")
            elif "確認して" in visible_text(limits_match.group(1)):
                article_structure_failures.append(f"{name}: limits read like an instruction")
        source_match = re.search(r'<div class="source">(.*?)</div>', html, flags=re.S)
        if summary_match and source_match:
            between = html[summary_match.end() : source_match.start()]
            if not information_required and visible_text(between):
                article_structure_failures.append(f"{name}: body exists outside article summary")
            source_links = re.findall(r"<a\b", source_match.group(1), flags=re.I)
            if not article_summary_required and len(source_links) > MAX_SOURCE_LINKS_PER_DETAIL:
                too_many_sources.append(f"{name}: {len(source_links)} links")
        validate_reader_facing_headlines(
            f"detail page {name}",
            heading_texts(html, ("title", "h1")),
        )
        validate_reader_process_language(f"detail page {name}", html)
        if 'class="source"' not in html or "原文確認" not in html:
            missing_source.append(name)
        if 'class="back"' not in html or "../index.html" not in html:
            missing_back.append(name)
    if weak:
        fail("detail pages too thin: " + "; ".join(weak[:8]))
    if leaked:
        fail("detail headings contain policy/checklist wording: " + ", ".join(leaked[:8]))
    if checklist_headings:
        fail("detail pages use checklist/next-step section headings: " + ", ".join(checklist_headings[:8]))
    if article_structure_failures:
        expected_structure = "information-complete detail"
        fail(f"detail pages must use {expected_structure} structure: " + "; ".join(article_structure_failures[:8]))
    if weak_summaries:
        if information_required:
            fail("detail summaries are incomplete: " + "; ".join(weak_summaries[:8]))
        fail("detail summaries are too thin: " + "; ".join(weak_summaries[:8]))
    if missing_source:
        fail("detail pages missing source block: " + ", ".join(missing_source[:8]))
    if too_many_sources:
        fail("legacy detail pages have too many source links: " + "; ".join(too_many_sources[:8]))
    if missing_back:
        fail("detail pages missing back link: " + ", ".join(missing_back[:8]))


def validate_category_sections(root_html: str) -> None:
    body = section_before_history(root_html)
    missing = []
    too_thin = []
    for section_id, label in REQUIRED_SECTIONS.items():
        match = re.search(
            rf'<section class="section" id="{section_id}">(.*?)(?=<section class="section" id=|\Z)',
            body,
            flags=re.S,
        )
        if not match:
            missing.append(label)
            continue
        count = len(re.findall(r'<article class="card[^"]*">', match.group(1)))
        if count < MIN_CARDS_PER_SECTION:
            too_thin.append(f"{label}: {count}")
    if missing:
        fail("missing category sections: " + ", ".join(missing))
    if too_thin:
        fail("category sections below minimum cards: " + ", ".join(too_thin))


def validate_extraction_log(issue_date: str, extraction_log_html: str) -> None:
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    expected_japanese_date = f"{issue_dt.year}年{issue_dt.month}月{issue_dt.day}日版"
    if expected_japanese_date not in extraction_log_html:
        fail(f"extraction log heading does not show {expected_japanese_date}")

    missing_categories = [term for term in REQUIRED_CATEGORIES if term not in extraction_log_html]
    if missing_categories:
        fail("extraction log missing categories: " + ", ".join(missing_categories))

    missing_terms = [term for term in REQUIRED_COVERAGE_TERMS if term not in extraction_log_html]
    if missing_terms:
        fail("extraction log missing coverage terms: " + ", ".join(missing_terms))

    if "採用" not in extraction_log_html:
        fail("extraction log does not record adopted items")

    if "未確認" not in extraction_log_html and "重大リスク" not in extraction_log_html:
        fail("extraction log does not classify unresolved risk")

    manifest_match = re.search(
        r'<script type="application/json" id="coverage-manifest">(.*?)</script>',
        extraction_log_html,
        flags=re.S,
    )
    if not manifest_match:
        fail("extraction log missing coverage-manifest JSON")
    try:
        manifest = json.loads(manifest_match.group(1))
    except json.JSONDecodeError as exc:
        fail(f"coverage-manifest JSON is invalid: {exc}")

    if manifest.get("date") != issue_date:
        fail(f"coverage-manifest date mismatch: {manifest.get('date')} != {issue_date}")

    categories = manifest.get("categories")
    if not isinstance(categories, dict):
        fail("coverage-manifest missing categories object")

    for category in REQUIRED_CATEGORIES:
        entry = categories.get(category)
        if not isinstance(entry, dict):
            fail(f"coverage-manifest missing category entry: {category}")
        optional_source_classes = set(CATEGORY_CONFIG_BY_LABEL[category].get("optional_source_classes", []))
        for source_class in REQUIRED_SOURCE_CLASSES:
            value = entry.get(source_class)
            if source_class in optional_source_classes and (not isinstance(value, list) or not value):
                continue
            if not isinstance(value, list) or not value:
                fail(f"{category} missing source evidence: {source_class}")
            if any(not isinstance(item, str) or len(item.strip()) < 4 for item in value):
                fail(f"{category} has weak source evidence: {source_class}")
        for decision_class in REQUIRED_DECISION_CLASSES:
            value = entry.get(decision_class)
            if not isinstance(value, list):
                fail(f"{category} missing decision list: {decision_class}")
        search_terms = entry.get("search_terms")
        if not isinstance(search_terms, list) or not search_terms:
            fail(f"{category} missing search_terms")
        if not entry.get("freshness_check"):
            fail(f"{category} missing freshness_check")
        if entry.get("critical_unresolved"):
            fail(f"{category} has critical unresolved risks: {entry['critical_unresolved']}")


def validate(issue_date: str) -> None:
    issue_dt = datetime.strptime(issue_date, "%Y-%m-%d").date()
    sample = ROOT / f"night-brief-web-sample-{issue_date}.html"
    dated_index = SITE_ROOT / issue_date / "index.html"
    root_index = SITE_ROOT / "index.html"
    extraction_log = ROOT / "details" / f"extraction-log-{issue_date}.html"

    sample_html = read(sample)
    root_html = read(root_index)
    dated_html = read(dated_index)
    extraction_log_html = read(extraction_log)
    validate_extraction_log(issue_date, extraction_log_html)
    validate_daily_delta(issue_date, sample_html)

    expected_title = f"NIGHT SIGNAL | {issue_date}"
    if expected_title not in sample_html or expected_title not in root_html or expected_title not in dated_html:
        fail(f"issue title/date mismatch; expected {expected_title}")

    display_date = issue_date.replace("-", ".")
    if display_date not in root_html:
        fail(f"root page does not display {display_date}")

    validate_stable_hero("sample page", sample_html, issue_date)
    validate_stable_hero("root page", root_html, issue_date)
    validate_stable_hero("dated issue page", dated_html, issue_date)
    validate_priority_has_no_selection_process("root page", root_html, issue_date)
    validate_priority_has_no_selection_process("dated issue page", dated_html, issue_date)
    validate_reader_process_language("root page", section_before_history(root_html))
    validate_reader_process_language("dated issue page", section_before_history(dated_html))
    validate_no_confirmation_layer("root page", root_html)
    validate_no_confirmation_layer("dated issue page", dated_html)
    for context, html in [("root page", root_html), ("dated issue page", dated_html)]:
        for card in card_blocks(html):
            for paragraph in re.findall(r"<p[^>]*>(.*?)</p>", card, flags=re.S):
                validate_public_summary_language(f"{context} card summary", visible_text(paragraph), issue_date)

    cards = card_blocks(root_html)
    leaked_titles = [
        title
        for title in page_titles(root_html)
        if any(term in title for term in TITLE_POLICY_LEAK_TERMS)
    ]
    if leaked_titles:
        fail("card titles contain policy/checklist wording: " + "; ".join(leaked_titles[:8]))

    validate_reader_facing_headlines(
        "root page",
        heading_texts(section_before_history(root_html), ("h1", "h3")),
    )

    stale: list[str] = []
    label_failures: list[str] = []
    fresh_count = 0
    undated: list[str] = []
    max_card_age_days = max_adopted_source_age_days(COVERAGE_CONTRACT, issue_dt)
    freshness_label_required = effective_on_or_after(
        COVERAGE_CONTRACT, "latest_three_calendar_days_effective_date", issue_dt
    )
    for card in cards:
        dates = card_dates(card)
        if not dates:
            # Priority cards may omit explicit dates; ignore those.
            if "priority-card" not in card:
                undated.append(card_title(card))
            continue
        newest = max(datetime.strptime(d, "%Y-%m-%d").date() for d in dates)
        age = (issue_dt - newest).days
        if age < 0:
            # Future scheduled events are allowed only when clearly marked as a plan.
            if "予定" not in card and "次回" not in card and "発表" not in card:
                stale.append(f"future date without schedule context: {card_title(card)} ({newest})")
            continue
        if age > max_card_age_days:
            stale.append(f"{card_title(card)} ({newest}, {age} days old)")
        if freshness_label_required and 0 <= age <= 2 and LATEST_THREE_DAY_LABELS[age] not in visible_text(card):
            label_failures.append(f"{card_title(card)} needs {LATEST_THREE_DAY_LABELS[age]} label")
        if age <= 1:
            fresh_count += 1

    if undated:
        fail("undated cards found: " + "; ".join(undated[:5]))
    if stale:
        fail("stale cards found: " + "; ".join(stale[:8]))
    if label_failures:
        fail("cards missing 今日/昨日/一昨日 freshness labels: " + "; ".join(label_failures[:8]))
    if effective_on_or_after(COVERAGE_CONTRACT, "rolling_display_cards_effective_date", issue_dt):
        display_cards = normal_card_blocks(root_html)
        expected_dates = {
            issue_dt.fromordinal(issue_dt.toordinal() - offset).isoformat()
            for offset in range(3)
        }
        visible_dates = {
            date
            for card in display_cards
            for date in card_dates(card)
            if date in expected_dates
        }
        missing_dates = sorted(expected_dates - visible_dates)
        if missing_dates:
            fail("rolling three-day display missing dates: " + ", ".join(missing_dates))

    validate_category_sections(root_html)
    validate_unique_detail_links("root page", root_html)
    validate_unique_detail_links("dated issue page", dated_html)
    validate_unique_display_clusters("root page", root_html)
    validate_unique_display_clusters("dated issue page", dated_html)
    validate_coverage_contract(issue_date, root_html, extraction_log_html)
    validate_detail_quality(issue_date, root_html, dated_html)
    validate_card_detail_alignment(issue_date, root_html, dated_html)
    validate_detail_daily_delta(issue_date, root_html, dated_html)

    required_links = [
        f"{issue_date}/details/extraction-log-{issue_date}.html",
        f"{issue_date}/details/policy.html",
    ]
    for link in required_links:
        if link not in root_html:
            fail(f"missing required root link: {link}")

    validate_detail_scope(issue_date, root_html, dated_html)
    validate_local_links(issue_date)

    print(f"QUALITY GATE PASSED: {issue_date}, cards={len(cards)}, fresh={fresh_count}")


if __name__ == "__main__":
    validate(issue_date_from_args())
