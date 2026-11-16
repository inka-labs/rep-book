"""Where Rep Book keeps its data: the database, backups and the sign-in token."""

import os
import sys
from pathlib import Path

# The page itself (one HTML file), served by the same process as the API.
STATIC = Path(__file__).resolve().parent / "static"


def data_dir() -> Path:
    """The data folder, created if needed. REPBOOK_DATA_DIR points somewhere else (tests, a second copy)."""
    if override := os.environ.get("REPBOOK_DATA_DIR"):
        path = Path(override).expanduser()
    elif sys.platform == "win32":
        path = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "RepBook"
    elif sys.platform == "darwin":
        path = Path.home() / "Library" / "Application Support" / "RepBook"
    else:
        path = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "repbook"
    path.mkdir(parents=True, exist_ok=True)
    return path
