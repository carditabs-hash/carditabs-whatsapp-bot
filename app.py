import os
import re
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ---- CONFIG (set these as Environment Variables on Render) ----
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "carditabs_verify_123")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "").strip().strip('"').strip("'")
if WHATSAPP_TOKEN.lower().startswith("bearer "):
    WHATSAPP_TOKEN = WHATSAPP_TOKEN[7:].strip()
print(f"TOKEN CHECK: length={len(WHATSAPP_TOKEN)} start={WHATSAPP_TOKEN[:4]} end={WHATSAPP_TOKEN[-4:]}", flush=True)
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "").strip()
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
TELEGRAM_SECRET = os.environ.get("TELEGRAM_SECRET", "").strip()
WC_CONSUMER_KEY = os.environ.get("WC_CONSUMER_KEY", "")
WC_CONSUMER_SECRET = os.environ.get("WC_CONSUMER_SECRET", "")
WC_SITE_URL = os.environ.get("WC_SITE_URL", "https://carditabs.com")

# ---- FAQ RESPONSES ----
FAQS = {
    "shipping": "Hum pan-India shipping karte hain! Order aam taur par 24 ghante mein ship ho jaata hai. Details: carditabs.com/shipping-policy/",
    "return": "Aap delivery ke 8 din ke andar return/exchange kar sakte hain agar product mein koi issue ho. Details: carditabs.com/refund-return-policy/",
    "payment": "Hum COD, Credit/Debit Card, aur UPI accept karte hain.",
    "contact": "Aap humein +91-9559102009 par call kar sakte hain, ya info@carditabs.com par email kar sakte hain.",
    "warranty": "Zyadatar products par 1-3 saal ki manufacturer warranty hoti hai, product ke hisaab se.",
}


def send_whatsapp_message(to, text):
    url = f"https://graph.facebook.com/v21.0/{PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WHATSAPP_TOKEN}",
        "Content-Type": "application/json"
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"body": text}
    }
    r = requests.post(url, headers=headers, json=payload, timeout=20)
    print(f"SEND to {to}: {r.status_code} {r.text}", flush=True)
    return r


# ---- TELEGRAM (owner inbox) ----
def tg_send(chat_id, text, reply_to=None):
    if not TELEGRAM_BOT_TOKEN or not chat_id:
        return None
    payload = {"chat_id": chat_id, "text": text[:4000]}
    if reply_to:
        payload["reply_to_message_id"] = reply_to
    try:
        r = requests.post(f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
                          json=payload, timeout=20)
        if r.status_code != 200:
            print(f"TELEGRAM SEND ERROR: {r.status_code} {r.text}", flush=True)
        return r
    except Exception as e:
        print(f"TELEGRAM SEND ERROR: {e}", flush=True)
        return None


def forward_to_owner(name, number, customer_text, bot_reply):
    text = (
        f"📩 WhatsApp message\n"
        f"Naam: {name}\n"
        f"Number: +{number}\n\n"
        f"Customer: {customer_text}\n\n"
        f"🤖 Bot ne jawab diya: {bot_reply if bot_reply else '(koi auto-reply nahi)'}\n\n"
        f"↩️ Customer ko jawab dene ke liye is message ko Reply karein.\n"
        f"#wa{number}"
    )
    tg_send(TELEGRAM_CHAT_ID, text)


def _last10(num):
    digits = "".join(filter(str.isdigit, str(num or "")))
    return digits[-10:]


NOT_MATCHED_MSG = (
    "Maaf kijiye, ye order aapke is WhatsApp number se registered nahi mila. "
    "Kripya usi number se message karein jo order karte waqt diya tha, "
    "ya +91 95591 02009 par call karein."
)


def get_order_status(order_id, from_number):
    try:
        url = f"{WC_SITE_URL}/wp-json/wc/v3/orders/{order_id}"
        r = requests.get(url, auth=(WC_CONSUMER_KEY, WC_CONSUMER_SECRET), timeout=20)
        if r.status_code != 200:
            return NOT_MATCHED_MSG
        order = r.json()
        sender = _last10(from_number)
        phones = {
            _last10(order.get("billing", {}).get("phone")),
            _last10(order.get("shipping", {}).get("phone")),
        }
        phones.discard("")
        if not sender or sender not in phones:
            print(f"ORDER {order_id}: phone mismatch for sender ending {sender[-4:]}", flush=True)
            return NOT_MATCHED_MSG
        status = order.get("status", "unknown")
        total = order.get("total", "N/A")
        status_map = {
            "pending": "Payment ka wait ho raha hai",
            "processing": "Order process ho raha hai, jaldi ship hoga",
            "on-hold": "Order hold par hai",
            "completed": "Order deliver ho chuka hai",
            "cancelled": "Order cancel ho gaya hai",
            "refunded": "Order refund ho gaya hai",
            "shipped": "Order ship ho chuka hai"
        }
        friendly_status = status_map.get(status, status)
        return f"Order #{order_id} ka status: {friendly_status}\nTotal: Rs {total}"
    except Exception as e:
        print(f"Order lookup error: {e}", flush=True)
        return "Order status check karne mein problem aa rahi hai. Please thodi der baad try karein."


