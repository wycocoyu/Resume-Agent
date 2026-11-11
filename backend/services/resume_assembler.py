"""
简历组装服务
根据 MinerU文本 + OCR文本 融合生成结构化 Resume JSON
使用 DeepSeek 作为文本模型，Prompt 模板来自 agent/prompt/pdf_parser.py

数据流（简化版）：
1. MinerU：PDF → Markdown（基础文本结构）
2. glm-ocr：PDF → Markdown（高质量 OCR + 结构识别）
3. DeepSeek：融合两路数据 → 结构化 JSON

说明：glm-ocr 的 Markdown 输出已包含完整的结构信息（标题层级、列表格式、
嵌套结构如 "## · xxx专项"、技能分类如 "后端：xxx"），DeepSeek 可从文本
直接推断格式特征，无需额外的布局骨架。
"""

from __future__ import annotations

import json
import logging
import os
import re
from typing import Dict, Any, Optional

from openai import OpenAI

logger = logging.getLogger(__name__)

try:
    from backend.prompts_pdf_parser import (
        SYSTEM_PROMPT,
        OUTPUT_SCHEMA,
        DATA_FUSION_RULES,
        SECTION_MAPPING_RULES,
        HIGHLIGHTS_RULES,
        NESTED_RULES,
        SKILLS_RULES,
        FORMAT_RULES,
        ASSEMBLER_PROMPT,
    )
except ImportError:
    from prompts_pdf_parser import (
        SYSTEM_PROMPT,
        OUTPUT_SCHEMA,
        DATA_FUSION_RULES,
        SECTION_MAPPING_RULES,
        HIGHLIGHTS_RULES,
        NESTED_RULES,
        SKILLS_RULES,
        FORMAT_RULES,
        ASSEMBLER_PROMPT,
    )


# 2026-09-16 从阿里云百炼切到 DeepSeek 官方（百炼账户欠费，返回 400 Arrearage）。
# 官方只提供 deepseek-flash 与 deepseek-v4-pro 两个模型，qwen 系列在这边不存在。
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "").strip() or "deepseek-flash"
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "").strip() or "https://api.deepseek.com"

# deepseek-flash 默认开思考模式，会返回 reasoning_content 并拒绝 tool_choice=required。
# 关它只认下面这个参数——DashScope 时代的 enable_thinking=false 在官方端被静默忽略。
DEEPSEEK_NO_THINKING = {"thinking": {"type": "disabled"}}

# Claude 走 RuoLi 中转（OpenAI 兼容），与 DeepSeek 通道独立。
RUOLI_BASE_URL = os.getenv("RUOLI_BASE_URL", "https://ruoli.dev/v1").strip()

# 结构化默认模型。原为 qwen-plus-latest（实测输出 token 少约一半、更快），
# 但那是 DashScope 独有模型，切到 DeepSeek 官方后不可用，故回落到 deepseek-flash。
# 可用环境变量 ASSEMBLER_MODEL 覆盖。
DEFAULT_ASSEMBLER_MODEL = os.getenv("ASSEMBLER_MODEL", "").strip() or DEEPSEEK_MODEL


def resolve_assembler_model(model: Optional[str]) -> str:
    """决定结构化用哪个模型。
    - 传已下线的 deepseek 旧名（deepseek-chat / reasoner / v4-flash）：归一到当前官方模型，
      向后兼容老前端与老会话里存下的模型名
    - 传 qwen-*：DashScope 独有，切到 DeepSeek 官方后不存在，同样归一，
      否则老数据会带着一个必然 404 的模型名打过去
    - 其它显式模型（如 claude-*）：放行
    - 未传 / 空：用 DEFAULT_ASSEMBLER_MODEL
    """
    name = (model or "").strip()
    if not name:
        return DEFAULT_ASSEMBLER_MODEL
    # 别名表统一维护在 backend/simple.py，两条链路共用一份，避免各自漂移
    try:
        from backend.simple import normalize_model_name
    except ImportError:
        from simple import normalize_model_name
    return normalize_model_name(name)

