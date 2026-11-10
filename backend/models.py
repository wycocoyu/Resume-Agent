"""
Pydantic 数据模型定义
"""
import sys
from pydantic import BaseModel, Field
from typing import Optional, Literal, List, Dict, Any
from sqlalchemy import Column, Integer, String, DateTime, Date, ForeignKey, JSON, Text, Boolean, Float, UniqueConstraint
from sqlalchemy.sql import func

# 统一模块别名，避免同一文件被以 `models` 和 `backend.models` 重复加载，
# 进而生成两套 SQLAlchemy mapper（会导致关系同步异常）。
if __name__ == "models":
    sys.modules.setdefault("backend.models", sys.modules[__name__])
elif __name__ == "backend.models":
    sys.modules.setdefault("models", sys.modules[__name__])

try:
    from database import Base
except ImportError:
    from backend.database import Base


class RewriteRequest(BaseModel):
    """重写请求"""
    provider: Literal["deepseek"] = Field(default="deepseek")
    resume: Dict[str, Any]
    path: str = Field(..., description="JSON 路径，如 summary 或 experience[0].achievements[1]")
    instruction: str = Field(..., description="修改意图，如：更量化、更贴合后端 JD")
    locale: Literal["zh", "en"] = Field(default="zh")
    history: list[dict] = Field(default=[], description="多轮对话历史 [{role, content}]")


class AITestRequest(BaseModel):
    """AI 测试请求"""
    provider: Literal["deepseek"] = Field(default="deepseek")
    prompt: str = Field(..., description="测试提示词")


class ResumeGenerateRequest(BaseModel):
    """简历生成请求"""
    provider: Literal["deepseek"] = Field(default="deepseek")
    instruction: str = Field(..., description="一句话或少量信息，说明岗位/经历/技能等")
    locale: Literal["zh", "en"] = Field(default="zh", description="输出语言")


class ResumeGenerateResponse(BaseModel):
    """简历生成响应"""
    resume: Dict[str, Any]
    provider: str


class ResumeJSON(BaseModel):
    """简历 JSON 结构"""
    name: Optional[str] = None
    contact: Optional[Dict[str, Optional[str]]] = None
    summary: Optional[str] = None
    experience: Optional[List[Dict[str, Any]]] = None
    projects: Optional[List[Dict[str, Any]]] = None
    skills: Optional[List[str]] = None
    education: Optional[List[Dict[str, Any]]] = None
    awards: Optional[List[Dict[str, Any]]] = None


class RenderPDFRequest(BaseModel):
    """PDF 渲染请求"""
    resume: Dict[str, Any]
    demo: Optional[bool] = False
    section_order: Optional[List[str]] = None
    engine: Optional[str] = "latex"


class SaveKeysRequest(BaseModel):
    """保存 API Key 请求（DeepSeek 官方 + 智谱 GLM-OCR）"""
    deepseek_key: Optional[str] = None
    zhipu_key: Optional[str] = None


class ChatMessage(BaseModel):
    """聊天消息"""
    role: str
    content: str


class ChatRequest(BaseModel):
    """聊天请求"""
    messages: List[ChatMessage]
    provider: Optional[str] = None


class SectionParseRequest(BaseModel):
    """单模块 AI 解析请求"""
    text: str = Field(..., description="用户粘贴的模块文本")
    section_type: str = Field(..., description="模块类型: contact/education/experience/projects/skills/awards/summary/opensource")
    provider: Optional[Literal["deepseek"]] = Field(default=None)
    model: Optional[str] = Field(default=None, description="可选，指定具体模型 (如 deepseek-v3.2, deepseek-reasoner)")


class ResumeParseRequest(BaseModel):
    """简历解析请求"""
    text: str = Field(..., description="用户粘贴的简历文本")
    provider: Optional[Literal["deepseek"]] = Field(default=None)
    model: Optional[str] = Field(default=None, description="可选，指定具体模型 (如 deepseek-v3.2, deepseek-reasoner)")


# ======================
# SQLAlchemy ORM 模型
# ======================

