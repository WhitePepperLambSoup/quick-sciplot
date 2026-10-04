# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [0.2.0] - 2026-10-05

### Added

- Statistical significance annotation: Welch's t-test or Mann-Whitney U for pairs, one-way ANOVA or Kruskal-Wallis for three or more groups, Bonferroni or Benjamini-Hochberg correction, Cohen's d, and brackets with stars drawn on the figure.
- Multi-panel figure composer (1×2, 2×1, 2×2, 1+2, 2+1, 1×3, 3×1) with isolated panel scopes and A/B/C panel tags.
- Paper figure mimic: generate code that follows a described or uploaded reference figure, using your own data.
- Interactive correction: drag reference lines and y-axis limits on the canvas and have the plotting code updated.
- Layout critique and journal compliance checks (Nature, IEEE, Cell) for DPI, physical width, vector formats, and file size.
- EPS export, persisted dataset list with delete, revision detail endpoint, and toast notifications.
- `.txt` imports detect tab, comma, or semicolon delimiters.
- Desktop CI job (`cargo fmt`, `clippy`, unit tests) and a broader backend regression suite.

### Changed

- Docker is now the default sandbox. The local process sandbox must be enabled explicitly with `ALLOW_UNSAFE_PROCESS_SANDBOX=1`, and the backend no longer falls back silently when Docker is unavailable.
- The sandbox image is now tagged `quick-sciplot-sandbox:0.2.0`; rebuild it from `backend/Dockerfile.sandbox`.
- Uploads are streamed to disk with per-file and per-batch limits, controlled JSON parsing, Excel ZIP expansion limits, row/column/cell limits, parse and plot concurrency limits, and rollback of partially imported batches.
- Renderer logs and output files are capped while the code is running; revision history is pruned by total size and per-dataset count.
- Session tokens are no longer returned by `/api/config` or accepted in query strings; the API no longer returns internal file paths.
- LLM base URLs are validated against private, loopback, link-local, and metadata addresses (including DNS results), and redirects are disabled.
- Dataset summaries sent to the model omit category values unless `LLM_SEND_DATA_VALUES=1`, and prompts are redacted and length-limited.
- Python dependencies are pinned in lock files; the sidecar build can emit an SBOM with `GENERATE_SBOM=1`.
- The version shown in the UI now comes from `package.json`.

### Fixed

- Packaged Windows desktop builds could not reach the backend: the `http://tauri.localhost` origin was not allowed by CORS, and the cross-site session cookie was dropped by the WebView. The desktop app now gets the session token from the Tauri shell and sends it as a header.
- The desktop shell killed the backend if it was not ready within about 30 seconds, although the one-file sidecar can take longer to unpack on a busy machine or first launch. The window now opens immediately and the UI keeps retrying for up to three minutes.
- In packaged builds, any error in the plotting code opened a modal "Unhandled exception in script" dialog and hung until the sandbox timeout, hiding the traceback from automatic repair. The worker now reports errors on stderr and exits.
- On systems without the configured CJK fonts (Linux, the Docker image), font-lookup warnings flooded the renderer log until it hit the size limit and the plot was killed. These warnings are now silenced.
- Requests whose Host header is not a local name are rejected, closing a DNS-rebinding path to the session cookie (`ALLOWED_HOSTS` to configure).
- A plot finishing while another was still rendering could delete the other plot's output directory.
- Docker containers kept running after a timeout or output-limit violation; large scripts exceeded the Windows command-line limit.
- 300 DPI PNG files were reported as 299 DPI and failed the compliance and critique checks.
- Numeric columns with missing values were summarized as text, losing their statistics.
- Comma-separated `.txt` files were imported as a single column.
- Combining a dataset that was already combined returned a server error.
- Non-JSON responses from the LLM provider caused a server error.
- Paper mimic silently returned demo code when no API key was configured.
- Interactive correction injected code with the wrong indentation, misdetected `ax` (for example in `max`), and accepted `nan`/`inf`.
- A relative `DATA_DIR` was resolved against the working directory instead of `backend/`.
- Validation errors were shown as `[object Object]`; toasts did not expire while typing; a failed copy was reported as copied; pandas 3 text columns were not recognized as categorical.

### Known Limitations

- The desktop app uses the Docker sandbox by default. Without Docker, enable the bundled worker for trusted local use by adding `SANDBOX_MODE=process` and `ALLOW_UNSAFE_PROCESS_SANDBOX=1` to `%APPDATA%\com.quicksciplot.desktop\config\.env`.
- The Docker execution path is not yet covered by automated tests against a running Docker daemon.
- The Docker sandbox image does not include CJK fonts, so Chinese labels render as boxes there; the bundled worker uses the fonts installed on Windows.
- The one-file backend unpacks itself on every launch, so the desktop app can take 10–40 seconds to become ready.
- This is a single-user local tool: there are no per-user accounts or object-level permissions, so do not expose the service to other users or networks.

## [0.1.0] - 2026-08-07

### Added

- Natural-language scientific plotting with OpenAI-compatible LLM APIs.
- CSV, TSV, Excel, and JSON import with automatic summaries.
- Multiple-file import, row-wise combination, and `source_file` provenance.
- Matplotlib, Seaborn, Plotly, SciencePlots, Nature, IEEE, LovelyPlots, and fallback styles.
- Bilingual Chinese/English UI and bilingual x/y variable explanations.
- AST-based code locator, parameter forms, full-code editor, and line highlighting.
- SQLite revision history, restore, PNG/SVG/PDF/Plotly JSON export.
- Process worker, optional Docker sandbox, and PyInstaller backend sidecar.
- Tauri 2 desktop shell with NSIS and MSI installers.
- Mock/real model evaluation and HTML human-review reports.
- MIT license and GitHub Actions CI.

### Known Limitations

- Multiple files are combined by rows; explicit key-based joins are not implemented yet.
- The final desktop build requires Docker for the strongest isolation mode, while the bundled worker also supports local execution without Docker.
- Real-model visual quality still needs a larger benchmark and human-scored dataset.
