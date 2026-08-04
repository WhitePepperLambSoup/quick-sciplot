"""运行可重复的绘图生成评测和人工审阅报告。

示例：
    python evaluate.py --mock
    python evaluate.py --model deepseek-chat --model deepseek-reasoner
    python evaluate.py --model-config model_matrix.example.json --output reports/result.json --human-report reports/review.html

真实模式只从环境变量读取 API Key，不把密钥写入报告。
"""

from __future__ import annotations

import argparse
import ast
import html
import json
import os
import shutil
import sys
import tempfile
import time
from pathlib import Path

from app import data_loader, llm, sandbox
from app.config import settings


def run(cases_path: Path, mock: bool, models: list[dict], artifact_dir: Path | None = None) -> dict:
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    if not isinstance(cases, list) or not cases:
        raise ValueError("评测用例必须是非空数组")

    temporary_root = None
    if artifact_dir is None:
        temporary_root = tempfile.TemporaryDirectory(prefix="quick-sciplot-eval-")
        root = Path(temporary_root.name)
    else:
        artifact_dir = artifact_dir.resolve()
        artifact_dir.mkdir(parents=True, exist_ok=True)
        root = artifact_dir

    model_reports = []
    try:
        for model in models:
            model_report = _run_model(cases, model, mock, root, artifact_dir is not None)
            model_reports.append(model_report)
    finally:
        if temporary_root is not None:
            temporary_root.cleanup()

    total_cases = sum(item["cases"] for item in model_reports)
    total_passed = sum(item["passed"] for item in model_reports)
    return {
        "mode": "mock" if mock else "api",
        "models": model_reports,
        "cases": total_cases,
        "passed": total_passed,
        "pass_rate": round(total_passed / total_cases, 3) if total_cases else 0,
    }


