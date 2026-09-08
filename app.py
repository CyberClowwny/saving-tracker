import os
import json
from flask import Flask, request, jsonify, send_from_directory
import requests

app = Flask(__name__, static_folder="static")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
BASE_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"
APP_URL = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")

DATA_FILE = "data.json"
CURRENCIES = ["₽", "$", "€", "₴", "£"]


def load_data():
    if not os.path.exists(DATA_FILE):
        return {}
    with open(DATA_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_data(data):
    with open(DATA_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def get_user(data, user_id):
    user_id = str(user_id)
    if user_id not in data:
        data[user_id] = {"balance": 0, "currency": "₽", "history": []}
    return data[user_id]


# ---------- Веб-страница и API мини-аппа ----------

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/api/data")
def api_get_data():
    user_id = request.args.get("user_id")
    if not user_id:
        return jsonify({"error": "no user_id"}), 400
    data = load_data()
    user = get_user(data, user_id)
    save_data(data)
    return jsonify(user)


@app.route("/api/currency", methods=["POST"])
def api_set_currency():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    currency = body.get("currency")
    if not user_id or currency not in CURRENCIES:
        return jsonify({"error": "invalid request"}), 400
    data = load_data()
    user = get_user(data, user_id)
    user["currency"] = currency
    save_data(data)
    return jsonify(user)


@app.route("/api/operation", methods=["POST"])
def api_add_operation():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    amount = body.get("amount")
    comment = (body.get("comment") or "").strip() or "без комментария"
    if not user_id:
        return jsonify({"error": "no user_id"}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid amount"}), 400
    data = load_data()
    user = get_user(data, user_id)
    user["balance"] += amount
    user["history"].insert(0, {"amount": amount, "comment": comment})
    user["history"] = user["history"][:20]
    save_data(data)
    return jsonify(user)


# ---------- Бот через вебхук (вместо постоянного опроса) ----------

@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message")

    if message and message.get("text") == "/start":
        chat_id = message["chat"]["id"]
        requests.post(f"{BASE_URL}/sendMessage", json={
            "chat_id": chat_id,
            "text": "Привет! Я твой трекер накоплений.\nНажми кнопку, чтобы открыть его:",
            "reply_markup": {
                "inline_keyboard": [[
                    {"text": "Открыть трекер", "web_app": {"url": APP_URL}}
                ]]
            }
        })

    return jsonify({"ok": True})


@app.route("/set_webhook")
def set_webhook():
    res = requests.get(f"{BASE_URL}/setWebhook", params={"url": f"{APP_URL}/webhook"})
    return jsonify(res.json())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
