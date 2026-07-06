#!/usr/bin/env python3
"""Reusable delegate runtime helpers shared by host adapters."""

from __future__ import annotations

from dataclasses import dataclass
import os
import time
from typing import Callable, Dict, List, Optional

from tools.delegate_runtime.backend import (
    BackendProtocol,
    CancelResult,
    LocalBackend,
    RunningSubagent,
    SubagentResult,
    SubagentState,
    TaskSpec,
    get_backend_from_env,
)


@dataclass
class LocalBackendBindings:
    dispatch_fn: Callable[[TaskSpec], str]
    get_status_fn: Callable[[str], Optional[SubagentState]]
    get_result_fn: Callable[[str], Optional[SubagentResult]]
    cancel_fn: Callable[[str], CancelResult]
    list_running_fn: Callable[[], List[RunningSubagent]]


def get_runtime_backend(
    bindings: LocalBackendBindings,
    *,
    daedalus_base_url: Optional[str] = None,
) -> BackendProtocol:
    return get_backend_from_env(
        lambda: LocalBackend(
            dispatch_fn=bindings.dispatch_fn,
            get_status_fn=bindings.get_status_fn,
            get_result_fn=bindings.get_result_fn,
            cancel_fn=bindings.cancel_fn,
            list_running_fn=bindings.list_running_fn,
        ),
        daedalus_base_url=(
            daedalus_base_url
            or os.environ.get("HERMES_DAEDALUS_URL", "http://127.0.0.1:7878")
        ),
    )


def get_delegate_status(
    bindings: LocalBackendBindings,
    subagent_id: str,
    *,
    daedalus_base_url: Optional[str] = None,
) -> Optional[SubagentState]:
    return get_runtime_backend(
        bindings, daedalus_base_url=daedalus_base_url
    ).get_status(subagent_id)


def get_delegate_result(
    bindings: LocalBackendBindings,
    subagent_id: str,
    *,
    daedalus_base_url: Optional[str] = None,
) -> Optional[SubagentResult]:
    return get_runtime_backend(
        bindings, daedalus_base_url=daedalus_base_url
    ).get_result(subagent_id)


def list_running_subagents(
    bindings: LocalBackendBindings,
    *,
    daedalus_base_url: Optional[str] = None,
) -> List[RunningSubagent]:
    return get_runtime_backend(
        bindings, daedalus_base_url=daedalus_base_url
    ).list_running()


def cancel_subagent(
    bindings: LocalBackendBindings,
    subagent_id: str,
    *,
    daedalus_base_url: Optional[str] = None,
) -> CancelResult:
    return get_runtime_backend(
        bindings, daedalus_base_url=daedalus_base_url
    ).cancel(subagent_id)


def build_task_specs(
    task_list: List[Dict[str, object]],
    *,
    top_role: str,
    toolsets: Optional[List[str]],
    blocked_tools: List[str],
    max_iterations: Optional[int],
    run_in_background: bool,
    normalize_role: Callable[[Optional[str]], str],
) -> List[TaskSpec]:
    specs: List[TaskSpec] = []
    for task in task_list:
        effective_role = normalize_role(task.get("role") or top_role)
        specs.append(
            TaskSpec(
                agent_id=effective_role,
                goal=str(task["goal"]),
                context=task.get("context")
                if isinstance(task.get("context"), str)
                else None,
                toolsets=list(task.get("toolsets") or toolsets or []),
                blocked_tools=list(blocked_tools),
                max_iterations=max_iterations,
                run_in_background=run_in_background,
            )
        )
    return specs


def dispatch_remote_tasks(
    backend: BackendProtocol,
    specs: List[TaskSpec],
    *,
    started_at: Optional[float] = None,
) -> Optional[Dict[str, object]]:
    if not backend.dispatches_remotely:
        return None
    dispatched = []
    for index, spec in enumerate(specs):
        dispatched.append(
            {
                "task_index": index,
                "subagent_id": backend.dispatch(spec),
                "status": "dispatched",
                "summary": None,
            }
        )
    base = started_at if started_at is not None else time.monotonic()
    return {
        "results": dispatched,
        "backend": "daedalus",
        "total_duration_seconds": round(time.monotonic() - base, 2),
    }
