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
ISSUE_DATE = "2026-05-15"


def copy_fixture() -> Path:
    tmp = Path(tempfile.mkdtemp(prefix="night-signal-gate-"))
    (tmp / "scripts").mkdir()
    (tmp / "details").mkdir()
    shutil.copyfile(ROOT / "scripts" / "quality_gate.py", tmp / "scripts" / "quality_gate.py")
    shutil.copyfile(ROOT / f"night-brief-web-sample-{ISSUE_DATE}.html", tmp / f"night-brief-web-sample-{ISSUE_DATE}.html")
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
            lambda html: html.replace("<h3>SoftBank Group", "<h3>一次で固定 SoftBank Group", 1),
        ),
        "card titles contain policy/checklist wording",
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
        lambda tmp: mutate_root_and_dated(tmp, lambda html: html.replace(">2026-05-15<", ">2026-05-10<", 1)),
        "stale cards found",
    )

    assert_fail(
        "broken local detail link",
        lambda tmp: mutate_root_and_dated(tmp, lambda html: html.replace("details/softbank-2026-05-15.html", "details/missing.html", 1)),
        "missing file: site/2026-05-15/details/missing.html",
    )

    assert_fail(
        "unlinked stale detail page copied into issue",
        lambda tmp: write(tmp / "site" / ISSUE_DATE / "details" / "stale-extra.html", "<html><body>old</body></html>"),
        "published issue contains unlinked stale detail pages",
    )

    assert_fail(
        "coverage manifest source evidence missing",
        lambda tmp: mutate_manifest(tmp, "OpenAI", "official", []),
        "OpenAI missing source evidence: official",
    )

    assert_fail(
        "detail page too thin",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / "softbank-2026-05-15.html",
            '<html><head><title>SoftBank</title></head><body><main><a class="back" href="../index.html#softbank">一覧へ戻る</a><article><h1>SoftBank</h1><p>薄い要約。</p><div class="source">原文確認:<a href="https://example.com">source</a></div></article></main></body></html>',
        ),
        "detail pages too thin",
    )

    assert_fail(
        "detail heading policy wording leak",
        lambda tmp: write(
            tmp / "site" / ISSUE_DATE / "details" / "softbank-2026-05-15.html",
            read(tmp / "site" / ISSUE_DATE / "details" / "softbank-2026-05-15.html").replace("<h1>", "<h1>一次で固定 ", 1),
        ),
        "detail headings contain policy/checklist wording",
    )

    assert_fail(
        "category-specific search axis missing",
        lambda tmp: mutate_manifest(tmp, "アジア経済", "search_terms", ["India CPI April 2026"]),
        "アジア経済 search_terms missing required axis",
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
