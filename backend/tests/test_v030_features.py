"""Tests for the 0.3.0 feature set."""

import io
import json
import sqlite3
import subprocess
import sys
import threading
import zipfile
from pathlib import Path

import httpx
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app import (
    compliance_checker,
    config as app_config,
    data_transform,
    database,
    llm,
    main,
    plot_templates,
    sandbox,
    stats_annotator,
    system,
    visual_manipulator,
)
from app.config import SESSION_TOKEN, settings, validate_safe_llm_url
from app.main import app

AUTH = TestClient(app, headers={"X-Session-Token": SESSION_TOKEN})


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    main.DATASETS.clear()
    database.init_db()
    yield tmp_path
    main.DATASETS.clear()


def _upload(frame: pd.DataFrame, name: str = "data.csv") -> dict:
    response = AUTH.post("/api/datasets", files={"file": (name, io.BytesIO(frame.to_csv(index=False).encode()), "text/csv")})
    assert response.status_code == 200, response.text
    return response.json()


SIMPLE_PLOT = "import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.plot(df['x'], df['y'])\n"


# ------------------------------------------------------------------ system setup


def test_system_status_reports_sandbox_and_docker(isolated, monkeypatch):
    monkeypatch.setattr(sandbox, "_find_docker", lambda: None)
    status = AUTH.get("/api/system/status").json()
    assert status["sandbox_mode"] == "process"
    assert status["sandbox_ready"] is True
    assert status["docker"]["installed"] is False
    assert status["can_build_image"] is True
    assert {"desktop", "llm_configured", "image_build"} <= set(status)


def test_local_worker_can_only_be_enabled_from_the_desktop_app_with_consent(isolated, monkeypatch, tmp_path):
    monkeypatch.setattr(app_config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(settings, "sandbox_mode", "docker")
    monkeypatch.setattr(settings, "allow_unsafe_process_sandbox", False)

    monkeypatch.setattr(settings, "quick_sciplot_desktop", False)
    denied = AUTH.post("/api/system/sandbox", json={"mode": "process", "acknowledge_risk": True})
    assert denied.status_code == 400 and "桌面版" in denied.json()["detail"]

    monkeypatch.setattr(settings, "quick_sciplot_desktop", True)
    unconfirmed = AUTH.post("/api/system/sandbox", json={"mode": "process"})
    assert unconfirmed.status_code == 400

    enabled = AUTH.post("/api/system/sandbox", json={"mode": "process", "acknowledge_risk": True})
    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["sandbox_mode"] == "process"
    env_text = (tmp_path / ".env").read_text(encoding="utf-8")
    assert 'SANDBOX_MODE="process"' in env_text and 'ALLOW_UNSAFE_PROCESS_SANDBOX="1"' in env_text


def test_image_build_reports_missing_docker(monkeypatch):
    monkeypatch.setattr(sandbox, "_find_docker", lambda: None)
    job = system.ImageBuildJob()
    assert job.start() is True
    for _ in range(50):
        if job.snapshot()["state"] != "running":
            break
        threading.Event().wait(0.05)
    snapshot = job.snapshot()
    assert snapshot["state"] == "failed"
    assert "Docker" in snapshot["error"]


def test_image_build_runs_docker_build_in_a_minimal_context(monkeypatch, tmp_path):
    recorded = tmp_path / "args.json"
    fake_docker = tmp_path / "fake_docker.py"
    fake_docker.write_text(
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'files': sorted(os.listdir('.'))}}, open({str(recorded)!r}, 'w'))\n"
        "print('Step 1/1 : done')\n",
        encoding="utf-8",
    )
    launcher = tmp_path / ("docker.cmd" if sys.platform == "win32" else "docker")
    if sys.platform == "win32":
        launcher.write_text(f'@"{sys.executable}" "{fake_docker}" %*\n', encoding="utf-8")
    else:
        launcher.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{fake_docker}" "$@"\n', encoding="utf-8")
        launcher.chmod(0o755)
    monkeypatch.setattr(sandbox, "_find_docker", lambda: str(launcher))
    job = system.ImageBuildJob()
    job.start()
    for _ in range(200):
        if job.snapshot()["state"] != "running":
            break
        threading.Event().wait(0.05)
    snapshot = job.snapshot()
    assert snapshot["state"] == "succeeded", snapshot
    call = json.loads(recorded.read_text(encoding="utf-8"))
    assert call["argv"][:3] == ["build", "-f", "Dockerfile.sandbox"]
    assert sorted(call["files"]) == sorted(system.SANDBOX_BUILD_FILES)