def process_message(text, from_number):
    text_lower = text.lower().strip()

    # Order status check: "order 12345" or "order status 12345"
    if "order" in text_lower:
        digits = "".join(filter(str.isdigit, text_lower))
        if digits:
            return get_order_status(digits, from_number)
        else:
            return "Order status check karne ke liye, apna order number bhejein. Jaise: 'order 12345'"

    # FAQ matching
    for keyword, answer in FAQS.items():
        if keyword in text_lower:
            return answer

    # Default fallback
    return (
        "Namaste! CardiTabs mein aapka swagat hai. Main in cheezon mein madad kar sakta hoon:\n\n"
        "- Order status: 'order [number]' likhein\n"
        "- Shipping info: 'shipping' likhein\n"
        "- Return policy: 'return' likhein\n"
        "- Payment options: 'payment' likhein\n"
        "- Contact info: 'contact' likhein\n\n"
        "Ya humse seedha baat karne ke liye +91-9559102009 par call karein."
    )


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")

    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200
    return "Verification failed", 403


@app.route("/webhook", methods=["POST"])
def receive_message():
    data = request.get_json(silent=True) or {}
    print(f"WEBHOOK IN: {data}", flush=True)

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "messages" in value:
            message = value["messages"][0]
            from_number = message["from"]
            msg_type = message["type"]
            name = (value.get("contacts") or [{}])[0].get("profile", {}).get("name", "")

            if msg_type == "text":
                text = message["text"]["body"]
                reply = process_message(text, from_number)
                send_whatsapp_message(from_number, reply)
                forward_to_owner(name, from_number, text, reply)
            else:
                reply = ("Shukriya! Aapka message mil gaya hai. Humari team jaldi aapko jawab degi. "
                         "Order status ke liye 'order [number]' likhein.")
                send_whatsapp_message(from_number, reply)
                forward_to_owner(name, from_number, f"[{msg_type} bheja - WhatsApp par hi dekhna sambhav nahi, customer se text mein poochein]", reply)

    except (KeyError, IndexError) as e:
        print(f"Error processing webhook: {e}", flush=True)

    return jsonify({"status": "ok"}), 200


@app.route("/telegram", methods=["POST"])
def telegram_webhook():
    if TELEGRAM_SECRET and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != TELEGRAM_SECRET:
        return "forbidden", 403
    upd = request.get_json(silent=True) or {}
    msg = upd.get("message") or {}
    chat_id = str((msg.get("chat") or {}).get("id", ""))
    text = (msg.get("text") or "").strip()
    if not chat_id:
        return jsonify({"ok": True}), 200

    # Setup help: /start batata hai chat id
    if text.startswith("/start") or text.startswith("/id"):
        tg_send(chat_id, f"Aapka Telegram chat ID: {chat_id}\nIse Render mein TELEGRAM_CHAT_ID mein daalein.")
        return jsonify({"ok": True}), 200

    # Sirf owner hi reply kar sakta hai
    if not TELEGRAM_CHAT_ID or chat_id != TELEGRAM_CHAT_ID:
        return jsonify({"ok": True}), 200

    replied = (msg.get("reply_to_message") or {}).get("text", "")
    m = re.search(r"#wa(\d{8,15})", replied)
    if not m:
        tg_send(chat_id, "Customer ko jawab dene ke liye uske WhatsApp wale message par 'Reply' karke likhein.",
                reply_to=msg.get("message_id"))
        return jsonify({"ok": True}), 200
    if not text:
        tg_send(chat_id, "Abhi sirf text jawab bheja ja sakta hai.", reply_to=msg.get("message_id"))
        return jsonify({"ok": True}), 200

    number = m.group(1)
    r = send_whatsapp_message(number, text)
    if r is not None and r.status_code == 200:
        tg_send(chat_id, f"✅ +{number} ko bhej diya.", reply_to=msg.get("message_id"))
    else:
        err = ""
        try:
            err = r.json().get("error", {}).get("message", "")
        except Exception:
            pass
        hint = ""
        if r is not None and "131047" in (r.text or ""):
            hint = "\n(Customer ka aakhri message 24 ghante se purana hai. WhatsApp ke niyam se ab sirf approved template hi bheja ja sakta hai.)"
        tg_send(chat_id, f"❌ Nahi gaya: {err}{hint}", reply_to=msg.get("message_id"))
    return jsonify({"ok": True}), 200



