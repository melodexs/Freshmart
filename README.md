# Freshmart

**Fatoke Market**: a grocery delivery demo. A Python (FastAPI) API that also serves a plain HTML/CSS/JS storefront, in one repository.

```
Freshmart/
├── apps/
│   ├── api/        Python FastAPI backend (accounts, orders, staff inbox)
│   └── web/        Storefront: index.html, styles.css, app.js
├── docs/           Architecture, API reference, deployment, security
├── scripts/        Small helpers (secrets, cleanup)
├── .github/        CI workflow and pull request template
├── Makefile        One-command setup, dev, test, lint
└── render.yaml     Render Blueprint (API + Postgres)
```

## Quick start

You need Python 3.11 or newer.

```bash
make setup     # create apps/api/.venv and install dependencies
make dev       # http://localhost:4000 (API and storefront together)
make test      # run the test suite
make lint      # check code style (make format to fix)
```

Run `make help` for the full list. With no `DATABASE_URL` set, data is kept in a local JSON file (`apps/api/data/db.json`). Set `DATABASE_URL` to use Postgres.

## What is real and what is simulated

| Real | Simulated |
| --- | --- |
| Accounts with hashed passwords and httpOnly session cookies | Card, bank transfer and USSD payments (no money moves) |
| Orders saved server-side with prices recalculated from the server catalog | The "SMS to store" message (logged and shown in a staff-only inbox) |
| Staff-only store inbox protected by a staff key | |

To make payments real, integrate Paystack or Flutterwave. To make SMS real, use Termii or Africa's Talking. Both must be called from the API, never from the browser.

## Documentation

- [Architecture](docs/architecture.md): how the pieces fit together
- [API reference](docs/api.md): every endpoint
- [Deployment](docs/deployment.md): Render setup and environment variables
- [Security notes](docs/security.md): what is protected and known limits
- [Contributing](CONTRIBUTING.md): workflow and conventions

## License

See [LICENSE](LICENSE).
