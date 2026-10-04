"""Regression tests for the security and correctness hardening pass."""

import asyncio
import io
import os
import socket
import sys
import threading
from pathlib import Path

import pandas as pd
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

from app import compliance_checker, config as app_config, data_loader, database, llm, main, sandbox, stats_annotator
from app.config import SESSION_TOKEN, settings, validate_safe_llm_url
from app.main import app


AUTH_HEADERS = {"X-Session-Token": SESSION_TOKEN}
AUTH_CLIENT = TestClient(app, headers=AUTH_HEADERS)


class _ChunkedUpload:
    def __init__(self, chunks: list[bytes], filename: str = "data.csv"):
        self.filename = filename
        self._chunks = iter(chunks)

    async def read(self, _chunk_size: int) -> bytes:
        return next(self._chunks, b"")


def test_config_does_not_disclose_session_token():
    response = TestClient(app).get("/api/config")

    assert response.status_code == 200
    assert "session_token" not in response.json()


def test_query_string_token_is_not_accepted_for_protected_routes():
    response = TestClient(app).get(f"/api/datasets?token={SESSION_TOKEN}")

    assert response.status_code == 401


def test_public_dataset_listing_does_not_expose_absolute_path():
    response = AUTH_CLIENT.post(
        "/api/datasets",
        files={"file": ("security.csv", io.BytesIO(b"x,y\n1,2\n"), "text/csv")},
    )
    assert response.status_code == 200, response.text

    listing = AUTH_CLIENT.get("/api/datasets")
    assert listing.status_code == 200
    assert all("path" not in item for item in listing.json()["datasets"])


def test_revision_detail_does_not_expose_output_directory():
    upload = AUTH_CLIENT.post(
        "/api/datasets",
        files={"file": ("revision.csv", io.BytesIO(b"x,y\n1,2\n2,3\n"), "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    dataset_id = upload.json()["id"]
    run = AUTH_CLIENT.post(
        "/api/plots/run",
        json={
            "dataset_id": dataset_id,
            "code": "import matplotlib.pyplot as plt\nplt.plot(df['x'], df['y'])",
        },
    )
    assert run.status_code == 200, run.text

    detail = AUTH_CLIENT.get(f"/api/plots/history/{run.json()['revision_id']}/detail")
    assert detail.status_code == 200
    assert "output_dir" not in detail.json()


def test_process_sandbox_requires_explicit_opt_in(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "sandbox_mode", "process")
    monkeypatch.setattr(settings, "allow_unsafe_process_sandbox", False)

    with __import__("pytest").raises(sandbox.SandboxUnavailableError):
        sandbox.run_plot_code(
            "import matplotlib.pyplot as plt\nplt.plot([1], [1])",
            tmp_path / "data.csv",
            tmp_path / "output",
        )


def test_sandbox_blocks_runtime_aliases():
    for code in ("_os.system('whoami')", "_sys.modules", "_sys._getframe()"):
        with __import__("pytest").raises(sandbox.SandboxError):
            sandbox.validate_script(code)


def test_ssrf_rejects_noncanonical_numeric_host():
    with __import__("pytest").raises(ValueError):
        validate_safe_llm_url("http://2130706433/v1")


def test_ssrf_rejects_dns_name_resolving_to_loopback(monkeypatch):
    def fake_getaddrinfo(*args, **kwargs):
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 80))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with __import__("pytest").raises(ValueError):
        validate_safe_llm_url("https://llm.example.test/v1")


def test_initial_llm_config_fails_closed_when_api_key_is_configured(monkeypatch):
    monkeypatch.setattr(settings, "llm_api_key", "configured")
    monkeypatch.setattr(settings, "llm_base_url", "http://127.0.0.1:8000/v1")

    with pytest.raises(RuntimeError, match="LLM_BASE_URL"):
        app_config.validate_initial_settings()


def test_compliance_missing_dpi_fails_overall_report(tmp_path):
    image_path = tmp_path / "out.png"
    Image.new("RGB", (1050, 750), "white").save(image_path)
    (tmp_path / "out.svg").write_text("<svg></svg>", encoding="utf-8")

    report = compliance_checker.check_journal_compliance(tmp_path, "nature")

    assert report["passed"] is False
    dpi_checks = [check for check in report["checks"] if "DPI" in check["item"]]
    assert dpi_checks and dpi_checks[0]["passed"] is False


def test_stats_stars_use_selected_multiple_comparison_correction(monkeypatch):
    def fake_compare(*args, **kwargs):
        return {
            "group_a": "A",
            "group_b": "B",
            "test_name": "test",
            "statistic": 1.0,
            "p_value": 0.04,
            "p_formatted": "p = 0.0400",
            "stars": "*",
            "mean_a": 1.0,
            "mean_b": 2.0,
            "cohens_d": 1.0,
        }

    monkeypatch.setattr(stats_annotator, "compare_groups", fake_compare)
    df = pd.DataFrame({"group": ["A", "B", "C"], "value": [1, 2, 3]})

    _, results = stats_annotator.inject_stat_brackets(
        "import matplotlib.pyplot as plt\nplt.plot([1], [1])",
        df,
        "group",
        "value",
        [("A", "B"), ("A", "C")],
        correction_method="bonferroni",
    )

    assert results[0]["p_value"] == 0.04
    assert results[0]["p_adjusted"] == 0.08
    assert results[0]["raw_stars"] == "*"
    assert results[0]["stars"] == "ns"


def test_runner_stops_when_log_output_exceeds_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "MAX_LOG_BYTES", 1024)
    script = tmp_path / "emit.py"
    script.write_text("print('x' * 4096)", encoding="utf-8")

    result = sandbox._run_command(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=os.environ.copy(),
    )

    assert result.returncode == -1
    assert "日志输出超过大小限制" in result.stderr