# ------------------------------------------------------------------- local models


def test_loopback_llm_urls_need_the_explicit_switch(monkeypatch):
    with pytest.raises(ValueError):
        validate_safe_llm_url("http://127.0.0.1:11434/v1")
    validate_safe_llm_url("http://127.0.0.1:11434/v1", allow_loopback=True)
    validate_safe_llm_url("http://localhost:1234/v1", allow_loopback=True)
    with pytest.raises(ValueError, match="自身"):
        validate_safe_llm_url(f"http://127.0.0.1:{settings.port}/v1", allow_loopback=True)
    with pytest.raises(ValueError):
        validate_safe_llm_url("http://10.0.0.5:11434/v1", allow_loopback=True)


def test_local_model_needs_no_api_key_and_sends_no_authorization(monkeypatch):
    monkeypatch.setattr(settings, "llm_mock", False)
    monkeypatch.setattr(settings, "llm_api_key", "")
    monkeypatch.setattr(settings, "llm_base_url", "http://127.0.0.1:11434/v1")
    monkeypatch.setattr(settings, "allow_loopback_llm", True)
    url, headers = llm._request_target("/chat/completions")
    assert url == "http://127.0.0.1:11434/v1/chat/completions"
    assert "Authorization" not in headers
    assert llm.is_configured()

    monkeypatch.setattr(settings, "allow_loopback_llm", False)
    with pytest.raises(llm.LLMError):
        llm._request_target("/chat/completions")


def test_runtime_config_can_enable_a_local_model_in_one_request(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(settings, "allow_loopback_llm", False)
    monkeypatch.setattr(settings, "llm_base_url", settings.llm_base_url)
    result = AUTH.put(
        "/api/config/llm",
        json={"base_url": "http://127.0.0.1:11434/v1", "allow_loopback_llm": True, "model": "qwen2.5"},
    )
    assert result.status_code == 200, result.text
    assert result.json()["allow_loopback_llm"] is True


class _FakeResponse:
    def __init__(self, status_code=200, payload=None, lines=None, content_type="application/json"):
        self.status_code = status_code
        self._payload = payload
        self._lines = lines or []
        self.headers = {"content-type": content_type}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=httpx.Request("GET", "http://x"), response=httpx.Response(self.status_code))

    def json(self):
        return self._payload

    def read(self):
        return json.dumps(self._payload).encode()

    def iter_lines(self):
        yield from self._lines

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _fake_client(response):
    class Client:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def get(self, url, **kwargs):
            return response

        def stream(self, method, url, **kwargs):
            assert kwargs["json"]["stream"] is True
            return response

    return Client


@pytest.fixture
def real_llm(monkeypatch):
    monkeypatch.setattr(settings, "llm_mock", False)
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm, "validate_safe_llm_url", lambda *args, **kwargs: None)


def test_list_models_reads_the_openai_models_endpoint(real_llm, monkeypatch):
    payload = {"data": [{"id": "b-model"}, {"id": "a-model"}, {"id": "a-model"}]}
    monkeypatch.setattr(llm.httpx, "Client", _fake_client(_FakeResponse(payload=payload)))
    assert llm.list_models() == ["a-model", "b-model"]


