# SPDX-License-Identifier: GPL-3.0-or-later
import json
import threading
import time
import urllib.request
import webbrowser

import uvicorn


def already_running():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8765/api/health", timeout=1) as response:
            return json.load(response).get("app") == "karapincho"
    except (OSError, ValueError):
        return False


def open_when_ready():
    for _ in range(120):
        try:
            if already_running():
                webbrowser.open("http://127.0.0.1:8765")
                return
            time.sleep(0.5)
        except OSError:
            time.sleep(0.5)


if __name__ == "__main__":
    if already_running():
        webbrowser.open("http://127.0.0.1:8765")
    else:
        threading.Thread(target=open_when_ready, daemon=True).start()
        uvicorn.run("karapincho.app:app", host="127.0.0.1", port=8765, log_level="info", access_log=False)
