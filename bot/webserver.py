import hashlib
import hmac
import html
import json
import os
import secrets
import time
from urllib.parse import urlencode

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
import uvicorn

try:
    import database as db
except ModuleNotFoundError:
    from bot import database as db

app = FastAPI(title="Velocity Bingo Coin Store")

BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
BOT_USERNAME = os.environ.get("TELEGRAM_BOT_USERNAME", "").strip().lstrip("@")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "https://bingos-9b203c93cae2.herokuapp.com").rstrip("/")

# Default packages; edit these values to change the store's offer/pricing.
COIN_PACKAGES = {
    "starter": {"name": "Starter", "coins": 1000, "stars": 25, "description": "A little boost for your Bingo wallet."},
    "popular": {"name": "Popular", "coins": 3500, "stars": 75, "description": "More coins for your next games."},
    "premium": {"name": "Premium", "coins": 8000, "stars": 150, "description": "A bigger coin bundle."},
    "pro": {"name": "Pro", "coins": 30000, "stars": 500, "description": "For regular players."},
    "mega": {"name": "Mega", "coins": 100000, "stars": 1200, "description": "The largest coin bundle."},
}

PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="theme-color" content="#101020"><title>Velocity Bingo · Coin Store</title>
<style>
:root{color-scheme:dark;--bg:#0b0b14;--card:#171727;--line:#2b2b43;--gold:#ffd166;--muted:#a8a8c2;--purple:#8b5cf6}
*{box-sizing:border-box}body{margin:0;background:radial-gradient(ellipse at top,#242044 0,#0b0b14 52%);color:#f8f7ff;font-family:Inter,system-ui,-apple-system,Segoe UI,sans-serif;min-height:100vh}
.wrap{max-width:1000px;margin:auto;padding:32px 18px 56px}.brand{text-align:center;margin-bottom:28px}.logo{display:inline-flex;align-items:center;justify-content:center;width:70px;height:70px;border-radius:22px;background:linear-gradient(135deg,#ffd166,#f59e0b);font-size:34px;box-shadow:0 12px 45px #f59e0b33}.eyebrow{color:var(--gold);font-weight:800;letter-spacing:.15em;text-transform:uppercase;font-size:12px;margin-top:15px}.brand h1{font-size:clamp(30px,6vw,48px);margin:8px 0}.brand p{color:var(--muted);margin:0}.notice{max-width:650px;margin:0 auto 24px;background:#1a1930;border:1px solid var(--line);border-radius:14px;padding:14px 16px;color:#c8c7df;font-size:14px;line-height:1.5}.login{display:flex;justify-content:center;margin:18px 0 26px;min-height:44px}.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(175px,1fr));gap:14px}.pkg{position:relative;background:linear-gradient(160deg,#1c1c31,#131320);border:1px solid var(--line);border-radius:20px;padding:20px 16px;text-align:center;box-shadow:0 10px 30px #0002}.pkg.popular{border-color:#a78bfa;box-shadow:0 0 0 1px #a78bfa22,0 15px 45px #8b5cf622}.tag{font-size:10px;letter-spacing:.12em;color:#c4b5fd;text-transform:uppercase;font-weight:900;min-height:14px}.pkg h2{font-size:19px;margin:9px 0}.coins{font-size:27px;font-weight:900;letter-spacing:-.04em}.coin-label{color:var(--muted);font-size:12px;margin-top:2px}.price{font-size:16px;font-weight:800;margin:18px 0 12px;color:var(--gold)}button{border:0;border-radius:11px;background:linear-gradient(135deg,#fcd34d,#f59e0b);color:#211500;font-weight:900;padding:12px 14px;width:100%;cursor:pointer;font-size:14px}button:disabled{opacity:.45;cursor:not-allowed}.foot{text-align:center;color:#777790;font-size:12px;margin-top:28px;line-height:1.6}#status{text-align:center;color:#c4b5fd;min-height:22px;margin:10px 0 20px;font-size:14px}.legal{max-width:750px;margin:20px auto 0;color:#777790;font-size:11px;line-height:1.6;text-align:center}
</style>
</head><body><main class="wrap">
<header class="brand"><div class="logo">🪙</div><div class="eyebrow">Velocity Bingo</div><h1>Coin Store</h1><p>Top up your virtual Bingo wallet with Telegram Stars.</p></header>
<div class="notice">Sign in with Telegram to connect a purchase to your Bingo wallet. Payments are processed through Telegram Stars. Coins are virtual game credits and cannot be withdrawn or exchanged for cash.</div>
<div class="login" id="login-area"></div><div id="status" role="status">Sign in with Telegram to purchase coins.</div>
<section class="grid" id="packages">
<div class="pkg"><div class="tag">Starter</div><h2>Starter</h2><div class="coins">1,000</div><div class="coin-label">Bingo coins</div><div class="price">⭐ 25 Stars</div><button disabled>Buy coins</button></div>
<div class="pkg popular"><div class="tag">Popular</div><h2>Popular</h2><div class="coins">3,500</div><div class="coin-label">Bingo coins</div><div class="price">⭐ 75 Stars</div><button disabled>Buy coins</button></div>
<div class="pkg"><div class="tag">Premium</div><h2>Premium</h2><div class="coins">8,000</div><div class="coin-label">Bingo coins</div><div class="price">⭐ 150 Stars</div><button disabled>Buy coins</button></div>
<div class="pkg"><div class="tag">Pro</div><h2>Pro</h2><div class="coins">30,000</div><div class="coin-label">Bingo coins</div><div class="price">⭐ 500 Stars</div><button disabled>Buy coins</button></div>
<div class="pkg"><div class="tag">Mega</div><h2>Mega</h2><div class="coins">100,000</div><div class="coin-label">Bingo coins</div><div class="price">⭐ 1,200 Stars</div><button disabled>Buy coins</button></div>
</section>
<div class="foot">Secure payment confirmation · Automatic wallet credit · Payment records protected against duplicate credit</div>
<div class="legal">Purchases are subject to Telegram Stars terms and applicable local requirements. For payment support, contact the bot owner using the support channel configured for Velocity Bingo.</div>
</main>
<script>
const BOT_USERNAME = __BOT_USERNAME__;
let telegramAuth = null;
const statusEl = document.getElementById('status');
function setStatus(text){statusEl.textContent=text;}
function enableButtons(enabled){document.querySelectorAll('#packages button').forEach(b=>b.disabled=!enabled);}
window.onTelegramAuth = function(user){
  telegramAuth = user;
  const label = user.first_name || user.username || ('User '+user.id);
  setStatus('Signed in as '+label+'. Choose a coin package below.');
  enableButtons(true);
  const area=document.getElementById('login-area');
  area.innerHTML='<div style="border:1px solid #353550;background:#171727;padding:10px 16px;border-radius:12px;color:#e9e7ff">✓ Connected to Telegram · ID '+String(user.id)+'</div>';
};
async function buy(packageId, button){
  if(!telegramAuth){setStatus('Please sign in with Telegram first.');return;}
  button.disabled=true;setStatus('Creating secure Telegram Stars invoice…');
  try{
    const response=await fetch('/api/create-invoice',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({package_id:packageId,auth:telegramAuth})});
    const data=await response.json();
    if(!response.ok)throw new Error(data.detail||'Could not create invoice.');
    setStatus('Invoice ready. Opening Telegram to complete payment…');
    window.location.href=data.invoice_url;
  }catch(e){setStatus(e.message||'Something went wrong. Please try again.');button.disabled=false;}
}
const ids=['starter','popular','premium','pro','mega'];
document.querySelectorAll('#packages .pkg button').forEach((button,i)=>button.addEventListener('click',()=>buy(ids[i],button)));
if(!BOT_USERNAME){setStatus('Store setup is incomplete: configure TELEGRAM_BOT_USERNAME on your hosting dashboard.');}
else{
  const script=document.createElement('script');script.async=true;script.src='https://telegram.org/js/telegram-widget.js?22';
  script.setAttribute('data-telegram-login',BOT_USERNAME);script.setAttribute('data-size','large');script.setAttribute('data-radius','10');script.setAttribute('data-request-access','write');script.setAttribute('data-onauth','onTelegramAuth(user)');
  document.getElementById('login-area').appendChild(script);
}
</script></body></html>'''

@app.get("/")
async def home():
    return {"status": "alive", "service": "Velocity Bingo Bot"}

@app.get("/buy-coins", response_class=HTMLResponse)
async def buy_coins_page():
    return HTMLResponse(PAGE.replace("__BOT_USERNAME__", json.dumps(BOT_USERNAME)))

@app.get("/health")
async def health():
    return {"ok": True, "service": "Velocity Bingo Coin Store"}


def _valid_telegram_login(auth: dict) -> bool:
    if not BOT_TOKEN or not isinstance(auth, dict):
        return False
    received_hash = str(auth.get("hash", ""))
    if not received_hash:
        return False
    data = {str(k): str(v) for k, v in auth.items() if k != "hash" and v is not None}
    data_check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data))
    secret_key = hashlib.sha256(BOT_TOKEN.encode("utf-8")).digest()
    expected = hmac.new(secret_key, data_check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, received_hash):
        return False
    try:
        auth_date = int(data.get("auth_date", "0"))
        user_id = int(data.get("id", "0"))
    except (TypeError, ValueError):
        return False
    now = int(time.time())
    return user_id > 0 and auth_date <= now + 30 and now - auth_date <= 600


@app.post("/api/create-invoice")
async def create_invoice(request: Request):
    if not BOT_TOKEN:
        return JSONResponse({"detail": "Payment service is not configured."}, status_code=503)
    if not BOT_USERNAME:
        return JSONResponse({"detail": "Telegram bot username is not configured."}, status_code=503)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"detail": "Invalid request."}, status_code=400)
    auth = body.get("auth", {}) if isinstance(body, dict) else {}
    package_id = str(body.get("package_id", "")) if isinstance(body, dict) else ""
    package = COIN_PACKAGES.get(package_id)
    if not package:
        return JSONResponse({"detail": "Unknown coin package."}, status_code=400)
    if not _valid_telegram_login(auth):
        return JSONResponse({"detail": "Telegram sign-in expired or could not be verified. Please sign in again."}, status_code=401)
    try:
        user_id = int(auth["id"])
    except (KeyError, TypeError, ValueError):
        return JSONResponse({"detail": "Invalid Telegram account."}, status_code=400)
    player = await db.get_user(user_id)
    if not player:
        return JSONResponse({"detail": "First open the Bingo bot and send /start, then return here to buy coins."}, status_code=400)

    payload = f"vbcoins:{user_id}:{package_id}:{secrets.token_hex(8)}"
    body = {
        "title": f"{package['name']} Bingo Coins",
        "description": f"{package['coins']:,} virtual Bingo coins for your Velocity Bingo wallet.",
        "payload": payload,
        "provider_token": "",
        "currency": "XTR",
        "prices": [{"label": f"{package['coins']:,} Bingo coins", "amount": int(package["stars"])}],
    }
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/createInvoiceLink", json=body)
        result = response.json()
        if not response.is_success or not result.get("ok") or not result.get("result"):
            detail = result.get("description", "Telegram could not create the invoice.")
            return JSONResponse({"detail": detail}, status_code=502)
        return {"invoice_url": result["result"]}
    except Exception:
        return JSONResponse({"detail": "Could not reach Telegram payments. Please try again shortly."}, status_code=502)


def run():
    port = int(os.environ.get("PORT", 10000))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


def start_webserver():
    import threading
    threading.Thread(target=run, daemon=True).start()
