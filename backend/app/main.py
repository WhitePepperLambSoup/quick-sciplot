"""FastAPI 入口与路由。"""

import asyncio
import hmac
import shutil
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, File, Header, HTTPException, Request, Response, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import (
    code_locator,
    compliance_checker,
    config as app_config,
    data_loader,
    database,
    figure_composer,
    figure_mimic,
    llm,
    preset_registry,
    sandbox,
    stats_annotator,
    visual_critic,
    visual_manipulator,
)
from .config import settings

app = FastAPI(title="Quick SciPlot", version="0.2.0", description="LLM 驱动的快捷科研画图")

SAFE_ORIGINS = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
    "tauri://localhost",
    # Tauri 2 serves the window from http://tauri.localhost on Windows unless
    # `useHttpsScheme` is enabled (then it is https://tauri.localhost).
    "http://tauri.localhost",
    "https://tauri.localhost",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=SAFE_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _hostname_from_host_header(value: str) -> str:
    """Extract the bare hostname from a Host header (handles ports and [::1])."""
    host = value.strip().lower()
    if host.startswith("["):
        return host[1:].split("]", 1)[0]
    if host.count(":") == 1:
        host = host.split(":", 1)[0]
    return host.rstrip(".")


@app.middleware("http")
async def reject_untrusted_host(request: Request, call_next):
    """Block DNS-rebinding requests: the Host header must name this machine."""
    allowed = {item.strip().lower() for item in settings.allowed_hosts}
    if _hostname_from_host_header(request.headers.get("host", "")) not in allowed:
        return JSONResponse(status_code=400, content={"detail": "不受信任的 Host 请求头"})
    return await call_next(request)


settings.ensure_dirs()
database.init_db()

DATASETS: dict[str, dict] = {}  # id -> {"path": str, "summary": dict}
_PLOT_SEMAPHORE = threading.BoundedSemaphore(max(1, settings.max_plot_concurrency))


def verify_session_token(
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
    session_cookie: str | None = Cookie(None, alias="quick_sciplot_session"),
) -> str:
    """验证客户端会话凭据。"""
    if not settings.require_auth:
        return x_session_token or session_cookie or ""
    candidate = x_session_token or session_cookie
    if not candidate or not hmac.compare_digest(candidate, app_config.SESSION_TOKEN):
        raise HTTPException(
            status_code=401,
            detail="未授权或无效的会话凭据 (Invalid or missing X-Session-Token)",
        )
    return candidate


class GenerateRequest(BaseModel):
    dataset_id: str = Field(..., max_length=128)
    instruction: str = Field(..., max_length=10000)
    preset: str | None = Field(None, max_length=128)


class EditRequest(BaseModel):
    code: str = Field(..., max_length=100000)
    instruction: str = Field(..., max_length=10000)
    dataset_id: str = Field(..., max_length=128)
    preset: str | None = Field(None, max_length=128)
    history: list[dict] | None = None


class RunRequest(BaseModel):
    code: str = Field(..., max_length=100000)
    dataset_id: str = Field(..., max_length=128)
    preset: str | None = Field(None, max_length=128)


class ParameterRequest(BaseModel):
    code: str = Field(..., max_length=100000)
    dataset_id: str = Field(..., max_length=128)
    parameter: dict[str, object]
    value: str = Field(..., max_length=1000)
    preset: str | None = Field(None, max_length=128)


class LLMConfigRequest(BaseModel):
    api_key: str | None = Field(None, max_length=512)
    base_url: str | None = Field(None, max_length=2048)
    model: str | None = Field(None, max_length=128)
    mock: bool | None = None
    auto_repair_attempts: int | None = None
    sandbox_mode: str | None = Field(None, max_length=64)
    send_data_values: bool | None = None


class CombineRequest(BaseModel):
    dataset_ids: list[str] = Field(..., max_length=50)
    name: str | None = Field(None, max_length=256)


class StatsAnnotationRequest(BaseModel):
    dataset_id: str = Field(..., max_length=128)
    code: str = Field(..., max_length=100000)
    group_col: str = Field(..., max_length=128)
    val_col: str = Field(..., max_length=128)
    pairs: list[list[str]] = Field(..., max_length=50)
    test_type: str = Field("auto", max_length=64)
    correction_method: str = Field("bonferroni", max_length=32)
    preset: str | None = Field(None, max_length=128)


