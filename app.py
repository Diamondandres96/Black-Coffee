import os, json, time
import stripe
from dotenv import load_dotenv
from flask import Flask, render_template, request, session, redirect, url_for, abort

load_dotenv()
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "dev-only-change-me")
stripe.api_key = os.getenv("STRIPE_SECRET_KEY", "")
WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "")
BASE_URL = os.getenv("BASE_URL", "http://localhost:5000").rstrip("/")

CUR = {"usd": dict(sym="$", ship=1490, free=8000), "eur": dict(sym="€", ship=1390, free=7500)}  # flat shipping / free-shipping threshold
COUNTRIES = ["US","CA","GB","ES","DE","FR","IT","NL","PT","IE","AU","MX","CL","AR","PE","PA","CR","BR"]

# Prices are ALWAYS taken from here (server side), never from the browser.
PRODUCTS = {
  "classic":    dict(name="Juan Valdez Classic", desc="Freeze-dried instant · 150 g · 100 cups", cents=2490, eur=2290, img="classic.jpg", img2="classic_back.jpg", kind="single"),
  "vanicanela": dict(name="Juan Valdez Vanicanela", desc="Vanilla & cinnamon freeze-dried · 95 g · 63 cups", cents=1990, eur=1790, img="vanicanela.jpg", img2="vanicanela_alt.jpg", kind="single"),
  "mesa454":    dict(name="Mesa de los Santos Organic", desc="Certified organic whole bean · 454 g (16 oz)", cents=3490, eur=3190, img="mesa454.jpg", kind="single"),
  "mesa340":    dict(name="Mesa de los Santos Tanager", desc="Roasted Colombian coffee · 340 g (12 oz)", cents=2990, eur=2790, img="mesa340.jpg", kind="single"),
  "wush":       dict(name="Mesa de los Santos Wush", desc="Roasted Colombian coffee · Tangara cyanicollis edition", cents=2990, eur=2790, img="wush.jpg", kind="single"),
  "descaf":     dict(name="Juan Valdez Decaf", desc="Freeze-dried decaf instant · 95 g · 63 cups", cents=2190, eur=1990, img="descaf.jpg", kind="single"),
  "clasico250": dict(name="Juan Valdez Classic 250 g", desc="Freeze-dried instant, resealable doypack · 250 g", cents=3690, eur=3390, img="clasico250.jpg", kind="single"),
  "kit5":       dict(name="Juan Valdez Premium Kit", desc="5 ground coffee sachets, 70 g each: Colina, Cumbre, Volcan, Macizo, Colina", cents=2890, eur=2690, img="kit5.jpg", kind="single"),
  "starter":    dict(name="Colombian Starter Combo", desc="Classic 150 g + Vanicanela 95 g. Save about 10%", cents=3990, eur=3690, img="combo_starter.jpg", kind="combo"),
  "duo":        dict(name="Andes Duo Combo", desc="Organic whole bean 454 g + Classic 150 g. Save about 10%", cents=5490, eur=4990, img="combo_duo.jpg", kind="combo"),
  "full":       dict(name="Full Colombia Box", desc="All five coffees. Save about 10% and ships free", cents=12490, eur=11690, img="combo_full.jpg", kind="combo"),
}
# Monthly subscriptions: shipping is included in the monthly price.
PLANS = {
  "starter-monthly":  dict(name="Starter Box, monthly", desc="Classic 150 g + Vanicanela 95 g every month. Shipping included.", cents=5490, eur=4990, img="combo_starter.jpg", tag=None,
                            perks=["Classic + Vanicanela every month", "Shipping included", "Cancel anytime"]),
  "explorer-monthly": dict(name="Explorer Box, monthly", desc="Organic whole bean 454 g + Classic 150 g every month. Shipping included.", cents=6490, eur=5990, img="combo_duo.jpg", tag="Most popular",
                            perks=["Organic whole bean + Classic every month", "Shipping included", "Cancel anytime"]),
}

def cur():
    c = session.get("cur", "usd"); return c if c in CUR else "usd"
def unit(p): return p["eur"] if cur() == "eur" else p["cents"]
def money(c): return f"{CUR[cur()]['sym']}{c/100:,.2f}"
app.jinja_env.filters["money"] = money
app.jinja_env.filters["price"] = unit

def cart_lines():
    lines, sub = [], 0
    for pid, qty in session.get("cart", {}).items():
        p = PRODUCTS.get(pid)
        if p and qty > 0:
            u = unit(p); lines.append(dict(p, id=pid, qty=qty, cents=u, total=qty * u)); sub += qty * u
    return lines, sub

def shipping_for(sub):
    c = CUR[cur()]; return 0 if sub == 0 or sub >= c["free"] else c["ship"]

