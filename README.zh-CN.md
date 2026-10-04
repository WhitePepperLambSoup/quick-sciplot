# Quick SciPlot

[English](README.md) | [简体中文](README.zh-CN.md)

Quick SciPlot 是一个开源的 AI 辅助科研画图桌面/网页应用。
用户可以导入一个或多个数据文件，用自然语言描述想要的图，然后通过直观界面调整图像、代码、变量和科研风格。

[![CI](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml/badge.svg)](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## 主要功能

- 支持 CSV、TSV、TXT（自动识别制表符/逗号/分号）、Excel、JSON，并自动生成数据摘要。
- 一次导入多个文件，勾选后可按行合并，并增加 `source_file` 来源列；已合并的数据集可以继续合并。
- 通过 OpenAI 兼容 API 生成 Matplotlib、Seaborn 或 Plotly 图表，失败时可自动调用模型修复。
- 支持 SciencePlots、Nature、IEEE、LovelyPlots 以及内置兜底风格。
- 完整代码查看、行高亮和每条绘图语句的中英文解释。
- 可直接选择 x/y 数据列，也可以调整颜色、透明度、线宽、标签等参数。
- **统计显著性标注**：Welch t 检验 / Mann-Whitney U、多组 ANOVA / Kruskal-Wallis，Bonferroni 或 FDR 校正后在图上添加括号和星号。
- **多图拼版**：1×2、2×1、2×2、1+2 等期刊常用布局，自动添加 A/B/C 子图标号。
- **论文图复刻**：上传参考图截图或描述版式，按自己的数据生成风格相近的代码。
- **交互式修正**：在画布上拖动参考线和坐标范围，代码同步更新。
- **排版体检与期刊合规检查**：检查 DPI、物理宽度、矢量格式和文件大小（Nature / IEEE / Cell）。
- SQLite 保存生成、编辑、参数调整和恢复历史。
- 支持 PNG（300 DPI）、SVG、PDF、EPS 和 Plotly JSON 导出。
- 默认在 Docker 中执行生成代码；可信本机 process 模式必须显式启用。
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
        ├── Docker / 显式启用的 process 沙箱 / 内置 worker
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

### Windows 安装包

先安装构建依赖：

```bash
cd backend
pip install -r requirements-build.txt
cd ..\frontend
npm run desktop:build
```

NSIS 和 MSI 安装包位于 `frontend/src-tauri/target/release/bundle/`。
正式构建包含 PyInstaller 后端 sidecar，目标电脑不需要单独安装 Python。也可以直接从 [Releases](https://github.com/WhitePepperLambSoup/quick-sciplot/releases) 下载安装包。

桌面版的配置和数据保存在 `%APPDATA%\com.quicksciplot.desktop\` 下（`config\.env`、`data\`）。默认使用 Docker 沙箱，因此需要安装 Docker Desktop 并按下文构建沙箱镜像；如果只在可信的本机环境使用、没有 Docker，可以在 `config\.env` 中写入以下两行后重启应用，改用内置 worker（不是操作系统级沙箱）：

```text
SANDBOX_MODE=process
ALLOW_UNSAFE_PROCESS_SANDBOX=1
```

### Docker 隔离（默认）

启动后端前先构建沙箱镜像：

```bash
cd backend
docker build -f Dockerfile.sandbox -t quick-sciplot-sandbox:0.2.0 .
```

Docker 模式是默认设置，用于执行不可信的生成代码；Docker 不可用时后端会直接失败，不会静默降级。

如果只是可信本机开发且没有 Docker，必须同时设置 `SANDBOX_MODE=process` 和 `ALLOW_UNSAFE_PROCESS_SANDBOX=1`；该模式不是操作系统级沙箱。

### 资源限制

上传文件会流式写入磁盘，并受单文件和单批次大小限制。JSON 使用受控解析和嵌套深度限制；CSV/TSV/Excel/JSON 导入会限制行数、列数、单元格数、工作表数和 Excel ZIP 展开大小。批量导入后续文件失败时会回滚本批次已创建的数据集。绘图执行期间实时限制日志和单个产物文件大小，输出目录总量限制为 128 MiB，历史记录同时按总产物大小和单数据集版本数清理。运行时 `.env` 更新使用临时文件、`fsync` 和原子替换。

## 多文件作图

多个文件导入后仍然是独立数据集。用户勾选文件并点击“合并选中文件”后，程序会按行拼接、保留所有列、对缺失列填空，并增加 `source_file` 列，AI 可以据此按文件来源分组或着色。

程序不会猜测 join key，也不会擅自进行关系型连接。后续可以在用户明确指定连接键和连接类型后增加 join 模式。

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

程序会执行 LLM 生成的 Python 代码。本项目定位是本机单用户工具，不是多租户服务。Docker 模式是默认安全边界：禁用网络、使用只读根文件系统、丢弃 capabilities、以非 root 用户运行并限制资源。process 模式只有静态检查、独立进程和超时限制，不是操作系统级沙箱，只能在可信本机环境显式启用。

后端只允许绑定回环地址，并通过会话 token 认证：浏览器使用 HttpOnly cookie，桌面版由 Tauri 壳把 token 交给前端、以请求头发送。为防御 DNS 重绑定，服务只接受 Host 为 `localhost`、`127.0.0.1` 或 `::1` 的请求（可用 `ALLOWED_HOSTS` 调整）。

不要把当前本地 FastAPI 服务暴露到公网。详见 [SECURITY.md](SECURITY.md)。

## 目录结构

- `backend/`：FastAPI 服务、数据处理、LLM、沙箱、测试和 sidecar 构建脚本。
- `frontend/`：React + Vite WebUI，以及 `src-tauri/` 下的 Tauri 2 桌面壳。
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
