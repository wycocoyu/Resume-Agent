"""
简单版本的 AI API 调用示例
包含智谱和豆包的基本调用方法
"""

"""
智谱 / 豆包 / DeepSeek API 配置（从环境变量读取）
- DEEPSEEK_API_KEY（旧部署兼容 DASHSCOPE_API_KEY）
- DEEPSEEK_MODEL（默认 deepseek-flash）
- DEEPSEEK_BASE_URL（默认 https://api.deepseek.com）
"""
import os
"""
可选：从 .env 读取环境变量
"""
try:
    from dotenv import load_dotenv
    from pathlib import Path
    # 确保从项目根目录加载 .env 文件
    ROOT_DIR = Path(__file__).resolve().parent.parent  # backend -> 项目根目录
    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=str(env_path), override=True)
    else:
        load_dotenv()  # 回退到默认位置
except Exception:
    pass


"""豆包配置"""

"""DeepSeek 配置"""
# 2026-09-16 从阿里云百炼切到 DeepSeek 官方（百炼欠费）。
# key 以 DEEPSEEK_API_KEY 为准，DASHSCOPE_API_KEY 仅作旧部署兜底。
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "") or os.getenv("DASHSCOPE_API_KEY", "")
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL", "deepseek-flash")
DEEPSEEK_BASE_URL = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com")

# 已下线型号 → 当前在售型号。老前端 bundle 会缓存在用户浏览器里继续发旧模型名，
# 原样透传给上游必然 404/无可用渠道，所以在最底层统一归一，各调用方不必各自处理。
# 注意 claude-sonnet-4-6 曾是 PDF 导入的默认选中项，缓存用户命中率不低。
LEGACY_MODEL_ALIASES = {
    "deepseek-v4-flash": DEEPSEEK_MODEL,
    "deepseek-chat": DEEPSEEK_MODEL,
    "deepseek-reasoner": DEEPSEEK_MODEL,
    "claude-sonnet-4-6": DEEPSEEK_MODEL,
    "qwen-max": DEEPSEEK_MODEL,
    "qwen-plus": DEEPSEEK_MODEL,
    "qwen-plus-latest": DEEPSEEK_MODEL,
    "qwen-turbo": DEEPSEEK_MODEL,
}


def normalize_model_name(model: str | None) -> str:
    """把已下线型号换成当前在售型号；未知名字原样返回。"""
    name = (model or "").strip()
    if not name:
        return DEEPSEEK_MODEL
    return LEGACY_MODEL_ALIASES.get(name, name)


"""全局客户端实例，避免重复创建"""


"""
导入 requests 用于 HTTP 调用
"""
import requests
import json
import time
from requests.adapters import HTTPAdapter
try:
    from urllib3.util.retry import Retry
except ImportError:
    """如果没有 urllib3，使用简单的重试机制"""
    Retry = None
import urllib3
"""禁用 SSL 警告（仅在临时禁用验证时）"""
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# 导入 llm_utils（兼容多种运行方式）
try:
    from backend.llm_utils import retry_with_backoff
except ImportError:
    from llm_utils import retry_with_backoff

"""
========== HTTP 客户端优化 ==========
尝试使用支持 HTTP/2 + DNS 预解析的高性能客户端
"""
_use_http2_client = False
try:
    # 优先使用 backend 包形式
    from backend.http_client import (
        get_httpx_client, get_requests_session, 
        call_api, init as http_init, prefetch_api_hosts
    )
    _use_http2_client = True
    print("[simple] 使用 HTTP/2 高性能客户端")
except ImportError:
    try:
        # 兼容脚本直接运行的顶层导入
        from http_client import (
            get_httpx_client, get_requests_session, 
            call_api, init as http_init, prefetch_api_hosts
        )
        _use_http2_client = True
        print("[simple] 使用 HTTP/2 高性能客户端")
    except ImportError:
        # 回退到 requests
        print("[simple] http_client 模块不可用，使用默认 requests")

"""降级方案：原有的 Session"""
_http_session = None
_connection_warmed = False