def test_stream_chat_parses_server_sent_events(real_llm, monkeypatch):
    lines = [
        'data: {"choices":[{"delta":{"content":"import "}}]}',
        "",
        'data: {"choices":[{"delta":{"reasoning_content":"hidden"}}]}',
        'data: {"choices":[{"delta":{"content":"numpy"}}]}',
        "data: [DONE]",
        'data: {"choices":[{"delta":{"content":"ignored"}}]}',
    ]
    monkeypatch.setattr(llm.httpx, "Client", _fake_client(_FakeResponse(lines=lines, content_type="text/event-stream")))
    assert "".join(llm.stream_chat([{"role": "user", "content": "x"}])) == "import numpy"


def test_stream_chat_accepts_a_non_streaming_reply(real_llm, monkeypatch):
    payload = {"choices": [{"message": {"content": "print(1)"}}]}
    monkeypatch.setattr(llm.httpx, "Client", _fake_client(_FakeResponse(payload=payload)))
    assert "".join(llm.stream_chat([{"role": "user", "content": "x"}])) == "print(1)"


# -------------------------------------------------------------- streaming & cancel


def _ndjson(response) -> list[dict]:
    return [json.loads(line) for line in response.text.splitlines() if line.strip()]


def test_streaming_generation_emits_tokens_stages_and_the_result(isolated):
    dataset = _upload(pd.DataFrame({"year": [2020, 2021, 2022], "revenue": [1, 3, 2], "group": ["A", "B", "A"]}))
    response = AUTH.post("/api/plots/generate/stream", json={"dataset_id": dataset["id"], "instruction": "画折线图"})
    assert response.status_code == 200
    events = _ndjson(response)
    kinds = [event["type"] for event in events if event["type"] != "ping"]
    assert kinds[0] == "stage" and "token" in kinds and kinds[-1] == "result"
    stages = [event["stage"] for event in events if event["type"] == "stage"]
    assert stages[:2] == ["llm", "render"]
    tokens = "".join(event["text"] for event in events if event["type"] == "token")
    result = events[-1]["data"]
    assert result["run"]["success"], result["run"].get("stderr")
    assert result["code"].strip() == llm._extract_code(tokens).strip()


def test_streaming_edit_reports_errors_as_events(isolated):
    response = AUTH.post("/api/plots/edit/stream", json={"dataset_id": "missing", "code": "x = 1", "instruction": "x"})
    assert response.status_code == 404


def test_cancelled_render_raises_and_keeps_no_revision(isolated):
    dataset = _upload(pd.DataFrame({"x": [1, 2], "y": [3, 4]}))
    ds = main._get_dataset(dataset["id"])
    cancel = threading.Event()
    threading.Timer(1.0, cancel.set).start()
    with pytest.raises(main.PlotCancelled):
        main._execute_and_decorate(
            "import math\ntotal = 0.0\nfor i in range(10**10):\n    total += math.sqrt(i)\n",
            ds,
            "default",
            "run",
            cancel_event=cancel,
        )
    assert database.list_revisions(dataset["id"]) == []
    assert not any((isolated / "outputs").iterdir())


def test_runtime_errors_report_the_line_in_the_users_code(isolated):
    dataset = _upload(pd.DataFrame({"x": [1, 2], "y": [3, 4]}))
    code = "import matplotlib.pyplot as plt\n\nvalue = df['missing']\nplt.plot([1], [1])\n"
    result = AUTH.post("/api/plots/run", json={"dataset_id": dataset["id"], "code": code}).json()
    assert result["run"]["success"] is False
    assert result["run"]["error_line"] == 3


def test_syntax_errors_name_the_line(isolated):
    dataset = _upload(pd.DataFrame({"x": [1, 2], "y": [3, 4]}))
    response = AUTH.post("/api/plots/run", json={"dataset_id": dataset["id"], "code": "x = 1\ny = (\n"})
    assert response.status_code == 400
    assert "line 2" in response.json()["detail"]


# ------------------------------------------------------------------ data workbench


