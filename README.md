# Hermes Delegate Runtime

Extracted Python runtime core for delegate orchestration.

Included:
- `tools/delegate_runtime/backend.py`
- `tools/delegate_runtime/runtime.py`
- `tools/delegate_runtime/execution.py`
- `tools/delegate_runtime/registry.py`
- `tools/delegate_runtime/postprocess.py`
- `tools/orchestrator_backend.py` compatibility shim

Not included:
- Hermes host adapter logic from `tools/delegate_tool.py`
- child-agent construction
- session, credential, toolset, hook, memory, and background delivery integration

This repo is the reusable runtime slice, not the full Hermes delegate host.
