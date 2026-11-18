"""
路由模块
"""
from .health import router as health_router
from .config import router as config_router
from .resume import router as resume_router
from .auth import router as auth_router
from .better_auth import router as better_auth_router
from .pdf import router as pdf_router
from .share import router as share_router
from .resumes import router as resumes_router
from .logos import router as logos_router
from .school_logos import router as school_logos_router
from .photos import router as photos_router
from .asr import router as asr_router
from .semantic_search import router as semantic_search_router
from .admin import router as admin_router
from .leetcode import router as leetcode_router
from .billing import router as billing_router

# TTS 路由（优先使用 edge-tts，如果不可用则尝试 Coqui TTS）
try:
    from .tts_edge import router as tts_router
    _tts_available = True
    _tts_type = "edge-tts"
except Exception:
    # edge-tts 不可用，尝试 Coqui TTS
    try:
        from .tts import router as tts_router
        _tts_available = True
        _tts_type = "coqui-tts"
    except Exception:
        # TTS 依赖未安装，创建一个占位符
        tts_router = None
        _tts_available = False
        _tts_type = None

__all__ = [
    'health_router',
    'config_router',
    'resume_router',
    'pdf_router',
    'share_router',
    'auth_router',
    'better_auth_router',
    'resumes_router',
    'logos_router',
    'school_logos_router',
    'photos_router',
    'tts_router',
    'asr_router',
    'semantic_search_router',
    'admin_router',
    'leetcode_router',
    'billing_router',
]
