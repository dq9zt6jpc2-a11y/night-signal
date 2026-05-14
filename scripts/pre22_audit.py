#!/usr/bin/env python3
"""Pre-22:00 JST publication audit for NIGHT SIGNAL.

This script is meant to run at ~21:45 JST to confirm:
1) Today's artifacts exist (sample, extraction log, published site files).
2) The stable entry page shows today's date.
3) The quality gate passes (freshness + extraction evidence manifest).

Exit code:
- 0 when audit passes (quality gate passes).
- 1 when audit fails (missing artifacts or quality gate fails).
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[assignment]


ROOT = Path(__file__).resolve().parents[1]
SITE_ROOT = ROOT / "site"
DETAILS = ROOT / "details"


def jst_today() -> str:
    if ZoneInfo is None:
        return datetime.now().strftime("%Y-%m-%d")
    return datetime.now(ZoneInfo("Asia/Tokyo")).strftime("%Y-%m-%d")


def issue_date_from_args() -> str:
    return sys.argv[1] if len(sys.argv) > 1 else jst_today()


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@dataclass(frozen=True)
class CardStats:
    total: int
    newest_date_counts: Counter[str]


def section_before_history(html: str) -> str:
    return html.split('<section class="section" id="history">', 1)[0]


def card_blocks(html: str) -> list[str]:
    body = section_before_history(html)
    return re.findall(r'<article class="(?:card|priority-card)[^"]*">.*?</article>', body, flags=re.S)


def card_newest_date(card_html: str) -> str | None:
    dates = re.findall(r'<span class="pill[^"]*">(20\d{2}-\d{2}-\d{2})</span>', card_html)
    if not dates:
        return None
    return max(dates)


def card_stats(html: str) -> CardStats:
    cards = card_blocks(html)
    newest = [d for c in cards if (d := card_newest_date(c))]
    return CardStats(total=len(cards), newest_date_counts=Counter(newest))


def parse_manifest_counts(extraction_log_html: str) -> dict[str, dict[str, int]]:
    match = re.search(
        r'<script type="application/json" id="coverage-manifest">(.*?)</script>',
        extraction_log_html,
        flags=re.S,
    )
    if not match:
        return {}
    manifest = json.loads(match.group(1))
    categories = manifest.get("categories")
    if not isinstance(categories, dict):
        return {}
    result: dict[str, dict[str, int]] = {}
    for category, entry in categories.items():
        if not isinstance(entry, dict):
            continue
        result[str(category)] = {
            "adopted": len(entry.get("adopted", []) or []),
            "held": len(entry.get("held", []) or []),
            "excluded": len(entry.get("excluded", []) or []),
            "unresolved": len(entry.get("unresolved", []) or []),
            "critical_unresolved": len(entry.get("critical_unresolved", []) or []),
        }
    return result


def run_quality_gate(issue_date: str) -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "quality_gate.py"), issue_date],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
    )
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    combined = "\n".join([part for part in [out, err] if part])
    return proc.returncode == 0, combined


def main() -> int:
    issue_date = issue_date_from_args()
    expected_title = f"NIGHT SIGNAL | {issue_date}"
    display_date = issue_date.replace("-", ".")

    required = [
        ROOT / f"night-brief-web-sample-{issue_date}.html",
        DETAILS / f"extraction-log-{issue_date}.html",
        SITE_ROOT / issue_date / "index.html",
        SITE_ROOT / "index.html",
    ]

    missing = [path for path in required if not path.exists()]
    if missing:
        print("AUDIT FAILED: missing required artifacts", file=sys.stderr)
        for path in missing:
            print(f"- {path.relative_to(ROOT)}", file=sys.stderr)
        ok, msg = run_quality_gate(issue_date)
        if msg:
            print(msg, file=sys.stderr)
        return 1

    root_html = read_text(SITE_ROOT / "index.html")
    if expected_title not in root_html or display_date not in root_html:
        print("AUDIT FAILED: stable page date mismatch", file=sys.stderr)
        print(f"- expected title: {expected_title}", file=sys.stderr)
        print(f"- expected display date: {display_date}", file=sys.stderr)
        return 1

    extraction_log_html = read_text(DETAILS / f"extraction-log-{issue_date}.html")
    manifest_counts = parse_manifest_counts(extraction_log_html)

    ok, gate_message = run_quality_gate(issue_date)
    if ok:
        print(f"AUDIT PASSED: {issue_date}")
        print(gate_message)
    else:
        print(f"AUDIT FAILED: {issue_date}", file=sys.stderr)
        print(gate_message, file=sys.stderr)

    stats = card_stats(root_html)
    print(f"Cards(total): {stats.total}")
    for d, c in stats.newest_date_counts.most_common(6):
        print(f"- newest_date {d}: {c}")

    if manifest_counts:
        print("Coverage(adopted/held/excluded/unresolved/critical):")
        for category, counts in manifest_counts.items():
            print(
                f"- {category}: "
                f"{counts['adopted']}/{counts['held']}/{counts['excluded']}/"
                f"{counts['unresolved']}/{counts['critical_unresolved']}"
            )
    else:
        print("Coverage: (no manifest parsed)")

    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

