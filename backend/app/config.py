"""环境配置：从 .env / 环境变量读取。"""

import re
import os
import ipaddress
import socket
import subprocess
import tempfile
import threading
from pathlib import Path
from urllib.parse import urlparse

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
CONFIG_DIR = Path(os.environ.get("QUICK_SCIPLOT_CONFIG_DIR", str(BACKEND_DIR)))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=CONFIG_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM（OpenAI 兼容）
    llm_api_key: str = ""
    llm_base_url: str = "https://api.deepseek.com/v1"
    llm_model: str = "deepseek-chat"
    llm_max_tokens: int = 8192
    llm_mock: bool = False
    llm_send_data_values: bool = False
    auto_repair_attempts: int = 1
    # Docker is the only production-safe execution boundary.  The local
    # subprocess mode is retained for explicitly trusted development setups.
    sandbox_mode: str = "docker"
    docker_image: str = "quick-sciplot-sandbox:0.2.0"

    # 服务
    host: str = "127.0.0.1"
    port: int = 8000
    data_dir: Path = BACKEND_DIR / "data"
    max_import_bytes: int = 200 * 1024 * 1024
    max_total_import_bytes: int = 500 * 1024 * 1024
    max_json_bytes: int = 64 * 1024 * 1024
    max_json_nesting: int = 64
    max_archive_members: int = 4096
    max_archive_expanded_bytes: int = 512 * 1024 * 1024
    max_excel_sheets: int = 50
    max_parse_concurrency: int = 2
    max_plot_concurrency: int = 2
    max_output_bytes: int = 1 * 1024 * 1024 * 1024
    max_revisions_per_dataset: int = 50

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

    # 安全与鉴权
    require_auth: bool = True
    # Host 请求头白名单：服务只监听回环地址，但 /api/config 会向任何回环请求下发
    # 会话 cookie，因此必须拒绝 DNS 重绑定页面（Host 为攻击者域名）发来的请求。
    allowed_hosts: tuple[str, ...] = ("localhost", "127.0.0.1", "::1")
    allow_local_network_llm: bool = False
    allow_unsafe_process_sandbox: bool = False

    @field_validator("data_dir")
    @classmethod
    def _anchor_relative_data_dir(cls, value: Path) -> Path:
        """Resolve a relative DATA_DIR against backend/ as documented in .env.example.

        Otherwise it depends on the process working directory, so starting the
        server from the repository root silently created a second ./data.
        """
        value = Path(value)
        return value if value.is_absolute() else BACKEND_DIR / value

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()


def _is_blocked_address(address: ipaddress._BaseAddress, allow_local_network: bool) -> bool:
    """Return whether an IP is unsafe for an outbound LLM connection."""
    # Cloud metadata endpoints remain blocked even when a user enables local
    # network access.  That switch is for trusted on-prem LLMs, not metadata.
    metadata_networks = (
        ipaddress.ip_network("169.254.169.254/32"),
        ipaddress.ip_network("169.254.170.2/32"),
        ipaddress.ip_network("fd00:ec2::254/128"),
    )
    if any(address in network for network in metadata_networks):
        return True
    if address.is_unspecified or address.is_multicast or address.is_reserved:
        return True
    if not allow_local_network and (address.is_loopback or address.is_private or address.is_link_local):
        return True
    return False


