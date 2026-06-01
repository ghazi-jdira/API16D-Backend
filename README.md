# API 16D Accumulator Sizing — Backend

FastAPI service that holds **all confidential data and formulas** for the API 16D
accumulator-sizing calculator:

- the NIST nitrogen property grid (`data/nist.json`),
- the Cameron EB702D shear master-lookup constants (`data/masterLookup.json`),
- the BOP equipment specs and dropdown lists (`data/bopSpecs.json`, `data/lists.json`),
- and the Method B / Method C sizing engine (`engine.py`, `nist.py`).

The browser never receives any of this — only computed results. Access is gated
by a **username/password login**, verified on the server against stored password
hashes.

> 🔒 **Keep this repository PRIVATE.** Its `data/` files are the confidential
> inputs. Do **not** add it to GitHub Pages or merge it into the frontend repo.

## Endpoints

| Method | Path           | Auth | Returns                                            |
|--------|----------------|------|----------------------------------------------------|
| GET    | `/health`      | no   | `{"status":"ok"}`                                  |
| POST   | `/api/login`   | no   | `{token, username, expiresIn}` for valid credentials |
| GET    | `/api/meta`    | yes  | BOP specs + dropdown lists (no secret constants)   |
| POST   | `/api/compute` | yes  | Full sizing results (no NIST grid, no C1/C2/C3/σ)  |

Authenticated calls require `Authorization: Bearer <login-token>` (the token
returned by `/api/login`).

## Configuration (environment variables)

See `.env.example`. Set these in the Render dashboard (or a local `.env`):

| Variable            | Example                                       | Purpose                                            |
|---------------------|-----------------------------------------------|----------------------------------------------------|
| `SECRET_KEY`        | a long random hex string                      | Signs/verifies login tokens. **Set a stable value in prod.** |
| `ALLOWED_ORIGINS`   | `https://you.github.io,http://localhost:8123` | Comma-separated CORS origins (your Pages URL)      |
| `TOKEN_TTL_SECONDS` | `43200`                                       | Optional — how long a login stays valid (default 12h) |

Generate a `SECRET_KEY` with:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

(On Render, the included `render.yaml` auto-generates a stable `SECRET_KEY` for you.)

## Managing logins (usernames & passwords)

Users live in `users.json` (PBKDF2-hashed passwords, never plaintext). Manage them
with `manage_users.py`:

```bash
python manage_users.py add <username> <password>   # add or update a user
python manage_users.py remove <username>            # delete a user
python manage_users.py list                         # list usernames
```

A starter login is included: **`admin` / `sigma2026`** — change it before going
live (`python manage_users.py add admin <new-password>`), then commit the updated
`users.json` and redeploy. To hand a client access, run `add` with their username
and a password and share those with them.

## Deploy to Render

1. Push this folder to a **private** GitHub repo:

   ```bash
   git init
   git add .
   git commit -m "API 16D accumulator sizing — backend"
   git branch -M main
   git remote add origin https://github.com/<you>/<backend-repo>.git
   git push -u origin main
   ```

2. In Render: **New → Web Service**, connect the private repo. The included
   `render.yaml` sets it up (Python, free plan):
   - Build: `pip install -r requirements.txt`
   - Start: `uvicorn app:app --host 0.0.0.0 --port $PORT`

3. Under the service's **Environment** tab, set `ALLOWED_ORIGINS` to your Pages
   URL. `SECRET_KEY` is generated automatically by `render.yaml`.

4. Note the service URL (e.g. `https://api16d-backend.onrender.com`) and put it
   in the frontend's `js/config.js` (`apiBase`).

> Render's free tier sleeps after inactivity, so the first request after idle can
> take ~30–60 s to wake. The frontend shows "Loading…" until `/api/meta` responds.

## Run locally

```bash
pip install -r requirements.txt

# Windows PowerShell:
$env:SECRET_KEY="dev-secret"; $env:ALLOWED_ORIGINS="http://localhost:8123"; uvicorn app:app --port 8000

# macOS / Linux:
SECRET_KEY=dev-secret ALLOWED_ORIGINS=http://localhost:8123 uvicorn app:app --port 8000
```

Quick check: `curl http://localhost:8000/health` → `{"status":"ok"}`.

## Adding / editing BOP equipment

Edit **`data/bopSpecs.json`**. Each entry is one object:

```json
{
  "name": "Pipe Ram BOP 11\" 5k",
  "rwp": 5000,
  "open": 3.4,
  "close": 3.5,
  "ratio": 7.3,
  "pclose": 684.93,
  "note": "Cameron U Pipe Ram 11\" 5K"
}
```

- `name` — label shown in the dropdowns (must be unique)
- `rwp` — rated working pressure (psig)
- `open` / `close` — opening / closing volumes (gal)
- `ratio` — operating ratio (`null` if not applicable)
- `pclose` — pressure to close (psig)
- `note` — free-text description

Changes take effect on the next redeploy (the file is read at startup).

## Project layout

```
app.py             FastAPI app: /health, /api/login, /api/meta, /api/compute
userauth.py        Password hashing (PBKDF2) + signed-token helpers (stdlib only)
manage_users.py    CLI to add/remove/list logins (writes users.json)
users.json         Usernames + PBKDF2 password hashes (no plaintext)
engine.py          Method B / C sizing engine (port of the validated workbook)
nist.py            NIST density/entropy interpolation engine
data/nist.json         NIST nitrogen density/entropy grid (confidential)
data/masterLookup.json Cameron EB702D shear constants (confidential)
data/bopSpecs.json     Editable BOP equipment catalogue
data/lists.json        Dropdown lists (BOP / RAM types, pipe grades, max-op map)
requirements.txt   Python dependencies
render.yaml        Render service definition
.env.example       Environment-variable template
```

## Accuracy

With the default inputs the engine reproduces the reference workbook: minimum
volume **213.02 gal**, optimum precharge **1624 psig**, governing branch
**ρ_XBC (intersect)**, shear pressures **1958 / 2331 psi**, **22 / 16** bottles.

## License

[MIT](../API16D-Accumulator-Sizing/LICENSE)
