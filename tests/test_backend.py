import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tools.delegate_runtime.backend import (
    DaedalusBackend,
    LocalBackend,
    TaskSpec,
    get_backend_from_env,
)
from tools.delegate_runtime.execution import (
    ExecutionTask,
    build_background_dispatch_payload,
    build_execution_entry,
    build_execution_result_payload,
    build_execution_tasks,
    build_interrupted_entry,
)
from tools.orchestrator_backend import TaskSpec as CompatTaskSpec


class _FakeDaedalusHandler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, format, *args):
        return

    def _write_json(self, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(length).decode("utf-8"))
        self.requests.append(("POST", self.path, body))
        if self.path == "/api/tasks":
            self._write_json({"run_id": "run-1"})
            return
        self.send_error(404)

    def do_GET(self):
        self.requests.append(("GET", self.path, None))
        if self.path == "/api/tasks/run-1":
            self._write_json(
                {
                    "run_id": "run-1",
                    "agent_id": "codex",
                    "status": "completed",
                    "started_at": 10,
                    "ended_at": 15,
                    "output": "done",
                    "messages": [{"role": "assistant", "content": "done"}],
                }
            )
            return
        if self.path == "/api/tasks?status=running":
            self._write_json(
                {
                    "tasks": [
                        {
                            "run_id": "run-2",
                            "agent_id": "claude",
                            "status": "running",
                            "started_at": 20,
                            "goal": "work",
                            "depth": 1,
                        }
                    ]
                }
            )
            return
        self.send_error(404)


def test_compat_task_spec_reexport():
    assert CompatTaskSpec is TaskSpec


def test_runtime_imports_and_payload_helpers():
    tasks = build_execution_tasks([{"goal": "ship it"}, {"goal": "second"}])
    entry = build_execution_entry(task_index=0, status="completed", summary="done")
    interrupted = build_interrupted_entry(task_index=1)
    payload = build_execution_result_payload(
        [{"task_index": 1}, {"task_index": 0}],
        started_at=10.0,
        finished_at=12.5,
    )
    background = build_background_dispatch_payload("dg-1", ["ship it"])

    assert tasks == [
        ExecutionTask(task_index=0, goal="ship it"),
        ExecutionTask(task_index=1, goal="second"),
    ]
    assert entry["summary"] == "done"
    assert interrupted["status"] == "interrupted"
    assert payload["results"][0]["task_index"] == 0
    assert payload["total_duration_seconds"] == 2.5
    assert background["delegation_id"] == "dg-1"


def test_get_backend_from_env_defaults_to_local():
    old = os.environ.pop("HERMES_DELEGATE_BACKEND", None)
    called = []
    try:
        backend = get_backend_from_env(lambda: called.append(True) or LocalBackend())
    finally:
        if old is not None:
            os.environ["HERMES_DELEGATE_BACKEND"] = old
    assert isinstance(backend, LocalBackend)
    assert called == [True]
    assert backend.dispatches_remotely is False


def test_daedalus_backend_roundtrip():
    _FakeDaedalusHandler.requests = []
    server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeDaedalusHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    host, port = server.server_address
    base_url = f"http://{host}:{port}"
    try:
        backend = DaedalusBackend(base_url)
        run_id = backend.dispatch(
            TaskSpec(
                agent_id="codex",
                goal="ship it",
                context="ctx",
                toolsets=["terminal"],
                blocked_tools=["memory"],
                max_iterations=5,
                run_in_background=True,
            )
        )
        state = backend.get_status("run-1")
        result = backend.get_result("run-1")
        running = backend.list_running()
        cancelled = backend.cancel("run-1")
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()

    assert run_id == "run-1"
    assert state.subagent_id == "run-1"
    assert result.output == "done"
    assert running[0].subagent_id == "run-2"
    assert cancelled.cancelled is False
