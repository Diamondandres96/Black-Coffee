# Black Coffee (Flask + Stripe)
```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env     # add your Stripe test keys
flask --app app run --debug
```
- Test card: 4242 4242 4242 4242, any future date, any CVC.
- Webhook locally: `stripe listen --forward-to localhost:5000/webhook` and copy the whsec_ into .env.
- Each paid order is appended to `orders.jsonl` (items + shipping address) so you can buy and ship it.
- Production: `gunicorn app:app`, set BASE_URL to your https domain, use live keys, and add the webhook in the Stripe dashboard (event: checkout.session.completed).
- Prices live in `PRODUCTS` / `PLANS` in app.py. Shipping: `SHIPPING_CENTS`, `FREE_SHIPPING_OVER`.

## New
- Prices in USD or EUR (switch in the header). EUR prices are fixed in `PRODUCTS`/`PLANS` (`eur=`), shipping in `CUR`.
- Remove one item / clear cart in /cart. Story page at /story.

## UI
Bootstrap 5.3 (CDN) + custom theme in static/style.css. Logo: static/img/logo.png.
