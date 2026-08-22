<p align="center">
  <img src="https://upload.wikimedia.org/wikipedia/commons/f/fd/State_flag_of_Iran_%281964%E2%80%931980%29.svg" width="110" alt="Lion and Sun Flag of Iran">
</p>

# 🐦 ربات تلگرام فالوور توییتر / X

> بدون نیاز به API پولی توییتر — با RSS کار میکنه.
> هر وقت اکانت‌هایی که اضافه کردی توییت جدید بزنن، مستقیم داخل تلگرام برات میفرسته. با متن + عکس + ترجمه فارسی.

---

### ✨ امکانات

- 🔔 ارسال خودکار توییت‌ها به تلگرام با عکس
- 🦁 ترجمه فارسی خودکار (با هوش مصنوعی یا Google Translate)
- 📊 داشبورد وب زنده (PWA)
- ⚡ پشتیبانی از ۵۰+ اکانت همزمان
- 🔄 بررسی خودکار هر ۵ دقیقه

---

### ۱. ساخت ربات تلگرام

1. برو به [@BotFather](https://t.me/BotFather) در تلگرام
2. بزن `/newbot` و اسم و یوزرنیم بده
3. توکنی که بهت میده رو کپی کن (چیزی مثل: `123456:ABC-DEF...`)

---

### ۲. نصب و راه‌اندازی

```bash
# کلون کردن پروژه
git clone https://github.com/YOUR_USER/twitter-telegram-bot.git
cd twitter-telegram-bot

# نصب وابستگی‌ها
pip install -r requirements.txt
```

یک فایل `.env` بساز و این داخلش بزار:

```env
TELEGRAM_BOT_TOKEN=توکنی که از BotFather گرفتی
ADMIN_CHAT_ID=چت آیدی خودت (اختیاری)

# ترجمه فارسی (اختیاری)
TRANSLATE_FA=true
REQUESTY_API_KEY=key
REQUESTY_BASE_URL=https://api.openai.com/v1
REQUESTY_MODEL=gpt-4o-mini
```

---

### ۳. تست لوکال

```bash
# اجرای مستقیم
python twitter_telegram_bot.py
```

ربات روشن میشه. یه پیام `/start` بفرست به رباتت توی تلگرام.

**دستورات تلگرام:**

| دستور | توضیح |
|-------|-------|
| `/start` | راهنما |
| `/add vitalikbuterin` | اضافه کردن اکانت |
| `/add user1 user2` | اضافه چند اکانت همزمان |
| `/del vitalikbuterin` | حذف اکانت |
| `/list` | لیست اکانت‌های دنبال‌شده |
| `/test` | تست سریع با @ElonMusk |

---

### ۴. دیتابیس (PostgreSQL)

برای استفاده از Railway رایگان:

1. Railway.app → یه پروژه بساز
2. PostgreSQL دیتابیس اضافه کن
3. متغیر `DATABASE_URL` خودکار ست میشه

---

### ۵. هاست ۲۴ ساعته رایگان

برای اینکه همیشه روشن باشه، روی یکی از اینها رایگان دیپلوی کن:

- **Railway.app** — ساده‌ترین (۵$ credit رایگان ماهانه)
- **Render.com** — plan رایگان
- یا روی یک سرور VPS خودت

فقط کافیه فایل‌ها رو آپلود کنی و متغیرهای محیطی رو ست کنی.

---

### ⚙️ تنظیمات

| متغیر | پیش‌فرض | توضیح |
|-------|---------|-------|
| `CHECK_INTERVAL` | `300` | فاصله بررسی (ثانیه) |
| `CONCURRENT_LIMIT` | `8` | تعداد درخواست همزمان |

---

### 📝 نکات

- اکانت‌های **خصوصی / Private** کار نمیکنن
- اگر یک Nitter فیلتر بود، ربات خودش از بقیه امتحان میکنه
- ترجمه فقط توییت‌های انگلیسی رو به فارسی ترجمه میکنه
- توییت‌ها با عکس هم ارسال میشن
- تصاویر با lazy loading در وب داشبورد بارگذاری میشن
- Service Worker برای حالت آفلاین فعاله

---

### 🛠 ساختار پروژه

```
twitter-telegram-bot/
├── twitter_telegram_bot.py   # ربات اصلی + وب سرور
├── database.py               # مدیریت PostgreSQL
├── web_server.py             # سرور وب (اختیاری)
├── templates/index.html      # قالب داشبورد وب
├── sw.js                     # Service Worker
├── manifest.json             # PWA Manifest
├── requirements.txt          # وابستگی‌ها
└── Procfile                  # فایل هاست
```
