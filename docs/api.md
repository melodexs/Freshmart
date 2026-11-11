# API reference

All endpoints are under `/api`. Request and response bodies are JSON. Errors always look like `{"error": "message"}`.

## Health

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/api/health` | none | Returns `{"ok": true}`. Used by Render. |

## Products

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | `/api/products` | none | The catalog and the delivery fee. |

## Accounts (`/api/auth`)

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/api/auth/signup` | none | Create an account and sign in. 409 if the email exists. Rate limited. |
| POST | `/api/auth/login` | none | Sign in. Sets the `fm_token` httpOnly cookie. Rate limited. |
| POST | `/api/auth/logout` | cookie | Clear the session. |
| GET | `/api/auth/me` | cookie | The signed-in user, or 401. |
| GET | `/api/auth/lookup/{email}` | none | Returns the first name for the quick sign-in prompt. Rate limited. |

## Orders (`/api/orders`)

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/api/orders` | customer cookie | Place an order. The server recalculates all prices from the catalog and ignores any price sent by the browser. |
| GET | `/api/orders/mine` | customer cookie | The signed-in customer's orders, newest first. |

## Store inbox (`/api/store`)

Staff only. These endpoints expose customer addresses and phone numbers.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/api/store/login` | none | Body `{"key": "..."}`. On success sets the `fm_staff` cookie (12 hours, httpOnly, SameSite=Strict). Rate limited to 5 per minute. |
| POST | `/api/store/logout` | none | Clear the staff cookie. |
| GET | `/api/store/session` | none | `{"enabled": bool, "staff": bool}` so the UI knows whether to show the sign-in form. |
| GET | `/api/store/notifications` | staff cookie or `X-Staff-Key` header | The simulated store SMS feed. |

In production the inbox is disabled (403) unless `STORE_STAFF_KEY` is set. In local development with no key set it is open.

Example for scripts:

```bash
curl -H "X-Staff-Key: $STORE_STAFF_KEY" https://your-site.onrender.com/api/store/notifications
```

## Pages and fragments (HTML)

These return HTML for the browser (HTMX), not JSON.

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| POST | `/ui/orders/{id}/cancel` | customer cookie | Cancel your own order if it has not left the store. |
| GET | `/ui/track` | none | The order tracking form. |
| POST | `/ui/track` | none | Form fields `order_id` and `phone`. Both must match. Rate limited to 10 per minute. |
| POST | `/api/store/ui/orders/{id}/status` | staff cookie | Form field `status`. Only allowed moves are accepted. |
