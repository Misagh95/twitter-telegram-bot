<p align="center">
  <img src="https://upload.wikimedia.org/wikipedia/commons/f/fd/State_flag_of_Iran_%281964%E2%80%931980%29.svg" width="110" alt="Lion and Sun Flag of Iran">
</p>

# 🐦 ربات تلگرام فالوور توییتر / X

> بدون X API هم کار می‌کند: RSSHub عمومی و آینه‌های RSS را امتحان می‌کند. پایداری این منابع تضمین‌شده نیست؛ X API رسمی اختیاری است.
> هر وقت اکانت‌هایی که اضافه کردی توییت جدید بزنن، مستقیم داخل تلگرام برات میفرسته. با متن + عکس + ترجمه فارسی.

---

### ✨ امکانات

- 🔔 ارسال خودکار توییت‌ها به تلگرام با عکس
- 🦁 ترجمه فارسی خودکار (با هوش مصنوعی یا Google Translate)
- 🚫 فیلتر خودکار ریتوییت‌ها / repostها (بدون افتادن اکانت‌هایی که نام نمایشی‌شان شبیه یوزرنیم است، مثل RippleX)
- 📊 داشبورد وب زنده (PWA)
- ⚡ پشتیبانی از چندین اکانت با دریافت و ترجمه کنترل‌شده برای جلوگیری از محدودیت سرویس‌ها
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
DATABASE_URL=آدرس PostgreSQL
# اختیاری: فقط اگر دسترسی X API داری
# X_BEARER_TOKEN=توکن Bearer از X Developer Portal
# اختیاری: آدرس یک RSSHub دیگر
# RSSHUB_BASE_URL=https://rsshub.app
ADMIN_CHAT_ID=چت آیدی خودت (اختیاری)

# ترجمه فارسی (اختیاری)
TRANSLATE_FA=true
# می‌تونی REQUESTY_API_KEY یا GEMINI_API_KEY استفاده کنی
REQUESTY_API_KEY=your_requesty_or_gemini_key
REQUESTY_BASE_URL=https://api.openai.com/v1
REQUESTY_MODEL=gpt-4o-mini
```

`X_BEARER_TOKEN` اجباری نیست؛ بدون آن ربات از RSSHub عمومی (`https://rsshub.app/twitter/user/<username>`) و سپس آینه‌های دیگر استفاده می‌کند. این سرویس‌های عمومی ممکن است محدود یا قطع شوند. اگر X API داری، می‌توانی Bearer Token را در Railway Variables تنظیم کنی؛ هرگز آن را در چت یا Git قرار نده. برای استفاده از RSSHub دیگری، `RSSHUB_BASE_URL` را تغییر بده.

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
4. در Variables سرویس، `TELEGRAM_BOT_TOKEN` را تنظیم کن. `X_BEARER_TOKEN` اختیاری است؛ بدون آن ربات RSSHub و RSSهای عمومی را امتحان می‌کند.

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
| `X_BEARER_TOKEN` | خالی | اختیاری؛ با تنظیم آن دریافت timeline از X API انجام می‌شود |
| `X_API_BASE_URL` | `https://api.x.com/2` | ریشهٔ API نسخهٔ ۲ X |
| `X_USER_ID_CACHE_TTL` | `86400` | مدت نگهداری شناسهٔ کاربر X در حافظه (ثانیه) |
| `RSSHUB_BASE_URL` | `https://rsshub.app` | آدرس RSSHub که در حالت بدون X API همراه دیگر منابع RSS امتحان می‌شود |
| `HTTP_MAX_CONNECTIONS` | `50` | اندازهٔ pool اتصال HTTP؛ برای درخواست‌های RSS ظرفیت اضافه نگه می‌دارد |
| `RSS_FETCH_TIMEOUT` | `12` | حداکثر زمان بررسی آینه‌های RSS برای هر حساب (ثانیه) |
| `RSS_MERGE_GRACE` | `0.25` | زمان کوتاه برای ادغام پاسخ آینه‌های سریع پس از اولین فید قابل‌استفاده |
| `CHECK_INTERVAL` | `300` | فاصله بررسی (ثانیه) |
| `REQUESTY_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` | خالی | کلید سرویس AI برای ترجمه باکیفیت‌تر |
| `CONCURRENT_LIMIT` | `3` | تعداد حساب‌هایی که هم‌زمان بررسی می‌شوند |
| `RSS_FETCH_CONCURRENCY` | `12` | سقف کلی درخواست‌های هم‌زمان RSS برای جلوگیری از PoolTimeout |
| `TRANSLATION_TIMEOUT` | `20` | تایم‌اوت هر تلاش ترجمه (ثانیه) |
| `TRANSLATION_DELIVERY_TIMEOUT` | `15` | حداکثر انتظار برای ترجمه؛ بعدش متن اصلی ارسال می‌شود |
| `TRANSLATION_RETRIES` | `2` | تعداد تلاش دوباره برای تلاش‌های اصلی AI/Google |
| `TRANSLATION_CONCURRENT_LIMIT` | `1` | تعداد ترجمه همزمان (برای جلوگیری از محدودیت گوگل کم نگه دار) |
| `TRANSLATION_BACKFILL_LIMIT` | `15` | تعداد توییت‌های بدون ترجمه که در هر نوبت ترمیم می‌شوند |
| `MAX_TWEETS_PER_CHECK` | `10` | تعداد پست‌های ارسال‌شده برای هر حساب در هر نوبت؛ بقیهٔ موارد در نوبت بعد ادامه می‌یابد |
| `MYMEMORY_SOURCE_LANG` | `en` | زبان مبدأ برای fallback غیرگوگلی ترجمه |
| `MYMEMORY_EMAIL` | خالی | ایمیل اختیاری برای سقف رایگان بالاتر MyMemory |
| `LOG_LEVEL` | `INFO` | روی `DEBUG` بگذار تا دلیل نگه‌داشتن یا حذف هر آیتم فید لاگ شود |

---

### 📝 نکات

- اکانت‌های **خصوصی / Private** بدون دسترسی مناسب X API/RSS قابل‌خواندن نیستند
- با تنظیم `X_BEARER_TOKEN` ربات از X API رسمی استفاده می‌کند؛ بدون آن RSSHub عمومی و RSSهای دیگر را امتحان می‌کند، اما دسترسی این منابع عمومی تضمینی نیست
- ریتوییت‌ها/repostها فیلتر میشن و ارسال نمیشن؛ فیلتر فقط به یوزرنیم واقعی (یعنی لینک استاتوس یا `@handle` موجود در فید) نگاه می‌کنه و نام نمایشی هرگز جای یوزرنیم حساب نمیشه
- با `LOG_LEVEL=DEBUG` دلیل حذف هر توییت لاگ میشه (مثلاً `Skip @nasa 123: status link is @nasa`)
- هر توییت به صورت یک کارت تکی در تلگرام ارسال می‌شود؛ در صورت طولانی شدن کپشن، متن و ترجمه به صورت خودکار خلاصه می‌شوند و هرگز پیام جداگانه‌ای ارسال نمی‌شود
- ترجمه با چند بار تلاش دوباره انجام میشه و اگر AI خطا بده، از Google/MyMemory fallback استفاده میشه
- توییت‌های ذخیره‌شده‌ای که ترجمه خالی دارند، به صورت خودکار در پس‌زمینه برای دیتابیس و داشبورد بک‌فیل می‌شوند و پیام جداگانه به تلگرام فرستاده نمی‌شود
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
