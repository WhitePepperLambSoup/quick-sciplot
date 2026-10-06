# Quick SciPlot

[English](README.md) | [简体中文](README.zh-CN.md)

Quick SciPlot 是一个开源的 AI 辅助科研画图桌面/网页应用。
用户可以导入一个或多个数据文件，用自然语言描述想要的图，然后通过直观界面调整图像、代码、变量和科研风格。

[![CI](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml/badge.svg)](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 主要功能

**数据**

- 支持 CSV、TSV、TXT（自动识别制表符/逗号/分号）、Excel、JSON；可点按钮、按 Ctrl+O 或直接把文件拖进窗口导入。
- **数据工作台**：分页查看原始数据（双击单元格可修正数值），筛选行、宽表转长表、选择/排序列、删除缺失值，并可按指定键连接两个数据集。每一步都会生成新数据集，原数据不变。
- **在图上拖动数据点修正数据**：打开“拖动数据点”后，散点、折线顶点、逐行柱子、抖动散点等直接画出原始数值的点都会出现手柄，并自动对应到数据行（Matplotlib 与 Plotly、线性/对数轴、分类或日期横轴都支持）。可单点或框选多点一起拖、锁定方向、方向键微调、输入精确值、设为缺失值，应用前可撤销/重做。应用后另存为新的数据集版本并重新出图，原数据不会被覆盖；每个单元格的原值、新值、时间和原因都记录在“修正记录”里，导出项目包时附带 `data_corrections.csv`。
- 多个文件可按行合并，并增加 `source_file` 来源列。

**作图**

- 通过任意 OpenAI 兼容 API 或**本机模型**（Ollama、LM Studio）生成 Matplotlib、Seaborn、Plotly 图表。代码边生成边显示，可随时**取消**。
- **科研图模板**（不调用模型）：火山图、Kaplan-Meier 生存曲线（含 log-rank 检验）、PCA、聚类热图、剂量反应曲线（4PL，标注 EC50）、相关性下三角热图、柱状图 + 散点（SD/SEM）。
- **统计**：Welch t、Mann-Whitney U、配对 t、Wilcoxon 符号秩、Tukey HSD，可选 Bonferroni、FDR 或不校正，自动画括号与星号；**回归拟合**并在图上标注方程与 R²。
- **多图拼版**（7 种期刊布局）、**论文图复刻**、**交互式修正**（Matplotlib 与 Plotly 图都支持参考线和 X/Y 轴范围）。
- **排版体检**：规则快速检查或 **AI 视觉审查**；**期刊合规**（Nature / IEEE / Cell），一键适配单栏或双栏宽度。
- SciencePlots、Nature、IEEE、LovelyPlots 以及内置兜底风格。

**代码与版本**

- 完整代码编辑器：语法高亮、撤销、Ctrl+Enter 运行，运行出错时高亮出错行。
- 每次生成、编辑、恢复都会保存为版本；可命名、收藏（收藏的版本不会被自动清理），并**对比**任意两个版本的图片与代码差异。
- **批量出图**：把当前代码套用到多个数据集，打包下载全部图片。
- 导出 PNG（300 DPI）、SVG、PDF、EPS、Plotly JSON、**可独立运行的 Python 脚本**，或**可复现项目包**（数据 + 脚本 + 图片）。

**桌面版**

- **首次启动向导**：检查 Docker，可在应用内构建沙箱镜像；或在确认风险后启用内置的本地 worker。
- 后端几秒内启动，并可从 GitHub 已签名的发布版本**自动更新**。
- 同一套 React 界面也可在浏览器中运行，支持中文 / English。

## 软件架构

```text
React + Vite WebUI
        │ 浏览器或 Tauri WebView
        ▼
本地 FastAPI 后端
        ├── LLM 适配层（OpenAI 兼容、本机模型、流式输出）
        ├── AST 代码定位、参数编辑、模板与统计
        ├── Docker 沙箱 / 显式启用的本地 worker
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
# 默认使用 Docker。仅可信本机开发时可改用：
# $env:SANDBOX_MODE="process"
# $env:ALLOW_UNSAFE_PROCESS_SANDBOX="1"
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

### Windows 桌面版

从 [Releases](https://github.com/WhitePepperLambSoup/quick-sciplot/releases) 下载 NSIS（`*-setup.exe`）或 MSI 安装包，目标电脑不需要安装 Python。安装包目前没有代码签名，Windows SmartScreen 可能会要求确认（点击“更多信息 → 仍要运行”）。

首次启动时，设置向导提供两种代码执行方式：

- **Docker 沙箱（推荐）**：安装并启动 Docker Desktop，然后在向导中点击“构建沙箱镜像”。
- **本地 worker**：在本机独立进程中运行代码，带静态检查和资源限制，但不是操作系统级沙箱，启用前需要确认风险。

配置和数据保存在 `%APPDATA%\com.quicksciplot.desktop\`（`config\.env` 与 `data\`）。已安装的应用启动时会检查 GitHub Releases 上的新版本。

自行构建安装包：

```bash
cd backend
pip install -r requirements-build.txt
cd ..\frontend
npm run desktop:build
```

NSIS 和 MSI 安装包位于 `frontend/src-tauri/target/release/bundle/`。正式构建还会生成已签名的更新包，构建前需设置 `TAURI_SIGNING_PRIVATE_KEY`（更新私钥文件内容或路径）和 `TAURI_SIGNING_PRIVATE_KEY_PASSWORD`，然后为发布生成 `latest.json`：

```bash
node scripts/make-latest-json.mjs 0.3.0 "src-tauri/target/release/bundle/nsis/Quick SciPlot_0.3.0_x64-setup.exe" https://github.com/WhitePepperLambSoup/quick-sciplot/releases/download/v0.3.0/Quick-SciPlot_0.3.0_x64-setup.exe
```

### Docker 沙箱

桌面版向导可以直接构建镜像；也可以在仓库中手动构建：

```bash
cd backend
docker build -f Dockerfile.sandbox -t quick-sciplot-sandbox:0.3.0 .
```

Docker 模式是默认设置，用于执行不可信的生成代码；Docker 不可用时后端会直接失败，不会静默降级。如果只是可信本机开发且没有 Docker，必须同时设置 `SANDBOX_MODE=process` 和 `ALLOW_UNSAFE_PROCESS_SANDBOX=1`；该模式不是操作系统级沙箱。

### 本机模型

在“设置”中选择“Ollama（本机）”或“LM Studio（本机）”，或填写任意 `http://127.0.0.1:<端口>/v1` 地址，并勾选“允许连接本机模型服务”。不需要 API Key，数据不出本机。“从服务获取列表”会读取服务器上可用的模型。该开关只放行回环地址；其它内网地址仍需设置 `ALLOW_LOCAL_NETWORK_LLM=1`。

### 资源限制

上传文件会流式写入磁盘，并受单文件和单批次大小限制。JSON 使用受控解析和嵌套深度限制；CSV/TSV/Excel/JSON 导入会限制行数、列数、单元格数、工作表数和 Excel ZIP 展开大小。批量导入后续文件失败时会回滚本批次已创建的数据集。预计连接结果超过行数上限时会拒绝连接。绘图执行期间实时限制日志和单个产物文件大小，输出目录总量限制为 128 MiB，历史记录同时按总产物大小和单数据集版本数清理（收藏的版本保留）。运行时 `.env` 更新使用临时文件、`fsync` 和原子替换。

## 评测

运行不调用外部 API 的 mock 评测：

```bash
cd backend
python evaluate.py --mock --sandbox-mode process --allow-unsafe-process-sandbox --output data/evaluation-report.json
```

使用 `model_matrix.example.json` 比较多个模型，并生成 HTML 人工评测报告：

```bash
python evaluate.py --model-config model_matrix.example.json \
  --output reports/models.json \
  --human-report reports/models.html
```

## 安全说明

程序会执行 LLM 生成的 Python 代码。本项目定位是本机单用户工具，不是多租户服务。Docker 模式是默认安全边界：禁用网络、使用只读根文件系统、丢弃 capabilities、以非 root 用户运行并限制资源。本地 worker 只有静态检查、独立进程和超时限制，不是操作系统级沙箱；只有桌面版可以在界面中启用，并且需要明确确认风险。

后端只允许绑定回环地址，并通过会话 token 认证：浏览器使用 HttpOnly cookie，桌面版由 Tauri 壳把 token 交给前端、以请求头发送。为防御 DNS 重绑定，服务只接受 Host 为 `localhost`、`127.0.0.1` 或 `::1` 的请求（可用 `ALLOWED_HOSTS` 调整）。

“AI 视觉体检”会把渲染出的图片发送给所配置的模型服务，“排版体检”不会。桌面版更新包在安装前会用 `tauri.conf.json` 中的公钥校验签名。

不要把当前本地 FastAPI 服务暴露到公网。详见 [SECURITY.md](SECURITY.md)。

## 目录结构

- `backend/`：FastAPI 服务、数据处理、LLM、沙箱、模板、测试和 sidecar 构建脚本。
- `frontend/`：React + Vite WebUI，`src-tauri/` 下的 Tauri 2 桌面壳，以及 `scripts/` 下的发布辅助脚本。
- `docs/`：调研和评测文档。
- `presets/`、`references/`、`skills/`：可选的第三方本地仓库，已加入 Git 忽略。

## 测试

```bash
cd backend
python -m pytest tests -q
```

测试会自动启用仅供测试的 process 模式和 mock 模型，不需要 Docker 或 API Key。前端使用 `npm run build` 检查；桌面壳使用 `cargo fmt --check`、`cargo clippy -- -D warnings` 和 `cargo test --lib` 检查。GitHub Actions 会在每次推送时运行以上检查。

版本变更见 [CHANGELOG.md](CHANGELOG.md)。

## 许可证

MIT License，详见 [LICENSE](LICENSE)。
