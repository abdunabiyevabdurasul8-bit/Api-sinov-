import os
import uuid
import logging
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
import psycopg2
from psycopg2.extras import RealDictCursor

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
)
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)


# =========================================================
# LOGGING
# =========================================================

logging.basicConfig(
    format="%(asctime)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)

logger = logging.getLogger(__name__)


# =========================================================
# ENV SETTINGS
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "8799964859:AAE1ykyVhycVfPwT9z7X-DbCtMs6A5Kxcl0")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL", "")
PORT = int(os.getenv("PORT", "10000"))

SOS_USERNAME = os.getenv("SOS_USERNAME", "@donuz1")


# =========================================================
# API URL
# =========================================================

PAYSTARS_API = "https://paystars.uz/api/v1"
PLAYPAY_API = "https://playpay.uz/api/v1"
AKTIVSIM_API = "https://ws2524.wineclo.com/AktivSimBot/api/v2/"


# =========================================================
# API SETTINGS
# =========================================================

API_SETTINGS = {
    "stars": {
        "name": "⭐ Stars API",
        "setting": "api_key_stars",
    },

    "premium": {
        "name": "💎 Premium API",
        "setting": "api_key_premium",
    },

    "donat": {
        "name": "🎁 Donat API",
        "setting": "api_key_donat",
    },

    "sim": {
        "name": "📱 SIM API",
        "setting": "api_key_sim",
    },
}


# =========================================================
# DEFAULT PRICES
# =========================================================

DEFAULT_PRICES = {
    "stars_50": 5000,
    "stars_100": 9500,
    "stars_250": 22000,
    "stars_500": 42000,

    "premium_3": 35000,
    "premium_6": 65000,
    "premium_12": 120000,

    "donat_1": 5000,
    "donat_7": 20000,
    "donat_30": 38000,

    "sim_1": 5000,
    "sim_7": 20000,
    "sim_30": 38000,
}


# =========================================================
# DATABASE
# =========================================================

def get_db():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL mavjud emas")

    return psycopg2.connect(DATABASE_URL)


def db_query(query, params=None, fetch=False, fetchone=False):
    conn = get_db()

    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(query, params or ())

            result = None

            if fetch:
                result = cur.fetchall()

            elif fetchone:
                result = cur.fetchone()

            conn.commit()
            return result

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


# =========================================================
# DATABASE INIT
# =========================================================

def init_database():

    db_query("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance NUMERIC DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db_query("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            service TEXT NOT NULL,
            started_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            source TEXT DEFAULT 'bot'
        )
    """)

    db_query("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    db_query("""
        CREATE TABLE IF NOT EXISTS orders (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            service TEXT NOT NULL,
            plan TEXT NOT NULL,
            price NUMERIC DEFAULT 0,
            provider_order_id TEXT,
            status TEXT DEFAULT 'Kutilmoqda',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    db_query("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            amount NUMERIC DEFAULT 0,
            status TEXT DEFAULT 'Kutilmoqda',
            admin_id BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    # -----------------------------------------------------
    # DEFAULT SETTINGS
    # -----------------------------------------------------

    defaults = {
        "card": "",
        "sos_username": SOS_USERNAME,

        "api_key_stars": os.getenv(
            "PAYSTARS_STARS_API_KEY", ""
        ),

        "api_key_premium": os.getenv(
            "PAYSTARS_PREMIUM_API_KEY", ""
        ),

        "api_key_donat": os.getenv(
            "PLAYPAY_API_KEY", ""
        ),

        "api_key_sim": os.getenv(
            "AKTIVSIM_API_KEY", ""
        ),
    }

    for key, value in defaults.items():

        db_query("""
            INSERT INTO settings(key, value)
            VALUES(%s, %s)
            ON CONFLICT(key) DO NOTHING
        """, (key, value))

    # -----------------------------------------------------
    # DEFAULT PRICES
    # -----------------------------------------------------

    for key, value in DEFAULT_PRICES.items():

        db_query("""
            INSERT INTO settings(key, value)
            VALUES(%s, %s)
            ON CONFLICT(key) DO NOTHING
        """, (
            "price_" + key,
            str(value)
        ))


# =========================================================
# SETTINGS
# =========================================================

def get_setting(key, default=""):

    row = db_query("""
        SELECT value
        FROM settings
        WHERE key = %s
    """, (key,), fetchone=True)

    if not row:
        return default

    return row["value"]


def set_setting(key, value):

    db_query("""
        INSERT INTO settings(key, value)
        VALUES(%s, %s)
        ON CONFLICT(key)
        DO UPDATE SET value = EXCLUDED.value
    """, (
        key,
        str(value)
    ))


def get_price(key):

    value = get_setting(
        "price_" + key,
        str(DEFAULT_PRICES.get(key, 0))
    )

    try:
        return int(float(value))
    except Exception:
        return 0


def money(value):

    try:
        return f"{int(float(value)):,}".replace(",", " ")
    except Exception:
        return "0"


# =========================================================
# USER
# =========================================================

def save_user(user):

    now = datetime.now(timezone.utc).replace(tzinfo=None)

    db_query("""
        INSERT INTO users(
            user_id,
            username,
            first_name,
            balance,
            created_at,
            last_seen
        )
        VALUES(%s, %s, %s, 0, %s, %s)

        ON CONFLICT(user_id)
        DO UPDATE SET
            username = EXCLUDED.username,
            first_name = EXCLUDED.first_name,
            last_seen = EXCLUDED.last_seen
    """, (
        user.id,
        user.username,
        user.first_name,
        now,
        now
    ))


def get_user(user_id):

    return db_query("""
        SELECT *
        FROM users
        WHERE user_id = %s
    """, (
        user_id,
    ), fetchone=True)


def get_active_subscription(user_id, service):

    now = datetime.utcnow()

    return db_query("""
        SELECT *
        FROM subscriptions
        WHERE user_id = %s
        AND service = %s
        AND expires_at > %s
        ORDER BY expires_at DESC
        LIMIT 1
    """, (
        user_id,
        service,
        now
    ), fetchone=True)


# =========================================================
# MAIN MENU
# =========================================================

def main_menu():

    return ReplyKeyboardMarkup(
        [
            [
                "🤝 Hamkorlik (API)"
            ],
            [
                "💰 Balans",
                "➕ Balans to'ldirish"
            ],
            [
                "📦 Obunalarim"
            ],
            [
                "🆘 SOS"
            ],
        ],
        resize_keyboard=True
    )


# =========================================================
# SERVICE MENU
# =========================================================

def service_menu(service):

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "1 kun",
                    callback_data=f"buy:{service}:1"
                ),
                InlineKeyboardButton(
                    "7 kun",
                    callback_data=f"buy:{service}:7"
                ),
            ],
            [
                InlineKeyboardButton(
                    "1 oy",
                    callback_data=f"buy:{service}:30"
                ),
            ],
            [
                InlineKeyboardButton(
                    "🎁 1 kun bepul sinov",
                    callback_data=f"trial:{service}"
                ),
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Orqaga",
                    callback_data="close"
                )
            ],
        ]
    )


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    save_user(user)

    context.user_data.clear()

    text = (
        "👋 <b>DONUZ BOT</b>\n\n"
        "Kerakli bo‘limni tanlang:"
    )

    await update.message.reply_text(
        text,
        parse_mode="HTML",
        reply_markup=main_menu()
    )


