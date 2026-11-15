"""
LaTeX 直接编译模块
使用 slager 原版样式编译用户上传的 LaTeX 文件
"""
import subprocess
import tempfile
import shutil
from pathlib import Path
from typing import Optional
from io import BytesIO

try:
    from .latex_utils import (
        resolve_xelatex_executable,
        subprocess_env_with_xelatex_bin,
        xelatex_install_hint,
    )
except ImportError:
    from latex_utils import (
        resolve_xelatex_executable,
        subprocess_env_with_xelatex_bin,
        xelatex_install_hint,
    )


def compile_latex_raw(latex_content: str) -> BytesIO:
    """
    直接编译 LaTeX 内容为 PDF
    使用 slager 原版样式（与 slager.link 完全一致）
    
    参数:
        latex_content: LaTeX 源代码字符串
    
    返回:
        PDF 文件的 BytesIO 对象
    """
    # 获取 slager 原版模板目录
    current_dir = Path(__file__).resolve().parent
    root_dir = current_dir.parent
    template_dir = root_dir / "latex-resume-template"
    
    if not template_dir.exists():
        raise RuntimeError("latex-resume-template 模板目录不存在")
    
    if not template_dir.exists():
        raise RuntimeError(f"LaTeX 模板目录不存在: {template_dir}")
    
    # 创建临时目录
    temp_dir = tempfile.mkdtemp()
    
    try:
        # 复制所有模板文件
        template_files = [
            'resume.cls', 'fontawesome.sty', 'linespacing_fix.sty',
            'zh_CN-Adobefonts_external.sty', 'zh_CN-Adobefonts_internal.sty'
        ]
        for file_name in template_files:
            src_file = template_dir / file_name
            if src_file.exists():
                dest_file = Path(temp_dir) / file_name
                shutil.copy2(src_file, dest_file)
        
        # 复制字体目录
        fonts_dir = template_dir / 'fonts'
        if fonts_dir.exists():
            shutil.copytree(fonts_dir, Path(temp_dir) / 'fonts', dirs_exist_ok=True)
        
        # 写入 LaTeX 文件
        tex_file = Path(temp_dir) / 'resume.tex'
        tex_file.write_text(latex_content, encoding='utf-8')
        
        # 检查 xelatex 是否可用（Windows 下额外搜索 MiKTeX 常见路径）
        xelatex_path = resolve_xelatex_executable()
        if not xelatex_path:
            raise RuntimeError(f"xelatex 命令未找到。{xelatex_install_hint()}")
        
        # 使用 xelatex 编译
        compile_cmd = [
            xelatex_path,
            '-interaction=nonstopmode',
            '-output-directory', temp_dir,
            str(tex_file)
        ]
        
        _latex_env = subprocess_env_with_xelatex_bin(xelatex_path)
        result = subprocess.run(
            compile_cmd,
            cwd=temp_dir,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
            env=_latex_env,
        )
        
        if result.returncode != 0:
            # 提取有用的错误信息
            error_lines = []
            compiler_output = result.stdout or result.stderr or ""
            for line in compiler_output.split('\n'):
                if '!' in line or 'Error' in line or 'error' in line or 'Undefined' in line:
                    error_lines.append(line)
            # 如果找到关键错误行，使用它们；否则使用最后500字符
            if error_lines:
                error_msg = '\n'.join(error_lines[:20])  # 最多20行关键错误
            else:
                error_msg = compiler_output[-1000:] if len(compiler_output) > 1000 else compiler_output
            print(f"[LaTeX 编译] 错误: {error_msg}")
            raise RuntimeError(f"LaTeX 编译失败: {error_msg}")
        
        # 读取生成的 PDF
        pdf_file = Path(temp_dir) / 'resume.pdf'
        if not pdf_file.exists():
            raise RuntimeError("PDF 文件未生成")
        
        pdf_bytes = pdf_file.read_bytes()
        print(f"[LaTeX 编译] 成功，PDF 大小: {len(pdf_bytes)} 字节")
        
        pdf_io = BytesIO(pdf_bytes)
        pdf_io.seek(0)
        return pdf_io
        
    finally:
        # 清理临时目录
        shutil.rmtree(temp_dir, ignore_errors=True)

