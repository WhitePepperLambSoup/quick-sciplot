"""运行可重复的绘图生成评测。

示例：
    python evaluate.py --mock
    python evaluate.py

默认读取 evaluation_cases.json。真实模式需要先配置 LLM_API_KEY；mock
模式用于验证执行链路，不代表真实模型质量。
"""

from __future__ import annotations

import argparse
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
                item["stderr"] = render.get("stderr", "")[-500:]
                item["code_chars"] = len(code)
            except Exception as exc:  #评测报告应收集单个 case 失败，而不是提前退出
                item["error"] = str(exc)
            item["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
            results.append(item)

    passed = sum(1 for item in results if item["code_generated"] and item["render_success"])
    return {
        "mode": "mock" if settings.llm_mock else "api",
        "cases": len(results),
        "passed": passed,
        "pass_rate": round(passed / len(results), 3) if results else 0,
        "results": results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Quick SciPlot generation evaluation")
    parser.add_argument("--mock", action="store_true", help="使用内置 mock LLM，不调用外部 API")
    parser.add_argument(
        "--cases",
        type=Path,
        default=Path(__file__).with_name("evaluation_cases.json"),
        help="评测用例 JSON 文件",
    )
    args = parser.parse_args()
    try:
        report = run(args.cases, args.mock)
    except (OSError, json.JSONDecodeError, RuntimeError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] == report["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
