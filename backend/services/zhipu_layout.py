"""
智谱混合识别服务
- glm-ocr: 直接解析 PDF 获取结构化内容
- glm-4.6v: 图片布局识别，识别格式特征
"""
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Optional, Dict, Any, Iterable

try:
    from zhipuai import ZhipuAI
except ImportError as exc:
    raise ImportError("zhipuai 未安装，请运行: uv pip install zhipuai") from exc

try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Python < 3.11


def _load_zhipu_config() -> Dict[str, str]:
    """从 config.toml 加载智谱配置"""
    config_path = Path(__file__).resolve().parent.parent.parent / "config.toml"
    if config_path.exists():
        with open(config_path, "rb") as f:
            config = tomllib.load(f)
            zhipu_config = config.get("zhipu", {})
            return {
                "api_key": zhipu_config.get("api_key", ""),
                "vision_model": zhipu_config.get("vision_model", "glm-4.6v"),
                "ocr_model": zhipu_config.get("ocr_model", "glm-ocr"),
            }
    return {"api_key": "", "vision_model": "glm-4.6v", "ocr_model": "glm-ocr"}


_config = _load_zhipu_config()
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "") or _config["api_key"]
ZHIPU_VISION_MODEL = os.getenv("ZHIPU_VISION_MODEL", "") or _config["vision_model"]
ZHIPU_OCR_MODEL = os.getenv("ZHIPU_OCR_MODEL", "") or _config.get("ocr_model", "glm-ocr")

_zhipu_client: Optional[ZhipuAI] = None
_last_key: Optional[str] = None


def _get_client(api_key: Optional[str] = None) -> ZhipuAI:
    global _zhipu_client, _last_key, ZHIPU_API_KEY
    key = (api_key or os.getenv("ZHIPU_API_KEY", "") or ZHIPU_API_KEY).strip()
    if not key:
        raise ValueError("ZHIPU_API_KEY 未配置")
    ZHIPU_API_KEY = key
    if _zhipu_client is None or _last_key != key:
        _zhipu_client = ZhipuAI(api_key=key)
        _last_key = key
    return _zhipu_client


def refresh_zhipu_api_key(api_key: Optional[str] = None) -> str:
    """刷新内存中的智谱 API Key 并重置客户端缓存（供配置中心保存/删除后即时生效）。"""
    global ZHIPU_API_KEY, _zhipu_client, _last_key
    resolved = (api_key if api_key is not None else os.getenv("ZHIPU_API_KEY", "")).strip()
    ZHIPU_API_KEY = resolved
    _zhipu_client = None
    _last_key = None
    return ZHIPU_API_KEY


