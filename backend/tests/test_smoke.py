"""M1 闭环冒烟测试：上传 -> 摘要 -> 生成 -> 渲染 -> 编辑 -> 安全检查。"""

import io
import os
import sys

import pytest

os.environ["LLM_MOCK"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

client = TestClient(app)

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
