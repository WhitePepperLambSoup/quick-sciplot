"""PyInstaller sidecar entry point for Quick SciPlot."""

import argparse
import os
import sys
import traceback
from pathlib import Path

import uvicorn


def _ensure_std_streams() -> None:
    """Give a windowed (--noconsole) build usable stdout/stderr.

    The sandbox redirects the worker's output to files; make sure Python
    writes to those handles instead of dropping output when the bootloader
    starts without console streams.
    """
    for name, fd in (("stdout", 1), ("stderr", 2)):
        if getattr(sys, name) is not None:
            continue
        try:
            stream = open(fd, "w", encoding="utf-8", errors="replace", buffering=1, closefd=False)
        except OSError:
            stream = open(os.devnull, "w", encoding="utf-8")
        setattr(sys, name, stream)


def run_worker(script_file: str) -> int:
    """Run one plotting script and return its exit code.

    Failures are reported on stderr instead of escaping: the sidecar is built
    with --noconsole, and an unhandled exception there makes the PyInstaller
    bootloader open a modal "Unhandled exception in script" dialog that waits
    for a click.  The sandbox would then only see a timeout, and the traceback
    that automatic repair relies on would be lost.
    """
    _ensure_std_streams()
    script_path = Path(script_file)
    try:
        code = script_path.read_text(encoding="utf-8-sig")
        namespace = {"__name__": "__main__", "__file__": str(script_path)}
        exec(compile(code, str(script_path), "exec"), namespace, namespace)
    except SystemExit as exc:
        if exc.code is None:
            return 0
        if isinstance(exc.code, int):
            return exc.code
        print(exc.code, file=sys.stderr)
        return 1
    except BaseException:  # noqa: BLE001 - every failure must reach stderr
        traceback.print_exc()
        return 1
    return 0


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
        exit_code = run_worker(args.script_file)
        for stream in (sys.stdout, sys.stderr):
            try:
                stream.flush()
            except (AttributeError, OSError, ValueError):
                pass
        sys.exit(exit_code)
    else:
        run_server(args.host, args.port)


if __name__ == "__main__":
    main()
