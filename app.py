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


@app.route("/", methods=["GET"])
def home():
    return "CardiTabs WhatsApp Bot is running!", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
