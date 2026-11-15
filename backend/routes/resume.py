"""
简历相关路由
"""

import re
import json as _json
import os
import sys
import time
import asyncio
import threading
from pathlib import Path
from typing import Dict, Any, List, Optional
from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

# 统一导入方式：优先使用顶层模块，避免重复加载 backend.models
try:
    from models import (
        ResumeGenerateRequest,
        ResumeGenerateResponse,
        ResumeParseRequest,
        SectionParseRequest,
        RewriteRequest,
        ScoreRequest,
        ScoreResponse,
    )
    from llm import call_llm, call_llm_stream, DEFAULT_AI_PROVIDER
    from prompts import (
        build_resume_prompt,
        build_resume_markdown_prompt,
        build_rewrite_prompt,
        SECTION_PROMPTS,
    )
    from json_path import parse_path, get_by_path, set_by_path
    from chunk_processor import split_resume_text, merge_resume_chunks
    from parallel_chunk_processor import parse_resume_text_parallel
    from resume_text_preprocessor import normalize_pasted_resume_text
    from resume_parse_rules import RESUME_PARSE_EXTRA_RULES
    from config.parallel_config import get_parallel_config
    from prompt_templates import render_rewrite_text_prompt
    from backend.core.logger import get_logger, write_llm_debug
    from services.zhipu_layout import recognize_with_ocr
    from services.resume_assembler import assemble_resume_data, assemble_resume_data_fast
    from services.vision_ocr import image_to_text, SUPPORTED_IMAGE_TYPES
    from json_normalizer import normalize_resume_json
    from database import get_db
    from middleware.auth import AppUser, get_current_user
    from sqlalchemy.orm import Session
except ImportError:
    # 确保 backend 目录在 sys.path 中
    backend_dir = Path(__file__).resolve().parent.parent
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))

    from backend.models import (
        ResumeGenerateRequest,
        ResumeGenerateResponse,
        ResumeParseRequest,
        SectionParseRequest,
        RewriteRequest,
        ScoreRequest,
        ScoreResponse,
    )
    from backend.llm import call_llm, call_llm_stream, DEFAULT_AI_PROVIDER
    from backend.prompts import (
        build_resume_prompt,
        build_resume_markdown_prompt,
        build_rewrite_prompt,
        SECTION_PROMPTS,
    )
    from backend.json_path import parse_path, get_by_path, set_by_path
    from backend.chunk_processor import split_resume_text, merge_resume_chunks
    from backend.parallel_chunk_processor import parse_resume_text_parallel
    from backend.resume_text_preprocessor import normalize_pasted_resume_text
    from backend.resume_parse_rules import RESUME_PARSE_EXTRA_RULES
    from backend.config.parallel_config import get_parallel_config
    from backend.prompt_templates import render_rewrite_text_prompt
    from core.logger import get_logger, write_llm_debug
    from backend.services.zhipu_layout import recognize_with_ocr
    from backend.services.resume_assembler import assemble_resume_data, assemble_resume_data_fast
    from backend.services.vision_ocr import image_to_text, SUPPORTED_IMAGE_TYPES
    from backend.json_normalizer import normalize_resume_json
    from backend.database import get_db
    from backend.middleware.auth import AppUser, get_current_user
    from sqlalchemy.orm import Session

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["Resume"])

ROOT = Path(__file__).resolve().parents[2]
MAX_PDF_SIZE_MB = 10


class RewriteTextStreamRequest(BaseModel):
    """划词改写流式请求（不依赖完整 resume 结构）"""
    provider: Optional[str] = Field(default=None)
    text: str = Field(..., description="选中的原始文本")
    instruction: str = Field(..., description="改写指令")
    path: Optional[str] = Field(default=None, description="可选，来源字段路径")
    locale: str = Field(default="zh")


class RewriteIntentRequest(BaseModel):
    provider: Optional[str] = Field(default=None)
    text: str = Field(default="")
    instruction: str = Field(..., description="改写指令")
    path: Optional[str] = Field(default=None, description="可选，来源字段路径")
    locale: str = Field(default="zh")


class ChatMessage(BaseModel):
    role: str = Field(..., description="user 或 assistant")
    content: str = Field(..., description="消息内容")


class ChatStreamRequest(BaseModel):
    """轻量简历问答流式请求（供右下角悬浮 AI 助手使用）"""
    provider: Optional[str] = Field(default=None)
    messages: List[ChatMessage] = Field(default_factory=list, description="多轮对话历史，最后一条为用户最新提问")
    resume_context: Optional[str] = Field(default=None, description="可选，当前简历的精简文本，用于让回答贴合简历")
    locale: str = Field(default="zh")


class GrammarCheckRequest(BaseModel):
    """单字段语法/表达体检（不依赖完整 resume 结构）"""
    provider: Optional[str] = Field(default=None)
    text: str = Field(..., description="待检查的字段内容（纯文本或 HTML）")
    path: Optional[str] = Field(default=None, description="可选，来源字段路径，用于场景判断")
    locale: str = Field(default="zh")


def clean_llm_response(raw: str) -> str:
    """清理 LLM 返回的内容"""
    cleaned = re.sub(r"<\|begin_of_box\|>", "", raw)
    cleaned = re.sub(r"<\|end_of_box\|>", "", cleaned)
    cleaned = re.sub(r"```json\s*", "", cleaned)
    cleaned = re.sub(r"```\s*", "", cleaned)
    return cleaned.strip()


def parse_json_response(cleaned: str) -> Dict:
    """解析 JSON 响应"""
    try:
        return _json.loads(cleaned)
    except Exception:
        # 尝试提取 JSON 部分
        if cleaned.startswith("["):
            start = cleaned.find("[")
            end = cleaned.rfind("]")
        else:
            start = cleaned.find("{")
            end = cleaned.rfind("}")

        if start != -1 and end != -1 and end > start:
            return _json.loads(cleaned[start : end + 1])
        raise


def _rule_detect_rewrite_intents(instruction: str) -> tuple[list[str], float]:
    value = (instruction or "").strip().lower()
    if not value:
        return ["rewrite"], 0.0

    has_bold = ("加粗" in value) or ("加黑" in value) or ("bold" in value)
    wants_rewrite = (
        ("优化" in value)
        or ("润色" in value)
        or ("改写" in value)
        or ("更专业" in value)
        or ("更简洁" in value)
        or ("更有力" in value)
        or ("重写" in value)
    )
    if ("去掉加粗" in value) or ("取消加粗" in value) or ("不要加粗" in value) or ("remove bold" in value):
        return ["remove_bold"], 0.99
    if ("无序列表改成有序列表" in value) or ("无序改有序" in value) or ("改成有序列表" in value):
        return ["list_transform"], 0.98
    if has_bold and (
        ("全部" in value) or ("整段" in value) or ("全段" in value) or ("整体" in value) or ("通篇" in value) or ("所有" in value)
    ):
        return (["rewrite", "full_bold"] if wants_rewrite else ["full_bold"]), 0.97
    if has_bold and (
        ("一些" in value)
        or ("有些" in value)
        or ("部分" in value)
        or ("重点" in value)
        or ("关键词" in value)
        or ("你觉得" in value)
        or ("挑" in value)
        or ("该加粗" in value)
    ):
        return (["rewrite", "selective_bold"] if wants_rewrite else ["selective_bold"]), 0.95
    if has_bold:
        return (["rewrite", "full_bold"] if wants_rewrite else ["full_bold"]), 0.72
    return ["rewrite"], 0.9


def _llm_detect_rewrite_intent(
    *,
    provider: str,
    instruction: str,
    source_text: str,
    path_hint: str,
    locale: str,
) -> tuple[Optional[list[str]], float]:
    prompt = f"""你是一个文本编辑意图分类器。请基于用户指令判断意图类别。

可选意图：
1. full_bold：全部/整段加粗
2. selective_bold：选择性加粗（技术关键词、数字指标、重点词）
3. remove_bold：去掉加粗
4. list_transform：列表结构转换（如无序转有序）
5. rewrite：普通改写润色

输入信息：
- 语言: {locale}
- 路径: {path_hint}
- 用户指令: {instruction}
- 选中文本片段(可截断): {source_text[:600]}

只输出 JSON：
{{
  "intents": ["rewrite", "selective_bold"],
  "confidence": 0.0
}}
"""
    try:
        raw = call_llm(provider, prompt)
        cleaned = clean_llm_response(raw)
        data = parse_json_response(cleaned)
        raw_intents = data.get("intents")
        if not raw_intents and data.get("intent"):
            raw_intents = [data.get("intent")]
        intents = [str(i).strip() for i in (raw_intents or []) if str(i).strip()]
        confidence = float(data.get("confidence", 0.0))
        valid = {"full_bold", "selective_bold", "remove_bold", "list_transform", "rewrite"}
        normalized: list[str] = []
        for intent in intents:
            if intent in valid and intent not in normalized:
                normalized.append(intent)
        if normalized:
            return normalized, max(0.0, min(1.0, confidence))
    except Exception:
        return None, 0.0
    return None, 0.0


