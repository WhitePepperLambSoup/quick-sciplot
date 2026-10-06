"""科研级统计检验与显著性标记（Statistical Annotator）。

支持对分组数据进行两两假设检验（t 检验、Mann-Whitney U 检验），
计算精确 p 值并自动为 Matplotlib 柱状图/箱线图生成学术规范的连线括号与星号标注。
"""

from typing import Any
import numpy as np
import pandas as pd
from scipy import stats


def p_value_to_asterisks(p: float) -> str:
    """将 p 值转化为学术期刊通用的星号标记。"""
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    return "ns"


def compute_cohens_d(data_a: np.ndarray, data_b: np.ndarray) -> float:
    """计算两组独立样本的 Cohen's d 效应量。"""
    n1, n2 = len(data_a), len(data_b)
    if n1 < 2 or n2 < 2:
        return 0.0
    s1, s2 = np.var(data_a, ddof=1), np.var(data_b, ddof=1)
    pooled_sd = np.sqrt(((n1 - 1) * s1 + (n2 - 1) * s2) / max(n1 + n2 - 2, 1))
    if pooled_sd == 0 or np.isnan(pooled_sd):
        return 0.0
    return float(round(float(np.mean(data_a) - np.mean(data_b)) / pooled_sd, 3))


TEST_TYPES = {"auto", "welch", "t-test", "mann-whitney", "paired-t", "wilcoxon", "tukey", "kruskal", "anova"}
CORRECTION_METHODS = {"bonferroni", "fdr_bh", "none"}
PAIRED_TESTS = {"paired-t", "wilcoxon"}


def adjust_p_values(p_values: list[float], method: str = "fdr_bh") -> list[float]:
    """计算多重比较校正 p 值 (Bonferroni、Benjamini-Hochberg FDR，或不校正)。"""
    if method not in CORRECTION_METHODS:
        raise ValueError(f"不支持的 p 值校正方法: {method}")
    m = len(p_values)
    if m <= 1 or method == "none":
        return list(p_values)
    if method == "bonferroni":
        return [min(float(p * m), 1.0) for p in p_values]

    # Benjamini-Hochberg (FDR)
    indexed = sorted(enumerate(p_values), key=lambda x: x[1])
    adjusted = [0.0] * m
    min_p = 1.0
    for rank in range(m - 1, -1, -1):
        orig_idx, p_val = indexed[rank]
        val = min(min_p, p_val * m / (rank + 1))
        adjusted[orig_idx] = float(min(round(val, 6), 1.0))
        min_p = val
    return adjusted


def compare_groups(
    df: pd.DataFrame,
    group_col: str,
    val_col: str,
    group_a: Any,
    group_b: Any,
    test_type: str = "auto",
    pair_col: str | None = None,
) -> dict:
    """计算两组数据的统计检验结果与效应量。"""
    if test_type in PAIRED_TESTS:
        return _compare_paired(df, group_col, val_col, group_a, group_b, test_type, pair_col)

    data_a = pd.to_numeric(df[df[group_col].astype(str) == str(group_a)][val_col], errors="coerce").dropna().values
    data_b = pd.to_numeric(df[df[group_col].astype(str) == str(group_b)][val_col], errors="coerce").dropna().values

    if len(data_a) == 0 or len(data_b) == 0:
        raise ValueError(f"组 {group_a} 或组 {group_b} 没有有效数值数据")

    # 自动选择或按用户指定
    if test_type == "mann-whitney":
        stat, p_val = stats.mannwhitneyu(data_a, data_b, alternative="two-sided")
        test_name = "Mann-Whitney U"
    else:
        # 默认使用 Welch's t-test (不假设方差齐性)
        stat, p_val = stats.ttest_ind(data_a, data_b, equal_var=False)
        test_name = "Welch's t-test"

    if np.isnan(p_val) or np.isnan(stat):
        is_same = False
        if len(data_a) == len(data_b) and np.allclose(data_a, data_b, equal_nan=True):
            is_same = True
        elif len(data_a) > 0 and len(data_b) > 0:
            if np.allclose(data_a, data_a[0]) and np.allclose(data_b, data_a[0]) and np.isclose(data_a[0], data_b[0]):
                is_same = True

        if is_same:
            stat = 0.0
            p_val = 1.0
        else:
            try:
                stat, p_val = stats.mannwhitneyu(data_a, data_b, alternative="two-sided")
                test_name = "Mann-Whitney U (fallback)"
            except Exception:
                stat = 0.0
                p_val = 1.0

    stars = p_value_to_asterisks(p_val)
    cohens_d = compute_cohens_d(data_a, data_b)
    return {
        "group_a": str(group_a),
        "group_b": str(group_b),
        "test_name": test_name,
        "statistic": float(round(stat, 4)),
        "p_value": float(round(p_val, 6)),
        "p_formatted": f"p < 0.001" if p_val < 0.001 else f"p = {p_val:.4f}",
        "stars": stars,
        "mean_a": float(round(np.mean(data_a), 4)),
        "mean_b": float(round(np.mean(data_b), 4)),
        "cohens_d": cohens_d,
    }


