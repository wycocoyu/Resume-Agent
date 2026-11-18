// @vitest-environment jsdom

import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { STORAGE_KEY } from "../constants";
import type { ResumeData } from "../types";

// ---- mocks ----
let mockPathname = "/workspace";
let mockRouteResumeId: string | undefined;
vi.mock("react-router-dom", () => ({
  useLocation: () => ({ pathname: mockPathname }),
  useParams: () => ({ resumeId: mockRouteResumeId }),
}));

// 稳定引用：每次返回同一 setResume，否则 setResumeData useCallback 身份
// 每渲染变化 → loadResume effect 反复重跑 → 无限循环
const stableSetResume = vi.fn();
vi.mock("@/contexts/ResumeContext", () => ({
  useResumeContext: () => ({ resume: null, setResume: stableSetResume }),
}));

const getResume = vi.fn();
let mockCurrentId: string | null = null;
vi.mock("@/services/resumeStorage", () => ({
  getResume: (...args: unknown[]) => getResume(...args),
  getCurrentResumeId: () => mockCurrentId,
  setCurrentResumeId: (id: string | null) => {
    mockCurrentId = id;
  },
}));

import { useResumeData } from "./useResumeData";

(globalThis as typeof globalThis & { IS_REACT_ACT_ENVIRONMENT: boolean })
  .IS_REACT_ACT_ENVIRONMENT = true;

// 一份「幽灵」草稿：非空白（有姓名+经历），模拟删除前编辑过的旧简历
const GHOST_DRAFT = {
  basic: { name: "张露巍", title: "算法工程师" },
  experience: [{ id: "e1", company: "联想", position: "实习", date: "", details: "x" }],
  projects: [],
  education: [],
  menuSections: [],
};

function Harness({ onData }: { onData: (d: ResumeData, loaded: boolean) => void }) {
  const { resumeData, isDataLoaded } = useResumeData();
  onData(resumeData, isDataLoaded);
  return null;
}

describe("useResumeData · 删除后不显示幽灵简历（L1 加载失效兜底）", () => {
  let container: HTMLDivElement;
  let root: Root;

  beforeEach(() => {
    container = document.createElement("div");
    document.body.appendChild(container);
    root = createRoot(container);
    getResume.mockReset();
    mockCurrentId = null;
    mockRouteResumeId = undefined;
    mockPathname = "/workspace";
    localStorage.clear();
  });

  afterEach(() => {
    act(() => root.unmount());
    container.remove();
  });

  async function renderAndSettle() {
    let latest: { data: ResumeData; loaded: boolean } | null = null;
    await act(async () => {
      root.render(
        <Harness onData={(data, loaded) => (latest = { data, loaded })} />,
      );
      // 让 loadResume 的异步 effect 跑完
      await Promise.resolve();
      await Promise.resolve();
    });
    return latest!;
  }

  it("resets to blank template when the routed resumeId no longer exists (deleted)", async () => {
    // 幽灵草稿在 localStorage，URL 指向一个已删简历，getResume 返回 null
    localStorage.setItem(STORAGE_KEY, JSON.stringify(GHOST_DRAFT));
    mockRouteResumeId = "deleted-id";
    getResume.mockResolvedValue(null);

    const { data } = await renderAndSettle();

    // 不再显示幽灵「张露巍」，而是空白默认模板「张三」
    expect(data.basic.name).toBe("张三");
    expect(getResume).toHaveBeenCalledWith("deleted-id");
    // 幽灵草稿已被清（下次加载不会再复活）
    const persisted = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    expect(persisted.basic?.name).not.toBe("张露巍");
  });

  it("resets to blank on bare /workspace with no current resume (all deleted)", async () => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(GHOST_DRAFT));
    mockRouteResumeId = undefined;
    mockCurrentId = null; // 全删后无 current

    const { data } = await renderAndSettle();

    expect(data.basic.name).toBe("张三");
    // 无目标简历时不应发起 getResume
    expect(getResume).not.toHaveBeenCalled();
  });

  it("loads normally when the resume still exists (no regression)", async () => {
    mockRouteResumeId = "real-id";
    getResume.mockResolvedValue({
      id: "real-id",
      name: "韦宇",
      data: { basic: { title: "后端" }, experience: [], projects: [], education: [], menuSections: [] },
    });

    const { data } = await renderAndSettle();

    expect(data.basic.name).toBe("韦宇");
  });

  it("clears previous basic.photo when loading a saved resume without photo", async () => {
    localStorage.setItem(
      STORAGE_KEY,
      JSON.stringify({
        ...GHOST_DRAFT,
        basic: { ...GHOST_DRAFT.basic, photo: "data:image/png;base64,OLDPHOTO" },
      }),
    );
    mockRouteResumeId = "no-photo-id";
    getResume.mockResolvedValue({
      id: "no-photo-id",
      name: "无照片简历",
      data: { basic: { title: "全栈" }, experience: [], projects: [], education: [], menuSections: [] },
    });

    const { data } = await renderAndSettle();

    expect(data.basic.name).toBe("无照片简历");
    expect(data.basic.photo).toBeUndefined();
  });
});