@router.post("/resume/rewrite-text/intent")
async def detect_rewrite_text_intent(body: RewriteIntentRequest):
    instruction = (body.instruction or "").strip()
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction 不能为空")

    provider = body.provider or DEFAULT_AI_PROVIDER
    source_text = (body.text or "").strip()
    path_hint = body.path or "selected_text"
    locale = body.locale or "zh"

    rule_intents, rule_confidence = _rule_detect_rewrite_intents(instruction)
    llm_intents, llm_confidence = await asyncio.to_thread(
        _llm_detect_rewrite_intent,
        provider=provider,
        instruction=instruction,
        source_text=source_text,
        path_hint=path_hint,
        locale=locale,
    )

    if llm_intents and llm_confidence >= 0.7:
        return {
            "intent": llm_intents[0],
            "intents": llm_intents,
            "confidence": llm_confidence,
            "source": "llm",
            "rule_intent": rule_intents[0],
            "rule_intents": rule_intents,
            "rule_confidence": rule_confidence,
            "llm_intent": llm_intents[0],
            "llm_intents": llm_intents,
            "llm_confidence": llm_confidence,
        }

    return {
        "intent": rule_intents[0],
        "intents": rule_intents,
        "confidence": rule_confidence,
        "source": "rule",
        "rule_intent": rule_intents[0],
        "rule_intents": rule_intents,
        "rule_confidence": rule_confidence,
        "llm_intent": (llm_intents[0] if llm_intents else None),
        "llm_intents": llm_intents,
        "llm_confidence": llm_confidence,
    }


def _build_resume_chat_prompt(*, messages: List[ChatMessage], resume_context: str, locale: str) -> str:
    history_text = "\n".join(
        f"{'用户' if m.role == 'user' else '助手'}：{m.content.strip()}" for m in messages
    )
    context_block = (
        f"\n\n【当前简历内容（供参考，回答需贴合，不要编造没有的经历或数据）】\n{resume_context.strip()[:4000]}"
        if resume_context and resume_context.strip()
        else ""
    )
    return f"""你是「简历助手」，一名资深中文简历顾问 + 求职教练，服务于一个简历编辑器里的用户。你的目标是用最少的话帮用户把简历改得更好、更容易拿到面试。

# 角色与边界
- 只处理简历、求职、自我表达、面试准备相关的话题；遇到明显无关的问题，一句话礼貌带回简历主题。
- 严格基于【当前简历内容】作答，不编造用户没有的经历、公司、数字或技能；信息不足时直接说"简历里没看到X，你可以补充"。

# 回答方式（按用户意图自适应）
- 用户在**提问/咨询**（如"我适合投什么岗""自我评价怎么写"）：先给一句直接结论，再用 2-4 个要点展开，必要时给一个可直接用的范例句。
- 用户要**评估/挑问题**（如"看看我项目经历有什么问题"）：按"亮点 / 待改进 / 具体改法"组织，针对简历里的真实内容点名指出。
- 用户要**改写某段文字**：直接输出改写后的成稿（可用），不要解释一大段；如能量化就补量化、用强动词、贴合目标岗位。

# 风格
- 用{locale}语言，专业但口语化，简洁直接，不说空话套话和免责声明。
- 默认简短；只有用户要"详细"时才展开。善用要点，不堆砌大段文字。{context_block}

【对话】
{history_text}
助手："""


def _build_grammar_check_prompt(*, text: str, path_hint: str, locale: str) -> str:
    return f"""你是一名资深简历写作教练。请对下面这段简历字段内容做"语法与表达体检"，找出可改进之处。

检查维度（type 取值）：
- grammar：语法错误、错别字、用词搭配错误
- wording：弱动词、平淡/口语化表达，可替换为更专业有力的措辞
- vague：含糊笼统、缺少信息量的描述
- quantify：缺少量化指标、可补充数字/结果的地方

严格要求：
1. 用与内容相同的语言输出（内容是中文就用中文）。
2. 每条 issue 的 "original" 必须是输入内容里**逐字出现的连续片段**（便于程序做精确替换），不要跨越标签、不要改写后再当原文。
3. 只标注**确实值得改**的问题，宁缺毋滥；没有问题就返回空数组。
4. "suggestion" 是该片段改进后的替换文本，需可直接替换原片段。
5. severity 取 high/medium/low；score 为该字段整体写作质量分（0-100，100=很好）。

输入信息：
- 语言：{locale}
- 字段路径：{path_hint or "未知"}
- 字段内容：
{text[:4000]}

只输出 JSON，不要任何额外文字或代码块标记：
{{
  "issues": [
    {{"original": "原片段", "suggestion": "改进后片段", "type": "wording", "severity": "medium"}}
  ],
  "summary": "一句话总体评价",
  "score": 80
}}
"""


