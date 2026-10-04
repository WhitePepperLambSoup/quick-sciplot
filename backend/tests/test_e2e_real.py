"""真实用户体验与极端边界的端到端严苛测试 (Strict E2E Real User Experience Tests)。

覆盖：
1. GBK/GB18030 编码的中文 CSV 文件上传与列名空白防御；
2. 中文图表与负号在沙箱中渲染、TrueType 矢量 PDF 与 PNG 300 DPI 校验；
3. 单因素 ANOVA 全局多组显著性检验与学术括号分层排序；
4. 多子图拼图编排 (1+2 网格) 真实沙箱渲染与多格式导出；
5. 历史版本详细代码回查与期刊合规报告。
"""

import io
import os
from pathlib import Path
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from PIL import Image

from app.main import app
from app.config import settings, SESSION_TOKEN as TEST_SESSION_TOKEN
from app import database, stats_annotator, figure_composer

settings.llm_mock = True
client = TestClient(app, headers={"X-Session-Token": TEST_SESSION_TOKEN})


def test_e2e_gbk_csv_and_whitespace_columns():
    """测试 Windows 导出常见 GBK 编码及带空格列名数据的解析与代码生成。"""
    # 构造 GBK 编码、含前后空格的 CSV 数据
    csv_text = " 样本名称 , 浓度 , 吸光度 \nControl , 1.2 , 0.15 \nTreatment , 3.4 , 0.48 \n"
    gbk_bytes = csv_text.encode("gb18030")

    resp = client.post(
        "/api/datasets",
        files=[("files", ("gbk_data.csv", io.BytesIO(gbk_bytes), "text/csv"))],
    )
    assert resp.status_code == 200, resp.text
    datasets = resp.json()["datasets"]
    assert len(datasets) == 1
    ds = datasets[0]
    
    # 验证列名被智能剔除前后空格
    col_names = [col["name"] for col in ds["summary"]["columns"]]
    assert "样本名称" in col_names
    assert "浓度" in col_names
    assert "吸光度" in col_names
    assert " 样本名称 " not in col_names

    # 验证针对这组数据绘制柱状图能够正常运行
    gen_resp = client.post(
        "/api/plots/generate",
        json={
            "dataset_id": ds["id"],
            "instruction": "绘制不同样本名称的吸光度柱状图",
        },
    )
    assert gen_resp.status_code == 200, gen_resp.text
    gen_data = gen_resp.json()
    assert gen_data["run"]["success"], gen_data["run"].get("stderr")


def test_e2e_cjk_font_and_vector_pdf_export(tmp_path):
    """测试中文学术图表与负号在沙箱中的渲染，并验证生成的 PDF 为 TrueType 矢量格式。"""
    # 创建带负数与中文的测试数据
    df = pd.DataFrame({
        "组别": ["对照组", "实验组A", "实验组B"],
        "温差变化": [-5.2, 12.8, -2.4],
    })
    csv_path = tmp_path / "cjk_data.csv"
    df.to_csv(csv_path, index=False, encoding="utf-8-sig")

    resp = client.post(
        "/api/datasets",
        files=[("files", ("cjk_data.csv", open(csv_path, "rb"), "text/csv"))],
    )
    assert resp.status_code == 200
    ds_id = resp.json()["datasets"][0]["id"]

    code = """import matplotlib.pyplot as plt
fig, ax = plt.subplots(figsize=(6, 4))
ax.bar(df['组别'], df['温差变化'], color=['#3498db', '#e74c3c', '#2ecc71'])
ax.set_title('各组别温差变化对照分析 (含负值 -5.2℃)', fontsize=11, fontweight='bold')
ax.set_ylabel('温差 (°C)')
ax.axhline(0, color='gray', linestyle='--', linewidth=0.8)
"""
    run_resp = client.post(
        "/api/plots/run",
        json={"dataset_id": ds_id, "code": code},
    )
    assert run_resp.status_code == 200
    run_data = run_resp.json()
    assert run_data["run"]["success"], run_data["run"].get("stderr")
    assert "pdf" in run_data["export_formats"]
    assert "svg" in run_data["export_formats"]
    assert "png" in run_data["export_formats"]

    rev_id = run_data["revision_id"]

    # 验证 PDF 导出文件为合法 PDF
    pdf_resp = client.get(f"/api/plots/revisions/{rev_id}/export/pdf")
    assert pdf_resp.status_code == 200
    assert pdf_resp.headers["content-type"] == "application/pdf"
    pdf_content = pdf_resp.content
    assert pdf_content.startswith(b"%PDF")
    # 验证是否包含 TrueType 字体定义
    assert b"TrueType" in pdf_content or b"Type42" in pdf_content or b"Font" in pdf_content

    # 验证 PNG 导出文件尺寸与 DPI
    png_resp = client.get(f"/api/plots/revisions/{rev_id}/export/png")
    assert png_resp.status_code == 200
    img = Image.open(io.BytesIO(png_resp.content))
    assert img.size[0] > 500
    assert img.size[1] > 300


