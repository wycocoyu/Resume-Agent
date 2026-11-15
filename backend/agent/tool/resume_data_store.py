"""
共享的简历数据存储

所有简历相关工具（cv_reader_agent, cv_analyzer_agent, cv_editor_agent）
共享同一个简历数据源，确保数据一致性。
"""

import uuid
from copy import deepcopy
from typing import Optional, Dict, Any

from backend.agent.agent.shared_state import AgentSharedState
from backend.agent.utils.experience_entry import sanitize_resume_payload
from backend.agent.utils.optimize_progress import (
    build_module_facts,
    compute_pending_modules,
)
from backend.core.logger import get_logger

logger = get_logger(__name__)


class ResumeDataStore:
    """共享的简历数据存储"""

    _data: Optional[dict] = None
    _data_by_session: Dict[str, dict] = {}
    _shared_state_by_session: Dict[str, AgentSharedState] = {}
    _meta_by_session: Dict[str, Dict[str, Any]] = {}
    # 会话级目标岗位 JD：一次提供、本会话后续所有优化自动对齐
    _jd_by_session: Dict[str, str] = {}
    # 会话级"整份优化"任务内进度（任务级状态，非简历数据、非跨会话记忆）：
    # {task_id, status: optimizing|reviewing|done, pending:[模块], done:[], facts:{},
    #  continue_count, review_dispatched}。见 optimize_progress.py 与设计方案七点二。
    # 清理：clear_data() 里 pop（跟随简历数据），另有 clear_progress() 供
    # session_manager.discard_session 在"是否保留简历数据"门外无条件调用——
    # 这仓库已犯过 3 次"新增会话字典忘接清理"，反射式元测试兜底防复发。
    _progress_by_session: Dict[str, Dict[str, Any]] = {}

    @staticmethod
    def _extract_meta(resume_data: dict) -> Dict[str, Any]:
        """从简历数据中提取元信息（如 resume_id/user_id）"""
        meta = resume_data.get("_meta") or {}
        return {
            "resume_id": resume_data.get("resume_id") or resume_data.get("id") or meta.get("resume_id"),
            "user_id": resume_data.get("user_id") or meta.get("user_id"),
        }

    @staticmethod
    def _extract_name(resume_data: dict) -> Optional[str]:
        """尽量从简历数据中提取名称"""
        basics = resume_data.get("basic") or resume_data.get("basics") or {}
        if isinstance(basics, str):
            return basics.strip() or None
        if isinstance(basics, dict):
            return basics.get("name")
        return None

    @staticmethod
    def _needs_sanitize(resume_data: dict) -> bool:
        basic = resume_data.get("basic") or resume_data.get("basics")
        if isinstance(basic, str):
            return True
        exp = resume_data.get("experience")
        if isinstance(exp, list):
            for item in exp:
                if item is None or item == {} or isinstance(item, str):
                    return True
        return False

    @classmethod
    def _prepare_data(cls, resume_data: dict) -> dict:
        if not isinstance(resume_data, dict):
            return {}
        if not cls._needs_sanitize(resume_data):
            return resume_data
        return sanitize_resume_payload(resume_data)

    @classmethod
    def set_data(cls, resume_data: dict, session_id: Optional[str] = None):
        """设置简历数据（严格按 session 隔离）"""
        cleaned = cls._prepare_data(resume_data)
        if session_id:
            cls._data_by_session[session_id] = cleaned
            cls._meta_by_session[session_id] = cls._extract_meta(cleaned)
            shared_state = cls._shared_state_by_session.get(session_id)
            if shared_state:
                shared_state.set("resume_data", cleaned)
        else:
            cls._data = cleaned

    @classmethod
    def get_data(cls, session_id: Optional[str] = None) -> Optional[dict]:
        """获取简历数据（严格按 session，不 fallback 到全局）"""
        if session_id:
            raw: Optional[dict] = None
            shared_state = cls._shared_state_by_session.get(session_id)
            if shared_state and shared_state.has("resume_data"):
                raw = shared_state.get("resume_data")
            elif session_id in cls._data_by_session:
                raw = cls._data_by_session[session_id]
            if raw is None:
                return None
            cleaned = cls._prepare_data(raw)
            if cleaned != raw:
                cls._data_by_session[session_id] = cleaned
                if shared_state:
                    shared_state.set("resume_data", cleaned)
            return cleaned
        if cls._data is None:
            return None
        return cls._prepare_data(cls._data)

    @classmethod
    def clear_data(cls, session_id: Optional[str] = None):
        """清空简历数据"""
        if session_id:
            cls._data_by_session.pop(session_id, None)
            cls._meta_by_session.pop(session_id, None)
            cls._jd_by_session.pop(session_id, None)
            cls._progress_by_session.pop(session_id, None)
            shared_state = cls._shared_state_by_session.pop(session_id, None)
            if shared_state:
                shared_state.delete("resume_data")
        else:
            cls._data = None

    @classmethod
    def set_shared_state(cls, session_id: str, state: AgentSharedState):
        """绑定会话级 shared_state"""
        cls._shared_state_by_session[session_id] = state
        if session_id in cls._data_by_session:
            state.set("resume_data", deepcopy(cls._data_by_session[session_id]))

    @classmethod
    def snapshot(cls, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """返回可持久化的会话级简历状态快照。"""

        if not session_id:
            return None
        resume_data = cls.get_data(session_id)
        progress = cls.get_progress(session_id)
        if resume_data is None and not cls.get_session_jd(session_id) and progress is None:
            return None
        return {
            "resume_data": deepcopy(resume_data),
            "meta": deepcopy(cls._meta_by_session.get(session_id, {})),
            "jd": cls.get_session_jd(session_id),
            "progress": deepcopy(progress),
        }

    @classmethod
    def restore_snapshot(
        cls,
        session_id: Optional[str],
        snapshot: Optional[Dict[str, Any]],
    ) -> None:
        """恢复持久化的会话级简历状态；缺失或损坏快照时安全跳过。"""

        if not session_id or not isinstance(snapshot, dict):
            return
        resume_data = snapshot.get("resume_data")
        if isinstance(resume_data, dict):
            cls.set_data(deepcopy(resume_data), session_id=session_id)
        jd = snapshot.get("jd")
        if isinstance(jd, str) and jd.strip():
            cls.set_session_jd(session_id, jd)
        progress = snapshot.get("progress")
        if isinstance(progress, dict):
            cls._progress_by_session[session_id] = deepcopy(progress)

    @classmethod
    def persist_data(cls, session_id: str) -> bool:
        """将简历数据写回 AI 简历存储（如果具备必要上下文）"""
        resume_data = cls.get_data(session_id)
        if not resume_data:
            logger.warning(
                f"[ResumeDataStore] No resume data for session: {session_id}"
            )
            return False

        meta = cls._meta_by_session.get(session_id, {})
        resume_id = meta.get("resume_id")
        user_id = meta.get("user_id")
        if not resume_id or not user_id:
            logger.warning(
                "[ResumeDataStore] Missing resume_id or user_id for session: "
                f"{session_id}, meta={meta}"
            )
            return False

        try:
            from backend.database import SessionLocal
            from backend.models import Resume

            db = SessionLocal()
            try:
                resume = db.query(Resume).filter(
                    Resume.id == resume_id, Resume.user_id == user_id
                ).first()
                if not resume:
                    # resume_id 不在 DB 里（如 LaTeX 简历前端创建后未入库），
                    # 自动创建一条记录，避免修改只在内存生效、断连后丢失。
                    name = cls._extract_name(resume_data) or "未命名简历"
                    resume = Resume(
                        id=resume_id,
                        user_id=user_id,
                        name=name,
                        data=resume_data,
                    )
                    db.add(resume)
                    logger.info(
                        "[ResumeDataStore] Auto-created resume: "
                        f"resume_id={resume_id}, name={name}"
                    )
                else:
                    resume.name = cls._extract_name(resume_data) or resume.name
                    resume.data = resume_data

                db.commit()
                logger.info(
                    "[ResumeDataStore] Successfully persisted resume: "
                    f"resume_id={resume_id}, name={resume.name}"
                )
                return True
            finally:
                db.close()
        except Exception as exc:
            logger.exception(
                "[ResumeDataStore] Failed to persist resume: "
                f"session_id={session_id}, resume_id={resume_id}, error={exc}"
            )
            return False


    @classmethod
    def set_session_jd(cls, session_id: str, jd_text: str) -> None:
        """记录本会话的目标岗位 JD（后续优化自动对齐）。"""
        if session_id and jd_text and jd_text.strip():
            cls._jd_by_session[session_id] = jd_text.strip()

    @classmethod
    def get_session_jd(cls, session_id: str) -> str:
        return cls._jd_by_session.get(session_id or "", "")

    # ---- 整份优化任务内进度（会话级/任务级，非跨会话记忆）----

    # 续跑硬上限：per-task 服务端自动续跑次数封顶，超过强制收尾防死循环
    # （设计方案七点一：auto_continue 不设上限会死循环）。
    MAX_CONTINUE_COUNT: int = 4

    @classmethod
    def get_progress(cls, session_id: Optional[str]) -> Optional[Dict[str, Any]]:
        """取当前会话的整份优化进度，无任务返回 None。"""
        if not session_id:
            return None
        return cls._progress_by_session.get(session_id)

    @classmethod
    def init_progress(
        cls, session_id: str, resume_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """初始化一次整份优化任务：pending 由简历结构确定性算出，不问 LLM。

        幂等安全：已有"未完成"任务直接复用（避免同一任务多步 think 反复重置）；
        只有无任务或上一任务已 done 时才新建。
        """
        existing = cls._progress_by_session.get(session_id)
        if existing and existing.get("status") != "done":
            return existing

        pending = compute_pending_modules(resume_data)
        progress: Dict[str, Any] = {
            "task_id": uuid.uuid4().hex,
            "status": "optimizing",
            "pending": pending,
            "done": [],
            "facts": build_module_facts(resume_data, pending),
            "continue_count": 0,
            "review_dispatched": False,
        }
        cls._progress_by_session[session_id] = progress
        logger.info(
            f"[ResumeDataStore] 整份优化任务初始化: session={session_id}, "
            f"task_id={progress['task_id']}, pending={pending}"
        )
        return progress

    @classmethod
    def mark_module_done(
        cls, session_id: str, module: str, skip: bool = False
    ) -> bool:
        """把某模块从 pending 移入 done（幂等：不在 pending 里则 no-op）。

        pending 清空且仍处 optimizing 时，代码规则触发相变 optimizing→reviewing
        （零 LLM 步数）。返回是否发生了推进。
        """
        progress = cls._progress_by_session.get(session_id)
        if not progress or module not in progress.get("pending", []):
            return False
        progress["pending"].remove(module)
        if module not in progress["done"]:
            progress["done"].append(module)
        logger.info(
            f"[ResumeDataStore] 模块推进{'(skip)' if skip else ''}: {module} "
            f"→ done; 剩余 pending={progress['pending']}"
        )
        if not progress["pending"] and progress["status"] == "optimizing":
            progress["status"] = "reviewing"
            logger.info(
                f"[ResumeDataStore] 全部模块处理完，相变 optimizing→reviewing: "
                f"session={session_id}"
            )
        return True

    @classmethod
    def bump_continue_count(cls, session_id: str) -> int:
        """自动续跑计数 +1，返回新值。"""
        progress = cls._progress_by_session.get(session_id)
        if not progress:
            return 0
        progress["continue_count"] = progress.get("continue_count", 0) + 1
        return progress["continue_count"]

    @classmethod
    def mark_review_dispatched(cls, session_id: str) -> None:
        """标记一致性审阅请求已独占派发一次（防止重复触发审阅）。"""
        progress = cls._progress_by_session.get(session_id)
        if progress:
            progress["review_dispatched"] = True

    @classmethod
    def finish_progress(cls, session_id: str) -> None:
        """任务收尾：清空进度（下次整份优化请求重新初始化）。"""
        cls._progress_by_session.pop(session_id, None)

    @classmethod
    def clear_progress(cls, session_id: Optional[str] = None) -> None:
        """清空整份优化进度。session_id 为空时清全部（防御性）。

        由 session_manager.discard_session 在"是否保留简历数据"门外无条件调用：
        进度是任务级状态，不该被"保留简历数据"的决定连带影响。
        """
        if session_id:
            cls._progress_by_session.pop(session_id, None)
        else:
            cls._progress_by_session.clear()