def validate_safe_llm_url(url: str, allow_local_network: bool = False) -> None:
    """Validate an LLM URL, including every address returned by DNS.

    This is intentionally a conservative preflight check.  Redirects are also
    disabled at the HTTP client, so the configured endpoint cannot silently
    redirect a request into a private network.
    """
    if not isinstance(url, str) or not url.strip():
        raise ValueError("LLM Base URL 不能为空")
    parsed = urlparse(url.strip())
    if parsed.scheme not in {"http", "https"}:
        raise ValueError("LLM Base URL 必须以 http:// 或 https:// 开头")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("LLM Base URL 不允许包含用户名或密码")
    if parsed.fragment:
        raise ValueError("LLM Base URL 不允许包含 URL fragment")

    hostname = parsed.hostname
    if not hostname or any(char.isspace() for char in hostname) or "%" in hostname:
        raise ValueError("无效的主机名")
    hostname = hostname.rstrip(".").lower()
    if not hostname:
        raise ValueError("无效的主机名")

    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError("LLM Base URL 端口无效") from exc
    if port is None:
        port = 443 if parsed.scheme == "https" else 80
    dangerous_hostnames = {
        "169.254.169.254",
        "169.254.170.2",
        "metadata.google.internal",
        "instance-data",
        "localhost",
        "localhost.localdomain",
        "0.0.0.0",
        "::",
    }
    if hostname in dangerous_hostnames:
        raise ValueError(f"禁止访问元数据服务或不安全主机: {hostname}")

    addresses: list[ipaddress._BaseAddress] = []
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        # Numeric-but-non-canonical host forms (decimal, octal-like, or mixed
        # dotted values) have historically been interpreted inconsistently by
        # URL parsers and DNS libraries.  Reject them rather than normalizing.
        if re.fullmatch(r"[0-9.]+", hostname):
            raise ValueError(f"不接受非标准数字主机名: {hostname}")
        try:
            idna_hostname = hostname.encode("idna").decode("ascii")
            infos = socket.getaddrinfo(idna_hostname, port, type=socket.SOCK_STREAM)
        except (UnicodeError, socket.gaierror, OSError) as exc:
            raise ValueError(f"无法解析 LLM 主机名: {hostname}") from exc
        for info in infos:
            sockaddr = info[4]
            if sockaddr:
                try:
                    addresses.append(ipaddress.ip_address(sockaddr[0]))
                except ValueError as exc:
                    raise ValueError(f"DNS 返回了无效地址: {sockaddr[0]}") from exc
    else:
        addresses.append(literal)

    if not addresses:
        raise ValueError(f"LLM 主机名没有可用地址: {hostname}")
    for address in addresses:
        if _is_blocked_address(address, allow_local_network):
            raise ValueError(f"禁止访问私有、回环、链路本地或保留地址: {address}")
    if port not in {80, 443} and not allow_local_network:
        raise ValueError("LLM Base URL 只允许使用 80 或 443 端口")


def validate_local_bind_host(host: str) -> None:
    """Only allow the single-user service to bind to a loopback address."""
    normalized = str(host or "").strip().lower()
    if normalized.startswith("[") and normalized.endswith("]"):
        normalized = normalized[1:-1]
    normalized = normalized.rstrip(".")
    if normalized == "localhost":
        return
    try:
        address = ipaddress.ip_address(normalized)
    except ValueError as exc:
        raise ValueError("单用户服务必须绑定回环地址（127.0.0.1、::1 或 localhost）") from exc
    if not address.is_loopback:
        raise ValueError("单用户服务必须绑定回环地址（127.0.0.1、::1 或 localhost）")


def validate_initial_settings() -> None:
    """Fail closed for non-local service bindings or unsafe LLM endpoints."""
    validate_local_bind_host(settings.host)
    if not settings.llm_api_key:
        return
    try:
        validate_safe_llm_url(
            settings.llm_base_url,
            allow_local_network=settings.allow_local_network_llm,
        )
    except ValueError as exc:
        raise RuntimeError(f"LLM_BASE_URL 配置不安全: {exc}") from exc


validate_initial_settings()


def _get_or_create_session_token() -> str:
    env_token = os.environ.get("QUICK_SCIPLOT_SESSION_TOKEN")
    if env_token:
        return env_token.strip()
    token_file = CONFIG_DIR / ".session_token"
    if token_file.exists():
        try:
            saved = token_file.read_text(encoding="utf-8").strip()
            if saved:
                _harden_private_file_permissions(token_file)
                return saved
        except Exception:
            pass
    new_token = os.urandom(16).hex()
    try:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        token_file.write_text(new_token, encoding="utf-8")
        _harden_private_file_permissions(token_file)
    except Exception:
        pass
    return new_token


def _harden_private_file_permissions(token_file: Path) -> None:
    """Restrict a local secret-bearing file to the current user where possible."""
    os.chmod(token_file, 0o600)
    if os.name != "nt":
        return

    # chmod does not enforce ACLs on Windows. Remove inherited entries and
    # grant full access only to the account running this local service.
    try:
        username = subprocess.check_output(
            ["whoami"], text=True, stderr=subprocess.DEVNULL, timeout=5
        ).strip()
        if username:
            subprocess.run(
                ["icacls", str(token_file), "/inheritance:r", "/grant:r", f"{username}:F"],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
            )
    except (OSError, subprocess.SubprocessError):
        # Keep token creation available on minimal Windows images.
        pass


SESSION_TOKEN: str = _get_or_create_session_token()


