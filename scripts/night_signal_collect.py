#!/usr/bin/env python3
"""Collect NIGHT SIGNAL Evidence without performing editorial work."""

from __future__ import annotations

import argparse
import json
from datetime import datetime

import night_signal_core as core


def self_test() -> None:
    category = {
        "label": "CoverageTest",
        "axes": [],
        "watch_topics": [
            {"id": f"topic-{index}", "terms": [f"term-{index}"], "event_classes": []}
            for index in range(20)
        ],
    }
    if "term-19" not in " ".join(core.news_queries(category, "2099-01-01")):
        core.fail("collector dropped later watch topics")
    records = [
        {
            "url": f"https://example.com/{index}",
            "observed": True,
            "source_class": "discovered_media",
            "published_date": "2099-01-01",
            "title": f"Material update {index}",
            "excerpt": f"A distinct material change {index} was announced.",
        }
        for index in range(20)
    ]
    if len(core.select_clustered_evidence(category, records)) != len(records):
        core.fail("collector truncated distinct Evidence records")
    if len(core.enrichment_target_urls(category, "2099-01-01", records)) != len(records):
        core.fail("collector capped distinct headline-only enrichment targets")
    print("NIGHT SIGNAL COLLECT SELF-TEST PASSED")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "issue_date",
        nargs="?",
        default=datetime.now(core.JST).date().isoformat(),
    )
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args()
    if args.self_test:
        self_test()
        return 0
    print(json.dumps(core.collect_evidence(args.issue_date), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
