import asyncio
import logging
import sqlite3
import uuid
import datetime
import os
import threading

from http.server import BaseHTTPRequestHandler, HTTPServer

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message
)


# ============================================================
# RENDER ENVIRONMENT
# ============================================================

TOKEN = os.getenv("BOT_TOKEN", "8799964859:AAHqdOHx_K6L0Ms_VLKqeT12RDRsF0_U7jc").strip()

ADMIN_ID = int(os.getenv("ADMIN_ID", "5692925792"))

PORT = int(os.getenv("PORT", "10000"))

DB_FILE = "database.db"


if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN topilmadi! Render Environment Variables ga BOT_TOKEN qo'ying."
    )


# ============================================================
# BOT
# ============================================================

bot = Bot(token=TOKEN)

router = Router()


# ============================================================
# DATABASE
# ============================================================

def db_start():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            joined_date TEXT,
            balance INTEGER DEFAULT 0,
            api_key TEXT,
            sub_active INTEGER DEFAULT 0,
            sub_expire TEXT
        )
    """)

    try:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN sub_active INTEGER DEFAULT 0"
        )
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN sub_expire TEXT"
        )
    except sqlite3.OperationalError:
        pass

    try:
        cursor.execute(
            "ALTER TABLE users ADD COLUMN api_key TEXT"
        )
    except sqlite3.OperationalError:
        pass

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            photo TEXT,
            status TEXT,
            date TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    """)

    cursor.execute("""
        INSERT OR IGNORE INTO settings (key, value)
        VALUES ('card', '')
    """)

    conn.commit()
    conn.close()


db_start()


# ============================================================
# STATES
# ============================================================

class PaymentState(StatesGroup):
    waiting_for_amount = State()
    waiting_for_receipt = State()


class AdminReject(StatesGroup):
    waiting_for_reason = State()


class AdminBalanceState(StatesGroup):
    waiting_for_user_id = State()
    waiting_for_amount = State()


class AdminCardState(StatesGroup):
    waiting_for_new_card = State()


# ============================================================
# MAIN MENU
# ============================================================

def main_menu(is_admin=False):

    kb = [
        [
            InlineKeyboardButton(
                text="👤 Profil",
                callback_data="profile"
            ),
            InlineKeyboardButton(
                text="💳 Balansni to'ldirish",
                callback_data="top_up"
            )
        ],
        [
            InlineKeyboardButton(
                text="🛒 Obuna sotib olish",
                callback_data="shop"
            ),
            InlineKeyboardButton(
                text="🔑 API olish",
                callback_data="get_api"
            )
        ],
        [
            InlineKeyboardButton(
                text="⚙️ API yangilash",
                callback_data="refresh_api"
            )
        ]
    ]

    if is_admin:
        kb.append([
            InlineKeyboardButton(
                text="👑 ADMIN PANEL",
                callback_data="admin_panel"
            )
        ])

    return InlineKeyboardMarkup(inline_keyboard=kb)


# ============================================================
# ADMIN MENU
# ============================================================

def admin_menu_kb():

    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💰 Balansni +/-",
                    callback_data="adm_balance"
                ),
                InlineKeyboardButton(
                    text="💳 Karta sozlash",
                    callback_data="adm_card"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📊 Statistika",
                    callback_data="adm_stats"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Asosiy menyu",
                    callback_data="back_main"
                )
            ]
        ]
    )


# ============================================================
# START
# ============================================================

@router.message(Command("start"))
async def cmd_start(message: Message):

    user_id = message.from_user.id

    joined_date = message.date.strftime("%Y-%m-%d")

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT user_id FROM users WHERE user_id = ?",
        (user_id,)
    )

    user = cursor.fetchone()

    if not user:

        cursor.execute("""
            INSERT INTO users (
                user_id,
                joined_date,
                balance,
                api_key,
                sub_active,
                sub_expire
            )
            VALUES (?, ?, 0, '', 0, '')
        """, (
            user_id,
            joined_date
        ))

        conn.commit()

    conn.close()

    is_admin = user_id == ADMIN_ID

    await message.answer(
        f"Assalomu alaykum, {message.from_user.first_name}!\n\n"
        f"API xizmatlari botiga xush kelibsiz.",
        reply_markup=main_menu(is_admin)
    )


