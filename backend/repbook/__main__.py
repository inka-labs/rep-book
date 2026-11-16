import argparse
import os
import sys
import threading
import webbrowser

import uvicorn

from . import __version__, paths
from .app import create_app
from .launch import running
from .security import session_token

PORT = int(os.environ.get("REPBOOK_PORT") or 8775)


def main() -> None:
    parser = argparse.ArgumentParser(prog="repbook", description="Run Rep Book on this computer.")
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--host", default="127.0.0.1",
                        help="127.0.0.1 (default) keeps it on this computer; 0.0.0.0 lets your phone open it "
                             "too, on the same Wi-Fi.")
    parser.add_argument("--no-browser", action="store_true", help="Don't open the browser.")
    parser.add_argument("--version", action="version", version=f"Rep Book {__version__}")
    args = parser.parse_args()

    if sys.stdout is None:  # pythonw (Windows shortcut): no console to write to
        sys.stdout = sys.stderr = open(paths.data_dir() / "repbook.log", "a", buffering=1, encoding="utf-8")

    if running(args.port) == "repbook":
        url = f"http://127.0.0.1:{args.port}/auth?token={session_token(paths.data_dir())}"
        print(f"Rep Book is already running: {url}", flush=True)
        if not args.no_browser:
            webbrowser.open(url)
        return

    app = create_app(lan=args.host != "127.0.0.1")
    url = f"http://127.0.0.1:{args.port}/auth?token={app.state.token}"
    lan = (f"  Phone (same Wi-Fi): http://<this computer's IP>:{args.port}/auth?token={app.state.token}\n"
           if args.host != "127.0.0.1" else "")
    print(f"\n  Rep Book {__version__}\n  Open: {url}\n{lan}  Data: {app.state.data}\n", flush=True)
    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
