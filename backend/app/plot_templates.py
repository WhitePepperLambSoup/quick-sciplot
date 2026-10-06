"""Built-in scientific figure templates.

Each template turns validated parameters (column names, numbers, choices) into
deterministic plotting code.  Values are embedded with ``repr`` and the result
still goes through the sandbox's static checks, so a template is never more
powerful than code the user could type.
"""

import math
from dataclasses import dataclass, field
from typing import Any, Callable


class TemplateError(ValueError):
    """Unknown template or invalid template parameters."""


@dataclass(frozen=True)
class Param:
    name: str
    label_zh: str
    label_en: str
    kind: str  # column | numeric | numeric_multi | number | choice
    required: bool = True
    default: Any = None
    options: tuple[str, ...] = ()
    minimum: float | None = None
    maximum: float | None = None


@dataclass(frozen=True)
class Template:
    id: str
    name_zh: str
    name_en: str
    description_zh: str
    description_en: str
    params: tuple[Param, ...]
    build: Callable[[dict], str] = field(repr=False)


# --------------------------------------------------------------------------- code


def _volcano(p: dict) -> str:
    return f'''import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

fc_col = {p["fc_col"]!r}
p_col = {p["p_col"]!r}
label_col = {p.get("label_col")!r}
fc_threshold = {p["fc_threshold"]!r}
p_threshold = {p["p_threshold"]!r}

columns = [c for c in (fc_col, p_col, label_col) if c]
data = df[columns].copy()
data[fc_col] = pd.to_numeric(data[fc_col], errors="coerce")
data[p_col] = pd.to_numeric(data[p_col], errors="coerce")
data = data.dropna(subset=[fc_col, p_col])
data = data[data[p_col] > 0]
data["neg_log_p"] = -np.log10(data[p_col])

up = (data[fc_col] >= fc_threshold) & (data[p_col] < p_threshold)
down = (data[fc_col] <= -fc_threshold) & (data[p_col] < p_threshold)
other = ~(up | down)

fig, ax = plt.subplots(figsize=(5, 4.2))
ax.scatter(data.loc[other, fc_col], data.loc[other, "neg_log_p"], s=10, color="#bdbdbd", alpha=0.6, linewidths=0, label=f"NS ({{int(other.sum())}})")
ax.scatter(data.loc[up, fc_col], data.loc[up, "neg_log_p"], s=14, color="#d62728", alpha=0.85, linewidths=0, label=f"Up ({{int(up.sum())}})")
ax.scatter(data.loc[down, fc_col], data.loc[down, "neg_log_p"], s=14, color="#1f77b4", alpha=0.85, linewidths=0, label=f"Down ({{int(down.sum())}})")
for x in (fc_threshold, -fc_threshold):
    ax.axvline(x, color="gray", linestyle="--", linewidth=0.8)
ax.axhline(-np.log10(p_threshold), color="gray", linestyle="--", linewidth=0.8)

if label_col:
    top = data[up | down].nsmallest(10, p_col)
    for _, row in top.iterrows():
        ax.annotate(str(row[label_col]), (row[fc_col], row["neg_log_p"]), fontsize=7, xytext=(3, 3), textcoords="offset points")

ax.set_xlabel(f"log2 fold change ({{fc_col}})")
ax.set_ylabel(f"-log10({{p_col}})")
ax.legend(frameon=False, fontsize=8)
fig.tight_layout()
'''


