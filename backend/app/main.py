"""FastAPI 入口与路由。"""

import subprocess
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import config as app_config
from . import code_locator, data_loader, database, llm, preset_registry, sandbox
from .config import settings

app = FastAPI(title="Quick SciPlot", version="0.1.0", description="LLM 驱动的快捷科研画图")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本地开发；开源版默认放开，公网部署需收紧
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.ensure_dirs()
database.init_db()

DATASETS: dict[str, dict] = {}  # id -> {"path": str, "summary": dict}


class GenerateRequest(BaseModel):
    dataset_id: str
    instruction: str
    preset: str | None = None


class EditRequest(BaseModel):
    code: str
    instruction: str
    dataset_id: str
    preset: str | None = None


class RunRequest(BaseModel):
    code: str
    dataset_id: str
    preset: str | None = None


class ParameterRequest(BaseModel):
    code: str
    dataset_id: str
    parameter: dict[str, object]
    value: str
    preset: str | None = None


class LLMConfigRequest(BaseModel):
    api_key: str | None = None
    base_url: str | None = None
    model: str | None = None
    mock: bool | None = None
    auto_repair_attempts: int | None = None
    sandbox_mode: str | None = None


class CombineRequest(BaseModel):
    dataset_ids: list[str]
    name: str | None = None


def _get_dataset(dataset_id: str) -> dict:
    ds = DATASETS.get(dataset_id)
    if ds is None:
        ds = database.get_dataset(dataset_id)
        if ds is not None and not Path(ds["path"]).exists():
            ds = None
        if ds is not None:
            DATASETS[dataset_id] = ds
    if not ds:
        raise HTTPException(status_code=404, detail="数据集不存在或已过期")
    return ds


@app.post("/api/datasets", summary="上传数据文件，返回摘要")
async def upload_dataset(
    files: list[UploadFile] | None = File(default=None),
    file: UploadFile | None = File(default=None),
):
    uploads = list(files or [])
    if file is not None:
        uploads.insert(0, file)
    if not uploads:
        raise HTTPException(status_code=400, detail="至少需要选择一个数据文件")
    if len(uploads) > 20:
        raise HTTPException(status_code=413, detail="一次最多导入 20 个文件")

    total_bytes = 0
    contents = []
    for upload in uploads:
        content = await upload.read()
        total_bytes += len(content)
        if len(content) > 200 * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"文件 {upload.filename or 'data'} 超过 200MB 限制")
        if total_bytes > 500 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="本次导入总大小不能超过 500MB")
        contents.append((upload, content))

    datasets = []
    for upload, content in contents:
        try:
            ds = data_loader.import_dataset(settings.data_dir, upload.filename or "data.csv", content)
        except data_loader.DataError as exc:
            raise HTTPException(status_code=400, detail=f"{upload.filename or 'data'}: {exc}") from exc
        ds["name"] = upload.filename or "data.csv"
        DATASETS[ds["id"]] = ds
        database.save_dataset(ds)
        datasets.append({"id": ds["id"], "name": ds["name"], "summary": ds["summary"]})

    response = {"datasets": datasets}
    if len(datasets) == 1:
        response.update({"id": datasets[0]["id"], "summary": datasets[0]["summary"]})
    return response


@app.post("/api/datasets/combine", summary="将多个数据集按行拼接为一个数据集")
def combine_datasets(req: CombineRequest):
    unique_ids = list(dict.fromkeys(req.dataset_ids))
    if len(unique_ids) < 2:
        raise HTTPException(status_code=400, detail="至少选择两个文件")
    if len(unique_ids) > 20:
        raise HTTPException(status_code=413, detail="一次最多合并 20 个文件")
    selected = [_get_dataset(dataset_id) for dataset_id in unique_ids]
    try:
        combined = data_loader.combine_datasets(settings.data_dir, selected)
    except data_loader.DataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if req.name and req.name.strip():
        combined["name"] = req.name.strip()
    DATASETS[combined["id"]] = combined
    database.save_dataset(combined)
    return {"id": combined["id"], "name": combined["name"], "summary": combined["summary"]}


@app.get("/api/datasets/{dataset_id}", summary="获取数据集摘要")
def get_dataset(dataset_id: str):
    ds = _get_dataset(dataset_id)
    return {"id": ds["id"], "summary": ds["summary"]}


@app.get("/api/presets", summary="获取可用绘图预设")
def get_presets():
    return {"presets": preset_registry.list_presets()}


@app.get("/api/config", summary="获取非敏感运行配置")
def get_config():
    return app_config.public_config()


@app.put("/api/config/llm", summary="更新本地 LLM 配置")
def update_llm_config(req: LLMConfigRequest):
    if req.base_url is not None and not req.base_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="LLM Base URL 必须以 http:// 或 https:// 开头")
    for value in (req.api_key, req.base_url, req.model):
        if value is not None and any(char in value for char in "\r\n"):
            raise HTTPException(status_code=400, detail="配置值不能包含换行符")
    if req.model is not None and not req.model.strip():
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if req.auto_repair_attempts is not None and not 0 <= req.auto_repair_attempts <= 3:
        raise HTTPException(status_code=400, detail="自动修复次数必须在 0 到 3 之间")
    if req.sandbox_mode is not None and req.sandbox_mode not in {"process", "docker"}:
        raise HTTPException(status_code=400, detail="沙箱模式只能是 process 或 docker")
    try:
        return app_config.update_runtime_config(
            api_key=req.api_key,
            base_url=req.base_url,
            model=req.model,
            mock=req.mock,
            auto_repair_attempts=req.auto_repair_attempts,
            sandbox_mode=req.sandbox_mode,
        )
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"保存本地配置失败: {exc}") from exc


