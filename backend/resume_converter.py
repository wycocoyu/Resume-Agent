"""1:1 Python port of frontend Workspace v2 convertToBackendFormat + birthDateDisplay."""
from __future__ import annotations

import copy
import re
from datetime import date
from typing import Any

from backend.cli.schema import ResumeDataModel

_BR_DIV_P_RE = re.compile(r"<\s*(?:br|div|p)\s*/?>", re.IGNORECASE)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_MULTI_SPACE_RE = re.compile(r"\s+")
_BIRTH_DATE_RE = re.compile(r"^(\d{4})-(\d{2})(?:-(\d{2}))?$")
_COMPACT_TOKEN_RE = re.compile(r"[\s：:·\-]")
_MIDDLE_DOT_SPLIT_RE = re.compile(r"\s*·\s*")
_AGE_ONLY_RE = re.compile(r"^(?:年龄[：:]\s*)?\d{1,3}\s*岁$")
_DATE_ONLY_RE = re.compile(r"^\d{4}[-/]\d{2}(?:[-/]\d{2})?$")

SECTION_ID_MAPPING: dict[str, str] = {
    "skills": "skills",
    "experience": "internships",
    "workExperience": "workExperience",
    "projects": "projects",
    "openSource": "open_source",
    "selfEvaluation": "summary",
    "awards": "awards",
    "education": "education",
}


def strip_html_tags(text: str) -> str:
    """Strip HTML tags and normalize whitespace identically to textUtils.ts:stripHtmlTags."""
    if not text:
        return text
    result = _BR_DIV_P_RE.sub(" ", text)
    result = _ANY_TAG_RE.sub("", result)
    return _MULTI_SPACE_RE.sub(" ", result).strip()


def _is_js_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def get_age_from_birth_date(birth_date: str, *, today: date | None = None) -> int | None:
    """Compute integer age from YYYY-MM or YYYY-MM-DD (aligned with birthDateDisplay.ts)."""
    raw = (birth_date or "").strip()
    if not raw:
        return None
    match = _BIRTH_DATE_RE.match(raw)
    if not match:
        return None
    year = int(match.group(1))
    month = int(match.group(2))
    if month < 1 or month > 12:
        return None
    day = int(match.group(3)) if match.group(3) else 1
    ref = today or date.today()
    age = ref.year - year
    if ref.month < month or (ref.month == month and ref.day < day):
        age -= 1
    return age if 0 <= age <= 120 else None


def format_birth_date_for_header(
    birth_date: str,
    mode: str = "birthDate",
    *,
    today: date | None = None,
) -> str:
    raw = (birth_date or "").strip()
    if not raw:
        return ""
    if mode == "age":
        age = get_age_from_birth_date(raw, today=today)
        return f"{age}岁" if age is not None else raw
    return raw


def _compact_contact_token(text: str) -> str:
    return _COMPACT_TOKEN_RE.sub("", text or "").lower()


def collapse_duplicate_contact_segments(status: str) -> str:
    trimmed = (status or "").strip()
    if not trimmed:
        return ""
    parts = [p.strip() for p in _MIDDLE_DOT_SPLIT_RE.split(trimmed) if p.strip()]
    if len(parts) < 2:
        return trimmed
    compact_parts = [_compact_contact_token(p) for p in parts]
    if len(set(compact_parts)) == 1:
        return parts[0]
    deduped: list[str] = []
    for idx, part in enumerate(parts):
        if idx > 0 and compact_parts[idx] == compact_parts[idx - 1]:
            continue
        deduped.append(part)
    return " · ".join(deduped)


def _status_is_pure_age_or_date(status: str) -> bool:
    return bool(_AGE_ONLY_RE.match(status) or _DATE_ONLY_RE.match(status))


