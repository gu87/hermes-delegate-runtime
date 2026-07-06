#!/usr/bin/env python3
"""Pure result post-processing helpers for delegate runtime hosts."""

from __future__ import annotations

from typing import Any, Dict, Iterable, Optional, Tuple


def strip_child_entry_metadata(
    entry: Dict[str, Any],
) -> Tuple[Dict[str, Any], Optional[str], float]:
    cleaned = dict(entry)
    child_role = cleaned.pop("_child_role", None)
    raw_child_cost = cleaned.pop("_child_cost_usd", 0.0)
    try:
        child_cost = float(raw_child_cost) if raw_child_cost else 0.0
    except (TypeError, ValueError):
        child_cost = 0.0
    return cleaned, child_role if isinstance(child_role, str) else None, child_cost


def sum_child_costs(costs: Iterable[Any]) -> float:
    total = 0.0
    for value in costs:
        try:
            total += float(value) if value else 0.0
        except (TypeError, ValueError):
            continue
    return total


def build_subagent_stop_payload(
    *,
    parent_session_id: Optional[str],
    parent_turn_id: str,
    child_session_id: Optional[str],
    child_role: Optional[str],
    child_summary: Any,
    child_status: Any,
    duration_seconds: Any,
) -> Dict[str, Any]:
    try:
        duration_ms = int((duration_seconds or 0) * 1000)
    except (TypeError, ValueError):
        duration_ms = 0
    return {
        "parent_session_id": parent_session_id,
        "parent_turn_id": parent_turn_id,
        "child_session_id": child_session_id,
        "child_role": child_role,
        "child_summary": child_summary,
        "child_status": child_status,
        "duration_ms": duration_ms,
    }
