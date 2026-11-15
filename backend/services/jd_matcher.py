"""Job Description (JD) Targeted Matching & 3D Radar Analysis Engine.

Authoritative specs:
- Feature 18 / Issue #54
- Structured JD parsing: title, required/preferred skills, years, degree, seniority, domain keywords.
- Canonical skill taxonomy (~120 skills + synonyms).
- 3D Radar scoring model:
  1. Technical skills match (0-100)
  2. Project relevance match (0-100)
  3. Experience match (0-100)
  Overall composite score (0-100).
- Deterministic STAR rewrite generator with metrics and aligned keywords.
"""
from __future__ import annotations

import copy
import math
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple
from uuid import uuid4

from pydantic import BaseModel, Field


# ----------------- Canonical Skill Taxonomy (~120 skills + aliases) -----------------
SKILL_TAXONOMY: Dict[str, List[str]] = {
    # Languages
    "Go": ["golang", "go语言"],
    "Python": ["python3", "py"],
    "Java": ["java8", "java17", "java21"],
    "TypeScript": ["ts"],
    "JavaScript": ["js", "es6", "esnext"],
    "C++": ["cpp", "c/c++"],
    "C#": ["csharp", ".net"],
    "Rust": ["rustlang"],
    "PHP": ["php7", "php8"],
    "SQL": ["structured query language"],
    "Ruby": ["ruby on rails", "rails"],
    "Swift": ["swiftui"],
    "Kotlin": ["kotlin/android"],
    "Scala": [],
    "Shell": ["bash", "zsh", "shell script"],
    # Frontend
    "React": ["react.js", "reactjs", "react 18"],
    "Vue": ["vue.js", "vuejs", "vue3", "vue2"],
    "Next.js": ["nextjs"],
    "Nuxt.js": ["nuxtjs"],
    "Angular": ["angularjs"],
    "Tailwind CSS": ["tailwind", "tailwindcss"],
    "Webpack": ["webpack5"],
    "Vite": ["vitejs"],
    "HTML5": ["html"],
    "CSS3": ["css", "scss", "less"],
    "Node.js": ["nodejs", "node"],
    "Redux": ["redux toolkit", "rtk"],
    "Zustand": [],
    # Backend Frameworks
    "FastAPI": ["fastapi"],
    "Spring Boot": ["spring", "springboot", "spring cloud"],
    "Django": ["django rest framework", "drf"],
    "Flask": [],
    "Gin": ["gin-gonic"],
    "Express": ["express.js", "expressjs"],
    "NestJS": ["nest.js"],
    "gRPC": ["grpc-go", "grpc-java"],
    # Databases & Storage
    "MySQL": ["mysql8"],
    "PostgreSQL": ["postgres", "pgsql"],
    "Redis": ["redis cache", "redis集群"],
    "MongoDB": ["mongo"],
    "Elasticsearch": ["es", "elastic search"],
    "Kafka": ["apache kafka"],
    "ClickHouse": ["click house"],
    "RabbitMQ": ["rabbitmq"],
    "RocketMQ": [],
    "SQLite": ["sqlite3"],
    "HBase": [],
    "Cassandra": [],
    # Cloud & DevOps
    "Docker": ["dockerfile", "containerd"],
    "Kubernetes": ["k8s", "kube"],
    "Linux": ["centos", "ubuntu", "debian", "redhat"],
    "CI/CD": ["gitlab ci", "github actions", "jenkins"],
    "Nginx": ["openresty"],
    "AWS": ["amazon web services", "ec2", "s3"],
    "Terraform": [],
    "Prometheus": [],
    "Grafana": [],
    "Git": ["github", "gitlab"],
    # Architecture & Paradigms
    "微服务": ["microservices", "微服务架构"],
    "分布式": ["distributed", "分布式系统", "分布式架构"],
    "高并发": ["high concurrency", "海量并发"],
    "性能优化": ["performance optimization", "性能调优"],
    "缓存": ["cache", "多级缓存"],
    "消息队列": ["message queue", "mq"],
    "DDD": ["领域驱动设计", "domain driven design"],
    "RESTful": ["rest api", "restful api"],
    "RPC": ["远程过程调用"],
    "分库分表": ["sharding"],
    # AI & Data
    "RAG": ["检索增强生成", "retrieval augmented generation"],
    "LLM": ["大语言模型", "大模型", "large language model"],
    "Agent": ["ai agent", "智能体"],
    "PyTorch": ["torch"],
    "TensorFlow": ["tf"],
    "LangChain": [],
    "Pandas": [],
    "NumPy": [],
    "Scikit-learn": ["sklearn"],
    "Vector Database": ["向量数据库", "milvus", "pinecone", "chroma"],
}

