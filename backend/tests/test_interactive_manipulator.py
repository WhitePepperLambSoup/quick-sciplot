"""交互式图像修正测试 (Tests for Interactive Plot Correction & Code Sync)。"""

import io
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.config import settings, SESSION_TOKEN as TEST_SESSION_TOKEN
from app import visual_manipulator

settings.llm_mock = True
client = TestClient(app, headers={"X-Session-Token": TEST_SESSION_TOKEN})


def test_visual_manipulator_adjust_hline_insert_and_update():
    base_code = """import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.plot([1, 2, 3], [10, 20, 30])
plt.tight_layout()
"""
    # 1. 初始注入一条水平参考线
    modified = visual_manipulator.adjust_hline(base_code, 15.5, color="red", linestyle="--", label="Threshold")
    assert "ax.axhline(y=15.5" in modified
    assert modified.index("ax.axhline") < modified.index("plt.tight_layout()")

    # 2. 对已有参考线进行拖拽更新
    updated = visual_manipulator.adjust_hline(modified, 22.8)
    assert "ax.axhline(y=22.8" in updated
    assert "15.5" not in updated

    # 3. 静态元素检查器能够提取出该参考线
    elements = visual_manipulator.inspect_code_elements(updated)
    assert 22.8 in elements["hlines"]


def test_visual_manipulator_adjust_vline_and_limits():
    base_code = """import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.scatter([1, 2, 3], [4, 5, 6])
"""
    # 1. 注入垂直线
    with_vline = visual_manipulator.adjust_vline(base_code, 2.5, color="blue", linestyle=":")
    assert "ax.axvline(x=2.5" in with_vline

    # 2. 拖拽调整垂直线
    updated_vline = visual_manipulator.adjust_vline(with_vline, 1.8)
    assert "ax.axvline(x=1.8" in updated_vline

    # 3. 调整坐标轴极值边界 (ylim, xlim)
    with_limits = visual_manipulator.adjust_ylim(updated_vline, -10.0, 50.0)
    with_limits = visual_manipulator.adjust_xlim(with_limits, 0.0, 5.0)
    assert "ax.set_ylim(-10.0, 50.0)" in with_limits
    assert "ax.set_xlim(0.0, 5.0)" in with_limits

    elements = visual_manipulator.inspect_code_elements(with_limits)
    assert elements["ylim"] == [-10.0, 50.0]
    assert elements["xlim"] == [0.0, 5.0]
    assert 1.8 in elements["vlines"]


def test_e2e_interactive_adjust_api_endpoint():
    """端到端测试：在真实沙箱中触发交互式修正，验证代码更新、图片重绘以及元数据导出。"""
    df = pd.DataFrame({"timepoint": [1, 2, 3, 4], "concentration": [2.5, 5.0, 8.2, 12.0]})
    resp = client.post(
        "/api/datasets",
        files=[("files", ("curve.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv"))],
    )
    assert resp.status_code == 200
    ds_id = resp.json()["datasets"][0]["id"]

    code = """import matplotlib.pyplot as plt
fig, ax = plt.subplots()
ax.plot(df['timepoint'], df['concentration'], marker='o')
"""
    # 初始运行并验证元数据输出
    initial_run = client.post("/api/plots/run", json={"dataset_id": ds_id, "code": code}).json()
    assert initial_run["run"]["success"]
    assert "meta" in initial_run
    meta = initial_run["meta"]
    assert meta is not None
    assert "xlim" in meta
    assert "ylim" in meta
    assert "bbox" in meta
    assert len(meta["bbox"]) == 4

    # 动作 1：用户拖拽添加一条水平阈值线 y = 7.5
    adjust1 = client.post(
        "/api/plots/interactive-adjust",
        json={
            "dataset_id": ds_id,
            "code": code,
            "action": "hline",
            "params": {"y": 7.5, "color": "red", "linestyle": "--", "label": "Cutoff"},
        },
    )
    assert adjust1.status_code == 200, adjust1.text
    data1 = adjust1.json()
    assert data1["run"]["success"]
    assert "ax.axhline(y=7.5" in data1["code"]
    assert data1["meta"] is not None
    assert 7.5 in data1["inspected"]["hlines"]

    # 动作 2：用户在画布上直接拖拽坐标轴上界，调整 ylim 到 [0, 20]
    adjust2 = client.post(
        "/api/plots/interactive-adjust",
        json={
            "dataset_id": ds_id,
            "code": data1["code"],
            "action": "ylim",
            "params": {"ymin": 0.0, "ymax": 20.0},
        },
    )
    assert adjust2.status_code == 200, adjust2.text
    data2 = adjust2.json()
    assert data2["run"]["success"]
    assert "ax.set_ylim(0.0, 20.0)" in data2["code"]
    assert "ax.axhline(y=7.5" in data2["code"]  # 之前的参考线依然完整保留