class ComposeRequest(BaseModel):
    dataset_id: str = Field(..., max_length=128)
    layout: str = Field("1x2", max_length=64)
    panels: list[dict] = Field(..., max_length=16)
    preset: str | None = Field(None, max_length=128)


class MimicRequest(BaseModel):
    dataset_id: str = Field(..., max_length=128)
    reference_description: str = Field(..., max_length=10000)
    reference_image_b64: str | None = Field(None, max_length=25 * 1024 * 1024)
    preset: str | None = Field(None, max_length=128)


class CritiqueRequest(BaseModel):
    revision_id: str = Field(..., max_length=128)


class InteractiveAdjustRequest(BaseModel):
    dataset_id: str = Field(..., max_length=128)
    code: str = Field(..., max_length=100000)
    action: str = Field(..., max_length=64)  # "hline", "vline", "ylim", "xlim"
    params: dict[str, object]
    preset: str | None = Field(None, max_length=128)


def _get_dataset(dataset_id: str) -> dict:
    ds = DATASETS.get(dataset_id)
    if ds is not None:
        safe_path = database.safe_dataset_path(settings.data_dir, ds.get("path", ""))
        if safe_path is None:
            DATASETS.pop(dataset_id, None)
            ds = None
        else:
            ds = {**ds, "path": str(safe_path)}
            DATASETS[dataset_id] = ds
    if ds is None:
        ds = database.get_dataset(dataset_id)
        if ds is not None:
            safe_path = database.safe_dataset_path(settings.data_dir, ds.get("path", ""))
        else:
            safe_path = None
        if safe_path is None:
            ds = None
        else:
            ds = {**ds, "path": str(safe_path)}
            DATASETS[dataset_id] = ds
    if not ds:
        raise HTTPException(status_code=404, detail="数据集不存在或已过期")
    return ds


def _public_dataset(dataset: dict) -> dict:
    """Remove internal filesystem paths before returning dataset metadata."""
    return {
        "id": dataset["id"],
        "name": dataset.get("name", ""),
        "summary": dataset.get("summary", {}),
    }


def _set_session_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        "quick_sciplot_session",
        token,
        httponly=True,
        samesite="strict",
        secure=False,
        max_age=60 * 60 * 24 * 30,
        path="/api",
    )


async def _write_upload_to_temp(
    upload: UploadFile,
    target_dir: Path,
    max_bytes: int,
    total_limit: int,
    current_total: int,
) -> tuple[Path, int]:
    """流式写入临时文件，避免在内存中累积完整上传内容。"""
    target_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(upload.filename or "data").suffix.lower()
    if suffix not in data_loader.ALLOWED_EXTS:
        suffix = ".upload"
    handle = tempfile.NamedTemporaryFile(prefix=".upload-", suffix=suffix, dir=target_dir, delete=False)
    temp_path = Path(handle.name)
    written = 0
    chunk_size = 64 * 1024
    try:
        with handle:
            while True:
                chunk = await upload.read(chunk_size)
                if not chunk:
                    break
                next_size = written + len(chunk)
                if next_size > max_bytes:
                    raise HTTPException(
                        status_code=413,
                        detail=f"文件 {upload.filename or 'data'} 超过 {max_bytes // (1024 * 1024)}MB 限制",
                    )
                if current_total + next_size > total_limit:
                    raise HTTPException(
                        status_code=413,
                        detail=(
                            "本次导入总大小不能超过 "
                            f"{total_limit // (1024 * 1024)}MB"
                        ),
                    )
                handle.write(chunk)
                written = next_size
        return temp_path, written
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise


def _discard_imported_dataset(dataset: dict) -> None:
    """Remove a dataset created by the current batch after a later failure."""
    dataset_id = dataset.get("id")
    if dataset_id:
        DATASETS.pop(dataset_id, None)
        try:
            database.delete_dataset(dataset_id)
        except Exception:
            # Best-effort rollback continues with direct file cleanup below.
            pass
    raw_path = dataset.get("path")
    if raw_path:
        try:
            Path(raw_path).unlink(missing_ok=True)
        except OSError:
            pass


