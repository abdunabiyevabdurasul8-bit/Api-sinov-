import os
import uuid
import logging
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from decimal import Decimal, InvalidOperation

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

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()

try:
    ADMIN_ID = int(os.getenv("ADMIN_ID", "0").strip())
except Exception:
    ADMIN_ID = 0

DATABASE_URL = os.getenv("DATABASE_URL", "").strip()

try:
    PORT = int(os.getenv("PORT", "10000"))
except Exception:
    PORT = 10000

SOS_USERNAME = os.getenv(
    "SOS_USERNAME",
    "@donuz1"
).strip()


# =========================================================
# API URLS
# =========================================================

PAYSTARS_API = "https://paystars.uz/api/v1"

PLAYPAY_API = "https://playpay.uz/api/v1"

AKTIVSIM_API = (
    "https://ws2524.wineclo.com/"
    "AktivSimBot/api/v2/"
)


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
# TIME
# =========================================================

def utc_now():
    return datetime.now(
        timezone.utc
    ).replace(
        tzinfo=None
    )


# =========================================================
# DATABASE CONNECTION
# =========================================================

def get_db():

    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL mavjud emas."
        )

    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=15,
    )


# =========================================================
# DATABASE QUERY
# =========================================================

def db_query(
    query,
    params=None,
    fetch=False,
    fetchone=False,
    returning=False,
):

    conn = get_db()

    try:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                query,
                params or ()
            )

            result = None

            if fetch:
                result = cur.fetchall()

            elif fetchone or returning:
                result = cur.fetchone()

            conn.commit()

            return result

    except Exception:

        conn.rollback()
        raise

    finally:

        conn.close()


# =========================================================
# SAFE COLUMN MIGRATION
# =========================================================

def add_column_if_missing(
    table,
    column,
    definition
):

    try:

        db_query(
            f"""
            ALTER TABLE {table}
            ADD COLUMN IF NOT EXISTS
            {column} {definition}
            """
        )

    except Exception as e:

        logger.error(
            "Migration failed: %s.%s -> %s",
            table,
            column,
            e
        )

        raise


# =========================================================
# DATABASE INIT
# =========================================================

def init_database():

    logger.info(
        "Database jadvallari tekshirilmoqda..."
    )

    # =====================================================
    # USERS
    # =====================================================

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

    # -----------------------------------------------------
    # IMPORTANT MIGRATION
    # Eski users jadvalida created_at bo‘lmasligi mumkin.
    # -----------------------------------------------------

    add_column_if_missing(
        "users",
        "username",
        "TEXT"
    )

    add_column_if_missing(
        "users",
        "first_name",
        "TEXT"
    )

    add_column_if_missing(
        "users",
        "balance",
        "NUMERIC DEFAULT 0"
    )

    add_column_if_missing(
        "users",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    )

    add_column_if_missing(
        "users",
        "last_seen",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    )

    # NULL bo‘lib qolgan eski qatorlarni to‘ldiramiz
    db_query("""
        UPDATE users
        SET created_at = CURRENT_TIMESTAMP
        WHERE created_at IS NULL
    """)

    db_query("""
        UPDATE users
        SET last_seen = CURRENT_TIMESTAMP
        WHERE last_seen IS NULL
    """)

    db_query("""
        UPDATE users
        SET balance = 0
        WHERE balance IS NULL
    """)

    # =====================================================
    # SUBSCRIPTIONS
    # =====================================================

    db_query("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            service TEXT NOT NULL,
            plan TEXT,
            started_at TIMESTAMP NOT NULL,
            expires_at TIMESTAMP NOT NULL,
            source TEXT DEFAULT 'bot'
        )
    """)

    add_column_if_missing(
        "subscriptions",
        "user_id",
        "BIGINT"
    )

    add_column_if_missing(
        "subscriptions",
        "service",
        "TEXT"
    )

    add_column_if_missing(
        "subscriptions",
        "plan",
        "TEXT"
    )

    add_column_if_missing(
        "subscriptions",
        "started_at",
        "TIMESTAMP"
    )

    add_column_if_missing(
        "subscriptions",
        "expires_at",
        "TIMESTAMP"
    )

    add_column_if_missing(
        "subscriptions",
        "source",
        "TEXT DEFAULT 'bot'"
    )

    # =====================================================
    # SETTINGS
    # =====================================================

    db_query("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    # =====================================================
    # ORDERS
    # =====================================================

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

    add_column_if_missing(
        "orders",
        "user_id",
        "BIGINT"
    )

    add_column_if_missing(
        "orders",
        "service",
        "TEXT"
    )

    add_column_if_missing(
        "orders",
        "plan",
        "TEXT"
    )

    add_column_if_missing(
        "orders",
        "price",
        "NUMERIC DEFAULT 0"
    )

    add_column_if_missing(
        "orders",
        "provider_order_id",
        "TEXT"
    )

    add_column_if_missing(
        "orders",
        "status",
        "TEXT DEFAULT 'Kutilmoqda'"
    )

    add_column_if_missing(
        "orders",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    )

    # =====================================================
    # PAYMENTS
    # =====================================================

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

    add_column_if_missing(
        "payments",
        "user_id",
        "BIGINT"
    )

    add_column_if_missing(
        "payments",
        "amount",
        "NUMERIC DEFAULT 0"
    )

    add_column_if_missing(
        "payments",
        "status",
        "TEXT DEFAULT 'Kutilmoqda'"
    )

    add_column_if_missing(
        "payments",
        "admin_id",
        "BIGINT"
    )

    add_column_if_missing(
        "payments",
        "created_at",
        "TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    )

    # =====================================================
    # SETTINGS DEFAULTS
    # =====================================================

    defaults = {

        "card": "",

        "sos_username": SOS_USERNAME,

        "api_key_stars": os.getenv(
            "PAYSTARS_STARS_API_KEY",
            ""
        ),

        "api_key_premium": os.getenv(
            "PAYSTARS_PREMIUM_API_KEY",
            ""
        ),

        "api_key_donat": os.getenv(
            "PLAYPAY_API_KEY",
            ""
        ),

        "api_key_sim": os.getenv(
            "AKTIVSIM_API_KEY",
            ""
        ),
    }

    for key, value in defaults.items():

        db_query("""
            INSERT INTO settings(
                key,
                value
            )
            VALUES(
                %s,
                %s
            )
            ON CONFLICT(key)
            DO NOTHING
        """, (
            key,
            value
        ))

    # =====================================================
    # PRICE DEFAULTS
    # =====================================================

    for key, value in DEFAULT_PRICES.items():

        db_query("""
            INSERT INTO settings(
                key,
                value
            )
            VALUES(
                %s,
                %s
            )
            ON CONFLICT(key)
            DO NOTHING
        """, (
            "price_" + key,
            str(value)
        ))

    logger.info(
        "Database migration/initialization tugadi."
    )


# =========================================================
# SETTINGS GET
# =========================================================

def get_setting(
    key,
    default=""
):

    row = db_query("""
        SELECT value
        FROM settings
        WHERE key = %s
    """, (
        key,
    ), fetchone=True)

    if not row:
        return default

    return row["value"]


# =========================================================
# SETTINGS SET
# =========================================================

def set_setting(
    key,
    value
):

    db_query("""
        INSERT INTO settings(
            key,
            value
        )
        VALUES(
            %s,
            %s
        )
        ON CONFLICT(key)
        DO UPDATE SET
            value = EXCLUDED.value
    """, (
        key,
        str(value)
    ))


# =========================================================
# PRICE
# =========================================================

def get_price(key):

    value = get_setting(
        "price_" + key,
        str(DEFAULT_PRICES.get(key, 0))
    )

    try:

        return int(
            Decimal(str(value))
        )

    except Exception:

        return 0


# =========================================================
# MONEY
# =========================================================

def money(value):

    try:

        return f"{int(Decimal(str(value))):,}".replace(
            ",",
            " "
        )

    except Exception:

        return "0"


# =========================================================
# USER SAVE
# =========================================================

def save_user(user):

    now = utc_now()

    db_query("""
        INSERT INTO users(
            user_id,
            username,
            first_name,
            balance,
            created_at,
            last_seen
        )
        VALUES(
            %s,
            %s,
            %s,
            0,
            %s,
            %s
        )
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
        now,
    ))


