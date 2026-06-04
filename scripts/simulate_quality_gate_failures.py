#!/usr/bin/env python3
"""Run failure-mode simulations for NIGHT SIGNAL quality gates.

The goal is not to test Python internals. It is to prove that common real
operational mistakes fail before publication.
"""

from __future__ import annotations

import json
import html as html_lib
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
ISSUE_DATE = "2026-05-24"
SOFTBANK_CARD_TITLE = "<h3>SoftBank株はOpenAI IPO観測で買われたが、NAVの中身と負債管理が再び論点に戻る"
SOFTBANK_DETAIL = "softbank-nav-debt-ipo-premium-2026-05-24.html"
BREX_DETAIL = "brex-newbill-transfer-altiri-chiba-2026-05-24.html"
OPENAI_PRIMARY_DETAIL = "openai-codex-approval-remote-2026-05-24.html"
OPENAI_SECONDARY_DETAIL = "openai-pac-federal-framework-2026-05-24.html"
INVESTMENT_SECOND_TITLE = "米株ファンドは利回り上昇で資金流出、AI物色は続いてもポジションは軽くなる"
INVESTMENT_SECOND_DETAIL = "north-america-us-equity-fund-outflows-2026-05-24.html"
NEXT_ISSUE_DATE = "2026-05-26"


def copy_fixture() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="night-signal-gate-"))
    (tmp / "scripts").mkdir()
    (tmp / "details").mkdir()
    (tmp / "config").mkdir()
    shutil.copyfile(ROOT / "scripts" / "quality_gate.py", tmp / "scripts" / "quality_gate.py")
    shutil.copyfile(ROOT / "scripts" / "coverage_audit.py", tmp / "scripts" / "coverage_audit.py")
    shutil.copyfile(ROOT / "scripts" / "guardrail_inventory.py", tmp / "scripts" / "guardrail_inventory.py")
    shutil.copyfile(ROOT / "scripts" / "publication_audit.py", tmp / "scripts" / "publication_audit.py")
    shutil.copyfile(ROOT / "scripts" / "current_issue_audit.py", tmp / "scripts" / "current_issue_audit.py")
    shutil.copyfile(ROOT / "scripts" / "sync_site.py", tmp / "scripts" / "sync_site.py")
    shutil.copyfile(ROOT / "scripts" / "render_detail.py", tmp / "scripts" / "render_detail.py")
    shutil.copyfile(ROOT / "scripts" / "night_signal_state.py", tmp / "scripts" / "night_signal_state.py")
    shutil.copyfile(ROOT / "scripts" / "simulate_quality_gate_failures.py", tmp / "scripts" / "simulate_quality_gate_failures.py")
    shutil.copyfile(ROOT / "config" / "night_signal_coverage.json", tmp / "config" / "night_signal_coverage.json")
    shutil.copyfile(ROOT / "config" / "night_signal_guardrails.json", tmp / "config" / "night_signal_guardrails.json")
    shutil.copyfile(ROOT / f"night-brief-web-sample-{ISSUE_DATE}.html", tmp / f"night-brief-web-sample-{ISSUE_DATE}.html")
    shutil.copyfile(ROOT / "night-brief-web-sample-2026-05-18.html", tmp / "night-brief-web-sample-2026-05-18.html")
    sample_html = (ROOT / f"night-brief-web-sample-{ISSUE_DATE}.html").read_text(encoding="utf-8")
    detail_names = {
        match.group(1)
        for match in re.finditer(r'href="details/([^"#?]+\.html)', sample_html)
    }
    detail_names.add(f"extraction-log-{ISSUE_DATE}.html")
    for name in sorted(detail_names):
        shutil.copyfile(ROOT / "details" / name, tmp / "details" / name)
    backfill_fixture_manifest_for_current_contract(tmp)
    shutil.copyfile(ROOT / "details" / "_style.css", tmp / "details" / "_style.css")
    shutil.copyfile(ROOT / "details" / "policy.html", tmp / "details" / "policy.html")
    shutil.copytree(ROOT / ".github", tmp / ".github")
    shutil.copytree(ROOT / "site", tmp / "site")
    subprocess.run(
        [sys.executable, str(tmp / "scripts" / "sync_site.py"), ISSUE_DATE],
        cwd=tmp,
        check=True,
        text=True,
        capture_output=True,
    )
    return tmp


def backfill_fixture_manifest_for_current_contract(tmp: Path) -> None:
    path = tmp / "details" / f"extraction-log-{ISSUE_DATE}.html"
    html = path.read_text(encoding="utf-8")
    match = re.search(r'(<script type="application/json" id="coverage-manifest">)(.*?)(</script>)', html, flags=re.S)
    if not match:
        return
    manifest = json.loads(match.group(2))
    asia = manifest.get("categories", {}).get("アジア経済")
    if not isinstance(asia, dict):
        return
    if any(candidate.get("topic_id") == "china_macro_policy" for candidate in asia.get("latest_candidates", [])):
        return
    title = "アジア経済 china_macro_policy: 近接候補を確認したが掲載優先度に届かず"
    asia.setdefault("search_axes", {})["china_macro_policy"] = [
        f"アジア経済 china_macro_policy china 中国 pmi nbs manufacturing Web SNS/X YouTube {ISSUE_DATE}",
        f"アジア経済 china 中国 pmi nbs manufacturing official latest update {ISSUE_DATE}",
    ]
    asia.setdefault("search_terms", []).extend(["china", "中国", "nbs", "pmi"])
    asia["search_terms"] = sorted(set(asia["search_terms"]))
    asia.setdefault("latest_candidates", []).append(
        {
            "topic_id": "china_macro_policy",
            "title": title,
            "source_url": "https://www.stats.gov.cn/english/",
            "source_published_date": ISSUE_DATE,
            "decision": "no_fresh_item",
            "rationale": "アジア経済のchina_macro_policyは公式、報道、補助チャネルを確認し、近接候補の有無を見たが、当日号で新規カード化する具体的な実質差分は確認できなかった。",
            "non_adoption_reason_class": "no_material_change",
            "change_class": "background_only",
            "publication_assessment": "確認した資料は既報、予定表、周辺情報にとどまり、読者向け本文へ追加する新しい決定・数値・結果ではない。",
        }
    )
    asia.setdefault("collected_items", []).append(
        {
            "topic_id": "china_macro_policy",
            "title": title,
            "source_url": "https://www.stats.gov.cn/english/",
            "source_published_date": ISSUE_DATE,
            "observed_at_jst": f"{ISSUE_DATE}T21:55:00+09:00",
            "channel": "web",
            "collection_note": "アジア経済のchina_macro_policyについて直接ページと関連チャネルを当日照合し、当日版へ加える実質差分の有無を判定した。",
        }
    )
    asia.setdefault("watch_topic_checks", []).append(
        {
            "topic_id": "china_macro_policy",
            "checked_at_jst": f"{ISSUE_DATE}T21:55:00+09:00",
            "candidate_titles": [title],
            "result": "アジア経済のchina_macro_policyは直接資料、独立情報、補助チャネルを当日照合し、当日版への反映可否を確認済みの事実に基づいて判定した。",
            "event_classes": ["macro_data", "operations_market"],
            "source_roles_checked": ["primary_or_official", "independent_media_or_data", "social_or_video_signal"],
            "investigation_paths": [
                {
                    "source_role": "primary_or_official",
                    "channel": "web",
                    "evidence_url": "https://www.stats.gov.cn/english/",
                    "finding": "中国国家統計局の公表経路で、対象となる統計系列と公表主体を確認した。",
                },
                {
                    "source_role": "independent_media_or_data",
                    "channel": "web",
                    "evidence_url": "https://www.reuters.com/markets/asia/",
                    "finding": "独立報道の経路で、公式情報と矛盾する追加事実の有無を確認した。",
                },
                {
                    "source_role": "social_or_video_signal",
                    "channel": "web",
                    "evidence_url": "https://www.stats.gov.cn/english/",
                    "finding": "補助情報として公表ページを再確認し、話題のみの更新を切り分けた。",
                },
            ],
            "investigation_hypotheses": [
                "アジア経済のchina_macro_policyに前号後の新しい決定または数値変更がある可能性。",
                "アジア経済のchina_macro_policyは定例・既報・周辺情報であり掲載に足る実質差分がない可能性。",
            ],
            "time_window_jst": {
                "start": "2026-05-21T21:55:00+09:00",
                "end": f"{ISSUE_DATE}T21:55:00+09:00",
            },
            "delta_basis": "公式日付、数値、予定、結果を前号の掲載内容と照合し、実質変化だけを本文に採用した。",
            "search_sweep": {
                "queries": [
                    f"アジア経済 china_macro_policy latest {ISSUE_DATE}",
                    f"アジア経済 china_macro_policy official update {ISSUE_DATE}",
                ],
                "result": "no_new_update",
                "selection_reason": "アジア経済のchina_macro_policyについて、公式ページと関連報道の直近日付を照合し、採用または非採用の理由を確定した。",
            },
            "web": ["https://www.stats.gov.cn/english/", "https://www.reuters.com/markets/asia/"],
        }
    )
    path.write_text(html[: match.start(2)] + json.dumps(manifest, ensure_ascii=False, indent=2) + html[match.end(2) :], encoding="utf-8")


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