@app.post("/api/datasets", summary="上传数据文件，返回摘要")
async def upload_dataset(
    files: list[UploadFile] | None = File(default=None),
    file: UploadFile | None = File(default=None),
    _token: str = Depends(verify_session_token),
):
    uploads = list(files or [])
    if file is not None:
        uploads.insert(0, file)
    if not uploads:
        raise HTTPException(status_code=400, detail="至少需要选择一个数据文件")
    if len(uploads) > 20:
        raise HTTPException(status_code=413, detail="一次最多导入 20 个文件")

    total_bytes = 0
    datasets = []
    created_datasets: list[dict] = []
    try:
        for upload in uploads:
            temp_path, file_size = await _write_upload_to_temp(
                upload,
                settings.data_dir / ".uploads",
                max(1, int(settings.max_import_bytes)),
                max(1, int(settings.max_total_import_bytes)),
                total_bytes,
            )
            total_bytes += file_size
            try:
                ds = await asyncio.to_thread(
                    data_loader.import_dataset_file,
                    settings.data_dir,
                    upload.filename or "data.csv",
                    temp_path,
                )
            except data_loader.DataBusyError as exc:
                raise HTTPException(status_code=429, detail=str(exc)) from exc
            except data_loader.DataError as exc:
                raise HTTPException(status_code=400, detail=f"{upload.filename or 'data'}: {exc}") from exc
            finally:
                temp_path.unlink(missing_ok=True)
            ds["name"] = upload.filename or "data.csv"
            created_datasets.append(ds)
            DATASETS[ds["id"]] = ds
            database.save_dataset(ds)
            datasets.append({"id": ds["id"], "name": ds["name"], "summary": ds["summary"]})
    except Exception:
        for dataset in reversed(created_datasets):
            _discard_imported_dataset(dataset)
        raise

    response = {"datasets": datasets}
    if len(datasets) == 1:
        response.update({"id": datasets[0]["id"], "summary": datasets[0]["summary"]})
    return response


@app.post("/api/datasets/combine", summary="将多个数据集按行拼接为一个数据集")
def combine_datasets(req: CombineRequest, _token: str = Depends(verify_session_token)):
    unique_ids = list(dict.fromkeys(req.dataset_ids))
    if len(unique_ids) < 2:
        raise HTTPException(status_code=400, detail="至少选择两个文件")
    if len(unique_ids) > 20:
        raise HTTPException(status_code=413, detail="一次最多合并 20 个文件")
    selected = [_get_dataset(dataset_id) for dataset_id in unique_ids]
    try:
        combined = data_loader.combine_datasets(settings.data_dir, selected)
    except data_loader.DataBusyError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except data_loader.DataError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if req.name and req.name.strip():
        combined["name"] = req.name.strip()
    DATASETS[combined["id"]] = combined
    database.save_dataset(combined)
    return {"id": combined["id"], "name": combined["name"], "summary": combined["summary"]}


@app.get("/api/datasets", summary="获取所有已持久化的数据集列表")
def list_datasets(_token: str = Depends(verify_session_token)):
    stored_datasets = database.list_datasets(include_path=True)
    for ds in stored_datasets:
        DATASETS[ds["id"]] = ds
    return {"datasets": [_public_dataset(ds) for ds in stored_datasets]}


@app.delete("/api/datasets/{dataset_id}", summary="删除数据集及其历史记录")
def delete_dataset(dataset_id: str, _token: str = Depends(verify_session_token)):
    DATASETS.pop(dataset_id, None)
    success = database.delete_dataset(dataset_id)
    if not success:
        raise HTTPException(status_code=404, detail="数据集不存在")
    return {"ok": True, "id": dataset_id}


@app.get("/api/datasets/{dataset_id}", summary="获取数据集摘要")
def get_dataset(dataset_id: str, _token: str = Depends(verify_session_token)):
    ds = _get_dataset(dataset_id)
    return {"id": ds["id"], "summary": ds["summary"]}


@app.get("/api/presets", summary="获取可用绘图预设")
def get_presets():
    return {"presets": preset_registry.list_presets()}


