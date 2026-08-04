"""运行可重复的绘图生成评测。

示例：
    python evaluate.py --mock
    python evaluate.py

默认读取 evaluation_cases.json。真实模式需要先配置 LLM_API_KEY；mock
模式用于验证执行链路，不代表真实模型质量。
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
import tempfile
import time
from pathlib import Path

from app import data_loader, llm, sandbox
from app.config import settings


def run(cases_path: Path, mock: bool) -> dict:
    if mock:
        settings.llm_mock = True
    if not settings.llm_mock and not settings.llm_api_key:
        raise RuntimeError("未配置 LLM_API_KEY；请使用 --mock 或配置 backend/.env")

    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    results = []
    with tempfile.TemporaryDirectory(prefix="quick-sciplot-eval-") as temp_dir:
        root = Path(temp_dir)
        data_dir = root / "data"
        output_root = root / "outputs"
        for case in cases:
            started = time.perf_counter()
            item = {"id": case["id"], "code_generated": False, "render_success": False}
            try:
                dataset = data_loader.import_dataset(data_dir, f"{case['id']}.csv", case["csv"].encode("utf-8"))
                code = llm.generate_plot_code(case["instruction"], dataset["summary"], case.get("preset"))
                item["code_generated"] = bool(code.strip())
                render = sandbox.run_plot_code(code, Path(dataset["path"]), output_root / case["id"], case.get("preset"))
                item["render_success"] = bool(render["success"])
                item["formats"] = render.get("formats", [])
                item.update(_inspect_code(code, case.get("expected_format", "png"), item["formats"]))
                item["stderr"] = render.get("stderr", "")[-500:]
                item["code_chars"] = len(code)
            except Exception as exc:  #评测报告应收集单个 case 失败，而不是提前退出
                item["error"] = str(exc)
            item["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            results.append(item)

    passed = sum(1 for item in results if item.get("quality_pass", False))
    return {
        "mode": "mock" if settings.llm_mock else "api",
        "cases": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 3) if results else 0,
        "results": results,
    }


def _inspect_code(code: str, expected_format: str, formats: list[str]) -> dict:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {
            "data_reference": False,
            "plot_call": False,
            "expected_format": expected_format,
            "format_match": False,
            "quality_pass": False,
        }

    has_data_reference = any(isinstance(node, ast.Name) and node.id == "df" for node in ast.walk(tree))
    plot_tokens = ("plot", "bar", "scatter", "hist", "box", "violin", "heatmap", "imshow", "contour")
    has_plot_call = any(
        isinstance(node, ast.Call) and any(token in _call_name(node.func) for token in plot_tokens)
        for node in ast.walk(tree)
    )
    format_match = expected_format in formats
    return {
        "data_reference": has_data_reference,
        "plot_call": has_plot_call,
        "expected_format": expected_format,
        "format_match": format_match,
        "quality_pass": has_data_reference and has_plot_call and format_match,
    }


def _call_name(node: ast.AST) -> str:
    parts = []
    current = node
    while isinstance(current, ast.Attribute):
        parts.append(current.attr)
        current = current.value
    if isinstance(current, ast.Name):
        parts.append(current.id)
    return ".".join(reversed(parts))


def main() -> int:
    parser = argparse.ArgumentParser(description="Quick SciPlot generation evaluation")
    parser.add_argument("--mock", action="store_true", help="使用内置 mock LLM，不调用外部 API")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).with_name("evaluation_cases.json"),
        help="评测用例 JSON 文件",
    )
    parser.add_argument("--output", type=Path, help="将 JSON 报告保存到指定文件")
    args = parser.parse_args()
    try:
        report = run(args.cases, args.mock)
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] == report["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