# =====================================================================
#  SHOP WITH AI  (website par "Shop with AI" chat ke liye)
#  Render env: GEMINI_API_KEY (zaroori), GEMINI_MODEL (optional)
# =====================================================================
import json, time, html as _html
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "").strip()   # khali = apne aap sahi model chunega
_model = {"name": GEMINI_MODEL, "t": 0, "pool": []}

def pick_model(force=False):
    """Google ki list se naya 'flash' model chunna (purane model band ho jate hain)."""
    if _model["name"] and not force and (GEMINI_MODEL or time.time() - _model["t"] < 24 * 3600):
        return _model["name"]
    r = requests.get("https://generativelanguage.googleapis.com/v1beta/models",
                     headers={"x-goog-api-key": GEMINI_API_KEY}, params={"pageSize": 200}, timeout=20)
    r.raise_for_status()
    names = [m["name"].split("/")[-1] for m in r.json().get("models", [])
             if "generateContent" in m.get("supportedGenerationMethods", [])]
    flash = [n for n in names if "flash" in n and not any(x in n for x in ("lite", "image", "tts", "audio", "live", "preview", "exp", "thinking"))]
    def ver(n):
        m = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(m.group(1)) if m else 0
    pool = flash or [n for n in names if "flash" in n] or names
    pool.sort(key=lambda n: (ver(n), "latest" not in n), reverse=True)
    if not pool:
        raise RuntimeError("koi Gemini model nahi mila")
    lite = sorted([n for n in names if "flash-lite" in n and "preview" not in n], key=ver, reverse=True)
    _model.update(name=pool[0], t=time.time(), pool=(pool[:3] + lite[:2]))
    print("GEMINI MODEL:", pool[0], flush=True)
    return pool[0]
ALLOWED_ORIGINS = {"https://carditabs.com", "https://www.carditabs.com"}
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"}
_catalog = {"t": 0, "items": []}
_rate = {}

def _strip(t):
    return re.sub(r"\s+", " ", _html.unescape(re.sub(r"<[^>]+>|\[[^\]]*\]", " ", t or ""))).strip()

def get_catalog():
    if _catalog["items"] and time.time() - _catalog["t"] < 6 * 3600:
        return _catalog["items"]
    items, page = [], 1
    while page <= 5:
        try:
            r = requests.get(f"{WC_SITE_URL}/wp-json/wc/store/v1/products",
                             params={"per_page": 100, "page": page}, headers=_UA, timeout=20)
            data = r.json() if r.ok else []
        except Exception as e:
            print("catalog error", e, flush=True); break
        if not data:
            break
        for p in data:
            pr = p.get("prices", {}); mu = 10 ** int(pr.get("currency_minor_unit", 2) or 2)
            items.append({
                "id": p["id"], "name": _html.unescape(p["name"]),
                "price": int(int(pr.get("price") or 0) / mu), "mrp": int(int(pr.get("regular_price") or 0) / mu),
                "cat": ", ".join(c["name"] for c in p.get("categories", [])),
                "stock": p.get("is_in_stock", True), "url": p.get("permalink", ""),
                "img": (p.get("images") or [{}])[0].get("thumbnail", ""),
                "desc": _strip(p.get("short_description") or p.get("description"))[:180]})
        page += 1
    if items:
        _catalog.update(t=time.time(), items=items)
    return _catalog["items"]

AI_RULES = """You are "CardiTabs AI", the shopping assistant of CardiTabs (carditabs.com), a genuine medical equipment store from Lucknow, India.
Rules:
- Recommend ONLY products from the CATALOG below. Never invent products, prices or specs. Max 4 products.
- Reply in the customer's language/style (Hinglish, Hindi or English). Keep replies short (2-5 sentences), warm and practical.
- You are not a doctor. Never diagnose or suggest doses/settings. For CPAP/BiPAP pressure, oxygen or anything clinical, say to follow the doctor's prescription.
- Store facts: pan-India delivery, dispatch usually within 24 hours, Cash on Delivery available, 8-day easy returns, first order code WELCOME500 (20% off up to Rs 500). WhatsApp/Call +91 95591 02009.
- If nothing in the catalog fits, say so and suggest WhatsApp for help.
Return ONLY JSON: {"reply": "<text>", "product_ids": [<ids from catalog>]}"""

