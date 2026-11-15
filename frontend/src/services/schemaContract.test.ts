import { describe, it, expect } from "vitest";
import {
  ResumeDataSchema,
  StreamEventSchema,
  parseResumeData,
  parseStreamEvent,
  parseSSEBlock,
  formatSSEMessage,
} from "@cococv/schema";

describe("frontend <-> @cococv/schema contract alignment", () => {
  it("aligns frontend default resume data with ResumeDataSchema", () => {
    const frontendResume = {
      name: "张三",
      contact: {
        phone: "13800000000",
        email: "zhangsan@example.com",
        role: "前端开发工程师",
        location: "北京",
      },
      objective: "高级前端工程师",
      summary: "熟练掌握 React, TypeScript, Vite 与现代前端工程化",
      education: [
        {
          title: "清华大学",
          subtitle: "软件工程",
          degree: "本科",
          date: "2018-2022",
          details: ["获得国家奖学金"],
        },
      ],
      internships: [
        {
          title: "字节跳动",
          subtitle: "前端日常实习生",
          date: "2021.03-2021.09",
          highlights: ["参与飞书协作文档性能优化"],
        },
      ],
      projects: [
        {
          title: "CocoCV 智能简历制作平台",
          subtitle: "前端核心开发",
          date: "2026.01-至今",
          highlights: ["双渲染引擎预览", "单文件可编辑自包含 HTML 导出"],
          items: [
            {
              title: "自动一页算法",
              details: ["基于 DOM 高度度量的三档自适应算法"],
            },
          ],
        },
      ],
      skills: [
        { category: "前端框架", details: "React, Next.js, Vue" },
        "Node.js, Vite, Tailwind CSS",
      ],
      awards: ["校级优秀毕业生"],
      sectionTitles: {
        education: "教育背景",
        projects: "项目经验",
        internships: "实习经历",
        skills: "技术栈",
      },
    };

    const parsed = parseResumeData(frontendResume);
    expect(parsed.name).toBe("张三");
    expect(parsed.contact.role).toBe("前端开发工程师");
    expect(parsed.education?.[0].title).toBe("清华大学");
    expect(parsed.projects?.[0].items?.[0].title).toBe("自动一页算法");
    expect(parsed.skills?.length).toBe(2);
  });

  it("aligns SSE streaming event frames between backend and frontend presentation", () => {
    const events = [
      {
        id: "evt_101",
        event_type: "thought",
        data: { content: "正在分析目标岗位 JD 的技术要求..." },
        timestamp: Date.now(),
      },
      {
        id: "evt_102",
        event_type: "tool_call",
        data: {
          tool: "jd_match_analyzer",
          args: { jd_text: "要求熟悉分布式架构" },
          tool_call_id: "call_jd_1",
        },
        timestamp: Date.now(),
      },
      {
        id: "evt_103",
        event_type: "resume_patch",
        data: {
          patch_id: "patch_jd_match",
          paths: ["projects.0.highlights"],
          summary: "针对 JD 强化高并发分布式经历",
        },
        timestamp: Date.now(),
      },
      {
        id: "evt_104",
        event_type: "status",
        data: { status: "complete", message: "优化完成" },
        timestamp: Date.now(),
      },
      {
        id: "evt_105",
        event_type: "done",
        data: { summary: "修改完毕" },
        timestamp: Date.now(),
      },
    ];

    for (const evt of events) {
      const parsed = parseStreamEvent(evt);
      expect(parsed.id).toBe(evt.id);
      expect(parsed.event_type).toBe(evt.event_type);

      const sseText = formatSSEMessage(parsed);
      expect(sseText).toContain(`id: ${evt.id}`);
      expect(sseText).toContain(`event: ${evt.event_type}`);

      const roundtrip = parseSSEBlock(sseText);
      expect(roundtrip).not.toBeNull();
      expect(roundtrip?.id).toBe(evt.id);
      expect(roundtrip?.event_type).toBe(evt.event_type);
    }
  });
});
