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
CONCURRENT_LIMIT = int(os.getenv("CONCURRENT_LIMIT", "3"))

PLACEHOLDER_API_KEYS = {"key", "your_key", "your_api_key", "your_gemini_api_key", "your_requesty_or_gemini_key"}

def _clean_api_key(value):
    value = (value or "").strip()
    return "" if value.lower() in PLACEHOLDER_API_KEYS else value

GEMINI_API_KEY = _clean_api_key(os.getenv("GEMINI_API_KEY"))
OPENAI_API_KEY = _clean_api_key(os.getenv("OPENAI_API_KEY"))
REQUESTY_API_KEY = _clean_api_key(os.getenv("REQUESTY_API_KEY")) or GEMINI_API_KEY or OPENAI_API_KEY

if os.getenv("REQUESTY_BASE_URL"):
    REQUESTY_BASE_URL = os.getenv("REQUESTY_BASE_URL", "").strip().rstrip("/")
elif GEMINI_API_KEY and REQUESTY_API_KEY == GEMINI_API_KEY:
    REQUESTY_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
elif OPENAI_API_KEY and REQUESTY_API_KEY == OPENAI_API_KEY:
    REQUESTY_BASE_URL = "https://api.openai.com/v1"
else:
    REQUESTY_BASE_URL = "https://api.17.wtf/v1"

if os.getenv("REQUESTY_MODEL"):
    REQUESTY_MODEL = os.getenv("REQUESTY_MODEL", "").strip()
elif GEMINI_API_KEY and REQUESTY_API_KEY == GEMINI_API_KEY:
    REQUESTY_MODEL = "gemini-2.0-flash"
elif OPENAI_API_KEY and REQUESTY_API_KEY == OPENAI_API_KEY:
    REQUESTY_MODEL = "gpt-4o-mini"
else:
    REQUESTY_MODEL = "posiden/deepseek-v4-flash"
TRANSLATE_FA = os.getenv("TRANSLATE_FA", "true").lower() in ("1", "true", "yes")
TRANSLATION_TIMEOUT = float(os.getenv("TRANSLATION_TIMEOUT", "20"))
TRANSLATION_RETRIES = int(os.getenv("TRANSLATION_RETRIES", "2"))
TRANSLATION_CONCURRENT_LIMIT = int(os.getenv("TRANSLATION_CONCURRENT_LIMIT", "1"))
TRANSLATION_BACKFILL_LIMIT = int(os.getenv("TRANSLATION_BACKFILL_LIMIT", "15"))
MAX_TWEETS_PER_CHECK = int(os.getenv("MAX_TWEETS_PER_CHECK", "10"))
MYMEMORY_SOURCE_LANG = os.getenv("MYMEMORY_SOURCE_LANG", "en").strip() or "en"
MYMEMORY_EMAIL = os.getenv("MYMEMORY_EMAIL", "").strip()

logging.basicConfig(format="%(asctime)s [%(levelname)s] %(message)s", level=logging.INFO)
logger = logging.getLogger(__name__)

db = Database()
if not db.enabled:
    logger.warning("Running without database - /add, /list, dashboard disabled")
app = FastAPI()
templates = Jinja2Templates(directory=os.path.join(BASE_PATH, "templates"))

http: httpx.AsyncClient = None
bot_app_ref = None
translations_cache = {}
translation_sem = asyncio.Semaphore(max(1, TRANSLATION_CONCURRENT_LIMIT))

RSS_SOURCES = [
    "https://nitter.perennialte.ch/{username}/rss",
    "https://nitter.jaydenha.uk/{username}/rss",
    "https://nitter.netbub.com/{username}/rss",
    "https://nitter.kareem.one/{username}/rss",
    "https://nitter.cz/{username}/rss",
    "https://nitter.meowing.monster/{username}/rss",
    "https://nitter.privacydev.net/{username}/rss",
]
RSS_HEADERS = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"}


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

def extract_tweet_id_from_link(link):
    value = str(link or "")
    match = re.search(r"status(?:es)?/(\d+)", value)
    if match:
        return match.group(1)
    match = re.search(r"(\d{17,})", value)
    return match.group(1) if match else None

def is_newer_tweet_id(tweet_id, last_id):
    if not last_id:
        return True
    try:
        return int(tweet_id) > int(last_id)
    except (TypeError, ValueError):
        return str(tweet_id) > str(last_id)

