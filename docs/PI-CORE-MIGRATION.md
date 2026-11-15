# Pi Core 迁移说明

## 已完成

- `backend/agent/pi_core/loop.py` 提供单协程、线性有序的模型→工具事件流。
- `AgentMessage` 与 provider-facing `LLMMessage` 分层，UI 结构化字段不会写入 LLM 上下文。
- `prepare_request`、`before_tool_call`、`after_tool_call`、`finish_turn` 四个生命周期 Hook 已落地。
- `stop_reason == "length"` 时拒绝执行不完整的工具调用。
- `context.py` 提供 compaction、supersede/pruning 与消息转换。
- `durable.py` 提供追加式 JSONL journal 与原子快照。
- `resume_agent.py`、`resume_tools.py`、`resume_coordinator.py` 组成简历领域 runtime；生产 SSE 只依赖这一组组合式 API。
- `web/streaming/agent_stream.py` 只负责把 Pi Core 事件转换成既有 SSE 事件，不再创建 Queue、Future 或忙轮询。
- `AgentStream` 仅保留历史构造函数兼容名；实际实现为 `PiCoreAgentStream`。

## 生产边界

生产入口是：

```text
backend.agent.web.routes.stream
  -> backend.agent.pi_core.resume_agent.ResumeAgentRuntime
  -> backend.agent.pi_core.stream.PiCoreAgentStream
  -> backend.agent.pi_core.loop.run_agent_loop
```

旧的 `backend.agent.agent.manus.Manus` 兼容入口已删除。生产代码统一通过
`backend.agent.pi_core.resume_agent.ResumeAgentRuntime` 组合式 runtime 进入，
不再承载旧的 agent 继承链或旧的 step/think/act/run 生命周期。

## 灰度开关

- `RESUME_AGENT_PI_CORE_ROLLOUT_PERCENT`：按 session 稳定哈希控制灰度比例。
- `RESUME_AGENT_PI_CORE=false`：直接禁用 Pi Core 请求并返回明确错误；不会回退到旧 SSE 实现。

## 验证

```powershell
$env:PYTHONPATH = "C:\Users\DKF\Downloads\Resume-Agent-github"
C:\Users\DKF\Downloads\Resume-Agent-main\Resume-Agent-main\.venv\Scripts\python.exe `
  -m pytest backend/tests -q
```

上下文裁剪可通过以下离线脚本复现：

```powershell
python -m backend.scripts.bench_pi_core_context --rounds 8 --chars 4000
```
