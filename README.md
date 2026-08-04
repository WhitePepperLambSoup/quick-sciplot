# 快捷科研画图（Quick SciPlot）

> 上传数据 → 自然语言告诉 AI 要画什么 → 沙箱内自动出图 → 对话微调 → 直观的代码定位面板。
> An LLM-powered quick scientific plotting app. Import data, describe the figure in plain language, and let AI generate, execute, and refine the plotting code — all through an intuitive UI instead of raw code.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 特性

- **数据导入即摘要**：支持 CSV / TSV / Excel / JSON，自动推断列类型并生成统计摘要（LLM 依据摘要理解数据）
- **LLM 生成图表**：任意 OpenAI 兼容 API（DeepSeek / OpenAI / 通义 / 智谱 / 本地 vLLM），无需绑定厂商
- **沙箱执行**：LLM 生成的代码在受限子进程中执行，白名单 import、超时限制，产出 PNG/SVG
- **多轮对话调整**：改颜色、改轴、加误差棒……自然语言即可，只改相关代码
- **代码定位工作台**：完整代码行号高亮、语句解释、颜色/透明度/线宽/标题等参数表单，点击参数即可应用并重绘
- **风格预设**：可选默认、SciencePlots、Nature、IEEE、色盲友好、LovelyPlots、tueplots 等预设；本地有第三方仓库时自动使用，没有时使用内置兜底
- **版本历史与导出**：SQLite 保存每次生成/编辑/参数调整，可恢复任意成功版本；支持 PNG/SVG/PDF 下载

## 快速开始

### 1. 后端（Python 3.10+）

```bash
cd backend
python -m venv .venv
# Windows: .venv\Scripts\activate   /   macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
```

配置密钥：复制 `.env.example` 为 `.env` 并填写 LLM 配置（默认 DeepSeek 兼容接口）。

无密钥时可用 mock 模式验证全流程：

```bash
# Windows
$env:LLM_MOCK=1
python -m uvicorn app.main:app --reload
```

### 2. 前端（Node 18+）

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 ，上传数据文件 → 描述想要画的图 → 查看结果。

预设仓库是可选的本地资源。若已经按调研计划克隆了 `presets/SciencePlots` 等仓库，启动后会自动发现；全新 GitHub 克隆没有这些目录时，预设仍可通过内置样式运行。

## API 概览

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/datasets` | 上传数据文件，返回数据集 id 与摘要 |
| GET | `/api/datasets/{id}` | 获取数据集摘要与预览 |
| GET | `/api/presets` | 获取风格预设及本地资源状态 |
| POST | `/api/plots/generate` | 依据指令 + 数据摘要生成并执行绘图代码 |
| POST | `/api/plots/edit` | 在已有代码上按指令修改并重新执行 |
| POST | `/api/plots/run` | 直接执行一段代码（编辑预览用） |
| POST | `/api/plots/parameter` | 修改定位到的一个参数并重新执行 |
| GET | `/api/plots/history/{dataset_id}` | 获取数据集的版本历史 |
| POST | `/api/plots/history/{revision_id}/restore` | 恢复版本并创建新版本 |
| GET | `/api/plots/revisions/{revision_id}/export/{format}` | 下载 PNG/SVG/PDF |

## 目录结构

```
├── backend/           # FastAPI 后端
│   └── app/
│       ├── main.py        # 应用入口与路由
│       ├── config.py      # 环境配置
│       ├── database.py     # SQLite 数据集与版本历史
│       ├── data_loader.py # 数据导入与摘要
│       ├── llm.py         # LLM 调用与提示词
│       ├── preset_registry.py # 风格预设注册与本地资源发现
│       ├── sandbox.py     # 沙箱执行绘图代码
│       └── code_locator.py# AST 代码片段、参数定位与安全替换
├── frontend/          # React + Vite + TypeScript 前端
├── presets/           # 本地克隆的风格预设仓库（不入库，见 README 下方说明）
├── references/        # 本地克隆的参考实现（不入库）
└── skills/            # 本地克隆的绘图 skill 素材（不入库）
```

> `presets/`、`references/`、`skills/` 是本地克隆的第三方仓库（SciencePlots、LovelyPlots、LIDA、PlotCraft、AgentFigureGallery 等），用于离线参考与预设素材，**不随本仓库提交**。如需分发请保留各自上游许可证。

## 安全说明

LLM 会生成并执行任意 Python 代码。当前沙箱为"白名单 import + 超时 + 子进程隔离"的轻量方案，适合本地个人使用；**不要**将本服务暴露到公网。计划后续提供 Docker 强隔离。

## 路线图

- [x] M0 调研：生态扫描与预设仓库收集
- [x] M1 最小闭环：数据导入 → LLM 生成 → 沙箱渲染 → 对话调整
- [x] M2 预设系统：风格包接入与选择、第三方风格缺失时内置兜底
- [x] M3 代码定位增强：完整代码行高亮、参数表单化、直接编辑与重绘
- [x] M4a 版本历史、版本恢复、PNG/SVG/PDF 导出
- [ ] M4b Plotly 交互图支持、错误自修复循环

## 许可证

[MIT](LICENSE) © pic contributors
