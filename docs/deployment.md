# Deployment (Render)

`render.yaml` is a Render Blueprint that creates a Python web service from `apps/api` and a free managed Postgres database.

## Steps

1. Push the repository to GitHub.
2. In the [Render dashboard](https://dashboard.render.com) choose **New +**, then **Blueprint**, and select the repository.
3. Render creates the service and database. It sets `DATABASE_URL` and generates `JWT_SECRET` and `STORE_STAFF_KEY`.
4. Open the service's **Environment** tab to read `STORE_STAFF_KEY`. Staff use it to open the Store SMS inbox.

## Manual setup instead of the Blueprint

- Root directory: `apps/api`
- Build command: `pip install -r requirements.txt`
- Start command: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`
- Health check path: `/api/health`

## Environment variables

| Name | Required | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | In production | Postgres connection string. If unset, a local JSON file is used. |
| `JWT_SECRET` | In production | Signs session cookies. At least 32 characters. The app will not start in production without it, or with a shorter one. |
| `STORE_STAFF_KEY` | In production | Key staff enter to view the store inbox. The inbox is disabled if unset. |
| `ENV` | Off Render | Set to `production` anywhere that is not Render. |
| `PGSSLMODE` | No | Set to `disable` only for a local Postgres without SSL. |
| `PORT` | No | Port to listen on (default 4000). |

`scripts/new-secret.sh` prints a suitable random value.

## Moving from the old layout

The service root moved from `backend` to `apps/api`. If you already deployed the earlier version, update **Root Directory** in the Render service settings (or redeploy from the Blueprint). Nothing changes in the database.

## Before you deploy: checklist

1. **Root Directory** is `apps/api` (the Blueprint sets this; a hand-made service may still point at the repo root).
2. **`JWT_SECRET`** is set and at least 32 characters. Generate one with `python3 -c "import secrets; print(secrets.token_hex(32))"`.
3. **`STORE_STAFF_KEY`** is set to something only staff know. Without it the staff screen is disabled.
4. **`DATABASE_URL`** points at your Postgres. Tables are created on first start; this release adds no columns.
5. **Health checks:** `/api/health` says the process is up. `/api/ready` also confirms the data store answers (use it for monitoring).
6. **Browser security policy:** scripts may only load from your own site. If you later add a third-party script (analytics, a payment widget), allow its host in `CSP` in `apps/api/app/main.py`, or the browser will block it.
7. **Static files are cached for a day.** After a deploy, browsers re-check them, so changes appear without a hard refresh.

