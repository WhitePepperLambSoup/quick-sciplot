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

MATPLOTLIB_DATA_CALLS = {
    "ax.plot",
    "plt.plot",
    "ax.scatter",
    "plt.scatter",
    "ax.bar",
    "plt.bar",
    "ax.barh",
    "plt.barh",
    "ax.errorbar",
    "plt.errorbar",
    "ax.step",
    "plt.step",
}

CALL_ENGLISH = {
    "绘制折线/曲线": "Draw a line or curve",
    "绘制散点": "Draw a scatter plot",
    "绘制柱状图": "Draw a bar chart",
    "绘制横向柱状图": "Draw a horizontal bar chart",
    "绘制误差棒图": "Draw an error-bar plot",
    "绘制直方图": "Draw a histogram",
    "绘制分布直方图": "Draw a distribution histogram",
    "绘制热图(矩阵图)": "Draw a heatmap",
    "绘制热图": "Draw a heatmap",
    "设置标题": "Set the title",
    "设置 x 轴标签": "Set the x-axis label",
    "设置 y 轴标签": "Set the y-axis label",
    "创建画布与子图": "Create the figure and axes",
    "创建画布": "Create the figure",
}

COLUMN_HINTS = {
    "revenue": ("收入", "revenue or income"),
    "income": ("收入", "income"),
    "sales": ("销售额", "sales"),
    "price": ("价格", "price"),
    "cost": ("成本", "cost"),
    "profit": ("利润", "profit"),
    "user": ("用户数", "user count"),
    "count": ("计数", "count"),
    "age": ("年龄", "age"),
    "time": ("时间", "time"),
    "date": ("日期", "date"),
    "year": ("年份", "year"),
    "month": ("月份", "month"),
    "temperature": ("温度", "temperature"),
    "value": ("测量值", "measurement value"),
    "score": ("得分", "score"),
    "group": ("分组", "group"),
}


class CodeEditError(ValueError):
    """代码已变化或参数值不符合预期。"""


