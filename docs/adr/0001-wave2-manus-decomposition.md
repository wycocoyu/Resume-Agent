# ADR 0001 · Wave 2 按用例接缝拆分 Manus，分三子波纯结构重构

- 状态：Accepted（2026-07-10，用户批准）
- 关联：[`../agent-glossary.md`](../agent-glossary.md)（领域术语表）

## 背景

`Manus` 2602 行混合九类职责、5 个散落 flag；`AgentStream` 1402 行持有执行语义；会话态在 Wave 0.5 façade 后仍有 `ResumeDataStore` 类级字典与 `AgentSharedState` 各自为政。新增一个意图/用例需要跨多处修改，回归风险高。方案经 Codex 架构分析 → Claude 逐条核验 → Codex 二轮 review 三方校验。

## 决策

1. **按用例/运行时接缝拆分，不按 helper 类型拆分**：产出 `TurnExecutionState` / `PromptBuilder` / `ResumeUseCases` / `IntentRouter`（输出 `RouteDecision`）/ `ToolInvocationBuilder`；Manus 退化为编排壳（≤600 行）。
2. **第一刀先收拢 flag 而非消灭 flag**：5 个 flag 先进 `TurnExecutionState` 单轮状态对象，降低散落度后再重塑执行流（Codex review 结论：一步到位消 flag 是重构事故来源）。
3. **分三子波按序交付**：2a 拆 Manus（四步 S1-S4）→ 2b AgentStream 降级为事件适配器（`stream_runtime.run_stream()` 接管执行语义，两步 B1/B2）→ 2c 会话态完整收拢进 session_manager。每步独立 commit，每子波独立分支 + Codex review + 浏览器实测。
4. **纯结构重构铁律**：外部行为零变化；现有测试（含 Wave 1.2 协议快照 11 条）零修改通过是硬门槛；发现的行为怪癖只记录不修。

## 备选方案与否决理由

- **按 helper 类型拆**（utils/parsing/formatting）：机械简单但接缝不对齐业务语义，同一用例逻辑仍散落多文件——Codex review 明确否决。
- **三块一次做完**：diff 巨大、review 困难、回滚成本高——用户否决。
- **顺带修行为怪癖**：diff 混入行为变化，"纯结构"验收失效——用户否决（怪癖单独记录：patch 队列跨轮残留、AI 生成 latex 型简历预览不支持、AgentErrorEvent 嵌套字段前端读不到）。

## 后果

- 正面：意图/用例/prompt 各有唯一归属文件；IntentRouter 可决策表单测；2b 后执行语义单一所有者，重复回复/漏发 answer 类问题可定位到一处。
- 负面/代价：迁移期存在临时委托层（property 委托、ResumeDataStore 委托），须在各子波收尾清零（锁定决策 D2）；golden 对拍测试是一次性成本。
- 后续已登记：patch 队列生命周期治理、`%%SUGGESTIONS%%` prompt 协议移除、canonical envelope（run_id/seq）、CLTP 资产处置——均排 Wave 2 之后。
