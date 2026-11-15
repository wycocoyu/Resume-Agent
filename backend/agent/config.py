import json
import os
import re
import threading
from contextlib import contextmanager
try:
    import tomllib  # Python 3.11+
except ImportError:
    import tomli as tomllib  # Python < 3.11
from pathlib import Path
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field

# 加载 .env 文件（优先根目录 .env，否则 agent-backend 目录）
try:
    from dotenv import load_dotenv
    _cfg_dir = Path(__file__).resolve().parent.parent.parent  # agent-backend
    _env_path = _cfg_dir.parent.parent / ".env"  # 仓库根目录 .env
    if not _env_path.exists():
        _env_path = _cfg_dir / ".env"
    if _env_path.exists():
        load_dotenv(dotenv_path=str(_env_path), override=True)
except ImportError:
    pass  # dotenv 未安装则跳过


def get_project_root() -> Path:
    """Get the project root directory"""
    return Path(__file__).resolve().parent.parent.parent


def _expand_env_vars(value: Any) -> Any:
    """递归替换配置中的环境变量占位符 ${VAR_NAME}"""
    if isinstance(value, str):
        # 匹配 ${VAR_NAME} 格式
        pattern = r'\$\{([^}]+)\}'
        def replacer(match):
            var_name = match.group(1)
            return os.environ.get(var_name, match.group(0))
        return re.sub(pattern, replacer, value)
    elif isinstance(value, dict):
        return {k: _expand_env_vars(v) for k, v in value.items()}
    elif isinstance(value, list):
        return [_expand_env_vars(item) for item in value]
    return value


PROJECT_ROOT = get_project_root()
WORKSPACE_ROOT = PROJECT_ROOT / "docs"


class LLMSettings(BaseModel):
    model: str = Field(..., description="Model name")
    base_url: str = Field(..., description="API base URL")
    api_key: str = Field(..., description="API key")
    max_tokens: int = Field(4096, description="Maximum number of tokens per request")
    max_input_tokens: Optional[int] = Field(
        None,
        description="Maximum input tokens to use across all requests (None for unlimited)",
    )
    temperature: float = Field(0.3, description="Sampling temperature")
    api_type: str = Field(..., description="Azure, Openai, or Ollama")
    api_version: str = Field(..., description="Azure Openai version if AzureOpenai")
    extra_body: Optional[dict] = Field(
        None,
        description="Extra JSON body merged into every chat request (e.g. DashScope enable_thinking)",
    )


class ProxyConfig(BaseModel):
    """Global proxy configuration."""
    enabled: bool = Field(False, description="Whether to enable proxy")
    http_proxy: Optional[str] = Field(None, description="HTTP proxy URL")
    https_proxy: Optional[str] = Field(None, description="HTTPS proxy URL")
    no_proxy: Optional[str] = Field(None, description="No-proxy list")

    def apply(self) -> None:
        if not self.enabled:
            return
        if self.http_proxy:
            os.environ["HTTP_PROXY"] = self.http_proxy
        if self.https_proxy:
            os.environ["HTTPS_PROXY"] = self.https_proxy
        if self.no_proxy:
            os.environ["NO_PROXY"] = self.no_proxy


class NetworkConfig(BaseModel):
    """Network configuration (proxy, SSL, etc.) for agent operations.
    
    Provides structured configuration for network-related operations,
    including proxy settings and operation-specific overrides (e.g., tiktoken downloads).
    """
    use_proxy: bool = Field(False, description="Whether to enable proxy globally")
    http_proxy: Optional[str] = Field(None, description="HTTP proxy URL")
    https_proxy: Optional[str] = Field(None, description="HTTPS proxy URL")
    no_proxy: Optional[str] = Field(None, description="No-proxy list (comma-separated)")
    
    # Operation-specific proxy configuration
    disable_proxy_for_tiktoken: bool = Field(
        True,
        description="Disable proxy for tiktoken downloads (default: True, to avoid proxy connection failures)"
    )
    
    # Agent initialization retry configuration
    agent_init_max_retries: int = Field(3, description="Maximum retry attempts for agent initialization")
    agent_init_retry_delay: float = Field(0.3, description="Base delay for retry (seconds)")
    agent_init_retry_backoff: float = Field(1.5, description="Exponential backoff multiplier for retries")
    
    def apply(self) -> None:
        """Apply proxy configuration to environment variables."""
        if not self.use_proxy:
            return
        
        if self.http_proxy:
            os.environ["HTTP_PROXY"] = self.http_proxy
        if self.https_proxy:
            os.environ["HTTPS_PROXY"] = self.https_proxy
        if self.no_proxy:
            os.environ["NO_PROXY"] = self.no_proxy
    
    @contextmanager
    def without_proxy(self):
        """Context manager to temporarily disable proxy for operations that need direct connection.
        
        Useful for tiktoken downloads when proxy is unavailable or causes connection failures.
        """
        if not self.disable_proxy_for_tiktoken:
            yield
            return
        
        original = {}
        proxy_keys = ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy")
        for key in proxy_keys:
            original[key] = os.environ.pop(key, None)
        
        try:
            yield
        finally:
            for key, value in original.items():
                if value is not None:
                    os.environ[key] = value