def _km_survival(p: dict) -> str:
    return f'''import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from statsmodels.duration.survfunc import SurvfuncRight, survdiff

time_col = {p["time_col"]!r}
event_col = {p["event_col"]!r}
group_col = {p.get("group_col")!r}

columns = [c for c in (time_col, event_col, group_col) if c]
data = df[columns].copy()
data[time_col] = pd.to_numeric(data[time_col], errors="coerce")
data[event_col] = pd.to_numeric(data[event_col], errors="coerce")
data = data.dropna()
data[event_col] = (data[event_col] > 0).astype(int)

groups = sorted(data[group_col].astype(str).unique())[:8] if group_col else [None]
fig, ax = plt.subplots(figsize=(5.5, 4))
for group in groups:
    subset = data if group is None else data[data[group_col].astype(str) == group]
    if len(subset) == 0:
        continue
    curve = SurvfuncRight(subset[time_col].values, subset[event_col].values)
    times = np.concatenate([[0.0], curve.surv_times])
    probabilities = np.concatenate([[1.0], curve.surv_prob])
    name = "All" if group is None else str(group)
    ax.step(times, probabilities, where="post", linewidth=1.5, label=f"{{name}} (n={{len(subset)}})")

if group_col and len(groups) >= 2:
    subset = data[data[group_col].astype(str).isin(groups)]
    statistic, p_value = survdiff(subset[time_col].values, subset[event_col].values, subset[group_col].astype(str).values)
    ax.text(0.98, 0.95, f"Log-rank p = {{p_value:.3g}}", transform=ax.transAxes, ha="right", va="top", fontsize=8)

ax.set_ylim(0, 1.05)
ax.set_xlabel(str(time_col))
ax.set_ylabel("Survival probability")
ax.legend(frameon=False, fontsize=8, loc="lower left")
fig.tight_layout()
'''


def _numeric_columns_code(columns: list[str]) -> str:
    if columns:
        return f"columns = {columns!r}"
    return "columns = df.select_dtypes(include=[np.number]).columns.tolist()"


def _pca(p: dict) -> str:
    return f'''import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

{_numeric_columns_code(p.get("columns") or [])}
group_col = {p.get("group_col")!r}
if len(columns) < 2:
    raise ValueError("PCA 至少需要两列数值数据")

values = df[columns].apply(pd.to_numeric, errors="coerce").dropna()
if len(values) < 3:
    raise ValueError("PCA 至少需要 3 行完整数据")
standardized = (values - values.mean()) / values.std(ddof=0).replace(0, 1)
u, s, vt = np.linalg.svd(standardized.values, full_matrices=False)
scores = u[:, :2] * s[:2]
explained = s ** 2 / np.sum(s ** 2)

fig, ax = plt.subplots(figsize=(5, 4.2))
if group_col:
    labels = df.loc[values.index, group_col].astype(str)
    for name in list(dict.fromkeys(labels))[:12]:
        mask = (labels == name).values
        ax.scatter(scores[mask, 0], scores[mask, 1], s=22, alpha=0.8, label=name)
    ax.legend(frameon=False, fontsize=8)
else:
    ax.scatter(scores[:, 0], scores[:, 1], s=22, alpha=0.8, color="#1f77b4")
ax.axhline(0, color="gray", linewidth=0.6)
ax.axvline(0, color="gray", linewidth=0.6)
ax.set_xlabel(f"PC1 ({{explained[0] * 100:.1f}}%)")
ax.set_ylabel(f"PC2 ({{explained[1] * 100:.1f}}%)")
ax.set_title("PCA")
fig.tight_layout()
'''


def _clustermap(p: dict) -> str:
    z_score = "1" if p["standardize"] == "yes" else "None"
    center = "0" if p["standardize"] == "yes" else "None"
    return f'''import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt

{_numeric_columns_code(p.get("columns") or [])}
label_col = {p.get("label_col")!r}
if len(columns) < 2:
    raise ValueError("聚类热图至少需要两列数值数据")

matrix = df[columns].apply(pd.to_numeric, errors="coerce").dropna()
if label_col:
    matrix.index = df.loc[matrix.index, label_col].astype(str)
matrix = matrix.iloc[:200]
if len(matrix) < 2:
    raise ValueError("聚类热图至少需要 2 行完整数据")
grid = sns.clustermap(matrix, z_score={z_score}, cmap="vlag", center={center},
                      figsize=(6, 6.5), dendrogram_ratio=0.15, yticklabels=len(matrix) <= 60)
grid.ax_heatmap.set_xlabel("")
grid.ax_heatmap.set_ylabel("")
'''


