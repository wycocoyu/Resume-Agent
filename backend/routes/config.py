"""
配置管理路由（统一管理 DeepSeek 官方 API Key 与 智谱 GLM-OCR API Key）
"""
import os
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from pydantic import BaseModel

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

# 统一优先使用顶层模块，避免 models 被重复加载为两个模块名
try:
    from models import SaveKeysRequest, AITestRequest, ChatRequest
    from llm import call_llm, get_ai_config
    from middleware.auth import AppUser, get_current_user_optional, require_admin_only
    from prompt_templates import (
        get_prompt_templates,
        save_prompt_templates,
        get_prompt_registry,
    )
except ImportError:  # fallback
    from backend.models import SaveKeysRequest, AITestRequest, ChatRequest
    from backend.llm import call_llm, get_ai_config
    from backend.middleware.auth import AppUser, get_current_user_optional, require_admin_only
    from backend.prompt_templates import (
        get_prompt_templates,
        save_prompt_templates,
        get_prompt_registry,
    )

router = APIRouter(prefix="/api", tags=["Config"])

ROOT_DIR = Path(__file__).resolve().parents[2]

_ENV_KEY_BY_PROVIDER = {
    "deepseek": "DEEPSEEK_API_KEY",
    "zhipu": "ZHIPU_API_KEY",
}


class SavePromptsRequest(BaseModel):
    prompts: dict[str, str] | None = None
    rewrite_text_prompt_template: str | None = None  # backward compatible
    rewrite_default_instruction: str | None = None  # backward compatible


def _is_local_unauthenticated_dev(request: Request) -> bool:
    """判断是否为本地自托管开发环境请求（允许开源本地启动免登配置 .env 密钥）。
    线上生产环境（LOG_MODE=production 或经过反向代理 X-Forwarded-For）一律返回 False。
    """
    if os.getenv("LOG_MODE", "").strip().lower() == "production":
        return False
    if request.headers.get("x-forwarded-for") or request.headers.get("x-real-ip"):
        return False
    client_host = (request.client.host if request.client else "") or ""
    return client_host in {"127.0.0.1", "::1", "localhost"}


async def require_config_access(
    request: Request,
    current_user: Optional[AppUser] = Depends(get_current_user_optional),
) -> Optional[AppUser]:
    """配置管理权限守卫：
    - 已登录管理员（role == 'admin'）放行；
    - 本地直连开发环境且未登录时放行（方便开源本地启动首次配 Key）；
    - 其余情况：未登录返回 401，非管理员返回 403。
    """
    if current_user is not None:
        if current_user.role != "admin":
            raise HTTPException(status_code=403, detail="仅管理员可访问密钥配置")
        return current_user
    if _is_local_unauthenticated_dev(request):
        return None
    raise HTTPException(status_code=401, detail="未提供有效的认证信息")


def _mask_key(raw: str) -> str:
    """对 API Key 生成安全的脱敏预览"""
    val = (raw or "").strip()
    if not val:
        return ""
    if len(val) > 12:
        return f"{val[:8]}••••••{val[-4:]}"
    if len(val) > 6:
        return f"{val[:4]}••••{val[-2:]}"
    return f"{val[:2]}•••"