def status_duplicates_birth(
    status: str | None,
    birth_date: str | None,
    mode: str = "birthDate",
    *,
    today: date | None = None,
) -> bool:
    s = (status or "").strip()
    birth = (birth_date or "").strip()
    if not s or not birth:
        return False
    birth_text = format_birth_date_for_header(birth, mode, today=today)
    if not birth_text:
        return False
    compact_status = _compact_contact_token(s)
    compact_birth = _compact_contact_token(birth_text)
    if compact_birth and compact_birth in compact_status:
        return True
    compact_raw = _compact_contact_token(birth)
    if compact_raw and compact_raw in compact_status:
        return True
    return False


def resolve_employment_status_for_render(
    status: str | None,
    birth_date: str | None,
    mode: str = "birthDate",
    *,
    today: date | None = None,
) -> str | None:
    s = collapse_duplicate_contact_segments((status or "").strip())
    if not (birth_date or "").strip():
        return s or None
    if s and _status_is_pure_age_or_date(s):
        return None
    if s and status_duplicates_birth(s, birth_date, mode, today=today):
        return None
    return s or None


def _convert_experience_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    converted: list[dict[str, Any]] = []
    for exp in items:
        if exp.get("visible") is False:
            continue
        entry: dict[str, Any] = {
            "title": strip_html_tags(exp["company"]),
            "subtitle": strip_html_tags(exp["position"]),
            "date": exp["date"],
            "highlights": [exp["details"]],
        }
        if exp.get("companyNameFontSize"):
            entry["companyNameFontSize"] = exp["companyNameFontSize"]
        if exp.get("companyLogo"):
            entry["logo"] = exp["companyLogo"]
        if exp.get("companyLogoSize"):
            entry["logoSize"] = exp["companyLogoSize"]
        converted.append(entry)
    return converted


