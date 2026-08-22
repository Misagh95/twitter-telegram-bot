import os, asyncio, logging, feedparser, re, httpx, html, random, hashlib
from contextlib import asynccontextmanager
from dotenv import load_dotenv
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton, WebAppInfo,
    InlineQueryResultArticle, InputTextMessageContent,
)
from telegram.ext import Application, CommandHandler, InlineQueryHandler, ContextTypes
from telegram.constants import ParseMode
from database import Database
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.templating import Jinja2Templates
import uvicorn

load_dotenv()

BASE_PATH = os.path.dirname(os.path.abspath(__file__))
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))
CONCURRENT_LIMIT = 8

REQUESTY_API_KEY = os.getenv("REQUESTY_API_KEY", "").strip()
REQUESTY_BASE_URL = os.getenv("REQUESTY_BASE_URL", "https://api.17.wtf/v1").strip().rstrip("/")
REQUESTY_MODEL = os.getenv("REQUESTY_MODEL", "posiden/deepseek-v4-flash").strip()
TRANSLATE_FA = os.getenv("TRANSLATE_FA", "true").lower() in ("1", "true", "yes")

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database()
if not db.enabled:
    raise SystemExit("DATABASE_URL not found! Set it in .env")
app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(BASE_PATH, "templates"))

http: httpx.AsyncClient = None
bot_app_ref = None
translations_cache = {}

RSS_SOURCES = [
    "https://xcancel.com/{username}/rss",
    "https://nitter.privacydev.net/{username}/rss",
    "https://nitter.perennialte.ch/{username}/rss",
    "https://nitter.net/{username}/rss",
]
RSS_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"}


# ── Helpers ───────────────────────────────────────────────────────────────

def clean_username(raw):
    raw = (raw or "").strip().lower()
    raw = raw.replace("https://", "").replace("http://", "")
    for d in ["x.com/", "twitter.com/", "nitter.net/", "xcancel.com/", "uni-sonia.com/"]:
        raw = raw.replace(d, "")
    return raw.lstrip("@").split("?")[0].split("/")[0].strip()

def is_valid_twitter(u):
    return bool(re.match(r"^[a-z0-9_]{1,15}$", u))

def extract_id(entry):
    for key in ["id", "guid", "link"]:
        val = str(entry.get(key, ""))
        m = re.search(r"status(?:es)?/(\d+)", val)
        if m: return m.group(1)
        m2 = re.search(r"(\d{17,})", val)
        if m2: return m2.group(1)
    val = str(entry.get("id", ""))
    m3 = re.search(r"(\d+)$", val)
    if m3 and len(m3.group(1)) >= 10:
        return m3.group(1)
    return None

def extract_image_url(entry):
    desc = entry.get("description", "") or entry.get("summary", "")
    img_match = re.search(r'<img[^>]+src=["\']([^"\']+)["\']', desc, re.I)
    if img_match:
        url = img_match.group(1)
        if "/pic/media%2F" in url:
            media_id = url.split("%2F")[-1].split("?")[0]
            return f"https://pbs.twimg.com/media/{media_id}"
        return url
    if "media_content" in entry:
        return entry.media_content[0].get("url")
    return None


async def translate_text(text):
    if not TRANSLATE_FA or not text:
        return ""
    cache_key = hashlib.md5(text.encode()).hexdigest()
    if cache_key in translations_cache:
        return translations_cache[cache_key]
    result = ""
    if REQUESTY_API_KEY:
        try:
            base = REQUESTY_BASE_URL if "/v1" in REQUESTY_BASE_URL else f"{REQUESTY_BASE_URL}/v1"
            payload = {
                "model": REQUESTY_MODEL,
                "messages": [{"role": "user", "content": f"Translate this tweet to colloquial Persian (informal). Keep crypto terms English: {text[:1000]}"}],
                "temperature": 0.2,
            }
            resp = await http.post(f"{base}/chat/completions", headers={"Authorization": f"Bearer {REQUESTY_API_KEY}"}, json=payload)
            if resp.status_code == 200:
                result = resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as e:
            logger.warning(f"AI translate failed: {e}")
    if not result:
        try:
            from deep_translator import GoogleTranslator
            result = await asyncio.to_thread(GoogleTranslator(source="auto", target="fa").translate, text[:1500])
        except Exception as e:
            logger.warning(f"Google translate failed: {e}")
            result = ""
    if len(translations_cache) > 500:
        translations_cache.clear()
    translations_cache[cache_key] = result
    return result


async def fetch_feed(username):
    for src in RSS_SOURCES:
        url = src.format(username=username)
        try:
            resp = await http.get(url, timeout=10, follow_redirects=True)
            if resp.status_code != 200 or "uni-sonia" in str(resp.url):
                continue
            feed = await asyncio.to_thread(feedparser.parse, resp.text)
            valid = [e for e in feed.entries if extract_id(e)]
            if valid:
                return valid
        except Exception:
            continue
    return []