def test_zhipu_api_key(api_key: Optional[str] = None) -> None:
    """使用最小请求检测智谱 API Key 是否有效（用于设置页连通性探测）。"""
    import httpx

    key = (api_key or os.getenv("ZHIPU_API_KEY", "") or ZHIPU_API_KEY).strip()
    if not key:
        raise ValueError("ZHIPU_API_KEY 未配置")

    # 320x80 标准 PNG 的 base64（智谱 glm-ocr 要求标准 PNG 结构与最小尺寸，过小图片会报 1214）
    tiny_png_b64 = (
        "iVBORw0KGgoAAAANSUhEUgAAAUAAAABQCAIAAADnUzvSAAAHDElEQVR4nO3aX0hT"
        "fRzH8emktUIGpVJWREYgaTY3g9b0bLklopabRV1ookkUXQhZLfCimy7KzC6y6CKb"
        "FSEWNgkitlXmIkuJIqKYkCvtH1nQZjlty7Pvw9OBIXNTn2dR/PTzujo7O+fsd37z"
        "vXM2jCEiEQCwKfZvDwAA/j8EDMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAEDMAwBAzA"
        "MAQMwDAEDMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAEDMAwBAzA"
        "MAQMwDAEDMAwBAzAMAQMwDAEDDCLA543b55Wq9VoNAqFwuFwiP6gpqYmiUQyODgY"
        "5XGOHz8+/mFzc7NSqVSpVEql8tKlS8LK8+fPKxQKjUZTWFj47t27Sc69vb1d+0tc"
        "XJyw0NbW9p8GYDabc3Jy5HK53W4XiURDQ0MGgyE7O9tgMAwNDYXdJhAIVFdXq1Qq"
        "juNev34d5YQASyg6MplMWHj+/PmaNWvoD9qyZcvBgwfNZvPvOgUislqtarXa7XYT"
        "kdvtVqvVt2/fttvtGzduHBkZIaJbt27l5uZO59zHH3b6A/j8+TPHcTzPO53O1NRU"
        "Ijp06FBDQwMRnTx58vDhw2G3OXv2bG1tLRFZLBaj0RjlhABDflvAgUBgwYIFX79+"
        "LS0t1el0OTk5PT09RHT69Gm5XJ6ZmWmz2UL+WIPLMpmssrIyJSXl3LlzpaWlK1as"
        "OHXqFBFNPFqQ1+vV6XS9vb0lJSVE9OnTp82bN2dnZ5eVlS1cuDDSvjKZrLa2luO4"
        "jIwMi8VCREeOHBGLxZs2bRI20Ol0Dx8+DL5KV1eXXq/Py8t79OhRcOXu3bv9fv/E"
        "c480M5PPScgAnE7ntWvXiGh4eDgxMZGI0tLSPnz4QETv379PT08Pu82GDRtevXpF"
        "RD6fr66uLsr3FGZjwFarddu2bVVVVd3d3UQ0MDCwdu1aIkpMTPz27ZvT6dy5c2ek"
        "gCUSSXd398DAQExMTE9PT39//+LFi4lo4tGCLBZLfX09ESkUCp/PV1ZWduXKFSJq"
        "b2+XSCSR9pVKpcJHg8vlWrZsWcgwiCg5OXl0dDT4cHR0NDk5ecmSJT9+/Jjy3CM9"
        "+5/mJOjixYu7du0iooSEBJ7niYjneSHXsNs0NDRoNBqDwfDmzZtpvG8wQ8RFeQfu"
        "9/u1Wu3Pnz97e3tfvny5bt26vr4+4Smv18vzfEFBQXl5+b59+y5fvhyybyAQEBZi"
        "Y2OzsrLEYvGcOXOysrJiY2NHRkZEIpHNZgs5mlgsFh7euHHj2bNnbW1tHz9+dDgc"
        "nZ2dTU1NIpGoqKhI2CbsvoFAoLKyUiQSpaSkBL9PTv79IiYmhuf56Zx7pINMHMkk"
        "cyJwuVz19fX37t2bZGzjt/H7/cuXL+/s7Lx+/XpVVdXdu3enPDWYIaL8AAhePerq"
        "6o4dO7Zo0SLhCsbzvMPhEJ5yOBxGo7GiooKI4uPjhZVut1u4VIbcS49fCHs0Ihob"
        "G1OpVMKy1Wqtrq5OSkoSLpI+n08qlUbaN/jqYV+UiPR6fVdXV/DhgwcP8vLyOI4T"
        "LqHC3XJ5eXnYc480M1POScgV+Pv370qlMviKE2+hJ26zatWqsbExYWYSEhKm8b7B"
        "DPHbAn769KnRaNy6dWtLSwsR3bx5Mz8/3+PxcBzn9/uHh4eTkpKIaOnSpS9evCCi"
        "M2fOzJ07N+QgIQshRwu+qMPh2Lt3r7Ds9XpTU1MNBsPVq1eJqLW1VThs2H3D3sDH"
        "x8cL96hEZLPZ1Gq1x+MJ/oh1586d1tZWvV4vfEC0tLTs2LEj7LlHmpkp52T8AAKB"
        "QElJibC9YPyPWCaTKew2e/bs6ejoIKKOjg6dThfF+wmzNWCv17ty5cr+/v78/HyO"
        "43Jzc10uFxGdOHFCoVDI5fLGxkbhu+vq1au1Wq3JZIrUbXDh7du3IUcT1NTUCL/i"
        "CDiOs9vtOb+YTCbhR6yw+4YNuKCgoLCwMLj+woULmZmZ69evVygUzc3NwsqjR4+m"
        "paVptdrt27d/+fIl7LkHIwx5duJIQuZk/ADMZvP8+fM1vwgrPR5PcXGxWq0uLi4W"
        "PlkmbjM4OFhUVKTVavV6fV9fX5TvKTAk5t+I2VdRUVFTU5ORkfH48eMDBw7cv3//"
        "b48I4E+YIQE/efJk//79UqnU7/c3Njamp6f/7REB/AkzJGCA2Qn/Cw3AMAQMwDAE"
        "DMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAE"
        "DMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAE"
        "DMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAEDMAwBAzAMAQMwDAE"
        "DMAwBAzAMAQMwDAEDCBi1z9WZJbigbIt9wAAAABJRU5ErkJggg=="
    )
    api_url = "https://open.bigmodel.cn/api/paas/v4/layout_parsing"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": ZHIPU_OCR_MODEL or "glm-ocr",
        "file": f"data:image/png;base64,{tiny_png_b64}",
    }
    transport = httpx.HTTPTransport(retries=2)
    with httpx.Client(timeout=20, transport=transport) as http_client:
        resp = http_client.post(api_url, json=payload, headers=headers)
    if resp.status_code in (401, 403):
        raise ValueError(f"智谱 API Key 鉴权失败 (HTTP {resp.status_code}): {resp.text}")
    if resp.status_code >= 500:
        raise ValueError(f"智谱服务端异常 (HTTP {resp.status_code}): {resp.text}")
    if resp.status_code != 200:
        # 若因 1x1 图片无文字返回业务 400 但非鉴权错误，进一步检查错误码
        err_text = resp.text
        if "1001" in err_text or "1002" in err_text or "token" in err_text.lower() or "auth" in err_text.lower() or "key" in err_text.lower():
            raise ValueError(f"智谱 API Key 无效: {err_text}")
        raise ValueError(f"智谱 OCR 探测异常 (HTTP {resp.status_code}): {err_text}")


