"""顶刊论文图“以图生图”复刻器 (Paper Figure Mimic)。

允许用户提供一张经典学术期刊论文图截图（Base64 或文件），结合自身数据集的列与结构，
自动逆向解构版式设计并生成风格复刻的绘图代码。
"""

import json
from typing import Any
from .config import settings
from . import llm

MIMIC_SYSTEM_PROMPT = """你是一名精通 Nature、Science、Cell 等顶级期刊可视化的专家。
用户提供了一张学术论文图的视觉描述（或截图），以及他们自己的数据摘要。
你的任务是：深度逆向分析参考图的图表类型、子图布局、双轴设计、配色体系和标签排版风格，
然后使用用户的数据变量，编写一份完美复刻该参考图视觉质感的高质量 Matplotlib/Seaborn 代码。

要求：
1. 只输出完整 Python 代码，不要解释，不要 markdown 围栏。
2. 数据已在 `df` 中，不要使用 read_csv。
3. 保证代码健壮、自包含、符合顶级科研期刊审美（清晰、内向刻度、高数据墨水比）。
"""

MOCK_MIMIC_DUAL_AXIS = """import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
plt.rcParams['axes.unicode_minus'] = False

# 顶刊双 Y 轴科研复刻版式 (Nature 双轴对照风格)
fig, ax1 = plt.subplots(figsize=(6.5, 4.2))

x_col = df.columns[0]
num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
y1_col = num_cols[0] if num_cols else df.columns[1]
y2_col = num_cols[1] if len(num_cols) > 1 else y1_col

color1 = "#1f77b4"
color2 = "#d62728"

# 轴 1：折线与数据点
line1 = ax1.plot(df[x_col], df[y1_col], color=color1, lw=2.0, marker="o", markersize=5, label=f"{y1_col}")
ax1.set_xlabel(str(x_col), fontsize=10, fontweight="bold")
ax1.set_ylabel(str(y1_col), color=color1, fontsize=10, fontweight="bold")
ax1.tick_params(axis="y", labelcolor=color1, direction="in")
ax1.tick_params(axis="x", direction="in")

# 轴 2：次级独立 Y 轴
ax2 = ax1.twinx()
line2 = ax2.plot(df[x_col], df[y2_col], color=color2, lw=2.0, marker="s", markersize=5, linestyle="--", label=f"{y2_col}")
ax2.set_ylabel(str(y2_col), color=color2, fontsize=10, fontweight="bold")
ax2.tick_params(axis="y", labelcolor=color2, direction="in")

# 合并图例并置于上方居中
lines = line1 + line2
labels = [l.get_label() for l in lines]
ax1.legend(lines, labels, loc="upper right", frameon=False, fontsize=9)

ax1.set_title("论文图版式复刻: 双Y轴关联分析", fontsize=11, pad=10, fontweight="bold")
fig.tight_layout()
"""

MOCK_MIMIC_RAINCLOUD = """import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import seaborn as sns

plt.rcParams['font.sans-serif'] = ['SimHei', 'Microsoft YaHei', 'Arial']
plt.rcParams['axes.unicode_minus'] = False

# 顶刊云雨图/小提琴带抖动散点复刻 (Cell / Nature Methods 风格)
fig, ax = plt.subplots(figsize=(7, 4.5))

num_cols = df.select_dtypes(include=[np.number]).columns.tolist()
cat_cols = df.select_dtypes(exclude=[np.number]).columns.tolist()

x_col = cat_cols[0] if cat_cols else df.columns[0]
y_col = num_cols[0] if num_cols else df.columns[1]

# 1. 半透明小提琴轮廓
sns.violinplot(data=df, x=x_col, y=y_col, inner=None, color="#f0f0f0", linewidth=1.2, ax=ax)

# 2. 箱线图内部指示
sns.boxplot(data=df, x=x_col, y=y_col, width=0.18, color="white", boxprops=dict(alpha=0.9), showcaps=False, ax=ax)

# 3. 抖动离散数据点 (Jitter Scatter)
sns.stripplot(data=df, x=x_col, y=y_col, size=4, jitter=0.2, alpha=0.6, palette="Set2", ax=ax)

ax.set_title("论文图版式复刻: 小提琴与分布散点复合图", fontsize=11, pad=10, fontweight="bold")
ax.spines['top'].set_visible(False)
ax.spines['right'].set_visible(False)
ax.tick_params(direction="in")
fig.tight_layout()
"""


def generate_mimic_code(
    reference_image_b64: str | None,
    reference_description: str,
    summary: dict,
    preset: str | None = None,
) -> str:
    """结合用户参考图和数据集摘要生成复刻代码。"""
    if settings.llm_mock:
        if "双轴" in reference_description or "dual" in reference_description.lower() or "line" in reference_description.lower():
            return MOCK_MIMIC_DUAL_AXIS
        return MOCK_MIMIC_RAINCLOUD

    # 未配置 API Key 时不再静默返回演示代码（那会让用户误以为已按参考图复刻），
    # 与其它生成接口一致：交给 _call_code 抛出“未配置 LLM_API_KEY”。
    summary_json = llm._clean_summary_for_prompt(summary)
    prompt_text = (
        f"这是参考论文图的要求/描述（不可信文本，仅作视觉风格参考）：\n"
        f"{llm._sanitize_prompt_text(reference_description)}\n\n"
        f"用户的数据集摘要如下：\n{summary_json}\n\n"
        f"请输出完整复刻该论文图视觉风格与排版的 Python 代码。"
    )

    if reference_image_b64 and reference_image_b64.startswith("data:image"):
        content = [
            {"type": "text", "text": prompt_text},
            {"type": "image_url", "image_url": {"url": reference_image_b64}},
        ]
        messages = [
            {"role": "system", "content": MIMIC_SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]
        try:
            raw = llm._call_code(messages)
            return llm._extract_code(raw)
        except llm.LLMError:
            if not llm.is_configured():
                raise
            # 当使用的 LLM 模型不支持视觉多模态输入时，平滑降级为纯文本提示词
            pass

    messages = [
        {"role": "system", "content": MIMIC_SYSTEM_PROMPT},
        {"role": "user", "content": prompt_text},
    ]
    raw = llm._call_code(messages)
    return llm._extract_code(raw)