# ============================================================
# BACK MAIN
# ============================================================

@router.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):

    is_admin = callback.from_user.id == ADMIN_ID

    try:
        await callback.message.edit_text(
            "🏠 Asosiy menyu:",
            reply_markup=main_menu(is_admin)
        )
    except Exception:
        await callback.message.answer(
            "🏠 Asosiy menyu:",
            reply_markup=main_menu(is_admin)
        )

    await callback.answer()


# ============================================================
# PROFILE
# ============================================================

@router.callback_query(F.data == "profile")
async def profile_handler(callback: CallbackQuery):

    try:

        user_id = callback.from_user.id

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT joined_date, balance, sub_active, sub_expire
            FROM users
            WHERE user_id = ?
        """, (user_id,))

        user = cursor.fetchone()

        if not user:

            date_str = datetime.datetime.now().strftime("%Y-%m-%d")

            cursor.execute("""
                INSERT INTO users (
                    user_id,
                    joined_date,
                    balance,
                    api_key,
                    sub_active,
                    sub_expire
                )
                VALUES (?, ?, 0, '', 0, '')
            """, (
                user_id,
                date_str
            ))

            conn.commit()

            user = (
                date_str,
                0,
                0,
                ""
            )

        conn.close()

        if user[2] == 1:
            sub_status = (
                f"Faol ✅\n"
                f"Tugash vaqti: {user[3]}"
            )
        else:
            sub_status = "Faol emas ❌"

        text = (
            f"👤 <b>Profil ma'lumotlari</b>\n\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"📅 Qo'shilgan sana: {user[0]}\n"
            f"💰 Balans: {user[1]} so'm\n"
            f"📦 Obuna: {sub_status}"
        )

        is_admin = user_id == ADMIN_ID

        try:
            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin)
            )
        except Exception:
            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin)
            )

        await callback.answer()

    except Exception as e:

        logging.exception("Profil xatosi")

        await callback.answer(
            f"Xatolik: {e}",
            show_alert=True
        )


# ============================================================
# TOP UP
# ============================================================

@router.callback_query(F.data == "top_up")
async def top_up_handler(
    callback: CallbackQuery,
    state: FSMContext
):

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT value FROM settings WHERE key = 'card'"
    )

    card_row = cursor.fetchone()

    if card_row and card_row[0]:
        card = card_row[0]
    else:
        card = "Karta admin tomonidan sozlanmagan"

    conn.close()

    await callback.message.answer(
        f"💳 <b>To'lov uchun karta:</b>\n\n"
        f"<code>{card}</code>\n\n"
        f"Iltimos, qancha summa o'tkazganingizni "
        f"raqamlarda yozib yuboring.",
        parse_mode="HTML"
    )

    await state.set_state(
        PaymentState.waiting_for_amount
    )

    await callback.answer()


# ============================================================
# PAYMENT AMOUNT
# ============================================================

@router.message(PaymentState.waiting_for_amount)
async def process_amount(
    message: Message,
    state: FSMContext
):

    if not message.text or not message.text.isdigit():

        await message.answer(
            "❌ Iltimos, faqat raqamlardan iborat "
            "summani kiriting!"
        )

        return

    amount = int(message.text)

    if amount <= 0:

        await message.answer(
            "❌ Summa 0 dan katta bo'lishi kerak."
        )

        return

    await state.update_data(
        amount=amount
    )

    await message.answer(
        "📸 Endi o'tkazmani tasdiqlovchi "
        "chek rasmini yuboring."
    )

    await state.set_state(
        PaymentState.waiting_for_receipt
    )


# ============================================================
# RECEIPT
# ============================================================

@router.message(
    PaymentState.waiting_for_receipt,
    F.photo
)
async def process_receipt(
    message: Message,
    state: FSMContext
):

    data = await state.get_data()

    amount = data.get("amount")

    if not amount:

        await message.answer(
            "❌ To'lov summasi topilmadi. "
            "Qaytadan urinib ko'ring."
        )

        await state.clear()

        return

    photo_id = message.photo[-1].file_id

    user_id = message.from_user.id

    date = message.date.strftime(
        "%Y-%m-%d %H:%M"
    )

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO payments (
            user_id,
            amount,
            photo,
            status,
            date
        )
        VALUES (?, ?, ?, 'pending', ?)
    """, (
        user_id,
        amount,
        photo_id,
        date
    ))

    payment_id = cursor.lastrowid

    conn.commit()
    conn.close()

    admin_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Qabul qilish",
                    callback_data=f"accept_{payment_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Rad etish",
                    callback_data=f"reject_{payment_id}"
                )
            ]
        ]
    )

    await bot.send_photo(
        ADMIN_ID,
        photo=photo_id,
        caption=(
            f"🔔 <b>Yangi to'lov!</b>\n\n"
            f"👤 Foydalanuvchi: "
            f"<code>{user_id}</code>\n"
            f"💰 Summa: {amount} so'm\n"
            f"🧾 To'lov ID: {payment_id}"
        ),
        reply_markup=admin_kb,
        parse_mode="HTML"
    )

    await message.answer(
        "✅ Chekingiz adminga yuborildi.\n\n"
        "Tasdiqlanishini kuting."
    )

    await state.clear()


