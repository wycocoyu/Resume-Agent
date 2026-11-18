"""简历图片视觉识别：图片 bytes → 文本（Markdown）。

支持的视觉模型：
- qwen-vl-max（默认，DashScope，OpenAI 兼容 chat/completions）
- glm-ocr（智谱 layout_parsing，复用 zhipu_layout.recognize_with_ocr）
"""
from __future__ import annotations

import base64
import os

import httpx

try:
    from backend.services.ai_guard import (
        ensure_ai_circuit_open,
        handle_upstream_quota_error,
    )
except ImportError:
    from services.ai_guard import (
        ensure_ai_circuit_open,
        handle_upstream_quota_error,
    )

DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
# 2026-09-16 解耦：原先复用 DEEPSEEK_BASE_URL，而文本链路已切到 DeepSeek 官方，
# 再共用会把 qwen-vl 指到一个没有该模型的域名上。这里只认自己的变量。
DASHSCOPE_BASE_URL = os.getenv(
    "DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"
)

VISION_OCR_PROMPT = (
    "你是简历OCR助手。请逐字、忠实地提取这张简历图片中的全部文字内容，"
    "保持原有层级结构（姓名、求职意向、专业概况、教育经历、实习经历、项目经历、"
    "竞赛科研、技能等），用 Markdown 输出。"
    "严禁编造、推测或修改任何信息；看不清的地方原样标注[?]，不要脑补。"
)

# 支持的图片 MIME
SUPPORTED_IMAGE_TYPES = {"image/jpeg", "image/png"}


def resolve_vision_provider(model: str) -> str:
    """把视觉模型 id 映射到 provider 标识。未知模型抛 ValueError。"""
    if model.startswith("qwen"):
        return "qwen"
    if model == "glm-ocr":
        return "zhipu_ocr"
    raise ValueError(f"不支持的视觉模型: {model}")


def _qwen_vl_ocr(image_bytes: bytes, content_type: str, model: str) -> str:
    """用 DashScope qwen-vl 把图片识别成文本。"""
    if not DASHSCOPE_API_KEY:
        raise ValueError("DASHSCOPE_API_KEY 未配置")
    ensure_ai_circuit_open()
    data_uri = f"data:{content_type};base64,{base64.b64encode(image_bytes).decode()}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {DASHSCOPE_API_KEY}",
    }
    payload = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": VISION_OCR_PROMPT},
                    {"type": "image_url", "image_url": {"url": data_uri}},
                ],
            }
        ],
    }
    with httpx.Client(timeout=120) as client:
        resp = client.post(
            f"{DASHSCOPE_BASE_URL}/chat/completions", json=payload, headers=headers
        )
    if resp.status_code != 200:
        handle_upstream_quota_error(
            status_code=resp.status_code,
            error_text=resp.text,
            provider="qwen",
        )
        raise ValueError(f"qwen-vl 识别失败 (HTTP {resp.status_code}): {resp.text}")
    return resp.json()["choices"][0]["message"]["content"]


def image_to_text(image_bytes: bytes, content_type: str, model: str) -> str:
    """图片 → 文本。按 model 分流到对应视觉 provider。"""
    provider = resolve_vision_provider(model)
    if provider == "qwen":
        return _qwen_vl_ocr(image_bytes, content_type, model)
    if provider == "zhipu_ocr":
        try:
            from backend.services.zhipu_layout import recognize_with_ocr
        except ImportError:
            from services.zhipu_layout import recognize_with_ocr
        return recognize_with_ocr(image_bytes, mime=content_type)
    raise ValueError(f"未知 provider: {provider}")
