import os
import json
import hmac
import hashlib
import sqlite3
import uuid
import time
from urllib.parse import parse_qsl
from contextlib import contextmanager

import httpx
from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "").strip()
DATABASE_PATH = os.getenv("DATABASE_PATH", "/var/data/yupi_stars.sqlite3")
WEB_APP_URL = os.getenv("WEB_APP_URL", "https://qwert44003.github.io/yupistars-/").strip()
SUPPORT_USERNAME = os.getenv("SUPPORT_USERNAME", "@your_support").strip()

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is required")
if not WEBHOOK_SECRET:
    raise RuntimeError("WEBHOOK_SECRET environment variable is required")

BOT_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
app = FastAPI(title="Yupi Stars Payments API", version="1.0.0")

allowed_origins = [
    "https://qwert44003.github.io",
    "http://localhost:8000",
    "http://127.0.0.1:8000",
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-Telegram-Init-Data"],
)

@contextmanager
def db():
    folder = os.path.dirname(DATABASE_PATH)
    if folder:
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init_db():
    with db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id INTEGER PRIMARY KEY,
                balance INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                payload TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at INTEGER NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS payments (
                charge_id TEXT PRIMARY KEY,
                telegram_id INTEGER NOT NULL,
                amount INTEGER NOT NULL,
                payload TEXT NOT NULL,
                created_at INTEGER NOT NULL
            )
        """)

init_db()

def verify_init_data(init_data: str) -> dict:
    if not init_data:
        raise HTTPException(status_code=401, detail="Telegram initData is missing")

    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received_hash = pairs.pop("hash", None)
        if not received_hash:
            raise ValueError("hash missing")

        auth_date = int(pairs.get("auth_date", "0"))
        if auth_date <= 0 or time.time() - auth_date > 86400 or auth_date - time.time() > 60:
            raise ValueError("initData expired")

        data_check_string = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
        secret_key = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calculated_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calculated_hash, received_hash):
            raise ValueError("invalid signature")

        user_data = json.loads(pairs["user"])
        user_id = int(user_data["id"])
        return {"user_id": user_id, "user": user_data}
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired Telegram initData")

async def telegram_call(method: str, data: dict):
    async with httpx.AsyncClient(timeout=20) as client:
        response = await client.post(f"{BOT_API}/{method}", json=data)
        response.raise_for_status()
        result = response.json()
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail=f"Telegram API error: {result.get('description', 'unknown error')}")
    return result["result"]

class InvoiceRequest(BaseModel):
    amount: int = Field(ge=1, le=10000)

@app.get("/")
def root():
    return {"ok": True, "service": "Yupi Stars payment server"}

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/create-invoice")
async def create_invoice(body: InvoiceRequest, x_telegram_init_data: str = Header(default="")):
    auth = verify_init_data(x_telegram_init_data)
    user_id = auth["user_id"]
    amount = body.amount
    payload = f"yupi:{user_id}:{uuid.uuid4().hex}"

    with db() as conn:
        conn.execute("INSERT OR IGNORE INTO users (telegram_id, balance) VALUES (?, 0)", (user_id,))
        conn.execute(
            "INSERT INTO orders (payload, telegram_id, amount, status, created_at) VALUES (?, ?, ?, 'pending', ?)",
            (payload, user_id, amount, int(time.time())),
        )

    invoice_link = await telegram_call("createInvoiceLink", {
        "title": "Пополнение Yupi Stars",
        "description": f"Начисление {amount} игровых звёзд на баланс Yupi Stars",
        "payload": payload,
        "provider_token": "",
        "currency": "XTR",
        "prices": [{"label": f"{amount} игровых звёзд", "amount": amount}],
    })
    return {"invoice_link": invoice_link, "amount": amount, "currency": "XTR"}

@app.get("/balance")
def get_balance(x_telegram_init_data: str = Header(default="")):
    auth = verify_init_data(x_telegram_init_data)
    with db() as conn:
        row = conn.execute("SELECT balance FROM users WHERE telegram_id = ?", (auth["user_id"],)).fetchone()
        balance = int(row["balance"]) if row else 0
    return {"user_id": auth["user_id"], "balance": balance}

@app.post("/telegram-webhook")
async def telegram_webhook(request: Request, x_telegram_bot_api_secret_token: str = Header(default="")):
    if not hmac.compare_digest(x_telegram_bot_api_secret_token, WEBHOOK_SECRET):
        raise HTTPException(status_code=403, detail="Forbidden")

    update = await request.json()

    if "pre_checkout_query" in update:
        query = update["pre_checkout_query"]
        payload = query.get("invoice_payload", "")
        with db() as conn:
            order = conn.execute(
                "SELECT telegram_id, amount, status FROM orders WHERE payload = ?", (payload,)
            ).fetchone()

        valid = (
            order is not None
            and order["status"] == "pending"
            and int(order["telegram_id"]) == int(query["from"]["id"])
            and query.get("currency") == "XTR"
            and int(query.get("total_amount", 0)) == int(order["amount"])
        )
        answer = {"pre_checkout_query_id": query["id"], "ok": valid}
        if not valid:
            answer["error_message"] = "Не удалось проверить заказ. Создайте новый счёт."
        await telegram_call("answerPreCheckoutQuery", answer)
        return {"ok": True}

    message = update.get("message", {})
    successful = message.get("successful_payment")
    if successful:
        payment = successful
        user_id = int(message["from"]["id"])
        amount = int(payment.get("total_amount", 0))
        payload = payment.get("invoice_payload", "")
        charge_id = payment.get("telegram_payment_charge_id", "")

        if payment.get("currency") != "XTR" or not charge_id:
            return {"ok": True}

        with db() as conn:
            conn.execute("BEGIN IMMEDIATE")
            order = conn.execute(
                "SELECT telegram_id, amount, status FROM orders WHERE payload = ?", (payload,)
            ).fetchone()

            if (order and order["status"] == "pending"
                    and int(order["telegram_id"]) == user_id
                    and int(order["amount"]) == amount):
                inserted = conn.execute(
                    "INSERT OR IGNORE INTO payments (charge_id, telegram_id, amount, payload, created_at) VALUES (?, ?, ?, ?, ?)",
                    (charge_id, user_id, amount, payload, int(time.time())),
                ).rowcount
                if inserted:
                    conn.execute(
                        "INSERT OR IGNORE INTO users (telegram_id, balance) VALUES (?, 0)", (user_id,)
                    )
                    conn.execute(
                        "UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, user_id)
                    )
                    conn.execute("UPDATE orders SET status = 'paid' WHERE payload = ?", (payload,))

        if order and order["status"] == "pending":
            await telegram_call("sendMessage", {
                "chat_id": user_id,
                "text": f"⭐ Оплата получена! На баланс Yupi Stars начислено {amount} игровых звёзд."
            })
        return {"ok": True}

    # Basic bot commands, including required payment support entry point.
    text = message.get("text", "")
    chat_id = message.get("chat", {}).get("id")
    if chat_id and text.startswith("/start"):
        await telegram_call("sendMessage", {
            "chat_id": chat_id,
            "text": "Добро пожаловать в Yupi Stars! Откройте Mini App, чтобы пополнить игровой баланс."
        })
    elif chat_id and text.startswith("/paysupport"):
        await telegram_call("sendMessage", {
            "chat_id": chat_id,
            "text": f"Поддержка по платежам: {SUPPORT_USERNAME}. Укажите дату, сумму и Telegram ID платежа."
        })
    elif chat_id and text.startswith("/terms"):
        await telegram_call("sendMessage", {
            "chat_id": chat_id,
            "text": "Оплачивая пополнение, вы подтверждаете согласие с правилами Yupi Stars. Цифровое пополнение зачисляется после подтверждения Telegram. По вопросам платежей: /paysupport."
        })
    return {"ok": True}
