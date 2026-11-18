"""
CVEditor Agent Tool - 将 CVEditor Agent 包装成 Manus 可调用的工具

参考 MCPAgent 的集成方式，这个工具内部使用 CVEditor Agent 来处理简历编辑任务。
Manus 可以委托简历修改任务给这个工具。
"""

from typing import Optional, Any, Dict
import json
import re
import uuid
from pydantic import Field
from backend.agent.tool.base import BaseTool, ToolResult
from backend.agent.tool.resume_data_store import ResumeDataStore
from backend.agent.utils.experience_entry import (
    build_indexed_patch_after,
    build_indexed_patch_before,
    coerce_tool_value,
    is_indexed_array_item_path,
    normalize_education_add_entry,
    normalize_experience_add_entry,
    normalize_opensource_add_entry,
    resolve_experience_add_path,
    to_internships_schema,
)
from backend.agent.utils.resume_richtext import is_richtext_path, normalize_editor_value
from backend.agent.utils.coverage_check import check_coverage, check_invented
from backend.agent.llm import LLM
from backend.core.logger import get_logger

logger = get_logger(__name__)


class CVEditorAgentTool(BaseTool):
    """CVEditor Agent 工具

    这是一个特殊的工具，它内部使用 CVEditor Agent 来处理简历编辑任务。
    Manus 可以委托简历修改任务给这个工具，CVEditor 会以 Agent 的方式处理。

    使用场景：
    - 用户要求修改简历中的某个字段
    - 用户要求添加新的工作经历
    - 用户要求删除某个项目
    - 用户要求更新个人信息
    """

    name: str = "cv_editor_agent"
    description: str = """修改当前简历的字段(改/加/删)。用户要求修改、优化、润色、添加、删除简历内容时使用;可多次调用完成多处修改。

path 必须精确到叶子字段,常用路径:
- 姓名 basic.name / 手机 basic.phone / 邮箱 basic.email / 求职意向 basic.title
- 教育 education[0].school|major|degree|gpa
- **工作经历**(全职)描述 workExperience[N].details ← 与实习是两个独立板块,别混
- **实习经历**描述 experience[N].details;项目描述 projects[N].description
- 开源经历 openSource[N].description;技能 skillContent
- 整段追加:path=workExperience|experience(或 projects/openSource),action=add,value 传完整对象
- 选板块规则:用户说"工作/全职/正式工作"→ workExperience;说"实习"→ experience;
  说不清时看 system context 里两个板块各自已有的条目,改哪条就用哪条所在的板块路径

action 语义:update=改现有值;add=向数组追加(value 必须是对象,禁止二次 JSON 编码成字符串);delete=删除。

富文本约束(details/description/skillContent 的 value 必须遵守):
- 只用 HTML,禁止 Markdown:加粗 <strong>文字</strong>,不要 **文字**
- 多条要点用 <ul class="custom-list"><li><p><strong>小标题</strong>:描述…</p></li></ul>,不要 1. 2. 3.
- 经历/项目/开源/技能的描述必须拆成多条 <li> 要点(每条一个动作+成果),禁止写成整段散文;仅 selfEvaluation(自我评价)可用段落
- 改写必须基于简历现有内容(在 system context 中),不得凭空编造经历或数据

add 新实习示例 value:
{"company":"美的集团","position":"后端开发实习生","date":"2024.12 - 2025.03","details":"<p>…</p><ul class=\\"custom-list\\">…</ul>"}
(用 date 字段,不要 period)

add 教育经历示例 value(path=education):
{"school":"XX大学","major":"计算机科学与技术","degree":"本科","startDate":"2018.09","endDate":"2022.06"}
(字段是 school/major/degree,不要用 company/position;用户没说日期就留空字符串)"""

    parameters: dict = {
        "type": "object",
        "properties": {
            "path": {
                "type": "string",
                "description": "简历字段的 JSON 路径,精确到叶子字段。如 basic.name、experience[0].details、projects[1].description;整段追加时用数组名如 experience"
            },
            "action": {
                "type": "string",
                "enum": ["update", "add", "delete"],
                "description": "update=修改现有值;add=向数组追加完整对象;delete=删除该路径"
            },
            "value": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "object"},
                    {"type": "array"},
                ],
                "description": "新值。update 时通常是字符串(富文本字段必须是 HTML);add 时必须是完整对象(不要编码成 JSON 字符串);delete 时省略"
            }
        },
        "required": ["path", "action"]
    }
    user_id: Optional[str] = Field(default=None, exclude=True)

    class Config:
        arbitrary_types_allowed = True

    # patch 卡标题的人话化:用户看到的应是「实习经历「美团」的描述」,
    # 而不是 experience[1].details 这种技术路径
    _SECTION_CN = {
        "experience": "实习经历",
        "projects": "项目经历",
        "openSource": "开源经历",
        "opensource": "开源经历",
        "education": "教育经历",
        "awards": "荣誉奖项",
    }
    _FIELD_CN = {
        "details": "描述", "description": "描述", "company": "公司", "position": "职位",
        "name": "名称", "school": "学校", "major": "专业", "degree": "学历", "gpa": "GPA",
        "date": "时间", "role": "角色", "link": "链接",
    }
    _TOP_FIELD_CN = {
        "selfEvaluation": "自我评价", "skillContent": "专业技能",
        "basic.name": "姓名", "basic.phone": "电话", "basic.email": "邮箱",
        "basic.title": "求职意向", "basic.location": "所在地",
    }

    def _humanize_path(self, path_str: str) -> str:
        p = (path_str or "").strip()
        if p in self._TOP_FIELD_CN:
            return self._TOP_FIELD_CN[p]
        m = re.match(r"^(\w+)\[(\d+)\](?:\.(\w+))?$", p)
        if m:
            section, idx, field = m.group(1), int(m.group(2)), m.group(3)
            section_cn = self._SECTION_CN.get(section)
            if section_cn:
                label = self._entry_label(section, idx)
                head = f"{section_cn}「{label}」" if label else f"第 {idx + 1} 段{section_cn}"
                return f"{head}的{self._FIELD_CN.get(field, field)}" if field else head
        if p in self._SECTION_CN:
            return self._SECTION_CN[p]
        return p  # 未识别的路径保底原样,不弄巧成拙

    def _entry_label(self, section: str, idx: int) -> str:
        """尽量取条目名(公司/项目名/学校)当标题;取不到返回空串走序号兜底。"""
        try:
            from backend.agent.tool.resume_data_store import ResumeDataStore

            data = ResumeDataStore.get_data(self.session_id) or {}
            entry = (data.get(section) or [])[idx] or {}
            label = str(
                entry.get("company") or entry.get("name") or entry.get("school") or ""
            ).strip()
            return label[:20]
        except Exception:
            return ""

    @staticmethod
    def _values_equal(old_val: Any, new_val: Any) -> bool:
        if old_val == new_val:
            return True
        return str(old_val or "").strip() == str(new_val or "").strip()

    @staticmethod
    def _stringify_value(value: Any) -> str:
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, indent=2)
        if value is None:
            return "null"
        return str(value)

    @staticmethod
    def _resolve_simple_edit_path(path: str, resume_data: Dict[str, Any]) -> tuple[str, Dict[str, Any]]:
        """将简单编辑路径映射到当前简历结构（internships <-> experience）。"""
        meta: Dict[str, Any] = {"normalized_path": path}
        match = re.match(r"^internships\[(\d+)\]\.company$", path)
        if not match:
            return path, meta

        index = int(match.group(1))
        internships = resume_data.get("internships")
        experience = resume_data.get("experience")

        if isinstance(internships, list):
            if index >= len(internships):
                raise ValueError(f"当前只有 {len(internships)} 段实习，无法修改第 {index + 1} 段")
            meta["section"] = "internships"
            meta["index"] = index
            return path, meta

        if isinstance(experience, list):
            if index >= len(experience):
                raise ValueError(f"当前只有 {len(experience)} 段经历，无法修改第 {index + 1} 段")
            mapped_path = f"experience[{index}].company"
            meta["section"] = "internships"
            meta["index"] = index
            meta["normalized_path"] = mapped_path
            return mapped_path, meta

        raise ValueError("当前简历中未找到可修改的实习/经历条目，请先完善对应内容")

    @staticmethod
    def _is_empty_experience_entry(value: Any) -> bool:
        """判断 update 值是否等价于“删除整条经历”（避免前端留下未命名公司）。"""
        if value is None:
            return True
        if isinstance(value, str) and not value.strip():
            return True
        if not isinstance(value, dict):
            return False
        company = str(
            value.get("company") or value.get("title") or value.get("organization") or ""
        ).strip()
        position = str(
            value.get("position") or value.get("subtitle") or value.get("role") or ""
        ).strip()
        details = value.get("details") or value.get("description") or ""
        if isinstance(details, list):
            details = "\n".join(str(x) for x in details)
        details = str(details or "").strip()
        if details and re.search(r"<[a-z][^>]*>", details, re.I):
            details = re.sub(r"<[^>]+>", "", details).strip()
        return not company and not position and not details

    async def execute(self, path: str, action: str, value: Any = None) -> ToolResult:
        """执行简历编辑

        内部创建 CVEditor Agent 并运行它来处理编辑任务
        """
        # 🔍 诊断日志
        logger.info(f"[CVEditorAgentTool] execute called: session_id={self.session_id}, path={path}, action={action}")
        
        resume_data = ResumeDataStore.get_data(self.session_id)
        meta = ResumeDataStore._meta_by_session.get(self.session_id, {})
        logger.info(f"[CVEditorAgentTool] resume_data: {bool(resume_data)}, meta: {meta}")
        
        if not resume_data:
            return ToolResult(
                output="No resume data loaded. Please use cv_reader_agent tool first to read resume data."
            )

        try:
            normalized_path, simple_edit_meta = self._resolve_simple_edit_path(path, resume_data)

            if action == "add":
                normalized_path = resolve_experience_add_path(normalized_path, resume_data)
                value = coerce_tool_value(value)
                if isinstance(value, dict):
                    idx_hint = len(resume_data.get(normalized_path) or [])
                    if normalized_path == "openSource":
                        # openSource 用专用规范化，避免被 experience 格式吞掉 name/repo
                        value = normalize_opensource_add_entry(value, index_hint=idx_hint)
                    elif normalized_path == "education":
                        # education 同理:school/major/degree 会被 experience 格式吞成空壳
                        value = normalize_education_add_entry(value, index_hint=idx_hint)
                    else:
                        workspace_entry = normalize_experience_add_entry(
                            value,
                            array_path=normalized_path,
                            index_hint=idx_hint,
                        )
                        if normalized_path == "internships":
                            value = to_internships_schema(workspace_entry)
                        else:
                            value = workspace_entry

            # 延迟导入避免循环依赖
            from backend.agent.agent.cv_editor import CVEditor

            # 创建 CVEditor Agent 实例
            cv_editor = CVEditor()

            # 加载简历数据（传入引用，所以修改会直接影响原始数据）
            cv_editor.load_resume(resume_data)

            # 富文本字段：将 LLM 的 Markdown/编号列表规范为 HTML 无序列表（add 已在上方规范化）
            if action == "update" and value is not None:
                if is_richtext_path(normalized_path) or (
                    isinstance(value, str)
                    and ("**" in value or re.search(r"^\d+\.\s", value, re.M))
                ):
                    value = normalize_editor_value(value, normalized_path)

            # update 数组项整体替换：openSource[i] 走专用规范化；experience[i] 空对象等价 delete
            if action == "update" and is_indexed_array_item_path(normalized_path):
                coerced = coerce_tool_value(value)
                if normalized_path.startswith("openSource[") and isinstance(coerced, dict):
                    value = normalize_opensource_add_entry(coerced)
                elif self._is_empty_experience_entry(coerced):
                    action = "delete"
                    value = None

            # 执行编辑操作
            result = await cv_editor.edit_resume(normalized_path, action, value)

            if result.get("success"):
                old_val = result.get("old_value")
                new_val = result.get("new_value")

                # 无实质变更：不弹 diff 卡片、不写库
                if action == "update" and self._values_equal(old_val, new_val):
                    logger.info(
                        f"[CVEditorAgentTool] No-op update skipped: {normalized_path}"
                    )
                    return ToolResult(
                        output=f"✅ {normalized_path} 内容未变化，已跳过更新。"
                    )

                # 同步更新 ResumeDataStore（因为 CVEditor 直接修改了传入的字典引用）
                ResumeDataStore.set_data(resume_data, session_id=self.session_id)
                meta = ResumeDataStore._meta_by_session.get(self.session_id, {})
                is_anonymous_session = self.user_id is None and not meta.get("user_id")
                # 匿名会话不落盘服务端 DB；仅登录会话写回数据库
                persisted = True if is_anonymous_session else ResumeDataStore.persist_data(self.session_id)

                # 格式化成功消息
                output = f"✅ {result.get('message', 'Edit completed')}"
                if not persisted:
                    # 🔧 改进：检查持久化失败的具体原因
                    meta = ResumeDataStore._meta_by_session.get(self.session_id, {})
                    resume_id = meta.get("resume_id")
                    user_id = meta.get("user_id")
                    
                    if not resume_id or not user_id:
                        logger.error(
                            f"[CVEditorAgentTool] 持久化失败：缺少元数据。"
                            f"session_id={self.session_id}, resume_id={resume_id}, user_id={user_id}"
                        )
                        output += (
                            f"\n❌ **持久化失败**: 缺少必要的元数据（resume_id 或 user_id）。"
                            f"请联系管理员或刷新页面重试。"
                        )
                    else:
                        logger.warning(
                            f"[CVEditorAgentTool] 持久化失败：数据库操作失败。"
                            f"session_id={self.session_id}, resume_id={resume_id}, user_id={user_id}"
                        )
                        output += (
                            f"\n⚠️ **持久化失败**: 修改已应用在内存中，但未保存到数据库。"
                            f"请刷新页面确认，或稍后重试。"
                        )
                # 工具结果里保留"修改后"内容的截断摘要（前 300 字符），
                # 让 agent 能判断改了什么、还剩哪些模块没改——但不放完整的
                # before/after 文本（before 是 token 膨胀最大来源且 agent 不需要）。
                # 完整 before/after 已通过 structured_data 发给前端渲染。
                _MAX_RESULT_PREVIEW = 300
                if action == "update":
                    new_str = self._stringify_value(new_val)[:_MAX_RESULT_PREVIEW]
                    output += f"\n修改后:\n{new_str}"
                    # 覆盖度回验：原文中的数字指标/专有技术名词，改写后是否还在——
                    # 纯规则匹配，不过 LLM，堵"整段技术内容消失"这种信息保真度事故。
                    # 只做数字/专有名词这个粗粒度子集，见 coverage_check.py 顶部说明。
                    old_str = self._stringify_value(old_val)
                    new_str_full = self._stringify_value(new_val)
                    missing_facts = check_coverage(old_str, new_str_full)
                    if missing_facts:
                        preview = "、".join(f"「{m}」" for m in missing_facts[:8])
                        output += (
                            f"\n⚠️ 覆盖校验[漏删]：原文中的 {preview} 未出现在改写后文本，"
                            f"可能被删减，如果不是有意去掉请补回。"
                        )
                    # 反向校验：改写后凭空多出的数字/量化声明，原文找不到依据——
                    # 堵 LLM 量化包装时编造数字（"提升效率"→"提升35%"）。软提示，
                    # 精确匹配自带假阳性（"70%"→"约70.0%"会误报），故不硬阻断。
                    invented_facts = check_invented(old_str, new_str_full)
                    if invented_facts:
                        preview = "、".join(f"「{m}」" for m in invented_facts[:8])
                        output += (
                            f"\n⚠️ 疑似编造[新增数字]：改写后文本中的 {preview} 在原文中"
                            f"找不到依据，如果不是用户明确提供的新信息，请核实或去掉。"
                        )
                elif "new_value" in result:
                    new_str = self._stringify_value(new_val)[:_MAX_RESULT_PREVIEW]
                    output += f"\n新内容:\n{new_str}"
                if "new_index" in result:
                    output += f"\nIndex: {result['new_index']}"
                patch_id = str(uuid.uuid4())
                path_str = normalized_path
                patch_operation = action
                before_payload: Dict[str, Any] = {"_raw": self._stringify_value(old_val)}
                after_payload: Dict[str, Any] = {"_raw": self._stringify_value(new_val)}

                # add：必须指向具体下标，避免前端把整段 experience 替换成 JSON 字符串
                if action == "add" and "new_index" in result:
                    idx = int(result["new_index"])
                    path_str = f"{normalized_path}[{idx}]"
                    before_payload = {}
                    after_payload = build_indexed_patch_after(path_str, new_val)
                elif action == "delete":
                    after_payload = {}
                    if is_indexed_array_item_path(path_str) and old_val is not None:
                        before_payload = build_indexed_patch_before(path_str, old_val)
                    else:
                        before_payload = {"_raw": self._stringify_value(old_val)}
                elif action == "update" and is_indexed_array_item_path(path_str):
                    if self._is_empty_experience_entry(new_val):
                        patch_operation = "delete"
                        after_payload = {}
                        before_payload = build_indexed_patch_before(path_str, old_val)
                    else:
                        before_payload = build_indexed_patch_before(path_str, old_val)
                        after_payload = build_indexed_patch_after(path_str, new_val)

                verb = "删除了" if patch_operation == "delete" else (
                    "新增了" if action == "add" else "修改了"
                )
                summary = f"{verb} {self._humanize_path(path_str)}"
                structured_data = {
                    "type": "resume_patch",
                    "patch_id": patch_id,
                    "operation": patch_operation,
                    "paths": [path_str],
                    "before": before_payload,
                    "after": after_payload,
                    "summary": summary,
                }
                # structured_data 走显式通道;system JSON 双写保留兼容(Wave 1.1 迁移期)
                return ToolResult(
                    output=output,
                    system=json.dumps(structured_data, ensure_ascii=False),
                    structured_data=structured_data,
                )
            else:
                return ToolResult(
                    error=f"❌ Edit failed: {result.get('message', 'Unknown error')}"
                )

        except Exception as e:
            return ToolResult(error=f"CVEditor Agent error: {str(e)}")