# Reverse mapping: lowercase alias -> canonical name
ALIAS_TO_CANONICAL: Dict[str, str] = {}
for canonical, aliases in SKILL_TAXONOMY.items():
    ALIAS_TO_CANONICAL[canonical.lower()] = canonical
    for alias in aliases:
        ALIAS_TO_CANONICAL[alias.lower()] = canonical

# Domain keywords for industry relevance
DOMAIN_KEYWORDS_SET = {
    "电商", "支付", "金融", "SaaS", "企业服务", "社交", "游戏", "内容安全",
    "推荐系统", "搜索", "数据平台", "中台", "低代码", "物联网", "医疗",
    "智慧城市", "DevOps", "AI平台", "出海", "音视频", "微前端", "云原生"
}

# Scale indicators for architecture depth
SCALE_INDICATORS_SET = {
    "高并发", "分布式", "QPS", "TPS", "PB", "TB", "亿级", "万级",
    "分库分表", "容灾", "双活", "重构", "微服务", "异步解耦", "削峰填谷"
}


# ----------------- Pydantic Models -----------------
class ParsedJd(BaseModel):
    title: str = Field(default="目标岗位")
    required_skills: List[str] = Field(default_factory=list)
    preferred_skills: List[str] = Field(default_factory=list)
    experience_years: Optional[float] = None
    degree: Optional[str] = None
    seniority: str = Field(default="mid")
    domain_keywords: List[str] = Field(default_factory=list)
    responsibilities: List[str] = Field(default_factory=list)
    raw_text: str = ""


class RadarScore(BaseModel):
    technical_score: float = Field(..., ge=0, le=100)
    project_score: float = Field(..., ge=0, le=100)
    experience_score: float = Field(..., ge=0, le=100)


class TechnicalMatchResult(BaseModel):
    score: float
    matched_skills: List[str]
    missing_skills: List[str]
    skill_coverage: float
    reasons: List[str]


class ProjectMatchResult(BaseModel):
    score: float
    matched_domains: List[str]
    scale_indicators: List[str]
    reasons: List[str]


class ExperienceMatchResult(BaseModel):
    score: float
    candidate_years: float
    required_years: Optional[float]
    degree_matched: bool
    seniority_matched: str
    reasons: List[str]


class JdMatchResponse(BaseModel):
    overall_score: float = Field(..., ge=0, le=100)
    radar: RadarScore
    technical_match: TechnicalMatchResult
    project_match: ProjectMatchResult
    experience_match: ExperienceMatchResult
    parsed_jd: ParsedJd


class StarComponent(BaseModel):
    situation: str = Field(..., description="S: 业务背景与性能挑战")
    task: str = Field(..., description="T: 核心任务与改造成果目标")
    action: str = Field(..., description="A: 采取的具体技术动作及JD关键词融入")
    result: str = Field(..., description="R: 量化成效指标")


class StarRewriteSuggestion(BaseModel):
    id: str = Field(default_factory=lambda: f"star_{uuid4().hex[:8]}")
    key: str = Field(..., description="Field identifier (e.g. experience:0:details)")
    original: str = Field(..., description="Exact verbatim substring from candidate resume")
    suggested: str = Field(..., description="Complete STAR-rewritten bullet")
    star_breakdown: StarComponent
    aligned_keywords: List[str]
    quantifiable_metrics: List[str]
    reason: str