# ============================================================
# RECEIPT ERROR
# ============================================================

@router.message(
    PaymentState.waiting_for_receipt
)
async def receipt_not_photo(message: Message):

    await message.answer(
        "📸 Iltimos, o'tkazma chekini "
        "rasm ko'rinishida yuboring."
    )


# ============================================================
# ACCEPT PAYMENT
# ============================================================

@router.callback_query(
    F.data.startswith("accept_")
)
async def accept_payment(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "❌ Siz admin emassiz!",
            show_alert=True
        )

        return

    try:
        payment_id = int(
            callback.data.split("_")[1]
        )
    except Exception:

        await callback.answer(
            "❌ Noto'g'ri to'lov ID.",
            show_alert=True
        )

        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id, amount, status
        FROM payments
        WHERE id = ?
    """, (payment_id,))

    payment = cursor.fetchone()

    if not payment:

        conn.close()

        await callback.answer(
            "❌ To'lov topilmadi.",
            show_alert=True
        )

        return

    user_id, amount, status = payment

    if status != "pending":

        conn.close()

        await callback.answer(
            "⚠️ Bu to'lov allaqachon ko'rib chiqilgan.",
            show_alert=True
        )

        return

    cursor.execute("""
        UPDATE users
        SET balance = balance + ?
        WHERE user_id = ?
    """, (
        amount,
        user_id
    ))

    cursor.execute("""
        UPDATE payments
        SET status = 'accepted'
        WHERE id = ?
    """, (payment_id,))

    conn.commit()
    conn.close()

    await bot.send_message(
        user_id,
        f"✅ Sizning {amount} so'm to'lovingiz "
        f"tasdiqlandi va balansingizga qo'shildi!"
    )

    try:

        old_caption = callback.message.caption or ""

        await callback.message.edit_caption(
            caption=(
                old_caption +
                "\n\n<b>STATUS: Qabul qilindi ✅</b>"
            ),
            parse_mode="HTML"
        )

    except Exception:
        pass

    await callback.answer(
        "To'lov tasdiqlandi!"
    )


# ============================================================
# REJECT PAYMENT
# ============================================================

@router.callback_query(
    F.data.startswith("reject_")
)
async def reject_payment(
    callback: CallbackQuery,
    state: FSMContext
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "❌ Siz admin emassiz!",
            show_alert=True
        )

        return

    try:

        payment_id = int(
            callback.data.split("_")[1]
        )

    except Exception:

        await callback.answer(
            "❌ Noto'g'ri to'lov ID.",
            show_alert=True
        )

        return

    await state.update_data(
        payment_id=payment_id
    )

    await callback.message.answer(
        "❌ Rad etish sababini yozib yuboring:"
    )

    await state.set_state(
        AdminReject.waiting_for_reason
    )

    await callback.answer()


# ============================================================
# REJECT REASON
# ============================================================

@router.message(
    AdminReject.waiting_for_reason
)
async def process_reject_reason(
    message: Message,
    state: FSMContext
):

    if message.from_user.id != ADMIN_ID:
        return

    data = await state.get_data()

    payment_id = data.get("payment_id")

    reason = (
        message.text
        if message.text
        else "Sabab ko'rsatilmagan."
    )

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id, status
        FROM payments
        WHERE id = ?
    """, (payment_id,))

    payment = cursor.fetchone()

    if not payment:

        conn.close()

        await message.answer(
            "❌ To'lov topilmadi."
        )

        await state.clear()

        return

    user_id, status = payment

    if status != "pending":

        conn.close()

        await message.answer(
            "⚠️ Bu to'lov allaqachon ko'rib chiqilgan."
        )

        await state.clear()

        return

    cursor.execute("""
        UPDATE payments
        SET status = 'rejected'
        WHERE id = ?
    """, (payment_id,))

    conn.commit()
    conn.close()

    await bot.send_message(
        user_id,
        f"❌ Sizning to'lovingiz rad etildi.\n\n"
        f"Sabab: {reason}"
    )

    await message.answer(
        "✅ Foydalanuvchiga rad etish sababi yuborildi."
    )

    await state.clear()


