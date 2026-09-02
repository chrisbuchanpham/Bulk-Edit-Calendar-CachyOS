from __future__ import annotations

import argparse
import socket
import threading
import webbrowser

import uvicorn

from . import __version__
from .app import create_app


def available_port(requested: int) -> int:
    if requested:
        return requested
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Run Bulk Edit Calendar locally")
    result.add_argument(
        "--host",
        default="127.0.0.1",
        choices=["127.0.0.1"],
        help="Loopback host (remote binding is intentionally disabled)",
    )
    result.add_argument("--port", type=int, default=0, help="Local port; defaults to an available port")
    result.add_argument("--no-browser", action="store_true", help="Do not open the web interface automatically")
    result.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return result


def main(argv: list[str] | None = None) -> None:
    args = parser().parse_args(argv)
    if not 0 <= args.port <= 65535:
        parser().error("--port must be between 0 and 65535")
    port = available_port(args.port)
    url = f"http://127.0.0.1:{port}/"
    if not args.no_browser:
        threading.Timer(0.8, lambda: webbrowser.open(url)).start()
    print(f"Bulk Edit Calendar is running at {url}")
    print("Press Ctrl+C to stop. Calendar previews and undo data stay in memory only.")
    uvicorn.run(create_app(), host="127.0.0.1", port=port, log_level="warning", access_log=False)


if __name__ == "__main__":
    main()