# ── Bot Commands ──────────────────────────────────────────────────────────

WELCOME = (
    "👋 <b>سلام!</b>\n\n"
    "ربات فالوور توییتر/X\n"
    "بدون نیاز به API پولی — با RSS کار میکنه.\n\n"
    "📌 <b>دستورات:</b>\n"
    "/add username  — اضافه کردن\n"
    "/del username  — حذف کردن\n"
    "/list  — لیست اکانت‌ها\n"
    "/test  — تست سریع\n"
    "/search متن  — جستجو در توییت‌ها\n\n"
    "💡 از کیبورد پایین هم میتونی استفاده کنی.\n"
    "🔍 <b>Inline Mode:</b> از هر چتی بنویس <code>@رباتت متن</code>"
)

MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("➕ اضافه کردن"), KeyboardButton("📋 لیست اکانت‌ها")],
        [KeyboardButton("🔍 جستجو"), KeyboardButton("🌐 داشبورد")],
        [KeyboardButton("🔄 بروزرسانی"), KeyboardButton("ℹ️ راهنما")],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="نام کاربری توییتر رو بنویس...",
)

DASHBOARD_URL = os.getenv("DASHBOARD_URL", "http://localhost:8080")


async def cmd_start(update, context):
    await update.message.reply_text(WELCOME, parse_mode=ParseMode.HTML, reply_markup=MAIN_KEYBOARD)


async def cmd_quick_add(update, context):
    text = update.message.text.strip()
    username = clean_username(text)
    if is_valid_twitter(username):
        if db.is_subscribed(update.effective_chat.id, username):
            await update.message.reply_text(f"⏭ @{username} قبلاً اضافه شده.")
        else:
            db.add_subscription(update.effective_chat.id, username, "")
            await update.message.reply_text(f"✅ @{username} اضافه شد!")
    else:
        await update.message.reply_text("⚠️ یوزرنیم معتبر نیست. فقط حروف انگلیسی، اعداد و _ مجازه.")


async def cmd_quick_list(update, context):
    chat_id = str(update.effective_chat.id)
    users = db.get_subs_for_chat(chat_id)
    if users:
        lines = [f"• @{u}" for u in sorted(set(users))]
        await update.message.reply_text(f"📋 لیست شما ({len(lines)}):\n\n" + "\n".join(lines))
    else:
        await update.message.reply_text("📋 لیست شما خالیه.")


async def cmd_quick_search(update, context):
    await update.message.reply_text("🔍 بنویس چی میخوای جستجو کنی:")


async def cmd_quick_dashboard(update, context):
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 باز کردن داشبورد", url=DASHBOARD_URL)]])
    await update.message.reply_text("🌐 داشبورد لایو توییترها:", reply_markup=kb)


async def cmd_quick_refresh(update, context):
    await update.message.reply_text("🔄 در حال بروزرسانی...")


async def handle_text(update, context):
    text = update.message.text.strip()
    if not text:
        return
    if text.startswith("/"):
        return
    if text == "➕ اضافه کردن":
        await update.message.reply_text("📝 یوزرنیم توییتر رو بنویس (مثلاً ElonMusk):")
        return
    if text == "📋 لیست اکانت‌ها":
        await cmd_quick_list(update, context)
        return
    if text == "🔍 جستجو":
        await update.message.reply_text("🔍 متن جستجو رو بنویس:")
        return
    if text == "🌐 داشبورد":
        await cmd_quick_dashboard(update, context)
        return
    if text == "🔄 بروزرسانی":
        await update.message.reply_text("🔄 بروزرسانی شد! توییت‌های جدید بررسی میشن.")
        return
    if text == "ℹ️ راهنما":
        await cmd_start(update, context)
        return
    if is_valid_twitter(clean_username(text)):
        await cmd_quick_add(update, context)
    else:
        await cmd_search(update, context)

async def cmd_add(update, context):
    raw = " ".join(context.args)
    if not raw.strip():
        await update.message.reply_text("UsageId: /add username1 username2", parse_mode=ParseMode.HTML)
        return
    users = list(set([clean_username(u) for u in re.split(r"[,\s]+", raw) if u]))
    added, skipped = [], []
    for u in users:
        if not is_valid_twitter(u):
            skipped.append(f"@{u}")
            continue
        if db.is_subscribed(update.effective_chat.id, u):
            skipped.append(f"@{u}")
            continue
        db.add_subscription(update.effective_chat.id, u, "")
        added.append(f"@{u}")
    msg = ""
    if added:
        msg += f"✅ اضافه شد: {', '.join(added)}\n"
    if skipped:
        msg += f"⏭ رد شد: {', '.join(skipped)}\n"
    if not msg:
        msg = "هیچی اضافه نشد."
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML)