def convert_to_backend_format(
    data: dict[str, Any] | ResumeDataModel,
    *,
    today: date | None = None,
) -> dict[str, Any]:
    """Convert validated Workspace v2 ResumeData into BackendResumeData dict."""
    if isinstance(data, ResumeDataModel):
        src = data.model_dump(exclude_unset=True)
    elif isinstance(data, dict):
        src = data
    else:
        raise TypeError("convert_to_backend_format expects a validated ResumeData dict or ResumeDataModel")

    menu_sections = src["menuSections"]
    section_titles: dict[str, str] = {}
    for section in menu_sections:
        raw_title = section.get("title")
        if not raw_title or not raw_title.strip():
            continue
        trimmed = raw_title.strip()
        sec_id = section["id"]
        mapped_id = SECTION_ID_MAPPING.get(sec_id, sec_id)
        section_titles[sec_id] = trimmed
        section_titles[mapped_id] = trimmed
        if sec_id == "openSource":
            section_titles["opensource"] = trimmed

    global_settings = src.get("globalSettings") or {}
    birth_display_mode = global_settings.get("birthDateDisplayMode") or "birthDate"
    basic = src["basic"]
    employment_status = resolve_employment_status_for_render(
        basic.get("employementStatus"),
        basic.get("birthDate"),
        birth_display_mode,
        today=today,
    )

    skill_content = src.get("skillContent") or ""
    result: dict[str, Any] = {
        "name": basic["name"],
    }
    if basic.get("birthDate"):
        result["birthDate"] = basic["birthDate"]
    if basic.get("photo"):
        result["photo"] = basic["photo"]
    for num_field in ("photoOffsetX", "photoOffsetY", "photoWidthCm", "photoHeightCm"):
        val = basic.get(num_field)
        if _is_js_number(val):
            result[num_field] = val

    result["contact"] = {
        "phone": basic["phone"],
        "email": basic["email"],
        "location": basic["location"],
    }
    if employment_status:
        result["employementStatus"] = employment_status
    if basic.get("workYears"):
        result["workYears"] = basic["workYears"]
    if basic.get("blog"):
        result["blog"] = basic["blog"]

    result["objective"] = basic["title"]
    result["summary"] = src.get("selfEvaluation") or ""
    result["skillContent"] = skill_content
    result["skills"] = [{"category": "", "details": skill_content}] if skill_content else []

    result["internships"] = _convert_experience_items(src.get("experience") or [])
    result["workExperience"] = _convert_experience_items(src.get("workExperience") or [])

    projects_out: list[dict[str, Any]] = []
    for proj in src.get("projects") or []:
        if proj.get("visible") is False:
            continue
        p_entry: dict[str, Any] = {
            "title": strip_html_tags(proj["name"]),
        }
        if proj.get("projectNameFontSize"):
            p_entry["projectNameFontSize"] = proj["projectNameFontSize"]
        if proj.get("projectLinkFontSize"):
            p_entry["projectLinkFontSize"] = proj["projectLinkFontSize"]
        p_entry["subtitle"] = strip_html_tags(proj["role"])
        p_entry["date"] = proj["date"]
        p_entry["highlights"] = [proj["description"]]
        raw_link = proj.get("link")
        if isinstance(raw_link, str) and raw_link.strip():
            p_entry["link"] = raw_link.strip()
        projects_out.append(p_entry)
    result["projects"] = projects_out

    open_source_out: list[dict[str, Any]] = []
    for os_item in src.get("openSource") or []:
        if os_item.get("visible") is False:
            continue
        os_entry: dict[str, Any] = {
            "title": strip_html_tags(os_item["name"]),
        }
        if os_item.get("projectNameFontSize"):
            os_entry["projectNameFontSize"] = os_item["projectNameFontSize"]
        os_entry["subtitle"] = strip_html_tags(os_item.get("role") or "")
        os_entry["repoUrl"] = os_item.get("repo") or ""
        if os_item.get("repoUrlFontSize"):
            os_entry["repoUrlFontSize"] = os_item["repoUrlFontSize"]
        os_entry["date"] = os_item.get("date") or ""
        os_entry["items"] = [os_item["description"]]
        open_source_out.append(os_entry)
    result["open_source"] = open_source_out

    awards_out: list[dict[str, Any]] = []
    for award in src.get("awards") or []:
        if award.get("visible") is False:
            continue
        awards_out.append(
            {
                "title": strip_html_tags(award["title"]),
                "issuer": strip_html_tags(award.get("issuer") or ""),
                "date": award.get("date") or "",
                "description": award.get("description") or "",
            }
        )
    result["awards"] = awards_out

    education_out: list[dict[str, Any]] = []
    for edu in src.get("education") or []:
        if edu.get("visible") is False:
            continue
        edu_entry: dict[str, Any] = {
            "title": strip_html_tags(edu["school"]),
            "subtitle": strip_html_tags(edu["major"]),
            "degree": strip_html_tags(edu["degree"]),
            "date": f"{edu['startDate']} - {edu['endDate']}" if edu.get("endDate") else edu["startDate"],
            "details": [edu["description"]] if edu.get("description") else [],
        }
        if edu.get("schoolNameFontSize"):
            edu_entry["schoolNameFontSize"] = edu["schoolNameFontSize"]
        if edu.get("schoolLogo"):
            edu_entry["logo"] = edu["schoolLogo"]
        if edu.get("schoolLogoSize"):
            edu_entry["logoSize"] = edu["schoolLogoSize"]
        education_out.append(edu_entry)
    result["education"] = education_out

    result["sectionOrder"] = [
        SECTION_ID_MAPPING.get(s["id"], s["id"])
        for s in menu_sections
        if s.get("enabled") and s.get("id") != "basic"
    ]
    result["sectionTitles"] = section_titles

    custom_out: dict[str, list[dict[str, Any]]] = {}
    for section_id, items in (src.get("customData") or {}).items():
        item_list = items if isinstance(items, list) else []
        custom_out[section_id] = [
            {
                "id": item["id"],
                "title": strip_html_tags(item.get("title") or ""),
                "subtitle": strip_html_tags(item.get("subtitle") or ""),
                "dateRange": item.get("dateRange") or "",
                "description": item.get("description") or "",
                "visible": item.get("visible") is not False,
            }
            for item in item_list
            if item.get("visible") is not False
        ]
    result["customData"] = custom_out
    result["globalSettings"] = copy.deepcopy(src.get("globalSettings"))

    return result