def _strip_json_block(text: str) -> str:
    cleaned = text.strip()
    if "```json" in cleaned:
        cleaned = cleaned.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in cleaned:
        cleaned = cleaned.split("```", 1)[1].split("```", 1)[0]
    return cleaned.strip()


def _fix_json_string(text: str) -> str:
    """修复常见的 JSON 格式问题"""
    import re
    # 移除可能的 BOM 和不可见字符
    text = text.strip().lstrip('\ufeff')
    # 修复尾部多余逗号: ,] -> ] 和 ,} -> }
    text = re.sub(r',\s*]', ']', text)
    text = re.sub(r',\s*}', '}', text)
    # 修复中文冒号
    text = text.replace('：', ':')
    # 修复中文引号
    text = text.replace('"', '"').replace('"', '"')
    text = text.replace(''', "'").replace(''', "'")
    return text


def _balance_json_braces(text: str) -> str:
    """
    平衡 JSON 的括号，修复多余或缺失的闭合括号
    """
    # 统计括号
    brace_count = 0  # {}
    bracket_count = 0  # []
    in_string = False
    escape = False
    last_valid_pos = 0
    
    for i, char in enumerate(text):
        if escape:
            escape = False
            continue
        if char == '\\':
            escape = True
            continue
        if char == '"' and not escape:
            in_string = not in_string
            continue
        if in_string:
            continue
            
        if char == '{':
            brace_count += 1
        elif char == '}':
            brace_count -= 1
            if brace_count == 0 and bracket_count == 0:
                # 找到完整的 JSON 对象
                last_valid_pos = i + 1
                break
            elif brace_count < 0:
                # 多余的 }，截断
                return text[:i]
        elif char == '[':
            bracket_count += 1
        elif char == ']':
            bracket_count -= 1
            if bracket_count < 0:
                # 多余的 ]，截断
                return text[:i]
    
    if last_valid_pos > 0:
        return text[:last_valid_pos]
    return text


def _parse_json(text: str) -> Dict[str, Any]:
    cleaned = _strip_json_block(text)
    cleaned = _fix_json_string(cleaned)
    
    # 尝试直接解析
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    
    # 尝试提取 JSON 对象
    start = cleaned.find("{")
    if start != -1:
        json_str = cleaned[start:]
        json_str = _fix_json_string(json_str)
        # 使用括号平衡来截取正确的 JSON
        json_str = _balance_json_braces(json_str)
        try:
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            # 打印调试信息
            print(f"[智谱JSON解析] 原始内容前100字符: {json_str[:100]}", flush=True)
            print(f"[智谱JSON解析] 错误位置附近: {json_str[max(0, e.pos-50):e.pos+50]}", flush=True)
            raise ValueError(f"JSON 解析失败: {e}")
    
    raise ValueError("未找到有效的 JSON 对象")