# =========================================================
# SERVICE SELECT
# =========================================================

async def show_service(update, service):

    query = update.callback_query

    name = {
        "stars": "⭐ Stars",
        "premium": "💎 Premium",
        "donat": "🎁 Donat",
        "sim": "📱 SIM",
    }.get(service, service)

    text = (
        f"<b>{name}</b>\n\n"
        "Kerakli muddatni tanlang:"
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=service_menu(service)
    )


# =========================================================
# BALANCE
# =========================================================

async def balance(update, context):

    user = get_user(update.effective_user.id)

    balance_value = user["balance"] if user else 0

    await update.message.reply_text(
        "💰 <b>Balansingiz:</b> "
        f"{money(balance_value)} so‘m",
        parse_mode="HTML"
    )


# =========================================================
# SUBSCRIPTIONS
# =========================================================

async def subscriptions(update, context):

    rows = db_query("""
        SELECT *
        FROM subscriptions
        WHERE user_id = %s
        ORDER BY expires_at DESC
        LIMIT 20
    """, (
        update.effective_user.id,
    ), fetch=True)

    if not rows:

        await update.message.reply_text(
            "📦 Sizda hozircha obuna yo‘q."
        )
        return

    text = "📦 <b>Obunalarim</b>\n\n"

    for row in rows:

        text += (
            f"• {row['service']}\n"
            f"  Boshlangan: {row['started_at']}\n"
            f"  Tugaydi: {row['expires_at']}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# SOS
# =========================================================

async def sos(update, context):

    username = get_setting(
        "sos_username",
        SOS_USERNAME
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🆘 Yordam",
                    url=f"https://t.me/{username.lstrip('@')}"
                )
            ]
        ]
    )

    await update.message.reply_text(
        "🆘 <b>Yordam kerakmi?</b>\n\n"
        "Operator bilan bog‘lanish uchun tugmani bosing.",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# API KEY MASK
# =========================================================

def mask_api_key(key):

    if not key:
        return "❌ Kiritilmagan"

    if len(key) <= 8:
        return "••••••••"

    return key[:4] + "••••••••" + key[-4:]


# =========================================================
# ADMIN MENU
# =========================================================

def admin_menu():

    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⭐ Stars API",
                    callback_data="admin_api:stars"
                ),
                InlineKeyboardButton(
                    "💎 Premium API",
                    callback_data="admin_api:premium"
                ),
            ],

            [
                InlineKeyboardButton(
                    "🎁 Donat API",
                    callback_data="admin_api:donat"
                ),
                InlineKeyboardButton(
                    "📱 SIM API",
                    callback_data="admin_api:sim"
                ),
            ],

            [
                InlineKeyboardButton(
                    "💳 Karta",
                    callback_data="admin_card"
                ),
            ],

            [
                InlineKeyboardButton(
                    "💰 Balans +",
                    callback_data="admin_balance_add"
                ),
                InlineKeyboardButton(
                    "💸 Balans −",
                    callback_data="admin_balance_sub"
                ),
            ],

            [
                InlineKeyboardButton(
                    "👥 Foydalanuvchilar",
                    callback_data="admin_users"
                ),
            ],

            [
                InlineKeyboardButton(
                    "📊 Statistika",
                    callback_data="admin_stats"
                ),

                InlineKeyboardButton(
                    "📋 Obunalar",
                    callback_data="admin_subs"
                ),
            ],

            [
                InlineKeyboardButton(
                    "💵 Narxlar",
                    callback_data="admin_prices"
                ),

                InlineKeyboardButton(
                    "💳 To‘lovlar",
                    callback_data="admin_payments"
                ),
            ],

            [
                InlineKeyboardButton(
                    "🆘 SOS",
                    callback_data="admin_sos"
                ),
            ],
        ]
    )