# =========================================================
# GET USER
# =========================================================

def get_user(user_id):

    return db_query("""
        SELECT *
        FROM users
        WHERE user_id = %s
    """, (
        user_id,
    ), fetchone=True)


# =========================================================
# ACTIVE SUBSCRIPTION
# =========================================================

def get_active_subscription(
    user_id,
    service
):

    now = utc_now()

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

    rows = []

    # -----------------------------------------------------
    # STARS
    # -----------------------------------------------------

    if service == "stars":

        rows.extend([

            [
                InlineKeyboardButton(
                    "⭐ 50 Stars",
                    callback_data="stars:50"
                ),
                InlineKeyboardButton(
                    "⭐ 100 Stars",
                    callback_data="stars:100"
                ),
            ],

            [
                InlineKeyboardButton(
                    "⭐ 250 Stars",
                    callback_data="stars:250"
                ),
                InlineKeyboardButton(
                    "⭐ 500 Stars",
                    callback_data="stars:500"
                ),
            ],
        ])

    # -----------------------------------------------------
    # PREMIUM
    # -----------------------------------------------------

    elif service == "premium":

        rows.extend([

            [
                InlineKeyboardButton(
                    "💎 3 oy",
                    callback_data="premium:3"
                ),
                InlineKeyboardButton(
                    "💎 6 oy",
                    callback_data="premium:6"
                ),
            ],

            [
                InlineKeyboardButton(
                    "💎 12 oy",
                    callback_data="premium:12"
                ),
            ],
        ])

    # -----------------------------------------------------
    # DONAT / SIM
    # -----------------------------------------------------

    else:

        rows.extend([

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
        ])

    # -----------------------------------------------------
    # TRIAL
    # -----------------------------------------------------

    rows.append([

        InlineKeyboardButton(
            "🎁 1 kun bepul sinov",
            callback_data=f"trial:{service}"
        )

    ])

    # -----------------------------------------------------
    # BACK
    # -----------------------------------------------------

    rows.append([

        InlineKeyboardButton(
            "⬅️ Orqaga",
            callback_data="close"
        )

    ])

    return InlineKeyboardMarkup(rows)


# =========================================================
# START
# =========================================================

async def start(
    update,
    context
):

    if not update.effective_user:
        return

    try:

        save_user(
            update.effective_user
        )

    except Exception as e:

        logger.exception(
            "save_user error: %s",
            e
        )

        if update.message:

            await update.message.reply_text(
                "❌ Bot bazasida vaqtinchalik xatolik yuz berdi."
            )

        return

    context.user_data.clear()

    text = (
        "👋 <b>DONUZ BOT</b>\n\n"
        "Kerakli bo‘limni tanlang:"
    )

    if update.message:

        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=main_menu()
        )


# =========================================================
# BALANCE
# =========================================================

async def balance(
    update,
    context
):

    user = get_user(
        update.effective_user.id
    )

    value = (
        user["balance"]
        if user
        else 0
    )

    await update.message.reply_text(
        "💰 <b>Balansingiz:</b>\n\n"
        f"{money(value)} so‘m",
        parse_mode="HTML"
    )


# =========================================================
# SUBSCRIPTIONS
# =========================================================

async def subscriptions(
    update,
    context
):

    rows = db_query("""
        SELECT *
        FROM subscriptions
        WHERE user_id = %s
        ORDER BY expires_at DESC
        LIMIT 30
    """, (
        update.effective_user.id,
    ), fetch=True)

    if not rows:

        await update.message.reply_text(
            "📦 Sizda hozircha obuna yo‘q."
        )

        return

    names = {

        "stars": "⭐ Stars",

        "premium": "💎 Premium",

        "donat": "🎁 Donat",

        "sim": "📱 SIM",
    }

    text = "📦 <b>Obunalarim</b>\n\n"

    for row in rows:

        service = row["service"]

        service_name = names.get(
            service,
            service
        )

        text += (
            f"• <b>{service_name}</b>\n"
            f"  Plan: {row.get('plan') or '-'}\n"
            f"  Boshlangan: {row['started_at']}\n"
            f"  Tugaydi: {row['expires_at']}\n"
            f"  Manba: {row.get('source') or 'bot'}\n\n"
        )

    await update.message.reply_text(
        text,
        parse_mode="HTML"
    )


# =========================================================
# SOS
# =========================================================

