"""多子图拼图编排器 (Multi-panel Figure Composer)。

为学术论文提供标准的组合大图排版（Figure 1A, 1B, 1C...）。
支持 1x2、2x1、2x2、1+2 等常见期刊布局，自动统一样式层级并注入标准子图标号。
"""

import re
from typing import Any

class LayoutValidationError(ValueError):
    """布局校验错误。"""
    pass


LAYOUT_TEMPLATES = {
    "1x2": {"rows": 1, "cols": 2, "figsize": (10, 4.5), "slots": [(0, 0), (0, 1)], "max_panels": 2},
    "2x1": {"rows": 2, "cols": 1, "figsize": (6, 8), "slots": [(0, 0), (1, 0)], "max_panels": 2},
    "2x2": {"rows": 2, "cols": 2, "figsize": (10, 8), "slots": [(0, 0), (0, 1), (1, 0), (1, 1)], "max_panels": 4},
    "1+2": {"rows": 2, "cols": 2, "figsize": (11, 7), "custom_gridspec": True, "max_panels": 3},
    "2+1": {"rows": 2, "cols": 2, "figsize": (11, 7), "custom_gridspec": True, "max_panels": 3},
    "1x3": {"rows": 1, "cols": 3, "figsize": (14, 4.5), "slots": [(0, 0), (0, 1), (0, 2)], "max_panels": 3},
    "3x1": {"rows": 3, "cols": 1, "figsize": (6, 11), "slots": [(0, 0), (1, 0), (2, 0)], "max_panels": 3},
}

PANEL_TAGS = ["A", "B", "C", "D", "E", "F", "G", "H"]


def sanitize_subplot_code(raw_code: str) -> str:
    """清理子图脚本中的独立 plt.subplots、plt.figure、plt.show、plt.close 等干扰代码。"""
    cleaned_lines = []
    skip_patterns = (
        r"^\s*fig\s*,\s*ax\s*=\s*plt\.subplots",
        r"^\s*fig\s*=\s*plt\.figure",
        r"^\s*plt\.show\s*\(",
        r"^\s*plt\.close\s*\(",
        r"^\s*plt\.savefig\s*\(",
        r"^\s*plt\.rcParams",
        r"^\s*import\s+matplotlib\.pyplot\s+as\s+plt",
        r"^\s*import\s+numpy\s+as\s+np",
        r"^\s*import\s+pandas\s+as\s+pd",
        r"^\s*import\s+seaborn\s+as\s+sns",
        r"^\s*from\s+matplotlib\s+",
    )
    for line in raw_code.splitlines():
        if any(re.search(pat, line) for pat in skip_patterns):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines).strip()


def compose_multipanel_figure(
    panels: list[dict[str, Any]],
    layout: str = "1x2",
    tag_style: str = "bold_capital",
) -> str:
    """将多个子图代码拼接并封装为一个出版级多面板大图脚本。"""
    if layout not in LAYOUT_TEMPLATES:
        valid_layouts = ", ".join(LAYOUT_TEMPLATES.keys())
        raise LayoutValidationError(f"不支持的布局类型: '{layout}'。支持的布局包括: {valid_layouts}")

    cfg = LAYOUT_TEMPLATES[layout]
    max_panels = cfg["max_panels"]
    if not panels:
        raise LayoutValidationError("至少需要提供 1 个子图面板")
    if len(panels) > max_panels:
        raise LayoutValidationError(f"布局 '{layout}' 最多支持 {max_panels} 个面板，但传入了 {len(panels)} 个面板")

    figsize = cfg["figsize"]

    header = [
        "import matplotlib.pyplot as plt",
        "import numpy as np",
        "import pandas as pd",
        "import seaborn as sns",
        "from matplotlib.gridspec import GridSpec",
        f"fig = plt.figure(figsize={figsize!r})",
    ]

    total_panels = len(panels)
    if layout == "1+2":
        header.append("gs = GridSpec(2, 2, figure=fig)")
        if total_panels == 3:
            axes_defs = [
                "ax_0 = fig.add_subplot(gs[:, 0])",  # 左侧跨越 2 行的大图
                "ax_1 = fig.add_subplot(gs[0, 1])",  # 右上
                "ax_2 = fig.add_subplot(gs[1, 1])",  # 右下
            ]
        elif total_panels == 2:
            axes_defs = [
                "ax_0 = fig.add_subplot(gs[:, 0])",
                "ax_1 = fig.add_subplot(gs[:, 1])",
            ]
        else:
            axes_defs = ["ax_0 = fig.add_subplot(gs[:, :])"]
    elif layout == "2+1":
        header.append("gs = GridSpec(2, 2, figure=fig)")
        if total_panels == 3:
            axes_defs = [
                "ax_0 = fig.add_subplot(gs[0, 0])",  # 左上
                "ax_1 = fig.add_subplot(gs[1, 0])",  # 左下
                "ax_2 = fig.add_subplot(gs[:, 1])",  # 右侧跨越 2 行的大图
            ]
        elif total_panels == 2:
            axes_defs = [
                "ax_0 = fig.add_subplot(gs[0, :])",
                "ax_1 = fig.add_subplot(gs[1, :])",
            ]
        else:
            axes_defs = ["ax_0 = fig.add_subplot(gs[:, :])"]
    else:
        rows, cols = cfg["rows"], cfg["cols"]
        axes_defs = [f"ax_{i} = fig.add_subplot({rows}, {cols}, {i + 1})" for i in range(total_panels)]

    header.extend(axes_defs)
    code_body = ["\n".join(header)]

    for i in range(total_panels):
        panel = panels[i]
        tag_char = PANEL_TAGS[i]
        tag_str = f"({tag_char.lower()})" if tag_style == "lowercase_parens" else tag_char
        raw_code = panel.get("code", "")
        cleaned = sanitize_subplot_code(raw_code)

        # 缩进 cleaned 代码放入独立函数体，保证变量作用域隔离
        indented_code = "\n".join(f"    {line}" for line in cleaned.splitlines()) if cleaned else "    pass"

        panel_code = f"\n# ===== Subplot {tag_char} =====\n"
        panel_code += f"def _draw_panel_{i}(ax):\n"
        panel_code += f"    plt.sca(ax)\n"
        panel_code += f"{indented_code}\n"
        panel_code += (
            f"    ax.text(-0.12, 1.06, {tag_str!r}, transform=ax.transAxes, "
            f"fontsize=13, fontweight='bold', va='bottom', ha='right')\n"
        )
        if panel.get("title"):
            panel_code += f"    ax.set_title({panel['title']!r})\n"
        panel_code += f"_draw_panel_{i}(ax_{i})\n"
        code_body.append(panel_code)

    footer = "\nfig.tight_layout(pad=2.0)\n"
    code_body.append(footer)

    return "\n".join(code_body)
