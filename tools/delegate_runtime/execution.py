#!/usr/bin/env python3
"""Pure execution-plan helpers for delegate runtime hosts."""

from __future__ import annotations

from concurrent.futures import FIRST_COMPLETED, Future, wait
from dataclasses import dataclass
import time
from typing import Any, Callable, Dict, List, Optional, Sequence


@dataclass(frozen=True)
class ExecutionTask:
    task_index: int
    goal: str

    @property
    def label(self) -> str:
        return self.goal[:40]


@dataclass(frozen=True)
class ExecutionUnit:
    task: ExecutionTask
    payload: Any


def build_execution_tasks(task_list: Sequence[Dict[str, Any]]) -> List[ExecutionTask]:
    return [
        ExecutionTask(task_index=index, goal=str(task["goal"]))
        for index, task in enumerate(task_list)
    ]


def sort_results_by_task_index(results: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(results, key=lambda entry: entry["task_index"])


def total_duration_seconds(
    started_at: float,
    *,
    finished_at: Optional[float] = None,
) -> float:
    end = time.monotonic() if finished_at is None else finished_at
    return round(end - started_at, 2)


def build_execution_result_payload(
    results: Sequence[Dict[str, Any]],
    *,
    started_at: float,
    finished_at: Optional[float] = None,
    sort_results: bool = True,
) -> Dict[str, Any]:
    ordered = (
        sort_results_by_task_index(results)
        if sort_results
        else list(results)
    )
    return {
        "results": ordered,
        "total_duration_seconds": total_duration_seconds(
            started_at, finished_at=finished_at
        ),
    }


def build_execution_entry(
    *,
    task_index: int,
    status: str,
    summary: Optional[str] = None,
    error: Optional[str] = None,
    api_calls: int = 0,
    duration_seconds: float = 0.0,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    entry: Dict[str, Any] = {
        "task_index": task_index,
        "status": status,
        "summary": summary,
        "api_calls": api_calls,
        "duration_seconds": duration_seconds,
    }
    if error is not None:
        entry["error"] = error
    if extra:
        entry.update(extra)
    return entry


def build_error_entry(
    *,
    task_index: int,
    error: str,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return build_execution_entry(
        task_index=task_index,
        status="error",
        summary=None,
        error=error,
        api_calls=0,
        duration_seconds=0.0,
        extra=extra,
    )


def build_interrupted_entry(
    *,
    task_index: int,
    error: str = "Parent agent interrupted — child did not finish in time",
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    return build_execution_entry(
        task_index=task_index,
        status="interrupted",
        summary=None,
        error=error,
        api_calls=0,
        duration_seconds=0.0,
        extra=extra,
    )


def build_background_dispatch_payload(
    delegation_id: str,
    goals: Sequence[str],
) -> Dict[str, Any]:
    count = len(goals)
    note = (
        "Subagent is running in the background. You and the user can "
        "keep working; its full result re-enters the conversation as a "
        "new message when it finishes. Do not wait or poll — just "
        "continue."
        if count == 1
        else
        f"{count} subagents are running in parallel in the background. You "
        f"and the user can keep working; they wait on each other and "
        f"their consolidated results re-enter the conversation as a "
        f"single message once ALL of them finish. Do not wait or poll "
        f"— just continue."
    )
    return {
        "status": "dispatched",
        "mode": "background",
        "count": count,
        "delegation_id": delegation_id,
        "goals": list(goals),
        "note": note,
    }


def run_execution_units(
    units: Sequence[ExecutionUnit],
    *,
    run_unit: Callable[[ExecutionUnit], Dict[str, Any]],
    submit_unit: Optional[Callable[[ExecutionUnit], Future]] = None,
    resolve_completed: Optional[
        Callable[[ExecutionUnit, Optional[Future]], Dict[str, Any]]
    ] = None,
    is_interrupted: Optional[Callable[[], bool]] = None,
    make_interrupted_entry: Optional[
        Callable[[ExecutionUnit, Optional[Future]], Dict[str, Any]]
    ] = None,
    on_result: Optional[Callable[[Dict[str, Any], int, int], None]] = None,
    poll_timeout: float = 0.5,
) -> List[Dict[str, Any]]:
    total = len(units)
    if total == 0:
        return []

    if total == 1 or submit_unit is None:
        entry = run_unit(units[0])
        if on_result is not None:
            on_result(entry, 1, total)
        return [entry]

    if resolve_completed is None:
        raise ValueError("resolve_completed is required for batch execution")
    if is_interrupted is None:
        raise ValueError("is_interrupted is required for batch execution")
    if make_interrupted_entry is None:
        raise ValueError("make_interrupted_entry is required for batch execution")

    futures = {submit_unit(unit): unit for unit in units}
    pending = set(futures.keys())
    results: List[Dict[str, Any]] = []
    completed = 0

    while pending:
        if is_interrupted():
            for future in pending:
                unit = futures[future]
                entry = (
                    resolve_completed(unit, future)
                    if future.done()
                    else make_interrupted_entry(unit, future)
                )
                results.append(entry)
                completed += 1
                if on_result is not None:
                    on_result(entry, completed, total)
            break

        done, pending = wait(
            pending, timeout=poll_timeout, return_when=FIRST_COMPLETED
        )
        for future in done:
            unit = futures[future]
            entry = resolve_completed(unit, future)
            results.append(entry)
            completed += 1
            if on_result is not None:
                on_result(entry, completed, total)

    return sort_results_by_task_index(results)
