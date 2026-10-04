"""沙箱执行：LLM 生成的代码在受限子进程中运行。

限制策略（轻量级，面向本地单用户）：
- 子进程 + 超时强杀；
- import 白名单（ast 静态检查）；
- 禁用 eval/exec/open/input/子进程/网络等危险调用；
- 由沙箱自动注入 Agg 后端、数据加载与图片保存，LLM 代码无需感知。
"""

import ast
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import uuid
from collections.abc import Callable
from pathlib import Path

from .config import settings
from . import preset_registry

FORBIDDEN_NAMES = {
    "eval", "exec", "compile", "open", "input", "breakpoint", "globals", "locals", "vars",
    "getattr", "setattr", "delattr", "__import__", "__builtins__", "__loader__", "__spec__", "importlib",
    "_os", "_sys",
}
FORBIDDEN_ATTRS = {
    "os.system", "os.popen", "os.remove", "os.unlink", "os.rmdir", "shutil", "subprocess",
    "socket", "requests", "urllib", "pathlib.Path.open", "Path.open", "system", "popen",
    "spawn", "execv", "execve",
}
FORBIDDEN_INTERNAL_ATTRS = {
    "__subclasses__", "__bases__", "__mro__", "__globals__", "__class__", "__code__",
    "__closure__", "__dict__", "environ",
}
MAX_INTERACTIVE_BYTES = 15 * 1024 * 1024
MAX_OUTPUT_FILE_BYTES = 25 * 1024 * 1024
MAX_OUTPUT_DIR_BYTES = 128 * 1024 * 1024
MAX_LOG_BYTES = 64 * 1024

FALLBACK_RC_PARAMS = {
    "default": {},
    "science": {
        "figure.figsize": (3.5, 2.625),
        "axes.linewidth": 0.8,
        "axes.grid": False,
        "xtick.direction": "in",
        "ytick.direction": "in",
        "legend.frameon": False,
        "font.size": 9,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.05,
    },
    "nature": {
        "figure.figsize": (3.35, 2.5),
        "axes.linewidth": 0.8,
        "axes.grid": False,
        "font.family": "sans-serif",
        "font.size": 8,
        "axes.labelsize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.frameon": False,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.04,
    },
    "ieee": {
        "figure.figsize": (3.5, 2.625),
        "axes.linewidth": 0.7,
        "axes.grid": False,
        "font.family": "serif",
        "font.size": 8,
        "lines.linewidth": 1.0,
        "legend.frameon": False,
        "savefig.bbox": "tight",
        "savefig.pad_inches": 0.04,
    },
    "lovely": {
        "figure.figsize": (6.4, 4.2),
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": False,
        "font.size": 10,
        "legend.frameon": False,
        "savefig.bbox": "tight",
    },
    "tueplots": {
        "figure.figsize": (3.35, 2.5),
        "font.size": 8,
        "axes.labelsize": 8,
        "xtick.labelsize": 7,
        "ytick.labelsize": 7,
        "legend.frameon": False,
        "savefig.bbox": "tight",
    },
}


class SandboxError(Exception):
    pass


class SandboxSyntaxError(SandboxError):
    """生成代码无法解析，允许生成流程交给 LLM 修复。"""


class SandboxUnavailableError(SandboxError):
    """请求了 Docker 模式但运行环境不可用。"""


def process_sandbox_allowed() -> bool:
    """Whether the explicitly unsafe local subprocess mode is enabled."""
    return bool(settings.allow_unsafe_process_sandbox)