# =========================================================
# ADMIN PANEL
# =========================================================

async def admin_panel(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    text = (
        "🛠 <b>DONUZ ADMIN PANEL</b>\n\n"
        "Kerakli bo‘limni tanlang:"
    )

    if update.callback_query:

        await update.callback_query.edit_message_text(
            text,
            parse_mode="HTML",
            reply_markup=admin_menu()
        )

    else:

        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=admin_menu()
        )


# =========================================================
# ADMIN API MENU
# =========================================================

async def admin_api_menu(update, context, service):

    query = update.callback_query

    if update.effective_user.id != ADMIN_ID:
        await query.answer("Ruxsat yo‘q.", show_alert=True)
        return

    info = API_SETTINGS[service]

    key = get_setting(info["setting"])

    text = (
        f"<b>{info['name']}</b>\n\n"
        f"API manzil:\n"
    )

    if service in ("stars", "premium"):
        text += f"{PAYSTARS_API}\n\n"

    elif service == "donat":
        text += f"{PLAYPAY_API}\n\n"

    elif service == "sim":
        text += f"{AKTIVSIM_API}\n\n"

    text += (
        f"🔑 API key: <code>{mask_api_key(key)}</code>\n\n"
        "API keyni almashtirish uchun tugmani bosing."
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✏️ API keyni o‘zgartirish",
                    callback_data=f"admin_api_edit:{service}"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Admin panel",
                    callback_data="admin_back"
                )
            ],
        ]
    )

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN API EDIT
# =========================================================

async def admin_api_edit(update, context, service):

    query = update.callback_query

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["admin_action"] = "api_key"
    context.user_data["api_service"] = service

    name = API_SETTINGS[service]["name"]

    await query.edit_message_text(
        f"{name}\n\n"
        "🔑 Yangi API keyni yuboring.\n\n"
        "Bekor qilish uchun /cancel yozing."
    )


# =========================================================
# CANCEL
# =========================================================

async def cancel(update, context):

    context.user_data.clear()

    await update.message.reply_text(
        "❌ Bekor qilindi.",
        reply_markup=main_menu()
    )


# =========================================================
# ADMIN CARD
# =========================================================

async def admin_card(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["admin_action"] = "card"

    card = get_setting("card")

    await update.callback_query.edit_message_text(
        "💳 <b>Karta sozlamasi</b>\n\n"
        f"Joriy karta:\n<code>{card or 'Kiritilmagan'}</code>\n\n"
        "Yangi karta raqamini yuboring.",
        parse_mode="HTML"
    )


# =========================================================
# ADMIN BALANCE
# =========================================================

async def admin_balance_start(update, context, mode):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["admin_action"] = "balance"
    context.user_data["balance_mode"] = mode

    await update.callback_query.edit_message_text(
        "👤 Foydalanuvchi Telegram ID sini yuboring."
    )


# =========================================================
# ADMIN PRICES
# =========================================================

async def admin_prices(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    text = "💵 <b>Narxlar</b>\n\n"

    labels = {
        "stars_50": "⭐ 50 Stars",
        "stars_100": "⭐ 100 Stars",
        "stars_250": "⭐ 250 Stars",
        "stars_500": "⭐ 500 Stars",

        "premium_3": "💎 Premium 3 oy",
        "premium_6": "💎 Premium 6 oy",
        "premium_12": "💎 Premium 12 oy",

        "donat_1": "🎁 Donat 1 kun",
        "donat_7": "🎁 Donat 7 kun",
        "donat_30": "🎁 Donat 1 oy",

        "sim_1": "📱 SIM 1 kun",
        "sim_7": "📱 SIM 7 kun",
        "sim_30": "📱 SIM 1 oy",
    }

    for key, label in labels.items():

        text += (
            f"{label}: "
            f"<b>{money(get_price(key))} so‘m</b>\n"
        )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✏️ Narx o‘zgartirish",
                    callback_data="admin_price_edit"
                )
            ],
            [
                InlineKeyboardButton(
                    "⬅️ Admin panel",
                    callback_data="admin_back"
                )
            ],
        ]
    )

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN PRICE EDIT
# =========================================================

