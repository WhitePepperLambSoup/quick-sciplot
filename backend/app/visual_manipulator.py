"""交互式图像修正：基于 AST 的代码逆向映射与修改引擎 (Visual Manipulator & Code Sync)。

科研人员在图表画布上直接拖拽阈值线、标记线、坐标轴边界或控制点时，
本模块将视觉调整精确转化为 Python/Matplotlib 代码更新，
既支持修改已有参数，也支持自动注入新的规范学术标尺。
"""

import ast
import math
import re
from typing import Any


class ManipulationError(Exception):
    """交互式代码修改异常。"""


def inspect_code_elements(code: str) -> dict[str, Any]:
    """通过 AST 静态扫描代码中已存在的参考线、坐标轴限制等视觉元素。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"hlines": [], "vlines": [], "ylim": None, "xlim": None}

    hlines = []
    vlines = []
    ylim = None
    xlim = None

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = _get_func_name(node.func)

        # ax.axhline(y=...) / plt.axhline(...)
        if func_name in ("ax.axhline", "plt.axhline"):
            val = None
            if node.args:
                val = _eval_literal(node.args[0])
            for kw in node.keywords:
                if kw.arg == "y":
                    val = _eval_literal(kw.value)
            if isinstance(val, (int, float)):
                hlines.append(float(val))

        # ax.axvline(x=...) / plt.axvline(...)
        elif func_name in ("ax.axvline", "plt.axvline"):
            val = None
            if node.args:
                val = _eval_literal(node.args[0])
            for kw in node.keywords:
                if kw.arg == "x":
                    val = _eval_literal(kw.value)
            if isinstance(val, (int, float)):
                vlines.append(float(val))

        # ax.set_ylim(...) / plt.ylim(...)
        elif func_name in ("ax.set_ylim", "plt.ylim"):
            if len(node.args) >= 2:
                v1 = _eval_literal(node.args[0])
                v2 = _eval_literal(node.args[1])
                if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                    ylim = [float(v1), float(v2)]
            elif len(node.args) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)):
                elts = node.args[0].elts
                if len(elts) >= 2:
                    v1 = _eval_literal(elts[0])
                    v2 = _eval_literal(elts[1])
                    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                        ylim = [float(v1), float(v2)]

        # ax.set_xlim(...) / plt.xlim(...)
        elif func_name in ("ax.set_xlim", "plt.xlim"):
            if len(node.args) >= 2:
                v1 = _eval_literal(node.args[0])
                v2 = _eval_literal(node.args[1])
                if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                    xlim = [float(v1), float(v2)]
            elif len(node.args) == 1 and isinstance(node.args[0], (ast.List, ast.Tuple)):
                elts = node.args[0].elts
                if len(elts) >= 2:
                    v1 = _eval_literal(elts[0])
                    v2 = _eval_literal(elts[1])
                    if isinstance(v1, (int, float)) and isinstance(v2, (int, float)):
                        xlim = [float(v1), float(v2)]

    return {"hlines": hlines, "vlines": vlines, "ylim": ylim, "xlim": xlim}


def adjust_hline(
    code: str,
    y: float,
    color: str = "red",
    linestyle: str = "--",
    label: str = "Cutoff",
) -> str:
    """更新已有水平参考线，或智能注入一条出版级 axhline。"""
    y_val = round(_finite_number(y, "y"), 4)

    # 1. 尝试使用正则精确匹配已有的 axhline 调用并替换数值
    pattern = re.compile(r"((?:ax|plt)\.axhline\s*\(\s*(?:y\s*=\s*)?)([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")
    if pattern.search(code):
        return pattern.sub(rf"\g<1>{y_val}", code, count=1)

    # 2. 若不存在，则寻找绘图主轴对象 ax 或在关键位置安全追加
    target = _axes_target(code)
    statement = (
        f"{target}.axhline(y={y_val}, color={_text_param(color, 'color')!r}, "
        f"linestyle={_text_param(linestyle, 'linestyle')!r}, linewidth=1.2, alpha=0.85, "
        f"label={_text_param(label, 'label')!r})"
    )
    return _inject_ax_statement(code, statement)


def adjust_vline(
    code: str,
    x: float,
    color: str = "blue",
    linestyle: str = "--",
    label: str = "Marker",
) -> str:
    """更新已有垂直标记线，或智能注入一条出版级 axvline。"""
    x_val = round(_finite_number(x, "x"), 4)

    pattern = re.compile(r"((?:ax|plt)\.axvline\s*\(\s*(?:x\s*=\s*)?)([-+]?\d*\.?\d+(?:[eE][-+]?\d+)?)")
    if pattern.search(code):
        return pattern.sub(rf"\g<1>{x_val}", code, count=1)

    target = _axes_target(code)
    statement = (
        f"{target}.axvline(x={x_val}, color={_text_param(color, 'color')!r}, "
        f"linestyle={_text_param(linestyle, 'linestyle')!r}, linewidth=1.2, alpha=0.85, "
        f"label={_text_param(label, 'label')!r})"
    )
    return _inject_ax_statement(code, statement)


def adjust_ylim(code: str, ymin: float, ymax: float) -> str:
    """更新或注入 ax.set_ylim(ymin, ymax)。"""
    ymin_val = round(_finite_number(ymin, "ymin"), 4)
    ymax_val = round(_finite_number(ymax, "ymax"), 4)
    if ymin_val > ymax_val:
        ymin_val, ymax_val = ymax_val, ymin_val

    pattern = re.compile(r"((?:ax\.set_ylim|plt\.ylim)\s*\(\s*)(?:[-+]?\d*\.?\d+)\s*,\s*(?:[-+]?\d*\.?\d+)(\s*\))")
    if pattern.search(code):
        return pattern.sub(rf"\g<1>{ymin_val}, {ymax_val}\g<2>", code, count=1)

    call = "ax.set_ylim" if _axes_target(code) == "ax" else "plt.ylim"
    return _inject_ax_statement(code, f"{call}({ymin_val}, {ymax_val})")


def adjust_xlim(code: str, xmin: float, xmax: float) -> str:
    """更新或注入 ax.set_xlim(xmin, xmax)。"""
    xmin_val = round(_finite_number(xmin, "xmin"), 4)
    xmax_val = round(_finite_number(xmax, "xmax"), 4)
    if xmin_val > xmax_val:
        xmin_val, xmax_val = xmax_val, xmin_val

    pattern = re.compile(r"((?:ax\.set_xlim|plt\.xlim)\s*\(\s*)(?:[-+]?\d*\.?\d+)\s*,\s*(?:[-+]?\d*\.?\d+)(\s*\))")
    if pattern.search(code):
        return pattern.sub(rf"\g<1>{xmin_val}, {xmax_val}\g<2>", code, count=1)

    call = "ax.set_xlim" if _axes_target(code) == "ax" else "plt.xlim"
    return _inject_ax_statement(code, f"{call}({xmin_val}, {xmax_val})")


def apply_visual_action(code: str, action: str, params: dict[str, Any]) -> str:
    """总入口：按交互动作类型修改 Python 代码。"""
    if action == "hline":
        y = params.get("y", 0.0)
        color = params.get("color", "red")
        linestyle = params.get("linestyle", "--")
        label = params.get("label", "Cutoff")
        return adjust_hline(code, y, color=color, linestyle=linestyle, label=label)

    if action == "vline":
        x = params.get("x", 0.0)
        color = params.get("color", "blue")
        linestyle = params.get("linestyle", "--")
        label = params.get("label", "Marker")
        return adjust_vline(code, x, color=color, linestyle=linestyle, label=label)

    if action == "ylim":
        ymin = params.get("ymin", 0.0)
        ymax = params.get("ymax", 10.0)
        return adjust_ylim(code, ymin, ymax)

    if action == "xlim":
        xmin = params.get("xmin", 0.0)
        xmax = params.get("xmax", 10.0)
        return adjust_xlim(code, xmin, xmax)

    raise ManipulationError(f"未知的交互修正动作: {action}")


def _finite_number(value: Any, name: str) -> float:
    """Coerce an interactive parameter to a finite float, rejecting nan/inf."""
    if isinstance(value, bool):
        raise ManipulationError(f"参数 {name} 必须是数字")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ManipulationError(f"参数 {name} 必须是数字") from exc
    if not math.isfinite(number):
        # nan/inf 会被写成裸名称 nan/inf，运行时变成 NameError。
        raise ManipulationError(f"参数 {name} 必须是有限数值")
    return number


def _text_param(value: Any, name: str) -> str:
    if not isinstance(value, str):
        raise ManipulationError(f"参数 {name} 必须是字符串")
    return value


def _axes_target(code: str) -> str:
    """Return ``ax`` when the script has an ``ax`` variable, else ``plt``.

    Uses a word-boundary match: a plain substring test also matches ``max``,
    ``axis`` or ``relax`` and made the check always succeed.
    """
    return "ax" if re.search(r"\bax\b", code) else "plt"


def _inject_ax_statement(code: str, statement: str) -> str:
    """智能将绘图/修饰语句插入到合适位置（图表保存/显示之前，或主体绘制之后）。"""
    lines = code.splitlines()

    # 优先插入到 plt.tight_layout(), plt.show(), plt.savefig() 之前，并沿用该行缩进，
    # 否则注入到函数/代码块内部的语句会产生 IndentationError 或脱离原作用域。
    insert_idx = len(lines)
    indent = ""
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith(("plt.tight_layout", "fig.tight_layout", "plt.show", "fig.savefig", "plt.savefig")):
            insert_idx = i
            indent = line[: len(line) - len(line.lstrip())]
            break

    lines.insert(insert_idx, indent + statement)
    return "\n".join(lines)


def _get_func_name(node: ast.AST) -> str:
    parts = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
    return ".".join(reversed(parts))


def _eval_literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        return None
