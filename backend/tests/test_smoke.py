"""M1 闭环冒烟测试：上传 -> 摘要 -> 生成 -> 渲染 -> 编辑 -> 安全检查。"""

import io
import os
import sys
from pathlib import Path

import pytest

os.environ["LLM_MOCK"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402
from app.config import SESSION_TOKEN as TEST_SESSION_TOKEN  # noqa: E402

client = TestClient(app, headers={"X-Session-Token": TEST_SESSION_TOKEN})

CSV = """year,revenue,users,group
2020,100,1200,A
2021,150,1800,A
2022,210,2600,B
2023,260,3100,B
2024,320,3900,C
"""


def upload_dataset() -> dict:
    resp = client.post("/api/datasets", files={"file": ("demo.csv", io.BytesIO(CSV.encode()), "text/csv")})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_upload_and_summary():
    data = upload_dataset()
    assert "id" in data and "summary" in data
    assert data["summary"]["shape"] == {"rows": 5, "cols": 4}
    names = [c["name"] for c in data["summary"]["columns"]]
    assert names == ["year", "revenue", "users", "group"]
    assert data["summary"]["columns"][1]["mean"] == 208.0


def test_upload_multiple_datasets():
    second = "time,value\n1,10\n2,20\n"
    resp = client.post(
        "/api/datasets",
        files=[
            ("files", ("first.csv", io.BytesIO(CSV.encode()), "text/csv")),
            ("files", ("second.csv", io.BytesIO(second.encode()), "text/csv")),
        ],
    )
    assert resp.status_code == 200, resp.text
    datasets = resp.json()["datasets"]
    assert len(datasets) == 2
    assert [item["name"] for item in datasets] == ["first.csv", "second.csv"]

    combined = client.post("/api/datasets/combine", json={"dataset_ids": [item["id"] for item in datasets]})
    assert combined.status_code == 200, combined.text
    combined_data = combined.json()
    assert combined_data["summary"]["shape"]["rows"] == 7
    assert combined_data["summary"]["columns"][0]["name"] == "source_file"


def test_generate_bar():
    ds_id = upload_dataset()["id"]
    resp = client.post("/api/plots/generate", json={"dataset_id": ds_id, "instruction": "画柱状图，对比每年的 revenue"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run"]["success"], data["run"].get("stderr")
    assert data["run"]["image"].startswith("data:image/png;base64,")
    assert len(data["statements"]) >= 2, data["statements"]
    assert any("柱状" in (s["label"] or "") or "bar" in s["code"] for s in data["statements"])


def test_generate_histogram_switch():
    ds_id = upload_dataset()["id"]
    resp = client.post("/api/plots/generate", json={"dataset_id": ds_id, "instruction": "画直方图"})
    assert resp.status_code == 200
    assert resp.json()["run"]["success"]
    assert "hist" in resp.json()["code"]


def test_edit_then_run():
    ds_id = upload_dataset()["id"]
    gen = client.post("/api/plots/generate", json={"dataset_id": ds_id, "instruction": "画柱状图"}).json()
    resp = client.post("/api/plots/edit", json={"dataset_id": ds_id, "code": gen["code"], "instruction": "把标题改成英文"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run"]["success"], data["run"].get("stderr")
    assert data["code"] != gen["code"]

    run = client.post("/api/plots/run", json={"dataset_id": ds_id, "code": data["code"]})
    assert run.status_code == 200 and run.json()["run"]["success"]


def test_sandbox_blocks_dangerous_import():
    ds_id = upload_dataset()["id"]
    resp = client.post("/api/plots/run", json={"dataset_id": ds_id, "code": "import os\nos.system('echo hi')"})
    assert resp.status_code == 400
    assert "安全检查" in resp.json()["detail"]


def test_sandbox_blocks_open():
    ds_id = upload_dataset()["id"]
    resp = client.post("/api/plots/run", json={"dataset_id": ds_id, "code": "open('C:/Windows/win.ini')"})
    assert resp.status_code == 400


def test_missing_dataset_404():
    resp = client.post("/api/plots/generate", json={"dataset_id": "nope", "instruction": "x"})
    assert resp.status_code == 404


def test_config_status_and_mock_connection():
    config = client.get("/api/config")
    assert config.status_code == 200
    body = config.json()
    assert {"base_url", "model", "mock", "has_api_key", "auto_repair_attempts", "sandbox_mode"}.issubset(body)

    connection = client.post("/api/config/test")
    assert connection.status_code == 200, connection.text
    assert connection.json()["ok"] is True
    assert connection.json()["mode"] == "mock"


def test_llm_empty_response_retries(monkeypatch):
    from app import llm

    calls = {"count": 0}

    def fake_call(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise llm.LLMEmptyResponseError("empty")
        return "import matplotlib.pyplot as plt\nplt.plot([1, 2], [3, 4])"

    monkeypatch.setattr(llm, "_call_chat", fake_call)
    code = llm.generate_plot_code("画折线图", {"shape": {"rows": 2, "cols": 2}})
    assert "plt.plot" in code
    assert calls["count"] == 2


def test_docker_mode_reports_missing_runtime(monkeypatch, tmp_path):
    from app import sandbox
    from app.config import settings

    monkeypatch.setattr(settings, "sandbox_mode", "docker")
    monkeypatch.setattr(sandbox, "_find_docker", lambda: None)
    with pytest.raises(sandbox.SandboxUnavailableError):
        sandbox.run_plot_code("pass", tmp_path / "data.csv", tmp_path / "output")


def test_code_locator_labels():
    from app import code_locator

    code = "import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.plot([1, 2], [3, 4])\nax.set_title('t')\nax.legend()"
    cards = code_locator.split_statements(code)
    labels = [c["label"] for c in cards]
    assert "绘制折线/曲线" in labels
    assert "设置标题" in labels
    assert "添加图例" in labels
    assert cards[0]["start"] == 1 and cards[0]["end"] == 1


def test_code_locator_parameters_and_patch():
    from app import code_locator

    code = """import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(8, 5))
ax.bar([1, 2], [3, 4], color='red', alpha=0.5, linewidth=2)
ax.set_title('My plot')
"""
    cards = code_locator.split_statements(code)
    parameters = [parameter for card in cards for parameter in card["parameters"]]
    by_name = {parameter["name"]: parameter for parameter in parameters}
    assert {"figsize", "color", "alpha", "linewidth"}.issubset(by_name)
    assert by_name["color"]["value"] == "red"

    patched = code_locator.apply_parameter(code, by_name["color"], "blue")
    with pytest.raises(code_locator.CodeEditError):
        code_locator.apply_parameter(patched, by_name["alpha"], "0.8")
    fresh_parameters = [parameter for card in code_locator.split_statements(patched) for parameter in card["parameters"]]
    fresh_alpha = next(parameter for parameter in fresh_parameters if parameter["name"] == "alpha")
    patched = code_locator.apply_parameter(patched, fresh_alpha, "0.8")
    assert "color='blue'" in patched
    assert "alpha=0.8" in patched

    with pytest.raises(code_locator.CodeEditError):
        code_locator.apply_parameter(code.replace("red", "green"), by_name["color"], "blue")


def test_code_locator_axis_bindings():
    from app import code_locator

    code = "import matplotlib.pyplot as plt\nax.plot(df['year'], df['revenue'])"
    summary = {"columns": [{"name": "year"}, {"name": "revenue"}]}
    card = code_locator.split_statements(code, summary)[1]
    assert card["data_bindings"][0]["column"] == "year"
    assert card["data_bindings"][0]["meaning_zh"] == "年份"
    x_parameter = next(parameter for parameter in card["parameters"] if parameter["name"] == "x 数据")
    patched = code_locator.apply_parameter(code, x_parameter, "revenue")
    assert "df['revenue']" in patched


def test_parameter_endpoint_rerenders():
    from app import code_locator

    ds_id = upload_dataset()["id"]
    code = """import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.bar([1, 2], [3, 4], color='red', alpha=0.5)
ax.set_title('test')
"""
    card = code_locator.split_statements(code)[2]
    parameter = next(item for item in card["parameters"] if item["name"] == "color")
    resp = client.post(
        "/api/plots/parameter",
        json={"dataset_id": ds_id, "code": code, "parameter": parameter, "value": "blue"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert "color='blue'" in data["code"]
    assert data["run"]["success"], data["run"].get("stderr")


def test_history_restore_and_export():
    ds_id = upload_dataset()["id"]
    generated = client.post("/api/plots/generate", json={"dataset_id": ds_id, "instruction": "画柱状图"})
    assert generated.status_code == 200, generated.text
    first = generated.json()
    assert first["revision_id"]
    assert {"png", "svg", "pdf"}.issubset(set(first["export_formats"]))

    history = client.get(f"/api/plots/history/{ds_id}")
    assert history.status_code == 200
    revisions = history.json()["revisions"]
    assert revisions[0]["id"] == first["revision_id"]
    assert revisions[0]["operation"] == "generate"

    for format_name in ("png", "svg", "pdf"):
        exported = client.get(f"/api/plots/revisions/{first['revision_id']}/export/{format_name}")
        assert exported.status_code == 200, exported.text
        assert len(exported.content) > 100

    restored = client.post(f"/api/plots/history/{first['revision_id']}/restore")
    assert restored.status_code == 200, restored.text
    restored_data = restored.json()
    assert restored_data["revision_id"] != first["revision_id"]
    assert restored_data["run"]["success"]


def test_interactive_plotly_render_and_export():
    ds_id = upload_dataset()["id"]
    code = """import plotly.express as px
fig = px.scatter(df, x='revenue', y='users', color='group', title='interactive')
fig.update_layout(template='plotly_white')
"""
    resp = client.post("/api/plots/run", json={"dataset_id": ds_id, "code": code})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run"]["success"]
    assert data["run"]["interactive"]["data"]
    assert "plotly" in data["export_formats"]

    exported = client.get(f"/api/plots/revisions/{data['revision_id']}/export/plotly")
    assert exported.status_code == 200
    assert b"revenue" in exported.content


def test_generation_auto_repairs_runtime_error(monkeypatch):
    from app import llm

    ds_id = upload_dataset()["id"]
    monkeypatch.setattr(llm, "generate_plot_code", lambda *args, **kwargs: "raise ValueError('intentional test error')")
    resp = client.post("/api/plots/generate", json={"dataset_id": ds_id, "instruction": "画柱状图"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["repair_attempts"] == 1
    assert data["run"]["success"], data["run"].get("stderr")


def test_generation_auto_repairs_syntax_error(monkeypatch):
    from app import llm

    ds_id = upload_dataset()["id"]
    monkeypatch.setattr(llm, "generate_plot_code", lambda *args, **kwargs: "fig = [")
    resp = client.post("/api/plots/generate", json={"dataset_id": ds_id, "instruction": "画柱状图"})
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["repair_attempts"] == 1
    assert data["run"]["success"], data["run"].get("stderr")


def test_preset_list_has_fallbacks():
    resp = client.get("/api/presets")
    assert resp.status_code == 200
    presets = resp.json()["presets"]
    ids = {preset["id"] for preset in presets}
    assert {"default", "science", "science-nature", "science-ieee"}.issubset(ids)
    assert all(preset["has_fallback"] for preset in presets)


def test_generate_with_preset():
    ds_id = upload_dataset()["id"]
    resp = client.post(
        "/api/plots/generate",
        json={"dataset_id": ds_id, "instruction": "画一张 Nature 风格柱状图", "preset": "science-nature"},
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["preset"] == "science-nature"
    assert data["run"]["success"], data["run"].get("stderr")


def test_preset_fallback_without_local_repository(monkeypatch, tmp_path):
    from app import preset_registry

    monkeypatch.setattr(preset_registry, "PRESETS_ROOT", tmp_path / "no-cloned-presets")
    ds_id = upload_dataset()["id"]
    resp = client.post(
        "/api/plots/generate",
        json={"dataset_id": ds_id, "instruction": "画图", "preset": "science-nature"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["run"]["success"], resp.json()["run"].get("stderr")


def test_unknown_preset_is_rejected():
    ds_id = upload_dataset()["id"]
    resp = client.post(
        "/api/plots/generate",
        json={"dataset_id": ds_id, "instruction": "画图", "preset": "not-a-real-preset"},
    )
    assert resp.status_code == 400
    assert "未知预设" in resp.json()["detail"]


def test_dataset_preserves_full_data_on_import(tmp_path):
    from app import data_loader

    # 生成一个超出常规模拟采样的行数（例如 100 行），验证行数被如实记录和存储
    lines = ["index,val"] + [f"{i},{i*10}" for i in range(150)]
    csv_bytes = "\n".join(lines).encode("utf-8")
    ds = data_loader.import_dataset(tmp_path, "large.csv", csv_bytes)
    assert ds["summary"]["shape"]["rows"] == 150
    # 验证底层实际落盘文件未被随机采样破坏
    import pandas as pd
    saved_df = pd.read_csv(ds["path"])
    assert len(saved_df) == 150
    assert list(saved_df["index"][:5]) == [0, 1, 2, 3, 4]


def test_edit_plot_passes_history():
    ds_id = upload_dataset()["id"]
    gen = client.post("/api/plots/generate", json={"dataset_id": ds_id, "instruction": "画柱状图"}).json()
    resp = client.post(
        "/api/plots/edit",
        json={
            "dataset_id": ds_id,
            "code": gen["code"],
            "instruction": "按第二轮意见修改",
            "history": [
                {"role": "user", "content": "第一轮画柱状图"},
                {"role": "assistant", "content": "好的"},
            ],
        },
    )
    assert resp.status_code == 200
    assert resp.json()["run"]["success"]


def test_stats_annotator_calculations():
    from app import stats_annotator
    import pandas as pd

    data = {
        "treatment": ["A", "A", "A", "A", "B", "B", "B", "B"],
        "measurement": [10.2, 10.5, 11.0, 9.8, 25.0, 26.2, 24.8, 27.1],
    }
    df = pd.DataFrame(data)
    res = stats_annotator.compare_groups(df, "treatment", "measurement", "A", "B")
    assert res["p_value"] < 0.001
    assert res["stars"] == "***"
    assert res["mean_a"] < res["mean_b"]


def test_stats_annotation_endpoint():
    # 上传带两组对比的测试数据
    csv_content = "group,val\nctrl,10\nctrl,12\nctrl,11\ntreat,25\ntreat,28\ntreat,26\n"
    resp = client.post("/api/datasets", files={"file": ("stats_demo.csv", io.BytesIO(csv_content.encode()), "text/csv")})
    assert resp.status_code == 200
    ds_id = resp.json()["id"]

    base_code = """import matplotlib.pyplot as plt
fig, ax = plt.subplots()
means = df.groupby('group')['val'].mean()
ax.bar(range(len(means)), means.values)
ax.set_xticks(range(len(means)))
ax.set_xticklabels(means.index)
"""
    stat_resp = client.post(
        "/api/plots/stats",
        json={
            "dataset_id": ds_id,
            "code": base_code,
            "group_col": "group",
            "val_col": "val",
            "pairs": [["ctrl", "treat"]],
        },
    )
    assert stat_resp.status_code == 200, stat_resp.text
    data = stat_resp.json()
    assert data["run"]["success"], data["run"].get("stderr")
    assert "stats_results" in data
    assert len(data["stats_results"]) == 1
    assert data["stats_results"][0]["stars"] in ("*", "**", "***")
    assert "学术统计显著性标尺" in data["code"]


def test_compose_multipanel_figure():
    ds_id = upload_dataset()["id"]
    panel_1 = {"title": "Panel A: Revenue", "code": "ax.plot(df['year'], df['revenue'], marker='o')"}
    panel_2 = {"title": "Panel B: Users", "code": "ax.bar(df['year'], df['users'], color='orange')"}
    resp = client.post(
        "/api/plots/compose",
        json={
            "dataset_id": ds_id,
            "layout": "1x2",
            "panels": [panel_1, panel_2],
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run"]["success"], data["run"].get("stderr")
    assert "Subplot A" in data["code"]
    assert "Subplot B" in data["code"]
    assert "fig.tight_layout" in data["code"]


def test_mimic_figure_generator():
    ds_id = upload_dataset()["id"]
    resp = client.post(
        "/api/plots/mimic",
        json={
            "dataset_id": ds_id,
            "reference_description": "想要 Nature 风格的双轴对比曲线图，带独立次级坐标轴",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["run"]["success"], data["run"].get("stderr")
    assert "twinx" in data["code"] or "双Y轴" in data["code"]


def test_stats_annotator_edge_cases():
    from app import stats_annotator
    import pandas as pd

    # 1. 零方差常数数据测试
    df_const = pd.DataFrame({
        "group": ["Control", "Control", "Treatment", "Treatment"],
        "value": [5.0, 5.0, 5.0, 5.0],
    })
    res = stats_annotator.compare_groups(df_const, "group", "value", "Control", "Treatment")
    assert res["p_value"] == 1.0
    assert res["stars"] == "ns"
    assert res["statistic"] == 0.0

    # 2. 全负数数据测试
    df_neg = pd.DataFrame({
        "group": ["A", "A", "B", "B"],
        "value": [-20.0, -22.0, -10.0, -12.0],
    })
    code = "import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.bar([0, 1], [-21, -11])\n"
    annotated_code, results = stats_annotator.inject_stat_brackets(
        code, df_neg, "group", "value", [("A", "B")]
    )
    assert "_y_span = max(_y_max - _y_min, 1e-4)" in annotated_code
    assert "_bracket_y = _y_max + _y_span * 0.05" in annotated_code
    assert len(results) == 1
    assert results[0]["group_a"] == "A"


def test_figure_composer_scope_isolation():
    from app import figure_composer

    panels = [
        {"title": "Panel 1", "code": "val = 100\nax.plot([1, 2], [val, val])"},
        {"title": "Panel 2", "code": "val = 200\nax.plot([1, 2], [val, val])"},
    ]
    composed = figure_composer.compose_multipanel_figure(panels, layout="1x2")
    assert "def _draw_panel_0(ax):" in composed
    assert "def _draw_panel_1(ax):" in composed
    assert "plt.sca(ax)" in composed
    assert "_draw_panel_0(ax_0)" in composed
    assert "_draw_panel_1(ax_1)" in composed


def test_visual_critic_and_compliance():
    ds_id = upload_dataset()["id"]
    # 先生成一张标准图
    gen = client.post("/api/plots/generate", json={"dataset_id": ds_id, "instruction": "画散点图"}).json()
    assert gen["revision_id"]

    # 1. 运行视觉质检
    critique_resp = client.post("/api/plots/critique", json={"revision_id": gen["revision_id"]})
    assert critique_resp.status_code == 200, critique_resp.text
    critique_data = critique_resp.json()
    assert "score" in critique_data
    assert "suggestions" in critique_data
    assert isinstance(critique_data["suggestions"], list)

    # 2. 运行顶刊合规检查 (Nature)
    comp_resp = client.get(f"/api/plots/revisions/{gen['revision_id']}/compliance/nature")
    assert comp_resp.status_code == 200, comp_resp.text
    comp_data = comp_resp.json()
    assert comp_data["journal"] == "Nature Portfolio"
    assert "checks" in comp_data
    assert any("矢量图" in check["item"] for check in comp_data["checks"])


def test_auth_boundary_enforcement():
    """测试未授权请求拦截与 Session Token 校验。"""
    anon_client = TestClient(app)
    # 1. 无 token 访问数据集列表 -> 401
    resp = anon_client.get("/api/datasets")
    assert resp.status_code == 401

    # 2. 无 token 修改 LLM 配置 -> 401
    resp = anon_client.put("/api/config/llm", json={"model": "deepseek-chat"})
    assert resp.status_code == 401

    # 3. 携带错误 token -> 401
    resp = anon_client.get("/api/datasets", headers={"X-Session-Token": "invalid_fake_token"})
    assert resp.status_code == 401

    # 4. 携带正确 token -> 200
    resp = anon_client.get("/api/datasets", headers={"X-Session-Token": TEST_SESSION_TOKEN})
    assert resp.status_code == 200


def test_ssrf_protection():
    """测试 LLM Base URL 的 SSRF 攻击防御。"""
    # 1. 禁止访问云元数据服务
    resp = client.put("/api/config/llm", json={"base_url": "http://169.254.169.254/latest"})
    assert resp.status_code == 400
    assert "禁止" in resp.json()["detail"] or "元数据" in resp.json()["detail"]

    # 2. 禁止私有内网 IP (10.x.x.x)
    resp = client.put("/api/config/llm", json={"base_url": "http://10.0.0.1:8000/v1"})
    assert resp.status_code == 400
    assert "私有内网" in resp.json()["detail"] or "禁止" in resp.json()["detail"]

    # 3. 禁止私有内网 IP (192.168.x.x)
    resp = client.put("/api/config/llm", json={"base_url": "http://192.168.1.1:8000/v1"})
    assert resp.status_code == 400


def test_composer_validation():
    """测试多子图编排器的面板容量与布局校验。"""
    ds_id = upload_dataset()["id"]
    p1 = {"title": "A", "code": "ax.plot([1, 2], [3, 4])"}
    p2 = {"title": "B", "code": "ax.bar([1, 2], [3, 4])"}
    p3 = {"title": "C", "code": "ax.scatter([1, 2], [3, 4])"}

    # 1. 1x2 布局传入 3 个面板超限 -> 400
    resp = client.post(
        "/api/plots/compose",
        json={"dataset_id": ds_id, "layout": "1x2", "panels": [p1, p2, p3]},
    )
    assert resp.status_code == 400
    assert "最多支持 2 个面板" in resp.json()["detail"]

    # 2. 未知布局 -> 400
    resp = client.post(
        "/api/plots/compose",
        json={"dataset_id": ds_id, "layout": "unknown_3x3", "panels": [p1]},
    )
    assert resp.status_code == 400
    assert "不支持的布局类型" in resp.json()["detail"]


def test_compliance_validation_unknown_journal():
    """测试合规检查对未知期刊的明确提示。"""
    ds_id = upload_dataset()["id"]
    gen = client.post("/api/plots/generate", json={"dataset_id": ds_id, "instruction": "柱状图"}).json()
    rev_id = gen["revision_id"]

    resp = client.get(f"/api/plots/revisions/{rev_id}/compliance/unknown_journal_xyz")
    assert resp.status_code == 200
    data = resp.json()
    assert not data["passed"]
    assert "未知期刊" in data["journal"]
    assert "未收录" in data["checks"][0]["detail"]


def test_sandbox_ast_blocks_dangerous_escapes():
    """测试沙箱 AST 静态分析对原型链遍历与 __import__ 逃逸的封堵。"""
    from app.sandbox import validate_script, SandboxError

    # 1. 封堵 __import__
    with pytest.raises(SandboxError, match="禁止"):
        validate_script("__import__('os').system('dir')")

    # 2. 封堵 __subclasses__ 原型链反射
    with pytest.raises(SandboxError, match="禁止"):
        validate_script("x = ().__class__.__bases__[0].__subclasses__()")

    # 3. 封堵 __builtins__
    with pytest.raises(SandboxError, match="禁止"):
        validate_script("b = __builtins__")


def test_database_cleans_up_revision_output_directories(tmp_path):
    """测试删除数据集时级联清理磁盘上的 output 目录。"""
    ds_id = upload_dataset()["id"]
    gen = client.post("/api/plots/generate", json={"dataset_id": ds_id, "instruction": "折线图"}).json()
    rev_id = gen["revision_id"]
    from app.database import get_revision
    rev = get_revision(rev_id)
    out_dir = Path(rev["output_dir"])
    assert out_dir.exists()

    # 删除数据集
    del_resp = client.delete(f"/api/datasets/{ds_id}")
    assert del_resp.status_code == 200

    # 验证数据库记录已删除且磁盘物理目录已清理
    assert not out_dir.exists()