@router.post("/resume/grammar-check")
async def grammar_check(body: GrammarCheckRequest):
    """单字段语法/表达体检：返回结构化 issues + 评分，供前端弹窗展示与一键修复。"""
    raw_text = (body.text or "").strip()
    if not raw_text:
        raise HTTPException(status_code=400, detail="text 不能为空")

    provider = body.provider or DEFAULT_AI_PROVIDER
    prompt = _build_grammar_check_prompt(
        text=raw_text,
        path_hint=body.path or "",
        locale=body.locale or "zh",
    )

    try:
        raw = await asyncio.to_thread(call_llm, provider, prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {e}")

    cleaned = clean_llm_response(raw)
    try:
        data = parse_json_response(cleaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析 JSON 失败: {e}")

    # 校验 LLM 输出（系统边界）：只保留 original 在原文中逐字出现、且与 suggestion 不同的条目
    valid_types = {"grammar", "wording", "vague", "quantify"}
    valid_severity = {"high", "medium", "low"}
    issues: list[dict] = []
    for item in (data.get("issues") or []):
        if not isinstance(item, dict):
            continue
        original = str(item.get("original", "")).strip()
        suggestion = str(item.get("suggestion", "")).strip()
        if not original or not suggestion or original == suggestion:
            continue
        if original not in raw_text:
            continue
        issue_type = str(item.get("type", "wording")).strip()
        severity = str(item.get("severity", "medium")).strip()
        issues.append({
            "original": original,
            "suggestion": suggestion,
            "type": issue_type if issue_type in valid_types else "wording",
            "severity": severity if severity in valid_severity else "medium",
        })

    score = data.get("score")
    try:
        score = max(0, min(100, int(score)))
    except (TypeError, ValueError):
        score = None

    return {
        "issues": issues,
        "summary": str(data.get("summary", "")).strip(),
        "score": score,
    }


class JdOptimizeField(BaseModel):
    key: str = Field(..., description="字段唯一标识，如 selfEvaluation / experience:<id>")
    label: str = Field(default="", description="字段展示名")
    content: str = Field(default="", description="字段当前内容（纯文本或 HTML）")


class JdOptimizeRequest(BaseModel):
    """针对 JD 的简历优化（无状态，多字段）"""
    provider: Optional[str] = Field(default=None)
    jd_text: str = Field(..., description="目标职位 JD 文本")
    fields: list[JdOptimizeField] = Field(default_factory=list)
    locale: str = Field(default="zh")


class JdKeywordIntegrateRequest(BaseModel):
    """把某个 JD 缺失关键词自然融入最相关的简历字段（无状态，多字段）"""
    provider: Optional[str] = Field(default=None)
    keyword: str = Field(..., description="待融入的 JD 关键词")
    jd_text: str = Field(default="", description="目标岗位 JD 文本，作为融入语境参考")
    fields: list[JdOptimizeField] = Field(default_factory=list)
    locale: str = Field(default="zh")


class TranslateRequest(BaseModel):
    """简历多字段翻译（复用 JdOptimizeField 的 key/label/content 形状）"""
    provider: Optional[str] = Field(default=None)
    target_lang: str = Field(..., description="目标语言代码，如 en/zh/ja/ko")
    fields: list[JdOptimizeField] = Field(default_factory=list)
    locale: str = Field(default="zh")


class HealthCheckRequest(BaseModel):
    """通用简历体检（无需 JD，多字段）"""
    provider: Optional[str] = Field(default=None)
    fields: list[JdOptimizeField] = Field(default_factory=list)
    locale: str = Field(default="zh")


def _build_health_check_prompt(*, fields: list[JdOptimizeField], locale: str) -> str:
    try:
        from backend.ai_phrase_blacklist import build_ai_phrase_check_block
    except ImportError:
        from ai_phrase_blacklist import build_ai_phrase_check_block
    ai_check_block = build_ai_phrase_check_block()
    fields_block = "\n".join(
        f'- key={f.key}｜{f.label or f.key}：{(f.content or "")[:1200]}' for f in fields
    )
    return f"""你是一名资深简历顾问。请对下面这份简历做一次"通用质量体检"（不依赖任何 JD），按维度打分并给出可落地的改进建议。

评分维度（dimension 固定用这些名称）：
- 完整度：关键模块与信息是否齐全
- 表达质量：用词是否专业有力、是否避免空话套话
- 量化成果：是否用数字/结果证明价值
- 关键词丰富度：是否覆盖目标方向的技术/能力关键词
- 格式规范：结构、长度、表达是否清晰规范

体检纪律（打分与建议都要执行）：
- 六秒门：只看基本信息与排在最前的内容模块，六秒内能否看出目标角色、最强技术栈/领域、至少一个量化成果；看不出→在「完整度」「格式规范」酌情扣分，并给出把最强证据前置的建议。
- 技术岗从严（仅当从内容判断求职方向为研发/算法/数据/测试/运维等技术岗时启用，非技术岗不套用）：技能须标注掌握程度分级（熟练掌握/熟悉/了解）并落到框架与深度，笼统的「熟悉 Java」算扣分点；项目须有能支撑面试追问（动机→方案→难点→数据效果）的技术亮点；量化须落到具体业务/性能指标（QPS/耗时/DAU/留存/转化率等）；表述不清视为硬伤重扣。
- 应届/社招分口径：从教育时间线与经历年限判断候选人属应届（校招）还是社招——应届重潜力与基础（竞赛/课程/实习可补位），社招重即战力与业务结果；按对应口径打分与给建议，不混用。
{ai_check_block}

简历字段（每条含唯一 key）：
{fields_block}

严格要求：
1. 用{locale}语言输出。
2. 每个维度给 0-100 的 score 和一句话 comment；overallScore 为整体分（0-100）。
3. suggestions 给具体改写建议：original 必须是某字段里**逐字出现的连续片段**（便于程序精确替换），suggested 为改进后片段，reason 说明为何更好；只给确有价值的，宁缺毋滥。
4. 不编造经历或数据。

只输出 JSON，不要任何额外文字或代码块：
{{
  "overallScore": 0,
  "dimensions": [{{"dimension": "完整度", "score": 0, "comment": "..."}}],
  "suggestions": [{{"key": "字段key", "original": "原片段", "suggested": "改进后片段", "reason": "为何更好"}}],
  "summary": "一句话总体评价"
}}
"""


_TRANSLATE_LANG_NAMES = {
    "en": "英语", "zh": "中文", "ja": "日语", "ko": "韩语",
    "fr": "法语", "de": "德语", "es": "西班牙语", "pt": "葡萄牙语", "ru": "俄语",
}


def _build_translate_prompt(*, target_lang: str, fields: list[JdOptimizeField]) -> str:
    lang_name = _TRANSLATE_LANG_NAMES.get(target_lang, target_lang)
    fields_block = "\n".join(
        f'- key={f.key}｜{f.label or f.key}：{(f.content or "")[:1500]}' for f in fields
    )
    return f"""你是一名专业的简历翻译。请把下列简历字段内容翻译成{lang_name}。

严格要求：
1. 忠实翻译，保留数字与量化指标；技术名词/公司名按行业惯例处理。
2. 完整保留每个字段原有的 HTML 标签结构（如 <strong>、<ul>、<li>、<p>），只翻译标签之间的文字；<strong> 等强调标签必须套在对应的译词上，不得丢失加粗。
3. 翻译要地道、符合目标语言的简历表达习惯，不逐字硬译；不新增或删减信息。

待翻译字段（每条含唯一 key）：
{fields_block}

只输出 JSON，不要任何额外文字或代码块：
{{"translations": [{{"key": "字段key", "translated": "翻译后的内容（保留 HTML 标签）"}}]}}
"""


def _build_jd_optimize_prompt(*, jd_text: str, fields: list[JdOptimizeField], locale: str) -> str:
    fields_block = "\n".join(
        f'- key={f.key}｜{f.label or f.key}：{(f.content or "")[:1200]}' for f in fields
    )
    return f"""你是一名资深简历顾问。请基于目标岗位 JD，给出让简历更匹配该岗位的改写建议。

目标岗位 JD：
{jd_text[:2500]}

候选人简历字段（每条含唯一 key）：
{fields_block}

严格要求：
1. 用与简历相同的语言输出（中文内容就用中文）。
2. 每条建议针对某个字段：给出该字段内**逐字出现的连续原片段** original 与改进后 suggested（自然融入 JD 关键词、更贴合岗位、突出量化成果），original 必须能在对应 key 的内容里精确匹配以便程序替换。
3. 只给**确有价值**的建议，宁缺毋滥；不要编造经历、不得脱离原文事实。
4. keywordMatches 列出 JD 要求且简历**已命中**的关键词；missingKeywords 列出 JD 要求但简历**明显缺失**的关键词（两者不重叠）。
5. matchScore 为当前简历与 JD 的总体匹配度（0-100）。
6. atsScore 为简历对 ATS（招聘方简历筛选系统）的兼容/通过度（0-100）：关键词覆盖、术语规范、可被机器解析的清晰表述越好分越高。
7. 关键词改写铁律：**绝不添加候选人不具备的技能**——只用 JD 的原词重述简历里真实存在的经历。范式（同一事实换用 JD 词汇）：JD 说「RAG 检索管线」、简历写「基于向量检索的 LLM 工作流」→ 改成「RAG 检索管线设计与 LLM 编排」。
8. 关键词落位优先级：目标关键词优先落到 ①摘要/自我评价前部 ②最相关经历的**第一条要点** ③技能区；不要生硬堆进无关段落。
9. atsChecklist 逐条输出 ATS 兼容检查。status 取值：pass=达标 / fail=不达标（note 写怎么改）/ template=由本产品 LaTeX 模板天然保证。必查项：标准小标题命名、关键词覆盖摘要、关键词落位经历首条要点、技能区覆盖目标关键词、表述可被机器解析（无图片文字/生僻符号）；「单栏布局」「无嵌套表格」「正文文本可选中」三项直接输出 status=template。

只输出 JSON，不要任何额外文字或代码块：
{{
  "matchScore": 0,
  "atsScore": 0,
  "keywordMatches": ["..."],
  "missingKeywords": ["..."],
  "atsChecklist": [
    {{"item": "检查项", "status": "pass|fail|template", "note": "一句话说明"}}
  ],
  "suggestions": [
    {{"key": "字段key", "original": "原片段", "suggested": "改进后片段", "reason": "为何更匹配JD"}}
  ]
}}
"""


@router.post("/resume/jd-optimize")
async def jd_optimize(body: JdOptimizeRequest):
    """针对 JD 给出多字段优化建议（结构化），供前端弹窗展示与逐条/一键应用。"""
    jd = (body.jd_text or "").strip()
    if not jd:
        raise HTTPException(status_code=400, detail="jd_text 不能为空")
    fields = [f for f in (body.fields or []) if (f.content or "").strip()]
    if not fields:
        raise HTTPException(status_code=400, detail="没有可优化的字段内容")

    provider = body.provider or DEFAULT_AI_PROVIDER
    prompt = _build_jd_optimize_prompt(jd_text=jd, fields=fields, locale=body.locale or "zh")

    try:
        raw = await asyncio.to_thread(call_llm, provider, prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {e}")

    cleaned = clean_llm_response(raw)
    try:
        data = parse_json_response(cleaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析 JSON 失败: {e}")

    # 校验 LLM 输出（系统边界）：original 必须逐字命中对应字段内容
    content_by_key = {f.key: (f.content or "") for f in fields}
    suggestions: list[dict] = []
    for item in (data.get("suggestions") or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        original = str(item.get("original", "")).strip()
        suggested = str(item.get("suggested", "")).strip()
        if not key or key not in content_by_key:
            continue
        if not original or not suggested or original == suggested:
            continue
        if original not in content_by_key[key]:
            continue
        suggestions.append({
            "key": key,
            "original": original,
            "suggested": suggested,
            "reason": str(item.get("reason", "")).strip(),
        })

    missing = [str(k).strip() for k in (data.get("missingKeywords") or []) if str(k).strip()]
    matched = [str(k).strip() for k in (data.get("keywordMatches") or []) if str(k).strip()]

    def _clamp_score(value):
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return None

    checklist = []
    for item in (data.get("atsChecklist") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("item", "")).strip()
        status = str(item.get("status", "")).strip()
        if name and status in {"pass", "fail", "template"}:
            checklist.append({
                "item": name,
                "status": status,
                "note": str(item.get("note", "")).strip(),
            })

    return {
        "matchScore": _clamp_score(data.get("matchScore")),
        "atsScore": _clamp_score(data.get("atsScore")),
        "keywordMatches": matched,
        "missingKeywords": missing,
        "atsChecklist": checklist,
        "suggestions": suggestions,
    }


def _build_jd_keyword_integrate_prompt(*, keyword: str, jd_text: str, fields: list[JdOptimizeField]) -> str:
    fields_block = "\n".join(
        f'- key={f.key}｜{f.label or f.key}：{(f.content or "")[:1200]}' for f in fields
    )
    jd_block = f"目标岗位 JD（语境参考）：\n{jd_text[:1500]}\n\n" if jd_text else ""
    return f"""你是一名资深简历顾问。下面这个 JD 关键词在候选人简历中缺失，请把它**自然地融入最相关的一条经历**。

待融入关键词：{keyword}

{jd_block}候选人简历字段（每条含唯一 key）：
{fields_block}

严格要求：
1. 用与简历相同的语言输出（中文内容就用中文）。
2. 只挑**一个最相关**的字段：给出该字段内**逐字出现的连续原片段** original，与融入关键词后的 suggested；original 必须能在对应 key 的内容里精确匹配以便程序替换。
3. 融入要自然贴合上下文、与已有事实一致，**不得编造**未发生的经历或数据；若该关键词无法真实自然地融入任何字段，则返回空对象 {{}}。
4. suggested 应当真实体现该关键词或其等价表述，并尽量保留原片段的量化与结果。
5. 改写铁律：绝不添加候选人不具备的技能——只是**换用 JD 的原词重述真实经历**（范式：简历写「基于向量检索的 LLM 工作流」、JD 说「RAG 检索管线」→「RAG 检索管线设计与 LLM 编排」）。
6. 落位优先级：优先融入 ①最相关经历的第一条要点 ②技能区 ③摘要前部；同等相关时选更靠前的位置。

只输出 JSON，不要任何额外文字或代码块：
{{"key": "字段key", "original": "原片段", "suggested": "融入关键词后的片段", "reason": "为何这样融入更匹配JD"}}
"""


@router.post("/resume/jd-keyword-integrate")
async def jd_keyword_integrate(body: JdKeywordIntegrateRequest):
    """把某个 JD 缺失关键词自然融入最相关的字段，返回可确定性替换的 original/suggested。"""
    keyword = (body.keyword or "").strip()
    if not keyword:
        raise HTTPException(status_code=400, detail="keyword 不能为空")
    fields = [f for f in (body.fields or []) if (f.content or "").strip()]
    if not fields:
        raise HTTPException(status_code=400, detail="没有可融入的字段内容")

    provider = body.provider or DEFAULT_AI_PROVIDER
    prompt = _build_jd_keyword_integrate_prompt(keyword=keyword, jd_text=(body.jd_text or "").strip(), fields=fields)

    try:
        raw = await asyncio.to_thread(call_llm, provider, prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {e}")

    cleaned = clean_llm_response(raw)
    try:
        data = parse_json_response(cleaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析 JSON 失败: {e}")

    # 校验 LLM 输出（系统边界）：original 必须逐字命中对应字段内容
    content_by_key = {f.key: (f.content or "") for f in fields}
    key = str(data.get("key", "")).strip()
    original = str(data.get("original", "")).strip()
    suggested = str(data.get("suggested", "")).strip()
    ok = (
        key in content_by_key
        and original and suggested and original != suggested
        and original in content_by_key[key]
    )
    if not ok:
        return {"integrated": False, "keyword": keyword}

    return {
        "integrated": True,
        "keyword": keyword,
        "key": key,
        "original": original,
        "suggested": suggested,
        "reason": str(data.get("reason", "")).strip(),
    }


@router.post("/resume/translate")
async def translate_resume_fields(body: TranslateRequest):
    """简历多字段翻译：逐字段返回 original/translated，供前端预览并写回。"""
    target = (body.target_lang or "").strip()
    if not target:
        raise HTTPException(status_code=400, detail="target_lang 不能为空")
    fields = [f for f in (body.fields or []) if (f.content or "").strip()]
    if not fields:
        raise HTTPException(status_code=400, detail="没有可翻译的字段内容")

    provider = body.provider or DEFAULT_AI_PROVIDER

    # 逐字段翻译并发执行：每次调用输出受单字段约束（避免单次响应过大），
    # 用信号量限并发 + to_thread 把同步 call_llm 丢到线程，gather 保持字段顺序。
    sem = asyncio.Semaphore(5)

    async def translate_one(f: JdOptimizeField):
        async with sem:
            prompt = _build_translate_prompt(target_lang=target, fields=[f])
            try:
                raw = await asyncio.to_thread(call_llm, provider, prompt)
                data = parse_json_response(clean_llm_response(raw))
            except Exception:
                return None
            for item in (data.get("translations") or []):
                if isinstance(item, dict) and str(item.get("key", "")).strip() == f.key:
                    translated = str(item.get("translated", "")).strip()
                    if translated:
                        return {"key": f.key, "original": f.content or "", "translated": translated}
            return None

    results = await asyncio.gather(*[translate_one(f) for f in fields])
    translations = [r for r in results if r]

    # 全部失败才视为接口错误，部分成功正常返回
    if not translations and fields:
        raise HTTPException(status_code=500, detail="翻译失败，请重试")

    return {"translations": translations}


@router.post("/resume/health-check")
async def resume_health_check(body: HealthCheckRequest):
    """通用简历体检（无需 JD）：维度评分 + 逐条可应用建议。"""
    fields = [f for f in (body.fields or []) if (f.content or "").strip()]
    if not fields:
        raise HTTPException(status_code=400, detail="没有可体检的字段内容")

    provider = body.provider or DEFAULT_AI_PROVIDER
    prompt = _build_health_check_prompt(fields=fields, locale=body.locale or "zh")

    try:
        raw = await asyncio.to_thread(call_llm, provider, prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {e}")

    cleaned = clean_llm_response(raw)
    try:
        data = parse_json_response(cleaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析 JSON 失败: {e}")

    def _clamp(value):
        try:
            return max(0, min(100, int(value)))
        except (TypeError, ValueError):
            return None

    dimensions: list[dict] = []
    for item in (data.get("dimensions") or []):
        if not isinstance(item, dict):
            continue
        name = str(item.get("dimension", "")).strip()
        if not name:
            continue
        dimensions.append({
            "dimension": name,
            "score": _clamp(item.get("score")),
            "comment": str(item.get("comment", "")).strip(),
        })

    content_by_key = {f.key: (f.content or "") for f in fields}
    suggestions: list[dict] = []
    for item in (data.get("suggestions") or []):
        if not isinstance(item, dict):
            continue
        key = str(item.get("key", "")).strip()
        original = str(item.get("original", "")).strip()
        suggested = str(item.get("suggested", "")).strip()
        if not key or key not in content_by_key:
            continue
        if not original or not suggested or original == suggested:
            continue
        if original not in content_by_key[key]:
            continue
        suggestions.append({
            "key": key,
            "original": original,
            "suggested": suggested,
            "reason": str(item.get("reason", "")).strip(),
        })

    return {
        "overallScore": _clamp(data.get("overallScore")),
        "dimensions": dimensions,
        "suggestions": suggestions,
        "summary": str(data.get("summary", "")).strip(),
    }


@router.post("/resume/generate", response_model=ResumeGenerateResponse)
async def generate_resume(body: ResumeGenerateRequest):
    """一句话 → 结构化简历 JSON"""
    prompt = build_resume_prompt(body.instruction, body.locale)
    try:
        raw = await asyncio.to_thread(call_llm, body.provider, prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {e}")

    cleaned = clean_llm_response(raw)

    # 修复常见的 JSON 格式错误
    cleaned = re.sub(r'\]\}\s*,\s*"', ']}}, "', cleaned)
    cleaned = re.sub(r'\]\}\s*,\s*(["\}])', r"]} \1", cleaned)
    cleaned = re.sub(r'\]\s*,\s*(["\}])', r"] \1", cleaned)
    cleaned = re.sub(r'\]\s+""([a-zA-Z_]+)"', r'], "\1"', cleaned)
    cleaned = re.sub(r'\]\s+"([a-zA-Z_]+)"\s*:', r'], "\1":', cleaned)
    cleaned = re.sub(r'\]\}\s+"([a-zA-Z_]+)"\s*:', r']}, "\1":', cleaned)

    try:
        data = parse_json_response(cleaned)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"解析 JSON 失败: {e}")

    return ResumeGenerateResponse(resume=data, provider=body.provider)


@router.post("/resume/generate/stream")
async def generate_resume_stream(body: ResumeGenerateRequest):
    """流式生成简历 - 输出 Markdown 格式，最后返回 JSON"""
    import asyncio

    # 生成 Markdown 的提示词
    markdown_prompt = build_resume_markdown_prompt(body.instruction, body.locale)

    # 生成 JSON 的提示词（用于最后返回结构化数据）
    json_prompt = build_resume_prompt(body.instruction, body.locale)

    async def generate():
        """生成 SSE 流"""
        full_markdown = ""

        try:
            # 流式输出 Markdown
            for chunk in call_llm_stream(body.provider, markdown_prompt):
                full_markdown += chunk
                yield f"data: {_json.dumps({'type': 'markdown', 'content': chunk}, ensure_ascii=False)}\n\n"
                # 关键：让出控制权，强制 uvicorn 立即发送数据
                await asyncio.sleep(0)

            # Markdown 输出完成，开始生成 JSON
            yield f"data: {_json.dumps({'type': 'status', 'content': 'parsing'}, ensure_ascii=False)}\n\n"

            # 调用 LLM 生成 JSON
            raw_json = await asyncio.to_thread(call_llm, body.provider, json_prompt)
            cleaned = clean_llm_response(raw_json)

            # 修复常见的 JSON 格式错误
            import re

            cleaned = re.sub(r'\]\}\s*,\s*"', ']}}, "', cleaned)
            cleaned = re.sub(r'\]\}\s*,\s*(["\}])', r"]} \1", cleaned)
            cleaned = re.sub(r'\]\s*,\s*(["\}])', r"] \1", cleaned)
            cleaned = re.sub(r'\]\s+""([a-zA-Z_]+)"', r'], "\1"', cleaned)
            cleaned = re.sub(r'\]\s+"([a-zA-Z_]+)"\s*:', r'], "\1":', cleaned)
            cleaned = re.sub(r'\]\}\s+"([a-zA-Z_]+)"\s*:', r']}, "\1":', cleaned)

            resume_data = parse_json_response(cleaned)

            # 发送完整的 JSON 数据
            yield f"data: {_json.dumps({'type': 'json', 'content': resume_data}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/resume/parse")
async def parse_resume_text(body: ResumeParseRequest):
    """AI 解析简历文本 → 结构化简历 JSON（支持并行分块处理）"""
    body_text = normalize_pasted_resume_text(body.text)
    # 使用 print 和 logger 双重记录，确保能看到日志
    print("========== 收到解析请求 ==========", file=sys.stderr, flush=True)
    print(f"文本长度: {len(body_text)} 字符", file=sys.stderr, flush=True)
    logger.info("========== 收到解析请求 ==========")
    logger.info(f"文本长度: {len(body_text)} 字符")

    provider = body.provider or DEFAULT_AI_PROVIDER
    print(f"Provider: {provider}", file=sys.stderr, flush=True)
    logger.info(f"Provider: {provider}")

    # 获取并行处理配置
    config = get_parallel_config(provider)
    use_parallel = getattr(body, "use_parallel", config.get("enabled", True))
    print(
        f"use_parallel: {use_parallel}, enabled: {config.get('enabled')}",
        file=sys.stderr,
        flush=True,
    )
    logger.info(f"use_parallel: {use_parallel}, enabled: {config.get('enabled')}")

    chunk_threshold = config.get("chunk_threshold", 500)
    serial_body = body.model_copy(update={"text": body_text})
    print(
        f"chunk_threshold: {chunk_threshold}, text_length: {len(body_text)}",
        file=sys.stderr,
        flush=True,
    )
    if use_parallel and len(body_text) > chunk_threshold:
        print("========== 并行处理开始 ==========", file=sys.stderr, flush=True)
        print(f"文本长度: {len(body_text)} 字符", file=sys.stderr, flush=True)
        print(f"阈值: {chunk_threshold} 字符", file=sys.stderr, flush=True)
        print(
            f"配置: max_concurrent={config.get('max_concurrent')}, max_chunk_size={config.get('max_chunk_size')}",
            file=sys.stderr,
            flush=True,
        )
        logger.info("========== 并行处理开始 ==========")
        logger.info(f"文本长度: {len(body_text)} 字符")
        logger.info(f"阈值: {chunk_threshold} 字符")
        logger.info(
            f"配置: max_concurrent={config.get('max_concurrent')}, max_chunk_size={config.get('max_chunk_size')}"
        )
        import time

        parallel_start = time.time()
        try:
            # 使用异步并行处理
            short_data = await parse_resume_text_parallel(
                text=body_text,
                provider=provider,
                max_concurrent=config.get("max_concurrent"),
                max_chunk_size=config.get("max_chunk_size", 300),
                model=getattr(body, "model", None),
            )
            parallel_elapsed = time.time() - parallel_start
            logger.info(f"✅ 并行处理成功！总耗时: {parallel_elapsed:.2f}秒")
            logger.info("========== 并行处理结束 ==========")
        except Exception as e:
            import traceback

            parallel_elapsed = time.time() - parallel_start
            logger.error(f"❌ 并行处理失败，耗时: {parallel_elapsed:.2f}秒")
            logger.error(f"错误信息: {str(e)}")
            logger.error(f"错误详情:\n{traceback.format_exc()}")
            logger.warning("回退到串行模式...")
            # 回退到原有的串行处理
            result = await _parse_resume_serial(serial_body)
            if isinstance(result, dict) and "resume" in result:
                return result
            else:
                # 处理标准化数据格式
                normalized_data = result.get("data", result)
                data = {
                    "name": normalized_data.get("name", ""),
                    "contact": normalized_data.get(
                        "contact", {"phone": "", "email": ""}
                    ),
                    "objective": normalized_data.get("objective", ""),
                    "education": normalized_data.get("education", []),
                    "internships": normalized_data.get("internships", []),
                    "projects": normalized_data.get("projects", []),
                    "openSource": normalized_data.get("openSource", []),
                    "skills": normalized_data.get("skills", []),
                    "awards": normalized_data.get("awards", []),
                }
                return {"resume": data, "provider": provider}
    else:
        # 短文本或禁用并行时，使用原有的处理方式
        if len(body_text) > config.get("chunk_threshold", 500):
            logger.info(f"文本长度 {len(body_text)}，使用串行分块处理")
        result = await _parse_resume_serial(serial_body)
        if isinstance(result, dict) and "resume" in result:
            return result
        else:
            # 处理标准化数据格式
            normalized_data = result.get("data", result)
            data = {
                "name": normalized_data.get("name", ""),
                "contact": normalized_data.get("contact", {"phone": "", "email": ""}),
                "objective": normalized_data.get("objective", ""),
                "education": normalized_data.get("education", []),
                "internships": normalized_data.get("internships", []),
                "projects": normalized_data.get("projects", []),
                "openSource": normalized_data.get("openSource", []),
                "skills": normalized_data.get("skills", []),
                "awards": normalized_data.get("awards", []),
            }
            return {"resume": data, "provider": provider}

    # 额外的数据清理和标准化
    try:
        from json_normalizer import normalize_resume_json

        normalized_data = normalize_resume_json(short_data)
    except Exception as e:
        print(f"[解析] 数据标准化失败: {e}", file=sys.stderr, flush=True)
        normalized_data = short_data

    # 统一返回格式：与串行处理保持一致
    data = {
        "name": normalized_data.get("name", ""),
        "contact": normalized_data.get("contact", {"phone": "", "email": ""}),
        "objective": normalized_data.get("objective", ""),
        "education": normalized_data.get("education", []),
        "internships": normalized_data.get("internships", []),
        "projects": normalized_data.get("projects", []),
        "openSource": normalized_data.get("openSource", []),
        "skills": normalized_data.get("skills", []),
        "awards": normalized_data.get("awards", []),
    }
    return {"resume": data, "provider": provider}


@router.post("/resume/upload-pdf")
async def upload_resume_pdf(
    file: UploadFile = File(...),
    model: Optional[str] = Form(default=None),
    provider: Optional[str] = Form(default=None),
):
    """
    上传 PDF 简历并解析为结构化简历 JSON。

    数据流（单路 OCR + 分段并行结构化）：
    1. glm-ocr：PDF → Markdown（高质量 OCR + 结构识别，唯一数据源，失败直接 502）
    2. 结构化：OCR Markdown → 简历 JSON（默认按 section 分段并行，qwen-plus-latest）

    说明：glm-ocr 的 Markdown 已含完整结构信息（标题层级、列表、嵌套），
    移除了原 MinerU 本地解析（服务器无 GPU、CPU 冷启动 30-60s，收益为负）。
    """
    import time

    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="仅支持 PDF 文件")

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail="文件为空")

    if len(pdf_bytes) > MAX_PDF_SIZE_MB * 1024 * 1024:
        raise HTTPException(
            status_code=413, detail=f"文件过大，最大支持 {MAX_PDF_SIZE_MB}MB"
        )

    total_start = time.time()

    # ========== 步骤1: glm-ocr 单路提取（失败直接 502，不再兜底 MinerU） ==========
    step1_start = time.time()
    try:
        ocr_text = await asyncio.to_thread(recognize_with_ocr, pdf_bytes)
    except Exception as e:
        logger.warning(f"[PDF解析] glm-ocr 失败: {e}")
        raise HTTPException(status_code=502, detail=f"PDF 识别失败，请稍后重试: {e}")
    if not ocr_text or not ocr_text.strip():
        raise HTTPException(status_code=422, detail="未识别到文字，请换清晰的 PDF")
    step1_time = time.time() - step1_start
    logger.info(f"[PDF解析] 步骤1 glm-ocr 完成: {step1_time:.2f}s, {len(ocr_text)}字符")

    # ========== 步骤2: 结构化（分段并行，回退单次） ==========
    step2_start = time.time()
    try:
        resume_data = await assemble_resume_data_fast(ocr_text, model=model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"简历结构化失败: {e}")
    step2_time = time.time() - step2_start
    logger.info(f"[PDF解析] 步骤2 结构化完成: {step2_time:.2f}s")

    total_time = time.time() - total_start
    logger.info(
        f"[PDF解析] 总耗时: {total_time:.2f}s (OCR: {step1_time:.2f}s, 结构化: {step2_time:.2f}s)"
    )

    try:
        from backend.json_normalizer import normalize_resume_json
    except ImportError:
        from json_normalizer import normalize_resume_json

    try:
        normalized = normalize_resume_json(resume_data)
        return {"resume": normalized, "provider": "glm-ocr"}
    except Exception as e:
        logger.warning(f"JSON 标准化失败: {e}")
        return {"resume": resume_data, "provider": "glm-ocr"}


MAX_IMAGE_COUNT = 2
IMAGE_STREAM_HEARTBEAT_INTERVAL = 15.0


async def _validate_and_read_uploaded_images(
    files: List[UploadFile],
) -> list[tuple[bytes, str]]:
    """校验并读取上传的图片字节，避免在 StreamingResponse 启动后才报 400/413。"""
    if not files:
        raise HTTPException(status_code=400, detail="请上传图片")
    if len(files) > MAX_IMAGE_COUNT:
        raise HTTPException(
            status_code=400, detail=f"最多支持 {MAX_IMAGE_COUNT} 张图片"
        )

    payloads: list[tuple[bytes, str]] = []
    for f in files:
        if f.content_type not in SUPPORTED_IMAGE_TYPES:
            raise HTTPException(status_code=400, detail="仅支持 JPG / PNG 图片")
        image_bytes = await f.read()
        if not image_bytes:
            raise HTTPException(status_code=400, detail="文件为空")
        if len(image_bytes) > MAX_PDF_SIZE_MB * 1024 * 1024:
            raise HTTPException(
                status_code=413, detail=f"单张图片过大，最大支持 {MAX_PDF_SIZE_MB}MB"
            )
        payloads.append((image_bytes, f.content_type))
    return payloads


def _normalize_uploaded_resume(resume_data: dict, label: str = "图片解析") -> dict:
    try:
        return normalize_resume_json(resume_data)
    except Exception as e:
        logger.warning(f"{label} JSON 标准化失败: {e}")
        return resume_data


@router.post("/resume/upload-image")
async def upload_resume_image(
    files: List[UploadFile] = File(...),
    model: str = Form(default="glm-ocr"),
):
    """上传简历图片(JPG/PNG，最多 2 张)，经视觉模型识别 + 结构化为简历 JSON。

    多张图片按顺序识别后合并文本再结构化（适用于两页简历分两张图）。
    与 /resume/upload-pdf 同构返回 {"resume": ...}。
    视觉模型由前端传入：glm-ocr（默认，实测比 qwen-vl-max 快约 5 倍）/ qwen-vl-max。
    """
    payloads = await _validate_and_read_uploaded_images(files)

    # 步骤1：逐张图片 → 文本（线程池卸载同步 OCR，避免阻塞事件循环）
    texts = []
    for image_bytes, content_type in payloads:
        try:
            text_piece = await run_in_threadpool(
                image_to_text, image_bytes, content_type, model
            )
            texts.append(text_piece)
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"图片识别失败: {e}")

    ocr_text = "\n\n".join(t for t in texts if t.strip())
    if not ocr_text.strip():
        raise HTTPException(status_code=422, detail="未识别到文字，请换清晰的图片")

    # 步骤2：文本 → 结构化简历（复用 PDF 同款：分段并行 + qwen-plus-latest，失败回退单次）
    try:
        resume_data = await assemble_resume_data_fast(ocr_text, model=None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"简历结构化失败: {e}")

    normalized = _normalize_uploaded_resume(resume_data, "图片解析")
    return {"resume": normalized, "provider": model}


@router.post("/resume/upload-image/stream")
async def upload_resume_image_stream(
    files: List[UploadFile] = File(...),
    model: str = Form(default="glm-ocr"),
):
    """流式上传并解析简历图片（SSE 阶段状态 + 15s 心跳保活，防止反代 100s 空闲断连）。"""
    payloads = await _validate_and_read_uploaded_images(files)

    def _sse(payload: dict | str) -> str:
        if isinstance(payload, str):
            return f"data: {payload}\n\n"
        return f"data: {_json.dumps(payload, ensure_ascii=False)}\n\n"

    async def generate():
        started_at = time.time()
        state = {"stage": "ocr"}
        event_queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

        async def _run_pipeline():
            try:
                total = len(payloads)
                texts: list[str] = []
                for idx, (image_bytes, content_type) in enumerate(payloads, start=1):
                    await event_queue.put(
                        _sse(
                            {
                                "type": "status",
                                "stage": "ocr",
                                "image_index": idx,
                                "total_images": total,
                                "content": f"正在识别第 {idx}/{total} 张图片...",
                            }
                        )
                    )
                    try:
                        text_piece = await run_in_threadpool(
                            image_to_text, image_bytes, content_type, model
                        )
                    except Exception as e:
                        await event_queue.put(
                            _sse({"type": "error", "status": 502, "content": f"图片识别失败: {e}"})
                        )
                        return
                    texts.append(text_piece)

                ocr_text = "\n\n".join(t for t in texts if t.strip())
                if not ocr_text.strip():
                    await event_queue.put(
                        _sse(
                            {
                                "type": "error",
                                "status": 422,
                                "content": "未识别到文字，请换清晰的图片",
                            }
                        )
                    )
                    return

                state["stage"] = "structuring"
                await event_queue.put(
                    _sse(
                        {
                            "type": "status",
                            "stage": "structuring",
                            "content": "正在整理简历结构...",
                        }
                    )
                )
                try:
                    resume_data = await assemble_resume_data_fast(ocr_text, model=None)
                except Exception as e:
                    await event_queue.put(
                        _sse(
                            {
                                "type": "error",
                                "status": 500,
                                "content": f"简历结构化失败: {e}",
                            }
                        )
                    )
                    return

                normalized = _normalize_uploaded_resume(resume_data, "图片流式解析")
                await event_queue.put(
                    _sse(
                        {
                            "type": "json",
                            "content": {"resume": normalized, "provider": model},
                        }
                    )
                )
                await event_queue.put(_sse("[DONE]"))
            except asyncio.CancelledError:
                raise
            except Exception as e:
                await event_queue.put(
                    _sse({"type": "error", "status": 500, "content": str(e)})
                )
            finally:
                await event_queue.put(None)

        pipeline_task = asyncio.create_task(_run_pipeline())
        try:
            while True:
                try:
                    frame = await asyncio.wait_for(
                        event_queue.get(), timeout=IMAGE_STREAM_HEARTBEAT_INTERVAL
                    )
                except asyncio.TimeoutError:
                    yield _sse(
                        {
                            "type": "heartbeat",
                            "stage": state["stage"],
                            "elapsed": round(time.time() - started_at, 1),
                        }
                    )
                    continue
                if frame is None:
                    break
                yield frame
        finally:
            if not pipeline_task.done():
                pipeline_task.cancel()
                await asyncio.gather(pipeline_task, return_exceptions=True)

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


async def _parse_resume_serial(body: ResumeParseRequest):
    """串行解析简历文本（原有逻辑）"""
    provider = body.provider or DEFAULT_AI_PROVIDER
    model = getattr(body, "model", None)
    text = normalize_pasted_resume_text(body.text)

    # 格式定义
    schema_desc = """格式:{"name":"姓名","contact":{"phone":"电话","email":"邮箱"},"objective":"求职意向","education":[{"title":"学校","subtitle":"专业","degree":"学位(本科/硕士/博士)","date":"时间","details":["荣誉"]}],"internships":[{"title":"公司","subtitle":"职位","date":"时间","highlights":["工作内容"]}],"projects":[{"title":"项目名","subtitle":"角色","date":"时间","description":"项目描述(可选)","highlights":["描述"]}],"openSource":[{"title":"开源项目","subtitle":"角色/描述","date":"时间(格式: 2023.01-2023.12 或 2023.01-至今)","items":["贡献描述"],"repoUrl":"仓库链接"}],"skills":[{"category":"类别","details":"技能描述"}],"awards":["奖项"]}

重要说明：
1. 技能描述：如果原文中技能描述部分有多行，每行以"-"开头，应该将每一行作为一个独立的技能项，格式为{"category":"","details":"该行的完整内容(去掉开头的破折号)"}
2. 项目经历（极其重要，必须严格遵守）：
   - "### xxx"或"## xxx"开头的是项目标题；若无 markdown 标题，则「项目经历：」后第一行是项目名
   - 项目描述段落（从项目标题后、技术栈前的完整段落）必须放入"description"字段
   - 技术栈信息（如"技术栈：SpringBoot MySQL..."）应该附加到 description 字段末尾
   - "- **标题**：描述"或 "- 架构设计：描述"格式是项目的功能亮点，必须放入该项目的"highlights"数组，绝不能作为独立项目！
   - highlights数组中的每一项应该保持原文格式，包括加粗标记
   - 如果只看到功能亮点（"- **xxx**：描述"）而没有项目标题，将这些放入highlights数组，title留空，系统会自动合并
""" + RESUME_PARSE_EXTRA_RULES

    # 如果文本过长，使用分块处理（阈值与 parallel chunk_threshold 对齐，中短简历走单次 LLM）
    if len(text) > 1500:
        print(f"[解析] 文本长度 {len(text)}，启用分块处理")
        chunks = split_resume_text(text, max_chunk_size=300)
        chunks_results = []

        for i, chunk in enumerate(chunks):
            logger.info(f"处理第 {i+1}/{len(chunks)} 块: {chunk['section']}")
            chunk_prompt = f"""从简历文本片段提取信息,只输出JSON(不要markdown,无数据的字段用空数组[]):

解析规则：
1. 技能描述：如果有多行以"-"开头的技能描述，每行应该作为一个独立的技能项，格式为{{"category":"","details":"该行的完整内容(去掉开头的破折号)"}}
2. 项目经历（极其重要，必须严格遵守）：
   - 只有"### xxx"或"## xxx"开头的才是项目标题
   - 项目描述段落（从项目标题后、第一个"- **"之前的完整段落）放入"description"字段
   - 技术栈信息（如"技术栈：SpringBoot MySQL..."）附加到 description 字段末尾
   - 以"- **标题**：描述"格式开头的行是项目的功能亮点，每行一个，放入该项目的"highlights"字符串数组
   - highlights数组中的每一项保持原格式，包括**加粗标记**
   - 绝对不要把功能亮点合并到description中！

正确示例：
输入文本：
### RAG 知识库助手
基于私有知识库的 RAG 对话平台。
技术栈：SpringBoot MySQL Redis

- **上下文截断**：解决截断问题
- **文档解析**：多格式解析

输出：
{{
  "projects": [
    {{
      "title": "RAG 知识库助手",
      "description": "基于私有知识库的 RAG 对话平台。技术栈：SpringBoot MySQL Redis",
      "highlights": [
        "**上下文截断**：解决截断问题",
        "**文档解析**：多格式解析"
      ]
    }}
  ]
}}

注意：highlights数组中每项不要开头的"- "符号，前端会用无序列表渲染！

片段内容({chunk['section']}):
{chunk['content']}
{schema_desc}"""
            try:
                raw = await asyncio.to_thread(call_llm, provider, chunk_prompt, model=model)
            except Exception as e:
                logger.warning(f"分块 {i+1} 解析失败: {e}")
                write_llm_debug(f"Chunk {i+1} Error: {e}")
                continue

            cleaned = clean_llm_response(raw)

            try:
                chunk_data = parse_json_response(cleaned)
                chunks_results.append(chunk_data)
                logger.info(f"分块 {i+1} 解析成功")
            except Exception as e:
                logger.warning(f"分块 {i+1} JSON 解析失败: {e}")
                write_llm_debug(f"Chunk {i+1} Raw: {raw}")
                continue

        short_data = merge_resume_chunks(chunks_results)
        print("[解析] 分块合并完成")

    else:
        # 短文本直接处理
        prompt = f"""从简历文本提取信息,只输出JSON(不要markdown,无数据的字段用空数组[]):

解析规则：
1. 技能描述：如果有多行以"-"开头的技能描述，每行应该作为一个独立的技能项，格式为{{"category":"","details":"该行的完整内容(去掉开头的破折号)"}}
2. 项目经历（极其重要，必须严格遵守）：
   - 只有"### xxx"或"## xxx"开头的才是项目标题
   - 项目描述段落（从项目标题后、第一个"- **"之前的完整段落）放入"description"字段
   - 技术栈信息（如"技术栈：SpringBoot MySQL..."）附加到 description 字段末尾
   - 以"- **标题**：描述"格式开头的行是项目的功能亮点，每行一个，放入该项目的"highlights"字符串数组
   - highlights数组中的每一项保持原格式，包括**加粗标记**
   - 绝对不要把功能亮点合并到description中！

正确示例：
输入文本：
### RAG 知识库助手
基于私有知识库的 RAG 对话平台。
技术栈：SpringBoot MySQL Redis

- **上下文截断**：解决截断问题
- **文档解析**：多格式解析

输出：
{{
  "projects": [
    {{
      "title": "RAG 知识库助手",
      "description": "基于私有知识库的 RAG 对话平台。技术栈：SpringBoot MySQL Redis",
      "highlights": [
        "**上下文截断**：解决截断问题",
        "**文档解析**：多格式解析"
      ]
    }}
  ]
}}

注意：highlights数组中每项不要开头的"- "符号，前端会用无序列表渲染！

简历文本:
{text}
{schema_desc}"""

        try:
            raw = await asyncio.to_thread(call_llm, provider, prompt, model=model)
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"LLM 调用失败: {e}")

        cleaned = clean_llm_response(raw)

        try:
            short_data = parse_json_response(cleaned)
        except Exception as e:
            logger.error(f"JSON 解析失败: {e}")
            write_llm_debug(f"Raw Response:\n{raw}")

            raise HTTPException(
                status_code=500, detail="AI 返回的内容无法解析为 JSON，请重试"
            )

    # 额外的数据清理和标准化
    try:
        from json_normalizer import normalize_resume_json

        normalized_data = normalize_resume_json(short_data)
        return {"success": True, "data": normalized_data}
    except Exception as e:
        print(f"[解析] 数据标准化失败: {e}")
        # 返回原始数据
        data = {
            "name": short_data.get("name", ""),
            "contact": short_data.get("contact", {"phone": "", "email": ""}),
            "objective": short_data.get("objective", ""),
            "education": short_data.get("education", []),
            "internships": short_data.get("internships", []),
            "projects": short_data.get("projects", []),
            "openSource": short_data.get("openSource", []),
            "skills": short_data.get("skills", []),
            "awards": short_data.get("awards", []),
        }
        return {"resume": data, "provider": provider}


_STREAM_PARSE_SCHEMA = '格式:{"name":"姓名","contact":{"phone":"电话","email":"邮箱"},"objective":"求职意向","education":[{"title":"学校","subtitle":"专业","degree":"学位(本科/硕士/博士)","date":"时间","details":["荣誉"]}],"internships":[{"title":"公司","subtitle":"职位","date":"时间","highlights":["工作内容"]}],"projects":[{"title":"项目名","subtitle":"角色","date":"时间","description":"项目描述(可选)","highlights":["描述"]}],"openSource":[{"title":"开源项目","subtitle":"角色/描述","date":"时间","items":["贡献描述"],"repoUrl":"仓库链接"}],"skills":[{"category":"类别","details":"技能描述"}],"awards":["奖项"]}'


def _build_stream_parse_prompt(text: str) -> str:
    return f"""从简历文本提取信息,只输出JSON(不要markdown,无数据的字段用空数组[]):

解析规则：
1. 技能：多行以"-"开头的技能描述，每行作为独立技能项 {{"category":"","details":"该行内容(去掉破折号)"}}
2. 项目：项目描述段落放入"description"；以"- **标题**：描述"格式、或"1. 2. 3."数字编号的功能亮点放入该项目"highlights"数组(保留**加粗**、去掉开头"- "或序号)，不要并入 description
3. 实习/工作的每条职责(含「1. 2.」数字编号要点)放入对应条目的"highlights"数组
4. 开源经历：「开源经历」段下每个开源项目作为 openSource 数组一条记录(不要放进 projects/internships)；项目/社区名→title，括号或一句话角色→subtitle，仓库链接→repoUrl，形如「1.简介：」「2.个人职责：」的逐条说明每条作为 items 一项(去掉开头序号)

简历文本:
{text}
{_STREAM_PARSE_SCHEMA}"""


@router.post("/resume/parse/stream")
async def parse_resume_text_stream(body: ResumeParseRequest):
    """流式解析简历文本：单次 LLM 流式输出 token 进度，结束时返回标准化 JSON。
    与非流式 /resume/parse（含并行分块）并存，仅用于需要实时进度反馈的导入场景。"""
    import asyncio

    text = normalize_pasted_resume_text(body.text)
    if not text.strip():
        raise HTTPException(status_code=400, detail="文本不能为空")
    provider = body.provider or DEFAULT_AI_PROVIDER
    prompt = _build_stream_parse_prompt(text)

    async def generate():
        started_at = time.time()
        full = ""
        chunk_queue: asyncio.Queue[tuple[str, Any]] = asyncio.Queue()
        stop_event = threading.Event()
        loop = asyncio.get_running_loop()

        def _producer():
            try:
                for chunk in call_llm_stream(provider, prompt):
                    if stop_event.is_set():
                        break
                    loop.call_soon_threadsafe(chunk_queue.put_nowait, ("chunk", chunk))
                loop.call_soon_threadsafe(chunk_queue.put_nowait, ("eof", None))
            except Exception as err:
                loop.call_soon_threadsafe(chunk_queue.put_nowait, ("error", err))

        worker = threading.Thread(target=_producer, daemon=True)
        worker.start()

        try:
            yield f"data: {_json.dumps({'type': 'status', 'content': 'parsing'}, ensure_ascii=False)}\n\n"
            while True:
                try:
                    kind, payload = await asyncio.wait_for(
                        chunk_queue.get(), timeout=IMAGE_STREAM_HEARTBEAT_INTERVAL
                    )
                except asyncio.TimeoutError:
                    yield f"data: {_json.dumps({'type': 'heartbeat', 'elapsed': round(time.time() - started_at, 1)}, ensure_ascii=False)}\n\n"
                    continue
                if kind == "chunk":
                    full += payload
                    yield f"data: {_json.dumps({'type': 'progress', 'chars': len(full)}, ensure_ascii=False)}\n\n"
                elif kind == "error":
                    raise payload
                elif kind == "eof":
                    break

            cleaned = clean_llm_response(full)
            data = parse_json_response(cleaned)
            try:
                from json_normalizer import normalize_resume_json
                data = normalize_resume_json(data)
            except Exception as norm_err:
                logger.warning(f"流式解析标准化失败，返回原始数据: {norm_err}")

            yield f"data: {_json.dumps({'type': 'json', 'content': data}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'type': 'error', 'content': str(e)}, ensure_ascii=False)}\n\n"
        finally:
            stop_event.set()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/resume/parse-section")
async def parse_section_text(body: SectionParseRequest):
    """AI 解析单个模块文本 → 结构化数据"""
    provider = body.provider or DEFAULT_AI_PROVIDER
    model = body.model  # 获取用户指定的模型

    section_prompt = SECTION_PROMPTS.get(body.section_type, "提取信息,输出JSON")

    prompt = f"""{section_prompt}
只输出JSON,不要markdown,不要解释。

文本内容:
{body.text}"""

    try:
        raw = await asyncio.to_thread(call_llm, provider, prompt, model=model)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败: {e}")

    cleaned = clean_llm_response(raw)

    try:
        data = parse_json_response(cleaned)
    except Exception:
        raise HTTPException(
            status_code=500, detail="AI 返回的内容无法解析为 JSON，请重试"
        )

    if body.section_type == "summary" and isinstance(data, dict):
        data = data.get("summary", data)

    return {
        "data": data,
        "section_type": body.section_type,
        "provider": provider,
        "model": model,
    }


@router.post("/resume/rewrite")
async def rewrite_resume(body: RewriteRequest):
    """对简历 JSON 的某个路径进行 AI 改写"""
    try:
        parts = parse_path(body.path)
        parent, key, cur_value = get_by_path(body.resume, parts)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"路径错误：{e}")

    prompt = build_rewrite_prompt(body.path, cur_value, body.instruction, body.locale, body.history)
    try:
        raw = await asyncio.to_thread(call_llm, body.provider, prompt)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"LLM 调用失败：{e}")

    new_value: Any = None
    if isinstance(cur_value, str):
        text = raw.strip()
        if text.startswith("```"):
            idx = text.find("\n")
            if idx != -1:
                text = text[idx + 1 :]
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()
        new_value = text
    else:
        try:
            new_value = _json.loads(raw)
        except Exception:
            try:
                s = raw.find("{")
                e = raw.rfind("}")
                if s != -1 and e != -1 and e > s:
                    new_value = _json.loads(raw[s : e + 1])
                else:
                    raise
            except Exception as e:
                raise HTTPException(status_code=500, detail=f"解析 JSON 失败: {e}")

    try:
        updated = set_by_path(body.resume, parts, new_value)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"写入失败：{e}")

    return {"resume": updated}


@router.post("/resume/rewrite/stream")
async def rewrite_resume_stream(body: RewriteRequest):
    """流式对简历 JSON 的某个路径进行 AI 改写"""
    try:
        parts = parse_path(body.path)
        parent, key, cur_value = get_by_path(body.resume, parts)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"路径错误：{e}")

    # 默认使用 deepseek（如果未指定 provider）
    provider = body.provider or DEFAULT_AI_PROVIDER

    prompt = build_rewrite_prompt(body.path, cur_value, body.instruction, body.locale, body.history)

    async def generate():
        """生成 SSE 流"""
        try:
            for chunk in call_llm_stream(provider, prompt):
                """发送 SSE 格式数据"""
                yield f"data: {_json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/resume/rewrite-text/stream")
