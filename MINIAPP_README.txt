DONUZ TELEGRAM MINI APP — DEPLOY

Fayllar:
- bot.py
- templates/miniapp.html
- static/miniapp.css
- static/miniapp.js

1) Render loyihangizdagi eski bot.py ni ushbu bot.py bilan almashtiring.
2) templates va static papkalarini ham loyihaning asosiy papkasiga yuklang.
3) Render Environment bo'limida quyidagini qo'shing:
   WEB_APP_URL=https://SIZNING-RENDER-MANZILINGIZ
   Masalan: WEB_APP_URL=https://sayt-q1rl.onrender.com
4) Mavjud BOT_TOKEN, ADMIN_ID, DATABASE_URL, BAY2GAME_API_KEY va PLAYPAY_API_KEY qiymatlarini saqlang.
5) Start Command: python bot.py
6) Deploy qiling. Bot ishga tushganda Telegram menyu tugmasini Mini App URL ga ulashga urinadi.
7) Botda avval /start bosing, keyin pastdagi menyu tugmasidan Donuz Mini App ni oching.

Eslatma:
- Mini App Telegram initData HMAC orqali serverda tekshiriladi; client yuborgan Telegram ID ga ishonilmaydi.
- Bot foydalanuvchisi bazada bo'lishi kerak. Yangi foydalanuvchi avval botda /start bosadi.
- Katalog, balans, ID tekshirish va buyurtma amaldagi bot API/funksiyalaridan foydalanadi.
- Buyurtmalar eski sozlamangizga muvofiq order jadvaliga yozilmaydi; mijoz va ORDER_CHANNEL_ID kanaliga xabar yuboriladi.
- Web App HTTPS manzilda ishlashi shart.
