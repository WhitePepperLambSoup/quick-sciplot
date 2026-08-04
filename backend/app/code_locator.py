"""代码定位：用 AST 把生成代码拆成带行号、带中文解释的片段卡。

前端据此展示"直观界面"：每段代码是什么作用、能改什么，而不是一整坨黑盒。
"""

import ast
from typing import Any

CALL_LABELS = {
    "ax.plot": "绘制折线/曲线",
    "plt.plot": "绘制折线/曲线",
    "ax.scatter": "绘制散点",
    "plt.scatter": "绘制散点",
    "ax.bar": "绘制柱状图",
    "plt.bar": "绘制柱状图",
    "ax.barh": "绘制横向柱状图",
    "plt.barh": "绘制横向柱状图",
    "ax.errorbar": "绘制误差棒图",
    "plt.errorbar": "绘制误差棒图",
    "ax.imshow": "绘制热图(矩阵图)",
    "plt.imshow": "绘制热图(矩阵图)",
    "ax.contourf": "绘制等高线填充图",
    "ax.hist": "绘制直方图",
    "plt.hist": "绘制直方图",
    "sns.histplot": "绘制分布直方图",
    "ax.boxplot": "绘制箱线图",
    "plt.boxplot": "绘制箱线图",
    "sns.boxplot": "绘制箱线图",
    "ax.violinplot": "绘制小提琴图",
    "sns.violinplot": "绘制小提琴图",
    "sns.scatterplot": "绘制散点图",
    "sns.lineplot": "绘制折线图",
    "sns.barplot": "绘制柱状统计图",
    "sns.heatmap": "绘制热图",
    "ax.set_title": "设置标题",
    "plt.title": "设置标题",
    "ax.set_xlabel": "设置 x 轴标签",
    "plt.xlabel": "设置 x 轴标签",
    "ax.set_ylabel": "设置 y 轴标签",
    "plt.ylabel": "设置 y 轴标签",
    "ax.legend": "添加图例",
    "plt.legend": "添加图例",
    "ax.set_xscale": "设置 x 轴刻度(如 log)",
    "ax.set_yscale": "设置 y 轴刻度(如 log)",
    "ax.set_xlim": "设置 x 轴范围",
    "ax.set_ylim": "设置 y 轴范围",
    "ax.axhline": "添加水平参考线",
    "ax.axvline": "添加垂直参考线",
    "ax.annotate": "添加注释",
    "ax.text": "添加文字",
    "plt.annotate": "添加注释",
    "plt.rcParams": "全局绘图参数配置",
    "plt.style.use": "套用图表风格",
    "sns.set_style": "套用 seaborn 风格",
    "sns.set_palette": "设置配色",
    "sns.set": "设置 seaborn 全局样式",
    "plt.subplots": "创建画布与子图",
    "plt.figure": "创建画布",
    "plt.subplot": "创建子图",
    "fig.tight_layout": "自动调整子图间距",
    "plt.tight_layout": "自动调整子图间距",
    "fig.savefig": "保存图片",
    "plt.show": "显示图片(沙箱内禁用)",
}

KEYWORD_LABELS = {
    "style.use": "图表风格",
    "font.sans-serif": "中文字体配置",
    "grid": "网格线",
    "alpha": "透明度",
    "color": "颜色",
    "label": "图例标签",
    "linewidth": "线宽",
    "markersize": "点大小",
    "dpi": "输出分辨率",
    "figsize": "画布尺寸",
    "log": "对数刻度",
    "rotate": "刻度旋转",
}

PANDAS_LABELS = {
    "read_csv": "读取 CSV 数据",
    "read_excel": "读取 Excel 数据",
    "groupby": "分组聚合",
    "melt": "数据整形(melt)",
    "pivot": "数据透视",
    "dropna": "去除缺失值",
    "fillna": "填充缺失值",
    "astype": "转换数据类型",
    "value_counts": "统计取值频次",
    "merge": "合并数据",
    "sort_values": "按值排序",
}

EDITABLE_ARGUMENTS = {
    "alpha",
    "bins",
    "capsize",
    "color",
    "edgecolor",
    "facecolor",
    "figsize",
    "fontsize",
    "kde",
    "label",
    "linewidth",
    "linestyle",
    "marker",
    "markersize",
    "pad",
    "palette",
    "rotation",
    "s",
}

POSITIONAL_ARGUMENTS = {
    "ax.set_title": ((0, "标题"),),
    "plt.title": ((0, "标题"),),
    "ax.set_xlabel": ((0, "x 轴标签"),),
    "plt.xlabel": ((0, "x 轴标签"),),
    "ax.set_ylabel": ((0, "y 轴标签"),),
    "plt.ylabel": ((0, "y 轴标签"),),
    "ax.set_xscale": ((0, "x 轴刻度"),),
    "ax.set_yscale": ((0, "y 轴刻度"),),
    "plt.xscale": ((0, "x 轴刻度"),),
    "plt.yscale": ((0, "y 轴刻度"),),
}


class CodeEditError(ValueError):
    """代码已变化或参数值不符合预期。"""


