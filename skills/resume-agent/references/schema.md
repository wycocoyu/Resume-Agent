# ResumeData Schema & Field Conventions

Run `resume-agent schema` at any time to inspect the live JSON Schema generated from `backend/cli/schema.py:ResumeDataModel`.

## 1. Top-Level `ResumeData` Keys

### Required Keys (all 18 must be present)

| Key | Type | Notes |
| :--- | :--- | :--- |
| `id` | `string` (non-empty) | e.g. `"resume_1730000000000"` or UUID |
| `title` | `string` | Workspace document title, e.g. `"我的简历"` |
| `createdAt` | `string` | ISO-8601 timestamp |
| `updatedAt` | `string` | ISO-8601 timestamp |
| `templateId` | `string \| null` | Keep `null` for standard LaTeX template |
| `basic` | `BasicInfo` | Candidate header & contact info |
| `education` | `Education[]` | Education entries |
| `experience` | `Experience[]` | Internship entries (`实习经历`) |
| `projects` | `Project[]` | Project entries (`项目经历`) |
| `openSource` | `OpenSource[]` | Open-source entries (`开源经历`) |
| `awards` | `Award[]` | Honors & awards (`荣誉奖项`) |
| `customData` | `Record<string, CustomItem[]>` | Keyed by `custom_*` section ID (e.g. `custom_research`) |
| `selfEvaluation` | `string` (HTML) | Summary / self-evaluation (`自我评价`) |
| `skillContent` | `string` (HTML) | Technical skills (`专业技能`) |
| `activeSection` | `string` | Active UI tab, default `"basic"` |
| `draggingProjectId` | `string \| null` | Keep `null` |
| `menuSections` | `MenuSection[]` | Controls section titles, enabled flags, and PDF section order |
| `globalSettings` | `GlobalSettings` | Typography, spacing, and LaTeX layout settings |

### Optional Top-Level Keys

| Key | Type | Notes |
| :--- | :--- | :--- |
| `workExperience` | `Experience[] \| null` | Full-time work experience (`工作经历`), separate from `experience` (`实习经历`) |
| `templateType` | `"latex" \| "html" \| null` | Default `"latex"`. Note: CLI always renders via LaTeX and emits a warning if `"html"` |
| `alias` | `string \| null` | Optional workspace remark/tag |

---

## 2. Rich-Text HTML vs Plain-Text Convention

### Exactly 8 HTML Rich-Text Fields

Use `<p>`, `<ul class="custom-list"><li><p>...</p></li></ul>`, `<ol>`, `<strong>`, `<em>`, `<a href="...">`, `<br>` ONLY in these 8 paths:

1. `education[*].description`
2. `workExperience[*].details`
3. `experience[*].details`
4. `projects[*].description`
5. `openSource[*].description`
6. `customData[*][*].description`
7. `selfEvaluation`
8. `skillContent`

Recommended bullet pattern:
```html
<ul class="custom-list"><li><p><strong>高并发网关</strong>：重构核心限流链路，峰值吞吐提升 45%，P99 延迟降至 12ms</p></li></ul>
```

### Plain-Text Fields (No HTML Tags!)

- **`awards[*].description` is PLAIN TEXT ONLY.** The LaTeX awards generator escapes it directly via `escape_latex`; HTML tags like `<p>` will appear literally in the rendered PDF.
- All title/header fields (`basic.*`, `education[*].school/major/degree`, `workExperience[*].company/position`, `experience[*].company/position`, `projects[*].name/role`, `openSource[*].name/role`, `awards[*].title/issuer`, `customData[*][*].title/subtitle`) must be plain strings.

---

## 3. Sub-Object Schemas

### `basic` (`BasicInfo`)
- Required: `name`, `title` (target role), `email`, `phone`, `location` (`string`, use `""` when omitted).
- Optional:
  - `birthDate`: `"YYYY-MM"` or `"YYYY-MM-DD"`
  - `employementStatus`: e.g. `"26届应届"` or `"在职-考虑机会"` (note spelling `employementStatus` with `e`)
  - `workYears`: e.g. `"3年经验"`
  - `blog`: URL string, e.g. `"https://github.com/username"`
  - `photo`: CLI accepts local PNG/JPEG/PDF file path or `data:image/png;base64,...` (or `https://...` with `--online`). WebP and SVG are rejected by magic-byte check.
  - `photoOffsetX`, `photoOffsetY`, `photoWidthCm`, `photoHeightCm`: `number`

### `education[*]` (`Education`)
- Required: `id` (non-empty `string`), `school`, `major`, `degree`, `startDate`, `endDate`.
- Optional: `gpa`, `description` (HTML), `visible` (`boolean`), `schoolNameFontSize` (`number`), `schoolLogo` (Chinese school name key, e.g. `"北京大学"`), `schoolLogoSize` (`number`).

### `workExperience[*]` and `experience[*]` (`Experience`)
- Required: `id`, `company`, `position`, `date`, `details` (HTML).
- Optional: `visible` (`boolean`), `companyNameFontSize` (`number`), `companyLogo` (`string`), `companyLogoSize` (`number`).
- Built-in `companyLogo` keys: `bytedance`, `tencent`, `tencentcloud`, `alibaba`, `meituan`, `kuaishou`, `baidu`, `jd`, `huawei`, `xiaohongshu`, `netease`, `xiaomi`, `didi`, `pinduoduo`, `bilibili`, `antgroup`, `microsoft`, `google`, `apple`, `deeplang`.

### `projects[*]` (`Project`)
- Required: `id`, `name`, `role`, `date`, `description` (HTML).
- Optional: `visible` (`boolean`, default `true`), `link` (`string`), `projectNameFontSize` (`number`), `projectLinkFontSize` (`number`).

### `openSource[*]` (`OpenSource`)
- Required: `id`, `name`, `description` (HTML).
- Optional: `repo` (URL `string`), `role`, `date`, `visible` (`boolean`), `projectNameFontSize` (`number`), `repoUrlFontSize` (`number`).

### `awards[*]` (`Award`)
- Required: `id`, `title`.
- Optional: `issuer`, `date`, `description` (**plain text only**), `visible` (`boolean`).

### `customData[sectionId][*]` (`CustomItem`)
- `sectionId` must start with `custom_` (for example `"custom_research"`) and match an entry in `menuSections` with `"id": sectionId` and `"enabled": true`.
- Required per item: `id`, `title`, `subtitle`, `dateRange`, `description` (HTML).
- Optional: `visible` (`boolean`, default `true`).

### `menuSections[*]` (`MenuSection`)
- Required: `id`, `title`, `icon`, `enabled` (`boolean`), `order` (`integer`).
- Standard IDs: `basic`, `education`, `workExperience`, `experience`, `projects`, `openSource`, `skills`, `awards`, `selfEvaluation`, `custom_research`.
- PDF section rendering follows the order of enabled non-`basic` entries in `menuSections`.

### `globalSettings` (`GlobalSettings`)
- Key LaTeX options:
  - `latexFontSize`: integer `8`..`12` (default `11`)
  - `latexMargin`: `"tight" | "compact" | "standard" | "relaxed" | "wide"` (default `"standard"`)
  - `latexLineSpacing`: `0.8`..`2.0` (default `1.15`)
  - `experienceListType`: `"none" | "unordered" | "ordered"`
  - `awardsListType`: `"unordered" | "ordered"`
  - `birthDateDisplayMode`: `"birthDate" | "age"`
  - `fieldLabelModes`: map of `title | birthDate | email | phone | location | blog | workYears` to `"icon" | "text" | "none"`
