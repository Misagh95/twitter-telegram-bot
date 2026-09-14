import os
import logging
from contextlib import contextmanager
import psycopg2
from psycopg2.pool import ThreadedConnectionPool

logger = logging.getLogger(__name__)

class Database:
    def __init__(self):
        self.db_url = os.getenv("DATABASE_URL") or os.getenv("DATABASE_PUBLIC_URL")
        self._pool = None
        self.enabled = False
        if not self.db_url:
            logger.critical("No DATABASE_URL found! Running without database.")
            return
        if self.db_url.startswith("postgres://"):
            self.db_url = self.db_url.replace("postgres://", "postgresql://", 1)
        try:
            self._pool = ThreadedConnectionPool(1, 8, self.db_url)
            self.enabled = True
            logger.info("Database pool ready.")
            self._init_schema()
        except Exception as e:
            logger.critical(f"Database init failed: {e}")

    @contextmanager
    def cursor(self):
        if not self.enabled:
            raise RuntimeError("Database not available")
        conn = self._pool.getconn()
        try:
            if conn.closed:
                self._pool.putconn(conn, close=True)
                conn = self._pool.getconn()
            conn.autocommit = True
            with conn.cursor() as cur:
                yield cur
        finally:
            if conn and not conn.closed:
                self._pool.putconn(conn)

    def _run(self, query, params=None, fetch="all", default=None):
        if not self.enabled:
            return default
        for attempt in range(3):
            try:
                with self.cursor() as cur:
                    cur.execute(query, params)
                    if fetch == "one":
                        return cur.fetchone()
                    if fetch == "all":
                        return cur.fetchall()
                    return None
            except (psycopg2.InterfaceError, psycopg2.OperationalError) as e:
                logger.warning(f"DB retry {attempt+1}: {e}")
                if attempt == 2:
                    try:
                        self._pool.closeall()
                        self._pool = ThreadedConnectionPool(1, 8, self.db_url)
                    except Exception:
                        self.enabled = False
            except Exception as e:
                logger.error(f"DB error: {e}")
                return default
        return default

    def _init_schema(self):
        self._run("CREATE TABLE IF NOT EXISTS tracked_users (username TEXT PRIMARY KEY, last_id TEXT)", fetch=None)
        self._run("CREATE TABLE IF NOT EXISTS subscriptions (chat_id TEXT, username TEXT, PRIMARY KEY(chat_id, username))", fetch=None)
        self._run("CREATE TABLE IF NOT EXISTS sent_ids (chat_id TEXT, tweet_id TEXT, created_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY(chat_id, tweet_id))", fetch=None)
        self._run("""CREATE TABLE IF NOT EXISTS tweets_content (
            id SERIAL PRIMARY KEY, username TEXT, title TEXT,
            translation TEXT, img_url TEXT, tweet_link TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)""", fetch=None)
        self._run("CREATE INDEX IF NOT EXISTS idx_subs_username ON subscriptions(username)", fetch=None)
        self._run("CREATE INDEX IF NOT EXISTS idx_tweets_created ON tweets_content(created_at DESC)", fetch=None)
        self._run("CREATE INDEX IF NOT EXISTS idx_sent_created ON sent_ids(created_at)", fetch=None)

    def get_all_tracked(self):
        return self._run("SELECT username, last_id FROM tracked_users", default=[])

    def update_last_id(self, username, last_id):
        self._run("UPDATE tracked_users SET last_id = %s WHERE username = %s", (last_id, username), fetch=None)

    def get_subs_for_user(self, username):
        rows = self._run("SELECT chat_id FROM subscriptions WHERE username = %s", (username,), default=[])
        return [r[0] for r in rows]

    def get_subs_for_chat(self, chat_id):
        rows = self._run("SELECT username FROM subscriptions WHERE chat_id = %s", (str(chat_id),), default=[])
        return [r[0] for r in rows]

    def is_subscribed(self, chat_id, username):
        row = self._run("SELECT 1 FROM subscriptions WHERE chat_id = %s AND username = %s", (str(chat_id), username), fetch="one", default=None)
        return row is not None

    def add_subscription(self, chat_id, username, last_id=""):
        self._run("INSERT INTO tracked_users (username, last_id) VALUES (%s, %s) ON CONFLICT (username) DO NOTHING", (username, last_id), fetch=None)
        self._run("INSERT INTO subscriptions (chat_id, username) VALUES (%s, %s) ON CONFLICT (chat_id, username) DO NOTHING", (str(chat_id), username), fetch=None)

    def remove_subscription(self, chat_id, username):
        self._run("DELETE FROM subscriptions WHERE chat_id = %s AND username = %s", (str(chat_id), username), fetch=None)
        row = self._run("SELECT 1 FROM subscriptions WHERE username = %s", (username,), fetch="one", default=None)
        if not row:
            self._run("DELETE FROM tracked_users WHERE username = %s", (username,), fetch=None)

    def is_duplicate(self, chat_id, tweet_id):
        row = self._run("SELECT 1 FROM sent_ids WHERE chat_id = %s AND tweet_id = %s", (str(chat_id), str(tweet_id)), fetch="one", default=None)
        return row is not None

    def mark_sent(self, chat_id, tweet_id):
        self._run("INSERT INTO sent_ids (chat_id, tweet_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (str(chat_id), str(tweet_id)), fetch=None)

    def save_tweet_content(self, username, title, translation, img_url, tweet_link):
        self._run("INSERT INTO tweets_content (username, title, translation, img_url, tweet_link) VALUES (%s,%s,%s,%s,%s)", (username, title, translation, img_url, tweet_link), fetch=None)

    def get_latest_tweets(self, limit=30):
        rows = self._run("SELECT username, title, translation, img_url, tweet_link, created_at FROM tweets_content ORDER BY created_at DESC LIMIT %s", (limit,), default=[])
        if not rows:
            return []
        columns = ["username", "title", "translation", "img_url", "tweet_link", "created_at"]
        return [dict(zip(columns, r)) for r in rows]

    def search_tweets(self, query, chat_id=None, limit=5):
        pattern = f"%{query}%"
        if chat_id:
            sql = "SELECT username, title, translation, tweet_link FROM tweets_content WHERE (title ILIKE %s OR translation ILIKE %s OR username ILIKE %s) AND username IN (SELECT username FROM subscriptions WHERE chat_id = %s) ORDER BY created_at DESC LIMIT %s"
            rows = self._run(sql, (pattern, pattern, pattern, str(chat_id), limit), default=[])
        else:
            sql = "SELECT username, title, translation, tweet_link FROM tweets_content WHERE (title ILIKE %s OR translation ILIKE %s OR username ILIKE %s) ORDER BY created_at DESC LIMIT %s"
            rows = self._run(sql, (pattern, pattern, pattern, limit), default=[])
        if not rows:
            return []
        columns = ["username", "title", "translation", "tweet_link"]
        return [dict(zip(columns, r)) for r in rows]

    def cleanup(self):
        self._run("DELETE FROM sent_ids WHERE created_at < NOW() - INTERVAL '%s days'" % 30, fetch=None)
        self._run("DELETE FROM tweets_content WHERE id NOT IN (SELECT id FROM tweets_content ORDER BY created_at DESC LIMIT 300)", fetch=None)
        logger.info("DB cleanup done.")