def split_statements(code: str) -> list[dict]:
    """返回按行划分的语句片段列表，附带作用标签。"""
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return []

    lines = code.splitlines()
    cards: list[dict] = []

    def extract_body(nodes: list[ast.stmt]) -> None:
        for stmt in nodes:
            start = getattr(stmt, "lineno", 1)
            end = max(getattr(stmt, "end_lineno", start), start)
            snippet = "\n".join(lines[start - 1 : end])
            labels = _labels_for(stmt)
            cards.append(
                {
                    "start": start,
                    "end": end,
                    "code": snippet,
                    "label": labels[0] if labels else "",
                    "tags": labels,
                    "parameters": _parameters_for(stmt, code),
                }
            )

    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            extract_body([node])
        elif isinstance(node, (ast.For, ast.While, ast.If, ast.With, ast.Try)):
            extract_body([node])
        else:
            extract_body([node])

    # 多行表达式语句可能被上面的循环重复包含，做一次行号去重
    seen: set[tuple[int, int]] = set()
    deduped = []
    for c in cards:
        key = (c["start"], c["end"])
        if key not in seen:
            seen.add(key)
            deduped.append(c)
    return deduped


def _labels_for(stmt: ast.stmt) -> list[str]:
    labels: list[str] = []
    for node in ast.walk(stmt):
        if isinstance(node, ast.Call):
            name = _call_name(node.func)
            if name in CALL_LABELS:
                labels.append(CALL_LABELS[name])
            for kw in node.keywords:
                if kw.arg in KEYWORD_LABELS:
                    labels.append(f"{KEYWORD_LABELS[kw.arg]} {kw.arg}={_literal(kw.value)}")
        elif isinstance(node, ast.Attribute):
            for k in PANDAS_LABELS:
                if node.attr == k:
                    labels.append(PANDAS_LABELS[k])
    return list(dict.fromkeys(labels))


def _call_name(node: ast.AST) -> str:
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


def _parameters_for(stmt: ast.stmt, code: str) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    for node in ast.walk(stmt):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node.func)
        for keyword in node.keywords:
            if keyword.arg in EDITABLE_ARGUMENTS:
                parameter = _make_parameter(code, keyword.value, keyword.arg, keyword.arg)
                if parameter:
                    parameters.append(parameter)
        for index, label in POSITIONAL_ARGUMENTS.get(call_name, ()):
            if index < len(node.args):
                parameter = _make_parameter(code, node.args[index], label, label)
                if parameter:
                    parameters.append(parameter)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for parameter in parameters:
        if parameter["id"] not in seen:
            seen.add(parameter["id"])
            unique.append(parameter)
    return unique


def _make_parameter(code: str, node: ast.AST, name: str, label: str) -> dict[str, Any] | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None

    if not isinstance(node, ast.expr) or not hasattr(node, "lineno") or not hasattr(node, "end_lineno"):
        return None

    lines = code.splitlines()
    start_line = node.lineno
    end_line = node.end_lineno
    start_column = _char_column(lines[start_line - 1], node.col_offset)
    end_column = _char_column(lines[end_line - 1], node.end_col_offset)
    source = ast.get_source_segment(code, node) or repr(value)
    kind = _value_kind(value)
    return {
        "id": f"{start_line}:{start_column}:{end_line}:{end_column}:{name}",
        "name": name,
        "label": label,
        "value": _display_value(value),
        "source": source,
        "type": kind,
        "start_line": start_line,
        "start_column": start_column,
        "end_line": end_line,
        "end_column": end_column,
    }


def _value_kind(value: Any) -> str:
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "literal"


def _display_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, bool):
        return str(value).lower()
    return repr(value)


def _char_column(line: str, byte_column: int) -> int:
    """AST 列是 UTF-8 字节偏移，前端和替换逻辑使用字符偏移。"""
    prefix = line.encode("utf-8")[:byte_column]
    return len(prefix.decode("utf-8", errors="ignore"))


def _offset(code: str, line: int, column: int) -> int:
    if line < 1 or column < 0:
        raise CodeEditError("参数位置无效")
    lines = code.splitlines(keepends=True)
    if line > len(lines) + (1 if code.endswith(("\n", "\r")) else 0):
        raise CodeEditError("参数所在行不存在")
    return sum(len(item) for item in lines[: line - 1]) + column


def apply_parameter(code: str, parameter: dict[str, Any], value: str) -> str:
    """按定位信息替换一个字面量参数，返回完整代码。"""
    try:
        start = _offset(code, int(parameter["start_line"]), int(parameter["start_column"]))
        end = _offset(code, int(parameter["end_line"]), int(parameter["end_column"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise CodeEditError("参数定位信息不完整") from exc

    current = code[start:end]
    expected = parameter.get("source")
    if expected and current != expected:
        raise CodeEditError("代码已变化，请重新选择参数")
    replacement = _format_value(value, parameter.get("type", "literal"))
    return code[:start] + replacement + code[end:]


def _format_value(value: str, kind: str) -> str:
    raw = value.strip()
    if kind == "string":
        return repr(value)
    if kind == "boolean":
        if raw.lower() in {"true", "1", "yes"}:
            return "True"
        if raw.lower() in {"false", "0", "no"}:
            return "False"
        raise CodeEditError("布尔参数只能填写 true 或 false")
    try:
        parsed = ast.literal_eval(raw)
    except (ValueError, SyntaxError) as exc:
        raise CodeEditError("参数值不是有效的 Python 字面量") from exc
    if kind == "number" and (not isinstance(parsed, (int, float)) or isinstance(parsed, bool)):
        raise CodeEditError("该参数需要填写数字")
    return repr(parsed)


def _literal(node: ast.AST) -> Any:
    try:
        return ast.literal_eval(node)
    except Exception:
        return "..."
