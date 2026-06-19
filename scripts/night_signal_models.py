#!/usr/bin/env python3
"""Resolve NIGHT SIGNAL model routes from one config file."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config" / "night_signal_models.json"


def load_config() -> dict[str, Any]:
    value = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("night_signal_models config must be an object")
    return value


def route_config(route: str) -> dict[str, Any]:
    routes = load_config().get("routes", {})
    if not isinstance(routes, dict):
        raise ValueError("night_signal_models routes must be an object")
    value = routes.get(route)
    if not isinstance(value, dict):
        fallback = routes.get("small_structured_extractor")
        if not isinstance(fallback, dict):
            raise ValueError(f"missing model route: {route}")
        return fallback
    return value


def model_for_route(route: str) -> str:
    config = load_config()
    route_value = route_config(route)
    env_key = route_value.get("env")
    if isinstance(env_key, str) and os.getenv(env_key):
        return os.environ[env_key]
    global_env = config.get("global_env")
    if isinstance(global_env, str) and os.getenv(global_env):
        return os.environ[global_env]
    model = route_value.get("default_model")
    if not isinstance(model, str) or not model:
        raise ValueError(f"missing default model for route: {route}")
    return model


def reasoning_for_route(route: str) -> dict[str, str]:
    effort = os.getenv("NIGHT_SIGNAL_REASONING_EFFORT")
    if not effort:
        route_value = route_config(route)
        configured = route_value.get("reasoning_effort")
        effort = configured if isinstance(configured, str) and configured else "low"
    return {"effort": effort}


def self_test() -> None:
    if not model_for_route("small_structured_extractor"):
        raise SystemExit("small route model missing")
    if not model_for_route("frontier_reasoning_model"):
        raise SystemExit("frontier route model missing")
    if reasoning_for_route("frontier_reasoning_model").get("effort") not in {"low", "medium", "high"}:
        raise SystemExit("frontier reasoning effort invalid")
    print("NIGHT SIGNAL MODELS PASSED")


if __name__ == "__main__":
    self_test()