def run_guardrail(tmp: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(tmp / "scripts" / "guardrail_inventory.py")],
        cwd=tmp,
        text=True,
        capture_output=True,
    )


def run_sync(tmp: Path) -> None:
    subprocess.run(
        [sys.executable, str(tmp / "scripts" / "sync_site.py"), ISSUE_DATE],
        cwd=tmp,
        text=True,
        capture_output=True,
        check=True,
    )


def assert_pass(name: str, tmp: Path) -> None:
    result = run_gate(tmp)
    if result.returncode != 0:
        raise AssertionError(f"{name}: expected pass, got fail\nSTDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}")


def assert_guardrail_pass(name: str, tmp: Path) -> None:
    result = run_guardrail(tmp)
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


def assert_guardrail_fail(name: str, mutate, expected: str) -> None:
    tmp = copy_fixture()
    mutate(tmp)
    result = run_guardrail(tmp)
    output = result.stdout + result.stderr
    if result.returncode == 0:
        raise AssertionError(f"{name}: expected guardrail failure but passed")
    if expected not in output:
        raise AssertionError(f"{name}: expected '{expected}' in output\n{output}")
    print(f"PASS expected guardrail failure: {name}")


def mutate_root_and_dated(tmp: Path, transform) -> None:
    for path in [tmp / "site" / "index.html", tmp / "site" / ISSUE_DATE / "index.html"]:
        write(path, transform(read(path)))


def remove_investment_section_once(html: str) -> str:
    return re.sub(
        r'\n    <section class="section" id="north_america">.*?(?=\n    <section class="section" id="history">|\n  </main>)',
        "",
        html,
        count=1,
        flags=re.S,
    )


def remove_ici_investment_card(html: str) -> str:
    return re.sub(
        rf'\s*<article class="card[^"]*">(?:(?!</article>).)*<h3>{re.escape(INVESTMENT_SECOND_TITLE)}</h3>.*?</article>',
        "",
        html,
        count=1,
        flags=re.S,
    )


def remove_section_cards(html: str, section_id: str) -> str:
    pattern = rf'(<section class="section" id="{re.escape(section_id)}">.*?<div class="cards">).*?(</div>\s*</section>)'
    return re.sub(pattern, r"\1\n\n      \2", html, count=1, flags=re.S)


def mutate_manifest(tmp: Path, category: str, key: str, value) -> None:
    path = tmp / "details" / f"extraction-log-{ISSUE_DATE}.html"
    html = read(path)
    match = re.search(r'(<script type="application/json" id="coverage-manifest">)(.*?)(</script>)', html, flags=re.S)
    if not match:
        raise AssertionError("fixture missing coverage manifest")
    manifest = json.loads(match.group(2))
    manifest["categories"][category][key] = value
    write(path, html[: match.start(2)] + json.dumps(manifest, ensure_ascii=False, indent=2) + html[match.end(2) :])


def mutate_manifest_entry(tmp: Path, category: str, transform) -> None:
    path = tmp / "details" / f"extraction-log-{ISSUE_DATE}.html"
    html = read(path)
    match = re.search(r'(<script type="application/json" id="coverage-manifest">)(.*?)(</script>)', html, flags=re.S)
    if not match:
        raise AssertionError("fixture missing coverage manifest")
    manifest = json.loads(match.group(2))
    transform(manifest["categories"][category])
    write(path, html[: match.start(2)] + json.dumps(manifest, ensure_ascii=False, indent=2) + html[match.end(2) :])


def mutate_contract(tmp: Path, transform) -> None:
    path = tmp / "config" / "night_signal_coverage.json"
    contract = json.loads(read(path))
    transform(contract)
    write(path, json.dumps(contract, ensure_ascii=False, indent=2) + "\n")


def mutate_manifest_all(tmp: Path, transform) -> None:
    path = tmp / "details" / f"extraction-log-{ISSUE_DATE}.html"
    html = read(path)
    match = re.search(r'(<script type="application/json" id="coverage-manifest">)(.*?)(</script>)', html, flags=re.S)
    if not match:
        raise AssertionError("fixture missing coverage manifest")
    manifest = json.loads(match.group(2))
    transform(manifest)
    write(path, html[: match.start(2)] + json.dumps(manifest, ensure_ascii=False, indent=2) + html[match.end(2) :])