async def sos(
    update,
    context
):

    username = get_setting(
        "sos_username",
        SOS_USERNAME
    ).strip()

    clean_username = username.lstrip("@")

    if not clean_username:

        await update.message.reply_text(
            "❌ Operator sozlanmagan."
        )

        return

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "🆘 Operator bilan bog‘lanish",
                url=f"https://t.me/{clean_username}"
            )
        ]

    ])

    await update.message.reply_text(
        "🆘 <b>Yordam kerakmi?</b>\n\n"
        "Operator bilan bog‘lanish uchun "
        "quyidagi tugmani bosing.",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# MASK API KEY
# =========================================================

def mask_api_key(key):

    if not key:
        return "❌ Kiritilmagan"

    if len(key) <= 8:
        return "••••••••"

    return (
        key[:4]
        + "••••••••"
        + key[-4:]
    )


# =========================================================
# ADMIN MENU
# =========================================================

def admin_menu():

    return InlineKeyboardMarkup([

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

    ])


# =========================================================
# ADMIN PANEL
# =========================================================

async def admin_panel(
    update,
    context
):

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

    elif update.message:

        await update.message.reply_text(
            text,
            parse_mode="HTML",
            reply_markup=admin_menu()
        )


# =========================================================
# ADMIN API MENU
# =========================================================

async def admin_api_menu(
    update,
    context,
    service
):

    query = update.callback_query

    if update.effective_user.id != ADMIN_ID:

        await query.answer(
            "Ruxsat yo‘q.",
            show_alert=True
        )

        return

    info = API_SETTINGS.get(
        service
    )

    if not info:
        return

    key = get_setting(
        info["setting"]
    )

    if service in (
        "stars",
        "premium"
    ):

        api_url = PAYSTARS_API

    elif service == "donat":

        api_url = PLAYPAY_API

    else:

        api_url = AKTIVSIM_API

    text = (
        f"<b>{info['name']}</b>\n\n"
        f"API manzil:\n"
        f"<code>{api_url}</code>\n\n"
        f"🔑 API key:\n"
        f"<code>{mask_api_key(key)}</code>\n\n"
        "API keyni almashtirish uchun "
        "quyidagi tugmani bosing."
    )

    keyboard = InlineKeyboardMarkup([

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

    ])

    await query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN API EDIT
# =========================================================

async def admin_api_edit(
    update,
    context,
    service
):

    if update.effective_user.id != ADMIN_ID:
        return

    if service not in API_SETTINGS:
        return

    context.user_data.clear()

    context.user_data[
        "admin_action"
    ] = "api_key"

    context.user_data[
        "api_service"
    ] = service

    name = API_SETTINGS[
        service
    ]["name"]

    await update.callback_query.edit_message_text(
        f"{name}\n\n"
        "🔑 Yangi API keyni yuboring.\n\n"
        "Bekor qilish: /cancel"
    )


# =========================================================
# ADMIN CARD
# =========================================================

async def admin_card(
    update,
    context
):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.clear()

    context.user_data[
        "admin_action"
    ] = "card"

    card = get_setting(
        "card"
    )

    await update.callback_query.edit_message_text(
        "💳 <b>Karta</b>\n\n"
        f"Joriy karta:\n"
        f"<code>{card or 'Kiritilmagan'}</code>\n\n"
        "Yangi karta raqamini yoki to‘lov "
        "ma'lumotini yuboring.",
        parse_mode="HTML"
    )


# =========================================================
# ADMIN BALANCE START
# =========================================================

async def admin_balance_start(
    update,
    context,
    mode
):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.clear()

    context.user_data[
        "admin_action"
    ] = "balance"

    context.user_data[
        "balance_mode"
    ] = mode

    await update.callback_query.edit_message_text(
        "👤 Foydalanuvchining Telegram ID sini yuboring.\n\n"
        "Bekor qilish: /cancel"
    )


# =========================================================
# ADMIN PRICES
# =========================================================

async def admin_prices(
    update,
    context
):

    if update.effective_user.id != ADMIN_ID:
        return

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

    text = "💵 <b>Narxlar</b>\n\n"

    for key, label in labels.items():

        text += (
            f"{label}: "
            f"<b>{money(get_price(key))} so‘m</b>\n"
        )

    keyboard = InlineKeyboardMarkup([

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

    ])

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN PRICE EDIT
# =========================================================

async def admin_price_edit(
    update,
    context
):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.clear()

    context.user_data[
        "admin_action"
    ] = "price"

    keys = "\n".join(
        DEFAULT_PRICES.keys()
    )

    await update.callback_query.edit_message_text(
        "✏️ <b>Narx o‘zgartirish</b>\n\n"
        "Quyidagi kalitlardan birini yuboring:\n\n"
        f"<code>{keys}</code>\n\n"
        "Masalan:\n"
        "<code>stars_50</code>\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML"
    )


# =========================================================
# ADMIN USERS
# =========================================================

async def admin_users(
    update,
    context
):

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
        ORDER BY created_at DESC NULLS LAST
        LIMIT 50
    """, fetch=True)

    if not rows:

        text = "👥 Foydalanuvchilar yo‘q."

    else:

        text = "👥 <b>Foydalanuvchilar</b>\n\n"

        for row in rows:

            if row["username"]:

                username = (
                    "@"
                    + str(
                        row["username"]
                    ).lstrip("@")
                )

            else:

                username = "username yo‘q"

            text += (
                f"🆔 <code>{row['user_id']}</code>\n"
                f"👤 {username}\n"
                f"📅 Qo‘shilgan: "
                f"{row['created_at']}\n"
                f"💰 Balans: "
                f"{money(row['balance'])} so‘m\n"
                f"──────────────\n"
            )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "⬅️ Admin panel",
                callback_data="admin_back"
            )
        ]

    ])

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN STATS
# =========================================================

async def admin_stats(
    update,
    context
):

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

    subscriptions_count = db_query("""
        SELECT COUNT(*) AS count
        FROM subscriptions
    """, fetchone=True)

    payments = db_query("""
        SELECT COUNT(*) AS count
        FROM payments
    """, fetchone=True)

    total_balance = db_query("""
        SELECT COALESCE(
            SUM(balance),
            0
        ) AS total
        FROM users
    """, fetchone=True)

    text = (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Foydalanuvchilar: "
        f"{users['count']}\n"
        f"📦 Buyurtmalar: "
        f"{orders['count']}\n"
        f"📋 Obunalar: "
        f"{subscriptions_count['count']}\n"
        f"💳 To‘lovlar: "
        f"{payments['count']}\n"
        f"💰 Jami balans: "
        f"{money(total_balance['total'])} so‘m"
    )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "⬅️ Admin panel",
                callback_data="admin_back"
            )
        ]

    ])

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN SUBSCRIPTIONS
# =========================================================

async def admin_subs(
    update,
    context
):

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
                f"ID: <code>{row['id']}</code>\n"
                f"User: <code>{row['user_id']}</code>\n"
                f"Xizmat: {row['service']}\n"
                f"Plan: {row.get('plan') or '-'}\n"
                f"Tugash: {row['expires_at']}\n"
                f"Manba: {row.get('source') or 'bot'}\n"
                f"────────────\n"
            )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "⬅️ Admin panel",
                callback_data="admin_back"
            )
        ]

    ])

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN PAYMENTS
# =========================================================

async def admin_payments(
    update,
    context
):

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
                f"ID: <code>{row['id']}</code>\n"
                f"User: <code>{row['user_id']}</code>\n"
                f"Summa: "
                f"{money(row['amount'])} so‘m\n"
                f"Holat: {row['status']}\n"
                f"────────────\n"
            )

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "⬅️ Admin panel",
                callback_data="admin_back"
            )
        ]

    ])

    await update.callback_query.edit_message_text(
        text,
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# ADMIN SOS
# =========================================================

async def admin_sos(
    update,
    context
):

    if update.effective_user.id != ADMIN_ID:
        return

    context.user_data.clear()

    context.user_data[
        "admin_action"
    ] = "sos"

    current = get_setting(
        "sos_username",
        SOS_USERNAME
    )

    await update.callback_query.edit_message_text(
        "🆘 <b>SOS sozlamasi</b>\n\n"
        f"Joriy: <code>{current}</code>\n\n"
        "Yangi Telegram username yuboring.\n"
        "Masalan: <code>@donuz1</code>\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML"
    )


# =========================================================
# ADMIN TEXT HANDLER
# =========================================================

async def handle_admin_text(
    update,
    context
):

    if update.effective_user.id != ADMIN_ID:
        return False

    if not update.message:
        return False

    action = context.user_data.get(
        "admin_action"
    )

    if not action:
        return False

    text = (
        update.message.text or ""
    ).strip()

    # =====================================================
    # API KEY
    # =====================================================

    if action == "api_key":

        service = context.user_data.get(
            "api_service"
        )

        if service not in API_SETTINGS:

            context.user_data.clear()

            await update.message.reply_text(
                "❌ Xizmat topilmadi."
            )

            return True

        if not text:

            await update.message.reply_text(
                "❌ API key bo‘sh bo‘lishi mumkin emas."
            )

            return True

        setting = API_SETTINGS[
            service
        ]["setting"]

        set_setting(
            setting,
            text
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ API key muvaffaqiyatli saqlandi.",
            reply_markup=main_menu()
        )

        return True

    # =====================================================
    # CARD
    # =====================================================

    if action == "card":

        if not text:

            await update.message.reply_text(
                "❌ Karta ma'lumotini kiriting."
            )

            return True

        set_setting(
            "card",
            text
        )

        context.user_data.clear()

        await update.message.reply_text(
            "✅ Karta ma'lumoti saqlandi."
        )

        return True

    # =====================================================
    # SOS
    # =====================================================

    if action == "sos":

        if not text:

            await update.message.reply_text(
                "❌ Username kiriting."
            )

            return True

        if not text.startswith("@"):

            text = "@" + text

        set_setting(
            "sos_username",
            text
        )

        context.user_data.clear()

        await update.message.reply_text(
            f"✅ SOS o‘zgartirildi: {text}"
        )

        return True

    # =====================================================
    # BALANCE USER ID
    # =====================================================

    if action == "balance":

        try:

            target_id = int(text)

        except Exception:

            await update.message.reply_text(
                "❌ Telegram ID noto‘g‘ri."
            )

            return True

        user = get_user(
            target_id
        )

        if not user:

            await update.message.reply_text(
                "❌ Bu ID bilan foydalanuvchi "
                "topilmadi."
            )

            return True

        context.user_data[
            "balance_user_id"
        ] = target_id

        context.user_data[
            "admin_action"
        ] = "balance_amount"

        await update.message.reply_text(
            "💰 Endi summani yuboring.\n\n"
            "Masalan: 10000\n\n"
            "Bekor qilish: /cancel"
        )

        return True

    # =====================================================
    # BALANCE AMOUNT
    # =====================================================

    if action == "balance_amount":

        try:

            amount = Decimal(
                text.replace(" ", "")
            )

            if amount <= 0:
                raise ValueError

        except Exception:

            await update.message.reply_text(
                "❌ Summa noto‘g‘ri."
            )

            return True

        user_id = context.user_data.get(
            "balance_user_id"
        )

        mode = context.user_data.get(
            "balance_mode"
        )

        if not user_id or mode not in (
            "add",
            "sub"
        ):

            context.user_data.clear()

            await update.message.reply_text(
                "❌ Amal ma'lumotlari topilmadi."
            )

            return True

        user = get_user(
            user_id
        )

        if not user:

            context.user_data.clear()

            await update.message.reply_text(
                "❌ Foydalanuvchi topilmadi."
            )

            return True

        try:

            if mode == "add":

                db_query("""
                    UPDATE users
                    SET balance = balance + %s
                    WHERE user_id = %s
                """, (
                    amount,
                    user_id
                ))

                action_text = (
                    f"✅ {money(amount)} so‘m "
                    "qo‘shildi."
                )

            else:

                db_query("""
                    UPDATE users
                    SET balance =
                        GREATEST(
                            balance - %s,
                            0
                        )
                    WHERE user_id = %s
                """, (
                    amount,
                    user_id
                ))

                action_text = (
                    f"✅ {money(amount)} so‘m "
                    "ayirildi."
                )

            new_user = get_user(
                user_id
            )

            new_balance = (
                new_user["balance"]
                if new_user
                else 0
            )

            context.user_data.clear()

            await update.message.reply_text(
                action_text
                + "\n\n"
                + "User ID: "
                + str(user_id)
                + "\n"
                + "Yangi balans: "
                + money(new_balance)
                + " so‘m"
            )

            # USERGA XABAR
            try:

                if mode == "add":

                    await context.bot.send_message(
                        chat_id=user_id,
                        text=(
                            "💰 <b>Balansingiz to‘ldirildi.</b>\n\n"
                            f"Qo‘shildi: "
                            f"{money(amount)} so‘m\n"
                            f"Joriy balans: "
                            f"{money(new_balance)} so‘m"
                        ),
                        parse_mode="HTML"
                    )

                else:

                    await context.bot.send_message(
                        chat_id=user_id,
                        text=(
                            "💸 <b>Balansingizdan mablag‘ ayrildi.</b>\n\n"
                            f"Ayirildi: "
                            f"{money(amount)} so‘m\n"
                            f"Joriy balans: "
                            f"{money(new_balance)} so‘m"
                        ),
                        parse_mode="HTML"
                    )

            except Exception as e:

                logger.warning(
                    "Balance user notify error: %s",
                    e
                )

        except Exception as e:

            logger.exception(
                "Balance update error: %s",
                e
            )

            await update.message.reply_text(
                "❌ Balansni o‘zgartirishda xatolik."
            )

        return True

    # =====================================================
    # PRICE
    # =====================================================

    if action == "price":

        price_key = context.user_data.get(
            "price_key"
        )

        # -------------------------------------------------
        # KEY
        # -------------------------------------------------

        if not price_key:

            if text not in DEFAULT_PRICES:

                await update.message.reply_text(
                    "❌ Noto‘g‘ri kalit.\n\n"
                    "Masalan: stars_50"
                )

                return True

            context.user_data[
                "price_key"
            ] = text

            await update.message.reply_text(
                f"💵 {text}\n\n"
                "Endi yangi narxni so‘mda yuboring.\n\n"
                "Masalan: 15000\n\n"
                "Bekor qilish: /cancel"
            )

            return True

        # -------------------------------------------------
        # PRICE
        # -------------------------------------------------

        try:

            amount = int(
                text.replace(" ", "")
            )

            if amount < 0:
                raise ValueError

        except Exception:

            await update.message.reply_text(
                "❌ Narx noto‘g‘ri."
            )

            return True

        set_setting(
            "price_" + price_key,
            amount
        )

        context.user_data.clear()

        await update.message.reply_text(
            f"✅ {price_key} narxi "
            f"{money(amount)} so‘m bo‘ldi."
        )

        return True

    # =====================================================
    # PAYMENT AMOUNT
    # =====================================================

    if action == "payment_amount":

        payment_id = context.user_data.get(
            "payment_id"
        )

        if not payment_id:

            context.user_data.clear()

            await update.message.reply_text(
                "❌ To‘lov ma'lumoti topilmadi."
            )

            return True

        try:

            amount = Decimal(
                text.replace(" ", "")
            )

            if amount <= 0:
                raise ValueError

        except Exception:

            await update.message.reply_text(
                "❌ Summa noto‘g‘ri."
            )

            return True

        try:

            # -------------------------------------------------
            # PAYMENTNI TRANZAKSIYADA TASDIQLASH
            # -------------------------------------------------

            conn = get_db()

            try:

                with conn.cursor(
                    cursor_factory=RealDictCursor
                ) as cur:

                    cur.execute("""
                        SELECT *
                        FROM payments
                        WHERE id = %s
                        FOR UPDATE
                    """, (
                        payment_id,
                    ))

                    payment = cur.fetchone()

                    if not payment:

                        conn.rollback()

                        context.user_data.clear()

                        await update.message.reply_text(
                            "❌ To‘lov topilmadi."
                        )

                        return True

                    if payment["status"] != "Kutilmoqda":

                        conn.rollback()

                        context.user_data.clear()

                        await update.message.reply_text(
                            "❌ Bu to‘lov allaqachon "
                            "ko‘rib chiqilgan."
                        )

                        return True

                    cur.execute("""
                        UPDATE payments
                        SET amount = %s,
                            status = %s,
                            admin_id = %s
                        WHERE id = %s
                    """, (
                        amount,
                        "Tasdiqlandi",
                        ADMIN_ID,
                        payment_id
                    ))

                    cur.execute("""
                        UPDATE users
                        SET balance = balance + %s
                        WHERE user_id = %s
                    """, (
                        amount,
                        payment["user_id"]
                    ))

                    cur.execute("""
                        SELECT balance
                        FROM users
                        WHERE user_id = %s
                    """, (
                        payment["user_id"],
                    ))

                    updated_user = cur.fetchone()

                    conn.commit()

            except Exception:

                conn.rollback()
                raise

            finally:

                conn.close()

            context.user_data.clear()

            new_balance = (
                updated_user["balance"]
                if updated_user
                else 0
            )

            await update.message.reply_text(
                "✅ <b>To‘lov tasdiqlandi.</b>\n\n"
                f"User ID: "
                f"<code>{payment['user_id']}</code>\n"
                f"Payment ID: "
                f"<code>{payment_id}</code>\n"
                f"Summa: "
                f"{money(amount)} so‘m\n"
                f"Yangi balans: "
                f"{money(new_balance)} so‘m",
                parse_mode="HTML"
            )

            # USERGA XABAR
            try:

                await context.bot.send_message(
                    chat_id=payment["user_id"],
                    text=(
                        "✅ <b>Balansingiz to‘ldirildi!</b>\n\n"
                        f"Qo‘shildi: "
                        f"{money(amount)} so‘m\n"
                        f"Joriy balans: "
                        f"{money(new_balance)} so‘m"
                    ),
                    parse_mode="HTML"
                )

            except Exception as e:

                logger.warning(
                    "Payment user message error: %s",
                    e
                )

        except Exception as e:

            logger.exception(
                "Payment approve error: %s",
                e
            )

            await update.message.reply_text(
                "❌ To‘lovni tasdiqlashda xatolik."
            )

        return True

    return False


# =========================================================
# CANCEL
# =========================================================

async def cancel(
    update,
    context
):

    context.user_data.clear()

    await update.message.reply_text(
        "❌ Amal bekor qilindi.",
        reply_markup=main_menu()
    )


# =========================================================
# PAYSTARS HEADERS
# =========================================================

def paystars_headers(
    api_key,
    idempotency=False
):

    headers = {

        "X-API-Key": api_key,

        "Content-Type": "application/json",

        "Accept": "application/json",
    }

    if idempotency:

        headers[
            "Idempotency-Key"
        ] = str(uuid.uuid4())

    return headers


# =========================================================
# PAYSTARS REQUEST
# =========================================================

def paystars_request(
    method,
    endpoint,
    api_key,
    data=None,
    idempotency=False
):

    if not api_key:

        raise RuntimeError(
            "API key mavjud emas."
        )

    url = (
        PAYSTARS_API.rstrip("/")
        + "/"
        + endpoint.lstrip("/")
    )

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

        logger.error(
            "PayStars HTTP %s: %s",
            response.status_code,
            response.text[:500]
        )

        raise RuntimeError(
            "Provider request failed."
        )

    try:

        return response.json()

    except Exception:

        return {}


# =========================================================
# CHECK USERNAME
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
# BUY STARS
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
# BUY PREMIUM
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

async def api_menu(
    update,
    context
):

    keyboard = InlineKeyboardMarkup([

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

        [
            InlineKeyboardButton(
                "🆘 SOS",
                callback_data="user_sos"
            )
        ],

    ])

    await update.message.reply_text(
        "🤝 <b>Xizmatlar</b>\n\n"
        "Kerakli xizmatni tanlang:",
        parse_mode="HTML",
        reply_markup=keyboard
    )


# =========================================================
# SHOW SERVICE
# =========================================================

async def show_service(
    update,
    service
):

    query = update.callback_query

    names = {

        "stars": "⭐ Stars",

        "premium": "💎 Premium",

        "donat": "🎁 Donat",

        "sim": "📱 SIM",
    }

    name = names.get(
        service,
        service
    )

    await query.edit_message_text(
        f"<b>{name}</b>\n\n"
        "Kerakli paketni tanlang:",
        parse_mode="HTML",
        reply_markup=service_menu(service)
    )


# =========================================================
# USER HAS BALANCE
# =========================================================

def user_has_balance(
    user_id,
    price
):

    user = get_user(
        user_id
    )

    if not user:
        return False

    try:

        return Decimal(
            str(user["balance"])
        ) >= Decimal(
            str(price)
        )

    except Exception:

        return False


# =========================================================
# LOCAL PURCHASE
# =========================================================

async def local_purchase(
    update,
    context,
    service,
    days,
    price,
    plan
):

    query = update.callback_query

    user_id = update.effective_user.id

    try:

        price_decimal = Decimal(
            str(price)
        )

        if price_decimal < 0:
            raise ValueError

    except Exception:

        await query.answer(
            "Narx xatosi.",
            show_alert=True
        )

        return

    # -----------------------------------------------------
    # TRANSACTION
    # -----------------------------------------------------

    conn = get_db()

    try:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute("""
                SELECT balance
                FROM users
                WHERE user_id = %s
                FOR UPDATE
            """, (
                user_id,
            ))

            user = cur.fetchone()

            if not user:

                conn.rollback()

                await query.answer(
                    "Foydalanuvchi topilmadi.",
                    show_alert=True
                )

                return

            balance_value = Decimal(
                str(user["balance"])
            )

            if balance_value < price_decimal:

                conn.rollback()

                await query.answer(
                    "❌ Balansingiz yetarli emas.",
                    show_alert=True
                )

                return

            now = utc_now()

            expires = (
                now
                + timedelta(days=days)
            )

            cur.execute("""
                UPDATE users
                SET balance = balance - %s
                WHERE user_id = %s
            """, (
                price_decimal,
                user_id
            ))

            cur.execute("""
                INSERT INTO subscriptions(
                    user_id,
                    service,
                    plan,
                    started_at,
                    expires_at,
                    source
                )
                VALUES(
                    %s,
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
            """, (
                user_id,
                service,
                plan,
                now,
                expires,
                "bot"
            ))

            cur.execute("""
                INSERT INTO orders(
                    user_id,
                    service,
                    plan,
                    price,
                    status
                )
                VALUES(
                    %s,
                    %s,
                    %s,
                    %s,
                    %s
                )
            """, (
                user_id,
                service,
                plan,
                price_decimal,
                "Bajarildi"
            ))

            conn.commit()

    except Exception as e:

        conn.rollback()

        logger.exception(
            "Local purchase error: %s",
            e
        )

        await query.answer(
            "❌ Buyurtmani bajarishda xatolik.",
            show_alert=True
        )

        return

    finally:

        conn.close()

    await query.edit_message_text(
        "✅ <b>Buyurtma muvaffaqiyatli bajarildi!</b>\n\n"
        f"Xizmat: {service}\n"
        f"Muddat: {days} kun\n"
        f"Narx: {money(price)} so‘m\n"
        f"Tugash: {expires}",
        parse_mode="HTML"
    )


# =========================================================
# STARS CALLBACK
# =========================================================

async def stars_callback(
    update,
    context
):

    query = update.callback_query

    try:

        quantity = int(
            query.data.split(":")[1]
        )

    except Exception:

        await query.answer(
            "Noto‘g‘ri paket.",
            show_alert=True
        )

        return

    if quantity not in (
        50,
        100,
        250,
        500
    ):

        await query.answer(
            "Paket topilmadi.",
            show_alert=True
        )

        return

    price = get_price(
        f"stars_{quantity}"
    )

    user_id = update.effective_user.id

    user = get_user(
        user_id
    )

    if not user:

        return

    if Decimal(
        str(user["balance"])
    ) < Decimal(
        str(price)
    ):

        await query.answer(
            "❌ Balansingiz yetarli emas.",
            show_alert=True
        )

        return

    context.user_data[
        "purchase"
    ] = {

        "type": "stars",

        "quantity": quantity,

        "price": price,
    }

    await query.edit_message_text(
        "⭐ <b>Telegram Stars</b>\n\n"
        f"Stars: <b>{quantity}</b>\n"
        f"Narx: <b>{money(price)} so‘m</b>\n\n"
        "Telegram usernameingizni yuboring.\n\n"
        "Masalan:\n"
        "<code>@username</code>\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML"
    )


# =========================================================
# PREMIUM CALLBACK
# =========================================================

async def premium_callback(
    update,
    context
):

    query = update.callback_query

    try:

        months = int(
            query.data.split(":")[1]
        )

    except Exception:

        await query.answer(
            "Noto‘g‘ri paket.",
            show_alert=True
        )

        return

    if months not in (
        3,
        6,
        12
    ):

        await query.answer(
            "Paket topilmadi.",
            show_alert=True
        )

        return

    price = get_price(
        f"premium_{months}"
    )

    user_id = update.effective_user.id

    user = get_user(
        user_id
    )

    if not user:
        return

    if Decimal(
        str(user["balance"])
    ) < Decimal(
        str(price)
    ):

        await query.answer(
            "❌ Balansingiz yetarli emas.",
            show_alert=True
        )

        return

    context.user_data[
        "purchase"
    ] = {

        "type": "premium",

        "months": months,

        "price": price,
    }

    await query.edit_message_text(
        "💎 <b>Telegram Premium</b>\n\n"
        f"Muddat: <b>{months} oy</b>\n"
        f"Narx: <b>{money(price)} so‘m</b>\n\n"
        "Telegram usernameingizni yuboring.\n\n"
        "Masalan:\n"
        "<code>@username</code>\n\n"
        "Bekor qilish: /cancel",
        parse_mode="HTML"
    )


# =========================================================
# GENERIC BUY CALLBACK
# =========================================================

async def buy_callback(
    update,
    context
):

    query = update.callback_query

    parts = query.data.split(":")

    if len(parts) != 3:
        return

    service = parts[1]

    try:

        days = int(
            parts[2]
        )

    except Exception:

        return

    if service == "donat":

        price_key = {

            1: "donat_1",

            7: "donat_7",

            30: "donat_30",

        }.get(days)

        if not price_key:
            return

        price = get_price(
            price_key
        )

        # Bu qism hozircha ichki
        # obuna tizimi orqali ishlaydi.
        await local_purchase(
            update,
            context,
            "donat",
            days,
            price,
            f"{days} kun"
        )

        return

    if service == "sim":

        price_key = {

            1: "sim_1",

            7: "sim_7",

            30: "sim_30",

        }.get(days)

        if not price_key:
            return

        price = get_price(
            price_key
        )

        await local_purchase(
            update,
            context,
            "sim",
            days,
            price,
            f"{days} kun"
        )

        return


# =========================================================
# TRIAL
# =========================================================

async def trial_callback(
    update,
    context
):

    query = update.callback_query

    parts = query.data.split(":")

    if len(parts) != 2:
        return

    service = parts[1]

    if service not in (
        "stars",
        "premium",
        "donat",
        "sim"
    ):

        await query.answer(
            "Xizmat topilmadi.",
            show_alert=True
        )

        return

    user_id = update.effective_user.id

    # -----------------------------------------------------
    # ACTIVE
    # -----------------------------------------------------

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

    # -----------------------------------------------------
    # OLD TRIAL
    # -----------------------------------------------------

    old_trial = db_query("""
        SELECT id
        FROM subscriptions
        WHERE user_id = %s
          AND service = %s
          AND source = 'trial'
        LIMIT 1
    """, (
        user_id,
        service
    ), fetchone=True)

    if old_trial:

        await query.answer(
            "🎁 Siz bu xizmat uchun sinov muddatidan "
            "avval foydalangansiz.",
            show_alert=True
        )

        return

    # -----------------------------------------------------
    # CREATE TRIAL
    # -----------------------------------------------------

    now = utc_now()

    expires = (
        now
        + timedelta(days=1)
    )

    try:

        db_query("""
            INSERT INTO subscriptions(
                user_id,
                service,
                plan,
                started_at,
                expires_at,
                source
            )
            VALUES(
                %s,
                %s,
                %s,
                %s,
                %s,
                %s
            )
        """, (
            user_id,
            service,
            "1 kunlik sinov",
            now,
            expires,
            "trial"
        ))

        db_query("""
            INSERT INTO orders(
                user_id,
                service,
                plan,
                price,
                status
            )
            VALUES(
                %s,
                %s,
                %s,
                %s,
                %s
            )
        """, (
            user_id,
            service,
            "1 kunlik sinov",
            0,
            "Bajarildi"
        ))

    except Exception as e:

        logger.exception(
            "Trial error: %s",
            e
        )

        await query.answer(
            "❌ Sinovni aktivlashtirishda xatolik.",
            show_alert=True
        )

        return

    names = {

        "stars": "⭐ Stars",

        "premium": "💎 Premium",

        "donat": "🎁 Donat",

        "sim": "📱 SIM",
    }

    await query.edit_message_text(
        "🎁 <b>1 kunlik bepul sinov aktivlashtirildi!</b>\n\n"
        f"Xizmat: {names.get(service, service)}\n"
        f"Tugash vaqti: {expires}",
        parse_mode="HTML"
    )


# =========================================================
# USER PURCHASE USERNAME
# =========================================================

async def process_purchase_username(
    update,
    context,
    username
):

    purchase = context.user_data.get(
        "purchase"
    )

    if not purchase:
        return False

    user_id = update.effective_user.id

    username = username.strip()

    if not username.startswith("@"):

        username = "@" + username

    if len(username) < 2:

        await update.message.reply_text(
            "❌ Username noto‘g‘ri."
        )

        return True

    purchase_type = purchase["type"]

    # -----------------------------------------------------
    # PRICE
    # -----------------------------------------------------

    try:

        price = Decimal(
            str(purchase["price"])
        )

    except Exception:

        context.user_data.clear()

        await update.message.reply_text(
            "❌ Narx xatosi.",
            reply_markup=main_menu()
        )

        return True

    user = get_user(
        user_id
    )

    if not user:

        context.user_data.clear()

        await update.message.reply_text(
            "❌ Foydalanuvchi topilmadi."
        )

        return True

    balance = Decimal(
        str(user["balance"])
    )

    if balance < price:

        context.user_data.clear()

        await update.message.reply_text(
            "❌ Balansingiz yetarli emas.",
            reply_markup=main_menu()
        )

        return True

    # -----------------------------------------------------
    # API KEY
    # -----------------------------------------------------

    if purchase_type == "stars":

        api_key = get_setting(
            "api_key_stars"
        )

    elif purchase_type == "premium":

        api_key = get_setting(
            "api_key_premium"
        )

    else:

        api_key = ""

    if not api_key:

        context.user_data.clear()

        await update.message.reply_text(
            "❌ Xizmat hozircha mavjud emas.",
            reply_markup=main_menu()
        )

        return True

    # -----------------------------------------------------
    # USERNAME CHECK
    # -----------------------------------------------------

    try:

        check = check_paystars_username(
            api_key,
            username,
            purchase_type
        )

        verification_token = check.get(
            "verification_token"
        )

        if not verification_token:

            logger.warning(
                "Username verification failed: %s",
                check
            )

            await update.message.reply_text(
                "❌ Username tekshirilmadi.\n\n"
                "Username to‘g‘ri ekanini tekshirib, "
                "qaytadan yuboring."
            )

            return True

        # -------------------------------------------------
        # STARS
        # -------------------------------------------------

        if purchase_type == "stars":

            quantity = int(
                purchase["quantity"]
            )

            result = buy_paystars_stars(
                api_key,
                username,
                quantity,
                verification_token
            )

            plan = str(
                quantity
            )

        # -------------------------------------------------
        # PREMIUM
        # -------------------------------------------------

        else:

            months = int(
                purchase["months"]
            )

            result = buy_paystars_premium(
                api_key,
                username,
                months,
                verification_token
            )

            plan = f"{months} oy"

        # -------------------------------------------------
        # PROVIDER ORDER ID
        # -------------------------------------------------

        provider_order_id = (
            result.get("order_id")
            or result.get("id")
            or ""
        )

        # -------------------------------------------------
        # DEDUCT BALANCE SAFELY
        # -------------------------------------------------

        conn = get_db()

        try:

            with conn.cursor(
                cursor_factory=RealDictCursor
            ) as cur:

                cur.execute("""
                    UPDATE users
                    SET balance = balance - %s
                    WHERE user_id = %s
                      AND balance >= %s
                    RETURNING balance
                """, (
                    price,
                    user_id,
                    price
                ))

                updated = cur.fetchone()

                if not updated:

                    conn.rollback()

                    # Providerga buyurtma yuborilgan bo‘lsa,
                    # lekin balans yetarli bo‘lmasa,
                    # xavfsizlik uchun foydalanuvchiga
                    # umumiy xabar beramiz.
                    raise RuntimeError(
                        "Balance deduction failed."
                    )

                # -------------------------------------------------
                # ORDER
                # -------------------------------------------------

                cur.execute("""
                    INSERT INTO orders(
                        user_id,
                        service,
                        plan,
                        price,
                        provider_order_id,
                        status
                    )
                    VALUES(
                        %s,
                        %s,
                        %s,
                        %s,
                        %s,
                        %s
                    )
                """, (
                    user_id,
                    purchase_type,
                    plan,
                    price,
                    provider_order_id,
                    "Kutilmoqda"
                ))

                conn.commit()

        except Exception:

            conn.rollback()
            raise

        finally:

            conn.close()

        context.user_data.clear()

        service_name = (
            "⭐ Stars"
            if purchase_type == "stars"
            else "💎 Premium"
        )

        await update.message.reply_text(
            "✅ <b>Buyurtma qabul qilindi!</b>\n\n"
            f"Xizmat: {service_name}\n"
            f"Username: <code>{username}</code>\n"
            f"Plan: {plan}\n"
            f"Narx: {money(price)} so‘m\n\n"
            "Buyurtma bajarilishi kutilmoqda.",
            parse_mode="HTML",
            reply_markup=main_menu()
        )

        return True

    except Exception as e:

        logger.exception(
            "Purchase error: %s",
            e
        )

        await update.message.reply_text(
            "❌ Hozircha buyurtmani bajarib bo‘lmadi.\n\n"
            "Birozdan keyin qayta urinib ko‘ring.",
            reply_markup=main_menu()
        )

        return True


# =========================================================
# RECEIPT PHOTO
# =========================================================

async def receipt_photo(
    update,
    context
):

    if not update.message:
        return

    if not context.user_data.get(
        "waiting_receipt"
    ):

        return

    if ADMIN_ID == 0:

        await update.message.reply_text(
            "❌ Admin sozlanmagan."
        )

        return

    photo = update.message.photo[-1]

    file_id = photo.file_id

    try:

        payment = db_query("""
            INSERT INTO payments(
                user_id,
                amount,
                status
            )
            VALUES(
                %s,
                %s,
                %s
            )
            RETURNING id
        """, (
            update.effective_user.id,
            0,
            "Kutilmoqda"
        ), returning=True)

        payment_id = payment["id"]

    except Exception as e:

        logger.exception(
            "Payment create error: %s",
            e
        )

        await update.message.reply_text(
            "❌ Chekni qabul qilishda xatolik."
        )

        return

    context.user_data.clear()

    keyboard = InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                "✅ Tasdiqlash",
                callback_data=f"payment:approve:{payment_id}"
            ),

            InlineKeyboardButton(
                "❌ Rad etish",
                callback_data=f"payment:reject:{payment_id}"
            ),
        ],

    ])

    try:

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=(
                "💳 <b>Yangi to‘lov cheki</b>\n\n"
                f"👤 User ID: "
                f"<code>{update.effective_user.id}</code>\n"
                f"🧾 Payment ID: "
                f"<code>{payment_id}</code>\n\n"
                "Chekni tekshiring.\n"
                "Tasdiqlash uchun tugmani bosing."
            ),
            parse_mode="HTML",
            reply_markup=keyboard
        )

    except Exception as e:

        logger.exception(
            "Admin photo error: %s",
            e
        )

        # Admin ololmagan bo‘lsa, paymentni
        # bekor qilamiz.
        try:

            db_query("""
                UPDATE payments
                SET status = %s,
                    admin_id = %s
                WHERE id = %s
                  AND status = %s
            """, (
                "Xatolik",
                ADMIN_ID,
                payment_id,
                "Kutilmoqda"
            ))

        except Exception:
            pass

        await update.message.reply_text(
            "❌ Chekni adminga yuborishda xatolik."
        )

        return

    await update.message.reply_text(
        "✅ Chek qabul qilindi.\n\n"
        "Admin tekshirganidan keyin "
        "balansingiz to‘ldiriladi.",
        reply_markup=main_menu()
    )


# =========================================================
# PAYMENT CALLBACK
# =========================================================

async def payment_callback(
    update,
    context
):

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

    try:

        payment_id = int(
            parts[2]
        )

    except Exception:

        await query.answer(
            "Payment ID noto‘g‘ri.",
            show_alert=True
        )

        return

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

    # =====================================================
    # REJECT
    # =====================================================

    if action == "reject":

        try:

            db_query("""
                UPDATE payments
                SET status = %s,
                    admin_id = %s
                WHERE id = %s
                  AND status = %s
            """, (
                "Rad etildi",
                ADMIN_ID,
                payment_id,
                "Kutilmoqda"
            ))

        except Exception as e:

            logger.exception(
                "Payment reject error: %s",
                e
            )

            await query.answer(
                "Rad etishda xatolik.",
                show_alert=True
            )

            return

        try:

            await query.edit_message_caption(
                caption=(
                    "❌ <b>To‘lov rad etildi.</b>\n\n"
                    f"Payment ID: "
                    f"<code>{payment_id}</code>"
                ),
                parse_mode="HTML"
            )

        except Exception:
            pass

        try:

            await context.bot.send_message(
                chat_id=payment["user_id"],
                text=(
                    "❌ <b>To‘lovingiz rad etildi.</b>\n\n"
                    f"Payment ID: "
                    f"<code>{payment_id}</code>\n\n"
                    "Savollar bo‘lsa SOS orqali "
                    "operator bilan bog‘laning."
                ),
                parse_mode="HTML"
            )

        except Exception:
            pass

        await query.answer(
            "To‘lov rad etildi."
        )

        return

    # =====================================================
    # APPROVE
    # =====================================================

    if action == "approve":

        context.user_data.clear()

        context.user_data[
            "admin_action"
        ] = "payment_amount"

        context.user_data[
            "payment_id"
        ] = payment_id

        await query.message.reply_text(
            f"💰 <b>Payment ID {payment_id}</b>\n\n"
            "To‘lov summasini so‘mda yuboring.\n\n"
            "Masalan: <code>25000</code>\n\n"
            "Bekor qilish: /cancel",
            parse_mode="HTML"
        )

        await query.answer()

        return


# =========================================================
# USER CALLBACKS
# =========================================================

async def user_callbacks(
    update,
    context
):

    query = update.callback_query

    data = query.data

    # =====================================================
    # USER SOS
    # =====================================================

    if data == "user_sos":

        await query.answer()

        username = get_setting(
            "sos_username",
            SOS_USERNAME
        ).strip()

        clean = username.lstrip("@")

        if not clean:

            await query.edit_message_text(
                "❌ Operator sozlanmagan."
            )

            return

        keyboard = InlineKeyboardMarkup([

            [
                InlineKeyboardButton(
                    "🆘 Operator",
                    url=f"https://t.me/{clean}"
                )
            ],

            [
                InlineKeyboardButton(
                    "⬅️ Orqaga",
                    callback_data="close"
                )
            ],

        ])

        await query.edit_message_text(
            "🆘 <b>Yordam</b>\n\n"
            "Operator bilan bog‘lanish uchun "
            "quyidagi tugmani bosing.",
            parse_mode="HTML",
            reply_markup=keyboard
        )

        return

    # =====================================================
    # OPEN SERVICE
    # =====================================================

    if data.startswith(
        "open_service:"
    ):

        await query.answer()

        service = data.split(":")[1]

        if service not in (
            "stars",
            "premium",
            "donat",
            "sim"
        ):

            return

        await show_service(
            update,
            service
        )

        return

    # =====================================================
    # STARS
    # =====================================================

    if data.startswith(
        "stars:"
    ):

        await query.answer()

        await stars_callback(
            update,
            context
        )

        return

    # =====================================================
    # PREMIUM
    # =====================================================

    if data.startswith(
        "premium:"
    ):

        await query.answer()

        await premium_callback(
            update,
            context
        )

        return

    # =====================================================
    # BUY
    # =====================================================

    if data.startswith(
        "buy:"
    ):

        await query.answer()

        await buy_callback(
            update,
            context
        )

        return

    # =====================================================
    # TRIAL
    # =====================================================

    if data.startswith(
        "trial:"
    ):

        await query.answer()

        await trial_callback(
            update,
            context
        )

        return

    # =====================================================
    # CLOSE
    # =====================================================

    if data == "close":

        await query.answer()

        await query.edit_message_text(
            "⬅️ Menuga qaytdingiz.\n\n"
            "Pastdagi tugmalardan foydalaning."
        )

        return


# =========================================================
# ADMIN CALLBACKS
# =========================================================

async def admin_all_callbacks(
    update,
    context
):

    query = update.callback_query

    data = query.data

    if update.effective_user.id != ADMIN_ID:

        await query.answer(
            "Ruxsat yo‘q.",
            show_alert=True
        )

        return

    # =====================================================
    # PAYMENT
    # =====================================================

    if data.startswith(
        "payment:"
    ):

        await payment_callback(
            update,
            context
        )

        return

    await query.answer()

    # =====================================================
    # API
    # =====================================================

    if data.startswith(
        "admin_api:"
    ):

        service = data.split(":")[1]

        await admin_api_menu(
            update,
            context,
            service
        )

        return

    # =====================================================
    # API EDIT
    # =====================================================

    if data.startswith(
        "admin_api_edit:"
    ):

        service = data.split(":")[1]

        await admin_api_edit(
            update,
            context,
            service
        )

        return

    # =====================================================
    # BACK
    # =====================================================

    if data == "admin_back":

        await admin_panel(
            update,
            context
        )

        return

    # =====================================================
    # CARD
    # =====================================================

    if data == "admin_card":

        await admin_card(
            update,
            context
        )

        return

    # =====================================================
    # BALANCE ADD
    # =====================================================

    if data == "admin_balance_add":

        await admin_balance_start(
            update,
            context,
            "add"
        )

        return

    # =====================================================
    # BALANCE SUB
    # =====================================================

    if data == "admin_balance_sub":

        await admin_balance_start(
            update,
            context,
            "sub"
        )

        return

    # =====================================================
    # USERS
    # =====================================================

    if data == "admin_users":

        await admin_users(
            update,
            context
        )

        return

    # =====================================================
    # STATS
    # =====================================================

    if data == "admin_stats":

        await admin_stats(
            update,
            context
        )

        return

    # =====================================================
    # SUBSCRIPTIONS
    # =====================================================

    if data == "admin_subs":

        await admin_subs(
            update,
            context
        )

        return

    # =====================================================
    # PAYMENTS
    # =====================================================

    if data == "admin_payments":

        await admin_payments(
            update,
            context
        )

        return

    # =====================================================
    # PRICES
    # =====================================================

    if data == "admin_prices":

        await admin_prices(
            update,
            context
        )

        return

    # =====================================================
    # PRICE EDIT
    # =====================================================

    if data == "admin_price_edit":

        await admin_price_edit(
            update,
            context
        )

        return

    # =====================================================
    # SOS
    # =====================================================

    if data == "admin_sos":

        await admin_sos(
            update,
            context
        )

        return


# =========================================================
# USER TEXT
# =========================================================

async def messages(
    update,
    context
):

    if not update.message:
        return

    text = (
        update.message.text or ""
    ).strip()

    # =====================================================
    # ADMIN ACTION
    # =====================================================

    if update.effective_user.id == ADMIN_ID:

        handled = await handle_admin_text(
            update,
            context
        )

        if handled:
            return

    # =====================================================
    # BALANCE
    # =====================================================

    if text == "💰 Balans":

        await balance(
            update,
            context
        )

        return

    # =====================================================
    # SUBSCRIPTIONS
    # =====================================================

    if text == "📦 Obunalarim":

        await subscriptions(
            update,
            context
        )

        return

    # =====================================================
    # SOS
    # =====================================================

    if text == "🆘 SOS":

        await sos(
            update,
            context
        )

        return

    # =====================================================
    # API
    # =====================================================

    if text == "🤝 Hamkorlik (API)":

        await api_menu(
            update,
            context
        )

        return

    # =====================================================
    # BALANCE TOP UP
    # =====================================================

    if text == "➕ Balans to'ldirish":

        card = get_setting(
            "card"
        )

        if not card:

            await update.message.reply_text(
                "❌ Karta hali sozlanmagan."
            )

            return

        await update.message.reply_text(
            "➕ <b>Balans to‘ldirish</b>\n\n"
            f"💳 To‘lov uchun:\n"
            f"<code>{card}</code>\n\n"
            "To‘lovni amalga oshirgach, "
            "chek rasmini shu yerga yuboring.",
            parse_mode="HTML"
        )

        context.user_data[
            "waiting_receipt"
        ] = True

        return

    # =====================================================
    # PURCHASE USERNAME
    # =====================================================

    purchase = context.user_data.get(
        "purchase"
    )

    if purchase:

        await process_purchase_username(
            update,
            context,
            text
        )

        return


# =========================================================
# ADMIN COMMAND
# =========================================================

async def admin_command(
    update,
    context
):

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

class HealthHandler(
    BaseHTTPRequestHandler
):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-type",
            "text/plain; charset=utf-8"
        )

        self.end_headers()

        self.wfile.write(
            b"DONUZ BOT OK"
        )

    def log_message(
        self,
        format,
        *args
    ):

        return


def start_health_server():

    try:

        server = HTTPServer(
            ("0.0.0.0", PORT),
            HealthHandler
        )

        logger.info(
            "Health server started on port %s",
            PORT
        )

        server.serve_forever()

    except Exception as e:

        logger.exception(
            "Health server error: %s",
            e
        )


# =========================================================
# ERROR HANDLER
# =========================================================

async def error_handler(
    update,
    context
):

    logger.exception(
        "Telegram error: %s",
        context.error
    )


# =========================================================
# MAIN
# =========================================================

def main():

    # =====================================================
    # ENV CHECK
    # =====================================================

    if not BOT_TOKEN:

        raise RuntimeError(
            "BOT_TOKEN Environment Variable mavjud emas."
        )

    if ADMIN_ID == 0:

        raise RuntimeError(
            "ADMIN_ID Environment Variable noto‘g‘ri."
        )

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL Environment Variable mavjud emas."
        )

    # =====================================================
    # DATABASE
    # =====================================================

    logger.info(
        "Database initializatsiya qilinmoqda..."
    )

    init_database()

    logger.info(
        "Database tayyor."
    )

    # =====================================================
    # HEALTH SERVER
    # =====================================================

    threading.Thread(
        target=start_health_server,
        daemon=True
    ).start()

    # =====================================================
    # APPLICATION
    # =====================================================

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # =====================================================
    # ERROR
    # =====================================================

    application.add_error_handler(
        error_handler
    )

    # =====================================================
    # COMMANDS
    # =====================================================

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

    # =====================================================
    # PHOTO
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            receipt_photo
        )
    )

    # =====================================================
    # ADMIN CALLBACKS
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            admin_all_callbacks,
            pattern=r"^(admin_|payment:)"
        )
    )

    # =====================================================
    # USER CALLBACKS
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            user_callbacks
        )
    )

    # =====================================================
    # TEXT
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            messages
        )
    )

    # =====================================================
    # START
    # =====================================================

    print("=" * 50)
    print("DONUZ BOT ISHGA TUSHDI")
    print("=" * 50)

    application.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# RUN
# =========================================================

if __name__ == "__main__":

    main()
