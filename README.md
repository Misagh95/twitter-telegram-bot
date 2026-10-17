<p align="center">
  <img src="https://upload.wikimedia.org/wikipedia/commons/f/fd/State_flag_of_Iran_%281964%E2%80%931980%29.svg" width="110" alt="Lion and Sun Flag of Iran">
</p>

<h1 align="center">🐦 Twitter/X → Telegram Bot</h1>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.10+-blue?logo=python&logoColor=white" alt="Python">
  <img src="https://img.shields.io/badge/Telegram-Bot%20API-26A5E4?logo=telegram&logoColor=white" alt="Telegram">
  <img src="https://img.shields.io/badge/FastAPI-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/PostgreSQL-4169E1?logo=postgresql&logoColor=white" alt="PostgreSQL">
  <img src="https://img.shields.io/badge/Gemini-AI-8B5CF6?logo=google&logoColor=white" alt="Gemini AI">
</p>

<p align="center">
  <b>Forward new posts from X to Telegram.</b><br>
  Works without an X API token via RSSHub and public RSS mirrors; the official X API v2 is an optional, more direct source. Public feeds may be unavailable. Supports AI-powered Persian translation.<br>
  Includes a live web dashboard + PWA.
</p>

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🔄 **Auto Forward** | Tweets delivered to Telegram automatically |
| 🦁 **AI Translation** | Gemini / Google Translate to Persian |
| 🚫 **Retweet Filter** | Skips retweets/reposts, without misreading display names as handles |
| 🖼️ **Media Support** | Photos included with tweets |
| 📊 **Live Dashboard** | Web UI to view all tweets |
| 🔍 **Inline Search** | Search tweets from any chat |
| ⌨️ **Keyboard Menu** | Quick buttons for easy use |
| 🌐 **PWA Support** | Installable web app |
| ⚡ **Parallel Fetching** | Feed checks are throttled for reliability |
| 🧠 **Smart Caching** | Translation cache (500 entries) |
| 🛡️ **Auto Recovery** | DB reconnect + API fallback |
| 📱 **Mobile Friendly** | Responsive dark UI |

---

## 🚀 Quick Start

### 1. Create Telegram Bot

