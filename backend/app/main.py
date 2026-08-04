"""FastAPI 入口与路由。"""

import subprocess
import uuid
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import code_locator, data_loader, llm, preset_registry, sandbox
from .config import settings

app = FastAPI(title="Quick SciPlot", version="0.1.0", description="LLM 驱动的快捷科研画图")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 本地开发；开源版默认放开，公网部署需收紧
    allow_methods=["*"],
    allow_headers=["*"],
)

settings.ensure_dirs()

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


def _get_dataset(dataset_id: str) -> dict:
    ds = DATASETS.get(dataset_id)
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
    return _execute_and_decorate(code, ds, preset)


@app.post("/api/plots/edit", summary="按指令修改已有代码并重新执行")
def edit_plot(req: EditRequest):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    try:
        code = llm.edit_plot_code(req.code, req.instruction, ds["summary"], preset)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _execute_and_decorate(code, ds, preset)


@app.post("/api/plots/run", summary="直接执行一段代码（编辑预览用）")
def run_plot(req: RunRequest):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    return _execute_and_decorate(req.code, ds, preset)


def _normalize_preset(preset_id: str | None) -> str:
    try:
        return preset_registry.get_preset(preset_id).id
    except preset_registry.PresetError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def _execute_and_decorate(code: str, ds: dict, preset_id: str = "default") -> dict:
    out_dir = settings.data_dir / "outputs" / uuid.uuid4().hex
    try:
        result = sandbox.run_plot_code(code, Path(ds["path"]), out_dir, preset_id)
    except sandbox.SandboxError as exc:
        raise HTTPException(status_code=400, detail=f"代码未通过安全检查: {exc}") from exc
    except subprocess.TimeoutExpired as exc:
        raise HTTPException(status_code=408, detail=f"执行超时（>{settings.sandbox_timeout}s）") from exc
    return {
        "code": code,
        "preset": preset_id,
        "statements": code_locator.split_statements(code),
        "run": result,
    }
