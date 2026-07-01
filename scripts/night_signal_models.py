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
    quality_model = config.get("quality_model")
    fallbacks = config.get("fallback_models", [])
    if not isinstance(fallbacks, list):
        raise ValueError("fallback_models must be a list")
    return list(
        dict.fromkeys(
            [
                primary,
                *([quality_model] if isinstance(quality_model, str) and quality_model else []),
                *[value for value in fallbacks if isinstance(value, str) and value],
            ]
        )
    )


def extraction_model() -> str:
    return extraction_models()[0]


def routed_models(*, quality_required: bool) -> list[str]:
    config = load_config()["extraction"]
    routine = extraction_model()
    quality = config.get("quality_model")
    preferred = (
        str(quality)
        if quality_required and isinstance(quality, str) and quality
        else routine
    )
    return list(dict.fromkeys([preferred, *extraction_models()]))


def self_test() -> None:
    chain = extraction_models()
    if not chain:
        raise SystemExit("extraction model chain is empty")
    if len(chain) != len(set(chain)):
        raise SystemExit("extraction model chain contains duplicates")
    config = load_config()["extraction"]
    if (
        not os.getenv("NIGHT_SIGNAL_MODEL")
        and config.get("quality_model")
        and chain.index(str(config["quality_model"])) == 0
    ):
        raise SystemExit("quality model must be an escalation, not the routine model")
    if routed_models(quality_required=False)[0] != chain[0]:
        raise SystemExit("routine routing must use the routine model first")
    quality = config.get("quality_model")
    if quality and routed_models(quality_required=True)[0] != quality:
        raise SystemExit("quality routing must use the quality model first")
    print("NIGHT SIGNAL MODELS PASSED")


if __name__ == "__main__":
    self_test()
