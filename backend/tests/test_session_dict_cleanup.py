"""反射式清理覆盖元测试（2026-07-12，设计方案七点三）。

结构性根除"新增会话级字典忘接统一清理入口"这个错——这仓库已经犯过 3 次
（session_manager.py docstring + git log a3082cc7/a3003809/f766b6f5）。

做法：用反射自动枚举 ResumeDataStore 上所有 `_*_by_session` 命名的类级字典，
逐一塞一条会话数据，走一遍 discard_session，断言每个字典都被清空。
任何人以后再新增一个 `_xxx_by_session` 却忘了接清理，这个测试会自动挂掉，
不依赖手工维护清单。
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))

from backend.core.logger import setup_logging
setup_logging(False, "INFO", "logs/test")

import backend.agent.pi_core.resume_agent as _runtime  # noqa: F401 触发 tool 包初始化，避开循环导入
from backend.agent.tool.resume_data_store import ResumeDataStore
from backend.agent.web import session_manager


class _DuckDummy:
    """鸭子类型占位：任何被清理逻辑调用的方法（如 shared_state.delete）都吞成 no-op，
    让元测试对每个字典塞同一种占位而不必硬编码各字典的真实值类型。"""

    def __getattr__(self, _name):
        def _noop(*args, **kwargs):
            return None

        return _noop


def _session_dict_attrs():
    """反射枚举 ResumeDataStore 上所有 `_*_by_session` 的类级 dict 属性名。"""
    return [
        name
        for name, val in vars(ResumeDataStore).items()
        if name.endswith("_by_session") and isinstance(val, dict)
    ]


def test_reflective_all_session_dicts_present():
    """至少枚举到已知的 4 个会话字典，防止反射本身失效导致空跑。"""
    attrs = set(_session_dict_attrs())
    for expected in (
        "_data_by_session",
        "_meta_by_session",
        "_jd_by_session",
        "_progress_by_session",
    ):
        assert expected in attrs, f"反射未枚举到 {expected}，元测试可能失效"


def test_discard_session_clears_every_session_dict():
    """核心断言：discard_session 后，每个 `_*_by_session` 都不再残留该会话数据。"""
    sid = "reflective-cleanup-session"
    attrs = _session_dict_attrs()
    assert attrs, "未枚举到任何会话字典，反射失效"

    # 每个会话字典都塞一条该 session 的数据（鸭子占位，避免依赖各字典真实值类型）
    for name in attrs:
        getattr(ResumeDataStore, name)[sid] = _DuckDummy()

    # 也登记一条内存会话条目，走完整 discard 路径
    session_manager.register_session(sid, {"user_id": "uDictCleanup32CharBaId000001"})

    session_manager.discard_session(sid)

    leaked = [name for name in attrs if sid in getattr(ResumeDataStore, name)]
    assert not leaked, f"discard_session 后以下会话字典仍残留 {sid}: {leaked}"


def test_discard_session_keep_resume_data_still_clears_progress():
    """clear_resume_data=False（原地重建会话）时，进度仍必须被清——它是任务级
    状态，不该被"保留简历数据"的决定连带保留（设计方案七点三，门外无条件清理）。"""
    sid = "keep-resume-clear-progress"
    ResumeDataStore._data_by_session[sid] = {"basic": {"name": "x"}}
    ResumeDataStore._progress_by_session[sid] = {"status": "optimizing", "pending": ["projects"]}

    session_manager.discard_session(sid, clear_resume_data=False)

    assert sid not in ResumeDataStore._progress_by_session, "进度未在门外被清理"
    # 简历数据按约定保留（clear_resume_data=False）
    assert sid in ResumeDataStore._data_by_session, "clear_resume_data=False 不应清简历数据"

    ResumeDataStore._data_by_session.pop(sid, None)
