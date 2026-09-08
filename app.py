import os
import re
import json
import time
from flask import Flask, request, jsonify, send_from_directory
import requests

app = Flask(__name__, static_folder="static")

BOT_TOKEN = os.environ.get("BOT_TOKEN")
TG_BASE = f"https://api.telegram.org/bot{BOT_TOKEN}"
APP_URL = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:5000")

DATA_FILE = "data.json"
CURRENCIES = ["₽", "$", "€", "₴", "£"]

CATEGORY_EMOJI = {
    "еда": "🍔", "транспорт": "🚌", "шоппинг": "🛍️", "дом": "🏠",
    "счета": "📱", "развлечения": "🎬", "доход": "💰", "накопление": "🎯", "другое": "✨",
}

CATEGORY_KEYWORDS = {
    "еда": ["кофе", "обед", "ужин", "завтрак", "еда", "продукт", "ресторан", "кафе", "пицц", "суши", "бургер", "магнит", "пятерочк"],
    "транспорт": ["такси", "метро", "автобус", "бензин", "заправк", "проезд", "транспорт", "уберк"],
    "шоппинг": ["одежд", "куртк", "обувь", "магазин", "шоппинг", "покупк", "кроссовк"],
    "дом": ["аренда", "квартир", "ремонт", "мебель"],
    "счета": ["телефон", "интернет", "связь", "подписк", "коммуналк", "счет", "счёт"],
    "развлечения": ["кино", "игра", "концерт", "бар", "развлечен", "клуб"],
}

INCOME_TRIGGERS = ["зарплат", "аванс", "получил", "вернули", "кэшбек", "заработал", "доход"]
GOAL_CONTRIB_TRIGGERS = ["отложил", "отложила", "закинул на", "добавил на", "закинула на"]
NEW_GOAL_TRIGGERS = ["хочу накопить", "коплю на", "новая цель", "цель:"]


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
        data[user_id] = {"balance": 0, "currency": "₽", "history": [], "goals": {}, "debts": []}
    u = data[user_id]
    u.setdefault("goals", {})
    u.setdefault("debts", [])
    return u


def extract_amount(text):
    m = re.search(r'(\d+[.,]?\d*)\s*(к|тыс)?', text.lower())
    if not m:
        return None
    num = float(m.group(1).replace(',', '.'))
    if m.group(2):
        num *= 1000
    return num


def detect_category(text):
    low = text.lower()
    for cat, words in CATEGORY_KEYWORDS.items():
        for w in words:
            if w in low:
                return cat
    return "другое"


def extract_goal_name(text):
    m = re.search(r'на\s+([а-яё]+)', text.lower())
    if m:
        return m.group(1)
    return "цель"


def parse_rule_based(text):
    low = text.lower()
    amount = extract_amount(text) or 0
    comment = text.strip()[:40] or "без комментария"

    if any(t in low for t in NEW_GOAL_TRIGGERS):
        return {"type": "new_goal", "amount": 0, "category": "накопление", "comment": comment,
                "goal_name": extract_goal_name(text), "goal_target": amount or 100000}
    if any(t in low for t in GOAL_CONTRIB_TRIGGERS):
        return {"type": "goal_contribution", "amount": amount, "category": "накопление", "comment": comment,
                "goal_name": extract_goal_name(text), "goal_target": None}
    if any(t in low for t in INCOME_TRIGGERS):
        return {"type": "income", "amount": amount, "category": "доход", "comment": comment,
                "goal_name": None, "goal_target": None}
    return {"type": "expense", "amount": amount, "category": detect_category(text), "comment": comment,
            "goal_name": None, "goal_target": None}