def clean_tweet_text(text):
    """Turn Nitter/RSS HTML-ish text into plain text before sending/translating."""
    if not text:
        return ""
    text = html.unescape(str(text))
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</p\s*>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def extract_tweet_text(entry):
    for key in ("title", "summary", "description"):
        text = clean_tweet_text(entry.get(key, ""))
        # RSS descriptions can be media-only HTML. Prefer the first field that has real text.
        if re.search(r"[\w\u0600-\u06FF]", text, flags=re.UNICODE):
            return text
    return ""

def _username_from_text(value):
    value = html.unescape(str(value or "")).strip()
    if not value:
        return None
    match = re.search(r"@([A-Za-z0-9_]{1,15})", value)
    if match:
        return clean_username(match.group(1))
    # Feedparser sometimes gives only the handle or profile URL as the author, without @.
    # Do not guess from display names like "Elon Musk"; that would look like @elon.
    if re.search(r"\s", value):
        return None
    candidate = clean_username(value)
    return candidate if is_valid_twitter(candidate) else None

def extract_author_username(entry):
    candidates = [entry.get("author"), entry.get("dc_creator"), entry.get("creator")]
    author_detail = entry.get("author_detail") or {}
    if isinstance(author_detail, dict):
        candidates.extend([author_detail.get("name"), author_detail.get("href"), author_detail.get("email")])
    for author in entry.get("authors", []) or []:
        if isinstance(author, dict):
            candidates.extend([author.get("name"), author.get("href"), author.get("email")])
        else:
            candidates.append(author)
    for value in candidates:
        username = _username_from_text(value)
        if username:
            return username
    return None

def extract_link_username(entry):
    for key in ("link", "id", "guid"):
        value = str(entry.get(key, "") or "")
        match = re.search(r"https?://[^/]+/([^/?#]+)/status(?:es)?/\d+", value, flags=re.I)
        if not match:
            continue
        username = clean_username(match.group(1))
        if username and username not in {"i", "status", "statuses"} and is_valid_twitter(username):
            return username
    return None

def is_retweet(entry, username=None):
    """Detect RSS entries that are retweets/reposts rather than tweets by `username`."""
    raw_text = "\n".join(str(entry.get(k, "") or "") for k in ("title", "summary", "description"))
    clean_text = clean_tweet_text(raw_text).lower()
    raw_lower = raw_text.lower()

    retweet_patterns = [
        r"^\s*rt\s+@",
        r"^\s*retweet(?:ed)?\b",
        r"^\s*@?[A-Za-z0-9_]{1,15}\s+retweeted\b",
        r"\bretweeted by\b",
        r"\breposted by\b",
    ]
    if any(re.search(pattern, clean_text, flags=re.I) for pattern in retweet_patterns):
        return True
    if "retweet-header" in raw_lower or ("retweet" in raw_lower and "retweeted by" in raw_lower):
        return True

    for tag in entry.get("tags", []) or []:
        term = tag.get("term") if isinstance(tag, dict) else str(tag)
        if term and term.lower() in {"rt", "retweet", "repost"}:
            return True

    expected = clean_username(username) if username else ""
    if expected:
        link_username = extract_link_username(entry)
        if link_username and link_username != expected:
            return True
        author_username = extract_author_username(entry)
        if author_username and author_username != expected:
            return True

    return False

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

def _trim_translation(result):
    result = clean_tweet_text(result)
    result = re.sub(r"^(ترجمه(?:\s*فارسی)?|translation)\s*[:：-]\s*", "", result, flags=re.I)
    return result.strip(' "“”')

def _message_content_to_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict):
                parts.append(str(item.get("text") or item.get("content") or ""))
            else:
                parts.append(str(item))
        return "".join(parts)
    return str(content or "")

def _has_text_to_translate(text):
    # Avoid wasting API quota on empty/media-only tweets, links, emoji-only posts, etc.
    return bool(re.search(r"[A-Za-z\u0600-\u06FF\u0400-\u04FF\u4E00-\u9FFF]", text or "", flags=re.UNICODE))

@asynccontextmanager
async def _translation_client():
    global http
    if http is not None:
        yield http
        return
    async with httpx.AsyncClient(headers=RSS_HEADERS, timeout=TRANSLATION_TIMEOUT, follow_redirects=True) as client:
        yield client