def get_http_session():
    """获取 HTTP Session (优先使用 HTTP/2)"""
    global _http_session
    
    """优先使用 HTTP/2 客户端"""
    if _use_http2_client:
        return get_requests_session()
    
    """降级方案"""
    if _http_session is None:
        _http_session = requests.Session()
        adapter = HTTPAdapter(
            pool_connections=20,
            pool_maxsize=50,
            max_retries=Retry(
                total=1,
                backoff_factor=0.05,
                status_forcelist=[502, 503, 504]
            ) if Retry else 1
        )
        _http_session.mount('http://', adapter)
        _http_session.mount('https://', adapter)
        _http_session.headers.update({
            'Connection': 'keep-alive',
            'Accept-Encoding': 'gzip, deflate',  # 不使用 br (Brotli)，requests 不支持自动解压
            'Accept': 'application/json',
        })
    return _http_session


def warmup_connection():
    """预热 HTTP 连接 + DNS 预解析"""
    global _connection_warmed
    if _connection_warmed:
        return
    
    """使用新的 http_client 预热"""
    if _use_http2_client:
        try:
            """执行 DNS 预解析"""
            prefetch_api_hosts()
            _connection_warmed = True
            return
        except:
            pass
    
    """降级方案"""
    try:
        session = get_http_session()
        session.head(DEEPSEEK_BASE_URL, timeout=2)
        _connection_warmed = True
    except:
        pass


"""简化的系统提示词，让模型更快响应"""
FAST_SYSTEM_PROMPT = """你是一个简历解析助手。直接输出 JSON，不要多余解释。"""


@retry_with_backoff(max_retries=1, initial_delay=0.1)

def _deepseek_thinking_off(model: str) -> dict:
    """deepseek-* 关闭思考模式的请求字段。

    deepseek-flash 默认开思考，会返回 reasoning_content、拖慢解析并多烧 token。
    只认 thinking.type=disabled —— DashScope 时代的 enable_thinking=false 在官方端被静默忽略。
    """
    return {"thinking": {"type": "disabled"}} if (model or "").startswith("deepseek") else {}


def _get_live_deepseek_key() -> str:
    """读取最新 DEEPSEEK_API_KEY（支持多 Worker 进程感知 .env 热更新）。"""
    global DEEPSEEK_API_KEY
    try:
        try:
            from backend.env_keys import get_live_api_key
        except ImportError:
            from env_keys import get_live_api_key
        live = get_live_api_key("deepseek")
        if live:
            DEEPSEEK_API_KEY = live
            return live
    except Exception:
        pass
    return (os.getenv("DEEPSEEK_API_KEY", "") or DEEPSEEK_API_KEY or os.getenv("DASHSCOPE_API_KEY", "")).strip()


