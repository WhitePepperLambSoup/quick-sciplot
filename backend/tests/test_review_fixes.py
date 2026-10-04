"""Regression tests for the project review fixes."""

import ast
import io
import os
import subprocess
import sys
from pathlib import Path

import httpx
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app import (
    compliance_checker,
    data_loader,
    database,
    llm,
    main,
    sandbox,
    visual_critic,
    visual_manipulator,
)
from app.config import SESSION_TOKEN, settings
from app.main import app

AUTH_CLIENT = TestClient(app, headers={"X-Session-Token": SESSION_TOKEN})


# --------------------------------------------------------------------------- DPI


def _png_with_dpi(path, dpi=300):
    # Pillow stores the resolution as pixels per metre, so it reads back as 299.9994.
    Image.new("RGB", (1050, 750), "white").save(path, dpi=(dpi, dpi))


def test_dpi_helper_rounds_instead_of_truncating():
    assert compliance_checker.dpi_from_image_info((299.9994, 299.9994)) == 300
    assert compliance_checker.dpi_from_image_info(299.9994) == 300
    assert compliance_checker.dpi_from_image_info((72, 72)) == 72
    assert compliance_checker.dpi_from_image_info(None) is None
    assert compliance_checker.dpi_from_image_info(()) is None
    assert compliance_checker.dpi_from_image_info(("bad", "bad")) is None


def test_300_dpi_png_passes_the_resolution_check(tmp_path):
    png = tmp_path / "out.png"
    _png_with_dpi(png)
    assert Image.open(png).info["dpi"][0] < 300  # the precondition that used to break the check
    (tmp_path / "out.svg").write_text("<svg></svg>", encoding="utf-8")

    report = compliance_checker.check_journal_compliance(tmp_path, "nature")

    resolution = [check for check in report["checks"] if "分辨率" in check["item"]]
    assert resolution and resolution[0]["passed"] is True
    assert report["passed"] is True, report["checks"]


def test_visual_critic_accepts_300_dpi_png(tmp_path):
    png = tmp_path / "out.png"
    _png_with_dpi(png)

    report = visual_critic.critique_figure_image(png, "fig.tight_layout(); ax.legend(loc='best'); fontsize=9")

    assert report["dpi_ok"] is True


# ----------------------------------------------------------------------- summary


def test_summary_keeps_numeric_stats_for_columns_with_missing_values():
    frame = pd.DataFrame({"a": [1.0, 2.0, float("nan"), 4.0], "b": ["x", "y", "x", None]})

    summary = data_loader.build_summary(frame)

    numeric, categorical = summary["columns"]
    assert numeric["nulls"] == 1
    assert "float" in numeric["dtype"]
    assert numeric["min"] == 1.0 and numeric["max"] == 4.0
    assert numeric["mean"] == pytest.approx(7 / 3, abs=1e-3)
    assert "top_values" not in numeric
    assert "top_values" in categorical
    assert summary["head"][2]["a"] is None


# -------------------------------------------------------------------- .txt files


@pytest.mark.parametrize("separator", ["\t", ",", ";"])
def test_txt_import_detects_the_delimiter(tmp_path, separator):
    source = tmp_path / "table.txt"
    source.write_text(f"x{separator}y\n1{separator}2\n3{separator}4\n", encoding="utf-8")

    frame = data_loader.load_dataframe(source)

    assert list(frame.columns) == ["x", "y"]
    assert frame.shape == (2, 2)


def test_txt_import_keeps_single_column_files(tmp_path):
    source = tmp_path / "single.txt"
    source.write_text("value\n1\n2\n", encoding="utf-8")

    frame = data_loader.load_dataframe(source)

    assert list(frame.columns) == ["value"]
    assert frame.shape == (2, 1)


# -------------------------------------------------------------- combine datasets


