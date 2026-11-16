"""Build the downloads for people who don't use a terminal:

    pixi run release      # packaging/dist/Rep-Book-<version>-{mac,windows}.zip

Each zip holds an installer to double-click, "Read me first.txt" and app/: the app's code and pixi.toml /
pixi.lock (the installer installs exactly the locked packages). The installer downloads pixi itself (the
version this was built with), so the zips stay small. Adapted from Vina Tsama's packaging.
"""

import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "packaging" / "dist"
PRODUCT = "Rep Book"
SKIP_DIRS = {"__pycache__", ".pytest_cache", "tests", ".pixi", ".venv", "venv", ".mypy_cache", ".ruff_cache"}
SKIP_SUFFIXES = {".pyc", ".pyo", ".sqlite3", ".db", ".log"}
SKIP_NAMES = {".DS_Store", "Thumbs.db", ".env"}


def app_version() -> str:
    text = (REPO / "backend" / "pyproject.toml").read_text()
    return re.search(r'^version\s*=\s*"([^"]+)"', text, re.M).group(1)


def pixi_version() -> str:
    if os.environ.get("PIXI_VERSION"):
        return os.environ["PIXI_VERSION"]
    pixi = os.environ.get("PIXI_EXE") or shutil.which("pixi") or str(Path.home() / ".pixi" / "bin" / "pixi")
    out = subprocess.run([pixi, "--version"], capture_output=True, text=True, check=True).stdout
    return out.split()[-1]


def _keep(path: Path) -> bool:
    rel = path.relative_to(REPO)
    return (path.is_file() and not SKIP_DIRS & set(rel.parts) and OUT not in path.parents
            and not any(part.endswith(".egg-info") for part in rel.parts)
            and path.suffix not in SKIP_SUFFIXES and path.name not in SKIP_NAMES)


def app_files() -> list[Path]:
    files = [REPO / "pixi.toml", REPO / "pixi.lock"]
    files += [p for p in (REPO / "README.md",) if p.exists()]
    for top in ("backend", "packaging"):
        files += [p for p in sorted((REPO / top).rglob("*")) if _keep(p)]
    return files


def fill(text: str, versions: dict[str, str]) -> str:
    for key, value in versions.items():
        text = text.replace(f"__{key}__", value)
    return text


def add(zf: zipfile.ZipFile, name: str, data: bytes, executable: bool = False) -> None:
    info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
    info.create_system = 3  # unix: keep the executable bit (macOS Archive Utility honours it)
    info.external_attr = (0o100755 if executable else 0o100644) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    zf.writestr(info, data)


def read_me(system: str, version: str) -> str:
    if system == "mac":
        return f"""{PRODUCT} {version} for Mac
=========================

INSTALL
1. Double-click "Install {PRODUCT}".
   The first time, macOS may say it "can't be opened" or "could not be verified". Then:
     - right-click (or Control-click) "Install {PRODUCT}" and choose Open, then Open again; or
     - open System Settings > Privacy & Security, scroll down and click "Open Anyway".
   This only happens because the installer isn't registered with Apple; it doesn't need your password.
2. A window shows the progress. The first install downloads about 150 MB and takes a few minutes.
3. {PRODUCT} opens in your browser. From now on, open "{PRODUCT}" from Applications
   (or press Cmd+Space and type Rep). After the first install it opens straight away, even without internet.

UPDATE
Download the newer {PRODUCT} and run its installer the same way. Your log is kept.

GOOD TO KNOW
- {PRODUCT} runs only on this computer; it opens in your web browser.
- Your log is in ~/Library/Application Support/RepBook, with a backup made every day.
  The Data tab exports it to a file you can keep anywhere.

UNINSTALL
Double-click "Uninstall {PRODUCT}" (in this folder, or in ~/Library/Application Support/RepBook-app).
Your log is not deleted.
"""
    return f"""{PRODUCT} {version} for Windows
=============================

INSTALL
1. Double-click "Install {PRODUCT}".
   Windows may show "Windows protected your PC": click "More info", then "Run anyway".
   If it asks "Do you want to run this file?", click Run. No administrator rights are needed.
2. A window shows the progress. The first install downloads about 150 MB and takes a few minutes.
3. {PRODUCT} opens in your browser. From now on, open "{PRODUCT}" from the Start menu or the Desktop.
   After the first install it opens straight away, even without internet.

UPDATE
Download the newer {PRODUCT} and run its installer the same way. Your log is kept.

GOOD TO KNOW
- {PRODUCT} runs only on this computer; it opens in your web browser.
- Your log is in %LOCALAPPDATA%\\RepBook, with a backup made every day.
  The Data tab exports it to a file you can keep anywhere.

UNINSTALL
Windows Settings > Apps > Installed apps > {PRODUCT} > Uninstall. Your log is not deleted.
""".replace("\n", "\r\n")


def build() -> list[Path]:
    if not (REPO / "pixi.lock").is_file():
        sys.exit("pixi.lock is missing: run pixi install first (the installers install exactly what it locks).")
    version = app_version()
    versions = {"APP_VERSION": version, "PIXI_VERSION": pixi_version()}
    files = app_files()
    OUT.mkdir(parents=True, exist_ok=True)
    top = f"{PRODUCT} {version}"
    slug = PRODUCT.replace(" ", "-")
    built = []
    for system in ("mac", "windows"):
        target = OUT / f"{slug}-{version}-{system}.zip"
        with zipfile.ZipFile(target, "w") as zf:
            for path in files:
                rel = path.relative_to(REPO).as_posix()
                data = path.read_bytes()
                if rel.startswith(("packaging/mac/", "packaging/windows/")) and path.suffix in (".command", ".ps1", ".cmd"):
                    data = fill(data.decode(), versions).encode()
                add(zf, f"{top}/app/{rel}", data, executable=path.suffix == ".command")
            add(zf, f"{top}/Read me first.txt", read_me(system, version).encode())
            if system == "mac":
                for script, name in (("install", "Install"), ("uninstall", "Uninstall")):
                    text = fill((REPO / "packaging" / "mac" / f"{script}.command").read_text(), versions)
                    add(zf, f"{top}/{name} {PRODUCT}.command", text.encode(), executable=True)
            else:
                add(zf, f"{top}/Install {PRODUCT}.cmd", (REPO / "packaging" / "windows" / "install.cmd").read_bytes())
        built.append(target)
    return built


if __name__ == "__main__":
    for path in build():
        print(f"{path.relative_to(REPO)}  ({path.stat().st_size / 1e6:.1f} MB)")
