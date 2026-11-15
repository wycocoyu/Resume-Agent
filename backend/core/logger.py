import os
import re
import sys
from contextvars import ContextVar
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger as _base_logger

logger = _base_logger

request_id_var: ContextVar[Optional[str]] = ContextVar("request_id", default=None)
flow_id_var: ContextVar[Optional[str]] = ContextVar("flow_id", default=None)

_SENSITIVE_EXTRA_KEYS = {
    "body",
    "body_text",
    "post_body",
    "comment_body",
    "username",
    "user_name",
    "reddit_username",
    "author",
    "author_name",
}
_SENSITIVE_PATTERNS = [
    re.compile(r"(user(?:name)?|author(?:_name)?|reddit_username)=([^\s,]+)", re.IGNORECASE),
    re.compile(r"(body|body_text|comment_body)=([^,]+)"),
]
_LOG_RECORD_RESERVED_KEYS = {
    "name",
    "msg",
    "args",
    "levelname",
    "levelno",
    "pathname",
    "filename",
    "module",
    "exc_info",
    "exc_text",
    "stack_info",
    "lineno",
    "funcName",
    "created",
    "msecs",
    "relativeCreated",
    "thread",
    "threadName",
    "processName",
    "process",
}

_logging_config: Optional["LoggingConfig"] = None
_log_dir: Optional[Path] = None


class _DeferredLogger:
    """Resolve the configured logger lazily after import-time bootstrap."""

    def __init__(self, name: Optional[str]) -> None:
        self._name = name

    def _target(self):
        active = logger if _logging_config is not None else _base_logger
        return active.bind(name=self._name) if self._name else active

    def __getattr__(self, attribute: str):
        return getattr(self._target(), attribute)


def _sanitize_text_payload(message: str) -> str:
    sanitized = message
    for pattern in _SENSITIVE_PATTERNS:
        sanitized = pattern.sub(lambda match: f"{match.group(1)}=[REDACTED]", sanitized)
    return sanitized


def _infer_category(name: Optional[str]) -> str:
    if not name:
        return "backend"
    lowered = name.lower()
    if "agent" in lowered:
        return "agent"
    if "latex" in lowered:
        return "latex"
    return "backend"


def _ensure_log_dirs() -> None:
    if _log_dir is None:
        return
    for category in ("backend", "agent", "latex", "other"):
        (_log_dir / category).mkdir(parents=True, exist_ok=True)


def _get_log_path(category: str, filename: Optional[str] = None) -> Path:
    if _log_dir is None:
        raise RuntimeError("Log directory not configured")
    _ensure_log_dirs()
    if filename is None:
        filename = f"{datetime.now().strftime('%Y-%m-%d')}.log"
    return _log_dir / category / filename