def test_preview_values_transform_and_join(isolated):
    left = _upload(pd.DataFrame({"id": [1, 2, 3, 4], "group": ["a", "b", "a", "c"], "w1": [1, 2, 3, 4], "w2": [5, 6, 7, 8]}), "left.csv")
    right = _upload(pd.DataFrame({"id": [1, 2, 3, 5], "dose": [10, 20, 30, 50]}), "right.csv")

    preview = AUTH.get(f"/api/datasets/{left['id']}/preview", params={"offset": 1, "limit": 2}).json()
    assert preview["total_rows"] == 4 and len(preview["rows"]) == 2 and preview["rows"][0]["id"] == 2

    values = AUTH.get(f"/api/datasets/{left['id']}/values", params={"column": "group"}).json()
    assert values["values"][0] == {"value": "a", "count": 2} and values["total_unique"] == 3

    transformed = AUTH.post(
        f"/api/datasets/{left['id']}/transform",
        json={
            "operations": [
                {"op": "filter", "column": "w1", "operator": ">=", "value": "2"},
                {"op": "melt", "id_vars": ["id", "group"], "value_vars": ["w1", "w2"], "var_name": "week", "value_name": "score"},
            ],
            "name": "long",
        },
    )
    assert transformed.status_code == 200, transformed.text
    assert transformed.json()["summary"]["shape"] == {"rows": 6, "cols": 4}

    joined = AUTH.post(
        "/api/datasets/join",
        json={"left_id": left["id"], "right_id": right["id"], "left_on": ["id"], "right_on": ["id"], "how": "left"},
    )
    assert joined.status_code == 200, joined.text
    summary = joined.json()["summary"]
    assert summary["shape"]["rows"] == 4
    assert "dose" in [column["name"] for column in summary["columns"]]


def test_transforms_reject_unknown_operations_and_columns(isolated):
    dataset = _upload(pd.DataFrame({"x": [1, 2]}))
    for operations in ([{"op": "eval", "expr": "1"}], [{"op": "filter", "column": "nope", "operator": "==", "value": 1}]):
        response = AUTH.post(f"/api/datasets/{dataset['id']}/transform", json={"operations": operations})
        assert response.status_code == 400


def test_join_refuses_many_to_many_explosions(isolated, monkeypatch):
    monkeypatch.setattr(data_transform.data_loader, "MAX_ROWS_FOR_COMBINE", 10)
    left = _upload(pd.DataFrame({"k": ["a"] * 5}), "l.csv")
    right = _upload(pd.DataFrame({"k": ["a"] * 5}), "r.csv")
    response = AUTH.post("/api/datasets/join", json={"left_id": left["id"], "right_id": right["id"], "left_on": ["k"], "right_on": ["k"]})
    assert response.status_code == 400 and "连接键" in response.json()["detail"]


# -------------------------------------------------------------------- templates


TEMPLATE_FRAME = pd.DataFrame(
    {
        "gene": [f"G{i}" for i in range(24)],
        "log2fc": np.linspace(-3, 3, 24),
        "pvalue": np.geomspace(1e-6, 0.9, 24),
        "time": np.arange(1, 25),
        "event": [1, 0] * 12,
        "group": ["A", "B", "C"] * 8,
        "dose": np.repeat([0.01, 0.1, 1, 10, 100, 1000], 4),
        "response": np.repeat([2, 5, 20, 60, 90, 98], 4) + np.tile([0.0, 1.0, -1.0, 0.5], 6),
        "m1": np.sin(np.arange(24)),
        "m2": np.cos(np.arange(24)),
        "m3": np.arange(24) ** 0.5,
    }
)

TEMPLATE_PARAMS = {
    "volcano": {"fc_col": "log2fc", "p_col": "pvalue", "label_col": "gene"},
    "km_survival": {"time_col": "time", "event_col": "event", "group_col": "group"},
    "pca": {"columns": ["m1", "m2", "m3"], "group_col": "group"},
    "clustermap": {"columns": ["m1", "m2", "m3"], "label_col": "gene"},
    "dose_response": {"dose_col": "dose", "response_col": "response"},
    "correlation": {"columns": ["m1", "m2", "m3"], "method": "spearman"},
    "bar_points": {"group_col": "group", "value_col": "m3", "error": "sem"},
}