def call_deepseek_api(prompt: str, model: str = None) -> str:
    """
    调用 DeepSeek API

    参数:
        prompt: 用户输入的提示词
        model: 使用的模型名称，默认为 DEEPSEEK_MODEL

    返回:
        API 返回的响应内容
    """
    live_key = _get_live_deepseek_key()
    # 检查 API Key 是否配置
    if not live_key:
        raise Exception("DEEPSEEK_API_KEY 未配置。请在本地 .env 或系统环境中设置 DEEPSEEK_API_KEY")
    
    if model is None:
        model = DEEPSEEK_MODEL

    api_url = f"{DEEPSEEK_BASE_URL}/chat/completions"

    """优化参数"""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": FAST_SYSTEM_PROMPT},
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.1,  # 极低温度
        "max_tokens": 4000,   # DeepSeek 支持较长输出
        "top_p": 0.9,
        "frequency_penalty": 0,
        "presence_penalty": 0,
        **_deepseek_thinking_off(model),
    }

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {live_key}"
    }

    """使用复用的 HTTP Session"""
    session = get_http_session()
    
    try:
        response = session.post(
            api_url,
            json=payload,
            headers=headers,
            timeout=50
        )
    except requests.exceptions.RequestException as e:
        raise Exception(f"DeepSeek API 网络请求失败: {str(e)}")

    if response.status_code == 200:
        # 检查响应内容
        if not response.content:
            raise Exception(f"DeepSeek API 返回空响应 (status=200, body为空)")
        
        # 检查是否是 gzip 压缩的内容（但响应头没有正确设置）
        if len(response.content) >= 2 and response.content[:2] == b'\x1f\x8b':  # gzip magic number
            import gzip
            try:
                decompressed = gzip.decompress(response.content).decode('utf-8')
                result = json.loads(decompressed)
                content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
                if not content:
                    raise Exception(f"DeepSeek API 返回空内容。响应: {json.dumps(result, ensure_ascii=False)[:500]}")
                return content
            except (gzip.BadGzipFile, json.JSONDecodeError, UnicodeDecodeError) as e:
                raise Exception(f"DeepSeek API 返回压缩数据但解压失败: {str(e)}")
        
        # 确保响应编码正确
        if response.encoding is None or response.encoding == 'ISO-8859-1':
            # 尝试从响应头或内容推断编码
            response.encoding = response.apparent_encoding or 'utf-8'
        
        # 获取响应文本
        try:
            raw_text = response.text
        except UnicodeDecodeError:
            # 如果解码失败，尝试使用 UTF-8
            raw_text = response.content.decode('utf-8', errors='ignore')
        
        # 检查响应是否为空
        if not raw_text or not raw_text.strip():
            raise Exception(f"DeepSeek API 返回空响应 (status=200, body为空)")
        
        # 尝试解析 JSON
        try:
            result = response.json()
        except (json.JSONDecodeError, ValueError) as e:
            preview = raw_text[:300] if len(raw_text) > 300 else raw_text
            raise Exception(f"DeepSeek API 返回非 JSON 内容: {preview}")
        
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        if not content:
            raise Exception(f"DeepSeek API 返回空内容。响应: {json.dumps(result, ensure_ascii=False)[:500]}")
        return content
    else:
        # 获取错误详情
        try:
            error_detail = response.text[:500] if response.text else "无响应内容"
        except:
            error_detail = response.content[:500].decode('utf-8', errors='ignore') if response.content else "无响应内容"
        try:
            error_json = response.json()
            if "error" in error_json:
                error_detail = error_json["error"].get("message", error_detail)
        except:
            pass
        raise Exception(f"DeepSeek API 错误 {response.status_code}: {error_detail}")


def call_deepseek_api_stream(prompt: str, model: str = None):
    """
    流式调用 DeepSeek API

    参数:
        prompt: 用户输入的提示词
        model: 使用的模型名称，默认为 DEEPSEEK_MODEL

    生成器返回:
        每次返回一个文本片段
    """
    if model is None:
        model = DEEPSEEK_MODEL

    api_url = f"{DEEPSEEK_BASE_URL}/chat/completions"

    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.3,
        "max_tokens": 4000,
        "top_p": 0.9,
        "stream": True,  # 启用流式输出
        **_deepseek_thinking_off(model),
    }

    live_key = _get_live_deepseek_key()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {live_key}"
    }

    # 使用复用的 HTTP Session
    session = get_http_session()
    response = session.post(
        api_url,
        json=payload,
        headers=headers,
        timeout=90,
        stream=True  # 启用流式响应
    )

    if response.status_code != 200:
        raise Exception(f"DeepSeek API 调用失败: {response.status_code} - {response.text}")

    # 解析 SSE 流
    for line in response.iter_lines():
        if line:
            line = line.decode('utf-8')
            if line.startswith('data: '):
                data = line[6:]  # 移除 'data: ' 前缀
                if data == '[DONE]':
                    break
                try:
                    import json
                    chunk = json.loads(data)
                    if 'choices' in chunk and len(chunk['choices']) > 0:
                        delta = chunk['choices'][0].get('delta', {})
                        content = delta.get('content', '')
                        if content:
                            yield content
                except json.JSONDecodeError:
                    continue


