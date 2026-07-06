import threading
import unittest
from concurrent.futures import Future

from tools.delegate_runtime import (
    ActiveSubagentRegistry,
    CancelResult,
    ExecutionTask,
    ExecutionUnit,
    LocalBackendBindings,
    RunningSubagent,
    SubagentResult,
    SubagentState,
    build_error_entry,
    build_execution_entry,
    build_interrupted_entry,
    build_subagent_stop_payload,
    build_task_specs,
    get_runtime_backend,
    run_execution_units,
    strip_child_entry_metadata,
    sum_child_costs,
)


class _FakeHost:
    def __init__(self) -> None:
        self.registry = ActiveSubagentRegistry()
        self._lock = threading.Lock()
        self._counter = 0
        self._results = {}
        self._backend = get_runtime_backend(
            LocalBackendBindings(
                dispatch_fn=self.dispatch,
                get_status_fn=self.get_status,
                get_result_fn=self.get_result,
                cancel_fn=self.cancel,
                list_running_fn=self.list_running,
            )
        )

    @property
    def backend(self):
        return self._backend

    def dispatch(self, spec) -> str:
        with self._lock:
            self._counter += 1
            subagent_id = f"fake-{self._counter}"
        self.registry.register(
            {
                "subagent_id": subagent_id,
                "parent_id": spec.agent_id,
                "goal": spec.goal,
                "depth": 0,
                "started_at": float(self._counter),
                "status": "running",
            }
        )
        self._results[subagent_id] = SubagentResult(
            subagent_id=subagent_id,
            status="done",
            output=f"finished: {spec.goal}",
            messages=[{"role": "assistant", "content": spec.goal}],
            usage={"tokens": len(spec.goal)},
            duration_seconds=0.5,
        )
        return subagent_id

    def get_status(self, subagent_id: str):
        record = self.registry.get(subagent_id)
        if record is None:
            return None
        return SubagentState(
            subagent_id=subagent_id,
            agent_id=str(record.get("parent_id") or ""),
            status=str(record.get("status") or "running"),
            started_at=float(record.get("started_at") or 0.0),
        )

    def get_result(self, subagent_id: str):
        return self._results.get(subagent_id)

    def cancel(self, subagent_id: str):
        record = self.registry.get(subagent_id)
        if record is None:
            return CancelResult(subagent_id=subagent_id, cancelled=False, note="not found")
        self.registry.update(subagent_id, status="cancelled")
        return CancelResult(subagent_id=subagent_id, cancelled=True)

    def list_running(self):
        running = []
        for record in self.registry.snapshot():
            if record.get("status") != "running":
                continue
            running.append(
                RunningSubagent(
                    subagent_id=str(record["subagent_id"]),
                    agent_id=str(record.get("parent_id") or ""),
                    started_at=float(record.get("started_at") or 0.0),
                    goal=str(record.get("goal") or ""),
                    depth=int(record.get("depth") or 0),
                )
            )
        return running


class TestDelegateRuntimeFakeHost(unittest.TestCase):
    def test_fake_host_runs_runtime_v0_main_path(self):
        host = _FakeHost()
        specs = build_task_specs(
            [{"goal": "ship it", "context": "ctx"}],
            top_role="leaf",
            toolsets=["terminal"],
            blocked_tools=["memory"],
            max_iterations=3,
            run_in_background=False,
            normalize_role=lambda role: role or "leaf",
        )

        subagent_id = host.backend.dispatch(specs[0])
        state = host.backend.get_status(subagent_id)
        result = host.backend.get_result(subagent_id)
        running = host.backend.list_running()
        cancelled = host.backend.cancel(subagent_id)
        cancelled_state = host.backend.get_status(subagent_id)

        self.assertEqual(specs[0].goal, "ship it")
        self.assertEqual(subagent_id, "fake-1")
        self.assertEqual(state.status, "running")
        self.assertEqual(result.output, "finished: ship it")
        self.assertEqual(running[0].goal, "ship it")
        self.assertTrue(cancelled.cancelled)
        self.assertEqual(cancelled_state.status, "cancelled")

    def test_fake_host_execution_and_postprocess_helpers(self):
        single = run_execution_units(
            [
                ExecutionUnit(
                    task=ExecutionTask(task_index=0, goal="single"),
                    payload={"summary": "done"},
                )
            ],
            run_unit=lambda unit: build_execution_entry(
                task_index=unit.task.task_index,
                status="completed",
                summary=unit.payload["summary"],
                api_calls=1,
                duration_seconds=0.25,
                extra={"_child_role": "leaf", "_child_cost_usd": 1.5},
            ),
        )

        future_a = Future()
        future_b = Future()
        future_a.set_result(
            build_execution_entry(
                task_index=0,
                status="completed",
                summary="batch-a",
                extra={"_child_role": "leaf", "_child_cost_usd": 0.5},
            )
        )
        future_b.set_exception(RuntimeError("boom"))
        batch = run_execution_units(
            [
                ExecutionUnit(ExecutionTask(task_index=0, goal="batch-a"), payload=None),
                ExecutionUnit(ExecutionTask(task_index=1, goal="batch-b"), payload=None),
                ExecutionUnit(ExecutionTask(task_index=2, goal="batch-c"), payload=None),
            ],
            run_unit=lambda _unit: {},
            submit_unit=lambda unit: {
                0: future_a,
                1: future_b,
                2: Future(),
            }[unit.task.task_index],
            resolve_completed=lambda unit, future: future.result()
            if future.exception() is None
            else build_error_entry(
                task_index=unit.task.task_index,
                error=str(future.exception()),
                extra={"_child_role": "worker"},
            ),
            is_interrupted=lambda: True,
            make_interrupted_entry=lambda unit, _future: build_interrupted_entry(
                task_index=unit.task.task_index,
                extra={"_child_role": "worker", "_child_cost_usd": 0.25},
            ),
        )

        cleaned_single, child_role, child_cost = strip_child_entry_metadata(single[0])
        cleaned_batch = [strip_child_entry_metadata(entry) for entry in batch]
        payload = build_subagent_stop_payload(
            parent_session_id="parent-1",
            parent_turn_id="turn-1",
            child_session_id="child-1",
            child_role=child_role,
            child_summary=cleaned_single.get("summary"),
            child_status=cleaned_single.get("status"),
            duration_seconds=cleaned_single.get("duration_seconds"),
        )

        self.assertEqual(cleaned_single["status"], "completed")
        self.assertEqual(child_role, "leaf")
        self.assertEqual(child_cost, 1.5)
        self.assertEqual([entry[0]["status"] for entry in cleaned_batch], ["completed", "error", "interrupted"])
        self.assertEqual(sum_child_costs([child_cost] + [entry[2] for entry in cleaned_batch]), 2.25)
        self.assertEqual(payload["duration_ms"], 250)
        self.assertEqual(payload["child_role"], "leaf")


if __name__ == "__main__":
    unittest.main()