def _compare_paired(
    df: pd.DataFrame,
    group_col: str,
    val_col: str,
    group_a: Any,
    group_b: Any,
    test_type: str,
    pair_col: str | None,
) -> dict:
    """Paired comparison: rows of the two groups are matched by ``pair_col`` (e.g. subject id)."""
    if not pair_col:
        raise ValueError("配对检验需要指定配对 ID 列（例如受试者编号）")
    subset = df[df[group_col].astype(str).isin([str(group_a), str(group_b)])][[pair_col, group_col, val_col]].copy()
    subset[val_col] = pd.to_numeric(subset[val_col], errors="coerce")
    subset[group_col] = subset[group_col].astype(str)
    wide = subset.dropna().groupby([pair_col, group_col])[val_col].mean().unstack(group_col)
    if str(group_a) not in wide.columns or str(group_b) not in wide.columns:
        raise ValueError(f"组 {group_a} 或组 {group_b} 没有可配对的数据")
    wide = wide[[str(group_a), str(group_b)]].dropna()
    if len(wide) < 2:
        raise ValueError("可配对的样本少于 2 对")
    data_a = wide[str(group_a)].values
    data_b = wide[str(group_b)].values
    differences = data_a - data_b
    if np.allclose(differences, 0):
        stat, p_val = 0.0, 1.0
    elif test_type == "wilcoxon":
        stat, p_val = stats.wilcoxon(data_a, data_b)
    else:
        stat, p_val = stats.ttest_rel(data_a, data_b)
    if np.isnan(p_val) or np.isnan(stat):
        stat, p_val = 0.0, 1.0
    sd = np.std(differences, ddof=1) if len(differences) > 1 else 0.0
    effect = float(round(float(np.mean(differences)) / sd, 3)) if sd and not np.isnan(sd) else 0.0
    return {
        "group_a": str(group_a),
        "group_b": str(group_b),
        "test_name": "Wilcoxon signed-rank" if test_type == "wilcoxon" else "Paired t-test",
        "statistic": float(round(float(stat), 4)),
        "p_value": float(round(float(p_val), 6)),
        "p_formatted": "p < 0.001" if p_val < 0.001 else f"p = {p_val:.4f}",
        "stars": p_value_to_asterisks(p_val),
        "mean_a": float(round(float(np.mean(data_a)), 4)),
        "mean_b": float(round(float(np.mean(data_b)), 4)),
        "cohens_d": effect,
        "n_pairs": int(len(wide)),
    }


