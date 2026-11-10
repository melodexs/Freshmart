# Security notes

## What is protected

- **Passwords** are hashed with bcrypt. Hashes from the earlier Node version remain valid.
- **Sessions** are signed JWTs in httpOnly cookies. Cookies are `Secure` on Render or when `ENV=production`.
- **Secrets**: the app refuses to start in production without `JWT_SECRET`. There is no built-in fallback secret.
- **Prices** are always recalculated on the server.
- **Store inbox** requires a staff key, exchanged for a separate `SameSite=Strict` cookie scoped to `/api/store`. A customer session never grants staff access.
- **Rate limiting** applies to signup, login, email lookup and staff login.
- **Script injection**: pages are rendered by Jinja2 with autoescape on, and the TypeScript only sets `textContent`. Customer text (names, addresses, notes) is never parsed as HTML. Browser tests cover this.
- **Order IDs** are random, so they cannot collide or be guessed from timing.

## Known limits

- Payments and SMS are simulated. Do not collect real card details with this code.
- The rate limiter is in memory and per process. Running several instances needs a shared store such as Redis.
- The staff key is one shared secret, not per-person accounts. Rotate it in the Render Environment tab if someone leaves.
- The JSON file store is for development only. It is not safe for concurrent production use.

## Reporting a problem

Open a private security advisory on the GitHub repository rather than a public issue.
