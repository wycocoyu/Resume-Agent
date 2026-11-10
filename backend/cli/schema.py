"""Single-source Pydantic v2 schema, skeleton builder, and read-only validator for ResumeData."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Literal

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    StrictBool,
    StrictFloat,
    StrictInt,
    StrictStr,
    ValidationError,
)


def _require_non_empty(value: str) -> str:
    if not value.strip():
        raise ValueError("must be a non-empty string")
    return value


NonEmptyStrictStr = Annotated[StrictStr, AfterValidator(_require_non_empty)]
NumberValue = StrictInt | StrictFloat
FieldLabelMode = Literal["icon", "text", "none"]


FIELD_CONVENTIONS: dict[str, Any] = {
    "html_rich_text_fields": [
        "education[*].description",
        "workExperience[*].details",
        "experience[*].details",
        "projects[*].description",
        "openSource[*].description",
        "customData[*][*].description",
        "selfEvaluation",
        "skillContent",
    ],
    "plain_text_fields": [
        "awards[*].description",
        "awards[*].title",
        "awards[*].issuer",
        "awards[*].date",
        "basic.name",
        "basic.title",
        "basic.email",
        "basic.phone",
        "basic.location",
        "basic.employementStatus",
        "basic.workYears",
        "basic.birthDate",
        "basic.blog",
        "education[*].school",
        "education[*].major",
        "education[*].degree",
        "workExperience[*].company",
        "workExperience[*].position",
        "experience[*].company",
        "experience[*].position",
        "projects[*].name",
        "projects[*].role",
        "openSource[*].name",
        "openSource[*].role",
        "customData[*][*].title",
        "customData[*][*].subtitle",
    ],
    "notes": {
        "html_allowed_tags": ["p", "ul", "ol", "li", "strong", "em", "a", "br"],
        "awards_description": (
            "awards[*].description is plain text ONLY (LaTeX escapes it directly; "
            "do NOT wrap in <p>, <ul>, or other HTML tags)."
        ),
        "custom_sections": (
            "Any custom_* key in customData requires a matching entry in menuSections "
            "with id='custom_*' and enabled=true to be rendered."
        ),
    },
}


class MenuSectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStrictStr
    title: StrictStr
    icon: StrictStr
    enabled: StrictBool
    order: StrictInt


class BasicFieldTypeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStrictStr
    key: StrictStr
    label: StrictStr
    type: Literal["date", "textarea", "text", "editor"] | None = None
    visible: StrictBool
    custom: StrictBool | None = None


class CustomFieldTypeModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStrictStr
    label: StrictStr
    value: StrictStr
    icon: StrictStr | None = None
    visible: StrictBool | None = None
    custom: StrictBool | None = None


class BasicInfoModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: StrictStr
    title: StrictStr
    email: StrictStr
    phone: StrictStr
    location: StrictStr
    birthDate: StrictStr | None = None
    workYears: StrictStr | None = None
    employementStatus: StrictStr | None = None
    blog: StrictStr | None = None
    photo: StrictStr | None = None
    photoOffsetX: NumberValue | None = None
    photoOffsetY: NumberValue | None = None
    photoWidthCm: NumberValue | None = None
    photoHeightCm: NumberValue | None = None
    icons: dict[StrictStr, StrictStr] | None = None
    layout: Literal["left", "center", "right"] | None = None
    customFields: list[CustomFieldTypeModel] | None = None
    fieldOrder: list[BasicFieldTypeModel] | None = None


class EducationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStrictStr
    school: StrictStr
    major: StrictStr
    degree: StrictStr
    startDate: StrictStr
    endDate: StrictStr
    gpa: StrictStr | None = None
    description: StrictStr | None = None
    visible: StrictBool | None = None
    schoolNameFontSize: NumberValue | None = None
    schoolLogo: StrictStr | None = None
    schoolLogoSize: NumberValue | None = None


class ExperienceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStrictStr
    company: StrictStr
    position: StrictStr
    date: StrictStr
    details: StrictStr
    visible: StrictBool | None = None
    companyNameFontSize: NumberValue | None = None
    companyLogo: StrictStr | None = None
    companyLogoSize: NumberValue | None = None


class OpenSourceModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStrictStr
    name: StrictStr
    projectNameFontSize: NumberValue | None = None
    repo: StrictStr | None = None
    repoUrlFontSize: NumberValue | None = None
    role: StrictStr | None = None
    date: StrictStr | None = None
    description: StrictStr
    visible: StrictBool | None = None


class AwardModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStrictStr
    title: StrictStr
    issuer: StrictStr | None = None
    date: StrictStr | None = None
    description: StrictStr | None = None
    visible: StrictBool | None = None


class ProjectModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStrictStr
    name: StrictStr
    projectNameFontSize: NumberValue | None = None
    projectLinkFontSize: NumberValue | None = None
    role: StrictStr
    date: StrictStr
    description: StrictStr
    visible: StrictBool = True
    link: StrictStr | None = None


class CustomItemModel(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: NonEmptyStrictStr
    title: StrictStr
    subtitle: StrictStr
    dateRange: StrictStr
    description: StrictStr
    visible: StrictBool = True


class GlobalSettingsModel(BaseModel):
    model_config = ConfigDict(extra="allow")

    themeColor: StrictStr | None = None
    fontFamily: StrictStr | None = None
    baseFontSize: NumberValue | None = None
    pagePadding: NumberValue | None = None
    paragraphSpacing: NumberValue | None = None
    lineHeight: NumberValue | None = None
    sectionSpacing: NumberValue | None = None
    headerSize: NumberValue | None = None
    subheaderSize: NumberValue | None = None
    useIconMode: StrictBool | None = None
    centerSubtitle: StrictBool | None = None
    companyNameFontSize: NumberValue | None = None
    companyLogoSize: NumberValue | None = None
    experienceListType: Literal["none", "unordered", "ordered"] | None = None
    awardsListType: Literal["unordered", "ordered"] | None = None
    openSourceRepoDisplay: Literal["below", "inline", "icon"] | None = None
    openSourceRepoLabel: StrictStr | None = None
    projectLinkDisplay: Literal["below", "inline", "icon"] | None = None
    projectLinkLabel: StrictStr | None = None
    experienceGap: NumberValue | None = None
    projectExperienceGap: NumberValue | None = None
    latexFontSize: NumberValue | None = None
    latexMargin: Literal["tight", "compact", "standard", "relaxed", "wide"] | None = None
    latexLineSpacing: NumberValue | None = None
    latexHeaderTopGapPx: NumberValue | None = None
    latexHeaderNameContactGapPx: NumberValue | None = None
    latexHeaderBottomGapPx: NumberValue | None = None
    birthDateDisplayMode: Literal["birthDate", "age"] | None = None
    contactLabelMode: FieldLabelMode | None = None
    builderSettings: dict[StrictStr, Any] | None = None
    fieldLabelModes: dict[StrictStr, FieldLabelMode] | None = None


class ResumeDataModel(BaseModel):
    """Authoritative Workspace v2 ResumeData contract."""

    model_config = ConfigDict(extra="forbid")

    # Required top-level keys (R2)
    id: NonEmptyStrictStr
    title: StrictStr
    createdAt: StrictStr
    updatedAt: StrictStr
    templateId: StrictStr | None
    basic: BasicInfoModel
    education: list[EducationModel]
    experience: list[ExperienceModel]
    projects: list[ProjectModel]
    openSource: list[OpenSourceModel]
    awards: list[AwardModel]
    customData: dict[StrictStr, list[CustomItemModel]]
    selfEvaluation: StrictStr
    skillContent: StrictStr
    activeSection: StrictStr
    draggingProjectId: StrictStr | None
    menuSections: list[MenuSectionModel]
    globalSettings: GlobalSettingsModel

    # Optional top-level keys (R2)
    templateType: Literal["latex", "html"] | None = None
    alias: StrictStr | None = None
    workExperience: list[ExperienceModel] | None = None


DEFAULT_MENU_SECTIONS: list[dict[str, Any]] = [
    {"id": "basic", "title": "基本信息", "icon": "👤", "enabled": True, "order": 0},
    {"id": "education", "title": "教育经历", "icon": "🎓", "enabled": True, "order": 1},
    {"id": "workExperience", "title": "工作经历", "icon": "🏢", "enabled": True, "order": 2},
    {"id": "experience", "title": "实习经历", "icon": "💼", "enabled": True, "order": 3},
    {"id": "projects", "title": "项目经历", "icon": "🚀", "enabled": True, "order": 4},
    {"id": "openSource", "title": "开源经历", "icon": "🔗", "enabled": True, "order": 5},
    {"id": "skills", "title": "专业技能", "icon": "⚡", "enabled": True, "order": 6},
    {"id": "awards", "title": "荣誉奖项", "icon": "🎖️", "enabled": True, "order": 7},
    {"id": "selfEvaluation", "title": "自我评价", "icon": "📝", "enabled": True, "order": 8},
    {"id": "custom_research", "title": "竞赛科研", "icon": "🔬", "enabled": True, "order": 9},
]

DEFAULT_GLOBAL_SETTINGS: dict[str, Any] = {
    "lineHeight": 1.5,
    "baseFontSize": 16,
    "headerSize": 18,
    "pagePadding": 40,
    "sectionSpacing": 20,
    "paragraphSpacing": 10,
    "experienceGap": 1,
    "projectExperienceGap": 1,
    "latexFontSize": 11,
    "latexMargin": "standard",
    "latexLineSpacing": 1.15,
    "latexHeaderTopGapPx": -4,
    "latexHeaderNameContactGapPx": 0,
    "latexHeaderBottomGapPx": -1,
}


@dataclass(frozen=True)
class FieldValidationIssue:
    path: str
    message: str
    error_type: str

    def to_dict(self) -> dict[str, str]:
        return {
            "path": self.path,
            "message": self.message,
            "type": self.error_type,
        }


def format_error_loc(loc: tuple[int | str, ...]) -> str:
    """Format Pydantic error location tuple as dot/bracket path (e.g. menuSections[0].enabled)."""
    if not loc:
        return "<root>"
    out = ""
    for part in loc:
        if isinstance(part, int):
            out += f"[{part}]"
        else:
            key = str(part)
            if not out:
                out = key
            else:
                out += f".{key}"
    return out


def build_initial_resume(*, title: str = "我的简历") -> dict[str, Any]:
    """Build standard empty ResumeData skeleton aligned with Workspace v2 constants.ts."""
    now_ms = int(time.time() * 1000)
    now_iso = datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    skeleton: dict[str, Any] = {
        "id": f"resume_{now_ms}",
        "title": title,
        "createdAt": now_iso,
        "updatedAt": now_iso,
        "templateId": None,
        "templateType": "latex",
        "basic": {
            "name": "",
            "title": "",
            "email": "",
            "phone": "",
            "location": "",
        },
        "education": [],
        "workExperience": [],
        "experience": [],
        "projects": [],
        "openSource": [],
        "awards": [],
        "customData": {},
        "selfEvaluation": "",
        "skillContent": "",
        "activeSection": "basic",
        "draggingProjectId": None,
        "menuSections": [dict(sec) for sec in DEFAULT_MENU_SECTIONS],
        "globalSettings": dict(DEFAULT_GLOBAL_SETTINGS),
    }
    ResumeDataModel.model_validate(skeleton)
    return skeleton


def get_resume_json_schema() -> dict[str, Any]:
    """Export JSON Schema from ResumeDataModel and inject x-field-conventions."""
    schema = ResumeDataModel.model_json_schema()
    schema["x-field-conventions"] = json.loads(json.dumps(FIELD_CONVENTIONS, ensure_ascii=False))
    return schema


def validate_resume_data(raw: Any) -> tuple[ResumeDataModel | None, list[FieldValidationIssue]]:
    """Strictly validate raw parsed JSON without mutating input."""
    if not isinstance(raw, dict):
        return None, [
            FieldValidationIssue(
                path="<root>",
                message="Resume JSON root must be an object",
                error_type="dict_type",
            )
        ]
    try:
        model = ResumeDataModel.model_validate(raw)
        return model, []
    except ValidationError as exc:
        issues: list[FieldValidationIssue] = []
        for err in exc.errors(include_url=False):
            loc = tuple(err.get("loc") or ())
            issues.append(
                FieldValidationIssue(
                    path=format_error_loc(loc),
                    message=str(err.get("msg") or "Invalid value"),
                    error_type=str(err.get("type") or "validation_error"),
                )
            )
        return None, issues


def load_and_validate_resume_file(
    file_path: Path,
) -> tuple[dict[str, Any] | None, ResumeDataModel | None, list[FieldValidationIssue], str | None]:
    """Read-only load + validate from disk. Never writes to file_path."""
    if not file_path.exists():
        return None, None, [], f"File not found: {file_path}"
    if not file_path.is_file():
        return None, None, [], f"Not a regular file: {file_path}"
    try:
        raw_text = file_path.read_text(encoding="utf-8")
    except OSError as exc:
        return None, None, [], f"Failed to read file {file_path}: {exc}"
    try:
        raw_data = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        return (
            None,
            None,
            [
                FieldValidationIssue(
                    path=f"<json>:line {exc.lineno} col {exc.colno}",
                    message=exc.msg,
                    error_type="json_invalid",
                )
            ],
            f"Invalid JSON syntax at line {exc.lineno}, column {exc.colno}: {exc.msg}",
        )
    model, issues = validate_resume_data(raw_data)
    if issues:
        return raw_data if isinstance(raw_data, dict) else None, None, issues, None
    return raw_data, model, [], None