# 旧 JWT 用户表 User(users) 已于 2026-07-17 身份统一时退役：
# 身份唯一锚点 = BetterAuth "user".id（32 位字符串），app 侧 profile 见 BetterAuthEntitlement。
class BetterAuthEntitlement(Base):
    """BetterAuth 用户的商业化权益模型。"""
    __tablename__ = "better_auth_entitlements"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    better_auth_user_id = Column(String(255), unique=True, nullable=False, index=True)
    email = Column(String(255), nullable=True, index=True)
    name = Column(String(255), nullable=True)
    image = Column(Text, nullable=True)

    plan = Column(String(64), nullable=False, server_default="free", index=True)
    credits = Column(Integer, nullable=False, server_default="0")
    daily_usage_count = Column(Integer, nullable=False, server_default="0")
    last_usage_reset_at = Column(DateTime(timezone=True), nullable=True)

    # app 侧身份 profile（原 users 表迁入，2026-07-17 身份统一）
    role = Column(String(32), nullable=False, server_default="user", index=True)  # user/member/staff/admin
    pdf_download_count = Column(Integer, nullable=False, server_default="0")      # 已成功生成 PDF 次数

    subscription_status = Column(String(64), nullable=False, server_default="free", index=True)
    provider_customer_id = Column(String(255), nullable=True, index=True)
    provider_subscription_id = Column(String(255), nullable=True, index=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)


class Resume(Base):
    """简历模型"""
    __tablename__ = "resumes"
    __table_args__ = {'extend_existing': True}

    id = Column(String(255), primary_key=True, index=True)
    # BetterAuth "user".id（字符串）；不声明跨工具 FK——"user" 表由 better-auth CLI 管理，
    # 声明硬 FK 会让 create_all 依赖建表顺序（真实库可由迁移脚本 --with-fk 补库级约束）
    user_id = Column(String(255), nullable=False, index=True)
    name = Column(String(255), nullable=False)
    alias = Column(String(255), nullable=True)  # 备注/别名，用于标识简历用途
    data = Column(JSON, nullable=False)  # MySQL JSON 类型，存储完整简历数据
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class Member(Base):
    """平台内部成员模型"""
    __tablename__ = "members"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    name = Column(String(128), nullable=False)
    email = Column(String(255), nullable=True, index=True)
    position = Column(String(128), nullable=True)
    team = Column(String(128), nullable=True)
    status = Column(String(32), nullable=False, server_default="active")
    user_id = Column(String(255), nullable=True, index=True)  # BetterAuth "user".id（无跨工具 FK）
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class APIRequestLog(Base):
    """接口请求日志"""
    __tablename__ = "api_request_logs"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    request_id = Column(String(64), nullable=False, index=True)
    method = Column(String(16), nullable=False)
    path = Column(String(512), nullable=False, index=True)
    status_code = Column(Integer, nullable=False)
    latency_ms = Column(Float, nullable=False, default=0)
    user_id = Column(String(255), nullable=True, index=True)  # BetterAuth "user".id（无跨工具 FK）
    ip = Column(String(64), nullable=True, index=True)
    user_agent = Column(String(512), nullable=True)
    request_size = Column(Integer, nullable=True)
    response_size = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class APIErrorLog(Base):
    """接口错误日志"""
    __tablename__ = "api_error_logs"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    request_log_id = Column(Integer, ForeignKey("api_request_logs.id", ondelete="SET NULL"), nullable=True, index=True)
    trace_id = Column(String(64), nullable=False, index=True)
    error_type = Column(String(128), nullable=True)
    error_message = Column(Text, nullable=False)
    error_stack = Column(Text, nullable=True)
    service = Column(String(128), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class APITraceSpan(Base):
    """接口链路 span"""
    __tablename__ = "api_trace_spans"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    trace_id = Column(String(64), nullable=False, index=True)
    span_id = Column(String(64), nullable=False, index=True)
    parent_span_id = Column(String(64), nullable=True, index=True)
    span_name = Column(String(255), nullable=False)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=False)
    duration_ms = Column(Float, nullable=False, default=0)
    status = Column(String(32), nullable=False, server_default="ok")
    tags = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class PermissionAuditLog(Base):
    """权限修改审计日志"""
    __tablename__ = "permission_audit_logs"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    operator_user_id = Column(String(255), nullable=True, index=True)  # BetterAuth "user".id
    target_user_id = Column(String(255), nullable=True, index=True)    # BetterAuth "user".id
    from_role = Column(String(32), nullable=True)
    to_role = Column(String(32), nullable=True)
    action = Column(String(128), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)


