# CONTEXT — Resume-Agent 领域术语表

> 全项目共用一份。改词义先改这里，代码与文档跟随。
> 建立于 Wave 2 重构（2026-07-10），此前口头用法以此表为准收口。

## Agent 执行域

| 术语 | 定义 | 代码锚点 |
|---|---|---|
| **Manus** | 简历产品 Agent 主类，`BaseAgent→ReActAgent→ToolCallAgent` 链的末端；Wave 2 后退化为"编排壳"（生命周期 + 工具装配 + decide→dispatch） | `backend/agent/agent/manus.py` |
| **轮（turn）** | 一次用户消息触发的完整执行（可含多个 step）；**单轮状态**指本轮结束即失效的执行标志 | — |
| **step** | ReAct 循环的一次 think+act 迭代 | `backend/agent/agent/react.py` |
| **fast-path** | 不经 LLM 决策、由规则直接产生回复或工具调用的路径（Greeting / Load / Edit / 优化确认四条） | `Manus.think()` 内，Wave 2a-S4 迁 `intent_router.py` |
| **LLM-first（让权）** | 与 fast-path 相对：把本轮决策权交给 LLM（走 super().think() 的工具调用循环） | 同上 |
| **RouteDecision** | IntentRouter 的输出：`fast_path / direct_tool / llm_first / clarify` 四种去向之一 + payload | Wave 2a-S4 `intent_router.py` |
| **TurnExecutionState** | 轮级执行状态对象，现存 5 个字段（pending_edit_tool_call / pending_resume_patches / finish_after_load_resume_tool / read_only / diagnosis_only；历史 pending_immediate_stream 随 qwq 死分支于 Wave A-2 删除）；diagnosis_only 保证宽泛优化轮只产出诊断与只读建议；注意 patches 队列**非严格单轮**（见 patch 队列词条） | Wave 2a-S1 `turn_state.py` |
| **qwq 流（诊断流）** | 【已删除的历史实现】简历诊断场景的双通道流式输出（thinking + content 并行推送）；全仓无生产者，Wave A-2（2026-07-13）连同 AgentStream 消费分支、turn_state 字段、llm.ask_with_thinking_stream 一并移除 | 历史：`agent_stream.py` 死分支 |
| **直接工具调用（direct tool call）** | 后端替 LLM 构造 tool_call（不等模型输出），用于确定性场景 | `_handle_direct_tool_call`，Wave 2a-S4 迁 `tool_invocation_builder.py` |

## 事件与流式域

| 术语 | 定义 | 代码锚点 |
|---|---|---|
| **StreamEvent** | 后端内部事件模型；`to_dict()` 必含统一外壳 `type/session_id/timestamp` + 扁平业务字段（Wave 1.2 起） | `backend/agent/web/streaming/events.py` |
| **SSE 外层帧** | `{id, type, data, timestamp}`，`data` 即 StreamEvent 的 to_dict；外层/内层 type 重复是已知兼容代价（Wave 2 canonical envelope 前不动） | `backend/agent/web/schemas/stream.py` |
| **suggestions 标记** | `%%SUGGESTIONS%%[...]%%END%%` 文本协议：LLM/后端在正文尾部携带建议按钮；后端全路径提取转 `SuggestionsEvent`，每 run 只发一次（Wave 1.2 起） | `agent_stream._extract_suggestions` / `_make_suggestions_event` |
| **patch（简历补丁）** | 一次简历字段修改的 before/after diff，经 `resume_patch` 事件推前端渲染确认卡 | `ResumePatchEvent`、`queue_resume_patch` |
| **patch 队列** | Manus 侧暂存的待发 patch 列表，由 AgentStream 发射时 drain；跨轮残留是已知现状（锁定决策 D3，不改） | `_pending_resume_patches` → `TurnExecutionState.pending_resume_patches` |
| **structured_data（显式通道）** | 工具结构化输出的显式字段，优先于 legacy 的 system JSON 旁路（Wave 1.1 起双写迁移） | `ToolResult.structured_data` |
| **stream runtime** | 执行语义唯一所有者：step 循环、memory 读写、去重、final answer、history 落盘（Wave 2b 从 AgentStream 迁出） | Wave 2b `stream_runtime.py` |
| **事件适配器** | Wave 2b 后 AgentStream 的定位：心跳 / 取消 / SSE 封装，不再持有执行语义 | `agent_stream.py` |

## 会话与数据域

| 术语 | 定义 | 代码锚点 |
|---|---|---|
| **会话（session / conversation）** | 一个 conversation_id 对应的对话上下文；内存态含 agent 实例、chat_history、简历数据 | `backend/agent/web/session_manager.py` |
| **session_manager** | 内存会话操作唯一入口（Wave 0.5 façade；Wave 2c 升级为拥有 ResumeDataStore/SharedState 生命周期的完全体） | 同上 |
| **touch-then-sweep** | TTL 回收策略：当前会话先刷活跃时间再清扫，判据 `last_accessed`（Wave 0.2 起） | `session_manager.evict_idle_sessions` |
| **ResumeDataStore** | 会话级简历数据共享存储（简历 JSON / meta / JD / shared_state 绑定）；Wave 2c 后为 session_manager 的委托层 | `backend/agent/tool/resume_data_store.py` |
| **会话 JD** | 本会话的目标岗位描述，一次提供后续优化自动对齐；随会话销毁清除（Wave 0.1 起） | `_jd_by_session` |
| **AgentSharedState** | Agent 与工具间的会话级共享键值状态 | `backend/agent/agent/shared_state.py` |

## 流程域（研发协作）

| 术语 | 定义 |
|---|---|
| **Wave** | 架构优化的交付批次：0/0.5（bug+façade）→ 1.1/1.2（接口收敛）→ 2a/2b/2c（结构重构）→ 3（清理） |
| **纯结构重构** | 本项目约定：只搬运不改行为，现有测试零修改通过为硬门槛；发现的行为怪癖记录不修（Wave 2 铁律） |
| **golden 对拍** | 迁移验证手法：同输入下新旧实现输出逐字符相等的临时测试，迁移完成后随旧实现一起删除 |