@app.get("/api/config", summary="获取非敏感运行配置")
def get_config(
    request: Request,
    response: Response,
    x_session_token: str | None = Header(None, alias="X-Session-Token"),
    session_cookie: str | None = Cookie(None, alias="quick_sciplot_session"),
):
    client_host = request.client.host if request.client else ""
    candidate = x_session_token or session_cookie
    if settings.require_auth and client_host in ("127.0.0.1", "::1", "localhost", "testclient"):
        if not candidate or not hmac.compare_digest(candidate, app_config.SESSION_TOKEN):
            _set_session_cookie(response, app_config.SESSION_TOKEN)
    return app_config.public_config()


@app.post("/api/auth/rotate-token", summary="轮换本地会话凭据")
def rotate_token(response: Response, _token: str = Depends(verify_session_token)):
    new_token = app_config.rotate_session_token()
    _set_session_cookie(response, new_token)
    return {"ok": True}


@app.put("/api/config/llm", summary="更新本地 LLM 配置")
def update_llm_config(req: LLMConfigRequest, _token: str = Depends(verify_session_token)):
    if req.base_url is not None:
        try:
            app_config.validate_safe_llm_url(req.base_url, allow_local_network=settings.allow_local_network_llm)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
    for value in (req.api_key, req.base_url, req.model):
        if value is not None and any(char in value for char in "\r\n"):
            raise HTTPException(status_code=400, detail="配置值不能包含换行符")
    if req.model is not None and not req.model.strip():
        raise HTTPException(status_code=400, detail="模型名称不能为空")
    if req.auto_repair_attempts is not None and not 0 <= req.auto_repair_attempts <= 3:
        raise HTTPException(status_code=400, detail="自动修复次数必须在 0 到 3 之间")
    if req.sandbox_mode is not None and req.sandbox_mode not in {"process", "docker"}:
        raise HTTPException(status_code=400, detail="沙箱模式只能是 process 或 docker")
    if req.sandbox_mode == "process" and not sandbox.process_sandbox_allowed():
        raise HTTPException(status_code=400, detail="process 沙箱仅允许在显式设置 ALLOW_UNSAFE_PROCESS_SANDBOX=1 时启用")
    try:
        return app_config.update_runtime_config(
            api_key=req.api_key,
            base_url=req.base_url,
            model=req.model,
            mock=req.mock,
            auto_repair_attempts=req.auto_repair_attempts,
            sandbox_mode=req.sandbox_mode,
            send_data_values=req.send_data_values,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except OSError as exc:
        raise HTTPException(status_code=500, detail=f"保存本地配置失败: {exc}") from exc


@app.post("/api/config/test", summary="测试当前 LLM 连接")
def test_llm_config(_token: str = Depends(verify_session_token)):
    try:
        return llm.test_connection()
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@app.post("/api/plots/generate", summary="按指令生成并执行绘图代码")
def generate_plot(req: GenerateRequest, _token: str = Depends(verify_session_token)):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    try:
        code = llm.generate_plot_code(req.instruction, ds["summary"], preset)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _execute_and_decorate(code, ds, preset, "generate")


@app.post("/api/plots/edit", summary="按指令修改已有代码并重新执行")
def edit_plot(req: EditRequest, _token: str = Depends(verify_session_token)):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    try:
        code = llm.edit_plot_code(req.code, req.instruction, ds["summary"], preset, history=req.history)
    except llm.LLMError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _execute_and_decorate(code, ds, preset, "edit")


@app.post("/api/plots/run", summary="直接执行一段代码（编辑预览用）")
def run_plot(req: RunRequest, _token: str = Depends(verify_session_token)):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    return _execute_and_decorate(req.code, ds, preset, "run")


@app.post("/api/plots/parameter", summary="应用一个可视化参数并重新执行")
def apply_plot_parameter(req: ParameterRequest, _token: str = Depends(verify_session_token)):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    try:
        code = code_locator.apply_parameter(req.code, req.parameter, req.value)
    except code_locator.CodeEditError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _execute_and_decorate(code, ds, preset, "parameter")


@app.post("/api/plots/stats", summary="执行科学假设检验并向图表中注入显著性标尺与星号")
def annotate_stats(req: StatsAnnotationRequest, _token: str = Depends(verify_session_token)):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    try:
        df = data_loader.load_dataframe(ds["path"])
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"读取数据集失败: {exc}") from exc
    converted_pairs = [(pair[0], pair[1]) for pair in req.pairs if len(pair) >= 2]
    if not converted_pairs:
        raise HTTPException(status_code=400, detail="至少需要提供一组对比分组")
    if req.correction_method not in {"bonferroni", "fdr_bh"}:
        raise HTTPException(status_code=400, detail="多重比较校正方式只能是 bonferroni 或 fdr_bh")
    try:
        annotated_code, results = stats_annotator.inject_stat_brackets(
            req.code,
            df,
            req.group_col,
            req.val_col,
            converted_pairs,
            req.test_type,
            correction_method=req.correction_method,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"统计标尺生成失败: {exc}") from exc

    decorated = _execute_and_decorate(annotated_code, ds, preset, "stats")
    decorated["stats_results"] = results
    return decorated