# ============================================================
# SHOP
# ============================================================

@router.callback_query(
    F.data == "shop"
)
async def shop_handler(
    callback: CallbackQuery
):

    kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📦 1 Haftalik obuna - 10,000 so'm",
                    callback_data="buy_sub_7"
                )
            ],
            [
                InlineKeyboardButton(
                    text="📦 1 Oylik obuna - 30,000 so'm",
                    callback_data="buy_sub_30"
                )
            ],
            [
                InlineKeyboardButton(
                    text="🔙 Orqaga",
                    callback_data="back_main"
                )
            ]
        ]
    )

    text = (
        "🛒 <b>Obuna do'koniga xush kelibsiz.</b>\n\n"
        "Obuna turini tanlang:"
    )

    try:

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=kb
        )

    except Exception:

        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=kb
        )

    await callback.answer()


# ============================================================
# BUY SUBSCRIPTION
# ============================================================

@router.callback_query(
    F.data.startswith("buy_sub_")
)
async def buy_subscription(
    callback: CallbackQuery
):

    try:

        days = int(
            callback.data.split("_")[2]
        )

        if days == 7:
            price = 10000
        elif days == 30:
            price = 30000
        else:

            await callback.answer(
                "❌ Noto'g'ri obuna.",
                show_alert=True
            )

            return

        user_id = callback.from_user.id

        now = datetime.datetime.now()

        expire_date = (
            now +
            datetime.timedelta(days=days)
        ).strftime("%Y-%m-%d")

        conn = sqlite3.connect(DB_FILE)
        cursor = conn.cursor()

        cursor.execute("""
            SELECT balance
            FROM users
            WHERE user_id = ?
        """, (user_id,))

        user_row = cursor.fetchone()

        if not user_row:

            cursor.execute("""
                INSERT INTO users (
                    user_id,
                    joined_date,
                    balance,
                    api_key,
                    sub_active,
                    sub_expire
                )
                VALUES (?, ?, 0, '', 0, '')
            """, (
                user_id,
                now.strftime("%Y-%m-%d")
            ))

            conn.commit()

            balance = 0

        else:

            balance = user_row[0]

        if balance < price:

            conn.close()

            await callback.answer(
                "❌ Balansingizda yetarli mablag' yo'q!",
                show_alert=True
            )

            return

        cursor.execute("""
            UPDATE users
            SET
                balance = balance - ?,
                sub_active = 1,
                sub_expire = ?
            WHERE user_id = ?
        """, (
            price,
            expire_date,
            user_id
        ))

        conn.commit()
        conn.close()

        is_admin = user_id == ADMIN_ID

        text = (
            "✅ <b>Muvaffaqiyatli obuna sotib oldingiz!</b>\n\n"
            f"📦 Muddati: {days} kun\n"
            f"💰 Narxi: {price} so'm\n"
            f"📅 Tugash vaqti: {expire_date}"
        )

        try:

            await callback.message.edit_text(
                text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin)
            )

        except Exception:

            await callback.message.answer(
                text,
                parse_mode="HTML",
                reply_markup=main_menu(is_admin)
            )

        await callback.answer(
            "Tabriklaymiz!",
            show_alert=True
        )

    except Exception as e:

        logging.exception(
            "Obuna xatosi"
        )

        await callback.answer(
            f"Xatolik: {e}",
            show_alert=True
        )


