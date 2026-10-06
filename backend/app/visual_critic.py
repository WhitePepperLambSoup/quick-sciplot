"""视觉排版质检 Agent (Visual Critic)。

审查生成的图片排版质量，检查文字重叠、图例遮挡、DPI 以及边距紧凑度，
并输出针对性的自愈修复指令。
"""

import base64
import io
from pathlib import Path

from PIL import Image

from . import llm
from .compliance_checker import dpi_from_image_info

MAX_VISION_EDGE = 1600


def _vision_data_url(image_path: Path) -> str:
    """Downscaled PNG data URL: a 300 DPI figure is far larger than a model needs."""
    with Image.open(image_path) as image:
        image = image.convert("RGB")
        image.thumbnail((MAX_VISION_EDGE, MAX_VISION_EDGE))
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii")


def ai_critique(image_path: Path, code: str) -> dict:
    """Review the rendered figure with a multimodal model; errors are reported, not raised."""
    if not image_path.is_file():
        return {"available": False, "error": "未找到输出图像文件"}
    try:
        review = llm.critique_image(_vision_data_url(image_path), code)
    except llm.LLMError as exc:
        return {
            "available": False,
            "error": f"AI 视觉体检失败（当前模型可能不支持图像输入）：{exc}",
        }
    return {"available": True, **review}


def critique_figure_image(image_path: Path, code: str) -> dict:
    """对已生成的图片文件及源码进行视觉排版质量评估。"""
    if not image_path.is_file():
        return {
            "score": 0,
            "suggestions": ["未找到输出图像文件"],
            "has_overlap": True,
            "legend_ok": False,
            "dpi_ok": False,
            "repair_prompt": "重新运行代码生成图片",
        }

    suggestions = []
    score = 95
    has_overlap = False
    legend_ok = True
    dpi_ok = False

    try:
        with Image.open(image_path) as img:
            width, height = img.size
            aspect = round(width / max(height, 1), 2)
            # 检查极端的长宽比
            if aspect > 2.5 or aspect < 0.4:
                suggestions.append(f"图像比例失衡 (长宽比 {aspect})，建议调整 figsize 尺寸使其更适合期刊版面")
                score -= 15

            # 真实检查位图 DPI 元数据
            dpi_val = dpi_from_image_info(img.info.get("dpi"))

            if dpi_val is not None:
                dpi_ok = dpi_val >= 300
                if not dpi_ok:
                    suggestions.append(f"图像分辨率不足 ({dpi_val} DPI)，学术期刊印刷要求至少 300 DPI")
                    score -= 10
            else:
                dpi_ok = False
                suggestions.append("图像缺少 DPI 分辨率元数据，建议保存时指定 dpi=300")
                score -= 5

            # 静态代码启发式规则审查：
            # 1. 检查是否设置了 tight_layout 或 bbox_inches='tight'
            if "tight_layout" not in code and "bbox_inches" not in code:
                suggestions.append("代码中未检测到 tight_layout，轴标签或标题可能靠近边框产生截断风险")
                score -= 10

            # 2. 检查多系列是否有图例重叠风险
            if "legend(" in code:
                if "bbox_to_anchor" not in code and "loc=" not in code:
                    suggestions.append("图例未明确指定位置，可能遮挡核心数据区域，建议设置 bbox_to_anchor=(1.02, 1) 或 loc='best'")
                    score -= 10
                    legend_ok = False

            # 3. 检查 X 轴标签是否可能重叠
            overlap_risks = []
            if "xticklabels" in code and not any(k in code for k in ("rotation", "rot=", "tick_params")):
                overlap_risks.append("X 轴离散标签未设置旋转角度 (rotation)，存在水平重叠挤压风险")
                suggestions.append("若 X 轴包含较长文本类别标签，建议加入 rotation=30 或 45 度旋转以防重叠")
                score -= 5
            if not legend_ok:
                overlap_risks.append("图例可能覆盖数据几何图形")
            has_overlap = bool(overlap_risks)

            # 4. 检查字体大小与层次
            if "fontsize" not in code and "labelsize" not in code:
                suggestions.append("推荐显式指定坐标轴标签字号 (例如 fontsize=9)，保证印刷缩放后的清晰度")
                score -= 5

    except Exception as exc:
        suggestions.append(f"图像读取异常: {exc}")
        score -= 20

    if not suggestions:
        suggestions.append("图表视觉排版良好，符合科研规范。")

    repair_prompt = (
        "请优化该图的视觉排版：\n" + "\n".join(f"- {s}" for s in suggestions if "良好" not in s)
        if score < 90
        else ""
    )

    return {
        "score": max(score, 40),
        "suggestions": suggestions,
        "has_overlap": has_overlap,
        "legend_ok": legend_ok,
        "dpi_ok": dpi_ok,
        "repair_prompt": repair_prompt,
    }
