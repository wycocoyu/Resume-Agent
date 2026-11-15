"""
LaTeX 工具函数模块
提供 LaTeX 特殊字符转义和简历数据标准化功能
"""
import os
import re
import shutil
from pathlib import Path
from typing import Dict, Any, List, Optional


def strip_html_tags(text: str) -> str:
    """移除 HTML 标签，保留纯文本内容"""
    if not text:
        return text
    # 将 <br>, <br/>, <div>, </div> 等块级标签替换为空格（避免文字粘连）
    text = re.sub(r'<\s*(?:br|div|p)\s*/?\s*>', ' ', text, flags=re.IGNORECASE)
    # 移除所有剩余 HTML 标签
    text = re.sub(r'<[^>]+>', '', text)
    # 合并多余空格
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def escape_latex(text: str) -> str:
    """
    转义 LaTeX 特殊字符，并处理 Markdown 加粗语法
    """
    if not isinstance(text, str):
        text = str(text)
    
    """先清理 HTML 标签（来自富文本编辑器的残留）"""
    text = strip_html_tags(text)
    
    """先处理 **text** -> \textbf{text} (在转义之前)"""
    bold_pattern = re.compile(r'\*\*(.+?)\*\*')
    bold_matches = []
    
    def save_bold(match):
        bold_matches.append(match.group(1))
        return f'__BOLD_{len(bold_matches)-1}__'
    
    text = bold_pattern.sub(save_bold, text)
    
    """移除换行符（LaTeX 命令参数不能跨行）"""
    text = text.replace('\n', ' ').replace('\r', ' ')
    
    """LaTeX 特殊字符转义"""
    replacements = {
        '\\': r'\textbackslash{}',
        '&': r'\&',
        '%': r'\%',
        '$': r'\$',
        '#': r'\#',
        '^': r'\textasciicircum{}',
        '_': r'\_',
        '{': r'\{',
        '}': r'\}',
        '~': r'\textasciitilde{}',
    }
    
    result = text
    for char, replacement in replacements.items():
        result = result.replace(char, replacement)
    
    """恢复加粗文本（转义后的内容需要再次转义）"""
    for i, bold_text in enumerate(bold_matches):
        escaped_bold = bold_text
        for char, replacement in replacements.items():
            escaped_bold = escaped_bold.replace(char, replacement)
        result = result.replace(f'\\_\\_BOLD\\_{i}\\_\\_', f'\\textbf{{{escaped_bold}}}')
    
    return result