@app.post("/api/config/test", summary="测试当前 LLM 连接")
def test_llm_config():
    try:
        return llm.test_connection()
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/plots/generate", summary="按指令生成并执行绘图代码")
def generate_plot(req: GenerateRequest):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    try:
        code = llm.generate_plot_code(req.instruction, ds["summary"], preset)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _execute_and_decorate(code, ds, preset, "generate")


@app.post("/api/plots/edit", summary="按指令修改已有代码并重新执行")
def edit_plot(req: EditRequest):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    try:
        code = llm.edit_plot_code(req.code, req.instruction, ds["summary"], preset)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _execute_and_decorate(code, ds, preset, "edit")


@app.post("/api/plots/run", summary="直接执行一段代码（编辑预览用）")
def run_plot(req: RunRequest):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    return _execute_and_decorate(req.code, ds, preset, "run")


@app.post("/api/plots/parameter", summary="应用一个可视化参数并重新执行")
def apply_plot_parameter(req: ParameterRequest):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    try:
        code = code_locator.apply_parameter(req.code, req.parameter, req.value)
    except code_locator.CodeEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _execute_and_decorate(code, ds, preset, "parameter")


@app.get("/api/plots/history/{dataset_id}", summary="获取数据集的绘图版本历史")
def get_plot_history(dataset_id: str):
    _get_dataset(dataset_id)
    return {"revisions": database.list_revisions(dataset_id)}


@app.post("/api/plots/history/{revision_id}/restore", summary="恢复一个绘图版本并生成新版本")
def restore_plot_revision(revision_id: str):
    revision = database.get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="绘图版本不存在")
    ds = _get_dataset(revision["dataset_id"])
    return _execute_and_decorate(revision["code"], ds, revision["preset"], "restore")


@app.get("/api/plots/revisions/{revision_id}/export/{format_name}", summary="导出绘图文件")
def export_plot_revision(revision_id: str, format_name: str):
    if format_name not in {"png", "svg", "pdf", "plotly"}:
        raise HTTPException(status_code=400, detail="只支持 png、svg、pdf、plotly")
    revision = database.get_revision(revision_id)
    if revision is None or not revision["success"]:
        raise HTTPException(status_code=404, detail="可导出的绘图版本不存在")

    data_root = settings.data_dir.resolve()
    output_dir = Path(revision["output_dir"]).resolve()
    try:
        output_dir.relative_to(data_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="导出文件不存在") from exc

    extensions = {"png": "png", "svg": "svg", "pdf": "pdf", "plotly": "plotly.json"}
    file_path = (output_dir / f"out.{extensions[format_name]}").resolve()
    if file_path.parent != output_dir or not file_path.is_file():
        raise HTTPException(status_code=404, detail="该版本没有此格式的导出文件")
    media_types = {
        "png": "image/png",
        "svg": "image/svg+xml",
        "pdf": "application/pdf",
        "plotly": "application/json",
    }
    filename_extensions = {"png": "png", "svg": "svg", "pdf": "pdf", "plotly": "plotly.json"}
    return FileResponse(
        file_path,
        media_type=media_types[format_name],
        filename=f"quick-sciplot-{revision_id[:8]}.{filename_extensions[format_name]}",
    )


def _normalize_preset(preset_id: str | None) -> str:
    try:
        return preset_registry.get_preset(preset_id).id
    except preset_registry.PresetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _execute_and_decorate(code: str, ds: dict, preset_id: str = "default", operation: str = "run") -> dict:
    out_dir = settings.data_dir / "outputs" / uuid.uuid4().hex
    repair_attempts = 0
    repair_error = ""
    try:
        result = sandbox.run_plot_code(code, Path(ds["path"]), out_dir, preset_id)
    except sandbox.SandboxUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except sandbox.SandboxSyntaxError as exc:
        if operation == "run" or settings.auto_repair_attempts <= 0:
            raise HTTPException(status_code=400, detail=f"代码语法错误: {exc}") from exc
        result = {
            "success": False,
            "returncode": 1,
            "stdout": "",
            "stderr": str(exc),
            "formats": [],
        }
    except sandbox.SandboxError as exc:
        raise HTTPException(status_code=400, detail=f"代码未通过安全检查: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=408, detail=f"执行超时（>{settings.sandbox_timeout}s）") from exc
    if not result["success"] and operation != "run":
        while repair_attempts < max(0, settings.auto_repair_attempts):
            try:
                code = llm.repair_plot_code(code, result.get("stderr", ""), ds["summary"], preset_id)
            except llm.LLMError as exc:
                repair_error = str(exc)
                break
            repair_attempts += 1
            try:
                result = sandbox.run_plot_code(code, Path(ds["path"]), out_dir, preset_id)
            except sandbox.SandboxError as exc:
                result = {
                    "success": False,
                    "returncode": 1,
                    "stdout": "",
                    "stderr": f"自动修复后的代码未通过安全检查: {exc}",
                    "formats": [],
                }
            except subprocess.TimeoutExpired:
                result = {
                    "success": False,
                    "returncode": -1,
                    "stdout": "",
                    "stderr": f"自动修复后的代码执行超时（>{settings.sandbox_timeout}s）",
                    "formats": [],
                }
            if result["success"]:
                break
    if repair_error:
        result["repair_error"] = repair_error
    revision_id = database.create_revision(
        dataset_id=ds["id"],
        code=code,
        preset=preset_id,
        operation=operation,
        output_dir=out_dir,
        success=result["success"],
        stderr=result.get("stderr", ""),
    )
    return {
        "code": code,
        "preset": preset_id,
        "revision_id": revision_id,
        "export_formats": result.get("formats", []),
        "repair_attempts": repair_attempts,
        "statements": code_locator.split_statements(code, ds["summary"]),
        "run": result,
    }