async def _translate_with_requesty(text):
    if not REQUESTY_API_KEY:
        return ""
    base = REQUESTY_BASE_URL if re.search(r"/v\d", REQUESTY_BASE_URL) else f"{REQUESTY_BASE_URL}/v1"
    payload = {
        "model": REQUESTY_MODEL,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a reliable translation engine. Translate the user's tweet to natural, "
                    "colloquial Persian. Keep crypto symbols, tickers, hashtags, usernames, URLs, "
                    "and product names in English. Return only the Persian translation; no notes."
                ),
            },
            {"role": "user", "content": text},
        ],
        "temperature": 0.2,
    }
    async with _translation_client() as client:
        resp = await client.post(
            f"{base}/chat/completions",
            headers={"Authorization": f"Bearer {REQUESTY_API_KEY}", "Content-Type": "application/json"},
            json=payload,
            timeout=TRANSLATION_TIMEOUT,
        )
    if resp.status_code != 200:
        logger.warning("AI translate status %s: %s", resp.status_code, resp.text[:250])
        return ""
    data = resp.json()
    result = data.get("choices", [{}])[0].get("message", {}).get("content", "")
    return _trim_translation(_message_content_to_text(result))

async def _translate_with_google_endpoint(text):
    # Fast unofficial endpoint used only as a fallback when the AI provider is absent/down.
    params = {"client": "gtx", "sl": "auto", "tl": "fa", "dt": "t", "q": text}
    async with _translation_client() as client:
        resp = await client.get(
            "https://translate.googleapis.com/translate_a/single",
            params=params,
            timeout=TRANSLATION_TIMEOUT,
        )
    if resp.status_code != 200:
        logger.warning("Google endpoint translate status %s: %s", resp.status_code, resp.text[:200])
        return ""
    data = resp.json()
    if not data or not data[0]:
        return ""
    return _trim_translation("".join(part[0] for part in data[0] if part and part[0]))

def _chunk_text(text, max_chars=450):
    parts = re.split(r"(?<=[.!?؟؛])\s+|\n+", text)
    chunks, current = [], ""
    for part in [p.strip() for p in parts if p.strip()]:
        if len(part) > max_chars:
            if current:
                chunks.append(current)
                current = ""
            chunks.extend(part[i:i + max_chars] for i in range(0, len(part), max_chars))
            continue
        candidate = f"{current} {part}".strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                chunks.append(current)
            current = part
    if current:
        chunks.append(current)
    return chunks or [text[:max_chars]]

async def _translate_with_mymemory(text):
    # Non-Google fallback for hosts where Google is rate-limited/blocked.
    translated_parts = []
    async with _translation_client() as client:
        for chunk in _chunk_text(text):
            params = {"q": chunk, "langpair": f"{MYMEMORY_SOURCE_LANG}|fa"}
            if MYMEMORY_EMAIL:
                params["de"] = MYMEMORY_EMAIL
            resp = await client.get(
                "https://api.mymemory.translated.net/get",
                params=params,
                timeout=TRANSLATION_TIMEOUT,
            )
            if resp.status_code != 200:
                logger.warning("MyMemory translate status %s: %s", resp.status_code, resp.text[:200])
                return ""
            data = resp.json()
            if data.get("responseStatus") not in (None, 200):
                logger.warning("MyMemory translate response %s: %s", data.get("responseStatus"), data.get("responseDetails"))
                return ""
            part = data.get("responseData", {}).get("translatedText", "")
            if not part:
                return ""
            translated_parts.append(part)
            await asyncio.sleep(0.2)
    return _trim_translation("\n".join(translated_parts))

def _translate_with_deep_translator_sync(text):
    from deep_translator import GoogleTranslator
    result = GoogleTranslator(source="auto", target="fa").translate(text)
    return _trim_translation(result)

async def _translate_with_deep_translator(text):
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_translate_with_deep_translator_sync, text),
            timeout=TRANSLATION_TIMEOUT,
        )
    except Exception as e:
        logger.warning("deep-translator failed: %s", e)
        return ""

async def translate_text(text):
    text = clean_tweet_text(text)
    if not TRANSLATE_FA or not text or not _has_text_to_translate(text):
        return ""

    # Keep enough context for long posts/quotes but stay below provider limits.
    source_text = text[:3000]
    cache_key = hashlib.md5(source_text.encode()).hexdigest()
    if cache_key in translations_cache:
        return translations_cache[cache_key]

    translators = [_translate_with_requesty] if REQUESTY_API_KEY else []
    translators.extend([_translate_with_google_endpoint, _translate_with_mymemory, _translate_with_deep_translator])

    async with translation_sem:
        for translator in translators:
            attempts = max(1, TRANSLATION_RETRIES) if translator in (_translate_with_requesty, _translate_with_google_endpoint) else 1
            for attempt in range(1, attempts + 1):
                try:
                    result = await translator(source_text)
                except Exception as e:
                    logger.warning("%s failed on attempt %s: %s", translator.__name__, attempt, e)
                    result = ""
                if result:
                    if len(translations_cache) > 500:
                        translations_cache.clear()
                    translations_cache[cache_key] = result
                    return result
                if attempt < attempts:
                    await asyncio.sleep(0.6 * attempt)

    # Important: do not cache failures. A temporary provider outage should not make this
    # tweet permanently untranslated for the rest of the process lifetime.
    logger.warning("Translation unavailable after all fallbacks for text: %s", source_text[:120])
    return ""


