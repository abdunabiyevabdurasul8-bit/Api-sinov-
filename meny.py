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

BOT_TOKEN = os.getenv("BOT_TOKEN", "8799964859:AAE1ykyVhycVfPwT9z7X-DbCtMs6A5Kxcl0")
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
        with connection.cursor(
            cursor_factory=RealDictCursor
        ) as cursor:

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

    db_query("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """)

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

    db_query("""
        CREATE TABLE IF NOT EXISTS payments (
            id BIGSERIAL PRIMARY KEY,
            user_id BIGINT NOT NULL,
            amount BIGINT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    db_query("""
        INSERT INTO settings(key, value)
        VALUES('card', '8600 0000 0000 0000')
        ON CONFLICT(key) DO NOTHING
    """)

    db_query("""
        INSERT INTO settings(key, value)
        VALUES('sos_username', %s)
        ON CONFLICT(key) DO NOTHING
    """, (SOS_USERNAME,))

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

def get_setting(key, default=""):

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

    return default


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
        f"price_{service}_{plan}",
        str(DEFAULT_PRICES.get(service, {}).get(plan, 0))
    )

    try:
        return int(value)
    except (ValueError, TypeError):
        return 0


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
            "🤝 Hamkorlik (API)"
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

    context.user_data.clear()

    await update.message.reply_text(
        "Assalomu alaykum! 👋\n\n"
        "DONUZ xizmatlariga xush kelibsiz.\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=main_menu()
    )


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

async def sos_handler(update, context):

    sos_username = get_setting(
        "sos_username",
        SOS_USERNAME
    )

    if sos_username and not sos_username.startswith("@"):
        sos_username = "@" + sos_username

    await update.message.reply_text(
        "🆘 YORDAM KERAKMI?\n\n"
        "Admin bilan bog'lanish uchun:\n"
        f"👤 {sos_username}"
    )


# =========================================================
# USER CALLBACKLARI
# =========================================================

async def callbacks(update, context):

    query = update.callback_query

    await query.answer()

    user = query.from_user

    save_user(user)

    data = query.data

    # =====================================================
    # HAMKORLIK — XIZMAT TANLASH
    # =====================================================

    if data.startswith("open_service:"):

        service = data.split(":")[1]

        if service not in SERVICES:

            await query.message.reply_text(
                "❌ Xizmat topilmadi."
            )

            return

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

        await query.message.reply_text(
            f"{SERVICES[service]}"
            f"{current_text}\n\n"
            "Obuna muddatini tanlang:",
            reply_markup=service_menu(service)
        )

        return

    # =====================================================
    # SINOV
    # =====================================================

    if data.startswith("trial:"):

        service = data.split(":")[1]

        if service not in SERVICES:

            await query.message.reply_text(
                "❌ Xizmat topilmadi."
            )

            return

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

        try:
            _, service, plan = data.split(":")
        except ValueError:
            await query.message.reply_text(
                "❌ Buyurtma ma'lumotlari noto'g'ri."
            )
            return

        if service not in SERVICES:

            await query.message.reply_text(
                "❌ Xizmat topilmadi."
            )

            return

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
            start_time = old_expire
        else:
            start_time = now

        expires = start_time + timedelta(days=days)

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
                start_time,
                expires
            )
        )

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
# BALANS TO'LDIRISH
# =========================================================

async def start_balance_topup(update, context):

    card = get_setting(
        "card",
        "8600 0000 0000 0000"
    )

    context.user_data["topup_action"] = "amount"

    await update.message.reply_text(
        "💳 BALANS TO'LDIRISH\n\n"
        f"💳 Karta:\n{card}\n\n"
        "Qancha summa to'ldirmoqchisiz?\n\n"
        "Masalan:\n"
        "20000"
    )


async def topup_amount(update, context):

    if context.user_data.get(
        "topup_action"
    ) != "amount":
        return

    try:

        amount = int(
            update.message.text.strip()
        )

        if amount <= 0:
            raise ValueError

    except ValueError:

        await update.message.reply_text(
            "❌ Summa noto'g'ri.\n\n"
            "Faqat musbat son yuboring.\n"
            "Masalan: 20000"
        )

        return

    context.user_data["topup_amount"] = amount
    context.user_data["topup_action"] = "receipt"

    card = get_setting(
        "card",
        "8600 0000 0000 0000"
    )

    await update.message.reply_text(
        "💳 TO'LOV MA'LUMOTLARI\n\n"
        f"💰 Summa: {amount} so'm\n"
        f"💳 Karta: {card}\n\n"
        "To'lovni amalga oshirgandan so'ng,\n"
        "shu yerga chek/skrinshot rasmini yuboring."
    )


async def topup_receipt(update, context):

    if context.user_data.get(
        "topup_action"
    ) != "receipt":
        return

    if not update.message.photo:

        await update.message.reply_text(
            "❌ Iltimos, to'lov chekini rasm qilib yuboring."
        )

        return

    amount = context.user_data.get(
        "topup_amount"
    )

    if not amount:

        await update.message.reply_text(
            "❌ To'lov summasi topilmadi.\n"
            "Qaytadan balans to'ldirishni boshlang."
        )

        context.user_data.clear()

        return

    photo = update.message.photo[-1]

    file_id = photo.file_id

    with get_db() as conn:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                INSERT INTO payments
                (user_id, amount, status, created_at)
                VALUES (%s, %s, %s, NOW())
                RETURNING id
                """,
                (
                    update.effective_user.id,
                    amount,
                    "pending"
                )
            )

            payment = cur.fetchone()

            conn.commit()

    payment_id = payment["id"]

    user = update.effective_user

    context.user_data.clear()

    await update.message.reply_text(
        "✅ CHEK QABUL QILINDI!\n\n"
        f"💰 Summa: {amount} so'm\n"
        f"🧾 To'lov ID: #{payment_id}\n\n"
        "⏳ Admin tasdiqlashini kuting."
    )

    try:

        username = user.username or "username yo'q"
        first_name = user.first_name or "Noma'lum"

        await context.bot.send_photo(
            chat_id=ADMIN_ID,
            photo=file_id,
            caption=(
                "💳 YANGI TO'LOV!\n\n"
                f"🧾 To'lov ID: #{payment_id}\n"
                f"👤 Ism: {first_name}\n"
                f"🔹 Username: @{username}\n"
                f"🆔 User ID: {user.id}\n"
                f"💰 Summa: {amount} so'm\n\n"
                "Tasdiqlash yoki rad etishni tanlang."
            ),
            reply_markup=InlineKeyboardMarkup([
                [
                    InlineKeyboardButton(
                        "✅ Tasdiqlash",
                        callback_data=f"payment_accept:{payment_id}"
                    ),
                    InlineKeyboardButton(
                        "❌ Rad etish",
                        callback_data=f"payment_reject:{payment_id}"
                    )
                ]
            ])
        )

    except Exception as e:

        logging.error(
            f"Adminga chek yuborishda xatolik: {e}"
        )