def _build_prompt() -> str:
    return """识别简历结构骨架，按从上到下顺序输出JSON。请特别注意识别每个section的**格式特征**和**嵌套层级结构**。

type值: basic/experience/projects/education/skills/openSource/awards

规则:
- 标题含"开源"→openSource
- 含GitHub链接→openSource
- 只输出JSON,不要解释

**格式识别规则（非常重要）**:
- list_style: 观察该section的内容是用什么方式排列的
  - "bullet": 有圆点(•)、方点(■)或连字符(-)开头的无序列表
  - "numbered": 有1.2.3.或一二三开头的有序列表
  - "none": 没有列表符号，是纯文本段落
- has_category: 技能模块是否有分类标题(如"后端:"、"数据库:"等)
- item_count: 该section下有多少个条目

**嵌套层级识别（非常重要 - 项目/经历模块）**:
- has_nested_groups: 判断该条目的描述是否有嵌套的子分组结构
  - true: 有加粗的小标题(如"**搜索服务拆分专项**")，下面跟着缩进的子项列表
  - false: 是扁平的列表，没有分组标题
- nested_structure: 如果 has_nested_groups=true，描述每个分组的结构
  - 例如: [{"group_title": "搜索服务拆分专项", "child_count": 3}, {"group_title": "性能优化专项", "child_count": 2}]

格式:
{
  "sections": [
    {
      "type": "experience",
      "title": "实习经历",
      "format": {"list_style": "bullet", "has_category": false, "has_nested_groups": false},
      "items": [{"name": "腾讯云", "subtitle": "后端开发", "date": "2025.05-2025.09"}]
    },
    {
      "type": "projects",
      "title": "项目经历",
      "format": {"list_style": "bullet", "has_category": false, "has_nested_groups": true},
      "items": [
        {
          "name": "xxx系统",
          "subtitle": "后端开发",
          "date": "2024.01-2024.06",
          "nested_structure": [
            {"group_title": "搜索服务拆分专项", "child_count": 3},
            {"group_title": "性能优化", "child_count": 2}
          ]
        }
      ]
    },
    {
      "type": "skills",
      "title": "专业技能",
      "format": {"list_style": "bullet", "has_category": true, "has_nested_groups": false},
      "items": [{"category": "后端", "content": "熟悉Java..."}]
    }
  ]
}"""


def recognize_layout_from_images(
    image_bytes_list: Iterable[bytes],
    api_key: Optional[str] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    """
    使用智谱 GLM-4.6V 识别简历布局骨架（支持多页图片）
    """
    images = [img for img in image_bytes_list if img]
    if not images:
        raise ValueError("图片内容为空")

    content = []
    for image_bytes in images:
        image_base64 = base64.b64encode(image_bytes).decode("utf-8")
        content.append(
            {
                "type": "image_url",
                "image_url": {
                    "url": f"data:image/png;base64,{image_base64}"
                },
            }
        )
    content.append({"type": "text", "text": _build_prompt()})

    client = _get_client(api_key)
    try:
        print(f"[智谱布局] 开始调用 API，模型: {model or ZHIPU_VISION_MODEL}，图片数: {len(images)}", flush=True)
        response = client.chat.completions.create(
            model=model or ZHIPU_VISION_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": content
                }
            ],
            temperature=0.1,
            max_tokens=10000
        )
    except Exception as e:
        error_msg = str(e)
        print(f"[智谱布局] API 调用失败: {error_msg}", flush=True)
        # 检查是否是 API 密钥问题
        if "api_key" in error_msg.lower() or "authentication" in error_msg.lower() or "401" in error_msg:
            raise ValueError(f"智谱 API 密钥无效或已过期: {error_msg}")
        # 检查是否是限流问题
        if "rate" in error_msg.lower() or "429" in error_msg:
            raise ValueError(f"智谱 API 请求过于频繁，请稍后重试: {error_msg}")
        # 其他错误
        raise ValueError(f"智谱 API 调用失败: {error_msg}")

    msg = response.choices[0].message
    content = msg.content or ""
    # GLM-4.6V 可能将内容放在 reasoning_content 中
    if not content and hasattr(msg, "reasoning_content") and msg.reasoning_content:
        content = msg.reasoning_content
    if not content:
        raise ValueError("智谱未返回布局内容")
    
    # 调试日志
    print(f"[智谱布局] 返回内容长度: {len(content)} 字符", flush=True)
    if len(content) < 500:
        print(f"[智谱布局] 完整内容: {content}", flush=True)
    else:
        print(f"[智谱布局] 前200字符: {content[:200]}...", flush=True)
    
    return _parse_json(content)


def recognize_layout_from_image_bytes(
    image_bytes: bytes,
    api_key: Optional[str] = None,
    model: Optional[str] = None
) -> Dict[str, Any]:
    """
    使用智谱 GLM-4.6V 识别简历布局骨架（单张图片）
    """
    return recognize_layout_from_images([image_bytes], api_key=api_key, model=model)


