import os
import logging
import threading
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer

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
# SOZLAMALAR
# =========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN", "8799964859:AAHqdOHx_K6L0Ms_VLKqeT12RDRsF0_U7jc")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))
DATABASE_URL = os.getenv("DATABASE_URL", "")
PORT = int(os.getenv("PORT", "10000"))

SOS_USERNAME = os.getenv("SOS_USERNAME", "@donuz1")


# =========================================================
# XIZMATLAR
# =========================================================

SERVICES = {
    "stars": "⭐ Stars",
    "premium": "💎 Premium",
    "donat": "🎁 Donat",
    "sim": "📱 SIM",
}


# Har bir xizmatning narxi ALOHIDA saqlanadi
DEFAULT_PRICES = {
    "stars": {
        "1d": 5000,
        "7d": 20000,
        "30d": 38000,
    },

    "premium": {
        "1d": 5000,
        "7d": 20000,
        "30d": 38000,
    },

    "donat": {
        "1d": 5000,
        "7d": 20000,
        "30d": 38000,
    },

    "sim": {
        "1d": 5000,
        "7d": 20000,
        "30d": 38000,
    },
}


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)

log = logging.getLogger("DONUZ")


# =========================================================
# DATABASE
# =========================================================

def get_db():
    if not DATABASE_URL:
        raise RuntimeError(
            "DATABASE_URL topilmadi! Render Environment Variables "
            "ichiga DATABASE_URL qo'ying."
        )

    return psycopg2.connect(
        DATABASE_URL,
        sslmode="require"
    )


def db_query(sql, params=(), fetch=False, one=False):
    connection = get_db()

    try:
        with connection.cursor(cursor_factory=RealDictCursor) as cursor:
            cursor.execute(sql, params)

            result = None

            if fetch:
                if one:
                    result = cursor.fetchone()
                else:
                    result = cursor.fetchall()

            connection.commit()

            return result

    finally:
        connection.close()


# =========================================================
# DATABASE JADVALLARI
# =========================================================

