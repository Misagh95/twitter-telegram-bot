import asyncio
import html
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from twitter_telegram_bot import (
    TELEGRAM_CAPTION_LIMIT,
    TELEGRAM_TEXT_LIMIT,
    RSS_SOURCES,
    build_content,
    build_message,
    deliver,
    escape_and_truncate,
    extract_author_username,
    fetch_feed,
    is_retweet,
    run_translation_backfill,
    translate_text,
    translations_cache,
    utf16_len,
)


class TestTweetBot(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        translations_cache.clear()

    def test_utf16_len(self):
        self.assertEqual(utf16_len("hello"), 5)
        # Emojis like 🦁 and 🔔 are surrogate pairs in UTF-16 (2 code units each)
        self.assertEqual(utf16_len("🦁"), 2)
        self.assertEqual(utf16_len("🔔"), 2)

    def test_escape_and_truncate(self):
        text = "Hello <world> & friends" * 20
        budget = 50
        res = escape_and_truncate(text, budget)
        self.assertLessEqual(utf16_len(res), budget)
        self.assertTrue(res.endswith("…"))
        # Must be valid HTML escaped
        self.assertIn("&lt;world&gt;", res)
        self.assertIn("&amp;", res)

    def test_truncation_shortens_both_original_and_translation(self):
        """When caption is too long, BOTH original and translation must be shortened with ellipsis."""
        c = {
            "username": "user1",
            "title": "Alpha " * 150,
            "translation": "بتا " * 150,
            "img_url": "https://pbs.twimg.com/media/pic.jpg",
            "link": "https://x.com/i/status/999",
        }
        caption = build_message(c, max_len=TELEGRAM_CAPTION_LIMIT)
        self.assertLessEqual(utf16_len(caption), TELEGRAM_CAPTION_LIMIT)
        # Check that both sections have ellipsis indicating truncation
        self.assertIn("Alpha", caption)
        self.assertIn("بتا", caption)
        self.assertEqual(caption.count("…"), 2)
        # Check valid HTML tags are all properly closed
        self.assertEqual(caption.count("<b>"), caption.count("</b>"))
        self.assertEqual(caption.count("<blockquote expandable>"), caption.count("</blockquote>"))
        self.assertEqual(caption.count("<i>"), caption.count("</i>"))

    def test_quote_tweet_not_filtered(self):
        """Quote tweet where link matches username should not be flagged as retweet."""
        entry = {
            "title": "Check out this amazing launch https://x.com/nasa/status/999",
            "link": "https://nitter.cz/elonmusk/status/1111",
            "description": "Check out this amazing launch",
        }
        self.assertFalse(is_retweet(entry, "elonmusk"))

    def test_single_card_without_translation(self):
        """When translation is empty, card contains only original text without pending notice."""
        c = {
            "username": "vitalikbuterin",
            "title": "Ethereum upgrade is live",
            "translation": "",
            "img_url": None,
            "link": "https://x.com/i/status/456",
        }
        msg = build_message(c, max_len=TELEGRAM_TEXT_LIMIT)
        self.assertIn("NEW UPDATE | @VITALIKBUTERIN", msg)
        self.assertIn("Original:", msg)
        self.assertNotIn("ترجمه فارسی:", msg)
        self.assertNotIn("بعداً ارسال می‌کند", msg)

    async def test_deliver_sends_only_one_message_with_photo(self):
        """When tweet has photo, deliver sends exactly 1 send_photo call, never send_message."""
        bot = MagicMock()
        bot.send_photo = AsyncMock()
        bot.send_message = AsyncMock()

        c = {
            "tid": "12345",
            "username": "testuser",
            "title": "A" * 1500,  # Long text
            "translation": "ت" * 1500,
            "img_url": "https://pbs.twimg.com/media/pic.jpg",
            "link": "https://x.com/i/status/12345",
        }

        with patch("twitter_telegram_bot.db") as mock_db:
            mock_db.is_duplicate.return_value = False
            await deliver(c, ["1111"], bot, force=True)

        self.assertEqual(bot.send_photo.call_count, 1)
        self.assertEqual(bot.send_message.call_count, 0)
        # Verify caption passed to send_photo is <= 1024
        call_kwargs = bot.send_photo.call_args.kwargs
        self.assertLessEqual(utf16_len(call_kwargs["caption"]), 1024)

    async def test_deliver_falls_back_to_single_text_if_photo_fails(self):
        """If send_photo fails, fall back to exactly 1 send_message."""
        bot = MagicMock()
        bot.send_photo = AsyncMock(side_effect=Exception("Failed to download image"))
        bot.send_message = AsyncMock()

        c = {
            "tid": "12345",
            "username": "testuser",
            "title": "A tweet",
            "translation": "یک توییت",
            "img_url": "https://pbs.twimg.com/media/broken.jpg",
            "link": "https://x.com/i/status/12345",
        }

        with patch("twitter_telegram_bot.db") as mock_db:
            mock_db.is_duplicate.return_value = False
            await deliver(c, ["1111"], bot, force=True)

        self.assertEqual(bot.send_photo.call_count, 1)
        self.assertEqual(bot.send_message.call_count, 1)

    def test_is_retweet_filtering(self):
        """All variations of retweets/reposts must be filtered."""
        # 1. RT by @username
        self.assertTrue(is_retweet({"title": "RT by @elonmusk: NASA Artemis launch"}, "elonmusk"))
        # 2. RT by username (no @)
        self.assertTrue(is_retweet({"title": "RT by elonmusk: NASA Artemis launch"}, "elonmusk"))
        # 3. RT @nasa
        self.assertTrue(is_retweet({"title": "RT @nasa: Launching now"}, "elonmusk"))
        # 4. RT: @nasa
        self.assertTrue(is_retweet({"title": "RT: @nasa Launching now"}, "elonmusk"))
        # 5. [RT]
        self.assertTrue(is_retweet({"title": "[RT] Launching now"}, "elonmusk"))
        # 6. Retweeted by @...
        self.assertTrue(is_retweet({"title": "Retweeted by @elonmusk: Launching"}, "elonmusk"))
        # 7. Reposted by @...
        self.assertTrue(is_retweet({"title": "Reposted by @elonmusk: Launching"}, "elonmusk"))
        # 8. HTML retweet-header
        self.assertTrue(
            is_retweet(
                {"title": "Some tweet", "description": '<div class="retweet-header">Retweeted</div>'},
                "elonmusk",
            )
        )
        # 9. Tags
        self.assertTrue(is_retweet({"title": "Some tweet", "tags": [{"term": "retweet"}]}, "elonmusk"))
        # 10. Link username mismatch
        self.assertTrue(
            is_retweet(
                {"title": "Great news", "link": "https://nitter.cz/nasa/status/98765"},
                "elonmusk",
            )
        )
        # 11. Author mismatch
        self.assertTrue(is_retweet({"title": "Great news", "author": "@nasa"}, "elonmusk"))

        # Normal original tweet must NOT be filtered
        self.assertFalse(
            is_retweet(
                {"title": "Working on Falcon Heavy today", "link": "https://nitter.cz/elonmusk/status/123"},
                "elonmusk",
            )
        )
        self.assertFalse(
            is_retweet(
                {"title": "I will start at noon", "link": "https://nitter.cz/elonmusk/status/123"},
                "elonmusk",
            )
        )

    def test_display_name_is_not_mistaken_for_a_handle(self):
        """A display name such as "RippleX" must never make a real tweet look like a retweet."""
        # <dc:creator> holds the fullname on many mirrors: no spaces, looks exactly like a handle.
        self.assertEqual(extract_author_username({"author": "RippleX"}), ("ripplex", False))
        entry = {
            "title": "X Money support is live",
            "link": "https://nitter.cz/RippleSupport/status/1234",
            "author": "RippleX",
        }
        self.assertFalse(is_retweet(entry, "ripplesupport"))
        # Without a usable status link, a guessed handle is still not evidence of a repost.
        self.assertFalse(is_retweet({"title": "Hello", "author": "RippleX"}, "ripplesupport"))
        # Full names with spaces are not even reported as hints.
        self.assertEqual(extract_author_username({"author": "Ripple Support"}), ("", False))

    def test_author_email_is_not_the_mirror_domain(self):
        """`<author>nasa@nitter.net (NASA)</author>` means @nasa, not @nitter."""
        entry = {"title": "Perseverance update", "author": "nasa@nitter.net (NASA)"}
        self.assertEqual(extract_author_username(entry), ("nasa", True))
        self.assertFalse(is_retweet(entry, "nasa"))
        self.assertTrue(is_retweet(entry, "elonmusk"))

    def test_own_status_link_wins_over_conflicting_author_field(self):
        """If the entry links to the subscribed account's own status, that tweet is theirs."""
        entry = {
            "title": "Interesting thread",
            "link": "https://nitter.cz/elonmusk/status/7",
            "author": "Elon (@nasa)",
        }
        self.assertFalse(is_retweet(entry, "elonmusk"))

    def test_explicit_foreign_handle_still_filters(self):
        """Nitter credits a repost to the original author with an explicit @handle."""
        entry = {"title": "Great launch", "link": "https://nitter.cz/i/status/8", "author": "@nasa"}
        self.assertTrue(is_retweet(entry, "elonmusk"))

    def test_quoted_block_cannot_leak_retweet_markers(self):
        """Banners inside an embedded quote/card block belong to the quoted tweet, not to us."""
        entry = {
            "title": "This take aged badly",
            "link": "https://nitter.cz/elonmusk/status/9",
            "description": (
                "This take aged badly<hr/>\n<blockquote>\n"
                '<div class="retweet-header">nasa retweeted</div>\n<p>old</p>\n</blockquote>'
            ),
        }
        self.assertFalse(is_retweet(entry, "elonmusk"))

    def test_tweet_talking_about_retweets_is_kept(self):
        """"I was retweeted by @nasa" is the tweet's own text, not a feed banner."""
        entry = {
            "title": "I was retweeted by @nasa today",
            "description": "I was retweeted by @nasa today. RT by @nasa got 3k likes.",
            "link": "https://nitter.cz/elonmusk/status/10",
        }
        self.assertFalse(is_retweet(entry, "elonmusk"))
        # The same wording on the banner line (before the text) is still a repost.
        banner = {
            "title": "RT by @nasa: Great launch",
            "description": "RT by @nasa: Great launch",
            "link": "https://nitter.cz/nasa/status/11",
        }
        self.assertTrue(is_retweet(banner, "elonmusk"))

    def test_parsed_feed_entries(self):
        """End-to-end classification of the two Nitter RSS shapes we have to support."""
        import feedparser

        def parse(creator, link, title="Hello world"):
            xml = (
                '<?xml version="1.0"?><rss version="2.0" '
                'xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>ch</title>'
                f"<item><title>{title}</title><guid isPermaLink=\"false\">123</guid>"
                f"<link>{link}</link><dc:creator>{creator}</dc:creator>"
                "<description><![CDATA[<p>Hello world</p>]]></description></item></channel></rss>"
            )
            return feedparser.parse(xml).entries[0]

        # A repost: Nitter links and credits it to the original author.
        repost = parse("@nasa", "https://nitter.cz/nasa/status/123", title="RT by @ripplesupport: Hello world")
        self.assertTrue(is_retweet(repost, "ripplesupport"))
        # An original tweet whose creator field is only the display name.
        own = parse("RippleX", "https://nitter.cz/ripplesupport/status/124")
        self.assertFalse(is_retweet(own, "ripplesupport"))
        # An explicit @creator that matches the subscription is never a repost.
        self.assertFalse(is_retweet(parse("@ripplesupport", "https://nitter.cz/ripplesupport/status/125"), "ripplesupport"))

    def _rss(self, items):
        return (
            '<?xml version="1.0"?><rss version="2.0" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><channel><title>ch</title>'
            + items
            + "</channel></rss>"
        )

    async def test_fetch_feed_drops_reposts_and_keeps_originals(self):
        """A feed with a repost and an own tweet returns only the own tweet."""
        items = (
            "<item><title>RT by @ripplesupport: NASA news</title>"
            "<link>https://nitter.cz/nasa/status/1</link><dc:creator>@nasa</dc:creator>"
            "<description>NASA news</description></item>"
            "<item><title>My own news</title>"
            "<link>https://nitter.cz/ripplesupport/status/2</link><dc:creator>RippleX</dc:creator>"
            "<description>My own news</description></item>"
        )
        resp = MagicMock(status_code=200, text=self._rss(items))
        resp.url = "https://nitter.cz/ripplesupport/rss"
        client = MagicMock()
        client.get = AsyncMock(return_value=resp)
        with patch("twitter_telegram_bot.http", client):
            entries = await fetch_feed("ripplesupport")
        self.assertEqual([str(e.get("title")) for e in entries], ["My own news"])
        # Parallel mirror race: every mirror is tried once (simultaneously), the first
        # usable feed wins.
        self.assertEqual(client.get.await_count, len(RSS_SOURCES))

    async def test_fetch_feed_all_reposts_does_not_hammer_mirrors(self):
        """An all-reposts feed is a complete answer, not a reason to try every mirror."""
        items = (
            "<item><title>RT by @ripplesupport: Someone else</title>"
            "<link>https://nitter.cz/nasa/status/3</link><dc:creator>@nasa</dc:creator>"
            "<description>Someone else</description></item>"
        )
        resp = MagicMock(status_code=200, text=self._rss(items))
        resp.url = "https://nitter.cz/ripplesupport/rss"
        client = MagicMock()
        client.get = AsyncMock(return_value=resp)
        with patch("twitter_telegram_bot.http", client):
            entries = await fetch_feed("ripplesupport")
        self.assertEqual(entries, [])
        self.assertEqual(client.get.await_count, len(RSS_SOURCES))

    async def test_empty_translation_never_cached(self):
        """Empty translation results must never be added to cache."""
        with patch("twitter_telegram_bot._translate_with_requesty", new=AsyncMock(return_value="")):
            with patch("twitter_telegram_bot._translate_with_google_endpoint", new=AsyncMock(return_value="")):
                with patch("twitter_telegram_bot._translate_with_deep_translator", new=AsyncMock(return_value="")):
                    with patch("twitter_telegram_bot._translate_with_mymemory", new=AsyncMock(return_value="")):
                        with patch("twitter_telegram_bot._translate_with_deep_mymemory", new=AsyncMock(return_value="")):
                            res = await translate_text("Some text that cannot be translated")
                            self.assertEqual(res, "")
                            self.assertEqual(len(translations_cache), 0)

    async def test_successful_translation_cached(self):
        """Valid translation is cached."""
        with patch("twitter_telegram_bot.REQUESTY_API_KEY", "test_key"):
            with patch("twitter_telegram_bot._translate_with_requesty", new=AsyncMock(return_value="ترجمه تستی")):
                res = await translate_text("A test tweet")
                self.assertEqual(res, "ترجمه تستی")
                self.assertGreater(len(translations_cache), 0)
                # Second call should return from cache
                res2 = await translate_text("A test tweet")
                self.assertEqual(res2, "ترجمه تستی")

    async def test_backfill_does_not_send_telegram_message(self):
        """run_translation_backfill only updates DB and sends NO Telegram messages."""
        bot = MagicMock()
        bot.send_message = AsyncMock()
        context = MagicMock()
        context.application.bot = bot

        fake_rows = [{"id": 42, "username": "elonmusk", "title": "Tweet to backfill", "tweet_link": "https://x.com/elonmusk/status/123"}]

        with patch("twitter_telegram_bot.db") as mock_db:
            mock_db.enabled = True
            mock_db.get_tweets_missing_translation.return_value = fake_rows
            with patch("twitter_telegram_bot.translate_text", new=AsyncMock(return_value="ترجمه بک‌فیل")):
                await run_translation_backfill(context)
                mock_db.update_tweet_translation.assert_called_once_with(42, "ترجمه بک‌فیل")

        # Bot must NEVER be called during backfill
        self.assertEqual(bot.send_message.call_count, 0)


if __name__ == "__main__":
    unittest.main()