class LoggingConfig:
    def __init__(self, is_production: bool, log_level: str = "INFO", log_dir: Optional[str] = None):
        self.is_production = is_production
        self.log_level = log_level
        self.log_dir = Path(log_dir) if log_dir else None
        self._configured = False

    def configure(self) -> None:
        if self._configured:
            return

        global logger, _log_dir

        _base_logger.remove()
        _log_dir = self.log_dir

        def add_request_and_flow_id(record):
            record.setdefault("extra", {})
            record["extra"]["request_id"] = request_id_var.get() or "N/A"
            record["extra"]["flow_id"] = flow_id_var.get() or "N/A"

        logger_with_request = _base_logger.patch(add_request_and_flow_id)

        def scrub_sensitive_fields(record):
            record["message"] = _sanitize_text_payload(str(record.get("message", "")))
            extras = record.setdefault("extra", {})
            for key in list(extras.keys()):
                if key and key.lower() in _SENSITIVE_EXTRA_KEYS:
                    extras[key] = "[REDACTED]"

        logger = logger_with_request.patch(scrub_sensitive_fields)

        if self.is_production:
            logger.add(
                sys.stdout,
                level=self.log_level,
                serialize=True,
                enqueue=True,
            )
        else:
            # Windows 默认控制台编码常为 GBK，而 Agent 日志包含中文和 emoji。
            # 将控制台流切到 UTF-8，避免日志输出失败反过来污染请求处理。
            for stream in (sys.stdout, sys.stderr):
                reconfigure = getattr(stream, "reconfigure", None)
                if reconfigure is None:
                    continue
                try:
                    reconfigure(encoding="utf-8", errors="backslashreplace")
                except (OSError, ValueError):
                    # 测试捕获流或外部托管流可能不允许重配置，保留原流即可。
                    pass

            def safe_format(record):
                request_id = record.get("extra", {}).get("request_id", "N/A")
                flow_id = record.get("extra", {}).get("flow_id", "N/A")
                safe_function = str(record["function"]).replace("<", "\\<").replace(">", "\\>")
                safe_name = str(record["name"]).replace("<", "\\<").replace(">", "\\>")
                message = str(record["message"]).replace("{", "{{").replace("}", "}}")
                base_msg = "<green>{}</green> | <level>{:<8}</level> | <yellow>[{}|{}]</yellow> | <cyan>{}:{}</cyan>:<cyan>{}</cyan> | <level>{}</level>".format(
                    record["time"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
                    record["level"].name,
                    request_id,
                    flow_id,
                    safe_name,
                    safe_function,
                    record["line"],
                    message,
                )
                if record["exception"] is not None:
                    base_msg += "\n{exception}"
                return base_msg + "\n"

            logger.add(
                sys.stdout,
                level=self.log_level,
                colorize=False,
                format=safe_format,
                filter=lambda record: record["level"].name not in ["ERROR", "CRITICAL"],
            )
            logger.add(
                sys.stderr,
                level="ERROR",
                colorize=False,
                format=safe_format,
            )

            if _log_dir is not None:
                _ensure_log_dirs()
                for category in ("backend", "agent", "latex", "other"):
                    file_path = _get_log_path(category)
                    logger.add(
                        file_path,
                        level=self.log_level,
                        rotation="00:00",
                        retention="30 days",
                        compression="zip",
                        encoding="utf-8",
                        enqueue=True,
                        filter=lambda record, c=category: _infer_category(record.get("extra", {}).get("name")) == c,
                    )

        self._configured = True


def setup_logging(is_production: bool, log_level: str = "INFO", log_dir: Optional[str] = None) -> None:
    global _logging_config
    resolved_log_dir = log_dir or os.getenv("LOG_DIR", "logs")
    _logging_config = LoggingConfig(is_production, log_level, resolved_log_dir)
    _logging_config.configure()


def get_logger(name: Optional[str] = None):
    if _logging_config is None:
        # Import-time consumers (notably the lazy Pi Core tool registry) may
        # be loaded before the web application's logging bootstrap runs.
        # Return a proxy so modules imported before bootstrap still resolve to
        # the configured sinks and filters after ``setup_logging`` executes.
        return _DeferredLogger(name)
    return logger.bind(name=name) if name else logger


def bridge_std_logging_to_loguru(level: str = "INFO") -> None:
    import logging

    class InterceptHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            try:
                level_name = logger.level(record.levelname).name
            except ValueError:
                level_name = record.levelno

            frame = logging.currentframe()
            depth = 2
            while frame and frame.f_code.co_filename == logging.__file__:
                frame = frame.f_back
                depth += 1

            extras = {
                k: v for k, v in record.__dict__.items()
                if k not in _LOG_RECORD_RESERVED_KEYS and not k.startswith("_")
            }
            logger.bind(**extras).opt(depth=depth, exception=record.exc_info).log(level_name, record.getMessage())

    if any(isinstance(h, InterceptHandler) for h in logging.getLogger().handlers):
        return

    logging.basicConfig(handlers=[InterceptHandler()], level=level, force=True)


def write_debug_log(category: str, content: str, filename: Optional[str] = None) -> None:
    if _log_dir is None:
        raise RuntimeError("Log directory not configured")
    log_path = _get_log_path(category, filename)
    with open(log_path, "a", encoding="utf-8") as handle:
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        handle.write(f"\n{'=' * 60}\n")
        handle.write(f"[{timestamp}]\n")
        handle.write(f"{'=' * 60}\n")
        handle.write(content)
        handle.write("\n")


def write_latex_debug(latex_content: str, error_msg: str = "") -> None:
    content = ""
    if error_msg:
        content += f"Error:\n{error_msg}\n\n"
    content += f"LaTeX Source:\n{latex_content}"
    write_debug_log("latex", content, f"latex_debug_{datetime.now().strftime('%Y-%m-%d')}.log")


def write_llm_debug(raw_response: str, cleaned_response: str = "") -> None:
    content = f"Raw Response:\n{raw_response}"
    if cleaned_response:
        content += f"\n\nCleaned Response:\n{cleaned_response}"
    write_debug_log("backend", content, f"llm_debug_{datetime.now().strftime('%Y-%m-%d')}.log")

