"""环境配置：从 .env / 环境变量读取。"""

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