def tukey_pairwise(df: pd.DataFrame, group_col: str, val_col: str, pairs: list[tuple[Any, Any]]) -> list[dict]:
    """Tukey HSD over all groups involved in ``pairs``; p-values are already family-wise adjusted."""
    names = list(dict.fromkeys(str(name) for pair in pairs for name in pair))
    samples = [pd.to_numeric(df[df[group_col].astype(str) == name][val_col], errors="coerce").dropna().values for name in names]
    if any(len(sample) < 2 for sample in samples):
        raise ValueError("Tukey HSD 要求每组至少 2 个数值")
    result = stats.tukey_hsd(*samples)
    index = {name: i for i, name in enumerate(names)}
    rows = []
    for group_a, group_b in pairs:
        i, j = index[str(group_a)], index[str(group_b)]
        p_val = float(result.pvalue[i][j])
        stat = float(result.statistic[i][j])
        rows.append(
            {
                "group_a": str(group_a),
                "group_b": str(group_b),
                "test_name": "Tukey HSD",
                "statistic": float(round(stat, 4)),
                "p_value": float(round(p_val, 6)),
                "p_formatted": "p < 0.001" if p_val < 0.001 else f"p = {p_val:.4f}",
                "stars": p_value_to_asterisks(p_val),
                "mean_a": float(round(float(np.mean(samples[i])), 4)),
                "mean_b": float(round(float(np.mean(samples[j])), 4)),
                "cohens_d": compute_cohens_d(samples[i], samples[j]),
            }
        )
    return rows


def fit_regression(df: pd.DataFrame, x_col: str, y_col: str, degree: int = 1) -> dict:
    """Least-squares polynomial fit of ``y_col`` on ``x_col``."""
    if degree not in {1, 2, 3}:
        raise ValueError("拟合阶数只能是 1、2 或 3")
    data = df[[x_col, y_col]].apply(pd.to_numeric, errors="coerce").dropna()
    if len(data) < degree + 2:
        raise ValueError(f"{degree} 阶拟合至少需要 {degree + 2} 个有效数据点")
    x = data[x_col].values.astype(float)
    y = data[y_col].values.astype(float)
    if np.ptp(x) == 0:
        raise ValueError("x 列取值全部相同，无法拟合")
    coefficients = np.polyfit(x, y, degree)
    predicted = np.polyval(coefficients, x)
    ss_res = float(np.sum((y - predicted) ** 2))
    ss_tot = float(np.sum((y - np.mean(y)) ** 2))
    r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 1.0
    result = {
        "x_col": x_col,
        "y_col": y_col,
        "degree": degree,
        "n": int(len(data)),
        "coefficients": [float(c) for c in coefficients],
        "r_squared": round(float(r_squared), 6),
        "x_range": [float(np.min(x)), float(np.max(x))],
    }
    if degree == 1:
        slope_test = stats.linregress(x, y)
        result["p_value"] = float(slope_test.pvalue)
    result["equation"] = _equation_text(coefficients)
    return result


def _equation_text(coefficients) -> str:
    degree = len(coefficients) - 1
    terms = []
    for power, value in zip(range(degree, -1, -1), coefficients):
        magnitude = f"{abs(value):.4g}"
        variable = "" if power == 0 else ("x" if power == 1 else f"x^{power}")
        term = f"{magnitude}{variable}"
        if not terms:
            terms.append(("-" if value < 0 else "") + term)
        else:
            terms.append(("- " if value < 0 else "+ ") + term)
    return "y = " + " ".join(terms)


def inject_regression(original_code: str, fit: dict, color: str = "#d62728") -> str:
    """Append code that draws the fitted curve and its equation/R² on the current axes."""
    label = f"{fit['equation']}\nR² = {fit['r_squared']:.4f}"
    if "p_value" in fit:
        p_val = fit["p_value"]
        label += "\np < 0.001" if p_val < 0.001 else f"\np = {p_val:.4f}"
    snippet = [
        "",
        f"# --- 自动生成的回归拟合 ({fit['degree']} 阶, n={fit['n']}) ---",
        "import numpy as np",
        "import matplotlib.pyplot as plt",
        "_fit_ax = plt.gca()",
        f"_fit_x = np.linspace({fit['x_range'][0]!r}, {fit['x_range'][1]!r}, 200)",
        f"_fit_ax.plot(_fit_x, np.polyval({fit['coefficients']!r}, _fit_x), color={color!r}, linewidth=1.5, label='fit')",
        f"_fit_ax.text(0.03, 0.97, {label!r}, transform=_fit_ax.transAxes, ha='left', va='top', fontsize=8,",
        "              bbox=dict(boxstyle='round,pad=0.3', facecolor='white', alpha=0.8, edgecolor='none'))",
        "# --- 回归拟合结束 ---",
        "",
    ]
    return original_code.rstrip() + "\n" + "\n".join(snippet)


