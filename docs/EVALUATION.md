# 绘图评测

`backend/evaluation_cases.json` 提供一组小型、可重复的静态图与交互图用例。评测会检查：

- LLM 是否返回非空代码
- 代码是否能在当前沙箱中成功执行
- 输出是否包含预期格式（PNG/SVG/PDF 或 Plotly JSON）
- 每个用例的耗时和错误摘要

## Mock 模式

不调用外部 API，只验证数据加载、代码执行和渲染链路：

```bash
cd backend
python evaluate.py --mock
```

## 真实模型模式

先配置 `backend/.env` 中的 `LLM_API_KEY`、`LLM_BASE_URL` 和 `LLM_MODEL`，再运行：

```bash
cd backend
python evaluate.py
```

Mock 通过只代表执行链路通过，不能代表真实 LLM 的绘图质量。后续应增加人工审美评分、数据忠实性检查和不同模型的对比报告。