async def cmd_del(update, context):
    if not context.args:
        await update.message.reply_text("UsageId: /del username")
        return
    for arg in context.args:
        db.remove_subscription(update.effective_chat.id, clean_username(arg))
    await update.message.reply_text("✅ حذف شد.")

async def cmd_list(update, context):
    chat_id = str(update.effective_chat.id)
    users = db.get_subs_for_chat(chat_id)
    if users:
        lines = [f"• @{u}" for u in sorted(set(users))]
        await update.message.reply_text(f"📋 لیست شما ({len(lines)}):\n\n" + "\n".join(lines))
    else:
        await update.message.reply_text("📋 لیست شما خالیه.")

async def cmd_test(update, context):
    username = clean_username(context.args[0]) if context.args else "ElonMusk"
    await update.message.reply_text(f"🔍 تست @{username}...")
    entries = await fetch_feed(username)
    if entries:
        content = await build_content(username, entries[0])
        if content:
            await deliver(content, [str(update.effective_chat.id)], context.application.bot)
    else:
        await update.message.reply_text("❌ خطا در دریافت فید.")


async def cmd_search(update, context):
    if context.args:
        query = " ".join(context.args)
    else:
        text = update.message.text.strip()
        if text in ["🔍 جستجو", "/search"]:
            await update.message.reply_text("🔍 متن جستجو رو بنویس:")
            return
        query = text
    if not query:
        await update.message.reply_text("🔍 استفاده: /search متن جستجو")
        return
    chat_id = str(update.effective_chat.id)
    rows = db.search_tweets(query, chat_id, limit=5)
    if not rows:
        await update.message.reply_text("🔍 نتیجه‌ای پیدا نشد.")
        return
    for r in rows:
        msg = f"🐦 @{r['username']}:\n{r['title'][:200]}"
        if r.get("translation"):
            msg += f"\n\n🦁 {r['translation'][:200]}"
        kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 View", url=r["tweet_link"])]] if r.get("tweet_link") else [])
        await update.message.reply_text(msg, reply_markup=kb)


async def handle_inline_query(update, context):
    query = update.inline_query.query.strip()
    if not query or len(query) < 2:
        return
    rows = db.search_tweets(query, limit=5)
    results = []
    for i, r in enumerate(rows):
        text = f"🐦 @{r['username']}\n\n{r['title'][:300]}"
        if r.get("translation"):
            text += f"\n\n🦁 {r['translation'][:300]}"
        results.append(
            InlineQueryResultArticle(
                id=str(i),
                title=f"@{r['username']}: {r['title'][:50]}...",
                description=r["title"][:100],
                input_message_content=InputTextMessageContent(text, parse_mode=ParseMode.HTML),
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("🔗 View on X", url=r["tweet_link"])]]) if r.get("tweet_link") else None,
            )
        )
    await update.inline_query.answer(results, cache_time=300, is_persistent=True)


# ── Tweet Engine ──────────────────────────────────────────────────────────

async def build_content(username, entry):
    tid = extract_id(entry)
    if not tid:
        return None
    title = entry.get("title", "")
    translation = await translate_text(title)
    img_url = extract_image_url(entry)
    link = f"https://x.com/i/status/{tid}"
    return {"tid": tid, "username": username, "title": title, "translation": translation, "img_url": img_url, "link": link}


def build_message(c):
    header = f"🔔 <b>NEW UPDATE | @{html.escape(c['username']).upper()}</b>"
    body = f"\n📝 <b>Original:</b>\n<blockquote expandable>{html.escape(c['title'][:1900])}</blockquote>"
    msg = f"{header}\n{body}"
    if c["translation"]:
        msg += f"\n{'━'*10}\n🦁 <b>ترجمه فارسی:</b>\n<blockquote expandable><i>{html.escape(c['translation'][:1900])}</i></blockquote>"
    return msg


