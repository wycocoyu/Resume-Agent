"""
CVEditor Agent - 简历编辑 Agent

可以修改、添加或删除简历数据
"""

from typing import Any, Dict, Optional

from backend.agent.utils.json_path import parse_path, get_by_path, set_by_path, delete_by_path, exists_path

PATH_ALIASES = {
    "opensource": "openSource",
    "open_source": "openSource",
    "skillcontent": "skillContent",
    "selfevaluation": "selfEvaluation",
    "self_evaluation": "selfEvaluation",
    "startdate": "startDate",
    "enddate": "endDate",
    "companaylogo": "companyLogo",
    "companylogo": "companyLogo",
}


def normalize_path(path: str) -> str:
    """将 LLM 可能输出的路径别名归一化为 JSON 中的真实 key。"""
    parts = path.split(".")
    normalized = []
    for part in parts:
        bracket_idx = part.find("[")
        if bracket_idx != -1:
            key = part[:bracket_idx]
            suffix = part[bracket_idx:]
        else:
            key = part
            suffix = ""
        key = PATH_ALIASES.get(key.lower(), key)
        normalized.append(f"{key}{suffix}")
    return ".".join(normalized)


class CVEditor:
    """简历编辑 Agent

    专门用于修改简历内容的 Agent
    """

    def __init__(self) -> None:
        self._resume_data: Optional[Dict] = None

    def load_resume(self, resume_data: Dict) -> str:
        """加载简历数据到 Agent

        Args:
            resume_data: 简历数据字典

        Returns:
            简历摘要文本
        """
        self._resume_data = resume_data

        basic = resume_data.get("basic", {})
        context = f"""Current Resume Loaded for Editing:

Name: {basic.get('name', 'N/A')}
Target Position: {basic.get('title', 'N/A')}

You can edit this resume using update, add, or delete operations.
"""
        return context

    async def edit_resume(self, path: str, action: str, value: Any = None) -> Dict[str, Any]:
        """编辑简历

        Args:
            path: JSON 路径，如 'basic.name', 'education[0].school'
            action: 操作类型: 'update', 'add', 'delete'
            value: 新值（update/add 时需要）

        Returns:
            操作结果
        """
        if not self._resume_data:
            return {
                "success": False,
                "message": "No resume data loaded. Please load a resume first.",
                "error_type": "NO_RESUME"
            }

        path = normalize_path(path)

        try:
            if action == "update":
                return self._update(path, value)
            elif action == "add":
                return self._add(path, value)
            elif action == "delete":
                return self._delete(path)
            else:
                return {
                    "success": False,
                    "message": f"Unsupported action: {action}",
                    "error_type": "INVALID_ACTION"
                }
        except Exception as e:
            return {
                "success": False,
                "message": f"Edit failed: {str(e)}",
                "error_type": "INTERNAL_ERROR"
            }

    def _update(self, path: str, value: Any) -> Dict[str, Any]:
        """更新操作"""
        try:
            old_value = None
            parts = parse_path(path)
            if exists_path(self._resume_data, parts):
                _, _, old_value = get_by_path(self._resume_data, parts)
            set_by_path(self._resume_data, path, value)
            return {
                "success": True,
                "message": f"Successfully updated: {path}",
                "path": path,
                "old_value": old_value,
                "new_value": value,
            }
        except ValueError as e:
            return {
                "success": False,
                "message": f"Update failed: {e}",
                "path": path,
                "error_type": "UPDATE_ERROR"
            }

    # 顶层标量字符串字段：add 到这些字段时应视为"设置值"，不能转成数组——
    # 否则下游格式化（cv_reader_tool.strip_html）拿到 list 会直接抛 TypeError。
    _SCALAR_STRING_FIELDS = {"selfEvaluation", "skillContent"}

    def _add(self, path: str, value: Any) -> Dict[str, Any]:
        """添加操作"""
        leaf = path.split(".")[-1].split("[")[0]
        try:
            parts = parse_path(path)
            _, _, target = get_by_path(self._resume_data, parts)

            if isinstance(target, str):
                # 字段已存在且当前是字符串（如空的 selfEvaluation）：
                # add 语义退化为"设置该值"，不转数组。
                set_by_path(self._resume_data, path, value)
                return {
                    "success": True,
                    "message": f"Successfully set: {path}",
                    "path": path,
                    "new_value": value,
                }

            if not isinstance(target, list):
                # 创建新数组
                set_by_path(self._resume_data, path, [])
                _, _, target = get_by_path(self._resume_data, parts)

            target.append(value)
            return {
                "success": True,
                "message": f"Successfully added to: {path}",
                "path": path,
                "new_value": value,
                "new_index": len(target) - 1
            }
        except ValueError:
            if leaf in self._SCALAR_STRING_FIELDS:
                # 字段此前完全不存在（未初始化）：仍按标量语义直接赋值。
                set_by_path(self._resume_data, path, value)
                return {
                    "success": True,
                    "message": f"Successfully set: {path}",
                    "path": path,
                    "new_value": value,
                }
            # 创建新数组并添加
            set_by_path(self._resume_data, path, [value])
            return {
                "success": True,
                "message": f"Created new array and added to: {path}",
                "path": path,
                "new_value": value,
                "new_index": 0
            }
        except Exception as e:
            return {
                "success": False,
                "message": f"Add failed: {e}",
                "path": path,
                "error_type": "ADD_ERROR"
            }

    def _delete(self, path: str) -> Dict[str, Any]:
        """删除操作"""
        try:
            parts = parse_path(path)
            old_value = None
            if exists_path(self._resume_data, parts):
                _, _, old_value = get_by_path(self._resume_data, parts)
            delete_by_path(self._resume_data, path)
            return {
                "success": True,
                "message": f"Successfully deleted: {path}",
                "path": path,
                "old_value": old_value,
                "new_value": None,
            }
        except ValueError as e:
            return {
                "success": False,
                "message": f"Delete failed: {e}",
                "path": path,
                "error_type": "DELETE_ERROR"
            }

    def get_resume_data(self) -> Dict:
        """获取当前简历数据"""
        return self._resume_data or {}

    async def chat(self, message: str, resume_data: Optional[Dict] = None) -> str:
        """与编辑对话

        Args:
            message: 用户消息
            resume_data: 简历数据（如果未加载过）

        Returns:
            AI 回复
        """
        if resume_data:
            self.load_resume(resume_data)
        elif not self._resume_data:
            return "No resume data loaded. Please load a resume first."

        # 添加用户消息
        self.update_memory("user", message)

        # 运行 Agent
        result = await self.run()

        return result