# ============================================================
# GET API
# ============================================================

@router.callback_query(
    F.data == "get_api"
)
async def get_api_handler(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            api_key,
            sub_active,
            sub_expire
        FROM users
        WHERE user_id = ?
    """, (user_id,))

    user = cursor.fetchone()

    if not user:

        conn.close()

        await callback.message.answer(
            "❌ Profil topilmadi. /start ni bosing."
        )

        await callback.answer()

        return

    api_key, sub_active, sub_expire = user

    if sub_active == 1 and sub_expire:

        try:

            expire = datetime.datetime.strptime(
                sub_expire,
                "%Y-%m-%d"
            )

            if datetime.datetime.now() >= expire:

                cursor.execute("""
                    UPDATE users
                    SET sub_active = 0
                    WHERE user_id = ?
                """, (user_id,))

                conn.commit()

                sub_active = 0

        except Exception:
            pass

    if sub_active == 0:

        conn.close()

        await callback.message.answer(
            "⚠️ API ishlashi uchun avval "
            "obuna sotib olishingiz kerak!"
        )

        await callback.answer()

        return

    if not api_key:

        api_key = str(uuid.uuid4())

        cursor.execute("""
            UPDATE users
            SET api_key = ?
            WHERE user_id = ?
        """, (
            api_key,
            user_id
        ))

        conn.commit()

    conn.close()

    await callback.message.answer(
        f"🔑 <b>Sizning API kalitingiz:</b>\n\n"
        f"<code>{api_key}</code>\n\n"
        f"📡 API xizmatlari faol.",
        parse_mode="HTML"
    )

    await callback.answer()


# ============================================================
# REFRESH API
# ============================================================

@router.callback_query(
    F.data == "refresh_api"
)
async def refresh_api_handler(
    callback: CallbackQuery
):

    user_id = callback.from_user.id

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT
            sub_active,
            sub_expire
        FROM users
        WHERE user_id = ?
    """, (user_id,))

    sub = cursor.fetchone()

    if not sub:

        conn.close()

        await callback.message.answer(
            "❌ Profil topilmadi."
        )

        await callback.answer()

        return

    sub_active, sub_expire = sub

    if sub_active == 1 and sub_expire:

        try:

            expire = datetime.datetime.strptime(
                sub_expire,
                "%Y-%m-%d"
            )

            if datetime.datetime.now() >= expire:

                cursor.execute("""
                    UPDATE users
                    SET sub_active = 0
                    WHERE user_id = ?
                """, (user_id,))

                conn.commit()

                sub_active = 0

        except Exception:
            pass

    if sub_active == 0:

        conn.close()

        await callback.message.answer(
            "⚠️ API yangilash uchun "
            "obunangiz faol bo'lishi kerak!"
        )

        await callback.answer()

        return

    new_api_key = str(uuid.uuid4())

    cursor.execute("""
        UPDATE users
        SET api_key = ?
        WHERE user_id = ?
    """, (
        new_api_key,
        user_id
    ))

    conn.commit()
    conn.close()

    await callback.message.answer(
        f"🔄 <b>Yangi API kalit yaratildi:</b>\n\n"
        f"<code>{new_api_key}</code>",
        parse_mode="HTML"
    )

    await callback.answer(
        "API yangilandi!"
    )


