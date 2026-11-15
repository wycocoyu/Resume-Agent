import { describe, it, expect } from "vitest";
import {
  ResumeDataSchema,
  parseResumeData,
  isResumeData,
  StreamEventSchema,
  StreamEventTypeSchema,
  parseStreamEvent,
  formatSSEMessage,
  parseSSEBlock,
  TextDeltaPayloadSchema,
  ToolCallPayloadSchema,
  ToolResultPayloadSchema,
  StatusPayloadSchema,
  ErrorPayloadSchema,
  DonePayloadSchema,
  ResumePatchPayloadSchema,
  ResumeGeneratedPayloadSchema,
} from "../src/index";

describe("packages/schema: ResumeDataSchema", () => {
  it("validates a minimal valid resume object", () => {
    const minimal = { name: "张三" };
    const parsed = parseResumeData(minimal);
    expect(parsed.name).toBe("张三");
    expect(parsed.contact).toEqual({});
    expect(isResumeData(minimal)).toBe(true);
  });

  it("validates an empty object with defaults", () => {
    const empty = {};
    const parsed = parseResumeData(empty);
    expect(parsed.name).toBe("");
    expect(parsed.contact).toEqual({});
  });

  it("validates a comprehensive resume with all sections", () => {
    const fullResume = {
      name: "李四",
      contact: {
        phone: "13800138000",
        email: "lisi@example.com",
        role: "高级后端工程师",
        location: "北京",
        github: "https://github.com/lisi",
      },
      objective: "寻求分布式架构师岗位",
      summary: "8年高并发系统架构与微服务实战经验",
      education: [
        {
          title: "清华大学",
          subtitle: "计算机科学与技术",
          degree: "硕士",
          date: "2016-2019",
          details: ["GPA: 3.9/4.0", "优秀毕业生"],
        },
      ],
      internships: [
        {
          title: "字节跳动",
          subtitle: "后端实习生",
          date: "2018.06-2018.12",
          highlights: ["负责抖音推荐系统召回链路重构"],
        },
      ],
      experience: [
        {
          title: "腾讯科技",
          subtitle: "高级工程师",
          date: "2019.07-至今",
          highlights: ["主导微信核心网关重构", "支撑亿级 QPS 流量"],
        },
      ],
      projects: [
        {
          title: "CocoCV 全栈智能简历平台",
          subtitle: "核心作者",
          date: "2026",
          items: [
            {
              title: "XeLaTeX 双层 CMap 补丁引擎",
              details: ["解决中文提取乱码问题", "复制准确率 100%"],
            },
          ],
          highlights: ["单协程线性流式事件循环"],
        },
      ],
      openSource: [
        {
          title: "wycocoyu/Resume-Agent",
          subtitle: "开源协同项目",
          items: ["实现通用技能抽象与多 Harness 适配"],
        },
      ],
      skills: [
        { category: "后端技术", details: "Go / Python / TypeScript / Rust" },
        "Docker / K8s / 云原生基础设施",
      ],
      awards: ["ACM-ICPC 区域赛金牌"],
      competitions: [
        {
          title: "全国大学生程序设计竞赛",
          award: "全国一等奖",
          date: "2017",
        },
      ],
      publications: [
        {
          title: "Efficient Event-Driven Stream Architectures",
          authors: ["李四", "张三"],
          venue: "IEEE Cloud",
          date: "2025",
        },
      ],
      sectionTitles: {
        education: "教育背景",
        experience: "职业经历",
        internships: "实习经历",
        projects: "核心项目",
        skills: "技术栈",
      },
    };

    const parsed = parseResumeData(fullResume);
    expect(parsed.name).toBe("李四");
    expect(parsed.education?.[0].title).toBe("清华大学");
    expect(parsed.education?.[0].degree).toBe("硕士");
    expect(parsed.projects?.[0].items?.[0].title).toBe("XeLaTeX 双层 CMap 补丁引擎");
    expect(parsed.skills?.length).toBe(2);
    expect(parsed.competitions?.[0].award).toBe("全国一等奖");
    expect(isResumeData(fullResume)).toBe(true);
  });

  it("allows passthrough extra properties for forward compatibility", () => {
    const withCustomFields = {
      name: "王五",
      customScore: 98,
      aiDiagnosis: { radarScore: 92 },
    };
    const parsed: any = parseResumeData(withCustomFields);
    expect(parsed.customScore).toBe(98);
    expect(parsed.aiDiagnosis.radarScore).toBe(92);
  });
});