def test_runner_stops_when_artifact_exceeds_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "MAX_OUTPUT_FILE_BYTES", 1024)
    artifact = tmp_path / "out.png"
    script = tmp_path / "write_artifact.py"
    script.write_text(
        "from pathlib import Path\n"
        f"Path({str(artifact)!r}).write_bytes(b'x' * 4096)\n",
        encoding="utf-8",
    )

    result = sandbox._run_command(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=os.environ.copy(),
        monitored_paths=[artifact],
    )

    assert result.returncode == -1
    assert "输出文件超过大小限制" in result.stderr


def test_upload_stream_writes_to_temp_file_without_buffering_all_bytes(tmp_path):
    upload = _ChunkedUpload([b"x,y\n", b"1,2\n"])

    path, size = asyncio.run(main._write_upload_to_temp(upload, tmp_path, 1024, 2048, 0))

    assert path.parent == tmp_path
    assert path.read_bytes() == b"x,y\n1,2\n"
    assert size == 8


def test_upload_stream_removes_partial_file_when_limit_is_exceeded(tmp_path):
    upload = _ChunkedUpload([b"x" * 8, b"y" * 8])

    with pytest.raises(HTTPException, match="超过"):
        asyncio.run(main._write_upload_to_temp(upload, tmp_path, 10, 100, 0))

    assert list(tmp_path.iterdir()) == []


def test_upload_route_uses_configured_import_byte_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_import_bytes", 4)

    response = AUTH_CLIENT.post(
        "/api/datasets",
        files={"file": ("configured-limit.csv", io.BytesIO(b"x,y\n1,2\n"), "text/csv")},
    )

    assert response.status_code == 413
    assert "configured-limit.csv" in response.json()["detail"]


def test_upload_route_uses_configured_batch_byte_limit(monkeypatch):
    monkeypatch.setattr(settings, "max_import_bytes", 1024)
    monkeypatch.setattr(settings, "max_total_import_bytes", 12, raising=False)

    response = AUTH_CLIENT.post(
        "/api/datasets",
        files=[
            ("files", ("first.csv", io.BytesIO(b"x,y\n1,2\n"), "text/csv")),
            ("files", ("second.csv", io.BytesIO(b"x,y\n3,4\n"), "text/csv")),
        ],
    )

    assert response.status_code == 413
    assert "总大小" in response.json()["detail"]


def test_batch_upload_rolls_back_previous_datasets_when_a_later_file_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    main.DATASETS.clear()
    database.init_db()

    response = AUTH_CLIENT.post(
        "/api/datasets",
        files=[
            ("files", ("valid.csv", io.BytesIO(b"x,y\n1,2\n"), "text/csv")),
            ("files", ("unsupported.exe", io.BytesIO(b"not a dataset"), "application/octet-stream")),
        ],
    )

    assert response.status_code == 400
    assert database.list_datasets() == []
    assert not list(tmp_path.glob("*.csv"))