def _read_current_keys() -> dict[str, str]:
    """从 .env 文件与当前进程环境变量读取最新的 DEEPSEEK_API_KEY 与 ZHIPU_API_KEY。"""
    env_path = ROOT_DIR / ".env"
    file_vals: dict[str, str] = {}
    if env_path.exists():
        try:
            with open(env_path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    key, value = line.split("=", 1)
                    key = key.strip()
                    value = value.strip().strip('"').strip("'")
                    file_vals[key] = value
        except Exception:
            pass

    deepseek_key = (
        file_vals.get("DEEPSEEK_API_KEY")
        if "DEEPSEEK_API_KEY" in file_vals
        else (os.getenv("DEEPSEEK_API_KEY", "") or file_vals.get("DASHSCOPE_API_KEY", "") or os.getenv("DASHSCOPE_API_KEY", ""))
    ).strip()

    zhipu_key = (
        file_vals.get("ZHIPU_API_KEY")
        if "ZHIPU_API_KEY" in file_vals
        else os.getenv("ZHIPU_API_KEY", "")
    ).strip()

    return {
        "deepseek": deepseek_key,
        "zhipu": zhipu_key,
    }


def _sync_runtime_keys(deepseek_key: Optional[str] = None, zhipu_key: Optional[str] = None) -> None:
    """将最新 Key 同步到进程环境变量、simple 模块、zhipu_layout 模块及 Agent 运行时配置。"""
    if deepseek_key is not None:
        os.environ["DEEPSEEK_API_KEY"] = deepseek_key
        try:
            try:
                from backend import simple
            except ImportError:
                import simple
            simple.DEEPSEEK_API_KEY = deepseek_key
        except Exception as e:
            print(f"[警告] 同步 simple.DEEPSEEK_API_KEY 失败: {e}")

        # 同步 Agent Config 单例（若已初始化）
        try:
            from backend.agent.config import Config as AgentConfig
            if AgentConfig._instance is not None and getattr(AgentConfig._instance, "_config", None) is not None:
                llm_map = getattr(AgentConfig._instance._config, "llm", {}) or {}
                if "default" in llm_map and llm_map["default"] is not None:
                    llm_map["default"].api_key = deepseek_key
        except Exception:
            pass

    if zhipu_key is not None:
        os.environ["ZHIPU_API_KEY"] = zhipu_key
        try:
            try:
                from backend.services.zhipu_layout import refresh_zhipu_api_key
            except ImportError:
                from services.zhipu_layout import refresh_zhipu_api_key
            refresh_zhipu_api_key(zhipu_key)
        except Exception as e:
            print(f"[警告] 同步 zhipu_layout.ZHIPU_API_KEY 失败: {e}")


@router.get("/ai/config")
async def get_ai_config_endpoint():
    """获取当前 AI 配置"""
    return get_ai_config()


@router.get("/config/keys")
async def get_keys_status(_current_user=Depends(require_config_access)):
    """获取 API Key 配置状态（不返回明文 Key，仅返回脱敏预览与配置状态）"""
    keys = _read_current_keys()
    deepseek_key = keys["deepseek"]
    zhipu_key = keys["zhipu"]

    return {
        "deepseek": {
            "configured": bool(deepseek_key and len(deepseek_key) >= 8),
            "preview": _mask_key(deepseek_key) if deepseek_key and len(deepseek_key) >= 8 else "",
            "env_key": "DEEPSEEK_API_KEY",
            "model": os.getenv("DEEPSEEK_MODEL", "deepseek-flash"),
        },
        "zhipu": {
            "configured": bool(zhipu_key and len(zhipu_key) >= 8),
            "preview": _mask_key(zhipu_key) if zhipu_key and len(zhipu_key) >= 8 else "",
            "env_key": "ZHIPU_API_KEY",
            "model": os.getenv("ZHIPU_OCR_MODEL", "glm-ocr"),
        },
    }


def _blank_env_keys(env_keys: list[str]) -> None:
    """把指定 env key 的值清空（保留行），并同步进程内存状态"""
    env_path = ROOT_DIR / ".env"
    lines = []
    if env_path.exists():
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    with open(env_path, "w", encoding="utf-8") as f:
        for line in lines:
            key = line.split("=", 1)[0].strip() if "=" in line else ""
            f.writelines([f"{key}=\n"] if key in env_keys else [line])

    if "DEEPSEEK_API_KEY" in env_keys:
        _sync_runtime_keys(deepseek_key="")
    if "ZHIPU_API_KEY" in env_keys:
        _sync_runtime_keys(zhipu_key="")


@router.delete("/config/keys/{provider}")
async def delete_key(provider: str, _current_user=Depends(require_config_access)):
    """删除单个 Provider 的 API Key（清空 .env 中的值并同步内存）"""
    env_key = _ENV_KEY_BY_PROVIDER.get(provider)
    if not env_key:
        raise HTTPException(status_code=404, detail=f"未知 provider: {provider}")
    _blank_env_keys([env_key])
    return {"success": True, "message": f"{provider} 的 API Key 已删除"}


@router.delete("/config/keys")
async def clear_keys(_current_user=Depends(require_config_access)):
    """清除全部已存储的 API Key"""
    _blank_env_keys(list(_ENV_KEY_BY_PROVIDER.values()))
    return {"success": True, "message": "全部 API Key 已清除"}


@router.get("/config/stats")
async def get_config_stats(_current_user=Depends(require_config_access)):
    """系统状态统计：数据库连通、简历数、用户数、DeepSeek base_url"""
    try:
        from database import SessionLocal
    except ImportError:
        from backend.database import SessionLocal
    from sqlalchemy import text as sql_text

    db_ok = True
    resumes = 0
    users = 0
    try:
        db = SessionLocal()
        try:
            resumes = db.execute(sql_text("SELECT count(*) FROM resumes")).scalar() or 0
            users = db.execute(sql_text('SELECT count(*) FROM "user"')).scalar() or 0
        finally:
            db.close()
    except Exception:
        db_ok = False

    try:
        from backend import simple
    except ImportError:
        import simple
    base_url = getattr(simple, "DEEPSEEK_BASE_URL", "https://api.deepseek.com")

    return {"db_ok": db_ok, "resumes": resumes, "users": users, "deepseek_base_url": base_url}


@router.post("/config/keys")
async def save_keys(body: SaveKeysRequest, _current_user=Depends(require_config_access)):
    """保存 DeepSeek 与智谱 GLM-OCR 的 API Key 到 .env 文件并热更新内存"""
    try:
        deepseek_val = body.deepseek_key.strip() if body.deepseek_key else None
        zhipu_val = body.zhipu_key.strip() if body.zhipu_key else None

        if not deepseek_val and not zhipu_val:
            raise HTTPException(status_code=400, detail="请至少填写一个需要保存的 API Key")

        env_path = ROOT_DIR / ".env"
        existing_lines = []
        if env_path.exists():
            with open(env_path, "r", encoding="utf-8") as f:
                existing_lines = f.readlines()

        new_lines = []
        deepseek_found = False
        zhipu_found = False

        for line in existing_lines:
            stripped = line.strip()
            key_part = stripped.split("=", 1)[0].strip() if "=" in stripped and not stripped.startswith("#") else ""
            if key_part == "DEEPSEEK_API_KEY" and deepseek_val is not None:
                new_lines.append(f"DEEPSEEK_API_KEY={deepseek_val}\n")
                deepseek_found = True
            elif key_part == "ZHIPU_API_KEY" and zhipu_val is not None:
                new_lines.append(f"ZHIPU_API_KEY={zhipu_val}\n")
                zhipu_found = True
            else:
                new_lines.append(line)

        if new_lines and not new_lines[-1].endswith("\n"):
            new_lines[-1] = new_lines[-1] + "\n"

        if deepseek_val is not None and not deepseek_found:
            new_lines.append(f"DEEPSEEK_API_KEY={deepseek_val}\n")
        if zhipu_val is not None and not zhipu_found:
            new_lines.append(f"ZHIPU_API_KEY={zhipu_val}\n")

        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)

        if load_dotenv:
            load_dotenv(dotenv_path=str(env_path), override=True)

        _sync_runtime_keys(deepseek_key=deepseek_val, zhipu_key=zhipu_val)

        return {"success": True, "message": "API Key 已保存并立即生效"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"保存失败: {str(e)}")