# =========================================================
# TO'LOV ADMIN CALLBACK
# =========================================================

async def payment_admin_callback(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    parts = query.data.split(":")

    action = parts[0]
    payment_id = int(parts[1])

    with get_db() as conn:

        with conn.cursor(
            cursor_factory=RealDictCursor
        ) as cur:

            cur.execute(
                """
                SELECT id, user_id, amount, status
                FROM payments
                WHERE id=%s
                """,
                (payment_id,)
            )

            payment = cur.fetchone()

            if not payment:

                await query.edit_message_caption(
                    caption="❌ To'lov topilmadi."
                )

                return

            if payment["status"] != "pending":

                await query.answer(
                    "Bu to'lov allaqachon ko'rib chiqilgan.",
                    show_alert=True
                )

                return

            if action == "payment_accept":

                cur.execute(
                    """
                    UPDATE users
                    SET balance = balance + %s
                    WHERE user_id=%s
                    RETURNING balance
                    """,
                    (
                        payment["amount"],
                        payment["user_id"]
                    )
                )

                result = cur.fetchone()

                cur.execute(
                    """
                    UPDATE payments
                    SET status='approved',
                        admin_id=%s
                    WHERE id=%s
                    """,
                    (
                        ADMIN_ID,
                        payment_id
                    )
                )

                new_balance = result["balance"]

            else:

                cur.execute(
                    """
                    UPDATE payments
                    SET status='rejected',
                        admin_id=%s
                    WHERE id=%s
                    """,
                    (
                        ADMIN_ID,
                        payment_id
                    )
                )

                new_balance = None

            conn.commit()

    if action == "payment_accept":

        await query.edit_message_caption(
            caption=(
                "✅ TO'LOV TASDIQLANDI\n\n"
                f"🧾 ID: #{payment_id}\n"
                f"💰 Summa: {payment['amount']} so'm\n"
                f"👤 User ID: {payment['user_id']}\n"
                f"💳 Yangi balans: {new_balance} so'm"
            )
        )

        try:

            await context.bot.send_message(
                chat_id=payment["user_id"],
                text=(
                    "✅ BALANS TO'LDIRILDI!\n\n"
                    f"💰 Qo'shilgan summa: "
                    f"{payment['amount']} so'm\n"
                    f"💳 Hozirgi balans: "
                    f"{new_balance} so'm"
                )
            )

        except Exception as e:

            logging.error(
                f"Foydalanuvchiga xabar yuborishda xatolik: {e}"
            )

    else:

        await query.edit_message_caption(
            caption=(
                "❌ TO'LOV RAD ETILDI\n\n"
                f"🧾 ID: #{payment_id}\n"
                f"💰 Summa: {payment['amount']} so'm\n"
                f"👤 User ID: {payment['user_id']}"
            )
        )

        try:

            await context.bot.send_message(
                chat_id=payment["user_id"],
                text=(
                    "❌ TO'LOV RAD ETILDI.\n\n"
                    f"🧾 To'lov ID: #{payment_id}\n"
                    f"💰 Summa: {payment['amount']} so'm\n\n"
                    "Agar xatolik bo'lsa, "
                    "🆘 SOS orqali admin bilan bog'laning."
                )
            )

        except Exception as e:

            logging.error(
                f"Foydalanuvchiga xabar yuborishda xatolik: {e}"
            )


# =========================================================
# ADMIN MENYU
# =========================================================

def admin_menu():

    keyboard = [

        [
            InlineKeyboardButton(
                "⭐ Stars",
                callback_data="admin_service:stars"
            ),
            InlineKeyboardButton(
                "💎 Premium",
                callback_data="admin_service:premium"
            )
        ],

        [
            InlineKeyboardButton(
                "🎁 Donat",
                callback_data="admin_service:donat"
            ),
            InlineKeyboardButton(
                "📱 SIM",
                callback_data="admin_service:sim"
            )
        ],

        [
            InlineKeyboardButton(
                "💳 Karta",
                callback_data="admin_card"
            )
        ],

        [
            InlineKeyboardButton(
                "💰 Balans + / −",
                callback_data="admin_balance"
            )
        ],

        [
            InlineKeyboardButton(
                "👥 Foydalanuvchilar",
                callback_data="admin_users"
            ),
            InlineKeyboardButton(
                "📊 Statistika",
                callback_data="admin_stats"
            )
        ],

        [
            InlineKeyboardButton(
                "📋 Obunalar",
                callback_data="admin_subscriptions"
            )
        ],

        [
            InlineKeyboardButton(
                "🆘 SOS",
                callback_data="admin_sos"
            )
        ]

    ]

    return InlineKeyboardMarkup(keyboard)


async def admin_command(update, context):

    if update.effective_user.id != ADMIN_ID:

        await update.message.reply_text(
            "❌ Siz admin emassiz."
        )

        return

    await update.message.reply_text(
        "⚙️ ADMIN PANEL\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=admin_menu()
    )


# =========================================================
# ADMIN NARXLAR
# =========================================================

async def admin_price_menu(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    service = query.data.split(":")[1]

    service_name = SERVICES.get(
        service,
        service
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "1 kun",
                callback_data=f"admin_price:{service}:1d"
            ),
            InlineKeyboardButton(
                "7 kun",
                callback_data=f"admin_price:{service}:7d"
            )
        ],
        [
            InlineKeyboardButton(
                "1 oy",
                callback_data=f"admin_price:{service}:30d"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin panel",
                callback_data="admin_back"
            )
        ]
    ]

    prices = {
        "1d": get_setting(
            f"price_{service}_1d",
            "5000"
        ),
        "7d": get_setting(
            f"price_{service}_7d",
            "20000"
        ),
        "30d": get_setting(
            f"price_{service}_30d",
            "38000"
        )
    }

    text = (
        f"⚙️ {service_name} narxlari\n\n"
        f"1 kun: {prices['1d']} so'm\n"
        f"7 kun: {prices['7d']} so'm\n"
        f"1 oy: {prices['30d']} so'm\n\n"
        "O'zgartirmoqchi bo'lgan muddatni tanlang:"
    )

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_price_edit(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    parts = query.data.split(":")

    service = parts[1]
    plan = parts[2]

    context.user_data["admin_action"] = "price"
    context.user_data["admin_price_service"] = service
    context.user_data["admin_price_plan"] = plan

    plan_names = {
        "1d": "1 kun",
        "7d": "7 kun",
        "30d": "1 oy"
    }

    await query.edit_message_text(
        f"💰 {SERVICES.get(service, service)}\n\n"
        f"📅 Muddat: {plan_names.get(plan, plan)}\n\n"
        "Yangi narxni so'mda yuboring.\n\n"
        "Masalan:\n"
        "5000"
    )


async def admin_price_text(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    if context.user_data.get(
        "admin_action"
    ) != "price":
        return

    try:

        price = int(
            update.message.text.strip()
        )

        if price < 0:
            raise ValueError

    except ValueError:

        await update.message.reply_text(
            "❌ Narx noto'g'ri.\n\n"
            "Faqat son yuboring.\n"
            "Masalan: 5000"
        )

        return

    service = context.user_data.get(
        "admin_price_service"
    )

    plan = context.user_data.get(
        "admin_price_plan"
    )

    set_setting(
        f"price_{service}_{plan}",
        str(price)
    )

    context.user_data.pop(
        "admin_action",
        None
    )

    context.user_data.pop(
        "admin_price_service",
        None
    )

    context.user_data.pop(
        "admin_price_plan",
        None
    )

    plan_names = {
        "1d": "1 kun",
        "7d": "7 kun",
        "30d": "1 oy"
    }

    await update.message.reply_text(
        "✅ Narx muvaffaqiyatli o'zgartirildi!\n\n"
        f"Xizmat: {SERVICES.get(service, service)}\n"
        f"Muddat: {plan_names.get(plan, plan)}\n"
        f"Yangi narx: {price} so'm"
    )


# =========================================================
# ADMIN KARTA
# =========================================================

async def admin_card_menu(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    current_card = get_setting(
        "card",
        "8600 0000 0000 0000"
    )

    context.user_data["admin_action"] = "card"

    await query.edit_message_text(
        "💳 KARTA SOZLAMASI\n\n"
        f"Hozirgi karta:\n`{current_card}`\n\n"
        "Yangi karta raqamini yuboring.\n\n"
        "Masalan:\n"
        "8600 1234 5678 9012",
        parse_mode="Markdown"
    )


async def admin_card_text(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    if context.user_data.get(
        "admin_action"
    ) != "card":
        return

    card = update.message.text.strip()

    card_digits = card.replace(" ", "")

    if not card_digits.isdigit():

        await update.message.reply_text(
            "❌ Karta raqami faqat raqamlardan iborat bo'lishi kerak."
        )

        return

    if len(card_digits) != 16:

        await update.message.reply_text(
            "❌ Karta raqami 16 ta raqamdan iborat bo'lishi kerak."
        )

        return

    formatted_card = " ".join(
        card_digits[i:i + 4]
        for i in range(0, 16, 4)
    )

    set_setting(
        "card",
        formatted_card
    )

    context.user_data.pop(
        "admin_action",
        None
    )

    await update.message.reply_text(
        "✅ Karta raqami muvaffaqiyatli o'zgartirildi!\n\n"
        f"💳 Yangi karta:\n"
        f"{formatted_card}"
    )


# =========================================================
# ADMIN BALANS
# =========================================================

async def admin_balance_menu(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    keyboard = [
        [
            InlineKeyboardButton(
                "➕ Pul qo'shish",
                callback_data="admin_balance_add"
            )
        ],
        [
            InlineKeyboardButton(
                "➖ Pul ayirish",
                callback_data="admin_balance_sub"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin panel",
                callback_data="admin_back"
            )
        ]
    ]

    await query.edit_message_text(
        "💰 BALANS BOSHQARUVI\n\n"
        "Kerakli amalni tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_balance_action(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    if query.data == "admin_balance_add":

        action = "add"
        title = "➕ BALANS QO'SHISH"

    else:

        action = "sub"
        title = "➖ BALANS AYIRISH"

    context.user_data["admin_action"] = "balance"
    context.user_data["admin_balance_type"] = action

    await query.edit_message_text(
        f"{title}\n\n"
        "Foydalanuvchi ID sini yuboring.\n\n"
        "Masalan:\n"
        "123456789"
    )


async def admin_balance_user_id(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    if context.user_data.get(
        "admin_action"
    ) != "balance":
        return

    try:

        target_user_id = int(
            update.message.text.strip()
        )

    except ValueError:

        await update.message.reply_text(
            "❌ User ID noto'g'ri."
        )

        return

    target = db_query(
        """
        SELECT
            user_id,
            username,
            first_name,
            balance
        FROM users
        WHERE user_id=%s
        """,
        (target_user_id,),
        fetch=True,
        one=True
    )

    if not target:

        await update.message.reply_text(
            "❌ Bu ID bilan foydalanuvchi topilmadi."
        )

        return

    context.user_data["admin_balance_user_id"] = target_user_id
    context.user_data["admin_action"] = "balance_amount"

    username = target["username"] or "username yo'q"
    first_name = target["first_name"] or "Noma'lum"
    balance = target["balance"]

    action = context.user_data.get(
        "admin_balance_type"
    )

    action_text = (
        "➕ qo'shish"
        if action == "add"
        else "➖ ayirish"
    )

    await update.message.reply_text(
        "👤 Foydalanuvchi topildi!\n\n"
        f"🆔 ID: {target_user_id}\n"
        f"👤 Ism: {first_name}\n"
        f"🔹 Username: @{username}\n"
        f"💰 Hozirgi balans: {balance} so'm\n\n"
        f"{action_text} uchun summani yuboring."
    )


async def admin_balance_amount(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    if context.user_data.get(
        "admin_action"
    ) != "balance_amount":
        return

    try:

        amount = int(
            update.message.text.strip()
        )

        if amount <= 0:
            raise ValueError

    except ValueError:

        await update.message.reply_text(
            "❌ Summa noto'g'ri."
        )

        return

    target_user_id = context.user_data.get(
        "admin_balance_user_id"
    )

    action = context.user_data.get(
        "admin_balance_type"
    )

    if action == "add":

        row = db_query(
            """
            UPDATE users
            SET balance = balance + %s
            WHERE user_id=%s
            RETURNING balance
            """,
            (
                amount,
                target_user_id
            ),
            fetch=True,
            one=True
        )

    else:

        row = db_query(
            """
            UPDATE users
            SET balance = GREATEST(balance - %s, 0)
            WHERE user_id=%s
            RETURNING balance
            """,
            (
                amount,
                target_user_id
            ),
            fetch=True,
            one=True
        )

    context.user_data.pop(
        "admin_action",
        None
    )

    context.user_data.pop(
        "admin_balance_user_id",
        None
    )

    context.user_data.pop(
        "admin_balance_type",
        None
    )

    new_balance = row["balance"] if row else 0

    if action == "add":

        await update.message.reply_text(
            "✅ BALANS TO'LDIRILDI\n\n"
            f"🆔 User ID: {target_user_id}\n"
            f"💵 Qo'shildi: +{amount} so'm\n"
            f"💰 Yangi balans: {new_balance} so'm"
        )

    else:

        await update.message.reply_text(
            "✅ BALANS AYIRILDI\n\n"
            f"🆔 User ID: {target_user_id}\n"
            f"💵 Ayirildi: -{amount} so'm\n"
            f"💰 Yangi balans: {new_balance} so'm"
        )


# =========================================================
# ADMIN USERS
# =========================================================

async def admin_users_menu(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    users = db_query(
        """
        SELECT
            user_id,
            username,
            first_name,
            balance,
            created_at
        FROM users
        ORDER BY created_at DESC
        LIMIT 50
        """,
        fetch=True
    )

    if not users:

        text = (
            "👥 FOYDALANUVCHILAR\n\n"
            "Hozircha foydalanuvchilar yo'q."
        )

    else:

        text = "👥 FOYDALANUVCHILAR\n\n"

        for index, user in enumerate(
            users,
            start=1
        ):

            username = user["username"] or "username yo'q"
            first_name = user["first_name"] or "Noma'lum"

            created_at = user["created_at"]

            created_text = (
                created_at.strftime("%d.%m.%Y %H:%M")
                if created_at
                else "-"
            )

            text += (
                f"{index}. 👤 {first_name}\n"
                f"   🆔 ID: {user['user_id']}\n"
                f"   🔹 @{username}\n"
                f"   💰 Balans: {user['balance']} so'm\n"
                f"   📅 Qo'shilgan: {created_text}\n\n"
            )

    keyboard = [
        [
            InlineKeyboardButton(
                "🔄 Yangilash",
                callback_data="admin_users"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin panel",
                callback_data="admin_back"
            )
        ]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# ADMIN STATISTIKA
# =========================================================

async def admin_stats_menu(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    total_users = db_query(
        "SELECT COUNT(*) AS total FROM users",
        fetch=True,
        one=True
    )["total"]

    today_users = db_query(
        """
        SELECT COUNT(*) AS total
        FROM users
        WHERE created_at >= CURRENT_DATE
        """,
        fetch=True,
        one=True
    )["total"]

    total_orders = db_query(
        "SELECT COUNT(*) AS total FROM orders",
        fetch=True,
        one=True
    )["total"]

    approved_payments = db_query(
        """
        SELECT COUNT(*) AS total
        FROM payments
        WHERE status='approved'
        """,
        fetch=True,
        one=True
    )["total"]

    total_payments = db_query(
        """
        SELECT COALESCE(SUM(amount), 0) AS total
        FROM payments
        WHERE status='approved'
        """,
        fetch=True,
        one=True
    )["total"]

    active_subscriptions = db_query(
        """
        SELECT COUNT(*) AS total
        FROM subscriptions
        WHERE expires_at > NOW()
        """,
        fetch=True,
        one=True
    )["total"]

    total_balance = db_query(
        """
        SELECT COALESCE(SUM(balance), 0) AS total
        FROM users
        """,
        fetch=True,
        one=True
    )["total"]

    text = (
        "📊 BOT STATISTIKASI\n\n"
        f"👥 Jami foydalanuvchilar: {total_users}\n"
        f"🆕 Bugun qo'shilganlar: {today_users}\n\n"
        f"📦 Jami buyurtmalar: {total_orders}\n"
        f"📋 Faol obunalar: {active_subscriptions}\n\n"
        f"💳 Tasdiqlangan to'lovlar: {approved_payments}\n"
        f"💵 Jami tushgan pul: {total_payments} so'm\n"
        f"💰 Foydalanuvchilar balanslari: {total_balance} so'm"
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "🔄 Yangilash",
                callback_data="admin_stats"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin panel",
                callback_data="admin_back"
            )
        ]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# ADMIN OBUNALAR
# =========================================================

async def admin_subscriptions_menu(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    subscriptions = db_query(
        """
        SELECT
            s.id,
            s.user_id,
            s.service,
            s.started_at,
            s.expires_at,
            s.source,
            u.username,
            u.first_name
        FROM subscriptions s
        LEFT JOIN users u
            ON u.user_id=s.user_id
        WHERE s.expires_at > NOW()
        ORDER BY s.expires_at ASC
        LIMIT 50
        """,
        fetch=True
    )

    if not subscriptions:

        text = (
            "📋 OBUNALAR\n\n"
            "Hozircha faol obunalar yo'q."
        )

    else:

        text = "📋 FAOL OBUNALAR\n\n"

        for index, sub in enumerate(
            subscriptions,
            start=1
        ):

            service_name = SERVICES.get(
                sub["service"],
                sub["service"]
            )

            username = sub["username"] or "username yo'q"
            first_name = sub["first_name"] or "Noma'lum"

            expires = (
                sub["expires_at"].strftime(
                    "%d.%m.%Y %H:%M"
                )
                if sub["expires_at"]
                else "-"
            )

            text += (
                f"{index}. {service_name}\n"
                f"   👤 {first_name}\n"
                f"   🆔 {sub['user_id']}\n"
                f"   🔹 @{username}\n"
                f"   ⏰ Tugaydi: {expires}\n"
                f"   📌 Manba: {sub['source']}\n\n"
            )

    keyboard = [
        [
            InlineKeyboardButton(
                "🔄 Yangilash",
                callback_data="admin_subscriptions"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin panel",
                callback_data="admin_back"
            )
        ]
    ]

    await query.edit_message_text(
        text,
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


# =========================================================
# ADMIN SOS
# =========================================================

async def admin_sos_menu(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    current_sos = get_setting(
        "sos_username",
        SOS_USERNAME
    )

    keyboard = [
        [
            InlineKeyboardButton(
                "✏️ SOS kontaktini o'zgartirish",
                callback_data="admin_sos_edit"
            )
        ],
        [
            InlineKeyboardButton(
                "⬅️ Admin panel",
                callback_data="admin_back"
            )
        ]
    ]

    await query.edit_message_text(
        "🆘 SOS SOZLAMASI\n\n"
        f"Hozirgi kontakt:\n"
        f"{current_sos}\n\n"
        "Kerakli amalni tanlang:",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )


async def admin_sos_edit(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    context.user_data["admin_action"] = "sos"

    await query.edit_message_text(
        "🆘 YANGI SOS KONTAKT\n\n"
        "Telegram username yuboring.\n\n"
        "Masalan:\n"
        "@donuz1"
    )


async def admin_sos_text(update, context):

    if update.effective_user.id != ADMIN_ID:
        return

    if context.user_data.get(
        "admin_action"
    ) != "sos":
        return

    username = update.message.text.strip()

    if not username.startswith("@"):
        username = "@" + username

    clean_username = username[1:]

    if not clean_username.replace("_", "").isalnum():

        await update.message.reply_text(
            "❌ Username noto'g'ri."
        )

        return

    if len(clean_username) < 5:

        await update.message.reply_text(
            "❌ Username juda qisqa."
        )

        return

    set_setting(
        "sos_username",
        username
    )

    context.user_data.pop(
        "admin_action",
        None
    )

    await update.message.reply_text(
        "✅ SOS kontakt o'zgartirildi!\n\n"
        f"🆘 Yangi kontakt: {username}"
    )


# =========================================================
# ADMIN BACK
# =========================================================

async def admin_back(update, context):

    query = update.callback_query

    await query.answer()

    if query.from_user.id != ADMIN_ID:
        return

    await query.edit_message_text(
        "⚙️ ADMIN PANEL\n\n"
        "Kerakli bo'limni tanlang:",
        reply_markup=admin_menu()
    )


# =========================================================
# ADMIN CALLBACKLARINI BIRLASHTIRISH
# =========================================================

async def admin_all_callbacks(update, context):

    query = update.callback_query

    if query.from_user.id != ADMIN_ID:

        await query.answer(
            "❌ Siz admin emassiz.",
            show_alert=True
        )

        return

    data = query.data

    if data.startswith("admin_service:"):

        await admin_price_menu(
            update,
            context
        )

        return

    if data.startswith("admin_price:"):

        await admin_price_edit(
            update,
            context
        )

        return

    if data == "admin_card":

        await admin_card_menu(
            update,
            context
        )

        return

    if data == "admin_balance":

        await admin_balance_menu(
            update,
            context
        )

        return

    if data in (
        "admin_balance_add",
        "admin_balance_sub"
    ):

        await admin_balance_action(
            update,
            context
        )

        return

    if data == "admin_users":

        await admin_users_menu(
            update,
            context
        )

        return

    if data == "admin_stats":

        await admin_stats_menu(
            update,
            context
        )

        return

    if data == "admin_subscriptions":

        await admin_subscriptions_menu(
            update,
            context
        )

        return

    if data == "admin_sos":

        await admin_sos_menu(
            update,
            context
        )

        return

    if data == "admin_sos_edit":

        await admin_sos_edit(
            update,
            context
        )

        return

    if data == "admin_back":

        await admin_back(
            update,
            context
        )

        return

    if data.startswith("payment_accept:"):

        await payment_admin_callback(
            update,
            context
        )

        return

    if data.startswith("payment_reject:"):

        await payment_admin_callback(
            update,
            context
        )

        return


# =========================================================
# UMUMIY MATN HANDLER
# =========================================================

async def messages(update, context):

    user = update.effective_user
    text = update.message.text

    # =====================================================
    # ADMIN ACTIONLAR
    # =====================================================

    if user.id == ADMIN_ID:

        action = context.user_data.get(
            "admin_action"
        )

        if action == "price":

            await admin_price_text(
                update,
                context
            )

            return

        if action == "card":

            await admin_card_text(
                update,
                context
            )

            return

        if action == "balance":

            await admin_balance_user_id(
                update,
                context
            )

            return

        if action == "balance_amount":

            await admin_balance_amount(
                update,
                context
            )

            return

        if action == "sos":

            await admin_sos_text(
                update,
                context
            )

            return

    # =====================================================
    # HAMKORLIK
    # =====================================================

    if text == "🤝 Hamkorlik (API)":

        keyboard = [

            [
                InlineKeyboardButton(
                    "⭐ Stars",
                    callback_data="open_service:stars"
                ),
                InlineKeyboardButton(
                    "💎 Premium",
                    callback_data="open_service:premium"
                )
            ],

            [
                InlineKeyboardButton(
                    "🎁 Donat",
                    callback_data="open_service:donat"
                ),
                InlineKeyboardButton(
                    "📱 SIM",
                    callback_data="open_service:sim"
                )
            ]

        ]

        await update.message.reply_text(
            "🤝 Hamkorlik (API)\n\n"
            "Kerakli xizmatni tanlang:",
            reply_markup=InlineKeyboardMarkup(
                keyboard
            )
        )

        return

    # =====================================================
    # TOPUP
    # =====================================================

    topup_action = context.user_data.get(
        "topup_action"
    )

    if topup_action == "amount":

        await topup_amount(
            update,
            context
        )

        return

    # =====================================================
    # BALANS
    # =====================================================

    if text == "💰 Balans":

        await show_balance(update)

        return

    # =====================================================
    # OBUNALAR
    # =====================================================

    if text == "📦 Obunalarim":

        await show_subscriptions(update)

        return

    # =====================================================
    # SOS
    # =====================================================

    if text == "🆘 SOS":

        await sos_handler(
            update,
            context
        )

        return

    # =====================================================
    # BALANS TO'LDIRISH
    # =====================================================

    if text == "➕ Balans to'ldirish":

        await start_balance_topup(
            update,
            context
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
            "BOT_TOKEN Render Environment Variables ichida yo'q."
        )

    if not ADMIN_ID:

        raise RuntimeError(
            "ADMIN_ID Render Environment Variables ichida yo'q."
        )

    if not DATABASE_URL:

        raise RuntimeError(
            "DATABASE_URL Render Environment Variables ichida yo'q."
        )

    # =====================================================
    # DATABASE
    # =====================================================

    init_database()

    # payments jadvaliga admin_id qo'shamiz
    db_query("""
        ALTER TABLE payments
        ADD COLUMN IF NOT EXISTS admin_id BIGINT
    """)

    # =====================================================
    # HEALTH SERVER
    # =====================================================

    threading.Thread(
        target=run_web_server,
        daemon=True
    ).start()

    # =====================================================
    # TELEGRAM
    # =====================================================

    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .build()
    )

    # =====================================================
    # START
    # =====================================================

    application.add_handler(
        CommandHandler(
            "start",
            start
        )
    )

    # =====================================================
    # ADMIN
    # =====================================================

    application.add_handler(
        CommandHandler(
            "admin",
            admin_command
        )
    )

    # =====================================================
    # ADMIN + PAYMENT CALLBACK
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            admin_all_callbacks,
            pattern=r"^(admin_|payment_)"
        )
    )

    # =====================================================
    # USER CALLBACK
    # open_service + buy + trial
    # =====================================================

    application.add_handler(
        CallbackQueryHandler(
            callbacks,
            pattern=r"^(open_service:|buy:|trial:)"
        )
    )

    # =====================================================
    # CHEK RASMI
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.PHOTO,
            topup_receipt
        )
    )

    # =====================================================
    # UMUMIY MATNLAR
    # =====================================================

    application.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            messages
        )
    )

    # =====================================================
    # LOG
    # =====================================================

    logging.info("================================")
    logging.info("DONUZ BOT ISHGA TUSHDI")
    logging.info("================================")

    # =====================================================
    # ISHGA TUSHIRISH
    # =====================================================

    application.run_polling(
        drop_pending_updates=True
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
