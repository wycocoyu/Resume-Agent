"""
简历评分服务
计算简历与JD的多维度匹配分数
"""
from datetime import datetime, timezone
import json
import sys
from types import SimpleNamespace
from typing import Dict, List, Any, Optional, Union
from sqlalchemy.orm import Session

if __name__ == "services.scoring_service":
    sys.modules.setdefault("backend.services.scoring_service", sys.modules[__name__])
elif __name__ == "backend.services.scoring_service":
    sys.modules.setdefault("services.scoring_service", sys.modules[__name__])

from models import ScoreResult, Resume
from services.embedding_service import EmbeddingService
from services.reason_quotes import mark_unverified_quotes as _mark_unverified_quotes
from llm import call_llm

try:
    from backend.services.ai_guard import AiGuardError
except ImportError:
    from services.ai_guard import AiGuardError


class ScoringService:
    """简历评分服务"""

    def __init__(self, db: Session):
        self.db = db

    def score_resume(self, resume_id: str, user_id: Union[str, int], jd_text: str) -> Dict[str, Any]:
        """
        对简历进行多维度评分
        """
        normalized_user_id = str(user_id)
        # 获取简历数据
        resume = self.db.query(Resume).filter(
            Resume.id == resume_id,
            Resume.user_id == normalized_user_id
        ).first()

        if not resume:
            raise ValueError(f"Resume {resume_id} not found")

        resume_data = resume.data

        # 1. 技能与经验匹配评分
        skill_experience_result = self._score_skill_experience(resume_data, jd_text)

        # 2. 教育背景匹配评分
        education_result = self._score_education(resume_data, jd_text)

        # 3. 项目与整体匹配评分
        project_result = self._score_project_overall(resume, jd_text)

        # 计算总体匹配度（权重：技能经验40%，教育20%，项目40%）
        overall_score = (
            skill_experience_result["score"] * 0.4 +
            education_result["score"] * 0.2 +
            project_result["score"] * 0.4
        )

        # 组装结果
        dimensions = [
            {"name": "技能与经验匹配", "score": skill_experience_result["score"], "reasons": skill_experience_result["reasons"]},
            {"name": "教育背景匹配", "score": education_result["score"], "reasons": education_result["reasons"]},
            {"name": "项目与整体匹配", "score": project_result["score"], "reasons": project_result["reasons"]}
        ]

        # 保存到数据库
        score_record = ScoreResult(
            resume_id=resume_id,
            user_id=normalized_user_id,
            jd_text=jd_text,
            overall_score=round(overall_score, 1),
            skill_experience_score=skill_experience_result["score"],
            education_score=education_result["score"],
            project_overall_score=project_result["score"],
            dimension_reasons={
                "技能与经验匹配": skill_experience_result["reasons"],
                "教育背景匹配": education_result["reasons"],
                "项目与整体匹配": project_result["reasons"]
            }
        )
        self.db.add(score_record)
        self.db.commit()

        return {
            "resume_id": resume_id,
            "overall_score": round(overall_score, 1),
            "dimensions": dimensions,
            "created_at": score_record.created_at.isoformat()
        }

    def score_resume_data(
        self,
        resume_data: Dict[str, Any],
        jd_text: str,
        resume_id: str = "anonymous",
    ) -> Dict[str, Any]:
        """对未入库的内联简历 JSON 直接评分（不写数据库，供匿名模式使用）。"""
        skill_experience_result = self._score_skill_experience(resume_data, jd_text)
        education_result = self._score_education(resume_data, jd_text)
        project_result = self._score_project_overall(SimpleNamespace(data=resume_data), jd_text)

        overall_score = (
            skill_experience_result["score"] * 0.4
            + education_result["score"] * 0.2
            + project_result["score"] * 0.4
        )
        dimensions = [
            {"name": "技能与经验匹配", "score": skill_experience_result["score"], "reasons": skill_experience_result["reasons"]},
            {"name": "教育背景匹配", "score": education_result["score"], "reasons": education_result["reasons"]},
            {"name": "项目与整体匹配", "score": project_result["score"], "reasons": project_result["reasons"]},
        ]
        return {
            "resume_id": resume_id or "anonymous",
            "overall_score": round(overall_score, 1),
            "dimensions": dimensions,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def _score_skill_experience(self, resume_data: Dict, jd_text: str) -> Dict[str, Any]:
        """技能与经验匹配评分"""
        skills = resume_data.get("skills", [])
        experience = resume_data.get("experience", [])

        prompt = f"""你是一个专业的简历评估专家。请分析以下简历的技能和经验与职位要求的匹配程度。

职位描述：
{jd_text}

简历技能：
{json.dumps(skills, ensure_ascii=False)}

简历经历：
{json.dumps(experience, ensure_ascii=False)}

请以JSON格式输出评估结果：
{{
    "score": 0-100的分数,
    "reasons": ["匹配：结论（依据：『简历原文逐字片段，≤30字』）", "不匹配：结论（依据：『相关原文片段』或写明简历未提及）", "建议：可执行的改进动作"]
}}

引用铁律：『』内必须是上面简历内容里**逐字出现的连续片段**（含标点），禁止改写、翻译或概括；没有可引用的原文就写明"简历未提及"，不要伪造引用。

只输出JSON，不要其他内容。"""

        try:
            result = call_llm("deepseek", prompt)
            data = json.loads(result)
            source_text = json.dumps(resume_data, ensure_ascii=False)
            return {
                "score": float(data.get("score", 0)),
                "reasons": _mark_unverified_quotes(data.get("reasons", []), source_text)
            }
        except AiGuardError:
            raise
        except Exception as e:
            print(f"[ERROR] Skill/experience scoring failed: {e}")
            return {"score": 0, "reasons": [f"评分失败: {str(e)}"]}

    def _score_education(self, resume_data: Dict, jd_text: str) -> Dict[str, Any]:
        """教育背景匹配评分"""
        education = resume_data.get("education", [])

        prompt = f"""你是一个专业的简历评估专家。请分析以下简历的教育背景与职位要求的匹配程度。

职位描述：
{jd_text}

简历教育背景：
{json.dumps(education, ensure_ascii=False)}

请以JSON格式输出评估结果：
{{
    "score": 0-100的分数,
    "reasons": ["匹配：结论（依据：『简历原文逐字片段，≤30字』）", "不匹配：结论（依据：『相关原文片段』或写明简历未提及）", "建议：可执行的改进动作"]
}}

引用铁律：『』内必须是上面简历内容里**逐字出现的连续片段**（含标点），禁止改写、翻译或概括；没有可引用的原文就写明"简历未提及"，不要伪造引用。

只输出JSON，不要其他内容。"""

        try:
            result = call_llm("deepseek", prompt)
            data = json.loads(result)
            source_text = json.dumps(resume_data, ensure_ascii=False)
            return {
                "score": float(data.get("score", 0)),
                "reasons": _mark_unverified_quotes(data.get("reasons", []), source_text)
            }
        except AiGuardError:
            raise
        except Exception as e:
            print(f"[ERROR] Education scoring failed: {e}")
            return {"score": 0, "reasons": [f"评分失败: {str(e)}"]}

    def _score_project_overall(self, resume: Resume, jd_text: str) -> Dict[str, Any]:
        """项目与整体匹配评分（Embedding + LLM）"""
        from services.embedding_service import EmbeddingService

        embedding_service = EmbeddingService(self.db)

        resume_text = json.dumps(resume.data, ensure_ascii=False)
        resume_emb = embedding_service.generate_embedding(resume_text)
        jd_emb = embedding_service.generate_embedding(jd_text)

        embedding_score = 0.0
        if resume_emb and jd_emb:
            embedding_score = embedding_service._cosine_similarity(resume_emb, jd_emb) * 100

        projects = resume.data.get("projects", [])

        prompt = f"""你是一个专业的简历评估专家。请分析以下简历的项目经历与职位的相关性。

职位描述：
{jd_text}

简历项目经历：
{json.dumps(projects, ensure_ascii=False)}

请以JSON格式输出评估结果：
{{
    "score": 0-100的分数（综合项目相关性和整体匹配度）,
    "reasons": ["匹配：结论（依据：『简历原文逐字片段，≤30字』）", "不匹配：结论（依据：『相关原文片段』或写明简历未提及）", "建议：可执行的改进动作"]
}}

引用铁律：『』内必须是上面简历内容里**逐字出现的连续片段**（含标点），禁止改写、翻译或概括；没有可引用的原文就写明"简历未提及"，不要伪造引用。

只输出JSON，不要其他内容。"""

        try:
            llm_result = call_llm("deepseek", prompt)
            data = json.loads(llm_result)
            llm_score = float(data.get("score", 0))
            final_score = embedding_score * 0.4 + llm_score * 0.6
            source_text = json.dumps(resume.data, ensure_ascii=False)
            return {
                "score": round(final_score, 1),
                "reasons": _mark_unverified_quotes(data.get("reasons", []), source_text)
            }
        except AiGuardError:
            raise
        except Exception as e:
            print(f"[ERROR] Project/overall scoring failed: {e}")
            return {"score": round(embedding_score, 1), "reasons": [f"LLM评分失败，使用向量相似度: {round(embedding_score, 1)}"]}