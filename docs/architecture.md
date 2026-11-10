# Architecture

One deployable service. The FastAPI app in `apps/api` serves the JSON API under `/api/*` and the static storefront from `apps/web`, so there is a single origin and no CORS configuration.

## apps/api

```
app/
├── main.py          App setup, error shape, security headers, serves the frontend
├── config.py        Environment-driven settings (the only place env vars are read)
├── products.py      The product catalog: the single source of truth for prices
├── auth.py          Customer session (JWT in httpOnly cookie) and staff session
├── ratelimit.py     In-memory per-IP limiter for sensitive endpoints
├── db.py            Chooses the file store or Postgres at startup
├── db_file.py       JSON file store (local development)
├── db_postgres.py   Postgres store using asyncpg
└── routes/
    ├── auth.py      signup, login, logout, me, email lookup
    ├── products.py  GET /api/products
    ├── orders.py    place an order, list my orders
    └── store.py     staff login and the store notification feed
tests/               pytest suite (runs against the file store)
```

## apps/web

Plain HTML, CSS and JavaScript with no build step. `app.js` fetches the catalog from the API, keeps the cart in memory, and calls `/api/*` for accounts and orders. All customer-supplied text is escaped before it is rendered.

## Key design decisions

- **Prices are never trusted from the browser.** The API recalculates every order total from `products.py`.
- **The database is swappable.** Routes only call functions in `db.py`. `db_file.py` and `db_postgres.py` implement the same functions, chosen by whether `DATABASE_URL` is set.
- **Two separate sessions.** Customers get an `fm_token` cookie. Staff get an `fm_staff` cookie scoped to `/api/store`. A customer cookie never grants staff access.
- **Secrets come from the environment.** `JWT_SECRET` is required in production and the app refuses to start without it.