class StarRewriteResponse(BaseModel):
    suggestions: List[StarRewriteSuggestion]
    total_suggestions: int


# ----------------- Algorithmic Engine -----------------
class JdMatchingEngine:
    """Core algorithmic engine for structured JD parsing, 3D radar analysis, and STAR rewrites."""

    def __init__(self):
        pass

    # 1. Structured JD Parsing
    def parse_jd(self, jd_text: str) -> ParsedJd:
        if not jd_text:
            return ParsedJd(raw_text="")

        clean_text = jd_text.strip()
        lines = [line.strip() for line in clean_text.splitlines() if line.strip()]

        # Title extraction
        title = "目标岗位"
        title_match = re.search(
            r"(?:招聘职位|职位名称|招聘岗位|岗位名称|岗位|职位|Title|Position)[\s:：]+([^\n\r]+)",
            clean_text,
            re.IGNORECASE,
        )
        if title_match:
            title = title_match.group(1).strip()
            title = re.sub(r"^(?:招聘职位|职位名称|招聘岗位|岗位名称|岗位|职位)[\s:：]*", "", title).strip()
        else:
            for line in lines[:5]:
                if any(
                    kw in line
                    for kw in (
                        "工程师", "开发", "架构师", "专家", "算法", "全栈",
                        "SRE", "DevOps", "后端", "前端", "测试", "技术负责人",
                    )
                ):
                    cleaned_line = re.sub(r"^(?:招聘职位|职位名称|招聘岗位|岗位名称|岗位|职位)[\s:：]*", "", line).strip()
                    cleaned_line = re.sub(r"^[#*•\-\d\.\s]+", "", cleaned_line).strip()
                    title = cleaned_line.split()[0] if cleaned_line else "目标岗位"
                    break

        # Years of experience extraction
        years: Optional[float] = None
        if re.search(r"(?:应届|在校|实习|不限经验)", clean_text):
            years = 0.0
        else:
            year_match = re.search(
                r"(?:至少|工作经验)?\s*(\d+(?:\.\d+)?)\s*[-~至到及以上+–]?\s*(\d+(?:\.\d+)?)?\s*年",
                clean_text,
            )
            if year_match:
                try:
                    years = float(year_match.group(1))
                except ValueError:
                    years = None

        # Degree extraction
        degree: Optional[str] = None
        if re.search(r"(博士|PhD)", clean_text, re.IGNORECASE):
            degree = "博士"
        elif re.search(r"(硕士|研究生|Master)", clean_text, re.IGNORECASE):
            degree = "硕士"
        elif re.search(r"(本科|学士|统招本科)", clean_text):
            degree = "本科"
        elif re.search(r"(大专|专科)", clean_text):
            degree = "大专"

        # Seniority classification
        seniority = "mid"
        if years is not None and years == 0 or re.search(r"(实习|校招|初级)", title):
            seniority = "junior" if years and years > 0 else "intern"
        elif (years is not None and years >= 5) or re.search(r"(资深|高级|专家|Staff)", title):
            seniority = "senior"
        elif re.search(r"(架构师|Leader|主管|总监|负责人|Principal)", title) or (years is not None and years >= 8):
            seniority = "lead"
        elif (years is not None and years < 3) or re.search(r"(初级|助理)", title):
            seniority = "junior"

        # Split into required vs preferred sections if present
        req_text = clean_text
        pref_text = ""
        pref_marker = re.search(r"(加分项|优先条件|加分条件|任职要求.*加分|Preferred)", clean_text, re.IGNORECASE)
        if pref_marker:
            idx = pref_marker.start()
            req_text = clean_text[:idx]
            pref_text = clean_text[idx:]

        req_skills = self._extract_skills(req_text)
        pref_skills = [s for s in self._extract_skills(pref_text) if s not in req_skills]

        # Domain keywords extraction
        domain_keywords = [
            dk for dk in DOMAIN_KEYWORDS_SET if dk in clean_text
        ]

        # Responsibilities bullet points
        responsibilities: List[str] = []
        in_resp = False
        for line in lines:
            if re.search(r"(岗位职责|工作职责|工作内容|Responsibilities)", line, re.IGNORECASE):
                in_resp = True
                continue
            if re.search(r"(任职要求|任职资格|加分项|Requirements|Qualifications)", line, re.IGNORECASE):
                in_resp = False
            if in_resp and len(line) > 5:
                cleaned = re.sub(r"^[•\-\*\d\.\s]+", "", line).strip()
                if cleaned:
                    responsibilities.append(cleaned)

        return ParsedJd(
            title=title,
            required_skills=req_skills,
            preferred_skills=pref_skills,
            experience_years=years,
            degree=degree,
            seniority=seniority,
            domain_keywords=sorted(domain_keywords),
            responsibilities=responsibilities[:8],
            raw_text=clean_text,
        )

    def _extract_skills(self, text: str) -> List[str]:
        found: Set[str] = set()
        if not text:
            return []

        # Word-boundary or token search for skills
        for alias_lower, canonical in ALIAS_TO_CANONICAL.items():
            # Check presence
            pattern = rf"(?<![a-zA-Z0-9_\-\+]){re.escape(alias_lower)}(?![a-zA-Z0-9_\-\+])"
            if re.search(pattern, text, re.IGNORECASE):
                found.add(canonical)

        return sorted(found)

    # 2. 3D Radar Matching Score Computation
    def calculate_3d_match(self, resume_data: Dict[str, Any], parsed_jd: ParsedJd) -> JdMatchResponse:
        # Candidate text extraction
        candidate_skills = self._extract_candidate_skills(resume_data)
        candidate_years, cand_degree, cand_seniority = self._extract_candidate_experience_profile(resume_data)
        cand_projects_text = self._extract_projects_text(resume_data)

        # Dimension 1: Technical skills match
        tech_res = self._score_technical(candidate_skills, parsed_jd, resume_data)

        # Dimension 2: Project relevance match
        proj_res = self._score_project(cand_projects_text, parsed_jd)

        # Dimension 3: Experience match
        exp_res = self._score_experience(candidate_years, cand_degree, cand_seniority, parsed_jd)

        # Overall composite score: 40% tech + 35% project + 25% experience
        overall = round(
            0.40 * tech_res.score + 0.35 * proj_res.score + 0.25 * exp_res.score, 1
        )
        overall = max(10.0, min(100.0, overall))

        radar = RadarScore(
            technical_score=tech_res.score,
            project_score=proj_res.score,
            experience_score=exp_res.score,
        )

        return JdMatchResponse(
            overall_score=overall,
            radar=radar,
            technical_match=tech_res,
            project_match=proj_res,
            experience_match=exp_res,
            parsed_jd=parsed_jd,
        )

    def _extract_candidate_skills(self, resume_data: Dict[str, Any]) -> Set[str]:
        skills: Set[str] = set()
        raw_skills = resume_data.get("skills")
        if isinstance(raw_skills, list):
            for item in raw_skills:
                if isinstance(item, str):
                    skills.update(self._extract_skills(item))
                elif isinstance(item, dict):
                    skills.update(self._extract_skills(str(item.get("name", ""))))
                    skills.update(self._extract_skills(str(item.get("keywords", ""))))
                    skills.update(self._extract_skills(str(item.get("level", ""))))
        elif isinstance(raw_skills, str):
            skills.update(self._extract_skills(raw_skills))

        # Also scan skillContent, experience, projects
        if resume_data.get("skillContent"):
            skills.update(self._extract_skills(str(resume_data["skillContent"])))

        for exp in resume_data.get("experience") or resume_data.get("workExperience") or []:
            if isinstance(exp, dict):
                skills.update(self._extract_skills(str(exp.get("details", ""))))
                skills.update(self._extract_skills(str(exp.get("title", ""))))

        for proj in resume_data.get("projects") or []:
            if isinstance(proj, dict):
                skills.update(self._extract_skills(str(proj.get("details", ""))))
                skills.update(self._extract_skills(str(proj.get("technologies", ""))))
                skills.update(self._extract_skills(str(proj.get("name", ""))))

        return skills

    def _extract_candidate_experience_profile(
        self, resume_data: Dict[str, Any]
    ) -> Tuple[float, Optional[str], str]:
        total_months = 0
        exp_list = resume_data.get("experience") or resume_data.get("workExperience") or []

        for exp in exp_list:
            if not isinstance(exp, dict):
                continue
            date_range = exp.get("date") or exp.get("period") or exp.get("time") or ""
            parsed_months = self._parse_duration_months(date_range)
            total_months += parsed_months

        # If no dates parsed but entries exist, estimate 1.5 years per entry
        if total_months == 0 and exp_list:
            total_months = len(exp_list) * 18

        years = round(total_months / 12.0, 1) if total_months > 0 else 2.0

        # Degree extraction
        deg: Optional[str] = None
        for edu in resume_data.get("education") or []:
            if isinstance(edu, dict):
                text = f"{edu.get('degree', '')} {edu.get('major', '')} {edu.get('school', '')}"
                if re.search(r"(博士|PhD)", text, re.IGNORECASE):
                    deg = "博士"
                    break
                elif re.search(r"(硕士|研究生|Master)", text, re.IGNORECASE):
                    deg = "硕士"
                    break
                elif re.search(r"(本科|学士)", text):
                    deg = "本科"
                elif re.search(r"(大专|专科)", text) and not deg:
                    deg = "大专"

        seniority = "mid"
        if years < 2:
            seniority = "junior"
        elif years >= 5:
            seniority = "senior"
        elif years >= 8:
            seniority = "lead"

        return years, deg, seniority

    def _parse_duration_months(self, date_str: str) -> int:
        if not date_str:
            return 0
        # Match e.g. 2021.06 - 2024.08, 2020-03 ~ 至今
        dates = re.findall(r"(\d{4})[./\-](\d{1,2})", date_str)
        if len(dates) >= 2:
            try:
                y1, m1 = int(dates[0][0]), int(dates[0][1])
                y2, m2 = int(dates[1][0]), int(dates[1][1])
                return max(1, (y2 - y1) * 12 + (m2 - m1))
            except Exception:
                pass
        elif len(dates) == 1 and re.search(r"(至今|现在|Present|current)", date_str, re.IGNORECASE):
            try:
                y1, m1 = int(dates[0][0]), int(dates[0][1])
                now = datetime.now()
                return max(1, (now.year - y1) * 12 + (now.month - m1))
            except Exception:
                pass
        return 0

    def _extract_projects_text(self, resume_data: Dict[str, Any]) -> str:
        parts: List[str] = []
        for p in resume_data.get("projects") or []:
            if isinstance(p, dict):
                parts.append(str(p.get("name", "")))
                parts.append(str(p.get("role", "")))
                parts.append(str(p.get("details", "")))
                parts.append(str(p.get("technologies", "")))
        for e in resume_data.get("experience") or resume_data.get("workExperience") or []:
            if isinstance(e, dict):
                parts.append(str(e.get("company", "")))
                parts.append(str(e.get("title", "")))
                parts.append(str(e.get("details", "")))
        return " ".join(parts)

    def _score_technical(
        self,
        candidate_skills: Set[str],
        parsed_jd: ParsedJd,
        resume_data: Dict[str, Any],
    ) -> TechnicalMatchResult:
        req_set = set(parsed_jd.required_skills)
        pref_set = set(parsed_jd.preferred_skills)

        if not req_set and not pref_set:
            return TechnicalMatchResult(
                score=85.0,
                matched_skills=sorted(candidate_skills)[:6],
                missing_skills=[],
                skill_coverage=1.0,
                reasons=["JD 未指定特定技术栈要求，候选人具备通用技术能力"],
            )

        matched_req = sorted(candidate_skills.intersection(req_set))
        matched_pref = sorted(candidate_skills.intersection(pref_set))
        missing_req = sorted(req_set.difference(candidate_skills))

        # Coverage formula
        req_denom = len(req_set) + 0.5 * len(pref_set)
        req_nom = len(matched_req) + 0.5 * len(matched_pref)
        coverage = req_nom / max(1.0, req_denom)

        base_score = min(85.0, coverage * 85.0)

        # Evidence depth bonus: for each matched core skill accompanied by numbers/metrics
        evidence_bonus = 0.0
        full_text = self._extract_projects_text(resume_data)
        num_pattern = re.compile(r"(\d+(?:\.\d+)?%|倍|万|ms|s|QPS|TPS)")
        for sk in matched_req:
            if re.search(rf"{re.escape(sk)}[^\n]*?{num_pattern.pattern}", full_text, re.IGNORECASE):
                evidence_bonus += 3.0
        evidence_bonus = min(15.0, evidence_bonus)

        final_score = round(min(100.0, max(15.0, base_score + evidence_bonus)), 1)

        reasons: List[str] = []
        if matched_req:
            reasons.append(f"命中核心技能 {len(matched_req)} 项: {', '.join(matched_req[:4])}")
        if missing_req:
            reasons.append(f"暂缺核心技能: {', '.join(missing_req[:4])}")
        if evidence_bonus > 0:
            reasons.append("关键技能在项目中有明确量化成果支撑")

        return TechnicalMatchResult(
            score=final_score,
            matched_skills=matched_req + matched_pref,
            missing_skills=missing_req,
            skill_coverage=round(coverage, 2),
            reasons=reasons,
        )

    def _score_project(self, cand_projects_text: str, parsed_jd: ParsedJd) -> ProjectMatchResult:
        if not cand_projects_text:
            return ProjectMatchResult(
                score=30.0,
                matched_domains=[],
                scale_indicators=[],
                reasons=["简历中未包含详细项目或工作经历描述"],
            )

        # 1. CJK bi-gram + English word token cosine similarity
        jd_text = f"{parsed_jd.title} {' '.join(parsed_jd.responsibilities)} {parsed_jd.raw_text}"
        sim = self._text_cosine_similarity(cand_projects_text, jd_text)
        sim_score = sim * 50.0

        # 2. Domain keywords match (up to 25 pts)
        matched_domains = [
            dk for dk in parsed_jd.domain_keywords if dk in cand_projects_text
        ]
        domain_score = min(25.0, len(matched_domains) * 12.0)

        # 3. Architectural scale indicators (up to 25 pts)
        scale_indicators = [
            si for si in SCALE_INDICATORS_SET if si in cand_projects_text and si in jd_text
        ]
        scale_score = min(25.0, len(scale_indicators) * 5.0)

        base_presence = 15.0 if len(cand_projects_text) > 50 else 0.0

        total_score = round(min(100.0, max(20.0, base_presence + sim_score + domain_score + scale_score)), 1)

        reasons: List[str] = []
        if matched_domains:
            reasons.append(f"业务领域契合: {', '.join(matched_domains[:3])}")
        if scale_indicators:
            reasons.append(f"包含大厂高可用架构指标: {', '.join(scale_indicators[:3])}")
        if sim > 0.2:
            reasons.append("项目职责描述与目标岗位工作内容高度相关")
        else:
            reasons.append("建议补充与目标岗位直接相关的业务落地场景")

        return ProjectMatchResult(
            score=total_score,
            matched_domains=matched_domains,
            scale_indicators=scale_indicators,
            reasons=reasons,
        )

    def _text_cosine_similarity(self, text_a: str, text_b: str) -> float:
        vec_a = self._extract_term_freq(text_a)
        vec_b = self._extract_term_freq(text_b)
        all_terms = set(vec_a.keys()).union(set(vec_b.keys()))
        if not all_terms:
            return 0.0

        dot_product = sum(vec_a.get(t, 0) * vec_b.get(t, 0) for t in all_terms)
        norm_a = math.sqrt(sum(v * v for v in vec_a.values()))
        norm_b = math.sqrt(sum(v * v for v in vec_b.values()))
        if norm_a == 0 or norm_b == 0:
            return 0.0
        return dot_product / (norm_a * norm_b)

    def _extract_term_freq(self, text: str) -> Dict[str, int]:
        freq: Dict[str, int] = {}
        # English words
        words = re.findall(r"[a-zA-Z0-9_\-\+]{2,}", text.lower())
        for w in words:
            freq[w] = freq.get(w, 0) + 1
        # CJK character unigrams & bi-grams
        cjk_chars = re.findall(r"[\u4e00-\u9fa5]", text)
        for c in cjk_chars:
            freq[c] = freq.get(c, 0) + 1
        for i in range(len(cjk_chars) - 1):
            bg = cjk_chars[i] + cjk_chars[i + 1]
            freq[bg] = freq.get(bg, 0) + 2
        return freq

    def _score_experience(
        self,
        candidate_years: float,
        candidate_degree: Optional[str],
        candidate_seniority: str,
        parsed_jd: ParsedJd,
    ) -> ExperienceMatchResult:
        reasons: List[str] = []

        # 1. Years score (45% weight)
        req_years = parsed_jd.experience_years
        if req_years is None or req_years == 0:
            years_score = 95.0
            reasons.append("岗位无硬性工作年限限制")
        elif candidate_years >= req_years:
            years_score = 100.0
            reasons.append(f"工作年限 ({candidate_years}年) 达到岗位要求 ({req_years}年)")
        else:
            ratio = candidate_years / max(1.0, req_years)
            years_score = max(25.0, round(100.0 * ratio, 1))
            reasons.append(f"工作年限 ({candidate_years}年) 略低于岗位期望 ({req_years}年)")

        # 2. Degree score (25% weight)
        degree_map = {"大专": 1, "本科": 2, "硕士": 3, "博士": 4}
        cand_deg_val = degree_map.get(candidate_degree or "本科", 2)
        req_deg_val = degree_map.get(parsed_jd.degree or "本科", 2)

        if parsed_jd.degree is None:
            deg_score = 90.0
            deg_matched = True
        elif cand_deg_val >= req_deg_val:
            deg_score = 100.0
            deg_matched = True
            reasons.append(f"学历符合要求 ({candidate_degree or '本科'})")
        else:
            deg_score = 55.0
            deg_matched = False
            reasons.append(f"学历与要求存在差距 (需 {parsed_jd.degree})")

        # 3. Seniority score (30% weight)
        sen_map = {"intern": 1, "junior": 2, "mid": 3, "senior": 4, "lead": 5}
        c_sen_val = sen_map.get(candidate_seniority, 3)
        r_sen_val = sen_map.get(parsed_jd.seniority, 3)
        diff = abs(c_sen_val - r_sen_val)

        if diff == 0:
            sen_score = 100.0
        elif diff == 1:
            sen_score = 90.0
        else:
            sen_score = 65.0

        score = round(0.45 * years_score + 0.25 * deg_score + 0.30 * sen_score, 1)
        score = max(10.0, min(100.0, score))

        return ExperienceMatchResult(
            score=score,
            candidate_years=candidate_years,
            required_years=req_years,
            degree_matched=deg_matched,
            seniority_matched=candidate_seniority,
            reasons=reasons,
        )

    # 3. Deterministic STAR Rewrite Generator
    async def generate_star_rewrites(
        self,
        jd_text: str,
        fields: Optional[List[Dict[str, Any]]] = None,
        resume_data: Optional[Dict[str, Any]] = None,
        mode: str = "auto",
        provider: Optional[str] = "deepseek",
    ) -> List[StarRewriteSuggestion]:
        parsed_jd = self.parse_jd(jd_text)
        candidates: List[Tuple[str, str, str]] = []  # (field_key, original_bullet, field_content)

        # Collect bullet points from fields or resume_data
        if fields:
            for f in fields:
                key = f.get("key", "")
                content = str(f.get("content", ""))
                bullets = self._split_bullets(content)
                for b in bullets:
                    if len(b.strip()) >= 8:
                        candidates.append((key, b.strip(), content))
        elif resume_data:
            for idx, exp in enumerate(resume_data.get("experience") or resume_data.get("workExperience") or []):
                if isinstance(exp, dict):
                    details = str(exp.get("details", ""))
                    for b in self._split_bullets(details):
                        if len(b.strip()) >= 8:
                            candidates.append((f"experience:{idx}:details", b.strip(), details))
            for idx, proj in enumerate(resume_data.get("projects") or []):
                if isinstance(proj, dict):
                    details = str(proj.get("details", ""))
                    for b in self._split_bullets(details):
                        if len(b.strip()) >= 8:
                            candidates.append((f"projects:{idx}:details", b.strip(), details))

        if not candidates:
            return []

        # Find candidates needing STAR rewriting (lacking metrics or missing JD skills)
        suggestions: List[StarRewriteSuggestion] = []
        target_skills = (parsed_jd.required_skills + parsed_jd.preferred_skills)[:6]

        for key, original, field_content in candidates[:8]:
            # Verify verbatim containment
            if original not in field_content:
                continue

            has_metrics = bool(re.search(r"(\d+(?:\.\d+)?%|倍|万|ms|s|QPS|TPS|GB|TB|人|套)", original))
            has_jd_skills = any(sk.lower() in original.lower() for sk in target_skills)

            # If it's already strong and contains JD skills and numbers, skip or prioritize weak ones
            if has_metrics and has_jd_skills and len(suggestions) >= 2:
                continue

            # Deterministic STAR synthesis
            suggestion = self._synthesize_star_deterministic(
                key=key,
                original=original,
                target_skills=target_skills,
                parsed_jd=parsed_jd,
            )
            suggestions.append(suggestion)

            if len(suggestions) >= 5:
                break

        return suggestions

    def _split_bullets(self, text: str) -> List[str]:
        if not text:
            return []
        # Strip HTML tags if any
        clean = re.sub(r"<[^>]+>", "\n", text)
        lines = [re.sub(r"^[•\-\*\d\.\s]+", "", l).strip() for l in clean.splitlines()]
        return [l for l in lines if len(l) >= 8]

    def _synthesize_star_deterministic(
        self,
        key: str,
        original: str,
        target_skills: List[str],
        parsed_jd: ParsedJd,
    ) -> StarRewriteSuggestion:
        # Determine aligned skills to inject
        aligned: List[str] = []
        for sk in target_skills:
            if sk.lower() not in original.lower():
                aligned.append(sk)
            if len(aligned) >= 2:
                break
        if not aligned and target_skills:
            aligned = [target_skills[0]]

        # Clean verb from original
        core_action = original
        for prefix in ["负责", "主要负责", "参与", "承担", "协助"]:
            if core_action.startswith(prefix):
                core_action = core_action[len(prefix):].lstrip("，, ")
                break

        # S / T / A / R synthesis
        situation = f"针对{parsed_jd.domain_keywords[0] if parsed_jd.domain_keywords else '业务核心场景'}下的高可用与扩展性挑战"
        task = f"主导{core_action[:24]}与架构演进"
        tech_inject = " 及 ".join(aligned) if aligned else "核心技术栈"
        action = f"采用 {tech_inject} 落地标准化治理方案并重构关键数据流"
        metric = "35%"
        result = f"使系统端到端处理耗时降低 {metric}，稳定性达 99.99%"

        suggested = f"{situation}，{task}；基于 {tech_inject} 进行全链路重构，{result}。"

        return StarRewriteSuggestion(
            key=key,
            original=original,
            suggested=suggested,
            star_breakdown=StarComponent(
                situation=situation,
                task=task,
                action=action,
                result=result,
            ),
            aligned_keywords=aligned,
            quantifiable_metrics=[metric, "99.99%"],
            reason=f"融入目标岗位要求的 {', '.join(aligned)} 并补全量化成果指标与业务背景",
        )
