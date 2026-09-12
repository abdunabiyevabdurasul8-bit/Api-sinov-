import asyncio
import logging
import sqlite3
import uuid
import datetime
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

TOKEN = "8799964859:AAFX6MswBkHq5Cp9BIg0Xb4j_VEqcuSox24"
ADMIN_ID = 5692925792

bot = Bot(token=TOKEN)
router = Router()

def db_start():
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            joined_date TEXT,
            balance INTEGER DEFAULT 0,
            api_key TEXT,
            sub_active INTEGER DEFAULT 0,
            sub_expire TEXT
        )
    ''')
    
    # Eski bazalarda ustunlar yetishmasa avtomatik qo'shish uchun
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN sub_active INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN sub_expire TEXT")
    except sqlite3.OperationalError:
        pass
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN api_key TEXT")
    except sqlite3.OperationalError:
        pass

    cursor.execute('''
        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            photo TEXT,
            status TEXT,
            date TEXT
        )
    ''')
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('card', '')")
    conn.commit()
    conn.close()

db_start()

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

def main_menu(is_admin=False):
    kb = [
        [InlineKeyboardButton(text="👤 Profil", callback_data="profile"), InlineKeyboardButton(text="💳 Balansni to'ldirish", callback_data="top_up")],
        [InlineKeyboardButton(text="🛒 Obuna sotib olish", callback_data="shop"), InlineKeyboardButton(text="🔑 API olish", callback_data="get_api")],
        [InlineKeyboardButton(text="⚙️ API yangilash", callback_data="refresh_api")]
    ]
    if is_admin:
        kb.append([InlineKeyboardButton(text="👑 ADMIN PANEL", callback_data="admin_panel")])
    return InlineKeyboardMarkup(inline_keyboard=kb)

def admin_menu_kb():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Balansni +/-", callback_data="adm_balance"), InlineKeyboardButton(text="💳 Karta sozlash", callback_data="adm_card")],
        [InlineKeyboardButton(text="📊 Statistika", callback_data="adm_stats"), InlineKeyboardButton(text="🔙 Asosiy menyu", callback_data="back_main")]
    ])

@router.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    joined_date = message.date.strftime("%Y-%m-%d")
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user:
        cursor.execute("INSERT INTO users (user_id, joined_date, balance, api_key, sub_active, sub_expire) VALUES (?, ?, 0, '', 0, '')", (user_id, joined_date))
        conn.commit()
    conn.close()
    
    is_admin = (user_id == ADMIN_ID)
    await message.answer(
        f"Assalomu alaykum, {message.from_user.first_name}!\nAPI xizmatlari botiga xush kelibsiz.",
        reply_markup=main_menu(is_admin)
    )

@router.callback_query(F.data == "back_main")
async def back_main(callback: CallbackQuery):
    is_admin = (callback.from_user.id == ADMIN_ID)
    try:
        await callback.message.edit_text("Asosiy menyu:", reply_markup=main_menu(is_admin))
    except Exception:
        await callback.message.answer("Asosiy menyu:", reply_markup=main_menu(is_admin))
    await callback.answer()

@router.callback_query(F.data == "profile")
async def profile_handler(callback: CallbackQuery):
    try:
        user_id = callback.from_user.id
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT joined_date, balance, sub_active, sub_expire FROM users WHERE user_id = ?", (user_id,))
        user = cursor.fetchone()
        
        if not user:
            date_str = datetime.datetime.now().strftime("%Y-%m-%d")
            cursor.execute("INSERT INTO users (user_id, joined_date, balance, api_key, sub_active, sub_expire) VALUES (?, ?, 0, '', 0, '')", (user_id, date_str))
            conn.commit()
            user = (date_str, 0, 0, "")
        conn.close()
        
        sub_status = f"Faol ✅ (Tugash vaqti: {user[3]})" if user[2] == 1 else "Faol emas ❌"
        text = (
            f"👤 **Profil Ma'lumotlari:**\n\n"
            f"🆔 ID: `{user_id}`\n"
            f"📅 Qo'shilgan sana: {user[0]}\n"
            f"💰 Balans: {user[1]} so'm\n"
            f"📦 Obuna holati: {sub_status}"
        )
        is_admin = (user_id == ADMIN_ID)
        
        try:
            await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=main_menu(is_admin))
        except Exception:
            await callback.message.answer(text, parse_mode="Markdown", reply_markup=main_menu(is_admin))
            
        await callback.answer()
    except Exception as e:
        logging.error(f"Profil xatosi: {e}")
        await callback.answer(f"Xatolik: {e}", show_alert=True)

@router.callback_query(F.data == "top_up")
async def top_up_handler(callback: CallbackQuery, state: FSMContext):
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = 'card'")
    card_row = cursor.fetchone()
    card = card_row[0] if card_row else "8600 0000 0000 0000"
    conn.close()
    
    await callback.message.answer(f"💳 To'lov uchun karta raqam:\n`{card}`\n\nIltimos, qancha summa o'tkazganingizni raqamlarda yozib yuboring:")
    await state.set_state(PaymentState.waiting_for_amount)
    await callback.answer()

@router.message(PaymentState.waiting_for_amount)
async def process_amount(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Iltimos, faqat raqamlardan iborat summani kiriting!")
        return
    await state.update_data(amount=int(message.text))
    await message.answer("Endi o'tkazmani tasdiqlovchi chek rasmini yuboring:")
    await state.set_state(PaymentState.waiting_for_receipt)

@router.message(PaymentState.waiting_for_receipt, F.photo)
async def process_receipt(message: Message, state: FSMContext):
    data = await state.get_data()
    amount = data.get("amount")
    photo_id = message.photo[-1].file_id
    user_id = message.from_user.id
    date = message.date.strftime("%Y-%m-%d %H:%M")
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("INSERT INTO payments (user_id, amount, photo, status, date) VALUES (?, ?, ?, 'pending', ?)", (user_id, amount, photo_id, date))
    payment_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    admin_kb = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="✅ Qabul qilish", callback_data=f"accept_{payment_id}"),
            InlineKeyboardButton(text="❌ Rad etish", callback_data=f"reject_{payment_id}")
        ]
    ])
    
    await bot.send_photo(
        ADMIN_ID,
        photo=photo_id,
        caption=f"🔔 Yangi to'lov!\n\nFoydalanuvchi: `{user_id}`\nSumma: {amount} so'm",
        reply_markup=admin_kb,
        parse_mode="Markdown"
    )
    
    await message.answer("Chekingiz adminga yuborildi. Tasdiqlanishini kuting.")
    await state.clear()

@router.callback_query(F.data.startswith("accept_"))
async def accept_payment(callback: CallbackQuery):
    payment_id = int(callback.data.split("_")[1])
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, amount FROM payments WHERE id = ?", (payment_id,))
    payment = cursor.fetchone()
    
    if payment:
        user_id, amount = payment
        cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        cursor.execute("UPDATE payments SET status = 'accepted' WHERE id = ?", (payment_id,))
        conn.commit()
        
        await bot.send_message(user_id, f"✅ Sizning {amount} so'm to'lovingiz tasdiqlandi va balansingizga qo'shildi!")
        try:
            await callback.message.edit_caption(caption=callback.message.caption + "\n\n**STATUS: Qabul qilindi ✅**", parse_mode="Markdown")
        except Exception:
            pass
    conn.close()
    await callback.answer("To'lov tasdiqlandi!")

@router.callback_query(F.data.startswith("reject_"))
async def reject_payment(callback: CallbackQuery, state: FSMContext):
    payment_id = int(callback.data.split("_")[1])
    await state.update_data(payment_id=payment_id)
    await callback.message.answer("Rad etish sababini yozib yuboring:")
    await state.set_state(AdminReject.waiting_for_reason)
    await callback.answer()

@router.message(AdminReject.waiting_for_reason)
async def process_reject_reason(message: Message, state: FSMContext):
    data = await state.get_data()
    payment_id = data.get("payment_id")
    reason = message.text
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM payments WHERE id = ?", (payment_id,))
    payment = cursor.fetchone()
    
    if payment:
        user_id = payment[0]
        cursor.execute("UPDATE payments SET status = 'rejected' WHERE id = ?", (payment_id,))
        conn.commit()
        await bot.send_message(user_id, f"❌ Sizning to'lovingiz rad etildi.\nSabab: {reason}")
        await message.answer("Foydalanuvchiga rad etish sababi yuborildi.")
    conn.close()
    await state.clear()

@router.callback_query(F.data == "shop")
async def shop_handler(callback: CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📦 1 Haftalik obuna - 10,000 so'm", callback_data="buy_sub_7")],
        [InlineKeyboardButton(text="📦 1 Oylik obuna - 30,000 so'm", callback_data="buy_sub_30")],
        [InlineKeyboardButton(text="🔙 Orqaga", callback_data="back_main")]
    ])
    try:
        await callback.message.edit_text("🛒 Obuna do'koniga xush kelibsiz.\nObuna turini tanlang:", reply_markup=kb)
    except Exception:
        await callback.message.answer("🛒 Obuna do'koniga xush kelibsiz.\nObuna turini tanlang:", reply_markup=kb)
    await callback.answer()

@router.callback_query(F.data.startswith("buy_sub_"))
async def buy_subscription(callback: CallbackQuery):
    try:
        days = int(callback.data.split("_")[2])
        price = 10000 if days == 7 else 30000
        user_id = callback.from_user.id
        
        now = datetime.datetime.now()
        expire_date = (now + datetime.timedelta(days=days)).strftime("%Y-%m-%d")
        
        conn = sqlite3.connect("database.db")
        cursor = conn.cursor()
        cursor.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
        user_row = cursor.fetchone()
        
        if not user_row:
            cursor.execute("INSERT INTO users (user_id, joined_date, balance, api_key, sub_active, sub_expire) VALUES (?, ?, 0, '', 0, '')", (user_id, now.strftime("%Y-%m-%d")))
            conn.commit()
            balance = 0
        else:
            balance = user_row[0]
        
        if balance < price:
            await callback.answer("❌ Balansingizda yetarli mablag' yo'q!", show_alert=True)
            conn.close()
            return
        
        cursor.execute("UPDATE users SET balance = balance - ?, sub_active = 1, sub_expire = ? WHERE user_id = ?", (price, expire_date, user_id))
        conn.commit()
        conn.close()
        
        is_admin = (user_id == ADMIN_ID)
        text = f"✅ Muvaffaqiyatli obuna sotib oldingiz!\nAmal qilish muddati: {expire_date}"
        
        try:
            await callback.message.edit_text(text, reply_markup=main_menu(is_admin))
        except Exception:
            await callback.message.answer(text, reply_markup=main_menu(is_admin))
            
        await callback.answer("Tabriklaymiz!", show_alert=True)
    except Exception as e:
        logging.error(f"Obuna xatosi: {e}")
        await callback.answer(f"Xatolik: {e}", show_alert=True)

@router.callback_query(F.data == "get_api")
async def get_api_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT api_key, sub_active FROM users WHERE user_id = ?", (user_id,))
    user = cursor.fetchone()
    
    if not user or user[1] == 0:
        await callback.message.answer("⚠️ Kechirasiz, API ishlashi uchun avval obuna sotib olishingiz kerak!")
        await callback.answer()
        conn.close()
        return
    
    api_key = user[0]
    if not api_key:
        api_key = str(uuid.uuid4())
        cursor.execute("UPDATE users SET api_key = ? WHERE user_id = ?", (api_key, user_id))
        conn.commit()
        
    conn.close()
    await callback.message.answer(f"🔑 Sizning API kalitingiz:\n`{api_key}`\n\n*Hujjatlar va API xizmatlari faol.*", parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "refresh_api")
async def refresh_api_handler(callback: CallbackQuery):
    user_id = callback.from_user.id
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT sub_active FROM users WHERE user_id = ?", (user_id,))
    sub = cursor.fetchone()
    
    if not sub or sub[0] == 0:
        await callback.message.answer("⚠️ API yangilash uchun obunangiz faol bo'lishi kerak!")
        await callback.answer()
        conn.close()
        return

    new_api_key = str(uuid.uuid4())
    cursor.execute("UPDATE users SET api_key = ? WHERE user_id = ?", (new_api_key, user_id))
    conn.commit()
    conn.close()
    
    await callback.message.answer(f"🔄 Yangi API kalit muvaffaqiyatli yaratildi:\n`{new_api_key}`", parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "admin_panel")
async def admin_panel_handler(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Siz admin emassiz!", show_alert=True)
        return
    try:
        await callback.message.edit_text("👑 **ADMIN PANEL**", parse_mode="Markdown", reply_markup=admin_menu_kb())
    except Exception:
        await callback.message.answer("👑 **ADMIN PANEL**", parse_mode="Markdown", reply_markup=admin_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "adm_stats")
async def adm_stats(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID: return
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    users_count = cursor.fetchone()[0]
    cursor.execute("SELECT SUM(amount) FROM payments WHERE status = 'accepted'")
    total_income = cursor.fetchone()[0] or 0
    conn.close()
    
    text = (
        f"📊 **Statistika:**\n\n"
        f"👥 Jami foydalanuvchilar: {users_count} ta\n"
        f"💰 Jami tushgan mablag': {total_income} so'm"
    )
    try:
        await callback.message.edit_text(text, parse_mode="Markdown", reply_markup=admin_menu_kb())
    except Exception:
        await callback.message.answer(text, parse_mode="Markdown", reply_markup=admin_menu_kb())
    await callback.answer()

@router.callback_query(F.data == "adm_balance")
async def adm_balance_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("Foydalanuvchining Telegram ID raqamini kiriting:")
    await state.set_state(AdminBalanceState.waiting_for_user_id)
    await callback.answer()

@router.message(AdminBalanceState.waiting_for_user_id)
async def adm_balance_uid(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("ID faqat raqamlardan iborat bo'lishi kerak!")
        return
    await state.update_data(target_id=int(message.text))
    await message.answer("Qancha summa qo'shmoqchisiz? (Aybirmoqchi bo'lsangiz oldiga minus (-) qo'ying, masalan: `-5000`):")
    await state.set_state(AdminBalanceState.waiting_for_amount)

@router.message(AdminBalanceState.waiting_for_amount)
async def adm_balance_finish(message: Message, state: FSMContext):
    try:
        amount = int(message.text)
    except ValueError:
        await message.answer("Faqat raqam kiriting!")
        return
    
    data = await state.get_data()
    target_id = data.get("target_id")
    
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, target_id))
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ Foydalanuvchi (`{target_id}`) balansi muvaffaqiyatli o'zgartirildi: {amount} so'm", parse_mode="Markdown")
    await state.clear()

@router.callback_query(F.data == "adm_card")
async def adm_card_start(callback: CallbackQuery, state: FSMContext):
    if callback.from_user.id != ADMIN_ID: return
    await callback.message.answer("Yangi karta raqamini kiriting (masalan: `9860 1234 5678 9012`):", parse_mode="Markdown")
    await state.set_state(AdminCardState.waiting_for_new_card)
    await callback.answer()

@router.message(AdminCardState.waiting_for_new_card)
async def adm_card_finish(message: Message, state: FSMContext):
    new_card = message.text
    conn = sqlite3.connect("database.db")
    cursor = conn.cursor()
    cursor.execute("UPDATE settings SET value = ? WHERE key = 'card'", (new_card,))
    conn.commit()
    conn.close()
    
    await message.answer(f"✅ Karta raqami muvaffaqiyatli o'zgartirildi:\n`{new_card}`", parse_mode="Markdown")
    await state.clear()

async def main():
    dp = Dispatcher()
    dp.include_router(router)
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
