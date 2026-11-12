# Architecture

One deployable service. The FastAPI app in `apps/api` renders the pages, serves the JSON API under `/api/*`, and serves static files from `apps/web/static`, so there is a single origin and no CORS configuration.

## apps/api

```
app/
├── main.py          App setup, error shape, security headers, static files
├── config.py        Environment-driven settings (the only place env vars are read)
├── products.py      The product catalog: the single source of truth for prices
├── auth.py          Customer session (JWT in httpOnly cookie) and staff session
├── ratelimit.py     In-memory per-IP limiter for sensitive endpoints
├── templating.py    Jinja2 setup (autoescape on) and the ₦ / date filters
├── db.py            Chooses the file store or Postgres at startup
├── db_file.py       JSON file store (local development)
├── db_postgres.py   Postgres store using asyncpg
├── templates/       Jinja2 pages and HTML fragments
└── routes/
    ├── ui.py        Server-rendered pages + HTMX fragments (/, /ui/*, /api/store/ui/*)
    ├── auth.py      JSON: signup, login, logout, me, email lookup
    ├── products.py  JSON: GET /api/products
    ├── orders.py    JSON: place an order, list my orders
    └── store.py     JSON: staff login and the store notification feed
tests/               pytest suite (runs against the file store)
```

## apps/web

```
src/        TypeScript (strict) for the parts that must run in the browser
static/
├── styles.css
├── vendor/htmx.min.js      HTMX, vendored so there is no CDN dependency
└── js/main.js              Compiled bundle. Committed, so Render needs no Node.
```

**Who does what.** The server renders everything that is just data: the page, product grid with search and category filter, sign-in and sign-up forms, order history and the staff inbox. HTMX swaps those HTML fragments in. TypeScript handles only what needs the browser: the in-memory cart, the checkout steps, the simulated card/OTP flow, modals and toasts. The TypeScript builds DOM nodes with `textContent`, never `innerHTML`, so there is no path for user text to become markup.

**Building.** `make build-web` compiles `src/` into `static/js/main.js`. Commit the result. CI rebuilds it and fails if the committed file is stale.

## Key design decisions

- **Pages are rendered on the server.** Jinja2 autoescapes every value, so customer text (names, addresses, notes) cannot become markup.
- **Prices are never trusted from the browser.** The API recalculates every order total from `products.py`.
- **The database is swappable.** Routes only call functions in `db.py`. `db_file.py` and `db_postgres.py` implement the same functions, chosen by whether `DATABASE_URL` is set.
- **Two separate sessions.** Customers get an `fm_token` cookie. Staff get an `fm_staff` cookie scoped to `/api/store`. A customer cookie never grants staff access.
- **Secrets come from the environment.** `JWT_SECRET` is required in production and the app refuses to start without it.

## Orders and artwork

- `order_status.py` is the single definition of statuses and allowed moves. See [orders.md](orders.md).
- `illustrations.py` draws each product as inline SVG from a small set of shapes (bottle, can, bag, sack and so on) plus colours. Nothing is downloaded or hosted. Real photos are optional: put `<id>.webp` in `apps/web/static/products/` and it replaces that product's drawing (see the README there).
- `apps/web/src/persist.ts` saves the cart in the browser (ids, size, quantity, note only).
