# Changelog

## Premium polish

### Shopping
- Sort products by price or name. The chosen sort is kept when you switch category or search.
- A result count beside the product heading.
- Back-to-top button after scrolling.
- Clear cart button in the cart drawer.
- An info strip explaining the delivery fee, payment options and order tracking.
- Copy button for the order reference on the confirmation screen.

### Orders
- Delivery phone numbers are checked and stored in one format. `0801 234 5678`, `+234 801 234 5678` and `2348012345678` are all accepted; anything that is not a Nigerian mobile number is rejected with a clear message.
- Staff see a count of orders per status above the order list.

### Accessibility
- Skip-to-content link and visible keyboard focus outlines.
- Every dialog is announced as a labelled dialog. Focus moves into a dialog when it opens and returns to the button that opened it.
- Animations are reduced for people who ask for that in their system settings.

### Security
- A Content-Security-Policy: scripts may only load from this site, and inline scripts are blocked.
- `Permissions-Policy` and `Cross-Origin-Opener-Policy` headers.
- In production the app refuses to start with a `JWT_SECRET` shorter than 32 characters.
- Rate-limited responses include `Retry-After`, and the limiter frees memory for clients that go quiet.
- Unexpected errors return a safe message (JSON for the API, a branded page for browsers) and never show internal details.

### Performance and operations
- Static files are cached for a day and revalidated; pages and the API are never cached.
- `/api/ready` checks that the data store answers, for monitoring.

### Search and sharing
- Page description, theme colour and share-card tags, an SVG favicon, `robots.txt`, `sitemap.xml`.
- A friendly 404 page for browsers. The API still returns JSON.

### Upgrade notes
- No database changes.
- Set `JWT_SECRET` to at least 32 characters before starting in production. See [docs/deployment.md](docs/deployment.md).
- If you add a third-party script later, allow its host in the Content-Security-Policy in `apps/api/app/main.py`.