async def admin_price_edit(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["admin_action"] = "price"

    await update.callback_query.edit_message_text(
        "✏️ Narxni o‘zgartirish.\n\n"
        "Avval quyidagi kalitlardan birini yuboring:\n\n"
        "stars_50\n"
        "stars_100\n"
        "stars_250\n"
        "stars_500\n"
        "premium_3\n"
        "premium_6\n"
        "premium_12\n"
        "donat_1\n"
        "donat_7\n"
        "donat_30\n"
        "sim_1\n"
        "sim_7\n"
        "sim_30"
    )


# =========================================================
# ADMIN USERS
# =========================================================

async def admin_users(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    rows = db_query("""
        SELECT
            user_id,
            username,
            first_name,
            balance,
            created_at
        FROM users
        ORDER BY created_at DESC
        LIMIT 50
    """, fetch=True)

    if not rows:

        text = "👥 Foydalanuvchilar yo‘q."

    else:

        text = "👥 <b>Foydalanuvchilar</b>\n\n"

        for row in rows:

            username = (
                f"@{row['username']}"
                if row["username"]
                else "username yo‘q"
            )

            joined = row["created_at"]

            text += (
                f"🆔 <code>{row['user_id']}</code>\n"
                f"👤 {username}\n"
                f"📅 Qo‘shilgan: {joined}\n"
                f"💰 Balans: {money(row['balance'])} so‘m\n"
                f"──────────────\n"
            )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Admin panel",
                    callback_data="admin_back"
                )
            ]
        ]
    )

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN STATS
# =========================================================

async def admin_stats(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    users = db_query("""
        SELECT COUNT(*) AS count
        FROM users
    """, fetchone=True)

    orders = db_query("""
        SELECT COUNT(*) AS count
        FROM orders
    """, fetchone=True)

    subscriptions = db_query("""
        SELECT COUNT(*) AS count
        FROM subscriptions
    """, fetchone=True)

    payments = db_query("""
        SELECT COUNT(*) AS count
        FROM payments
    """, fetchone=True)

    text = (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: {users['count']}\n"
        f"📦 Buyurtmalar: {orders['count']}\n"
        f"📋 Obunalar: {subscriptions['count']}\n"
        f"💳 To‘lovlar: {payments['count']}\n"
    )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Admin panel",
                    callback_data="admin_back"
                )
            ]
        ]
    )

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN SUBSCRIPTIONS
# =========================================================

async def admin_subs(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    rows = db_query("""
        SELECT *
        FROM subscriptions
        ORDER BY id DESC
        LIMIT 30
    """, fetch=True)

    if not rows:

        text = "📋 Obunalar yo‘q."

    else:

        text = "📋 <b>Obunalar</b>\n\n"

        for row in rows:

            text += (
                f"ID: {row['id']}\n"
                f"User: <code>{row['user_id']}</code>\n"
                f"Xizmat: {row['service']}\n"
                f"Tugash: {row['expires_at']}\n"
                f"────────────\n"
            )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Admin panel",
                    callback_data="admin_back"
                )
            ]
        ]
    )

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN PAYMENTS
# =========================================================

async def admin_payments(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    rows = db_query("""
        SELECT *
        FROM payments
        ORDER BY id DESC
        LIMIT 30
    """, fetch=True)

    if not rows:

        text = "💳 To‘lovlar yo‘q."

    else:

        text = "💳 <b>To‘lovlar</b>\n\n"

        for row in rows:

            text += (
                f"ID: {row['id']}\n"
                f"User: <code>{row['user_id']}</code>\n"
                f"Summa: {money(row['amount'])} so‘m\n"
                f"Holat: {row['status']}\n"
                f"────────────\n"
            )

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⬅️ Admin panel",
                    callback_data="admin_back"
                )
            ]
        ]
    )

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN SOS
# =========================================================

