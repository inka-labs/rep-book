# Rep Book

A workout log for a 4-day split (Push, Pull, Legs, Upper): sets and reps per exercise, body weight, a week view,
a year calendar, targets and progress charts. It runs on one computer and opens in the browser.

## How it's built

One Python process serves everything at <http://127.0.0.1:8775>, in the same way as Vina Tsama and Ecoscope Studio:

- **API**: [FastAPI](https://fastapi.tiangolo.com) + SQLAlchemy under `/api/v1/` ([backend/repbook/](backend/repbook/)).
  The interactive API docs are at `/api/docs`.
- **UI**: a single page, [backend/repbook/static/index.html](backend/repbook/static/index.html), in plain
  HTML/CSS/JS with no build step.
- **Data**: a SQLite database (`db.sqlite3`), daily backups (`backups/`, the last 30 are kept) and the sign-in token,
  all kept in the data folder:

  | | |
  |---|---|
  | Mac | `~/Library/Application Support/RepBook/` |
  | Windows | `%LOCALAPPDATA%\RepBook\` |
  | Linux | `~/.local/share/repbook/` |

  Set `REPBOOK_DATA_DIR` to use another folder.

The Data tab shows where the folder is. From that tab you can make a backup or restore one, export everything
(.json, to import elsewhere) or the sets and days (.csv, for spreadsheets), and import a .json export.

## Install

**Without a terminal (Mac and Windows):** download `Rep-Book-<version>-mac.zip` or `-windows.zip`, unzip it and
double-click **Install Rep Book**. After that, open **Rep Book** from Applications or the Start menu.
To build those zips, run `pixi run release`; the zips are written to `packaging/dist/`.

**From the source:** install [pixi](https://pixi.sh), then run:

    pixi run start        # serves it and opens the browser

There's no password. Rep Book prints a sign-in link when it starts (`http://127.0.0.1:8775/auth?token=...`), and
the app's shortcut opens that link for you. Opening the link sets a cookie in that browser, and every API call needs
the cookie, so other websites can't read or change the log. To sign every browser out, delete `session_token` in
the data folder and restart.

Options: `pixi run start -- --port 8776` and `--no-browser`. The `--host 0.0.0.0` option lets your phone open it
on the same Wi-Fi, at `http://<this computer's IP>:8775/auth?token=...`.

## Develop

    pixi run serve        # on :8775 without opening the browser (the page reloads from disk on each request)
    pixi run test         # API tests

Try changes against a scratch data folder and port, not your real log:

    REPBOOK_DATA_DIR=/tmp/rb REPBOOK_PORT=8799 pixi run serve