async def rewrite_text_stream(body: RewriteTextStreamRequest):
    """流式改写文本片段（兼容前端划词改写入口）"""
    source_text = (body.text or "").strip()
    instruction = (body.instruction or "").strip()
    if not source_text:
        raise HTTPException(status_code=400, detail="text 不能为空")
    if not instruction:
        raise HTTPException(status_code=400, detail="instruction 不能为空")

    provider = body.provider or DEFAULT_AI_PROVIDER
    path_hint = body.path or "selected_text"
    locale = body.locale or "zh"

    prompt = render_rewrite_text_prompt(
        locale=locale,
        path_hint=path_hint,
        instruction=instruction,
        source_text=source_text,
    )

    async def generate():
        try:
            for chunk in call_llm_stream(provider, prompt):
                yield f"data: {_json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/resume/chat/stream")
async def resume_chat_stream(body: ChatStreamRequest):
    """轻量简历问答（流式）：供右下角悬浮 AI 助手对话窗口使用"""
    messages = [m for m in body.messages if (m.content or "").strip()]
    if not messages:
        raise HTTPException(status_code=400, detail="messages 不能为空")

    provider = body.provider or DEFAULT_AI_PROVIDER
    prompt = _build_resume_chat_prompt(
        messages=messages,
        resume_context=body.resume_context or "",
        locale=body.locale or "zh",
    )

    async def generate():
        try:
            for chunk in call_llm_stream(provider, prompt):
                yield f"data: {_json.dumps({'content': chunk}, ensure_ascii=False)}\n\n"
            yield "data: [DONE]\n\n"
        except Exception as e:
            yield f"data: {_json.dumps({'error': str(e)}, ensure_ascii=False)}\n\n"

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/resume/score", response_model=ScoreResponse)
async def score_resume(
    request: ScoreRequest,
    db: Session = Depends(get_db),
    current_user: AppUser = Depends(get_current_user),
):
    """
    对简历进行JD匹配评分

    输入：简历ID + JD文本
    输出：3维度评分 + 总体匹配度
    """
    if not request.jd_text or not request.jd_text.strip():
        raise HTTPException(status_code=400, detail="JD文本不能为空")

    try:
        from services.scoring_service import ScoringService

        service = ScoringService(db)
        result = service.score_resume(
            resume_id=request.resume_id,
            user_id=current_user.id,
            jd_text=request.jd_text,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"评分失败: {str(e)}")