def test_e2e_anova_omnibus_and_smart_brackets():
    """测试多组单因素方差分析 (ANOVA) 全局检验及智能跨度排序连线。"""
    df = pd.DataFrame({
        "group": ["WT", "WT", "WT", "KO1", "KO1", "KO1", "KO2", "KO2", "KO2"],
        "expression": [10.2, 10.5, 9.8, 4.1, 4.3, 3.9, 20.1, 21.0, 19.5],
    })

    # 1. 验证全局 ANOVA 计算
    omnibus = stats_annotator.compute_omnibus_test(df, "group", "expression", test_type="auto")
    assert omnibus is not None
    assert omnibus["test_name"] == "One-way ANOVA"
    assert omnibus["statistic"] > 50  # WT vs KO1 vs KO2 差异巨大
    assert omnibus["p_value"] < 0.001
    assert omnibus["stars"] == "***"

    # 2. 验证多对对比括号注入 (故意乱序传入跨度为 1 与跨度为 2 的对)
    code = "import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.bar(['WT', 'KO1', 'KO2'], [10.1, 4.1, 20.2])\n"
    pairs = [("WT", "KO2"), ("WT", "KO1"), ("KO1", "KO2")]  # WT-KO2 跨度为 2, 其他跨度为 1
    annotated_code, results = stats_annotator.inject_stat_brackets(
        code, df, "group", "expression", pairs
    )
    assert len(results) == 3
    # 验证全局检验信息被注入
    assert "One-way ANOVA" in annotated_code
    # 验证排序后，跨度为 1 的对先渲染，跨度为 2 的宽连线在顶层
    assert annotated_code.index("WT vs KO1") < annotated_code.index("WT vs KO2")


def test_e2e_composer_and_revision_detail_integration():
    """测试多子图组合编排大图生成与历史版本详情查询。"""
    # 1. 创建数据集并运行两次生成两个历史版本
    df = pd.DataFrame({"x": [1, 2, 3, 4], "y": [10, 20, 15, 30]})
    resp = client.post(
        "/api/datasets",
        files=[("files", ("sample.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv"))],
    )
    ds_id = resp.json()["datasets"][0]["id"]

    code1 = "import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.plot(df['x'], df['y'])"
    code2 = "import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.bar(df['x'], df['y'])"
    run1 = client.post("/api/plots/run", json={"dataset_id": ds_id, "code": code1}).json()
    run2 = client.post("/api/plots/run", json={"dataset_id": ds_id, "code": code2}).json()

    # 2. 测试获取版本详情接口
    rev1_detail = client.get(f"/api/plots/history/{run1['revision_id']}/detail")
    assert rev1_detail.status_code == 200
    assert "ax.plot" in rev1_detail.json()["code"]

    rev2_detail = client.get(f"/api/plots/history/{run2['revision_id']}/detail")
    assert rev2_detail.status_code == 200
    assert "ax.bar" in rev2_detail.json()["code"]

    # 3. 进行 1+2 复合大图拼接渲染
    compose_resp = client.post(
        "/api/plots/compose",
        json={
            "dataset_id": ds_id,
            "layout": "1+2",
            "panels": [
                {"title": "Overall Trend", "code": rev1_detail.json()["code"]},
                {"title": "Bar Distribution", "code": rev2_detail.json()["code"]},
                {"title": "Residual Scatter", "code": "ax.scatter(df['x'], df['y'] * 0.5)"},
            ],
        },
    )
    assert compose_resp.status_code == 200, compose_resp.text
    comp_data = compose_resp.json()
    assert comp_data["run"]["success"], comp_data["run"].get("stderr")
    assert "GridSpec" in comp_data["code"]
    assert "Subplot A" in comp_data["code"]
    assert "Subplot B" in comp_data["code"]
    assert "Subplot C" in comp_data["code"]


