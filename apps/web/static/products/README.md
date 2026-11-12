# Product photos (optional)

Put a photo here named after the product id and it replaces the drawn illustration on the shop page. No code change needed.

- File name: `<id>.webp` (best), `.jpg`, `.jpeg` or `.png`. For example `p1.webp` for Local Rice.
- Product ids are in `apps/api/app/products.py` (`p1` to `p28`).
- Square or slightly tall photos around 600 px wide look best, under 100 KB each.
- Products without a photo keep their drawn illustration, so you can add them one at a time.
- Only use photos you own or that are licensed for this. Keep the credit for any CC BY photo.

The shop loads these from its own address, which the Content-Security-Policy already allows.