# ============================================================
# ADMIN PANEL
# ============================================================

@router.callback_query(
    F.data == "admin_panel"
)
async def admin_panel_handler(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "❌ Siz admin emassiz!",
            show_alert=True
        )

        return

    text = (
        "👑 <b>ADMIN PANEL</b>\n\n"
        "Kerakli bo'limni tanlang:"
    )

    try:

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=admin_menu_kb()
        )

    except Exception:

        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=admin_menu_kb()
        )

    await callback.answer()


# ============================================================
# ADMIN STATISTICS
# ============================================================

@router.callback_query(
    F.data == "adm_stats"
)
async def adm_stats(
    callback: CallbackQuery
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "❌ Ruxsat yo'q.",
            show_alert=True
        )

        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute(
        "SELECT COUNT(*) FROM users"
    )

    users_count = cursor.fetchone()[0]

    cursor.execute("""
        SELECT SUM(amount)
        FROM payments
        WHERE status = 'accepted'
    """)

    total_income = cursor.fetchone()[0] or 0

    cursor.execute("""
        SELECT COUNT(*)
        FROM users
        WHERE sub_active = 1
    """)

    active_subs = cursor.fetchone()[0]

    conn.close()

    text = (
        "📊 <b>Statistika</b>\n\n"
        f"👥 Jami foydalanuvchilar: {users_count} ta\n"
        f"📦 Faol obunalar: {active_subs} ta\n"
        f"💰 Jami tushgan mablag': {total_income} so'm"
    )

    try:

        await callback.message.edit_text(
            text,
            parse_mode="HTML",
            reply_markup=admin_menu_kb()
        )

    except Exception:

        await callback.message.answer(
            text,
            parse_mode="HTML",
            reply_markup=admin_menu_kb()
        )

    await callback.answer()


# ============================================================
# ADMIN BALANCE
# ============================================================

@router.callback_query(
    F.data == "adm_balance"
)
async def adm_balance_start(
    callback: CallbackQuery,
    state: FSMContext
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "❌ Ruxsat yo'q.",
            show_alert=True
        )

        return

    await callback.message.answer(
        "👤 Foydalanuvchining Telegram ID "
        "raqamini kiriting:"
    )

    await state.set_state(
        AdminBalanceState.waiting_for_user_id
    )

    await callback.answer()


# ============================================================
# ADMIN USER ID
# ============================================================

@router.message(
    AdminBalanceState.waiting_for_user_id
)
async def adm_balance_uid(
    message: Message,
    state: FSMContext
):

    if message.from_user.id != ADMIN_ID:
        return

    if not message.text or not message.text.isdigit():

        await message.answer(
            "❌ ID faqat raqamlardan iborat "
            "bo'lishi kerak!"
        )

        return

    target_id = int(message.text)

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT user_id
        FROM users
        WHERE user_id = ?
    """, (target_id,))

    exists = cursor.fetchone()

    conn.close()

    if not exists:

        await message.answer(
            "❌ Bu Telegram ID bilan "
            "foydalanuvchi topilmadi."
        )

        return

    await state.update_data(
        target_id=target_id
    )

    await message.answer(
        "💰 Qancha summa qo'shmoqchisiz?\n\n"
        "➕ Qo'shish: <code>10000</code>\n"
        "➖ Ayirish: <code>-5000</code>",
        parse_mode="HTML"
    )

    await state.set_state(
        AdminBalanceState.waiting_for_amount
    )


# ============================================================
# ADMIN BALANCE FINISH
# ============================================================

@router.message(
    AdminBalanceState.waiting_for_amount
)
async def adm_balance_finish(
    message: Message,
    state: FSMContext
):

    if message.from_user.id != ADMIN_ID:
        return

    try:

        amount = int(message.text)

    except (ValueError, TypeError):

        await message.answer(
            "❌ Faqat raqam kiriting!"
        )

        return

    data = await state.get_data()

    target_id = data.get("target_id")

    if not target_id:

        await message.answer(
            "❌ Foydalanuvchi ID topilmadi."
        )

        await state.clear()

        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        SELECT balance
        FROM users
        WHERE user_id = ?
    """, (target_id,))

    row = cursor.fetchone()

    if not row:

        conn.close()

        await message.answer(
            "❌ Foydalanuvchi topilmadi."
        )

        await state.clear()

        return

    old_balance = row[0]

    new_balance = old_balance + amount

    if new_balance < 0:

        conn.close()

        await message.answer(
            "❌ Balansni manfiy qilish mumkin emas."
        )

        return

    cursor.execute("""
        UPDATE users
        SET balance = ?
        WHERE user_id = ?
    """, (
        new_balance,
        target_id
    ))

    conn.commit()
    conn.close()

    await message.answer(
        f"✅ <b>Balans o'zgartirildi!</b>\n\n"
        f"👤 ID: <code>{target_id}</code>\n"
        f"💰 Eski balans: {old_balance} so'm\n"
        f"🔄 O'zgarish: {amount} so'm\n"
        f"💵 Yangi balans: {new_balance} so'm",
        parse_mode="HTML"
    )

    try:

        await bot.send_message(
            target_id,
            f"💰 Balansingiz admin tomonidan "
            f"o'zgartirildi.\n\n"
            f"🔄 O'zgarish: {amount} so'm\n"
            f"💵 Yangi balans: {new_balance} so'm"
        )

    except Exception:
        pass

    await state.clear()