_deepseek_client: Optional[OpenAI] = None
_last_key: Optional[str] = None
# Claude 中转 client 独立缓存，不污染 DashScope 单例
_ruoli_client: Optional[OpenAI] = None
_last_ruoli_key: Optional[str] = None


def _thinking_off(model_name: Optional[str]) -> Optional[dict]:
    """deepseek-* 关闭思考模式；其它通道（claude）不认这个参数，必须传 None。"""
    name = (model_name or "").strip()
    return DEEPSEEK_NO_THINKING if name.startswith("deepseek") else None


def _get_client(model_name: Optional[str] = None) -> OpenAI:
    """按模型名选 LLM 通道：
    - claude-* → RuoLi 中转（RUOLI_API_KEY + RUOLI_BASE_URL）
    - 其它    → DeepSeek 官方（DEEPSEEK_API_KEY + DEEPSEEK_BASE_URL）
    main 启动时已 load_dotenv。
    """
    # ---- Claude 走中转 ----
    if model_name and model_name.startswith("claude-"):
        global _ruoli_client, _last_ruoli_key
        key = os.getenv("RUOLI_API_KEY", "").strip()
        if not key:
            raise ValueError("RUOLI_API_KEY 未配置（claude 模型需要中转 key）")
        if _ruoli_client is None or _last_ruoli_key != key:
            _ruoli_client = OpenAI(
                api_key=key,
                base_url=RUOLI_BASE_URL,
                timeout=60.0,
                max_retries=0,
            )
            _last_ruoli_key = key
        return _ruoli_client

    # ---- DeepSeek 官方通道 ----
    global _deepseek_client, _last_key
    try:
        from backend.env_keys import get_live_api_key
    except ImportError:
        from env_keys import get_live_api_key
    # 2026-09-16 起以 DEEPSEEK_API_KEY 为准；DASHSCOPE_API_KEY 仅作旧部署兜底。
    key = get_live_api_key("deepseek")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY 未配置")
    if _deepseek_client is None or _last_key != key:
        # 显式 timeout + 关闭 SDK 默认指数退避重试：
        # SDK 默认 timeout=600s + 重试 2 次(0.8→1.6→3.8s)，一次上游抖动会被放大到 10s+。
        # 这里 60s 超时 + 不重试，失败快速抛出，交给上层 EASY/EXP 并发 + _serial 回退处理。
        _deepseek_client = OpenAI(
            api_key=key,
            base_url=DEEPSEEK_BASE_URL,
            timeout=60.0,
            max_retries=0,
        )
        _last_key = key
    return _deepseek_client


def _strip_json_block(text: str) -> str:
    cleaned = text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in cleaned:
        cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
    return cleaned.strip()


def _parse_json(text: str) -> Dict[str, Any]:
    cleaned = _strip_json_block(text)
    try:
        return json.loads(cleaned)
    except Exception:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start != -1 and end != -1 and end > start:
            snippet = cleaned[start : end + 1]
            try:
                return json.loads(snippet)
            except Exception:
                # 便宜修复：去掉 } / ] 前的尾逗号（LLM 常见错误）
                repaired = re.sub(r",(\s*[}\]])", r"\1", snippet)
                return json.loads(repaired)
        raise


def _split_text_by_headings(text: str) -> Dict[str, str]:
    """
    按常见简历标题切分文本，减少跨模块混入
    """
    headings = [
        ("experience", ["实习经历", "工作经历", "工作经验"]),
        ("projects", ["项目经验", "项目经历"]),
        ("openSource", ["开源经历", "开源项目", "开源"]),
        ("skills", ["专业技能", "技能"]),
        ("education", ["教育经历", "教育背景"]),
        ("awards", ["获奖", "奖项", "荣誉"]),
    ]

    positions: Dict[str, tuple[int, str]] = {}
    for key, keywords in headings:
        for kw in keywords:
            idx = text.find(kw)
            if idx != -1:
                if key not in positions or idx < positions[key][0]:
                    positions[key] = (idx, kw)

    if not positions:
        return {}

    ordered = sorted(
        ((idx, key, kw) for key, (idx, kw) in positions.items()), key=lambda x: x[0]
    )
    segments: Dict[str, str] = {}
    for i, (start_idx, key, kw) in enumerate(ordered):
        end_idx = ordered[i + 1][0] if i + 1 < len(ordered) else len(text)
        segments[key] = text[start_idx:end_idx].strip()
    return segments


