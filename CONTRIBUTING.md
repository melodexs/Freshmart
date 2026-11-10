# Contributing

## Setup

```bash
make setup
make dev
```

## Before opening a pull request

```bash
make lint
make test
```

CI runs the same checks on every pull request that touches `apps/`.

## Conventions

- **Backend**: Python 3.11, formatted and linted by Ruff (`make format`). Read environment variables only in `apps/api/app/config.py`.
- **Database changes**: add the function to both `db_file.py` and `db_postgres.py`, and expose it through `db.py`, so routes never depend on a specific store.
- **Prices and totals** are computed on the server only. Never trust a price sent by the browser.
- **Frontend**: escape anything that came from a user with `escHtml()` before putting it into `innerHTML`.
- **Tests**: add or update a test in `apps/api/tests/` for any API behaviour you change.
- **Secrets** never go in the repository. Use environment variables (see `apps/api/.env.example`).

## Pull requests

Keep them focused, describe what changed and how you tested it, and wait for review before merging.
