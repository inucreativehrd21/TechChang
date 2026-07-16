---
name: run-local
description: Launch and drive the TechChang Django site locally on Windows — run the dev server, hit routes, and capture page screenshots with headless Chrome. Use when asked to run/start the app, verify a change in the real app, or screenshot a page.
---

# Run & capture the TechChang site locally (Windows)

Verified 2026-07-16. This app is a Django 5.1 site (community app mounted at **root**).

## Environment gotchas (read first)

- **Never call `python` directly** — it's a Windows Store stub that pops an app picker. There is **no `venv/`** in the repo.
- Use the **`py` launcher**. `py` defaults to **3.12 which lacks the project deps** (daphne, etc.). The working interpreter is **Python 3.10** → always use **`py -3.10`** for scripts, or **`py manage.py …`** (manage.py resolves 3.10).
- Korean-containing scripts piped to `py manage.py shell` via **stdin get mangled** (cp949). Save a `.py` file and run `py -3.10 file.py` instead (Python reads source as UTF-8).

## 1. Launch the dev server

Use the **local** settings (`config.settings.local`) so `DEBUG=True` — this auto-allows `127.0.0.1`/`localhost` (base settings have `ALLOWED_HOSTS=[]` → 400) and serves static CSS (needed for accurate rendering).

```bash
DJANGO_SETTINGS_MODULE=config.settings.local py -3.10 manage.py runserver 127.0.0.1:8000 --noreload
```

Run it in the background. Then poll until ready:

```bash
for i in $(seq 1 20); do
  code=$(curl -s -o /dev/null -w '%{http_code}' -A 'Mozilla/5.0' http://127.0.0.1:8000/ 2>/dev/null)
  [ "$code" = "200" ] && { echo READY; break; }; sleep 1
done
```

## 2. URL structure

The community app is at **root**, not `/pybo/`. `/pybo/…` returns a **301 redirect** to the root equivalent (legacy compat), so always request the root path directly:

- `/` — main question/column list
- `/<id>/` — question / column / series-episode detail
- `/series/` — series list · `/series/<slug>/` — series table of contents
- Admin is at a secret path (`ADMIN_URL`), not `/admin/`.

Send a normal `User-Agent` (`-A 'Mozilla/5.0'`); a security middleware logs blank-UA requests as "Suspicious".

## 3. Capture screenshots (headless Chrome)

No Playwright installed; **Chrome and Edge are present**. Use Chrome headless `--screenshot`:

```bash
CHROME="/c/Program Files/Google/Chrome/Application/chrome.exe"
OUT="<scratchpad dir>"
"$CHROME" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
  --user-data-dir="$OUT/chrome-prof" --window-size=1280,1400 \
  --screenshot="$OUT/cap.png" "http://127.0.0.1:8000/series/"
```

- `--window-size=W,H` sets the captured area (content taller than H is cut off — size generously).
- Pages have an **entrance fade-in animation**; a fast capture looks greyed/faded. Add **`--virtual-time-budget=4000`** to let animations settle before the shot.
- **Always open the PNG and look at it.** A blank/faded frame is a failure to observe, not a pass.

## 4. Seed & clean up demo data

For pages that need content (e.g. a series with episodes), seed via a `py -3.10` script using `config.settings.local`, capture, then delete. Columns/episodes are `community.Question` rows authored by the bot user `techchang연구팀`; series live in `community.ColumnSeries`. Always delete seeded rows afterward so the dev DB returns to a clean state.

## 5. Tear down

Stop the background server task when done.
