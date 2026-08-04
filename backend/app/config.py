"""环境配置：从 .env / 环境变量读取。"""

import re
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM（OpenAI 兼容）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_mock: bool = False
    auto_repair_attempts: int = 1

    # 服务
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = BACKEND_DIR / "data"

    # 沙箱
    sandbox_timeout: float = 60.0
    sandbox_allowed_modules: tuple[str, ...] = (
        "matplotlib",
        "numpy",
        "pandas",
        "seaborn",
        "scipy",
        "statsmodels",
        "math",
        "itertools",
        "functools",
        "collections",
        "statistics",
        "datetime",
        "random",
        "plotly",
    )

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()


def public_config() -> dict:
    """返回可给前端的配置，绝不返回完整 API key。"""
    key = settings.llm_api_key
    masked = f"{key[:3]}***{key[-4:]}" if len(key) > 7 else ("***" if key else "")
    return {
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "mock": settings.llm_mock,
        "has_api_key": bool(key),
        "api_key_masked": masked,
        "auto_repair_attempts": settings.auto_repair_attempts,
        "sandbox_timeout": settings.sandbox_timeout,
    }


def update_runtime_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    mock: bool | None = None,
    auto_repair_attempts: int | None = None,
) -> dict:
    """更新当前进程，并同步到被 .gitignore 保护的本地 .env。"""
    updates: dict[str, str] = {}
    if api_key is not None:
        settings.llm_api_key = api_key
        updates["LLM_API_KEY"] = api_key
    if base_url is not None:
        settings.llm_base_url = base_url.rstrip("/")
        updates["LLM_BASE_URL"] = settings.llm_base_url
    if model is not None:
        settings.llm_model = model
        updates["LLM_MODEL"] = model
    if mock is not None:
        settings.llm_mock = mock
        updates["LLM_MOCK"] = "1" if mock else "0"
    if auto_repair_attempts is not None:
        settings.auto_repair_attempts = auto_repair_attempts
        updates["AUTO_REPAIR_ATTEMPTS"] = str(auto_repair_attempts)
    if updates:
        _persist_env(updates)
    return public_config()


def _persist_env(updates: dict[str, str]) -> None:
    env_path = BACKEND_DIR / ".env"
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = text.splitlines()
    for key, value in updates.items():
        safe_value = value.replace("\\", "\\\\").replace('"', '\\"')
        replacement = f'{key}="{safe_value}"'
        pattern = re.compile(rf"^\s*{re.escape(key)}\s*=.*$")
        for index, line in enumerate(lines):
            if pattern.match(line):
                lines[index] = replacement
                break
        else:
            lines.append(replacement)
    env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
