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
        "published issue missing linked detail pages",
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

    print("ALL QUALITY GATE SIMULATIONS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