def ai_answer(message, history):
    cat = get_catalog()
    lines = "\n".join(f'{c["id"]} | {c["name"]} | Rs {c["price"]} (MRP {c["mrp"]}) | {c["cat"]} | '
                      f'{"in stock" if c["stock"] else "out of stock"} | {c["desc"]}' for c in cat)
    contents = []
    for h in history[-6:]:
        role = "model" if h.get("role") == "ai" else "user"
        contents.append({"role": role, "parts": [{"text": str(h.get("text", ""))[:600]}]})
    contents.append({"role": "user", "parts": [{"text": message[:600]}]})
    body = {"systemInstruction": {"parts": [{"text": AI_RULES + "\n\nCATALOG (id | name | price | category | stock | info):\n" + lines}]},
            "contents": contents,
            "generationConfig": {"temperature": 0.4, "responseMimeType": "application/json", "maxOutputTokens": 800}}
    def call(model):
        return requests.post(f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
                             headers={"x-goog-api-key": GEMINI_API_KEY}, json=body, timeout=40)
    first = pick_model()
    r = call(first)
    if r.status_code == 404:               # model band ho gaya -> naya chuno
        first = pick_model(force=True)
        r = call(first)
    if r.status_code in (429, 500, 503):   # busy / quota -> dobara, phir dusra model
        tried = [first]
        for m in [first] + [x for x in _model.get("pool", []) if x != first]:
            time.sleep(1.5)
            r = call(m)
            tried.append(m)
            if r.ok:
                print("GEMINI fallback ok:", m, flush=True)
                break
            if len(tried) >= 4:
                break
    if not r.ok:
        raise RuntimeError(f"Gemini {r.status_code}: {r.text[:200]}")
    txt = r.json()["candidates"][0]["content"]["parts"][0]["text"]
    try:
        out = json.loads(txt)
    except Exception:
        m = re.search(r"\{.*\}", txt, re.S)
        out = json.loads(m.group(0)) if m else {"reply": txt, "product_ids": []}
    by_id = {c["id"]: c for c in cat}
    prods = [by_id[int(i)] for i in out.get("product_ids", []) if str(i).isdigit() and int(i) in by_id][:4]
    return out.get("reply", ""), [{k: p[k] for k in ("name", "price", "mrp", "url", "img", "stock")} for p in prods]

@app.after_request
def _cors(resp):
    o = request.headers.get("Origin", "")
    if o in ALLOWED_ORIGINS and request.path.startswith("/ai-shop"):
        resp.headers["Access-Control-Allow-Origin"] = o
        resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type"
    return resp

@app.route("/ai-shop", methods=["POST", "OPTIONS"])
def ai_shop():
    if request.method == "OPTIONS":
        return "", 204
    if not GEMINI_API_KEY:
        return jsonify({"reply": "AI abhi set nahi hai. Kripya WhatsApp karein: +91 95591 02009", "products": []}), 200
    ip = (request.headers.get("X-Forwarded-For", request.remote_addr) or "").split(",")[0].strip()
    now = time.time()
    hits = [t for t in _rate.get(ip, []) if now - t < 3600]
    if len(hits) >= 30:
        return jsonify({"reply": "Bahut zyada sawaal ho gaye. Thodi der baad try karein ya WhatsApp karein: +91 95591 02009", "products": []}), 200
    _rate[ip] = hits + [now]
    data = request.get_json(silent=True) or {}
    msg = str(data.get("message", "")).strip()
    if not msg:
        return jsonify({"reply": "Aap kya dhoondh rahe hain? Jaise: 'ghar ke liye BP machine'", "products": []}), 200
    try:
        reply, prods = ai_answer(msg, data.get("history") or [])
    except Exception as e:
        print("AI error:", e, flush=True)
        return jsonify({"reply": "Maaf kijiye, abhi jawab nahi de pa raha. WhatsApp karein: +91 95591 02009", "products": []}), 200
    try:
        if TELEGRAM_CHAT_ID:
            tg_send(TELEGRAM_CHAT_ID, f"🤖 Shop with AI\nQ: {msg[:300]}\nA: {reply[:300]}\nProducts: {', '.join(p['name'][:40] for p in prods) or '-'}")
    except Exception:
        pass
    return jsonify({"reply": reply, "products": prods}), 200

@app.route("/", methods=["GET"])
def home():
    return "CardiTabs WhatsApp Bot is running!", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
