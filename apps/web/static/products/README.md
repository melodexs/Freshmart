# Product images

One image per product, named after the product id (`p1.webp` is Local Rice, and so on). If an image is missing, the shop falls back to the drawn illustration for that product.

- **11 of the 28 images are real photographs** (rice, Semovita, palm oil, groundnut oil, plantain chips, water, Coca-Cola, tomatoes, onions, yam, Pepsi), cleaned up on a studio-style background. Photographers and licences are in `apps/api/app/photo_credits.json` and shown on `/photo-credits`. Each has a 400px twin (`p1-400.webp`) used on phones.
- **The other 17 are still AI-generated studio-style pictures, not photographs of the real products.** They show a typical example of each item. Branded products (Coca-Cola, Pepsi, Indomie, Peak Milk, Climax) are shown with generic, unbranded packaging on purpose, so no one else's logo is faked.
- Replace any of them with your own real photo of the product by saving it here with the same name. Square, about 600 px wide, and under 100 KB works best. WebP is smallest; `.jpg` and `.png` also work.
- Product ids are in `apps/api/app/products.py`.
- The shop loads these from its own address, which the Content-Security-Policy already allows. A test fails if a product has no image or an image is over 120 KB.
