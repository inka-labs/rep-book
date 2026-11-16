"""Who may use the API: whoever opened the sign-in link (as in Ecoscope Studio and Vina Tsama).

The launcher opens /auth?token=... (it's also printed at startup). That sets a cookie, and every /api call must
carry it, so other websites open in the same browser can't read or change the log. The host check in app.py
blocks DNS rebinding. There are no passwords.
"""

import secrets
from pathlib import Path

COOKIE = "repbook_session"


def session_token(data: Path) -> str:
    """Stable across restarts so an open tab keeps working; delete the file to make a new link."""
    path = data / "session_token"
    if not path.exists():
        path.write_text(secrets.token_urlsafe(32))
        path.chmod(0o600)
    return path.read_text().strip()