# ============================================================
# ADMIN CARD
# ============================================================

@router.callback_query(
    F.data == "adm_card"
)
async def adm_card_start(
    callback: CallbackQuery,
    state: FSMContext
):

    if callback.from_user.id != ADMIN_ID:

        await callback.answer(
            "❌ Ruxsat yo'q.",
            show_alert=True
        )

        return

    await callback.message.answer(
        "💳 Yangi karta raqamini kiriting.\n\n"
        "Masalan:\n"
        "<code>9860 1234 5678 9012</code>",
        parse_mode="HTML"
    )

    await state.set_state(
        AdminCardState.waiting_for_new_card
    )

    await callback.answer()


# ============================================================
# SAVE CARD
# ============================================================

@router.message(
    AdminCardState.waiting_for_new_card
)
async def adm_card_finish(
    message: Message,
    state: FSMContext
):

    if message.from_user.id != ADMIN_ID:
        return

    new_card = (message.text or "").strip()

    if not new_card:

        await message.answer(
            "❌ Karta raqamini kiriting."
        )

        return

    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO settings (key, value)
        VALUES ('card', ?)
        ON CONFLICT(key)
        DO UPDATE SET value = excluded.value
    """, (
        new_card,
    ))

    conn.commit()
    conn.close()

    await message.answer(
        f"✅ Karta raqami muvaffaqiyatli o'zgartirildi:\n\n"
        f"<code>{new_card}</code>",
        parse_mode="HTML"
    )

    await state.clear()


# ============================================================
# RENDER WEB SERVICE HEALTH SERVER
# ============================================================

class HealthHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header(
            "Content-Type",
            "text/plain; charset=utf-8"
        )

        self.end_headers()

        self.wfile.write(
            b"API BOT ISHLAYAPTI"
        )

    def log_message(self, format, *args):
        pass


def start_health_server():

    server = HTTPServer(
        ("0.0.0.0", PORT),
        HealthHandler
    )

    logging.info(
        f"Render health server {PORT} portda ishga tushdi."
    )

    server.serve_forever()


# ============================================================
# MAIN
# ============================================================

async def main():

    health_thread = threading.Thread(
        target=start_health_server,
        daemon=True
    )

    health_thread.start()

    dp = Dispatcher()

    dp.include_router(router)

    logging.info(
        "Telegram bot ishga tushmoqda..."
    )

    await bot.delete_webhook(
        drop_pending_updates=True
    )

    await dp.start_polling(bot)


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":

    logging.basicConfig(
        level=logging.INFO
    )

    try:

        asyncio.run(main())

    except KeyboardInterrupt:

        logging.info(
            "Bot to'xtatildi."
        )