def enable_future_manifest_rules(tmp: Path) -> None:
    mutate_contract(
        tmp,
        lambda contract: contract.update(
            {
                "synthesis_manifest_effective_date": ISSUE_DATE,
                "publication_screening_effective_date": ISSUE_DATE,
                "claim_verification_effective_date": ISSUE_DATE,
                "topic_value_gate_effective_date": ISSUE_DATE,
            }
        ),
    )

    detail_by_title: dict[str, str] = {}
    for detail_path in (tmp / "details").glob("*.html"):
        detail_html = read(detail_path)
        h1 = re.search(r"<h1>(.*?)</h1>", detail_html, flags=re.S)
        if h1:
            title = html_lib.unescape(re.sub(r"<[^>]+>", "", h1.group(1))).strip()
            detail_by_title[title] = detail_html

    def augment(manifest: dict) -> None:
        for entry in manifest["categories"].values():
            for item in entry.get("new_or_changed_items", []):
                detail_html = detail_by_title.get(item["title"], "")
                matching_sources = [source for source in item.get("sources", []) if source in detail_html]
                if matching_sources:
                    item["sources"] = [matching_sources[0]]
                item["summary_mode"] = "single_source_summary"
                item["material_facts"] = [
                    "公表主体と公表日時を本文へ残し、出来事の起点を特定している。",
                    "掲載対象となった数値または結果を本文へ残し、変化の中身を説明している。",
                ]
                item["claim_verification"] = [
                    {
                        "claim_type": "announcement",
                        "source_state": "confirmed_update",
                        "evidence_kind": "direct_source",
                        "claim": "本文で発表または更新として扱った主張を、詳細ページに掲載した直接URLで確認した。",
                        "source_url": item["sources"][0],
                    },
                    {
                        "claim_type": "schedule",
                        "source_state": "scheduled",
                        "evidence_kind": "direct_source",
                        "claim": "本文で予定として扱った主張を、詳細ページに掲載した直接URLで確認した。",
                        "source_url": item["sources"][0],
                    },
                    {
                        "claim_type": "numeric",
                        "source_state": "published_value",
                        "evidence_kind": "direct_source",
                        "claim": "本文で数値として扱った主張を、詳細ページに掲載した直接URLで確認した。",
                        "source_url": item["sources"][0],
                    },
                    {
                        "claim_type": "result",
                        "source_state": "final_result",
                        "evidence_kind": "direct_source",
                        "claim": "本文で結果として扱った主張を、詳細ページに掲載した直接URLで確認した。",
                        "source_url": item["sources"][0],
                    },
                    {
                        "claim_type": "award",
                        "source_state": "confirmed_award",
                        "evidence_kind": "direct_source",
                        "claim": "本文で受賞として扱った主張を、詳細ページに掲載した直接URLで確認した。",
                        "source_url": item["sources"][0],
                    },
                    {
                        "claim_type": "status",
                        "source_state": "confirmed_status",
                        "evidence_kind": "direct_source",
                        "claim": "本文で状態として扱った主張を、詳細ページに掲載した直接URLで確認した。",
                        "source_url": item["sources"][0],
                    },
                ]
            for candidate in entry.get("latest_candidates", []):
                candidate["change_class"] = (
                    "material_update" if candidate.get("decision") == "adopted" else "background_only"
                )
                candidate["publication_assessment"] = (
                    "掲載済み候補は読者が知るべき確定した変化として扱い、非掲載候補は当日差分を伴わない背景情報として判定した。"
                )
                if candidate.get("decision") == "adopted":
                    candidate["topic_value_class"] = "technical_or_product_shift"
                    candidate["reader_delta"] = "公開済み候補は新しい製品、技術、運用、数値、結果のいずれかを含み、読者の見方を更新する。"
                    candidate["materiality_basis"] = "公式資料と補助資料で確認できる新しい変化があり、予定表だけではなく本文に残す価値がある。"

    mutate_manifest_all(tmp, augment)


def run_detail_renderer(tmp: Path, data: dict) -> subprocess.CompletedProcess[str]:
    input_path = tmp / "future-detail-input.json"
    write(input_path, json.dumps(data, ensure_ascii=False, indent=2))
    return subprocess.run(
        [sys.executable, str(tmp / "scripts" / "render_detail.py"), str(input_path)],
        cwd=tmp,
        text=True,
        capture_output=True,
    )


def enable_future_article_layout_on_fixture(tmp: Path) -> None:
    mutate_contract(tmp, lambda contract: contract.update({"article_summary_effective_date": ISSUE_DATE}))
    for detail_path in (tmp / "site" / ISSUE_DATE / "details").glob("*.html"):
        if detail_path.name.startswith("extraction-log-") or detail_path.name == "policy.html":
            continue
        text = read(detail_path)
        text = text.replace('class="summary-lead"', 'class="article-summary"')
        write(detail_path, text)


def append_workflow_text(tmp: Path, text: str) -> None:
    path = tmp / ".github" / "workflows" / "pages.yml"
    write(path, read(path) + "\n" + text + "\n")


def remove_workflow_text(tmp: Path, text: str) -> None:
    path = tmp / ".github" / "workflows" / "pages.yml"
    write(path, read(path).replace(text, "", 1))


def keep_only_one_investment_update(tmp: Path) -> None:
    mutate_root_and_dated(tmp, remove_ici_investment_card)
    detail = tmp / "site" / ISSUE_DATE / "details" / INVESTMENT_SECOND_DETAIL
    if detail.exists():
        detail.unlink()

    def transform(entry: dict) -> None:
        entry["published_card_titles"] = [
            title for title in entry["published_card_titles"] if title != INVESTMENT_SECOND_TITLE
        ]
        entry["new_or_changed_items"] = [
            item for item in entry["new_or_changed_items"] if item.get("title") != INVESTMENT_SECOND_TITLE
        ]
        entry["adopted"] = [
            item for item in entry["adopted"] if item != "ICI combined fund and ETF flows"
        ]
        for candidate in entry["latest_candidates"]:
            if candidate.get("title") == INVESTMENT_SECOND_TITLE:
                candidate["decision"] = "no_fresh_item"
                candidate["non_adoption_reason_class"] = "lower_importance"
                candidate["rationale"] = "北米経済カテゴリで当日採用できる変化が1件だけの場合、固定枠を埋めるためには公開カード化しない。調査証跡は候補として残す。"

    mutate_manifest_entry(tmp, "北米経済", transform)


def mirror_current_detail_to_previous(tmp: Path, name: str) -> None:
    previous_name = name.replace(ISSUE_DATE, "2026-05-18")
    current = read(tmp / "site" / ISSUE_DATE / "details" / name)
    previous = current.replace(ISSUE_DATE, "2026-05-18")
    previous_path = tmp / "site" / "2026-05-18" / "details" / previous_name
    previous_path.parent.mkdir(parents=True, exist_ok=True)
    write(previous_path, previous)


def link_detail_as_prior_date(tmp: Path, name: str) -> None:
    prior_name = name.replace(ISSUE_DATE, "2026-05-23")
    current_path = tmp / "site" / ISSUE_DATE / "details" / name
    prior_path = tmp / "site" / ISSUE_DATE / "details" / prior_name
    shutil.copyfile(current_path, prior_path)
    current_path.unlink()
    mutate_root_and_dated(tmp, lambda html: html.replace(name, prior_name))


