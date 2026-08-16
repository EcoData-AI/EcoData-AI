"""Backend entry point: `python -m gaia`.

Started by the Tauri desktop shell as a child process, and usable directly for
development. `--print-port` makes the shell's job easy: the chosen port is
written to stdout as a single JSON line before the server starts accepting
connections.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import threading
import time

import uvicorn

from gaia import __version__
from gaia.config import get_settings, reset_settings_cache


def _free_port(host: str, preferred: int) -> int:
    """Use the preferred port if it is free, otherwise let the OS choose one.

    Two GAIA windows, or an unrelated process on 8756, must not stop the app
    from starting.
    """
    for candidate in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((host, candidate))
                return sock.getsockname()[1]
            except OSError:
                continue
    raise RuntimeError("Could not bind a port for the GAIA backend.")


def _watch_parent(parent_pid: int) -> None:
    """Exit when the desktop shell goes away, so no orphan server is left behind."""

    def loop() -> None:
        while True:
            time.sleep(2)
            try:
                os.kill(parent_pid, 0)
            except OSError:
                os._exit(0)

    threading.Thread(target=loop, name="parent-watchdog", daemon=True).start()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="gaia-backend", description="GAIA backend server")
    parser.add_argument("--host", default=None)
    parser.add_argument("--port", type=int, default=None)
    parser.add_argument("--data-dir", default=None, help="Override the GAIA data directory")
    parser.add_argument(
        "--print-port",
        action="store_true",
        help="Print a JSON line with the bound port before serving",
    )
    parser.add_argument("--parent-pid", type=int, default=None)
    parser.add_argument("--version", action="version", version=f"GAIA {__version__}")
    args = parser.parse_args(argv)

    if args.data_dir:
        os.environ["GAIA_DATA_DIR"] = args.data_dir
        reset_settings_cache()

    settings = get_settings()
    host = args.host or settings.host
    port = args.port or _free_port(host, settings.port)

    parent_pid = args.parent_pid or settings.parent_pid
    if parent_pid:
        _watch_parent(parent_pid)

    if args.print_port:
        print(json.dumps({"event": "listening", "host": host, "port": port}), flush=True)

    uvicorn.run(
        "gaia.main:app",
        host=host,
        port=port,
        log_level=settings.log_level.lower(),
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
