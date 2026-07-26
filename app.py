import os
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

# ---- CONFIG (set these as Environment Variables on Render) ----
VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "carditabs_verify_123")
WHATSAPP_TOKEN = os.environ.get("WHATSAPP_TOKEN", "")
PHONE_NUMBER_ID = os.environ.get("PHONE_NUMBER_ID", "")
WC_CONSUMER_KEY = os.environ.get("WC_CONSUMER_KEY", "")
WC_CONSUMER_SECRET = os.environ.get("WC_CONSUMER_SECRET", "")
WC_SITE_URL = os.environ.get("WC_SITE_URL", "https://carditabs.com")

# ---- FAQ RESPONSES ----
FAQS = {
    "shipping": "Hum pan-India shipping karte hain! Orders usually 3-5 business days mein deliver hote hain.",
    "return": "Aap 7 din ke andar return/exchange kar sakte hain agar product mein koi issue ho. Details: carditabs.com/refund-return-policy/",
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
    requests.post(url, headers=headers, json=payload)


def get_order_status(order_id):
    try:
        url = f"{WC_SITE_URL}/wp-json/wc/v3/orders/{order_id}"
        r = requests.get(url, auth=(WC_CONSUMER_KEY, WC_CONSUMER_SECRET))
        if r.status_code == 200:
            order = r.json()
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
        else:
            return f"Order #{order_id} nahi mila. Please order ID check karein."
    except Exception as e:
        return "Order status check karne mein problem aa rahi hai. Please thodi der baad try karein."


def process_message(text, from_number):
    text_lower = text.lower().strip()

    # Order status check: "order 12345" or "order status 12345"
    if "order" in text_lower:
        digits = "".join(filter(str.isdigit, text_lower))
        if digits:
            return get_order_status(digits)
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
    data = request.get_json()

    try:
        entry = data["entry"][0]
        changes = entry["changes"][0]
        value = changes["value"]

        if "messages" in value:
            message = value["messages"][0]
            from_number = message["from"]
            msg_type = message["type"]

            if msg_type == "text":
                text = message["text"]["body"]
                reply = process_message(text, from_number)
                send_whatsapp_message(from_number, reply)

    except (KeyError, IndexError) as e:
        print(f"Error processing webhook: {e}")

    return jsonify({"status": "ok"}), 200


@app.route("/", methods=["GET"])
def home():
    return "CardiTabs WhatsApp Bot is running!", 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