def compute_omnibus_test(
    df: pd.DataFrame,
    group_col: str,
    val_col: str,
    test_type: str = "auto",
) -> dict | None:
    """计算多组全局检验 (One-way ANOVA 或 Kruskal-Wallis)。"""
    unique_groups = [g for g in df[group_col].dropna().unique()]
    if len(unique_groups) < 3:
        return None
    group_arrays = [
        pd.to_numeric(df[df[group_col].astype(str) == str(g)][val_col], errors="coerce").dropna().values
        for g in unique_groups
    ]
    group_arrays = [arr for arr in group_arrays if len(arr) > 0]
    if len(group_arrays) < 3:
        return None
    try:
        if test_type == "mann-whitney" or test_type == "kruskal":
            stat, p_val = stats.kruskal(*group_arrays)
            test_name = "Kruskal-Wallis"
        else:
            stat, p_val = stats.f_oneway(*group_arrays)
            test_name = "One-way ANOVA"
    except Exception:
        stat = 0.0
        p_val = 1.0
        test_name = "Kruskal-Wallis" if (test_type == "mann-whitney" or test_type == "kruskal") else "One-way ANOVA"

    if np.isnan(p_val) or np.isnan(stat):
        p_val = 1.0
        stat = 0.0

    return {
        "test_name": test_name,
        "statistic": float(round(stat, 4)),
        "p_value": float(round(p_val, 6)),
        "p_formatted": "p < 0.001" if p_val < 0.001 else f"p = {p_val:.4f}",
        "stars": p_value_to_asterisks(p_val),
    }