@app.context_processor
def inject():
    return dict(cart_count=sum(session.get("cart", {}).values()), free_over=CUR[cur()]["free"], ship=CUR[cur()]["ship"], cur=cur())

@app.get("/")
def index():
    return render_template("index.html", singles={k:v for k,v in PRODUCTS.items() if v["kind"]=="single"},
                           combos={k:v for k,v in PRODUCTS.items() if v["kind"]=="combo"})

@app.post("/cart/add/<pid>")
def cart_add(pid):
    if pid not in PRODUCTS: abort(404)
    cart = session.get("cart", {}); cart[pid] = min(cart.get(pid, 0) + 1, 20); session["cart"] = cart
    return redirect(url_for("cart"))

@app.post("/cart/set/<pid>")
def cart_set(pid):
    cart = session.get("cart", {}); qty = request.form.get("qty", type=int, default=0)
    if qty <= 0: cart.pop(pid, None)
    elif pid in PRODUCTS: cart[pid] = min(qty, 20)
    session["cart"] = cart
    return redirect(url_for("cart"))

@app.get("/cart")
def cart():
    lines, sub = cart_lines(); sh = shipping_for(sub)
    return render_template("cart.html", lines=lines, sub=sub, sh=sh, total=sub + sh)

@app.get("/currency/<c>")
def set_currency(c):
    if c in CUR: session["cur"] = c
    return redirect(request.referrer or url_for("index"))

@app.post("/cart/remove/<pid>")
def cart_remove(pid):
    cart = session.get("cart", {}); cart.pop(pid, None); session["cart"] = cart
    return redirect(url_for("cart"))

@app.post("/cart/clear")
def cart_clear():
    session.pop("cart", None); return redirect(url_for("cart"))

@app.get("/story")
def story(): return render_template("story.html")

@app.get("/founder")
def founder(): return render_template("founder.html")

@app.post("/checkout")
def checkout():
    lines, sub = cart_lines()
    if not lines: return redirect(url_for("cart"))
    s = stripe.checkout.Session.create(
        mode="payment",
        line_items=[dict(quantity=l["qty"], price_data=dict(currency=cur(), unit_amount=l["cents"],
                    product_data=dict(name=l["name"], description=l["desc"]))) for l in lines],
        shipping_address_collection=dict(allowed_countries=COUNTRIES),
        phone_number_collection=dict(enabled=True),
        shipping_options=[dict(shipping_rate_data=dict(type="fixed_amount",
            fixed_amount=dict(amount=shipping_for(sub), currency=cur()),
            display_name="International tracked shipping",
            delivery_estimate=dict(minimum=dict(unit="business_day", value=5), maximum=dict(unit="business_day", value=10))))],
        success_url=f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{BASE_URL}/cart")
    return redirect(s.url, code=303)

@app.get("/subscribe")
def subscribe(): return render_template("subscribe.html", plans=PLANS)

@app.post("/subscribe/<plan>")
def subscribe_checkout(plan):
    p = PLANS.get(plan) or abort(404)
    s = stripe.checkout.Session.create(
        mode="subscription",
        line_items=[dict(quantity=1, price_data=dict(currency=cur(), unit_amount=unit(p),
                    recurring=dict(interval="month"), product_data=dict(name=p["name"], description=p["desc"])))],
        shipping_address_collection=dict(allowed_countries=COUNTRIES),
        phone_number_collection=dict(enabled=True),
        success_url=f"{BASE_URL}/success?session_id={{CHECKOUT_SESSION_ID}}",
        cancel_url=f"{BASE_URL}/subscribe")
    return redirect(s.url, code=303)

@app.get("/success")
def success():
    session.pop("cart", None)
    return render_template("success.html")

@app.post("/webhook")
def webhook():
    try:
        ev = stripe.Webhook.construct_event(request.get_data(), request.headers.get("Stripe-Signature", ""), WEBHOOK_SECRET)
    except Exception:
        abort(400)
    if ev["type"] == "checkout.session.completed":
        s = ev["data"]["object"]
        items = stripe.checkout.Session.list_line_items(s["id"], limit=50)
        order = dict(ts=int(time.time()), id=s["id"], mode=s["mode"], email=(s.get("customer_details") or {}).get("email"),
                     phone=(s.get("customer_details") or {}).get("phone"), shipping=s.get("shipping_details") or (s.get("collected_information") or {}).get("shipping_details"),
                     total=s["amount_total"], items=[dict(n=i["description"], q=i["quantity"]) for i in items["data"]])
        with open("orders.jsonl", "a") as f: f.write(json.dumps(order) + "\n")  # replace with DB/email/dropship API
    return "", 200

if __name__ == "__main__":
    app.run(debug=True)