@app.post("/api/plots/compose", summary="多子图排版编排器：合成 Figure 1A, 1B 组合大图")
def compose_plot(req: ComposeRequest, _token: str = Depends(verify_session_token)):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    if not req.panels:
        raise HTTPException(status_code=400, detail="至少需要提供一个子图配置")
    try:
        composed_code = figure_composer.compose_multipanel_figure(req.panels, layout=req.layout)
    except figure_composer.LayoutValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"拼图生成失败: {exc}") from exc
    return _execute_and_decorate(composed_code, ds, preset, "compose")


@app.post("/api/plots/mimic", summary="顶刊论文图以图生图复刻：逆向提取参考图版式与配色")
def mimic_plot(req: MimicRequest, _token: str = Depends(verify_session_token)):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    try:
        code = figure_mimic.generate_mimic_code(
            req.reference_image_b64, req.reference_description, ds["summary"], preset
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return _execute_and_decorate(code, ds, preset, "mimic")


@app.post("/api/plots/interactive-adjust", summary="交互式图像修正：直接拖拽图表中点或线逆向更新代码并重新渲染")
def interactive_adjust_plot(req: InteractiveAdjustRequest, _token: str = Depends(verify_session_token)):
    ds = _get_dataset(req.dataset_id)
    preset = _normalize_preset(req.preset)
    try:
        updated_code = visual_manipulator.apply_visual_action(req.code, req.action, req.params)
    except visual_manipulator.ManipulationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"交互修正代码失败: {exc}") from exc
    return _execute_and_decorate(updated_code, ds, preset, "interactive")


@app.post("/api/plots/critique", summary="视觉排版质检 Agent：审查文字重叠、图例遮挡与布局自愈建议")
def critique_plot(req: CritiqueRequest, _token: str = Depends(verify_session_token)):
    revision = database.get_revision(req.revision_id)
    if revision is None or not revision["success"]:
        raise HTTPException(status_code=404, detail="未找到有效的绘图版本进行质检")
    out_dir = _revision_output_dir(revision)
    png_path = out_dir / "out.png"
    return visual_critic.critique_figure_image(png_path, revision["code"])


@app.get("/api/plots/revisions/{revision_id}/compliance/{journal}", summary="顶刊投稿合规检查：Nature/IEEE/Cell 尺寸与矢量检查")
def check_compliance(revision_id: str, journal: str = "nature", _token: str = Depends(verify_session_token)):
    revision = database.get_revision(revision_id)
    if revision is None or not revision["success"]:
        raise HTTPException(status_code=404, detail="未找到有效的绘图版本进行合规检查")
    out_dir = _revision_output_dir(revision)
    return compliance_checker.check_journal_compliance(out_dir, journal)



@app.get("/api/plots/history/{dataset_id}", summary="获取数据集的绘图版本历史")
def get_plot_history(dataset_id: str, _token: str = Depends(verify_session_token)):
    _get_dataset(dataset_id)
    return {"revisions": database.list_revisions(dataset_id)}


@app.post("/api/plots/history/{revision_id}/restore", summary="恢复一个绘图版本并生成新版本")
def restore_plot_revision(revision_id: str, _token: str = Depends(verify_session_token)):
    revision = database.get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="绘图版本不存在")
    ds = _get_dataset(revision["dataset_id"])
    return _execute_and_decorate(revision["code"], ds, revision["preset"], "restore")