async def admin_sos(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data["admin_action"] = "sos"

    current = get_setting(
        "sos_username",
        SOS_USERNAME
    )

    await update.callback_query.edit_message_text(
        "🆘 <b>SOS sozlamasi</b>\n\n"
        f"Joriy: {current}\n\n"
        "Yangi Telegram username yuboring.\n"
        "Masalan: @donuz1",
        parse_mode="HTML"
    )


# =========================================================
# ADMIN TEXT ACTIONS
# =========================================================

async def handle_admin_text(update, context):

    if update.effective_user.id != ADMIN_ID:
        return False

    action = context.user_data.get("admin_action")

    if not action:
        return False

    text = update.message.text.strip()

    # -----------------------------------------------------
    # API KEY
    # -----------------------------------------------------

    if action == "api_key":

        service = context.user_data.get("api_service")

        if service not in API_SETTINGS:
            context.user_data.clear()
            return True

        setting = API_SETTINGS[service]["setting"]

        set_setting(setting, text)

        context.user_data.clear()

        await update.message.reply_text(
            "✅ API key muvaffaqiyatli saqlandi.",
            reply_markup=main_menu()
        )

        return True

    # -----------------------------------------------------
    # CARD
    # -----------------------------------------------------

    if action == "card":

        set_setting("card", text)

        context.user_data.clear()

        await update.message.reply_text(
            "✅ Karta muvaffaqiyatli o‘zgartirildi."
        )

        return True

    # -----------------------------------------------------
    # SOS
    # -----------------------------------------------------

    if action == "sos":

        if not text.startswith("@"):
            text = "@" + text

        set_setting("sos_username", text)

        context.user_data.clear()

        await update.message.reply_text(
            f"✅ SOS o‘zgartirildi: {text}"
        )

        return True

    # -----------------------------------------------------
    # BALANCE
    # -----------------------------------------------------

    if action == "balance":

        try:
            target_id = int(text)

            context.user_data["balance_user_id"] = target_id
            context.user_data["admin_action"] = "balance_amount"

            await update.message.reply_text(
                "💰 Endi summani yuboring."
            )

        except ValueError:

            await update.message.reply_text(
                "❌ Telegram ID noto‘g‘ri."
            )

        return True

    # -----------------------------------------------------
    # BALANCE AMOUNT
    # -----------------------------------------------------

    if action == "balance_amount":

        try:
            amount = float(text)

            user_id = context.user_data["balance_user_id"]
            mode = context.user_data["balance_mode"]

            if mode == "add":

                db_query("""
                    UPDATE users
                    SET balance = balance + %s
                    WHERE user_id = %s
                """, (
                    amount,
                    user_id
                ))

                message = (
                    f"✅ {money(amount)} so‘m qo‘shildi."
                )

            else:

                db_query("""
                    UPDATE users
                    SET balance = GREATEST(balance - %s, 0)
                    WHERE user_id = %s
                """, (
                    amount,
                    user_id
                ))

                message = (
                    f"✅ {money(amount)} so‘m ayrildi."
                )

            context.user_data.clear()

            await update.message.reply_text(
                message
            )

        except Exception:

            await update.message.reply_text(
                "❌ Summa noto‘g‘ri."
            )

        return True

    # -----------------------------------------------------
    # PRICE
    # -----------------------------------------------------

    if action == "price":

        key = context.user_data.get("price_key")

        if not key:

            if text not in DEFAULT_PRICES:

                await update.message.reply_text(
                    "❌ Noto‘g‘ri kalit."
                )
                return True

            context.user_data["price_key"] = text

            await update.message.reply_text(
                "💵 Endi yangi narxni so‘mda yuboring."
            )

            return True

        try:

            amount = int(text)

            set_setting(
                "price_" + key,
                amount
            )

            context.user_data.clear()

            await update.message.reply_text(
                f"✅ {key} narxi "
                f"{money(amount)} so‘m bo‘ldi."
            )

        except Exception:

            await update.message.reply_text(
                "❌ Narx noto‘g‘ri."
            )

        return True

    return False


# =========================================================
# API HELPERS
# =========================================================

def paystars_headers(api_key, idempotency=False):

    headers = {
        "X-API-Key": api_key,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    if idempotency:
        headers["Idempotency-Key"] = str(uuid.uuid4())

    return headers


def paystars_request(
    method,
    endpoint,
    api_key,
    data=None,
    idempotency=False
):

    url = PAYSTARS_API + endpoint

    headers = paystars_headers(
        api_key,
        idempotency
    )

    response = requests.request(
        method,
        url,
        headers=headers,
        json=data,
        timeout=30
    )

    if response.status_code >= 400:
        raise RuntimeError("API request failed")

    try:
        return response.json()
    except Exception:
        return {}


# =========================================================
# PAYSTARS USERNAME CHECK
# =========================================================

def check_paystars_username(
    api_key,
    username,
    kind
):

    return paystars_request(
        "POST",
        "/check-username",
        api_key,
        {
            "username": username,
            "kind": kind
        }
    )


# =========================================================
# PAYSTARS STARS BUY
# =========================================================

def buy_paystars_stars(
    api_key,
    username,
    quantity,
    verification_token
):

    return paystars_request(
        "POST",
        "/stars/buy",
        api_key,
        {
            "username": username,
            "quantity": quantity,
            "verification_token": verification_token
        },
        idempotency=True
    )


# =========================================================
# PAYSTARS PREMIUM BUY
# =========================================================

def buy_paystars_premium(
    api_key,
    username,
    months,
    verification_token
):

    return paystars_request(
        "POST",
        "/premium/buy",
        api_key,
        {
            "username": username,
            "months": months,
            "verification_token": verification_token
        },
        idempotency=True
    )


# =========================================================
# USER API MENU
# =========================================================

async def api_menu(update, context):

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "⭐ Stars",
                    callback_data="open_service:stars"
                ),
                InlineKeyboardButton(
                    "💎 Premium",
                    callback_data="open_service:premium"
                ),
            ],

            [
                InlineKeyboardButton(
                    "🎁 Donat",
                    callback_data="open_service:donat"
                ),
                InlineKeyboardButton(
                    "📱 SIM",
                    callback_data="open_service:sim"
                ),
            ],
        ]
    )

    await update.message.reply_text(
        "🤝 <b>Xizmatlar</b>\n\n"
        "Kerakli xizmatni tanlang:",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# GENERIC LOCAL PURCHASE
# =========================================================

async def local_purchase(
    update,
    context,
    service,
    days,
    price,
    plan
):

    user_id = update.effective_user.id

    user = get_user(user_id)

    if not user:
        return

    balance = float(user["balance"])

    if balance < price:

        await update.callback_query.answer(
            "❌ Balansingiz yetarli emas.",
            show_alert=True
        )

        return

    now = datetime.utcnow()
    expires = now + timedelta(days=days)

    db_query("""
        UPDATE users
        SET balance = balance - %s
        WHERE user_id = %s
    """, (
        price,
        user_id
    ))

    db_query("""
        INSERT INTO subscriptions(
            user_id,
            service,
            started_at,
            expires_at,
            source
        )
        VALUES(%s, %s, %s, %s, %s)
    """, (
        user_id,
        service,
        now,
        expires,
        "bot"
    ))

    db_query("""
        INSERT INTO orders(
            user_id,
            service,
            plan,
            price,
            status
        )
        VALUES(%s, %s, %s, %s, %s)
    """, (
        user_id,
        service,
        plan,
        price,
        "Bajarildi"
    ))

    await update.callback_query.edit_message_text(
        "✅ <b>Buyurtma muvaffaqiyatli bajarildi!</b>\n\n"
        f"Xizmat: {service}\n"
        f"Muddat: {days} kun\n"
        f"Narx: {money(price)} so‘m",
        parse_mode="HTML"
    )


# =========================================================
# BUY CALLBACK
# =========================================================

async def buy_callback(update, context):

    query = update.callback_query

    parts = query.data.split(":")

    if len(parts) != 3:
        return

    service = parts[1]
    days = int(parts[2])

    # -----------------------------------------------------
    # STARS
    # -----------------------------------------------------

    if service == "stars":

        quantity_map = {
            1: 50,
            7: 100,
            30: 250
        }

        quantity = quantity_map.get(days, 50)

        price_key = {
            50: "stars_50",
            100: "stars_100",
            250: "stars_250"
        }[quantity]

        price = get_price(price_key)

        await query.edit_message_text(
            "⭐ <b>Stars</b>\n\n"
            f"Stars: {quantity}\n"
            f"Narx: {money(price)} so‘m\n\n"
            "Bu qismda Telegram username kerak bo‘ladi.\n"
            "Masalan: @username",
            parse_mode="HTML"
        )

        context.user_data["purchase"] = {
            "type": "stars",
            "quantity": quantity,
            "price": price,
        }

        return

    # -----------------------------------------------------
    # PREMIUM
    # -----------------------------------------------------

    if service == "premium":

        months_map = {
            1: 3,
            7: 6,
            30: 12
        }

        months = months_map.get(days, 3)

        price = get_price(
            f"premium_{months}"
        )

        await query.edit_message_text(
            "💎 <b>Telegram Premium</b>\n\n"
            f"Muddat: {months} oy\n"
            f"Narx: {money(price)} so‘m\n\n"
            "Telegram usernameingizni yuboring.\n"
            "Masalan: @username",
            parse_mode="HTML"
        )

        context.user_data["purchase"] = {
            "type": "premium",
            "months": months,
            "price": price,
        }

        return

    # -----------------------------------------------------
    # DONAT
    # -----------------------------------------------------

    if service == "donat":

        price_key = {
            1: "donat_1",
            7: "donat_7",
            30: "donat_30"
        }.get(days, "donat_1")

        await query.edit_message_text(
            "🎁 <b>Donat</b>\n\n"
            f"Muddat: {days} kun\n"
            f"Narx: {money(get_price(price_key))} so‘m\n\n"
            "Donat API integratsiyasi uchun "
            "keyingi bosqichda o‘yin va paket tanlash qo‘shiladi.",
            parse_mode="HTML"
        )

        return

    # -----------------------------------------------------
    # SIM
    # -----------------------------------------------------

    if service == "sim":

        price_key = {
            1: "sim_1",
            7: "sim_7",
            30: "sim_30"
        }.get(days, "sim_1")

        await query.edit_message_text(
            "📱 <b>SIM</b>\n\n"
            f"Muddat: {days} kun\n"
            f"Narx: {money(get_price(price_key))} so‘m\n\n"
            "SIM API uchun buyurtma jarayoni "
            "keyingi bosqichda qo‘shiladi.",
            parse_mode="HTML"
        )


# =========================================================
# TRIAL
# =========================================================

async def trial_callback(update, context):

    query = update.callback_query

    service = query.data.split(":")[1]

    user_id = update.effective_user.id

    existing = get_active_subscription(
        user_id,
        service
    )

    if existing:

        await query.answer(
            "Sizda bu xizmat uchun faol obuna mavjud.",
            show_alert=True
        )

        return

    now = datetime.utcnow()

    expires = now + timedelta(days=1)

    db_query("""
        INSERT INTO subscriptions(
            user_id,
            service,
            started_at,
            expires_at,
            source
        )
        VALUES(%s, %s, %s, %s, %s)
    """, (
        user_id,
        service,
        now,
        expires,
        "trial"
    ))

    await query.edit_message_text(
        "🎁 <b>1 kunlik sinov aktivlashtirildi!</b>\n\n"
        f"Xizmat: {service}\n"
        f"Tugash: {expires}",
        parse_mode="HTML"
    )


# =========================================================
# USER TEXT HANDLER
# =========================================================

async def messages(update, context):

    if not update.message:
        return

    text = update.message.text.strip()

    # -----------------------------------------------------
    # ADMIN ACTION
    # -----------------------------------------------------

    if update.effective_user.id == ADMIN_ID:

        handled = await handle_admin_text(
            update,
            context
        )

        if handled:
            return

    # -----------------------------------------------------
    # MAIN MENU
    # -----------------------------------------------------

    if text == "💰 Balans":

        await balance(
            update,
            context
        )
        return

    if text == "📦 Obunalarim":

        await subscriptions(
            update,
            context
        )
        return

    if text == "🆘 SOS":

        await sos(
            update,
            context
        )
        return

    if text == "🤝 Hamkorlik (API)":

        await api_menu(
            update,
            context
        )
        return

    if text == "➕ Balans to'ldirish":

        card = get_setting("card")

        if not card:

            await update.message.reply_text(
                "❌ Karta hali sozlanmagan."
            )
            return

        await update.message.reply_text(
            "➕ <b>Balans to‘ldirish</b>\n\n"
            f"💳 Karta:\n<code>{card}</code>\n\n"
            "To‘lovni amalga oshirgach, "
            "chek rasmini yuboring.",
            parse_mode="HTML"
        )

        context.user_data["waiting_receipt"] = True

        return

    # -----------------------------------------------------
    # PURCHASE USERNAME
    # -----------------------------------------------------

    purchase = context.user_data.get("purchase")

    if purchase:

        username = text

        if not username.startswith("@"):

            username = "@" + username

        api_key = get_setting(
            "api_key_" + purchase["type"]
        )

        # Premium alohida API key
        if purchase["type"] == "premium":
            api_key = get_setting(
                "api_key_premium"
            )

        if not api_key:

            await update.message.reply_text(
                "❌ Xizmat hozircha mavjud emas."
            )

            context.user_data.clear()
            return

        try:

            kind = purchase["type"]

            check = check_paystars_username(
                api_key,
                username,
                kind
            )

            verification_token = (
                check.get("verification_token")
            )

            if not verification_token:

                await update.message.reply_text(
                    "❌ Username tekshirilmadi. "
                    "Qaytadan urinib ko‘ring."
                )

                return

            # ---------------------------------------------
            # STARS
            # ---------------------------------------------

            if kind == "stars":

                result = buy_paystars_stars(
                    api_key,
                    username,
                    purchase["quantity"],
                    verification_token
                )

                provider_order_id = (
                    result.get("order_id")
                    or result.get("id")
                    or ""
                )

            # ---------------------------------------------
            # PREMIUM
            # ---------------------------------------------

            else:

                result = buy_paystars_premium(
                    api_key,
                    username,
                    purchase["months"],
                    verification_token
                )

                provider_order_id = (
                    result.get("order_id")
                    or result.get("id")
                    or ""
                )

            price = purchase["price"]

            user = get_user(
                update.effective_user.id
            )

            if float(user["balance"]) < price:

                await update.message.reply_text(
                    "❌ Balansingiz yetarli emas."
                )

                context.user_data.clear()
                return

            db_query("""
                UPDATE users
                SET balance = balance - %s
                WHERE user_id = %s
            """, (
                price,
                update.effective_user.id
            ))

            db_query("""
                INSERT INTO orders(
                    user_id,
                    service,
                    plan,
                    price,
                    provider_order_id,
                    status
                )
                VALUES(%s, %s, %s, %s, %s, %s)
            """, (
                update.effective_user.id,
                kind,
                str(
                    purchase.get(
                        "quantity",
                        purchase.get("months", "")
                    )
                ),
                price,
                provider_order_id,
                "Kutilmoqda"
            ))

            await update.message.reply_text(
                "✅ <b>Buyurtma qabul qilindi!</b>\n\n"
                "Buyurtma tez orada bajariladi.\n"
                "Provider ma’lumotlari mijozga ko‘rsatilmaydi.",
                parse_mode="HTML",
                reply_markup=main_menu()
            )

            context.user_data.clear()

        except Exception as e:

            logger.exception(
                "PayStars error: %s",
                e
            )

            await update.message.reply_text(
                "❌ Hozircha buyurtmani bajarib bo‘lmadi. "
                "Birozdan keyin qayta urinib ko‘ring."
            )

        return


# =========================================================
# RECEIPT PHOTO
# =========================================================

async def receipt_photo(update, context):

    if not update.message:
        return

    if not context.user_data.get("waiting_receipt"):
        return

    photo = update.message.photo[-1]

    file_id = photo.file_id

    payment = db_query("""
        INSERT INTO payments(
            user_id,
            amount,
            status
        )
        VALUES(%s, %s, %s)
        RETURNING id
    """, (
        update.effective_user.id,
        0,
        "Kutilmoqda"
    ), fetchone=True)

    payment_id = payment["id"]

    context.user_data.clear()

    keyboard = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "✅ Tasdiqlash",
                    callback_data=f"payment:approve:{payment_id}"
                ),
                InlineKeyboardButton(
                    "❌ Rad etish",
                    callback_data=f"payment:reject:{payment_id}"
                ),
            ]
        ]
    )

    try:

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=(
                "💳 <b>Yangi to‘lov cheki</b>\n\n"
                f"👤 User ID: "
                f"<code>{update.effective_user.id}</code>\n"
                f"🧾 Payment ID: {payment_id}\n\n"
                "Summani tekshirib, tasdiqlang."
            ),
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except Exception as e:

        logger.exception(
            "Admin photo error: %s",
            e
        )

    await update.message.reply_text(
        "✅ Chek qabul qilindi.\n"
        "Admin tekshirganidan keyin balansingiz to‘ldiriladi.",
        reply_markup=main_menu()
    )