async def fetch_feed(username):
    for src in RSS_SOURCES:
        url = src.format(username=username)
        try:
            resp = await http.get(url, timeout=15, follow_redirects=True)
            if resp.status_code != 200 or "uni-sonia" in str(resp.url):
                continue
            feed = await asyncio.to_thread(feedparser.parse, resp.text)
            valid = []
            skipped_retweets = 0
            for entry in feed.entries:
                if not extract_id(entry):
                    continue
                if is_retweet(entry, username):
                    skipped_retweets += 1
                    continue
                valid.append(entry)
            if skipped_retweets:
                logger.info("Skipped %s retweets/reposts for @%s", skipped_retweets, username)
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
        [KeyboardButton("📊 وضعیت"), KeyboardButton("ℹ️ راهنما")],
    ],
    resize_keyboard=True,
    is_persistent=True,
    input_field_placeholder="نام کاربری توییتر رو بنویس...",
)

RAILWAY_DOMAIN = os.getenv("RAILWAY_PUBLIC_DOMAIN")
DASHBOARD_URL = os.getenv("DASHBOARD_URL") or (f"https://{RAILWAY_DOMAIN}" if RAILWAY_DOMAIN else "http://localhost:8080")


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
    if text == "📊 وضعیت":
        await cmd_status(update, context)
        return
    if text == "ℹ️ راهنما":
        await cmd_start(update, context)
        return
    if is_valid_twitter(clean_username(text)):
        await cmd_quick_add(update, context)
    else:
        await cmd_search(update, context)


async def cmd_status(update, context):
    if not db.enabled:
        await update.message.reply_text("❌ دیتابیس متصل نیست. لطفاً PostgreSQL رو اضافه کن.")
        return
    chat_id = str(update.effective_chat.id)
    users = db.get_subs_for_chat(chat_id)
    tracked = db.get_all_tracked()
    tweet_count = db._run("SELECT COUNT(*) FROM tweets_content", fetch="one", default=[0])[0] if db.enabled else 0
    missing_translation_count = db.count_missing_translations() if db.enabled else 0
    ai_status = "✅ AI + Google/MyMemory fallback" if REQUESTY_API_KEY else "⚠️ Google/MyMemory fallback"
    db_status = "✅ PostgreSQL" if db.enabled else "❌ غیرفعال"

    lines = [
        "📊 <b>وضعیت ربات</b>",
        "",
        f"🤖 <b>ترجمه:</b> {ai_status}",
        f"💾 <b>دیتابیس:</b> {db_status}",
        f"📝 <b>توییت‌های ذخیره شده:</b> {tweet_count}",
        f"🦁 <b>بدون ترجمه:</b> {missing_translation_count}",
        f"👤 <b>اکانت‌های شما:</b> {len(set(users))}",
        f"🌐 <b>اکانت‌های کل:</b> {len(tracked)}",
        f"⏱ <b>بررسی هر:</b> {CHECK_INTERVAL} ثانیه",
    ]

    if REQUESTY_API_KEY:
        lines.append(f"🧠 <b>مدل:</b> {REQUESTY_MODEL}")

    await update.message.reply_text("\n".join(lines), parse_mode=ParseMode.HTML)

async def cmd_add(update, context):
    if not db.enabled:
        await update.message.reply_text("❌ دیتابیس متصل نیست. اول PostgreSQL رو اضافه کن.")
        return
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
    if not db.enabled:
        await update.message.reply_text("❌ دیتابیس متصل نیست.")
        return
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
    if not db.enabled:
        await update.message.reply_text("❌ دیتابیس متصل نیست.")
        return
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
    if not tid or is_retweet(entry, username):
        return None
    title = extract_tweet_text(entry)
    translation = await translate_text(title)
    translation_pending = bool(TRANSLATE_FA and title and _has_text_to_translate(title) and not translation)
    img_url = extract_image_url(entry)
    link = f"https://x.com/i/status/{tid}"
    return {
        "tid": tid,
        "username": username,
        "title": title,
        "translation": translation,
        "translation_pending": translation_pending,
        "img_url": img_url,
        "link": link,
    }