def _dose_response(p: dict) -> str:
    return f'''import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
from scipy.optimize import curve_fit

dose_col = {p["dose_col"]!r}
response_col = {p["response_col"]!r}
group_col = {p.get("group_col")!r}


def four_parameter_logistic(x, bottom, top, log_ec50, hill):
    return bottom + (top - bottom) / (1 + 10 ** ((log_ec50 - np.log10(x)) * hill))


columns = [c for c in (dose_col, response_col, group_col) if c]
data = df[columns].copy()
data[dose_col] = pd.to_numeric(data[dose_col], errors="coerce")
data[response_col] = pd.to_numeric(data[response_col], errors="coerce")
data = data.dropna()
data = data[data[dose_col] > 0]
groups = list(dict.fromkeys(data[group_col].astype(str)))[:8] if group_col else [None]

fig, ax = plt.subplots(figsize=(5, 4))
for index, group in enumerate(groups):
    subset = data if group is None else data[data[group_col].astype(str) == group]
    x = subset[dose_col].values.astype(float)
    y = subset[response_col].values.astype(float)
    color = plt.cm.tab10(index % 10)
    name = "Response" if group is None else str(group)
    ax.scatter(x, y, s=16, color=color, alpha=0.75)
    try:
        guess = [np.min(y), np.max(y), np.median(np.log10(x)), 1.0]
        params, _ = curve_fit(four_parameter_logistic, x, y, p0=guess, maxfev=20000)
        grid = np.logspace(np.log10(x.min()), np.log10(x.max()), 200)
        ax.plot(grid, four_parameter_logistic(grid, *params), color=color, linewidth=1.5,
                label=f"{{name}}: EC50 = {{10 ** params[2]:.3g}}")
    except Exception:
        ax.plot([], [], color=color, label=f"{{name}}: 拟合失败")

ax.set_xscale("log")
ax.set_xlabel(str(dose_col))
ax.set_ylabel(str(response_col))
ax.legend(frameon=False, fontsize=8)
fig.tight_layout()
'''


def _correlation(p: dict) -> str:
    return f'''import numpy as np
import pandas as pd
import seaborn as sns
import matplotlib.pyplot as plt
from scipy import stats

{_numeric_columns_code(p.get("columns") or [])}
method = {p["method"]!r}
if len(columns) < 2:
    raise ValueError("相关性热图至少需要两列数值数据")

values = df[columns].apply(pd.to_numeric, errors="coerce").dropna()
corr = values.corr(method=method)
annotations = corr.copy().astype(object)
for i, first in enumerate(columns):
    for j, second in enumerate(columns):
        if i == j:
            annotations.iloc[i, j] = ""
            continue
        test = stats.pearsonr if method == "pearson" else stats.spearmanr
        p_value = test(values[first], values[second])[1]
        stars = "***" if p_value < 0.001 else "**" if p_value < 0.01 else "*" if p_value < 0.05 else ""
        annotations.iloc[i, j] = f"{{corr.iloc[i, j]:.2f}}{{stars}}"

mask = np.triu(np.ones_like(corr, dtype=bool))
size = max(4.0, 0.6 * len(columns) + 2)
fig, ax = plt.subplots(figsize=(size, size * 0.85))
sns.heatmap(corr, mask=mask, cmap="RdBu_r", vmin=-1, vmax=1, annot=annotations, fmt="",
            square=True, linewidths=0.5, cbar_kws={{"shrink": 0.8, "label": f"{{method}} r"}}, ax=ax,
            annot_kws={{"fontsize": 8}})
ax.set_title(f"Correlation ({{method}})")
fig.tight_layout()
'''