def rotate_session_token() -> str:
    """Atomically replace the local session token and return the new value."""
    global SESSION_TOKEN
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    target = CONFIG_DIR / ".session_token"
    temporary_path: Path | None = None
    new_token = os.urandom(16).hex()
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".session_token-",
            suffix=".tmp",
            dir=CONFIG_DIR,
            delete=False,
        ) as handle:
            temporary_path = Path(handle.name)
            handle.write(new_token)
            handle.flush()
            os.fsync(handle.fileno())
        _harden_private_file_permissions(temporary_path)
        os.replace(temporary_path, target)
        _harden_private_file_permissions(target)
        SESSION_TOKEN = new_token
        return new_token
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def public_config() -> dict:
    """返回可给前端的配置，绝不返回 API key 或 session token。"""
    key = settings.llm_api_key
    masked = f"{key[:3]}***{key[-4:]}" if len(key) > 7 else ("***" if key else "")
    res = {
        "base_url": settings.llm_base_url,
        "model": settings.llm_model,
        "mock": settings.llm_mock,
        "has_api_key": bool(key),
        "api_key_masked": masked,
        "auto_repair_attempts": settings.auto_repair_attempts,
        "sandbox_timeout": settings.sandbox_timeout,
        "sandbox_mode": settings.sandbox_mode,
        "send_data_values": settings.llm_send_data_values,
        "auth_enabled": settings.require_auth,
    }
    return res


def update_runtime_config(
    *,
    api_key: str | None = None,
    base_url: str | None = None,
    model: str | None = None,
    mock: bool | None = None,
    auto_repair_attempts: int | None = None,
    sandbox_mode: str | None = None,
    send_data_values: bool | None = None,
) -> dict:
    """更新当前进程，并同步到被 .gitignore 保护的本地 .env。"""
    _validate_runtime_config_updates(
        api_key=api_key,
        base_url=base_url,
        model=model,
        auto_repair_attempts=auto_repair_attempts,
        sandbox_mode=sandbox_mode,
    )
    updates: dict[str, str] = {}
    settings_updates: dict[str, object] = {}
    if api_key is not None:
        updates["LLM_API_KEY"] = api_key
        settings_updates["llm_api_key"] = api_key
    if base_url is not None:
        normalized_base_url = base_url.rstrip("/")
        updates["LLM_BASE_URL"] = normalized_base_url
        settings_updates["llm_base_url"] = normalized_base_url
    if model is not None:
        updates["LLM_MODEL"] = model
        settings_updates["llm_model"] = model
    if mock is not None:
        updates["LLM_MOCK"] = "1" if mock else "0"
        settings_updates["llm_mock"] = mock
    if auto_repair_attempts is not None:
        updates["AUTO_REPAIR_ATTEMPTS"] = str(auto_repair_attempts)
        settings_updates["auto_repair_attempts"] = auto_repair_attempts
    if sandbox_mode is not None:
        updates["SANDBOX_MODE"] = sandbox_mode
        settings_updates["sandbox_mode"] = sandbox_mode
    if send_data_values is not None:
        updates["LLM_SEND_DATA_VALUES"] = "1" if send_data_values else "0"
        settings_updates["llm_send_data_values"] = send_data_values
    if updates:
        _persist_env(updates)
        for key, value in settings_updates.items():
            setattr(settings, key, value)
    return public_config()


def _validate_runtime_config_updates(
    *,
    api_key: str | None,
    base_url: str | None,
    model: str | None,
    auto_repair_attempts: int | None,
    sandbox_mode: str | None,
) -> None:
    for value in (api_key, base_url, model):
        if value is not None and any(char in value for char in "\r\n"):
            raise ValueError("配置值不能包含换行符")
    if base_url is not None:
        validate_safe_llm_url(
            base_url,
            allow_local_network=settings.allow_local_network_llm,
        )
    if model is not None and not model.strip():
        raise ValueError("模型名称不能为空")
    if auto_repair_attempts is not None and not 0 <= auto_repair_attempts <= 3:
        raise ValueError("自动修复次数必须在 0 到 3 之间")
    if sandbox_mode is not None and sandbox_mode not in {"process", "docker"}:
        raise ValueError("沙箱模式只能是 process 或 docker")
    if sandbox_mode == "process" and not settings.allow_unsafe_process_sandbox:
        raise ValueError("process 沙箱仅允许在显式设置 ALLOW_UNSAFE_PROCESS_SANDBOX=1 时启用")


_ENV_WRITE_LOCK = threading.Lock()


def _persist_env(updates: dict[str, str]) -> None:
    with _ENV_WRITE_LOCK:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        env_path = CONFIG_DIR / ".env"
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

        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=".env-",
                suffix=".tmp",
                dir=CONFIG_DIR,
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                handle.write("\n".join(lines) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            _harden_private_file_permissions(temporary_path)
            os.replace(temporary_path, env_path)
            _harden_private_file_permissions(env_path)
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
