import sys
import os
import webbrowser
import threading
import toml

# Playwright browsers installed to shared path so the app works regardless of
# which user account starts it (e.g. run.bat, Claude Code preview, a service).
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", r"C:\ProgramData\ms-playwright")

# make sure imports resolve from project root
sys.path.insert(0, os.path.dirname(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "web"))

from db import init_db
from web.app import app

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "config.toml")


def open_browser(port):
    import time
    time.sleep(1.2)  # wait for Flask to start
    webbrowser.open(f"http://localhost:{port}")


if __name__ == "__main__":
    config = toml.load(CONFIG_PATH)
    port = config["output"]["port"]
    auto_open = config["output"]["auto_open"]

    init_db()

    if auto_open and "--no-open" not in sys.argv:
        threading.Thread(target=open_browser, args=(port,), daemon=True).start()

    print(f"[job_tracker] running at http://localhost:{port}")
    app.run(port=port, debug=False)
