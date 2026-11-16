"""Open Rep Book without a terminal: start it in the background if it isn't running, then open it
in the browser. This is what the Rep Book app (macOS) and the Start-menu / Desktop shortcut
(Windows) run; see packaging/.

    python -m repbook.launch                 # open Rep Book (starting it if needed)
    python -m repbook.launch --no-browser    # just make sure it's running

Installed by the installers, the app lives in one folder: app/ (this code and its pixi environment)
next to bin/ (the pixi that installed it). The data (database, backups) is elsewhere: see
repbook.paths.data_dir().
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

APP_NAME = "Rep Book"
HEALTH_APP = "rep-book"  # what GET /api/health answers with as "app"
PORT = int(os.environ.get("REPBOOK_PORT") or 8775)
APP_DIR = Path(__file__).resolve().parents[2]  # backend/repbook/launch.py -> the repo / app folder


def log_path() -> Path:
    from .paths import data_dir  # not at import time: keeps `--help` working without the data folder
    folder = Path(data_dir())
    folder.mkdir(parents=True, exist_ok=True)
    return folder / "repbook.log"


def prepare_path() -> None:
    """Put this environment's own folders on PATH, for a server not started from a pixi shell (the
    app, a shortcut, start at login): on Windows some packages find their DLLs only that way."""
    prefix = Path(sys.prefix)
    own = [prefix, prefix / "Library" / "bin", prefix / "Scripts"] if os.name == "nt" else [prefix / "bin"]
    current = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p]
    add = [str(p) for p in own if p.is_dir() and str(p) not in current]
    if add:
        os.environ["PATH"] = os.pathsep.join(add + current)


def running(port: int = PORT) -> str | None:
    """"repbook" when Rep Book answers on the port, "other" when another program does, None
    when nothing does."""
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as resp:
            raw = resp.read()
    except urllib.error.HTTPError:
        return "other"  # something answers HTTP, but not with our health check
    except (OSError, ValueError):
        return None
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return "other"
    return "repbook" if isinstance(body, dict) and body.get("app") == HEALTH_APP else "other"


def _python(background: bool) -> str:
    """This environment's Python; pythonw on Windows for a process without a console window."""
    if background and os.name == "nt":
        pythonw = Path(sys.executable).with_name("pythonw.exe")
        if pythonw.is_file():
            return str(pythonw)
    return sys.executable


def server_command(port: int = PORT) -> list[str]:
    # -X utf8: read and write text as UTF-8 on Windows too, as on macOS and Linux
    return [_python(background=True), "-X", "utf8", "-m", "repbook", "--no-browser", "--port", str(port)]


def start(port: int = PORT, wait: float = 90) -> None:
    """Start the server as a background process (its output goes to repbook.log) and wait until it answers."""
    log = log_path()
    out = open(log, "ab")
    kwargs: dict = {"cwd": APP_DIR, "stdin": subprocess.DEVNULL, "stdout": out, "stderr": subprocess.STDOUT}
    if os.name == "nt":
        kwargs["creationflags"] = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        kwargs["start_new_session"] = True  # keeps running after the launcher (and the .app) exits
    proc = subprocess.Popen(server_command(port), **kwargs)
    out.close()
    deadline = time.monotonic() + wait
    while time.monotonic() < deadline:
        state = running(port)
        if state == "repbook":
            return
        if proc.poll() is not None and running(port) != "repbook":
            raise RuntimeError(f"{APP_NAME} stopped while starting.\n\n" + _tail(log))
        time.sleep(0.3)
    raise RuntimeError(f"{APP_NAME} didn't start within {int(wait)} seconds.\n\n" + _tail(log))


def _tail(log: Path, lines: int = 12) -> str:
    try:
        return "\n".join(log.read_text(errors="replace").splitlines()[-lines:])
    except OSError:
        return ""


def alert(message: str) -> None:
    """Show a message without a terminal: a dialog on macOS and Windows, else printed."""
    print(message, file=sys.stderr)
    try:
        if sys.platform == "darwin":
            script = f'on run argv\n display alert "{APP_NAME}" message (item 1 of argv) as critical\nend run'
            subprocess.run(["osascript", "-e", script, message], capture_output=True, timeout=600)
        elif os.name == "nt":
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, message, APP_NAME, 0x10)  # type: ignore[attr-defined]
        elif shutil.which("zenity"):  # Ubuntu and most GNOME desktops
            subprocess.run(["zenity", "--error", "--title", APP_NAME, "--text", message], capture_output=True, timeout=600)
        elif shutil.which("notify-send"):
            subprocess.run(["notify-send", "-u", "critical", APP_NAME, message], capture_output=True, timeout=10)
    except Exception:
        pass


def open_app(port: int = PORT, browser: bool = True) -> str:
    state = running(port)
    if state == "other":
        raise RuntimeError(f"Another program is using port {port}, which {APP_NAME} needs. "
                           f"Close it and open {APP_NAME} again.")
    if state is None:
        start(port)
    # The sign-in link: the server made the token in the data folder when it started.
    from .paths import data_dir
    from .security import session_token
    url = f"http://127.0.0.1:{port}/auth?token={session_token(data_dir())}"
    if browser:
        webbrowser.open(url)
    return url


def main() -> None:
    parser = argparse.ArgumentParser(prog="repbook-launch", description=f"Open {APP_NAME}, starting it if needed.")
    parser.add_argument("--no-browser", action="store_true", help="Only make sure it's running.")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()
    prepare_path()
    try:
        url = open_app(args.port, browser=not args.no_browser)
        if sys.stdout is not None:
            print(f"{APP_NAME} is running: {url}")
    except Exception as e:  # no terminal to show a traceback in: say it in a dialog
        alert(str(e) or repr(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