def clear_each_source_class_simulations() -> None:
    categories = ["OpenAI", "SoftBank", "Honda", "F1", "SpaceX", "日本経済", "アジア経済", "北米経済", "宇都宮ブレックス", "YOASOBI / 幾田りら"]
    optional_source_classes = {
        "日本経済": {"sns_x", "youtube_video"},
        "アジア経済": {"sns_x", "youtube_video"},
        "北米経済": {"sns_x", "youtube_video"},
    }
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
            if source_class in optional_source_classes.get(category, set()):
                continue
            assert_fail(
                f"{category} missing {source_class}",
                lambda tmp, c=category, s=source_class: mutate_manifest(tmp, c, s, []),
                f"{category} missing source evidence: {source_class}",
            )


def clear_search_terms_simulations() -> None:
    categories = ["OpenAI", "SoftBank", "Honda", "F1", "SpaceX", "日本経済", "アジア経済", "北米経済", "宇都宮ブレックス", "YOASOBI / 幾田りら"]
    for category in categories:
        assert_fail(
            f"{category} missing search_terms",
            lambda tmp, c=category: mutate_manifest(tmp, c, "search_terms", []),
            f"{category} missing search_terms",
        )


def clear_watch_topic_checks_simulations() -> None:
    categories = ["OpenAI", "SoftBank", "Honda", "F1", "SpaceX", "日本経済", "アジア経済", "北米経済", "宇都宮ブレックス", "YOASOBI / 幾田りら"]
    for category in categories:
        assert_fail(
            f"{category} missing watch_topic_checks",
            lambda tmp, c=category: mutate_manifest_entry(tmp, c, lambda entry: entry.pop("watch_topic_checks", None)),
            f"{category} missing watch_topic_checks",
        )