describe("packages/schema: StreamEventSchema", () => {
  it("validates core stream event types", () => {
    const validTypes = [
      "text_delta",
      "status",
      "error",
      "done",
      "thought",
      "answer",
      "tool_call",
      "tool_result",
      "tool_progress",
      "resume_updated",
      "resume_patch",
      "resume_generated",
      "agent_start",
      "agent_end",
      "suggestions",
      "auto_continue",
      "answer_reset",
    ];

    for (const t of validTypes) {
      expect(StreamEventTypeSchema.safeParse(t).success).toBe(true);
    }
  });

  it("validates text_delta event", () => {
    const payload = { content: "思考中...", delta: "正在规划第1步" };
    expect(TextDeltaPayloadSchema.safeParse(payload).success).toBe(true);

    const event = {
      id: "evt_12345",
      event_type: "text_delta",
      data: payload,
      timestamp: Date.now(),
      run_id: "run_abc",
      seq: 1,
    };
    const parsed = parseStreamEvent(event);
    expect(parsed.event_type).toBe("text_delta");
    expect(parsed.data.delta).toBe("正在规划第1步");
  });

  it("validates tool_call and tool_result events", () => {
    const callData = {
      tool: "render_pdf",
      args: { template: "asu-tech", engine: "latex" },
      tool_call_id: "call_001",
    };
    expect(ToolCallPayloadSchema.safeParse(callData).success).toBe(true);

    const callEvent = parseStreamEvent({
      event_type: "tool_call",
      data: callData,
    });
    expect(callEvent.data.tool).toBe("render_pdf");

    const resultData = {
      tool: "render_pdf",
      result: { pdf_url: "/api/pdf/download/123" },
      tool_call_id: "call_001",
      outcome: "success" as const,
    };
    expect(ToolResultPayloadSchema.safeParse(resultData).success).toBe(true);
  });

  it("validates status, error, and done events", () => {
    expect(StatusPayloadSchema.safeParse({ status: "running", message: "优化中" }).success).toBe(true);
    expect(ErrorPayloadSchema.safeParse({ message: "编译错误", code: 500 }).success).toBe(true);
    expect(DonePayloadSchema.safeParse({ summary: "全部用例执行完成", run_id: "run_xyz" }).success).toBe(true);

    const doneEvent = parseStreamEvent({
      event_type: "done",
      data: { summary: "完成" },
    });
    expect(doneEvent.event_type).toBe("done");
  });

  it("validates resume_patch and resume_generated events", () => {
    const patchPayload = {
      patch_id: "patch_01",
      paths: ["summary", "projects.0.highlights"],
      before: { summary: "旧总结" },
      after: { summary: "新高密度技术总结" },
      summary: "更新个人技术总结",
    };
    expect(ResumePatchPayloadSchema.safeParse(patchPayload).success).toBe(true);

    const generatedPayload = {
      resume: { name: "赵六", education: [] },
      summary: "已根据 JD 生成匹配简历",
    };
    expect(ResumeGeneratedPayloadSchema.safeParse(generatedPayload).success).toBe(true);
  });

  it("formats SSE string correctly", () => {
    const event = {
      id: "evt_777",
      event_type: "text_delta",
      data: { delta: "Hello CocoCV" },
    };
    const sse = formatSSEMessage(event);
    expect(sse).toContain("id: evt_777\n");
    expect(sse).toContain("event: text_delta\n");
    expect(sse).toContain('data: {"delta":"Hello CocoCV"}\n\n');
  });

  it("parses raw SSE block into structured event", () => {
    const rawBlock = `id: evt_999\nevent: status\ndata: {"status":"compiling","message":"XeLaTeX running"}\n\n`;
    const event = parseSSEBlock(rawBlock);
    expect(event).not.toBeNull();
    expect(event?.id).toBe("evt_999");
    expect(event?.event_type).toBe("status");
    expect(event?.data.status).toBe("compiling");
  });
});