class SearchSettings(BaseModel):
    engine: str = Field(default="Google", description="Search engine the llm to use")
    fallback_engines: List[str] = Field(
        default_factory=lambda: ["DuckDuckGo", "Baidu", "Bing"],
        description="Fallback search engines to try if the primary engine fails",
    )
    retry_delay: int = Field(
        default=60,
        description="Seconds to wait before retrying all engines again after they all fail",
    )
    max_retries: int = Field(
        default=3,
        description="Maximum number of times to retry all engines when all fail",
    )
    lang: str = Field(
        default="en",
        description="Language code for search results (e.g., en, zh, fr)",
    )
    country: str = Field(
        default="us",
        description="Country code for search results (e.g., us, cn, uk)",
    )


class RunflowSettings(BaseModel):
    use_data_analysis_agent: bool = Field(
        default=False, description="Enable data analysis agent in run flow"
    )


class AppConfig(BaseModel):
    llm: Dict[str, LLMSettings]
    proxy_config: Optional[ProxyConfig] = Field(
        None, description="Global proxy configuration (deprecated, use network instead)"
    )
    network: Optional[NetworkConfig] = Field(
        None, description="Network configuration (proxy, agent init retries, etc.)"
    )
    search_config: Optional[SearchSettings] = Field(
        None, description="Search configuration"
    )
    run_flow_config: Optional[RunflowSettings] = Field(
        None, description="Run flow configuration"
    )
    enable_session_persistence: bool = Field(
        default=False, description="Enable session state persistence"
    )

    class Config:
        arbitrary_types_allowed = True


class Config:
    _instance = None
    _lock = threading.Lock()
    _initialized = False

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if not self._initialized:
            with self._lock:
                if not self._initialized:
                    self._config = None
                    self._load_initial_config()
                    self._initialized = True

    @staticmethod
    def _get_config_path() -> Path:
        root = PROJECT_ROOT
        config_path = root / "config.toml"
        if config_path.exists():
            return config_path
        raise FileNotFoundError("No config.toml found in project root")

    def _load_config(self) -> dict:
        config_path = self._get_config_path()
        with config_path.open("rb") as f:
            raw_config = tomllib.load(f)
        # 展开环境变量 ${VAR_NAME}
        return _expand_env_vars(raw_config)

    def _load_initial_config(self):
        raw_config = self._load_config()
        base_llm = raw_config.get("llm", {})
        llm_overrides = {
            k: v for k, v in raw_config.get("llm", {}).items() if isinstance(v, dict)
        }

        default_settings = {
            "model": base_llm.get("model"),
            "base_url": base_llm.get("base_url"),
            "api_key": base_llm.get("api_key"),
            "max_tokens": base_llm.get("max_tokens", 4096),
            "max_input_tokens": base_llm.get("max_input_tokens"),
            "temperature": base_llm.get("temperature", 0.3),
            "api_type": base_llm.get("api_type", ""),
            "api_version": base_llm.get("api_version", ""),
            "extra_body": base_llm.get("extra_body"),
        }

        # handle global proxy config (deprecated, kept for backward compatibility)
        proxy_config = raw_config.get("proxy", {})
        proxy_settings = None
        if proxy_config:
            proxy_settings = ProxyConfig(
                **{
                    k: v
                    for k, v in proxy_config.items()
                    if k in ["enabled", "http_proxy", "https_proxy", "no_proxy"]
                    and v is not None
                }
            )
            proxy_settings.apply()

        # handle network config (new, preferred way)
        network_config_data = raw_config.get("network", {})
        network_settings = None
        if network_config_data:
            network_settings = NetworkConfig(**network_config_data)
            # Apply proxy configuration to environment variables
            network_settings.apply()
        else:
            # Default configuration: disable proxy for tiktoken downloads
            network_settings = NetworkConfig(disable_proxy_for_tiktoken=True)

        search_config = raw_config.get("search", {})
        search_settings = None
        if search_config:
            search_settings = SearchSettings(**search_config)
        run_flow_config = raw_config.get("runflow")
        if run_flow_config:
            run_flow_settings = RunflowSettings(**run_flow_config)
        else:
            run_flow_settings = RunflowSettings()
        config_dict = {
            "llm": {
                "default": default_settings,
                **{
                    name: {**default_settings, **override_config}
                    for name, override_config in llm_overrides.items()
                },
            },
            "proxy_config": proxy_settings,
            "network": network_settings,
            "search_config": search_settings,
            "run_flow_config": run_flow_settings,
            "enable_session_persistence": bool(
                raw_config.get("context", {}).get("enable_session_persistence", False)
            ),
        }

        self._config = AppConfig(**config_dict)

    @property
    def llm(self) -> Dict[str, LLMSettings]:
        return self._config.llm

    @property
    def search_config(self) -> Optional[SearchSettings]:
        return self._config.search_config

    @property
    def run_flow_config(self) -> RunflowSettings:
        """Get the Run Flow configuration"""
        return self._config.run_flow_config

    @property
    def enable_session_persistence(self) -> bool:
        return bool(self._config.enable_session_persistence)

    @property
    def network(self) -> Optional[NetworkConfig]:
        """Get the network configuration"""
        return self._config.network

    @property
    def workspace_root(self) -> Path:
        """Get the workspace root directory"""
        return WORKSPACE_ROOT

    @property
    def root_path(self) -> Path:
        """Get the root path of the application"""
        return PROJECT_ROOT

    @property
    def log_level(self) -> str:
        """Get log level."""
        return os.getenv("LOG_LEVEL", "INFO")

    @property
    def log_mode(self) -> str:
        """Get log mode."""
        return os.getenv("LOG_MODE", "development")

    @property
    def log_dir(self) -> str:
        """Get log directory."""
        return os.getenv("LOG_DIR", "logs")


config = Config()
