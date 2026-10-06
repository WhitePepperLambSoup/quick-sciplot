"""Runtime environment status and first-run sandbox setup."""

import collections
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path

from . import config as app_config
from . import llm, sandbox
from .config import settings

_NO_WINDOW = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
SANDBOX_BUILD_FILES = ("Dockerfile.sandbox", "requirements-sandbox.lock.txt")


class SetupError(ValueError):
    """A sandbox setup request that is not allowed or not possible."""


def _docker(binary: str, *args: str, timeout: float = 15) -> subprocess.CompletedProcess:
    return subprocess.run(
        [binary, *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
        creationflags=_NO_WINDOW,
        check=False,
    )


def docker_status() -> dict:
    binary = sandbox._find_docker()
    status = {
        "installed": binary is not None,
        "daemon_running": False,
        "image_present": False,
        "image": settings.docker_image,
    }
    if binary is None:
        return status
    try:
        info = _docker(binary, "info", "--format", "{{.ServerVersion}}")
        status["daemon_running"] = info.returncode == 0 and bool(info.stdout.strip())
        if status["daemon_running"]:
            image = _docker(binary, "image", "inspect", settings.docker_image, "--format", "{{.Id}}")
            status["image_present"] = image.returncode == 0
    except (OSError, subprocess.SubprocessError):
        pass
    return status


def build_files_dir() -> Path | None:
    """Directory holding the sandbox Dockerfile and its lock file (bundled with the sidecar)."""
    root = app_config.BACKEND_DIR
    if all((root / name).is_file() for name in SANDBOX_BUILD_FILES):
        return root
    return None


class ImageBuildJob:
    """Build the Docker sandbox image in the background and keep a log tail."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._state = "idle"
        self._error = ""
        self._log: collections.deque[str] = collections.deque(maxlen=400)

    def snapshot(self) -> dict:
        with self._lock:
            return {"state": self._state, "error": self._error, "log": list(self._log)[-60:]}

    def start(self) -> bool:
        with self._lock:
            if self._state == "running":
                return False
            self._state = "running"
            self._error = ""
            self._log.clear()
        threading.Thread(target=self._run, name="sandbox-image-build", daemon=True).start()
        return True

    def _append(self, line: str) -> None:
        with self._lock:
            self._log.append(line[-500:])

    def _finish(self, state: str, error: str = "") -> None:
        with self._lock:
            self._state = state
            self._error = error

    def _run(self) -> None:
        binary = sandbox._find_docker()
        source = build_files_dir()
        if binary is None:
            self._finish("failed", "未找到 Docker，请先安装并启动 Docker Desktop")
            return
        if source is None:
            self._finish("failed", "找不到沙箱镜像的 Dockerfile")
            return
        try:
            # Build from a minimal context: the backend folder (or the bundled
            # sidecar folder) is large and must not be sent to the daemon.
            with tempfile.TemporaryDirectory(prefix="quick-sciplot-image-") as context:
                for name in SANDBOX_BUILD_FILES:
                    shutil.copyfile(source / name, Path(context) / name)
                command = [binary, "build", "-f", "Dockerfile.sandbox", "-t", settings.docker_image, "."]
                self._append("$ " + " ".join(command[1:]))
                process = subprocess.Popen(
                    command,
                    cwd=context,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    creationflags=_NO_WINDOW,
                )
                assert process.stdout is not None
                for line in process.stdout:
                    self._append(line.rstrip())
                returncode = process.wait()
        except (OSError, subprocess.SubprocessError) as exc:
            self._finish("failed", f"构建失败: {exc}")
            return
        if returncode == 0:
            self._finish("succeeded")
        else:
            self._finish("failed", f"docker build 退出码 {returncode}")


IMAGE_BUILD = ImageBuildJob()


def system_status() -> dict:
    docker = docker_status()
    mode = settings.sandbox_mode
    process_allowed = sandbox.process_sandbox_allowed()
    if mode == "process":
        ready = process_allowed
    else:
        ready = docker["daemon_running"] and docker["image_present"]
    return {
        "sandbox_mode": mode,
        "sandbox_ready": ready,
        "process_allowed": process_allowed,
        "desktop": settings.quick_sciplot_desktop,
        "can_enable_process": settings.quick_sciplot_desktop,
        "can_build_image": build_files_dir() is not None,
        "docker": docker,
        "image_build": IMAGE_BUILD.snapshot(),
        "llm_configured": llm.is_configured(),
        "llm_mock": settings.llm_mock,
    }


def configure_sandbox(mode: str, acknowledge_risk: bool = False) -> dict:
    """Switch the execution sandbox from the first-run wizard."""
    if mode == "docker":
        app_config.update_runtime_config(sandbox_mode="docker")
    elif mode == "process":
        if not settings.quick_sciplot_desktop:
            raise SetupError("只有桌面版可以在界面中启用本地 worker；浏览器开发模式请设置 ALLOW_UNSAFE_PROCESS_SANDBOX=1")
        if not acknowledge_risk:
            raise SetupError("启用本地 worker 前需要确认：它不是操作系统级沙箱，只适合运行可信的代码")
        app_config._persist_env({"SANDBOX_MODE": "process", "ALLOW_UNSAFE_PROCESS_SANDBOX": "1"})
        settings.allow_unsafe_process_sandbox = True
        settings.sandbox_mode = "process"
    else:
        raise SetupError("沙箱模式只能是 process 或 docker")
    return system_status()