def apply_parsed(user, parsed):
    kind = parsed.get("type")
    amount = float(parsed.get("amount") or 0)
    category = parsed.get("category") or "другое"
    comment = parsed.get("comment") or "без комментария"
    emoji = CATEGORY_EMOJI.get(category, "✨")

    if kind == "expense":
        user["balance"] -= amount
        user["history"].insert(0, {"amount": -amount, "comment": comment, "category": category, "emoji": emoji})
    elif kind == "income":
        user["balance"] += amount
        user["history"].insert(0, {"amount": amount, "comment": comment, "category": category, "emoji": emoji})
    elif kind == "goal_contribution":
        goal_name = parsed.get("goal_name") or "цель"
        if goal_name not in user["goals"]:
            user["goals"][goal_name] = {"target": max(amount * 4, 1), "saved": 0}
        user["goals"][goal_name]["saved"] += amount
        user["balance"] -= amount
        user["history"].insert(0, {"amount": -amount, "comment": f"отложено: {goal_name}", "category": "накопление", "emoji": "🎯"})
    elif kind == "new_goal":
        goal_name = parsed.get("goal_name") or "цель"
        target = float(parsed.get("goal_target") or 100000)
        user["goals"][goal_name] = {"target": target, "saved": 0}

    user["history"] = user["history"][:20]
    return user


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


@app.route("/api/quick-add", methods=["POST"])
def api_quick_add():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    text = (body.get("text") or "").strip()
    if not user_id or not text:
        return jsonify({"error": "invalid request"}), 400

    parsed = parse_rule_based(text)
    data = load_data()
    user = get_user(data, user_id)
    user = apply_parsed(user, parsed)
    save_data(data)
    return jsonify(user)


@app.route("/api/debt/add", methods=["POST"])
def api_debt_add():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    name = (body.get("name") or "").strip()
    amount = body.get("amount")
    direction = body.get("direction")

    if not user_id or not name or direction not in ("in", "out"):
        return jsonify({"error": "invalid request"}), 400
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return jsonify({"error": "invalid amount"}), 400

    data = load_data()
    user = get_user(data, user_id)
    user["debts"].append({
        "id": int(time.time() * 1000),
        "name": name,
        "amount": amount,
        "direction": direction,
    })
    save_data(data)
    return jsonify(user)


@app.route("/api/debt/resolve", methods=["POST"])
def api_debt_resolve():
    body = request.get_json(silent=True) or {}
    user_id = body.get("user_id")
    debt_id = body.get("debt_id")
    if not user_id or debt_id is None:
        return jsonify({"error": "invalid request"}), 400

    data = load_data()
    user = get_user(data, user_id)
    user["debts"] = [d for d in user["debts"] if d["id"] != debt_id]
    save_data(data)
    return jsonify(user)


# ---------- Бот через вебхук ----------

def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text}
    if reply_markup:
        payload["reply_markup"] = reply_markup
    requests.post(f"{TG_BASE}/sendMessage", json=payload)


@app.route("/webhook", methods=["POST"])
def webhook():
    update = request.get_json(silent=True) or {}
    message = update.get("message")
    if not message:
        return jsonify({"ok": True})

    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    text = message.get("text", "")

    if text == "/start":
        send_message(chat_id,
            "Привет! Я твой трекер накоплений.\nПиши фразой: «потратил 350 на кофе», «отложил 5000 на машину»\n\nИли открой интерфейс:",
            reply_markup={"inline_keyboard": [[{"text": "Открыть трекер", "web_app": {"url": APP_URL}}]]}
        )
        return jsonify({"ok": True})

    parsed = parse_rule_based(text)
    data = load_data()
    user = get_user(data, user_id)
    user = apply_parsed(user, parsed)
    save_data(data)

    emoji = CATEGORY_EMOJI.get(parsed.get("category"), "✨")
    send_message(chat_id, f"{emoji} Записал: {parsed.get('comment')}\nБаланс: {user['balance']} {user['currency']}")
    return jsonify({"ok": True})


@app.route("/set_webhook")
def set_webhook():
    res = requests.get(f"{TG_BASE}/setWebhook", params={"url": f"{APP_URL}/webhook"})
    return jsonify(res.json())


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
