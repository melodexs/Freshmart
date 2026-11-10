# Freshmart
# Fatoke Market — grocery delivery demo

This is the same site you've been using in chat, now split into a real
**backend** (Node + Express) and **frontend** (plain HTML/CSS/JS), instead of
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
├── backend/
│   ├── server.js          # Express app: wires routes, serves the frontend
│   ├── package.json
│   ├── data/
│   │   └── db.json        # flat-file "database" — users, orders, SMS log
│   └── src/
│       ├── products.js    # the product catalog (single source of truth)
│       ├── db.js           # read/write helpers for data/db.json
│       ├── auth.js         # JWT cookie helpers + auth middleware
│       └── routes/
│           ├── auth.js     # signup, login, logout, session check, lookup
│           ├── products.js # GET the catalog
│           ├── orders.js   # place an order, list "my" orders
│           └── store.js    # the store's simulated SMS inbox
└── frontend/
    ├── index.html
    ├── styles.css
    └── app.js              # talks to the backend via fetch()
```

## Running it

You need [Node.js](https://nodejs.org) 18 or newer installed.

```bash
cd backend
npm install
npm start
```

Then open **http://localhost:4000** — the backend serves the frontend
itself, so there's only one address and no CORS setup needed.

To use a different port:

```bash
PORT=5000 npm start
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
- **`backend/src/products.js`** is the one place the product catalog is
  defined. The frontend fetches it on load rather than hard-coding it, and
  every order's prices are recalculated from this file — never trusted from
  the browser.
- **Sessions** use a JWT stored in an `httpOnly` cookie, so the token can't
  be read or stolen by JavaScript running on the page. `backend/src/auth.js`
  is where that's signed, verified, and attached to each request.
- **The database is swappable without touching any route.** `backend/src/db.js`
  picks one of two implementations based on whether `DATABASE_URL` is set:
  `db.file.js` (a flat JSON file, zero setup, used for local development)
  or `db.postgres.js` (real Postgres, used automatically once a connection
  string is configured — exactly what happens on Render). Every route calls
  the same functions (`getUserByEmail`, `saveUser`, `addOrder`, etc.)
  either way, so switching modes — or moving to a different database later
  — never means editing `routes/*.js`.

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
   - Build command: `npm install`
   - Start command: `npm start`
3. Under that service's **Environment** tab, add:
   - `DATABASE_URL` → the connection string from step 1
   - `JWT_SECRET` → any long random string (Render can generate one for you)
4. Deploy.

**Why not Vercel?** Vercel is built for short-lived serverless functions,
not a long-running server — this project keeps a persistent Express
process and a session cookie flow that fits Render's model much better.
If you specifically want this on Vercel, the backend would need to be
restructured into serverless API routes, which is a bigger rewrite than a
deployment config change.

## Known limitations, going into production

- `JWT_SECRET` falls back to a dev value when no environment variable is
  set — the Render Blueprint generates a real one automatically; if you
  set things up by hand, make sure to set your own.
- The session cookie is not marked `secure`, since local development runs
  over plain HTTP. Render serves everything over HTTPS by default, but if
  you deploy elsewhere without HTTPS, browsers may not send the cookie
  back reliably.
- `GET /api/store/notifications` has no access control in this demo, so
  anyone with the URL can see the store's order feed. Before going live,
  put real store-staff authentication in front of it.
- The local JSON-file database (used only when `DATABASE_URL` isn't set)
  doesn't handle concurrent writes safely — fine for development, but
  that's exactly why Postgres takes over automatically once it's
  configured, as it is on Render.

## Making future changes

Since we're building this together over time: tell me what to add or
change, and I'll edit the relevant file(s) directly — whether that's a new
product, a UI tweak, or a new backend route — and re-zip the project for
you to download again.
