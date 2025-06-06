import os
import logging
import urllib.parse
import requests

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
    def __init__(self, chat_id, bot_key):
        super().__init__()
        self.chat_id = chat_id
        self.bot_key = bot_key

    def emit(self, record):
        try:
            msg = self.format(record)
            text = urllib.parse.quote(msg, safe="")
            url = (
                f"https://api.telegram.org/bot{self.bot_key}"
                f"/sendMessage?chat_id={self.chat_id}"
                f"&text={text}&disable_web_page_preview=true"
            )
            resp = requests.get(url, timeout=5)
            if resp.status_code == 429:
                print(f"TelegramLoggerHandler rate-limited: {resp.text}")
            elif resp.status_code != 200:
                print(f"TelegramLoggerHandler failed ({resp.status_code}): {resp.text}")
        except Exception as e:
            print(f"TelegramLoggerHandler.emit exception: {e}")
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
            console.setLevel(logging.DEBUG)  # allow all through, filter below
            console.addFilter(LevelsFilter(console_levels))
        logger.addHandler(console)

    # Telegram handlers
    bot_key = os.getenv("ENV_BOT_KEY")
    # Telegram 1
    if os.getenv("LOGGING_TELEGRAM_1_ENABLED", "false").lower() == "true":
        chat_id_1 = os.getenv("LOGGING_TELEGRAM_1_CHAT_ID")
        levels_1 = get_env_list("LOGGING_TELEGRAM_1_LEVELS", "INFO")
        if bot_key and chat_id_1 and levels_1:
            h1 = TelegramLoggerHandler(chat_id_1, bot_key)
            h1.setFormatter(fmt_telegram)
            h1.setLevel(logging.DEBUG)
            h1.addFilter(LevelsFilter(levels_1))
            logger.addHandler(h1)
    # Telegram 2
    if os.getenv("LOGGING_TELEGRAM_2_ENABLED", "false").lower() == "true":
        chat_id_2 = os.getenv("LOGGING_TELEGRAM_2_CHAT_ID")
        levels_2 = get_env_list("LOGGING_TELEGRAM_2_LEVELS", "ERROR,CRITICAL")
        if bot_key and chat_id_2 and levels_2:
            h2 = TelegramLoggerHandler(chat_id_2, bot_key)
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
            # Sentry's SDK automatically captures ERROR+ logs
            # To restrict levels, you can use before_send or adjust root logger level if needed

    logging.getLogger("httpx").setLevel(logging.WARNING)

    logger.setLevel(logging.DEBUG)  # lowest, let handlers filter
    return logger