def split_statements(code: str, summary: dict | None = None) -> list[dict]:
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
            bindings = _data_bindings_for(stmt, code, _summary_columns(summary))
            explanation_zh, explanation_en = _explanation_for(labels, bindings)
            cards.append(
                {
                    "start": start,
                    "end": end,
                    "code": snippet,
                    "label": labels[0] if labels else "",
                    "tags": labels,
                    "parameters": _parameters_for(stmt, code, _summary_columns(summary)),
                    "explanation_zh": explanation_zh,
                    "explanation_en": explanation_en,
                    "data_bindings": bindings,
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


def _summary_columns(summary: dict | None) -> list[str]:
    return [str(column.get("name")) for column in (summary or {}).get("columns", []) if column.get("name")]


def _data_bindings_for(stmt: ast.stmt, code: str, columns: list[str]) -> list[dict[str, Any]]:
    bindings: list[dict[str, Any]] = []
    for node in ast.walk(stmt):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node.func)
        slots: list[tuple[str, ast.AST]] = []
        if call_name in MATPLOTLIB_DATA_CALLS:
            if len(node.args) > 0:
                slots.append(("x", node.args[0]))
            if len(node.args) > 1:
                slots.append(("y", node.args[1]))
        elif call_name.endswith((".hist", ".boxplot", ".violinplot")):
            if node.args:
                slots.append(("x", node.args[0]))
        for keyword in node.keywords:
            if keyword.arg in {"x", "y", "hue", "color", "z"}:
                slots.append((keyword.arg, keyword.value))

        for axis, value_node in slots:
            column = _column_from_node(value_node)
            if column and (not columns or column in columns):
                bindings.append(_binding(axis, column))
            elif call_name.startswith("px.") and isinstance(value_node, ast.Constant) and isinstance(value_node.value, str):
                if not columns or value_node.value in columns:
                    bindings.append(_binding(axis, value_node.value))
    unique: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for binding in bindings:
        key = (binding["axis"], binding["column"])
        if key not in seen:
            seen.add(key)
            unique.append(binding)
    return unique


def _binding(axis: str, column: str) -> dict[str, Any]:
    meaning_zh, meaning_en = _column_meaning(column)
    return {
        "axis": axis,
        "column": column,
        "meaning_zh": meaning_zh,
        "meaning_en": meaning_en,
    }


def _column_meaning(column: str) -> tuple[str, str]:
    normalized = column.lower().replace("-", "_").replace(" ", "_")
    for token, meaning in sorted(COLUMN_HINTS.items(), key=lambda item: len(item[0]), reverse=True):
        if token in normalized:
            return meaning
    return column, column


def _column_from_node(node: ast.AST) -> str | None:
    if not isinstance(node, ast.Subscript) or not isinstance(node.value, ast.Name) or node.value.id != "df":
        return None
    slice_node = node.slice
    if isinstance(slice_node, ast.Constant) and isinstance(slice_node.value, str):
        return slice_node.value
    return None


def _explanation_for(labels: list[str], bindings: list[dict[str, Any]]) -> tuple[str, str]:
    base_zh = labels[0] if labels else "执行数据处理"
    base_en = CALL_ENGLISH.get(base_zh, "Run a data-processing step")
    if not bindings:
        return base_zh, base_en
    zh_axes = "，".join(f"{item['axis']} 轴使用 {item['column']}（{item['meaning_zh']}）" for item in bindings)
    en_axes = ", ".join(f"{item['axis']}-axis uses {item['column']} ({item['meaning_en']})" for item in bindings)
    return f"{base_zh}；{zh_axes}", f"{base_en}; {en_axes}"


def _parameters_for(stmt: ast.stmt, code: str, columns: list[str]) -> list[dict[str, Any]]:
    parameters: list[dict[str, Any]] = []
    for node in ast.walk(stmt):
        if not isinstance(node, ast.Call):
            continue
        call_name = _call_name(node.func)
        data_names = {"x", "y", "hue", "color", "z"}
        for keyword in node.keywords:
            if keyword.arg in data_names:
                parameter = _column_parameter(code, keyword.value, keyword.arg, columns, call_name)
                if parameter:
                    parameters.append(parameter)
                elif keyword.arg in EDITABLE_ARGUMENTS:
                    parameter = _make_parameter(code, keyword.value, keyword.arg, keyword.arg)
                    if parameter:
                        parameters.append(parameter)
        for keyword in node.keywords:
            if keyword.arg in EDITABLE_ARGUMENTS and keyword.arg not in data_names:
                parameter = _make_parameter(code, keyword.value, keyword.arg, keyword.arg)
                if parameter:
                    parameters.append(parameter)
        for index, label in POSITIONAL_ARGUMENTS.get(call_name, ()):
            if index < len(node.args):
                parameter = _make_parameter(code, node.args[index], label, label)
                if parameter:
                    parameters.append(parameter)
        if call_name in MATPLOTLIB_DATA_CALLS or call_name.endswith((".hist", ".boxplot", ".violinplot")):
            slots = [(0, "x 数据"), (1, "y 数据")] if call_name in MATPLOTLIB_DATA_CALLS else [(0, "x 数据")]
            for index, label in slots:
                if index < len(node.args):
                    parameter = _column_parameter(code, node.args[index], label, columns, call_name)
                    if parameter:
                        parameters.append(parameter)
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for parameter in parameters:
        if parameter["id"] not in seen:
            seen.add(parameter["id"])
            unique.append(parameter)
    return unique


def _column_parameter(
    code: str,
    node: ast.AST,
    name: str,
    columns: list[str],
    call_name: str,
) -> dict[str, Any] | None:
    column = _column_from_node(node)
    kind = "column"
    if column is None and call_name.startswith("px.") and isinstance(node, ast.Constant) and isinstance(node.value, str):
        column = node.value
        kind = "column_name"
    if column is None or (columns and column not in columns):
        return None
    label = {"x": "x 数据", "y": "y 数据", "hue": "分组变量", "color": "颜色/分组", "z": "z 数据"}.get(name, name)
    parameter = _make_parameter(code, node, name, label, allow_expression=True)
    if parameter is None:
        return None
    parameter["type"] = kind
    parameter["value"] = column
    parameter["options"] = columns
    meaning_zh, meaning_en = _column_meaning(column)
    parameter["meaning_zh"] = meaning_zh
    parameter["meaning_en"] = meaning_en
    return parameter


def _make_parameter(
    code: str,
    node: ast.AST,
    name: str,
    label: str,
    allow_expression: bool = False,
) -> dict[str, Any] | None:
    try:
        value = ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        if not allow_expression:
            return None
        value = None

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
    if kind == "column":
        return f"df[{value!r}]"
    if kind == "column_name":
        return repr(value)
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