def test_runtime_config_does_not_mutate_memory_when_persistence_fails(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(app_config.settings, "llm_model", "before")

    def fail_persist(_updates):
        raise OSError("disk full")

    monkeypatch.setattr(app_config, "_persist_env", fail_persist)

    with pytest.raises(OSError, match="disk full"):
        app_config.update_runtime_config(model="after")

    assert app_config.settings.llm_model == "before"


def test_runtime_config_rejects_unsafe_values_before_persistence(monkeypatch):
    persisted: list[dict[str, str]] = []
    monkeypatch.setattr(app_config, "_persist_env", persisted.append)

    with pytest.raises(ValueError, match="换行"):
        app_config.update_runtime_config(api_key="secret\nINJECTED=1")
    with pytest.raises(ValueError, match="自动修复次数"):
        app_config.update_runtime_config(auto_repair_attempts=99)
    with pytest.raises(ValueError, match="沙箱模式"):
        app_config.update_runtime_config(sandbox_mode="unknown")
    with pytest.raises(ValueError, match="禁止"):
        app_config.update_runtime_config(base_url="http://127.0.0.1:8000/v1")

    assert persisted == []


def test_json_array_parser_rejects_configured_nesting_limit(tmp_path, monkeypatch):
    source = tmp_path / "nested.json"
    source.write_text("[[[1]]]", encoding="utf-8")
    monkeypatch.setattr(settings, "max_json_nesting", 2, raising=False)

    with pytest.raises(data_loader.DataError, match="嵌套深度"):
        data_loader.load_dataframe(source)


def test_runner_stops_when_untracked_output_exceeds_directory_limit(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "MAX_OUTPUT_DIR_BYTES", 1024, raising=False)
    artifact = tmp_path / "out.png"
    script = tmp_path / "write_untracked_artifact.py"
    script.write_text(
        "from pathlib import Path\n"
        f"Path({str(tmp_path / 'untracked.bin')!r}).write_bytes(b'x' * 4096)\n",
        encoding="utf-8",
    )

    result = sandbox._run_command(
        [sys.executable, str(script)],
        cwd=tmp_path,
        env=os.environ.copy(),
        monitored_paths=[artifact],
    )

    assert result.returncode == -1
    assert "输出目录超过大小限制" in result.stderr


def test_frozen_worker_monitors_individual_output_limits(monkeypatch, tmp_path):
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("x,y\n1,2\n", encoding="utf-8")
    captured: dict[str, object] = {}

    def fake_run_command(command, *, cwd, env, monitored_paths=None):
        captured["monitored_paths"] = monitored_paths
        return __import__("subprocess").CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(sandbox, "_run_command", fake_run_command)
    sandbox._run_frozen_worker(
        "import matplotlib.pyplot as plt\nplt.plot([1], [1])",
        csv_path,
        output_dir,
        "default",
        sandbox._output_paths(output_dir),
    )

    assert captured["monitored_paths"] == list(sandbox._output_paths(output_dir).values())


def test_json_import_rejects_configured_size_limit(tmp_path, monkeypatch):
    source = tmp_path / "large.json"
    source.write_text('{"values": [1, 2, 3]}', encoding="utf-8")
    monkeypatch.setattr(settings, "max_json_bytes", 8, raising=False)

    with pytest.raises(data_loader.DataError, match="JSON"):
        data_loader.load_dataframe(source)


def test_create_dataset_removes_partial_csv_when_write_fails(monkeypatch, tmp_path):
    frame = pd.DataFrame({"x": [1], "y": [2]})

    def fail_after_partial_write(self, path_or_buf, *args, **kwargs):
        if hasattr(path_or_buf, "write"):
            path_or_buf.write("x,y\n1,2\n")
        raise OSError("disk full")

    monkeypatch.setattr(pd.DataFrame, "to_csv", fail_after_partial_write)

    with pytest.raises(data_loader.DataError, match="保存数据集失败"):
        data_loader.create_dataset(tmp_path, frame, "broken.csv")

    assert list(tmp_path.glob("*.csv")) == []


def test_database_ignores_and_cannot_delete_dataset_outside_data_root(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    outside = tmp_path / "outside.csv"
    outside.write_text("secret,data\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(settings, "data_dir", data_root)
    database.init_db()
    with database._connect() as conn:
        conn.execute(
            "INSERT INTO datasets(id, name, path, summary_json) VALUES (?, ?, ?, ?)",
            ("outside", "outside.csv", str(outside), "{}"),
        )

    assert database.get_dataset("outside") is None
    assert database.list_datasets() == []
    assert database.delete_dataset("outside") is True
    assert outside.exists()


def test_database_delete_dataset_does_not_delete_external_revision_output(monkeypatch, tmp_path):
    data_root = tmp_path / "data"
    data_root.mkdir()
    dataset_path = data_root / "dataset.csv"
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")
    outside_output = tmp_path / "external-output"
    outside_output.mkdir()
    marker = outside_output / "marker.txt"
    marker.write_text("keep", encoding="utf-8")
    monkeypatch.setattr(settings, "data_dir", data_root)
    database.init_db()
    database.save_dataset(
        {"id": "dataset", "name": "dataset.csv", "path": str(dataset_path), "summary": {}}
    )
    with database._connect() as conn:
        conn.execute(
            "INSERT INTO revisions(id, dataset_id, code, preset, operation, output_dir, success, stderr) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            ("external-revision", "dataset", "code", "default", "run", str(outside_output), 1, ""),
        )

    assert database.delete_dataset("dataset") is True
    assert marker.exists()


def test_update_llm_config_returns_bad_request_for_runtime_validation_error(monkeypatch):
    monkeypatch.setattr(app_config, "update_runtime_config", lambda **_kwargs: (_ for _ in ()).throw(ValueError("bad config")))

    response = AUTH_CLIENT.put("/api/config/llm", json={"model": "valid-model"})

    assert response.status_code == 400
    assert response.json()["detail"] == "bad config"


def test_revision_output_path_must_be_inside_outputs_root(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    outside_outputs = tmp_path / "not-outputs"
    outside_outputs.mkdir()
    revision = {"output_dir": str(outside_outputs)}

    with pytest.raises(HTTPException, match="绘图产物不存在"):
        main._revision_output_dir(revision)


def test_json_array_parser_does_not_delegate_to_unbounded_pandas_json_load(tmp_path, monkeypatch):
    source = tmp_path / "records.json"
    source.write_text('[{"x": 1}, {"x": 2}]', encoding="utf-8")
    monkeypatch.setattr(
        data_loader.pd,
        "read_json",
        lambda *_args, **_kwargs: pytest.fail("pandas.read_json must not be used"),
    )

    frame = data_loader.load_dataframe(source)

    assert frame.to_dict(orient="records") == [{"x": 1}, {"x": 2}]


def test_json_array_parser_rejects_row_budget_before_dataframe_materialization(tmp_path, monkeypatch):
    source = tmp_path / "too-many-records.json"
    source.write_text('[{"x": 1}, {"x": 2}]', encoding="utf-8")
    monkeypatch.setattr(data_loader, "MAX_IMPORT_ROWS", 1)

    with pytest.raises(data_loader.DataError, match="行数"):
        data_loader.load_dataframe(source)


def test_xlsx_zip_expansion_limit_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "large.xlsx"
    source.write_bytes(b"placeholder")
    monkeypatch.setattr(settings, "max_archive_expanded_bytes", 100)
    monkeypatch.setattr(data_loader, "_zip_limits", lambda _path: (10, settings.max_archive_expanded_bytes + 1))

    with pytest.raises(data_loader.DataError, match="展开大小"):
        data_loader.validate_source_path(source)


def test_xlsx_zip_member_limit_is_rejected(tmp_path, monkeypatch):
    source = tmp_path / "many.xlsx"
    source.write_bytes(b"placeholder")
    monkeypatch.setattr(settings, "max_archive_members", 10)
    monkeypatch.setattr(data_loader, "_zip_limits", lambda _path: (settings.max_archive_members + 1, 10))

    with pytest.raises(data_loader.DataError, match="文件数量"):
        data_loader.validate_source_path(source)


def test_parse_concurrency_limit_is_enforced(monkeypatch, tmp_path):
    source = tmp_path / "data.csv"
    source.write_text("x,y\n1,2\n", encoding="utf-8")
    monkeypatch.setattr(settings, "max_parse_concurrency", 1)

    with data_loader._parse_slot():
        with pytest.raises(data_loader.DataBusyError, match="解析资源繁忙"):
            data_loader.load_dataframe(source)


def test_plot_execution_rejects_when_global_concurrency_is_exhausted(monkeypatch, tmp_path):
    permit = threading.BoundedSemaphore(1)
    permit.acquire()
    monkeypatch.setattr(main, "_PLOT_SEMAPHORE", permit)

    with pytest.raises(HTTPException) as exc:
        main._execute_and_decorate(
            "",
            {"id": "dataset", "path": str(tmp_path / "data.csv"), "summary": {}},
            "default",
            "run",
        )

    assert exc.value.status_code == 429


def test_prune_revisions_removes_old_outputs_and_keeps_recent(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    database.init_db()
    dataset_path = tmp_path / "dataset.csv"
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")
    dataset = {"id": "dataset", "name": "dataset.csv", "path": str(dataset_path), "summary": {}}
    database.save_dataset(dataset)

    for index in range(3):
        output_dir = tmp_path / "outputs" / str(index)
        output_dir.mkdir(parents=True)
        (output_dir / "out.png").write_bytes(b"x" * 512)
        database.create_revision("dataset", "code", "default", "run", output_dir, True)

    result = database.prune_revisions(max_revisions_per_dataset=1, max_output_bytes=1024)

    assert result["removed_revisions"] >= 2
    assert result["remaining_bytes"] <= 1024
    assert len(list((tmp_path / "outputs").iterdir())) == 1


def test_prune_revisions_enforces_quota_across_datasets(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    database.init_db()
    for dataset_index in range(2):
        dataset_id = f"dataset-{dataset_index}"
        dataset_path = tmp_path / f"{dataset_id}.csv"
        dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")
        database.save_dataset(
            {"id": dataset_id, "name": dataset_id, "path": str(dataset_path), "summary": {}}
        )
        for revision_index in range(2):
            output_dir = tmp_path / "outputs" / f"{dataset_index}-{revision_index}"
            output_dir.mkdir(parents=True)
            (output_dir / "out.png").write_bytes(b"x" * 1024)
            database.create_revision(dataset_id, "code", "default", "run", output_dir, True)

    result = database.prune_revisions(max_revisions_per_dataset=1, max_output_bytes=1024)

    assert result["remaining_bytes"] <= 1024
    assert len(list((tmp_path / "outputs").iterdir())) == 1


def test_llm_prompt_omits_top_values_by_default(monkeypatch):
    monkeypatch.setattr(settings, "llm_send_data_values", False)

    prompt = llm._clean_summary_for_prompt(
        {"columns": [{"name": "email", "dtype": "object", "top_values": [{"value": "alice@example.com", "count": 1}]}]}
    )

    assert "alice@example.com" not in prompt
    assert "top_values" not in prompt


def test_llm_prompt_can_send_redacted_values_only_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "llm_send_data_values", True)

    prompt = llm._clean_summary_for_prompt(
        {"columns": [{"name": "email", "dtype": "object", "top_values": [{"value": "alice@example.com", "count": 1}]}]}
    )

    assert "top_values" in prompt
    assert "alice@example.com" not in prompt
    assert "REDACTED_EMAIL" in prompt


def test_llm_prompt_redacts_credentials_and_email_addresses():
    clean = llm._sanitize_prompt_text("Bearer sk-secret alice@example.com api_key=super-secret")

    assert "sk-secret" not in clean
    assert "alice@example.com" not in clean
    assert "super-secret" not in clean


def test_non_loopback_host_is_rejected():
    with pytest.raises(ValueError, match="回环"):
        app_config.validate_local_bind_host("0.0.0.0")


def test_rotated_session_token_invalidates_previous(monkeypatch, tmp_path):
    old_token = app_config.SESSION_TOKEN
    monkeypatch.setattr(app_config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(app_config, "SESSION_TOKEN", old_token)

    new_token = app_config.rotate_session_token()

    assert new_token != old_token
    assert app_config.SESSION_TOKEN == new_token
    assert (tmp_path / ".session_token").read_text(encoding="utf-8").strip() == new_token


def test_dependency_files_use_reproducible_constraints():
    backend_root = Path(__file__).resolve().parents[1]
    for filename in ("requirements.txt", "requirements-build.txt", "requirements-sandbox.txt"):
        lines = [
            line.strip()
            for line in (backend_root / filename).read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.lstrip().startswith("#")
        ]
        assert lines
        assert all("==" in line or line.startswith("-r ") for line in lines), filename


def test_sidecar_build_checks_lockfiles_and_exposes_sbom_command():
    backend_root = Path(__file__).resolve().parents[1]
    script = (backend_root / "build_sidecar.ps1").read_text(encoding="utf-8")

    assert "requirements.lock.txt" in script
    assert "requirements-sandbox.lock.txt" in script
    assert "generate_sbom.py" in script
    assert (backend_root / "generate_sbom.py").is_file()
