"""代码定位：用 AST 把生成代码拆成带行号、带中文解释的片段卡。

前端据此展示"直观界面"：每段代码是什么作用、能改什么，而不是一整坨黑盒。
"""

import ast

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


def _literal(node: ast.AST) -> str:
    try:
        return ast.literal_eval(node)
    except Exception:
        return "..."
