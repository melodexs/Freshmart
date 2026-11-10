# Freshmart
# Fatoke Market — grocery delivery demo

This is the same site you've been using in chat, now split into a real
**backend** (Python + FastAPI) and **frontend** (plain HTML/CSS/JS), instead of
everything living in one browser-only file. The UI is unchanged — same
layout, same colours, same flows — but accounts, orders, and the store's
"SMS" log now live on a server instead of in your browser's local storage.

## What's real and what's simulated

**Real:**
- Accounts (signup/login) with hashed passwords and a proper session cookie
- Orders are saved server-side, in a small JSON file database
- Prices are always recalculated on the server from its own product catalog
  — the browser can never submit a price and have it trusted
- A quick sign-in flow that remembers the last signed-in email on this device

**Still simulated** (same as before — see the in-app notes):
- Card / bank transfer / USSD payment — there's a realistic-looking flow
  (bank connection, OTP, etc.) but no money moves and no real bank is
  contacted. Making this real means integrating a licensed Nigerian payment
  aggregator such as **Paystack** or **Flutterwave**.
- The "SMS sent to store" notification — it's logged and shown as a toast,
  but no real text message goes out. Making this real means an account with
  an SMS gateway such as **Termii** or **Africa's Talking**, called from the
  backend (never from the browser, since that would expose the API key).

## Project layout

```
freshmart-app/
├── backend/                  # Python (FastAPI)
│   ├── requirements.txt
│   ├── requirements-dev.txt
│   ├── data/db.json          # flat-file "database" for local dev
│   ├── app/
│   │   ├── main.py           # FastAPI app: wires routes, serves the frontend
│   │   ├── config.py         # environment-driven settings
│   │   ├── products.py       # the product catalog (single source of truth)
│   │   ├── auth.py           # JWT cookie helpers + auth dependencies
│   │   ├── ratelimit.py      # small in-memory limiter for auth endpoints
│   │   ├── db.py             # picks db_file or db_postgres
│   │   ├── db_file.py        # JSON file store (local development)
│   │   ├── db_postgres.py    # Postgres store (asyncpg)
│   │   └── routes/           # auth, products, orders, store
│   └── tests/                # pytest suite
└── frontend/                 # index.html, styles.css, app.js (unchanged)
```

## Running it

You need Python 3.11 or newer.

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 4000
```

Then open http://localhost:4000. The backend serves the frontend itself, so there is only one address and no CORS setup.

Run the tests:

```bash
pip install -r requirements-dev.txt
python -m pytest
```

### Resetting the demo data

Everything (accounts, orders, the SMS log) lives in
`backend/data/db.json`. To start fresh, stop the server and replace that
file's contents with:

```json
{ "users": {}, "orders": [], "storeSms": [] }
```

## How the pieces fit together

- **`frontend/app.js`** is the same UI logic as before, with every place
  that used to read/write `localStorage` for users, orders, or sessions now
  calling the backend instead (`fetch("/api/...")`). The cart itself still
  lives only in the browser's memory until checkout — that was already true
  in the original version.
- **`backend/app/products.py`** is the one place the product catalog is
  defined. The frontend fetches it on load rather than hard-coding it, and
  every order's prices are recalculated from this file — never trusted from
  the browser.
- **Sessions** use a JWT stored in an `httpOnly` cookie, so the token can't
  be read or stolen by JavaScript running on the page. `backend/app/auth.py`
  is where that's signed, verified, and attached to each request.
- **The database is swappable without touching any route.** `backend/app/db.py`
  picks one of two implementations based on whether `DATABASE_URL` is set:
  `db_file.py` (a flat JSON file, zero setup, used for local development)
  or `db_postgres.py` (real Postgres, used automatically once a connection
  string is configured — exactly what happens on Render). Every route calls
  the same functions (`getUserByEmail`, `saveUser`, `addOrder`, etc.)
  either way, so switching modes — or moving to a different database later
  — never means editing `routes/*.py`.

## Deploying to Render

This project includes `render.yaml`, which tells Render to create two
things together: the backend as a Web Service, and a free managed Postgres
database for it to use. Once deployed this way, `DATABASE_URL` is set
automatically and the app switches from the local JSON file to real
Postgres on its own — nothing in the code needs to change.

**Steps:**
1. Push this project to a GitHub repository (Render deploys from a repo,
   not a zip upload).
2. In the [Render dashboard](https://dashboard.render.com), click
   **New +** → **Blueprint**, and point it at that repository.
3. Render reads `render.yaml` and sets up both the web service and the
   database automatically, including generating a `JWT_SECRET` for you.
4. Once it finishes deploying, open the URL Render gives you — that's the
   live site.

**Prefer to set it up by hand instead of using the Blueprint?**
1. Create a new **PostgreSQL** instance on Render (free tier is fine to start).
   Copy its **Internal Connection String**.
2. Create a new **Web Service**, pointed at this repo, with:
   - Root directory: `backend`
   - Build command: `pip install -r requirements.txt`
   - Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
3. Under that service's **Environment** tab, add:
   - `DATABASE_URL` → the connection string from step 1
   - `JWT_SECRET` → any long random string (Render can generate one for you)
   - `STORE_STAFF_KEY` → a secret for the store's order feed (see below)
4. Deploy.

**Why not Vercel?** Vercel is built for short-lived serverless functions,
not a long-running server — this project keeps a persistent Python
server process and a session cookie flow that fits Render's model much better.
If you specifically want this on Vercel, the backend would need to be
restructured into serverless API routes, which is a bigger rewrite than a
deployment config change.

## Known limitations, going into production

- `JWT_SECRET` is **required in production** (the app refuses to start on
  Render without it). Locally it uses a random per-run secret, so sessions
  reset on restart; set it in `.env` to keep them.
- The session cookie is marked `secure` automatically on Render or when
  `ENV=production`. Plain-HTTP local development still works.
- **Store inbox (staff only).** The footer's "Store SMS inbox" now asks for a
  staff key. Set `STORE_STAFF_KEY` (Render's Blueprint generates one: open the
  service's **Environment** tab to read it). Signing in sets a 12 hour
  `httpOnly`, `SameSite=Strict` cookie, so the key is never stored in
  JavaScript. Scripts can instead send `X-Staff-Key: <key>` to
  `GET /api/store/notifications`. In production the inbox is disabled if no key
  is set; it is open only in local development.
- Customer-supplied text (addresses, notes) is HTML-escaped everywhere the UI
  renders it, so it cannot inject scripts into the customer or staff views.
- Login, signup and email lookup are rate limited per IP (in memory, so
  per process; use a shared store like Redis if you run several instances).
- The local JSON-file database (used only when `DATABASE_URL` isn't set)
  doesn't handle concurrent writes safely — fine for development, but
  that's exactly why Postgres takes over automatically once it's
  configured, as it is on Render.

## Making future changes

Since we're building this together over time: tell me what to add or
change, and I'll edit the relevant file(s) directly — whether that's a new
product, a UI tweak, or a new backend route — and re-zip the project for
you to download again.
