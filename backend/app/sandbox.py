"""沙箱执行：LLM 生成的代码在受限子进程中运行。

限制策略（轻量级，面向本地单用户）：
- 子进程 + 超时强杀；
- import 白名单（ast 静态检查）；
- 禁用 eval/exec/open/input/子进程/网络等危险调用；
- 由沙箱自动注入 Agg 后端、数据加载与图片保存，LLM 代码无需感知。
"""

import ast
import base64
import os
import subprocess
import sys
from pathlib import Path

from .config import settings

FORBIDDEN_NAMES = {"eval", "exec", "compile", "open", "input", "breakpoint", "globals", "locals", "vars", "getattr", "setattr", "delattr"}
FORBIDDEN_ATTRS = {"os.system", "os.popen", "os.remove", "os.unlink", "os.rmdir", "shutil", "subprocess", "socket", "requests", "urllib", "pathlib.Path.open", "Path.open"}


class SandboxError(Exception):
    pass


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


def _build_script(user_code: str, csv_path: Path) -> str:
    preamble = f"""# -*- coding: utf-8 -*-
import os
os.environ.setdefault("MPLBACKEND", "Agg")
import matplotlib
matplotlib.use("Agg")
import pandas as pd
df = pd.read_csv(r"{csv_path}")
"""
    epilogue = """
import matplotlib.pyplot as plt
import os as _os
_fig = plt.gcf()
_fig.savefig(_os.environ["OUTPUT_PATH"], dpi=300, bbox_inches="tight")
plt.close("all")
"""
    return preamble + user_code + epilogue


def run_plot_code(code: str, csv_path: Path, output_dir: Path) -> dict:
    validate_script(code)
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / "out.png"
    out_path.unlink(missing_ok=True)

    env = os.environ.copy()
    env["MPLBACKEND"] = "Agg"
    env["OUTPUT_PATH"] = str(out_path)
    env["PYTHONDONTWRITEBYTECODE"] = "1"

    proc = subprocess.run(
        [sys.executable, "-I", "-u", "-c", _build_script(code, csv_path)],
        capture_output=True,
        text=True,
        cwd=str(output_dir),
        env=env,
        timeout=settings.sandbox_timeout,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    result = {
        "success": proc.returncode == 0 and out_path.exists(),
        "returncode": proc.returncode,
        "stdout": (proc.stdout or "")[-4000:],
        "stderr": (proc.stderr or "")[-4000:],
    }
    if result["success"]:
        result["image"] = _to_data_url(out_path)
        result["size_bytes"] = out_path.stat().st_size
    return result


def _to_data_url(path: Path) -> str:
    with path.open("rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode("ascii")