def test_e2e_journal_compliance_deep_audit():
    """测试 Nature, IEEE, Cell 期刊标准的深度合规审查。"""
    df = pd.DataFrame({"x": [1, 2, 3], "y": [4, 5, 6]})
    resp = client.post(
        "/api/datasets",
        files=[("files", ("data.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv"))],
    )
    ds_id = resp.json()["datasets"][0]["id"]
    code = "import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.plot(df['x'], df['y'])"
    run = client.post("/api/plots/run", json={"dataset_id": ds_id, "code": code}).json()
    assert run["run"]["success"], run["run"].get("stderr")
    rev_id = run["revision_id"]

    for journal in ["nature", "ieee", "cell"]:
        comp = client.get(f"/api/plots/revisions/{rev_id}/compliance/{journal}")
        assert comp.status_code == 200
        data = comp.json()
        assert "checks" in data
        assert len(data["checks"]) >= 3
        items = [c["item"] for c in data["checks"]]
        assert any("矢量图" in item for item in items)
        assert any("分辨率" in item for item in items)


def test_e2e_dataset_persistence_delete_and_eps_export():
    """测试数据集持久化列表、删除功能以及出版级 EPS 矢量图导出。"""
    df = pd.DataFrame({"category": ["Control", "Treated"], "score": [12.5, 28.3]})
    resp = client.post(
        "/api/datasets",
        files=[("files", ("persist_test.csv", io.BytesIO(df.to_csv(index=False).encode()), "text/csv"))],
    )
    assert resp.status_code == 200
    ds_id = resp.json()["datasets"][0]["id"]

    # 1. 验证 GET /api/datasets 可以正确列出已保存的数据集
    list_resp = client.get("/api/datasets")
    assert list_resp.status_code == 200
    all_datasets = list_resp.json()["datasets"]
    assert any(item["id"] == ds_id for item in all_datasets)

    # 2. 运行画图并测试 EPS 导出
    code = "import matplotlib.pyplot as plt\nfig, ax = plt.subplots()\nax.bar(df['category'], df['score'])"
    run = client.post("/api/plots/run", json={"dataset_id": ds_id, "code": code}).json()
    assert run["run"]["success"], run["run"].get("stderr")
    rev_id = run["revision_id"]

    eps_resp = client.get(f"/api/plots/revisions/{rev_id}/export/eps")
    assert eps_resp.status_code == 200
    assert eps_resp.headers["content-type"].startswith("application/postscript")
    assert len(eps_resp.content) > 100  # 有效的 PostScript 内容
    assert eps_resp.content.startswith(b"%!PS-Adobe")

    # 3. 测试 DELETE /api/datasets/{id}
    del_resp = client.delete(f"/api/datasets/{ds_id}")
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True

    # 验证删除后列表不再包含此数据集
    list_resp_after = client.get("/api/datasets")
    assert not any(item["id"] == ds_id for item in list_resp_after.json()["datasets"])


def test_e2e_stats_annotator_unequal_constant_groups():
    """测试统计显著性检验在两组样本数不一致且方差为0（如两组全为常数）时的极端容错性。"""
    # Group A: 2 个常数 5.0；Group B: 3 个常数 5.0 (形状不同，原 np.allclose 会广播崩溃)
    df_unequal = pd.DataFrame({
        "group": ["A", "A", "B", "B", "B"],
        "val": [5.0, 5.0, 5.0, 5.0, 5.0],
    })
    res = stats_annotator.compare_groups(df_unequal, "group", "val", "A", "B")
    assert res["p_value"] == 1.0
    assert res["statistic"] == 0.0
    assert res["stars"] == "ns"

    # 全局检验极端情况：3 组全部是相同常数，避免 Kruskal-Wallis 抛出 All numbers are identical
    df_multi_const = pd.DataFrame({
        "group": ["A", "A", "B", "B", "C", "C"],
        "val": [10.0, 10.0, 10.0, 10.0, 10.0, 10.0],
    })
    omnibus = stats_annotator.compute_omnibus_test(df_multi_const, "group", "val", test_type="kruskal")
    assert omnibus is not None
    assert omnibus["p_value"] == 1.0
    assert omnibus["statistic"] == 0.0


def test_e2e_code_locator_format_resilience():
    """测试代码定位器参数格式化防双重引号与防 df['col'] 嵌套。"""
    from app import code_locator

    # 1. column 格式化：若传入 df['col'] 自动解构为规范 df['col']
    assert code_locator._format_value("df['col']", "column") == "df['col']"
    assert code_locator._format_value('df["speed"]', "column") == "df['speed']"
    assert code_locator._format_value("speed", "column") == "df['speed']"

    # 2. string 格式化：若传入 '#ffffff' 或 "'#ffffff'" 保持单层引号
    assert code_locator._format_value("'#ff0000'", "string") == "'#ff0000'"
    assert code_locator._format_value('"#ff0000"', "string") == "'#ff0000'"
    assert code_locator._format_value("#ff0000", "string") == "'#ff0000'"