async def deliver(content, chat_ids, bot, force=False):
    if not content:
        return
    msg = build_message(content)
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 View on X", url=content["link"])]])
    saved = False
    for cid in chat_ids:
        if not force and db.is_duplicate(cid, content["tid"]):
            continue
        try:
            if content["img_url"] and len(msg) <= 1024:
                await bot.send_photo(chat_id=cid, photo=content["img_url"], caption=msg, reply_markup=kb, parse_mode=ParseMode.HTML)
            elif content["img_url"]:
                short = f"🔔 <b>@{html.escape(content['username']).upper()}</b>\n🔗 {content['link']}"
                await bot.send_photo(chat_id=cid, photo=content["img_url"], caption=short, reply_markup=kb, parse_mode=ParseMode.HTML)
                await bot.send_message(chat_id=cid, text=msg, parse_mode=ParseMode.HTML)
            else:
                await bot.send_message(chat_id=cid, text=msg, reply_markup=kb, parse_mode=ParseMode.HTML)
            db.mark_sent(cid, content["tid"])
            saved = True
        except Exception as e:
            logger.error(f"Send failed to {cid}: {e}")
            try:
                await bot.send_message(chat_id=cid, text=msg, reply_markup=kb, parse_mode=ParseMode.HTML)
                db.mark_sent(cid, content["tid"])
                saved = True
            except Exception as e2:
                logger.error(f"Fallback send failed: {e2}")
    if saved:
        c = content
        db.save_tweet_content(c["username"], c["title"], c["translation"], c["img_url"], c["link"])


async def process_user(username, last_id, bot, sem):
    async with sem:
        entries = await fetch_feed(username)
    if not entries:
        return

    all_ids = []
    for e in entries[:10]:
        tid = extract_id(e)
        if tid:
            all_ids.append((tid, e))

    if not all_ids:
        return

    if not last_id:
        db.update_last_id(username, all_ids[0][0])
        logger.info(f"Baseline @{username}: {all_ids[0][0]}")
        return

    fresh = [(tid, e) for tid, e in all_ids if tid > last_id]

    if not fresh:
        return

    subs = db.get_subs_for_user(username)
    if not subs:
        return

    logger.info(f"@{username}: {len(fresh)} new tweets")
    for tid, entry in reversed(fresh[:3]):
        content = await build_content(username, entry)
        if content:
            await deliver(content, subs, bot)
            db.update_last_id(username, tid)


async def check_updates(context):
    tracked = db.get_all_tracked()
    bot = context.application.bot
    sem = asyncio.Semaphore(CONCURRENT_LIMIT)
    tasks = [process_user(u, li, bot, sem) for u, li in tracked]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    for (u, _), r in zip(tracked, results):
        if isinstance(r, Exception):
            logger.error(f"Error processing @{u}: {r}")


async def run_cleanup(context):
    db.cleanup()


# ── FastAPI + Telegram Lifecycle ──────────────────────────────────────────

@asynccontextmanager
async def lifespan(fastapi_app):
    global http, bot_app_ref
    http = httpx.AsyncClient(headers=RSS_HEADERS, timeout=10, follow_redirects=True, limits=httpx.Limits(max_connections=20))

    from telegram.ext import MessageHandler, filters

    bot_commands = [
        ("start", "شروع و راهنما"),
        ("add", "اضافه کردن اکانت"),
        ("del", "حذف اکانت"),
        ("list", "لیست اکانت‌ها"),
        ("test", "تست سریع"),
        ("search", "جستجو در توییت‌ها"),
    ]

    async def post_init(application):
        await application.bot.set_my_commands(bot_commands)

    bot_app_ref = Application.builder().token(TOKEN).post_init(post_init).build()

    bot_app_ref.add_handler(CommandHandler("start", cmd_start))
    bot_app_ref.add_handler(CommandHandler("help", cmd_start))
    bot_app_ref.add_handler(CommandHandler("add", cmd_add))
    bot_app_ref.add_handler(CommandHandler("del", cmd_del))
    bot_app_ref.add_handler(CommandHandler("remove", cmd_del))
    bot_app_ref.add_handler(CommandHandler("list", cmd_list))
    bot_app_ref.add_handler(CommandHandler("test", cmd_test))
    bot_app_ref.add_handler(CommandHandler("search", cmd_search))
    bot_app_ref.add_handler(InlineQueryHandler(handle_inline_query))
    bot_app_ref.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    bot_app_ref.job_queue.run_repeating(check_updates, interval=CHECK_INTERVAL, first=10)
    bot_app_ref.job_queue.run_repeating(run_cleanup, interval=86400, first=300)

    await bot_app_ref.initialize()
    await bot_app_ref.start()
    await bot_app_ref.updater.start_polling(drop_pending_updates=True)
    yield
    await bot_app_ref.updater.stop()
    await bot_app_ref.stop()
    await bot_app_ref.shutdown()
    await http.aclose()

app = FastAPI(lifespan=lifespan)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    tweets = db.get_latest_tweets(30)
    return templates.TemplateResponse(request=request, name="index.html", context={"tweets": tweets})

@app.get("/manifest.json")
async def get_manifest():
    return FileResponse(os.path.join(BASE_PATH, "manifest.json"))

@app.get("/sw.js")
async def get_sw():
    return FileResponse(os.path.join(BASE_PATH, "sw.js"))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