def init_database():

    db_query("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            balance BIGINT NOT NULL DEFAULT 0,
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            last_seen TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


    # 4 ta xizmatning obunasi shu jadvalda alohida saqlanadi.
    #
    # Masalan:
    #
    # user 123
    # stars   -> 7 kun
    # premium -> 30 kun
    #
    # bir-biriga ta'sir qilmaydi.

    db_query("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id BIGSERIAL PRIMARY KEY,

            user_id BIGINT NOT NULL,

            service TEXT NOT NULL,

            started_at TIMESTAMPTZ NOT NULL,

            expires_at TIMESTAMPTZ NOT NULL,

            source TEXT NOT NULL DEFAULT 'purchase'
        )
    """)


    # Narxlar
    db_query("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)


    # Buyurtmalar
    db_query("""
        CREATE TABLE IF NOT EXISTS orders (
            id BIGSERIAL PRIMARY KEY,

            user_id BIGINT NOT NULL,

            service TEXT NOT NULL,

            plan TEXT NOT NULL,

            price BIGINT NOT NULL,

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


    # To'lovlar
    db_query("""
        CREATE TABLE IF NOT EXISTS payments (
            id BIGSERIAL PRIMARY KEY,

            user_id BIGINT NOT NULL,

            amount BIGINT NOT NULL,

            status TEXT NOT NULL DEFAULT 'pending',

            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)


    # Karta
    db_query("""
        INSERT INTO settings(key, value)
        VALUES('card', '8600 0000 0000 0000')
        ON CONFLICT(key) DO NOTHING
    """)


    # 4 ta xizmat narxlarini yaratish
    for service in SERVICES:

        for plan, amount in DEFAULT_PRICES[service].items():

            key = f"price_{service}_{plan}"

            db_query("""
                INSERT INTO settings(key, value)
                VALUES(%s, %s)
                ON CONFLICT(key) DO NOTHING
            """, (
                key,
                str(amount)
            ))


# =========================================================
# SETTINGS
# =========================================================

def get_setting(key):

    row = db_query(
        """
        SELECT value
        FROM settings
        WHERE key=%s
        """,
        (key,),
        fetch=True,
        one=True
    )

    if row:
        return row["value"]

    return ""


def set_setting(key, value):

    db_query(
        """
        INSERT INTO settings(key, value)
        VALUES(%s, %s)

        ON CONFLICT(key)
        DO UPDATE SET value=EXCLUDED.value
        """,
        (
            key,
            str(value)
        )
    )


def get_price(service, plan):

    value = get_setting(
        f"price_{service}_{plan}"
    )

    if not value:
        return 0

    return int(value)


# =========================================================
# FORMAT
# =========================================================

def money(amount):

    return (
        f"{amount:,}"
        .replace(",", " ")
        + " so'm"
    )


# =========================================================
# USER
# =========================================================

def save_user(user):

    db_query("""
        INSERT INTO users(
            user_id,
            username,
            first_name
        )

        VALUES(%s, %s, %s)

        ON CONFLICT(user_id)

        DO UPDATE SET

            username=EXCLUDED.username,

            first_name=EXCLUDED.first_name,

            last_seen=NOW()
    """, (
        user.id,
        user.username or "",
        user.first_name or ""
    ))


# =========================================================
# FAOL OBUNA
# =========================================================

def get_active_subscription(user_id, service):

    row = db_query("""
        SELECT expires_at

        FROM subscriptions

        WHERE
            user_id=%s

            AND service=%s

            AND expires_at > NOW()

        ORDER BY expires_at DESC

        LIMIT 1
    """, (
        user_id,
        service
    ),
        fetch=True,
        one=True
    )

    if row:
        return row["expires_at"]

    return None


# =========================================================
# ASOSIY MENYU
# =========================================================

def main_menu():

    keyboard = [

        [
            "⭐ Stars",
            "💎 Premium"
        ],

        [
            "🎁 Donat",
            "📱 SIM"
        ],

        [
            "💰 Balans",
            "➕ Balans to'ldirish"
        ],

        [
            "📦 Obunalarim",
            "🆘 SOS"
        ]

    ]

    return ReplyKeyboardMarkup(
        keyboard,
        resize_keyboard=True
    )


# =========================================================
# XIZMAT MENYUSI
# =========================================================

def service_menu(service):

    return InlineKeyboardMarkup([

        [
            InlineKeyboardButton(
                f"1 kun — {money(get_price(service, '1d'))}",
                callback_data=f"buy:{service}:1d"
            )
        ],

        [
            InlineKeyboardButton(
                f"7 kun — {money(get_price(service, '7d'))}",
                callback_data=f"buy:{service}:7d"
            )
        ],

        [
            InlineKeyboardButton(
                f"1 oy — {money(get_price(service, '30d'))}",
                callback_data=f"buy:{service}:30d"
            )
        ],

        [
            InlineKeyboardButton(
                "🎁 1 kunlik bepul sinov",
                callback_data=f"trial:{service}"
            )
        ]

    ])


# =========================================================
# START
# =========================================================

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):

    user = update.effective_user

    save_user(user)

    await update.message.reply_text(

        "Assalomu alaykum! 👋\n\n"

        "DONUZ xizmatlariga xush kelibsiz.\n\n"

        "Kerakli xizmatni tanlang:",

        reply_markup=main_menu()
    )


# =========================================================
# XIZMATLAR
# =========================================================

async def handle_service(update, context):

    user = update.effective_user

    save_user(user)

    text = update.message.text

    service_map = {

        "⭐ Stars": "stars",

        "💎 Premium": "premium",

        "🎁 Donat": "donat",

        "📱 SIM": "sim",

    }

    if text not in service_map:
        return False

    service = service_map[text]

    expires = get_active_subscription(
        user.id,
        service
    )

    current_text = ""

    if expires:

        current_text = (
            "\n\n⏳ Faol obuna:\n"
            + expires.astimezone().strftime(
                "%d.%m.%Y %H:%M"
            )
        )

    await update.message.reply_text(

        f"{SERVICES[service]}\n"
        f"{current_text}\n\n"
        "Obuna muddatini tanlang:",

        reply_markup=service_menu(service)
    )

    return True


# =========================================================
# BALANS
# =========================================================

async def show_balance(update):

    user = update.effective_user

    row = db_query("""
        SELECT balance
        FROM users
        WHERE user_id=%s
    """,
        (user.id,),
        fetch=True,
        one=True
    )

    balance = row["balance"] if row else 0

    await update.message.reply_text(

        "💰 Sizning balansingiz:\n\n"

        f"{money(balance)}"
    )


# =========================================================
# OBUNALARIM
# =========================================================

async def show_subscriptions(update):

    user = update.effective_user

    rows = db_query("""
        SELECT
            service,
            expires_at

        FROM subscriptions

        WHERE
            user_id=%s

            AND expires_at > NOW()

        ORDER BY expires_at
    """,
        (user.id,),
        fetch=True
    )

    if not rows:

        await update.message.reply_text(
            "📦 Sizda hozircha faol obuna yo'q."
        )

        return


    text = "📦 Faol obunalaringiz:\n\n"

    for row in rows:

        service_name = SERVICES.get(
            row["service"],
            row["service"]
        )

        expires = row["expires_at"].astimezone().strftime(
            "%d.%m.%Y %H:%M"
        )

        text += (
            f"{service_name}\n"
            f"⏳ {expires}\n\n"
        )


    await update.message.reply_text(text)


# =========================================================
# SOS
# =========================================================

async def show_sos(update):

    await update.message.reply_text(

        "🆘 Yordam kerakmi?\n\n"

        f"Admin: {SOS_USERNAME}"
    )


# =========================================================
# CALLBACK
# =========================================================

async def callbacks(update, context):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    save_user(user)

    data = query.data


    # =====================================================
    # SINOV
    # =====================================================

    if data.startswith("trial:"):

        service = data.split(":")[1]

        # Shu xizmat uchun oldin sinov ishlatilganmi?
        used = db_query("""
            SELECT id

            FROM subscriptions

            WHERE
                user_id=%s

                AND service=%s

                AND source='trial'

            LIMIT 1
        """,
            (
                user.id,
                service
            ),
            fetch=True,
            one=True
        )


        if used:

            await query.message.reply_text(

                "❌ Bu xizmat uchun 1 kunlik "
                "bepul sinovdan oldin foydalanilgansiz."
            )

            return


        now = datetime.now(timezone.utc)

        expires = now + timedelta(days=1)


        db_query("""
            INSERT INTO subscriptions(
                user_id,
                service,
                started_at,
                expires_at,
                source
            )

            VALUES(%s, %s, %s, %s, 'trial')
        """,
            (
                user.id,
                service,
                now,
                expires
            )
        )


        await query.message.reply_text(

            f"🎁 {SERVICES[service]}\n\n"

            "1 kunlik bepul sinov faollashtirildi! ✅\n\n"

            f"⏳ Tugaydi: "
            f"{expires.astimezone().strftime('%d.%m.%Y %H:%M')}"
        )

        return


    # =====================================================
    # SOTIB OLISH
    # =====================================================

    if data.startswith("buy:"):

        _, service, plan = data.split(":")

        amount = get_price(
            service,
            plan
        )

        if plan == "1d":
            days = 1

        elif plan == "7d":
            days = 7

        elif plan == "30d":
            days = 30

        else:
            await query.message.reply_text(
                "❌ Noma'lum tarif."
            )

            return


        row = db_query("""
            SELECT balance

            FROM users

            WHERE user_id=%s
        """,
            (user.id,),
            fetch=True,
            one=True
        )

        balance = row["balance"] if row else 0


        if balance < amount:

            await query.message.reply_text(

                "❌ Balansingiz yetarli emas.\n\n"

                f"Kerak: {money(amount)}\n"

                f"Mavjud: {money(balance)}"
            )

            return


        now = datetime.now(timezone.utc)

        old_expire = get_active_subscription(
            user.id,
            service
        )


        if old_expire and old_expire > now:

            start = old_expire

        else:

            start = now


        expires = start + timedelta(days=days)


        # Faqat shu xizmat uchun balansdan yechiladi
        db_query("""
            UPDATE users

            SET balance = balance - %s

            WHERE user_id=%s
        """,
            (
                amount,
                user.id
            )
        )


        # Faqat shu xizmatga obuna yoziladi
        db_query("""
            INSERT INTO subscriptions(
                user_id,
                service,
                started_at,
                expires_at,
                source
            )

            VALUES(
                %s,
                %s,
                %s,
                %s,
                'purchase'
            )
        """,
            (
                user.id,
                service,
                start,
                expires
            )
        )


        # Buyurtma
        db_query("""
            INSERT INTO orders(
                user_id,
                service,
                plan,
                price
            )

            VALUES(
                %s,
                %s,
                %s,
                %s
            )
        """,
            (
                user.id,
                service,
                plan,
                amount
            )
        )


        await query.message.reply_text(

            "✅ Obuna muvaffaqiyatli faollashtirildi!\n\n"

            f"{SERVICES[service]}\n"

            f"📅 Muddat: {days} kun\n"

            f"💰 To'lov: {money(amount)}\n\n"

            f"⏳ Tugaydi: "
            f"{expires.astimezone().strftime('%d.%m.%Y %H:%M')}"
        )

        return


# =========================================================
# MATN HANDLER
# =========================================================

async def messages(update, context):

    text = update.message.text

    if await handle_service(update, context):

        return


    if text == "💰 Balans":

        await show_balance(update)

        return


    if text == "📦 Obunalarim":

        await show_subscriptions(update)

        return


    if text == "🆘 SOS":

        await show_sos(update)

        return


    if text == "➕ Balans to'ldirish":

        card = get_setting("card")

        await update.message.reply_text(

            "💳 Balans to'ldirish\n\n"

            f"Karta: {card}\n\n"

            "To'lov qilgandan keyin chekni yuboring."
        )

        return


# =========================================================
# RENDER HEALTH SERVER
# =========================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        body = b"DONUZ BOT OK"

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )

        self.send_header(
            "Content-Length",
            str(len(body))
        )

        self.end_headers()

        self.wfile.write(body)


    def log_message(self, *args):

        return


def run_web_server():

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
            "BOT_TOKEN topilmadi."
        )


    if not ADMIN_ID:

        raise RuntimeError(
            "ADMIN_ID topilmadi."
        )


    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL topilmadi."
        )


    # Database
    init_database()


    # Render Web Service health server
    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()


    # Telegram bot
    application = (
        Application
        .builder()
        .token(BOT_TOKEN)
        .build()
    )


    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )


    application.add_handler(
        CallbackQueryHandler(
            callbacks
        )
    )


    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            messages
        )
    )


    print("==============================")
    print("DONUZ BOT ISHGA TUSHDI")
    print("==============================")


    application.run_polling(
        drop_pending_updates=True
    )


if __name__ == "__main__":

    main()
