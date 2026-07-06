import unittest

import tools.delegate_runtime as runtime


class TestDelegateRuntimePublicApi(unittest.TestCase):
    def test_v0_symbols_exist_on_package_surface(self):
        expected = [
            "TaskSpec",
            "SubagentState",
            "SubagentResult",
            "CancelResult",
            "RunningSubagent",
            "BackendProtocol",
            "LocalBackend",
            "DaedalusBackend",
            "get_backend_from_env",
            "select_backend",
            "LocalBackendBindings",
            "build_task_specs",
            "get_runtime_backend",
            "get_delegate_status",
            "get_delegate_result",
            "list_running_subagents",
            "cancel_subagent",
            "dispatch_remote_tasks",
            "ExecutionTask",
            "ExecutionUnit",
            "build_execution_entry",
            "build_error_entry",
            "build_interrupted_entry",
            "run_execution_units",
            "ActiveSubagentRegistry",
            "to_subagent_state",
            "to_running_subagent",
            "strip_child_entry_metadata",
            "sum_child_costs",
            "build_subagent_stop_payload",
        ]

        for name in expected:
            self.assertTrue(hasattr(runtime, name), name)

    def test_package_surface_is_callable_for_core_entry_points(self):
        self.assertTrue(callable(runtime.get_backend_from_env))
        self.assertTrue(callable(runtime.get_runtime_backend))
        self.assertTrue(callable(runtime.build_task_specs))
        self.assertTrue(callable(runtime.run_execution_units))
        self.assertTrue(callable(runtime.strip_child_entry_metadata))
        self.assertTrue(callable(runtime.sum_child_costs))
        self.assertTrue(callable(runtime.build_subagent_stop_payload))


if __name__ == "__main__":
    unittest.main()