def _split_list_text(text: str) -> list[str]:
    if not isinstance(text, str):
        return []
    stripped = text.strip()
    if not stripped:
        return []
    if "<li" in stripped or "<ul" in stripped or "<ol" in stripped:
        return [stripped]
    lines = [line.strip() for line in stripped.splitlines() if line.strip()]
    if len(lines) > 1:
        return lines
    parts = [
        p.strip()
        for p in re.split(r"\s*(?:\d+[\.\、]|[•\-])\s+", stripped)
        if p.strip()
    ]
    if len(parts) > 1:
        return parts
    return [stripped]


def _normalize_highlights(data: Dict[str, Any]) -> Dict[str, Any]:
    for section in ("internships", "projects"):
        items = data.get(section)
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            highlights = item.get("highlights")
            if isinstance(highlights, str):
                item["highlights"] = _split_list_text(highlights)
            elif isinstance(highlights, list):
                normalized: list[str] = []
                for h in highlights:
                    if isinstance(h, str):
                        normalized.extend(_split_list_text(h))
                    elif h:
                        normalized.append(h)
                item["highlights"] = normalized
    open_source = data.get("openSource")
    if isinstance(open_source, list):
        for item in open_source:
            if not isinstance(item, dict):
                continue
            items = item.get("items")
            if isinstance(items, str):
                item["items"] = _split_list_text(items)
            elif isinstance(items, list):
                normalized_items: list[str] = []
                for it in items:
                    if isinstance(it, str):
                        normalized_items.extend(_split_list_text(it))
                    elif it:
                        normalized_items.append(it)
                item["items"] = normalized_items
    return data