def _run_model(cases: list[dict], model: dict, mock: bool, root: Path, keep_artifacts: bool) -> dict:
    model_name = model["name"]
    model_report = {"name": model_name, "model": model["model"], "cases": 0, "passed": 0, "results": []}
    try:
        _configure_model(model, mock)
    except RuntimeError as exc:
        model_report["error"] = str(exc)
        model_report["cases"] = len(cases)
        return model_report

    model_root = root / _slug(model_name)
    data_root = model_root / "datasets"
    output_root = model_root / "outputs"
    latencies = []
    for case in cases:
        started = time.perf_counter()
        item = {
            "id": case["id"],
            "code_generated": False,
            "render_success": False,
            "expected_format": case.get("expected_format", "png"),
        }
        try:
            dataset = data_loader.import_dataset(data_root, f"{case['id']}.csv", case["csv"].encode("utf-8"))
            code = llm.generate_plot_code(case["instruction"], dataset["summary"], case.get("preset"))
            item["code_generated"] = bool(code.strip())
            render = sandbox.run_plot_code(code, Path(dataset["path"]), output_root / case["id"], case.get("preset"))
            item["render_success"] = bool(render["success"])
            item["formats"] = render.get("formats", [])
            item.update(_inspect_code(code, item["expected_format"], item["formats"]))
            item["stderr"] = render.get("stderr", "")[-500:]
            item["code_chars"] = len(code)
            if keep_artifacts:
                item["artifact_dir"] = str((output_root / case["id"]).relative_to(root))
        except Exception as exc:  # 评测报告应收集单个 case 失败，而不是提前退出
            item["error"] = str(exc)
        item["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        latencies.append(item["latency_ms"])
        item["quality_pass"] = bool(
            item["code_generated"]
            and item["render_success"]
            and item.get("data_reference")
            and item.get("plot_call")
            and item.get("format_match")
        )
        model_report["results"].append(item)

    model_report["cases"] = len(model_report["results"])
    model_report["passed"] = sum(1 for item in model_report["results"] if item["quality_pass"])
    model_report["pass_rate"] = round(model_report["passed"] / model_report["cases"], 3) if model_report["cases"] else 0
    model_report["avg_latency_ms"] = round(sum(latencies) / len(latencies), 1) if latencies else 0
    return model_report


def _configure_model(model: dict, mock: bool) -> None:
    settings.llm_mock = mock
    settings.llm_model = model["model"]
    settings.llm_base_url = model.get("base_url") or settings.llm_base_url
    if mock:
        return
    env_name = model.get("api_key_env", "LLM_API_KEY")
    api_key = os.getenv(env_name, settings.llm_api_key if env_name == "LLM_API_KEY" else "")
    if not api_key:
        raise RuntimeError(f"模型 {model['name']} 未找到 API Key（环境变量 {env_name}）")
    settings.llm_api_key = api_key


def _inspect_code(code: str, expected_format: str, formats: list[str]) -> dict:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return {"data_reference": False, "plot_call": False, "format_match": False}

    has_data_reference = any(isinstance(node, ast.Name) and node.id == "df" for node in ast.walk(tree))
    plot_tokens = ("plot", "bar", "scatter", "hist", "box", "violin", "heatmap", "imshow", "contour")
    has_plot_call = any(
        isinstance(node, ast.Call) and any(token in _call_name(node.func) for token in plot_tokens)
        for node in ast.walk(tree)
    )
    return {
        "data_reference": has_data_reference,
        "plot_call": has_plot_call,
        "format_match": expected_format in formats,
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


def _slug(value: str) -> str:
    return "".join(char if char.isalnum() or char in "-_" else "_" for char in value).strip("_") or "model"


def load_models(args: argparse.Namespace) -> list[dict]:
    if args.model_config:
        raw = json.loads(args.model_config.read_text(encoding="utf-8"))
        configs = raw.get("models", raw) if isinstance(raw, dict) else raw
        if not isinstance(configs, list) or not configs:
            raise ValueError("model config 必须是非空数组或包含 models 数组的对象")
        required = {"name", "model"}
        if any(not required.issubset(item) for item in configs):
            raise ValueError("每个模型配置至少需要 name 和 model")
        for item in configs:
            item.setdefault("base_url", settings.llm_base_url)
        return configs

    names = args.model or [settings.llm_model]
    return [
        {
            "name": name,
            "model": name,
            "base_url": args.base_url or settings.llm_base_url,
            "api_key_env": args.api_key_env,
        }
        for name in names
    ]


def write_human_report(report: dict, report_path: Path, artifact_dir: Path) -> None:
    cards = []
    for model in report["models"]:
        for item in model.get("results", []):
            artifact = Path(item.get("artifact_dir", ""))
            output_dir = artifact_dir / artifact
            image_path = output_dir / "out.png"
            plotly_path = output_dir / "out.plotly.json"
            if image_path.is_file():
                source = html.escape(os.path.relpath(image_path, report_path.parent).replace(os.sep, "/"))
                visual = f'<img src="{source}" alt="{html.escape(item["id"])}" />'
            elif plotly_path.is_file():
                source = html.escape(os.path.relpath(plotly_path, report_path.parent).replace(os.sep, "/"))
                visual = f'<p>交互图数据：<a href="{source}">下载 Plotly JSON</a></p>'
            else:
                visual = "<p class=muted>没有可预览的输出</p>"
            error = html.escape(item.get("error", "") or item.get("stderr", ""))
            key = html.escape(f'{model["name"]}::{item["id"]}')
            cards.append(
                f"""<article class=card>
<h2>{html.escape(model['name'])} · {html.escape(item['id'])}</h2>
{visual}
<p class=meta>质量自动检查：{'通过' if item.get('quality_pass') else '未通过'} · 延迟 {item.get('latency_ms', 0)} ms</p>
<label>数据/图形正确性 <input class=score data-key="{key}" data-field="correctness" type=number min=1 max=5 /></label>
<label>视觉美观度 <input class=score data-key="{key}" data-field="aesthetics" type=number min=1 max=5 /></label>
<label>论文可用性 <input class=score data-key="{key}" data-field="publication" type=number min=1 max=5 /></label>
<label>备注 <textarea data-key="{key}" data-field="notes"></textarea></label>
<pre>{error}</pre>
</article>"""
            )

    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Quick SciPlot 人工评测</title>
<style>
body{{font-family:system-ui,"Microsoft YaHei",sans-serif;background:#f5f6fa;color:#202533;margin:0;padding:24px}}
header{{max-width:1100px;margin:0 auto 18px}}h1{{margin:0 0 6px;font-size:22px}}.summary{{color:#697286}}
.grid{{max-width:1100px;margin:auto;display:grid;grid-template-columns:repeat(auto-fit,minmax(330px,1fr));gap:14px}}
.card{{background:white;border:1px solid #e2e6ef;border-radius:10px;padding:14px;box-shadow:0 3px 12px #17203d0a}}
.card h2{{font-size:15px;margin:0 0 10px}}.card img{{width:100%;max-height:360px;object-fit:contain;border:1px solid #e7eaf1}}
label{{display:block;margin-top:8px;font-size:12px;color:#596276}}input,textarea{{display:block;width:100%;box-sizing:border-box;margin-top:4px;padding:6px;border:1px solid #ccd3e1;border-radius:5px;font:inherit}}textarea{{min-height:48px}}.meta,.muted{{color:#7b8497;font-size:11px}}pre{{white-space:pre-wrap;color:#b42318;font-size:11px}}
button{{padding:9px 14px;border:0;border-radius:6px;background:#2563eb;color:white;cursor:pointer}}
</style></head><body><header><h1>Quick SciPlot 人工评测</h1><p class=summary>自动通过率：{report['passed']}/{report['cases']}（{report['pass_rate']}） · 填写 1–5 分后点击导出评分。</p><button onclick="downloadScores()">导出评分 JSON</button></header><main class=grid>{''.join(cards)}</main>
<script>function downloadScores(){{const out={{}};document.querySelectorAll('[data-key]').forEach(e=>{{const k=e.dataset.key;out[k]=out[k]||{{}};out[k][e.dataset.field]=e.value;}});const blob=new Blob([JSON.stringify(out,null,2)],{{type:'application/json'}});const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='human-scores.json';a.click();URL.revokeObjectURL(a.href);}}</script>
</body></html>"""
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(document, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Quick SciPlot generation evaluation")
    parser.add_argument("--mock", action="store_true", help="使用内置 mock LLM，不调用外部 API")
    parser.add_argument("--model", action="append", help="要评测的模型名称，可重复传入")
    parser.add_argument("--model-config", type=Path, help="模型矩阵 JSON（不包含密钥）")
    parser.add_argument("--base-url", help="--model 模式下覆盖 Base URL")
    parser.add_argument("--api-key-env", default="LLM_API_KEY", help="--model 模式下 API Key 环境变量名")
    parser.add_argument("--cases", type=Path, default=Path(__file__).with_name("evaluation_cases.json"))
    parser.add_argument("--output", type=Path, help="保存机器可读 JSON 报告")
    parser.add_argument("--human-report", type=Path, help="生成带评分表的 HTML 人工评测报告")
    args = parser.parse_args()
    try:
        models = load_models(args)
        artifact_dir = args.human_report.with_name(args.human_report.stem + "_assets") if args.human_report else None
        if artifact_dir and artifact_dir.exists():
            shutil.rmtree(artifact_dir)
        report = run(args.cases, args.mock, models, artifact_dir)
        if args.human_report and artifact_dir:
            write_human_report(report, args.human_report, artifact_dir)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(f"evaluation failed: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["passed"] == report["cases"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
