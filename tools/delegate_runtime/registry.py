#!/usr/bin/env python3
"""Thread-safe active subagent registry for delegate runtime hosts."""

from __future__ import annotations

import threading
from typing import Any, Dict, Iterable, List, Optional

from tools.delegate_runtime.backend import RunningSubagent, SubagentState


class ActiveSubagentRegistry:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._records: Dict[str, Dict[str, Any]] = {}

    def register(self, record: Dict[str, Any]) -> None:
        sid = record.get("subagent_id")
        if not sid:
            return
        with self._lock:
            self._records[str(sid)] = dict(record)

    def unregister(self, subagent_id: str) -> None:
        with self._lock:
            self._records.pop(subagent_id, None)

    def get(
        self,
        subagent_id: str,
        *,
        exclude: Iterable[str] = (),
    ) -> Optional[Dict[str, Any]]:
        with self._lock:
            record = self._records.get(subagent_id)
            if record is None:
                return None
            excluded = set(exclude)
            return {k: v for k, v in record.items() if k not in excluded}

    def update(self, subagent_id: str, **fields: Any) -> bool:
        if not fields:
            return self.get(subagent_id) is not None
        with self._lock:
            record = self._records.get(subagent_id)
            if record is None:
                return False
            record.update(fields)
            return True

    def snapshot(
        self,
        *,
        exclude: Iterable[str] = ("agent",),
    ) -> List[Dict[str, Any]]:
        excluded = set(exclude)
        with self._lock:
            return [
                {k: v for k, v in record.items() if k not in excluded}
                for record in self._records.values()
            ]


def to_subagent_state(
    record: Optional[Dict[str, Any]],
    *,
    subagent_id: Optional[str] = None,
) -> Optional[SubagentState]:
    if not record:
        return None
    started_at = record.get("started_at")
    return SubagentState(
        subagent_id=str(record.get("subagent_id") or subagent_id or ""),
        agent_id=str(record.get("parent_id") or ""),
        status=str(record.get("status") or "running"),
        started_at=float(started_at) if isinstance(started_at, (int, float)) else 0.0,
    )


def to_running_subagent(record: Dict[str, Any]) -> RunningSubagent:
    started_at = record.get("started_at")
    depth = record.get("depth")
    return RunningSubagent(
        subagent_id=str(record.get("subagent_id") or ""),
        agent_id=str(record.get("parent_id") or ""),
        started_at=float(started_at) if isinstance(started_at, (int, float)) else 0.0,
        goal=str(record.get("goal") or ""),
        depth=int(depth) if isinstance(depth, int) else 0,
    )
