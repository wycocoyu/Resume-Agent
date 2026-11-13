# Pi Core 迁移阶段说明

当前分支已经加入 `backend/agent/pi_core/`，作为 #42 的第一阶段内核：

- 单协程线性事件流：`message_start` → `message_update` → `message_end` → 工具事件；
- `AgentMessage` 与 `LLMMessage` 分层；
- `prepare_request`、`before_tool_call`、`after_tool_call`、`finish_turn` 四个 Hook；
- `stop_reason == "length"` 时拒绝执行残缺工具调用；
- 通过 `supersede_key` 在发送给模型前裁剪过期工具输出；
- 不依赖 OpenManus 继承链，也不依赖 Web/SSE 层。

## 当前边界

这一步是**可独立测试的新执行内核**，尚未把生产入口
`backend/agent/web/streaming/agent_stream.py` 切换到新内核。原因是现有前端仍依赖
旧的 SSE 事件字段、旁白归位、审批卡和 `resume_patch` 语义，直接替换会把多个行为变更
混在一次提交里。

下一阶段应增加一个 Resume-Agent 业务适配器：

1. 将现有 `Message`/`ToolCall` 转成 `AgentMessage`/`ToolCall`；
2. 将 DeepSeek 的流式响应暴露为 `AssistantChunk`；
3. 将现有简历工具包装成 `ToolResult` 与 `tool_execution_update`；
4. 在薄 SSE 适配层把内核事件映射回现有前端事件；
5. 在独立回归通过后，再删除旧 Queue、Future 和轮询逻辑。

## 验证

```powershell
$env:PYTHONPATH = "C:\Users\DKF\Downloads\Resume-Agent-github"
C:\Users\DKF\Downloads\Resume-Agent-main\Resume-Agent-main\.venv\Scripts\python.exe `
  -m pytest backend/tests/test_pi_core_loop.py -q
```

当前内核测试覆盖事件顺序、截断工具熔断、Hook 阻断/早停和 supersede 裁剪。