def _bar_points(p: dict) -> str:
    return f'''import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

group_col = {p["group_col"]!r}
value_col = {p["value_col"]!r}
error = {p["error"]!r}

data = df[[group_col, value_col]].copy()
data[value_col] = pd.to_numeric(data[value_col], errors="coerce")
data = data.dropna()
data[group_col] = data[group_col].astype(str)
order = list(dict.fromkeys(data[group_col]))[:20]
summary = data.groupby(group_col)[value_col].agg(["mean", "std", "count"]).reindex(order)
errors = summary["std"] if error == "sd" else summary["std"] / np.sqrt(summary["count"])

fig, ax = plt.subplots(figsize=(max(3.5, 0.8 * len(order) + 1.5), 4))
positions = np.arange(len(order))
colors = [plt.cm.tab10(i % 10) for i in range(len(order))]
ax.bar(positions, summary["mean"], yerr=errors.fillna(0), capsize=4, color=colors, alpha=0.7,
       edgecolor="black", linewidth=0.8, error_kw={{"linewidth": 1}})
rng = np.random.default_rng(0)
for position, name in zip(positions, order):
    points = data.loc[data[group_col] == name, value_col].values
    ax.scatter(position + rng.uniform(-0.15, 0.15, len(points)), points, s=12, color="black", alpha=0.6, zorder=3)
ax.set_xticks(positions)
ax.set_xticklabels(order, rotation=30 if len(order) > 4 else 0, ha="right" if len(order) > 4 else "center")
ax.set_xlabel(str(group_col))
ax.set_ylabel(f"{{value_col}} (mean ± {{error.upper()}})")
ax.spines["top"].set_visible(False)
ax.spines["right"].set_visible(False)
fig.tight_layout()
'''


TEMPLATES: tuple[Template, ...] = (
    Template(
        "volcano", "火山图", "Volcano plot",
        "差异表达分析：横轴 log2 倍数变化，纵轴 -log10(p)，按阈值标出上调/下调。",
        "Differential expression: log2 fold change vs -log10(p) with up/down thresholds.",
        (
            Param("fc_col", "log2 倍数变化列", "log2 fold-change column", "numeric"),
            Param("p_col", "p 值列", "p-value column", "numeric"),
            Param("label_col", "标注名称列（可选）", "Label column (optional)", "column", required=False),
            Param("fc_threshold", "倍数阈值", "Fold-change threshold", "number", default=1.0, minimum=0, maximum=20),
            Param("p_threshold", "p 值阈值", "p-value threshold", "number", default=0.05, minimum=1e-300, maximum=1),
        ),
        _volcano,
    ),
    Template(
        "km_survival", "生存曲线 (Kaplan-Meier)", "Kaplan-Meier survival",
        "按分组绘制 Kaplan-Meier 生存曲线，并给出 log-rank 检验 p 值。",
        "Kaplan-Meier curves by group with a log-rank test.",
        (
            Param("time_col", "时间列", "Time column", "numeric"),
            Param("event_col", "事件列（1=发生，0=删失）", "Event column (1=event, 0=censored)", "numeric"),
            Param("group_col", "分组列（可选）", "Group column (optional)", "column", required=False),
        ),
        _km_survival,
    ),
    Template(
        "pca", "主成分分析 (PCA)", "PCA scatter",
        "对数值列标准化后做 PCA，绘制 PC1/PC2 散点并标注解释方差。",
        "Standardized PCA of numeric columns, PC1 vs PC2 with explained variance.",
        (
            Param("columns", "数值列（留空=全部）", "Numeric columns (empty = all)", "numeric_multi", required=False),
            Param("group_col", "着色分组列（可选）", "Color by column (optional)", "column", required=False),
        ),
        _pca,
    ),
    Template(
        "clustermap", "聚类热图", "Clustered heatmap",
        "对行和列层次聚类的热图，可按列 z-score 标准化。",
        "Hierarchically clustered heatmap with optional column z-scores.",
        (
            Param("columns", "数值列（留空=全部）", "Numeric columns (empty = all)", "numeric_multi", required=False),
            Param("label_col", "行标签列（可选）", "Row label column (optional)", "column", required=False),
            Param("standardize", "按列标准化", "Standardize columns", "choice", default="yes", options=("yes", "no")),
        ),
        _clustermap,
    ),
    Template(
        "dose_response", "剂量反应曲线 (4PL)", "Dose-response (4PL)",
        "四参数 logistic 拟合剂量反应曲线，标注 EC50，横轴对数刻度。",
        "Four-parameter logistic fit with EC50 on a log dose axis.",
        (
            Param("dose_col", "剂量/浓度列", "Dose column", "numeric"),
            Param("response_col", "响应列", "Response column", "numeric"),
            Param("group_col", "分组列（可选）", "Group column (optional)", "column", required=False),
        ),
        _dose_response,
    ),
    Template(
        "correlation", "相关性下三角热图", "Correlation heatmap",
        "数值列两两相关系数，下三角显示 r 值和显著性星号。",
        "Pairwise correlations with r values and significance stars (lower triangle).",
        (
            Param("columns", "数值列（留空=全部）", "Numeric columns (empty = all)", "numeric_multi", required=False),
            Param("method", "相关方法", "Method", "choice", default="pearson", options=("pearson", "spearman")),
        ),
        _correlation,
    ),
    Template(
        "bar_points", "柱状图 + 散点 (均值 ± 误差)", "Bar + points (mean ± error)",
        "按组绘制均值柱状图、SD 或 SEM 误差棒，并叠加原始数据点。",
        "Group means with SD or SEM error bars and the raw data points.",
        (
            Param("group_col", "分组列", "Group column", "column"),
            Param("value_col", "数值列", "Value column", "numeric"),
            Param("error", "误差类型", "Error type", "choice", default="sd", options=("sd", "sem")),
        ),
        _bar_points,
    ),
)