def normalize_resume_data(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    标准化简历数据字段名
    支持中文和英文字段名，统一转换为英文
    
    参数:
        data: 原始简历数据
    
    返回:
        标准化后的简历数据（英文字段名）
    """
    """字段名映射表：中文 -> 英文"""
    field_mapping = {
        '姓名': 'name',
        '联系方式': 'phone',
        '邮箱': 'email',
        '电话': 'phone',
        '手机': 'phone',
        '地址': 'location',
        '所在地': 'location',
        '求职方向': 'summary',
        '个人简介': 'summary',
        '自我评价': 'summary',
        '实习经历': 'internships',
        '工作经历': 'experience',
        '项目经验': 'projects',
        '项目经历': 'projects',
        '项目': 'projects',
        '开源经历': 'opensource',
        '开源贡献': 'opensource',
        '开源': 'opensource',
        '专业技能': 'skills',
        '技能': 'skills',
        '教育经历': 'education',
        '教育': 'education',
        '获奖荣誉': 'awards',
        '荣誉': 'awards',
        '证书': 'certifications',
        '资格证书': 'certifications',
        '论文': 'publications',
        '论文发表': 'publications',
        '竞赛经历': 'competitions',
        '竞赛': 'competitions',
    }
    
    normalized = {}
    contact_info = {}
    
    for key, value in data.items():
        """如果是中文字段名，转换为英文"""
        english_key = field_mapping.get(key, key)
        
        """特殊处理：联系信息字段"""
        if english_key in ['phone', 'email', 'location']:
            contact_info[english_key] = value
        else:
            """处理嵌套结构"""
            if isinstance(value, list):
                normalized[english_key] = [
                    normalize_item(item, field_mapping) if isinstance(item, dict) else item 
                    for item in value
                ]
            elif isinstance(value, dict) and key != 'contact':
                normalized[english_key] = normalize_item(value, field_mapping)
            else:
                normalized[english_key] = value
    
    """合并 contact 信息"""
    if contact_info:
        if 'contact' not in normalized:
            normalized['contact'] = {}
        """如果 contact 是字符串，转换为字典"""
        if isinstance(normalized.get('contact'), str):
            contact_info['phone'] = normalized['contact']
            normalized['contact'] = contact_info
        elif isinstance(normalized.get('contact'), dict):
            normalized['contact'].update(contact_info)
        else:
            normalized['contact'] = contact_info
    
    return normalized


def normalize_item(item: Dict[str, Any], field_mapping: Dict[str, str]) -> Dict[str, Any]:
    """
    标准化单个项目的字段名
    """
    """项目/经历项的字段映射"""
    item_field_mapping = {
        '公司': 'company',
        '职位': 'position',
        '时间': 'duration',
        '地点': 'location',
        '项目名称': 'name',
        '角色': 'role',
        '技术栈': 'stack',
        '亮点': 'highlights',
        '描述': 'description',
        '职责': 'achievements',
        '成就': 'achievements',
    }
    
    normalized_item = {}
    for k, v in item.items():
        english_key = item_field_mapping.get(k, field_mapping.get(k, k))
        """递归处理嵌套结构"""
        if isinstance(v, dict):
            normalized_item[english_key] = normalize_item(v, field_mapping)
        elif isinstance(v, list):
            normalized_item[english_key] = [
                normalize_item(sub, field_mapping) if isinstance(sub, dict) else sub 
                for sub in v
            ]
        else:
            normalized_item[english_key] = v
    
    return normalized_item


# ──────────────────────────────────────────────────────────────────────────────
# Windows 兼容：xelatex 路径解析
# MiKTeX 在 Windows 上常装到 %LOCALAPPDATA%\Programs\MiKTeX，但后台进程的
# PATH 里往往不包含这个目录，导致 shutil.which('xelatex') 返回 None。
# resolve_xelatex_executable() 先走标准 PATH，找不到再查 Windows 常见安装路径。
# ──────────────────────────────────────────────────────────────────────────────

def resolve_xelatex_executable() -> Optional[str]:
    """查找 xelatex 可执行路径，支持显式配置和常见 TeX 发行版目录。"""
    # 允许桌面启动器/IDE 通过环境变量显式指定路径，避免依赖进程继承的 PATH。
    for env_var in ("XELATEX_PATH", "LATEX_XELATEX_PATH"):
        configured = os.environ.get(env_var, "").strip().strip('"')
        if not configured:
            continue
        configured_path = Path(configured).expanduser()
        if configured_path.is_file():
            return str(configured_path.resolve())
        configured_from_path = shutil.which(configured)
        if configured_from_path:
            return configured_from_path

    # 优先走系统 PATH（与原有逻辑相同）
    found = shutil.which("xelatex") or shutil.which("xelatex.exe")
    if found:
        return found

    if os.name != "nt":
        # macOS：枚举常见 TeX 安装位置（BasicTeX / MacTeX）
        mac_candidates = [
            Path("/Library/TeX/texbin/xelatex"),
            Path("/usr/local/texlive/bin/universal-apple/xelatex"),
            Path("/usr/local/texlive/bin/x86_64-darwin/xelatex"),
        ]
        for p in mac_candidates:
            try:
                if p.exists():
                    return str(p)  # 保留符号链接路径，TeX 依赖文件名判断运行格式
            except OSError:
                continue
        return None

    # Windows：枚举常见 MiKTeX / TeX Live 安装位置
    candidates: List[Path] = []
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    if local_appdata:
        local_root = Path(local_appdata)
        candidates.extend(
            [
                local_root / "Programs" / "MiKTeX" / "miktex" / "bin" / "x64" / "xelatex.exe",
                local_root / "MiKTeX" / "miktex" / "bin" / "x64" / "xelatex.exe",
            ]
        )
    for env_var in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432"):
        base = os.environ.get(env_var, "")
        if base:
            candidates.append(Path(base) / "MiKTeX" / "miktex" / "bin" / "x64" / "xelatex.exe")

    for root in (Path("C:/texlive"), Path("D:/texlive")):
        if root.is_dir():
            try:
                candidates.extend(root.glob("*/bin/windows/xelatex.exe"))
            except OSError:
                pass

    for p in candidates:
        try:
            if p.is_file():
                return str(p.resolve())
        except OSError:
            continue
    return None


def xelatex_install_hint() -> str:
    """返回当前操作系统可直接执行的 XeLaTeX 安装提示。"""
    if os.name == "nt":
        return (
            "\n\nWindows 未检测到 XeLaTeX。请先安装 MiKTeX：\n"
            "  winget install --id MiKTeX.MiKTeX --exact\n"
            "安装完成后重启后端；如果已安装但未加入 PATH，可设置：\n"
            "  XELATEX_PATH=C:\\\\Program Files\\\\MiKTeX\\\\miktex\\\\bin\\\\x64\\\\xelatex.exe\n"
            "也可以在 MiKTeX Console 中启用“自动安装缺失宏包”。"
        )
    if os.name == "darwin":
        return (
            "\n\nmacOS 未检测到 XeLaTeX。可安装 BasicTeX：\n"
            "  brew install --cask basictex\n"
            "安装完成后重启终端或运行：\n"
            "  eval \"$(/usr/libexec/path_helper)\""
        )
    return (
        "\n\nLinux 未检测到 XeLaTeX。可安装 TeX Live：\n"
        "  sudo apt-get update && sudo apt-get install -y texlive-xetex"
    )


def subprocess_env_with_xelatex_bin(xelatex_path: str) -> dict:
    """返回在 PATH 最前面插入 xelatex 所在目录的环境变量字典，
    确保同目录的 kpsewhich 等工具也能被子进程找到。"""
    env = os.environ.copy()
    bin_dir = str(Path(xelatex_path).resolve().parent)
    env["PATH"] = bin_dir + os.pathsep + env.get("PATH", "")
    return env