def main() -> int:
    baseline = copy_fixture()
    assert_pass("baseline current issue", baseline)
    print("PASS baseline current issue")
    assert_guardrail_pass("baseline guardrail inventory", baseline)
    print("PASS baseline guardrail inventory")

    latest_link_fixture = copy_fixture()
    sample_path = latest_link_fixture / f"night-brief-web-sample-{ISSUE_DATE}.html"
    write(
        sample_path,
        read(sample_path).replace(
            '<a href="details/extraction-log-',
            '<a href="../index.html">最新号</a>\n        <a href="details/extraction-log-',
            1,
        ),
    )
    run_sync(latest_link_fixture)
    if '<a href="../index.html">最新号</a>' in read(latest_link_fixture / "site" / "index.html"):
        raise AssertionError("root strips dated latest link during sync: fixed URL retained ../index.html")
    assert_pass("root strips dated latest link during sync", latest_link_fixture)
    print("PASS root strips dated latest link during sync")

    assert_guardrail_fail(
        "guardrail catches removed SoftBank market price axis",
        lambda tmp: mutate_contract(
            tmp,
            lambda contract: [
                category.update(
                    {
                        "axes": [
                            axis
                            for axis in category["axes"]
                            if axis.get("id") != "market_price_nav"
                        ]
                    }
                )
                for category in contract["categories"]
                if category.get("label") == "SoftBank"
            ],
        ),
        "softbank_market_price_nav SoftBank missing category axes: market_price_nav",
    )

    assert_guardrail_fail(
        "guardrail catches removed listed-company market class",
        lambda tmp: mutate_contract(
            tmp,
            lambda contract: [
                category.update({"risk_classes": []})
                for category in contract["categories"]
                if category.get("label") in {"SoftBank", "Honda"}
            ],
        ),
        "guardrail category_class has no categories: listed_company_market_sensitive",
    )

    assert_guardrail_fail(
        "guardrail catches workflow fallback to latest issue",
        lambda tmp: append_workflow_text(
            tmp,
            'LATEST_ISSUE_DATE="$(ls night-brief-web-sample-*.html | tail -n 1)"\n'
            'echo "No pushed issue file; using latest committed issue ${LATEST_ISSUE_DATE}" >&2',
        ),
        "latest_issue_publish_only forbidden workflow terms",
    )

    assert_guardrail_fail(
        "guardrail catches workflow changed-date override",
        lambda tmp: append_workflow_text(
            tmp,
            'CHANGED_DATES="$(git diff --name-only ${GITHUB_EVENT_BEFORE} ${GITHUB_SHA})"\n'
            'ISSUE_DATE="$(echo "${CHANGED_DATES}" | tail -n 1)"',
        ),
        "latest_issue_publish_only forbidden workflow terms",
    )

    assert_guardrail_fail(
        "guardrail catches missing published content audit",
        lambda tmp: remove_workflow_text(tmp, "Audit published issue content"),
        "latest_issue_publish_only missing workflow terms",
    )

    assert_guardrail_fail(
        "guardrail catches published content audit mode removal",
        lambda tmp: remove_workflow_text(tmp, " --public-content-only"),
        "latest_issue_publish_only missing workflow terms",
    )

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
        "public abstract framing headline leak",
        lambda tmp: mutate_root_and_dated(
            tmp,
            lambda html: html.replace(SOFTBANK_CARD_TITLE, "<h3>SoftBank、AI投資の説明軸を更新</h3>", 1),
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
                "SoftBank株はOpenAI IPO観測で買われたが、NAVの中身と負債管理が再び論点に戻る",
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
        "detail pages must use 30-second overview-only structure",
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
        "legacy detail pages have too many source links",
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
                '<div class="summary-lead">D.J.ニュービルの移籍先が発表された。ブレックスは来季の後任編成を進める。</div>',
                read(tmp / "site" / ISSUE_DATE / "details" / BREX_DETAIL),
                count=1,
                flags=re.S,
            ).replace(
                "原文確認:",
                "原文確認: 契約満了と移籍先の発表日、所属クラブ名、掲載主体を確認できる公式および主要報道の参照先を明示し、情報の由来を保持する資料:",
                1,
            ),
        ),
        "detail summaries are too thin",
    )

    assert_fail(
        "strict detail summary too thin",
        lambda tmp: mutate_contract(
            tmp,
            lambda contract: contract.update(
                {
                    "summary_quality_effective_date": ISSUE_DATE,
                    "minimum_new_or_changed_summary_chars": 60,
                    "minimum_detail_summary_chars": 420,
                }
            ),
        ),
        "detail summaries are too thin",
    )

    assert_fail(
        "public summary research procedure leak",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL,
            read(tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL).replace(
                '<div class="summary-lead">',
                '<div class="summary-lead">このカテゴリでは公式発表とSNSを毎回確認する必要がある。採用判断は次の反応まで含めて行う。 ',
                1,
            ),
        ),
        "contains editorial/research procedure wording",
    )

    assert_fail(
        "public summary abstract framing leak",
        lambda tmp: [
            write(
                tmp / "scripts" / "quality_gate.py",
                read(tmp / "scripts" / "quality_gate.py").replace(
                    'PUBLIC_ABSTRACT_FRAMING_BAN_EFFECTIVE_DATE = "2026-06-01"',
                    f'PUBLIC_ABSTRACT_FRAMING_BAN_EFFECTIVE_DATE = "{ISSUE_DATE}"',
                    1,
                ),
            ),
            write(
                tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL,
                read(tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL).replace(
                    '<div class="summary-lead">',
                    '<div class="summary-lead">IR文脈で読める状態にしたため、AIデータセンター投資の説明軸がそろった。 ',
                    1,
                ),
            ),
        ],
        "contains abstract/editorial framing wording",
    )

    assert_fail(
        "public summary source-handling commentary leak",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL,
            read(tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL).replace(
                '<div class="summary-lead">',
                '<div class="summary-lead">原文確認先として公式Xも併記し、参照経路を揃えた。 ',
                1,
            ),
        ),
        "source-handling commentary",
    )

    assert_fail(
        "public card research procedure leak",
        lambda tmp: mutate_root_and_dated(
            tmp,
            lambda html: html.replace(
                "<p>公式ページには、神戸・横浜での4公演に続き、ソウルのオリンピック公園 オリンピックホールで2公演を行う日程が掲載されている…</p>",
                "<p>このカテゴリでは公式HPとSNSを必ず確認する必要がある。採用基準は当日反応を含める。</p>",
                1,
            ),
        ),
        "contains editorial/research procedure wording",
    )

    assert_fail(
        "priority selection rationale leak",
        lambda tmp: [
            write(
                tmp / "scripts" / "quality_gate.py",
                read(tmp / "scripts" / "quality_gate.py").replace(
                    'PUBLIC_SELECTION_RATIONALE_BAN_EFFECTIVE_DATE = "2026-05-25"',
                    'PUBLIC_SELECTION_RATIONALE_BAN_EFFECTIVE_DATE = "2026-05-24"',
                    1,
                ),
            ),
            mutate_root_and_dated(
                tmp,
                lambda html: html.replace(
                    '<div class="priority">',
                    '<p class="priority-rationale"><strong>選定理由:</strong> 全件から優先した作業上の説明を公開する。</p><div class="priority">',
                    1,
                ),
            ),
        ],
        "priority section exposes selection rationale",
    )

    assert_fail(
        "missing category section",
        lambda tmp: mutate_root_and_dated(tmp, remove_investment_section_once),
        "missing category sections",
    )

    assert_fail(
        "zero category challenge missing",
        lambda tmp: [
            mutate_contract(
                tmp,
                lambda contract: contract.update({"zero_category_challenge_effective_date": ISSUE_DATE}),
            ),
            mutate_root_and_dated(tmp, lambda html: remove_section_cards(html, "f1")),
            mutate_manifest_entry(
                tmp,
                "F1",
                lambda entry: [
                    entry.update(
                        {
                            "published_card_titles": [],
                            "new_or_changed_items": [],
                            "adopted": [],
                        }
                    ),
                    entry.pop("zero_category_challenge", None),
                    [
                        candidate.update(
                            {
                                "decision": "no_fresh_item",
                                "change_class": "background_only",
                                "non_adoption_reason_class": "no_material_change",
                                "rationale": "F1の候補は近接情報を確認したが、当日号で新規カード化する具体的な実質差分は確認できなかった。",
                                "publication_assessment": "確認した資料は既報または周辺情報にとどまり、読者向け本文へ追加する新しい決定や結果ではない。",
                            }
                        )
                        for candidate in entry.get("latest_candidates", [])
                    ],
                ],
            ),
        ],
        "zero published cards and needs zero_category_challenge",
    )

    one_card_fixture = copy_fixture()
    keep_only_one_investment_update(one_card_fixture)
    assert_pass("variable card count keeps one fresh North America update", one_card_fixture)
    print("PASS variable card count keeps one fresh North America update")

    economic_web_fixture = copy_fixture()
    mutate_manifest_entry(
        economic_web_fixture,
        "アジア経済",
        lambda entry: entry.update({"sns_x": [], "youtube_video": []}),
    )
    assert_pass("regional economy does not require unrelated social source class", economic_web_fixture)
    print("PASS regional economy does not require unrelated social source class")

    future_detail_fixture = copy_fixture()
    future_detail_result = run_detail_renderer(
        future_detail_fixture,
        {
            "issue_date": NEXT_ISSUE_DATE,
            "section_id": "openai",
            "kicker": "OpenAI / 公式・主要報道",
            "title": "OpenAIの新発表を複数原文から整理",
            "h1": "OpenAIの新発表を複数原文から整理",
            "slug": "future-30-second-summary.html",
            "summary": "公式発表は、公開日、対象機能、利用可能な範囲を明示した。主要報道は、導入背景と既存運用との差分を補った。公式に確認できる事実と報道による補足を分けて示し、未公表の条件は確定事項として扱わない。利用者が当日判断に使う対象範囲、時期、残る不確定点を同じ概要内にまとめる。",
            "sources": [
                {"label": "公式発表", "url": "https://example.com/official"},
                {"label": "主要報道", "url": "https://example.com/report"},
                {"label": "関連資料", "url": "https://example.com/data"},
            ],
        },
    )
    if future_detail_result.returncode != 0:
        raise AssertionError(f"future article summary renderer failed: {future_detail_result.stderr}")
    rendered_future_detail = read(future_detail_fixture / "details" / "future-30-second-summary.html")
    if "30秒概要" not in rendered_future_detail or "article-summary" not in rendered_future_detail:
        raise AssertionError("future detail renderer did not use 30-second article summary structure")
    if rendered_future_detail.count("<a href=") < 3:
        raise AssertionError("future article summary renderer discarded source links")
    print("PASS future detail renderer uses 30-second article summary")

    future_layout_fixture = copy_fixture()
    enable_future_article_layout_on_fixture(future_layout_fixture)
    assert_pass("future article detail structure baseline", future_layout_fixture)
    print("PASS future article detail structure baseline")

    assert_fail(
        "future issue rejects non-overview detail heading",
        lambda tmp: [
            enable_future_article_layout_on_fixture(tmp),
            write(
                tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL,
                read(tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL)
                .replace("<h2>30秒概要</h2>", "<h2>記事まとめ</h2>", 1),
            ),
        ],
        "detail pages must use 30-second overview-only structure",
    )

    assert_fail(
        "future issue rejects legacy summary-lead detail body",
        lambda tmp: [
            enable_future_article_layout_on_fixture(tmp),
            write(
                tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL,
                read(tmp / "site" / ISSUE_DATE / "details" / SOFTBANK_DETAIL)
                .replace('<div class="article-summary">', '<div class="summary-lead">', 1),
            ),
        ],
        "detail summaries are too thin",
    )

    assert_fail(
        "future issue rejects prior-date linked detail",
        lambda tmp: [
            enable_future_article_layout_on_fixture(tmp),
            link_detail_as_prior_date(tmp, SOFTBANK_DETAIL),
        ],
        "current issue detail filenames must include issue date",
    )

    future_manifest_fixture = copy_fixture()
    enable_future_manifest_rules(future_manifest_fixture)
    assert_pass("future manifest synthesis baseline", future_manifest_fixture)
    print("PASS future manifest synthesis baseline")

    assert_fail(
        "future published item missing summary mode",
        lambda tmp: [
            enable_future_manifest_rules(tmp),
            mutate_manifest_entry(tmp, "OpenAI", lambda entry: entry["new_or_changed_items"][0].pop("summary_mode", None)),
        ],
        "summary_mode is required for article synthesis",
    )

    assert_fail(
        "future multi-source synthesis omits a source link",
        lambda tmp: [
            enable_future_manifest_rules(tmp),
            mutate_manifest_entry(
                tmp,
                "OpenAI",
                lambda entry: entry["new_or_changed_items"][0].update(
                    {
                        "summary_mode": "multi_source_synthesis",
                        "synthesis_basis": "公式発表で確定した更新内容に主要報道の説明を重ね、同一の出来事として差分と影響を整理した。",
                        "sources": entry["new_or_changed_items"][0]["sources"] + ["https://example.com/omitted-source"],
                    }
                ),
            ),
        ],
        "all synthesis sources must appear on detail page",
    )

    assert_fail(
        "future published item missing claim verification",
        lambda tmp: [
            enable_future_manifest_rules(tmp),
            mutate_manifest_entry(tmp, "OpenAI", lambda entry: entry["new_or_changed_items"][0].pop("claim_verification", None)),
        ],
        "missing claim_verification",
    )

    assert_fail(
        "future result claim cannot use schedule evidence",
        lambda tmp: [
            enable_future_manifest_rules(tmp),
            mutate_manifest_entry(
                tmp,
                "OpenAI",
                lambda entry: entry["new_or_changed_items"][0]["claim_verification"][0].update(
                    {"claim_type": "result", "source_state": "scheduled", "claim": "本文で優勝した結果として扱った主張を予定情報で代用した。"}
                ),
            ),
        ],
        "claim/source state mismatch",
    )

    assert_fail(
        "future material candidate cannot remain no-fresh",
        lambda tmp: [
            enable_future_manifest_rules(tmp),
            mutate_manifest_entry(
                tmp,
                "OpenAI",
                lambda entry: next(
                    candidate for candidate in entry["latest_candidates"] if candidate["decision"] != "adopted"
                ).update({"change_class": "material_update"}),
            ),
        ],
        "fresh material candidate must be published or explicitly excluded",
    )

    assert_fail(
        "future routine adoption needs materiality basis",
        lambda tmp: [
            enable_future_manifest_rules(tmp),
            mutate_manifest_entry(
                tmp,
                "OpenAI",
                lambda entry: [
                    next(
                        candidate for candidate in entry["latest_candidates"] if candidate["decision"] == "adopted"
                    ).update({"change_class": "routine_recurring"}),
                    next(
                        candidate for candidate in entry["latest_candidates"] if candidate["decision"] == "adopted"
                    ).pop("materiality_basis", None),
                ],
            ),
        ],
        "adopted routine or duplicate candidate needs materiality_basis",
    )

    assert_fail(
        "future adopted item missing topic value",
        lambda tmp: [
            enable_future_manifest_rules(tmp),
            mutate_manifest_entry(
                tmp,
                "OpenAI",
                lambda entry: next(
                    candidate for candidate in entry["latest_candidates"] if candidate["decision"] == "adopted"
                ).pop("topic_value_class", None),
            ),
        ],
        "adopted candidate missing topic_value_class",
    )

    assert_fail(
        "future schedule-only topic value is rejected",
        lambda tmp: [
            enable_future_manifest_rules(tmp),
            mutate_manifest_entry(
                tmp,
                "OpenAI",
                lambda entry: next(
                    candidate for candidate in entry["latest_candidates"] if candidate["decision"] == "adopted"
                ).update(
                    {
                        "change_class": "routine_recurring",
                        "topic_value_class": "material_schedule_change",
                        "materiality_basis": "公式カレンダー上の日付と開催予定だけを確認した。結果や仕様変更はなく、予定表としての確認にとどまる。",
                        "reader_delta": "読者は開催日と周回数だけを知る。新しい決定、資金、技術、結果、安全リスクはまだ出ていない。",
                    }
                ),
            ),
        ],
        "schedule-only candidate is too weak",
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
            '<html><head><title>SoftBank</title></head><body><main><a class="back" href="../index.html#softbank">一覧へ戻る</a><article><h1>SoftBank株が続伸、OpenAIのIPO観測とSB Energy上場計画が材料に</h1><h2>30秒概要</h2><div class="summary-lead">SoftBank株はOpenAI IPO観測で動いた。</div><div class="source">原文確認:<a href="https://group.softbank/en/news/press/20260401_0">SBG</a></div></article></main></body></html>',
        ),
        "sources must overlap linked detail page sources",
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
        "OpenAI new_or_changed_items must mirror published cards",
    )

    assert_fail(
        "coverage new item source mismatch",
        lambda tmp: mutate_manifest(
            tmp,
            "OpenAI",
            "new_or_changed_items",
            [
                {
                    "title": "Codexは「承認付きの長時間実行」が標準に、リモート操作は便利さ以上に統制を問う",
                    "summary": "OpenAIは画像の出所情報を残す仕組みを強化し、C2PA準拠とSynthIDのウォーターマークを組み合わせる方針を示した。生成物の拡散前検知、ラベル付け、監査可能性を同時に上げるための基盤更新として重要度が高く、プラットフォーム側の運用コストにも直結する。",
                    "sources": ["https://example.com/not-the-detail-source"],
                },
                {
                    "title": "ChatGPTリリースノート更新：Codexのモバイル接続とAppshotsで「長時間タスク」を前提化",
                    "summary": "ChatGPTのリリースノートでは、Codexをモバイルから扱う導線やAppshotsのような画面文脈の共有が強まり、長時間タスクの進捗確認と承認が前提になってきた。企業利用では端末管理と承認フローの設計が焦点になり、便利さより統制設計が導入可否を左右する。",
                    "sources": ["https://help.openai.com/en/articles/6825453-chatgpt-release-notes"],
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
                    "title": "Codexは「承認付きの長時間実行」が標準に、リモート操作は便利さ以上に統制を問う",
                    "summary": "OpenAI disclosed that an internal model disproved a long-standing discrete geometry conjecture, making research capability itself a market and enterprise adoption signal beyond product release notes.",
                    "sources": ["https://openai.com/index/advancing-content-provenance/"],
                },
                {
                    "title": "ChatGPTリリースノート更新：Codexのモバイル接続とAppshotsで「長時間タスク」を前提化",
                    "summary": "ChatGPTのリリースノートでは、Codexをモバイルから扱う導線やAppshotsのような画面文脈の共有が強まり、長時間タスクの進捗確認と承認が前提になってきた。企業利用では端末管理と承認フローの設計が焦点になる。",
                    "sources": ["https://help.openai.com/en/articles/6825453-chatgpt-release-notes"],
                },
            ],
        ),
        "summary must be Japanese",
    )

    assert_fail(
        "coverage strict new item summary too thin",
        lambda tmp: [
            mutate_contract(tmp, lambda contract: contract.update({"summary_quality_effective_date": ISSUE_DATE})),
            mutate_manifest(
                tmp,
                "OpenAI",
                "new_or_changed_items",
                [
                    {
                        "title": "Codexは「承認付きの長時間実行」が標準に、リモート操作は便利さ以上に統制を問う",
                        "summary": "OpenAIは画像の出所情報を残す仕組みを強化し、C2PA準拠とSynthIDのウォーターマークを組み合わせる方針を示した。生成物の拡散前検知、ラベル付け、監査可能性を同時に上げるための基盤更新として重要度が高く、プラットフォーム側の運用コストにも直結する。",
                        "sources": ["https://openai.com/index/advancing-content-provenance/"],
                    },
                    {
                        "title": "ChatGPTリリースノート更新：Codexのモバイル接続とAppshotsで「長時間タスク」を前提化",
                        "summary": "Codexのモバイル接続が広がった。",
                        "sources": ["https://help.openai.com/en/articles/6825453-chatgpt-release-notes"],
                    },
                ],
            ),
        ],
        "sources must overlap linked detail page sources",
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
        "coverage latest candidates missing",
        lambda tmp: mutate_manifest(tmp, "OpenAI", "latest_candidates", []),
        "OpenAI latest_candidates missing watch topics",
    )

    assert_fail(
        "coverage collected items missing",
        lambda tmp: mutate_manifest_entry(tmp, "OpenAI", lambda entry: entry.pop("collected_items", None)),
        "OpenAI missing collected_items",
    )

    assert_fail(
        "coverage latest candidate search URL rejected",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["latest_candidates"][0].update(
                {"source_url": "https://www.youtube.com/results?search_query=OpenAI%20latest"}
            ),
        ),
        "OpenAI latest_candidates[1] source_url cannot be a search result URL",
    )

    assert_fail(
        "coverage collected item search URL rejected",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["collected_items"][0].update(
                {"source_url": "https://x.com/search?q=OpenAI%20latest&src=typed_query"}
            ),
        ),
        "OpenAI collected_items[1] source_url cannot be a search result URL",
    )

    assert_fail(
        "coverage latest watch topic missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry.update(
                {
                    "latest_candidates": [
                        candidate
                        for candidate in entry["latest_candidates"]
                        if candidate.get("topic_id") != "ipo_financing"
                    ]
                }
            ),
        ),
        "OpenAI latest_candidates missing watch topics: ipo_financing",
    )

    assert_fail(
        "coverage SoftBank market price watch topic missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "SoftBank",
            lambda entry: entry.update(
                {
                    "latest_candidates": [
                        candidate
                        for candidate in entry["latest_candidates"]
                        if candidate.get("topic_id") != "market_price_nav"
                    ]
                }
            ),
        ),
        "SoftBank latest_candidates missing watch topics: market_price_nav",
    )

    assert_fail(
        "coverage Honda market reaction watch topic missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "Honda",
            lambda entry: entry.update(
                {
                    "latest_candidates": [
                        candidate
                        for candidate in entry["latest_candidates"]
                        if candidate.get("topic_id") != "market_price_reaction"
                    ]
                }
            ),
        ),
        "Honda latest_candidates missing watch topics: market_price_reaction",
    )

    assert_fail(
        "coverage watch topic checks missing",
        lambda tmp: mutate_manifest_entry(tmp, "OpenAI", lambda entry: entry.pop("watch_topic_checks", None)),
        "OpenAI missing watch_topic_checks",
    )

    assert_fail(
        "coverage watch topic check missing topic",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry.update(
                {
                    "watch_topic_checks": [
                        check for check in entry["watch_topic_checks"] if check.get("topic_id") != "ipo_financing"
                    ]
                }
            ),
        ),
        "OpenAI watch_topic_checks missing topics: ipo_financing",
    )

    assert_fail(
        "coverage watch topic YouTube evidence missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["watch_topic_checks"][0].update({"youtube": ["https://example.com/no-youtube"]}),
        ),
        "OpenAI watch_topic_checks[1].youtube must include YouTube URL evidence",
    )

    assert_fail(
        "coverage investigation hypotheses missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["watch_topic_checks"][0].pop("investigation_hypotheses", None),
        ),
        "OpenAI watch_topic_checks[1] needs at least",
    )

    assert_fail(
        "coverage search sweep missing",
        lambda tmp: [
            mutate_contract(
                tmp,
                lambda contract: contract.update({"search_sweep_required_effective_date": ISSUE_DATE}),
            ),
            mutate_manifest_entry(
                tmp,
                "OpenAI",
                lambda entry: entry["watch_topic_checks"][0].pop("search_sweep", None),
            ),
        ],
        "OpenAI watch_topic_checks[1] missing search_sweep",
    )

    assert_fail(
        "coverage search sweep query URL rejected",
        lambda tmp: [
            mutate_contract(tmp, lambda contract: contract.update({"search_sweep_required_effective_date": ISSUE_DATE})),
            mutate_manifest_entry(
                tmp,
                "OpenAI",
                lambda entry: entry["watch_topic_checks"][0].update(
                    {
                        "search_sweep": {
                            "queries": [
                                "https://www.google.com/search?q=OpenAI+latest",
                                "OpenAI IPO mathematics Codex latest 2026",
                            ],
                            "result": "covered_by_existing_candidate",
                            "selection_reason": "検索結果ページそのものを根拠にしてしまう失敗例を検出するための日本語理由です。",
                        }
                    }
                ),
            ),
        ],
        "search_sweep.queries[1] must be query text, not a URL",
    )

    assert_fail(
        "coverage investigation paths missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["watch_topic_checks"][0].pop("investigation_paths", None),
        ),
        "OpenAI watch_topic_checks[1] needs at least",
    )

    assert_fail(
        "coverage investigation path search URL rejected",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["watch_topic_checks"][0]["investigation_paths"][0].update(
                {"evidence_url": "https://www.youtube.com/results?search_query=OpenAI%20latest", "channel": "youtube"}
            ),
        ),
        "OpenAI watch_topic_checks[1].investigation_paths[1] evidence_url cannot be a search result URL",
    )

    assert_fail(
        "coverage source roles missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["watch_topic_checks"][0].update({"source_roles_checked": ["primary_or_official"]}),
        ),
        "OpenAI watch_topic_checks[1] missing source_roles_checked",
    )

    assert_fail(
        "coverage event class missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["watch_topic_checks"][0].update({"event_classes": []}),
        ),
        "OpenAI watch_topic_checks[1] missing event_classes",
    )

    assert_fail(
        "coverage watch topic candidate not linked",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["watch_topic_checks"][0].update({"candidate_titles": ["OpenAI 未接続の候補"]}),
        ),
        "OpenAI watch_topic_checks[1] candidate_titles must match latest_candidates",
    )

    assert_fail(
        "coverage watch topic checked date mismatch",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["watch_topic_checks"][0].update({"checked_at_jst": "2026-05-20T20:45:00+09:00"}),
        ),
        "OpenAI watch_topic_checks[1] checked_at_jst date mismatch",
    )

    assert_fail(
        "coverage watch topic checked timezone missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["watch_topic_checks"][0].update({"checked_at_jst": "2026-05-21T20:45:00"}),
        ),
        "OpenAI watch_topic_checks[1] checked_at_jst must use JST offset",
    )

    assert_fail(
        "coverage adopted latest candidate not published",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["latest_candidates"].append(
                {
                    "topic_id": "product_release",
                    "title": "OpenAI、未掲載の新モデル候補を採用扱いにする",
                    "source_url": "https://help.openai.com/en/articles/6825453-chatgpt-release-notes",
                    "source_published_date": ISSUE_DATE,
                    "decision": "adopted",
                    "rationale": "採用扱いにした候補が公開カードへ出ていない状態を失敗させるための検証項目です。",
                }
            ),
        ),
        "adopted latest candidate is not published as a card",
    )

    assert_fail(
        "coverage fresh candidate deferred without resolution",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: entry["latest_candidates"].append(
                {
                    "topic_id": "product_release",
                    "title": "OpenAI、鮮度の高い重要候補を後回しにする",
                    "source_url": "https://help.openai.com/en/articles/6825453-chatgpt-release-notes",
                    "source_published_date": ISSUE_DATE,
                    "decision": "held",
                    "rationale": "現行公開カードには未反映のため、次回の採用候補として残すという失敗例です。",
                }
            ),
        ),
        "fresh latest candidate was deferred instead of resolved",
    )

    assert_fail(
        "coverage fresh non-adopted candidate missing reason class",
        lambda tmp: [
            mutate_contract(
                tmp,
                lambda contract: contract.update(
                    {"fresh_non_adopted_reason_required_effective_date": ISSUE_DATE}
                ),
            ),
            mutate_manifest_entry(
                tmp,
                "OpenAI",
                lambda entry: entry["latest_candidates"][0].pop("non_adoption_reason_class", None),
            ),
        ],
        "fresh non-adopted latest candidate missing non_adoption_reason_class",
    )

    assert_fail(
        "coverage stale adopted latest candidate without override",
        lambda tmp: [
            mutate_contract(
                tmp,
                lambda contract: contract.update(
                    {"strict_adopted_candidate_source_age_effective_date": "2099-01-01"}
                ),
            ),
            mutate_manifest_entry(
                tmp,
                "OpenAI",
                lambda entry: [
                    candidate.update({"source_published_date": "2026-05-18"})
                    for candidate in entry["latest_candidates"]
                    if candidate.get("title") == "Codexは「承認付きの長時間実行」が標準に、リモート操作は便利さ以上に統制を問う"
                ],
            ),
        ],
        "OpenAI adopted latest candidate is stale",
    )

    assert_fail(
        "coverage strict stale adopted candidate blocked after effective date",
        lambda tmp: [
            mutate_contract(
                tmp,
                lambda contract: contract.update(
                    {"strict_adopted_candidate_source_age_effective_date": ISSUE_DATE}
                ),
            ),
            mutate_manifest_entry(
                tmp,
                "OpenAI",
                lambda entry: [
                    candidate.update({"source_published_date": "2026-05-18"})
                    for candidate in entry["latest_candidates"]
                    if candidate.get("title") == "Codexは「承認付きの長時間実行」が標準に、リモート操作は便利さ以上に統制を問う"
                ],
            ),
        ],
        "adopted latest candidate exceeds strict source age and must stay background-only",
    )


    assert_fail(
        "OpenAI product release X signal missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "OpenAI",
            lambda entry: [
                entry.update({"sns_x": []}),
                [
                    check.update({"sns_x": []})
                    for check in entry.get("watch_topic_checks", [])
                    if check.get("topic_id") == "product_release"
                ],
            ],
        ),
        "OpenAI missing source evidence: sns_x",
    )

    assert_fail(
        "SpaceX official launch manifest X signal missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "SpaceX",
            lambda entry: [
                entry.update({"sns_x": []}),
                [
                    check.update({"sns_x": []})
                    for check in entry.get("watch_topic_checks", [])
                    if check.get("topic_id") == "official_launch_manifest"
                ],
            ],
        ),
        "SpaceX missing source evidence: sns_x",
    )

    assert_fail(
        "YOASOBI staff social search axis missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "YOASOBI / 幾田りら",
            lambda entry: entry["search_axes"].pop("staff_social_x_instagram", None),
        ),
        "YOASOBI / 幾田りら search_axis staff_social_x_instagram",
    )

    assert_fail(
        "YOASOBI staff X and Instagram source missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "YOASOBI / 幾田りら",
            lambda entry: [
                entry.update({"sns_x": []}),
                entry.update({"official": [url for url in entry.get("official", []) if "instagram" not in url]}),
                [
                    check.update({"sns_x": []})
                    for check in entry.get("watch_topic_checks", [])
                    if check.get("topic_id") == "staff_social_x_instagram"
                ],
            ],
        ),
        "YOASOBI / 幾田りら missing source evidence: sns_x",
    )

    assert_fail(
        "regional economy taxonomy rejects broad investment category",
        lambda tmp: mutate_contract(
            tmp,
            lambda contract: contract["categories"].append(
                {"label": "投資", "section_id": "investment", "axes": [], "watch_topics": []}
            ),
        ),
        "coverage contract still contains broad economic sections",
    )

    assert_fail(
        "regional economy taxonomy requires North America section",
        lambda tmp: mutate_contract(
            tmp,
            lambda contract: contract.update(
                {"categories": [category for category in contract["categories"] if category.get("label") != "北米経済"]}
            ),
        ),
        "coverage contract missing regional economic sections",
    )

    assert_fail(
        "regional economy rejects wrong-country official evidence",
        lambda tmp: [
            mutate_contract(
                tmp,
                lambda contract: contract.update({"scoped_primary_evidence_effective_date": ISSUE_DATE}),
            ),
            mutate_manifest_entry(
                tmp,
                "アジア経済",
                lambda entry: entry["watch_topic_checks"][1]["investigation_paths"][0].update(
                    {"evidence_url": "https://rbi.org.in/Scripts/BS_ViewWSS.aspx"}
                ),
            ),
        ],
        "primary evidence host outside configured topic scope",
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
        "アジア経済 search_axis india_macro_policy needs at least",
    )

    assert_fail(
        "SoftBank market price search axis missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "SoftBank",
            lambda entry: entry["search_axes"].pop("market_price_nav", None),
        ),
        "SoftBank search_axis market_price_nav",
    )

    assert_fail(
        "Honda market reaction search axis missing",
        lambda tmp: mutate_manifest_entry(
            tmp,
            "Honda",
            lambda entry: entry["search_axes"].pop("market_price_reaction", None),
        ),
        "Honda search_axis market_price_reaction",
    )

    assert_fail(
        "critical unresolved risk blocks publication",
        lambda tmp: mutate_manifest(tmp, "OpenAI", "critical_unresolved", ["official announcement not checked"]),
        "OpenAI has critical unresolved risks",
    )

    clear_each_source_class_simulations()
    clear_search_terms_simulations()
    clear_watch_topic_checks_simulations()

    print("ALL QUALITY GATE SIMULATIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