@app.get("/api/plots/history/{revision_id}/detail", summary="获取某个绘图版本的详细代码与参数")
def get_revision_detail(revision_id: str, _token: str = Depends(verify_session_token)):
    revision = database.get_revision(revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="绘图版本不存在")
    return database.public_revision(revision)


@app.get("/api/plots/revisions/{revision_id}/export/{format_name}", summary="导出绘图文件")
def export_plot_revision(revision_id: str, format_name: str, _token: str = Depends(verify_session_token)):
    if format_name not in {"png", "svg", "pdf", "eps", "plotly"}:
        raise HTTPException(status_code=400, detail="只支持 png、svg、pdf、eps、plotly")
    revision = database.get_revision(revision_id)
    if revision is None or not revision["success"]:
        raise HTTPException(status_code=404, detail="可导出的绘图版本不存在")

    output_dir = _revision_output_dir(revision)

    extensions = {"png": "png", "svg": "svg", "pdf": "pdf", "eps": "eps", "plotly": "plotly.json"}
    file_path = (output_dir / f"out.{extensions[format_name]}").resolve()
    if file_path.parent != output_dir or not file_path.is_file():
        raise HTTPException(status_code=404, detail="该版本没有此格式的导出文件")
    media_types = {
        "png": "image/png",
        "svg": "image/svg+xml",
        "pdf": "application/pdf",
        "eps": "application/postscript",
        "plotly": "application/json",
    }
    filename_extensions = {"png": "png", "svg": "svg", "pdf": "pdf", "eps": "eps", "plotly": "plotly.json"}
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


def _revision_output_dir(revision: dict) -> Path:
    """Resolve a revision output path while enforcing the outputs boundary."""
    outputs_root = (settings.data_dir / "outputs").resolve()
    try:
        output_dir = Path(revision["output_dir"]).resolve()
        output_dir.relative_to(outputs_root)
        if output_dir == outputs_root or output_dir.parent != outputs_root:
            raise ValueError("revision output must be a direct outputs child")
    except (KeyError, OSError, ValueError) as exc:
        raise HTTPException(status_code=404, detail="绘图产物不存在") from exc
    if not output_dir.is_dir():
        raise HTTPException(status_code=404, detail="绘图产物不存在")
    return output_dir


def _execute_and_decorate(code: str, ds: dict, preset_id: str = "default", operation: str = "run") -> dict:
    if not _PLOT_SEMAPHORE.acquire(blocking=False):
        raise HTTPException(status_code=429, detail="绘图执行资源繁忙，请稍后重试")

    out_dir = settings.data_dir / "outputs" / uuid.uuid4().hex
    # Registered before the directory exists so a concurrent request's orphan
    # sweep (database.prune_revisions) cannot delete it while we render.
    database.mark_output_inflight(out_dir)
    repair_attempts = 0
    repair_error = ""
    revision_id: str | None = None
    try:
        try:
            result = sandbox.run_plot_code(code, Path(ds["path"]), out_dir, preset_id)
        except sandbox.SandboxUnavailableError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except sandbox.SandboxSyntaxError as exc:
            if operation in ("run", "parameter") or settings.auto_repair_attempts <= 0:
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
        if not result["success"] and operation not in ("run", "parameter", "compose", "stats"):
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
        budget = database.prune_revisions(
            max_revisions_per_dataset=settings.max_revisions_per_dataset,
            max_output_bytes=settings.max_output_bytes,
        )
        if budget["remaining_bytes"] > settings.max_output_bytes:
            database.delete_revision(revision_id)
            revision_id = None
            raise HTTPException(status_code=507, detail="绘图历史超出磁盘配额，请删除旧数据后重试")
        return {
            "code": code,
            "preset": preset_id,
            "revision_id": revision_id,
            "export_formats": result.get("formats", []),
            "repair_attempts": repair_attempts,
            "statements": code_locator.split_statements(code, ds["summary"]),
            "meta": result.get("meta"),
            "inspected": visual_manipulator.inspect_code_elements(code),
            "run": result,
        }
    finally:
        if revision_id is None:
            shutil.rmtree(out_dir, ignore_errors=True)
        database.release_output_inflight(out_dir)
        _PLOT_SEMAPHORE.release()
