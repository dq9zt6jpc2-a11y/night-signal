#!/usr/bin/env python3
"""Validate NIGHT SIGNAL recurrence-prevention guardrails.

This script is intentionally meta: it checks that previous user-reported
failure classes are represented in the collection contract, policy, audit code,
and failure simulations. A fix that only changes today's HTML should not pass.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
COVERAGE_PATH = ROOT / "config" / "night_signal_coverage.json"
GUARDRAILS_PATH = ROOT / "config" / "night_signal_guardrails.json"
POLICY_PATH = ROOT / "details" / "policy.html"
AUDIT_PATHS = [
    ROOT / "scripts" / "coverage_audit.py",
    ROOT / "scripts" / "quality_gate.py",
    ROOT / "scripts" / "publication_audit.py",
    ROOT / "scripts" / "current_issue_audit.py",
    ROOT / "scripts" / "sync_site.py",
    ROOT / "scripts" / "render_detail.py",
    ROOT / "scripts" / "night_signal_state.py",
    ROOT / "scripts" / "night_signal_collect.py",
    ROOT / "scripts" / "night_signal_synthesize.py",
    ROOT / "scripts" / "night_signal_publish.py",
]
SIMULATION_PATH = ROOT / "scripts" / "simulate_quality_gate_failures.py"
WORKFLOW_PATHS = list((ROOT / ".github" / "workflows").glob("*.yml"))


def fail(message: str) -> None:
    print(f"GUARDRAIL INVENTORY FAILED: {message}", file=sys.stderr)
    raise SystemExit(1)


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        fail(f"missing file: {path.relative_to(ROOT)}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        fail(f"invalid JSON in {path.relative_to(ROOT)}: {exc}")
    if not isinstance(value, dict):
        fail(f"{path.relative_to(ROOT)} must contain a JSON object")
    return value


def read_all(paths: list[Path]) -> str:
    chunks = []
    for path in paths:
        if not path.exists():
            fail(f"missing file: {path.relative_to(ROOT)}")
        chunks.append(path.read_text(encoding="utf-8"))
    return "\n".join(chunks)


def require_terms(label: str, guard_id: str, text: str, terms: list[Any]) -> None:
    if not isinstance(terms, list):
        fail(f"{guard_id} {label} must be a list")
    missing = [term for term in terms if not isinstance(term, str) or term not in text]
    if missing:
        fail(f"{guard_id} missing {label}: " + ", ".join(str(term) for term in missing))


def forbid_terms(label: str, guard_id: str, text: str, terms: list[Any]) -> None:
    if not isinstance(terms, list):
        fail(f"{guard_id} {label} must be a list")
    present = [term for term in terms if isinstance(term, str) and term in text]
    invalid = [term for term in terms if not isinstance(term, str)]
    if invalid:
        fail(f"{guard_id} {label} contains invalid terms: " + ", ".join(str(term) for term in invalid))
    if present:
        fail(f"{guard_id} forbidden {label}: " + ", ".join(present))


def category_by_label(contract: dict[str, Any], label: str) -> dict[str, Any]:
    categories = contract.get("categories")
    if not isinstance(categories, list):
        fail("coverage contract missing categories")
    for category in categories:
        if isinstance(category, dict) and category.get("label") == label:
            return category
    fail(f"guardrail category is not configured: {label}")


def ids_in(category: dict[str, Any], key: str, guard_id: str) -> set[str]:
    values = category.get(key)
    if not isinstance(values, list):
        fail(f"{guard_id} category {key} must be a list")
    ids = {item.get("id") for item in values if isinstance(item, dict)}
    if any(not isinstance(item_id, str) for item_id in ids):
        fail(f"{guard_id} category {key} contains invalid ids")
    return {item_id for item_id in ids if isinstance(item_id, str)}


def category_terms(category: dict[str, Any]) -> str:
    terms: list[str] = []
    for key in ("axes", "watch_topics"):
        for item in category.get(key, []):
            if not isinstance(item, dict):
                continue
            item_terms = item.get("terms", [])
            if isinstance(item_terms, list):
                terms.extend(term for term in item_terms if isinstance(term, str))
    return "\n".join(terms)


def categories_by_class(contract: dict[str, Any], class_name: str) -> list[dict[str, Any]]:
    categories = contract.get("categories")
    if not isinstance(categories, list):
        fail("coverage contract missing categories")
    matched = []
    for category in categories:
        if not isinstance(category, dict):
            continue
        classes = category.get("risk_classes", [])
        if isinstance(classes, list) and class_name in classes:
            matched.append(category)
    if not matched:
        fail(f"guardrail category_class has no categories: {class_name}")
    return matched


def validate_category_requirements(category: dict[str, Any], guard_id: str, guard: dict[str, Any]) -> None:
    label = category.get("label", "<unknown>")
    required_axes = guard.get("required_axes", [])
    required_topics = guard.get("required_watch_topics", [])
    required_any_axes = guard.get("required_any_axes", [])
    required_any_topics = guard.get("required_any_watch_topics", [])
    required_terms = guard.get("required_terms", [])
    for key, value in [
        ("required_axes", required_axes),
        ("required_watch_topics", required_topics),
        ("required_any_axes", required_any_axes),
        ("required_any_watch_topics", required_any_topics),
    ]:
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            fail(f"{guard_id} {key} must be a string list")

    axis_ids = ids_in(category, "axes", guard_id)
    topic_ids = ids_in(category, "watch_topics", guard_id)
    missing_axes = sorted(set(required_axes) - axis_ids)
    if missing_axes:
        fail(f"{guard_id} {label} missing category axes: " + ", ".join(missing_axes))
    missing_topics = sorted(set(required_topics) - topic_ids)
    if missing_topics:
        fail(f"{guard_id} {label} missing watch topics: " + ", ".join(missing_topics))
    if required_any_axes and not set(required_any_axes).intersection(axis_ids):
        fail(f"{guard_id} {label} missing any category axis: " + ", ".join(required_any_axes))
    if required_any_topics and not set(required_any_topics).intersection(topic_ids):
        fail(f"{guard_id} {label} missing any watch topic: " + ", ".join(required_any_topics))
    require_terms(f"{label} category terms", guard_id, category_terms(category), required_terms)


def validate_contract_values(contract: dict[str, Any], guard_id: str, expected: dict[str, Any]) -> None:
    if not isinstance(expected, dict):
        fail(f"{guard_id} contract must be an object")
    for key, value in expected.items():
        if contract.get(key) != value:
            fail(f"{guard_id} contract mismatch for {key}: {contract.get(key)!r} != {value!r}")


def validate_guard(contract: dict[str, Any], guard: dict[str, Any], texts: dict[str, str]) -> None:
    guard_id = guard.get("id")
    if not isinstance(guard_id, str) or not guard_id:
        fail("guard missing id")
    if not isinstance(guard.get("description"), str) or len(guard["description"]) < 20:
        fail(f"{guard_id} needs a concrete description")

    if "contract" in guard:
        validate_contract_values(contract, guard_id, guard["contract"])

    category_label = guard.get("category")
    if category_label is not None:
        if not isinstance(category_label, str):
            fail(f"{guard_id} category must be a string")
        validate_category_requirements(category_by_label(contract, category_label), guard_id, guard)

    category_class = guard.get("category_class")
    if category_class is not None:
        if not isinstance(category_class, str):
            fail(f"{guard_id} category_class must be a string")
        for category in categories_by_class(contract, category_class):
            validate_category_requirements(category, guard_id, guard)

    require_terms("policy terms", guard_id, texts["policy"], guard.get("required_policy_terms", []))
    require_terms("audit terms", guard_id, texts["audit"], guard.get("required_audit_terms", []))
    require_terms("simulation terms", guard_id, texts["simulation"], guard.get("required_simulation_terms", []))
    require_terms("workflow terms", guard_id, texts["workflow"], guard.get("required_workflow_terms", []))
    forbid_terms("workflow terms", guard_id, texts["workflow"], guard.get("forbidden_workflow_terms", []))


def main() -> int:
    contract = load_json(COVERAGE_PATH)
    inventory = load_json(GUARDRAILS_PATH)
    guards = inventory.get("guards")
    if not isinstance(guards, list) or not guards:
        fail("guardrail inventory must define at least one guard")
    guard_ids = [guard.get("id") for guard in guards if isinstance(guard, dict)]
    if len(guard_ids) != len(set(guard_ids)):
        fail("guardrail ids must be unique")

    texts = {
        "policy": POLICY_PATH.read_text(encoding="utf-8"),
        "audit": read_all(AUDIT_PATHS),
        "simulation": SIMULATION_PATH.read_text(encoding="utf-8"),
        "workflow": read_all(WORKFLOW_PATHS),
    }
    for guard in guards:
        if not isinstance(guard, dict):
            fail("each guard must be an object")
        validate_guard(contract, guard, texts)
    print(f"GUARDRAIL INVENTORY PASSED: {len(guards)} guards")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