def build_message(c):
    header = f"🔔 <b>NEW UPDATE | @{html.escape(c['username']).upper()}</b>"
    body = f"\n📝 <b>Original:</b>\n<blockquote expandable>{html.escape(c['title'][:1900])}</blockquote>"
    msg = f"{header}\n{body}"
    if c["translation"]:
        msg += f"\n{'━'*10}\n🦁 <b>ترجمه فارسی:</b>\n<blockquote expandable><i>{html.escape(c['translation'][:1900])}</i></blockquote>"
    elif c.get("translation_pending"):
        msg += f"\n{'━'*10}\n🦁 <b>ترجمه فارسی:</b>\n<i>ترجمه فعلاً ناموفق بود؛ ربات دوباره تلاش می‌کند و بعداً ارسال می‌کند.</i>"
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
        await asyncio.sleep(1)
    if not entries:
        return

    all_ids = []
    for e in entries[:max(10, MAX_TWEETS_PER_CHECK)]:
        tid = extract_id(e)
        if tid:
            all_ids.append((tid, e))

    if not all_ids:
        return

    if not last_id:
        db.update_last_id(username, all_ids[0][0])
        logger.info(f"Baseline @{username}: {all_ids[0][0]}")
        return

    fresh = [(tid, e) for tid, e in all_ids if is_newer_tweet_id(tid, last_id)]

    if not fresh:
        return

    subs = db.get_subs_for_user(username)
    if not subs:
        return

    logger.info(f"@{username}: {len(fresh)} new tweets")
    if len(fresh) > MAX_TWEETS_PER_CHECK:
        logger.warning("@%s has %s fresh tweets; processing newest %s this cycle", username, len(fresh), MAX_TWEETS_PER_CHECK)
    selected = sorted(
        fresh[:MAX_TWEETS_PER_CHECK],
        key=lambda item: (0, int(item[0])) if str(item[0]).isdigit() else (1, str(item[0])),
    )
    for tid, entry in selected:
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


async def notify_backfilled_translation(row, translation, bot):
    tweet_id = extract_tweet_id_from_link(row.get("tweet_link"))
    if not tweet_id:
        return
    chat_ids = db.get_sent_chats_for_tweet(tweet_id)
    if not chat_ids:
        return
    username = html.escape(str(row.get("username") or "").upper())
    msg = (
        f"🦁 <b>ترجمه فارسی | @{username}</b>\n"
        f"<blockquote expandable><i>{html.escape(translation[:1900])}</i></blockquote>"
    )
    kb = InlineKeyboardMarkup([[InlineKeyboardButton("🔗 View on X", url=row["tweet_link"])]]) if row.get("tweet_link") else None
    for cid in chat_ids:
        try:
            await bot.send_message(chat_id=cid, text=msg, reply_markup=kb, parse_mode=ParseMode.HTML)
        except Exception as e:
            logger.error("Backfill translation notify failed to %s for %s: %s", cid, tweet_id, e)


async def run_translation_backfill(context):
    if not db.enabled or not TRANSLATE_FA:
        return
    rows = db.get_tweets_missing_translation(TRANSLATION_BACKFILL_LIMIT)
    if not rows:
        return
    logger.info("Backfilling translations for %s saved tweets", len(rows))
    bot = context.application.bot if context and context.application else None
    for row in rows:
        translation = await translate_text(row["title"])
        if translation:
            db.update_tweet_translation(row["id"], translation)
            if bot:
                await notify_backfilled_translation(row, translation, bot)
        await asyncio.sleep(0.4)


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
        ("status", "وضعیت ربات"),
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
    bot_app_ref.add_handler(CommandHandler("status", cmd_status))
    bot_app_ref.add_handler(InlineQueryHandler(handle_inline_query))
    bot_app_ref.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))

    async def handle_error(update, context):
        from telegram.error import Conflict
        if isinstance(context.error, Conflict):
            return
        logger.error(f"Unhandled exception: {context.error}")

    bot_app_ref.add_error_handler(handle_error)

    if db.enabled:
        bot_app_ref.job_queue.run_repeating(check_updates, interval=CHECK_INTERVAL, first=10)
        bot_app_ref.job_queue.run_repeating(
            run_translation_backfill,
            interval=max(CHECK_INTERVAL * 2, 600),
            first=120,
        )
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
    tweets = db.get_latest_tweets(30) if db.enabled else []
    return templates.TemplateResponse(request=request, name="index.html", context={"tweets": tweets})

@app.get("/manifest.json")
async def get_manifest():
    return FileResponse(os.path.join(BASE_PATH, "manifest.json"))

@app.get("/sw.js")
async def get_sw():
    return FileResponse(os.path.join(BASE_PATH, "sw.js"))

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", 8080)))