1. Open [@BotFather](https://t.me/BotFather) in Telegram
2. Send `/newbot` and choose a name & username
3. Copy the token (looks like: `123456:ABC-DEF...`)

### 2. Install

```bash
git clone https://github.com/Misagh95/twitter-telegram-bot.git
cd twitter-telegram-bot
pip install -r requirements.txt
```

### 3. Configure

Create a `.env` file:

```env
TELEGRAM_BOT_TOKEN=your_bot_token_here
DATABASE_URL=postgresql://user:pass@localhost:5432/dbname
# Optional: only if you have X API read access
# X_BEARER_TOKEN=your_x_api_bearer_token
# Optional: use another RSSHub instance
# RSSHUB_BASE_URL=https://rsshub.app

# AI Translation (optional)
TRANSLATE_FA=true
# You can use REQUESTY_API_KEY or GEMINI_API_KEY
REQUESTY_API_KEY=your_gemini_api_key
REQUESTY_BASE_URL=https://generativelanguage.googleapis.com/v1beta/openai
REQUESTY_MODEL=gemini-2.0-flash
```

`X_BEARER_TOKEN` is optional. Without it, the bot tries the public RSSHub route (`https://rsshub.app/twitter/user/<username>`) and other RSS mirrors; these public services can be rate-limited or unavailable. If you have X API read access, set its Bearer Token in your host's secrets (never commit or paste it). You can point `RSSHUB_BASE_URL` at another RSSHub instance.

### 4. Run

```bash
python twitter_telegram_bot.py
```

Open `http://localhost:8080` for the live dashboard.

---

## 📱 Bot Commands

| Command | Description |
|---------|-------------|
| `/start` | Welcome message + keyboard |
| `/add username` | Add Twitter account(s) |
| `/del username` | Remove account |
| `/list` | View tracked accounts |
| `/test` | Test with @ElonMusk |
| `/search text` | Search saved tweets |
| `/status` | Bot health check |

---

## ⌨️ Keyboard Buttons

| Button | Action |
|--------|--------|
| ➕ اضافه کردن | Add account |
| 📋 لیست اکانت‌ها | View list |
| 🔍 جستجو | Search tweets |
| 🌐 داشبورد | Open web dashboard |
| 📊 وضعیت | Bot status |
| ℹ️ راهنما | Help |

---

## 🔍 Inline Mode

From **any** Telegram chat, type:

```
@your_bot_name elonmusk
```

Searches saved tweets and shares them inline.

---

## 🌐 Deploy to Railway

1. Push to GitHub
2. Go to [railway.app](https://railway.app)
3. **New Project** → **Deploy from GitHub Repo**
4. Select your repo
5. Add **PostgreSQL** database
6. Set environment variables:

| Variable | Value |
|----------|-------|
| `TELEGRAM_BOT_TOKEN` | Your bot token |
| `DATABASE_URL` | Auto-set by Railway |
| `X_BEARER_TOKEN` | Optional Bearer Token with X API read access; otherwise RSSHub/RSS mirrors are used |
| `RSSHUB_BASE_URL` | Optional; defaults to `https://rsshub.app` |
| `REQUESTY_API_KEY` | Your Gemini key |
| `REQUESTY_BASE_URL` | `https://generativelanguage.googleapis.com/v1beta/openai` |
| `REQUESTY_MODEL` | `gemini-2.0-flash` |
| `TRANSLATE_FA` | `true` |

7. Deploy! 🎉

---

## 📁 Project Structure

```
twitter-telegram-bot/
├── twitter_telegram_bot.py   # Main bot + web server
├── database.py               # PostgreSQL manager
├── templates/
│   └── index.html            # Dashboard UI (PWA)
├── sw.js                     # Service Worker
├── manifest.json             # PWA manifest
├── requirements.txt          # Dependencies
├── Procfile                  # Railway config
├── README_FA.md              # 🇮🇷 Persian docs
└── README.md                 # 🇬🇧 English docs
```

---

## ⚙️ Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `X_BEARER_TOKEN` | empty | Optional X API v2 Bearer Token; used when configured |
| `X_API_BASE_URL` | `https://api.x.com/2` | X API v2 base URL |
| `X_USER_ID_CACHE_TTL` | `86400` | Cache lifetime for resolved X user IDs (seconds) |
| `RSSHUB_BASE_URL` | `https://rsshub.app` | RSSHub instance included among RSS sources when X API is not configured or fails |
| `HTTP_MAX_CONNECTIONS` | `50` | HTTP connection-pool size; leaves room beyond bounded RSS requests |
| `RSS_FETCH_TIMEOUT` | `12` | Maximum time spent checking RSS mirrors for one account (seconds) |
| `RSS_MERGE_GRACE` | `0.25` | Extra seconds to merge fast mirror responses after the first usable feed |
| `CHECK_INTERVAL` | `300` | Check interval (seconds) |
| `TRANSLATE_FA` | `true` | Enable Persian translation |
| `REQUESTY_API_KEY` / `GEMINI_API_KEY` / `OPENAI_API_KEY` | empty | AI provider key for higher quality translation |
| `DASHBOARD_URL` | `http://localhost:8080` | Dashboard URL |
| `CONCURRENT_LIMIT` | `3` | Number of accounts checked concurrently |
| `RSS_FETCH_CONCURRENCY` | `12` | Global cap on concurrent RSS HTTP requests (helps prevent connection-pool timeouts) |
| `TRANSLATION_TIMEOUT` | `20` | Timeout per translation attempt (seconds) |
| `TRANSLATION_DELIVERY_TIMEOUT` | `15` | Maximum wait for translation before sending the original post |
| `TRANSLATION_RETRIES` | `2` | Retries for the primary AI/Google translation attempts |
| `TRANSLATION_CONCURRENT_LIMIT` | `1` | Parallel translation calls (keep low to avoid Google rate limits) |
| `TRANSLATION_BACKFILL_LIMIT` | `15` | Saved untranslated tweets repaired per backfill run |
| `MAX_TWEETS_PER_CHECK` | `10` | Unseen posts sent per account per check; older backlog continues next check |
| `MYMEMORY_SOURCE_LANG` | `en` | Source language for the non-Google fallback translator |
| `MYMEMORY_EMAIL` | empty | Optional MyMemory contact email for higher free limits |
| `LOG_LEVEL` | `INFO` | Set to `DEBUG` to log why each feed entry was kept or skipped |

---

## 📝 Notes

- ❌ Private accounts require authenticated access
- ✅ Official X API v2 is used when `X_BEARER_TOKEN` is configured
- ⚠️ Without it, public RSSHub and Nitter mirrors are tried but are best-effort and may be unavailable
- ✅ Retweets/reposts are filtered out; a display name (e.g. `RippleX`) is never mistaken for a handle, so accounts stay visible
- ✅ With `LOG_LEVEL=DEBUG` every skipped entry is logged with its reason (e.g. `Skip @nasa 123: status link is @nasa`)
- ✅ Single Telegram card per tweet: long captions are auto-truncated without splitting into separate messages
- ✅ Translation retries + Google/MyMemory fallback when the AI provider fails
- ✅ Saved tweets with empty translations are backfilled automatically for database & dashboard (no duplicate Telegram messages)
- ✅ Deduplication prevents duplicate messages
- ✅ Old data auto-cleaned (30 days)

---

## 🛠️ Tech Stack

- **Backend:** Python 3.10+, python-telegram-bot v22
- **Web:** FastAPI + Jinja2 + Tailwind CSS
- **Database:** PostgreSQL (psycopg2)
- **AI:** Google Gemini API
- **RSS:** feedparser + httpx
- **PWA:** Service Worker + Manifest

---

<p align="center">
  Made with ❤️ by <a href="https://github.com/Misagh95">Misagh95</a>
</p>
