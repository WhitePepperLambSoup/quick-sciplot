# Quick SciPlot

[English](README.md) | [简体中文](README.zh-CN.md)

An open-source desktop and web application for AI-assisted scientific plotting.
Import one or more data files, describe the figure in natural language, and refine the result through an intuitive UI with editable code, semantic axis controls, version history, and publication-style presets.

[![CI](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml/badge.svg)](https://github.com/WhitePepperLambSoup/quick-sciplot/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Features

- Import CSV, TSV, TXT (tab, comma, or semicolon detected automatically), Excel, and JSON files with automatic data summaries.
- Select multiple files and combine them by rows with a `source_file` provenance column; combined datasets can be combined again.
- Generate Matplotlib, Seaborn, or Plotly figures through any OpenAI-compatible API, with optional automatic repair of failing code.
- Choose SciencePlots, Nature, IEEE, LovelyPlots, and built-in fallback styles.
- Inspect complete plotting code with line highlighting and bilingual data explanations.
- Change x/y data columns, colors, alpha, line width, labels, and other parameters from forms.
- **Significance annotation**: Welch's t-test / Mann-Whitney U, multi-group ANOVA / Kruskal-Wallis, Bonferroni or FDR correction, and brackets with stars drawn on the figure.
- **Multi-panel composer**: 1×2, 2×1, 2×2, and 1+2 journal layouts with automatic A/B/C panel tags.
- **Paper figure mimic**: describe or upload a reference figure and get matching code for your own data.
- **Interactive correction**: drag reference lines and axis limits on the canvas; the code updates to match.
- **Layout critique and journal compliance**: DPI, physical width, vector formats, and file size checks for Nature, IEEE, and Cell.
- Save every generation, edit, parameter change, and restore as an SQLite revision.
- Export PNG (300 DPI), SVG, PDF, EPS, and Plotly JSON.
- Apply bounded streaming imports, controlled JSON/Excel parsing, concurrency limits, and output-history quotas.
- Execute generated code in Docker by default; trusted local process mode requires explicit opt-in.
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
        ├── Docker / explicitly enabled process sandbox / packaged worker
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

### Windows installer

Install build dependencies first:

```bash
cd backend
pip install -r requirements-build.txt
cd ..\frontend
npm run desktop:build
```

The NSIS and MSI installers are generated under `frontend/src-tauri/target/release/bundle/`.
The release build includes a PyInstaller backend sidecar and does not require Python on the target machine. Prebuilt installers are attached to [Releases](https://github.com/WhitePepperLambSoup/quick-sciplot/releases).

The desktop app keeps its configuration and data under `%APPDATA%\com.quicksciplot.desktop\` (`config\.env` and `data\`). It uses the Docker sandbox by default, so install Docker Desktop and build the sandbox image as described below. For trusted local use without Docker, add these two lines to `config\.env` and restart the app to use the bundled worker instead (this is not an OS-level sandbox):

```text
SANDBOX_MODE=process
ALLOW_UNSAFE_PROCESS_SANDBOX=1
```

### Docker sandbox (default)

Build the sandbox image before starting the backend:

```bash
cd backend
docker build -f Dockerfile.sandbox -t quick-sciplot-sandbox:0.2.0 .
```

Docker mode is the default and is required for untrusted generated code. The backend fails closed if Docker is unavailable.

For trusted local development without Docker, explicitly set both `SANDBOX_MODE=process` and `ALLOW_UNSAFE_PROCESS_SANDBOX=1`; this mode is not an OS-level sandbox.

### Resource limits

Uploads are streamed to disk and bounded by per-file and per-batch limits. JSON uses controlled parsing with a nesting limit; CSV/TSV/Excel/JSON imports enforce row, column, cell, sheet, and Excel ZIP expansion limits. Failed multi-file imports roll back datasets already created in that batch. Renderer logs and each output file are limited during execution, the output directory is capped at 128 MiB, and revision history is pruned by both total output bytes and per-dataset revision count. Runtime `.env` updates use a temporary file, `fsync`, and atomic replacement.

## Multiple Files

Multiple imported files remain independent until the user selects them and clicks **Combine selected**. The application concatenates rows, keeps the union of columns, fills unavailable values with missing values, and adds `source_file` so the AI can group or color by origin.

The application deliberately does not guess join keys. Relational joins can be added later when the user specifies an explicit key and join type.

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

LLM-generated Python code is executed locally. This project is a single-user local tool, not a multi-tenant service. Docker mode is the default boundary: it disables networking, uses a read-only root filesystem, drops capabilities, runs as a non-root user, and applies resource limits. Process mode only adds static checks, a separate process, and timeouts; it is not an OS-level sandbox and must be explicitly enabled for trusted local use.

The backend only binds to loopback addresses and authenticates with a session token: browsers use an HttpOnly cookie, and the desktop app receives the token from the Tauri shell and sends it as a request header. To defend against DNS rebinding, requests are only accepted when the Host header is `localhost`, `127.0.0.1`, or `::1` (configurable through `ALLOWED_HOSTS`).

Do not expose the current local FastAPI service to the public internet. See [SECURITY.md](SECURITY.md).

## Repository Layout

- `backend/`: FastAPI service, data processing, LLM adapter, sandbox, tests, and sidecar build scripts.
- `frontend/`: React + Vite WebUI and Tauri 2 desktop shell in `src-tauri/`.
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
