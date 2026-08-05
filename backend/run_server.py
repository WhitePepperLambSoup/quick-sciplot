"""PyInstaller sidecar entry point for Quick SciPlot."""

import argparse
from pathlib import Path

import uvicorn


def run_worker(script_file: str) -> None:
    script_path = Path(script_file)
    code = script_path.read_text(encoding="utf-8")
    namespace = {"__name__": "__main__", "__file__": str(script_path)}
    exec(compile(code, str(script_path), "exec"), namespace, namespace)


def run_server(host: str, port: int) -> None:
    from app.main import app

    uvicorn.run(app, host=host, port=port, log_level="warning")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--script-file")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if args.worker:
        if not args.script_file:
            parser.error("--worker requires --script-file")
        run_worker(args.script_file)
    else:
        run_server(args.host, args.port)


if __name__ == "__main__":
    main()
