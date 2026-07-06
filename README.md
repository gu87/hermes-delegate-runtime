# Hermes Delegate Runtime

Hermes Delegate Runtime 是从 Hermes 里拆出来的一层 **delegate 编排运行时**。

它解决的问题很窄：把“把任务交给子 agent 或远端调度器、记录状态、整理结果”这部分公共逻辑抽出来，让 Hermes、Daedalus 或其他宿主可以复用。

它现在是 **v0 可复用模块**，不是完整的独立 agent 产品。

## 它和 Hermes / Daedalus 的关系

```text
Hermes delegate_tool
  └─ 调用 delegate_runtime
       ├─ local backend: 继续在 Hermes 本地构建并运行 child agent
       └─ daedalus backend: 把 TaskSpec 发给 Daedalus /api/tasks

Daedalus
  └─ 可以作为远端任务调度后端
```

简单说：

- Hermes 仍然负责真正的 child agent 构建、session、credentials、toolsets、hooks、memory。
- delegate runtime 只负责可复用的编排数据结构、backend 边界、执行结果整理、active subagent registry。
- Daedalus 可以接收 delegate runtime 生成的任务规格，作为远端调度器。

## 现在包含什么

| 文件 | 作用 |
| --- | --- |
| `tools/delegate_runtime/backend.py` | backend 协议、`TaskSpec`、local/Daedalus backend |
| `tools/delegate_runtime/runtime.py` | 构造任务、选择 backend、status/result/list/cancel wrapper |
| `tools/delegate_runtime/execution.py` | batch/single 执行单元、结果 entry 构造、排序和耗时 |
| `tools/delegate_runtime/registry.py` | active subagent 注册表和状态转换 |
| `tools/delegate_runtime/postprocess.py` | result metadata 清理、child cost 汇总、hook payload 构造 |
| `tools/orchestrator_backend.py` | 兼容旧导入路径的 re-export shim |

## 不包含什么

这些仍然属于宿主，不在这个 runtime 里：

- Hermes `tools/delegate_tool.py` 的 host adapter 逻辑
- child agent 构建
- session / credential / provider / toolset 继承
- hook 实际调用
- memory manager 集成
- parent cost 写入
- background delivery / re-entry
- CLI、daemon、server、发布打包

## 当前能力

- 默认 local backend：宿主注入本地执行能力。
- Daedalus backend：向 `/api/tasks` 发送 `TaskSpec`，并读取 status/result/list。
- fake host 测试：证明它不依赖 Hermes `delegate_tool.py` 也能跑。
- fake Daedalus 测试：证明 HTTP backend contract 可以独立使用。

## 快速验证

```bash
python -m pytest -q
```

当前测试覆盖：

- backend contract 和兼容 shim
- public API 符号
- fake host 调用路径
- fake Daedalus backend roundtrip

## 使用方式

当前仓库保留 Hermes 原包名：

```python
from tools.delegate_runtime import (
    TaskSpec,
    LocalBackendBindings,
    build_task_specs,
    get_runtime_backend,
)
```

宿主需要自己注入本地执行逻辑。例如 Hermes 侧会继续负责 child agent 的创建和执行；这个 runtime 不负责知道 child agent 是什么。

## 状态

这是 v0 runtime slice。

适合现在做：

- 作为 Hermes delegate 解耦后的公共模块继续迭代
- 给 Daedalus 做远端 delegate backend contract
- 给未来独立 package 提供基础

还不适合现在宣称：

- 完整 multi-agent 产品
- 独立 daemon
- 可直接替代 Hermes delegate host
- 已完成真实 Daedalus 生产联调
