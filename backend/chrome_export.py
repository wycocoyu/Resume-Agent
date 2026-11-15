"""Headless Chrome CDP / CLI PDF export engine.

Provides multi-platform Chrome auto-discovery and headless A4 PDF generation.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path




def find_chrome_executable() -> Path | None:
    """Discover Google Chrome or Chromium executable across macOS, Linux, and Windows."""
    # 1. Environment variable override
    for env_var in ("CHROME_BIN", "CHROME_PATH", "GOOGLE_CHROME_BIN"):
        val = os.environ.get(env_var)
        if val is not None:
            if not val.strip() or val.strip().lower() in ("0", "none", "false", "disabled"):
                return None
            p = Path(val).expanduser()
            if p.is_file() and os.access(p, os.X_OK):
                return p
            return None

    # 2. Standard macOS paths
    mac_paths = [
        Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"),
        Path("/Applications/Chromium.app/Contents/MacOS/Chromium"),
        Path.home() / "Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge"),
    ]
    for p in mac_paths:
        if p.is_file() and os.access(p, os.X_OK):
            return p

    # 3. Standard Linux / PATH executables
    linux_binaries = ["google-chrome", "google-chrome-stable", "chromium", "chromium-browser", "microsoft-edge"]
    for bin_name in linux_binaries:
        which = shutil.which(bin_name)
        if which:
            p = Path(which)
            if p.is_file() and os.access(p, os.X_OK):
                return p

    linux_static_paths = [
        Path("/usr/bin/google-chrome"),
        Path("/usr/bin/google-chrome-stable"),
        Path("/usr/bin/chromium"),
        Path("/usr/bin/chromium-browser"),
        Path("/snap/bin/chromium"),
    ]
    for p in linux_static_paths:
        if p.is_file() and os.access(p, os.X_OK):
            return p

    # 4. Standard Windows paths
    for base_env in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
        base_dir = os.environ.get(base_env)
        if base_dir:
            for rel in (
                "Google/Chrome/Application/chrome.exe",
                "Chromium/Application/chrome.exe",
                "Microsoft/Edge/Application/msedge.exe",
            ):
                p = Path(base_dir) / rel
                if p.is_file() and os.access(p, os.X_OK):
                    return p

    which_win = shutil.which("chrome.exe") or shutil.which("msedge.exe")
    if which_win:
        p = Path(which_win)
        if p.is_file() and os.access(p, os.X_OK):
            return p

    return None


def export_html_to_pdf(
    html_content: str,
    output_path: Path,
    print_background: bool = True,
    timeout: float = 30.0,
) -> bytes:
    """Export self-contained HTML content to an A4 PDF using headless Chrome.

    Raises:
        CLIError: with code 'chrome_not_found' when Chrome binary is missing.
        CLIError: with code 'chrome_timeout' or 'chrome_export_failed' on subprocess failure.
    """
    from backend.cli.errors import CLIError

    chrome_bin = find_chrome_executable()
    if chrome_bin is None:
        raise CLIError(
            "Google Chrome or Chromium executable is required for HTML CDP PDF export but was not found on your system. "
            "Please install Google Chrome or set the CHROME_BIN environment variable.",
            code="chrome_not_found",
            extra={"command": "render", "output": str(output_path)},
        )

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_dir_path = Path(temp_dir)
        temp_html = temp_dir_path / "resume.html"
        temp_pdf = temp_dir_path / "resume.pdf"

        temp_html.write_text(html_content, encoding="utf-8")

        cmd = [
            str(chrome_bin),
            "--headless=new",
            "--disable-gpu",
            "--no-pdf-header-footer",
            "--no-sandbox",
            "--disable-dev-shm-usage",
            f"--print-to-pdf={temp_pdf}",
            str(temp_html),
        ]

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise CLIError(
                f"Headless Chrome PDF export timed out after {timeout} seconds",
                code="chrome_timeout",
                extra={"command": "render", "output": str(output_path)},
            ) from exc

        if not temp_pdf.is_file() or temp_pdf.stat().st_size == 0:
            err_msg = res.stderr.decode("utf-8", errors="replace").strip() or "No output PDF generated"
            raise CLIError(
                f"Headless Chrome failed to generate PDF: {err_msg}",
                code="chrome_export_failed",
                extra={"command": "render", "output": str(output_path), "exit_code": res.returncode},
            )

        pdf_bytes = temp_pdf.read_bytes()
        if not pdf_bytes.startswith(b"%PDF-"):
            raise CLIError(
                "Headless Chrome generated an invalid PDF document (corrupt header).",
                code="chrome_export_failed",
                extra={"command": "render", "output": str(output_path)},
            )

        # Write to destination atomically
        output_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_dst = output_path.with_name(f".{output_path.name}.tmp")
        tmp_dst.write_bytes(pdf_bytes)
        tmp_dst.replace(output_path)

        return pdf_bytes
