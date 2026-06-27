#!/usr/bin/env python3
"""Resolve the one model chain used for evidence extraction."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "night_signal_models.json"


def load_config() -> dict[str, Any]:
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("extraction"), dict):
        raise ValueError("night_signal_models must define extraction")
    return value


def extraction_models() -> list[str]:
    config = load_config()["extraction"]
    override = os.getenv("NIGHT_SIGNAL_MODEL")
    primary = override or config.get("model")
    if not isinstance(primary, str) or not primary:
        raise ValueError("extraction model is missing")
    fallbacks = config.get("fallback_models", [])
    if not isinstance(fallbacks, list):
        raise ValueError("fallback_models must be a list")
    return list(
        dict.fromkeys(
            [primary, *[value for value in fallbacks if isinstance(value, str) and value]]
        )
    )


def extraction_model() -> str:
    return extraction_models()[0]


def self_test() -> None:
    if not extraction_models():
        raise SystemExit("extraction model chain is empty")
    print("NIGHT SIGNAL MODELS PASSED")


if __name__ == "__main__":
    self_test()
