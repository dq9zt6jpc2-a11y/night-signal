#!/usr/bin/env python3
"""Run failure-mode simulations for NIGHT SIGNAL quality gates.

The goal is not to test Python internals. It is to prove that common real
operational mistakes fail before publication.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ISSUE_DATE = "2026-05-21"
SOFTBANK_CARD_TITLE = "<h3>SoftBank、堺AIデータセンター電池計画を決算資料で再提示"
SOFTBANK_DETAIL = "softbank-battery-2026-05-21.html"
BREX_DETAIL = "brex-newbill-2026-05-21.html"
OPENAI_PRIMARY_DETAIL = "openai-dell-codex-2026-05-21.html"
OPENAI_SECONDARY_DETAIL = "openai-codex-mobile-2026-05-21.html"


def copy_fixture() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="night-signal-gate-"))
    (tmp / "scripts").mkdir()
    (tmp / "details").mkdir()
    (tmp / "config").mkdir()
    shutil.copyfile(ROOT / "scripts" / "quality_gate.py", tmp / "scripts" / "quality_gate.py")
    shutil.copyfile(ROOT / "scripts" / "coverage_audit.py", tmp / "scripts" / "coverage_audit.py")
    shutil.copyfile(ROOT / "config" / "night_signal_coverage.json", tmp / "config" / "night_signal_coverage.json")
    shutil.copyfile(ROOT / f"night-brief-web-sample-{ISSUE_DATE}.html", tmp / f"night-brief-web-sample-{ISSUE_DATE}.html")
    shutil.copyfile(ROOT / "night-brief-web-sample-2026-05-18.html", tmp / "night-brief-web-sample-2026-05-18.html")
    shutil.copyfile(ROOT / "details" / f"extraction-log-{ISSUE_DATE}.html", tmp / "details" / f"extraction-log-{ISSUE_DATE}.html")
    shutil.copytree(ROOT / "site", tmp / "site")
    return tmp


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def write(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8")


def run_gate(tmp: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(tmp / "scripts" / "quality_gate.py"), ISSUE_DATE],
        cwd=tmp,
        text=True,
        capture_output=True,
    )


def assert_pass(name: str, tmp: Path) -> None:
    result = run_gate(tmp)
    if result.returncode != 0:
        raise AssertionError(f"{name}: expected pass, got fail\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


def assert_fail(name: str, mutate, expected: str) -> None:
    tmp = copy_fixture()
    mutate(tmp)
    result = run_gate(tmp)
    output = result.stdout + result.stderr
    if result.returncode == 0:
        raise AssertionError(f"{name}: expected failure but passed")
    if expected not in output:
        raise AssertionError(f"{name}: expected '{expected}' in output\n{output}")
    print(f"PASS expected failure: {name}")


def mutate_root_and_dated(tmp: Path, transform) -> None:
    for path in [tmp / "site" / "index.html", tmp / "site" / ISSUE_DATE / "index.html"]:
        write(path, transform(read(path)))


def remove_investment_section_once(html: str) -> str:
    return re.sub(
        r'\n    <section class="section" id="investment">.*?(?=\n    <section class="section" id="history">|\n  </main>)',
        "",
        html,
        count=1,
        flags=re.S,
    )


def remove_one_investment_card(html: str) -> str:
    pattern = r'(<section class="section" id="investment">.*?<article class="card[^"]*">.*?</article>)(.*?</section>)'
    return re.sub(pattern, r"\1</div>\n    </section>", html, count=1, flags=re.S)


def mutate_manifest(tmp: Path, category: str, key: str, value) -> None:
    path = tmp / "details" / f"extraction-log-{ISSUE_DATE}.html"
    html = read(path)
    match = re.search(r'(<script type="application/json" id="coverage-manifest">)(.*?)(</script>)', html, flags=re.S)
    if not match:
        raise AssertionError("fixture missing coverage manifest")
    manifest = json.loads(match.group(2))
    manifest["categories"][category][key] = value
    write(path, html[: match.start(2)] + json.dumps(manifest, ensure_ascii=False, indent=2) + html[match.end(2) :])


def mirror_current_detail_to_previous(tmp: Path, name: str) -> None:
    previous_name = name.replace(ISSUE_DATE, "2026-05-18")
    current = read(tmp / "site" / ISSUE_DATE / "details" / name)
    previous = current.replace(ISSUE_DATE, "2026-05-18")
    write(tmp / "site" / "2026-05-18" / "details" / previous_name, previous)


def clear_each_source_class_simulations() -> None:
    categories = ["OpenAI", "SoftBank", "Honda", "F1", "SpaceX", "アジア経済", "宇都宮ブレックス", "投資"]
    source_classes = [
        "official",
        "major_media",
        "specialist_media",
        "sns_x",
        "youtube_video",
        "data_numeric",
        "schedule_calendar",
        "counter_search",
    ]
    for category in categories:
        for source_class in source_classes:
            assert_fail(
                f"{category} missing {source_class}",
                lambda tmp, c=category, s=source_class: mutate_manifest(tmp, c, s, []),
                f"{category} missing source evidence: {source_class}",
            )


def clear_search_terms_simulations() -> None:
    categories = ["OpenAI", "SoftBank", "Honda", "F1", "SpaceX", "アジア経済", "宇都宮ブレックス", "投資"]
    for category in categories:
        assert_fail(
            f"{category} missing search_terms",
            lambda tmp, c=category: mutate_manifest(tmp, c, "search_terms", []),
            f"{category} missing search_terms",
        )


def main() -> int:
    baseline = copy_fixture()
    assert_pass("baseline current issue", baseline)
    print("PASS baseline current issue")

    assert_fail(
        "title policy wording leak",
        lambda tmp: mutate_root_and_dated(
            tmp,
            lambda html: html.replace(SOFTBANK_CARD_TITLE, "<h3>一次で固定 SoftBank（9434）", 1),
        ),
        "card titles contain policy/checklist wording",
    )

    assert_fail(
        "abstract headline wording leak",
        lambda tmp: mutate_root_and_dated(
            tmp,
            lambda html: html.replace(SOFTBANK_CARD_TITLE, "<h3>投資枠とインフラを同じ地図で読む SoftBank（9434）", 1),
        ),
        "headings are not reader-facing",
    )

    assert_fail(
        "headline arrow shorthand leak",
        lambda tmp: mutate_root_and_dated(
            tmp,
            lambda html: html.replace(SOFTBANK_CARD_TITLE, "<h3>SoftBank（9434）: 投資枠→AI-RAN→堺DC", 1),
        ),
        "headings are not reader-facing",
    )

    assert_fail(
        "detail headline quote shorthand leak",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL,
            read(tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL).replace("<h1>", "<h1>“投資枠”と“CPUの現場” ", 1),
        ),
        "headings are not reader-facing",
    )

    assert_fail(
        "card detail title mismatch",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL,
            read(tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL).replace(
                "SoftBank、堺AIデータセンター電池計画を決算資料で再提示",
                "宇都宮ブレックス、スタッフ体制を再編",
            ),
        ),
        "card/detail title mismatch",
    )

    assert_fail(
        "detail checklist section heading leak",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / BREX_DETAIL,
            re.sub(
                r'(</div>)(\s*<div class="source">)',
                '\\1<h2>チェック観点</h2><p>補足情報を概要の外に混ぜる。</p>\\2',
                read(tmp / "site" / ISSUE_DATE / "details" / BREX_DETAIL),
                count=1,
                flags=re.S,
            ),
        ),
        "detail pages use checklist/next-step section headings",
    )

    assert_fail(
        "detail body exists after summary",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / BREX_DETAIL,
            re.sub(
                r'(</div>)(\s*<div class="source">)',
                '\\1<p>概要とは別に本文を追加し、別論点まで説明する。</p>\\2',
                read(tmp / "site" / ISSUE_DATE / "details" / BREX_DETAIL),
                count=1,
                flags=re.S,
            ),
        ),
        "detail pages must be overview-only",
    )

    assert_fail(
        "detail source list too broad",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL,
            read(tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL).replace(
                "</div>\n      <div class=\"return-row\">",
                '<a href="https://example.com/extra-1">extra 1</a><a href="https://example.com/extra-2">extra 2</a></div>\\n      <div class="return-row">',
                1,
            ),
        ),
        "detail pages have too many source links",
    )

    assert_fail(
        "duplicate card detail link",
        lambda tmp: mutate_root_and_dated(
            tmp,
            lambda html: html.replace(f"details/{OPENAI_SECONDARY_DETAIL}", f"details/{OPENAI_PRIMARY_DETAIL}", 1),
        ),
        "duplicate detail links",
    )

    assert_fail(
        "detail summary too thin",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / BREX_DETAIL,
            re.sub(
                r'<div class="summary-lead">.*?</div>',
                '<div class="summary-lead">D.J.ニュービルは契約満了で宇都宮ブレックスを退団した。攻撃の中心だった主力の退団で、来季ロスターは大きく変わる。得点、アシスト、外国籍枠、後任ガードの補強がチーム力を左右する。クラブは指導体制の再編も抱え、主力の穴を埋める編成判断が急務になる。主力の役割配分も見直しになる。</div>',
                read(tmp / "site" / ISSUE_DATE / "details" / BREX_DETAIL),
                count=1,
                flags=re.S,
            ),
        ),
        "detail summaries are too thin",
    )

    assert_fail(
        "missing category section",
        lambda tmp: mutate_root_and_dated(tmp, remove_investment_section_once),
        "missing category sections",
    )

    assert_fail(
        "category has only one card",
        lambda tmp: mutate_root_and_dated(tmp, remove_one_investment_card),
        "category sections below minimum cards",
    )

    assert_fail(
        "stale visible card date",
        lambda tmp: mutate_root_and_dated(tmp, lambda html: html.replace(f">{ISSUE_DATE}<", ">2026-05-10<", 1)),
        "stale cards found",
    )

    assert_fail(
        "broken local detail link",
        lambda tmp: mutate_root_and_dated(tmp, lambda html: html.replace(f"details/{SOFTBANK_DETAIL}", "details/missing.html", 1)),
        f"missing file: site/{ISSUE_DATE}/details/missing.html",
    )

    assert_fail(
        "unlinked stale detail page copied into issue",
        lambda tmp: write(tmp / "site" / ISSUE_DATE / "details" / "stale-extra.html", "<html><body>old</body></html>"),
        "published issue contains unlinked stale detail pages",
    )

    assert_fail(
        "linked detail copied from previous day",
        lambda tmp: mirror_current_detail_to_previous(tmp, SOFTBANK_DETAIL),
        "detail page appears copied from previous day",
    )

    assert_fail(
        "coverage manifest source evidence missing",
        lambda tmp: mutate_manifest(tmp, "OpenAI", "official", []),
        "OpenAI missing source evidence: official",
    )

    assert_fail(
        "detail page too thin",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL,
            '<html><head><title>SoftBank</title></head><body><main><a class="back" href="../index.html#softbank">一覧へ戻る</a><article><h1>SoftBank、堺AIデータセンター電池計画を決算資料で再提示</h1><h2>30秒概要</h2><div class="summary-lead">SoftBankは堺AIデータセンター向けに電池計画を進める。</div><div class="source">原文確認:<a href="https://www.softbank.jp/corp/news/press/sbkk/2026/20260511_01/">SoftBank</a></div></article></main></body></html>',
        ),
        "detail pages too thin",
    )

    assert_fail(
        "detail heading policy wording leak",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL,
            read(tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL).replace("<h1>", "<h1>一次で固定 ", 1),
        ),
        "detail headings contain policy/checklist wording",
    )

    assert_fail(
        "coverage card titles mismatch",
        lambda tmp: mutate_manifest(tmp, "OpenAI", "published_card_titles", ["old copied title"]),
        "OpenAI published_card_titles do not match page cards",
    )

    assert_fail(
        "coverage new or changed items missing",
        lambda tmp: mutate_manifest(tmp, "OpenAI", "new_or_changed_items", []),
        "OpenAI needs at least",
    )

    assert_fail(
        "coverage new item source mismatch",
        lambda tmp: mutate_manifest(
            tmp,
            "OpenAI",
            "new_or_changed_items",
            [
                {
                    "title": "OpenAIとDell、Codexを企業のオンプレ環境へ展開",
                    "summary": "OpenAIとDell Technologiesの提携は、Codexを企業のデータ基盤に近い場所へ置く選択肢を広げる。オンプレミスやハイブリッド環境では、既存の統制、監査、データ境界が導入判断になる。",
                    "sources": ["https://example.com/not-the-detail-source"],
                },
                {
                    "title": "Codex、ChatGPTモバイルから長時間タスクを操作可能に",
                    "summary": "OpenAIのリリースノートでは、CodexがChatGPTモバイルアプリから利用できるようになった。長時間タスクの出力確認、承認、接続先ホストの切り替えを外出先から扱える。",
                    "sources": ["https://help.openai.com/en/articles/10128477-chatgpt-enterprise-edu-release-notes"],
                },
            ],
        ),
        "sources must overlap linked detail page sources",
    )

    assert_fail(
        "coverage new item Japanese summary missing",
        lambda tmp: mutate_manifest(
            tmp,
            "OpenAI",
            "new_or_changed_items",
            [
                {
                    "title": "OpenAIとDell、Codexを企業のオンプレ環境へ展開",
                    "summary": "OpenAI and Dell announced an enterprise Codex deployment partnership for hybrid and on-premises environments.",
                    "sources": ["https://openai.com/index/dell-codex-enterprise-partnership/"],
                },
                {
                    "title": "Codex、ChatGPTモバイルから長時間タスクを操作可能に",
                    "summary": "OpenAIのリリースノートでは、CodexがChatGPTモバイルアプリから利用できるようになった。長時間タスクの出力確認、承認、接続先ホストの切り替えを外出先から扱える。",
                    "sources": ["https://help.openai.com/en/articles/10128477-chatgpt-enterprise-edu-release-notes"],
                },
            ],
        ),
        "summary must be Japanese",
    )

    assert_fail(
        "coverage no-change checks missing",
        lambda tmp: mutate_manifest(tmp, "OpenAI", "no_change_checks", []),
        "OpenAI needs at least",
    )

    assert_fail(
        "coverage no-change YouTube evidence missing",
        lambda tmp: mutate_manifest(
            tmp,
            "OpenAI",
            "no_change_checks",
            [
                {
                    "axis": "release notes / SNS",
                    "result": "ChatGPT release notesとOpenAI公式SNSを確認し、5月21日版ではYouTubeを欠いた証跡として扱う。",
                    "sources": ["https://help.openai.com/en/articles/6825453-chatgpt-release-notes", "https://x.com/OpenAI"],
                }
            ],
        ),
        "must include YouTube URL evidence",
    )

    assert_fail(
        "coverage search axes missing",
        lambda tmp: mutate_manifest(tmp, "OpenAI", "search_axes", {}),
        "OpenAI search_axis official_product_release",
    )

    assert_fail(
        "coverage official URL missing",
        lambda tmp: mutate_manifest(tmp, "OpenAI", "official", ["OpenAI blog checked without URL"]),
        "OpenAI official must include URL evidence",
    )

    assert_fail(
        "coverage collection status incomplete",
        lambda tmp: mutate_manifest(tmp, "OpenAI", "collection_status", "partial"),
        "OpenAI collection_status must be complete",
    )

    assert_fail(
        "category-specific search axis missing",
        lambda tmp: mutate_manifest(
            tmp,
            "アジア経済",
            "search_axes",
            {
                "india_macro": ["India CPI April 2026 MoSPI RBI", "インド CPI 2026年4月 RBI MOSPI"],
                "vietnam_macro": ["India central bank policy May 2026", "South Asia reserves policy May 2026"],
                "regional_markets_policy": ["ASEAN manufacturing PMI policy FX May 2026", "India Vietnam currency policy manufacturing supply chain May 2026"],
            },
        ),
        "アジア経済 search_axis vietnam_macro missing expected terms",
    )

    assert_fail(
        "critical unresolved risk blocks publication",
        lambda tmp: mutate_manifest(tmp, "OpenAI", "critical_unresolved", ["official announcement not checked"]),
        "OpenAI has critical unresolved risks",
    )

    clear_each_source_class_simulations()
    clear_search_terms_simulations()

    print("ALL QUALITY GATE SIMULATIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
