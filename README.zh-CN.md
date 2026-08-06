# Quick SciPlot

[English](README.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml/badge.svg)](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml)

Quick SciPlot 是一个开源的 AI 辅助科研画图桌面/网页应用。
用户可以导入一个或多个数据文件，用自然语言描述想要的图，然后通过直观界面调整图像、代码、变量和科研风格。

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 主要功能

- 支持 CSV、TSV、Excel、JSON，并自动生成数据摘要。
- 一次导入多个文件，勾选后可按行合并，并增加 `source_file` 来源列。
- 通过 OpenAI 兼容 API 生成 Matplotlib、Seaborn 或 Plotly 图表。
- 支持 SciencePlots、Nature、IEEE、LovelyPlots 以及内置兜底风格。
- 完整代码查看、行高亮和每条绘图语句的中英文解释。
- 可直接选择 x/y 数据列，也可以调整颜色、透明度、线宽、标签等参数。
- SQLite 保存生成、编辑、参数调整和恢复历史。
- 支持 PNG、SVG、PDF 和 Plotly JSON 导出。
- 无 Docker 时使用内置 worker；Docker 是可选的增强隔离模式。
- 同一套 React WebUI 可在浏览器运行，也可嵌入 Tauri 2 桌面 GUI。
- 支持中文/English 界面切换。

## 软件架构

```text
React + Vite WebUI
        │ 浏览器或 Tauri WebView
        ▼
本地 FastAPI 后端
        ├── LLM provider 适配层
        ├── AST 代码定位与参数编辑
        ├── process / Docker / 内置 worker 沙箱
        ├── SQLite 版本历史
        └── Matplotlib / Seaborn / Plotly 渲染
```

## 快速开始

### 浏览器开发模式

```bash
cd backend
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 复制 .env.example 为 .env，并配置 OpenAI 兼容模型。
$env:LLM_MOCK=1
python -m uvicorn app.main:app --reload
```

另开一个终端：

```bash
cd frontend
npm install
npm run dev
```

打开 `http://localhost:5173`。

### 桌面开发模式

Tauri 桌面壳会启动本地 FastAPI，并嵌入同一套 React WebUI：

```bash
cd frontend
npm run desktop:dev
```

### Windows 安装包

先安装构建依赖：

```bash
cd backend
pip install -r requirements-build.txt
cd ..\frontend
npm run desktop:build
```

NSIS 和 MSI 安装包位于 `frontend/src-tauri/target/release/bundle/`。
正式构建包含 PyInstaller 后端 sidecar，目标电脑不需要单独安装 Python。

### 可选 Docker 隔离

内置 worker 模式不需要 Docker。若要启用更强的容器隔离：

```bash
cd backend
docker build -f Dockerfile.sandbox -t quick-sciplot-sandbox:latest .
```

然后在程序设置中选择 Docker，或在 `.env` 设置 `SANDBOX_MODE=docker`。

## 多文件作图

多个文件导入后仍然是独立数据集。用户勾选文件并点击“合并选中文件”后，程序会按行拼接、保留所有列、对缺失列填空，并增加 `source_file` 列，AI 可以据此按文件来源分组或着色。

程序不会猜测 join key，也不会擅自进行关系型连接。后续可以在用户明确指定连接键和连接类型后增加 join 模式。

## 评测

运行不调用外部 API 的 mock 评测：

```bash
cd backend
python evaluate.py --mock --output data/evaluation-report.json
```

使用 `model_matrix.example.json` 比较多个模型，并生成 HTML 人工评测报告：

```bash
python evaluate.py --model-config model_matrix.example.json \
  --output reports/models.json \
  --human-report reports/models.html
```

## 安全说明

程序会执行 LLM 生成的 Python 代码。process 模式提供静态 import 检查、危险调用拦截、独立进程和超时限制；Docker 模式还会禁用网络、使用只读根文件系统、丢弃 capabilities、以非 root 用户运行并限制资源。

不要把当前本地 FastAPI 服务暴露到公网。详见 [SECURITY.md](SECURITY.md)。

## 目录结构

- `backend/`：FastAPI 服务、数据处理、LLM、沙箱、测试和 sidecar 构建脚本。
- `frontend/`：React + Vite WebUI，以及 `src-tauri/` 下的 Tauri 2 桌面壳。
- `docs/`：调研计划和评测文档。
- `presets/`、`references/`、`skills/`：可选的第三方本地仓库，已加入 Git 忽略。

## 测试

```bash
cd backend
python -m pytest tests -q
```

前端使用 `npm run build` 检查。

## 许可证

MIT License，详见 [LICENSE](LICENSE)。