def inject_stat_brackets(
    original_code: str,
    df: pd.DataFrame,
    group_col: str,
    val_col: str,
    pairs: list[tuple[Any, Any]],
    test_type: str = "auto",
    correction_method: str = "bonferroni",
    pair_col: str | None = None,
) -> tuple[str, list[dict]]:
    """向原有代码中注入标准显著性连线与星号标注代码。"""
    if not pairs:
        return original_code, []
    if test_type not in TEST_TYPES:
        raise ValueError(f"不支持的检验方法: {test_type}")
    if correction_method not in CORRECTION_METHODS:
        raise ValueError(f"不支持的 p 值校正方法: {correction_method}")
    if test_type == "tukey":
        # Tukey HSD p-values are already adjusted for all pairwise comparisons.
        correction_method = "none"

    # 获取组的唯一顺序以确定横坐标索引
    unique_groups = [str(g) for g in df[group_col].dropna().unique()]
    group_index_map = {name: idx for idx, name in enumerate(unique_groups)}

    # 按照跨度从小到大排序对，避免宽括号被窄括号穿透交叠
    sorted_pairs = sorted(
        pairs,
        key=lambda p: abs(group_index_map.get(str(p[1]), 0) - group_index_map.get(str(p[0]), 0)),
    )

    results = []
    snippets = ["\n# --- 自动生成的学术统计显著性标尺 (Auto-Stats Annotations) ---"]
    snippets.append("import matplotlib.pyplot as plt")
    snippets.append("import numpy as np")

    # 如果有 3 组以上，记录全局单因素方差分析结果
    omnibus = compute_omnibus_test(df, group_col, val_col, test_type)
    if omnibus:
        snippets.append(
            f"# 全局多组检验 ({omnibus['test_name']}): 统计量={omnibus['statistic']}, {omnibus['p_formatted']} ({omnibus['stars']})"
        )

    snippets.append("_curr_ax = plt.gca()")
    snippets.append("_y_min, _y_max = _curr_ax.get_ylim()")
    snippets.append("_y_span = max(_y_max - _y_min, 1e-4)")
    snippets.append("_bracket_y = _y_max + _y_span * 0.05")
    snippets.append("_y_step = _y_span * 0.12")

    if test_type == "tukey":
        results = tukey_pairwise(df, group_col, val_col, sorted_pairs)
    else:
        for g_a, g_b in sorted_pairs:
            results.append(compare_groups(df, group_col, val_col, g_a, g_b, test_type, pair_col=pair_col))

    # 计算多重比较校正 (Bonferroni 或 FDR)，并让图上的星号与所选方法一致。
    raw_p_values = [r["p_value"] for r in results]
    bonferroni_ps = adjust_p_values(raw_p_values, method="bonferroni")
    fdr_ps = adjust_p_values(raw_p_values, method="fdr_bh")
    adjusted_ps = adjust_p_values(raw_p_values, method=correction_method)

    for i, stat_info in enumerate(results):
        stat_info["p_bonferroni"] = bonferroni_ps[i]
        stat_info["p_fdr"] = fdr_ps[i]
        stat_info["raw_stars"] = stat_info["stars"]
        adjusted_p = adjusted_ps[i]
        stat_info["p_adjusted"] = adjusted_p
        stat_info["p_adjusted_formatted"] = (
            "p < 0.001" if adjusted_p < 0.001 else f"p = {adjusted_p:.4f}"
        )
        stat_info["correction_method"] = correction_method
        stat_info["stars"] = p_value_to_asterisks(adjusted_p)

    for i, (g_a, g_b) in enumerate(sorted_pairs):
        str_a, str_b = str(g_a), str(g_b)
        idx_a = group_index_map.get(str_a, 0)
        idx_b = group_index_map.get(str_b, 1)
        stat_info = results[i]
        stars = stat_info["stars"]
        d_val = stat_info.get("cohens_d", 0.0)

        snippets.append(
            f"# 对比 {str_a} vs {str_b}: 原始 {stat_info['p_formatted']}，校正 {stat_info['p_adjusted_formatted']} "
            f"({correction_method}: {stars}), Cohen's d={d_val}"
        )
        # 优先通过 ax.get_xticklabels() 获取真实渲染的类别 X 坐标，防止因排序/字符串轴造成的错位
        snippets.append(f"_labels = [t.get_text() for t in _curr_ax.get_xticklabels()]")
        snippets.append(f"_ticks = list(_curr_ax.get_xticks())")
        snippets.append(
            f"if {str_a!r} in _labels and {str_b!r} in _labels:\n"
            f"    _x1 = _ticks[_labels.index({str_a!r})]\n"
            f"    _x2 = _ticks[_labels.index({str_b!r})]\n"
            f"else:\n"
            f"    _x1, _x2 = {idx_a}, {idx_b}"
        )
        snippets.append(f"_cur_y = _bracket_y + {i} * _y_step")
        snippets.append(f"_tip_h = _y_step * 0.25")
        snippets.append(
            f"_curr_ax.plot([_x1, _x1, _x2, _x2], [_cur_y - _tip_h, _cur_y, _cur_y, _cur_y - _tip_h], "
            f"lw=1.0, c='k')"
        )
        snippets.append(
            f"_curr_ax.text((_x1 + _x2) * 0.5, _cur_y + _tip_h * 0.2, {stars!r}, "
            f"ha='center', va='bottom', color='k', fontsize=10, weight='bold')"
        )

    # 扩展 Y 轴以容纳括号与星号
    total_brackets = len(sorted_pairs)
    snippets.append(f"_curr_ax.set_ylim(_y_min, _bracket_y + {total_brackets + 0.5} * _y_step)")
    snippets.append("# --- 统计标尺结束 ---\n")

    annotated_code = original_code.rstrip() + "\n" + "\n".join(snippets)
    return annotated_code, results