_BY_ID = {template.id: template for template in TEMPLATES}


def list_templates() -> list[dict]:
    return [
        {
            "id": t.id,
            "name_zh": t.name_zh,
            "name_en": t.name_en,
            "description_zh": t.description_zh,
            "description_en": t.description_en,
            "params": [
                {
                    "name": p.name,
                    "label_zh": p.label_zh,
                    "label_en": p.label_en,
                    "kind": p.kind,
                    "required": p.required,
                    "default": p.default,
                    "options": list(p.options),
                    "minimum": p.minimum,
                    "maximum": p.maximum,
                }
                for p in t.params
            ],
        }
        for t in TEMPLATES
    ]


def build_code(template_id: str, params: dict, summary: dict) -> str:
    template = _BY_ID.get(template_id)
    if template is None:
        raise TemplateError(f"未知模板: {template_id}")
    if not isinstance(params, dict):
        raise TemplateError("模板参数必须是对象")
    columns = {str(c.get("name")): c for c in (summary or {}).get("columns", []) if isinstance(c, dict)}

    def is_numeric(name: str) -> bool:
        column = columns.get(name, {})
        dtype = str(column.get("dtype", ""))
        return "mean" in column or "int" in dtype or "float" in dtype

    clean: dict[str, Any] = {}
    for param in template.params:
        value = params.get(param.name, param.default)
        if value in (None, "", []):
            if param.required:
                raise TemplateError(f"缺少参数: {param.label_zh}")
            clean[param.name] = None if param.kind != "numeric_multi" else []
            continue
        if param.kind in {"column", "numeric"}:
            if not isinstance(value, str) or value not in columns:
                raise TemplateError(f"{param.label_zh}：列不存在 {value!r}")
            if param.kind == "numeric" and not is_numeric(value):
                raise TemplateError(f"{param.label_zh}：需要数值列，{value!r} 不是数值列")
            clean[param.name] = value
        elif param.kind == "numeric_multi":
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise TemplateError(f"{param.label_zh} 必须是列名数组")
            bad = [item for item in value if item not in columns or not is_numeric(item)]
            if bad:
                raise TemplateError(f"{param.label_zh}：不是数值列 {bad}")
            clean[param.name] = list(dict.fromkeys(value))
        elif param.kind == "number":
            try:
                number = float(value)
            except (TypeError, ValueError) as exc:
                raise TemplateError(f"{param.label_zh} 必须是数字") from exc
            if not math.isfinite(number):
                raise TemplateError(f"{param.label_zh} 必须是有限数字")
            if param.minimum is not None and number < param.minimum or param.maximum is not None and number > param.maximum:
                raise TemplateError(f"{param.label_zh} 超出范围 [{param.minimum}, {param.maximum}]")
            clean[param.name] = number
        elif param.kind == "choice":
            if value not in param.options:
                raise TemplateError(f"{param.label_zh} 只能是 {list(param.options)}")
            clean[param.name] = value
    return template.build(clean)