# =========================================================
# PAYMENT CALLBACK
# =========================================================

async def payment_callback(update, context):

    query = update.callback_query

    if update.effective_user.id != ADMIN_ID:
        await query.answer(
            "Ruxsat yo‘q.",
            show_alert=True
        )
        return

    parts = query.data.split(":")

    if len(parts) != 3:
        return

    action = parts[1]
    payment_id = int(parts[2])

    payment = db_query("""
        SELECT *
        FROM payments
        WHERE id = %s
    """, (
        payment_id,
    ), fetchone=True)

    if not payment:

        await query.answer(
            "To‘lov topilmadi.",
            show_alert=True
        )

        return

    if payment["status"] != "Kutilmoqda":

        await query.answer(
            "Bu to‘lov allaqachon ko‘rilgan.",
            show_alert=True
        )

        return

    if action == "reject":

        db_query("""
            UPDATE payments
            SET status = %s,
                admin_id = %s
            WHERE id = %s
        """, (
            "Rad etildi",
            ADMIN_ID,
            payment_id
        ))

        await query.edit_message_caption(
            caption="❌ To‘lov rad etildi."
        )

        return

    if action == "approve":

        context.user_data["admin_action"] = "payment_amount"
        context.user_data["payment_id"] = payment_id

        await query.message.reply_text(
            f"💰 Payment ID {payment_id}\n\n"
            "To‘lov summasini so‘mda yuboring."
        )

        await query.answer()


