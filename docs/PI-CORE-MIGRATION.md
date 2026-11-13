# Pi Core 迁移阶段说明

当前分支已经加入 `backend/agent/pi_core/`，作为 #42 的第一阶段内核：

- 单协程线性事件流：`message_start` → `message_update` → `message_end` → 工具事件；
- `AgentMessage` 与 `LLMMessage` 分层；
- `prepare_request`、`before_tool_call`、`after_tool_call`、`finish_turn` 四个 Hook；
- `stop_reason == "length"` 时拒绝执行残缺工具调用；
- 通过 `supersede_key` 在发送给模型前裁剪过期工具输出；
- 不依赖 OpenManus 继承链，也不依赖 Web/SSE 层。

同时增加了 `resume_adapter.py` 和 `sse_adapter.py`，负责把现有 `Message`、DeepSeek
流、Manus 工具和旧 SSE 事件互相转换。`StreamProcessor` 已提供一个**默认关闭的
灰度入口**：

```powershell
$env:RESUME_AGENT_PI_CORE = "true"
```

开启后单次请求只走 `PiCoreAgentStream`；未开启时仍走原来的
`AgentStream`。这样可以按会话/环境做回退，不会同时执行两套模型调用。

## 当前边界

这一步已经把生产入口接成**显式 opt-in**，但不建议在没有端到端回归前默认打开。现有
前端仍依赖旧的 SSE 事件字段、旁白归位、审批卡和 `resume_patch` 语义；新适配器已做
兼容映射，但 PDF 上传、审批、自动续跑等真实链路仍需在目标环境验证。

下一阶段应继续做灰度回归，并在确认所有旧语义等价后，再删除旧
Queue、Future 和 `0.01s` 轮询逻辑。

## 验证

```powershell
$env:PYTHONPATH = "C:\Users\DKF\Downloads\Resume-Agent-github"
C:\Users\DKF\Downloads\Resume-Agent-main\Resume-Agent-main\.venv\Scripts\python.exe `
  -m pytest backend/tests/test_pi_core_loop.py -q
```

当前测试覆盖事件顺序、截断工具熔断、Hook 阻断/早停、supersede 裁剪、旧 SSE 映射
以及 opt-in stream 的旁白→工具卡顺序。