def test_every_template_is_listed_with_test_parameters():
    assert {t["id"] for t in AUTH.get("/api/templates").json()["templates"]} == set(TEMPLATE_PARAMS)


@pytest.mark.parametrize("template_id", sorted(TEMPLATE_PARAMS))
def test_template_renders(isolated, template_id):
    dataset = _upload(TEMPLATE_FRAME)
    response = AUTH.post(
        "/api/plots/template",
        json={"dataset_id": dataset["id"], "template_id": template_id, "params": TEMPLATE_PARAMS[template_id]},
    )
    assert response.status_code == 200, response.text
    run = response.json()["run"]
    assert run["success"], run.get("stderr")


def test_template_parameters_are_validated():
    summary = {"columns": [{"name": "x", "dtype": "float64", "mean": 1.0}, {"name": "label", "dtype": "str"}]}
    with pytest.raises(plot_templates.TemplateError, match="数值列"):
        plot_templates.build_code("volcano", {"fc_col": "label", "p_col": "x"}, summary)
    with pytest.raises(plot_templates.TemplateError, match="列不存在"):
        plot_templates.build_code("volcano", {"fc_col": "__import__('os')", "p_col": "x"}, summary)
    with pytest.raises(plot_templates.TemplateError):
        plot_templates.build_code("volcano", {"fc_col": "x", "p_col": "x", "fc_threshold": "nan"}, summary)
    with pytest.raises(plot_templates.TemplateError):
        plot_templates.build_code("unknown", {}, summary)


# -------------------------------------------------------------------- statistics


def test_paired_wilcoxon_and_tukey_tests():
    paired = pd.DataFrame(
        {"subject": [1, 2, 3, 4, 5, 1, 2, 3, 4, 5], "time": ["pre"] * 5 + ["post"] * 5, "v": [1, 2, 3, 4, 5, 2.1, 3.3, 4.2, 5.4, 6.1]}
    )
    t_result = stats_annotator.compare_groups(paired, "time", "v", "pre", "post", "paired-t", pair_col="subject")
    assert t_result["test_name"] == "Paired t-test" and t_result["n_pairs"] == 5 and t_result["p_value"] < 0.01
    w_result = stats_annotator.compare_groups(paired, "time", "v", "pre", "post", "wilcoxon", pair_col="subject")
    assert w_result["test_name"] == "Wilcoxon signed-rank"
    with pytest.raises(ValueError, match="配对"):
        stats_annotator.compare_groups(paired, "time", "v", "pre", "post", "paired-t")

    groups = pd.DataFrame({"g": ["a"] * 4 + ["b"] * 4 + ["c"] * 4, "v": [1, 1.1, 0.9, 1.0, 5, 5.2, 4.9, 5.1, 1.05, 0.95, 1.0, 1.02]})
    _, results = stats_annotator.inject_stat_brackets("x = 1", groups, "g", "v", [("a", "b"), ("a", "c")], "tukey", "bonferroni")
    assert all(result["test_name"] == "Tukey HSD" for result in results)
    assert all(result["correction_method"] == "none" for result in results)
    by_pair = {(r["group_a"], r["group_b"]): r for r in results}
    assert by_pair[("a", "b")]["p_value"] < 0.001 and by_pair[("a", "c")]["p_value"] > 0.5


def test_no_correction_keeps_raw_p_values():
    assert stats_annotator.adjust_p_values([0.01, 0.04], "none") == [0.01, 0.04]


