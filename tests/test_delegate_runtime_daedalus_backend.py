import json
import os
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import tools.delegate_runtime as runtime


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
                    "agent_id": "leaf",
                    "status": "completed",
                    "started_at": 10,
                    "ended_at": 15,
                    "output": "done",
                    "messages": [{"role": "assistant", "content": "done"}],
                    "usage": {"tokens": 3},
                }
            )
            return
        if self.path == "/api/tasks?status=running":
            self._write_json(
                {
                    "tasks": [
                        {
                            "run_id": "run-2",
                            "agent_id": "leaf",
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


class TestDelegateRuntimeDaedalusBackend(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _FakeDaedalusHandler.requests = []
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _FakeDaedalusHandler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        host, port = cls.server.server_address
        cls.base_url = f"http://{host}:{port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.thread.join(timeout=5)
        cls.server.server_close()

    def setUp(self):
        _FakeDaedalusHandler.requests = []
        self.old_backend = os.environ.get("HERMES_DELEGATE_BACKEND")
        self.old_url = os.environ.get("HERMES_DAEDALUS_URL")
        os.environ["HERMES_DELEGATE_BACKEND"] = "daedalus"
        os.environ["HERMES_DAEDALUS_URL"] = self.base_url
        self.bindings = runtime.LocalBackendBindings(
            dispatch_fn=lambda spec: spec.agent_id,
            get_status_fn=lambda _sid: None,
            get_result_fn=lambda _sid: None,
            cancel_fn=lambda sid: runtime.CancelResult(sid, False, "noop"),
            list_running_fn=lambda: [],
        )

    def tearDown(self):
        if self.old_backend is None:
            os.environ.pop("HERMES_DELEGATE_BACKEND", None)
        else:
            os.environ["HERMES_DELEGATE_BACKEND"] = self.old_backend
        if self.old_url is None:
            os.environ.pop("HERMES_DAEDALUS_URL", None)
        else:
            os.environ["HERMES_DAEDALUS_URL"] = self.old_url

    def test_runtime_package_drives_daedalus_fake_backend(self):
        specs = runtime.build_task_specs(
            [{"goal": "ship it", "context": "ctx"}],
            top_role="leaf",
            toolsets=["terminal"],
            blocked_tools=["memory"],
            max_iterations=5,
            run_in_background=False,
            normalize_role=lambda role: role or "leaf",
        )
        backend = runtime.get_runtime_backend(
            self.bindings,
            daedalus_base_url=self.base_url,
        )
        payload = runtime.dispatch_remote_tasks(
            backend,
            specs,
            started_at=10.0,
        )
        state = runtime.get_delegate_status(
            self.bindings,
            "run-1",
            daedalus_base_url=self.base_url,
        )
        result = runtime.get_delegate_result(
            self.bindings,
            "run-1",
            daedalus_base_url=self.base_url,
        )
        running = runtime.list_running_subagents(
            self.bindings,
            daedalus_base_url=self.base_url,
        )
        cancelled = runtime.cancel_subagent(
            self.bindings,
            "run-1",
            daedalus_base_url=self.base_url,
        )

        self.assertIsInstance(backend, runtime.DaedalusBackend)
        self.assertTrue(backend.dispatches_remotely)
        self.assertEqual(specs[0].goal, "ship it")
        self.assertEqual(payload["backend"], "daedalus")
        self.assertEqual(payload["results"][0]["subagent_id"], "run-1")
        self.assertEqual(state.subagent_id, "run-1")
        self.assertEqual(result.output, "done")
        self.assertEqual(running[0].subagent_id, "run-2")
        self.assertFalse(cancelled.cancelled)
        self.assertIn("unsupported", cancelled.note)
        self.assertEqual(
            [request[1] for request in _FakeDaedalusHandler.requests],
            [
                "/api/tasks",
                "/api/tasks/run-1",
                "/api/tasks/run-1",
                "/api/tasks?status=running",
            ],
        )


if __name__ == "__main__":
    unittest.main()