def _extract_format_info(layout: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """
    从布局骨架中提取各section的格式信息
    """
    format_info = {}
    sections = layout.get("sections", [])
    for section in sections:
        section_type = section.get("type", "")
        section_format = section.get("format", {})
        if section_type:
            format_info[section_type] = {
                "list_style": section_format.get("list_style", "bullet"),
                "has_category": section_format.get("has_category", False),
                "has_nested_groups": section_format.get("has_nested_groups", False),
            }
            # 提取每个条目的嵌套结构信息
            items = section.get("items", [])
            nested_items = []
            for item in items:
                if isinstance(item, dict) and item.get("nested_structure"):
                    nested_items.append(
                        {
                            "name": item.get("name", ""),
                            "nested_structure": item.get("nested_structure", []),
                        }
                    )
            if nested_items:
                format_info[section_type]["nested_items"] = nested_items
    return format_info


def _build_data_sources_desc(raw_text: str, ocr_text: str, has_layout: bool) -> str:
    """构建多源数据说明"""
    lines = ["你有以下多个数据源（按精确度从高到低排列）："]
    idx = 0
    if ocr_text:
        idx += 1
        lines.append(
            f"{idx}. 【OCR文本】（glm-ocr 从 PDF 直接提取，格式最精确，内容最完整）"
        )
    if raw_text:
        idx += 1
        lines.append(f"{idx}. 【MinerU文本】（Markdown 格式，保留了列表结构）")
    if has_layout:
        idx += 1
        lines.append(
            f"{idx}. 【布局骨架】（glm-4.6v 视觉识别，提供模块顺序和格式特征）"
        )
    return "\n".join(lines)


def _build_data_content(
    raw_text: str,
    ocr_text: str,
    layout: Dict[str, Any],
    has_layout: bool,
    section_text: Dict[str, str],
) -> str:
    """
    构建各数据源的实际内容块

    数据源优先级：
    1. OCR文本（glm-ocr）：最精确，包含完整结构信息
    2. MinerU文本：快速提取，作为补充和校验
    3. 分区文本：辅助定位

    注意：布局骨架（glm-4.6v）已移除，DeepSeek 从文本直接推断结构
    """
    is_markdown = "##" in raw_text or "- " in raw_text or "* " in raw_text
    parts = []

    # 布局骨架（保留兼容性，但通常为空）
    if has_layout:
        parts.append(f"布局骨架（可选）：\n{json.dumps(layout, ensure_ascii=False)}")

    # OCR文本：主要数据源，包含结构信息如 "## · xxx专项"、"后端：xxx" 等
    if ocr_text:
        parts.append(f"OCR文本（glm-ocr，主要数据源，已包含结构信息）：\n{ocr_text}")

    # MinerU文本：补充数据源
    if raw_text:
        label = (
            "MinerU文本（Markdown 格式，补充）"
            if is_markdown
            else "MinerU文本（纯文本，补充）"
        )
        parts.append(f"{label}：\n{raw_text}")

    # 分区文本：辅助定位
    parts.append(
        f"分区文本（按标题切分，辅助定位）：\n{json.dumps(section_text, ensure_ascii=False)}"
    )

    return "\n\n".join(parts)


def assemble_resume_data(
    raw_text: str,
    layout: Dict[str, Any],
    ocr_text: str = "",
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    混合增强组装：根据 MinerU文本 + OCR文本 生成简历 JSON

    使用 PromptTemplate 模板系统构建 prompt，确保：
    - system/user 角色分离
    - 规则模块化（独立的模板片段，便于维护）
    - 变量验证（缺少变量时快速报错）

    数据源优先级：OCR文本(最精确，含结构信息) > MinerU Markdown

    注意：layout 参数保留以兼容旧调用，但通常为空字典。
    DeepSeek 从 OCR/MinerU 的 Markdown 文本直接推断格式特征。
    """
    if not raw_text and not ocr_text:
        raise ValueError("原始文本为空（MinerU 和 OCR 均无输出）")

    # 布局骨架可以为空（降级处理）
    has_layout = layout and "sections" in layout and len(layout.get("sections", [])) > 0

    # 提取格式信息
    format_info = _extract_format_info(layout) if has_layout else {}

    # ---- 使用模板系统构建 prompt ----

    # 1) 数据源说明
    data_sources_desc = _build_data_sources_desc(raw_text, ocr_text, has_layout)

    # 2) 数据融合规则
    data_fusion_rules = DATA_FUSION_RULES.format()

    # 3) 模块归属规则
    layout_hint = (
        "布局骨架定义了模块顺序和条目顺序，必须严格保持。"
        if has_layout
        else "没有布局骨架，请根据文本内容自行判断模块划分。"
    )
    section_mapping_rules = SECTION_MAPPING_RULES.format(has_layout_hint=layout_hint)

    # 4) Highlights 规则
    highlights_rules = HIGHLIGHTS_RULES.format()

    # 5) 嵌套规则
    nested_rules = NESTED_RULES.format()

    # 6) 技能规则
    skills_rules = SKILLS_RULES.format()

    # 7) 格式保留规则
    format_hint = (
        f"- 参考布局骨架中的 format 信息：{json.dumps(format_info, ensure_ascii=False)}"
        if format_info
        else "- 请根据文本内容自行判断格式特征"
    )
    format_rules = FORMAT_RULES.format(format_info_hint=format_hint)

    # 8) 数据内容
    primary_text = ocr_text if ocr_text else raw_text
    section_text = _split_text_by_headings(primary_text)
    data_content = _build_data_content(
        raw_text, ocr_text, layout, has_layout, section_text
    )

    # 9) 组装最终 prompt
    user_prompt = ASSEMBLER_PROMPT.format(
        data_sources_desc=data_sources_desc,
        data_fusion_rules=data_fusion_rules,
        section_mapping_rules=section_mapping_rules,
        highlights_rules=highlights_rules,
        nested_rules=nested_rules,
        skills_rules=skills_rules,
        format_rules=format_rules,
        data_content=data_content,
        schema=OUTPUT_SCHEMA,
    )

    # ---- 调用结构化模型（DashScope 兼容接口：deepseek-v* / qwen-* 同通道）----
    system_msg = SYSTEM_PROMPT.format()
    model_name = resolve_assembler_model(model)

    client = _get_client(model_name)
    response = client.chat.completions.create(
        model=model_name,
        messages=[
            {"role": "system", "content": system_msg},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.1,
        max_tokens=8000,
        extra_body=_thinking_off(model_name),
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("DeepSeek 未返回简历 JSON")
    parsed = _parse_json(content)
    if isinstance(parsed, dict):
        parsed = _normalize_highlights(parsed)
        # 确保 format 字段存在
        if "format" not in parsed:
            parsed["format"] = format_info
    return parsed


# ============ 两路并发结构化 ============
# 把 ~44s 单次压到 ~20s：EASY 组 与 EXP 组各看完整简历、只输出各自 section，并发执行。
# 关键：EXP 组（实习+项目）复用单次 assembler 那套「分类纪律」（SECTION_MAPPING_RULES 等），
# 否则拆开后 qwen 会把项目并入实习（实习7/项目0）——这是并行不稳的根因。
_FAST_PARALLEL_MIN_CHARS = 1000

# 实习+项目：边界模糊，必须整体判断，移植 assembler 的模块归属/highlights/嵌套规则
_EXP_INSTRUCT = (
    "只提取两类模块：【实习/工作经历 internships】和【项目经历 projects】，其它模块一律忽略（不要输出）。\n\n"
    "**实习 vs 项目的区分（关键，先判断再归类）：**\n"
    "- internships：在公司/组织/单位「任职」的经历，通常是 公司名 + 职位（如「腾讯｜后端开发实习生」）\n"
    "- projects：自己「做出来」的东西/作品/课题，通常是 项目名 + 角色（如「电商秒杀系统｜核心开发」）\n\n"
    + SECTION_MAPPING_RULES.format(has_layout_hint="没有布局骨架，按内容语义判断模块归属。")
    + "\n\n" + HIGHLIGHTS_RULES
    + "\n\n" + NESTED_RULES
)
_EXP_SCHEMA = (
    '{"internships":[{"title":"公司","subtitle":"职位","date":"时间","highlights":["工作内容,每条一项,保留原文**加粗**"]}],'
    '"projects":[{"title":"项目名","subtitle":"角色","date":"时间","description":"项目描述(可选)","highlights":["描述,每条一项,保留**加粗**"]}]}'
)

# 基本/教育/开源/技能/奖项：边界清晰，带上技能规则与「开源≠项目」提醒
_EASY_INSTRUCT = (
    "只提取这些模块：【基本信息、教育经历 education、开源经历 openSource、专业技能 skills、荣誉奖项 awards】，"
    "**不要提取实习和项目**（那两类由另一路处理）。\n"
    "- 标题含「开源」的模块 → openSource 数组，不要放到 projects。\n\n"
    + SKILLS_RULES.format()
)
_EASY_SCHEMA = (
    '{"name":"姓名","contact":{"phone":"电话","email":"邮箱","location":"地区"},"objective":"求职意向(无则空串)",'
    '"education":[{"title":"学校","subtitle":"专业","degree":"学位(本科/硕士/博士)","date":"时间","details":["荣誉/GPA/描述,每条一项"]}],'
    '"openSource":[{"title":"开源项目","subtitle":"角色/描述","date":"时间","items":["贡献"],"repoUrl":"仓库链接"}],'
    '"skills":[{"category":"类别(无则空串)","details":"技能描述,每行一项"}],'
    '"awards":["奖项,每项一条"]}'
)

_SECTION_KEYS = ("name", "contact", "objective", "education", "internships",
                 "projects", "openSource", "skills", "awards")


def _extract_sections(
    ocr_text: str, instruct: str, schema: str, model_name: str
) -> Dict[str, Any]:
    """从完整简历原文抽取指定分组的 section（带分类规则 + JSON mode + 一次重试）。"""
    base_user = (
        f"{instruct}\n\n"
        "只输出一个 JSON 对象（第一字符是 {），无数据的字段用空数组/空串，不要 markdown、不要解释。\n"
        f"输出格式：\n{schema}\n\n"
        f"简历原文：\n{ocr_text}"
    )
    client = _get_client(model_name)
    for attempt in range(2):
        user = base_user if attempt == 0 else (
            base_user + "\n\n【重要】请严格输出**合法** JSON：字符串内双引号转义、无多余逗号、不要截断。"
        )
        resp = client.chat.completions.create(
            model=model_name,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user},
            ],
            temperature=0.1,
            max_tokens=4000,
            response_format={"type": "json_object"},  # 约束解码，杜绝非法 JSON
            extra_body=_thinking_off(model_name),
        )
        try:
            parsed = _parse_json(resp.choices[0].message.content or "")
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            if attempt == 1:
                raise
    return {}


async def assemble_resume_data_fast(
    ocr_text: str, model: Optional[str] = None
) -> Dict[str, Any]:
    """OCR Markdown → 简历 JSON（异步）。

    默认走「两路并发结构化」：EASY 组（基本/教育/开源/技能/奖项）与 EXP 组（实习+项目）
    各看完整简历、只输出各自 section，并发执行，墙钟 ≈ 较慢的 EXP 组而非整份串行。
    EXP 组复用单次 assembler 的分类规则（SECTION_MAPPING/HIGHLIGHTS/NESTED），保证实习/项目
    分类稳定；EXP 组失败或全空时回退单次 assemble_resume_data，输出经 normalize_resume_json 与原一致。
    """
    import asyncio

    if not ocr_text or not ocr_text.strip():
        raise ValueError("OCR 文本为空")

    resolved = resolve_assembler_model(model)

    async def _serial() -> Dict[str, Any]:
        return await asyncio.to_thread(
            assemble_resume_data, ocr_text, {}, ocr_text, resolved
        )

    # 短简历分段无收益，直接单次
    if len(ocr_text) < _FAST_PARALLEL_MIN_CHARS:
        return await _serial()

    easy_r, exp_r = await asyncio.gather(
        asyncio.to_thread(_extract_sections, ocr_text, _EASY_INSTRUCT, _EASY_SCHEMA, resolved),
        asyncio.to_thread(_extract_sections, ocr_text, _EXP_INSTRUCT, _EXP_SCHEMA, resolved),
        return_exceptions=True,
    )

    # EXP（实习+项目）是核心且不可从 EASY 补，失败/全空 → 整体回退单次
    exp_ok = isinstance(exp_r, dict) and (exp_r.get("internships") or exp_r.get("projects"))
    if not exp_ok:
        # 之前这里静默回退，排查时无法区分「并发路径慢」和「回退到更慢的单次路径」。
        # 现在记录 EXP 组返回内容 + 是否异常，便于定位是超时、限流还是模型返回空。
        exp_detail = (
            f"exception={type(exp_r).__name__}: {str(exp_r)[:200]}"
            if isinstance(exp_r, Exception)
            else f"empty result keys={list(exp_r.keys()) if isinstance(exp_r, dict) else 'N/A'}"
        )
        easy_detail = (
            f"exception={type(easy_r).__name__}"
            if isinstance(easy_r, Exception)
            else f"keys={list(easy_r.keys()) if isinstance(easy_r, dict) else 'N/A'}"
        )
        logger.warning(
            "[结构化] EXP组为空或异常, 回退单次路径。exp=%s, easy=%s, ocr_chars=%d",
            exp_detail, easy_detail, len(ocr_text),
        )
        return await _serial()

    merged: Dict[str, Any] = {}
    for r in (easy_r, exp_r):
        if isinstance(r, dict):
            for k in _SECTION_KEYS:
                if k in r and r[k]:
                    merged[k] = r[k]

    merged = _normalize_highlights(merged)
    merged.setdefault("format", {})
    return merged
