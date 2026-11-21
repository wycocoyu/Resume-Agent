import json
from typing import Any, Optional
import uuid

from pydantic import Field

from backend.agent.tool.base import BaseTool, ToolResult
from backend.core.logger import get_logger

logger = get_logger(__name__)

GENERATE_RESUME_PROMPT = """你是专业简历写作专家。根据以下信息生成简历 JSON。

目标岗位：{job_description}
用户背景：{user_background}

**核心原则：只用「用户背景」里真实提供的信息，严禁编造或脑补用户没说的内容。**
- 用户没提供的字段一律留空：字符串留 ""，数组留 []。
- 例如：用户没说技能，skillContent 就留 ""；没说项目，projects 就留 []；没说实习，experience 就留 []。
- 不要根据目标岗位去"推测/补全"用户可能会的技能、可能做过的项目或课程。
- education 的 description 只写用户真实提到的（如"全日制本科、英语六级"），不要脑补主修课程。

严格按此 JSON schema 输出，不输出其他文字：
{{
  "basic": {{"name": "", "title": "", "email": "", "phone": "", "location": ""}},
  "education": [{{"id": "", "school": "", "major": "", "degree": "", "startDate": "", "endDate": "", "description": ""}}],
  "experience": [{{"id": "", "company": "", "position": "", "date": "", "details": ""}}],
  "projects": [{{"id": "", "name": "", "role": "", "date": "", "description": "", "link": ""}}],
  "openSource": [],
  "awards": [],
  "skillContent": ""
}}"""


class GenerateResumeTool(BaseTool):
    name: str = "generate_resume"
    description: str = (
        "根据岗位描述和用户背景，从零生成完整简历。"
        "适用于：用户没有简历、或想针对新岗位重新生成。"
    )
    parameters: dict = {
        "type": "object",
        "properties": {
            "job_description": {
                "type": "string",
                "description": "目标岗位 JD 或岗位名称",
            },
            "user_background": {
                "type": "string",
                "description": "用户自述经历、技能、教育背景（可选）",
            },
        },
        "required": ["job_description"],
    }
    llm: Optional[Any] = Field(default=None, exclude=True)

    async def execute(self, job_description: str, user_background: str = "") -> ToolResult:
        from backend.agent.llm import LLM
        from backend.agent.schema import Message, Role

        prompt = GENERATE_RESUME_PROMPT.format(
            job_description=job_description,
            user_background=user_background or "未提供",
        )
        try:
            llm = self.llm or LLM()
            response = await llm.ask(
                messages=[Message(role=Role.USER, content=prompt)],
            )
            content = response.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            resume_dict = json.loads(content.strip())

            for section in ["education", "experience", "projects", "openSource", "awards"]:
                for item in resume_dict.get(section, []):
                    if not item.get("id"):
                        item["id"] = str(uuid.uuid4())

            summary = f"已生成面向「{job_description[:30]}」的简历"
            structured_data = {
                "type": "resume_generated",
                "resume": resume_dict,
                "summary": summary,
            }
            # structured_data 走显式通道;system JSON 双写保留兼容(Wave 1.1 迁移期)
            return ToolResult(
                output=summary,
                system=json.dumps(structured_data, ensure_ascii=False),
                structured_data=structured_data,
            )
        except json.JSONDecodeError as e:
            logger.error(f"[GenerateResumeTool] JSON 解析失败: {e}")
            return ToolResult(output="生成失败，LLM 返回格式有误", error=str(e))
        except Exception as e:
            logger.error(f"[GenerateResumeTool] 生成异常: {e}")
            return ToolResult(output=f"生成失败: {e}", error=str(e))
