"""FastAPI 入口与路由。"""

import subprocess
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel

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
async def upload_dataset(file: UploadFile = File(...)):
    content = await file.read()
    if len(content) > 200 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="文件超过 200MB 限制")
    try:
        ds = data_loader.import_dataset(settings.data_dir, file.filename or "data.csv", content)
    except data_loader.DataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    DATASETS[ds["id"]] = ds
    database.save_dataset(ds)
    return {"id": ds["id"], "summary": ds["summary"]}


@app.get("/api/datasets/{dataset_id}", summary="获取数据集摘要")
def get_dataset(dataset_id: str):
    ds = _get_dataset(dataset_id)
    return {"id": ds["id"], "summary": ds["summary"]}


@app.get("/api/presets", summary="获取可用绘图预设")
def get_presets():
    return {"presets": preset_registry.list_presets()}


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
    if format_name not in {"png", "svg", "pdf"}:
        raise HTTPException(status_code=400, detail="只支持 png、svg、pdf")
    revision = database.get_revision(revision_id)
    if revision is None or not revision["success"]:
        raise HTTPException(status_code=404, detail="可导出的绘图版本不存在")

    data_root = settings.data_dir.resolve()
    output_dir = Path(revision["output_dir"]).resolve()
    try:
        output_dir.relative_to(data_root)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="导出文件不存在") from exc

    file_path = (output_dir / f"out.{format_name}").resolve()
    if file_path.parent != output_dir or not file_path.is_file():
        raise HTTPException(status_code=404, detail="该版本没有此格式的导出文件")
    media_types = {"png": "image/png", "svg": "image/svg+xml", "pdf": "application/pdf"}
    return FileResponse(
        file_path,
        media_type=media_types[format_name],
        filename=f"quick-sciplot-{revision_id[:8]}.{format_name}",
    )


def _normalize_preset(preset_id: str | None) -> str:
    try:
        return preset_registry.get_preset(preset_id).id
    except preset_registry.PresetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _execute_and_decorate(code: str, ds: dict, preset_id: str = "default", operation: str = "run") -> dict:
    out_dir = settings.data_dir / "outputs" / uuid.uuid4().hex
    try:
        result = sandbox.run_plot_code(code, Path(ds["path"]), out_dir, preset_id)
    except sandbox.SandboxError as exc:
        raise HTTPException(status_code=400, detail=f"代码未通过安全检查: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=408, detail=f"执行超时（>{settings.sandbox_timeout}s）") from exc
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
        "statements": code_locator.split_statements(code),
        "run": result,
    }
