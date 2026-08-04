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
from pathlib import Path

from .config import settings
from . import preset_registry

FORBIDDEN_NAMES = {"eval", "exec", "compile", "open", "input", "breakpoint", "globals", "locals", "vars", "getattr", "setattr", "delattr"}
FORBIDDEN_ATTRS = {"os.system", "os.popen", "os.remove", "os.unlink", "os.rmdir", "shutil", "subprocess", "socket", "requests", "urllib", "pathlib.Path.open", "Path.open"}
MAX_INTERACTIVE_BYTES = 15 * 1024 * 1024

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


class SandboxUnavailableError(SandboxError):
    """请求了 Docker 模式但运行环境不可用。"""


def validate_script(code: str) -> None:
    try:
        tree = ast.parse(code)
    except SyntaxError as exc:
        raise SandboxError(f"代码语法错误: {exc}") from exc

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
import os
import sys
os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib
matplotlib.use("Agg")

_scienceplots_src = {runtime["scienceplots_src"]!r}
if _scienceplots_src:
    sys.path.insert(0, _scienceplots_src)
    try:
        import scienceplots  # noqa: F401
    except Exception:
        pass

import pandas as pd
df = pd.read_csv({data_path!r})
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
"""
    epilogue = """
import os as _os
import sys as _sys
_interactive_fig = globals().get("fig")
if _interactive_fig is not None and hasattr(_interactive_fig, "to_plotly_json"):
    try:
        import plotly.io as _pio
        _pio.write_json(_interactive_fig, _os.environ["OUTPUT_PLOTLY"], pretty=False)
    except Exception as _exc:
        print(f"export plotly failed: {_exc}", file=_sys.stderr)
else:
    _fig = plt.gcf()
    _fig.savefig(_os.environ["OUTPUT_PNG"], dpi=300, bbox_inches="tight")
    for _format in ("svg", "pdf"):
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
    return preamble + user_code + epilogue


def run_plot_code(code: str, csv_path: Path, output_dir: Path, preset_id: str | None = None) -> dict:
    validate_script(code)
    preset_registry.get_preset(preset_id)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_paths = _output_paths(output_dir)
    for path in output_paths.values():
        path.unlink(missing_ok=True)

    if settings.sandbox_mode == "process":
        env = os.environ.copy()
        env["MPLBACKEND"] = "Agg"
        env["OUTPUT_PATH"] = str(output_paths["png"])
        env.update({f"OUTPUT_{format_name.upper()}": str(path) for format_name, path in output_paths.items()})
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        proc = subprocess.run(
            [sys.executable, "-I", "-u", "-c", _build_script(code, csv_path, preset_id)],
            capture_output=True,
            text=True,
            cwd=str(output_dir),
            env=env,
            timeout=settings.sandbox_timeout,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
    elif settings.sandbox_mode == "docker":
        proc = _run_in_docker(code, csv_path, output_dir, preset_id)
    else:
        raise SandboxError(f"未知沙箱模式: {settings.sandbox_mode}")

    out_path = output_paths["png"]
    result = {
        "success": proc.returncode == 0 and any(path.exists() for path in output_paths.values()),
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-4000:],
        "formats": [format_name for format_name, path in output_paths.items() if path.exists()],
    }
    if result["success"]:
        if out_path.exists():
            result["image"] = _to_data_url(out_path)
            result["size_bytes"] = out_path.stat().st_size
        interactive_path = output_paths["plotly"]
        if interactive_path.exists() and interactive_path.stat().st_size <= MAX_INTERACTIVE_BYTES:
            try:
                result["interactive"] = json.loads(interactive_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                result["stderr"] += f"\n读取交互图失败: {exc}"
    return result


def _output_paths(output_dir: Path) -> dict[str, Path]:
    extensions = {"png": "png", "svg": "svg", "pdf": "pdf", "plotly": "plotly.json"}
    return {format_name: output_dir / f"out.{extension}" for format_name, extension in extensions.items()}


def _run_in_docker(code: str, csv_path: Path, output_dir: Path, preset_id: str | None) -> subprocess.CompletedProcess:
    docker_binary = _find_docker()
    if docker_binary is None:
        raise SandboxUnavailableError("未找到 Docker。请安装 Docker Desktop，或将 SANDBOX_MODE 改为 process")

    output_paths = _output_paths(output_dir)
    container_env = {
        "MPLBACKEND": "Agg",
        "MPLCONFIGDIR": "/tmp/matplotlib",
        "PYTHONDONTWRITEBYTECODE": "1",
        **{f"OUTPUT_{format_name.upper()}": f"/workspace/output/{path.name}" for format_name, path in output_paths.items()},
    }
    command = [
        docker_binary,
        "run",
        "--rm",
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
            "-c",
            _build_script(code, Path("/workspace/data.csv"), preset_id, include_local_presets=False),
        ]
    )
    return subprocess.run(
        command,
        capture_output=True,
        text=True,
        cwd=str(output_dir),
        timeout=settings.sandbox_timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )


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
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