def test_combining_an_already_combined_dataset_keeps_the_original_source(tmp_path):
    first = data_loader.create_dataset(tmp_path, pd.DataFrame({"v": [1, 2]}), "a.csv")
    second = data_loader.create_dataset(tmp_path, pd.DataFrame({"v": [3, 4]}), "b.csv")
    third = data_loader.create_dataset(tmp_path, pd.DataFrame({"v": [5, 6]}), "c.csv")

    combined = data_loader.combine_datasets(tmp_path, [first, second])
    recombined = data_loader.combine_datasets(tmp_path, [combined, third])

    frame = data_loader.load_dataframe(recombined["path"])
    assert list(frame.columns) == ["source_file", "v"]
    assert frame["source_file"].tolist() == ["a.csv", "a.csv", "b.csv", "b.csv", "c.csv", "c.csv"]


def test_combine_route_accepts_an_already_combined_dataset(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    main.DATASETS.clear()
    database.init_db()
    ids = []
    for name in ("a.csv", "b.csv", "c.csv"):
        response = AUTH_CLIENT.post(
            "/api/datasets",
            files={"file": (name, io.BytesIO(b"v\n1\n2\n"), "text/csv")},
        )
        assert response.status_code == 200, response.text
        ids.append(response.json()["id"])

    first = AUTH_CLIENT.post("/api/datasets/combine", json={"dataset_ids": ids[:2]})
    assert first.status_code == 200, first.text
    second = AUTH_CLIENT.post("/api/datasets/combine", json={"dataset_ids": [first.json()["id"], ids[2]]})

    assert second.status_code == 200, second.text
    assert second.json()["summary"]["shape"]["rows"] == 6


# ------------------------------------------------------------ output-dir sweeping


def test_orphan_cleanup_skips_inflight_outputs_but_removes_real_orphans(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    database.init_db()
    inflight = tmp_path / "outputs" / "inflight"
    orphan = tmp_path / "outputs" / "orphan"
    inflight.mkdir(parents=True)
    orphan.mkdir(parents=True)

    database.mark_output_inflight(inflight)
    try:
        assert database.cleanup_orphaned_outputs() == 1
        assert inflight.is_dir()
        assert not orphan.exists()
    finally:
        database.release_output_inflight(inflight)

    assert database.cleanup_orphaned_outputs() == 1
    assert not inflight.exists()


def test_concurrent_prune_does_not_delete_a_running_plots_output(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    main.DATASETS.clear()
    database.init_db()
    dataset_path = tmp_path / "dataset.csv"
    dataset_path.write_text("x,y\n1,2\n", encoding="utf-8")
    dataset = {"id": "dataset", "name": "dataset.csv", "path": str(dataset_path), "summary": {}}
    database.save_dataset(dataset)

    def render_while_another_request_prunes(code, csv_path, output_dir, preset_id=None):
        output_dir.mkdir(parents=True, exist_ok=True)
        # A second request finishing at this moment runs the same sweep.
        database.prune_revisions(max_revisions_per_dataset=50, max_output_bytes=10**9)
        assert output_dir.is_dir(), "the sweep deleted the output directory of a running plot"
        (output_dir / "out.png").write_bytes(b"png")
        return {"success": True, "returncode": 0, "stdout": "", "stderr": "", "formats": ["png"]}

    monkeypatch.setattr(sandbox, "run_plot_code", render_while_another_request_prunes)

    result = main._execute_and_decorate("x = 1", dataset, "default", "run")

    assert result["revision_id"]
    revision = database.get_revision(result["revision_id"])
    assert revision is not None
    assert Path(revision["output_dir"]).is_dir()


# ------------------------------------------------------------------ Host header


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("localhost", "localhost"),
        ("localhost:8000", "localhost"),
        ("127.0.0.1:8000", "127.0.0.1"),
        ("[::1]:8000", "::1"),
        ("[::1]", "::1"),
        ("LOCALHOST.", "localhost"),
        ("", ""),
    ],
)
def test_host_header_parsing(header, expected):
    assert main._hostname_from_host_header(header) == expected


def test_untrusted_host_header_is_rejected_without_issuing_a_session_cookie():
    client = TestClient(app)

    assert client.get("/api/config", headers={"Host": "localhost:8000"}).status_code == 200
    assert client.get("/api/config", headers={"Host": "127.0.0.1:8000"}).status_code == 200
    assert client.get("/api/config", headers={"Host": "[::1]:8000"}).status_code == 200

    rebinding = client.get("/api/config", headers={"Host": "attacker.example:8000"})
    assert rebinding.status_code == 400
    assert "set-cookie" not in rebinding.headers


# ------------------------------------------------------------------- DATA_DIR


def test_relative_data_dir_is_anchored_to_backend_not_the_working_directory(monkeypatch, tmp_path):
    from app.config import BACKEND_DIR, Settings

    monkeypatch.setenv("DATA_DIR", "./relative-data")
    assert Settings().data_dir == BACKEND_DIR / "relative-data"

    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    assert Settings().data_dir == tmp_path


# --------------------------------------------------------------------------- LLM


def test_llm_non_json_success_response_becomes_llm_error(monkeypatch):
    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

        def post(self, url, **kwargs):
            return httpx.Response(200, text="<html>bad gateway</html>", request=httpx.Request("POST", url))

    monkeypatch.setattr(settings, "llm_mock", False)
    monkeypatch.setattr(settings, "llm_api_key", "test-key")
    monkeypatch.setattr(llm, "validate_safe_llm_url", lambda *args, **kwargs: None)
    monkeypatch.setattr(llm.httpx, "Client", FakeClient)

    with pytest.raises(llm.LLMError, match="无法解析"):
        llm._call_chat([{"role": "user", "content": "hi"}])


def test_mimic_without_api_key_reports_an_error_instead_of_demo_code(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "data_dir", tmp_path)
    main.DATASETS.clear()
    database.init_db()
    upload = AUTH_CLIENT.post(
        "/api/datasets",
        files={"file": ("mimic.csv", io.BytesIO(b"x,y\n1,2\n2,3\n"), "text/csv")},
    )
    assert upload.status_code == 200, upload.text
    monkeypatch.setattr(settings, "llm_mock", False)
    monkeypatch.setattr(settings, "llm_api_key", "")

    response = AUTH_CLIENT.post(
        "/api/plots/mimic",
        json={"dataset_id": upload.json()["id"], "reference_description": "双轴对比曲线"},
    )

    assert response.status_code == 502
    assert "LLM_API_KEY" in response.json()["detail"]


# ----------------------------------------------------------- visual manipulator


def test_injected_reference_line_keeps_the_indentation_of_its_anchor_line():
    code = (
        "import matplotlib.pyplot as plt\n"
        "def draw():\n"
        "    fig, ax = plt.subplots()\n"
        "    ax.plot([1, 2], [3, 4])\n"
        "    fig.tight_layout()\n"
        "draw()\n"
    )

    updated = visual_manipulator.adjust_hline(code, 2.5)

    ast.parse(updated)
    assert "    ax.axhline(y=2.5" in updated
    assert updated.index("axhline") < updated.index("tight_layout")


def test_plt_style_scripts_are_not_mistaken_for_ax_scripts_by_substrings():
    code = (
        "import matplotlib.pyplot as plt\n"
        "plt.plot([1, 2], [3, 4])\n"
        "limit = max([1, 2])\n"
        "plt.tight_layout()\n"
    )

    assert "plt.ylim(0.0, 5.0)" in visual_manipulator.adjust_ylim(code, 0, 5)
    assert "plt.xlim(0.0, 5.0)" in visual_manipulator.adjust_xlim(code, 0, 5)
    hline = visual_manipulator.adjust_hline(code, 1.5)
    assert "plt.axhline(y=1.5" in hline
    assert "ax.axhline" not in hline


@pytest.mark.parametrize("bad_value", [float("nan"), float("inf"), "abc", True, None])
def test_interactive_adjustments_reject_non_finite_numbers(bad_value):
    code = "import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\n"

    with pytest.raises(visual_manipulator.ManipulationError):
        visual_manipulator.adjust_hline(code, bad_value)
    with pytest.raises(visual_manipulator.ManipulationError):
        visual_manipulator.adjust_ylim(code, 0, bad_value)


# ------------------------------------------------------------- missing fonts


def test_render_survives_missing_fonts_without_flooding_the_log(tmp_path):
    """Without CJK fonts (Linux, the Docker image) findfont spam used to exceed the log cap."""
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("year,revenue,users\n2020,100,1200\n2021,150,1800\n2022,210,2600\n", encoding="utf-8")
    code = llm._MOCK_HIST.replace("['SimHei', 'Microsoft YaHei']", "['NoSuchFontA', 'NoSuchFontB']")
    assert "NoSuchFontA" in code

    result = sandbox.run_plot_code(code, csv_path, tmp_path / "output")

    assert result["success"], result["stderr"][-500:]
    assert "findfont" not in result["stderr"]
    assert "missing from font" not in result["stderr"]


# ------------------------------------------------------------ packaged worker


def _write_script(tmp_path, body: str, bom: bool = False):
    script = tmp_path / "script.py"
    script.write_text(body, encoding="utf-8-sig" if bom else "utf-8")
    return script


def test_packaged_worker_reports_exceptions_on_stderr_instead_of_crashing(tmp_path, capsys):
    import run_server

    script = _write_script(tmp_path, "raise ValueError('bad column name')\n")

    assert run_server.run_worker(str(script)) == 1
    stderr = capsys.readouterr().err
    assert "ValueError: bad column name" in stderr
    assert "Traceback" in stderr


def test_packaged_worker_handles_system_exit_and_success(tmp_path, capsys):
    import run_server

    assert run_server.run_worker(str(_write_script(tmp_path, "raise SystemExit('no numeric columns')\n"))) == 1
    assert "no numeric columns" in capsys.readouterr().err
    assert run_server.run_worker(str(_write_script(tmp_path, "raise SystemExit(3)\n"))) == 3
    assert run_server.run_worker(str(_write_script(tmp_path, "print('ok')\n", bom=True))) == 0
    assert "ok" in capsys.readouterr().out


# ------------------------------------------------------------------------ Docker


def test_docker_run_passes_the_script_as_a_file_and_names_the_container(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox, "_find_docker", lambda: "docker")
    csv_path = tmp_path / "data.csv"
    csv_path.write_text("x,y\n1,2\n", encoding="utf-8")
    output_dir = tmp_path / "output"
    output_dir.mkdir()
    captured: dict[str, object] = {}

    def fake_run_command(command, *, cwd, env, monitored_paths=None, on_terminate=None):
        captured["command"] = command
        captured["script_present"] = (output_dir / "runner_script.py").is_file()
        captured["on_terminate"] = on_terminate
        return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

    monkeypatch.setattr(sandbox, "_run_command", fake_run_command)
    # Larger than the ~32k character Windows command-line limit.
    big_code = "import matplotlib.pyplot as plt\n" + "# padding\n" * 6000 + "plt.plot([1], [1])\n"

    sandbox._run_in_docker(big_code, csv_path, output_dir, "default")

    command = captured["command"]
    assert "-c" not in command
    assert command[-1] == "/workspace/output/runner_script.py"
    assert sum(len(part) for part in command) < 2000
    assert captured["script_present"] is True
    assert not (output_dir / "runner_script.py").exists()

    container_name = command[command.index("--name") + 1]
    assert container_name.startswith("quick-sciplot-")
    removals: list[list[str]] = []
    monkeypatch.setattr(sandbox.subprocess, "run", lambda cmd, **kwargs: removals.append(cmd))
    captured["on_terminate"]()
    assert removals == [["docker", "rm", "-f", container_name]]


def test_runner_timeout_invokes_the_terminate_callback(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "sandbox_timeout", 0.5)
    called: list[int] = []

    result = sandbox._run_command(
        [sys.executable, "-c", "import time; time.sleep(30)"],
        cwd=tmp_path,
        env=os.environ.copy(),
        on_terminate=lambda: called.append(1),
    )

    assert result.returncode == -1
    assert "执行超时" in result.stderr
    assert called == [1]


def test_runner_does_not_invoke_the_terminate_callback_on_normal_exit(tmp_path):
    called: list[int] = []

    result = sandbox._run_command(
        [sys.executable, "-c", "print('ok')"],
        cwd=tmp_path,
        env=os.environ.copy(),
        on_terminate=lambda: called.append(1),
    )

    assert result.returncode == 0
    assert called == []