def test_regression_fit_and_annotation_endpoint(isolated):
    frame = pd.DataFrame({"x": np.arange(10.0), "y": 2 * np.arange(10.0) + 1})
    fit = stats_annotator.fit_regression(frame, "x", "y", 1)
    assert fit["coefficients"] == pytest.approx([2.0, 1.0])
    assert fit["r_squared"] == pytest.approx(1.0)
    assert fit["equation"] == "y = 2x + 1"
    assert stats_annotator._equation_text([1.0, -3.0, 0.5]) == "y = 1x^2 - 3x + 0.5"

    dataset = _upload(frame)
    response = AUTH.post(
        "/api/plots/regression",
        json={"dataset_id": dataset["id"], "code": "import matplotlib.pyplot as plt\nplt.scatter(df['x'], df['y'])", "x_col": "x", "y_col": "y"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["run"]["success"], body["run"].get("stderr")
    assert body["regression"]["r_squared"] == pytest.approx(1.0)
    assert "np.polyval" in body["code"]


# ------------------------------------------------------------- journal fit, plotly


def test_fit_journal_replaces_its_own_block(isolated):
    code, width = compliance_checker.fit_figure_code(SIMPLE_PLOT, "nature", "single")
    again, _ = compliance_checker.fit_figure_code(code, "ieee", "double")
    assert width == 3.5 and again.count("期刊版面尺寸结束") == 1 and "7.16" in again
    with pytest.raises(ValueError):
        compliance_checker.fit_figure_code("import plotly.express as px\nfig = px.line()", "nature")

    dataset = _upload(pd.DataFrame({"x": [1, 2, 3], "y": [3, 1, 2]}))
    response = AUTH.post("/api/plots/fit-journal", json={"dataset_id": dataset["id"], "code": SIMPLE_PLOT, "journal": "nature"})
    assert response.status_code == 200, response.text
    revision_id = response.json()["revision_id"]
    report = AUTH.get(f"/api/plots/revisions/{revision_id}/compliance/nature").json()
    width_check = [check for check in report["checks"] if "物理宽度" in check["item"]][0]
    assert width_check["passed"], width_check


def test_plotly_reference_lines_and_ranges():
    code = "import plotly.express as px\nfig = px.scatter(df, x='x', y='y')\nfig.show()\n"
    with_line = visual_manipulator.apply_visual_action(code, "hline", {"y": 2.5})
    assert "fig.add_hline(y=2.5" in with_line and with_line.index("add_hline") < with_line.index("fig.show")
    moved = visual_manipulator.apply_visual_action(with_line, "hline", {"y": 4})
    assert "fig.add_hline(y=4.0" in moved and moved.count("add_hline") == 1
    ranged = visual_manipulator.apply_visual_action(moved, "ylim", {"ymin": 10, "ymax": 0})
    ranged = visual_manipulator.apply_visual_action(ranged, "ylim", {"ymin": 1, "ymax": 9})
    assert ranged.count("update_yaxes") == 1 and "range=[1.0, 9.0]" in ranged
    inspected = visual_manipulator.inspect_code_elements(ranged)
    assert inspected["hlines"] == [4.0] and inspected["ylim"] == [1.0, 9.0]


# ------------------------------------------------------- revisions, exports, batch


def test_revision_labels_stars_and_pruning(isolated):
    dataset = _upload(pd.DataFrame({"x": [1, 2], "y": [3, 4]}))
    first = AUTH.post("/api/plots/run", json={"dataset_id": dataset["id"], "code": SIMPLE_PLOT}).json()["revision_id"]
    updated = AUTH.patch(f"/api/plots/history/{first}", json={"label": "  final   figure ", "starred": True})
    assert updated.status_code == 200 and updated.json()["label"] == "final figure" and updated.json()["starred"] is True
    assert AUTH.patch("/api/plots/history/missing", json={"starred": True}).status_code == 404

    database.prune_revisions(max_revisions_per_dataset=1, max_output_bytes=10**9)
    AUTH.post("/api/plots/run", json={"dataset_id": dataset["id"], "code": SIMPLE_PLOT})
    database.prune_revisions(max_revisions_per_dataset=1, max_output_bytes=10**9)
    history = AUTH.get(f"/api/plots/history/{dataset['id']}").json()["revisions"]
    assert any(item["id"] == first and item["starred"] for item in history)

    thumbnail = AUTH.get(f"/api/plots/revisions/{first}/thumbnail")
    assert thumbnail.status_code == 200 and thumbnail.content.startswith(b"\x89PNG")


def test_old_databases_are_migrated(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    with sqlite3.connect(tmp_path / "history.sqlite3") as conn:
        conn.executescript(
            "CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT, path TEXT, summary_json TEXT, created_at TIMESTAMP);"
            "CREATE TABLE revisions (id TEXT PRIMARY KEY, dataset_id TEXT, code TEXT, preset TEXT, operation TEXT,"
            " output_dir TEXT, success INTEGER, stderr TEXT, created_at TIMESTAMP);"
        )
    database.init_db()
    with sqlite3.connect(tmp_path / "history.sqlite3") as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(revisions)")}
    assert {"label", "starred"} <= columns


def test_script_and_bundle_exports_reproduce_the_figure(isolated, tmp_path):
    dataset = _upload(pd.DataFrame({"x": [1, 2, 3], "y": [2, 4, 3]}), "measure.csv")
    revision_id = AUTH.post("/api/plots/run", json={"dataset_id": dataset["id"], "code": SIMPLE_PLOT}).json()["revision_id"]

    script = AUTH.get(f"/api/plots/revisions/{revision_id}/export/script")
    assert script.status_code == 200 and "pd.read_csv('data.csv')" in script.text

    bundle = AUTH.get(f"/api/plots/revisions/{revision_id}/export/bundle")
    assert bundle.status_code == 200
    workdir = tmp_path / "bundle"
    with zipfile.ZipFile(io.BytesIO(bundle.content)) as archive:
        names = set(archive.namelist())
        assert {"data.csv", "plot.py", "figure.png", "figure.pdf", "revision.json", "README.txt"} <= names
        archive.extractall(workdir)
    for stale in ("figure.png", "figure.pdf"):
        (workdir / stale).unlink()
    completed = subprocess.run([sys.executable, "plot.py"], cwd=workdir, capture_output=True, text=True, timeout=180)
    assert completed.returncode == 0, completed.stderr[-2000:]
    assert (workdir / "figure.png").is_file() and (workdir / "figure.pdf").is_file()


def test_batch_plotting_and_zip_export(isolated):
    first = _upload(pd.DataFrame({"x": [1, 2], "y": [3, 4]}), "a.csv")
    second = _upload(pd.DataFrame({"x": [1, 2], "y": [5, 1]}), "b.csv")
    broken = _upload(pd.DataFrame({"other": [1]}), "c.csv")
    response = AUTH.post("/api/plots/batch", json={"code": SIMPLE_PLOT, "dataset_ids": [first["id"], second["id"], broken["id"], "missing"]})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["succeeded"] == 2
    by_id = {item["dataset_id"]: item for item in body["items"]}
    assert by_id[broken["id"]]["success"] is False and by_id["missing"]["success"] is False

    revision_ids = [item["revision_id"] for item in body["items"] if item.get("success")]
    archive = AUTH.post("/api/plots/export-zip", json={"revision_ids": revision_ids, "format": "png"})
    assert archive.status_code == 200
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
        assert len(zipped.namelist()) == 2 and all(name.endswith(".png") for name in zipped.namelist())


def test_ai_critique_is_merged_into_the_report(isolated):
    dataset = _upload(pd.DataFrame({"x": [1, 2], "y": [3, 4]}))
    revision_id = AUTH.post("/api/plots/run", json={"dataset_id": dataset["id"], "code": SIMPLE_PLOT}).json()["revision_id"]
    plain = AUTH.post("/api/plots/critique", json={"revision_id": revision_id}).json()
    assert "ai" not in plain
    with_ai = AUTH.post("/api/plots/critique", json={"revision_id": revision_id, "use_ai": True}).json()
    assert with_ai["ai"]["available"] is True and with_ai["ai"]["suggestions"]