@router.get("/config/prompts")
async def get_prompts(_current_user=Depends(require_admin_only)):
    """获取提示词模板配置（后台管理）"""
    return {
        "items": get_prompt_registry(),
        "templates": get_prompt_templates(),
    }


@router.put("/config/prompts")
async def save_prompts(body: SavePromptsRequest, _current_user=Depends(require_admin_only)):
    """保存提示词模板配置（后台管理）"""
    updates: dict[str, str] = {}
    if body.prompts:
        updates.update(body.prompts)
    if body.rewrite_text_prompt_template:
        updates["rewrite_text_prompt_template"] = body.rewrite_text_prompt_template
    if body.rewrite_default_instruction:
        updates["rewrite_default_instruction"] = body.rewrite_default_instruction

    updated = save_prompt_templates(updates)
    return {"success": True, "prompts": updated}


@router.get("/ai/test-keys")
async def test_ai_keys(
    provider: Optional[str] = Query(default=None, description="可选：仅检测指定通道 deepseek 或 zhipu"),
    _current_user=Depends(require_config_access),
):
    """检测 DeepSeek 与 智谱 GLM-OCR 的 API Key 是否真实连通可用"""
    keys = _read_current_keys()
    _sync_runtime_keys(
        deepseek_key=keys["deepseek"] if keys["deepseek"] else None,
        zhipu_key=keys["zhipu"] if keys["zhipu"] else None,
    )

    targets = ["deepseek", "zhipu"]
    if provider in ("deepseek", "zhipu"):
        targets = [provider]

    result = {}
    for item in targets:
        raw_key = keys.get(item, "")
        if not raw_key or len(raw_key) < 8:
            result[item] = {"configured": False, "ok": False, "error": "尚未配置密钥"}
            continue

        try:
            if item == "deepseek":
                call_llm("deepseek", "请仅回复OK", return_usage=False)
                result[item] = {"configured": True, "ok": True}
            elif item == "zhipu":
                try:
                    from backend.services.zhipu_layout import test_zhipu_api_key
                except ImportError:
                    from services.zhipu_layout import test_zhipu_api_key
                test_zhipu_api_key(raw_key)
                result[item] = {"configured": True, "ok": True}
        except HTTPException as he:
            result[item] = {
                "configured": True,
                "ok": False,
                "error": str(he.detail) if he.detail else f"HTTP {he.status_code}",
            }
        except Exception as e:
            result[item] = {"configured": True, "ok": False, "error": str(e)}

    return result


