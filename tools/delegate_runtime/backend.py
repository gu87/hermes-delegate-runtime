#!/usr/bin/env python3
"""Minimal backend boundary for delegate orchestration."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
import os
import time
from typing import Any, Callable, Dict, List, Optional, Protocol
from urllib import error as urllib_error
from urllib import request as urllib_request


class BackendError(RuntimeError):
    """Raised when a backend cannot satisfy the request."""


@dataclass
class TaskSpec:
    agent_id: str
    goal: str
    context: Optional[str] = None
    toolsets: List[str] = field(default_factory=list)
    blocked_tools: List[str] = field(default_factory=list)
    isolation: Optional[str] = None
    max_iterations: Optional[int] = None
    run_in_background: bool = False


@dataclass
class SubagentState:
    subagent_id: str
    agent_id: str
    status: str
    started_at: float
    ended_at: Optional[float] = None
    error: Optional[str] = None


@dataclass
class SubagentResult:
    subagent_id: str
    status: str
    output: str
    messages: List[dict] = field(default_factory=list)
    usage: Optional[dict] = None
    duration_seconds: float = 0.0


@dataclass
class CancelResult:
    subagent_id: str
    cancelled: bool
    note: Optional[str] = None


@dataclass
class RunningSubagent:
    subagent_id: str
    agent_id: str
    started_at: float
    goal: str
    depth: int = 0


class BackendProtocol(Protocol):
    @property
    def dispatches_remotely(self) -> bool: ...

    def dispatch(self, spec: TaskSpec) -> str: ...

    def get_status(self, subagent_id: str) -> Optional[SubagentState]: ...

    def get_result(self, subagent_id: str) -> Optional[SubagentResult]: ...

    def cancel(self, subagent_id: str) -> CancelResult: ...

    def list_running(self) -> List[RunningSubagent]: ...


class LocalBackend:
    """1:1 wrapper around delegate_tool callables supplied by the caller."""

    def __init__(
        self,
        *,
        dispatch_fn: Optional[Callable[[TaskSpec], str]] = None,
        get_status_fn: Optional[Callable[[str], Optional[SubagentState]]] = None,
        get_result_fn: Optional[Callable[[str], Optional[SubagentResult]]] = None,
        cancel_fn: Optional[Callable[[str], CancelResult]] = None,
        list_running_fn: Optional[Callable[[], List[RunningSubagent]]] = None,
    ) -> None:
        self._dispatch_fn = dispatch_fn
        self._get_status_fn = get_status_fn
        self._get_result_fn = get_result_fn
        self._cancel_fn = cancel_fn
        self._list_running_fn = list_running_fn

    @property
    def dispatches_remotely(self) -> bool:
        return False

    def dispatch(self, spec: TaskSpec) -> str:
        if self._dispatch_fn is None:
            raise BackendError("LocalBackend dispatch is not wired")
        return self._dispatch_fn(spec)

    def get_status(self, subagent_id: str) -> Optional[SubagentState]:
        if self._get_status_fn is None:
            return None
        return self._get_status_fn(subagent_id)

    def get_result(self, subagent_id: str) -> Optional[SubagentResult]:
        if self._get_result_fn is None:
            return None
        return self._get_result_fn(subagent_id)

    def cancel(self, subagent_id: str) -> CancelResult:
        if self._cancel_fn is None:
            return CancelResult(subagent_id, False, "not wired")
        return self._cancel_fn(subagent_id)

    def list_running(self) -> List[RunningSubagent]:
        if self._list_running_fn is None:
            return []
        return self._list_running_fn()


class DaedalusBackend:
    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = 10.0,
        opener: Any = None,
    ) -> None:
        self.base_url = (base_url or os.environ.get("HERMES_DAEDALUS_URL") or "http://127.0.0.1:7878").rstrip("/")
        self.timeout = timeout
        self._opener = opener or urllib_request

    @property
    def dispatches_remotely(self) -> bool:
        return True

    def dispatch(self, spec: TaskSpec) -> str:
        data = self._request("POST", "/api/tasks", asdict(spec))
        run_id = data.get("run_id") or data.get("task_id") or data.get("id")
        if not run_id:
            raise BackendError("Daedalus dispatch response did not include run_id")
        return str(run_id)

    def get_status(self, subagent_id: str) -> Optional[SubagentState]:
        data = self._get_task(subagent_id)
        if data is None:
            return None
        return self._state_from_task(data, subagent_id)

    def get_result(self, subagent_id: str) -> Optional[SubagentResult]:
        data = self._get_task(subagent_id)
        if data is None:
            return None
        status = _map_status(data.get("status") or data.get("state"))
        if status == "running":
            return None
        return SubagentResult(
            subagent_id=str(data.get("run_id") or data.get("task_id") or data.get("id") or subagent_id),
            status=status,
            output=_extract_output(data),
            messages=_extract_messages(data),
            usage=data.get("usage") if isinstance(data.get("usage"), dict) else None,
            duration_seconds=_duration_seconds(data),
        )

    def cancel(self, subagent_id: str) -> CancelResult:
        return CancelResult(
            subagent_id=subagent_id,
            cancelled=False,
            note="unsupported: Daedalus cancel endpoint is not available",
        )

    def list_running(self) -> List[RunningSubagent]:
        data = self._request("GET", "/api/tasks?status=running")
        tasks = data.get("tasks", data if isinstance(data, list) else [])
        if not isinstance(tasks, list):
            return []
        return [self._running_from_task(t) for t in tasks if isinstance(t, dict)]

    def _get_task(self, subagent_id: str) -> Optional[Dict[str, Any]]:
        try:
            return self._request("GET", f"/api/tasks/{subagent_id}")
        except urllib_error.HTTPError as exc:
            if exc.code == 404:
                return None
            raise

    def _request(
        self,
        method: str,
        path: str,
        payload: Optional[Dict[str, Any]] = None,
    ) -> Any:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        req = urllib_request.Request(
            self.base_url + path,
            data=body,
            method=method,
            headers={"Accept": "application/json", "Content-Type": "application/json"},
        )
        with self._opener.urlopen(req, timeout=self.timeout) as resp:
            raw = resp.read()
        if not raw:
            return {}
        return json.loads(raw.decode("utf-8"))

    def _state_from_task(self, data: Dict[str, Any], fallback_id: str) -> SubagentState:
        return SubagentState(
            subagent_id=str(data.get("run_id") or data.get("task_id") or data.get("id") or fallback_id),
            agent_id=str(data.get("agent_id") or data.get("agent") or ""),
            status=_map_status(data.get("status") or data.get("state")),
            started_at=_float_or_default(data.get("started_at") or data.get("created_at"), 0.0),
            ended_at=_float_or_none(data.get("ended_at") or data.get("completed_at")),
            error=data.get("error") if isinstance(data.get("error"), str) else None,
        )

    def _running_from_task(self, data: Dict[str, Any]) -> RunningSubagent:
        return RunningSubagent(
            subagent_id=str(data.get("run_id") or data.get("task_id") or data.get("id") or ""),
            agent_id=str(data.get("agent_id") or data.get("agent") or ""),
            started_at=_float_or_default(data.get("started_at") or data.get("created_at"), 0.0),
            goal=str(data.get("goal") or data.get("task") or ""),
            depth=int(data.get("depth") or 0),
        )


def select_backend(name: Optional[str] = None, **kwargs: Any) -> BackendProtocol:
    backend = (name or os.environ.get("HERMES_DELEGATE_BACKEND") or "local").strip().lower()
    if backend in ("", "local"):
        return LocalBackend(**kwargs)
    if backend == "daedalus":
        return DaedalusBackend(**kwargs)
    raise BackendError(f"Unsupported HERMES_DELEGATE_BACKEND={backend!r}")


def get_backend_from_env(
    local_backend_factory: Callable[[], BackendProtocol],
    daedalus_base_url: str = "http://127.0.0.1:7878",
) -> BackendProtocol:
    backend = os.environ.get("HERMES_DELEGATE_BACKEND", "local").strip().lower()
    if backend in ("", "local"):
        return local_backend_factory()
    if backend == "daedalus":
        return DaedalusBackend(daedalus_base_url)
    raise BackendError(f"Unsupported HERMES_DELEGATE_BACKEND={backend!r}")


def _map_status(status: Any) -> str:
    value = str(status or "running").lower()
    if value in {"done", "completed", "complete", "success", "succeeded"}:
        return "done"
    if value in {"timeout", "timed_out"}:
        return "timeout"
    if value in {"cancelled", "canceled"}:
        return "cancelled"
    if value in {"error", "failed", "failure"}:
        return "error"
    return "running"


def _extract_output(data: Dict[str, Any]) -> str:
    for key in ("output", "result", "final_response", "summary"):
        value = data.get(key)
        if isinstance(value, str):
            return value
    outbox = data.get("outbox") or data.get("outbox_json")
    if isinstance(outbox, str):
        # daedalus v0.3+: outbox_json 是 JSON 字符串，取 summary
        try:
            parsed = json.loads(outbox)
            if isinstance(parsed, dict) and parsed.get("summary"):
                return str(parsed["summary"])
        except (json.JSONDecodeError, ValueError):
            pass
        return outbox
    if isinstance(outbox, dict):
        return str(outbox.get("summary") or outbox.get("content") or "")
    if isinstance(outbox, list):
        return "\n".join(str(item.get("content") if isinstance(item, dict) else item) for item in outbox)
    return ""


def _extract_messages(data: Dict[str, Any]) -> List[dict]:
    messages = data.get("messages") or data.get("outbox") or data.get("outbox_json") or []
    return [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else []


def _duration_seconds(data: Dict[str, Any]) -> float:
    explicit = _float_or_none(data.get("duration_seconds"))
    if explicit is not None:
        return explicit
    started = _float_or_none(data.get("started_at") or data.get("created_at"))
    ended = _float_or_none(data.get("ended_at") or data.get("completed_at"))
    if started is not None and ended is not None:
        return max(0.0, ended - started)
    return 0.0


def _float_or_default(value: Any, default: float) -> float:
    parsed = _float_or_none(value)
    return default if parsed is None else parsed


def _float_or_none(value: Any) -> Optional[float]:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return time.time() if value == "now" else None
