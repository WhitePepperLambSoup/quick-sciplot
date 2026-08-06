# Quick SciPlot

[English](README.md) | [简体中文](README.zh-CN.md)

[![CI](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml/badge.svg)](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml)

An open-source desktop and web application for AI-assisted scientific plotting.
Import one or more data files, describe the figure in natural language, and refine the result through an intuitive UI with editable code, semantic axis controls, version history, and publication-style presets.

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- Import CSV, TSV, Excel, and JSON files with automatic data summaries.
- Select multiple files and combine them by rows with a `source_file` provenance column.
- Generate Matplotlib, Seaborn, or Plotly figures through any OpenAI-compatible API.
- Choose SciencePlots, Nature, IEEE, LovelyPlots, and built-in fallback styles.
- Inspect complete plotting code with line highlighting and bilingual data explanations.
- Change x/y data columns, colors, alpha, line width, labels, and other parameters from forms.
- Save every generation, edit, parameter change, and restore as an SQLite revision.
- Export PNG, SVG, PDF, and Plotly JSON.
- Run without Docker using the bundled worker; Docker is an optional stronger isolation mode.
- Use the same React WebUI in a browser or inside a Tauri 2 desktop GUI.
- Switch the interface between Chinese and English.

## Architecture

```text
React + Vite WebUI
        │ browser or Tauri WebView
        ▼
FastAPI local backend
        ├── LLM provider adapter
        ├── AST code locator and parameter editor
        ├── process / Docker / packaged worker sandbox
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

### Windows installer

Install build dependencies first:

```bash
cd backend
pip install -r requirements-build.txt
cd ..\frontend
npm run desktop:build
```

The NSIS and MSI installers are generated under `frontend/src-tauri/target/release/bundle/`.
The release build includes a PyInstaller backend sidecar and does not require Python on the target machine.

### Optional Docker isolation

Docker is not required for the bundled worker mode. To enable stronger container isolation:

```bash
cd backend
docker build -f Dockerfile.sandbox -t quick-sciplot-sandbox:latest .
```

Select Docker in the application settings or set `SANDBOX_MODE=docker` in `.env`.

## Multiple Files

Multiple imported files remain independent until the user selects them and clicks **Combine selected**. The application concatenates rows, keeps the union of columns, fills unavailable values with missing values, and adds `source_file` so the AI can group or color by origin.

The application deliberately does not guess join keys. Relational joins can be added later when the user specifies an explicit key and join type.

## Evaluation

Run the deterministic mock evaluation:

```bash
cd backend
python evaluate.py --mock --output data/evaluation-report.json
```

Compare multiple providers or models with `model_matrix.example.json` and generate an HTML human-review report:

```bash
python evaluate.py --model-config model_matrix.example.json \
  --output reports/models.json \
  --human-report reports/models.html
```

## Security

LLM-generated Python code is executed locally. Process mode provides static import checks, forbidden-call checks, a separate process, and timeouts. Docker mode additionally disables networking, uses a read-only root filesystem, drops capabilities, runs as a non-root user, and applies resource limits.

Do not expose the current local FastAPI service to the public internet. See [SECURITY.md](SECURITY.md).

## Repository Layout

- `backend/`: FastAPI service, data processing, LLM adapter, sandbox, tests, and sidecar build scripts.
- `frontend/`: React + Vite WebUI and Tauri 2 desktop shell in `src-tauri/`.
- `docs/`: research plan and evaluation documentation.
- `presets/`, `references/`, `skills/`: optional local third-party repositories, ignored by Git.

## Tests

```bash
cd backend
python -m pytest tests -q
```

The frontend is checked with `npm run build`.

## License

MIT License. See [LICENSE](LICENSE).