class AgentConversation(Base):
    """Agent 对话会话模型"""
    __tablename__ = "agent_conversations"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    session_id = Column(String(255), nullable=False, unique=True, index=True)
    user_id = Column(String(255), nullable=True, index=True)  # BetterAuth "user".id（无跨工具 FK）
    title = Column(String(255), nullable=False, default="New Conversation")
    message_count = Column(Integer, nullable=False, default=0)
    meta = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), index=True)
    last_message_at = Column(DateTime(timezone=True), nullable=True)


class AgentMessage(Base):
    """Agent 对话消息模型"""
    __tablename__ = "agent_messages"
    __table_args__ = (
        UniqueConstraint("conversation_id", "seq", name="uq_agent_messages_conversation_seq"),
        {'extend_existing': True},
    )

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    conversation_id = Column(
        Integer,
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    seq = Column(Integer, nullable=False)
    role = Column(String(20), nullable=False)
    content = Column(Text, nullable=True)
    thought = Column(Text, nullable=True)
    name = Column(String(255), nullable=True)
    message_hash = Column(String(64), nullable=True, index=True)
    tool_call_id = Column(String(255), nullable=True, index=True)
    tool_calls = Column(JSON, nullable=True)
    base64_image = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class ResumeEmbedding(Base):
    """简历向量嵌入模型 - 用于语义搜索"""
    __tablename__ = "resume_embeddings"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    resume_id = Column(String(255), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)  # BetterAuth "user".id（无跨工具 FK）

    # 向量维度（1536 对应 OpenAI text-embedding-ada-002）
    embedding = Column(JSON, nullable=False)  # PostgreSQL 中将使用 vector(1536) 类型

    # 用于生成向量的文本内容摘要
    content_type = Column(String(50), nullable=False)  # summary/experience/projects/skills 等
    content = Column(Text, nullable=False)  # 原始文本内容

    # 元数据（Python 属性名不用 metadata，避免与 SQLAlchemy 保留名冲突）
    extra_metadata = Column("metadata", JSON, nullable=True)  # 额外信息，如职位名称、公司等
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ======================
# 简历评分模型
# ======================

class ScoreRequest(BaseModel):
    """简历评分请求"""
    resume_id: str = Field(..., description="简历ID")
    jd_text: str = Field(..., description="职位描述文本")


class DimensionScore(BaseModel):
    """单个维度评分"""
    name: str  # 维度名称
    score: float  # 分数 0-100
    reasons: List[str]  # 匹配/不匹配原因


class ScoreResponse(BaseModel):
    """简历评分响应"""
    resume_id: str
    overall_score: float  # 总体匹配度
    dimensions: List[DimensionScore]
    created_at: str


class ScoreResult(Base):
    """简历评分结果"""
    __tablename__ = "score_results"
    __table_args__ = {'extend_existing': True}

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    resume_id = Column(String(255), ForeignKey("resumes.id", ondelete="CASCADE"), nullable=False, index=True)
    user_id = Column(String(255), nullable=False, index=True)  # BetterAuth "user".id（无跨工具 FK）
    jd_text = Column(Text, nullable=False)  # 原始JD文本
    overall_score = Column(Float, nullable=False)
    skill_experience_score = Column(Float, nullable=False)  # 技能与经验匹配
    education_score = Column(Float, nullable=False)  # 教育背景匹配
    project_overall_score = Column(Float, nullable=False)  # 项目与整体匹配
    dimension_reasons = Column(JSON, nullable=False)  # 各维度原因 {dimension_name: [reasons]}
    created_at = Column(DateTime(timezone=True), server_default=func.now())