@router.post("/ai/test")
async def ai_test(body: AITestRequest):
    """测试已有 AI 接口是否可用"""
    try:
        result = call_llm(body.provider, body.prompt, return_usage=True)
        if isinstance(result, dict):
            return {
                "provider": body.provider,
                "result": result.get("content", ""),
                "usage": result.get("usage", {})
            }
        else:
            return {"provider": body.provider, "result": result, "usage": {}}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 测试失败: {e}")


@router.post("/chat")
async def chat_api(body: ChatRequest):
    """通用聊天接口，用于AI改写等功能"""
    try:
        prompt_parts = []
        for msg in body.messages:
            if msg.role == "system":
                prompt_parts.append(f"系统指令：{msg.content}")
            elif msg.role == "user":
                prompt_parts.append(f"用户：{msg.content}")
            elif msg.role == "assistant":
                prompt_parts.append(f"助手：{msg.content}")

        prompt = "\n\n".join(prompt_parts) + "\n\n请回复："

        provider = body.provider or "deepseek"
        if not (os.getenv("DEEPSEEK_API_KEY") or os.getenv("DASHSCOPE_API_KEY")):
            raise HTTPException(
                status_code=400,
                detail="未配置 DEEPSEEK_API_KEY，请在设置页或 .env 中配置 DeepSeek API Key",
            )

        result = call_llm(provider, prompt)
        return {"content": result, "provider": provider}
    except HTTPException as he:
        raise he
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 请求失败: {e}")