# =========================================================
# ADMIN ALL CALLBACKS
# =========================================================

async def admin_all_callbacks(update, context):

    query = update.callback_query

    data = query.data

    if update.effective_user.id != ADMIN_ID:

        await query.answer(
            "Ruxsat yo‘q.",
            show_alert=True
        )

        return

    await query.answer()

    # -----------------------------------------------------
    # ADMIN API
    # -----------------------------------------------------

    if data.startswith("admin_api:"):

        service = data.split(":")[1]

        await admin_api_menu(
            update,
            context,
            service
        )

        return

    # -----------------------------------------------------
    # ADMIN API EDIT
    # -----------------------------------------------------

    if data.startswith("admin_api_edit:"):

        service = data.split(":")[1]

        await admin_api_edit(
            update,
            context,
            service
        )

        return

    # -----------------------------------------------------
    # ADMIN BACK
    # -----------------------------------------------------

    if data == "admin_back":

        await admin_panel(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # CARD
    # -----------------------------------------------------

    if data == "admin_card":

        await admin_card(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # BALANCE ADD
    # -----------------------------------------------------

    if data == "admin_balance_add":

        await admin_balance_start(
            update,
            context,
            "add"
        )

        return

    # -----------------------------------------------------
    # BALANCE SUB
    # -----------------------------------------------------

    if data == "admin_balance_sub":

        await admin_balance_start(
            update,
            context,
            "sub"
        )

        return

    # -----------------------------------------------------
    # USERS
    # -----------------------------------------------------

    if data == "admin_users":

        await admin_users(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # STATS
    # -----------------------------------------------------

    if data == "admin_stats":

        await admin_stats(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # SUBS
    # -----------------------------------------------------

    if data == "admin_subs":

        await admin_subs(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # PAYMENTS
    # -----------------------------------------------------

    if data == "admin_payments":

        await admin_payments(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # PRICES
    # -----------------------------------------------------

    if data == "admin_prices":

        await admin_prices(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # PRICE EDIT
    # -----------------------------------------------------

    if data == "admin_price_edit":

        await admin_price_edit(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # SOS
    # -----------------------------------------------------

    if data == "admin_sos":

        await admin_sos(
            update,
            context
        )

        return


# =========================================================
# USER CALLBACKS
# =========================================================

async def user_callbacks(update, context):

    query = update.callback_query

    data = query.data

    await query.answer()

    # -----------------------------------------------------
    # OPEN SERVICE
    # -----------------------------------------------------

    if data.startswith("open_service:"):

        service = data.split(":")[1]

        await show_service(
            update,
            service
        )

        return

    # -----------------------------------------------------
    # BUY
    # -----------------------------------------------------

    if data.startswith("buy:"):

        await buy_callback(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # TRIAL
    # -----------------------------------------------------

    if data.startswith("trial:"):

        await trial_callback(
            update,
            context
        )

        return

    # -----------------------------------------------------
    # CLOSE
    # -----------------------------------------------------

    if data == "close":

        await query.edit_message_text(
            "⬅️ Menuga qaytdingiz."
        )

        return


# =========================================================
# ADMIN COMMAND
# =========================================================

async def admin_command(update, context):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "❌ Siz admin emassiz."
        )

        return

    await admin_panel(
        update,
        context
    )


# =========================================================
# HEALTH SERVER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-type",
            "text/plain"
        )

        self.end_headers()

        self.wfile.write(
            b"DONUZ BOT OK"
        )

    def log_message(self, format, *args):
        return


def start_health_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    server.serve_forever()


# =========================================================
# MAIN
# =========================================================

def main():

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN mavjud emas"
        )

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL mavjud emas"
        )

    init_database()

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # -----------------------------------------------------
    # COMMANDS
    # -----------------------------------------------------

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    application.add_handler(
        CommandHandler(
            "cancel",
            cancel
        )
    )

    # -----------------------------------------------------
    # PHOTO
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            receipt_photo
        )
    )

    # -----------------------------------------------------
    # CALLBACKS
    # -----------------------------------------------------

    application.add_handler(
        CallbackQueryHandler(
            admin_all_callbacks,
            pattern=r"^(admin_|payment:)"
        )
    )

    application.add_handler(
        CallbackQueryHandler(
            user_callbacks
        )
    )

    # -----------------------------------------------------
    # TEXT
    # -----------------------------------------------------

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            messages
        )
    )

    print("=" * 40)
    print("DONUZ BOT ISHGA TUSHDI")
    print("=" * 40)

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":
    main() 
