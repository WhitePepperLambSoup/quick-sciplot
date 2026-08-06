# Changelog

This project follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
