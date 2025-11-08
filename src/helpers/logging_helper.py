import os
import logging
import urllib.parse
import requests
import time
from collections import deque
from threading import Lock

import sentry_sdk

# TODO:MED: Add extra={"log_importance": "high"} to important logger.info(...) calls for granular log filtering/routing. That will help to seprate importnat/less important logs that are still in INFO level.

def get_env_list(key, default=""):
    v = os.getenv(key, default)
    if not v:
        return []
    return [level.strip().upper() for level in v.split(",") if level.strip()]

class LevelsFilter(logging.Filter):
    def __init__(self, allowed_levels):
        super().__init__()
        self.allowed_levels = set(getattr(logging, level) for level in allowed_levels)
    def filter(self, record):
        return record.levelno in self.allowed_levels

class SingleLineFormatter(logging.Formatter):
    def format(self, record):
        msg = super().format(record)
        return msg.replace("\n", "\\n")

class MultiLineFormatter(logging.Formatter):
    def format(self, record):
        return super().format(record)

class TelegramLoggerHandler(logging.Handler):
    def __init__(self, bot_token, chat_id, rate_limit_per_minute=20):
        super().__init__()
        self.bot_token = bot_token
        self.chat_id = chat_id
        self.api_url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"
        self.max_length = 4000  # safe margin under Telegram's limit

        # Rate limiting: track timestamps of recent messages
        self.rate_limit_per_minute = rate_limit_per_minute
        self.message_timestamps = deque(maxlen=rate_limit_per_minute)
        self.lock = Lock()

        # Backoff tracking for 429 errors
        self.backoff_until = 0
        self.dropped_count = 0

    def _should_send(self):
        """Check if we can send a message based on rate limiting and backoff."""
        now = time.time()

        # Check if we're in backoff period
        if now < self.backoff_until:
            return False

        # Check rate limit (messages per minute)
        with self.lock:
            # Remove timestamps older than 1 minute
            while self.message_timestamps and now - self.message_timestamps[0] > 60:
                self.message_timestamps.popleft()

            # Check if we've hit the rate limit
            if len(self.message_timestamps) >= self.rate_limit_per_minute:
                return False

            return True

    def _record_send(self):
        """Record that we sent a message."""
        with self.lock:
            self.message_timestamps.append(time.time())

    def emit(self, record):
        # Prevent recursive logging from this handler
        if record.name == 'TelegramLoggerHandler':
            return

        try:
            # Check rate limiting
            if not self._should_send():
                self.dropped_count += 1
                # Silently drop the message, don't create recursive logs
                return

            msg = self.format(record)

            # If we had dropped messages, prepend a warning
            if self.dropped_count > 0:
                msg = f"[{self.dropped_count} messages dropped due to rate limiting]\n{msg}"
                self.dropped_count = 0

            chunks = [msg[i: i + 4096] for i in range(0, len(msg), 4096)] or [""]
            for chunk in chunks:
                text = urllib.parse.quote(chunk, safe="")
                url = (
                    f"https://api.telegram.org/bot{self.bot_token}"
                    f"/sendMessage?chat_id={self.chat_id}"
                    f"&text={text}&disable_web_page_preview=true"
                )
                resp = requests.get(url, timeout=5)

                if resp.status_code == 429:
                    # Extract retry_after from response if available
                    try:
                        retry_after = resp.json().get('parameters', {}).get('retry_after', 60)
                    except:
                        retry_after = 60

                    # Set backoff period
                    self.backoff_until = time.time() + retry_after

                    # Use a separate logger to avoid recursion
                    telegram_logger = logging.getLogger('TelegramLoggerHandler')
                    telegram_logger.error(
                        f"TelegramLoggerHandler rate-limited by Telegram API. "
                        f"Backing off for {retry_after}s. Response: {resp.text}"
                    )
                    break
                elif resp.status_code != 200:
                    # Use a separate logger to avoid recursion
                    telegram_logger = logging.getLogger('TelegramLoggerHandler')
                    telegram_logger.error(
                        f"TelegramLoggerHandler failed ({resp.status_code}): {resp.text}"
                    )
                else:
                    # Successfully sent, record it
                    self._record_send()

        except Exception as e:
            # Use a separate logger to avoid recursion
            telegram_logger = logging.getLogger('TelegramLoggerHandler')
            telegram_logger.error(f"TelegramLoggerHandler.emit exception: {e}")
            self.handleError(record)

def get_logger():
    logger = logging.getLogger()
    if logger.hasHandlers():
        logger.handlers.clear()

    log_format = os.getenv("LOGGING_FORMAT", "%(asctime)s - %(levelname)s - %(message)s")

    fmt_console = SingleLineFormatter(log_format)
    fmt_telegram = MultiLineFormatter(log_format)

    # Console handler
    if os.getenv("LOGGING_CONSOLE_ENABLED", "false").lower() == "true":
        console_levels = get_env_list("LOGGING_CONSOLE_LEVELS", "DEBUG,INFO,WARNING,ERROR,CRITICAL")
        console = logging.StreamHandler()
        console.setFormatter(fmt_console)
        if console_levels:
            console.setLevel(logging.DEBUG)
            console.addFilter(LevelsFilter(console_levels))
        logger.addHandler(console)

    # Telegram handlers
    bot_key = os.getenv("ENV_BOT_KEY")
    # Telegram 1
    if os.getenv("LOGGING_TELEGRAM_1_ENABLED", "false").lower() == "true":
        chat_id_1 = os.getenv("LOGGING_TELEGRAM_1_CHAT_ID")
        levels_1 = get_env_list("LOGGING_TELEGRAM_1_LEVELS", "INFO")
        if bot_key and chat_id_1 and levels_1:
            h1 = TelegramLoggerHandler(bot_key, chat_id_1)
            h1.setFormatter(fmt_telegram)
            h1.setLevel(logging.DEBUG)
            h1.addFilter(LevelsFilter(levels_1))
            logger.addHandler(h1)
    # Telegram 2
    if os.getenv("LOGGING_TELEGRAM_2_ENABLED", "false").lower() == "true":
        chat_id_2 = os.getenv("LOGGING_TELEGRAM_2_CHAT_ID")
        levels_2 = get_env_list("LOGGING_TELEGRAM_2_LEVELS", "ERROR,CRITICAL")
        if bot_key and chat_id_2 and levels_2:
            h2 = TelegramLoggerHandler(bot_key, chat_id_2)
            h2.setFormatter(fmt_telegram)
            h2.setLevel(logging.DEBUG)
            h2.addFilter(LevelsFilter(levels_2))
            logger.addHandler(h2)

    # Sentry handler (just init sentry SDK; Sentry integrates with logging by default)
    if os.getenv("LOGGING_SENTRY_ENABLED", "false").lower() == "true":
        sentry_dsn = os.getenv("LOGGING_SENTRY_DSN")
        sentry_levels = get_env_list("LOGGING_SENTRY_LEVELS", "ERROR,CRITICAL")
        if sentry_dsn:
            sentry_sdk.init(dsn=sentry_dsn, traces_sample_rate=1.0)
            sentry_logger = logging.getLogger("sentry_sdk")
            sentry_logger.setLevel(logging.ERROR)

    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger.setLevel(logging.DEBUG)
    return logger