def recognize_with_ocr(
    pdf_bytes: bytes,
    api_key: Optional[str] = None,
    mime: str = "application/pdf",
) -> str:
    """
    使用智谱 glm-ocr layout_parsing API 直接解析 PDF，返回 Markdown 格式文本
    glm-ocr 支持 PDF（≤50MB, ≤100页）、JPG、PNG（≤10MB）
    
    API 端点: POST /api/paas/v4/layout_parsing
    参数: {"model": "glm-ocr", "file": "<base64_or_url>"}
    返回: md_results (Markdown 格式识别结果)
    """
    import httpx
    
    key = (api_key or os.getenv("ZHIPU_API_KEY", "") or ZHIPU_API_KEY).strip()
    if not key:
        raise ValueError("ZHIPU_API_KEY 未配置")
    
    # 将文件转为 base64 data URI（支持 PDF 与图片）
    pdf_base64 = base64.b64encode(pdf_bytes).decode("utf-8")
    file_data = f"data:{mime};base64,{pdf_base64}"
    
    api_url = "https://open.bigmodel.cn/api/paas/v4/layout_parsing"
    headers = {
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": ZHIPU_OCR_MODEL,
        "file": file_data,
    }
    
    try:
        print(f"[智谱OCR] 开始调用 layout_parsing API，模型: {ZHIPU_OCR_MODEL}，PDF大小: {len(pdf_bytes)/1024:.1f}KB", flush=True)
        transport = httpx.HTTPTransport(retries=2)
        with httpx.Client(timeout=300, transport=transport) as http_client:
            resp = http_client.post(api_url, json=payload, headers=headers)
        
        if resp.status_code != 200:
            error_text = resp.text
            print(f"[智谱OCR] API 返回错误 (HTTP {resp.status_code}): {error_text}", flush=True)
            raise ValueError(f"智谱 OCR API 返回错误 (HTTP {resp.status_code}): {error_text}")
        
        result = resp.json()
        
        # 提取 Markdown 结果
        md_results = result.get("md_results", "")
        if not md_results:
            # 尝试从 layout_details 提取文本
            layout_details = result.get("layout_details", [])
            texts = []
            for page in layout_details:
                for item in page:
                    content = item.get("content", "")
                    if content:
                        texts.append(content)
            md_results = "\n".join(texts)
        
        print(f"[智谱OCR] 返回内容长度: {len(md_results)} 字符", flush=True)
        if len(md_results) < 200:
            print(f"[智谱OCR] 完整内容: {md_results}", flush=True)
        else:
            print(f"[智谱OCR] 前200字符: {md_results[:200]}...", flush=True)
        
        return md_results
        
    except httpx.HTTPError as e:
        error_msg = str(e)
        print(f"[智谱OCR] HTTP 请求失败: {error_msg}", flush=True)
        raise ValueError(f"智谱 OCR API 请求失败: {error_msg}")
    except ValueError:
        raise
    except Exception as e:
        error_msg = str(e)
        print(f"[智谱OCR] API 调用失败: {error_msg}", flush=True)
        raise ValueError(f"智谱 OCR API 调用失败: {error_msg}")


def hybrid_recognize(
    pdf_bytes: bytes,
    image_bytes_list: Iterable[bytes],
    api_key: Optional[str] = None,
) -> Dict[str, Any]:
    """
    混合识别策略：
    1. glm-ocr 解析 PDF 获取完整文本
    2. glm-4.6v 识别图片获取布局和格式信息
    返回: {"ocr_text": str, "layout": dict}
    """
    result = {"ocr_text": "", "layout": {}}
    
    # 1. 尝试 OCR 解析 PDF
    try:
        ocr_text = recognize_with_ocr(pdf_bytes, api_key)
        result["ocr_text"] = ocr_text
        print(f"[混合识别] OCR 成功，文本长度: {len(ocr_text)}", flush=True)
    except Exception as e:
        print(f"[混合识别] OCR 失败，跳过: {e}", flush=True)
    
    # 2. 使用视觉模型识别布局
    try:
        layout = recognize_layout_from_images(image_bytes_list, api_key, model="glm-4.6v")
        result["layout"] = layout
        print(f"[混合识别] 布局识别成功", flush=True)
    except Exception as e:
        print(f"[混合识别] 布局识别失败: {e}", flush=True)
    
    return result
