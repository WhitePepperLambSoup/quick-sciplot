"""顶刊出版合规检查器 (Journal Compliance Checker)。

对照 Nature Portfolio, IEEE, Cell Press, Science 等顶刊标准，
检查图像尺寸 (单栏/双栏)、分辨率 (DPI)、字体规范和矢量格式支持度。
"""

from pathlib import Path
from PIL import Image

JOURNAL_SPECS = {
    "nature": {
        "name": "Nature Portfolio",
        "single_col_width_inches": 3.5,  # 89 mm
        "double_col_width_inches": 7.2,  # 183 mm
        "min_dpi": 300,
        "recommended_formats": ["pdf", "svg", "eps"],
        "max_filesize_mb": 10,
    },
    "ieee": {
        "name": "IEEE Transactions",
        "single_col_width_inches": 3.5,
        "double_col_width_inches": 7.16,
        "min_dpi": 300,
        "recommended_formats": ["pdf", "eps"],
        "max_filesize_mb": 15,
    },
    "cell": {
        "name": "Cell Press",
        "single_col_width_inches": 3.35,  # 85 mm
        "double_col_width_inches": 6.85,  # 174 mm
        "min_dpi": 300,
        "recommended_formats": ["pdf", "svg"],
        "max_filesize_mb": 10,
    },
}


def dpi_from_image_info(raw) -> int | None:
    """Convert Pillow's ``info["dpi"]`` into a whole DPI value.

    PNG stores resolution as pixels per metre, so a 300 DPI figure is read back
    as 299.9994.  Truncating that with ``int()`` would report 299 DPI and fail
    every 300 DPI threshold; round to the nearest integer instead.
    """
    if isinstance(raw, (tuple, list)):
        raw = raw[0] if raw else None
    try:
        return int(round(float(raw)))
    except (TypeError, ValueError, OverflowError):
        return None


def check_journal_compliance(output_dir: Path, target_journal: str = "nature") -> dict:
    """检查输出目录下的图表文件是否符合目标学术期刊的投稿规范。"""
    j_key = target_journal.lower().strip()
    if j_key not in JOURNAL_SPECS:
        valid_keys = ", ".join(JOURNAL_SPECS.keys())
        return {
            "journal": f"未知期刊: {target_journal}",
            "passed": False,
            "checks": [{
                "item": "期刊规范收录",
                "passed": False,
                "detail": f"未收录目标期刊 '{target_journal}' 的投稿规范。当前支持: {valid_keys}",
            }],
            "formats_found": [],
        }

    spec = JOURNAL_SPECS[j_key]
    report = {
        "journal": spec["name"],
        "passed": True,
        "checks": [],
        "formats_found": [],
    }

    png_path = output_dir / "out.png"
    pdf_path = output_dir / "out.pdf"
    svg_path = output_dir / "out.svg"
    eps_path = output_dir / "out.eps"

    found_formats = []
    if png_path.is_file():
        found_formats.append("png")
    if pdf_path.is_file():
        found_formats.append("pdf")
    if svg_path.is_file():
        found_formats.append("svg")
    if eps_path.is_file():
        found_formats.append("eps")
    report["formats_found"] = found_formats

    # 1. 矢量格式要求
    has_vector = "pdf" in found_formats or "svg" in found_formats or "eps" in found_formats
    report["checks"].append({
        "item": "矢量图支持 (Vector Format)",
        "passed": has_vector,
        "detail": "包含 PDF/SVG/EPS 矢量格式，可无限缩放印刷" if has_vector else "缺少矢量格式，仅位图可能会影响印刷清晰度",
    })
    if not has_vector:
        report["passed"] = False

    # 2. 文件大小上限检查 (max_filesize_mb)
    max_mb = spec.get("max_filesize_mb", 10)
    size_passed = True
    size_details = []
    for fmt_label, p in [("PNG", png_path), ("PDF", pdf_path), ("SVG", svg_path), ("EPS", eps_path)]:
        if p.is_file():
            mb = p.stat().st_size / (1024 * 1024)
            if mb > max_mb:
                size_passed = False
                size_details.append(f"{fmt_label} 超过 {max_mb}MB ({mb:.2f}MB)")
            else:
                size_details.append(f"{fmt_label} 合规 ({mb:.2f}MB)")
    if size_details:
        report["checks"].append({
            "item": f"文件体积合规 (< {max_mb}MB)",
            "passed": size_passed,
            "detail": "; ".join(size_details),
        })
        if not size_passed:
            report["passed"] = False

    # 3. 位图分辨率与尺寸检查
    if png_path.is_file():
        try:
            with Image.open(png_path) as img:
                w_px, h_px = img.size
                dpi_raw = img.info.get("dpi")
                has_dpi_meta = dpi_raw is not None
                if not has_dpi_meta:
                    report["checks"].append({
                        "item": "DPI 图像元数据嵌入",
                        "passed": False,
                        "detail": "PNG 图像缺少内嵌 DPI 分辨率元数据",
                    })
                    report["passed"] = False

                dpi_val = dpi_from_image_info(dpi_raw)
                dpi_pass = dpi_val is not None and dpi_val >= spec["min_dpi"]

                report["checks"].append({
                    "item": f"图像分辨率 (DPI >= {spec['min_dpi']})",
                    "passed": dpi_pass,
                    "detail": f"当前分辨率约为 {dpi_val} DPI" if dpi_val is not None else "未检测到有效 DPI 元数据",
                })
                if not dpi_pass:
                    report["passed"] = False

                # 估算实际打印物理宽度 (英寸)
                physical_width_in = round(w_px / dpi_val, 2) if dpi_val else None
                is_single_or_double = bool(
                    physical_width_in is not None
                    and (
                        abs(physical_width_in - spec["single_col_width_inches"]) < 1.5
                        or abs(physical_width_in - spec["double_col_width_inches"]) < 2.0
                    )
                )
                report["checks"].append({
                    "item": "期刊版面物理宽度匹配",
                    "passed": is_single_or_double,
                    "detail": (
                        f"估算打印宽度 {physical_width_in} 英寸（期刊单栏标准 ~{spec['single_col_width_inches']} in，双栏 ~{spec['double_col_width_inches']} in）"
                        if physical_width_in is not None
                        else "无法在缺少 DPI 元数据时估算物理打印宽度"
                    ),
                })
                if not is_single_or_double:
                    report["passed"] = False
        except Exception as exc:
            report["checks"].append({"item": "图像读取检查", "passed": False, "detail": str(exc)})
            report["passed"] = False

    return report
