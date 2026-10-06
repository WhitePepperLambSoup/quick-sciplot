# Quick SciPlot

[English](README.md) | [简体中文](README.zh-CN.md)

An open-source desktop and web application for AI-assisted scientific plotting.
Import one or more data files, describe the figure in natural language, and refine the result through an intuitive UI with editable code, semantic axis controls, version history, and publication-style presets.

[![CI](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml/badge.svg)](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

**Data**

- Import CSV, TSV, TXT (tab, comma or semicolon detected automatically), Excel and JSON by button, Ctrl+O, or drag and drop.
- **Data workbench**: page through the raw rows (double-click a cell to correct it), filter, reshape wide tables to long, select or sort columns, drop missing values, and join two datasets on explicit keys. Every step creates a new dataset; the original is kept.
- **Drag data points to correct data**: in **Drag points** mode, every mark that plots raw values (scatter points, line vertices, one-bar-per-row bars, strip/jitter points) gets a handle bound to its dataset row, on Matplotlib and Plotly figures, linear or log axes, and category or date x axes. Drag one point or a box selection, lock the direction, nudge with the arrow keys, type an exact value or mark it missing, and undo/redo before applying. Applying saves a new dataset version and re-renders the figure; the original is never overwritten, every changed cell (old/new value, time, reason) is listed under **Corrections**, and project bundles include `data_corrections.csv`.
- Combine several files by rows with a `source_file` provenance column.

**Figures**

- Generate Matplotlib, Seaborn or Plotly figures through any OpenAI-compatible API or a **local model** (Ollama, LM Studio). The code streams in as it is written, and you can **cancel** at any time.
- **Templates** that need no model: volcano plot, Kaplan-Meier survival with log-rank test, PCA, clustered heatmap, dose-response (4PL with EC50), correlation triangle, and bar + points with SD/SEM.
- **Statistics**: Welch's t, Mann-Whitney U, paired t, Wilcoxon signed-rank and Tukey HSD with Bonferroni, FDR or no correction, drawn as brackets and stars; **regression fitting** with the equation and R² on the figure.
- **Multi-panel composer** with seven journal layouts, **paper figure mimic**, and **interactive correction** of reference lines and x/y limits for both Matplotlib and Plotly figures.
- **Layout critique** with fast rule checks or an **AI vision review**, and **journal compliance** (Nature, IEEE, Cell) with a one-click fit to single- or double-column width.
- SciencePlots, Nature, IEEE, LovelyPlots and built-in fallback styles.

**Code and history**

- A full code editor with syntax highlighting, undo, Ctrl+Enter to run, and the failing line highlighted when a run errors.
- Every generation, edit and restore is saved as a revision. Name and star revisions (starred ones are never cleaned up) and **compare** any two side by side with a code diff.
- **Batch plotting**: apply the current code to many datasets and download all figures as a zip.
- Export PNG (300 DPI), SVG, PDF, EPS, Plotly JSON, a **standalone Python script**, or a **reproducible project bundle** (data + script + figures).

**Desktop app**

- A **first-run wizard** checks Docker, builds the sandbox image from inside the app, or, after you confirm the risk, enables the bundled local worker.
- The backend starts in a few seconds, and the app **updates itself** from signed GitHub releases.
- The same React UI also runs in a browser. Chinese and English interface.

## Architecture

```text
React + Vite WebUI
        │ browser or Tauri WebView
        ▼
FastAPI local backend
        ├── LLM provider adapter (OpenAI-compatible, local models, streaming)
        ├── AST code locator, parameter editor, templates and statistics
        ├── Docker sandbox / explicitly enabled local worker
        ├── SQLite revision history
        └── Matplotlib / Seaborn / Plotly renderer
```

## Quick Start

### Browser development

```bash
cd backend
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# Copy .env.example to .env and configure an OpenAI-compatible provider.
$env:LLM_MOCK=1
# The production-safe default is Docker. For trusted local development only:
# $env:SANDBOX_MODE="process"
# $env:ALLOW_UNSAFE_PROCESS_SANDBOX="1"
python -m uvicorn app.main:app --reload
```

In another terminal:

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`.

### Desktop development

The Tauri shell starts the local FastAPI process and embeds the same React UI:

```bash
cd frontend
npm run desktop:dev
```

### Windows desktop app

Download the NSIS (`*-setup.exe`) or MSI installer from [Releases](https://github.com/WhitePepperLambSoup/quick-sciplot/releases). Python is not required. The installers are not code-signed yet, so Windows SmartScreen may ask you to confirm (**More info → Run anyway**).

On first launch the setup wizard offers two ways to run generated code:

- **Docker sandbox (recommended)**: install and start Docker Desktop, then click **Build sandbox image** in the wizard.
- **Local worker**: runs code in a separate local process with static checks and limits. It is not an OS-level sandbox, so the wizard asks you to confirm before enabling it.

Configuration and data live under `%APPDATA%\com.quicksciplot.desktop\` (`config\.env` and `data\`). Installed apps check GitHub Releases for updates on start-up.

To build the installers yourself:

```bash
cd backend
pip install -r requirements-build.txt
cd ..\frontend
npm run desktop:build
```

The NSIS and MSI installers are generated under `frontend/src-tauri/target/release/bundle/`. Release builds also produce signed updater artifacts, so set `TAURI_SIGNING_PRIVATE_KEY` (the updater private key file content or path) and `TAURI_SIGNING_PRIVATE_KEY_PASSWORD` first, then create `latest.json` for the release:

```bash
node scripts/make-latest-json.mjs 0.3.0 "src-tauri/target/release/bundle/nsis/Quick SciPlot_0.3.0_x64-setup.exe" https://github.com/WhitePepperLambSoup/quick-sciplot/releases/download/v0.3.0/Quick-SciPlot_0.3.0_x64-setup.exe
```

### Docker sandbox

The desktop wizard can build the image for you. From the repository:

```bash
cd backend
docker build -f Dockerfile.sandbox -t quick-sciplot-sandbox:0.3.0 .
```

Docker mode is the default and is required for untrusted generated code. The backend fails closed if Docker is unavailable. For trusted local development without Docker, set both `SANDBOX_MODE=process` and `ALLOW_UNSAFE_PROCESS_SANDBOX=1`; this mode is not an OS-level sandbox.

### Local models

In **Settings**, choose **Ollama (local)** or **LM Studio (local)**, or enter any `http://127.0.0.1:<port>/v1` endpoint, and enable **Allow a model server on this machine**. No API key is needed and data stays on your computer. **Fetch list** reads the available models from the server. This switch only allows loopback addresses; other private network addresses still require `ALLOW_LOCAL_NETWORK_LLM=1`.

### Resource limits

Uploads are streamed to disk and bounded by per-file and per-batch limits. JSON uses controlled parsing with a nesting limit; CSV/TSV/Excel/JSON imports enforce row, column, cell, sheet, and Excel ZIP expansion limits. Failed multi-file imports roll back datasets already created in that batch. Joins are refused when the estimated result exceeds the row limit. Renderer logs and each output file are limited during execution, the output directory is capped at 128 MiB, and revision history is pruned by both total output bytes and per-dataset revision count (starred revisions are kept). Runtime `.env` updates use a temporary file, `fsync`, and atomic replacement.

## Evaluation

Run the deterministic mock evaluation:

```bash
cd backend
python evaluate.py --mock --sandbox-mode process --allow-unsafe-process-sandbox --output data/evaluation-report.json
```

Compare multiple providers or models with `model_matrix.example.json` and generate an HTML human-review report:

```bash
python evaluate.py --model-config model_matrix.example.json \
  --output reports/models.json \
  --human-report reports/models.html
```

## Security

LLM-generated Python code is executed locally. This project is a single-user local tool, not a multi-tenant service. Docker mode is the default boundary: it disables networking, uses a read-only root filesystem, drops capabilities, runs as a non-root user, and applies resource limits. The local worker only adds static checks, a separate process, and timeouts; it is not an OS-level sandbox. It can be enabled from the UI only in the desktop app and only after explicit confirmation.

The backend only binds to loopback addresses and authenticates with a session token: browsers use an HttpOnly cookie, and the desktop app receives the token from the Tauri shell and sends it as a request header. To defend against DNS rebinding, requests are only accepted when the Host header is `localhost`, `127.0.0.1`, or `::1` (configurable through `ALLOWED_HOSTS`).

The **AI vision review** sends the rendered figure image to the configured model provider; the quick critique does not. Desktop updates are verified against the public key in `tauri.conf.json` before installation.

Do not expose the current local FastAPI service to the public internet. See [SECURITY.md](SECURITY.md).

## Repository Layout

- `backend/`: FastAPI service, data processing, LLM adapter, sandbox, templates, tests, and sidecar build scripts.
- `frontend/`: React + Vite WebUI and Tauri 2 desktop shell in `src-tauri/`; release helper scripts in `scripts/`.
- `docs/`: research and evaluation documentation.
- `presets/`, `references/`, `skills/`: optional local third-party repositories, ignored by Git.

## Tests

```bash
cd backend
python -m pytest tests -q
```

The tests switch to a test-only process sandbox and the mock model automatically, so neither Docker nor an API key is needed. The frontend is checked with `npm run build`, and the desktop shell with `cargo fmt --check`, `cargo clippy -- -D warnings`, and `cargo test --lib`. GitHub Actions runs all of these on every push.

See [CHANGELOG.md](CHANGELOG.md) for release notes.

## License

MIT License. See [LICENSE](LICENSE).
