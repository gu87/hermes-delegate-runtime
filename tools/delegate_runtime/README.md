# delegate_runtime

`tools.delegate_runtime` is a reusable module v0 for hosts that want local or
remote delegate orchestration primitives without importing the Hermes
`delegate_tool` host adapter.

## v0 public API

- Backend boundary:
  `TaskSpec`, `SubagentState`, `SubagentResult`, `CancelResult`,
  `RunningSubagent`, `BackendProtocol`, `LocalBackend`,
  `DaedalusBackend`, `get_backend_from_env`, `select_backend`
- Runtime wiring:
  `LocalBackendBindings`, `build_task_specs`, `get_runtime_backend`,
  `get_delegate_status`, `get_delegate_result`, `list_running_subagents`,
  `cancel_subagent`, `dispatch_remote_tasks`
- Execution helpers:
  `ExecutionTask`, `ExecutionUnit`, `build_execution_tasks`,
  `run_execution_units`, `build_execution_entry`, `build_error_entry`,
  `build_interrupted_entry`, `build_execution_result_payload`,
  `build_background_dispatch_payload`, `sort_results_by_task_index`,
  `total_duration_seconds`
- Active registry:
  `ActiveSubagentRegistry`, `to_subagent_state`, `to_running_subagent`
- Result postprocess:
  `strip_child_entry_metadata`, `sum_child_costs`,
  `build_subagent_stop_payload`

## What a host injects

- Local backend callbacks via `LocalBackendBindings`
- Task role normalization for `build_task_specs`
- The actual unit runner passed into `run_execution_units`
- Any host-owned storage, hook invocation, memory integration, and cost writes

## Not in v0

This module does not include Hermes child construction, session handling,
credential resolution, toolset inheritance, hook execution, or background
delivery/re-entry. Those stay in the host adapter.