def validate_script(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SandboxSyntaxError(f"代码语法错误: {exc}") from exc

    allowed = set(settings.sandbox_allowed_modules)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".")[0]
                if root not in allowed:
                    raise SandboxError(f"禁止导入模块: {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root not in allowed:
                raise SandboxError(f"禁止导入模块: {node.module}")
        elif isinstance(node, ast.Name):
            if node.id in FORBIDDEN_NAMES:
                raise SandboxError(f"禁止引用敏感名称: {node.id}")
        elif isinstance(node, ast.Attribute):
            if node.attr in FORBIDDEN_INTERNAL_ATTRS:
                raise SandboxError(f"禁止访问敏感内部属性: {node.attr}")
            attr = _attr_name(node)
            if any(attr.startswith(b + ".") for b in FORBIDDEN_ATTRS) or attr in FORBIDDEN_ATTRS:
                raise SandboxError(f"禁止访问属性: {attr}")
        elif isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id in FORBIDDEN_NAMES:
                raise SandboxError(f"禁止调用: {node.func.id}")
            if isinstance(node.func, ast.Attribute):
                attr = _attr_name(node.func)
                if any(attr.startswith(b + ".") for b in FORBIDDEN_ATTRS) or attr in FORBIDDEN_ATTRS:
                    raise SandboxError(f"禁止调用: {attr}")


def _attr_name(node: ast.Attribute) -> str:
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    elif isinstance(cur, ast.Call):
        parts.append("<call>")
    return ".".join(reversed(parts))


def _build_script(
    user_code: str,
    csv_path: Path,
    preset_id: str | None = None,
    include_local_presets: bool = True,
) -> str:
    runtime = preset_registry.runtime_options(preset_id)
    if not include_local_presets:
        runtime["scienceplots_src"] = None
    fallback = FALLBACK_RC_PARAMS[runtime["fallback"]]
    data_path = csv_path.as_posix() if not include_local_presets else str(csv_path)
    preamble = f"""# -*- coding: utf-8 -*-
import os as _os
import sys as _sys
import logging as _logging
import warnings as _warnings
_os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib
matplotlib.use("Agg")

# 没有中文字体的环境（Linux、Docker 镜像）里，下面的字体回退列表会让 matplotlib
# 为每次字体查找输出 findfont 日志和缺字形警告，很快超过日志上限而被终止，
# 也会淹没真正的报错信息（自动修复依赖它），因此静默这两类输出。
_logging.getLogger("matplotlib.font_manager").setLevel(_logging.ERROR)
_warnings.filterwarnings("ignore", message=r"Glyph .* missing from (current )?font")
del _logging
del _warnings

# 嵌入出版级 TrueType 矢量字体 (Type 42)，满足 IEEE/Nature 论文印刷标准
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42

# 配置学术与中文字体回退列表，杜绝负号与中文方块乱码 □
matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "PingFang SC", "WenQuanYi Micro Hei", "DejaVu Sans", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False

_scienceplots_src = {runtime["scienceplots_src"]!r}
if _scienceplots_src:
    _sys.path.insert(0, _scienceplots_src)
    try:
        import scienceplots  # noqa: F401
    except Exception:
        pass

del _os
del _sys

import pandas as pd
df = pd.read_csv({data_path!r})
df.columns = [str(c).strip() for c in df.columns]
import matplotlib.pyplot as plt

_selected_styles = {runtime["styles"]!r}
if _selected_styles:
    try:
        plt.style.use(_selected_styles)
    except Exception:
        pass

_fallback_rc_params = {fallback!r}
if _fallback_rc_params:
    plt.rcParams.update(_fallback_rc_params)

# 样式加载后确保 TrueType 与字体回退依然生效
matplotlib.rcParams["pdf.fonttype"] = 42
matplotlib.rcParams["ps.fonttype"] = 42
matplotlib.rcParams["font.sans-serif"] = ["SimHei", "Microsoft YaHei", "PingFang SC", "WenQuanYi Micro Hei", "DejaVu Sans", "sans-serif"]
matplotlib.rcParams["axes.unicode_minus"] = False
"""
    epilogue = """
import os as _os
import sys as _sys
_interactive_fig = globals().get("fig")
if _interactive_fig is not None and hasattr(_interactive_fig, "to_plotly_json"):
    try:
        import plotly.io as _pio
        with open(_os.environ["OUTPUT_PLOTLY"], "w", encoding="utf-8") as _pf:
            _pio.write_json(_interactive_fig, _pf, pretty=False)
    except Exception as _exc:
        print(f"export plotly failed: {_exc}", file=_sys.stderr)
else:
    _fig = plt.gcf()
    try:
        _fig.tight_layout()
    except Exception:
        pass
    try:
        import json as _json
        _ax = plt.gca()
        _pos = _ax.get_position()
        _meta_data = {
            "xlim": [float(_ax.get_xlim()[0]), float(_ax.get_xlim()[1])],
            "ylim": [float(_ax.get_ylim()[0]), float(_ax.get_ylim()[1])],
            "bbox": [float(_pos.x0), float(_pos.y0), float(_pos.width), float(_pos.height)],
        }
        with open(_os.environ["OUTPUT_META"], "w", encoding="utf-8") as _mf:
            _json.dump(_meta_data, _mf)
    except Exception as _mexc:
        print(f"export meta failed: {_mexc}", file=_sys.stderr)
    _fig.savefig(_os.environ["OUTPUT_PNG"], dpi=300, bbox_inches="tight")
    for _format in ("svg", "pdf", "eps"):
        try:
            _fig.savefig(
                _os.environ["OUTPUT_" + _format.upper()],
                format=_format,
                dpi=300,
                bbox_inches="tight",
            )
        except Exception as _exc:
            print(f"export {_format} failed: {_exc}", file=_sys.stderr)
plt.close("all")
"""
    return preamble + "\n" + user_code.strip() + "\n" + epilogue


def _clean_subprocess_env(output_paths: dict[str, Path], output_dir: Path) -> dict[str, str]:
    keep_keys = {
        "PATH",
        "PATHEXT",
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "HOMEDRIVE",
        "HOMEPATH",
        "USERPROFILE",
        "APPDATA",
        "LOCALAPPDATA",
        "LANG",
        "LC_ALL",
        "PYTHONPATH",
    }
    clean = {k: v for k, v in os.environ.items() if k.upper() in keep_keys}
    clean["MPLBACKEND"] = "Agg"
    clean["PYTHONDONTWRITEBYTECODE"] = "1"
    clean["PYTHONIOENCODING"] = "utf-8"
    clean["TEMP"] = str(output_dir)
    clean["TMP"] = str(output_dir)
    clean["OUTPUT_PATH"] = str(output_paths["png"])
    clean.update({f"OUTPUT_{format_name.upper()}": str(path) for format_name, path in output_paths.items()})
    return clean


def run_plot_code(code: str, csv_path: Path, output_dir: Path, preset_id: str | None = None) -> dict:
    validate_script(code)
    preset_registry.get_preset(preset_id)
    csv_path = csv_path.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = _output_paths(output_dir)
    for path in output_paths.values():
        path.unlink(missing_ok=True)

    execution_mode = settings.sandbox_mode

    if execution_mode == "process":
        if not process_sandbox_allowed():
            raise SandboxUnavailableError(
                "process 沙箱未启用。请配置 Docker，或仅在可信本机开发环境中设置 "
                "ALLOW_UNSAFE_PROCESS_SANDBOX=1"
            )
        if getattr(sys, "frozen", False):
            proc = _run_frozen_worker(code, csv_path, output_dir, preset_id, output_paths)
        else:
            script_path = output_dir / "runner_script.py"
            script_path.write_text(_build_script(code, csv_path, preset_id), encoding="utf-8")
            env = _clean_subprocess_env(output_paths, output_dir)
            proc = _run_command(
                [sys.executable, "-I", "-u", str(script_path)],
                cwd=output_dir,
                env=env,
                monitored_paths=list(output_paths.values()),
            )
    elif execution_mode == "docker":
        proc = _run_in_docker(code, csv_path, output_dir, preset_id)
    else:
        raise SandboxError(f"未知沙箱模式: {execution_mode}")

    oversized = [
        f"{format_name} ({path.stat().st_size // (1024 * 1024)}MB)"
        for format_name, path in output_paths.items()
        if path.is_file() and path.stat().st_size > MAX_OUTPUT_FILE_BYTES
    ]
    output_error = "输出文件超过大小限制: " + ", ".join(oversized) if oversized else ""
    out_path = output_paths["png"]
    result = {
        "success": proc.returncode == 0 and not oversized and any(path.exists() for path in output_paths.values()),
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": ((proc.stderr or "") + (f"\n{output_error}" if output_error else ""))[-4000:],
        "formats": [format_name for format_name, path in output_paths.items() if path.exists() and format_name != "meta"],
    }
    if result["success"]:
        if out_path.exists():
            result["image"] = _to_data_url(out_path)
            result["size_bytes"] = out_path.stat().st_size
        meta_path = output_paths["meta"]
        if meta_path.exists():
            try:
                result["meta"] = json.loads(meta_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        interactive_path = output_paths["plotly"]
        if interactive_path.exists() and interactive_path.stat().st_size <= MAX_INTERACTIVE_BYTES:
            try:
                result["interactive"] = json.loads(interactive_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                result["stderr"] += f"\n读取交互图失败: {exc}"
    return result


def _output_paths(output_dir: Path) -> dict[str, Path]:
    extensions = {"png": "png", "svg": "svg", "pdf": "pdf", "eps": "eps", "plotly": "plotly.json", "meta": "meta.json"}
    return {format_name: output_dir / f"out.{extension}" for format_name, extension in extensions.items()}


def _run_frozen_worker(
    code: str,
    csv_path: Path,
    output_dir: Path,
    preset_id: str | None,
    output_paths: dict[str, Path],
) -> subprocess.CompletedProcess:
    script_path = output_dir / "worker-script.py"
    script_path.write_text(_build_script(code, csv_path, preset_id, include_local_presets=False), encoding="utf-8")
    env = _clean_subprocess_env(output_paths, output_dir)
    try:
        return _run_command(
            [sys.executable, "--worker", "--script-file", str(script_path)],
            cwd=output_dir,
            env=env,
            monitored_paths=list(output_paths.values()),
        )
    finally:
        script_path.unlink(missing_ok=True)


def _run_in_docker(code: str, csv_path: Path, output_dir: Path, preset_id: str | None) -> subprocess.CompletedProcess:
    docker_binary = _find_docker()
    if docker_binary is None:
        raise SandboxUnavailableError(
            "未找到 Docker。请安装 Docker Desktop；如确需可信本机 process 模式，"
            "请同时设置 ALLOW_UNSAFE_PROCESS_SANDBOX=1"
        )

    output_paths = _output_paths(output_dir)
    container_env = {
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": "/tmp/matplotlib",
        "PYTHONDONTWRITEBYTECODE": "1",
        **{f"OUTPUT_{format_name.upper()}": f"/workspace/output/{path.name}" for format_name, path in output_paths.items()},
    }
    # 脚本通过挂载目录里的文件交给容器，而不是 `python -c <脚本>`：Windows 的命令行
    # 长度上限约 32767 字符，而 API 允许最长 10 万字符的代码。
    script_path = output_dir / "runner_script.py"
    script_path.write_text(
        _build_script(code, Path("/workspace/data.csv"), preset_id, include_local_presets=False),
        encoding="utf-8",
    )
    if os.name != "nt":
        # 容器以 uid 65532 运行，必须能向 bind mount 写入产物并读取脚本。
        output_dir.chmod(0o777)
        script_path.chmod(0o644)

    # 给容器命名：超时/超限时 taskkill 只能结束 docker 客户端，容器本身会继续运行，
    # 必须显式 `docker rm -f` 才能真正停止失控的绘图代码。
    container_name = f"quick-sciplot-{uuid.uuid4().hex[:16]}"

    def remove_container() -> None:
        try:
            subprocess.run(
                [docker_binary, "rm", "-f", container_name],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=30,
            )
        except (OSError, subprocess.SubprocessError):
            pass

    command = [
        docker_binary,
        "run",
        "--rm",
        "--name",
        container_name,
        "--network",
        "none",
        "--read-only",
        "--tmpfs",
        "/tmp:rw,noexec,nosuid,size=64m",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges:true",
        "--pids-limit",
        "128",
        "--memory",
        "1g",
        "--cpus",
        "1.0",
        "--user",
        "65532:65532",
        "--mount",
        f"type=bind,source={csv_path.resolve()},target=/workspace/data.csv,readonly",
        "--mount",
        f"type=bind,source={output_dir.resolve()},target=/workspace/output",
    ]
    for key, value in container_env.items():
        command.extend(["--env", f"{key}={value}"])
    command.extend(
        [
            settings.docker_image,
            "python",
            "-I",
            "-u",
            "/workspace/output/runner_script.py",
        ]
    )
    try:
        return _run_command(
            command,
            cwd=output_dir,
            env=None,
            monitored_paths=list(output_paths.values()),
            on_terminate=remove_container,
        )
    finally:
        script_path.unlink(missing_ok=True)


def _run_command(
    command: list[str],
    *,
    cwd: Path,
    env: dict[str, str] | None,
    monitored_paths: list[Path] | None = None,
    on_terminate: Callable[[], None] | None = None,
) -> subprocess.CompletedProcess:
    """Run a renderer while keeping untrusted stdout/stderr off the heap.

    ``on_terminate`` runs after the child was force-killed for a timeout or a
    limit violation; Docker uses it to remove the (still running) container.
    """
    stdout_path = cwd / ".runner.stdout"
    stderr_path = cwd / ".runner.stderr"
    creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    stdout_handle = stdout_path.open("wb")
    stderr_handle = stderr_path.open("wb")
    try:
        process = subprocess.Popen(
            command,
            cwd=str(cwd),
            env=env,
            stdout=stdout_handle,
            stderr=stderr_handle,
            creationflags=creationflags,
        )
    finally:
        stdout_handle.close()
        stderr_handle.close()

    timed_out = False
    limit_error = ""
    try:
        deadline = time.monotonic() + settings.sandbox_timeout
        while True:
            limit_error = _runner_limit_error(stdout_path, stderr_path, monitored_paths or [], cwd)
            if limit_error:
                _terminate_process(process, on_terminate)
                returncode = -1
                break

            polled = process.poll()
            if polled is not None:
                returncode = polled
                # A short-lived process may finish between checks; inspect once
                # more so a final oversized write is still rejected.
                limit_error = _runner_limit_error(stdout_path, stderr_path, monitored_paths or [], cwd)
                if limit_error:
                    returncode = -1
                break

            if time.monotonic() >= deadline:
                _terminate_process(process, on_terminate)
                returncode = -1
                timed_out = True
                break
            time.sleep(0.05)

        stdout = _read_tail(stdout_path)
        stderr = _read_tail(stderr_path)
        if timed_out:
            stderr = (stderr + f"\n执行超时（>{settings.sandbox_timeout}s）")[-4000:]
        if limit_error:
            stderr = (stderr + f"\n{limit_error}")[-4000:]
        return subprocess.CompletedProcess(command, returncode, stdout=stdout, stderr=stderr)
    finally:
        stdout_path.unlink(missing_ok=True)
        stderr_path.unlink(missing_ok=True)


def _runner_limit_error(
    stdout_path: Path,
    stderr_path: Path,
    monitored_paths: list[Path],
    output_dir: Path | None = None,
) -> str:
    for log_path in (stdout_path, stderr_path):
        try:
            if log_path.stat().st_size > MAX_LOG_BYTES:
                return "日志输出超过大小限制"
        except OSError:
            continue
    for artifact_path in monitored_paths:
        try:
            if artifact_path.is_file() and artifact_path.stat().st_size > MAX_OUTPUT_FILE_BYTES:
                return f"输出文件超过大小限制: {artifact_path.name}"
        except OSError:
            continue
    if output_dir is not None:
        try:
            total_bytes = sum(
                child.stat().st_size
                for child in output_dir.rglob("*")
                if child.is_file()
            )
        except OSError:
            total_bytes = 0
        if total_bytes > MAX_OUTPUT_DIR_BYTES:
            return "输出目录超过大小限制"
    return ""


def _read_tail(path: Path) -> str:
    try:
        with path.open("rb") as handle:
            handle.seek(0, os.SEEK_END)
            start = max(0, handle.tell() - MAX_LOG_BYTES)
            handle.seek(start)
            return handle.read(MAX_LOG_BYTES).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _terminate_process(process: subprocess.Popen, on_terminate: Callable[[], None] | None = None) -> None:
    if on_terminate is not None:
        on_terminate()
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass


def _find_docker() -> str | None:
    found = shutil.which("docker")
    if found:
        return found
    if os.name == "nt":
        candidates = [
            Path(os.environ.get("ProgramFiles", "C:\\Program Files")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
            Path(os.environ.get("LOCALAPPDATA", "")) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe",
        ]
        for candidate in candidates:
            if candidate.is_file():
                return str(candidate)
    return None


def _to_data_url(path: Path) -> str:
    with path.open("rb") as f:
        content = f.read(MAX_OUTPUT_FILE_BYTES + 1)
    if len(content) > MAX_OUTPUT_FILE_BYTES:
        raise SandboxError("PNG 输出超过大小限制")
    return "data:image/png;base64," + base64.b64encode(content).decode("ascii")
