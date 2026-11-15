from backend.agent.web.streaming.events import (
    ResumeGeneratedEvent,
    ResumePatchEvent,
)


def test_resume_patch_event_to_dict():
    evt = ResumePatchEvent(
        patch_id="p1",
        paths=["experience[0].details"],
        before={"experience": [{"details": "负责后端开发"}]},
        after={"experience": [{"details": "主导重构，QPS提升3x"}]},
        summary="量化工作经历",
        operation="update",
    )
    d = evt.to_dict()
    # Canonical 协议：公共外壳 + 唯一 data 业务载荷。
    assert d["type"] == "resume_patch"
    assert d["data"]["patch_id"] == "p1"
    assert d["data"]["paths"] == ["experience[0].details"]
    assert d["data"]["summary"] == "量化工作经历"
    assert d["data"]["operation"] == "update"
    assert "timestamp" in d and "session_id" in d

def test_resume_generated_event_to_dict():
    evt = ResumeGeneratedEvent(
        resume={"basic": {"name": "张三"}},
        summary="已生成后端工程师简历",
    )
    d = evt.to_dict()
    # Canonical 协议：业务字段不再在外壳重复铺平。
    assert d["type"] == "resume_generated"
    assert d["data"]["resume"]["basic"]["name"] == "张三"
    assert d["data"]["summary"] == "已生成后端工程师简历"

def test_resume_patch_event_session_id():
    evt = ResumePatchEvent(
        patch_id="p1", paths=[], before={}, after={}, summary="test",
        session_id="sess-123"
    )
    d = evt.to_dict()
    assert d.get("session_id") == "sess-123"
