#!/usr/bin/env python3
"""Send a NIGHT SIGNAL URL to LINE Messaging API.

Required environment variables:
  LINE_CHANNEL_ACCESS_TOKEN
  LINE_USER_ID

Usage:
  python3 scripts/send_line.py "https://example.com/night-signal/2026-05-10/"
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request


def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: send_line.py <public-url>", file=sys.stderr)
        return 2

    url = sys.argv[1]
    token = os.environ.get("LINE_CHANNEL_ACCESS_TOKEN")
    user_id = os.environ.get("LINE_USER_ID")

    if not token or not user_id:
        print(
            "Missing LINE_CHANNEL_ACCESS_TOKEN or LINE_USER_ID.",
            file=sys.stderr,
        )
        return 2

    message = (
        "NIGHT SIGNAL 夜版\n\n"
        "今日の重要情報を日本語要約でまとめました。\n"
        f"{url}"
    )
    payload = {
        "to": user_id,
        "messages": [{"type": "text", "text": message}],
    }
    req = urllib.request.Request(
        "https://api.line.me/v2/bot/message/push",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    with urllib.request.urlopen(req, timeout=20) as res:
        if res.status != 200:
            print(f"LINE API returned {res.status}", file=sys.stderr)
            return 1
    print("Sent LINE message.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
