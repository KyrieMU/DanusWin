"""DanusWin launcher: python -m app  (opens http://127.0.0.1:8765)."""
from __future__ import annotations

import threading
import webbrowser

import uvicorn


def _open_browser() -> None:
    webbrowser.open("http://127.0.0.1:8765")


if __name__ == "__main__":
    threading.Timer(1.2, _open_browser).start()
    uvicorn.run("app.server:app", host="127.0.0.1", port=8765, log_level="info")
